"""Read released v46 move files, which have partial snapshots and no player intents.

Remove this module when v46 moves stop converting, in v48.
See documentation/data_migrations.txt, CURRENT AND OLDER TOURNAMENT CHOICES.
Current moves use the shared commands in map_logic/actions/player_actions.py.
"""

# Keep presentation imports local so tournament file operations do not initialize UI support.

import copy
import math
from dataclasses import dataclass

import data.constants as c
from data import migrations, queries
from data.state_access import world_for
from map_logic.actions import production_actions
from map_logic.diplomacy import faction_actions
from map_logic.diplomacy.puppet_actions import canonical_puppet_release_queue


TOURNAMENT_UNIT_STATS = ("health", "max_health", "morale", "speed", "attack", "defense", "level")


@dataclass
class SnapshotMove:
    """A validated snapshot, ready to apply after any host review."""
    country_update: dict
    merged_country: dict
    provinces: dict
    warnings: list
    live_aircraft: dict
    aircraft_orders: list
    transport_commands: list


def structure_error(player_data):
    """Return why a move without intents has no readable snapshot, if any."""
    if "nation_data" not in player_data or "provinces" not in player_data:
        return "The move must contain both country and province records."
    country, provinces = player_data["nation_data"], player_data["provinces"]
    if not isinstance(country, dict) or not country or not isinstance(provinces, dict):
        return "Invalid country or province records."
    return None


def prepare(map_ref, cid, player_data):
    """Validate a snapshot without changing host state. Raises ValueError if it is invalid."""
    world_state = world_for(map_ref)
    nd, provs = player_data["nation_data"], player_data["provinces"]
    if not isinstance(world_state.nation_data.get(cid), dict):
        raise ValueError("The country does not exist in the host's game.")
    research_snapshot = {"nation_data": {cid: copy.deepcopy(nd)}}
    if "research_years" in player_data:
        research_snapshot["research_years"] = player_data["research_years"]
    migrations.migrate_infantry_research(research_snapshot, queries.get_tech_tree(map_ref))
    nd = research_snapshot["nation_data"][cid]
    queries.validate_air_drop_recovery_armies(
        cid, nd.get("armies", world_state.nation_data[cid].get("armies", [])),
        world_state.nation_data, world_state.map_data)
    existing_releases = world_state.nation_data[cid].get("release_puppet_queue", [])
    releases = player_data.get("release_subjects", existing_releases)
    canonical_releases = canonical_puppet_release_queue(
        world_state.map_data, world_state.nation_data, cid, releases, existing_releases)
    warnings = _validate_administrative_orders(map_ref, cid, provs)
    warnings.extend(_validate_production_projection(map_ref, cid, provs))
    transport_view, transport_commands = queries.air_transport_draft(
        map_ref, cid, player_data.get("air_transport", []))
    cargo_ids = {u["unit_id"] for p in world_state.map_data.values()
                 for plane in p.get("units", []) for u in plane.get("air_cargo", [])}
    cargo_ids.update(uid for command in transport_commands for uid in command["cargo_ids"])
    warnings.extend(_validate_move_snapshot(map_ref, cid, nd, provs, cargo_ids))
    live_aircraft, aircraft_orders = _validate_aircraft_orders(
        transport_view, cid, player_data, provs, cargo_ids)
    nd = dict(nd)
    nd["release_puppet_queue"] = canonical_releases
    merged = migrations.legacy_player_country(map_ref, cid, nd)
    return SnapshotMove(nd, merged, provs, warnings, live_aircraft, aircraft_orders, transport_commands)


def apply(map_ref, cid, player_data, move, summary):
    """Apply a prepared snapshot after any host review and record the result in summary."""
    world_state = world_for(map_ref)
    if move.warnings:
        summary["overridden"] += 1
    if "tournament_session" not in player_data or "tournament_turn" not in player_data:
        summary["legacy"] += 1

    existing = world_state.nation_data[cid]
    world_state.nation_data[cid] = move.merged_country
    summary["faction_renames"] += _apply_faction_renames(
        map_ref, cid, player_data, move.country_update)
    if any(existing.get(key) != move.merged_country.get(key)
           for key in ("name", "adjective", "leader_name", "leader_title",
                       "flag_data", "portrait_data", "color")):
        _sync_appearance_caches(map_ref, cid, move.merged_country)
    queries.apply_air_transport_commands(map_ref, cid, move.transport_commands)
    summary["appearance_updates"] += _apply_appearance_updates(
        map_ref, cid, player_data)
    summary["puppet_siphon_updates"] += _apply_puppet_siphon_updates(
        map_ref, cid, player_data)

    _apply_unit_projection(
        map_ref, cid, move.provinces, move.live_aircraft, move.aircraft_orders,
        replace_units=player_data.get("unit_snapshot") is True or bool(move.provinces))


