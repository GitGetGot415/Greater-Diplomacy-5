import data.constants as c
from data import queries

def process_economy(self):
    """Calculates income, applies building yields, and deducts unit upkeep."""
    
    # --- TACTICAL ECONOMY OVERRIDE ---
    if getattr(self, 'tactical_mode', False) and getattr(self, 'player_unit', None):
        u_type = self.player_unit.get("original_type", self.player_unit.get("type"))
        stats = queries.get_unit_library().get(u_type, {})
        
        upkeep = queries.get_unit_upkeep(stats)
        
        self.unit_economy["fuel_inc"] = upkeep["fuel"] # Stored cleanly for movement calcs
        
        self.unit_economy["manpower"] = min(self.unit_economy.get("manpower", 0) + upkeep["manpower"], c.TACTICAL_MAX_MANPOWER)
        self.unit_economy["materials"] = min(self.unit_economy.get("materials", 0) + upkeep["materials"], stats.get("cost_materials", 9999))
        self.unit_economy["fuel"] = min(self.unit_economy.get("fuel", 0) + upkeep["fuel"], stats.get("cost_fuel", 0))

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
    """Processes only the VERY FIRST item in the unit and building queues sequentially."""
    # REPLACE DISK I/O WITH CACHED QUERIES
    unit_library = queries.get_unit_library()
    building_library = queries.get_building_library()

    # --- NEW: Check if AI is disabled to freeze their queues ---
    ai_disabled_raw = self.scenario_settings.get("ai_disabled", c.DEFAULT_AI_DISABLED)
    ai_disabled = str(ai_disabled_raw).lower() == "true"
    
    # --- Build active unit counters once per turn for new deployments ---
    active_unit_counters = queries.build_active_unit_counters(self.map_data)

    for province in self.map_data.values():
        current_owner = province.get("owner", "None")
        
        # Freeze AI queues if AI is disabled
        if ai_disabled and current_owner not in getattr(self, 'active_players', [self.player_country]):
            continue

        in_combat = queries.is_province_in_active_combat(province, self.nation_data)
        
        # --- BUILDING QUEUE ---
        b_queue = province.get("building_queue", [])
        if b_queue and not in_combat:
            item = b_queue[0]
            if "days_remaining" in item:
                item["turns_remaining"] = max(1, item.pop("days_remaining") // c.DEFAULT_DAYS_PER_TURN)
            
            item["turns_remaining"] -= 1
            
            if item["turns_remaining"] <= 0:
                b_name = item.get("item_name")
                if b_name:
                    province.setdefault("buildings", []).append(b_name)
                    if current_owner == self.player_country:
                        self.show_feedback(f"CONSTRUCTED: {b_name}")
            
                b_queue.pop(0)

        # --- UNIT QUEUE ---
        u_queue = province.get("unit_queue", [])
        if u_queue and not in_combat:
            item = u_queue[0]
            if "days_remaining" in item:
                item["turns_remaining"] = max(1, item.pop("days_remaining") // c.DEFAULT_DAYS_PER_TURN)
            
            item["turns_remaining"] -= 1
            
            if item["turns_remaining"] <= 0:
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
                
                # Apply dynamic custom name for standard unit recruitment
                new_unit_data["custom_name"] = queries.generate_unit_custom_name(new_unit_data, active_unit_counters)
                
                province["units"].append(new_unit_data)
                if current_owner == self.player_country:
                    self.show_feedback(f"DEPLOYED: {unit_type}")
            
                u_queue.pop(0)