"""What a unit type is: names, groups, research requirements, tiers, and aircraft classification."""

import collections
import data.constants as c
import json
import re
import sys
from data.state_access import world_for
from data import migrations
from data.migrations import normalize_air_category
from data.runtime_rules import ActiveLibrary, for_world
from data import queries


def get_unit_range_defaults(unit_library=None):
    """Read editable range families from the complete, unmodified unit library."""
    if unit_library is None:
        # The live cache can contain scenario overrides or omit disabled units.
        with open(c.UNIT_DATA_PATH, encoding="utf-8") as handle:
            unit_library = json.load(handle)
    families = collections.defaultdict(list)
    for name, stats in unit_library.items():
        families[get_base_item_name(name)].append((name, stats))
    defaults = {}
    for family, members in families.items():
        fields = {}
        bombard = [get_bombardment_range(name, stats) for name, stats in members]
        if any(bombard):
            fields["bombard_range"] = max(bombard)
        aircraft = sorted(
            (_unit_range_level(name), stats["air_range_px"])
            for name, stats in members if stats.get("air_role") and stats.get("air_range_px", 0) > 0)
        if aircraft:
            first_level, first_range = aircraft[0]
            last_level, last_range = aircraft[-1]
            step = ((last_range - first_range) / (last_level - first_level)
                    if last_level > first_level else 0)
            fields["air_range_start"] = first_range - (first_level - 1) * step
            fields["air_range_per_level"] = step
        if fields:
            defaults[family] = fields
    return defaults


def refresh_unit_range_overrides(settings):
    """Restore library ranges and apply updated lobby settings without changing other stats."""
    with open(c.UNIT_DATA_PATH, encoding="utf-8") as handle:
        source = json.load(handle)
    apply_unit_range_overrides(source, settings)
    for name, stats in queries.get_unit_library().items():
        if name not in source:
            continue
        for key in ("bombard_range", "air_range_px"):
            if key in source[name]:
                stats[key] = source[name][key]
            else:
                stats.pop(key, None)


def _unit_range_level(name, *, context=None):
    """Return the numbered family level, or one for an unnumbered unit."""
    return max(1, get_unit_research_requirement(name, context=context)[1])


def get_unit_range_overrides(settings, defaults):
    """Keep valid range changes. Missing or malformed fields use library defaults."""
    raw = (settings or {}).get("unit_range_overrides", {})
    if not isinstance(raw, dict):
        return {}
    overrides = {}
    for family, fields in defaults.items():
        values = raw.get(family)
        if not isinstance(values, dict):
            continue
        changed = {}
        for key, default in fields.items():
            value = values.get(key)
            minimum = 0 if key == "air_range_per_level" else 1
            if type(value) is int and value >= minimum and value != default:
                changed[key] = value
        if changed:
            overrides[family] = changed
    return overrides


def scenario_has_unit_stat_customizations(settings):
    """Report effective range changes for the Unit Stats Editor badge."""
    if not settings or not settings.get("unit_range_overrides"):
        return False
    return bool(get_unit_range_overrides(settings, queries.get_unit_range_defaults()))


def apply_unit_range_overrides(unit_library, settings, *, context=None):
    """Apply scenario ranges to a freshly loaded library before units are restored."""
    defaults = queries.get_unit_range_defaults(unit_library)
    overrides = get_unit_range_overrides(settings, defaults)
    for name, stats in unit_library.items():
        family = get_base_item_name(name, context=context)
        changed = overrides.get(family, {})
        if "bombard_range" in changed and get_bombardment_range(name, stats, context=context) > 0:
            stats["bombard_range"] = changed["bombard_range"]
        if stats.get("air_role") and ("air_range_start" in changed or "air_range_per_level" in changed):
            start = changed.get("air_range_start", defaults[family]["air_range_start"])
            step = changed.get("air_range_per_level", defaults[family]["air_range_per_level"])
            stats["air_range_px"] = start + (_unit_range_level(name, context=context) - 1) * step


