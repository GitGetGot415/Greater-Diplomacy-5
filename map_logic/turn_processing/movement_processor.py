from collections import deque

import data.constants as c
from data import queries
from map_logic.turn_processing import edit_province_ownership

def process_dead_nations(map_screen):
    """Removes units belonging to nations that no longer control any territory and updates wars."""
    living_nations = queries.get_living_nations(map_screen.map_data)

    # 1. Disband orphaned units of dead nations
    for province in map_screen.map_data.values():
        surviving_units = []
        for unit in province.get("units", []):
            owner = unit.get("owner")
            # Keep the unit if it belongs to an unplayable faction (like Ocean) or an alive nation
            if owner in c.UNPLAYABLE_NATIONS or owner in living_nations:
                surviving_units.append(unit)
        
        # Overwrite the province units with only the survivors
        province["units"] = surviving_units

    # 2. Instantly clean up ghost wars so surviving nations stop treating them as active threats
    # (We run this again here because check_for_post_combat_captures just changed who is alive)
    queries.cleanup_ghost_wars(map_screen.nation_data, living_nations)

    for nation, data in list(map_screen.nation_data.items()):
        # --- NEW: Master Independence on Death ---
        master = data.get("master", "")
        if master and master not in living_nations:
            from map_logic.diplomacy.diplomacy_agreements import break_puppet_link
            break_puppet_link(map_screen.nation_data, master, nation)
            from map_logic.diplomacy.diplomacy_events import log_global_event
            log_global_event(map_screen.nation_data, f"{nation} has achieved independence following the collapse of {master}!")

def process_disbands(map_screen):
    """Processes the 1-turn timer for disbanding units and refunds their cost."""
    unit_library = queries.get_unit_library()

    for province in map_screen.map_data.values():
        units_to_keep = []
        for unit in province.get("units", []):
            order = unit.get("order")
            if isinstance(order, dict) and order.get("type") == "DISBAND":
                order["turns_left"] -= 1
                
                if order["turns_left"] <= 0:
                    # Time's up, process the refund and let the unit fade into the void
                    p_data = map_screen.nation_data.get(unit.get("owner"))
                    if p_data:
                        u_type = unit.get("original_type", unit.get("type"))
                        stats = unit_library.get(u_type, {})
                        queries.refund_resources(p_data, stats)
            else:
                units_to_keep.append(unit)
                
        # Overwrite with the surviving units
        province["units"] = units_to_keep

def process_upgrades(map_screen):
    """Processes the 1-turn timer for upgrading units to a new type."""
    unit_library = queries.get_unit_library()

    for province in map_screen.map_data.values():
        for unit in province.get("units", []):
            order = unit.get("order")
            if isinstance(order, dict) and order.get("type") == "UPGRADE":
                order["turns_left"] -= 1
                
                if order["turns_left"] <= 0:
                    target_type = order.get("target_type")
                    if target_type and target_type in unit_library:
                        stats = unit_library[target_type]
                        hp_pct = unit.get("health", 1) / max(1, unit.get("max_health", 1))
                        
                        unit["type"] = target_type
                        unit["max_health"] = stats.get("health", c.DEFAULT_UNIT_HP)
                        unit["attack"] = stats.get("attack", c.DEFAULT_UNIT_ATK)
                        unit["defense"] = stats.get("defense", c.DEFAULT_UNIT_DEF)
                        unit["speed"] = stats.get("speed", c.DEFAULT_UNIT_SPD)
                        
                        # Maintain percentage health upon upgrading
                        unit["health"] = unit["max_health"] * hp_pct
                        
                    # Reset back to a blank move order
                    unit["order"] = {"type": "MOVE", "path": []}

def process_repairs(map_screen):
    """Processes the 1-turn timer for repairing units to full health."""
    for province in map_screen.map_data.values():
        for unit in province.get("units", []):
            order = unit.get("order")
            if isinstance(order, dict) and order.get("type") == "REPAIR":
                order["turns_left"] -= 1
                
                if order["turns_left"] <= 0:
                    unit["health"] = unit.get("max_health", c.DEFAULT_UNIT_HP)
                    # Reset back to a blank move order so they can be selected again
                    unit["order"] = {"type": "MOVE", "path": []}

