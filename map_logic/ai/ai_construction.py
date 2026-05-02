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
        war_mult = c.AI_WAR_UPKEEP_MULTIPLIER if at_war else 1.0

        target_man = c.AI_UPKEEP_TARGETS["manpower"] * war_mult
        target_mat = c.AI_UPKEEP_TARGETS["materials"] * war_mult
        target_fuel = c.AI_UPKEEP_TARGETS["fuel"] * war_mult

        inc_mat = econ["total_inc"]["materials"]
        upk_mat = econ["upkeep"]["materials"]
        inc_man = econ["total_inc"]["manpower"]
        upk_man = econ["upkeep"]["manpower"]
        inc_fuel = econ["total_inc"]["fuel"]
        upk_fuel = econ["upkeep"]["fuel"]
        
        ratio_man = upk_man / inc_man if inc_man > 0 else 1.0
        ratio_mat = upk_mat / inc_mat if inc_mat > 0 else 1.0
        ratio_fuel = upk_fuel / inc_fuel if inc_fuel > 0 else 1.0

        deficits = []
        if ratio_man > target_man: deficits.append("cost_manpower")
        if ratio_mat > target_mat: deficits.append("cost_materials")
        if ratio_fuel > target_fuel: deficits.append("cost_fuel")

        if deficits:
            # Find units to disband
            owned_units = []
            for prov in my_provs:
                for u in prov.get("units", []):
                    if u.get("owner") == ai_name and u.get("order", {}).get("type") != "DISBAND":
                        owned_units.append(u)
                        
            candidates = []
            for u in owned_units:
                u_type = u.get("type", "")
                stats = unit_library.get(u_type, {})
                if any(stats.get(res, 0) > 0 for res in deficits):
                    candidates.append((u, u_type, stats))
                    
            if candidates:
                res_levels = data.get("research", {})
                def sort_key(item):
                    u, u_type, stats = item
                    is_obs = queries.is_unit_obsolete(u_type, res_levels)
                    # Outdated units (is_obs=True) have priority (0)
                    # Tie-breaker: lowest attack
                    return (0 if is_obs else 1, stats.get("attack", 0))
                    
                candidates.sort(key=sort_key)
                
                # Disband the worst unit
                worst_unit = candidates[0][0]
                worst_unit["order"] = {"type": "DISBAND", "turns_left": 1}
                
        # If current upkeep is below the desired percentage of income, build units!
        elif ratio_mat < target_mat and ratio_man < target_man and ratio_fuel < target_fuel:
            
            # --- NEW: Guard Target Calculation ---
            infantry_count = 0
            naval_count = 0
            guard_targets = 0
            coastal_targets = 0
            
            for prov in my_provs:
                # Count existing and queued units
                for u in prov.get("units", []):
                    if u.get("owner") == ai_name:
                        u_type = u.get("type", "")
                        if "Infantry" in u_type:
                            infantry_count += 1
                        elif queries.is_naval_unit(u_type) and not u_type.startswith("Convoy"):
                            naval_count += 1
                for q in prov.get("deployment_queue", []):
                    q_type = q.get("unit_type", "")
                    if "Infantry" in q_type:
                        infantry_count += 1
                    elif queries.is_naval_unit(q_type) and not q_type.startswith("Convoy"):
                        naval_count += 1
                
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
            elif coastal_targets > 0 and naval_count < coastal_targets * 1.5:
                # Prioritize naval deployment if coasts are undefended and ratio is low
                unit_name_to_build = queries.get_best_naval_unit(data.get("research", {}), unit_library)
                if not unit_name_to_build: # Fallback to offensive land units if no naval tech
                    unit_name_to_build = queries.get_best_offensive_unit(data.get("research", {}), unit_library)
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
            
            # --- NEW: Filter to coastal factories only if building a naval unit ---
            is_naval_recruit = queries.is_naval_unit(unit_name_to_build)
            valid_recruit_provs = [p for p in factory_provs if p.get("is_coastal", False)] if is_naval_recruit else factory_provs
            
            # Can we afford the upfront cost AND have a valid province?
            if valid_recruit_provs and data.get("materials", 0) >= cost_mat and data.get("manpower", 0) >= cost_man and data.get("fuel", 0) >= cost_fuel:
                target_prov = valid_recruit_provs[0] # Pick the first available industrial sector
                
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