def invalidate_unit_metadata():
    """Discard unit indexes and any loaded art-name resolutions after content edits."""
    global _UNIT_RESEARCH_INDEX_CACHE
    _UNIT_RESEARCH_INDEX_CACHE = None
    symbols = sys.modules.get("ui.rendering.symbol_loader")
    if symbols is not None:
        symbols.clear_caches()


def get_infantry_family_year(family_key, player_research, tech_tree):
    """Returns the highest year unlocked for infantry_type/motorized_infantry/
    mechanized_infantry/infantry_fighting_vehicle, or None if nothing is unlocked yet.

    motorized_infantry, mechanized_infantry, and infantry_fighting_vehicle aren't
    leveled techs of their own (see c.VEHICLE_INFANTRY_GATES) - owning the
    one-time "trucks"/"armored_personnel_carriers"/"infantry_fighting_vehicle"
    unlock lets a nation build that unit family up to whatever year its
    infantry_type research has reached, rather than requiring a separate
    multi-decade research track for each.
    """
    gate_tech = c.VEHICLE_INFANTRY_GATES.get(family_key)
    if gate_tech is not None:
        if player_research.get(gate_tech, 0) < 1:
            return None
        year_source = "infantry_type"
    else:
        year_source = family_key

    lvl = player_research.get(year_source, 0)
    if lvl <= 0:
        return None
    years = tech_tree.get(year_source, {}).get("years", [c.START_YEAR])
    return years[max(0, min(lvl - 1, len(years) - 1))]


def get_unit_for_family_tier(unit_library, family, tier, *, context=None):
    """Find an exact family tier without constructing a content identifier."""
    for name in unit_library:
        metadata = queries.get_unit_metadata(name, unit_library, context=context)
        if metadata["family"] == family and metadata["tier_order"] == tier:
            return name
    return None


def get_unit_for_family_year(unit_library, family, year, *, context=None):
    """Find the latest equipment stage available at or before a year."""
    candidates = [(get_unit_tier(name, unit_library, context=context), name)
                  for name in unit_library
                  if get_base_unit_name(name, unit_library, context=context) == family
                  and get_unit_tier(name, unit_library, context=context) <= year]
    return max(candidates)[1] if candidates else None


def get_highest_infantry(nation_data_block, tech_tree, unit_library, allow_fuel_units=True, *, context=None):
    """Preserve vehicle preference and the starting infantry fallback."""
    research = nation_data_block.get("research", {})
    tracks = (["infantry_fighting_vehicle", "mechanized_infantry", "motorized_infantry"]
              if allow_fuel_units else []) + ["infantry_type"]
    for track in tracks:
        year = get_infantry_family_year(track, research, tech_tree)
        if year is None:
            continue
        for name in unit_library:
            metadata = queries.get_unit_metadata(name, unit_library, context=context)
            if metadata["research"]["tech"] == track and metadata["tier_order"] == year:
                return name
    starting_years = tech_tree.get("infantry_type", {}).get("years", [])
    for name in unit_library:
        metadata = queries.get_unit_metadata(name, unit_library, context=context)
        if (starting_years and metadata["research"]["tech"] == "infantry_type"
                and metadata["tier_order"] == starting_years[0]):
            return name
    return None


def is_warship(unit_type, *, context=None):
    """Returns True if the unit is a combat naval vessel."""
    return is_naval_unit(unit_type, context=context) and not unit_type.startswith("Convoy")


def air_drop_recovery_turns(unit):
    """Read the saved recovery order. Older units have no recovery period."""
    order = unit.get("order")
    turns = order.get("turns_left", 0) if isinstance(order, dict) and order.get("type") == "AIR_DROP_RECOVERY" else 0
    return turns if type(turns) is int and turns > 0 else 0


def unit_is_air_drop_recovering(unit):
    return air_drop_recovery_turns(unit) > 0


