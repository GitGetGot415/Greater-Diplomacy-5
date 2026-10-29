"""Army groups, army symbols, defense-area orders, unit creation, and air-drop recovery."""

import data.constants as c
import os
import random
import uuid
from data.state_access import world_for
from data.queries.unit_info import (
    air_drop_recovery_turns,
    air_unit_has_mission,
    unit_is_air_drop_recovering,
    units_with_air_cargo,
)
from data.queries.units import held_volunteer_units, library_unit_stats
from data.queries.economy import get_conversion_turns
from data.queries.movement import find_unit_move_path
from data import queries


def create_unit_dict(unit_type, owner, unit_library):
    """Generates a standard base unit dictionary to avoid redundant stat parsing."""
    stats = unit_library.get(unit_type, {})
    combat = library_unit_stats(stats)
    return {
        # Unlike Python's ``id()``, this survives save/load, tournament files,
        # and authoritative real-time snapshots.  UI selection remains local,
        # but persistent army rosters refer to this stable identity.
        "unit_id": uuid.uuid4().hex,
        "type": unit_type,
        "owner": owner,
        "health": combat["max_health"],
        "max_health": combat["max_health"],
        "morale": stats.get("morale", c.DEFAULT_UNIT_MORALE),
        "speed": combat["speed"],
        "attack": combat["attack"],
        "defense": combat["defense"],
        "level": 0,
        "order": {"type": "MOVE", "path": []}
    }


def ensure_unit_ids(map_data, nation_data=None):
    """Give every live unit one unique persistent ID and return the IDs added.

    Old maps never had unit IDs.  This migration is intentionally tolerant of
    malformed or duplicate values: the loaded map becomes safe before any
    army roster can refer to it, and the repaired IDs are saved normally.
    """
    seen, added = set(), []
    groups = [units_with_air_cargo(province.get("units", []))
              for province in (map_data or {}).values() if isinstance(province, dict)]
    if nation_data is not None:
        groups.append(held_volunteer_units(nation_data))
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


def repair_spawned_territories(nation_data, map_data):
    """Restore missing starting territory lists for Integrated puppets.

    Editor scenarios can create an Integrated puppet without this list, so this runs on every load.
    """
    for name, country in nation_data.items():
        if country.get("puppet_type") == c.PUPPET_TYPE_INTEGRATED and "spawned_territories" not in country:
            country["spawned_territories"] = [province["id"] for province in map_data.values()
                                               if province.get("owner") == name]


def _army_unit_ids_by_owner(map_data, *, controllable_only=False, nation_data=None):
    """Return the live persistent unit IDs indexed by their owning country."""
    owners = {}
    for province in (map_data or {}).values():
        for unit in units_with_air_cargo(province.get("units", [])) if isinstance(province, dict) else ():
            if controllable_only and unit_is_air_drop_recovering(unit):
                continue
            owner, unit_id = unit.get("owner"), unit.get("unit_id")
            if isinstance(owner, str) and isinstance(unit_id, str) and unit_id:
                owners.setdefault(owner, set()).add(unit_id)
    if nation_data is not None and not controllable_only:
        for unit in held_volunteer_units(nation_data):
            owner, unit_id = unit.get("owner"), unit.get("unit_id")
            if isinstance(owner, str) and isinstance(unit_id, str) and unit_id:
                owners.setdefault(owner, set()).add(unit_id)
    return owners


def army_symbol_choices():
    """Return installed army-emblem names in a stable, display-ready order."""
    try:
        return sorted(
            os.path.splitext(filename)[0]
            for filename in os.listdir(c.ARMY_SYMBOLS_DIR)
            if filename.lower().endswith(".png"))
    except OSError:
        return []


def random_army_symbol():
    """Choose an installed emblem for a newly created army.

    The empty and Custom choices are UI-only options, so they deliberately do
    not appear in ``army_symbol_choices`` and can never be chosen here.
    """
    choices = queries.army_symbol_choices()
    return random.choice(choices) if choices else ""


