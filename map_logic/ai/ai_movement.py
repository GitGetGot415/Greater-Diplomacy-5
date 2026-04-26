import data.constants as c
from data import queries

def _bfs_nearest_target(start_id, target_ids, allowed_prov_ids, id_to_province, target_assignments):
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
            if n_id in target_ids:
                valid_paths.append(path + [n_id])
                if found_depth == -1:
                    found_depth = len(path)

            if n_id not in visited and n_id in allowed_prov_ids:
                visited.add(n_id)
                queue.append(path + [n_id])

    # Pick the path pointing to the target with the LEAST assignments, tie-breaking by distance.
    if valid_paths:
        best_path = min(valid_paths, key=lambda p: (target_assignments[p[-1]], len(p)))
        
        # If the best path is just staying where we are, return an empty array so we don't move
        if best_path[-1] == start_id:
            return []
            
        return best_path[1:]

    return []

def process_ai_unit_orders(map_screen):
    """Generates movement orders for AI-controlled units to balance borders or attack."""
    
    ai_nations = queries.get_active_ai_nations(map_screen)

    # Build a list of which units are where
    nation_units = {n: [] for n in ai_nations}
    nation_provs = {n: [] for n in ai_nations}

    for prov in map_screen.map_data.values():
        owner = prov.get("owner")
        if owner in ai_nations:
            nation_provs[owner].append(prov)
        for unit in prov.get("units", []):
            u_owner = unit.get("owner")
            if u_owner in ai_nations:
                # Clear old path so the AI can rethink its strategy every turn
                unit["order"] = {"type": "MOVE", "path": []}
                nation_units[u_owner].append((unit, prov))

    for ai_name in ai_nations:
        units_info = nation_units[ai_name]
        if not units_info:
            continue

        my_provs = nation_provs[ai_name]
        my_prov_ids = set(p["id"] for p in my_provs)
        enemies = map_screen.nation_data[ai_name].get("at_war_with", [])

        war_borders = set()
        peace_borders = set()
        enemy_targets = set()

        for prov in my_provs:
            is_war_border = False
            is_peace_border = False
            for n_id in prov.get("neighbors", []):
                n_prov = map_screen.id_to_province.get(n_id)
                if not n_prov: continue
                if n_prov.get("terrain") in c.WATER_TERRAINS: continue # Ignore water for basic land movement

                n_owner = n_prov.get("owner")
                if n_owner in enemies:
                    is_war_border = True
                    enemy_targets.add(n_id)
                elif n_owner != ai_name and n_owner not in c.WATER_NATIONS:
                    is_peace_border = True

            if is_war_border:
                war_borders.add(prov["id"])
            elif is_peace_border:
                peace_borders.add(prov["id"])

        at_war = len(enemies) > 0 and len(enemy_targets) > 0

        # Determine where units should be
        if at_war:
            target_destinations = list(enemy_targets)
        else:
            target_destinations = list(peace_borders)

        # If no targets (e.g. island with no neighbors), skip
        if not target_destinations:
            continue

        # Keep track of how many units are assigned to each target so we can spread them evenly
        target_assignments = {t_id: 0 for t_id in target_destinations}

        # Pre-count units already AT the targets so we don't over-assign
        for unit, prov in units_info:
            if prov["id"] in target_assignments:
                target_assignments[prov["id"]] += 1

        for unit, prov in units_info:
            u_type = unit.get("type", "")
            # Skip naval units for this basic land logic utilizing the cleaner query
            if queries.is_naval_unit(u_type):
                continue

            curr_id = prov["id"]

           # --- ANTI-SHUFFLE INTERCEPTS ---
            
            # --- NEW: Combat Lock (AI Check) ---
            in_combat = queries.is_nation_in_combat_here(ai_name, prov, map_screen.nation_data)
            
            # If the AI is currently engaged in active combat on its tile,
            # force it to hold the line. It cannot retreat or push forward blindly.
            if in_combat:
                continue
            # -----------------------------------
            
            # 1. Peacetime Anti-Shuffle
            # If we are holding a border and we are the ONLY unit here, hold the line.
            if not at_war and curr_id in target_assignments:
                if target_assignments[curr_id] <= 1:
                    continue # Skip BFS entirely, stay put
            
            # 2. Wartime Anti-Shuffle
            # If we are adjacent to the enemy, prioritize attacking them directly
            # instead of walking sideways down the border to balance numbers.
            if at_war:
                adjacent_targets = [n for n in prov.get("neighbors", []) if n in target_destinations]
                if adjacent_targets:
                    # Pick the adjacent enemy with the least attackers currently assigned
                    best_adj = min(adjacent_targets, key=lambda t: target_assignments[t])
                    
                    speed = unit.get("speed", 1)
                    unit["order"]["path"] = [best_adj] # Move directly into enemy territory
                    
                    target_assignments[best_adj] += 1
                    if curr_id in target_assignments:
                        target_assignments[curr_id] -= 1
                    continue # Skip BFS, we have our orders

            # --- END ANTI-SHUFFLE ---

            # Route to the nearest border/enemy that needs reinforcements
            path = _bfs_nearest_target(curr_id, set(target_destinations), my_prov_ids, map_screen.id_to_province, target_assignments)
            if path:
                # Truncate the AI's path to match its actual movement speed
                speed = unit.get("speed", 1)
                unit["order"]["path"] = path[:speed]
                
                # Tell the system this unit is taking this target, reducing its priority for the next unit
                if curr_id in target_assignments:
                    target_assignments[curr_id] -= 1
                target_assignments[path[-1]] += 1