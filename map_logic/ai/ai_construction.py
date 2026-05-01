import json
import os
import data.constants as c
from data import queries

def process_ai_economy_decisions(map_screen):
    """Handles AI unit recruitment and building construction based on economy."""
    unit_library = queries.get_unit_library()
    building_library = queries.get_building_library()

    tech_tree = queries.get_tech_tree()

    all_econ = queries.calculate_all_economies(map_screen.map_data, map_screen.nation_data)

    # Pre-group provinces by owner for efficiency
    nation_provs = {}
    for prov in map_screen.map_data.values():
        owner = prov.get("owner")
        if owner:
            nation_provs.setdefault(owner, []).append(prov)

    ai_nations = queries.get_active_ai_nations(map_screen)

    for ai_name in ai_nations:
        data = map_screen.nation_data[ai_name]
        econ = all_econ.get(ai_name)
        if not econ: continue

        my_provs = nation_provs.get(ai_name, [])
        if not my_provs: continue

        # --- 1. EVALUATE RECRUITMENT RATIOS ---
        at_war = len(data.get("at_war_with", [])) > 0
        desired_ratio = 0.8 if at_war else 0.2

        inc_mat = econ["total_inc"]["materials"]
        upk_mat = econ["upkeep"]["materials"]
        inc_man = econ["total_inc"]["manpower"]
        upk_man = econ["upkeep"]["manpower"]
        
        # If current upkeep is below the desired percentage of income, build units!
        if upk_mat < (inc_mat * desired_ratio) and upk_man < (inc_man * desired_ratio):
            
            # --- NEW: Guard Target Calculation ---
            infantry_count = 0
            guard_targets = 0
            coastal_targets = 0
            
            for prov in my_provs:
                # Count existing and queued infantry
                for u in prov.get("units", []):
                    if u.get("owner") == ai_name and "Infantry" in u.get("type", ""):
                        infantry_count += 1
                for q in prov.get("deployment_queue", []):
                    if "Infantry" in q.get("unit_type", ""):
                        infantry_count += 1
                
                # Check neighbors for foreign borders
                is_border = False
                for n_id in prov.get("neighbors", []):
                    n_prov = map_screen.id_to_province.get(n_id)
                    if n_prov and n_prov.get("terrain") not in c.WATER_TERRAINS and n_prov.get("owner") != ai_name:
                        is_border = True
                        break
                        
                if is_border:
                    guard_targets += 1
                elif prov.get("is_coastal", False):
                    coastal_targets += 1
            
            total_guard_needed = guard_targets + coastal_targets
            
            unit_name_to_build = None
            if infantry_count < total_guard_needed:
                unit_name_to_build = queries.get_highest_infantry(data, tech_tree, unit_library)
            else:
                unit_name_to_build = queries.get_best_offensive_unit(data.get("research", {}), unit_library)
                if not unit_name_to_build: # Fallback if no offensive tech is researched
                    unit_name_to_build = queries.get_highest_infantry(data, tech_tree, unit_library)

            unit_stats = unit_library.get(unit_name_to_build, {})
            cost_mat = unit_stats.get("cost_materials", 0)
            cost_man = unit_stats.get("cost_manpower", 0)
            cost_fuel = unit_stats.get("cost_fuel", 0)
            
            # Find a province capable of recruiting
            factory_provs = [p for p in my_provs if queries.has_industry(p)]
            
            # Can we afford the upfront cost?
            if factory_provs and data.get("materials", 0) >= cost_mat and data.get("manpower", 0) >= cost_man and data.get("fuel", 0) >= cost_fuel:
                target_prov = factory_provs[0] # Pick the first available industrial sector
                
                data["materials"] -= cost_mat
                data["manpower"] -= cost_man
                data["fuel"] -= cost_fuel
                
                order = {
                    "unit_type": unit_name_to_build,
                    "turns_remaining": max(1, unit_stats.get("production_time", c.DAYS_PER_TURN) // c.DAYS_PER_TURN),
                    "refund": {"materials": cost_mat, "manpower": cost_man, "fuel": cost_fuel}
                }
                target_prov.setdefault("deployment_queue", []).append(order)

        # --- 2. EVALUATE CONSTRUCTION LOGIC ---
        # If the AI has an excess hoard of materials, invest it back into factories
        if data.get("materials", 0) > 15000:
            res_levels = data.get("research", {})
            
            # Fetch the dynamic list of industry buildings in order
            industry_b_list = [b for b, d in building_library.items() if d.get("group") == "industry"]

            for prov in my_provs:
                current_buildings = prov.get("buildings", [])
                queue = prov.get("deployment_queue", [])

                # Double check the queue so it doesn't build two at once in the same province
                if any(q.get("group") == "industry" for q in queue):
                    continue

                owned_industry = [b for b in current_buildings if building_library.get(b, {}).get("group") == "industry"]
                target_bldg = None

                # Find the next sequential upgrade for this specific province
                if not owned_industry:
                    target_bldg = industry_b_list[0] if industry_b_list else None
                else:
                    for i, b_name in enumerate(industry_b_list):
                        if b_name in owned_industry:
                            if i + 1 < len(industry_b_list):
                                target_bldg = industry_b_list[i+1]

                if target_bldg:
                    # Check if the AI actually has the research required for this next tier
                    req_tech, req_lvl = queries.get_building_required_tech(target_bldg)
                    if req_tech and res_levels.get(req_tech, 0) < req_lvl:
                        continue # Lacks the research to build this next tier, try another province

                    # We have the tech and the physical foundation, now check costs
                    b_stats = building_library[target_bldg]
                    c_mat = b_stats.get("cost_materials", 0)
                    c_fuel = b_stats.get("cost_fuel", 0)

                    if data.get("materials", 0) >= c_mat and data.get("fuel", 0) >= c_fuel:
                        data["materials"] -= c_mat
                        data["fuel"] -= c_fuel

                        order = {
                            "order_type": "BUILDING",
                            "item_name": target_bldg,
                            "turns_remaining": max(1, b_stats.get("time", c.DAYS_PER_TURN) // c.DAYS_PER_TURN),
                            "group": b_stats["group"],
                            "refund": {"materials": c_mat, "manpower": 0, "fuel": c_fuel}
                        }
                        prov.setdefault("deployment_queue", []).append(order)
                        
                        # Successfully queued a building. Break out of the loop so it only queues one per turn 
                        # to avoid instantly draining its treasury on 30 workshops at once.
                        break