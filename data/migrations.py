"""Convert older Greater Diplomacy 5 (GD5) data to the current formats.

Keep older GD5 identifiers, schema conversions, and load repairs in this module.
Keep imports from other games in their separate translation modules.
Loaders own saved-file access. Shared gameplay modules own current rules and validation.
Import gameplay helpers inside functions to avoid startup import cycles.
Keep in-place conversions safe to repeat and preserve unknown valid fields.
"""

import copy
import gzip
import json
import uuid
import re

import data.constants as c


# SETTINGS AND DATA LIBRARIES
# ===========================


def tournament_player_intents(payload, map_data=None):
    """Read optional intents and reject conflicting older choice projections."""
    commands = payload["player_intents"]
    if not isinstance(commands, list):
        raise ValueError("Player intents must be a list.")
    country = payload.get("nation_data", {})
    provinces = payload.get("provinces", {})
    if not isinstance(country, dict) or not isinstance(provinces, dict):
        raise ValueError("Invalid compatibility projection.")
    transport = [command for command in commands
                 if isinstance(command, dict) and command.get("type") == "air_transport"]
    if "air_transport" in payload and payload["air_transport"] != transport:
        raise ValueError("Conflicting aircraft cargo choices in the move file.")
    by_id = {province["id"]: province.get("json_key") for province in (map_data or {}).values()}
    # Current intents establish state. Older projections are retained for supported readers.
    # A field present in both representations must describe the same choice.
    unit_choices = {unit.get("unit_id"): unit for province in provinces.values()
                    if isinstance(province, dict) for unit in province.get("units", [])
                    if isinstance(unit, dict) and unit.get("unit_id")}
    unit_choices.update({unit.get("unit_id"): unit for unit in payload.get("aircraft_orders", [])
                         if isinstance(unit, dict) and unit.get("unit_id")})
    for province in provinces.values():
        if not isinstance(province, dict):
            raise ValueError("Invalid province compatibility projection.")
        for unit in province.get("units", []):
            if not isinstance(unit, dict) or not isinstance(unit.get("type"), str):
                raise ValueError("Invalid unit compatibility projection.")
    for command in commands:
        if not isinstance(command, dict):
            raise ValueError("Invalid player intent.")
        kind = command.get("type")
        if kind == "province_queue":
            older = provinces.get(by_id.get(command.get("province_id")), {})
            queue = command.get("queue")
            if queue in older and older[queue] != command.get("items"):
                raise ValueError("Conflicting production choices in the move file.")
        elif kind == "research_queue" and "research_queue" in country:
            if [entry.get("tech_name") for entry in country["research_queue"]] != command.get("tech_names"):
                raise ValueError("Conflicting research choices in the move file.")
        elif kind == "army_roster" and "armies" in country:
            if country["armies"] != command.get("armies"):
                raise ValueError("Conflicting army choices in the move file.")
        elif kind == "unit_order" and command.get("unit_id") in unit_choices:
            older = unit_choices[command["unit_id"]]
            for key in ("order", "custom_name", "combat_stance", "lane_target"):
                if key in older and older[key] != command.get(key):
                    raise ValueError("Conflicting unit choices in the move file.")
        elif kind == "country_preferences":
            for key in ("political_drift", "automation", "conscription_slider",
                        "mat_to_fuel_slider", "custom_production_units"):
                if key in country and country[key] != command.get(key):
                    raise ValueError("Conflicting country choices in the move file.")
        elif kind == "country_appearance":
            for key, value in command.get("appearance", {}).items():
                if key in country and country[key] != value:
                    raise ValueError("Conflicting country appearance in the move file.")
        elif kind == "faction_rename" and payload.get("faction_renames"):
            if command.get("name") != payload["faction_renames"][-1].get("new_name"):
                raise ValueError("Conflicting faction renames in the move file.")
    return copy.deepcopy(commands)

SETTING_ALIASES = {
    "gemini_api_key": ("api_key",),
    "ollama_base_url": ("ollama_api_key",),
    "music_pitch": ("music_speed",),
    "sfx_pitch": ("sfx_speed",),
    "openrouter_api_key": ("ling_api_key",),
    "openrouter_model": ("ling_model",),
}
LEGACY_SETTINGS_KEYWORD_NAMES = frozenset(
    alias for key in ("ollama_base_url", "openrouter_api_key", "openrouter_model")
    for alias in SETTING_ALIASES[key])


def setting_keys(name):
    """Return the current key first, followed by supported older keys."""
    return (name,) + SETTING_ALIASES.get(name, ())


def read_setting_value(saved, name):
    """Read a saved value. A current key takes priority, including an empty value."""
    return next((saved[key] for key in setting_keys(name) if key in saved), None)


def controller_setting_values(controller, names):
    """Read current or older attributes from controllers and lightweight test doubles."""
    return {key: getattr(controller, key)
            for name in names for key in setting_keys(name)
            if hasattr(controller, key)}


def normalize_ai_mode(value):
    """Read the older provider ID as OpenRouter."""
    return "OPENROUTER" if value == "LING" else value


