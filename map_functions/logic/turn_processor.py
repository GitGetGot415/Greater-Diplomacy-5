import json
import os
import math
from map_functions.logic import diplomacy_logic
from map_functions.logic import edit_province_ownership
from map_functions.logic import ai_movement
from data.constants import BASE_YIELDS, UPKEEP_MODIFIER, DAYS_PER_TURN, WATER_TERRAINS, UNPLAYABLE_NATIONS

def prepare_turn(self):
    """Phase 1: Calculate diplomacy and generate AI movement paths."""
    diplomacy_logic.process_diplomacy_turn(self)
    ai_movement.process_ai_unit_orders(self)

def resolve_turn(self):
    """Phase 2: Execute all moves, combat, and advance the clock."""
    days_to_advance = DAYS_PER_TURN
    self.time_manager.process_time(days_to_advance)
    
    process_conversions(self, days_to_advance)
    process_movement(self)
    process_combat(self)
    check_for_post_combat_captures(self)
    process_economy(self)
    
    # 5. Process Unified Queue (Sequential)
    process_queues(self, days_to_advance)
    
    process_national_research(self, days_to_advance)

def process_next_turn(self):
    """Legacy compatibility just in case it's called elsewhere."""
    prepare_turn(self)
    resolve_turn(self)

def process_conversions(self, days_passed):
    """Processes the 10-day timer for transferring units into Convoys and back."""
    for province in self.map_data.values():
        for unit in province.get("units", []):
            order = unit.get("order")
            if isinstance(order, dict) and order.get("type") == "CONVERT":
                order["days_left"] -= days_passed
                
                if order["days_left"] <= 0:
                    if order.get("to") == "Convoy":
                        unit["original_type"] = unit["type"]
                        unit["original_speed"] = unit.get("speed", 1)
                        # Embed the name here!
                        unit["type"] = f"Convoy ({unit['type']})"
                        unit["speed"] = 1
                        unit["naval_unit"] = True
                    else:
                        unit["type"] = unit.get("original_type", "Infantry")
                        unit["speed"] = unit.get("original_speed", 1)
                        unit["naval_unit"] = False
                        if "original_type" in unit: del unit["original_type"]
                        if "original_speed" in unit: del unit["original_speed"]
                        
                    # Reset back to a blank move order so they can be selected again
                    unit["order"] = {"type": "MOVE", "path": []}

def process_national_research(self, days_passed):
    # Load template to know costs
    with open("data/json/research_template.json", "r") as f:
        template = json.load(f)
    
    points_per_day = 10
    total_points_generated = days_passed * points_per_day

    for country_name, country_data in self.nation_data.items():
        queue = country_data.get("research_queue", [])
        if not queue: continue

        # We iterate backwards through the queue so we can safely remove items
        for i in range(len(queue) - 1, -1, -1):
            project = queue[i]
            tech_key = project["tech_name"]
            
            # Use 'points_remaining' instead of 'days_remaining'
            # (First time initialization if coming from an old save)
            if "points_remaining" not in project:
                project["points_remaining"] = project.get("days_remaining", 30) * points_per_day
            
            project["points_remaining"] -= total_points_generated

            if project["points_remaining"] <= 0:
                country_data["research"][tech_key] = country_data["research"].get(tech_key, 0) + 1
                
                # CLEANUP: Remove from progress cache if it was there
                if "research_progress" in country_data:
                    country_data["research_progress"].pop(tech_key, None)
                
                if country_name == self.player_country:
                    self.show_feedback(f"TECH FINISHED: {tech_key.replace('_', ' ').title()}")
                
                # Remove completed tech from queue
                queue.pop(i)

