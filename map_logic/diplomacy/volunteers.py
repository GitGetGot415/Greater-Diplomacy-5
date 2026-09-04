"""Volunteer division lifecycle and the rules shared by diplomacy and turns."""

from collections import deque
import math

from data import queries
from map_logic.turn_processing import movement_processor

ACTION = "SEND_VOLUNTEERS"
RECALL_ACTION = "RECALL_VOLUNTEERS"
AWAITING = "AWAITING_ANSWER"
OUTBOUND = "OUTBOUND"
DEPLOYED = "DEPLOYED"
RETURNING = "RETURNING"


def combat_owner(unit):
    """The country a unit fights and captures land for.

    A volunteer's normal owner deliberately remains its donor: that is who can
    select and command it.  Its host is the military side it temporarily joins.
    """
    return unit.get("volunteer_host") or unit.get("owner", "")


def missions(nation_data, donor, writable=False):
    data = nation_data.get(donor, {})
    if writable:
        return data.setdefault("volunteer_missions", {})
    return data.get("volunteer_missions", {})


def is_eligible(donor, host, nation_data):
    if donor == host or donor not in nation_data or host not in nation_data:
        return False, "Choose another playable nation."
    if queries.are_at_war(donor, host, nation_data):
        return False, "You cannot send volunteers to an enemy."
    if queries.get_enemies(donor, nation_data):
        return False, "Countries at war cannot send volunteers."
    if not queries.get_enemies(host, nation_data):
        return False, "Volunteers can only be sent to a country at war."
    return True, ""


def _is_land(unit):
    return movement_processor.is_land_unit(unit)


def _held_count(mission):
    return len(mission.get("held_units", [])) if isinstance(mission, dict) else 0


def committed_count(map_screen, donor):
    """All of a donor's divisions unavailable as volunteers, across hosts."""
    count = 0
    for mission in missions(map_screen.nation_data, donor).values():
        count += _held_count(mission)
    for province in map_screen.map_data.values():
        count += sum(1 for unit in province.get("units", [])
                     if unit.get("owner") == donor and unit.get("volunteer_host"))
    return count


def total_divisions(map_screen, donor):
    """The donor's land divisions, including those temporarily off-map."""
    count = 0
    for province in map_screen.map_data.values():
        count += sum(1 for unit in province.get("units", [])
                     if unit.get("owner") == donor and _is_land(unit))
    for mission in missions(map_screen.nation_data, donor).values():
        count += sum(1 for entry in mission.get("held_units", [])
                     if _is_land(entry.get("unit", {})))
    return count


def cap(map_screen, donor):
    total = total_divisions(map_screen, donor)
    return min(6, max(1, int(math.ceil(total * 0.10)))) if total else 0


def remaining_capacity(map_screen, donor):
    return max(0, cap(map_screen, donor) - committed_count(map_screen, donor))


def available_units(map_screen, donor):
    """(province, unit) pairs that may be placed in a new volunteer offer."""
    result = []
    for province in map_screen.map_data.values():
        for unit in province.get("units", []):
            if (unit.get("owner") == donor and _is_land(unit)
                    and not unit.get("volunteer_host")):
                result.append((province, unit))
    return result


def travel_turns(map_screen, donor, host):
    """0 for a border, 1 within five graph steps, otherwise 2."""
    starts = [p["id"] for p in map_screen.map_data.values() if p.get("owner") == donor]
    if not starts:
        return 2
    queue = deque((pid, 0) for pid in starts)
    seen = set(starts)
    while queue:
        province_id, distance = queue.popleft()
        province = map_screen.id_to_province.get(province_id)
        if not province:
            continue
        for neighbor_id in province.get("neighbors", []):
            if neighbor_id in seen:
                continue
            neighbor = map_screen.id_to_province.get(neighbor_id)
            if not neighbor:
                continue
            if neighbor.get("owner") == host:
                return 0 if distance == 0 else (1 if distance + 1 <= 5 else 2)
            seen.add(neighbor_id)
            queue.append((neighbor_id, distance + 1))
    return 2