def migrate_setting_names(saved):
    """Update cached names in place. Keep unrelated and unknown settings."""
    for name, aliases in SETTING_ALIASES.items():
        for old_key in aliases:
            if old_key in saved:
                saved.setdefault(name, saved.pop(old_key))
    if "ai_mode" in saved:
        saved["ai_mode"] = normalize_ai_mode(saved["ai_mode"])
    return saved


def migrate_mouse_button_actions(value):
    """Convert older pan controls without changing the caller's mapping."""
    # pan_map_outside_orders was the first saved form of Pan + Exclude Orders.
    # An explicit current checkbox takes priority when both fields exist.
    if not isinstance(value, dict):
        return value
    result = dict(value)
    for button, actions in value.items():
        if not isinstance(actions, dict):
            continue
        legacy = actions.get("pan_map_outside_orders")
        if isinstance(legacy, bool) and "exclude_orders" not in actions:
            result[button] = dict(actions, exclude_orders=legacy)
            if legacy:
                result[button]["pan_map"] = True
    return result


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
        migrate_setting_names(data)
    elif cache_key == "country_data":
        migrate_country_records(data)
    elif cache_key in ("unit_library", "tech_tree"):
        field = "production_group" if cache_key == "unit_library" else "category"
        for entry in data.values():
            if field in entry:
                entry[field] = normalize_air_category(entry[field])


# SAVED MAPS, COUNTRIES, AND UNITS
# ================================


def migrate_country_record(country):
    """Discard the obsolete direct-alliance field without changing faction or subject relationships."""
    country.pop("allied_with", None)
    return country


def migrate_country_records(nation_data):
    """Update country records in place, including records from older saved games."""
    for country in nation_data.values():
        if isinstance(country, dict):
            migrate_country_record(country)
    return nation_data


def migrate_history_country_records(history):
    """Remove obsolete country fields after complete historical snapshots are restored."""
    for snapshot in history.values():
        if isinstance(snapshot, dict) and isinstance(snapshot.get("nation_data"), dict):
            migrate_country_records(snapshot["nation_data"])
    return history


LEGACY_RESEARCH_DEFAULT_DAYS = 30
LEGACY_RESEARCH_POINTS_PER_DAY = 10

# Original GD5 equipment dates. These describe older saved level numbers.
LEGACY_INFANTRY_RESEARCH_YEARS = {
    "infantry_type": list(range(1910, 2051)),
    "cavalry": list(range(1910, 1927, 4)),
    "militia": list(range(1910, 2051, 5)),
    "artillery": list(range(1910, 2051, 5)),
}


def migrate_infantry_research(saved, tech_tree, history=None):
    """Preserve equipment years when earlier research stages are inserted."""
    sources = saved.get("research_years", LEGACY_INFANTRY_RESEARCH_YEARS)
    if not isinstance(sources, dict):
        raise ValueError("Saved research_years must contain technology year lists.")
    targets = {key: list(tech_tree[key]["years"])
               for key in c.DATED_UNIT_RESEARCH_TRACKS if key in tech_tree}

    def convert(research, pending=()):
        if not isinstance(research, dict):
            return
        for key, target in targets.items():
            if key not in sources or key not in research:
                continue
            source = sources[key]
            if source == target:
                continue
            if (not isinstance(source, list) or not source
                    or any(type(year) is not int for year in source)
                    or source != sorted(set(source))):
                raise ValueError(f"Saved research years for {key} must be increasing integers.")
            level = research[key]
            if type(level) is not int or level < 0:
                raise ValueError(f"Saved research level for {key} must be a nonnegative integer.")
            if level:
                # Retain levels beyond an older content cap instead of discarding them.
                year = source[min(level, len(source)) - 1]
                research[key] = sum(value <= year for value in target) + max(0, level - len(source))
            elif key in pending:
                research[key] = sum(value < source[0] for value in target)

    def convert_countries(countries):
        if not isinstance(countries, dict):
            return
        for country in countries.values():
            if not isinstance(country, dict):
                continue
            pending = set(country.get("research_progress", {}))
            pending.update(project.get("tech_name") for project in country.get("research_queue", []))
            if isinstance(country.get("current_research"), str):
                pending.add(country["current_research"])
            convert(country.get("research"), pending)

    convert(saved.get("default_research"))
    convert_countries(saved.get("nation_data"))
    for snapshot in (history or {}).values():
        if isinstance(snapshot, dict):
            convert_countries(snapshot.get("nation_data"))
    saved["research_years"] = targets
    return saved


def migrate_research_project(project):
    """Convert the older research countdown only when research points are absent."""
    if "points_remaining" not in project:
        project["points_remaining"] = (project.get("days_remaining", LEGACY_RESEARCH_DEFAULT_DAYS)
                                       * LEGACY_RESEARCH_POINTS_PER_DAY)
    return project


