import json
import os
from map_logic.diplomacy import diplomacy_logic
from map_logic.rendering import edit_province_ownership
from map_logic.ai import ai_movement, ai_research, ai_construction, ai_diplomacy
import data.constants as c
from data import queries

def prepare_turn(self):
    """Phase 1: Calculate diplomacy and generate AI movement paths."""
    print("\n" + "="*40)
    print("--- [PHASE 1] AI PREPARATION START ---")
    
    # --- PROACTIVE AI REMOVED ---
    # print("[SYSTEM] Running AI Grand Strategy...")
    # ai_diplomacy.process_ai_grand_strategy(self)
    
    print("[SYSTEM] Processing Pending Diplomacy...")
    diplomacy_logic.process_diplomacy_turn(self)
    
    print("[SYSTEM] Running AI Research...")
    ai_research.process_ai_research(self)
    
    print("[SYSTEM] Running AI Economy & Construction...")
    ai_construction.process_ai_economy_decisions(self)
    
    print("[SYSTEM] Generating AI Movement Orders...")
    ai_movement.process_ai_unit_orders(self)
    print("--- [PHASE 1] COMPLETE ---")

def resolve_turn(self):
    """Phase 2: Execute all moves, combat, and advance the clock."""
    print("\n--- [PHASE 2] TURN RESOLUTION START ---")
    days_to_advance = c.DAYS_PER_TURN
    self.time_manager.process_time(days_to_advance)
    
    print("[SYSTEM] Executing Unit Orders & Combat...")
    process_conversions(self)
    
    # --- NEW: Pre-Movement Combat Mechanics ---
    process_pinning(self)
    process_meeting_engagements(self)
    # ------------------------------------------
    
    process_movement(self)
    process_combat(self)
    check_for_post_combat_captures(self)
    
    print("[SYSTEM] Calculating Economy & Processing Queues...")
    process_economy(self)
    
    # 5. Process Unified Queue (Sequential)
    process_queues(self)
    
    process_national_research(self)
    print("--- [PHASE 2] COMPLETE ---")
    print("="*40 + "\n")

def process_next_turn(self):
    """Legacy compatibility just in case it's called elsewhere."""
    prepare_turn(self)
    resolve_turn(self)

def process_pinning(self):
    """Rule: Units being attacked from a tile must defend the tile they're on, unless moving to friendly territory."""
    incoming_attacks = {}
    for province in self.map_data.values():
        for unit in province.get("units", []):
            order = unit.get("order")
            if order and order.get("type") == "MOVE" and order.get("path"):
                dest_id = order["path"][0]
                dest_prov = self.id_to_province.get(dest_id)
                if dest_prov and queries.is_hostile_territory(unit["owner"], dest_prov.get("owner", "Unclaimed"), self.nation_data):
                    # FIX: Track the origin province ID (province["id"]) along with the unit
                    incoming_attacks.setdefault(dest_id, []).append((unit, province["id"]))

    for province in self.map_data.values():
        for unit in province.get("units", []):
            order = unit.get("order")
            if order and order.get("type") == "MOVE" and order.get("path"):
                dest_id = order["path"][0]
                dest_prov = self.id_to_province.get(dest_id)
                
                # If moving to hostile territory, check if we are pinned by an incoming attack
                if dest_prov and queries.is_hostile_territory(unit["owner"], dest_prov.get("owner", "Unclaimed"), self.nation_data):
                    attackers = incoming_attacks.get(province["id"], [])
                    
                    # FIX: ONLY pin if the attacker is hostile AND NOT coming from the tile we are moving to.
                    hostile_attackers = [
                        a for a, origin_id in attackers 
                        if queries.are_at_war(unit["owner"], a["owner"], self.nation_data) and origin_id != dest_id
                    ]
                    
                    if hostile_attackers:
                        # Pinned! Cannot attack outwards. Must defend.
                        order["path"] = []

