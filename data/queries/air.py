"""Aircraft rules: missions, ranges, transport cargo, air drops, and ground-combat interaction."""

import collections
import copy
import data.constants as c
import pygame
from types import SimpleNamespace
from data.state_access import session_for, world_for
from data.queries.geometry import is_water_province
from data.queries.diplomacy import are_at_war
from data.queries.unit_info import (
    AIR_CONVERT_TURNS,
    AIR_DEFAULT_PRIORITY,
    AIR_INTERCEPTION_PRIORITIES,
    AIR_ORDER_TYPES,
    air_unit_stats,
    is_air_transport,
    is_air_unit,
    province_for_order,
    unit_display_domain,
    unit_is_air_drop_recovering,
    units_with_air_cargo,
)
from data.queries.combat_state import get_unit_combat_owner
from data.queries.movement_access import _can_enter_owned_tile
from data.queries.units import (
    apply_unit_health_loss,
    revert_transport,
    unit_target_damage_multiplier,
)
from data import queries


def is_tactical_player_unit(map_screen, unit):
    session_state = session_for(map_screen)
    return bool(session_state.tactical_mode and unit is session_state.player_unit)


def air_stack_attack_efficiency(aircraft_count):
    """Return the attack multiplier for one coalition's flying mission stack."""
    stack_root = max(0, aircraft_count - 1) ** 0.5
    if aircraft_count <= c.AIR_STACK_EFFICIENCY_BREAKPOINT:
        efficiency = 1.0 - c.AIR_STACK_EFFICIENCY_PENALTY * stack_root
    else:
        efficiency = c.AIR_STACK_LARGE_EFFICIENCY_BASE - c.AIR_STACK_LARGE_EFFICIENCY_PENALTY * stack_root
    return max(c.AIR_STACK_MIN_ATTACK_EFFICIENCY, efficiency)


def air_unit_can_patrol(unit, *, context=None):
    """Reusable combat aircraft can defend an area."""
    return (is_air_unit(unit, context=context) and not air_unit_stats(unit, context=context).get("air_consumable", False)
            and not air_unit_can_transport(unit, context=context))


def air_transport_capacity(unit, *, context=None):
    """Read cargo capacity from the current aircraft data."""
    stats = air_unit_stats(unit, context=context)
    return max(0, int(stats.get("air_transport_capacity", 0))) if stats.get("air_role") else 0


def air_unit_can_transport(unit, *, context=None):
    return air_transport_capacity(unit, context=context) > 0


def air_unit_can_strike(unit, *, context=None):
    return is_air_unit(unit, context=context) and not air_unit_can_transport(unit, context=context)


def air_cargo_is_eligible(plane, cargo, *, context=None):
    """A carrier accepts living ground units controlled by the same country."""
    return (cargo is not plane and cargo.get("health", 0) > 0
            and not unit_is_air_drop_recovering(cargo)
            and cargo.get("owner") == plane.get("owner")
            and get_unit_combat_owner(cargo) == get_unit_combat_owner(plane)
            and unit_display_domain(cargo, context=context) == "LAND" and not is_air_transport(cargo, context=context)
            and not cargo.get("air_cargo"))


def air_unit_can_air_drop(unit, *, context=None):
    """An air drop requires a transport with living, eligible ground cargo."""
    cargo = unit.get("air_cargo", [])
    return (air_unit_can_transport(unit, context=context) and 0 < len(cargo) <= air_transport_capacity(unit, context=context)
            and all(air_cargo_is_eligible(unit, member, context=context) for member in cargo))


def air_drop_target_is_legal(unit, target, nation_data):
    """Drop ground units only on land owned by a country at war with their carrier."""
    return (not is_water_province(target) and are_at_war(
        get_unit_combat_owner(unit), target.get("owner"), nation_data))