def _production_turns_from_days(days):
    """Use the original production countdown conversion."""
    return max(1, days // c.DEFAULT_DAYS_PER_TURN)


def production_queue_turns(entry):
    """Read a queue countdown without changing display state."""
    return entry.get("turns_remaining", _production_turns_from_days(
        entry.get("days_remaining", c.DEFAULT_DAYS_PER_TURN)))


def migrate_production_queue_item(entry):
    """Convert older production days when execution reaches the queue item."""
    if "days_remaining" in entry:
        # Execution historically gives the older field priority when both fields exist.
        entry["turns_remaining"] = _production_turns_from_days(entry.pop("days_remaining"))
    return entry


def normalize_production_order(entry, expected):
    """Complete older queue entries without replacing explicit countdowns or payments."""
    result = copy.deepcopy(entry)
    migrate_production_queue_item(result)
    defaults = copy.deepcopy(expected)
    migrate_production_queue_item(defaults)
    for key, value in defaults.items():
        result.setdefault(key, value)
    return result


def discard_legacy_deployment_queue(province):
    """Keep Data Refresh's existing removal of obsolete deployment data."""
    province.pop("deployment_queue", None)


def migrate_province_record(province, building_library):
    """Split old deployment queues and remove unavailable buildings on load."""
    province["unit_queue"] = province.get("unit_queue", [])
    province["building_queue"] = province.get("building_queue", [])
    if "deployment_queue" in province:
        for entry in province["deployment_queue"]:
            queue = "building_queue" if entry.get("order_type") == "BUILDING" else "unit_queue"
            province[queue].append(entry)
        del province["deployment_queue"]
    province["buildings"] = [name for name in province.get("buildings", []) if name in building_library]
    resources = province.get("resources", {})
    province["resources"] = resources if isinstance(resources, dict) else {}
    return province


def migrate_loaded_units(map_data, nation_data, unit_library, save_version):
    """Apply saved-unit conversions in their required load order."""
    from data import queries
    # Older transports can contain defense inherited from the carried unit.
    # Restore transport defense before applying the saved-version stat conversion.
    for province in map_data.values():
        for unit in queries.units_with_air_cargo(province.get("units", [])):
            unit_type = unit.get("type", "")
            if unit_type.startswith("Convoy ("):
                unit["defense"] = c.CONVOY_DEF
            elif unit_type.startswith("Truck ("):
                unit["defense"] = c.TRUCK_DEF
    migrate_aircraft_names(map_data, nation_data)
    if save_version != c.GAME_VERSION:
        migrate_units_to_current_stats(map_data, unit_library)
        print(f"[SYSTEM] Migrated save from version '{save_version or 'unversioned'}' to '{c.GAME_VERSION}'.")
    # These aircraft corrections also apply to older saves with the current version.
    migrate_aircraft_stats(map_data, unit_library)
    normalize_air_orders(map_data)


def ensure_unit_ids(map_data, nation_data=None):
    """Give every live unit one unique persistent ID and return the IDs added.

    Old maps never had unit IDs.  This migration is intentionally tolerant of
    malformed or duplicate values: the loaded map becomes safe before any
    army roster can refer to it, and the repaired IDs are saved normally.
    """
    from data import queries
    seen, added = set(), []
    groups = [queries.units_with_air_cargo(province.get("units", []))
              for province in (map_data or {}).values() if isinstance(province, dict)]
    if nation_data is not None:
        groups.append(queries.held_volunteer_units(nation_data))
    for group in groups:
        for unit in group:
            unit_id = unit.get("unit_id")
            if not isinstance(unit_id, str) or not unit_id or unit_id in seen:
                unit_id = uuid.uuid4().hex
                while unit_id in seen:
                    unit_id = uuid.uuid4().hex
                unit["unit_id"] = unit_id
                added.append(unit_id)
            seen.add(unit_id)
    return added


def migrate_spawned_territories(nation_data, map_data):
    """Restore missing starting territory lists for Integrated puppets."""
    for name, country in nation_data.items():
        if country.get("puppet_type") == c.PUPPET_TYPE_INTEGRATED and "spawned_territories" not in country:
            country["spawned_territories"] = [province["id"] for province in map_data.values()
                                               if province.get("owner") == name]


def overlay_saved_province_data(map_data, saved_provinces):
    """Apply legacy or history province overlays to their map-data records."""
    malformed_resources = 0
    for json_key, saved_province in saved_provinces.items():
        province = map_data.get(json_key)
        if province is not None and saved_province:
            if not isinstance(saved_province, dict):
                continue
            # A pre-fix history snapshot could contain resource names as a
            # list: snapshot_history used a list copier on the resources dict.
            # Do not replace a valid current resource mapping with that known
            # malformed value.  There is no amount data to recover from it,
            # but preserving the current mapping avoids silent resource loss.
            overlay = copy.deepcopy(saved_province)
            resources = overlay.get("resources")
            if "resources" in overlay and not isinstance(resources, dict):
                malformed_resources += 1
                del overlay["resources"]
            province.update(overlay)
    if malformed_resources:
        print(f"[WARN] Ignored malformed saved resources in {malformed_resources} province overlay(s).")


def merge_country_templates(nation_data):
    """Restore catalog countries and migrate missing fields in place.

    Empty save records are references to the shared country catalog. Filling
    them in place preserves the saved iteration order, including custom IDs,
    and keeps catalog countries available unless a spectator explicitly deleted them.
    Copies keep live edits from changing the process-wide template cache.
    """
    from data import queries
    deleted = nation_data.get("GLOBAL_EVENTS", {}).get("deleted_countries", [])
    for country in deleted:
        nation_data.pop(country, None)
    for country, template in queries.get_country_data().items():
        if country in deleted:
            continue
        if country not in nation_data:
            nation_data[country] = copy.deepcopy(template)
            continue
        current = nation_data[country]
        # SYNC FIX: Merge missing top-level and research keys from the base
        # template so old saves immediately get new fields and tech keys.
        for key, value in template.items():
            if key not in current:
                current[key] = copy.deepcopy(value)
        if "research" in template:
            research = current.setdefault("research", {})
            for key, value in template["research"].items():
                if key not in research:
                    research[key] = copy.deepcopy(value)
    return migrate_country_records(nation_data)


def saved_player_view(save_meta):
    """Return the offline viewing identity and active-player list for a save.

    Real-time matches save the authoritative server map. That map correctly
    uses ``None`` during the live session, but a completed result loaded from
    disk should be an ordinary offline spectator replay. The format check also
    repairs completed real-time saves made before ``offline_view`` was added.
    """
    realtime_match = save_meta.get("realtime_match") if isinstance(save_meta, dict) else None
    if isinstance(realtime_match, dict) and (
            realtime_match.get("offline_view") == "spectator"
            or realtime_match.get("format") == "gd5-realtime-v1"):
        return "Spectator", []

    player_country = save_meta.get("player_country", "None")
    loaded_players = save_meta.get("active_players", [player_country])
    return player_country, [] if loaded_players == ["None"] else loaded_players


def repair_faction_rosters(nation_data, map_data):
    """Drops from every faction roster the members who should never have been on it.

    Two states the engine now prevents but older saves are already in, because
    nothing checked them:

      - a puppet in a faction its master is not in. A subject holds whatever its
        master holds; it does not sign its own pacts. saves/Madagascar but not
        France has French Madagascar in the Axis while Vichy France, its master,
        is in nothing at all.
      - two members of the same faction at war. This was possible when a master
        attacked its own puppet: the puppet became independent, but the normal
        faction-leave guard had refused to move it first.

    Membership is cleared; nothing else about the nation is touched, and no
    nation is deleted. Each repair is logged, so a roster changing between one
    session and the next is traceable rather than mysterious.
    """
    from data import queries
    from map_logic.diplomacy.diplomacy_events import log_global_event

    for name, data in list(nation_data.items()):
        if not isinstance(data, dict) or not data.get("faction"):
            continue

        master = data.get("master", "")
        if master and nation_data.get(master, {}).get("faction", "") != data["faction"]:
            reason = f"its master {master} is not in it"
        else:
            continue

        log_global_event(nation_data,
                         f"{name} is no longer counted among {data['faction']}: {reason}.")
        data["faction"] = ""
        data["is_faction_leader"] = False

    # A repaired save can still contain a historical internal war. Keep the
    # war intact, but remove the least-established side from the faction so the
    # game never loads two allies as enemies. Prefer a non-leader and then a
    # puppet; the alphabetical tie-break makes this recovery deterministic.
    seen_pairs = set()
    for name, data in sorted(nation_data.items()):
        if not isinstance(data, dict):
            continue
        for enemy in data.get("at_war_with", []):
            if not isinstance(enemy, str) or enemy not in nation_data:
                continue
            pair = tuple(sorted((name, enemy)))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)

            other = nation_data.get(enemy, {})
            if not (isinstance(other, dict)
                    and queries.are_in_same_faction(name, enemy, nation_data)):
                continue

            def removal_priority(member):
                member_data = nation_data[member]
                try:
                    tenure = int(member_data.get("faction_tenure", 0) or 0)
                except (TypeError, ValueError):
                    tenure = 0
                return (bool(member_data.get("is_faction_leader")),
                        not bool(member_data.get("master", "")), tenure, member)

            leaver = min((name, enemy), key=removal_priority)
            faction = nation_data[leaver]["faction"]
            log_global_event(
                nation_data,
                f"{leaver} is no longer counted among {faction}: it is at war with "
                f"fellow member {enemy if leaver == name else name}.")
            nation_data[leaver]["faction"] = ""
            nation_data[leaver]["is_faction_leader"] = False