def process_combat(self):
    """Calculates turn-based damage for units sharing a province."""
    for province in self.map_data.values():
        units = province.get("units", [])
        if len(units) < 2:
            continue
            
        # Group units by owner to calculate total attack per side
        sides = {}
        for u in units:
            owner = u["owner"]
            if owner not in sides:
                sides[owner] = {"units": [], "total_atk": 0}
            sides[owner]["units"].append(u)
            # Fetch attack power (default to 5 if missing)
            sides[owner]["total_atk"] += u.get("attack", 5)

        owners = list(sides.keys())
        for i in range(len(owners)):
            for j in range(i + 1, len(owners)):
                nation_a = owners[i]
                nation_b = owners[j]
                
                # Check if they are actually at war
                at_war = nation_b in self.nation_data.get(nation_a, {}).get("at_war_with", [])
                
                if at_war:
                    # Side A attacks Side B
                    apply_group_damage(sides[nation_a]["total_atk"], sides[nation_b]["units"])
                    # Side B attacks Side A
                    apply_group_damage(sides[nation_b]["total_atk"], sides[nation_a]["units"])

        # Remove dead units (HP <= 0)
        province["units"] = [u for u in units if u.get("health", 0) > 0]

def check_for_post_combat_captures(self):
    """Assigns province ownership to units standing in an undefended enemy province."""
    from map_functions.logic import edit_province_ownership
    
    for province in self.map_data.values():
        units = province.get("units", [])
        if not units:
            continue
            
        current_owner = province.get("owner", "Unclaimed")
        
        # Get a list of unique owners of units currently in the tile
        unit_owners = list(set(u["owner"] for u in units))
        
        # If the current owner still has units here, they successfully defended it.
        if current_owner in unit_owners:
            continue
            
        # Tally HP for all foreign units on the tile that are eligible to capture it
        hp_totals = {}
        for u in units:
            o = u["owner"]
            player_data = self.nation_data.get(o, {})
            at_war = current_owner in player_data.get("at_war_with", [])
            is_unclaimed = current_owner in ["Unclaimed", "None", ""]
            
            # Flip ownership if the tile is unclaimed or if they are at war with the owner
            if is_unclaimed or at_war:
                hp_totals[o] = hp_totals.get(o, 0) + u.get("health", 0)
        
        if not hp_totals:
            continue

        # Find the nation(s) with the highest combined HP
        max_hp = -1
        top_nations = []
        for o, hp in hp_totals.items():
            if hp > max_hp:
                max_hp = hp
                top_nations = [o]
            elif hp == max_hp:
                top_nations.append(o)
                
        # If one clear winner, they take it
        if len(top_nations) == 1:
            edit_province_ownership.conquer_province(self, province, top_nations[0])
        # If there's a tie, it becomes unclaimed
        elif len(top_nations) > 1:
            edit_province_ownership.conquer_province(self, province, "Unclaimed")
                
def apply_group_damage(total_atk, target_units):
    """Distributes total attack among target units, reduced by their individual defense."""
    if not target_units: return
    # Simple distribution: Divide total attack by number of units
    damage_per_unit = total_atk / len(target_units)
    
    for u in target_units:
        defense = u.get("defense", 0)
        actual_dmg = max(0, damage_per_unit - defense)
        u["health"] -= actual_dmg

def process_movement(self):
    moving_units = []
    for province in self.map_data.values():
        units_to_keep = []
        for unit in province.get("units", []):
            order = unit.get("order")
            if order and order.get("type") == "MOVE" and order.get("path"):
                unit["_current_province_id"] = province["id"]
                moving_units.append(unit)
            else:
                units_to_keep.append(unit)
        province["units"] = units_to_keep

    if not moving_units: return
    max_speed = max(unit.get("speed", 1) for unit in moving_units)

    for step in range(max_speed):
        for unit in moving_units:
            # --- THE BUG FIX ---
            # Explicitly check if this individual unit has run out of moves
            if step >= unit.get("speed", 1):
                continue
                
            order = unit.get("order")
            if not order or not order.get("path"): continue

            target_id = order["path"][0]
            target_prov = self.id_to_province.get(target_id)
            if not target_prov: continue

            player_data = self.nation_data.get(unit["owner"], {})
            dest_owner = target_prov.get("owner", "Unclaimed")
            
            # Check for existing defenders before moving
            # We look for units belonging to anyone NOT the mover and NOT an ally
            defenders = [u for u in target_prov.get("units", []) 
                        if u["owner"] != unit["owner"] and u["owner"] not in player_data.get("allied_with", [])]

            can_enter = dest_owner in ["Unclaimed", "None", unit["owner"], "Ocean", "Lakes"] or \
                        dest_owner in player_data.get("at_war_with", []) or \
                        dest_owner in player_data.get("allied_with", [])

            if can_enter:
                unit["_current_province_id"] = target_id
                order["path"].pop(0)

                # Only conquer if there are NO defenders from an enemy nation
                if not defenders:
                    if dest_owner == "Unclaimed" or dest_owner in player_data.get("at_war_with", []):
                        edit_province_ownership.conquer_province(self, target_prov, unit["owner"])

                # Stop if an enemy was present
                if defenders:
                    order["path"] = [] 
            else:
                order["path"] = []

        # Sync units back to provinces so units moving later in the same sub-step "see" each other
        for unit in moving_units:
            prov = self.id_to_province.get(unit["_current_province_id"])
            
            if not any(u is unit for u in prov["units"]): 
                prov["units"].append(unit)
                
        if step < max_speed - 1:
            # Create a set of memory IDs for ultra-fast lookup
            moving_ids = {id(m) for m in moving_units} 
            
            for province in self.map_data.values():
                province["units"] = [u for u in province["units"] if id(u) not in moving_ids]

