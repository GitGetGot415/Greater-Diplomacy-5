"""Older unit identifiers, categories, and unit metadata for libraries that omit it.

Keep unit identity in the unit library. These helpers serve names that are not
library entries and libraries without explicit metadata.
"""

import re

import data.constants as c
from data.migrations import settings
from data.migrations.research import LEGACY_INFANTRY_RESEARCH_YEARS


def normalize_air_category(value):
    """Read older air category names without changing other categories."""
    if value == "Aerospace":
        return "Air"
    if value == "AEROSPACE":
        return "AIR"
    return value


def legacy_unit_tech_key(family):
    """Read research identifiers from older family names."""
    key = re.sub(r'[^a-z0-9 ]', '', family.lower())
    key = re.sub(r'\s+', '_', key.strip())
    return c.UNIT_TECH_KEY_OVERRIDES.get(key, key)


def legacy_unit_metadata(name, stats):
    """Infer metadata only for libraries which omit explicit unit identity."""
    family = re.sub(r'\s+\d{4}$', '', name)
    family = re.sub(r'\s+[IVXLCDM]+$', '', family).strip()
    key = legacy_unit_tech_key(family)
    year = re.search(r'\s+(\d{4})$', name)
    roman = re.search(r'\s+([IVXLCDM]+)$', name)
    tier = 0
    if year:
        tier = int(year.group(1))
    elif roman:
        letters = roman.group(1)
        values = c.ROMAN_LETTER_VALUES
        tier = sum(-values[ch] if i + 1 < len(letters) and values[ch] < values[letters[i + 1]]
                   else values[ch] for i, ch in enumerate(letters))
    research = {"tech": key, "level": max(1, tier if roman else 0)}
    if key in c.DATED_UNIT_RESEARCH_TRACKS and year:
        research = {"tech": key, "year": tier}
    elif key in LEGACY_INFANTRY_RESEARCH_YEARS and roman:
        years = LEGACY_INFANTRY_RESEARCH_YEARS[key]
        if tier <= len(years):
            tier = years[tier - 1]
            research = {"tech": key, "year": tier}
    requirements = [research.copy()]
    if key in c.VEHICLE_INFANTRY_GATES:
        requirements = [{"tech": c.VEHICLE_INFANTRY_GATES[key], "level": 1},
                        {"tech": "infantry_type", "minimum_year": tier if year else None}]
    display_year = re.search(r'\b(\d{4})\b', name)
    display_roman = re.search(r'\b([IVXLCDM]+)$', name)
    suffix = display_year.group(1) if display_year else display_roman.group(1) if display_roman else ""
    return {"family": family, "tier_order": tier, "research": research,
            "tier_kind": "year" if year else "roman" if roman else "single",
            "tier_label": name[len(family):].strip(), "division_suffix": suffix,
            "settings_family": family.removesuffix(" Type"),
            "production_group": legacy_unit_group(family, stats),
            "ai_tank": "Tank" in name or "Armored" in name or name == "Cavalry",
            "ai_force_category": legacy_ai_force_category(name, family, stats),
            "requirements": requirements,
            "recruitment": {"industry": "industry" if family == "Militia" else "basic_factory",
                            "coastal": bool(stats.get("naval_unit", False))}}


def legacy_unit_group(family, stats):
    """Preserve older production grouping when metadata is absent."""
    if family.startswith("Truck"):
        return "Infantry"
    if family.startswith("Convoy"):
        return "Navy"
    group = normalize_air_category(stats.get("production_group"))
    if group in ("Infantry", "Tanks", "Navy", "Air"):
        return group
    if stats.get("naval_unit", False):
        return "Navy"
    if "Tank" in family or "Armored Car" in family or family in c.TANK_GROUP_EXTRAS:
        return "Tanks"
    return "Infantry"


def legacy_ai_force_category(name, family, stats):
    """Preserve the AI quota groups independently from production categories."""
    if "Infantry" in name or family == "Militia":
        return "INFANTRY"
    if "Tank" in name or "Armored" in name or name == "Cavalry":
        return "TANKS"
    if stats.get("naval_unit", False) and not name.startswith("Convoy"):
        return "NAVY"
    return None