def _nearest_owned(map_screen, start_id, owner):
    if start_id not in map_screen.id_to_province:
        return None
    queue = deque([start_id])
    seen = {start_id}
    while queue:
        province_id = queue.popleft()
        province = map_screen.id_to_province.get(province_id)
        if not province:
            continue
        if province.get("owner") == owner:
            return province
        for neighbor_id in province.get("neighbors", []):
            if neighbor_id not in seen:
                seen.add(neighbor_id)
                queue.append(neighbor_id)
    return None


def _restore_to_origin(map_screen, donor, entry):
    unit = entry.get("unit")
    origin = map_screen.id_to_province.get(entry.get("origin_id"))
    if not unit:
        return False
    _clear_unit_metadata(unit)
    if origin and origin.get("owner") == donor:
        origin.setdefault("units", []).append(unit)
        return True
    start = origin or next(iter(map_screen.map_data.values()), None)
    if start is None:
        return False
    start.setdefault("units", []).append(unit)
    return movement_processor.send_unit_home(map_screen, start, unit)


def _clear_unit_metadata(unit):
    for key in ("volunteer_host", "volunteer_origin_id"):
        unit.pop(key, None)


def create_offer(map_screen, donor, host, chosen):
    """Remove selected units and create the off-map offer mission.

    `chosen` contains the exact (province, unit) objects displayed in the
    checkbox picker, so an index cannot become stale after earlier removals.
    """
    legal, reason = is_eligible(donor, host, map_screen.nation_data)
    if not legal:
        return None, reason
    if host in missions(map_screen.nation_data, donor):
        return None, "You already have volunteers assigned to this country."
    capacity = remaining_capacity(map_screen, donor)
    valid = [(province, unit) for province, unit in chosen
             if unit in province.get("units", []) and unit.get("owner") == donor
             and _is_land(unit) and not unit.get("volunteer_host")]
    if not valid:
        return None, "Select at least one land division."
    if len(valid) > capacity:
        return None, f"You may send at most {capacity} more volunteer divisions."

    held = []
    for province, unit in valid:
        province["units"].remove(unit)
        held.append({"unit": unit, "origin_id": province["id"]})
    turns = travel_turns(map_screen, donor, host)
    missions(map_screen.nation_data, donor, writable=True)[host] = {
        "state": AWAITING,
        "travel_turns": turns,
        "held_units": held,
    }
    return {"count": len(held), "travel_turns": turns}, ""


def cancel_offer(map_screen, donor, host):
    mission = missions(map_screen.nation_data, donor).get(host)
    if not mission or mission.get("state") != AWAITING:
        return
    for entry in mission.get("held_units", []):
        _restore_to_origin(map_screen, donor, entry)
    missions(map_screen.nation_data, donor, writable=True).pop(host, None)
    pending = map_screen.nation_data.get(donor, {}).get("pending_diplomacy", {})
    info = pending.get(host)
    if isinstance(info, dict) and info.get("action") == ACTION:
        del pending[host]


def accept_offer(map_screen, donor, host):
    mission = missions(map_screen.nation_data, donor).get(host)
    legal, reason = is_eligible(donor, host, map_screen.nation_data)
    if not mission or mission.get("state") != AWAITING:
        return False, "The volunteer offer is no longer available."
    if not legal:
        cancel_offer(map_screen, donor, host)
        return False, reason
    mission["state"] = OUTBOUND
    mission["turns_left"] = mission.get("travel_turns", 2)
    if mission["turns_left"] == 0:
        _deploy(map_screen, donor, host, mission)
    return True, ""


def reject_offer(map_screen, donor, host):
    cancel_offer(map_screen, donor, host)


