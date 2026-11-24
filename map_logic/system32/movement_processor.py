
# Faction and agreement cleanup calls movement helpers. Keep those mutation imports local to avoid cycles.

from data.state_access import world_for
from collections import deque

import data.constants as c
from data import queries
from map_logic.system32 import combat_processor
from map_logic.territory import ownership
from map_logic.diplomacy.diplomacy_events import log_global_event


def process_dead_nations(context):
    """Removes defunct units and updates wars, preserving faction exiles."""
    world_state = world_for(context)
    # A government in exile survives only while another member still has land
    # from which it could restore the defeated country. Do this before deriving
    # political activity so an exhausted faction's units and wars are cleaned
    # in this same turn.
    from map_logic.diplomacy.faction_actions import disband_exhausted_factions
    disband_exhausted_factions(world_state.map_data, world_state.nation_data)

    active_nations = queries.get_politically_active_nations(
        world_state.map_data, world_state.nation_data)

    # 1. Disband units whose owners are genuinely defunct.
    for province in world_state.map_data.values():
        surviving_units = []
        for unit in province.get("units", []):
            owner = unit.get("owner")
            # Faction-backed governments in exile retain their armies. They
            # remain on the map until a faction member restores their land.
            if owner in c.UNPLAYABLE_NATIONS or owner in active_nations:
                surviving_units.append(unit)

        # Overwrite the province units with only the survivors
        province["units"] = surviving_units

    # 2. Instantly clean up ghost wars after post-combat captures changed who
    # remains politically active.
    queries.cleanup_ghost_wars(world_state.nation_data, active_nations)

    for nation, data in list(world_state.nation_data.items()):
        # --- Master Independence on Collapse ---
        master = data.get("master", "")
        if master and master not in active_nations:
            from map_logic.diplomacy.puppet_actions import break_puppet_link
            break_puppet_link(world_state.nation_data, master, nation)
            log_global_event(world_state.nation_data, f"{nation} has achieved independence following the collapse of {master}!")

def process_unit_maintenance_orders(context, order_types=None):
    """Processes 1-turn timers for maintenance orders (conversions, disbands, repairs, upgrades).

    Consolidates the four individual maintenance passes into a single sweep over provinces and units.
    """
    world_state = world_for(context)
    unit_library = queries.get_unit_library(context)
    allowed_types = {"DISBAND", "UPGRADE", "REPAIR", "CONVERT"} if order_types is None else set(order_types)

    for province in world_state.map_data.values():
        units_to_keep = []
        has_factory = None
        for unit in province.get("units", []):
            order = unit.get("order")
            if not isinstance(order, dict):
                units_to_keep.append(unit)
                continue

            order_type = order.get("type")
            if order_type not in allowed_types or "turns_left" not in order:
                units_to_keep.append(unit)
                continue

            # 1. Validation & pre-decrement checks
            if order_type == "DISBAND":
                if unit.get("air_cargo"):
                    unit["order"] = {"type": "MOVE", "path": []}
                    units_to_keep.append(unit)
                    continue
            elif order_type == "UPGRADE":
                if has_factory is None:
                    has_factory = queries.has_industry(province)
                if queries.is_air_unit(unit, context=context):
                    try:
                        queries.canonical_unit_order(context, unit["owner"], province, unit, order)
                    except ValueError:
                        unit["order"] = {"type": "MOVE", "path": []}
                        units_to_keep.append(unit)
                        continue
                if not has_factory or queries.get_unit_tier(unit.get("type", ""), context=context) <= 0:
                    unit["order"] = {"type": "MOVE", "path": []}
                    units_to_keep.append(unit)
                    continue
            elif order_type == "CONVERT":
                if queries.is_air_unit(unit, context=context) or queries.is_air_transport(unit, context=context):
                    try:
                        queries.canonical_unit_order(context, unit["owner"], province, unit, order)
                    except ValueError:
                        unit["order"] = {"type": "MOVE", "path": []}
                        units_to_keep.append(unit)
                        continue

            # 2. Timer decrement
            order["turns_left"] -= 1

            if order["turns_left"] <= 0:
                # 3. Completion execution
                if order_type == "DISBAND":
                    p_data = world_state.nation_data.get(unit.get("owner"))
                    if p_data:
                        u_type = unit.get("original_type", unit.get("type"))
                        stats = unit_library.get(u_type, {})
                        queries.refund_resources(p_data, stats)
                    # Dropped from province units
                    continue
                elif order_type == "UPGRADE":
                    target_type = order.get("target_type")
                    if target_type and target_type in unit_library:
                        unit["type"] = target_type
                        queries.apply_library_stats(unit, unit_library, world_state.nation_data)
                    unit["order"] = {"type": "MOVE", "path": []}
                elif order_type == "REPAIR":
                    unit["health"] = unit.get("max_health", c.DEFAULT_UNIT_HP)
                    unit.pop("repair_trip", None)
                    unit["order"] = {"type": "MOVE", "path": []}
                elif order_type == "CONVERT":
                    target = order.get("to")
                    if target in ["Convoy", "Truck"]:
                        queries.load_transport(unit, target, context=context)
                    else:
                        queries.revert_transport(unit, context=context)
                    unit["order"] = {"type": "MOVE", "path": []}

            units_to_keep.append(unit)

        province["units"] = units_to_keep


