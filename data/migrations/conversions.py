"""Every conversion rule for older GD5 saves and moves. Every rule runs on every load.

Each rule finds an older shape in the data and converts it to the current format.
A rule does nothing to current data. Do not make a rule depend on a version number.
See data/migrations/MIGRATIONS.md.

Rules that compare saved data with the active libraries run later in the load,
when the scenario has selected its libraries. research.py and queries.refresh_unit_stats own them.
"""

import copy
import uuid

import data.constants as c
from data.migrations.units import LEGACY_UNIT_NAMES, equipment_stage_aliases
from data.migrations.validation import container, expect, number, numeric_fields, records, repaired, research_country, text_fields


LEGACY_RESEARCH_DEFAULT_DAYS = 30


LEGACY_RESEARCH_POINTS_PER_DAY = 10


#: Fields that a move holds beside the country record. The oldest moves held only a country record.
MOVE_FIELDS = ("game_version", "tournament_session", "tournament_turn", "research_years",
               "unit_snapshot", "aircraft_orders", "air_transport", "release_subjects",
               "faction_renames", "appearance_updates", "puppet_siphon_updates",
               "player_intents", "factions")


def convert_save(save_meta, map_data):
    """Convert meta.json and map_data.json in place.

    History snapshots stay in their saved format. Only a selected history turn becomes
    live state, and convert_history_turn converts it then.
    """
    expect(save_meta, dict, "meta")
    expect(map_data, dict, "map_data")
    aliases = {**LEGACY_UNIT_NAMES, **equipment_stage_aliases()}
    _nations(container(save_meta, "nation_data", dict, "meta", repair=True), aliases)
    for key, province in list(map_data.items()):
        if not isinstance(province, dict):
            del map_data[key]
            repaired(f"map_data.{key}")
            continue
        _province(province, province.get("terrain"), aliases, f"map_data.{key}")
    _province_overlays(save_meta, map_data, aliases, "meta")
    # Completed real-time saves made before offline_view open as spectator replays.
    realtime_match = save_meta.get("realtime_match")
    if isinstance(realtime_match, dict) and realtime_match.get("format") == "gd5-realtime-v1":
        realtime_match.setdefault("offline_view", "spectator")


def convert_history_turn(snapshot, map_data):
    """Convert one history snapshot in place before it becomes live state.

    map_data gives each province's terrain by JSON key.
    """
    if not isinstance(snapshot, dict):
        return  # Missing or unreadable historical turns do not prevent loading the world.
    expect(map_data, dict, "map_data")
    aliases = {**LEGACY_UNIT_NAMES, **equipment_stage_aliases()}
    _nations(container(snapshot, "nation_data", dict, "history", repair=True), aliases, "history.nation_data")
    _province_overlays(snapshot, map_data, aliases, "history")


def _province_overlays(saved, map_data, aliases, path):
    for key, province in list(container(saved, "provinces", dict, path, repair=True).items()):
        if not isinstance(province, dict):
            del saved["provinces"][key]
            repaired(f"{path}.provinces.{key}")
            continue
        geometry = map_data.get(key, {})
        if not isinstance(geometry, dict):
            geometry = {}
        _province(province, geometry.get("terrain"), aliases, f"{path}.provinces.{key}")