def get_unit_metadata(unit_name, unit_library=None, *, context=None):
    """Read active identity metadata. Infer names only for older content."""
    library = queries.get_unit_library(context) if unit_library is None else unit_library
    stats = library.get(unit_name, {})
    metadata = stats.get("metadata")
    if "metadata" not in stats:
        return migrations.legacy_unit_metadata(unit_name, stats)
    if not isinstance(metadata, dict):
        raise ValueError(f"Unit {unit_name}: metadata must be an object.")
    if not isinstance(metadata.get("family"), str) or not metadata["family"]:
        raise ValueError(f"Unit {unit_name}: metadata.family must be a nonempty string.")
    tier = metadata.get("tier_order")
    if isinstance(tier, bool) or not isinstance(tier, int) or tier < 0:
        raise ValueError(f"Unit {unit_name}: metadata.tier_order must be a nonnegative integer.")
    research = metadata.get("research")
    requirements = metadata.get("requirements")
    recruitment = metadata.get("recruitment")
    if not isinstance(research, dict) or not isinstance(requirements, list):
        raise ValueError(f"Unit {unit_name}: define metadata.research and metadata.requirements.")
    for requirement in [research] + requirements:
        if not isinstance(requirement, dict) or not isinstance(requirement.get("tech"), str):
            raise ValueError(f"Unit {unit_name}: each research requirement needs a tech key.")
        keys = set(requirement) & {"level", "year", "minimum_year"}
        if len(keys) != 1:
            raise ValueError(f"Unit {unit_name}: each requirement needs one level, year, or minimum_year.")
        value = requirement[next(iter(keys))]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"Unit {unit_name}: requirement values must be nonnegative integers.")
    if not isinstance(recruitment, dict) or recruitment.get("industry") not in ("industry", "basic_factory", "none"):
        raise ValueError(f"Unit {unit_name}: metadata.recruitment.industry must be industry, basic_factory, or none.")
    if not isinstance(recruitment.get("coastal"), bool):
        raise ValueError(f"Unit {unit_name}: metadata.recruitment.coastal must be boolean.")
    return metadata


def get_base_unit_name(unit_name, unit_library=None, *, context=None):
    """Return the explicit family, with a boundary adapter for older content."""
    return queries.get_unit_metadata(unit_name, unit_library, context=context)["family"]


# Word-for-word shorthand used ONLY by get_condensed_unit_name, for the tightly
# spaced production unit list and garrison rosters. Every other screen shows
# the full proper name. "Type" is dropped outright since it's a redundant
# connector word before the year/tier (e.g. "Infantry Type 1940" -> "Inf 1940").
CONDENSED_UNIT_NAME_WORDS = {
    "Type": "",
    "Mechanized": "Mech",
    "Motorized": "Mot",
    "Infantry": "Inf",
    "Militia": "Mil",
    "Breech-Loading": "Breech",
    "Metallic-Cartridge": "Cartridge",
    "Magazine-Rifle": "Mag-Rifle",
    "Smokeless-Rifle": "Smokeless",
    "Supported": "Supp",
    "Squad-Automatic": "Squad-Auto",
    "Semi-Automatic": "Semi-Auto",
    "Battle-Rifle": "Battle",
    "Assault-Rifle": "Assault",
    "Night-Equipped": "Night",
    "Optics-Equipped": "Optics",
    "Drone-Integrated": "Drone",
    "Sensor-Integrated": "Sensor",
    "Support-Weapon": "Support",
    "Self-Loading": "Self-Load",
    "Radio-Equipped": "Radio",
    "Drone-Supported": "Drone",
    "Indirect-Fire": "Indirect",
    "Radio-Coordinated": "Radio",
    "Advanced-Ammunition": "Adv Ammo",
    "Computer-Assisted": "Computer",
    "Fire-Control": "FC",
    "Precision-Guided": "Guided",
    "Sensor-Linked": "Sensor",
    "Automated": "Auto",
    "Mounted": "Mtd",
    "Armored": "Armd",
    "Artillery": "Arty",
    "Cavalry": "Cav",
    "Medium": "Med",
    "Heavy": "Hvy",
    "Light": "Lt",
    "Tank": "Tnk",
    "Super": "Sup",
    "Aircraft": "Acft",
    "Carrier": "Carr",
    "Destroyer": "Dstr",
    "Submarine": "Sub",
    "Pre-Dreadnought": "Pre-Dread",
    "Dreadnought": "Dread",
    "Railroad": "RR",
    "Landkreuzer": "LK",
    "P.1000": "",
    "P.1500": "",
    "Biplane": "Bi",
    "Monoplane": "Mono",
}