def faction_records(nation_data, records=None):
    """Read canonical factions or convert repaired country projections once."""
    import hashlib
    import copy

    if records is not None:
        if not isinstance(records, dict):
            raise ValueError("Faction records must be a mapping.")
        result = copy.deepcopy(records)
        assigned = set()
        for identity, record in result.items():
            if (not isinstance(identity, str) or not identity or not isinstance(record, dict)
                    or not isinstance(record.get("name"), str) or not record["name"]
                    or not isinstance(record.get("members"), list)
                    or not record["members"] or (record.get("leader") is not None
                                                and record["leader"] not in record["members"])
                    or not isinstance(record.get("pre_war_borders", {}), dict)):
                raise ValueError("Invalid faction record.")
            for member in record["members"]:
                if not isinstance(member, str) or member not in nation_data or member in assigned:
                    raise ValueError("Faction members must be distinct existing countries.")
                assigned.add(member)
            record.setdefault("pre_war_borders", {})
        return result
    groups = {}
    for country, data in nation_data.items():
        if isinstance(data, dict) and data.get("faction"):
            groups.setdefault(data["faction"], []).append(country)
    result = {}
    for name, members in groups.items():
        leader = next((member for member in members
                       if nation_data[member].get("is_faction_leader")), None)
        # Existing leadership repair selects a successor after loading land and units.
        identity = "faction-" + hashlib.sha256(name.encode("utf-8")).hexdigest()[:24]
        result[identity] = {"name": name, "leader": leader, "members": members,
                            "pre_war_borders": copy.deepcopy(
                                nation_data.get("FACTION_WAR_MAPS", {}).get(name, {}))}
    return result


