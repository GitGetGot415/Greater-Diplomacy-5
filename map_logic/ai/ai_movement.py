import data.constants as c
from data import queries

def _bfs_nearest_target(start_id, target_ids, allowed_prov_ids, id_to_province, target_assignments, is_convoy=False, is_ship=False, moving_nation=None, nation_data=None):
    """Finds shortest path using BFS. Returns the path to the target with the least units assigned."""
    queue = [[start_id]]
    visited = set([start_id])
    valid_paths = []
    found_depth = -1

    # If already on a target, staying is evaluated as a valid option
    if start_id in target_ids:
        valid_paths.append([start_id])
        found_depth = 0

    while queue:
        path = queue.pop(0)

        # Allow BFS to search a few tiles deeper than the first found target 
        # so it can accurately discover empty borders further down the line.
        if found_depth != -1 and (len(path) - 1) > found_depth + 3:
            break

        curr = path[-1]
        prov = id_to_province.get(curr)
        if not prov: continue

        for n_id in prov.get("neighbors", []):
            n_prov = id_to_province.get(n_id)
            if not n_prov: continue
            
            # --- NEW CONVOY AND NAVAL BFS RULE ---
            if is_convoy or is_ship:
                curr_is_water = prov.get("terrain") in c.WATER_TERRAINS
                dest_is_water = n_prov.get("terrain") in c.WATER_TERRAINS
                
                if not curr_is_water and not dest_is_water:
                    continue # Convoys and Ships on land cannot move to another land tile
                    
                if is_ship and not dest_is_water:
                    # Ships can only enter friendly coastal tiles
                    if not queries.can_ships_enter(moving_nation, n_prov, nation_data):
                        continue
            # ---------------------------

            if n_id in target_ids:
                valid_paths.append(path + [n_id])
                if found_depth == -1:
                    found_depth = len(path)

            if n_id not in visited and n_id in allowed_prov_ids:
                visited.add(n_id)
                queue.append(path + [n_id])

    # Pick the path pointing to the target with the LEAST assignments, tie-breaking by distance.
    if valid_paths:
        best_path = min(valid_paths, key=lambda p: (target_assignments.get(p[-1], 0), len(p)))
        
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
        allowed_prov_ids = my_prov_ids.union(allowed_prov_ids_cache)
        
        enemies = map_screen.nation_data[ai_name].get("at_war_with", [])

        war_borders = set()
        peace_borders = set()
        coastal_borders = set()
        enemy_targets = set()
        all_enemy_coasts = set()
        enemy_coastal_waters = set()
        unclaimed_targets = set()
        all_unclaimed_coasts = set()

        # Locate coastal provinces globally for naval targeting and island hopping
        for prov in map_screen.map_data.values():
            if prov.get("is_coastal", False):
                owner = prov.get("owner", "Unclaimed")
                
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

        at_war = len(enemies) > 0 and (len(enemy_targets) > 0 or len(all_enemy_coasts) > 0)

        # --- FIX: UNIVERSAL TARGETS ---
        # ALWAYS include peace and coastal borders to prevent abandonment
        target_destinations = list(unclaimed_targets) + list(all_unclaimed_coasts) + list(peace_borders) + list(coastal_borders)

        if at_war:
            target_destinations += list(enemy_targets) + list(all_enemy_coasts)

        # If no targets (e.g. island with no neighbors), skip
        if not target_destinations:
            target_destinations = list(coastal_borders)
            if not target_destinations: continue

        # Keep track of how many units are assigned to each target so we can spread them evenly
        target_assignments = {t_id: 0 for t_id in target_destinations}
        
        friendly_convoys = set()
        for unit, prov in units_info:
            if unit.get("type", "").startswith("Convoy"):
                friendly_convoys.add(prov["id"])
                
        naval_destinations = list(enemy_coastal_waters) + list(friendly_convoys)
        naval_assignments = {t_id: 0 for t_id in naval_destinations}
        
        # Convoy Escort Priority
        # Apply a massive negative weight so warships heavily prioritize covering active convoys
        for c_id in friendly_convoys:
            if c_id in naval_assignments:
                naval_assignments[c_id] -= c.AI_CONVOY_ESCORT_WEIGHT

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

        for unit, prov in units_info:
            u_type = unit.get("type", "")
            is_convoy = u_type.startswith("Convoy")
            is_naval_combatant = queries.is_naval_unit(u_type) and not is_convoy

            curr_id = prov["id"]

           # --- ANTI-SHUFFLE INTERCEPTS ---
            
            in_combat = queries.is_nation_in_combat_here(ai_name, prov, map_screen.nation_data)
            
            # If the AI is currently engaged in active combat on its tile,
            # force it to hold the line. It cannot retreat or push forward blindly.
            if in_combat:
                continue
            
            # --- UNIVERSAL GARRISON FIX ---
            # If we are holding a defensive border (peace or coastal) and we are the ONLY unit here, HOLD THE LINE.
            # Do not apply this to war_borders because we WANT to push forward into enemy_targets.
            is_defensive_hold = (curr_id in peace_borders or curr_id in coastal_borders) and curr_id not in war_borders
            if not is_naval_combatant and is_defensive_hold:
                if target_assignments.get(curr_id, 0) <= 1:
                    continue # Skip Unclaimed Grab, skip Wartime Anti-Shuffle, skip BFS entirely. Stay put!
            # ------------------------------
            
            adjacent_unclaimed = [n for n in prov.get("neighbors", []) if n in unclaimed_targets]
            
            # PREVENT ILLEGAL CONVOY MOVES
            if is_convoy:
                adjacent_unclaimed = [n for n in adjacent_unclaimed if queries.can_convoy_enter(prov, map_screen.id_to_province.get(n))]

            if adjacent_unclaimed and not is_naval_combatant:
                best_adj = min(adjacent_unclaimed, key=lambda t: target_assignments.get(t, 0))
                
                speed = unit.get("speed", 1)
                unit["order"]["path"] = [best_adj] 
                
                target_assignments[best_adj] = target_assignments.get(best_adj, 0) + 1
                if curr_id in target_assignments:
                    target_assignments[curr_id] -= 1
                continue

            if at_war and not is_naval_combatant:
                adjacent_targets = [n for n in prov.get("neighbors", []) if n in target_destinations and n in enemy_targets]
                
                # PREVENT ILLEGAL CONVOY ATTACKS
                if is_convoy:
                    adjacent_targets = [n for n in adjacent_targets if queries.can_convoy_enter(prov, map_screen.id_to_province.get(n))]

                if adjacent_targets:
                    # Pick the adjacent enemy with the least attackers currently assigned
                    best_adj = min(adjacent_targets, key=lambda t: target_assignments.get(t, 0))
                    
                    speed = unit.get("speed", 1)
                    unit["order"]["path"] = [best_adj] 
                    
                    # --- THE FIX: Let fast units pathfind deeper from the border! ---
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
                                    if not queries.can_convoy_enter(curr_prov_data, n_prov):
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
                    # ----------------------------------------------------------------
                    
                    target_assignments[best_adj] = target_assignments.get(best_adj, 0) + 1
                    if curr_id in target_assignments:
                        target_assignments[curr_id] -= 1
                    continue 

            # --- END ANTI-SHUFFLE ---

            # Branch routing logic between ground forces and naval forces
            if is_naval_combatant:
                targets = naval_destinations
                assignments = naval_assignments
            else:
                targets = target_destinations
                assignments = target_assignments

            if not targets:
                continue

            # Route to the nearest border/enemy/coast/convoy that needs reinforcements
            path = _bfs_nearest_target(
                curr_id, 
                set(targets), 
                allowed_prov_ids, 
                map_screen.id_to_province, 
                assignments, 
                is_convoy=is_convoy, 
                is_ship=is_naval_combatant, 
                moving_nation=ai_name, 
                nation_data=map_screen.nation_data
            )

            if path:
                # --- NEW: Convoy Conversion Check ---
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
                
                # Tell the system this unit is taking this target, reducing its priority for the next unit
                if curr_id in assignments:
                    assignments[curr_id] -= 1
                if path[-1] in assignments:
                    assignments[path[-1]] += 1
    # --- NEW: Anti-Swap Cleanup ---
    # Cancel redundant moves where two identical AI units just swap places with each other.
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