def process_economy(self):
    """Calculates income, applies building yields, and deducts unit upkeep."""
    all_econ = self.calculate_all_economies()

    for name, stats in self.nation_data.items():
        if name in UNPLAYABLE_NATIONS or name not in all_econ:
            continue

        econ = all_econ[name]

        stats["manpower"] += econ["total_inc"]["manpower"] - econ["upkeep"]["manpower"]
        stats["materials"] += econ["total_inc"]["materials"] - econ["upkeep"]["materials"]
        stats["fuel"] += econ["total_inc"]["fuel"] - econ["upkeep"]["fuel"]

        # Prevent negative resources
        for res in ["manpower", "materials", "fuel"]:
            stats[res] = max(0, stats[res])

    return self.nation_data.get(self.player_country, {}).get("manpower", 0)

def process_queues(self, days_passed):
    """Processes only the VERY FIRST item in the deployment queue sequentially."""
    unit_stats_path = 'data/json/unit_data.json'
    building_stats_path = 'data/json/building_data.json'
    
    unit_library = {}
    building_library = {}
    
    if os.path.exists(unit_stats_path):
        with open(unit_stats_path, 'r') as f: unit_library = json.load(f)
    if os.path.exists(building_stats_path):
        with open(building_stats_path, 'r') as f: building_library = json.load(f)

    for province in self.map_data.values():
        queue = province.get("deployment_queue", [])
        if not queue: continue
            
        # ONLY touch the first item!
        item = queue[0]
        item["days_remaining"] -= days_passed
        
        if item["days_remaining"] <= 0:
            current_owner = province.get("owner", "None")
            
            # IS BUILDING?
            if item.get("order_type") == "BUILDING":
                b_name = item["item_name"]
                b_data = building_library.get(b_name, {})
                
                current_buildings = province.get("buildings", [])
                updated_buildings = [b for b in current_buildings 
                                     if building_library.get(b, {}).get("group") != b_data.get("group")]
                
                updated_buildings.append(b_name)
                province["buildings"] = updated_buildings
                
                if current_owner == self.player_country:
                    self.show_feedback(f"CONSTRUCTION COMPLETE: {b_name}")

            # IS UNIT?
            else:
                unit_type = item["unit_type"]
                stats = unit_library.get(unit_type, {})
                
                max_health = stats.get("health", 100)
                attack = stats.get("attack", 5)
                defense = stats.get("defense", 0)
                speed = stats.get("speed", 1)

                new_unit_data = {
                    "type": unit_type,
                    "owner": current_owner,
                    "health": max_health,
                    "max_health": max_health,
                    "speed": speed,
                    "attack": attack,
                    "defense": defense,
                    "level": 0,
                    "order": {"type": "MOVE", "path": []}
                }
                
                province["units"].append(new_unit_data)
                if current_owner == self.player_country:
                    self.show_feedback(f"DEPLOYED: {unit_type}")
            
            # Remove the finished item so the next one can start on the next turn
            queue.pop(0)