def migrate_units_to_current_stats(map_data, unit_library):
    """
    Rescales every unit's frozen stats (max_health/attack/defense/speed/naval_unit)
    to match the currently loaded unit_library, preserving each unit's current
    health as a percentage of its (possibly changed) max health.

    Used when a save/map's version doesn't match c.GAME_VERSION (or has no
    version at all), since older saves carry stat values baked in at whatever
    balance patch they were created under.
    """
    from data import queries
    for province in map_data.values():
        for unit in queries.units_with_air_cargo(province.get("units", [])):
            stats = unit_library.get(unit.get("type"))
            if not stats:
                continue

            old_max_health = unit.get("max_health", 1)
            hp_pct = unit.get("health", old_max_health) / max(1, old_max_health)

            unit["max_health"] = stats.get("health", c.DEFAULT_UNIT_HP)
            unit["attack"] = stats.get("attack", c.DEFAULT_UNIT_ATK)
            unit["defense"] = stats.get("defense", c.DEFAULT_UNIT_DEF)
            unit["speed"] = stats.get("speed", c.DEFAULT_UNIT_SPD)
            unit["naval_unit"] = stats.get("naval_unit", queries.is_naval_unit(unit.get("type", "")))

            unit["health"] = unit["max_health"] * hp_pct


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

def migrate_aircraft_names(map_data, nation_data=None):
    """Preserve old aircraft, transports, production choices, and upgrade orders."""
    for province in map_data.values():
        for unit in province.get("units", []):
            for field in ("type", "original_type"):
                name = unit.get(field)
                if name in LEGACY_AIRCRAFT_NAMES:
                    unit[field] = LEGACY_AIRCRAFT_NAMES[name]
                elif isinstance(name, str):
                    for carrier in ("Truck", "Convoy"):
                        prefix = carrier + " ("
                        if name.startswith(prefix) and name.endswith(")"):
                            inner = name[len(prefix):-1]
                            if inner in LEGACY_AIRCRAFT_NAMES:
                                unit[field] = prefix + LEGACY_AIRCRAFT_NAMES[inner] + ")"
            order = unit.get("order") or {}
            target = order.get("target_type")
            if target in LEGACY_AIRCRAFT_NAMES:
                order["target_type"] = LEGACY_AIRCRAFT_NAMES[target]
        for item in province.get("unit_queue", []):
            name = item.get("unit_type")
            if name in LEGACY_AIRCRAFT_NAMES:
                item["unit_type"] = LEGACY_AIRCRAFT_NAMES[name]
    for country in (nation_data or {}).values():
        if "custom_production_units" in country:
            country["custom_production_units"] = [
                LEGACY_AIRCRAFT_NAMES.get(name, name) for name in country["custom_production_units"]]


def migrate_aircraft_stats(map_data, unit_library=None):
    """Refresh aircraft stats and unpack obsolete aircraft Trucks safely.

    Old saves can share this release's version. Always refresh these explicit
    library stats on load, preserving health fractions and original transport
    fields, so the migration is safe to repeat.
    """
    from data import queries
    library = queries.get_unit_library() if unit_library is None else unit_library
    for province in map_data.values():
        for unit in province.get("units", []):
            transported = queries.is_air_transport(unit)
            if transported and not unit.get("original_type"):
                # Some legacy transports only stored the name wrapper.
                unit["original_type"] = unit["type"].split(" (", 1)[1][:-1]
            stats = library.get(unit.get("original_type") if transported else unit.get("type"), {})
            if not stats.get("air_role"):
                continue
            if transported:
                for field in ("max_health", "attack", "defense", "speed"):
                    unit["original_" + field] = stats["health" if field == "max_health" else field]
                if unit["type"].startswith("Truck ("):
                    # Preserve the carried health fraction and identity without
                    # leaving an obsolete land-transport capability in saves.
                    queries.revert_transport(unit)
                    if queries.is_water_province(province):
                        queries.load_transport(unit, "Convoy")
                    unit["order"] = {"type": "MOVE", "path": []}
            else:
                fraction = unit.get("health", 0) / max(1, unit.get("max_health", c.DEFAULT_UNIT_HP))
                unit.update(max_health=stats["health"], health=stats["health"] * fraction,
                            attack=stats["attack"], defense=stats["defense"], speed=stats["speed"])


def normalize_air_orders(map_data):
    """Repair saved recovery timers and aircraft orders. Old units need no recovery."""
    from data import queries
    for province in map_data.values():
        for unit in queries.units_with_air_cargo(province.get("units", [])):
            order = unit.get("order")
            if isinstance(order, dict) and order.get("type") == "AIR_DROP_RECOVERY":
                if not queries.unit_is_air_drop_recovering(unit):
                    unit["order"] = {"type": "MOVE", "path": []}
                continue
            if not queries.is_air_unit(unit) or not isinstance(order, dict):
                continue
            if isinstance(order.get("type"), str) and order["type"] in queries.AIR_ORDER_TYPES:
                order.setdefault("base_id", province["id"])
                if order["type"] == "AIR_PATROL":
                    order.setdefault("priority", queries.AIR_DEFAULT_PRIORITY)
            elif order.get("type") == "MOVE" and not queries.air_unit_can_move_on_ground(unit):
                order["path"] = []
            elif order.get("type") == "CONVERT" and order.get("to") == "Truck":
                unit["order"] = (queries.air_conversion_order(unit) if province.get("is_coastal", False)
                                 else {"type": "MOVE", "path": []})


