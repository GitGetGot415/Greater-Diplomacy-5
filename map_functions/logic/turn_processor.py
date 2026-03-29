import json
import os
import math
from map_functions.logic import diplomacy_logic
from map_functions.logic import edit_province_ownership
from map_functions.data.building_data import BUILDING_LIBRARY

def process_next_turn(self):
    days_to_advance = 5
    self.time_manager.process_time(days_to_advance)
    
    # 1. Process Diplomacy
    diplomacy_logic.process_diplomacy_turn(self)

    # 2. Process Movement (Handles the "stop to fight" logic)
    process_movement(self)
    
    # 3. Process Combat (New: Damage calculations)
    process_combat(self)

    # 4. NEW: Check if winners of a battle should flip the province ownership
    check_for_post_combat_captures(self)
    
    # 4. Process Economy
    process_economy(self)
    
    # 5. Process Recruitment
    process_recruitment(self, days_to_advance)

    # 6. Process Construction
    process_construction(self, days_to_advance)

    # 7. Process National Research
    process_national_research(self, days_to_advance)

def process_construction(self, days_passed):
    for province in self.map_data.values():
        queue = province.get("deployment_queue", [])
        if not queue: continue
            
        still_deploying = []
        for item in queue:
            if item.get("order_type") == "BUILDING":
                item["days_remaining"] -= days_passed
                
                if item["days_remaining"] <= 0:
                    b_name = item["item_name"]
                    b_data = BUILDING_LIBRARY[b_name]
                    
                    current_buildings = province.get("buildings", [])
                    # OVERWRITE LOGIC:
                    # Remove any building that belongs to the same group (e.g., industry or refinery)
                    updated_buildings = [b for b in current_buildings 
                                    if BUILDING_LIBRARY.get(b, {}).get("group") != b_data["group"]]
                    
                    updated_buildings.append(b_name)
                    province["buildings"] = updated_buildings
                    
                    if province.get("owner") == self.player_country:
                        self.show_feedback(f"CONSTRUCTION COMPLETE: {b_name}")
                else:
                    still_deploying.append(item)
            else:
                # Keep units in the queue
                still_deploying.append(item)
        
        province["deployment_queue"] = still_deploying

def process_national_research(self, days_passed):
    # Load template to know costs
    with open("map_functions/data/research_template.json", "r") as f:
        template = json.load(f)
    
    points_per_day = 10
    total_points_generated = days_passed * points_per_day # e.g., 50 points

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
        
        # If there's more than one owner present, it's still a contested combat zone
        if len(unit_owners) > 1:
            continue
            
        # There is exactly one nation with units here
        occupier = unit_owners[0]
        
        # If the occupier doesn't own the tile
        if occupier != current_owner:
            player_data = self.nation_data.get(occupier, {})
            at_war = current_owner in player_data.get("at_war_with", [])
            is_unclaimed = current_owner in ["Unclaimed", "None", ""]
            
            # Flip ownership if the tile is unclaimed or if they are at war with the owner
            if is_unclaimed or at_war:
                edit_province_ownership.conquer_province(self, province, occupier)
                
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

            can_enter = dest_owner in ["Unclaimed", "None", unit["owner"]] or \
                        dest_owner in player_data.get("at_war_with", []) or \
                        dest_owner in player_data.get("allied_with", [])

            if can_enter:
                unit["_current_province_id"] = target_id
                order["path"].pop(0)

                # --- UPDATED ANNEXATION LOGIC ---
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
            if unit not in prov["units"]: prov["units"].append(unit)
        if step < max_speed - 1:
            for province in self.map_data.values():
                province["units"] = [u for u in province["units"] if u not in moving_units]