def process_disbands(context):
    """Processes the 1-turn timer for disbanding units and refunds their cost."""
    process_unit_maintenance_orders(context, order_types={"DISBAND"})


def process_upgrades(context):
    """Processes the 1-turn timer for upgrading units to a new type."""
    process_unit_maintenance_orders(context, order_types={"UPGRADE"})


def process_repairs(context):
    """Processes the 1-turn timer for repairing units to full health."""
    process_unit_maintenance_orders(context, order_types={"REPAIR"})


def process_conversions(context):
    """Processes the timer for transferring units into Convoys/Trucks and back."""
    process_unit_maintenance_orders(context, order_types={"CONVERT"})

def _resolve_step_swaps(context, moving_units, step, pinned_units, *, eligible_ids=None):
    """Fights same-step tile swaps that combat_rules.find_meeting_pairs can't see.

    That check only compares turn-start positions against a unit's very first
    step, so two hostile units that only become adjacent partway through the
    turn (e.g. a 2-speed unit catching up to one that moved last step) could
    otherwise step straight through each other unfought. Active movers are
    detached together before taking the step, so the ordinary destination
    defender check alone cannot detect two opponents exchanging tiles.

    Re-runs the same swap check for the units about to take this step, and
    resolves any hits with the shared combat_processor.resolve_meeting_engagement.
    Returns moving_units with anyone killed in the process removed.
    """
    world_state = world_for(context)
    eligible = [
        u for u in moving_units
        if not u.get("_skip_remaining_steps", False)
        and not u.get("_combat_locked") and u.get("health", 0) > 0
        and id(u) not in pinned_units
        and (eligible_ids is None or id(u) in eligible_ids)
        and u.get("order", {}).get("path")
        and step < queries.unit_movement_speed(u)
    ]
    by_origin = {}
    for u in eligible:
        by_origin.setdefault(u["_current_province_id"], []).append(u)

    seen_edges = set()
    dead_ids = set()
    for u in eligible:
        origin = u["_current_province_id"]
        dest = u["order"]["path"][0]
        edge = tuple(sorted([origin, dest]))
        if edge in seen_edges:
            continue

        opposing = any(
            o["order"]["path"][0] == origin
            and queries.are_at_war(queries.get_unit_combat_owner(u),
                                    queries.get_unit_combat_owner(o), world_state.nation_data)
            for o in by_origin.get(dest, [])
        )
        if not opposing:
            continue
        seen_edges.add(edge)

        prov1 = world_state.id_to_province.get(origin)
        prov2 = world_state.id_to_province.get(dest)
        if not prov1 or not prov2:
            continue

        units1 = [m for m in by_origin.get(origin, []) if m["order"]["path"][0] == dest]
        units2 = [m for m in by_origin.get(dest, []) if m["order"]["path"][0] == origin]

        remaining = combat_processor.defer_tactical_meeting(
            context, prov1, prov2, units1, units2, mid_movement=True, pinned_units=pinned_units)
        if remaining is not None:
            units1, units2 = remaining
        if not units1 or not units2:
            continue
        result = combat_processor.resolve_meeting_engagement(
            prov1, prov2, units1, units2, world_state.nation_data)
        survivors = result.survivors1 + result.survivors2
        survivor_ids = {id(m) for m in survivors}
        dead_ids.update(id(m) for m in units1 + units2 if id(m) not in survivor_ids)

        # A mutual standoff digs both sides in for the rest of this turn; a
        # one-sided win leaves the winners free to keep advancing. Only the
        # units that were actually in the battle are held -- somebody crossing
        # the same edge without a war of their own keeps marching.
        for m in survivors:
            m.pop("_combat_locked", None)
        fighters1 = [m for m in result.survivors1 if id(m) in result.fought]
        fighters2 = [m for m in result.survivors2 if id(m) in result.fought]
        if fighters1 and fighters2:
            for m in fighters1 + fighters2:
                m["_skip_remaining_steps"] = True

    if not dead_ids:
        return moving_units
    return [u for u in moving_units if id(u) not in dead_ids]