def set_air_cargo(map_screen, country_id, plane, base, cargo_ids):
    """Apply a validated cargo roster without using any client unit statistics."""
    world_state = world_for(map_screen)
    if (world_state.id_to_province.get(base["id"]) is not base
            or not any(unit is plane for unit in base.get("units", []))
            or plane.get("owner") != country_id or plane.get("health", 0) <= 0
            or not air_unit_can_transport(plane, context=map_screen)):
        raise ValueError("Transport requires your aircraft at its current base.")
    if (not isinstance(cargo_ids, list) or any(not isinstance(uid, str) or not uid for uid in cargo_ids)
            or len(set(cargo_ids)) != len(cargo_ids)):
        raise ValueError("Invalid or duplicate cargo identities.")
    previous = plane.get("air_cargo", [])
    previous_ids = [unit["unit_id"] for unit in previous]
    if cargo_ids == previous_ids:
        return
    if len(cargo_ids) > air_transport_capacity(plane, context=map_screen):
        raise ValueError("The transport aircraft has insufficient cargo capacity.")
    if not queries.air_unit_can_launch(map_screen, plane, base):
        raise ValueError("Load or release cargo on land outside ground combat.")
    available = {unit["unit_id"]: unit for unit in base.get("units", []) + previous}
    selected = []
    for uid in cargo_ids:
        cargo = available.get(uid)
        if cargo is None or not air_cargo_is_eligible(plane, cargo, context=map_screen):
            raise ValueError("Cargo must be your ground unit on the aircraft's tile.")
        if is_tactical_player_unit(map_screen, cargo):
            raise ValueError("The tactical player's division cannot be loaded by another unit.")
        selected.append(cargo)
    selected_ids = set(cargo_ids)
    for cargo in selected:
        if cargo["unit_id"] not in previous_ids:
            # A loaded unit cannot execute a ground order or retain a paid repair.
            order = cargo.get("order") or {}
            if order.get("refund"):
                raise ValueError("Cancel the cargo unit's paid order before loading it.")
    for cargo in previous:
        if cargo["unit_id"] not in selected_ids:
            cargo["order"] = {"type": "MOVE", "path": []}
            cargo.pop("_combat_locked", None)
            base["units"].append(cargo)
    base["units"][:] = [unit for unit in base["units"] if unit["unit_id"] not in selected_ids]
    for cargo in selected:
        cargo["order"] = {"type": "MOVE", "path": []}
        cargo.pop("combat_stance", None)
        cargo.pop("lane_target", None)
    plane["air_cargo"] = selected


def air_transport_commands(map_screen, country_id):
    """Serialize cargo identities, including empty rosters that release cargo."""
    world_state = world_for(map_screen)
    return [{"type": "air_transport", "plane_id": plane["unit_id"],
             "province_id": base["id"],
             "cargo_ids": [unit["unit_id"] for unit in plane.get("air_cargo", [])]}
            for base in world_state.map_data.values() for plane in base.get("units", [])
            if plane.get("owner") == country_id and air_unit_can_transport(plane, context=map_screen)]


def apply_air_transport_commands(map_screen, country_id, commands):
    """Validate a complete transport draft before applying it to host state."""
    world_state = world_for(map_screen)
    if not isinstance(commands, list):
        raise ValueError("Invalid transport commands.")
    if not commands:
        return []
    data = copy.deepcopy(world_state.map_data)
    draft = SimpleNamespace(map_data=data, id_to_province={p["id"]: p for p in data.values()},
                            nation_data=world_state.nation_data, tactical_mode=False, player_unit=None)
    seen, assigned, canonical = set(), set(), []
    for command in commands:
        if not isinstance(command, dict) or not isinstance(command.get("plane_id"), str):
            raise ValueError("Invalid transport aircraft identity.")
        uid = command["plane_id"]
        if uid in seen:
            raise ValueError("Duplicate transport aircraft command.")
        seen.add(uid)
        base = province_for_order(draft, command.get("province_id"))
        plane = next((u for u in base.get("units", []) if u.get("unit_id") == uid), None)
        if plane is None:
            raise ValueError("The transport aircraft is no longer at its base.")
        cargo_ids = command.get("cargo_ids")
        if (command.get("type") != "air_transport" or not isinstance(cargo_ids, list)
                or any(not isinstance(cid, str) or not cid for cid in cargo_ids)
                or len(set(cargo_ids)) != len(cargo_ids) or assigned.intersection(cargo_ids)):
            raise ValueError("Invalid or duplicate cargo assignment.")
        assigned.update(cargo_ids)
        canonical.append({"type": "air_transport", "plane_id": uid, "province_id": base["id"],
                          "cargo_ids": list(cargo_ids)})
    # Release first, so a transfer between carriers is independent of row order.
    _apply_air_cargo_rosters(draft, country_id, canonical)
    # All checks completed on a copy. Apply the same changes to live identities.
    _apply_air_cargo_rosters(map_screen, country_id, canonical)
    return canonical


