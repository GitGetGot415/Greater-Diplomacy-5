"""Unit move steps, path-finding, tactical speed and fuel, and air move orders."""

import collections
import data.constants as c
import math
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
from data.queries.combat_state import get_unit_combat_owner
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


def get_tactical_speed(unit):
    """Calculates the effective speed of a unit in tactical mode."""
    return unit.get("speed", c.DEFAULT_UNIT_SPD)


def get_tactical_fuel_cost_per_tile(unit, fuel_inc):
    """Calculates the fuel cost per tile moved in tactical mode."""
    calc_speed = get_tactical_speed(unit)
    return math.ceil(fuel_inc / (calc_speed * 0.75)) if calc_speed > 0 else 0


def air_move_order(map_screen, unit, base, destination, mission=None):
    """Retarget flights; idle aircraft choose a mission from the visible destination."""
    world_state = world_for(map_screen)
    if mission is None:
        current = air_unit_mission(unit)
        mission = current if current in AIR_TARGET_MISSION_TYPES else (
            "AIR_DROP" if air_unit_can_air_drop(unit, context=map_screen) and air_drop_target_is_legal(
                unit, destination, world_state.nation_data) else
            "STRIKE" if air_move_is_strike(map_screen, unit, destination) else "MOVE")
    if mission not in AIR_TARGET_MISSION_TYPES:
        raise ValueError("Choose Move, Strike, or Air Drop before selecting an air target.")
    if mission not in available_air_missions(map_screen, unit, base):
        raise ValueError("Air missions require a land base outside ground combat.")
    if mission == "STRIKE" and not air_move_is_strike(map_screen, unit, destination):
        raise ValueError("Air strikes require enemy territory or visible enemy units.")
    if mission == "MOVE" and air_unit_can_move_on_ground(unit, context=map_screen):
        path = find_unit_move_path(unit, base, destination["id"],
                                   world_state.id_to_province, world_state.nation_data, context=map_screen)
        if path is None:
            raise ValueError("No legal ground route exists for this aircraft.")
        return canonical_unit_order(map_screen, unit["owner"], base, unit,
                                    {"type": "MOVE", "path": path})
    kind = AIR_TARGET_MISSION_TYPES[mission]
    return queries.canonical_air_order(map_screen, unit, base,
                               {"type": kind, "target_id": destination["id"]})
