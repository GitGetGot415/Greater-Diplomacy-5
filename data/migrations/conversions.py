"""Every conversion rule for older GD5 saves and moves. Every rule runs on every load.

Each rule finds an older shape in the data and converts it to the current format.
A rule does nothing to current data. Do not make a rule depend on a version number.
See data/migrations/MIGRATIONS.md.

Rules that compare saved data with the active libraries run later in the load,
when the scenario has selected its libraries. research.py and queries.refresh_unit_stats own them.
"""

import uuid

import data.constants as c
from data.migrations.units import LEGACY_UNIT_NAMES, equipment_stage_aliases


LEGACY_RESEARCH_DEFAULT_DAYS = 30


LEGACY_RESEARCH_POINTS_PER_DAY = 10


#: Every v46 move file contains these sections. An older move file can omit them.
V46_MOVE_SECTIONS = ("nation_data", "provinces", "aircraft_orders", "release_subjects")


def convert_save(save_meta, map_data):
    """Convert meta.json and map_data.json in place.

    History snapshots stay in their saved format. Only a selected history turn becomes
    live state, and convert_history_turn converts it then.
    """
    _nations(save_meta.get("nation_data"))
    for province in map_data.values():
        _province(province, province.get("terrain"))
    for key, province in (save_meta.get("provinces") or {}).items():
        if isinstance(province, dict):
            _province(province, map_data.get(key, {}).get("terrain"))
    # Completed real-time saves made before offline_view open as spectator replays.
    realtime_match = save_meta.get("realtime_match")
    if isinstance(realtime_match, dict) and realtime_match.get("format") == "gd5-realtime-v1":
        realtime_match.setdefault("offline_view", "spectator")
    aliases = {**LEGACY_UNIT_NAMES, **equipment_stage_aliases()}
    for records in (save_meta, map_data):
        _unit_records(records, aliases)


def convert_history_turn(snapshot, map_data):
    """Convert one history snapshot in place before it becomes live state.

    map_data gives each province's terrain by JSON key.
    """
    if not isinstance(snapshot, dict):
        return
    _nations(snapshot.get("nation_data"))
    for key, province in (snapshot.get("provinces") or {}).items():
        if isinstance(province, dict):
            _province(province, map_data.get(key, {}).get("terrain"))
    _unit_records(snapshot, {**LEGACY_UNIT_NAMES, **equipment_stage_aliases()})


def convert_move(player_data):
    """Convert the country record and province updates in a tournament move in place."""
    # Moves gained game_version after v46. Only an unstamped move can be older than v46.
    if ("game_version" not in player_data
            and any(section not in player_data for section in V46_MOVE_SECTIONS)):
        raise ValueError(
            "This move was made with a game version older than v46. "
            f"The player must update to {c.GAME_VERSION} and export the move again.")
    country = player_data.get("nation_data")
    if isinstance(country, dict):
        _country(country)
    for entry in player_data.get("release_subjects", []):
        if isinstance(entry, dict):
            entry.setdefault("release_type", c.PUPPET_TYPE_INTEGRATED)
    for province in (player_data.get("provinces") or {}).values():
        if isinstance(province, dict):
            # A move has no terrain, so a Truck aircraft unpacks as on land.
            # Host validation then checks every unit against host state.
            _province(province, None)
    _unit_records(player_data, {**LEGACY_UNIT_NAMES, **equipment_stage_aliases()})


# --- Countries ---

def _nations(nation_data):
    if isinstance(nation_data, dict):
        for country in nation_data.values():
            if isinstance(country, dict):
                _country(country)


def _country(country):
    """Convert one country record."""
    country.pop("allied_with", None)
    for project in country.get("research_queue", []):
        days = project.get("days_remaining", LEGACY_RESEARCH_DEFAULT_DAYS) if isinstance(project, dict) else None
        if _is_count(days) and "points_remaining" not in project:
            project["points_remaining"] = days * LEGACY_RESEARCH_POINTS_PER_DAY
    if isinstance(country.get("custom_production_units"), list):
        country["custom_production_units"] = [
            _unit_name(name) for name in country["custom_production_units"]]
    for entry in country.get("release_puppet_queue", []):
        if isinstance(entry, dict):
            entry.setdefault("release_type", c.PUPPET_TYPE_INTEGRATED)
    for event in country.get("scripted_events", []):
        if isinstance(event, dict):
            _scripted_event(event)
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


def _scripted_event(event):
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
            action["unit_type"] = _unit_name(action.get("unit_type"))


# --- Provinces ---

def _province(province, terrain):
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
                _production_turns(entry)
                if "unit_type" in entry:
                    entry["unit_type"] = _unit_name(entry["unit_type"])
    for unit in province.get("units", []):
        if not isinstance(unit, dict):
            continue
        for field in ("type", "original_type"):
            if field in unit:
                unit[field] = _unit_name(unit[field])
        order = unit.get("order")
        if isinstance(order, dict) and "target_type" in order:
            order["target_type"] = _unit_name(order["target_type"])
        # Move files are player input. Validation reports malformed units after conversion.
        if not isinstance(unit.get("type"), str) or not queries.is_air_transport(unit):
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


def _production_turns(entry):
    """Replace the production day countdown. The older field has priority."""
    if _is_count(entry.get("days_remaining")):
        entry["turns_remaining"] = max(1, entry.pop("days_remaining") // c.DEFAULT_DAYS_PER_TURN)


# --- Unit names ---

def _unit_name(name):
    """Number older unit identifiers, including inside a transport name."""
    if not isinstance(name, str):
        return name
    if name in LEGACY_UNIT_NAMES:
        return LEGACY_UNIT_NAMES[name]
    for carrier in ("Truck", "Convoy"):
        prefix = carrier + " ("
        if name.startswith(prefix) and name.endswith(")"):
            inner = name[len(prefix):-1]
            return prefix + _unit_name(inner) + ")"
    return name


def _unit_records(records, aliases):
    """Convert typed references, including cargo, orders, scripts, and saved history."""
    def converted(name):
        if not isinstance(name, str):
            return name
        for carrier in ("Truck", "Convoy"):
            prefix = carrier + " ("
            if name.startswith(prefix) and name.endswith(")"):
                return prefix + converted(name[len(prefix):-1]) + ")"
        return aliases.get(name, name)

    # Recurse only into containers. A large save holds many plain values.
    if isinstance(records, list):
        for item in records:
            if isinstance(item, (dict, list)):
                _unit_records(item, aliases)
    elif isinstance(records, dict):
        for field, value in records.items():
            if field in ("type", "unit_type", "original_type", "target_type"):
                records[field] = converted(value)
            elif field == "custom_production_units" and isinstance(value, list):
                choices = []
                for name in value:
                    name = converted(name)
                    if name not in choices:
                        choices.append(name)
                records[field] = choices
            elif isinstance(value, (dict, list)):
                _unit_records(value, aliases)


def _is_count(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)