def _apply_air_cargo_rosters(map_screen, country_id, canonical):
    world_state = world_for(map_screen)
    for command in canonical:
        base = world_state.id_to_province[command["province_id"]]
        plane = next(u for u in base["units"] if u["unit_id"] == command["plane_id"])
        retained = [u["unit_id"] for u in plane.get("air_cargo", []) if u["unit_id"] in command["cargo_ids"]]
        set_air_cargo(map_screen, country_id, plane, base, retained)
    for command in canonical:
        base = world_state.id_to_province[command["province_id"]]
        plane = next(u for u in base["units"] if u["unit_id"] == command["plane_id"])
        set_air_cargo(map_screen, country_id, plane, base, command["cargo_ids"])


def air_transport_draft(map_screen, country_id, commands):
    """Create a transport projection for order validation without changing state."""
    world_state = world_for(map_screen)
    draft = copy.copy(map_screen)
    draft.map_data = copy.deepcopy(world_state.map_data)
    draft.id_to_province = {p["id"]: p for p in draft.map_data.values()}
    canonical = apply_air_transport_commands(draft, country_id, commands)
    return draft, canonical


def air_unit_can_launch(map_screen, unit, base):
    """A mission needs an unpacked aircraft at a land base outside ground combat."""
    world_state = world_for(map_screen)
    return (is_air_unit(unit, context=map_screen) and not is_water_province(base)
            and not queries.is_nation_in_combat_here(get_unit_combat_owner(unit), base, world_state.nation_data))


def air_target_is_hostile(unit, target, nation_data, visible_only=False):
    """Enemy territory or hostile units make a destination a strike target."""
    country = get_unit_combat_owner(unit)
    if are_at_war(country, target.get("owner"), nation_data):
        return True
    units = target.get("units", [])
    if visible_only:
        units = queries.filter_visible_units(units, country, target, nation_data)
    return any(other.get("health", 0) > 0 and are_at_war(
        country, get_unit_combat_owner(other), nation_data) for other in units)


def air_unit_can_land(unit, target, nation_data):
    """Landing needs accessible land without enemy troops or ownerless territory."""
    owner = target.get("owner", "Unclaimed")
    return (not is_water_province(target) and owner not in c.OWNERLESS_OWNERS
            and not air_target_is_hostile(unit, target, nation_data)
            and _can_enter_owned_tile(get_unit_combat_owner(unit), owner, nation_data))


def air_move_is_strike(map_screen, unit, destination):
    """Route clicks using known ownership and visible units, without revealing fogged troops."""
    world_state = world_for(map_screen)
    return (are_at_war(get_unit_combat_owner(unit), destination.get("owner"), world_state.nation_data)
            or queries.is_province_visible(map_screen, destination["id"]) and air_target_is_hostile(
                unit, destination, world_state.nation_data, visible_only=True))


def available_air_missions(map_screen, unit, base):
    """Read mission capabilities and launch legality for a mission selector."""
    missions = {"NONE"}
    if is_air_unit(unit, context=map_screen) and queries.air_unit_can_launch(map_screen, unit, base):
        missions.add("MOVE")
        if air_unit_can_transport(unit, context=map_screen):
            missions.add("TRANSPORT")
        if air_unit_can_air_drop(unit, context=map_screen):
            missions.add("AIR_DROP")
        if air_unit_can_strike(unit, context=map_screen):
            missions.add("STRIKE")
        if air_unit_can_patrol(unit, context=map_screen):
            missions.update(AIR_INTERCEPTION_PRIORITIES)
    return missions


def air_unit_can_move_on_ground(unit, *, context=None):
    """One-use air weapons relocate along land edges at their listed speed."""
    return is_air_unit(unit, context=context) and bool(air_unit_stats(unit, context=context).get("air_consumable"))