def process_meeting_engagements(self):
    """Rule: If 2 units move into each other, let them engage in combat in between the tiles."""
    incoming = {}
    for prov in self.map_data.values():
        for u in prov.get("units", []):
            order = u.get("order")
            if order and order.get("type") == "MOVE" and order.get("path"):
                dest_id = order["path"][0]
                incoming.setdefault(dest_id, []).append((u, prov["id"], prov))

    processed_pairs = set()
    for dest_id, attackers in incoming.items():
        for u_a, origin_a_id, prov_a in attackers:
            crossers = []
            for u_b, orig_b_id, prov_b in incoming.get(origin_a_id, []):
                if orig_b_id == dest_id and queries.are_at_war(u_a["owner"], u_b["owner"], self.nation_data):
                    crossers.append((u_b, prov_b))
            
            if crossers:
                pair = tuple(sorted([origin_a_id, dest_id]))
                if pair not in processed_pairs:
                    processed_pairs.add(pair)
                    
                    prov1 = self.id_to_province[pair[0]]
                    prov2 = self.id_to_province[pair[1]]
                    
                    # --- FIX: Safely check if the path has elements before grabbing index 0 ---
                    units1 = [u for u in prov1.get("units", []) if u.get("order", {}).get("path") and u["order"]["path"][0] == pair[1]]
                    units2 = [u for u in prov2.get("units", []) if u.get("order", {}).get("path") and u["order"]["path"][0] == pair[0]]
                    
                    atk1 = sum(u.get("attack", 5) for u in units1)
                    atk2 = sum(u.get("attack", 5) for u in units2)
                    
                    apply_group_damage(atk2, units1)
                    apply_group_damage(atk1, units2)
                    
                    # Lock them in combat so they don't slide past each other
                    for u in units1 + units2:
                        u["_combat_locked"] = True
                    
                    prov1["units"] = [u for u in prov1["units"] if u.get("health", 0) > 0]
                    prov2["units"] = [u for u in prov2["units"] if u.get("health", 0) > 0]

def process_conversions(self):
    """Processes the 1-turn timer for transferring units into Convoys and back."""
    for province in self.map_data.values():
        for unit in province.get("units", []):
            order = unit.get("order")
            if isinstance(order, dict) and order.get("type") == "CONVERT":
                order["turns_left"] -= 1
                
                if order["turns_left"] <= 0:
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

def process_national_research(self):
    # Load template to know costs (REPLACED WITH CACHE)
    template = queries.get_tech_tree()
    
    # Uses the new constant
    base_points_per_turn = c.BASE_RESEARCH_POINTS_PER_DAY * c.DAYS_PER_TURN

    current_exact_year = queries.get_exact_year(self.time_manager)

    for country_name, country_data in self.nation_data.items():
        queue = country_data.get("research_queue", [])
        if not queue: continue

        # We iterate backwards through the queue so we can safely remove items
        for i in range(len(queue) - 1, -1, -1):
            project = queue[i]
            tech_key = project["tech_name"]
            
            # --- AHEAD OF TIME PENALTY LOGIC ---
            # Figure out what level is currently being researched
            current_level = country_data.get("research", {}).get(tech_key, 0)
            tech_data = template.get(tech_key, {})
            years_array = tech_data.get("years", [1850])
            
            # Cap the index to prevent out-of-bounds if a nation somehow researches past max_lvl
            target_index = min(current_level, len(years_array) - 1)
            target_year = years_array[target_index]
            
            multiplier = queries.get_research_multiplier(current_exact_year, target_year)
            effective_points = base_points_per_turn * multiplier
            # -----------------------------------
            
            # Use 'points_remaining' instead of 'days_remaining'
            # (First time initialization if coming from an old save)
            if "points_remaining" not in project:
                project["points_remaining"] = project.get("days_remaining", 30) * 10
            
            project["points_remaining"] -= effective_points

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
        combat_occurred = False
        
        for i in range(len(owners)):
            for j in range(i + 1, len(owners)):
                nation_a = owners[i]
                nation_b = owners[j]
                
                # Check if they are actually at war
                at_war = queries.are_at_war(nation_a, nation_b, self.nation_data)
                
                if at_war:
                    combat_occurred = True
                    # Side A attacks Side B
                    apply_group_damage(sides[nation_a]["total_atk"], sides[nation_b]["units"])
                    # Side B attacks Side A
                    apply_group_damage(sides[nation_b]["total_atk"], sides[nation_a]["units"])

        # --- NEW: Wipe queues for units engaged in combat ---
        if combat_occurred:
            for u in units:
                if "order" in u and "path" in u["order"]:
                    u["order"]["path"] = []

        # Remove dead units (HP <= 0)
        province["units"] = [u for u in units if u.get("health", 0) > 0]

