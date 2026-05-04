import random
import os
import json
import data.constants as c
from data import queries

def randomize_all_provinces(map_screen, settings):
    target_country_count = settings["countries"]
    start_year = settings["year"]

    playable_nations = [
        name for name, stats in map_screen.nation_data.items()
        if queries.is_playable(name, map_screen.nation_data)
    ]
    
    land_provinces = [p for p in map_screen.map_data.values() if p.get("terrain", "") not in c.WATER_TERRAINS]
    
    if not land_provinces or not playable_nations: return

    # Wipe existing map data clean
    for prov in land_provinces:
        prov.update({"owner": "Unclaimed", "cores": [], "resources": {}, "buildings": [], "units": []})

    # --- Step 1: Island Filtering (Connected Components) ---
    # We find all landmasses and only keep those with 4 or more connected provinces.
    valid_land_provinces = []
    visited = set()
    land_ids = set(p["id"] for p in land_provinces)

    for prov in land_provinces:
        if prov["id"] in visited: continue
        comp = []
        queue = [prov["id"]]
        visited.add(prov["id"])

        while queue:
            curr_id = queue.pop(0)
            curr_prov = map_screen.id_to_province[curr_id]
            comp.append(curr_prov)

            for n_id in curr_prov.get("neighbors", []):
                if n_id in land_ids and n_id not in visited:
                    visited.add(n_id)
                    queue.append(n_id)

        if len(comp) >= 4:
            valid_land_provinces.extend(comp)
            
    if not valid_land_provinces: return

    import random
    random.shuffle(playable_nations)
    
    # 1. Adjust country count to not exceed available valid provinces
    num_seeds = min(target_country_count, len(valid_land_provinces))
    active_nations = playable_nations[:num_seeds]
    
    unassigned_land = set(p["id"] for p in valid_land_provinces)
    frontiers = {nation: [] for nation in active_nations}
    
    # --- Step A: Plant Seeds ---
    for nation in active_nations:
        seed_id = random.choice(list(unassigned_land))
        seed_prov = map_screen.id_to_province[seed_id]
        
        seed_prov["owner"] = nation
        seed_prov["cores"] = [nation]
        unassigned_land.remove(seed_id)
        
        for n_id in seed_prov.get("neighbors", []):
            if n_id in unassigned_land: frontiers[nation].append(n_id)

    # --- Step B: Round-Robin Expansion (Ensures Even Sizes) ---
    while unassigned_land:
        expanded_this_round = False
        for nation in active_nations:
            frontier_list = [pid for pid in frontiers[nation] if pid in unassigned_land]
            frontiers[nation] = frontier_list
            
            if frontier_list:
                target_id = frontier_list.pop(random.randint(0, len(frontier_list) - 1))
                target_prov = map_screen.id_to_province[target_id]
                
                target_prov["owner"] = nation
                target_prov["cores"] = [nation]
                unassigned_land.remove(target_id)
                expanded_this_round = True
                
                for n_id in target_prov.get("neighbors", []):
                    if n_id in unassigned_land: frontier_list.append(n_id)
        
        # Walled off island catch
        if not expanded_this_round and unassigned_land:
            target_id = random.choice(list(unassigned_land))
            nation = random.choice(active_nations)
            map_screen.id_to_province[target_id]["owner"] = nation
            map_screen.id_to_province[target_id]["cores"] = [nation]
            unassigned_land.remove(target_id)
            for n_id in map_screen.id_to_province[target_id].get("neighbors", []):
                if n_id in unassigned_land: frontiers[nation].append(n_id)

    # --- Step B.5: Assign Bordering Cores ---
    for nation in active_nations:
        # Get all land provinces this nation ended up owning
        owned_provs = [p for p in valid_land_provinces if p.get("owner") == nation]
        
        for prov in owned_provs:
            # Check every neighbor of the owned province
            for n_id in prov.get("neighbors", []):
                n_prov = map_screen.id_to_province.get(n_id)
                
                if n_prov:
                    # Ignore water tiles
                    if n_prov.get("terrain", "") in c.WATER_TERRAINS:
                        continue
                    
                    # If this neighbor belongs to someone else (or is unclaimed)
                    if n_prov.get("owner") != nation:
                        # Add a core for our nation if it doesn't have one already
                        if nation not in n_prov.setdefault("cores", []):
                            n_prov["cores"].append(nation)

    # --- Step C: Tech & Building Assignment ---
    
    # 1. Load the full baseline template so nobody is missing keys
    template_path = c.RESEARCH_TEMPLATE_PATH
    res_template = {}
    struct = {} # Store the struct to read the years later
    if os.path.exists(template_path):
        with open(template_path, "r") as f:
            struct = json.load(f)
            res_template = {tech: 0 for tech in struct.keys()}
            if "infantry_type" in res_template: res_template["infantry_type"] = 1
            if "cavalry" in res_template: res_template["cavalry"] = 1

    # Dynamically read years from the loaded JSON struct
    tech_timeline = {tech: data.get("years", [1850]) for tech, data in struct.items()}
    
    # Calculate what tech levels everyone gets based on the Start Year
    baseline_tech = {}
    for tech, years in tech_timeline.items():
        lvl = sum(1 for y in years if y <= start_year)
        if lvl > 0: baseline_tech[tech] = lvl

    # Apply base tech to all active nations
    for nation in active_nations:
        if "research" not in map_screen.nation_data[nation]:
            map_screen.nation_data[nation]["research"] = {}
        
        # First, lay down the foundational template so every key exists
        for k, v in res_template.items():
            if k not in map_screen.nation_data[nation]["research"]:
                map_screen.nation_data[nation]["research"][k] = v
        
        # Then, overwrite with the calculated timeline tech levels
        map_screen.nation_data[nation]["research"].update(baseline_tech)

    # Determine which buildings are legally allowed to spawn based on tech
    allowed_factories = []
    if baseline_tech.get("basic_factory", 0) > 0:
        allowed_factories.append(c.DEFAULT_STARTING_FACTORY)
        
    fac_lvl = baseline_tech.get("factory", 0)
    for lvl in range(1, fac_lvl + 1):
        allowed_factories.append(f"Factory Lvl {lvl}")

    allowed_refineries = []
    if baseline_tech.get("synthetic_fuel_experiments", 0) > 0:
        allowed_refineries.append(c.DEFAULT_STARTING_REFINERY)
        
    ref_lvl = baseline_tech.get("fuel_refining", 0)
    for lvl in range(1, ref_lvl + 1):
        allowed_refineries.append(f"Synthetic Refinery Lvl {lvl}")

    allowed_recruitment = []
    if baseline_tech.get("basic_recruitment", 0) > 0:
        allowed_recruitment.append("Basic Recruitment Center")
        
    rec_lvl = baseline_tech.get("recruitment_buildings", 0)
    for lvl in range(1, rec_lvl + 1):
        allowed_recruitment.append(f"Recruitment Building Lvl {lvl}")

    # Give out random resources and buildings
    for prov in valid_land_provinces:
        if random.random() < 0.15:
            res_type = random.choice(["Iron", "Coal", "Oil"])
            prov["resources"] = {res_type: random.randint(20, 80)}
            
        prov.setdefault("buildings", [])
        has_factory = False
        
        if allowed_factories and random.random() < 0.10:
            fac = random.choice(allowed_factories)
            prov["buildings"].append(fac)
            if "Basic Factory" in fac or "Factory Lvl" in fac:
                has_factory = True
            
        # Guarantee refineries/recruitment centers only spawn where basic factories exist
        if has_factory:
            if allowed_refineries and random.random() < 0.30:
                prov["buildings"].append(random.choice(allowed_refineries))
            if allowed_recruitment and random.random() < 0.30:
                prov["buildings"].append(random.choice(allowed_recruitment))

    # --- Step D: Guarantee Minimum Buildings ---
    for nation in active_nations:
        owned_provs = [p for p in valid_land_provinces if p["owner"] == nation]
        if not owned_provs: continue

        has_factory = False
        refinery_provs = []

        for prov in owned_provs:
            bldgs = prov.get("buildings", [])
            
            # Check if province contains an industrial building
            if any("Factory" in b for b in bldgs):
                has_factory = True
                
            if any("Refinery" in b for b in bldgs):
                refinery_provs.append(prov)
        
        # If the nation randomly got zero factories, guarantee them one
        if not has_factory:
            # Safely prioritize merging it with an existing refinery to save map space
            target_prov = random.choice(refinery_provs) if refinery_provs else random.choice(owned_provs)
            bldg_to_add = random.choice(allowed_factories) if allowed_factories else c.DEFAULT_STARTING_FACTORY
            target_prov.setdefault("buildings", []).append(bldg_to_add)

    # --- Step E: Generate Starting Armies & Spread Across Borders ---
    unit_library = queries.get_unit_library()
    tech_tree = queries.get_tech_tree()

    # Calculate starting economy so we can budget the starting armies
    all_econ = queries.calculate_all_economies(map_screen.map_data, map_screen.nation_data)

    # Helper to generate a fresh unit dictionary so pointers aren't shared across provinces
    def generate_unit(nation, u_name):
        stats = unit_library.get(u_name, {})
        return {
            "type": u_name,
            "owner": nation,
            "health": stats.get("health", c.DEFAULT_UNIT_HP),
            "max_health": stats.get("health", c.DEFAULT_UNIT_HP),
            "speed": stats.get("speed", c.DEFAULT_UNIT_SPD),
            "attack": stats.get("attack", c.DEFAULT_UNIT_ATK),
            "defense": stats.get("defense", c.DEFAULT_UNIT_DEF),
            "level": 0,
            "order": {"type": "MOVE", "path": []}
        }

    for nation in active_nations:
        owned_provs = [p for p in valid_land_provinces if p["owner"] == nation]
        if not owned_provs: continue

        data = map_screen.nation_data[nation]
        econ = all_econ.get(nation)
        if not econ: continue

        # 1. Establish the Budget
        inc_man = econ["total_inc"]["manpower"]
        inc_mat = econ["total_inc"]["materials"]
        inc_fuel = econ["total_inc"]["fuel"]

        target_man = inc_man * getattr(c, 'AI_UPKEEP_TARGETS', {"manpower": 0.60}).get("manpower", 0.60)
        target_mat = inc_mat * getattr(c, 'AI_UPKEEP_TARGETS', {"materials": 0.40}).get("materials", 0.40)
        target_fuel = inc_fuel * getattr(c, 'AI_UPKEEP_TARGETS', {"fuel": 0.50}).get("fuel", 0.50)

        # 2. Get highest unlocked tech
        res_levels = data.get("research", {})
        best_inf = queries.get_highest_infantry(data, tech_tree, unit_library)
        best_tank = queries.get_best_offensive_unit(res_levels, unit_library)
        best_navy = queries.get_best_naval_unit(res_levels, unit_library)

        # 3. Identify physical boundaries for deployment
        border_provs = []
        coastal_provs = []
        for prov in owned_provs:
            # Filter out lake-only coasts using your query
            if prov.get("is_coastal", False) and queries.borders_ocean(prov, map_screen.id_to_province):
                coastal_provs.append(prov)

            # Check if it touches anything not owned by this nation
            for n_id in prov.get("neighbors", []):
                n_prov = map_screen.id_to_province.get(n_id)
                if n_prov and n_prov.get("owner") != nation and n_prov.get("terrain") not in c.WATER_TERRAINS:
                    border_provs.append(prov)
                    break # Already flagged as a border, move to next province

        # Fallback if it's a completely isolated island with no land borders
        if not border_provs:
            border_provs = owned_provs

        # 4. Draft the Army Composition
        units_to_spawn = []
        upk_man, upk_mat, upk_fuel = 0, 0, 0

        mat_to_man_ratio = inc_man / max(1.0, inc_mat)
        dynamic_tank_ratio = max(1, int(mat_to_man_ratio * getattr(c, 'AI_INFANTRY_TO_TANK_RATIO', 4)))

        total_borders = len(border_provs) + len(coastal_provs)
        target_navy_ratio = 0.0
        
        if total_borders > 0:
            if len(coastal_provs) < getattr(c, 'AI_MIN_COAST_FOR_NAVY', 8) and len(border_provs) > 0:
                target_navy_ratio = 0.0
            else:
                target_navy_ratio = min(getattr(c, 'AI_MAX_NAVY_RATIO', 0.2), len(coastal_provs) / total_borders)

        inf_count, tank_count, navy_count = 0, 0, 0
        failsafe = 0

        # Purchase loop: Stop when budget maxes out or if we hit the limit
        while failsafe < 500:
            failsafe += 1
            total_units = inf_count + tank_count + navy_count
            current_navy_ratio = navy_count / max(1, total_units)

            unit_to_buy = None
            if current_navy_ratio < target_navy_ratio and best_navy:
                unit_to_buy = best_navy
            elif best_tank and (inf_count / max(1, tank_count)) > dynamic_tank_ratio:
                unit_to_buy = best_tank
            else:
                unit_to_buy = best_inf

            if not unit_to_buy: break

            stats = unit_library.get(unit_to_buy, {})
            u_man = stats.get("cost_manpower", 0) * c.UPKEEP_MODIFIERS["manpower"]
            u_mat = stats.get("cost_materials", 0) * c.UPKEEP_MODIFIERS["materials"]
            u_fuel = stats.get("cost_fuel", 0) * c.UPKEEP_MODIFIERS["fuel"]

            if upk_man + u_man <= target_man and upk_mat + u_mat <= target_mat and upk_fuel + u_fuel <= target_fuel:
                units_to_spawn.append(unit_to_buy)
                upk_man += u_man
                upk_mat += u_mat
                upk_fuel += u_fuel

                if unit_to_buy == best_navy: navy_count += 1
                elif unit_to_buy == best_tank: tank_count += 1
                else: inf_count += 1
            else:
                # If we couldn't afford the preferred unit (like an expensive tank), fallback to infantry
                if unit_to_buy != best_inf:
                    stats = unit_library.get(best_inf, {})
                    u_man = stats.get("cost_manpower", 0) * c.UPKEEP_MODIFIERS["manpower"]
                    u_mat = stats.get("cost_materials", 0) * c.UPKEEP_MODIFIERS["materials"]
                    u_fuel = stats.get("cost_fuel", 0) * c.UPKEEP_MODIFIERS["fuel"]
                    
                    if upk_man + u_man <= target_man and upk_mat + u_mat <= target_mat and upk_fuel + u_fuel <= target_fuel:
                        units_to_spawn.append(best_inf)
                        upk_man += u_man
                        upk_mat += u_mat
                        upk_fuel += u_fuel
                        inf_count += 1
                    else:
                        break
                else:
                    break

        # Guarantee at least 1 unit to prevent a totally defenseless nation
        if not units_to_spawn:
            units_to_spawn.append(best_inf)

        # 5. Distribute Units Evenly Across Borders
        random.shuffle(border_provs)
        random.shuffle(coastal_provs)

        border_idx = 0
        coast_idx = 0

        for u_name in units_to_spawn:
            stats = unit_library.get(u_name, {})
            is_naval = stats.get("naval_unit", False)

            # Route naval units strictly to ocean coasts, otherwise put land units on borders
            if is_naval:
                if coastal_provs:
                    target_prov = coastal_provs[coast_idx % len(coastal_provs)]
                    coast_idx += 1
                    target_prov.setdefault("units", []).append(generate_unit(nation, u_name))
                # If they have no valid ocean coast, the ship just doesn't spawn.
            else:
                target_prov = border_provs[border_idx % len(border_provs)]
                border_idx += 1
                target_prov.setdefault("units", []).append(generate_unit(nation, u_name))

    map_screen.show_feedback(f"Randomized {target_country_count} evenly sized nations for {start_year}!")