# SCRIPTED EVENTS AND DIPLOMACY
# =============================


def puppet_release_type(entry):
    """Read the Integrated release type used by older queues without this field."""
    return entry.get("release_type", c.PUPPET_TYPE_INTEGRATED)


def tournament_move_sections(payload):
    """Read current partial-state moves or older country-only moves."""
    if "nation_data" in payload and "provinces" in payload:
        return payload["nation_data"], payload["provinces"]
    return payload, {}


def tournament_release_requests(payload, country_data, existing):
    """Read explicit release requests or their older country-queue location."""
    return payload.get("release_subjects", country_data.get("release_puppet_queue", existing))


def tournament_aircraft_commands(payload, provinces, live_ids):
    """Recover drafts from older aircraft snapshots before host validation."""
    from data import queries
    commands = payload.get("aircraft_orders")
    if commands is None:
        # Older files serialized full aircraft. Recover only order/name drafts.
        # Ignore submitted stats and positions. Keep the existing land-unit path.
        commands = [{"unit_id": unit.get("unit_id"), "order": unit.get("order"),
                     "custom_name": unit.get("custom_name")}
                    for updates in provinces.values() if isinstance(updates, dict)
                    for unit in updates.get("units", []) if isinstance(unit, dict)
                    and (queries.is_air_unit(unit) or queries.is_air_transport(unit)
                         or unit.get("unit_id") in live_ids)]
    return commands


def decode_saved_json(payload):
    """Decode compressed JSON or the older plain JSON inside encrypted files."""
    if payload.startswith(b'\x1f\x8b'):
        payload = gzip.decompress(payload)
    return json.loads(payload.decode('utf-8'))


def scripted_event_conditions(event, *, migrate=False):
    """Read older conditions. Forecasts read them without changing saved state."""
    if "conditions" in event:
        return event["conditions"]
    conditions = [{
        "type": event.get("condition_type", "Turn Number"),
        "operator": "==", "value": event.get("condition_val", ""), "chain": "AND",
    }]
    if migrate:
        event["conditions"] = conditions
        event["fire_once"] = True
    return conditions


def migrate_scripted_event(event):
    """Update an older event's condition list in place."""
    scripted_event_conditions(event, migrate=True)
    return event


def scripted_event_actions(event):
    """Read an action list or the older single-action fields."""
    actions = event.get("actions", [])
    if not actions and "action_type" in event:
        actions = [{"type": event["action_type"], "target": event.get("action_target", "None")}]
    return actions


def pending_diplomacy_entry(entry):
    """Read an older bare action as a pending entry without changing its source."""
    return entry if isinstance(entry, dict) else {"action": entry, "turns": 0}


def pending_diplomacy_action(entry):
    """Read a pending action and preserve the missing-entry value."""
    return entry.get("action") if isinstance(entry, dict) else entry


def normalize_response_reference(nation_data, recipient, sender, response):
    """Bind omitted older references and validate supplied references against host state."""
    request = nation_data.get(sender, {}).get("pending_diplomacy", {}).get(recipient)
    if request is not None:
        request = normalize_diplomatic_request(copy.deepcopy(request), sender, recipient)
    reference = response.get("request_id")
    if reference is not None:
        if (not isinstance(reference, str) or not isinstance(request, dict)
                or reference != request.get("request_id") or response.get("action") != request.get("action")):
            raise ValueError("That response refers to an expired diplomatic request.")
        return {"request_id": reference}
    existing = nation_data.get(recipient, {}).get("diplo_responses", {}).get(sender)
    if isinstance(existing, dict) and existing.get("legacy_unmatched") and response == existing:
        return {"legacy_unmatched": True}
    if isinstance(request, dict) and response.get("action") == request.get("action"):
        return {"request_id": request["request_id"]}
    # Older files can contain standalone responses with copied treaty terms.
    return {"legacy_unmatched": True}


def normalize_diplomatic_request(entry, sender, target):
    """Give older requests reproducible identities without gameplay randomness."""
    if isinstance(entry, str):
        entry = {"action": entry, "turns": 1, "timer": 0}
    if not isinstance(entry, dict):
        raise ValueError("A diplomatic request must be an action or a record.")
    identity = entry.get("request_id")
    if identity is None:
        payload = json.dumps([sender, target, entry], sort_keys=True, separators=(",", ":"))
        entry["request_id"] = uuid.uuid5(uuid.NAMESPACE_URL, "gd5:diplomacy:" + payload).hex
    elif not isinstance(identity, str) or not identity or len(identity) > 128:
        raise ValueError("A diplomatic request_id must be a nonempty string of at most 128 characters.")
    return entry