def air_unit_can_damage_forts(unit, *, context=None):
    """Current unit-library capability; missing flags and transports cannot strike forts."""
    stats = air_unit_stats(unit, context=context)
    return bool(stats.get("air_role") and stats.get("air_damages_forts", False))


def air_range_preview_kind(map_screen, unit, destination=None):
    """Show the current mission's reach, or the pending move click's reach."""
    world_state = world_for(map_screen)
    order = unit.get("order")
    if isinstance(order, dict) and order.get("type") in AIR_ORDER_TYPES:
        return order["type"]
    if (air_unit_can_air_drop(unit, context=map_screen) and destination is not None
            and air_drop_target_is_legal(unit, destination, world_state.nation_data)):
        return "AIR_DROP"
    if air_unit_can_strike(unit, context=map_screen) and (air_unit_can_move_on_ground(unit, context=map_screen) or (
            destination is not None and air_move_is_strike(map_screen, unit, destination))):
        return "AIR_ATTACK"
    return "AIR_REPOSITION"


def air_order_radius(unit, kind, *, context=None):
    """Air drops reserve half the transport's listed movement range for the return."""
    stats = air_unit_stats(unit, context=context)
    radius = stats.get("air_range_px", 0)
    if kind == "AIR_DROP":
        return radius / 2
    if kind == "AIR_REPOSITION" and not air_unit_can_transport(unit, context=context):
        return radius * 2
    return radius


def get_air_unit_traits(unit_type, *, context=None):
    """Research details derived from the same capabilities as aircraft orders."""
    unit = {"type": unit_type}
    stats = air_unit_stats(unit, context=context)
    if not stats.get("air_role"):
        return []
    if air_unit_can_transport(unit, context=context):
        reposition = queries.air_order_radius(unit, "AIR_REPOSITION", context=context)
        return [f"Move range: {reposition:g} map pixels.",
                f"Air Drop range: {queries.air_order_radius(unit, 'AIR_DROP', context=context):g} map pixels; returns to base.",
                f"Transport capacity: {air_transport_capacity(unit, context=context)} ground units.",
                "Move, Transport, and Air Drop missions; no strikes or area defense.",
                "Load and release your ground units on the same tile.",
                "Cargo shares the carrier's proportional health loss.",
                "Destroyed immediately when caught in ground combat."]
    strike = queries.air_order_radius(unit, "AIR_ATTACK", context=context)
    if stats.get("air_consumable"):
        traits = [f"Strike range: {strike:g} map pixels; consumed after impact.",
                  "No patrol or air reposition; relocate on land at listed ground speed.",
                  "Immune to interception." if stats.get("air_interception_immune")
                  else "Can be intercepted by enemy fighters."]
    else:
        reposition = queries.air_order_radius(unit, "AIR_REPOSITION", context=context)
        traits = [f"Strike / Patrol range: {strike:g} map px; reposition: {reposition:g} px."]
        patrol = queries.air_order_radius(unit, "AIR_PATROL", context=context)
        if stats["air_role"] == "fighter":
            multiplier = unit_target_damage_multiplier(unit, unit, air_to_air=True, context=context)
            traits.append(f"Air-to-air damage x{multiplier:g}; no bonus against ground targets.")
    traits.append("Strikes damage forts." if air_unit_can_damage_forts(unit, context=context)
                  else "Strikes do not damage forts.")
    return traits


def build_air_geometry(map_screen, id_surface=None):
    """Index exact province pixel rectangles once at a map geometry boundary.

    Horizontal runs keep large map images compact. Range measures the nearest
    point of a tile rectangle to the base center, including boundary pixels;
    disconnected parts of a province participate too. No camera data is read.
    Rebuild after loading/repainting ID geometry; distances are discarded with it.
    """
    world_state = world_for(map_screen)
    import numpy as np
    surface = map_screen.id_map if id_surface is None else id_surface
    pixels = pygame.surfarray.array2d(surface)
    colors = {surface.map_rgb(p["map_color"]): p["id"]
              for p in world_state.map_data.values()}
    runs = collections.defaultdict(list)
    for y in range(pixels.shape[1]):
        row = pixels[:, y]
        starts = np.r_[0, np.flatnonzero(row[1:] != row[:-1]) + 1]
        ends = np.r_[starts[1:], len(row)]
        for start, end in zip(starts, ends):
            province_id = colors.get(int(row[start]))
            if province_id is not None:
                runs[province_id].append((int(start), int(end), y))
    map_screen._air_geometry = {key: np.asarray(value, dtype=float)
                                for key, value in runs.items()}
    map_screen._air_distances = {}