def _move_step(context, moving_units, step, active_ids):
    """Apply and commit one batch of simultaneous arrivals using the normal movement rules."""
    world_state = world_for(context)
    for province in world_state.map_data.values():
        province["units"] = [unit for unit in province.get("units", []) if id(unit) not in active_ids]

    for unit in moving_units:
        # Explicitly check if this individual unit has run out of moves or is skipping
        if id(unit) not in active_ids:
            continue

        order = unit.get("order")
        if not order or not order.get("path"): continue

        target_id = order["path"][0]
        target_prov = world_state.id_to_province.get(target_id)
        if not target_prov: continue
        if ((queries.is_air_unit(unit, context=context) or queries.is_air_transport(unit, context=context))
                and not queries.is_water_province(target_prov)
                and not queries.air_unit_can_land(unit, target_prov, world_state.nation_data)):
            order["path"] = []
            continue

        combat_owner = queries.get_unit_combat_owner(unit)
        player_data = world_state.nation_data.get(combat_owner, {})
        dest_owner = target_prov.get("owner", "Unclaimed")

        # --- Combat Lock (Execution Check) ---
        curr_prov = world_state.id_to_province.get(unit["_current_province_id"])
        if curr_prov and not queries.can_unit_leave_current_combat(context, unit, curr_prov, step=step):
            # Stop advancing for this turn, but DO NOT wipe the queue!
            unit["_skip_remaining_steps"] = True
            continue
        # ------------------------------------------

        # --- SHIP RULES EVALUATION ---
        dest_is_water = queries.is_water_province(target_prov)
        u_type = unit.get("type", "")
        is_convoy = u_type.startswith("Convoy")

        # --- Convoy Land Movement Check ---
        if is_convoy and curr_prov:
            if not queries.can_convoy_enter(curr_prov, target_prov):
                order["path"] = []
                continue
        # ---------------------------------------

        if is_convoy:
            is_naval = True
        else:
            stats = context.cached_unit_library.get(u_type, {})
            is_naval = stats.get("naval_unit", False)

        if is_naval and not is_convoy and not queries.can_ships_enter(combat_owner, target_prov, world_state.nation_data):
            # Ships cannot enter hostile/unclaimed land
            order["path"] = []
            continue
        # ---------------------------------

        # Check for existing defenders before moving
        # We look for units belonging to anyone NOT the mover and NOT an ally
        defenders = [u for u in target_prov.get("units", [])
                     if queries.are_at_war(combat_owner, queries.get_unit_combat_owner(u),
                                           world_state.nation_data)]

        if is_naval and not is_convoy:
            can_enter = True # Naval rules already handled above
        elif is_convoy and dest_is_water:
            can_enter = True
        else:
            can_enter = queries.can_land_units_enter(combat_owner, target_prov, world_state.nation_data)

        if can_enter:
            unit["_previous_province_id"] = unit["_current_province_id"]
            unit["_current_province_id"] = target_id
            order["path"].pop(0)

            # Both lane orders are decisions about one tile's fight. Marching
            # somewhere else makes them meaningless at best and misleading at
            # worst, so neither follows the army across the map -- being
            # ignored where it does not apply is not the same as being right.
            # A stale RESERVE in particular used to sit on a unit forever and
            # quietly keep it out of every battle it ever stood in.
            unit.pop("lane_target", None)
            unit.pop("combat_stance", None)

            # --- INSTANT CONVERT FOR CONVOYS UPON LANDING ---
            if is_convoy and not dest_is_water:
                queries.revert_transport(unit, context=context)
                if queries.is_air_unit(unit, context=context):
                    # Aircraft unload at the landing boundary, then must use
                    # flight orders (or a new ground route for missiles).
                    order["path"] = []
            # ------------------------------------------------------------

            # Only conquer if there are NO defenders from an enemy nation
            if not defenders:
                if dest_owner == "Unclaimed" or dest_owner in player_data.get("at_war_with", []):
                    # Prevent capturing water tiles via movement
                    if not queries.is_water_province(target_prov) and not queries.is_air_unit(unit, context=context):
                        capturer = combat_owner
                        # faction core transfer stuff
                        true_owner = queries.get_faction_core_transfer_target(capturer, target_prov, world_state.nation_data)
                        ownership.conquer_province(context, target_prov, true_owner)

            # Stop if an enemy was present
            if defenders:
                # Stop advancing for this turn, but DO NOT wipe the queue!
                unit["_skip_remaining_steps"] = True
        else:
            order["path"] = []

    # Commit the simultaneous arrivals before checking contact. Two enemies
    # entering the same tile must stop even when both had another step.
    for unit in moving_units:
        if unit.get("health", 0) <= 0:
            continue
        prov = world_state.id_to_province.get(unit["_current_province_id"])
        if not any(u is unit for u in prov["units"]):
            prov["units"].append(unit)

