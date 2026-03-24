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
    moves_to_execute = []
    for color_key, province in self.map_data.items():
        # Using a list copy to safely modify the list
        units = list(province.get("units", []))
        province["units"] = [] # Temporarily clear to redistribute
        
        remaining_in_tile = []
        for unit in units:
            order = unit.get("order")
            if order and order.get("type") == "MOVE":
                moves_to_execute.append((unit, order["target_id"]))
                # Clear order so they don't move again next turn unless told
                unit["order"] = {} 
            else:
                remaining_in_tile.append(unit)
        
        province["units"] = remaining_in_tile

    # Place moving units
    for unit, target_id in moves_to_execute:
        target_province = self.id_to_province.get(target_id)
        if target_province:
            target_province["units"].append(unit)

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
                
                # 3. Create the unified Unit JSON object
                new_unit_data = {
                    "type": unit_type,
                    "owner": current_owner,
                    "health": max_health,
                    "max_health": max_health # Useful for showing health bars later
                }
                
                province["units"].append(new_unit_data)
            else:
                # Keep in queue
                still_deploying.append(item)
        
        # Update the province queue with only the remaining items
        province["deployment_queue"] = still_deploying