def normalize_army_symbol(symbol):
    """Return a usable emblem name, or the no-emblem value for stale saves."""
    return symbol if isinstance(symbol, str) and symbol in queries.army_symbol_choices() else ""


def normalize_army_symbol_color(color):
    """Return a JSON-safe RGB army-emblem color, with a safe legacy default."""
    if (isinstance(color, (list, tuple)) and len(color) == 3
            and all(isinstance(channel, int) and not isinstance(channel, bool)
                    and 0 <= channel <= 255 for channel in color)):
        return list(color)
    return list(c.DEFAULT_ARMY_SYMBOL_COLOR)


def normalize_army_symbol_rotation(rotation):
    """Return a supported emblem rotation, defaulting old saves to upright."""
    if (isinstance(rotation, int) and not isinstance(rotation, bool)
            and rotation in c.ARMY_SYMBOL_ROTATIONS):
        return rotation
    return c.DEFAULT_ARMY_SYMBOL_ROTATION


def normalize_army_symbol_flipped(flipped):
    """Return the saved horizontal-emblem mirror flag with a safe default."""
    return flipped if isinstance(flipped, bool) else c.DEFAULT_ARMY_SYMBOL_FLIPPED


def normalize_army_custom_symbol(custom_symbol):
    """Return a safe 20x20 red/black emblem, or no custom emblem.

    A compact row-string format keeps this player-created art JSON-safe for
    saves and multiplayer without introducing a writable image asset.
    """
    size = c.ARMY_CUSTOM_SYMBOL_SIZE
    allowed = {c.ARMY_CUSTOM_SYMBOL_RED, c.ARMY_CUSTOM_SYMBOL_BLACK,
               c.ARMY_CUSTOM_SYMBOL_EMPTY}
    if (not isinstance(custom_symbol, list) or len(custom_symbol) != size
            or any(not isinstance(row, str) or len(row) != size
                   or any(pixel not in allowed for pixel in row)
                   for row in custom_symbol)):
        return None
    normalized = list(custom_symbol)
    return (normalized if any(pixel != c.ARMY_CUSTOM_SYMBOL_EMPTY
                              for row in normalized for pixel in row) else None)


def normalize_army_defense_area(province_ids, map_data):
    """Return a unique, live list of province IDs for an army target area.

    Army records are saved on countries, while province records own the map's
    IDs.  Keeping this validation beside the rest of the army schema means old
    saves, multiplayer rosters, and normal play all agree about what an area
    may contain.
    """
    if not isinstance(province_ids, list):
        return []
    valid_ids = {province.get("id") for province in (map_data or {}).values()
                 if isinstance(province, dict)}
    normalized = []
    for province_id in province_ids:
        if (isinstance(province_id, int) and not isinstance(province_id, bool)
                and province_id in valid_ids and province_id not in normalized):
            normalized.append(province_id)
    return normalized


