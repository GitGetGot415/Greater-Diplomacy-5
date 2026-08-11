import asyncio
from map_logic.diplomacy import diplomacy_logic
from map_logic.ai import ai_movement, ai_research, ai_construction, ai_diplomacy, ai_world, automation_logic
from map_logic.turn_processing import combat_processor, movement_processor, economy_processor, research_processor
import data.constants as c
from data import queries

async def prepare_turn(map_screen):
    """Phase 1: Calculate diplomacy and generate AI movement paths.

    Yields with `await asyncio.sleep(0)` between phases so run_background
    (data/platform.py) can interleave this with the main render loop -- on
    web that's what actually lets the loading bar animate and keeps the
    browser tab/audio scheduling alive instead of freezing for the whole
    turn; on desktop it's a no-op since this runs on its own thread/loop.
    """
    print("\n" + "="*40)
    print("--- [PHASE 1] AI PREPARATION START ---")

    # --- NEW: Check if AI is turned off ---
    ai_disabled = queries.get_scenario_flag("ai_disabled", c.DEFAULT_AI_DISABLED, map_screen.scenario_settings)


    if not ai_disabled:
        # --- TACTICAL HIDE ---
        # Mask the player unit so the AI handler doesn't touch it during ANY phase
        is_tactical = map_screen.tactical_mode and map_screen.player_unit
        if is_tactical:
            map_screen.player_unit["owner"] = "TACTICAL_HIDDEN"

        # One sweep of the map answers the border/strength/relation questions
        # every AI pass below would otherwise re-derive per nation, per target.
        # Built after the tactical hide so the masked unit is excluded from
        # strength exactly as it is from every other AI query, and torn down in
        # the finally so nothing can read a stale one next turn.
        map_screen.ai_world = ai_world.build(map_screen)

        try:
            # --- AI-to-AI summits ---
            # Before the proactive pass, so an agreement reached here is already
            # binding when each nation works out what it wants to do.
            map_screen.loading_status_text = "Holding Summits..."
            ai_diplomacy.process_summits(map_screen)
            await asyncio.sleep(0)

            # --- Basic Proactive AI & Grand Strategy ---
            print("[SYSTEM] Running Proactive AI...")
            ai_diplomacy.process_basic_proactive_ai(map_screen)
            await asyncio.sleep(0)

            map_screen.loading_status_text = "Running AI Research..."
            print("[SYSTEM] Running AI Research...")
            ai_research.process_ai_research(map_screen)
            await asyncio.sleep(0)

            map_screen.loading_status_text = "Running AI Economy & Construction..."
            print("[SYSTEM] Running AI Economy & Construction...")
            ai_construction.process_ai_economy_decisions(map_screen)
            await asyncio.sleep(0)

            map_screen.loading_status_text = "Generating AI Movement Orders..."
            print("[SYSTEM] Generating AI Movement Orders...")

            ai_movement.process_ai_unit_orders(map_screen)
            await asyncio.sleep(0)

            map_screen.loading_status_text = "Drafting Proactive Responses..."
            print("[SYSTEM] Drafting Proactive Responses...")
            ai_diplomacy.process_proactive_llm_tasks(map_screen)
            await asyncio.sleep(0)
        finally:
            # --- TACTICAL RESTORE ---
            # In a finally because an AI pass that raises used to leave the
            # player's own unit owned by TACTICAL_HIDDEN for the rest of the game.
            if is_tactical:
                map_screen.player_unit["owner"] = map_screen.player_country

            # Every AI pass is done. Scripted events below can hand provinces
            # between nations, which would make the cached fronts and strengths
            # wrong, so the snapshot never outlives the passes it was built for.
            map_screen.ai_world = None
    else:
        print("[SYSTEM] AI is OFF. Skipping standard AI actions...")

        # Since AI is off, we still need to clear proactive tasks to avoid errors
        map_screen.proactive_llm_tasks = []
        map_screen.proactive_tasks_total = 0
        map_screen.proactive_tasks_completed = 0
        map_screen.proactive_llm_tasks_total = 0
        map_screen.proactive_llm_tasks_completed = 0

    # --- Process Scripted Events ---
    # Moved here so AI can't immediately issue orders to units spawned by events this turn
    map_screen.loading_status_text = "Running Scripted Events..."
    print("[SYSTEM] Running Scripted Events...")
    ai_diplomacy.process_scripted_events(map_screen)
    await asyncio.sleep(0)

    # MOVED: Diplomacy is now processed AFTER AI movement generation.
    map_screen.loading_status_text = "Processing Pending Diplomacy..."
    print("[SYSTEM] Processing Pending Diplomacy...")
    diplomacy_logic.process_diplomacy_turn(map_screen)
    await asyncio.sleep(0)

    print("--- [PHASE 1] COMPLETE ---")

