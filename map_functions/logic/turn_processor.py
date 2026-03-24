import json
import os
from map_functions.logic import diplomacy_logic

def process_next_turn(self):
    days_to_advance = 5
    self.time_manager.process_time(days_to_advance)
    
    # 1. Process Diplomacy
    diplomacy_logic.process_diplomacy_turn(self)

    process_movement(self)
    
    # 2. Process Economy
    process_economy(self)
    
    # 3. Process Recruitment
    process_recruitment(self, days_to_advance)

def process_movement(self):
    # 1. Collect all units that have movement orders
    moving_units = []
    for province in self.map_data.values():
        units_to_keep = []
        for unit in province.get("units", []):
            order = unit.get("order")
            if order and order.get("type") == "MOVE":
                # Inject the current location so we know where they start
                unit["_current_province_id"] = province["id"]
                # Look up speed from unit_data if not already in the unit dict
                # (You may want to ensure speed is added during recruitment)
                moving_units.append(unit)
            else:
                units_to_keep.append(unit)
        province["units"] = units_to_keep

    # 2. Determine the maximum speed among all moving units
    # This tells us how many "sub-steps" the turn has
    if not moving_units:
        return

    # We'll use 1 as a floor, but your JSON says 2 or 3 for Hilux/Tanks
    max_speed = max(unit.get("speed", 1) for unit in moving_units)

    # 3. Process steps one by one
    for step in range(max_speed):
        for unit in moving_units:
            # Skip if unit finished its moves or its order was cancelled/stopped
            unit_speed = unit.get("speed", 1)
            order = unit.get("order")
            
            if step >= unit_speed or not order:
                continue

            current_prov = self.id_to_province.get(unit["_current_province_id"])
            target_id = order.get("target_id")
            target_prov = self.id_to_province.get(target_id)

            if not target_prov:
                continue

            # --- THE "STOP" LOGIC ---
            # Check if we can enter the target tile
            old_owner = target_prov.get("owner", "empty")
            player_data = self.nation_data.get(unit["owner"], {})
            at_war = old_owner in player_data.get("at_war_with", [])
            is_allied = old_owner in player_data.get("allied_with", [])
            is_self = old_owner == unit["owner"]
            is_empty = old_owner == "empty"

            # Check if tile is occupied by an enemy unit (even if owner is empty/neutral)
            enemy_present = any(u["owner"] in player_data.get("at_war_with", []) for u in target_prov.get("units", []))

            # Rule: Stop if tile is owned by someone else NOT at war and NOT allied
            # or if there is an enemy unit there.
            can_enter = is_empty or is_self or at_war or is_allied
            
            if can_enter and not enemy_present:
                # Execute the step
                unit["_current_province_id"] = target_id
                
                # If we move onto an empty/enemy province, conquer it
                if is_empty or at_war:
                    from map_functions.logic import edit_province_ownership
                    edit_province_ownership.conquer_province(self, target_prov, unit["owner"])
                
                # In your request: "if speed is 2, move to a tile, then move to another"
                # Currently, orders only have ONE target_id. 
                # To support speed 3 properly, your Order Screen needs to allow 
                # a list of IDs. For now, this logic handles "Move 1 tile per step".
                # If the unit reaches its target, we clear the order.
                unit["order"] = {} 
            else:
                # BLOCKED: Stop and cancel all future moves for this turn
                unit["order"] = {}

    # 4. Finalize: Put units back into their final province lists
    for unit in moving_units:
        final_prov = self.id_to_province.get(unit["_current_province_id"])
        if "_current_province_id" in unit:
            del unit["_current_province_id"]
        final_prov["units"].append(unit)

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
                    "order": {"type": "MOVE", "path": []} # Initialize with an empty path list
                }
                
                province["units"].append(new_unit_data)
            else:
                # Keep in queue
                still_deploying.append(item)
        
        # Update the province queue with only the remaining items
        province["deployment_queue"] = still_deploying