def process_conversions(map_screen):
    """Processes the timer for transferring units into Convoys/Trucks and back."""
    for province in map_screen.map_data.values():
        for unit in province.get("units", []):
            order = unit.get("order")
            if isinstance(order, dict) and order.get("type") == "CONVERT":
                order["turns_left"] -= 1
                
                if order["turns_left"] <= 0:
                    target = order.get("to")
                    
                    if target in ["Convoy", "Truck"]:
                        unit["original_type"] = unit["type"]
                        unit["original_speed"] = unit.get("speed", 1)
                        unit["original_max_health"] = unit.get("max_health", c.DEFAULT_UNIT_HP)
                        unit["original_attack"] = unit.get("attack", c.DEFAULT_UNIT_ATK)
                        unit["original_defense"] = unit.get("defense", c.DEFAULT_UNIT_DEF)

                        pct = unit.get("health", 1) / max(1, unit.get("max_health", 1))

                        unit["type"] = f"{target} ({unit['type']})"
                        unit["speed"] = 1

                        if target == "Convoy":
                            unit["naval_unit"] = True
                            unit["max_health"] = c.CONVOY_MAX_HP
                            unit["attack"] = c.CONVOY_ATK
                            unit["defense"] = c.CONVOY_DEF
                        else:
                            unit["naval_unit"] = False
                            unit["max_health"] = c.TRUCK_MAX_HP
                            unit["attack"] = c.TRUCK_ATK
                            unit["defense"] = c.TRUCK_DEF
                            
                        unit["health"] = unit["max_health"] * pct
                    else:
                        queries.revert_transport(unit)
                        
                    # Reset back to a blank move order so they can be selected again
                    unit["order"] = {"type": "MOVE", "path": []}

def process_movement(map_screen):
    moving_units = []
    for province in map_screen.map_data.values():
        units_to_keep = []
        for unit in province.get("units", []):
            
            # --- Check and clear the combat lock flag ---
            if unit.pop("_combat_locked", False):
                units_to_keep.append(unit)
                continue
                
            order = unit.get("order")
            if order and order.get("type") == "MOVE" and order.get("path"):
                unit["_current_province_id"] = province["id"]
                unit["_skip_remaining_steps"] = False
                moving_units.append(unit)
            else:
                units_to_keep.append(unit)
        province["units"] = units_to_keep

    if not moving_units: return
    
    if not hasattr(map_screen, 'cached_unit_library'):
        map_screen.cached_unit_library = queries.get_unit_library()

    # --- NEW HELPER FOR TACTICAL SPEED ---
    def get_eff_speed(u):
        if map_screen.tactical_mode and u is map_screen.player_unit:
            return queries.get_tactical_speed(u)
        return u.get("speed", 1)

    # Calculate max turns loop using the new helper
    max_speed = max(get_eff_speed(u) for u in moving_units)

    for step in range(max_speed):
        for unit in moving_units:
            # Explicitly check if this individual unit has run out of moves or is skipping
            if unit.get("_skip_remaining_steps", False) or step >= get_eff_speed(unit):
                continue
                
            order = unit.get("order")
            if not order or not order.get("path"): continue

            target_id = order["path"][0]
            target_prov = map_screen.id_to_province.get(target_id)
            if not target_prov: continue

            player_data = map_screen.nation_data.get(unit["owner"], {})
            dest_owner = target_prov.get("owner", "Unclaimed")
            
            # --- Combat Lock (Execution Check) ---
            curr_prov = map_screen.id_to_province.get(unit["_current_province_id"])
            if curr_prov:
                in_combat = queries.is_nation_in_combat_here(unit["owner"], curr_prov, map_screen.nation_data)
                
                if in_combat:
                    if step > 0 or queries.is_hostile_territory(unit["owner"], dest_owner, map_screen.nation_data):
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
                stats = map_screen.cached_unit_library.get(u_type, {})
                is_naval = stats.get("naval_unit", False)
                
            if is_naval and not is_convoy and not queries.can_ships_enter(unit["owner"], target_prov, map_screen.nation_data):
                # Ships cannot enter hostile/unclaimed land
                order["path"] = []
                continue
            # ---------------------------------

            # Check for existing defenders before moving
            # We look for units belonging to anyone NOT the mover and NOT an ally
            defenders = [u for u in target_prov.get("units", []) 
                        if u["owner"] != unit["owner"] and u["owner"] not in player_data.get("allied_with", [])]

            if is_naval and not is_convoy:
                can_enter = True # Naval rules already handled above
            elif is_convoy and dest_is_water:
                can_enter = True
            else:
                can_enter = queries.can_land_units_enter(unit["owner"], target_prov, map_screen.nation_data)

            if can_enter:
                # --- TACTICAL MOVEMENT ECONOMY ---
                if map_screen.tactical_mode and unit is map_screen.player_unit:
                    fuel_inc = map_screen.unit_economy.get("fuel_inc", 0)
                    cost_per_tile = queries.get_tactical_fuel_cost_per_tile(unit, fuel_inc)
                    
                    if map_screen.unit_economy.get("fuel", 0) >= cost_per_tile:
                        map_screen.unit_economy["fuel"] -= cost_per_tile
                    else:
                        unit["_skip_remaining_steps"] = True
                        continue
                # ---------------------------------

                unit["_previous_province_id"] = unit["_current_province_id"]
                unit["_current_province_id"] = target_id
                order["path"].pop(0)

                # --- INSTANT CONVERT FOR CONVOYS UPON LANDING ---
                if is_convoy and not dest_is_water:
                    queries.revert_transport(unit)
                # ------------------------------------------------------------

                # Only conquer if there are NO defenders from an enemy nation
                if not defenders:
                    if dest_owner == "Unclaimed" or dest_owner in player_data.get("at_war_with", []):
                        # Prevent capturing water tiles via movement
                        if not queries.is_water_province(target_prov):
                            capturer = unit["owner"]
                            # faction core transfer stuff
                            true_owner = queries.get_faction_core_transfer_target(capturer, target_prov, map_screen.nation_data)
                            edit_province_ownership.conquer_province(map_screen, target_prov, true_owner)

                # Stop if an enemy was present
                if defenders:
                    # Stop advancing for this turn, but DO NOT wipe the queue!
                    unit["_skip_remaining_steps"] = True 
            else:
                order["path"] = []

        # Sync units back to provinces so units moving later in the same sub-step "see" each other
        for unit in moving_units:
            prov = map_screen.id_to_province.get(unit["_current_province_id"])
            if not any(u is unit for u in prov["units"]): 
                prov["units"].append(unit)
                
        if step < max_speed - 1:
            # Create a set of memory IDs for ultra-fast lookup
            moving_ids = {id(m) for m in moving_units} 
            for province in map_screen.map_data.values():
                province["units"] = [u for u in province["units"] if id(u) not in moving_ids]

    # Clean up the temporary tracking flag so it doesn't pollute the save files!
    for unit in moving_units:
        if "_skip_remaining_steps" in unit:
            del unit["_skip_remaining_steps"]