def _apply_unit_projection(map_ref, country_id, provs, live_aircraft, aircraft_orders, *, replace_units):
    """Apply a validated snapshot's units. This preserves approved stats and queue overrides."""
    world_state = world_for(map_ref)
    # ``unit_snapshot`` was added after the original .gd5move format.
    # Preserve old files' behavior, but make every newly-created move
    # replace even an empty army so disbands and volunteer offers survive.
    apply_unit_snapshot = replace_units
    if apply_unit_snapshot:
        for target_prov in world_state.map_data.values():
            target_prov["units"] = [u for u in target_prov.get("units", [])
                                    if u.get("owner") != country_id or u.get("unit_id") in live_aircraft]

        # Create a lookup for json_key -> tuple key
        json_key_map = {v.get("json_key"): k for k, v in world_state.map_data.items()}

        for prov_key, updates in provs.items():
            real_key = json_key_map.get(prov_key)
            if real_key not in world_state.map_data:
                continue
            target_prov = world_state.map_data[real_key]

            if "building_queue" in updates:
                target_prov["building_queue"] = updates["building_queue"]
            if "unit_queue" in updates:
                target_prov["unit_queue"] = updates["unit_queue"]

            if "units" in updates:
                if "units" not in target_prov:
                    target_prov["units"] = []
                target_prov["units"].extend(u for u in updates["units"] if isinstance(u, dict)
                    and u.get("owner") == country_id and u.get("unit_id") not in live_aircraft
                    and not queries.is_air_unit(u, context=map_ref) and not queries.is_air_transport(u, context=map_ref)
                    and not (isinstance(u.get("order"), dict)
                             and isinstance(u["order"].get("type"), str)
                             and u["order"].get("type") in queries.AIR_ORDER_TYPES))

    for unit, order, name in aircraft_orders:
        uid = unit["unit_id"]
        current = next(u for p in world_state.map_data.values()
                       for u in queries.units_with_air_cargo(p.get("units", []))
                       if u.get("unit_id") == uid)
        current["order"] = order or {"type": "MOVE", "path": []}
        if name:
            current["custom_name"] = name


def _is_valid_map_color(color):
    return (isinstance(color, (list, tuple)) and len(color) in (3, 4)
            and all(isinstance(channel, int) and 0 <= channel <= 255
                    for channel in color))


def _sync_appearance_caches(map_ref, country_id, nation_data):
    """Keep cached country colors and labels consistent with a move import."""
    color = nation_data.get("color")
    if _is_valid_map_color(color) and hasattr(map_ref, "nation_colors"):
        map_ref.nation_colors[country_id] = tuple(color)

    from ui.rendering import country_names
    country_names.clear_country_name_cache(map_ref)


def _apply_faction_renames(map_ref, country_id, player_data, nation_update):
    """Apply a player's faction-rename commands before merging their move.

    A command is checked against the host's current roster, not the player's
    stale copy.  That prevents a non-leader from renaming a faction and means
    a later move from another member cannot undo an already accepted rename.
    """
    world_state = world_for(map_ref)

    has_commands = "faction_renames" in player_data
    commands = player_data.get("faction_renames", ())
    if commands is None:
        commands = ()
    if has_commands and not isinstance(commands, list):
        return 0

    applied = 0
    for command in commands:
        if not isinstance(command, dict):
            continue
        old_name = command.get("old_name")
        new_name = command.get("new_name")
        current_name = world_state.nation_data.get(country_id, {}).get("faction", "")

        # Re-importing the same move is harmless.  In particular this lets a
        # player load their own already-exported move without renaming twice.
        if current_name == new_name:
            continue

        if faction_actions.rename_faction(world_state.nation_data, country_id,
                                          old_name, new_name):
            applied += 1

    # Compatibility for a move exported by the prior tournament format: its
    # leader record is the only evidence of the rename.  Infer it only when
    # the host still has that country as the current leader, which is precisely
    # what the old Rename Faction UI was allowed to do.
    if not has_commands and isinstance(nation_update, dict):
        old_name = world_state.nation_data.get(country_id, {}).get("faction", "")
        new_name = nation_update.get("faction", old_name)
        if old_name != new_name:
            if faction_actions.rename_faction(world_state.nation_data, country_id,
                                              old_name, new_name):
                applied += 1

    if applied:
        from ui.rendering import country_names
        country_names.clear_country_name_cache(map_ref)
    return applied