def migrate_diplomatic_records(nation_data):
    """Normalize both channels after loading requests, preserving unknown fields."""
    for sender, country in nation_data.items():
        if not isinstance(country, dict):
            continue
        pending = country.get("pending_diplomacy", {})
        for target, entry in list(pending.items()):
            pending[target] = normalize_diplomatic_request(entry, sender, target)
    for recipient, country in nation_data.items():
        if not isinstance(country, dict):
            continue
        for sender, response in country.get("diplo_responses", {}).items():
            if not isinstance(response, dict) or "request_id" in response:
                continue
            request = nation_data.get(sender, {}).get("pending_diplomacy", {}).get(recipient, {})
            if isinstance(request, dict) and request.get("action") == response.get("action"):
                response["request_id"] = request["request_id"]
            else:
                # Older saves could contain standalone responses with copied terms.
                response["legacy_unmatched"] = True
    for signatory, country in nation_data.items():
        if not isinstance(country, dict):
            continue
        treaty = country.get("pending_treaty")
        if not isinstance(treaty, dict):
            continue
        if not treaty.get("treaty_id"):
            payload = json.dumps([signatory, treaty], sort_keys=True, separators=(",", ":"))
            treaty["treaty_id"] = uuid.uuid5(uuid.NAMESPACE_URL, "gd5:ratification:" + payload).hex
        for member in treaty.get("awaiting", []):
            request = nation_data.get(member, {}).get("pending_ratification")
            if isinstance(request, dict):
                request.setdefault("treaty_id", treaty["treaty_id"])
    return nation_data


def ensure_message_id(message):
    """Give an older message a stable reference when it is first forwarded."""
    message_id = message.get("message_id")
    if not message_id:
        message_id = uuid.uuid4().hex
        message["message_id"] = message_id
    return message_id


def migrate_pending_responses(nation_data):
    """Move older reply actions into the response channel in place."""
    migrate_country_records(nation_data)
    for country in nation_data.values():
        country.setdefault("at_war_with", [])
        country.setdefault("guarantees", [])
        country.setdefault("military_attaches", [])
        pending = country.setdefault("pending_diplomacy", {})
        responses = country.setdefault("diplo_responses", {})
        # Older replies occupied the proposal slot and could overwrite a travelling offer.
        for other, entry in list(pending.items()):
            action = pending_diplomacy_action(entry)
            if not isinstance(action, str):
                continue
            for prefix, verdict in (("ACCEPT_", "ACCEPT"), ("REJECT_", "REJECT")):
                if action.startswith(prefix):
                    responses[other] = {
                        "verdict": verdict, "action": action[len(prefix):],
                        "message": entry.get("message", "") if isinstance(entry, dict) else "",
                        "parameters": entry.get("parameters") if isinstance(entry, dict) else None,
                    }
                    del pending[other]
                    break
    return migrate_diplomatic_records(nation_data)


def from_legacy_string(peace_type, proposer, target):
    """Turns one of the three old peace sentences into a deal.

    Saves made before the rework can have a peace offer in flight, and the AI's
    own offers carried free prose where the terms were supposed to be. Anything
    that is not recognisably a demand is read as a white peace, which is what
    those offers already did when they executed -- treaty_effects fell back to
    PEACE_WHITE_PEACE whenever the parameters were empty.
    """
    from data import queries
    from map_logic.diplomacy import deal

    terms = peace_type if isinstance(peace_type, str) else ""

    if not (terms.startswith(c.PEACE_DEMAND_CLAIMS) or terms.startswith(c.PEACE_SURRENDER)):
        return deal.ceasefire_deal(proposer, target)

    winner, loser = queries.get_peace_winner_loser(terms, proposer, target)
    frozen = queries.parse_peace_frozen_ids(terms)
    return deal.new(deal.KIND_PEACE, [proposer], [target],
               [deal.tiles_clause(loser, winner, frozen, plus_originals=True)])


def migrate_legacy_deal(params, proposer, target, kind=None):
    """Whatever was stored on a pending action, as a deal.

    Three shapes reach this: a real deal, one of the old peace strings, and the
    old four-key trade dict {give_materials, take_fuel, puppet_state, ...}. Pass
    `kind` when the caller knows which it should be -- an AI peace offer carried
    free prose where the terms belonged, and reading that as a trade would be
    worse than reading it as the white peace it always executed as.
    """
    from map_logic.diplomacy import deal
    if deal.is_deal(params):
        return params

    if kind == deal.KIND_PEACE:
        return from_legacy_string(params if isinstance(params, str) else "", proposer, target)

    if isinstance(params, dict):
        agreement = deal.new(deal.KIND_TRADE, [proposer], [target])
        for resource in c.TRADE_RESOURCE_KEYS:
            given = int(params.get(f"give_{resource}", 0) or 0)
            taken = int(params.get(f"take_{resource}", 0) or 0)
            if given > 0:
                agreement = deal.add_clause(agreement, deal.resources_clause(proposer, target, resource, given))
            if taken > 0:
                agreement = deal.add_clause(agreement, deal.resources_clause(target, proposer, resource, taken))

        # "SENDER", "NONE" and "RECEIVER" are the three the old trade screen
        # wrote. Anything else is read as a vassalage term all the same, in the
        # sender's favour: the check it replaced was `!= "NONE"`, so an
        # unrecognised value was refused rather than waved through, and a value
        # this does not understand is the last thing that should quietly become
        # no clause at all.
        puppet_state = params.get("puppet_state") or "NONE"
        if puppet_state == "RECEIVER":
            agreement = deal.add_clause(agreement, {"type": deal.VASSALIZE, "master": target, "subject": proposer,
                                     "puppet_type": c.PUPPET_TYPE_AUTONOMOUS})
        elif puppet_state != "NONE":
            agreement = deal.add_clause(agreement, {"type": deal.VASSALIZE, "master": proposer, "subject": target,
                                     "puppet_type": c.PUPPET_TYPE_AUTONOMOUS})
        return agreement

    return from_legacy_string(params, proposer, target)


