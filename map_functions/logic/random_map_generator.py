import random
import os
import json

def randomize_all_provinces(map_screen, settings):
    target_country_count = settings["countries"]
    start_year = settings["year"]

    playable_nations = [
        name for name, stats in map_screen.nation_data.items()
        if stats.get("is_playable") and name not in ["Ocean", "Lakes", "Unclaimed"]
    ]
    
    land_provinces = [p for p in map_screen.map_data.values() if p.get("terrain", "") not in ["ocean", "coastal_sea", "inland_sea", "lakes"]]
    
    if not land_provinces or not playable_nations: return

    # Wipe existing map data clean
    for prov in land_provinces:
        prov.update({"owner": "Unclaimed", "cores": [], "resources": {}, "buildings": [], "units": []})

    import random
    random.shuffle(playable_nations)
    
    # 1. Adjust country count to not exceed available provinces
    num_seeds = min(target_country_count, len(land_provinces))
    active_nations = playable_nations[:num_seeds]
    
    unassigned_land = set(p["id"] for p in land_provinces)
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

    # --- Step C: Tech & Building Assignment ---
    
    # 1. Load the full baseline template so nobody is missing keys
    template_path = "data/json/research_template.json"
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

    for prov in land_provinces:
        if random.random() < 0.15:
            res_type = random.choice(["Iron", "Coal", "Oil"])
            prov["resources"] = {res_type: random.randint(20, 80)}
            
        # Only spawn buildings if the era permits it
        if allowed_buildings and random.random() < 0.10:
            prov["buildings"] = [random.choice(allowed_buildings)]

    map_screen.show_feedback(f"Randomized {target_country_count} evenly sized nations for {start_year}!")