def normalize_armies(nation_data, map_data):
    """Repair persistent army rosters against the current owned-unit state.

    An army is deliberately only an organizational collection.  It may not
    retain dead, transferred, duplicate, or foreign units, and an empty army
    has no useful UI representation.  This is the canonical cleanup path for
    load, turn resolution, and multiplayer imports.
    """
    ensure_unit_ids(map_data, nation_data)
    live_by_owner = _army_unit_ids_by_owner(map_data, nation_data=nation_data)
    for country_id, country in (nation_data or {}).items():
        if (country_id in ("GLOBAL_EVENTS", "FACTION_WAR_MAPS")
                or country_id in c.UNPLAYABLE_NATIONS or not isinstance(country, dict)):
            continue
        raw_armies = country.get("armies", [])
        if not isinstance(raw_armies, list):
            country["armies"] = []
            continue
        valid, assigned, army_ids = [], set(), set()
        live = live_by_owner.get(country_id, set())
        for raw in raw_armies:
            if not isinstance(raw, dict):
                continue
            army_id = raw.get("id")
            # Unassigned is a derived list entry, never a saved organization.
            if army_id == c.UNASSIGNED_ARMY_ID:
                continue
            if not isinstance(army_id, str) or not army_id or army_id in army_ids:
                army_id = uuid.uuid4().hex
            army_ids.add(army_id)
            requested = raw.get("unit_ids", [])
            if not isinstance(requested, list):
                requested = []
            unit_ids = []
            for unit_id in requested:
                if (isinstance(unit_id, str) and unit_id in live
                        and unit_id not in assigned):
                    unit_ids.append(unit_id)
                    assigned.add(unit_id)
            if not unit_ids:
                continue
            name = raw.get("name")
            if not isinstance(name, str) or not name.strip():
                name = f"Army {len(valid) + 1}"
            defense_area = normalize_army_defense_area(raw.get("defense_area", []), map_data)
            valid.append({"id": army_id, "name": name.strip()[:80],
                          "unit_ids": unit_ids,
                          "symbol": normalize_army_symbol(raw.get("symbol", "")),
                          "symbol_color": normalize_army_symbol_color(
                              raw.get("symbol_color")),
                          "symbol_rotation": normalize_army_symbol_rotation(
                              raw.get("symbol_rotation")),
                          "symbol_flipped": normalize_army_symbol_flipped(
                              raw.get("symbol_flipped")),
                          "custom_symbol": normalize_army_custom_symbol(
                              raw.get("custom_symbol")),
                          "defense_area": defense_area})
        country["armies"] = valid


def get_armies(country_id, nation_data, map_data):
    """Return a country's current army records without doing frame-time scans."""
    country = (nation_data or {}).get(country_id, {})
    return country.get("armies", []) if isinstance(country, dict) else []


def get_unassigned_army(country_id, nation_data, map_data):
    """Build the fixed list entry from current owned units outside saved armies.

    Call at state or input changes. Cache the result for frame rendering.
    This entry never changes map stack identity, saved rosters, or unit orders.
    """
    ensure_unit_ids(map_data)
    assigned = {unit_id for army in get_armies(country_id, nation_data, map_data)
                if army.get("id") != c.UNASSIGNED_ARMY_ID
                for unit_id in army.get("unit_ids", [])}
    unit_ids = [unit["unit_id"] for province in (map_data or {}).values()
                for unit in province.get("units", [])
                if unit.get("owner") == country_id and unit.get("unit_id") not in assigned]
    return {"id": c.UNASSIGNED_ARMY_ID, "name": "Unassigned", "unit_ids": unit_ids,
            "symbol": "", "custom_symbol": None,
            "symbol_color": list(c.UNASSIGNED_ARMY_COLOR),
            "symbol_rotation": c.DEFAULT_ARMY_SYMBOL_ROTATION,
            "symbol_flipped": c.DEFAULT_ARMY_SYMBOL_FLIPPED, "defense_area": []}


def _army_name(armies):
    used = {army.get("name") for army in armies if isinstance(army, dict)}
    number = 1
    while f"Army {number}" in used:
        number += 1
    return f"Army {number}"


def create_army(country_id, unit_ids, nation_data, map_data):
    """Create an automatically named army from owned unit IDs.

    Selected units are reassigned out of prior armies.  Returns the new record
    or ``None`` when no live owned unit was supplied.
    """
    normalize_armies(nation_data, map_data)
    armies = get_armies(country_id, nation_data, map_data)
    live = _army_unit_ids_by_owner(map_data, controllable_only=True).get(country_id, set())
    members = []
    for unit_id in unit_ids if isinstance(unit_ids, (list, tuple, set)) else ():
        if isinstance(unit_id, str) and unit_id in live and unit_id not in members:
            members.append(unit_id)
    if not members:
        return None
    member_set = set(members)
    for army in armies:
        army["unit_ids"] = [unit_id for unit_id in army.get("unit_ids", [])
                             if unit_id not in member_set]
    armies[:] = [army for army in armies if army.get("unit_ids")]
    army = {"id": uuid.uuid4().hex, "name": _army_name(armies),
            "unit_ids": members, "symbol": queries.random_army_symbol(),
            "symbol_color": list(random.choice(c.ARMY_SYMBOL_COLOR_CHOICES)),
            "symbol_rotation": c.DEFAULT_ARMY_SYMBOL_ROTATION,
            "symbol_flipped": c.DEFAULT_ARMY_SYMBOL_FLIPPED,
            "custom_symbol": None,
            "defense_area": []}
    armies.append(army)
    normalize_armies(nation_data, map_data)
    return next((item for item in nation_data[country_id]["armies"]
                 if item["id"] == army["id"]), None)


