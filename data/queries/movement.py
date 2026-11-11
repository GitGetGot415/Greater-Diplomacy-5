"""Unit move steps, path-finding, and air move orders."""

import collections
import data.constants as c
from data.state_access import world_for
from data.queries.geometry import is_water_province
from data.queries.unit_info import (
    AIR_TARGET_MISSION_TYPES,
    air_unit_mission,
    canonical_unit_order,
    is_air_transport,
    is_air_unit,
    is_naval_unit,
    unit_is_air_drop_recovering,
)
from data.queries.combat_state import get_unit_combat_owner, is_hostile_territory
from data.queries.diplomacy import are_at_war, get_enemies
from data.queries.factions import friendly_nations_view
from data.queries.movement_access import can_convoy_enter, can_land_units_enter, can_ships_enter
from data.queries.air import (
    air_drop_target_is_legal,
    air_move_is_strike,
    air_unit_can_air_drop,
    air_unit_can_land,
    air_unit_can_move_on_ground,
    available_air_missions,
)
from data import queries


def plan_unit_move_orders(context, records, destination, append=False):
    """Prepare the same selected-unit routes for execution and input availability."""
    choices = []
    for unit, origin in records:
        is_aircraft = queries.is_air_unit(unit, context=context)
        air_mission = queries.air_unit_mission(unit) if is_aircraft else None
        if air_mission in queries.AIR_INTERCEPTION_PRIORITIES:
            raise ValueError("Choose Move or Strike, or cancel the aircraft's defense mission, before moving.")
        order = unit.get("order", {})
        if isinstance(order, dict) and order.get("type") in c.ORDERS_BLOCKING_MOVEMENT:
            raise ValueError("Cannot move units with a blocking order.")
        if is_aircraft and (not queries.air_unit_can_move_on_ground(unit, context=context)
                or air_mission == "STRIKE"
                or (air_mission != "MOVE" and queries.air_move_is_strike(context, unit, destination))):
            choices.append((unit, origin, queries.air_move_order(context, unit, origin, destination)))
            continue
        old_path = (list(order.get("path", [])) if append and isinstance(order, dict)
                    and order.get("type") == "MOVE" else [])
        start = context.id_to_province.get(old_path[-1]) if old_path else origin
        if start is None:
            raise ValueError("A selected unit has an invalid queued route.")
        segment = queries.find_unit_move_path(
            unit, start, destination["id"], context.id_to_province, context.nation_data, context=context)
        if segment is None:
            raise ValueError("No legal route exists for every selected unit.")
        path = old_path + segment
        choices.append((unit, origin, {"type": "MOVE", "path": path} if path else None))
    return choices


def can_unit_move_step(unit, current_province, destination, nation_data, *, context=None):
    """Whether ``unit`` may take one currently legal map edge.

    This is deliberately a planning-time rule: combat can still stop a queued
    route during turn resolution, but UI route finding and real-time command
    validation must agree on terrain, convoy, naval, and access constraints.
    """
    if context is None:
        context = nation_data
    if unit_is_air_drop_recovering(unit) or not current_province or not destination:
        return False
    if is_air_unit(unit, context=context) and not air_unit_can_move_on_ground(unit, context=context):
        return False  # Reusable aircraft use flight orders; missiles use land edges.
    if is_air_unit(unit, context=context) and not air_unit_can_land(unit, destination, nation_data):
        return False
    if (is_air_transport(unit, context=context) and not is_water_province(destination)
            and not air_unit_can_land(unit, destination, nation_data)):
        return False
    if destination.get("id") not in current_province.get("neighbors", []):
        return False
    combat_owner = get_unit_combat_owner(unit)
    unit_type = unit.get("type", "")
    if unit_type.startswith("Convoy"):
        if not can_convoy_enter(current_province, destination):
            return False
        return (is_water_province(destination)
                or can_land_units_enter(combat_owner, destination, nation_data))
    if is_naval_unit(unit_type, context=context):
        return can_ships_enter(combat_owner, destination, nation_data)
    return can_land_units_enter(combat_owner, destination, nation_data)


def ground_move_records(context, records=None, *, step=0):
    """Living units able to take this movement step, paired with their current tiles."""
    if records is None:
        records = ((unit, province) for province in world_for(context).map_data.values()
                   for unit in province.get("units", []))
    return [(unit, province) for unit, province in records
            if unit.get("health", 0) > 0 and unit.get("speed", 1) > step
            and not unit.get("_combat_locked") and not unit.get("_skip_remaining_steps")
            and isinstance(unit.get("order"), dict) and unit["order"].get("type") == "MOVE"
            and unit["order"].get("path")
            and not (is_air_unit(unit, context=context)
                     and not air_unit_can_move_on_ground(unit, context=context))]


def move_route_enters_combat(context, unit, *, step=0):
    """Whether this turn's remaining route attacks outside friendly territory.

    A friendly first step cannot disguise an attack later in the same turn.
    Steps queued for a later turn do not prevent a withdrawal this turn.
    Fighting on friendly land does not turn a withdrawal into an offensive route.
    """
    world = world_for(context)
    side = get_unit_combat_owner(unit)
    friendly = friendly_nations_view(side, world.nation_data)
    path = unit.get("order", {}).get("path", [])
    for province_id in path[:max(0, unit.get("speed", 1) - step)]:
        province = world.id_to_province.get(province_id)
        if province is None:
            continue
        owner = province.get("owner", "Unclaimed")
        if is_hostile_territory(side, owner, world.nation_data):
            return True
        if owner not in friendly and any(other.get("health", 0) > 0 and are_at_war(
                side, get_unit_combat_owner(other), world.nation_data)
                for other in province.get("units", [])):
            return True
    return False


