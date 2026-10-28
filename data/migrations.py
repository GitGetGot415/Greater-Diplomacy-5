"""Convert older Greater Diplomacy 5 (GD5) data to the current formats.

The game version is the save version. Each version step converts all older data
to the format of one game version. See documentation/data_migrations.txt.
Keep imports from other games in their separate translation modules.
Loaders own saved-file access. Shared gameplay modules own current rules and validation.
Import gameplay helpers inside functions to avoid startup import cycles.
Preserve unknown valid fields.
"""

import copy
import gzip
import json
import uuid
import re

import data.constants as c


# GAME VERSIONS
# =============


class NewerVersionError(ValueError):
    """Data from a newer game version. Only an update can read it."""


def version_number(version):
    """Read "v46" as 46. Data from before version stamps reads as 0."""
    if isinstance(version, str):
        match = re.fullmatch(r"v(\d+)", version.strip())
        if match:
            return int(match.group(1))
    return 0


CURRENT_VERSION = version_number(c.GAME_VERSION)


def check_version(version, subject="This save"):
    """Return the version number. Refuse data that a newer game wrote."""
    number = version_number(version)
    if number > CURRENT_VERSION:
        raise NewerVersionError(
            f"{subject} was made with game version {version}. "
            f"This game is version {c.GAME_VERSION}. Update the game to open it.")
    return number


def upgrade_save(save_meta, map_data, history):
    """Convert one loaded save to the current version in place.

    save_meta is meta.json, map_data is map_data.json by JSON key, and history
    holds the decoded turn snapshots. A selected history turn becomes live
    state, so every step also converts every snapshot. Return the saved version.
    """
    version = check_version(save_meta.get("version"))
    for target, step in SAVE_STEPS:
        if version < target:
            step(save_meta, map_data, history)
    save_meta["version"] = c.GAME_VERSION
    return version


#: Move files gained game_version in v47. An unstamped move is from v46 or earlier.
LAST_UNSTAMPED_VERSION = 46


def move_version(player_data):
    """Return a move's version number. Refuse a move that no step can convert.

    Moves last one turn, so only moves from the previous release convert.
    """
    version = (check_version(player_data["game_version"], "This move")
               if "game_version" in player_data else LAST_UNSTAMPED_VERSION)
    if version < CURRENT_VERSION - 1:
        raise ValueError(
            f"This move was made with an older game version than v{CURRENT_VERSION - 1}. "
            f"The player must update to {c.GAME_VERSION} and export the move again.")
    return version


def upgrade_move(player_data):
    """Convert a move file from the previous release in place.

    The host approves each converted move. The move then passes normal validation.
    """
    version = move_version(player_data)
    for target, step in MOVE_STEPS:
        if version < target:
            step(player_data)
    player_data["game_version"] = c.GAME_VERSION
    return version


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
    elif cache_key in ("unit_library", "tech_tree"):
        field = "production_group" if cache_key == "unit_library" else "category"
        for entry in data.values():
            if field in entry:
                entry[field] = normalize_air_category(entry[field])


# SAVED MAPS, COUNTRIES, AND UNITS
# ================================


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


def normalize_production_order(entry, expected):
    """Complete older queue entries without replacing explicit countdowns or payments."""
    result = copy.deepcopy(entry)
    for key, value in copy.deepcopy(expected).items():
        result.setdefault(key, value)
    return result


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


# SCRIPTED EVENTS AND DIPLOMACY
# =============================


def decode_saved_json(payload):
    """Decode compressed JSON or the older plain JSON inside encrypted files."""
    if payload.startswith(b'\x1f\x8b'):
        payload = gzip.decompress(payload)
    return json.loads(payload.decode('utf-8'))


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
    lifecycle.normalize_diplomacy_channels(probe)
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
    lifecycle.normalize_diplomacy_channels(submitted)
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
    return merged


# VERSION 47
# ==========
# v47 added version steps. This step collects every conversion that v46 and
# earlier applied on each load, or when gameplay first read an old entry.


LEGACY_RESEARCH_DEFAULT_DAYS = 30
LEGACY_RESEARCH_POINTS_PER_DAY = 10

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


def _v47_aircraft_name(name):
    """Number an unnumbered aircraft, including inside a transport name."""
    if not isinstance(name, str):
        return name
    if name in LEGACY_AIRCRAFT_NAMES:
        return LEGACY_AIRCRAFT_NAMES[name]
    for carrier in ("Truck", "Convoy"):
        prefix = carrier + " ("
        if name.startswith(prefix) and name.endswith(")"):
            inner = name[len(prefix):-1]
            if inner in LEGACY_AIRCRAFT_NAMES:
                return prefix + LEGACY_AIRCRAFT_NAMES[inner] + ")"
    return name