def convert_move(player_data):
    """Convert a tournament move in place, whatever version wrote it.

    A move without player_intents holds a snapshot of the country.
    data/migrations/snapshot_moves.py reads it after conversion.
    """
    expect(player_data, dict, "move")
    if not any(key in player_data for key in ("nation_data", "provinces", "player_intents")):
        # The oldest moves held only the country record.
        country = {key: player_data.pop(key) for key in list(player_data) if key not in MOVE_FIELDS}
        player_data["nation_data"] = country
        player_data["provinces"] = {}
    aliases = {**LEGACY_UNIT_NAMES, **equipment_stage_aliases()}
    country = container(player_data, "nation_data", dict, "move")
    if "nation_data" in player_data:
        _country(country, aliases, "move.nation_data", player_input=True)
        if "release_subjects" not in player_data and isinstance(country.get("release_puppet_queue"), list):
            # Older moves held release requests only in the country's queue.
            player_data["release_subjects"] = copy.deepcopy(country["release_puppet_queue"])
    for entry, _entry_path in records(player_data, "release_subjects", "move"):
        entry.setdefault("release_type", c.PUPPET_TYPE_INTEGRATED)
    provinces = container(player_data, "provinces", dict, "move")
    for key, province in provinces.items():
        expect(province, dict, f"move.provinces.{key}")
        # A move has no terrain, so a Truck aircraft unpacks as on land.
        # Host validation then checks every unit against host state.
        _province(province, None, aliases, f"move.provinces.{key}", player_input=True)
    if "provinces" in player_data:
        if "aircraft_orders" not in player_data:
            player_data["aircraft_orders"] = _aircraft_orders(provinces)
        # Older moves replaced the country's units only when they listed provinces.
        player_data.setdefault("unit_snapshot", bool(provinces))
    for aircraft, aircraft_path in records(player_data, "aircraft_orders", "move"):
        if aircraft.get("unit_id") is not None:
            text_fields(aircraft, ("unit_id",), aircraft_path)
        _unit_order(aircraft.get("order"), aliases, aircraft_path + ".order", player_input=True)
    for rename, rename_path in records(player_data, "faction_renames", "move"):
        text_fields(rename, ("old_name", "new_name"), rename_path)
    for command, command_path in records(player_data, "player_intents", "move"):
        text_fields(command, ("type",), command_path)
        kind = command.get("type")
        if kind == "unit_order":
            text_fields(command, ("unit_id",), command_path)
            _unit_order(command.get("order"), aliases, command_path + ".order", player_input=True)
        elif kind == "province_queue":
            text_fields(command, ("queue",), command_path)
            if "province_id" in command:
                number(command["province_id"], command_path + ".province_id")
            for entry, entry_path in records(command, "items", command_path):
                _production_entry(entry, entry_path, player_input=True)
                if command.get("queue") == "unit_queue":
                    _unit_queue_entry(entry, aliases)
        elif kind == "country_preferences":
            _custom_production_units(command, aliases, command_path, player_input=True)
        elif kind == "country_appearance":
            container(command, "appearance", dict, command_path)


def _aircraft_orders(provinces):
    """Read orders from the whole aircraft records that older moves held.

    The host keeps its own aircraft statistics and positions, so only orders and names convert.
    """
    from data import queries
    commands = []
    for province in provinces.values():
        units = province.get("units") if isinstance(province, dict) else None
        for unit in units if isinstance(units, list) else ():
            if (isinstance(unit, dict) and isinstance(unit.get("type"), str)
                    and (queries.is_air_unit(unit) or queries.is_air_transport(unit))):
                commands.append({"unit_id": unit.get("unit_id"), "order": copy.deepcopy(unit.get("order")),
                                 "custom_name": unit.get("custom_name")})
    return commands


# --- Countries ---

def _nations(nation_data, aliases, path="meta.nation_data"):
    for name, country in nation_data.items():
        # Pre-war border maps are keyed by faction name, not country fields.
        if name != "FACTION_WAR_MAPS":
            if not isinstance(country, dict):
                country = nation_data[name] = {}
                repaired(f"{path}.{name}")
            _country(country, aliases, f"{path}.{name}")


def _country(country, aliases, path, *, player_input=False):
    """Convert one country record."""
    research_country(country, path, repair=not player_input)
    country.pop("allied_with", None)
    # Summits and the commitments they produced were removed. Nothing reads them.
    country.pop("ai_commitments", None)
    country.pop("summit_log", None)
    for project, _project_path in records(country, "research_queue", path, repair=not player_input):
        days = project.get("days_remaining", LEGACY_RESEARCH_DEFAULT_DAYS)
        if "points_remaining" not in project:
            project["points_remaining"] = days * LEGACY_RESEARCH_POINTS_PER_DAY
    _custom_production_units(country, aliases, path, player_input=player_input)
    for name, mission in container(country, "volunteer_missions", dict, path, repair=not player_input).items():
        mission_path = f"{path}.volunteer_missions.{name}"
        if not player_input and not isinstance(mission, dict):
            country["volunteer_missions"][name] = {}
            repaired(mission_path)
            continue
        expect(mission, dict, mission_path)
        if not player_input:
            held = container(mission, "held_units", list, mission_path, repair=True)
            valid = [entry for entry in held if isinstance(entry, dict)
                     and isinstance(entry.get("unit"), dict) and isinstance(entry["unit"].get("type"), str)]
            if len(valid) != len(held):
                held[:] = valid
                repaired(mission_path + ".held_units")
        for entry, entry_path in records(mission, "held_units", mission_path, repair=not player_input):
            if not player_input and not isinstance(entry.get("unit"), dict):
                continue
            if "unit" in entry:
                _unit(expect(entry["unit"], dict, entry_path + ".unit"), aliases, entry_path + ".unit",
                      player_input=player_input)
    for entry, _entry_path in records(country, "release_puppet_queue", path, repair=not player_input):
        entry.setdefault("release_type", c.PUPPET_TYPE_INTEGRATED)
    for event, event_path in records(country, "scripted_events", path, repair=not player_input):
        _scripted_event(event, aliases, event_path, player_input=player_input)
    for message, _message_path in records(country, "inbox", path, repair=not player_input):
        if not message.get("message_id"):
            message["message_id"] = uuid.uuid4().hex
    # Older replies occupied the proposal slot and could overwrite a travelling offer.
    pending = container(country, "pending_diplomacy", dict, path, repair=not player_input)
    container(country, "diplo_responses", dict, path, repair=not player_input)
    responses = country.setdefault("diplo_responses", {}) if pending else {}
    for other, entry in list(pending.items()):
        if not player_input and not isinstance(entry, (dict, str)):
            del pending[other]
            repaired(f"{path}.pending_diplomacy.{other}")
            continue
        if not isinstance(entry, (dict, str)):
            raise ValueError(f"{path}.pending_diplomacy.{other}: expected an object or text.")
        action = entry.get("action") if isinstance(entry, dict) else entry
        if isinstance(entry, dict):
            text_fields(entry, ("action",), f"{path}.pending_diplomacy.{other}", repair=not player_input)
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