# Multi-word unit-class names collapsed to a single acronym, checked before the
# per-word substitution above. A per-word map can't express these cleanly:
# "Infantry"/"Tank" already have their own one-word shorthand used by several
# *other* families (Infantry Type, Medium/Heavy/Light Tank, ...), so remapping
# either word on its own would wrongly shorten those too. Keyed by the exact
# leading class name (i.e. get_base_unit_name's output), matched as a whole.
CONDENSED_UNIT_NAME_PHRASES = {
    "Infantry Fighting Vehicle": "IFV",
    "Main Battle Tank": "MBT",
}


def _condense_words(name, word_map):
    """Shared word-for-word substitution behind get_condensed_unit_name and
    get_condensed_building_name: splits on spaces, swaps any word found in
    word_map, and drops words mapped to "" (connector words like "Type")."""
    words = [word_map.get(w, w) for w in name.split(" ")]
    return " ".join(w for w in words if w)


def get_unit_display_name(unit_name, unit_library=None, *, context=None):
    """Read the cached unit label while retaining its canonical identifier for actions."""
    library = queries.get_unit_library(context) if unit_library is None else unit_library
    if unit_name in library:
        return queries.get_unit_metadata(unit_name, library, context=context).get("display_name", unit_name)
    for carrier in ("Convoy", "Truck"):
        prefix = carrier + " ("
        if unit_name.startswith(prefix) and unit_name.endswith(")"):
            return prefix + get_unit_display_name(unit_name[len(prefix):-1], library, context=context) + ")"
    return unit_name


def unit_picker_items(unit_names, unit_library=None, *, context=None):
    """Return visible labels with canonical unit identifiers as picker values."""
    library = queries.get_unit_library(context) if unit_library is None else unit_library
    return [(get_unit_display_name(name, library, context=context), name) for name in unit_names]


def get_condensed_unit_name(unit_name, unit_library=None, *, context=None):
    """Shortens a unit name via CONDENSED_UNIT_NAME_WORDS for space-constrained
    displays (production unit list, garrison rosters). e.g. 'Mechanized
    Infantry Type 1940' -> 'Mech Inf 1940', 'Medium Tank III' -> 'Med Tank III'.
    Everywhere else should keep showing the full name."""
    # Convoys/Trucks wrap the carried unit's name in parens (e.g.
    # "Convoy (Infantry Type 1940)"); condense the inner name and keep the
    # wrapper, rather than leaving it untouched because the parens break the
    # plain word-for-word lookup below.
    unit_name = get_unit_display_name(unit_name, unit_library, context=context)
    carrier_match = re.match(r'^(Convoy|Truck) \((.+)\)$', unit_name)
    if carrier_match:
        carrier, inner = carrier_match.groups()
        return f"{carrier} ({get_condensed_unit_name(inner, unit_library, context=context)})"

    for phrase, short in CONDENSED_UNIT_NAME_PHRASES.items():
        if unit_name == phrase or unit_name.startswith(phrase + " "):
            unit_name = short + unit_name[len(phrase):]
            break

    return _condense_words(unit_name, CONDENSED_UNIT_NAME_WORDS)


# Word-for-word shorthand used ONLY by get_condensed_building_name, mirroring
# CONDENSED_UNIT_NAME_WORDS. "Building" is dropped as a connector word the
# same way "Type" is for units (e.g. "Recruitment Building Lvl 3" -> "Rcrt
# Lvl 3"); "Lvl" is kept since it's already short.
CONDENSED_BUILDING_NAME_WORDS = {
    "Building": "",
    "Recruitment": "Rcrt",
    "Factory": "Fac",
    "Center": "Ctr",
    "Refinery": "Rfn",
    "Workshop": "Wkshp",
}