def legacy_player_country(map_ref, country_id, nation_update):
    """Prepare a player's record without changing host state.

    Faction membership is shared state.  The player can queue a leave/invite
    in their normal diplomacy data, but the authoritative outcome is resolved
    by the host at turn processing.  A member's old move must therefore not
    restore the previous faction string after its leader has renamed the bloc.
    """
    from data.state_access import world_for
    from data import queries
    world_state = world_for(map_ref)
    if not isinstance(nation_update, dict) or country_id not in world_state.nation_data:
        raise ValueError("The move does not contain a valid country record.")

    existing = world_state.nation_data[country_id]
    faction_state = {
        key: existing[key]
        for key in ("faction", "is_faction_leader", "faction_pressure", "faction_tenure")
        if key in existing
    }
    merged = dict(nation_update)
    for key in ("faction", "is_faction_leader", "faction_pressure", "faction_tenure"):
        if key in faction_state:
            merged[key] = faction_state[key]
        else:
            merged.pop(key, None)

    # Tournament moves carry a full country record, but policy countdowns are
    # host-owned turn state.  Read only the player's requested lifecycle
    # statuses and rebuild the timers from the host's existing country record.
    from map_logic import politics
    requested_policies = politics.policy_draft_projection({country_id: merged}, country_id)
    canonical_policies = politics.canonicalize_policy_draft(
        world_state.nation_data, country_id, requested_policies)
    if canonical_policies:
        merged[politics.POLICY_KEY] = canonical_policies
    else:
        merged.pop(politics.POLICY_KEY, None)

    from map_logic.diplomacy import diplomacy_lifecycle as lifecycle
    probe = copy.deepcopy(world_state.nation_data)
    migrate_pending_responses(probe)
    pending = merged.get("pending_diplomacy", {})
    responses = merged.get("diplo_responses", {})
    draft_lists = merged.get("draft_lists", {})
    if not all(isinstance(channel, dict) for channel in (pending, responses, draft_lists)):
        raise ValueError("Invalid diplomatic channels.")
    if any(not isinstance(record, (dict, str)) for record in pending.values()):
        raise ValueError("Invalid diplomatic request.")
    if any(not isinstance(response, dict) for response in responses.values()):
        raise ValueError("Invalid diplomatic response.")
    submitted = {country_id: copy.deepcopy(merged)}
    migrate_pending_responses(submitted)
    drafts = {}
    for target, record in submitted[country_id]["pending_diplomacy"].items():
        if record.get("turns", 0) > 0:
            host_record = probe[country_id].get("pending_diplomacy", {}).get(target)
            supplied = pending[target]
            reference = supplied.get("request_id") if isinstance(supplied, dict) else None
            if (not isinstance(host_record, dict) or record.get("action") != host_record.get("action")
                    or (reference is not None and reference != host_record.get("request_id"))):
                raise ValueError("A travelling request does not belong to this move.")
        else:
            from map_logic.diplomacy.action_definitions import availability
            available = availability(map_ref, country_id, target, record.get("action", ""))
            if not available.allowed:
                # Older snapshots discard invalid drafts while retaining unrelated choices.
                continue
            drafts[target] = record
    canonical_responses = {}
    for target, response in submitted[country_id]["diplo_responses"].items():
        canonical = dict(response)
        canonical.pop("legacy_unmatched", None)
        canonical.update(lifecycle.canonical_response_reference(probe, country_id, target, response))
        canonical_responses[target] = canonical
    lifecycle.apply_draft(probe, country_id, drafts, canonical_responses, draft_lists)
    for channel in ("pending_diplomacy", "diplo_responses", "draft_lists"):
        merged[channel] = probe[country_id].get(channel, {})
    ratification = merged.get("pending_ratification")
    host_ratification = probe[country_id].get("pending_ratification")
    if isinstance(ratification, dict):
        reference = ratification.get("treaty_id")
        if (not isinstance(host_ratification, dict)
                or (reference is not None and reference != host_ratification.get("treaty_id"))):
            raise ValueError("That ratification refers to an expired treaty.")
        merged["pending_ratification"] = copy.deepcopy(host_ratification)
        if "verdict" in ratification:
            merged["pending_ratification"]["verdict"] = ratification["verdict"]
        else:
            merged["pending_ratification"].pop("verdict", None)
    elif ratification is not None:
        raise ValueError("Invalid treaty ratification.")
    elif isinstance(host_ratification, dict):
        merged["pending_ratification"] = copy.deepcopy(host_ratification)
    return migrate_country_record(merged)