def process_movement(context):
    world_state = world_for(context)
    moving_units = []
    # Defense areas only reassign units that began this turn idle.  Keep this
    # evidence on the live map controller rather than unit dictionaries so it
    # can never leak into a save or a multiplayer unit snapshot.
    context._units_with_move_order_this_turn = set()
    for province in world_state.map_data.values():
        units_to_keep = []
        for unit in province.get("units", []):

            # --- Check and clear the combat lock flag ---
            if unit.pop("_combat_locked", False):
                units_to_keep.append(unit)
                continue

            order = unit.get("order")
            if queries.is_air_unit(unit, context=context) and not queries.air_unit_can_move_on_ground(unit, context=context):
                units_to_keep.append(unit)
                continue
            if order and order.get("type") == "MOVE" and order.get("path"):
                if queries.is_air_unit(unit, context=context) or queries.is_air_transport(unit, context=context):
                    try:
                        queries.canonical_unit_order(context, unit["owner"], province, unit, order)
                    except ValueError:
                        unit["order"] = {"type": "MOVE", "path": []}
                        units_to_keep.append(unit)
                        continue
                context._units_with_move_order_this_turn.add(id(unit))
                unit["_current_province_id"] = province["id"]
                unit["_skip_remaining_steps"] = False
                moving_units.append(unit)
                # Keep the complete step-start positions available to pinning.
                # Active movers are detached together just before taking a step.
                units_to_keep.append(unit)
            else:
                units_to_keep.append(unit)
        province["units"] = units_to_keep

    if not moving_units: return

    if not hasattr(context, 'cached_unit_library'):
        context.cached_unit_library = queries.get_unit_library(context)

    max_speed = max(queries.unit_movement_speed(unit) for unit in moving_units)

    for step in range(max_speed):
        pinned = queries.find_movement_pins(context, ((unit, world_state.id_to_province[unit["_current_province_id"]]) for unit in moving_units), step=step)
        while True:
            moving_units = _resolve_step_swaps(context, moving_units, step, pinned)
            remaining_pins = queries.find_movement_pins(context, ((unit, world_state.id_to_province[unit["_current_province_id"]]) for unit in moving_units), step=step)
            if remaining_pins == pinned:
                break
            # Crossings can destroy or hold an incoming attacker. Reconsider its
            # intended pin before moving anyone or consuming a movement step.
            pinned = remaining_pins

        # Moving units take this step simultaneously. Finished, pinned, and
        # combat-held units stay visible as defenders throughout later steps.
        active_ids = {id(unit) for unit, _province in
                      queries.ground_move_records(context, (
                          (unit, world_state.id_to_province[unit["_current_province_id"]])
                          for unit in moving_units), step=step) if id(unit) not in pinned}
        _move_step(context, moving_units, step, active_ids)

        released = set()
        for unit in moving_units:
            if id(unit) not in pinned:
                continue
            province = world_state.id_to_province[unit["_current_province_id"]]
            if queries.is_nation_in_combat_here(queries.get_unit_combat_owner(unit), province, world_state.nation_data):
                unit["order"]["path"] = []
                unit["_skip_remaining_steps"] = True
            else:
                released.add(id(unit))

        if released:
            # A failed arrival costs the defender no movement. Use the same
            # crossing and movement rules for the released units on this step.
            moving_units = _resolve_step_swaps(context, moving_units, step, set(), eligible_ids=released)
            active_ids = {id(unit) for unit, _province in queries.ground_move_records(context, ((unit, world_state.id_to_province[unit["_current_province_id"]]) for unit in moving_units), step=step) if id(unit) in released}
            _move_step(context, moving_units, step, active_ids)

        for unit in moving_units:
            province = world_state.id_to_province[unit["_current_province_id"]]
            if queries.is_nation_in_combat_here(
                    queries.get_unit_combat_owner(unit), province, world_state.nation_data):
                if id(unit) in pinned:
                    unit["order"]["path"] = []
                unit["_skip_remaining_steps"] = True

    # Clean up the temporary tracking flag so it doesn't pollute the save files!
    for unit in moving_units:
        if "_skip_remaining_steps" in unit:
            del unit["_skip_remaining_steps"]