def get_condensed_building_name(building_name):
    """Shortens a building name via CONDENSED_BUILDING_NAME_WORDS for the same
    space-constrained displays as get_condensed_unit_name. e.g. 'Basic
    Recruitment Center' -> 'Basic Rcrt Ctr', 'Factory Lvl 5' -> 'Fac Lvl 5'.
    Names with no recognized words (e.g. "Core Territory") pass through
    unchanged. Everywhere else should keep showing the full name."""
    return _condense_words(building_name, CONDENSED_BUILDING_NAME_WORDS)


def get_base_item_name(name, *, context=None):
    """Collapses a unit OR building name down to the family the turn overrides key off.

    Unlike get_base_unit_name this also folds the tier separators away, so
    "Infantry Type 1936" and "Factory Lvl 3" both come back as "Infantry" and
    "Factory". The trailing-numeral test runs through roman_to_int rather than a
    hardcoded numeral list, so it keeps working past whatever tier someone adds.
    """
    library = queries.get_unit_library(context)
    if name in library:
        metadata = queries.get_unit_metadata(name, library, context=context)
        return metadata.get("settings_family", metadata["family"])
    if " Type " in name: return name.split(" Type ")[0]
    if " Lvl " in name: return name.split(" Lvl ")[0]

    parts = name.split(" ")
    if len(parts) > 1 and re.fullmatch(r'[IVXLCDM]+', parts[-1]) and roman_to_int(parts[-1]) > 0:
        return " ".join(parts[:-1])
    return name


# Production/research columns a unit family belongs to, in the order the UI shows them.
UNIT_GROUP_INFANTRY = "Infantry"


UNIT_GROUP_TANKS = "Tanks"


UNIT_GROUP_NAVY = "Navy"


UNIT_GROUP_AIR = "Air"


UNIT_GROUPS = (UNIT_GROUP_INFANTRY, UNIT_GROUP_TANKS, UNIT_GROUP_NAVY, UNIT_GROUP_AIR)


def classify_unit_group(base_name, stats):
    """Sorts a unit family into its production category.

    One rule for the production list, the custom-production picker and anything
    added later, so a unit can never land in different columns in two screens.
    """
    metadata = stats.get("metadata")
    if isinstance(metadata, dict):
        return normalize_air_category(stats.get("production_group")) or metadata.get("production_group", UNIT_GROUP_INFANTRY)
    return migrations.legacy_unit_group(base_name, stats)


#: The buckets the AI balances its army across.
#:
#: Deliberately NOT the same rule as classify_unit_group above, which sorts the
#: production screen's unit categories. The two genuinely
#: disagree -- the production list files Cavalry under Infantry and Railroad
#: Guns under Tanks, the AI does the opposite -- and reconciling them would
#: change what the AI builds, i.e. the game. They are two named rules now
#: rather than one rule and four inline copies of the other.
AI_FORCE_INFANTRY = "INFANTRY"


AI_FORCE_TANKS = "TANKS"


AI_FORCE_NAVY = "NAVY"


def is_ai_tank(unit_type, *, context=None):
    """Whether the AI counts this unit towards its armour quota."""
    return bool(queries.get_unit_metadata(unit_type, context=context).get("ai_tank", False))


def ai_force_category(unit_type, *, context=None):
    """Read the AI quota group independently from production presentation."""
    if not unit_type:
        return None
    return queries.get_unit_metadata(unit_type, context=context).get("ai_force_category")


def get_formatted_division_name(unit_type, *, context=None):
    """Standardizes parsing unit names into division categories while preserving case."""
    # Use regex to strip out " type" case-insensitively, without lowercasing the entire string
    base_name = re.sub(r'(?i)\s+type', '', get_base_unit_name(unit_type, context=context))
    
    # Use a lowercase check for the logic, but append to the preserved case string
    check_name = base_name.lower()
    if "division" not in check_name and not is_naval_unit(unit_type, context=context) and "convoy" not in check_name and "truck" not in check_name:
        base_name += " Division"
        
    return base_name


