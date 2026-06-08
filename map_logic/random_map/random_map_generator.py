import os
import json
import data.constants as c
from data import queries

def randomize_all_provinces(map_screen, settings):
    target_country_count = settings["countries"]
    start_year = settings["year"]
    island_filter_size = settings.get("island_filter_size", getattr(c, 'RANDOM_SCENARIO_DEFAULT_ISLAND_FILTER', 4))
    single_tile_start = settings.get("single_tile_start", getattr(c, 'RANDOM_SCENARIO_SINGLE_TILE_START', False))
    resource_chance = settings.get("resource_chance", getattr(c, 'RANDOM_SCENARIO_DEFAULT_RESOURCE_CHANCE', 0.15))

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

        if len(comp) >= island_filter_size:
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
    if not single_tile_start:
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
            # Changed these to 0 so the dynamic logic fully controls the starting tech
            if "infantry_type" in res_template: res_template["infantry_type"] = 0
            if "cavalry" in res_template: res_template["cavalry"] = 0

    # Dynamically read years from the loaded JSON struct
    tech_timeline = {tech: data.get("years", [1850]) for tech, data in struct.items()}
    
    # Calculate what tech levels everyone gets based on the Start Year
    baseline_tech = {}
    
    if start_year == 1910:
        # Load the exception from constants.py
        baseline_tech = getattr(c, 'DEFAULT_1910_TECH', {}).copy()
    else:
        for tech, years in tech_timeline.items():
            # Check the JSON structure to see if this is an infantry tech
            is_infantry = struct.get(tech, {}).get("category") == "INFANTRY"
            
            if is_infantry:
                # Infantry gets tech up to and including the start year
                lvl = sum(1 for y in years if y <= start_year)
            else:
                # Everything else only gets tech from STRICTLY previous years
                lvl = sum(1 for y in years if y < start_year)
                
            if lvl > 0: baseline_tech[tech] = lvl

    # Apply base tech to all active nations
    for nation in active_nations:
        if "research" not in map_screen.nation_data[nation]:
            map_screen.nation_data[nation]["research"] = {}
        
        # DO NOT keep existing leftover tech from the base map! 
        # Overwrite the entire research dict with a clean template first.
        map_screen.nation_data[nation]["research"] = res_template.copy()
        
        # Then, overwrite with the calculated timeline tech levels
        map_screen.nation_data[nation]["research"].update(baseline_tech)
        
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

    allowed_recruitment = []
    if baseline_tech.get("basic_recruitment", 0) > 0:
        allowed_recruitment.append("Basic Recruitment Center")
        
    rec_lvl = baseline_tech.get("recruitment_buildings", 0)
    for lvl in range(1, rec_lvl + 1):
        allowed_recruitment.append(f"Recruitment Building Lvl {lvl}")

    # Give out random resources and buildings
    for prov in valid_land_provinces:
        if random.random() < resource_chance:
            res_type = random.choice(["Iron", "Coal", "Oil"])
            prov["resources"] = {res_type: random.randint(20, 200)}
            
        prov.setdefault("buildings", [])
        has_factory = False
        
        if allowed_factories and random.random() < 0.10:
            fac = random.choice(allowed_factories)
            prov["buildings"].append(fac)
            if "Basic Factory" in fac or "Factory Lvl" in fac:
                has_factory = True
        
        # Guarantee every factory gets a recruitment center of a random level (if unlocked)
        if has_factory and allowed_recruitment:
            prov["buildings"].append(random.choice(allowed_recruitment))

    # --- Step D: Guarantee Minimum Buildings (Balanced by Tech) ---
    best_factory = allowed_factories[-1] if allowed_factories else getattr(c, 'DEFAULT_STARTING_FACTORY', "Basic Factory")
    best_recruitment = allowed_recruitment[-1] if allowed_recruitment else None
    min_factories_required = getattr(c, 'RANDOM_SCENARIO_MIN_FACTORIES', 2)

    for nation in active_nations:
        owned_provs = [p for p in valid_land_provinces if p["owner"] == nation]
        if not owned_provs: continue

        factory_provs = []
        recruitment_provs = []

        for prov in owned_provs:
            bldgs = prov.get("buildings", [])
            
            # Enforce rule: Recruitment centers always spawn with a factory if possible
            has_fac = any("Factory" in b for b in bldgs)
            if not has_fac and any("Recruitment" in b for b in bldgs):
                # Remove the orphaned recruitment center
                prov["buildings"] = [b for b in bldgs if "Recruitment" not in b]
                bldgs = prov.get("buildings", [])
                
            # Enforce new rule: Every factory MUST have a recruitment center (if researched)
            if has_fac and not any("Recruitment" in b for b in bldgs) and allowed_recruitment:
                prov["buildings"].append(random.choice(allowed_recruitment))
                bldgs = prov.get("buildings", [])
                
            if any("Factory" in b for b in bldgs): factory_provs.append(prov)
            if any("Recruitment" in b for b in bldgs): recruitment_provs.append(prov)

        # 1. Guarantee Minimum Factories (RANDOM_SCENARIO_MIN_FACTORIES unless 1 tile big)
        target_factory_count = min(min_factories_required, len(owned_provs))
        
        while len(factory_provs) < target_factory_count:
            no_fac_provs = [p for p in owned_provs if p not in factory_provs]
            if not no_fac_provs: break # Failsafe
            
            target_prov = random.choice(no_fac_provs)
            fac_to_place = random.choice(allowed_factories) if allowed_factories else best_factory
            target_prov.setdefault("buildings", []).append(fac_to_place)
            
            # Guarantee it gets a recruitment center if unlocked
            if allowed_recruitment:
                target_prov["buildings"].append(random.choice(allowed_recruitment))
                if target_prov not in recruitment_provs:
                    recruitment_provs.append(target_prov)
            
            factory_provs.append(target_prov)

        # 2. Guarantee Best Factory
        has_best_factory = any(best_factory in p.get("buildings", []) for p in factory_provs)
        if best_factory and not has_best_factory and factory_provs:
            # Upgrade an existing factory
            target_prov = random.choice(factory_provs)
            target_prov["buildings"] = [b for b in target_prov.get("buildings", []) if "Factory" not in b]
            target_prov["buildings"].append(best_factory)

        # 3. Guarantee Best Recruitment Center
        has_best_recruitment = any(best_recruitment in p.get("buildings", []) for p in recruitment_provs)
        if best_recruitment and not has_best_recruitment:
            if factory_provs:
                # Place it strictly on a factory province
                target_prov = random.choice(factory_provs)
                target_prov["buildings"] = [b for b in target_prov.get("buildings", []) if "Recruitment" not in b]
                target_prov["buildings"].append(best_recruitment)
                if target_prov not in recruitment_provs:
                    recruitment_provs.append(target_prov)

    # --- Step E: Generate Starting Armies & Spread Across Borders ---
    if getattr(c, 'RANDOM_SCENARIO_SPAWN_UNITS', True):
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
                
                # --- FIX: GUARANTEE GROUND ARMY FIRST ---
                if inf_count < getattr(c, 'RANDOM_SCENARIO_MIN_INFANTRY', 3):
                    unit_to_buy = best_inf
                elif current_navy_ratio < target_navy_ratio and best_navy:
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
                    # If we couldn't afford the preferred unit (like an expensive tank/ship), fallback to infantry
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
                inf_count += 1

            # GUARANTEE COASTAL FACTORY IF NAVY SPAWNS
            if navy_count > 0 and coastal_provs:
                has_coastal_factory = False
                for p in coastal_provs:
                    if queries.has_basic_factory(p):
                        has_coastal_factory = True
                        break
                    
                if not has_coastal_factory:
                    # Inject a factory into the first coastal province to validate the ships
                    fac_to_place = random.choice(allowed_factories) if allowed_factories else getattr(c, 'DEFAULT_STARTING_FACTORY', "Basic Factory")
                    coastal_provs[0].setdefault("buildings", []).append(fac_to_place)
                    
                    # Also spawn a random level recruitment center
                    if allowed_recruitment:
                        coastal_provs[0]["buildings"].append(random.choice(allowed_recruitment))

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

    map_screen.show_feedback(f"Randomized {target_country_count} nations for {start_year}!")