def assign_units_to_army(country_id, army_id, unit_ids, nation_data, map_data):
    """Move owned units into an existing army and return whether it changed."""
    if army_id == c.UNASSIGNED_ARMY_ID:
        return False
    normalize_armies(nation_data, map_data)
    armies = get_armies(country_id, nation_data, map_data)
    target = next((army for army in armies if army.get("id") == army_id), None)
    if target is None:
        return False
    live = _army_unit_ids_by_owner(map_data, controllable_only=True).get(country_id, set())
    members = []
    for unit_id in unit_ids if isinstance(unit_ids, (list, tuple, set)) else ():
        if isinstance(unit_id, str) and unit_id in live and unit_id not in members:
            members.append(unit_id)
    if not members:
        return False
    member_set = set(members)
    for army in armies:
        army["unit_ids"] = [unit_id for unit_id in army.get("unit_ids", [])
                             if army is target or unit_id not in member_set]
    target["unit_ids"] = list(dict.fromkeys([*target.get("unit_ids", []), *members]))
    normalize_armies(nation_data, map_data)
    return True


def ungroup_units(country_id, unit_ids, nation_data, map_data):
    """Remove selected owned units from every army without deleting units."""
    normalize_armies(nation_data, map_data)
    armies = get_armies(country_id, nation_data, map_data)
    live = _army_unit_ids_by_owner(map_data, controllable_only=True).get(country_id, set())
    members = {unit_id for unit_id in unit_ids if isinstance(unit_id, str) and unit_id in live}
    changed = False
    for army in armies:
        before = army.get("unit_ids", [])
        army["unit_ids"] = [unit_id for unit_id in before if unit_id not in members]
        changed |= len(before) != len(army["unit_ids"])
    normalize_armies(nation_data, map_data)
    return changed


def disband_army(country_id, army_id, nation_data, map_data):
    """Delete an army organization record, never its member units."""
    if army_id == c.UNASSIGNED_ARMY_ID:
        return False
    normalize_armies(nation_data, map_data)
    armies = get_armies(country_id, nation_data, map_data)
    proposed = [army for army in armies if army.get("id") != army_id]
    try:
        validate_air_drop_recovery_armies(country_id, proposed, nation_data, map_data)
    except ValueError:
        return False
    original_len = len(armies)
    armies[:] = [army for army in armies if army.get("id") != army_id]
    return len(armies) != original_len


def move_army(country_id, army_id, direction, nation_data, map_data):
    """Move an army one display slot up or down in its owner's roster."""
    if army_id == c.UNASSIGNED_ARMY_ID:
        return False
    normalize_armies(nation_data, map_data)
    armies = get_armies(country_id, nation_data, map_data)
    index = next((i for i, army in enumerate(armies)
                  if army.get("id") == army_id), None)
    if index is None or direction not in (-1, 1):
        return False
    target = index + direction
    if not 0 <= target < len(armies):
        return False
    armies[index], armies[target] = armies[target], armies[index]
    return True


def update_army_presentation(country_id, army_id, name, symbol, symbol_color, symbol_rotation,
                             symbol_flipped, custom_symbol,
                             nation_data, map_data):
    """Update an army's player-facing label and optional emblem.

    Membership remains untouched.  This is the one mutation path used by the
    map UI, while multiplayer validates the same schema before it reaches a
    canonical nation record.
    """
    if army_id == c.UNASSIGNED_ARMY_ID:
        return None
    normalize_armies(nation_data, map_data)
    army = next((item for item in get_armies(country_id, nation_data, map_data)
                 if item.get("id") == army_id), None)
    if army is None or not isinstance(name, str) or not name.strip():
        return None
    army["name"] = name.strip()[:80]
    army["symbol"] = normalize_army_symbol(symbol)
    army["symbol_color"] = normalize_army_symbol_color(symbol_color)
    army["symbol_rotation"] = normalize_army_symbol_rotation(symbol_rotation)
    army["symbol_flipped"] = normalize_army_symbol_flipped(symbol_flipped)
    army["custom_symbol"] = normalize_army_custom_symbol(custom_symbol)
    if army["custom_symbol"]:
        army["symbol"] = ""
    return army