def normalize_cached_json_names(cache_key, data):
    """Migrate names when data enters the cache. Keep shared dictionaries in place."""
    if not isinstance(data, dict):
        return
    if cache_key == "settings":
        settings.migrate_setting_names(data)
    elif cache_key in ("unit_library", "tech_tree"):
        if cache_key == "unit_library":
            for older, current in LEGACY_UNIT_NAMES.items():
                if older not in data:
                    continue
                entry = data.pop(older)
                metadata = entry.get("metadata")
                if isinstance(metadata, dict) and metadata.get("tier_kind") == "single":
                    metadata.update(tier_order=1, tier_kind="roman", tier_label="I")
                    if not metadata.get("division_suffix"):
                        metadata["division_suffix"] = "I"
                data.setdefault(current, entry)
        else:
            for entry in data.values():
                if isinstance(entry.get("level_names"), dict):
                    entry["level_names"] = {level: LEGACY_UNIT_NAMES.get(name, name)
                                            for level, name in entry["level_names"].items()}
        field = "production_group" if cache_key == "unit_library" else "category"
        for entry in data.values():
            if field in entry:
                entry[field] = normalize_air_category(entry[field])


LEGACY_AIRCRAFT_NAMES = {
    "Biplane": "Biplane Fighter I",
    "Piston Fighter": "Monoplane Fighter I",
    "Piston Bomber": "Monoplane Bomber I",
    "Biplane Fighter": "Biplane Fighter I",
    "Biplane Bomber": "Biplane Bomber I",
    "Monoplane Fighter": "Monoplane Fighter I",
    "Monoplane Bomber": "Monoplane Bomber I",
    "Monoplane Transport": "Monoplane Transport I",
    "Jet Fighter": "Jet Fighter I",
}


LEGACY_UNIT_NAMES = {
    **LEGACY_AIRCRAFT_NAMES,
    "WW1 Tank": "WW1 Tank I",
    "WW1 Armored Car": "WW1 Armored Car I",
    "Landkreuzer P.1000 Ratte": "Landkreuzer P.1000 Ratte I",
    "Landkreuzer P.1500 Monster": "Landkreuzer P.1500 Monster I",
    "Railgun": "Railgun I",
    "WW1 Railroad Gun": "WW1 Railroad Gun I",
    "WW2 Railroad Gun": "WW2 Railroad Gun I",
    "Carrack": "Carrack I",
    "Ironclad": "Ironclad I",
    "Pre-Dreadnought": "Pre-Dreadnought I",
    "Dreadnought": "Dreadnought I",
    "Battleship": "Battleship I",
    "Zeppelin": "Zeppelin I",
    "V1 Flying Bomb": "V1 Flying Bomb I",
    "V2 Rocket": "V2 Rocket I",
}


def equipment_stage_aliases():
    """Map supported older equipment identifiers to current named stages."""
    from data import queries

    library = queries.get_unit_library()
    families = dict(queries.get_unit_research_index(library))
    aliases = {}
    for name, stats in library.items():
        if (stats.get("metadata", {}).get("research", {}).get("tech") in
                (*c.DATED_UNIT_RESEARCH_TRACKS, *c.VEHICLE_INFANTRY_GATES)
                and name.endswith(" I")):
            aliases[name[:-2]] = name
    sources = {
        "Infantry Type": ([1800, 1830, 1850, 1865, 1875, 1885, 1895, 1905], "infantry_type"),
        "Motorized Infantry Type": ([], "infantry_type"),
        "Mechanized Infantry Type": ([], "infantry_type"),
        "Infantry Fighting Vehicle Type": ([], "infantry_type"),
        "Cavalry": ([1800, 1850, 1870, 1890], "cavalry"),
        "Militia": ([1800, 1840, 1870, 1900], "militia"),
        "Artillery": ([1800, 1830, 1850, 1870, 1890, 1900], "artillery"),
        "Heavy Artillery": ([1800, 1830, 1850, 1870, 1890, 1900], "artillery"),
    }
    for family, (early, tech) in sources.items():
        old = [(f"{family} {year}", year) for year in early]
        for i, year in enumerate(LEGACY_INFANTRY_RESEARCH_YEARS[tech], 1):
            suffix = str(year) if tech == "infantry_type" else c.ROMAN_NUMERALS[i]
            old.append((f"{family} {suffix}", year))
        for name, year in old:
            if name in library:
                continue
            target = next((unit for unit, tier, _ in families.get(family, ()) if tier <= year), None)
            if target:
                aliases[name] = target
    return aliases
