# --- START OF FILE CHANGES ---
import heapq
import data.constants as c
from data import queries

def _bfs_nearest_target(start_id, target_ids, allowed_prov_ids, id_to_province, target_assignments, is_convoy=False, is_ship=False, moving_nation=None, nation_data=None, unsafe_waters=None, unit_speed=1.0):
    """Finds shortest path using Dijkstra. Returns the path to the target with the least units assigned."""
    if unsafe_waters is None:
        unsafe_waters = {}
        
    queue = [(0.0, 0, start_id, [start_id])]
    visited = {start_id: 0.0}
    valid_paths = []
    found_cost = -1.0
    counter = 1

    # If already on a target, staying is evaluated as a valid option
    if start_id in target_ids:
        valid_paths.append((0.0, [start_id]))
        found_cost = 0.0

    while queue:
        current_cost, _, curr, path = heapq.heappop(queue)

        # Allow search a few tiles deeper than the first found target 
        # so it can accurately discover empty borders further down the line.
        # DEPTH OF 10 SO AI CAN SEE FAR (Scaled by speed)
        if found_cost != -1.0 and current_cost > found_cost + (10.0 / max(1.0, float(unit_speed))):
            break

        prov = id_to_province.get(curr)
        if not prov: continue

        for n_id in prov.get("neighbors", []):
            n_prov = id_to_province.get(n_id)
            if not n_prov: continue
            
            # --- NEW CONVOY AND NAVAL BFS RULE ---
            curr_is_water = queries.is_water_province(prov)
            dest_is_water = queries.is_water_province(n_prov)
            
            if is_convoy or is_ship:
                if not curr_is_water and not dest_is_water:
                    continue # Convoys and Ships on land cannot move to another land tile
                    
                if is_ship and not dest_is_water:
                    # Ships can only enter friendly coastal tiles
                    if not queries.can_ships_enter(moving_nation, n_prov, nation_data):
                        continue
                        
                if is_convoy and not dest_is_water:
                    # Convoys landing must obey land border rules
                    if not queries.can_land_units_enter(moving_nation, n_prov, nation_data):
                        continue

            # --- NEW: Cost Calculation for Dijkstra ---
            if dest_is_water and not is_ship:
                # Land unit moving over water (Convoy) applies the 2x sea penalty
                step_cost = 1.0 * c.AI_SEA_PATH_PENALTY_MULTIPLIER
            else:
                # Land unit moving over land, or ship moving over water
                step_cost = 1.0 / max(1.0, float(unit_speed)) if not is_ship else 1.0

            new_cost = current_cost + step_cost

            # --- BLOCK SUICIDE PATHS ---

            if n_id in target_ids:
                valid_paths.append((new_cost, path + [n_id]))
                if found_cost == -1.0:
                    found_cost = new_cost

            if n_id in allowed_prov_ids and (n_id not in visited or new_cost < visited[n_id]):
                visited[n_id] = new_cost
                heapq.heappush(queue, (new_cost, counter, n_id, path + [n_id]))
                counter += 1

    # Pick the path pointing to the target with the LEAST assignments, tie-breaking by cost.
    if valid_paths:
        best_path_tuple = min(valid_paths, key=lambda p: (target_assignments.get(p[1][-1], 0), p[0]))
        best_path = best_path_tuple[1]
        
        # If the best path is just staying where we are, return an empty array so we don't move
        if best_path[-1] == start_id:
            return []
            
        return best_path[1:]

    return []