def _apply_appearance_updates(map_ref, country_id, player_data):
    """Apply permitted integrated-puppet appearance edits from one move.

    The puppet editor intentionally lets a country customise its integrated
    subjects, but those nation records are not otherwise part of that
    country's move file.  The host verifies the ownership relationship and
    limits the payload to the fields that screen actually edits.
    """
    world_state = world_for(map_ref)
    updates = player_data.get("appearance_updates", ())
    if not isinstance(updates, list):
        return 0

    appearance_keys = c.COUNTRY_APPEARANCE_FIELDS
    applied = 0
    for update in updates:
        if not isinstance(update, dict):
            continue
        target = update.get("country_id")
        appearance = update.get("appearance")
        target_data = world_state.nation_data.get(target)
        if (not isinstance(target_data, dict) or not isinstance(appearance, dict)
                or target_data.get("master") != country_id
                or target_data.get("puppet_type") != c.PUPPET_TYPE_INTEGRATED):
            continue

        validated = {key: appearance[key] for key in appearance_keys[:-1]
                     if isinstance(appearance.get(key), str)}
        color = appearance.get("color")
        if _is_valid_map_color(color):
            validated["color"] = list(color)
        queries.apply_country_appearance(world_state.nation_data, target, validated)
        applied += 1

    if applied:
        for update in updates:
            if isinstance(update, dict):
                target = update.get("country_id")
                target_data = world_state.nation_data.get(target)
                if isinstance(target_data, dict):
                    _sync_appearance_caches(map_ref, target, target_data)
    return applied


def _apply_puppet_siphon_updates(map_ref, country_id, player_data):
    """Apply integrated-puppet resource siphons controlled by one player.

    The subject record belongs to a different country id, so it is deliberately
    excluded from the ordinary player nation-data merge.  Values are bounded
    here against the host's current relationship and the same slider limit the
    normal UI uses.
    """
    world_state = world_for(map_ref)
    updates = player_data.get("puppet_siphon_updates", ())
    if not isinstance(updates, list):
        return 0

    applied = 0
    resource_keys = tuple(c.ECON_RESOURCE_KEYS)
    for update in updates:
        if not isinstance(update, dict):
            continue
        target = update.get("country_id")
        rates = update.get("siphon_rates")
        target_data = world_state.nation_data.get(target)
        if (not isinstance(target_data, dict) or not isinstance(rates, dict)
                or target_data.get("master") != country_id
                or target_data.get("puppet_type") != c.PUPPET_TYPE_INTEGRATED):
            continue

        sanitized = {}
        valid = True
        for resource in resource_keys:
            value = rates.get(resource, 0.0)
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or value < 0 or value > c.MAX_PUPPET_SIPHON):
                valid = False
                break
            sanitized[resource] = float(value)
        if not valid:
            continue
        target_data["siphon_rates"] = sanitized
        applied += 1
    return applied


