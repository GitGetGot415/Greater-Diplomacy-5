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
        self.unit_economy["materials"] = min(self.unit_economy.get("materials", 0) + upkeep["materials"], c.TACTICAL_MAX_MATERIALS)
        self.unit_economy["fuel"] = min(self.unit_economy.get("fuel", 0) + upkeep["fuel"], c.TACTICAL_MAX_FUEL)

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
                if item.get("order_type") == "CORE":
                    if current_owner not in province.get("cores", []):
                        province.setdefault("cores", []).append(current_owner)
                    if current_owner == self.player_country:
                        self.show_feedback(f"CORED: Province {province.get('id')}")
                        
                elif item.get("order_type") == "REMOVE_CORE":
                    # Remove all foreign cores, solidify player core
                    province["cores"] = [current_owner]
                    
                    # Create the new rebellion tag
                    r_idx = 1
                    while f"rebellion {r_idx}" in self.nation_data:
                        r_idx += 1
                    reb_id = f"rebellion {r_idx}"
                    
                    reb_data = {
                        "name": f"Rebellion {r_idx}",
                        "color": [200, 30, 30],
                        "is_playable": True,
                        "research": {},
                        "at_war_with": [current_owner],
                        "allied_with": [],
                        "pending_diplomacy": {},
                        "claims": [],
                        "claim_queue": [],
                        "revoke_queue": [],
                        "return_queue": [],
                        "puppets": [],
                        "master": "",
                        "puppet_type": "",
                        "faction": "",
                        "is_faction_leader": False,
                        "manpower": 0,
                        "materials": 0,
                        "fuel": 0
                    }
                    self.nation_data[reb_id] = reb_data
                    if reb_id not in self.nation_data[current_owner].get("at_war_with", []):
                        self.nation_data[current_owner].setdefault("at_war_with", []).append(reb_id)
                        
                    if hasattr(self, 'nation_colors'):
                        self.nation_colors[reb_id] = (200, 30, 30)

                    # Determine Militia Level natively
                    current_year = self.time_manager.year
                    tech_tree = queries.get_tech_tree()
                    militia_years = tech_tree.get("militia", {}).get("years", [1910, 1915, 1920, 1925, 1930, 1935])
                    
                    militia_lvl = 1
                    for i, y in enumerate(militia_years):
                        if current_year >= y:
                            militia_lvl = i + 1
                    
                    reb_data["research"]["militia"] = militia_lvl
                    militia_name = queries.get_best_preferred_unit(reb_data["research"], unit_library, ["Militia"]) or "Militia I"
                    
                    # Transfer ownership
                    from map_logic.system32 import edit_province_ownership
                    edit_province_ownership.conquer_province(self, province, reb_id)
                    
                    # CRITICAL FIX: Override the turn start owner so it doesn't instantly auto-revert to the player!
                    province["_turn_start_owner"] = reb_id
                    
                    # Spawn 5 Militia
                    for _ in range(5):
                        u_dict = queries.create_unit_dict(militia_name, reb_id, unit_library)
                        u_dict["custom_name"] = queries.generate_unit_custom_name(u_dict, active_unit_counters)
                        province.setdefault("units", []).append(u_dict)
                        
                    # Queue a core for the rebellion so they solidify the tile if not crushed
                    core_order = {
                        "order_type": "CORE",
                        "item_name": "Core Territory",
                        "turns_remaining": 1,
                        "group": "administration",
                        "refund": {"cost_materials": 0, "cost_manpower": 0, "cost_fuel": 0}
                    }
                    province.setdefault("building_queue", []).append(core_order)
                    
                    if current_owner == self.player_country:
                        self.show_feedback(f"CORES REMOVED: Rebellion Sparked in {province.get('id')}!")
                        
                else:
                    b_name = item.get("item_name")
                    if b_name:
                        # Ensure higher levels overwrite lower levels of the same type
                        is_industrial = "Workshop" in b_name or "Factory" in b_name
                        is_refinery = "Refinery" in b_name
                        is_recruitment = "Recruitment" in b_name
                        
                        new_buildings = []
                        for b in province.get("buildings", []):
                            keep = True
                            if is_industrial and ("Workshop" in b or "Factory" in b):
                                keep = False
                            if is_refinery and "Refinery" in b:
                                keep = False
                            if is_recruitment and "Recruitment" in b:
                                keep = False
                            
                            if keep:
                                new_buildings.append(b)
                                
                        province["buildings"] = new_buildings
                        province["buildings"].append(b_name)
                        
                        if current_owner == self.player_country:
                            self.show_feedback(f"CONSTRUCTED: {b_name}")
        
                # --- CRITICAL FIX: Safely remove the item, accounting for list replacement ---
                if item in b_queue:
                    b_queue.remove(item)
                if item in province.get("building_queue", []):
                    province["building_queue"].remove(item)

        # --- UNIT QUEUE ---
        u_queue = province.get("unit_queue", [])
        if u_queue and not in_combat:
            item = u_queue[0]
            if "days_remaining" in item:
                item["turns_remaining"] = max(1, item.pop("days_remaining") // c.DEFAULT_DAYS_PER_TURN)
            
            item["turns_remaining"] -= 1
            
            if item["turns_remaining"] <= 0:
                unit_type = item["unit_type"]
                new_unit_data = queries.create_unit_dict(unit_type, current_owner, unit_library)
                
                # Apply dynamic custom name for standard unit recruitment
                new_unit_data["custom_name"] = queries.generate_unit_custom_name(new_unit_data, active_unit_counters)
                
                province["units"].append(new_unit_data)
                if current_owner == self.player_country:
                    self.show_feedback(f"DEPLOYED: {unit_type}")
        
                # --- CRITICAL FIX: Safely remove the item, accounting for list replacement ---
                if item in u_queue:
                    u_queue.remove(item)
                if item in province.get("unit_queue", []):
                    province["unit_queue"].remove(item)