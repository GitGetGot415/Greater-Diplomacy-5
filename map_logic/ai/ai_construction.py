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
            inf_name = queries.get_highest_infantry(data, tech_tree, unit_library)
            inf_stats = unit_library.get(inf_name, {})
            cost_mat = inf_stats.get("cost_materials", 0)
            cost_man = inf_stats.get("cost_manpower", 0)
            cost_fuel = inf_stats.get("cost_fuel", 0)
            
            # Find a province capable of recruiting
            factory_provs = [p for p in my_provs if queries.has_industry(p)]
            
            # Can we afford the upfront cost?
            if factory_provs and data.get("materials", 0) >= cost_mat and data.get("manpower", 0) >= cost_man and data.get("fuel", 0) >= cost_fuel:
                target_prov = factory_provs[0] # Pick the first available industrial sector
                
                data["materials"] -= cost_mat
                data["manpower"] -= cost_man
                data["fuel"] -= cost_fuel
                
                order = {
                    "unit_type": inf_name,
                    "turns_remaining": max(1, inf_stats.get("production_time", c.DAYS_PER_TURN) // c.DAYS_PER_TURN),
                    "refund": {"materials": cost_mat, "manpower": cost_man, "fuel": cost_fuel}
                }
                target_prov.setdefault("deployment_queue", []).append(order)

        # --- 2. EVALUATE CONSTRUCTION LOGIC ---
        # If the AI has an excess hoard of materials, invest it back into factories
        if data.get("materials", 0) > 15000:
            res_levels = data.get("research", {})
            best_bldg = None
            
            # Find highest unlocked industrial building
            if res_levels.get("factory", 0) > 0:
                best_bldg = f"Factory Lvl {res_levels['factory']}"
            elif res_levels.get("basic_factory", 0) > 0:
                best_bldg = "Basic Factory"
            else:
                # If they haven't researched actual factories yet, build the best workshop
                best_bldg = "Workshop Lvl 5"

            if best_bldg and best_bldg in building_library:
                b_stats = building_library[best_bldg]
                c_mat = b_stats.get("cost_materials", 0)
                c_fuel = b_stats.get("cost_fuel", 0)
                
                if data.get("materials", 0) >= c_mat and data.get("fuel", 0) >= c_fuel:
                    # Find a province that doesn't already have an industry building
                    valid_provs = [p for p in my_provs if not any(b_stats["group"] == building_library.get(b, {}).get("group") for b in p.get("buildings", []))]
                    # Double check the queue so it doesn't build two at once
                    valid_provs = [p for p in valid_provs if not any(q.get("group") == b_stats["group"] for q in p.get("deployment_queue", []))]

                    if valid_provs:
                        target_prov = valid_provs[0]
                        data["materials"] -= c_mat
                        data["fuel"] -= c_fuel
                        
                        order = {
                            "order_type": "BUILDING",
                            "item_name": best_bldg,
                            "turns_remaining": max(1, b_stats.get("time", c.DAYS_PER_TURN) // c.DAYS_PER_TURN),
                            "group": b_stats["group"],
                            "refund": {"materials": c_mat, "manpower": 0, "fuel": c_fuel}
                        }
                        target_prov.setdefault("deployment_queue", []).append(order)