def _validate_aircraft_orders(map_ref, country_id, player_data, provinces, cargo_ids=()):
    """Validate aircraft order commands before any import mutation."""
    world_state = world_for(map_ref)
    live = {unit.get("unit_id"): (unit, province)
            for province in world_state.map_data.values()
            for unit in queries.units_with_air_cargo(province.get("units", []))
            if queries.is_air_unit(unit, context=map_ref) or queries.is_air_transport(unit, context=map_ref)
            or unit.get("unit_id") in cargo_ids or queries.unit_is_air_drop_recovering(unit)}
    for updates in provinces.values():
        if not isinstance(updates, dict) or not isinstance(updates.get("units", []), list):
            raise ValueError("Invalid province unit snapshot.")
        for unit in updates.get("units", []):
            if not isinstance(unit, dict) or (unit.get("unit_id") is not None
                                              and not isinstance(unit["unit_id"], str)):
                raise ValueError("Invalid snapshot unit.")
            if not isinstance(unit.get("type", ""), str):
                raise ValueError("Invalid snapshot unit type.")
            if unit.get("air_cargo") and not queries.is_air_unit(unit, context=map_ref):
                raise ValueError("Unauthorized snapshot cargo.")
            if queries.is_air_unit(unit, context=map_ref) or queries.is_air_transport(unit, context=map_ref):
                if unit.get("unit_id") not in live or unit.get("owner") != country_id:
                    raise ValueError("Unauthorized snapshot aircraft.")
    commands = player_data.get("aircraft_orders", [])
    if not isinstance(commands, list):
        raise ValueError("Invalid aircraft commands.")
    commands = list(commands)
    # Released cargo retains host statistics. Recover only its ground orders.
    commands.extend({"unit_id": unit["unit_id"], "order": unit.get("order"),
                     "custom_name": unit.get("custom_name")}
                    for updates in provinces.values() for unit in updates.get("units", [])
                    if unit.get("unit_id") in cargo_ids
                    and any(current is live[unit["unit_id"]][0]
                            for current in live[unit["unit_id"]][1].get("units", [])))
    validated = []
    seen = set()
    for command in commands:
        if not isinstance(command, dict) or not isinstance(command.get("unit_id"), str):
            raise ValueError("Invalid aircraft identity.")
        uid = command["unit_id"]
        if uid not in live or uid in seen:
            raise ValueError("Unknown or duplicated aircraft command.")
        seen.add(uid)
        unit, province = live[uid]
        if unit.get("owner") != country_id:
            raise ValueError("Aircraft command belongs to another country.")
        if uid in cargo_ids and not any(current is unit for current in province.get("units", [])):
            raise ValueError("Units inside aircraft cannot receive ground orders.")
        queries.validate_air_drop_recovery_draft(unit, command)
        order = queries.canonical_unit_order(map_ref, country_id, province, unit, command.get("order"))
        if isinstance(order, dict):
            order.pop("realtime_cost", None)  # Tournament resources are already in the nation draft.
        name = command.get("custom_name")
        if name is not None and (not isinstance(name, str) or len(name) > 120
                                or any(ord(ch) < 32 for ch in name)):
            raise ValueError("Invalid aircraft name.")
        validated.append((unit, order, name))
    return live, validated


def _validate_administrative_orders(map_ref, country_id, provinces):
    """Validate new core orders against host settings before merging any state.

    Existing entries retain their progress; older moves without administrative
    orders need no new fields. Players cannot change the host's action settings.
    """
    world_state = world_for(map_ref)
    # Lightweight legacy hosts may not carry scenario settings.
    settings = map_ref.scenario_settings
    by_key = {p.get("json_key"): p for p in world_state.map_data.values()}
    warnings = []
    for key, updates in provinces.items():
        if not isinstance(updates, dict):
            raise ValueError("Invalid province updates.")
        queue = updates.get("building_queue", [])
        if not isinstance(queue, list):
            raise ValueError("Invalid building queue.")
        for item in queue:
            if not isinstance(item, dict):
                raise ValueError("Invalid building queue entry.")
            order_type = item.get("order_type")
            if order_type is not None and not isinstance(order_type, str):
                raise ValueError("Invalid building order type.")
            if order_type not in queries.ADMINISTRATIVE_ACTIONS:
                continue
            province = by_key.get(key)
            if province is None or province.get("owner") != country_id:
                raise ValueError("Foreign administrative order.")
            if item in province.get("building_queue", []):
                continue
            if not queries.is_administrative_action_enabled(order_type, settings):
                raise ValueError("Administrative action is disabled.")
            duration = queries.get_administrative_turns(order_type, settings)
            if type(item.get("turns_remaining")) is not int or item["turns_remaining"] < 0:
                raise ValueError("Invalid administrative duration.")
            if item["turns_remaining"] != duration:
                warnings.append(f"Province {key}: {order_type} duration is "
                                f"{item['turns_remaining']}; the host expects {duration}.")
    return warnings


