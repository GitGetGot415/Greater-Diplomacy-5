import json
import os
from map_functions.logic import diplomacy_logic
from map_functions.logic import edit_province_ownership

def process_next_turn(self):
    days_to_advance = 5
    self.time_manager.process_time(days_to_advance)
    
    # 1. Process Diplomacy
    diplomacy_logic.process_diplomacy_turn(self)

    # 2. Process Movement (Handles the "stop to fight" logic)
    process_movement(self)
    
    # 3. Process Combat (New: Damage calculations)
    process_combat(self)
    
    # 4. Process Economy
    process_economy(self)
    
    # 5. Process Recruitment
    process_recruitment(self, days_to_advance)

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
            dest_owner = target_prov.get("owner", "empty")
            
            # Check for existing defenders before moving
            # We look for units belonging to anyone NOT the mover and NOT an ally
            defenders = [u for u in target_prov.get("units", []) 
                        if u["owner"] != unit["owner"] and u["owner"] not in player_data.get("allied_with", [])]

            can_enter = dest_owner in ["empty", "None", unit["owner"]] or \
                        dest_owner in player_data.get("at_war_with", []) or \
                        dest_owner in player_data.get("allied_with", [])

            if can_enter:
                unit["_current_province_id"] = target_id
                order["path"].pop(0)

                # --- UPDATED ANNEXATION LOGIC ---
                # Only conquer if there are NO defenders from an enemy nation
                if not defenders:
                    if dest_owner == "empty" or dest_owner in player_data.get("at_war_with", []):
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
    """Calculates income for ALL countries based on the provinces they own."""
    BASE_TAX = 10
    
    # 1. Tracker for this turn's earnings
    turn_income = {name: 0 for name in self.nation_data.keys()}

    # 2. Sum up province income
    for province in self.map_data.values():
        owner = province.get("owner")
        if owner in turn_income and owner != "None":
            turn_income[owner] += BASE_TAX

    # 3. Update the actual data
    player_earned = 0
    for country_name, amount in turn_income.items():
        if country_name in self.nation_data:
            self.nation_data[country_name]["money"] += amount
            # Manpower could have its own logic, but adding for now
            self.nation_data[country_name]["manpower"] = self.nation_data[country_name].get("manpower", 0) + amount
            
            if country_name == self.player_country:
                player_earned = amount

    return player_earned

def process_recruitment(self, days_passed):
    """Handles the deployment of units from the queue to the field."""
    
    # --- Load Unit Data for Stats Lookup ---
    unit_stats_path = 'map_functions/data/unit_data.json'
    unit_library = {}
    
    if os.path.exists(unit_stats_path):
        with open(unit_stats_path, 'r') as f:
            unit_library = json.load(f)

    for province in self.map_data.values():
        queue = province.get("deployment_queue", [])
        if not queue:
            continue
            
        # We use a list comprehension to find what's finished 
        # and keep what's still cooking
        still_deploying = []
        
        for item in queue:
            # Each 'Next Turn' represents 5 days
            item["days_remaining"] -= days_passed
            
            if item["days_remaining"] <= 0:
                # 1. Identify owner at time of deployment
                current_owner = province.get("owner", "None")
                unit_type = item["unit_type"]
                
                # 2. Look up starting health from unit_data.json
                # Default to 100 if the unit type isn't found in the JSON
                stats = unit_library.get(unit_type, {})
                max_health = stats.get("health", 100)
                unit_speed = stats.get("speed", 1) # <--- GET SPEED HERE
                
                # 3. Create the unified Unit JSON object
                new_unit_data = {
                    "type": unit_type,
                    "owner": current_owner,
                    "health": max_health,
                    "max_health": max_health, # Useful for showing health bars later
                    "speed": unit_speed, # <--- ADD SPEED HERE
                    "attack": stats.get("attack", 5),   # ADDED
                    "defense": stats.get("defense", 0), # ADDED
                    "order": {"type": "MOVE", "path": []} # Initialize with an empty path list
                }
                
                province["units"].append(new_unit_data)
            else:
                # Keep in queue
                still_deploying.append(item)
        
        # Update the province queue with only the remaining items
        province["deployment_queue"] = still_deploying