def set_army_defense_area(country_id, army_id, province_ids, nation_data, map_data):
    """Save one army's selected target tiles and return its canonical record."""
    if army_id == c.UNASSIGNED_ARMY_ID:
        return None
    normalize_armies(nation_data, map_data)
    army = next((item for item in get_armies(country_id, nation_data, map_data)
                 if item.get("id") == army_id), None)
    if army is None:
        return None
    army["defense_area"] = normalize_army_defense_area(province_ids, map_data)
    return army


def unit_has_active_order(unit):
    """Whether a unit has an order that should prevent automatic reassignment."""
    order = unit.get("order") if isinstance(unit, dict) else None
    return (isinstance(order, dict) and bool(order)
            and (order.get("type") != "MOVE" or bool(order.get("path"))))


def begin_air_drop_recovery(unit, scenario_settings=None):
    """Start an uninterruptible recovery order after deployment."""
    turns = get_conversion_turns("AIR_DROP_RECOVERY", scenario_settings)
    unit["order"] = {"type": "AIR_DROP_RECOVERY", "turns_left": turns}


def finish_air_drop_recovery_turn(units):
    """Tick only units that were already recovering when resolution started."""
    for unit in units:
        if unit_is_air_drop_recovering(unit):
            turns = air_drop_recovery_turns(unit) - 1
            unit["order"] = ({"type": "AIR_DROP_RECOVERY", "turns_left": turns} if turns
                             else {"type": "MOVE", "path": []})


def validate_air_drop_recovery_draft(unit, draft):
    """Accept unchanged snapshots but reject commands that interrupt recovery."""
    if unit_is_air_drop_recovering(unit):
        for key in ("order", "custom_name", "combat_stance", "lane_target", "type", "owner"):
            if key in draft and draft[key] != unit.get(key):
                raise ValueError("This unit is recovering from an air drop and cannot be controlled.")


def validate_air_drop_recovery_armies(country_id, armies, nation_data, map_data):
    """Keep recovering units in their existing army, including unassigned units."""
    recovering = [unit for province in map_data.values()
                  for unit in units_with_air_cargo(province.get("units", []))
                  if unit.get("owner") == country_id and unit_is_air_drop_recovering(unit)]
    if not recovering:
        return

    def membership(roster):
        if not isinstance(roster, list) or any(not isinstance(army, dict) for army in roster):
            raise ValueError("Invalid army roster.")
        return {uid: army.get("id") for army in roster for uid in army.get("unit_ids", [])}

    previous = membership(nation_data.get(country_id, {}).get("armies", []))
    proposed = membership(armies)
    if any(previous.get(unit.get("unit_id")) != proposed.get(unit.get("unit_id")) for unit in recovering):
        raise ValueError("A recovering unit cannot change armies.")


def find_unit_move_paths_to_destinations(unit, start_province, destination_ids,
                                         id_to_province, nation_data, *, context=None):
    """Return each legal route from ``start_province`` to a target-area tile.

    ``find_unit_move_path`` remains the movement-rule owner.  Keeping the
    routes separate lets the target-area planner choose a destination that fills
    an uncovered tile instead of independently selecting every unit's nearest
    tile.
    """
    if context is None:
        context = nation_data
    if not isinstance(start_province, dict):
        return {}
    paths = {}
    for destination_id in destination_ids or ():
        if destination_id in paths:
            continue
        if destination_id not in id_to_province:
            continue
        path = find_unit_move_path(unit, start_province, destination_id,
                                   id_to_province, nation_data, context=context)
        if path is not None:
            paths[destination_id] = path
    return paths


