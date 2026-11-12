from data.state_access import world_for, session_for
import asyncio
import pygame
from data.platform import run_background
from map_logic.system32 import turn_processor
from ui.panels import diplomatic_popups
from map_logic.ai import ai_handler
from data import queries
import data.constants as c

import traceback

def advance_time(context):
    session_state = session_for(context)
    diplomatic_popups.clear_popups(context)

    session_state.turn_start_time = pygame.time.get_ticks()

    # PHASE 2: Resolve the turn
    if session_state.viewing_ai_moves:
        session_state.is_refreshing = True
        session_state.loading_status_text = "Resolving Orders & Map Refreshes..."

        # Fire-and-forget the heavy work (see run_background's docstring). The
        # main render loop's own per-frame draw already shows the turn-loading
        # bar whenever is_refreshing is set (map_renderer.py), so we don't need
        # to force any draw/flip calls here ourselves -- we just need the
        # background coroutine below to yield often enough to let that render
        # loop keep running, which is what actually fixes the "loading bar
        # never shows up, tab just freezes" bug on web.
        run_background(_resolve_turn_and_refresh, context)
        return

    # PHASE 1: Prepare the turn and generate AI moves
    if len(session_state.active_players) > 1:
        session_state.current_player_index += 1
        
        if session_state.current_player_index < len(session_state.active_players):
            # Next player's turn to issue orders
            session_state.player_country = session_state.active_players[session_state.current_player_index]
            context.show_player_ready_screen = True
        else:
            # All players have gone, loop back to player 1 and PREPARE the turn!
            session_state.current_player_index = 0
            session_state.player_country = "n/a"
            trigger_ai_thread(context)
    else:
        trigger_ai_thread(context)
        
def trigger_ai_thread(context):
    """Helper to lock the UI and start the background thread."""
    session_state = session_for(context)
    session_state.ai_is_thinking = True
    session_state.loading_status_text = "Initializing Turn..."
    session_state.force_skip_llm = False # Reset the skip flag
    
    # --- IMPORTANT: Reset the module-level abort flag so APIs work again ---
    ai_handler.FORCE_SKIP = False
    ai_handler.CURRENT_TURN_ID += 1
        
    # Pre-calculate determinable totals so the UI instantly knows the workload
    ai_disabled = queries.get_scenario_flag(
        "ai_disabled", c.DEFAULT_AI_DISABLED, world_for(context).scenario_settings)
    ai_count = len(queries.get_active_ai_nations(context))
    if ai_disabled:
        ai_count = 0
    session_state.proactive_tasks_total = ai_count
    session_state.proactive_tasks_completed = 0
    session_state.movement_tasks_total = ai_count
    session_state.movement_tasks_completed = 0
    
    # Unknown model workloads stay pending; no AI or no model means N/A.
    model_pending = -1 if ai_count and ai_handler.get_ai_mode() != "OFF" else 0
    session_state.proactive_llm_tasks_total = model_pending
    session_state.proactive_llm_tasks_completed = 0
    session_state.proactive_llm_tasks = []
    
    session_state.responsive_tasks_total = model_pending
    session_state.responsive_tasks_completed = 0

    # Clear last turn's work. Model phases with no work remain visible as N/A.
    session_state.letters_total = model_pending
    session_state.letters_completed = 0
    
    # Map Refresh always executes exactly 7 background render passes now
    session_state.refresh_tasks_total = 7
    session_state.refresh_tasks_completed = 0

    # Force the loading screen to actually appear before run_background either
    # spawns a thread (desktop) or, on web, blocks the frame running synchronously.
    context.draw(pygame.display.get_surface())
    pygame.display.flip()

    # Fire and forget the background process
    run_background(run_ai_processing_thread, context)

async def run_ai_processing_thread(context):
    """This runs in the background. Pygame keeps running!"""
    session_state = session_for(context)
    try:
        await turn_processor.prepare_turn(context)
    except Exception as e:
        session_state.thread_error = traceback.format_exc()
        print(f"BACKGROUND CRASH CAUGHT:\n{session_state.thread_error}")
    finally:
        session_state.ai_processing_complete = True # Always signal the main thread we are done

async def _resolve_turn_and_refresh(context):
    """Background body for advance_time's Phase 2 (see run_background)."""
    session_state = session_for(context)
    try:
        # 1. Run the heavy logic (Combat, Movement, etc.)
        await turn_processor.resolve_turn_logic(context)

        # --- MULTI-TURN OPTIMIZATION ---
        is_multi = session_state.multi_turns_total > 0
        is_last_multi = not is_multi or (session_state.multi_turns_completed >= session_state.multi_turns_total - 1)

        # 2. Define Refresh Tasks
        refresh_steps = [
            ("Refreshing Political Map...", lambda: context.refresh_map_layers("political")),
            ("Refreshing Relations Map...", lambda: context.refresh_map_layers("relations")),
            ("Refreshing Factions Map...", lambda: context.refresh_map_layers("factions")),
            ("Refreshing Core Map...", lambda: context.refresh_map_layers("cores")),
            ("Refreshing Territories...", lambda: context.refresh_map_layers("faction_territories")),
            ("Refreshing Fog of War...", lambda: context.refresh_map_layers("fog")),
            ("Updating Map Labels...", context.update_country_centers)
        ]

        session_state.refresh_tasks_total = len(refresh_steps)
        session_state.refresh_tasks_completed = 0

        # 3. Process each refresh step, yielding a frame to the render loop after each
        for label, func in refresh_steps:
            session_state.loading_status_text = label

            if is_multi and not is_last_multi:
                # Skip heavy Numpy visual rebuilds until the final turn
                session_state.refresh_tasks_completed += 1
                continue

            func() # Execute the refresh
            session_state.refresh_tasks_completed += 1
            await asyncio.sleep(0)

        session_state.viewing_ai_moves = False
        session_state.is_refreshing = False

        if len(session_state.active_players) > 1:
            session_state.player_country = session_state.active_players[session_state.current_player_index]
            context.show_player_ready_screen = True

        # map_buttons imports turn_manager. Load its UI helper after both modules initialize.
        from screens.game import map_buttons
        map_buttons.render_buttons(context)

        elapsed_seconds = (pygame.time.get_ticks() - session_state.turn_start_time) / 1000.0
        context.show_feedback(f"Turn resolved in {elapsed_seconds:.2f}s")
    except Exception:
        session_state.thread_error = traceback.format_exc()
        print(f"BACKGROUND CRASH CAUGHT:\n{session_state.thread_error}")
        session_state.viewing_ai_moves = False
        session_state.is_refreshing = False