def _validate_move_snapshot(map_ref, country_id, nation_update, provinces, protected_unit_ids=()):
    """Reject malformed snapshots. Report numeric unit differences separately."""
    world_state = world_for(map_ref)
    for resource in c.ECON_RESOURCE_KEYS:
        if resource in nation_update:
            value = nation_update[resource]
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError(f"Invalid {resource} amount: expected a finite number.")

    by_key = {p.get("json_key"): p for p in world_state.map_data.values()}
    live_units = {u.get("unit_id"): u for p in world_state.map_data.values()
                  for u in queries.units_with_air_cargo(p.get("units", []))
                  if u.get("unit_id") is not None}
    seen = set()
    warnings = []
    for key, updates in provinces.items():
        province = by_key.get(key)
        if province is None:
            raise ValueError(f"Unknown province: {key}.")
        if not isinstance(updates, dict):
            raise ValueError(f"Province {key}: expected an update record.")
        for queue_key in ("building_queue", "unit_queue"):
            if queue_key in updates:
                if province.get("owner") != country_id:
                    raise ValueError(f"Province {key}: cannot edit another country's queues.")
                queue = updates[queue_key]
                if not isinstance(queue, list) or any(not isinstance(item, dict) for item in queue):
                    raise ValueError(f"Province {key}: invalid {queue_key}.")
        units = updates.get("units", [])
        if not isinstance(units, list):
            raise ValueError(f"Province {key}: expected a unit list.")
        for unit in units:
            if not isinstance(unit, dict) or unit.get("owner") != country_id:
                raise ValueError(f"Province {key}: invalid unit or unit owned by another country.")
            if not isinstance(unit.get("type", ""), str):
                raise ValueError(f"Province {key}: invalid unit type.")
            uid = unit.get("unit_id")
            if uid is not None:
                if not isinstance(uid, str) or uid in seen:
                    raise ValueError(f"Province {key}: invalid or duplicated unit ID.")
                seen.add(uid)
            original = live_units.get(uid)
            if original is not None and original.get("owner") != country_id:
                raise ValueError(f"Province {key}: unit ID belongs to another country.")
            if original is not None and queries.unit_is_air_drop_recovering(original):
                if not any(current is original for current in province.get("units", [])):
                    raise ValueError("A recovering unit cannot change province.")
                queries.validate_air_drop_recovery_draft(original, unit)
            elif isinstance(unit.get("order"), dict) and unit["order"].get("type") == "AIR_DROP_RECOVERY":
                raise ValueError("Only the host can start air drop recovery.")
            order = unit.get("order")
            if isinstance(order, dict) and order.get("type") == "CONVERT":
                # Legacy snapshots without IDs cannot supply trusted progress.
                source = original if original is not None else dict(unit, order=None)
                if (queries.truck_ship_conversion_order(source, context=map_ref) is not None
                        or order.get("to") in ("Truck", "Ship")):
                    if original is not None and not any(current is original for current in province.get("units", [])):
                        raise ValueError("A converting unit cannot change province.")
                    unit["order"] = queries.canonical_unit_order(map_ref, country_id, province, source, order)
            for stat in TOURNAMENT_UNIT_STATS:
                if stat in unit:
                    value = unit[stat]
                    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                        raise ValueError(f"Province {key}: invalid unit {stat}; expected a finite, nonnegative number.")
                # Legacy units without IDs cannot be matched reliably.
                # Form changes have their own stats and are not comparable.
                if (original is not None and original.get("type") == unit.get("type")
                        and stat in original and unit.get(stat) != original[stat]
                        and uid not in protected_unit_ids
                        and not queries.unit_is_air_drop_recovering(original)
                        and not queries.is_air_unit(unit, context=map_ref) and not queries.is_air_transport(unit, context=map_ref)):
                    warnings.append(f"Unit {uid}, {stat}: move has {unit.get(stat)!r}; "
                                    f"host has {original[stat]!r}.")
    return warnings


def _validate_production_projection(map_ref, country_id, provinces):
    """Use shared production rules while retaining numeric host-review overrides."""
    world = world_for(map_ref)
    by_key = {province.get("json_key"): province for province in world.map_data.values()}
    commands, warnings = [], []
    for key, update in provinces.items():
        province = by_key.get(key)
        if province is None or not isinstance(update, dict):
            raise ValueError("Invalid province production projection.")
        for queue in ("building_queue", "unit_queue"):
            if queue not in update:
                continue
            if province.get("owner") != country_id:
                raise ValueError("Foreign production order.")
            command = production_actions.reconstruct_queue(map_ref, country_id, province, queue, update[queue])
            normalized = []
            for supplied, expected in zip(update[queue], command["items"]):
                supplied = migrations.normalize_production_order(supplied, expected)
                normalized.append(supplied)
                if supplied != migrations.normalize_production_order(expected, {}):
                    warnings.append(f"Province {key}: production timing or refund differs from host data.")
            update[queue] = normalized
            commands.append(command)
    production_actions.validate_queue_budget(world.nation_data[country_id], commands)
    return warnings