def get_unit_tech_key(base_name, unit_library=None, *, context=None):
    """Read a family's explicit research track, with an older-content adapter."""
    library = queries.get_unit_library(context) if unit_library is None else unit_library
    if base_name in library:
        return queries.get_unit_metadata(base_name, library, context=context)["research"]["tech"]
    for name, stats in library.items():
        metadata = stats.get("metadata")
        if isinstance(metadata, dict) and metadata.get("family") == base_name:
            return queries.get_unit_metadata(name, library, context=context)["research"]["tech"]
    return migrations.legacy_unit_tech_key(base_name)


def roman_to_int(s):
    """Converts a roman numeral string to an integer.

    Reads its symbol table from constants, so it understands exactly the
    numerals _gen_roman can produce. It used to carry its own {I, V, X} and
    score everything else as zero, which disagreed with both the generator and
    with get_base_item_name's [IVXLCDM]+ regex above.
    """
    if not s: return 0
    rom_val = c.ROMAN_LETTER_VALUES
    res, i = 0, 0
    while i < len(s):
        s1 = rom_val.get(s[i], 0)
        if i + 1 < len(s):
            s2 = rom_val.get(s[i+1], 0)
            if s1 >= s2: res += s1; i += 1
            else: res += s2 - s1; i += 2
        else: res += s1; i += 1
    return res


def _unit_research_pair(requirement, *, context=None):
    tech = requirement["tech"]
    if "year" in requirement:
        years = queries.get_tech_tree(context).get(tech, {}).get("years", [])
        year = requirement["year"]
        return tech, years.index(year) + 1 if year in years else 1
    return tech, requirement.get("level", 1)


def get_unit_research_requirement(unit_name, unit_library=None, *, context=None):
    """Return the primary research pair for compatibility and research displays."""
    return _unit_research_pair(queries.get_unit_metadata(unit_name, unit_library, context=context)["research"], context=context)


def get_unit_requirements(unit_name, unit_library=None, *, context=None):
    """Return explicit compound requirements for one unit."""
    return {"all": queries.get_unit_metadata(unit_name, unit_library, context=context)["requirements"]}


def get_unit_unlock_requirement(unit_name, unit_library=None, *, context=None):
    """Preserve the older three-field requirement interface for existing callers."""
    metadata = queries.get_unit_metadata(unit_name, unit_library, context=context)
    tech, level = _unit_research_pair(metadata["research"], context=context)
    if tech in c.VEHICLE_INFANTRY_GATES:
        for requirement in metadata["requirements"]:
            if "minimum_year" in requirement:
                return tech, None, requirement["minimum_year"]
    return tech, level, None


def unit_requirement_is_met(requirement, player_research, *, context=None):
    """Evaluate a parsed rule; shared by exact-tier UI checks and AI indexes."""
    if isinstance(requirement, dict):
        for item in requirement["all"]:
            tech = item["tech"]
            if "minimum_year" in item:
                year = get_infantry_family_year(tech, player_research, queries.get_tech_tree(context))
                minimum = item["minimum_year"]
                if minimum is None or year is None or year < minimum:
                    return False
            else:
                tech, level = _unit_research_pair(item, context=context)
                if player_research.get(tech, 0) < level:
                    return False
        return True
    # Older callers can still pass the former three-field requirement.
    tech_key, required_lvl, year = requirement
    if required_lvl is None:
        unlocked_year = get_infantry_family_year(tech_key, player_research, queries.get_tech_tree(context))
        return year is not None and unlocked_year is not None and year <= unlocked_year
    return player_research.get(tech_key, 0) >= required_lvl


def is_unit_unlocked(unit_name, player_research, unit_library=None, *, context=None):
    """Returns True if player_research meets the requirement for this exact unit tier,
    independent of whether it's the group's currently-highest tier (see Custom production)."""
    if context is None and isinstance(unit_library, ActiveLibrary):
        context = unit_library
    return unit_requirement_is_met(queries.get_unit_requirements(unit_name, unit_library, context=context), player_research, context=context)


def get_unit_tier(unit_name, unit_library=None, *, context=None):
    """Read the active family's tier order without parsing a display name."""
    return queries.get_unit_metadata(unit_name, unit_library, context=context)["tier_order"]


_UNIT_RESEARCH_INDEX_CACHE = None