def process_ai_unit_orders(map_screen):
    """Generates movement orders for AI-controlled units to balance borders, attack, or escort."""
    
    ai_nations = queries.get_active_ai_nations(map_screen)

    # Build a list of which units are where
    nation_units = {}
    nation_provs = {}

    # --- NEW: Pre-calculate allowed pathing IDs to include water for convoys ---
    allowed_prov_ids_cache = set()
    for prov in map_screen.map_data.values():
        if prov.get("terrain") in c.WATER_TERRAINS:
            allowed_prov_ids_cache.add(prov["id"])

    for ai_name in ai_nations:
        provs, units = queries.get_nation_provinces_and_units(ai_name, map_screen.map_data)
        nation_provs[ai_name] = provs
        nation_units[ai_name] = []
        
        for unit, prov in units:
            # Clear old path so the AI can rethink its strategy every turn
            unit["order"] = {"type": "MOVE", "path": []}
            nation_units[ai_name].append((unit, prov))

    for ai_name in ai_nations:
        units_info = nation_units[ai_name]
        if not units_info:
            continue

        my_provs = nation_provs[ai_name]
        my_prov_ids = set(p["id"] for p in my_provs)
        
        # Combine land and water IDs so BFS can route overseas
        # Include ALL legally passable tiles so the AI isn't blind!
        allowed_prov_ids = set(allowed_prov_ids_cache)
        for p in map_screen.map_data.values():
            if queries.can_land_units_enter(ai_name, p, map_screen.nation_data):
                allowed_prov_ids.add(p["id"])
        
        enemies = map_screen.nation_data[ai_name].get("at_war_with", [])

        # --- NEW: IDENTIFY UNSAFE WATERS FOR NAVAL SURVIVAL ---
        # Pre-calculates areas heavily patrolled by enemies so Convoys and weak ships don't suicide
        unsafe_waters = {}
        for p in map_screen.map_data.values():
            if p.get("terrain") in c.WATER_TERRAINS:
                enemy_str = sum(u.get("attack", c.DEFAULT_UNIT_ATK) + u.get("defense", 0) for u in p.get("units", []) 
                                if queries.are_at_war(ai_name, u.get("owner"), map_screen.nation_data) 
                                and queries.is_naval_unit(u.get("type", "")))
                if enemy_str > 0:
                    unsafe_waters[p["id"]] = enemy_str
        # ------------------------------------------------------

        # --- Identify Friendly Nations for Expedition Logic ---
        friendly_nations = {ai_name}
        my_faction = map_screen.nation_data[ai_name].get("faction", "")
        if my_faction:
            friendly_nations.update(queries.get_faction_members(my_faction, map_screen.nation_data))
        friendly_nations.update(map_screen.nation_data[ai_name].get("allied_with", []))

        war_borders = set()
        peace_borders = set()
        coastal_borders = set()
        enemy_targets = set()
        all_enemy_coasts = set()
        enemy_coastal_waters = set()
        unclaimed_targets = set()
        all_unclaimed_coasts = set()
        active_battles = set() 
        expedition_targets = set()

        # Locate coastal provinces globally for naval targeting and island hopping
        for prov in map_screen.map_data.values():
            owner = prov.get("owner", "Unclaimed")
            
            if prov.get("is_coastal", False):
                if enemies and owner in enemies:
                    all_enemy_coasts.add(prov["id"])
                    
                    # Find adjacent water tiles for ships to blockade from
                    for n_id in prov.get("neighbors", []):
                        n_prov = map_screen.id_to_province.get(n_id)
                        if n_prov and n_prov.get("terrain") in c.WATER_TERRAINS:
                            enemy_coastal_waters.add(n_id)
                            
                # Identify unclaimed islands globally
                elif owner in ["Unclaimed", "None", ""]:
                    all_unclaimed_coasts.add(prov["id"])

            # --- Distant Allied Wars / Expedition Targets ---
            if enemies:
                # 1. Reinforce allied battles
                if queries.is_province_in_active_combat(prov, map_screen.nation_data):
                    units_here = prov.get("units", [])
                    if any(u.get("owner") in friendly_nations for u in units_here):
                        expedition_targets.add(prov["id"])

                # 2. Reinforce allied borders touching mutual enemies
                if owner in enemies:
                    for n_id in prov.get("neighbors", []):
                        n_prov = map_screen.id_to_province.get(n_id)
                        if n_prov and n_prov.get("owner") in friendly_nations and n_prov.get("owner") != ai_name:
                            expedition_targets.add(prov["id"])
                            break

        for prov in my_provs:
            is_war_border = False
            is_peace_border = False
            is_coastal = prov.get("is_coastal", False)

            for n_id in prov.get("neighbors", []):
                n_prov = map_screen.id_to_province.get(n_id)
                if not n_prov: continue
                if n_prov.get("terrain") in c.WATER_TERRAINS: continue 

                n_owner = n_prov.get("owner", "Unclaimed") 
                if n_owner in enemies:
                    is_war_border = True
                    enemy_targets.add(n_id)
                elif n_owner in ["Unclaimed", "None", ""]: 
                    unclaimed_targets.add(n_id)
                elif n_owner != ai_name and n_owner not in c.WATER_NATIONS and not queries.are_in_same_faction(ai_name, n_owner, map_screen.nation_data):
                    is_peace_border = True

            if is_war_border:
                war_borders.add(prov["id"])
            elif is_peace_border:
                peace_borders.add(prov["id"])
            elif is_coastal:
                coastal_borders.add(prov["id"])

        at_war = len(enemies) > 0 and (len(enemy_targets) > 0 or len(all_enemy_coasts) > 0 or len(expedition_targets) > 0)

        # --- FIND ACTIVE BATTLES, RETREATS & CONVOY STATUS ---
        friendly_convoys = set()
        convoy_in_combat = set()
        convoy_near_ship = set()
        convoy_near_coast = set()

        lost_battles = {} # prov_id -> safe_retreat_id

        for unit, prov in units_info:
            p_id = prov["id"]
            if queries.is_nation_in_combat_here(ai_name, prov, map_screen.nation_data):
                if p_id not in active_battles and p_id not in lost_battles:
                    
                    # Evaluate if the AI will lose this battle on the next turn
                    my_units = [u for u in prov.get("units", []) if u.get("owner") in friendly_nations]
                    enemy_units = [u for u in prov.get("units", []) if queries.are_at_war(ai_name, u.get("owner"), map_screen.nation_data)]
                    
                    total_enemy_atk = sum(u.get("attack", c.DEFAULT_UNIT_ATK) for u in enemy_units)
                    
                    all_will_die = True
                    if my_units and enemy_units:
                        dmg_per_unit = total_enemy_atk / len(my_units)
                        for u in my_units:
                            if max(0, dmg_per_unit - u.get("defense", c.DEFAULT_UNIT_DEF)) < u.get("health", 1):
                                all_will_die = False
                                break
                    else:
                        all_will_die = False
                        
                    if all_will_die:
                        # Find a safe retreat target for the group
                        safe_retreats = []
                        for n_id in prov.get("neighbors", []):
                            if n_id in unsafe_waters: continue
                            n_prov = map_screen.id_to_province.get(n_id)
                            if not n_prov: continue
                            n_owner = n_prov.get("owner", "Unclaimed")
                            if not queries.is_hostile_territory(ai_name, n_owner, map_screen.nation_data):
                                safe_retreats.append(n_id)
                                
                        if safe_retreats:
                            # Prioritize friendly territory
                            best_retreat = safe_retreats[0]
                            for r_id in safe_retreats:
                                if map_screen.id_to_province[r_id].get("owner") in friendly_nations:
                                    best_retreat = r_id
                                    break
                            lost_battles[p_id] = best_retreat
                        else:
                            active_battles.add(p_id) # Nowhere to run, fight to the death
                    else:
                        active_battles.add(p_id)
                
            if unit.get("type", "").startswith("Convoy"):
                friendly_convoys.add(p_id)
                # Escort AI: Determine how much danger the convoy is in
                if queries.is_nation_in_combat_here(ai_name, prov, map_screen.nation_data):
                    convoy_in_combat.add(p_id)
                else:
                    near_ship = False
                    near_coast = False
                    for n_id in prov.get("neighbors", []):
                        if n_id in unsafe_waters:
                            near_ship = True
                        elif n_id in all_enemy_coasts or n_id in enemy_coastal_waters:
                            near_coast = True
                            
                    if near_ship:
                        convoy_near_ship.add(p_id)
                    elif near_coast:
                        convoy_near_coast.add(p_id)

        # --- FIX: UNIVERSAL TARGETS ---
        # ALWAYS include peace and coastal borders to prevent abandonment
        target_destinations = list(set(list(unclaimed_targets) + list(all_unclaimed_coasts) + list(peace_borders) + list(coastal_borders) + list(active_battles)))

        if at_war:
            # Inject expedition_targets so distant armies mobilize!
            target_destinations = list(set(target_destinations + list(enemy_targets) + list(all_enemy_coasts) + list(expedition_targets)))

        # If no targets (e.g. island with no neighbors), skip
        if not target_destinations:
            target_destinations = list(coastal_borders)
            if not target_destinations: continue

        # Keep track of how many units are assigned to each target so we can spread them evenly
        target_assignments = {t_id: 0 for t_id in target_destinations}
        
        naval_destinations = list(set(list(enemy_coastal_waters) + list(friendly_convoys)))
        naval_assignments = {t_id: 0 for t_id in naval_destinations}
        
        # Convoy Escort Priority
        # Apply massive negative weights so warships heavily prioritize covering active convoys
        for c_id in friendly_convoys:
            if c_id in naval_assignments:
                naval_assignments[c_id] -= c.AI_CONVOY_ESCORT_WEIGHT
                if c_id in convoy_in_combat:
                    naval_assignments[c_id] -= c.AI_CONVOY_COMBAT_WEIGHT
                elif c_id in convoy_near_ship:
                    naval_assignments[c_id] -= c.AI_CONVOY_DANGER_SHIP_WEIGHT
                elif c_id in convoy_near_coast:
                    naval_assignments[c_id] -= c.AI_CONVOY_DANGER_COAST_WEIGHT

        # Active Battle Reinforcement Priority
        for b_id in active_battles:
            if b_id in target_assignments:
                target_assignments[b_id] -= c.AI_REINFORCE_COMBAT_WEIGHT

        # Pre-count units already AT the targets
        for unit, prov in units_info:
            if prov["id"] in target_assignments:
                target_assignments[prov["id"]] += 1
            if prov["id"] in naval_assignments:
                naval_assignments[prov["id"]] += 1

        # --- STRATEGIC WEIGHTING FIX ---
        # 1. Coasts are low priority. Inflate their count so units prefer land borders.
        for c_id in coastal_borders:
            if c_id in target_assignments and c_id not in peace_borders and c_id not in war_borders:
                target_assignments[c_id] += 1
                
        # 2. Push the main army to the frontlines! Only keep 1 guard per peace/coastal border during war or expansion.
        if at_war or unclaimed_targets:
            for p_id in peace_borders:
                if target_assignments.get(p_id, 0) >= 1:
                    target_assignments[p_id] += 50
            for c_id in coastal_borders:
                if target_assignments.get(c_id, 0) >= 1:
                    target_assignments[c_id] += 50

        # 3. Penalize expedition targets so the AI defends its homeland fronts FIRST.
        for e_id in expedition_targets:
            if e_id in target_assignments and e_id not in enemy_targets and e_id not in war_borders:
                target_assignments[e_id] += c.AI_EXPEDITION_WEIGHT

        for unit, prov in units_info:
            u_type = unit.get("type", "")
            is_convoy = u_type.startswith("Convoy")
            is_naval_combatant = queries.is_naval_unit(u_type) and not is_convoy

            curr_id = prov["id"]

            # --- NEW: GROUP RETREAT FROM LOST BATTLES ---
            if curr_id in lost_battles:
                retreat_target = lost_battles[curr_id]
                n_prov = map_screen.id_to_province.get(retreat_target)
                if n_prov:
                    can_retreat = False
                    if is_convoy and queries.can_convoy_enter(prov, n_prov): can_retreat = True
                    elif is_naval_combatant and (n_prov.get("terrain") in c.WATER_TERRAINS or queries.can_ships_enter(ai_name, n_prov, map_screen.nation_data)): can_retreat = True
                    elif not is_naval_combatant and not is_convoy and queries.can_land_units_enter(unit["owner"], n_prov, map_screen.nation_data): can_retreat = True
                    
                    if can_retreat:
                        unit["order"]["path"] = [retreat_target]
                        continue
            # --------------------------------------------

            # --- ANTI-SHUFFLE & COMBAT INTERCEPTS ---
            in_combat = queries.is_nation_in_combat_here(ai_name, prov, map_screen.nation_data)
            
            # If the AI is currently engaged in active combat on its tile...
            if in_combat:
                # Check if we are hopelessly outmatched and should pull our ships/convoys out
                my_str = sum(u.get("attack", c.DEFAULT_UNIT_ATK) + u.get("defense", 0) for u in prov.get("units", []) if u.get("owner") in friendly_nations)
                enemy_str = sum(u.get("attack", c.DEFAULT_UNIT_ATK) + u.get("defense", 0) for u in prov.get("units", []) if queries.are_at_war(ai_name, u.get("owner"), map_screen.nation_data))
                
                # If Navy is outnumbered 1.5-to-1, or if a Convoy is literally fighting ANY warship
                if (is_naval_combatant and enemy_str > my_str * 1.5) or (is_convoy and enemy_str > 0):
                    safe_retreats = []
                    for n_id in prov.get("neighbors", []):
                        if n_id in unsafe_waters: continue # Don't retreat into ANOTHER enemy fleet
                        n_prov = map_screen.id_to_province.get(n_id)
                        if not n_prov: continue
                        
                        if is_convoy and queries.can_convoy_enter(prov, n_prov):
                            safe_retreats.append(n_id)
                        elif is_naval_combatant and (n_prov.get("terrain") in c.WATER_TERRAINS or queries.can_ships_enter(ai_name, n_prov, map_screen.nation_data)):
                            safe_retreats.append(n_id)
                    
                    if safe_retreats:
                        unit["order"]["path"] = [safe_retreats[0]]
                        continue # Successfully ordered retreat, skip normal BFS
                # -----------------------------------
                continue # Otherwise, hold the line and fight!
            
            # If we are holding a defensive border (peace or coastal) and we are the ONLY unit here, HOLD THE LINE.
            # Do not apply this to war_borders because we WANT to push forward into enemy_targets.
            is_defensive_hold = (curr_id in peace_borders or curr_id in coastal_borders) and curr_id not in war_borders
            
            # Break the hold if there's an active battle literally 1 tile away!
            is_near_battle = any(n in active_battles for n in prov.get("neighbors", []))
            if is_near_battle:
                is_defensive_hold = False

            if not is_naval_combatant and is_defensive_hold:
                if target_assignments.get(curr_id, 0) <= 1:
                    continue # Stay put!
            
            adjacent_unclaimed = [n for n in prov.get("neighbors", []) if n in unclaimed_targets]
            
            # PREVENT ILLEGAL CONVOY MOVES
            if is_convoy:
                adjacent_unclaimed = [n for n in adjacent_unclaimed if queries.can_convoy_enter(prov, map_screen.id_to_province.get(n)) and n not in unsafe_waters]

            if adjacent_unclaimed and not is_naval_combatant:
                best_adj = min(adjacent_unclaimed, key=lambda t: target_assignments.get(t, 0))
                
                speed = unit.get("speed", 1)
                unit["order"]["path"] = [best_adj] 
                
                # Let fast units pathfind deeper into unclaimed territory!
                if speed > 1:
                    curr_node = best_adj
                    for _ in range(speed - 1):
                        curr_prov_data = map_screen.id_to_province.get(curr_node)
                        if not curr_prov_data: break
                        
                        next_options = []
                        for n_id in curr_prov_data.get("neighbors", []):
                            n_prov = map_screen.id_to_province.get(n_id)
                            if not n_prov: continue
                            
                            # Prevent backtracking
                            if n_id in unit["order"]["path"] or n_id == curr_id:
                                continue
                                
                            # Obey movement rules using constants
                            if is_convoy:
                                if not queries.can_convoy_enter(curr_prov_data, n_prov) or n_id in unsafe_waters:
                                    continue
                            else:
                                if n_prov.get("terrain") in c.WATER_TERRAINS:
                                    continue
                                    
                            # Check if it's a valid tile to push into
                            n_owner = n_prov.get("owner", "Unclaimed")
                            if n_owner in ["Unclaimed", "None", ""]:
                                next_options.append(n_id)
                                
                        if next_options:
                            # Pick the adjacent unclaimed tile with the least attackers to spread the expansion
                            next_step = min(next_options, key=lambda t: target_assignments.get(t, 0))
                            unit["order"]["path"].append(next_step)
                            target_assignments[next_step] = target_assignments.get(next_step, 0) + 1
                            curr_node = next_step
                        else:
                            # Reached a dead end (e.g. hit an ocean or claimed border)
                            break
                # -----------------------------------------------------------------------

                target_assignments[best_adj] = target_assignments.get(best_adj, 0) + 1
                if curr_id in target_assignments:
                    target_assignments[curr_id] -= 1
                continue 

            if at_war and not is_naval_combatant:
                # Include expedition targets in the adjacent strike check so they can push off allied territory
                adjacent_targets = [n for n in prov.get("neighbors", []) if n in target_destinations and (n in enemy_targets or n in expedition_targets)]
                
                # PREVENT ILLEGAL CONVOY ATTACKS
                if is_convoy:
                    adjacent_targets = [n for n in adjacent_targets if queries.can_convoy_enter(prov, map_screen.id_to_province.get(n)) and n not in unsafe_waters]

                if adjacent_targets:
                    # Pick the adjacent enemy with the least attackers currently assigned
                    best_adj = min(adjacent_targets, key=lambda t: target_assignments.get(t, 0))
                    
                    speed = unit.get("speed", 1)
                    unit["order"]["path"] = [best_adj] 
                    
                    # Let fast units pathfind deeper from the border!
                    if speed > 1:
                        curr_node = best_adj
                        for _ in range(speed - 1):
                            curr_prov_data = map_screen.id_to_province.get(curr_node)
                            if not curr_prov_data: break
                            
                            next_options = []
                            for n_id in curr_prov_data.get("neighbors", []):
                                n_prov = map_screen.id_to_province.get(n_id)
                                if not n_prov: continue
                                
                                # Prevent backtracking
                                if n_id in unit["order"]["path"] or n_id == curr_id:
                                    continue
                                
                                # Obey movement rules using your constants/queries
                                if is_convoy:
                                    if not queries.can_convoy_enter(curr_prov_data, n_prov) or n_id in unsafe_waters:
                                        continue
                                else:
                                    if n_prov.get("terrain") in c.WATER_TERRAINS:
                                        continue
                                
                                # Check if it's a valid tile to push into
                                n_owner = n_prov.get("owner", "Unclaimed")
                                if queries.is_hostile_territory(ai_name, n_owner, map_screen.nation_data) or n_owner in ["Unclaimed", "None", ""]:
                                    next_options.append(n_id)
                            
                            if next_options:
                                # Pick the adjacent hostile tile with the least attackers to spread the invasion
                                next_step = min(next_options, key=lambda t: target_assignments.get(t, 0))
                                unit["order"]["path"].append(next_step)
                                target_assignments[next_step] = target_assignments.get(next_step, 0) + 1
                                curr_node = next_step
                            else:
                                # Reached a dead end (e.g. hit an ocean or friendly border)
                                break
                    
                    target_assignments[best_adj] = target_assignments.get(best_adj, 0) + 1
                    if curr_id in target_assignments:
                        target_assignments[curr_id] -= 1
                    continue 

            # Branch routing logic between ground forces and naval forces
            if is_naval_combatant:
                targets = naval_destinations
                assignments = naval_assignments
            else:
                targets = target_destinations
                assignments = target_assignments

            if not targets:
                continue

            # Bypass the depth limiter for fully garrisoned borders
            # Filter out targets that have the +50 "fully garrisoned" penalty applied
            priority_targets = [t for t in targets if assignments.get(t, 0) < 50]
            search_targets = priority_targets if priority_targets else targets

            # Route to the nearest border/enemy/coast/convoy that needs reinforcements
            path = _bfs_nearest_target(
                curr_id, 
                set(search_targets), 
                allowed_prov_ids, 
                map_screen.id_to_province, 
                assignments, 
                is_convoy=is_convoy, 
                is_ship=is_naval_combatant, 
                moving_nation=ai_name, 
                nation_data=map_screen.nation_data,
                unsafe_waters=unsafe_waters,
                unit_speed=unit.get("speed", 1)
            )

            if path:
                # Convoy Conversion Check
                next_prov = map_screen.id_to_province.get(path[0])
                next_is_water = next_prov.get("terrain") in c.WATER_TERRAINS
                
                if next_is_water and not is_convoy and not is_naval_combatant:
                    # Cannot step onto water, must explicitly convert first
                    unit["order"] = {"type": "CONVERT", "turns_left": 1, "to": "Convoy"}
                else:
                    # Truncate the AI's path to match its actual movement speed
                    speed = unit.get("speed", 1)
                    
                    # PREVENT LAND UNITS QUEUEING INTO OCEAN MID-MOVE
                    final_path = []
                    for step_id in path[:speed]:
                        step_prov = map_screen.id_to_province.get(step_id)
                        if not is_convoy and not is_naval_combatant and step_prov and step_prov.get("terrain") in c.WATER_TERRAINS:
                            break 
                        final_path.append(step_id)

                    unit["order"]["path"] = final_path
                
                # Tell the system this unit is taking this target, reducing its priority
                if curr_id in assignments:
                    assignments[curr_id] -= 1
                if path[-1] in assignments:
                    assignments[path[-1]] += 1
                    
    # --- Anti-Swap Cleanup ---
    for ai_name in ai_nations:
        units_info = nation_units[ai_name]
        
        # Track where every unit is trying to go for this specific nation
        transitions = {}
        for unit, prov in units_info:
            path = unit.get("order", {}).get("path", [])
            if path:
                src_id = prov["id"]
                dest_id = path[0]
                transitions.setdefault((src_id, dest_id), []).append(unit)
        
        # Check for opposing traffic
        processed = set()
        for (src, dest), fwd_units in transitions.items():
            if (src, dest) in processed: continue
            
            bwd_units = transitions.get((dest, src), [])
            if bwd_units:
                # Match up identical unit types AND health
                fwd_types = {}
                for u in fwd_units:
                    # Using int() on health prevents floating point mismatch errors
                    key = (u.get("type", ""), int(u.get("health", 0)))
                    fwd_types.setdefault(key, []).append(u)
                    
                bwd_types = {}
                for u in bwd_units:
                    key = (u.get("type", ""), int(u.get("health", 0)))
                    bwd_types.setdefault(key, []).append(u)
                    
                # Cancel pairs of identical units
                for u_key, f_list in fwd_types.items():
                    b_list = bwd_types.get(u_key, [])
                    cancel_count = min(len(f_list), len(b_list))
                    
                    for i in range(cancel_count):
                        f_list[i]["order"]["path"] = []
                        b_list[i]["order"]["path"] = []
                        
            processed.add((src, dest))
            processed.add((dest, src))