def _deploy(map_screen, donor, host, mission):
    legal, _reason = is_eligible(donor, host, map_screen.nation_data)
    if not legal:
        for entry in mission.get("held_units", []):
            _restore_to_origin(map_screen, donor, entry)
        missions(map_screen.nation_data, donor, writable=True).pop(host, None)
        return
    for entry in mission.get("held_units", []):
        unit = entry.get("unit")
        destination = _nearest_owned(map_screen, entry.get("origin_id"), host)
        if not unit or not destination:
            _restore_to_origin(map_screen, donor, entry)
            continue
        unit["volunteer_host"] = host
        unit["volunteer_origin_id"] = entry.get("origin_id")
        unit.setdefault("order", {"type": "MOVE", "path": []})["path"] = []
        destination.setdefault("units", []).append(unit)
    mission["held_units"] = []
    mission["state"] = DEPLOYED


def _recall_deployed(map_screen, donor, host, mission):
    held = []
    for province in map_screen.map_data.values():
        survivors = []
        for unit in province.get("units", []):
            if unit.get("owner") == donor and unit.get("volunteer_host") == host:
                held.append({"unit": unit, "origin_id": unit.get("volunteer_origin_id"),
                             "return_from_id": province["id"]})
            else:
                survivors.append(unit)
        province["units"] = survivors
    mission["held_units"] = held


def recall(map_screen, donor, host):
    mission = missions(map_screen.nation_data, donor).get(host)
    if not mission or mission.get("state") == RETURNING:
        return False
    if mission.get("state") == AWAITING:
        cancel_offer(map_screen, donor, host)
        return True
    if mission.get("state") == DEPLOYED:
        _recall_deployed(map_screen, donor, host, mission)
    mission["state"] = RETURNING
    mission["turns_left"] = mission.get("travel_turns", 2)
    if mission["turns_left"] == 0:
        _finish_return(map_screen, donor, host, mission)
    return True


def _finish_return(map_screen, donor, host, mission):
    for entry in mission.get("held_units", []):
        unit = entry.get("unit")
        if not unit:
            continue
        start = map_screen.id_to_province.get(entry.get("return_from_id"))
        if start is None:
            start = map_screen.id_to_province.get(entry.get("origin_id"))
        if start is None:
            continue
        _clear_unit_metadata(unit)
        start.setdefault("units", []).append(unit)
        movement_processor.send_unit_home(map_screen, start, unit)
    missions(map_screen.nation_data, donor, writable=True).pop(host, None)


def mission_state(nation_data, donor, host):
    mission = missions(nation_data, donor).get(host, {})
    return mission.get("state", "")


def tick(map_screen):
    """Advance travel and enforce automatic recall once per diplomacy turn."""
    for donor, data in list(map_screen.nation_data.items()):
        if not isinstance(data, dict):
            continue
        for host, mission in list(missions(map_screen.nation_data, donor).items()):
            state = mission.get("state")
            legal, _reason = is_eligible(donor, host, map_screen.nation_data)
            if state == AWAITING and not legal:
                cancel_offer(map_screen, donor, host)
                continue
            if state in (OUTBOUND, DEPLOYED) and not legal:
                recall(map_screen, donor, host)
                # Recall travel starts now; it must not lose its first turn by
                # also being ticked in this same automatic-recall pass.
                continue
            if state == DEPLOYED:
                if not any(unit.get("owner") == donor and unit.get("volunteer_host") == host
                           for province in map_screen.map_data.values()
                           for unit in province.get("units", [])):
                    missions(map_screen.nation_data, donor, writable=True).pop(host, None)
                continue
            if state in (OUTBOUND, RETURNING):
                mission["turns_left"] = mission.get("turns_left", mission.get("travel_turns", 2)) - 1
                if mission["turns_left"] <= 0:
                    if state == OUTBOUND:
                        _deploy(map_screen, donor, host, mission)
                    else:
                        _finish_return(map_screen, donor, host, mission)