def check_for_post_combat_captures(self):
    """Assigns province ownership to units standing in an undefended enemy province."""
    from map_logic.rendering import edit_province_ownership
    
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
            at_war = queries.is_hostile_territory(o, current_owner, self.nation_data)
            is_unclaimed = current_owner in ["Unclaimed", "None", ""]
            
            # Flip ownership if the tile is unclaimed or if they are at war with the owner
            if is_unclaimed or at_war:
                hp_totals[o] = hp_totals.get(o, 0) + u.get("health", 0)
        
        if not hp_totals:
            continue

        ## Find the nation(s) with the highest combined HP
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
            capturer = top_nations[0]
            # faction core transfer stuff
            true_owner = queries.get_faction_core_transfer_target(capturer, province, self.nation_data)
            edit_province_ownership.conquer_province(self, province, true_owner)
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
            
            # --- NEW: Check and clear the combat lock flag ---
            if unit.pop("_combat_locked", False):
                units_to_keep.append(unit)
                continue
                
            order = unit.get("order")
            if order and order.get("type") == "MOVE" and order.get("path"):
                unit["_current_province_id"] = province["id"]
                moving_units.append(unit)
            else:
                units_to_keep.append(unit)
        province["units"] = units_to_keep

    if not moving_units: return
    max_speed = max(unit.get("speed", 1) for unit in moving_units)

    # Pre-cache unit library for naval checks
    if not hasattr(self, 'cached_unit_library'):
        import json, os
        self.cached_unit_library = queries.get_unit_library() if os.path.exists(c.UNIT_DATA_PATH) else {}

    for step in range(max_speed):
        for unit in moving_units:
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
            
            # --- NEW: Combat Lock (Execution Check) ---
            # If the unit gets intercepted in a province during its move, 
            # it loses all remaining speed and its queue is wiped.
            curr_prov = self.id_to_province.get(unit["_current_province_id"])
            if curr_prov:
                in_combat = queries.is_nation_in_combat_here(unit["owner"], curr_prov, self.nation_data)
                
                if in_combat:
                    # If it already moved this turn (step > 0) and entered combat, stop immediately.
                    # Or, if it started in combat and is trying to advance deeper into enemy territory, stop.
                    if step > 0 or queries.is_hostile_territory(unit["owner"], dest_owner, self.nation_data):
                        order["path"] = []
                        continue
            # ------------------------------------------

            # --- NEW SHIP RULES EVALUATION ---
            dest_is_water = target_prov.get("terrain") in c.WATER_TERRAINS
            u_type = unit.get("type", "")
            is_convoy = u_type.startswith("Convoy")
            
            if is_convoy:
                is_naval = True
            else:
                stats = self.cached_unit_library.get(u_type, {})
                is_naval = stats.get("naval_unit", False)
                
            if is_naval and not is_convoy and not queries.can_ships_enter(unit["owner"], target_prov, self.nation_data):
                # Ships cannot enter hostile/unclaimed land
                order["path"] = []
                continue
            # ---------------------------------

            # Check for existing defenders before moving
            # We look for units belonging to anyone NOT the mover and NOT an ally
            defenders = [u for u in target_prov.get("units", []) 
                        if u["owner"] != unit["owner"] and u["owner"] not in player_data.get("allied_with", [])]

            if is_naval or is_convoy:
                can_enter = True # Naval and convoy rules already handled above
            else:
                can_enter = queries.can_land_units_enter(unit["owner"], target_prov, self.nation_data)

            if can_enter:
                unit["_current_province_id"] = target_id
                order["path"].pop(0)

                # --- INSTANT CONVERT FOR CONVOYS ON ENEMY/UNCLAIMED COAST ---
                if is_convoy and not dest_is_water and not queries.can_ships_enter(unit["owner"], target_prov, self.nation_data):
                    unit["type"] = unit.get("original_type", "Infantry")
                    unit["speed"] = unit.get("original_speed", 1)
                    unit["naval_unit"] = False
                    if "original_type" in unit: del unit["original_type"]
                    if "original_speed" in unit: del unit["original_speed"]
                # ------------------------------------------------------------

                # Only conquer if there are NO defenders from an enemy nation
                if not defenders:
                    if dest_owner == "Unclaimed" or dest_owner in player_data.get("at_war_with", []):
                        capturer = unit["owner"]
                        # faction core transfer stuff
                        true_owner = queries.get_faction_core_transfer_target(capturer, target_prov, self.nation_data)
                        edit_province_ownership.conquer_province(self, target_prov, true_owner)

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
    all_econ = queries.calculate_all_economies(self.map_data, self.nation_data)

    for name, stats in self.nation_data.items():
        # FIX: Explicitly skip the global events log 
        if name == "GLOBAL_EVENTS" or name in c.UNPLAYABLE_NATIONS or name not in all_econ:
            continue

        econ = all_econ[name]

        # FIX: Safely .get() the resource so it initializes to 0 if missing
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
    
    if os.path.exists(unit_stats_path):
        with open(unit_stats_path, 'r') as f: unit_library = json.load(f)
    if os.path.exists(building_stats_path):
        with open(building_stats_path, 'r') as f: building_library = json.load(f)

    for province in self.map_data.values():
        queue = province.get("deployment_queue", [])
        if not queue: continue
            
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