def _v47_production_turns(entry):
    """Replace the production day countdown. The older field has priority."""
    if "days_remaining" in entry:
        entry["turns_remaining"] = max(1, entry.pop("days_remaining") // c.DEFAULT_DAYS_PER_TURN)


def _v47_scripted_event(event):
    """Give an event the condition and action lists that replaced single fields."""
    if "conditions" not in event:
        event["conditions"] = [{
            "type": event.get("condition_type", "Turn Number"),
            "operator": "==", "value": event.get("condition_val", ""), "chain": "AND",
        }]
        event["fire_once"] = True
    if not event.get("actions") and "action_type" in event:
        event["actions"] = [{"type": event["action_type"],
                             "target": event.get("action_target", "None")}]
    for action in event.get("actions", []):
        if isinstance(action, dict) and action.get("type") == "Spawn Unit":
            action["unit_type"] = _v47_aircraft_name(action.get("unit_type"))


def _v47_country(country):
    """Convert one country record."""
    country.pop("allied_with", None)
    for project in country.get("research_queue", []):
        if isinstance(project, dict) and "points_remaining" not in project:
            project["points_remaining"] = (project.get("days_remaining", LEGACY_RESEARCH_DEFAULT_DAYS)
                                           * LEGACY_RESEARCH_POINTS_PER_DAY)
    if isinstance(country.get("custom_production_units"), list):
        country["custom_production_units"] = [
            _v47_aircraft_name(name) for name in country["custom_production_units"]]
    for entry in country.get("release_puppet_queue", []):
        if isinstance(entry, dict):
            entry.setdefault("release_type", c.PUPPET_TYPE_INTEGRATED)
    for event in country.get("scripted_events", []):
        if isinstance(event, dict):
            _v47_scripted_event(event)
    for message in country.get("inbox", []):
        if isinstance(message, dict) and not message.get("message_id"):
            message["message_id"] = uuid.uuid4().hex
    # Older replies occupied the proposal slot and could overwrite a travelling offer.
    pending = country.get("pending_diplomacy", {})
    responses = country.setdefault("diplo_responses", {}) if pending else {}
    for other, entry in list(pending.items()):
        action = entry.get("action") if isinstance(entry, dict) else entry
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


def _v47_nations(nation_data):
    if isinstance(nation_data, dict):
        for country in nation_data.values():
            if isinstance(country, dict):
                _v47_country(country)


def _v47_province(province, terrain):
    """Convert one province record. terrain is the province's map terrain."""
    from data import queries
    if "deployment_queue" in province:
        province.setdefault("unit_queue", [])
        province.setdefault("building_queue", [])
        for entry in province.pop("deployment_queue"):
            queue = "building_queue" if entry.get("order_type") == "BUILDING" else "unit_queue"
            province[queue].append(entry)
    for queue in ("unit_queue", "building_queue"):
        for entry in province.get(queue, []):
            if isinstance(entry, dict):
                _v47_production_turns(entry)
                if "unit_type" in entry:
                    entry["unit_type"] = _v47_aircraft_name(entry["unit_type"])
    for unit in province.get("units", []):
        if not isinstance(unit, dict):
            continue
        for field in ("type", "original_type"):
            if field in unit:
                unit[field] = _v47_aircraft_name(unit[field])
        order = unit.get("order")
        if isinstance(order, dict) and "target_type" in order:
            order["target_type"] = _v47_aircraft_name(order["target_type"])
        if not queries.is_air_transport(unit):
            continue
        if not unit.get("original_type"):
            # Some older transports stored only the name wrapper.
            unit["original_type"] = unit["type"].split(" (", 1)[1][:-1]
        if unit["type"].startswith("Truck ("):
            # Aircraft no longer ride in Trucks. Unpack them on land, or move
            # them into a Convoy at sea. The transport helpers keep identity and
            # the health fraction.
            queries.revert_transport(unit)
            if terrain in c.WATER_TERRAINS:
                queries.load_transport(unit, "Convoy")
            unit["order"] = {"type": "MOVE", "path": []}


def _v47_save(save_meta, map_data, history):
    _v47_nations(save_meta.get("nation_data"))
    for key, province in map_data.items():
        _v47_province(province, province.get("terrain"))
    for key, province in (save_meta.get("provinces") or {}).items():
        if isinstance(province, dict):
            _v47_province(province, map_data.get(key, {}).get("terrain"))
    for snapshot in history.values():
        if not isinstance(snapshot, dict):
            continue
        _v47_nations(snapshot.get("nation_data"))
        for key, province in (snapshot.get("provinces") or {}).items():
            if isinstance(province, dict):
                _v47_province(province, map_data.get(key, {}).get("terrain"))
    # Completed real-time saves made before offline_view open as spectator replays.
    realtime_match = save_meta.get("realtime_match")
    if isinstance(realtime_match, dict) and realtime_match.get("format") == "gd5-realtime-v1":
        realtime_match.setdefault("offline_view", "spectator")


#: Every v46 move file contains these sections. An older move file can omit them.
_V46_MOVE_SECTIONS = ("nation_data", "provinces", "aircraft_orders", "release_subjects")


def _v47_move(player_data):
    """Convert the country record and province updates in a v46 move."""
    if any(section not in player_data for section in _V46_MOVE_SECTIONS):
        raise ValueError(
            "This move was made with a game version older than v46. "
            f"The player must update to {c.GAME_VERSION} and export the move again.")
    country = player_data.get("nation_data")
    if isinstance(country, dict):
        _v47_country(country)
    for entry in player_data.get("release_subjects", []):
        if isinstance(entry, dict):
            entry.setdefault("release_type", c.PUPPET_TYPE_INTEGRATED)
    for province in (player_data.get("provinces") or {}).values():
        if isinstance(province, dict):
            # A move has no terrain, so a Truck aircraft unpacks as on land.
            # Host validation then checks every unit against host state.
            _v47_province(province, None)


SAVE_STEPS = ((47, _v47_save),)
MOVE_STEPS = ((47, _v47_move),)
