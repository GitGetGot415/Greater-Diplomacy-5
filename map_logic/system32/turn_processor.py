from map_logic.diplomacy import diplomacy_logic
from map_logic.ai import ai_movement, ai_research, ai_construction, ai_diplomacy
from map_logic.system32 import combat_processor, movement_processor, economy_processor, research_processor
import data.constants as c
from data import queries

def prepare_turn(self):
    """Phase 1: Calculate diplomacy and generate AI movement paths."""
    print("\n" + "="*40)
    print("--- [PHASE 1] AI PREPARATION START ---")
    
    # --- NEW: Check if AI is turned off ---
    ai_disabled = self.scenario_settings.get("ai_disabled", c.DEFAULT_AI_DISABLED)
    
    # --- Process Scripted Events ---
    print("[SYSTEM] Running Scripted Events...")
    ai_diplomacy.process_scripted_events(self)
    
    if not ai_disabled:
        # --- TACTICAL HIDE ---
        # Mask the player unit so the AI handler doesn't touch it during ANY phase
        is_tactical = getattr(self, 'tactical_mode', False) and getattr(self, 'player_unit', None)
        if is_tactical:
            self.player_unit["owner"] = "TACTICAL_HIDDEN"

        # --- Basic Proactive AI & Grand Strategy ---
        print("[SYSTEM] Running Proactive AI...")
        ai_diplomacy.process_basic_proactive_ai(self)
        
        self.loading_status_text = "Running AI Research..."
        print("[SYSTEM] Running AI Research...")
        ai_research.process_ai_research(self)
        
        self.loading_status_text = "Running AI Economy & Construction..."
        print("[SYSTEM] Running AI Economy & Construction...")
        ai_construction.process_ai_economy_decisions(self)
        
        self.loading_status_text = "Generating AI Movement Orders..."
        print("[SYSTEM] Generating AI Movement Orders...")
        
        ai_movement.process_ai_unit_orders(self)

        self.loading_status_text = "Drafting Proactive Responses..."
        print("[SYSTEM] Drafting Proactive Responses...")
        ai_diplomacy.process_proactive_llm_tasks(self)

        # --- TACTICAL RESTORE ---
        if is_tactical:
            self.player_unit["owner"] = self.player_country
    else:
        print("[SYSTEM] AI is OFF. Skipping standard AI actions...")
        
        # Since AI is off, we still need to clear proactive tasks to avoid errors
        self.proactive_llm_tasks = []
        self.proactive_tasks_total = 0
        self.proactive_tasks_completed = 0
        self.proactive_llm_tasks_total = 0
        self.proactive_llm_tasks_completed = 0
    
    # MOVED: Diplomacy is now processed AFTER AI movement generation.
    self.loading_status_text = "Processing Pending Diplomacy..."
    print("[SYSTEM] Processing Pending Diplomacy...")
    diplomacy_logic.process_diplomacy_turn(self)
    
    print("--- [PHASE 1] COMPLETE ---")

def snapshot_history(self):
    queries.scrub_default_images(self.nation_data)
    import copy
    if not hasattr(self, 'history'):
        self.history = {}
    turn_idx = str(self.time_manager.total_turns)
    
    snapshot = {
        "date_str": self.time_manager.get_date_string(),
        "day": self.time_manager.day,
        "month": self.time_manager.month_index,
        "year": self.time_manager.year,
        "nation_data": copy.deepcopy(self.nation_data),
        "provinces": {}
    }
    for data in self.map_data.values():
        snapshot["provinces"][data["json_key"]] = {
            "owner": data["owner"],
            "cores": data.get("cores", []),
            "is_coastal": data.get("is_coastal", False),
            "units": copy.deepcopy(data.get("units", [])),
            "building_queue": copy.deepcopy(data.get("building_queue", [])),
            "unit_queue": copy.deepcopy(data.get("unit_queue", [])),
            "orders": copy.deepcopy(data.get("orders", [])),
            "resources": copy.deepcopy(data.get("resources", [])),
            "buildings": copy.deepcopy(data.get("buildings", []))
        }
    self.history[turn_idx] = snapshot

def resolve_turn_logic(self): # Renamed from resolve_turn
    """Executes time, combat, movement, and economy logic (no refreshes)."""
    print("\n--- [PHASE 2] TURN RESOLUTION START ---")
    
    # Snapshot original owners for capture logic
    for prov in self.map_data.values():
        prov["_turn_start_owner"] = prov.get("owner", "Unclaimed")
        
    # Ghost War Cleanup
    living_nations = queries.get_living_nations(self.map_data)
    for nation, data in self.nation_data.items():
        if "at_war_with" in data:
            if nation not in living_nations:
                # The nation is dead, wipe its entire war list
                data["at_war_with"] = []
            else:
                # The nation is alive, only keep living enemies
                data["at_war_with"] = [enemy for enemy in data["at_war_with"] if enemy in living_nations]
    
    days_to_advance = queries.get_days_per_turn(self.scenario_settings)
    self.time_manager.process_time(days_to_advance)
    
    print("[SYSTEM] Executing Unit Orders & Combat...")
    movement_processor.process_conversions(self)
    movement_processor.process_disbands(self)
    
    # Process Queues (Deployments) so new units can defend
    print("[SYSTEM] Processing Queues (Deployments)...")
    economy_processor.process_queues(self)

    # Pre-Movement Combat Mechanics 
    combat_processor.process_pinning(self)
    combat_processor.process_meeting_engagements(self)
    
    movement_processor.process_movement(self)
    combat_processor.process_combat(self)
    combat_processor.check_for_post_combat_captures(self)
    
    # Kill orphaned units and ghost wars
    movement_processor.process_dead_nations(self)
    
    print("[SYSTEM] Calculating Economy...")
    economy_processor.process_economy(self)
    
    research_processor.process_national_research(self)
    
    if c.RECORD_HISTORY:
        print("[SYSTEM] Saving Turn History Snapshot...")
        snapshot_history(self)
    else:
        print("[SYSTEM] History Recording Disabled. Skipping Snapshot...")
    
    print("--- [PHASE 2] COMPLETE ---")
    print("="*40 + "\n")