def air_distance_squared(map_screen, base, target_id):
    """Exact tile-intersection distance, cached per base/geometry pair."""
    # Lightweight/headless maps can provide geometry directly. Missing geometry
    # fails closed rather than silently falling back to a center-only rule.
    if not hasattr(map_screen, "_air_geometry"):
        if not hasattr(map_screen, "id_map"):
            return float("inf")
        queries.build_air_geometry(map_screen)
    key = (tuple(base["center"]), target_id)
    cached = map_screen._air_distances.get(key)
    if cached is not None:
        return cached
    runs = map_screen._air_geometry.get(target_id)
    if runs is None or not len(runs):
        return float("inf")
    import numpy as np
    x, y = base["center"]
    dx = np.maximum(np.maximum(runs[:, 0] - x, x - runs[:, 1]), 0)
    dy = np.maximum(np.maximum(runs[:, 2] - y, y - runs[:, 2] - 1), 0)
    distance = float(np.min(dx * dx + dy * dy))
    map_screen._air_distances[key] = distance
    return distance


def air_target_in_range(map_screen, unit, base, kind, target_id):
    """One tile's mission reach; validating a command never sweeps the map."""
    world_state = world_for(map_screen)
    if kind not in AIR_ORDER_TYPES or not is_air_unit(unit, context=map_screen) or is_water_province(base):
        return False
    stats = air_unit_stats(unit, context=map_screen)
    if (kind == "AIR_PATROL" and not air_unit_can_patrol(unit, context=map_screen)
            or kind == "AIR_ATTACK" and not air_unit_can_strike(unit, context=map_screen)
            or kind == "AIR_DROP" and not air_unit_can_air_drop(unit, context=map_screen)
            or kind == "AIR_REPOSITION" and stats.get("air_consumable", False)):
        return False
    target = world_state.id_to_province.get(target_id)
    if target is None or kind in ("AIR_REPOSITION", "AIR_DROP") and is_water_province(target):
        return False
    radius = queries.air_order_radius(unit, kind, context=map_screen)
    return queries.air_distance_squared(map_screen, base, target_id) <= radius * radius


def get_air_targets(map_screen, unit, base, kind):
    """Geometry-only preview: never reads fogged units or private orders."""
    world_state = world_for(map_screen)
    return {pid for pid in world_state.id_to_province
            if air_target_in_range(map_screen, unit, base, kind, pid)}


def canonical_air_order(map_screen, unit, base, order):
    """Validate planning/resolution/network air orders against one rule.

    Callers enforce controller identity/phase; this validates capabilities, original
    launch base, target, radius, and priority. Old patrols default to WEAKEST.
    """
    world_state = world_for(map_screen)
    if (not isinstance(order, dict) or not isinstance(order.get("type"), str)
            or order["type"] not in AIR_ORDER_TYPES):
        raise ValueError("Invalid air order.")
    if not queries.air_unit_can_launch(map_screen, unit, base):
        raise ValueError("Air missions require a land base outside ground combat.")
    kind = order["type"]
    if kind == "AIR_ATTACK" and not air_unit_can_strike(unit, context=map_screen):
        raise ValueError("Transport aircraft cannot strike.")
    if kind == "AIR_DROP" and not air_unit_can_air_drop(unit, context=map_screen):
        raise ValueError("Air drops require a transport aircraft carrying ground units.")
    base_id = order.get("base_id", base["id"])
    if type(base_id) is not int or base_id != base["id"]:
        raise ValueError("The aircraft is no longer at its launch base.")
    result = {"type": kind, "base_id": base_id}
    if kind == "AIR_PATROL":
        priority = order.get("priority", AIR_DEFAULT_PRIORITY)
        if not air_unit_can_patrol(unit, context=map_screen) or priority not in AIR_INTERCEPTION_PRIORITIES:
            raise ValueError("Only reusable aircraft can patrol with a valid interception priority.")
        result["priority"] = priority
    else:
        target_id = order.get("target_id")
        if type(target_id) is not int or target_id not in world_state.id_to_province:
            raise ValueError("Unknown air target.")
        if not air_target_in_range(map_screen, unit, base, kind, target_id):
            raise ValueError("Air target is out of range or cannot be landed on.")
        target = world_state.id_to_province[target_id]
        if kind == "AIR_REPOSITION" and not air_unit_can_land(unit, target, world_state.nation_data):
            raise ValueError("Aircraft must land on accessible land without enemy units.")
        if kind == "AIR_ATTACK" and not air_target_is_hostile(unit, target, world_state.nation_data):
            raise ValueError("Air strikes require enemy territory or enemy units.")
        if kind == "AIR_DROP" and not air_drop_target_is_legal(unit, target, world_state.nation_data):
            raise ValueError("Air drops require enemy land territory.")
        result["target_id"] = target_id
    return result