def _queue_army_balanced_area_orders(map_screen, country_id, army, destination_ids,
                                     only_idle=False, excluded_unit_object_ids=()):
    """Queue balanced legal routes to one army's target-area tiles.

    Existing members count as defenders, reachable gaps are filled first, then
    reinforcements go to the least-covered destination.
    """
    world_state = world_for(map_screen)
    destinations = list(dict.fromkeys(destination_ids or ()))
    destinations = [province_id for province_id in destinations
                    if province_id in world_state.id_to_province]
    if not destinations:
        return 0
    excluded = set(excluded_unit_object_ids)
    members = set(army.get("unit_ids", []))
    coverage = {province_id: 0 for province_id in destinations}
    candidates = []
    for province in world_state.map_data.values():
        for unit in province.get("units", []):
            if (unit.get("owner") != country_id
                    or unit.get("unit_id") not in members):
                continue
            if unit_is_air_drop_recovering(unit):
                if province.get("id") in coverage:
                    coverage[province["id"]] += 1
                continue
            order = unit.get("order")
            province_id = province.get("id")
            if province_id in coverage:
                coverage[province_id] += 1
                if air_unit_has_mission(unit, context=map_screen):
                    continue
                if (not only_idle and isinstance(order, dict)
                        and order.get("type") == "MOVE"):
                    # A member already within the new area should remain a
                    # defender rather than continue along an old route.
                    unit.pop("order", None)
                continue
            if (id(unit) in excluded or air_unit_has_mission(unit, context=map_screen)
                    or (only_idle and unit_has_active_order(unit))):
                continue
            if (not only_idle and isinstance(order, dict)
                    and order.get("type") in c.ORDERS_BLOCKING_MOVEMENT):
                continue
            paths = find_unit_move_paths_to_destinations(
                unit, province, destinations, world_state.id_to_province,
                world_state.nation_data, context=map_screen)
            if not paths:
                continue
            candidates.append((unit, paths))

    assignments = []
    remaining = list(enumerate(candidates))
    target_rank = {province_id: index for index, province_id
                   in enumerate(destinations)}

    # Prefer a globally closest unit for every reachable gap.  Choosing from
    # all candidates, rather than one unit at a time, prevents an early unit
    # from taking a nearby occupied tile while another tile remains empty.
    while remaining:
        empty_targets = [province_id for province_id in destinations
                         if coverage[province_id] == 0]
        if not empty_targets:
            break
        choices = []
        for candidate_index, (unit, paths) in remaining:
            for province_id in empty_targets:
                path = paths.get(province_id)
                if path is not None:
                    choices.append((len(path), target_rank[province_id],
                                    candidate_index, province_id, unit, path))
        if not choices:
            break
        _length, _rank, candidate_index, province_id, unit, path = min(choices)
        assignments.append((unit, path))
        coverage[province_id] += 1
        remaining = [(index, candidate) for index, candidate in remaining
                     if index != candidate_index]

    # Spread remaining eligible units across the currently least-defended
    # targets.  Route length only breaks ties after defender counts, so the
    # target area stays balanced whenever movement legality permits it.
    while remaining:
        choices = []
        for candidate_index, (unit, paths) in remaining:
            for province_id, path in paths.items():
                choices.append((coverage[province_id], len(path),
                                target_rank[province_id], candidate_index,
                                province_id, unit, path))
        if not choices:
            break
        _count, _length, _rank, candidate_index, province_id, unit, path = min(choices)
        assignments.append((unit, path))
        coverage[province_id] += 1
        remaining = [(index, candidate) for index, candidate in remaining
                     if index != candidate_index]

    for unit, path in assignments:
        unit["order"] = {"type": "MOVE", "path": path}
    return len(assignments)


def _army_record(map_screen, country_id, army_id):
    world_state = world_for(map_screen)
    return next((item for item in get_armies(
        country_id, world_state.nation_data, world_state.map_data)
                 if item.get("id") == army_id), None)


