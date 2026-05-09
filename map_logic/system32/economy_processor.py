import data.constants as c
from data import queries

def process_economy(self):
    """Calculates income, applies building yields, and deducts unit upkeep."""
    all_econ = queries.calculate_all_economies(self.map_data, self.nation_data)

    for name, stats in self.nation_data.items():
        # Explicitly skip the global events log 
        if name == "GLOBAL_EVENTS" or name in c.UNPLAYABLE_NATIONS or name not in all_econ:
            continue

        econ = all_econ[name]

        # Safely .get() the resource so it initializes to 0 if missing
        stats["manpower"] = stats.get("manpower", 0) + econ["total_inc"]["manpower"] - econ["upkeep"]["manpower"]
        stats["materials"] = stats.get("materials", 0) + econ["total_inc"]["materials"] - econ["upkeep"]["materials"]
        stats["fuel"] = stats.get("fuel", 0) + econ["total_inc"]["fuel"] - econ["upkeep"]["fuel"]

        # Prevent negative resources
        for res in ["manpower", "materials", "fuel"]:
            stats[res] = max(0, stats[res])

    return self.nation_data.get(self.player_country, {}).get("manpower", 0)

def process_queues(self):
    """Processes only the VERY FIRST item in the deployment queue sequentially."""
    unit_stats_path = c.UNIT_DATA_PATH
    building_stats_path = c.BUILDING_DATA_PATH
    
    # REPLACE DISK I/O WITH CACHED QUERIES
    unit_library = queries.get_unit_library()
    building_library = queries.get_building_library()

    for province in self.map_data.values():
        queue = province.get("deployment_queue", [])
        if not queue: continue
            
        # --- Combat Pause Mechanic ---
        if queries.is_province_in_active_combat(province, self.nation_data):
            continue
        # ----------------------------------
            
        # ONLY touch the first item!
        item = queue[0]
        
        # Backwards compatibility check and dynamic day-to-turn scaling
        if "days_remaining" in item:
            item["turns_remaining"] = max(1, item.pop("days_remaining") // c.DAYS_PER_TURN)
            
        item["turns_remaining"] -= 1
        
        if item["turns_remaining"] <= 0:
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
                
                max_health = stats.get("health", c.DEFAULT_UNIT_HP)
                attack = stats.get("attack", c.DEFAULT_UNIT_ATK)
                defense = stats.get("defense", c.DEFAULT_UNIT_DEF)
                speed = stats.get("speed", c.DEFAULT_UNIT_SPD)

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