def _scripted_event(event, aliases, path, *, player_input=False):
    """Give an event the condition and action lists that replaced single fields."""
    # Local saves recover unreadable lists; player submissions retain structural checks.
    container(event, "conditions", list, path, repair=not player_input)
    container(event, "actions", list, path, repair=not player_input)
    if "conditions" not in event:
        event["conditions"] = [{
            "type": event.get("condition_type", "Turn Number"),
            "operator": "==", "value": event.get("condition_val", ""), "chain": "AND",
        }]
        event["fire_once"] = True
    if not event.get("actions") and "action_type" in event:
        event["actions"] = [{"type": event["action_type"],
                             "target": event.get("action_target", "None")}]
    for condition, condition_path in records(event, "conditions", path, repair=not player_input):
        text_fields(condition, ("type", "operator", "chain"), condition_path, repair=not player_input)
    for action, action_path in records(event, "actions", path, repair=not player_input):
        text_fields(action, ("type",), action_path, repair=not player_input)
        if action.get("type") == "Spawn Unit":
            text_fields(action, ("unit_type",), action_path, repair=not player_input)
            if "unit_type" in action:
                action["unit_type"] = _unit_name(action["unit_type"], aliases)


# --- Provinces ---

def _province(province, terrain, aliases, path, *, player_input=False):
    """Convert one province record. terrain is the province's map terrain."""
    from data import queries
    buildings = container(province, "buildings", list, path, repair=not player_input)
    if not player_input:
        buildings[:] = [name for name in buildings if isinstance(name, str)]
    else:
        for index, name in enumerate(buildings):
            expect(name, str, f"{path}.buildings[{index}]")
    if "deployment_queue" in province:
        for entry, entry_path in records(province, "deployment_queue", path, repair=not player_input):
            _production_entry(entry, entry_path, player_input=player_input)
        container(province, "unit_queue", list, path, repair=not player_input)
        container(province, "building_queue", list, path, repair=not player_input)
        province.setdefault("unit_queue", [])
        province.setdefault("building_queue", [])
        for entry in province.pop("deployment_queue"):
            queue = "building_queue" if entry.get("order_type") == "BUILDING" else "unit_queue"
            province[queue].append(entry)
    for queue in ("unit_queue", "building_queue"):
        for entry, entry_path in records(province, queue, path, repair=not player_input):
            _production_entry(entry, entry_path, player_input=player_input)
            if queue == "unit_queue":
                _unit_queue_entry(entry, aliases)
    if not player_input:
        for queue in ("unit_queue", "building_queue"):
            entries = container(province, queue, list, path, repair=True)
            valid = [entry for entry in entries if isinstance(entry, dict) and
                          (isinstance(entry.get("unit_type" if queue == "unit_queue" else "item_name"), str)
                           or queue == "building_queue" and entry.get("order_type") in queries.ADMINISTRATIVE_ACTIONS)]
            if len(valid) != len(entries):
                entries[:] = valid
                repaired(f"{path}.{queue}")
    if not player_input:
        units = container(province, "units", list, path, repair=True)
        valid = [unit for unit in units if isinstance(unit, dict) and isinstance(unit.get("type"), str)]
        if len(valid) != len(units):
            units[:] = valid
            repaired(path + ".units")
    for unit, unit_path in records(province, "units", path, repair=not player_input):
        _unit(unit, aliases, unit_path, player_input=player_input)
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


