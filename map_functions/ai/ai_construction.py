import json
import os
from data.constants import UNIT_DATA_PATH, BUILDING_DATA_PATH, RESEARCH_TEMPLATE_PATH, UNPLAYABLE_NATIONS, DAYS_PER_TURN

def get_highest_infantry(nation_data, tech_tree, unit_library):
    """Finds the highest level infantry unit the AI has researched."""
    res_lvl = nation_data.get("research", {}).get("infantry_type", 1)
    inf_years = tech_tree.get("infantry_type", {}).get("years", [1850])
    year_val = inf_years[min(res_lvl - 1, len(inf_years)-1)]
    u_name = f"Infantry Type {year_val}"
    
    if u_name in unit_library:
        return u_name
    return "Infantry Type 1850"

def process_ai_economy_decisions(map_screen):
    """Handles AI unit recruitment and building construction based on economy."""
    unit_library = {}
    if os.path.exists(UNIT_DATA_PATH):
        with open(UNIT_DATA_PATH, 'r') as f: unit_library = json.load(f)
        
    building_library = {}
    if os.path.exists(BUILDING_DATA_PATH):
        with open(BUILDING_DATA_PATH, 'r') as f: building_library = json.load(f)

    tech_tree = {}
    if os.path.exists(RESEARCH_TEMPLATE_PATH):
        with open(RESEARCH_TEMPLATE_PATH, 'r') as f: tech_tree = json.load(f)

    all_econ = map_screen.calculate_all_economies()

    # Pre-group provinces by owner for efficiency
    nation_provs = {}
    for prov in map_screen.map_data.values():
        owner = prov.get("owner")
        if owner:
            nation_provs.setdefault(owner, []).append(prov)

    for ai_name, data in map_screen.nation_data.items():
        if ai_name == map_screen.player_country or ai_name in UNPLAYABLE_NATIONS or not data.get("is_playable"):
            continue

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
            inf_name = get_highest_infantry(data, tech_tree, unit_library)
            inf_stats = unit_library.get(inf_name, {})
            cost_mat = inf_stats.get("cost_materials", 0)
            cost_man = inf_stats.get("cost_manpower", 0)
            cost_fuel = inf_stats.get("cost_fuel", 0)
            
            # Find a province capable of recruiting (needs a factory/workshop)
            factory_provs = [p for p in my_provs if any("Workshop" in b or "Factory" in b for b in p.get("buildings", []))]
            
            # Can we afford the upfront cost?
            if factory_provs and data.get("materials", 0) >= cost_mat and data.get("manpower", 0) >= cost_man and data.get("fuel", 0) >= cost_fuel:
                target_prov = factory_provs[0] # Pick the first available industrial sector
                
                data["materials"] -= cost_mat
                data["manpower"] -= cost_man
                data["fuel"] -= cost_fuel
                
                order = {
                    "unit_type": inf_name,
                    "turns_remaining": max(1, inf_stats.get("production_time", DAYS_PER_TURN) // DAYS_PER_TURN),
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
            elif res_levels.get("workshop", 0) > 0:
                best_bldg = f"Workshop Lvl {res_levels['workshop']}"

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
                            "turns_remaining": max(1, b_stats.get("time", DAYS_PER_TURN) // DAYS_PER_TURN),
                            "group": b_stats["group"],
                            "refund": {"materials": c_mat, "manpower": 0, "fuel": c_fuel}
                        }
                        target_prov.setdefault("deployment_queue", []).append(order)