def snapshot_history(map_screen):
    if not hasattr(map_screen, 'history'):
        map_screen.history = {}
    turn_idx = str(map_screen.time_manager.total_turns)
    
    # --- Manual copy of nation_data (avoids slow copy.deepcopy) ---
    nation_snap = {}
    for nation, ndata in map_screen.nation_data.items():
        nd = {}
        for k, v in ndata.items():
            if isinstance(v, list):
                nd[k] = list(v)           # shallow list copy (items are strings/ints)
            elif isinstance(v, dict):
                nd[k] = dict(v)           # shallow dict copy
            else:
                nd[k] = v                 # immutable scalar
        nation_snap[nation] = nd
    
    snapshot = {
        "date_str": map_screen.time_manager.get_date_string(),
        "day": map_screen.time_manager.day,
        "month": map_screen.time_manager.month_index,
        "year": map_screen.time_manager.year,
        "nation_data": nation_snap,
        "provinces": {}
    }
    
    # --- Manual copy of province data (avoids copy.deepcopy per-province) ---
    _copy_list = lambda lst: [dict(item) if isinstance(item, dict) else item for item in lst] if lst else []
    
    for data in map_screen.map_data.values():
        snapshot["provinces"][data["json_key"]] = {
            "owner": data["owner"],
            "cores": list(data.get("cores", [])),
            "is_coastal": data.get("is_coastal", False),
            "units": _copy_list(data.get("units", [])),
            "building_queue": _copy_list(data.get("building_queue", [])),
            "unit_queue": _copy_list(data.get("unit_queue", [])),
            "orders": _copy_list(data.get("orders", [])),
            "resources": _copy_list(data.get("resources", [])),
            "buildings": _copy_list(data.get("buildings", []))
        }
    map_screen.history[turn_idx] = snapshot

async def resolve_turn_logic(map_screen): # Renamed from resolve_turn
    """Executes time, combat, movement, and economy logic (no refreshes).

    Yields with `await asyncio.sleep(0)` between the major sub-phases -- see
    prepare_turn's docstring for why.
    """
    print("\n--- [PHASE 2] TURN RESOLUTION START ---")
    
    # Snapshot original owners for capture logic
    for prov in map_screen.map_data.values():
        prov["_turn_start_owner"] = prov.get("owner", "Unclaimed")
        
    # Ghost War Cleanup
    living_nations = queries.get_living_nations(map_screen.map_data)
    queries.cleanup_ghost_wars(map_screen.nation_data, living_nations)

    days_to_advance = queries.get_days_per_turn(map_screen.scenario_settings)
    map_screen.time_manager.process_time(days_to_advance)
    
    print("[SYSTEM] Executing Unit Orders & Combat...")
    movement_processor.process_conversions(map_screen)
    movement_processor.process_disbands(map_screen)
    movement_processor.process_repairs(map_screen)
    movement_processor.process_upgrades(map_screen)
    await asyncio.sleep(0)

    # Process Queues (Deployments) so new units can defend
    print("[SYSTEM] Processing Queues (Deployments)...")
    economy_processor.process_queues(map_screen)
    await asyncio.sleep(0)

    # Pre-Movement Combat Mechanics
    combat_processor.process_bombardments(map_screen)
    combat_processor.process_pinning(map_screen)
    combat_processor.process_meeting_engagements(map_screen)

    movement_processor.process_movement(map_screen)
    combat_processor.process_combat(map_screen)
    combat_processor.check_for_post_combat_captures(map_screen)
    await asyncio.sleep(0)

    # Exile any units left standing on foreign soil without a legal right to be there
    movement_processor.process_stranded_units(map_screen)

    # Kill orphaned units and ghost wars
    movement_processor.process_dead_nations(map_screen)
    await asyncio.sleep(0)

    # Process Morale updates
    for prov in map_screen.map_data.values():
        for u in prov.get("units", []):
            if u.get("_in_combat_this_turn"):
                u["morale"] = max(0.0, float(u.get("morale", c.DEFAULT_UNIT_MORALE)) - 5.0)
                u.pop("_in_combat_this_turn", None)
            else:
                u["morale"] = min(100.0, float(u.get("morale", c.DEFAULT_UNIT_MORALE)) + 5.0)

    print("[SYSTEM] Calculating Economy...")
    economy_processor.process_economy(map_screen)
    await asyncio.sleep(0)

    research_processor.process_national_research(map_screen)
    await asyncio.sleep(0)

    if c.RECORD_HISTORY:
        # --- MULTI-TURN OPTIMIZATION ---
        is_multi = map_screen.multi_turns_total > 0
        is_last_multi = not is_multi or (map_screen.multi_turns_completed >= map_screen.multi_turns_total - 1)
        is_spectator = map_screen.player_country == "Spectator"
        
        if is_multi and not is_last_multi and not is_spectator:
            pass # Skip deepcopying thousands of dictionaries on skipped turns
        else:
            print("[SYSTEM] Saving Turn History Snapshot...")
            snapshot_history(map_screen)
    else:
        print("[SYSTEM] History Recording Disabled. Skipping Snapshot...")
    
    print("--- [PHASE 2] COMPLETE ---")
    print("="*40 + "\n")
    
    # --- PROCESS PLAYER AUTOMATION FOR NEXT TURN ---
    player = map_screen.player_country
    if player and player != "Spectator":
        auto = map_screen.nation_data.get(player, {}).get("automation", {})
        if auto.get("construction"):
            automation_logic.automate_player_construction(map_screen)
        if auto.get("movement"):
            automation_logic.automate_player_movement(map_screen)
        if auto.get("research"):
            automation_logic.automate_player_research(map_screen)