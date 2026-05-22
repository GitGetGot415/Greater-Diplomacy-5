import json
import os
import random
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
        # Prevent AI from treating bugged water tiles as valid build sites
        if owner and prov.get("terrain") not in c.WATER_TERRAINS:
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

        # Disband Militia in peacetime
        if not at_war:
            for prov in my_provs:
                for u in prov.get("units", []):
                    if u.get("owner") == ai_name and u.get("type") == "Militia" and u.get("order", {}).get("type") != "DISBAND":
                        u["order"] = {"type": "DISBAND", "turns_left": 1}

        target_man = c.AI_UPKEEP_TARGETS["manpower"] * war_mult
        target_mat = c.AI_UPKEEP_TARGETS["materials"] * war_mult
        target_fuel = c.AI_UPKEEP_TARGETS["fuel"] * war_mult

        inc_mat = econ["total_inc"]["materials"]
        upk_mat = econ["upkeep"]["materials"]
        inc_man = econ["total_inc"]["manpower"]
        upk_man = econ["upkeep"]["manpower"]
        inc_fuel = econ["total_inc"]["fuel"]
        upk_fuel = econ["upkeep"]["fuel"]
        
        # --- THE FIX: Include Pending Queue in Upkeep Projections ---
        # Prevents the AI from bankupting itself on units that haven't spawned yet
        for prov in my_provs:
            for q in prov.get("deployment_queue", []):
                q_type = q.get("unit_type")
                if q_type:
                    q_stats = unit_library.get(q_type, {})
                    upk_man += q_stats.get("cost_manpower", 0) * c.UPKEEP_MODIFIERS["manpower"]
                    upk_mat += q_stats.get("cost_materials", 0) * c.UPKEEP_MODIFIERS["materials"]
                    upk_fuel += q_stats.get("cost_fuel", 0) * c.UPKEEP_MODIFIERS["fuel"]
        # ------------------------------------------------------------
        
        ratio_man = upk_man / inc_man if inc_man > 0 else 1.0
        ratio_mat = upk_mat / inc_mat if inc_mat > 0 else 1.0
        ratio_fuel = upk_fuel / inc_fuel if inc_fuel > 0 else 1.0

        deficits = []
        if ratio_man > target_man: deficits.append("cost_manpower")
        if ratio_mat > target_mat: deficits.append("cost_materials")
        if ratio_fuel > target_fuel: deficits.append("cost_fuel")

        # --- DYNAMIC AI CONVERSION FIX ---
        # Fetch the exact maximum conversion limit this specific AI is legally allowed to use
        max_conversion = queries.get_max_fuel_conversion(data)

        # If the ai is low on fuel but has a lot of materials, let them use this feature to balance out their economy
        if max_conversion > 0:
            if ratio_fuel > target_fuel and ratio_mat < target_mat and data.get("materials", 0) > 500:
                data["mat_to_fuel_slider"] = max_conversion * 0.5 # Convert using 50% of their LEGAL MAXIMUM capability
            elif data.get("materials", 0) > 5000 and data.get("fuel", 0) < 500 or data.get("materials", 0) > 50000:
                data["mat_to_fuel_slider"] = max_conversion # Emergency: Maximize production safely
            else:
                data["mat_to_fuel_slider"] = 0.0
        else:
            data["mat_to_fuel_slider"] = 0.0

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

        # --- NEW: Guard Target & Dynamic Naval Calculation (Outside Loop for Speed) ---
        infantry_count = 0
        naval_count = 0
        tank_count = 0
        land_border_count = 0
        sea_border_count = 0
        
        # --- NEW: Panic Militia & Combat Queue Clearing ---
        for prov in my_provs:
            in_combat = queries.is_nation_in_combat_here(ai_name, prov, map_screen.nation_data)
            has_factory = queries.has_industry(prov)
            
            # 1. Clear queues on tiles in active combat
            if in_combat:
                while prov.get("deployment_queue"):
                    item = prov["deployment_queue"].pop(0)
                    if "refund" in item:
                        data["materials"] += item["refund"].get("materials", 0)
                        data["manpower"] += item["refund"].get("manpower", 0)
                        data["fuel"] += item["refund"].get("fuel", 0)
                continue # Skip panic militia check since it's already in combat and can't build anyway
                
            # 2. Panic Militia
            if has_factory:
                enemy_adjacent = False
                for n_id in prov.get("neighbors", []):
                    n_prov = map_screen.id_to_province.get(n_id)
                    if not n_prov: continue
                    # Are there enemy units here?
                    for u in n_prov.get("units", []):
                        if queries.are_at_war(ai_name, u.get("owner"), map_screen.nation_data):
                            enemy_adjacent = True
                            break
                    if enemy_adjacent: break
                
                if enemy_adjacent:
                    queue = prov.get("deployment_queue", [])
                    safe_to_panic = True
                    
                    if queue:
                        first_item = queue[0]
                        is_bldg = first_item.get("order_type") == "BUILDING"
                        u_type = first_item.get("unit_type", "")
                        is_naval = queries.is_naval_unit(u_type) if u_type else False
                        turns = first_item.get("turns_remaining", 999)
                        
                        if not is_bldg and not is_naval and turns <= 1:
                            safe_to_panic = False # Let the ground unit finish!
                    
                    if safe_to_panic and (not queue or queue[0].get("unit_type") != "Militia"):
                        # Cancel existing queue
                        while queue:
                            item = queue.pop(0)
                            if "refund" in item:
                                data["materials"] += item["refund"].get("materials", 0)
                                data["manpower"] += item["refund"].get("manpower", 0)
                                data["fuel"] += item["refund"].get("fuel", 0)
                        
                        # Queue Militia
                        militia_stats = unit_library.get("Militia", {})
                        c_mat = militia_stats.get("cost_materials", 0)
                        c_man = militia_stats.get("cost_manpower", 0)
                        c_fuel = militia_stats.get("cost_fuel", 0)
                        
                        if data.get("materials", 0) >= c_mat and data.get("manpower", 0) >= c_man and data.get("fuel", 0) >= c_fuel:
                            data["materials"] -= c_mat
                            data["manpower"] -= c_man
                            data["fuel"] -= c_fuel
                            
                            # Adjust upkeep tracking
                            upk_man += c_man * c.UPKEEP_MODIFIERS["manpower"]
                            upk_mat += c_mat * c.UPKEEP_MODIFIERS["materials"]
                            upk_fuel += c_fuel * c.UPKEEP_MODIFIERS["fuel"]
                            infantry_count += 1
                            
                            order = {
                                "unit_type": "Militia",
                                "turns_remaining": max(1, militia_stats.get("production_time", c.DAYS_PER_TURN) // c.DAYS_PER_TURN),
                                "refund": {"materials": c_mat, "manpower": c_man, "fuel": c_fuel}
                            }
                            prov.setdefault("deployment_queue", []).append(order)

            # Count existing units
            for u in prov.get("units", []):
                if u.get("owner") == ai_name:
                    u_type = u.get("type", "")
                    if "Infantry" in u_type or u_type == "Militia":
                        infantry_count += 1
                    elif "Tank" in u_type or "Armored" in u_type or u_type == "Cavalry":  
                        tank_count += 1
                    elif queries.is_naval_unit(u_type) and not u_type.startswith("Convoy"):
                        naval_count += 1
            
            # Count queued units
            for q in prov.get("deployment_queue", []):
                q_type = q.get("unit_type", "")
                if "Infantry" in q_type or q_type == "Militia":
                    infantry_count += 1
                elif "Tank" in q_type or "Armored" in q_type or q_type == "Cavalry":  
                    tank_count += 1
                elif queries.is_naval_unit(q_type) and not q_type.startswith("Convoy"):
                    naval_count += 1
            
            # Check neighbors to determine land/sea ratios
            is_land_border = False
            is_coast = False
            for n_id in prov.get("neighbors", []):
                n_prov = map_screen.id_to_province.get(n_id)
                if n_prov:
                    if n_prov.get("terrain") in c.OCEAN_TERRAINS:
                        is_coast = True
                    elif n_prov.get("owner") != ai_name and n_prov.get("owner") not in c.WATER_NATIONS:
                        is_land_border = True
                        
            if is_land_border:
                land_border_count += 1
            if is_coast:
                sea_border_count += 1
        
        total_borders = land_border_count + sea_border_count
        target_navy_ratio = 0.0
        
        if total_borders > 0:
            # If they have a tiny coast BUT they have land borders to focus on, ignore the navy.
            if sea_border_count < getattr(c, 'AI_MIN_COAST_FOR_NAVY', 8) and land_border_count > 0:
                target_navy_ratio = 0.0
            else:
                # Otherwise, proceed with the normal ratio (this protects tiny island nations)
                target_navy_ratio = min(getattr(c, 'AI_MAX_NAVY_RATIO', 0.2), sea_border_count / total_borders)

        # --- THE FIX: AI Recruitment Loop ---
        # Allow the AI to purchase multiple units per turn until its budget maxes out
        failsafe = 0
        while failsafe < 50:
            failsafe += 1
            
            # Re-evaluate ratios dynamically inside the loop
            ratio_man = upk_man / inc_man if inc_man > 0 else 1.0
            ratio_mat = upk_mat / inc_mat if inc_mat > 0 else 1.0
            ratio_fuel = upk_fuel / inc_fuel if inc_fuel > 0 else 1.0

            # Stop recruiting if we've reached our target army size
            if ratio_mat >= target_mat or ratio_man >= target_man:
                break
                
            fuel_shortage = ratio_fuel >= target_fuel

            total_units = infantry_count + tank_count + naval_count
            current_navy_ratio = naval_count / max(1, total_units)
            
            # --- Dynamic Army Composition Ratio ---
            mat_to_man_ratio = inc_man / max(1.0, inc_mat)
            dynamic_tank_ratio = max(1, int(mat_to_man_ratio * getattr(c, 'AI_INFANTRY_TO_TANK_RATIO', 1)))
            
            unit_name_to_build = None

            # 1. Naval Check (Priority if below ratio)
            if current_navy_ratio < target_navy_ratio:
                if not fuel_shortage:
                    unit_name_to_build = queries.get_best_naval_unit(data.get("research", {}), unit_library)

            # 2. Force a tank if our infantry ratio is too high
            if not unit_name_to_build and (infantry_count / max(1, tank_count)) > dynamic_tank_ratio:
                if not fuel_shortage:
                    unit_name_to_build = queries.get_best_offensive_unit(data.get("research", {}), unit_library)
            
            # 3. Default to Infantry / Guard
            if not unit_name_to_build:
                unit_name_to_build = queries.get_highest_infantry(data, tech_tree, unit_library, allow_fuel_units=not fuel_shortage)

            unit_stats = unit_library.get(unit_name_to_build, {})
            cost_mat = unit_stats.get("cost_materials", 0)
            cost_man = unit_stats.get("cost_manpower", 0)
            cost_fuel = unit_stats.get("cost_fuel", 0)
            
            # --- SECONDARY FUEL CHECK (Upfront Cost vs Income) ---
            # If we passed the income ratio checks but we simply don't have enough 
            # stockpiled fuel to buy the unit, hard fallback to basic infantry!
            if cost_fuel > 0 and data.get("fuel", 0) < cost_fuel:
                unit_name_to_build = queries.get_highest_infantry(data, tech_tree, unit_library, allow_fuel_units=False)
                
                # Re-fetch stats for the fallback unit
                unit_stats = unit_library.get(unit_name_to_build, {})
                cost_mat = unit_stats.get("cost_materials", 0)
                cost_man = unit_stats.get("cost_manpower", 0)
                cost_fuel = unit_stats.get("cost_fuel", 0)
            
            # Find a province capable of recruiting (Exclude tiles in combat)
            if unit_name_to_build == "Militia":
                factory_provs = [p for p in my_provs if queries.has_industry(p) and not queries.is_nation_in_combat_here(ai_name, p, map_screen.nation_data)]
            else:
                factory_provs = [p for p in my_provs if queries.has_basic_factory(p) and not queries.is_nation_in_combat_here(ai_name, p, map_screen.nation_data)]
            
            # --- NEW: Filter to coastal factories only if building a naval unit ---
            is_naval_recruit = queries.is_naval_unit(unit_name_to_build)
            if is_naval_recruit:
                valid_recruit_provs = [p for p in factory_provs if p.get("is_coastal", False) and queries.borders_ocean(p, map_screen.id_to_province)]
            else:
                valid_recruit_provs = factory_provs
            
            # --- Fallback if AI tries to build a ship but has no coastal factories ---
            if is_naval_recruit and not valid_recruit_provs:
                # Force basic infantry fallback here as well so the turn isn't wasted
                unit_name_to_build = queries.get_highest_infantry(data, tech_tree, unit_library, allow_fuel_units=False)
                unit_stats = unit_library.get(unit_name_to_build, {})
                cost_mat = unit_stats.get("cost_materials", 0)
                cost_man = unit_stats.get("cost_manpower", 0)
                cost_fuel = unit_stats.get("cost_fuel", 0)
                is_naval_recruit = False
                valid_recruit_provs = factory_provs
            
            # Can we afford the upfront cost AND have a valid province?
            if valid_recruit_provs and data.get("materials", 0) >= cost_mat and data.get("manpower", 0) >= cost_man and data.get("fuel", 0) >= cost_fuel:
                # Pick the province with the shortest queue! Do not overload a province!
                target_prov = min(valid_recruit_provs, key=lambda p: len(p.get("deployment_queue", [])))
                
                data["materials"] -= cost_mat
                data["manpower"] -= cost_man
                data["fuel"] -= cost_fuel

                # Track loops internal variables so the ratio math is valid on the next loop
                upk_man += cost_man * c.UPKEEP_MODIFIERS["manpower"]
                upk_mat += cost_mat * c.UPKEEP_MODIFIERS["materials"]
                upk_fuel += cost_fuel * c.UPKEEP_MODIFIERS["fuel"]

                if is_naval_recruit:
                    naval_count += 1
                elif "Tank" in unit_name_to_build or "Armored" in unit_name_to_build or unit_name_to_build == "Cavalry":
                    tank_count += 1
                else:
                    infantry_count += 1
                
                order = {
                    "unit_type": unit_name_to_build,
                    "turns_remaining": max(1, unit_stats.get("production_time", c.DAYS_PER_TURN) // c.DAYS_PER_TURN),
                    "refund": {"materials": cost_mat, "manpower": cost_man, "fuel": cost_fuel}
                }
                target_prov.setdefault("deployment_queue", []).append(order)
            else:
                break # Can't afford it or out of valid factories. Exit recruitment loop.

        # --- 2. EVALUATE CONSTRUCTION LOGIC ---
        # If the AI has an excess hoard of materials, invest it back into factories
        if data.get("materials", 0) > 15000:
            res_levels = data.get("research", {})
            
            # Fetch the dynamic lists
            industry_b_list = [b for b, d in building_library.items() if d.get("group") == "industry"]
            recruit_b_list = [b for b, d in building_library.items() if d.get("group") == "recruitment"]

            # Sort provinces by queue length to spread out construction
            my_provs.sort(key=lambda p: len(p.get("deployment_queue", [])))

            for prov in my_provs:
                current_buildings = prov.get("buildings", [])
                queue = prov.get("deployment_queue", [])

                # Double check the queue so it doesn't build two at once in the same province
                if any(q.get("group") in ["industry", "recruitment"] for q in queue):
                    continue

                target_bldg = None
                has_factory = queries.has_basic_factory(prov)
                
                # Expand AI's building options dynamically based on the tile's current capacity
                groups_to_check = [industry_b_list]
                if has_factory:
                    groups_to_check.extend([recruit_b_list])
                    
                random.shuffle(groups_to_check)

                for b_list in groups_to_check:
                    if not b_list: continue
                    group_id = building_library[b_list[0]].get("group")
                    owned_in_group = [b for b in current_buildings if building_library.get(b, {}).get("group") == group_id]

                    if not owned_in_group:
                        target_bldg = b_list[0]
                    else:
                        for i, b_name in enumerate(b_list):
                            if b_name in owned_in_group:
                                if i + 1 < len(b_list):
                                    target_bldg = b_list[i+1]

                    if target_bldg:
                        # Check if the AI actually has the research required for this next tier
                        req_tech, req_lvl = queries.get_building_required_tech(target_bldg)
                        if req_tech and res_levels.get(req_tech, 0) < req_lvl:
                            target_bldg = None # Lacks the research, clear and check the next group
                            continue
                        break # Found a valid, fully-researched building!

                if target_bldg:
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
