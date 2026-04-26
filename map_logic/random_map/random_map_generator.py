import random
import os
import json
import data.constants as c

def randomize_all_provinces(map_screen, settings):
    target_country_count = settings["countries"]
    start_year = settings["year"]

    playable_nations = [
        name for name, stats in map_screen.nation_data.items()
        if stats.get("is_playable") and name not in c.UNPLAYABLE_NATIONS
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
            if "carrack" in res_template: res_template["carrack"] = 1
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

    # Determine which buildings are legally allowed to spawn
    allowed_buildings = []
    if baseline_tech.get("workshop", 0) > 0: allowed_buildings.append("Workshop Lvl 1")
    if baseline_tech.get("basic_factory", 0) > 0: allowed_buildings.append("Basic Factory")
    if baseline_tech.get("factory", 0) > 0: allowed_buildings.append("Factory Lvl 1")
    if baseline_tech.get("fuel_refining", 0) > 0: allowed_buildings.append("Synthetic Refinery Lvl 1")

    # Give out random resources and buildings
    for prov in valid_land_provinces:
        if random.random() < 0.15:
            res_type = random.choice(["Iron", "Coal", "Oil"])
            prov["resources"] = {res_type: random.randint(20, 80)}
            
        # Only spawn buildings if the era permits it
        if allowed_buildings and random.random() < 0.10:
            prov["buildings"] = [random.choice(allowed_buildings)]

    # --- Step D: Guarantee Minimums & Garrison Units ---
    unit_library = {}
    unit_stats_path = c.UNIT_DATA_PATH
    if os.path.exists(unit_stats_path):
        with open(unit_stats_path, 'r') as f:
            unit_library = json.load(f)

    # Helper function to get the correct infantry name for a nation's tech level
    def get_infantry_type(nation):
        res_lvl = map_screen.nation_data[nation]["research"].get("infantry_type", 1)
        inf_years = struct.get("infantry_type", {}).get("years", [1850])
        year_val = inf_years[min(res_lvl - 1, len(inf_years)-1)]
        return f"Infantry Type {year_val}"

    # Helper to generate a fresh unit dictionary so pointers aren't shared across provinces
    def generate_unit(nation, u_name):
        stats = unit_library.get(u_name, {})
        return {
            "type": u_name,
            "owner": nation,
            "health": stats.get("health", 100),
            "max_health": stats.get("health", 100),
            "speed": stats.get("speed", 1),
            "attack": stats.get("attack", 5),
            "defense": stats.get("defense", 0),
            "level": 1,
            "order": {"type": "MOVE", "path": []}
        }

    for nation in active_nations:
        owned_provs = [p for p in valid_land_provinces if p["owner"] == nation]
        if not owned_provs: continue

        infantry_name = get_infantry_type(nation)
        has_factory = False

        for prov in owned_provs:
            bldgs = prov.get("buildings", [])
            # Check if province contains an industrial building
            if any("Workshop" in b or "Factory" in b or "Refinery" in b for b in bldgs):
                has_factory = True
                prov.setdefault("units", []).append(generate_unit(nation, infantry_name))

                # other test summons (do not actually implement)
                # cavalry also exists (check if ai knows it can move them at 2x speed)
                # prov.setdefault("units", []).append(generate_unit(nation, "Cavalry"))
                # carrack (only summon if coastal)
                # if prov.get("is_coastal", False):
                #     prov.setdefault("units", []).append(generate_unit(nation, "Carrack"))
        
        # If the nation randomly got zero factories, guarantee them one + a garrison unit
        if not has_factory:
            target_prov = random.choice(owned_provs)
            bldg_to_add = allowed_buildings[-1] if allowed_buildings else "Workshop Lvl 1"
            target_prov.setdefault("buildings", []).append(bldg_to_add)
            target_prov.setdefault("units", []).append(generate_unit(nation, infantry_name))

    map_screen.show_feedback(f"Randomized {target_country_count} evenly sized nations for {start_year}!")