def queue_army_defense_orders(map_screen, country_id, army_id, only_idle=False,
                              excluded_unit_object_ids=()):
    """Queue balanced legal routes to one army's saved target area."""
    if army_id == c.UNASSIGNED_ARMY_ID:
        return 0
    army = _army_record(map_screen, country_id, army_id)
    if army is None:
        return 0
    return _queue_army_balanced_area_orders(
        map_screen, country_id, army, army.get("defense_area", []), only_idle,
        excluded_unit_object_ids)


def queue_idle_army_defense_orders(map_screen):
    """Prepare target-area returns for idle units after this turn resolves."""
    world_state = world_for(map_screen)
    moved_or_ordered = getattr(map_screen, "_units_with_move_order_this_turn", set())
    queued = 0
    for country_id, country in world_state.nation_data.items():
        if not isinstance(country, dict):
            continue
        for army in country.get("armies", []):
            if isinstance(army, dict):
                queued += queue_army_defense_orders(
                    map_screen, country_id, army.get("id"), only_idle=True,
                    excluded_unit_object_ids=moved_or_ordered)
    # This is turn-local evidence, not saved game state.  Clearing it here
    # makes the next resolution evaluate only the moves actually submitted for
    # that next turn.
    map_screen._units_with_move_order_this_turn = set()
    return queued


def army_for_unit(unit, nation_data):
    """Return the owning army for a unit, if it has one.

    The map only calls this for already-visible owned units, so it cannot leak
    army organization through fog-of-war rendering.
    """
    if not isinstance(unit, dict):
        return None
    owner, unit_id = unit.get("owner"), unit.get("unit_id")
    if not isinstance(owner, str) or not isinstance(unit_id, str):
        return None
    for army in get_armies(owner, nation_data, None):
        if unit_id in army.get("unit_ids", []):
            return army
    return None


def group_units_by_army(units, nation_data):
    """Return same-owner units split into their persistent army groups.

    The result preserves the supplied unit order and contains ``(army, units)``
    pairs.  Units outside an army share one ``None`` group, which lets map
    rendering keep an unorganized force compact while giving each organized
    army its own selectable stack.  Callers must pass units belonging to one
    country; owner stacks are intentionally kept separate before this helper is
    used.
    """
    if not units:
        return []

    owner = units[0].get("owner") if isinstance(units[0], dict) else None
    armies_by_unit_id = {}
    if isinstance(owner, str):
        for army in get_armies(owner, nation_data, None):
            if not isinstance(army, dict):
                continue
            for unit_id in army.get("unit_ids", []):
                if isinstance(unit_id, str):
                    armies_by_unit_id[unit_id] = army

    groups, group_indexes = [], {}
    for unit in units:
        unit_id = unit.get("unit_id") if isinstance(unit, dict) else None
        army = armies_by_unit_id.get(unit_id)
        key = army.get("id") if army is not None else None
        index = group_indexes.get(key)
        if index is None:
            group_indexes[key] = len(groups)
            groups.append((army, [unit]))
        else:
            groups[index][1].append(unit)
    return groups


def common_army_for_units(units, nation_data):
    """Return the army shared by every supplied unit, or ``None``.

    A partial selection still identifies its army, but one ungrouped unit or
    units from different armies deliberately removes that shared identity.
    This keeps selection labels and any future group actions on the same
    membership rule as the map and Orders roster.
    """
    common_army = None
    for unit in units:
        army = army_for_unit(unit, nation_data)
        if army is None:
            return None
        if common_army is None:
            common_army = army
        elif army.get("id") != common_army.get("id"):
            return None
    return common_army


def army_color_for_unit(unit, nation_data):
    """Return a unit's persistent army color, or ``None`` when ungrouped.

    This deliberately follows the army presentation field so the Orders
    roster band, army card, and map emblem cannot drift into separate colors.
    Callers must only use it for units whose army membership they may reveal.
    """
    army = army_for_unit(unit, nation_data)
    if army is None:
        return None
    return tuple(normalize_army_symbol_color(army.get("symbol_color")))