def get_unit_research_index(unit_library, *, context=None):
    """Families with tiers and canonical unlock rules, parsed once per schema.

    The library's names and the rules' contents detect in-place editor/mod
    changes, not just replacement dictionaries. Retain the library itself to
    avoid recycled id() values. JSON refresh also discards the index. Sorted
    tiers are stable: equal-tier names retain the library's original priority.
    This is transient derived state and never enters a save or snapshot.
    """
    global _UNIT_RESEARCH_INDEX_CACHE
    if context is None and isinstance(unit_library, ActiveLibrary):
        context = unit_library
    schema = (
        tuple((name, repr(stats.get("metadata"))) for name, stats in unit_library.items()),
        tuple((key, tuple(info.get("years", ()))) for key, info in queries.get_tech_tree(context).items()),
        tuple(sorted(c.VEHICLE_INFANTRY_GATES.items())),
        tuple(sorted(c.UNIT_TECH_KEY_OVERRIDES.items())),
        tuple(sorted((base, tuple(techs)) for base, techs in c.OBSOLESCENCE_RULES.items())),
    )
    indexes = for_world(context).indexes if context is not None else None
    cached = indexes.get("unit_research") if indexes is not None else _UNIT_RESEARCH_INDEX_CACHE
    if cached is not None and cached[0] is unit_library and cached[1] == schema:
        return cached[2]

    families = {}
    for name in unit_library:
        families.setdefault(get_base_unit_name(name, unit_library, context=context), []).append(
            (name, get_unit_tier(name, unit_library, context=context), queries.get_unit_requirements(name, unit_library, context=context)))
    index = tuple(
        (base, tuple(sorted(tiers, key=lambda tier: tier[1], reverse=True)))
        for base, tiers in families.items()
    )
    if indexes is None:
        _UNIT_RESEARCH_INDEX_CACHE = (unit_library, schema, index)
    else:
        indexes["unit_research"] = (unit_library, schema, index)
    return index


def is_naval_unit(unit_type, *, context=None):
    """Checks if a unit is a naval unit based on its type name or unit library stats."""
    if unit_type.startswith("Convoy"):
        return True
    if unit_type.startswith("Truck"):
        return False
    stats = queries.get_unit_library(context).get(unit_type, {})
    return stats.get("naval_unit", False)


def get_bombardment_range(unit_type, stats=None, *, context=None):
    """Returns how many tiles this unit class can shell, or 0 if it cannot bombard.

    The unit's own bombard_range wins, so adding one in unit_data.json is all it
    takes to give something a gun -- the AI already valued that stat, and the two
    answers disagreeing meant it could price a barrage the unit could not fire.
    The constant table is the fallback, matched on the base class name so every
    level of a family qualifies.

    A unit riding a Convoy/Truck ("Convoy (Artillery III)") still cannot shell:
    that name is not in the unit library, so the stat lookup misses, and it is
    not in the table either.
    """
    if stats is None:
        stats = queries.get_unit_library(context).get(unit_type) or {}
    from_stats = stats.get("bombard_range")
    if from_stats:
        return int(from_stats)
    return c.BOMBARDMENT_UNITS.get(get_base_unit_name(unit_type, context=context), 0)