def _find_nearest_owned_province(start_prov, owner, id_to_province):
    """BFS over the province graph for the closest tile owned by `owner`."""
    visited = {start_prov["id"]}
    queue = deque([start_prov["id"]])

    while queue:
        current_id = queue.popleft()
        prov = id_to_province.get(current_id)
        if not prov:
            continue

        for n_id in prov.get("neighbors", []):
            if n_id in visited:
                continue
            visited.add(n_id)

            n_prov = id_to_province.get(n_id)
            if not n_prov:
                continue
            if n_prov.get("owner") == owner:
                return n_prov
            queue.append(n_id)

    return None

def process_stranded_units(map_screen):
    """Exiles armies that end up occupying foreign soil without a legal right to be there.

    A unit can find itself standing in territory it no longer has any claim to enter
    (a ceasefire/peace is signed, access is revoked, a faction dissolves) since none of
    those events forcibly move units off the map. Rather than pathfinding a route home
    like a real retreat, we just teleport it to the nearest province it still owns,
    mirroring EU4-style "exiled army" handling.
    """
    unit_library = queries.get_unit_library()

    for province in list(map_screen.map_data.values()):
        owner = province.get("owner")
        if owner in c.UNPLAYABLE_NATIONS:
            continue

        units = province.get("units", [])
        if not units:
            continue

        stranded = []
        for unit in units:
            unit_owner = unit.get("owner")
            if not unit_owner or unit_owner == owner or unit_owner in c.UNPLAYABLE_NATIONS:
                continue

            # Naval units follow separate coastal-access rules; only land armies exile here.
            stats = unit_library.get(unit.get("type", ""), {})
            if unit.get("naval_unit") or stats.get("naval_unit", False):
                continue

            if queries.can_land_units_enter(unit_owner, province, map_screen.nation_data):
                continue  # legally present: at war, has access, or friendly territory

            stranded.append(unit)

        if not stranded:
            continue

        for unit in stranded:
            home_prov = _find_nearest_owned_province(province, unit["owner"], map_screen.id_to_province)
            if home_prov is None:
                continue  # nation holds no territory to return the unit to

            units.remove(unit)
            unit["_current_province_id"] = home_prov["id"]
            unit["_previous_province_id"] = home_prov["id"]
            order = unit.get("order")
            if isinstance(order, dict):
                order["path"] = []
            home_prov.setdefault("units", []).append(unit)