def nearest_owned_province(start_id, owner, id_to_province):
    """BFS over the province graph for the closest tile owned by `owner`, the start included."""
    if start_id not in id_to_province:
        return None
    seen = {start_id}
    queue = deque([start_id])
    while queue:
        province = id_to_province.get(queue.popleft())
        if not province:
            continue
        if province.get("owner") == owner:
            return province
        for neighbor_id in province.get("neighbors", []):
            if neighbor_id not in seen:
                seen.add(neighbor_id)
                queue.append(neighbor_id)
    return None

def send_unit_home(context, province, unit):
    """Teleports one unit off `province` to the nearest tile its owner holds.

    The EU4-style exiled army, lifted out of process_stranded_units so a deal
    can use it the moment the land changes hands rather than waiting for the
    end of the turn -- see deal_effects. Returns False, leaving the unit where
    it is, if its owner has no ground left to stand on.
    """
    world_state = world_for(context)
    home_prov = nearest_owned_province(province["id"], unit["owner"], world_state.id_to_province)
    if home_prov is None:
        return False  # nation holds no territory to return the unit to

    province["units"].remove(unit)
    unit["_current_province_id"] = home_prov["id"]
    unit["_previous_province_id"] = home_prov["id"]
    order = unit.get("order")
    if isinstance(order, dict):
        order["path"] = []
    home_prov.setdefault("units", []).append(unit)
    return True


def is_land_unit(unit, unit_library=None):
    """Whether this unit walks. Naval units follow separate coastal rules."""
    library = unit_library if unit_library is not None else queries.get_unit_library()
    stats = library.get(unit.get("type", ""), {})
    return not (stats.get("air_role") or unit.get("naval_unit") or stats.get("naval_unit", False))


def process_beached_units(context):
    """Puts anything that walks back aboard ship when it is found out at sea.

    A land unit has no legal way into a water province -- can_land_units_enter
    refuses one outright -- so a division standing in the ocean is always the
    wreckage of a bug rather than a move somebody made, and the honest repair is
    to put it back in the transport it must have been in to get there. It keeps
    its move order: a convoy may sail into an adjacent land tile and unpacks on
    arrival, so an invasion that was already under way still lands.

    Written for saves/HOW DO YOU LAUNCH ARTILLERY FROM THE OCEAN, where a
    meeting engagement fought across a shoreline unpacked three convoys that
    were still at sea (see combat_processor.resolve_meeting_engagement, now
    fixed). This is the net under that: it heals the saves the old rule already
    damaged, and closes off any other route to the same state.
    """
    world_state = world_for(context)
    unit_library = queries.get_unit_library(context)

    for province in world_state.map_data.values():
        if not queries.is_water_province(province):
            continue

        for unit in province.get("units", []):
            if not is_land_unit(unit, unit_library):
                continue

            # A Truck is a land transport, so it is caught by the same net.
            # Unload it first rather than wrapping one carrier inside another.
            if unit.get("type", "").startswith("Truck ("):
                queries.revert_transport(unit, context=context)

            queries.load_transport(unit, "Convoy", context=context)


def process_stranded_units(context):
    """Exiles armies that end up occupying foreign soil without a legal right to be there.

    A unit can find itself standing in territory it no longer has any claim to enter
    (a ceasefire/peace is signed, access is revoked, a faction dissolves) since none of
    those events forcibly move units off the map. Rather than pathfinding a route home
    like a real retreat, we just teleport it to the nearest province it still owns,
    mirroring EU4-style "exiled army" handling.
    """
    world_state = world_for(context)
    unit_library = queries.get_unit_library(context)

    for province in list(world_state.map_data.values()):
        owner = province.get("owner")
        if owner in c.UNPLAYABLE_NATIONS:
            continue

        units = province.get("units", [])
        if not units:
            continue

        stranded = []
        for unit in units:
            unit_owner = unit.get("owner")
            unit_side = queries.get_unit_combat_owner(unit)
            if not unit_owner or unit_side == owner or unit_owner in c.UNPLAYABLE_NATIONS:
                continue

            # Naval units follow separate coastal-access rules; only land armies exile here.
            if not is_land_unit(unit, unit_library):
                continue

            if queries.can_land_units_enter(unit_side, province, world_state.nation_data):
                continue  # legally present: at war, has access, or friendly territory

            stranded.append(unit)

        if not stranded:
            continue

        for unit in stranded:
            send_unit_home(context, province, unit)