def get_ordinal(n):
    """Returns the ordinal string for an integer."""
    if 11 <= (n % 100) <= 13:
        return str(n) + "th"
    return str(n) + {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


# Air capabilities come from the current unit type, so a carried aircraft uses
# Convoy rules until it is unpacked. These fields are unit-library tuning, not
# duplicated frozen state in saves or network snapshots.
AIR_TARGET_MISSION_TYPES = {"MOVE": "AIR_REPOSITION", "STRIKE": "AIR_ATTACK", "AIR_DROP": "AIR_DROP"}


AIR_ORDER_TYPES = frozenset((*AIR_TARGET_MISSION_TYPES.values(), "AIR_PATROL"))


AIR_INTERCEPTION_PRIORITIES = ("WEAKEST", "STRONGEST", "RANDOM")


AIR_DEFAULT_PRIORITY = "WEAKEST"


AIR_CONVERT_TURNS = 1


def air_unit_stats(unit, *, context=None):
    return queries.get_unit_library(context).get(unit.get("type", ""), {})


def is_air_unit(unit, *, context=None):
    return bool(air_unit_stats(unit, context=context).get("air_role"))


def units_with_air_cargo(units):
    """Include cargo for identity, upkeep, persistence, and casualty records."""
    for unit in units:
        yield unit
        yield from unit.get("air_cargo", [])


def unit_display_domain(unit, *, context=None):
    """Return the map category for the unit's current form."""
    if is_air_unit(unit, context=context):
        return "AIR"
    return "NAVAL" if is_naval_unit(unit.get("type", ""), context=context) else "LAND"


def air_unit_mission(unit):
    """Return the current aircraft mission, including relocation and idle state."""
    order = unit.get("order")
    if not isinstance(order, dict):
        return "NONE"
    kind = order.get("type")
    if kind == "AIR_PATROL":
        priority = order.get("priority", AIR_DEFAULT_PRIORITY)
        return priority if priority in AIR_INTERCEPTION_PRIORITIES else AIR_DEFAULT_PRIORITY
    if kind == "AIR_ATTACK":
        return "STRIKE"
    if kind == "AIR_DROP":
        return "AIR_DROP"
    if kind == "AIR_REPOSITION" or (kind == "MOVE" and order.get("path")):
        return "MOVE"
    return "NONE"


def air_unit_mission_icon(unit):
    """Cargo keeps its transport badge during movement and order cancellation."""
    if air_unit_mission(unit) == "AIR_DROP":
        return "AIR_DROP"
    return "TRANSPORT" if unit.get("air_cargo") else air_unit_mission(unit)


def air_unit_has_mission(unit, *, context=None):
    """Aircraft movement and mission buttons use the same active-order state."""
    return is_air_unit(unit, context=context) and air_unit_mission(unit) != "NONE"


def is_air_transport(unit, *, context=None):
    name = unit.get("type", "")
    # Truck names remain recognizable at the legacy-save/import boundary.
    for carrier in ("Convoy", "Truck"):
        prefix = carrier + " ("
        if name.startswith(prefix) and name.endswith(")"):
            original = unit.get("original_type") or name[len(prefix):-1]
            return bool(queries.get_unit_library(context).get(original, {}).get("air_role"))
    return False


def is_unit_obsolete(group_name, player_research):
    """Checks if a unit group is obsolete based on researched techs."""
    obsoleting_techs = c.OBSOLESCENCE_RULES.get(group_name, [])
    return any(player_research.get(tech, 0) >= 1 for tech in obsoleting_techs)


def get_grouped_units(unit_library, by_family=True, unit_filter=None, *, context=None):
    """Buckets a unit library into production categories via classify_unit_group.

    `by_family=True` lists each base class once (the production columns);
    False lists every individual tier (the custom-production picker).
    `unit_filter(name, stats)` drops units the caller doesn't want listed.
    """
    groups = {group: [] for group in UNIT_GROUPS}
    for name, stats in unit_library.items():
        if unit_filter and not unit_filter(name, stats):
            continue
        base = get_base_unit_name(name, unit_library, context=context)
        entry = base if by_family else name
        bucket = groups[classify_unit_group(base, stats)]
        if entry not in bucket:
            bucket.append(entry)
    return groups


def get_ordered_unit_groups(unit_library, *, context=None):
    """Returns unit families in the canonical production category order."""
    groups = get_grouped_units(unit_library, context=context)
    return tuple(groups[group] for group in UNIT_GROUPS)


def province_for_order(map_screen, province_id):
    world_state = world_for(map_screen)
    if type(province_id) is not int or province_id not in world_state.id_to_province:
        raise ValueError("Unknown province in order.")
    return world_state.id_to_province[province_id]


def canonical_unit_order(map_screen, country_id, province, unit, order):
    """Preserve the public order-validation interface."""
    from map_logic.actions.unit_actions import canonical_order
    return canonical_order(map_screen, country_id, province, unit, order)