def _production_entry(entry, path, *, player_input=False):
    """Recover local production fields or validate player input, then convert countdowns."""
    text_fields(entry, ("item_name", "unit_type", "order_type"), path, repair=not player_input)
    numeric_fields(entry, ("days_remaining",), path, repair=not player_input)
    if "days_remaining" in entry:
        # The released day field takes priority over any obsolete turn countdown.
        entry["turns_remaining"] = max(1, entry.pop("days_remaining") // c.DEFAULT_DAYS_PER_TURN)
    numeric_fields(entry, ("turns_remaining",), path, repair=not player_input)
    if "refund" in entry:
        refund = container(entry, "refund", dict, path, repair=not player_input)
        numeric_fields(refund, tuple("cost_" + resource for resource in c.ECON_RESOURCE_KEYS),
                       path + ".refund", repair=not player_input)
    if not player_input and "turns_remaining" not in entry:
        entry["turns_remaining"] = 1  # Complete an order whose remaining duration was lost.


# --- Unit names ---

def _unit_name(name, aliases):
    """Convert an older unit identifier, including inside a transport name."""
    if not isinstance(name, str):
        return name
    for carrier in ("Truck", "Convoy"):
        prefix = carrier + " ("
        if name.startswith(prefix) and name.endswith(")"):
            inner = name[len(prefix):-1]
            return prefix + _unit_name(inner, aliases) + ")"
    return aliases.get(name, name)


def _unit(unit, aliases, path, *, player_input=False):
    """Visit only unit fields and cargo; unknown extension data keeps its meaning."""
    text_fields(unit, ("type", "original_type"), path, repair=not player_input)
    # Local saves retain the established identity repair. Player input cannot establish IDs.
    if player_input and unit.get("unit_id") is not None:
        text_fields(unit, ("unit_id",), path)
    had_max_health = "max_health" in unit
    numeric_fields(unit, ("health", "max_health", "original_max_health", "attack", "defense", "speed"),
                   path, repair=not player_input)
    if not player_input and had_max_health and "max_health" not in unit:
        unit["max_health"] = max(1, unit.get("health", c.DEFAULT_UNIT_HP))
    for field in ("type", "original_type"):
        if field in unit:
            unit[field] = _unit_name(unit[field], aliases)
    # An unreadable local order can be canceled without losing the unit.
    if not player_input and unit.get("order") is not None and not isinstance(unit["order"], dict):
        unit["order"] = None
        repaired(path + ".order")
    _unit_order(unit.get("order"), aliases, path + ".order", player_input=player_input)
    if not player_input:
        cargo = container(unit, "air_cargo", list, path, repair=True)
        valid = [carried for carried in cargo if isinstance(carried, dict) and isinstance(carried.get("type"), str)]
        if len(valid) != len(cargo):
            cargo[:] = valid
            repaired(path + ".air_cargo")
    for cargo, cargo_path in records(unit, "air_cargo", path, repair=not player_input):
        _unit(cargo, aliases, cargo_path, player_input=player_input)


def _unit_order(order, aliases, path, *, player_input=False):
    if order is not None:
        expect(order, dict, path)
        text_fields(order, ("type",), path, repair=not player_input)
    if isinstance(order, dict) and order.get("type") == "UPGRADE" and "target_type" in order:
        text_fields(order, ("target_type",), path, repair=not player_input)
        if "target_type" in order:
            order["target_type"] = _unit_name(order["target_type"], aliases)
        elif not player_input:
            order.clear()


def _unit_queue_entry(entry, aliases):
    if isinstance(entry, dict) and "unit_type" in entry:
        entry["unit_type"] = _unit_name(entry["unit_type"], aliases)


def _custom_production_units(record, aliases, path, *, player_input=False):
    values = container(record, "custom_production_units", list, path, repair=not player_input)
    if "custom_production_units" in record:
        choices = []
        for index, name in enumerate(values):
            if not player_input and not isinstance(name, str):
                repaired(f"{path}.custom_production_units[{index}]")
                continue
            expect(name, str, f"{path}.custom_production_units[{index}]")
            name = _unit_name(name, aliases)
            if name not in choices:
                choices.append(name)
        values[:] = choices