def process_economy(self):
    """Calculates income and deducts unit upkeep for ALL countries."""
    # yes i know the values here are comically high just keep it this way (for testing)
    YIELD_MONEY = 999500
    YIELD_MANPOWER = 99950
    YIELD_MATERIALS = 999100
    YIELD_FUEL = 9991
    UPKEEP_MODIFIER = 0.05

    # 1. Load Unit Library for cost reference
    unit_stats_path = 'map_functions/data/unit_data.json'
    with open(unit_stats_path, 'r') as f:
        unit_library = json.load(f)

    # 2. Trackers
    turn_data = {name: {"inc": 0, "upkeep": {"money":0, "manpower":0, "materials":0, "fuel":0}} 
                 for name in self.nation_data.keys()}

    # 3. Sum Province Income
    for province in self.map_data.values():
        owner = province.get("owner")
        if owner in turn_data and owner not in ["None", "Unclaimed", "Ocean", "Lakes"]:
            turn_data[owner]["inc"] += 1

    # 4. Calculate Upkeep
    for province in self.map_data.values():
        for unit in province.get("units", []):
            owner = unit["owner"]
            stats = unit_library.get(unit["type"])
            if owner in turn_data and stats:
                turn_data[owner]["upkeep"]["money"] += stats.get("cost_money", 0) * UPKEEP_MODIFIER
                turn_data[owner]["upkeep"]["manpower"] += stats.get("cost_manpower", 0) * UPKEEP_MODIFIER
                turn_data[owner]["upkeep"]["materials"] += stats.get("cost_materials", 0) * UPKEEP_MODIFIER
                turn_data[owner]["upkeep"]["fuel"] += stats.get("cost_fuel", 0) * UPKEEP_MODIFIER

    # 5. Apply to Nation Data
    for name, data in turn_data.items():
        stats = self.nation_data[name]
        stats["money"] += (data["inc"] * YIELD_MONEY) - data["upkeep"]["money"]
        stats["manpower"] += (data["inc"] * YIELD_MANPOWER) - data["upkeep"]["manpower"]
        stats["materials"] += (data["inc"] * YIELD_MATERIALS) - data["upkeep"]["materials"]
        stats["fuel"] += (data["inc"] * YIELD_FUEL) - data["upkeep"]["fuel"]

        # Clamp resources at 0 so they don't go negative
        for res in ["money", "manpower", "materials", "fuel"]:
            stats[res] = max(0, stats[res])

    return self.nation_data.get(self.player_country, {}).get("money", 0)

def process_recruitment(self, days_passed):
    """Handles the deployment of units from the queue to the field with dynamic scaling."""
    unit_stats_path = 'map_functions/data/unit_data.json'
    unit_library = {}
    
    if os.path.exists(unit_stats_path):
        with open(unit_stats_path, 'r') as f:
            unit_library = json.load(f)

    for province in self.map_data.values():
        queue = province.get("deployment_queue", [])
        if not queue: continue
            
        still_deploying = []
        for item in queue:
            # FIX: Skip building orders (they use 'item_name' and 'order_type': 'BUILDING')
            if item.get("order_type") == "BUILDING":
                still_deploying.append(item)
                continue

            item["days_remaining"] -= days_passed
            
            if item["days_remaining"] <= 0:
                current_owner = province.get("owner", "None")
                unit_type = item["unit_type"]
                
                # 1. Get Base Stats from Library
                stats = unit_library.get(unit_type, {})
                
                # 2. Dynamic Scaling for Infantry
                if unit_type == "Infantry":
                    # Get research level for this country (Default to 1800)
                    owner_data = self.nation_data.get(current_owner, {})
                    inf_level = owner_data.get("research", {}).get("infantry", 1800)
                    
                    n = inf_level - 1800
                    # HP = 1000 * 1.01^n
                    max_health = int(1000 * math.pow(1.01, n))
                    # ATK = 100 * 1.01^n
                    attack = int(100 * math.pow(1.01, n))
                    defense = stats.get("defense", 0) # Keep base defense or scale if desired
                    speed = stats.get("speed", 1)
                else:
                    # Standard logic for manually defined units (Cavalry I, etc.)
                    max_health = stats.get("health", 100)
                    attack = stats.get("attack", 5)
                    defense = stats.get("defense", 0)
                    speed = stats.get("speed", 1)

                # 3. Create the Unit object
                new_unit_data = {
                    "type": unit_type,
                    "owner": current_owner,
                    "health": max_health,
                    "max_health": max_health,
                    "speed": speed,
                    "attack": attack,
                    "defense": defense,
                    "level": inf_level if unit_type == "Infantry" else 0, # Tag with level
                    "order": {"type": "MOVE", "path": []}
                }
                
                province["units"].append(new_unit_data)
            else:
                still_deploying.append(item)
        
        province["deployment_queue"] = still_deploying