def air_conversion_order(unit, *, context=None):
    if is_air_unit(unit, context=context):
        return {"type": "CONVERT", "to": "Convoy", "turns_left": AIR_CONVERT_TURNS}
    if is_air_transport(unit, context=context):
        return {"type": "CONVERT", "to": "Air Unit", "turns_left": AIR_CONVERT_TURNS}
    return None


def aircraft_caught_in_ground_combat(unit, opponents, nation_data, *, context=None):
    """A based aircraft sharing a ground battle with its enemy is a casualty."""
    # Recovery blocks normal attacks, but troops still occupy the aircraft's base.
    if context is None:
        context = nation_data
    return is_air_unit(unit, context=context) and any(
        other is not unit
        and are_at_war(get_unit_combat_owner(unit), get_unit_combat_owner(other), nation_data)
        for other in opponents)


def prepare_aircraft_for_ground_combat(units, nation_data, opponents=None, on_land=True, *, context=None):
    """Destroy based aircraft before assembling a ground battle or launching."""
    if context is None:
        context = nation_data
    enemies = units if opponents is None else opponents
    if not on_land:
        return
    for unit in units:
        if is_air_transport(unit, context=context) and any(
                other is not unit and other.get("health", 0) > 0
                and are_at_war(get_unit_combat_owner(unit), get_unit_combat_owner(other), nation_data)
                for other in enemies):
            revert_transport(unit, context=context)
    for unit in units:
        if queries.aircraft_caught_in_ground_combat(unit, enemies, nation_data, context=context):
            sources = [(enemy, 1) for enemy in enemies if enemy is not unit
                       and are_at_war(
                get_unit_combat_owner(unit), get_unit_combat_owner(enemy), nation_data)]
            apply_unit_health_loss(unit, unit.get("health", 0), sources=sources)
            unit["order"] = {"type": "MOVE", "path": []}


def normalize_air_orders(map_data):
    """Repair saved recovery timers and aircraft orders. Old units need no recovery."""
    for province in map_data.values():
        for unit in units_with_air_cargo(province.get("units", [])):
            order = unit.get("order")
            if isinstance(order, dict) and order.get("type") == "AIR_DROP_RECOVERY":
                if not unit_is_air_drop_recovering(unit):
                    unit["order"] = {"type": "MOVE", "path": []}
                continue
            if not is_air_unit(unit) or not isinstance(order, dict):
                continue
            if isinstance(order.get("type"), str) and order["type"] in AIR_ORDER_TYPES:
                order.setdefault("base_id", province["id"])
                if order["type"] == "AIR_PATROL":
                    order.setdefault("priority", AIR_DEFAULT_PRIORITY)
            elif order.get("type") == "MOVE" and not air_unit_can_move_on_ground(unit):
                order["path"] = []
            elif order.get("type") == "CONVERT" and order.get("to") == "Truck":
                unit["order"] = (air_conversion_order(unit) if province.get("is_coastal", False)
                                 else {"type": "MOVE", "path": []})