def find_movement_pins(context, records=None, *, step=0):
    """Return unit identities pinned by this step's incoming hostile movers.

    Read all intentions before canceling any, so iteration order cannot change
    the result. Hostility belongs to units, regardless of who owns their tiles.
    Opposite moves on the same edge are left to meeting-engagement resolution;
    an attack from any other tile pins an offensive route before that crossing.
    """
    records = ground_move_records(context, records, step=step)
    incoming = collections.defaultdict(list)
    for unit, province in records:
        incoming[unit["order"]["path"][0]].append((unit, province["id"]))
    nation_data = world_for(context).nation_data
    pinned = set()
    for unit, province in records:
        destination = unit["order"]["path"][0]
        attacked_elsewhere = any(
            origin != destination and are_at_war(
                get_unit_combat_owner(unit), get_unit_combat_owner(attacker), nation_data)
            for attacker, origin in incoming.get(province["id"], ()))
        if attacked_elsewhere and move_route_enters_combat(context, unit, step=step):
            pinned.add(id(unit))
    return pinned


def find_unit_move_path(unit, start_province, destination_id, id_to_province, nation_data, *, context=None):
    """Return a deterministic shortest legal route, or ``None`` if blocked.

    Paths contain destination province IDs only, matching the persisted MOVE
    order contract.  Neighbours are sorted so identical maps produce identical
    routes on every client and server.
    """
    if context is None:
        context = nation_data
    if not start_province or destination_id not in id_to_province:
        return None
    start_id = start_province.get("id")
    if start_id == destination_id:
        return []

    frontier = collections.deque([start_id])
    previous = {start_id: None}
    while frontier:
        current_id = frontier.popleft()
        current = id_to_province.get(current_id)
        if not current:
            continue
        for neighbor_id in sorted(current.get("neighbors", []), key=str):
            if neighbor_id in previous:
                continue
            neighbor = id_to_province.get(neighbor_id)
            if not can_unit_move_step(unit, current, neighbor, nation_data, context=context):
                continue
            previous[neighbor_id] = current_id
            if neighbor_id == destination_id:
                path = []
                cursor = destination_id
                while cursor != start_id:
                    path.append(cursor)
                    cursor = previous[cursor]
                return list(reversed(path))
            frontier.append(neighbor_id)
    return None


def find_retreat_routes(unit, province, id_to_province, nation_data, *, context=None):
    """One-step routes, keyed by tile id, from ``province`` to neighbors the unit may enter
    that are not hostile land and hold no units hostile to the unit's side (the AI's retreat rule)."""
    if context is None:
        context = nation_data
    enemies = get_enemies(get_unit_combat_owner(unit), nation_data)
    routes = {}
    for neighbor_id in sorted(province.get("neighbors", []), key=str):
        destination = id_to_province.get(neighbor_id)
        if destination is None or any(get_unit_combat_owner(other) in enemies
                                      for other in destination.get("units", [])):
            continue
        if not is_water_province(destination) and is_hostile_territory(
                get_unit_combat_owner(unit), destination.get("owner", "Unclaimed"), nation_data):
            continue
        if can_unit_move_step(unit, province, destination, nation_data, context=context):
            routes[neighbor_id] = [neighbor_id]
    return routes


def air_move_order(context, unit, base, destination, mission=None):
    """Retarget flights; idle aircraft choose a mission from the visible destination."""
    world_state = world_for(context)
    if mission is None:
        current = air_unit_mission(unit)
        mission = current if current in AIR_TARGET_MISSION_TYPES else (
            "AIR_DROP" if air_unit_can_air_drop(unit, context=context) and air_drop_target_is_legal(
                unit, destination, world_state.nation_data) else
            "STRIKE" if air_move_is_strike(context, unit, destination) else "MOVE")
    if mission not in AIR_TARGET_MISSION_TYPES:
        raise ValueError("Choose Move, Strike, or Air Drop before selecting an air target.")
    if mission not in available_air_missions(context, unit, base):
        raise ValueError("Air missions require a land base outside ground combat.")
    if mission == "STRIKE" and not air_move_is_strike(context, unit, destination):
        raise ValueError("Air strikes require enemy territory or visible enemy units.")
    if mission == "MOVE" and air_unit_can_move_on_ground(unit, context=context):
        path = find_unit_move_path(unit, base, destination["id"],
                                   world_state.id_to_province, world_state.nation_data, context=context)
        if path is None:
            raise ValueError("No legal ground route exists for this aircraft.")
        return canonical_unit_order(context, unit["owner"], base, unit,
                                    {"type": "MOVE", "path": path})
    kind = AIR_TARGET_MISSION_TYPES[mission]
    return queries.canonical_air_order(context, unit, base,
                               {"type": kind, "target_id": destination["id"]})
