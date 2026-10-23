from data.state_access import world_for, session_for
import asyncio
import pygame
from data.platform import run_background
from map_logic.turn_processing import turn_processor
from ui import diplomatic_popups
from map_logic.ai import ai_handler
from data import queries

import traceback

def advance_time(map_screen):
    session_state = session_for(map_screen)
    diplomatic_popups.clear_popups(map_screen)

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
        run_background(_resolve_turn_and_refresh, map_screen)
        return

    # PHASE 1: Prepare the turn and generate AI moves
    if hasattr(session_for(map_screen), 'active_players') and len(session_state.active_players) > 1:
        session_state.current_player_index += 1
        
        if session_state.current_player_index < len(session_state.active_players):
            # Next player's turn to issue orders
            session_state.player_country = session_state.active_players[session_state.current_player_index]
            map_screen.show_player_ready_screen = True
        else:
            # All players have gone, loop back to player 1 and PREPARE the turn!
            session_state.current_player_index = 0
            session_state.player_country = "n/a"
            trigger_ai_thread(map_screen)
    else:
        trigger_ai_thread(map_screen)
        
def trigger_ai_thread(map_screen):
    """Helper to lock the UI and start the background thread."""
    session_state = session_for(map_screen)
    session_state.ai_is_thinking = True
    session_state.loading_status_text = "Initializing Turn..."
    session_state.force_skip_llm = False # Reset the skip flag
    
    # --- IMPORTANT: Reset the module-level abort flag so APIs work again ---
    ai_handler.FORCE_SKIP = False
    ai_handler.CURRENT_TURN_ID += 1
        
    # Pre-calculate determinable totals so the UI instantly knows the workload
    session_state.proactive_tasks_total = len(queries.get_active_ai_nations(map_screen))
    session_state.proactive_tasks_completed = 0
    
    # Dynamic LLM tasks cannot be known until previous phases finish. Mark as -1 (Pending)
    session_state.proactive_llm_tasks_total = -1
    session_state.proactive_llm_tasks_completed = 0
    session_state.proactive_llm_tasks = []
    
    session_state.responsive_tasks_total = -1
    session_state.responsive_tasks_completed = 0

    # Summits are drawn only when there are any, so this has to go back to zero
    # or last turn's count would keep a bar and a Force Skip button on screen
    # for a phase that is not running.
    session_state.summits_total = 0
    session_state.summits_completed = 0
    
    # Map Refresh always executes exactly 7 background render passes now
    session_state.refresh_tasks_total = 7
    session_state.refresh_tasks_completed = 0

    # Force the loading screen to actually appear before run_background either
    # spawns a thread (desktop) or, on web, blocks the frame running synchronously.
    map_screen.draw(pygame.display.get_surface())
    pygame.display.flip()

    # Fire and forget the background process
    run_background(run_ai_processing_thread, map_screen)

async def run_ai_processing_thread(map_screen):
    """This runs in the background. Pygame keeps running!"""
    session_state = session_for(map_screen)
    try:
        await turn_processor.prepare_turn(map_screen)
    except Exception as e:
        session_state.thread_error = traceback.format_exc()
        print(f"BACKGROUND CRASH CAUGHT:\n{session_state.thread_error}")
    finally:
        session_state.ai_processing_complete = True # Always signal the main thread we are done

async def _resolve_turn_and_refresh(map_screen):
    """Background body for advance_time's Phase 2 (see run_background)."""
    session_state = session_for(map_screen)
    try:
        # 1. Run the heavy logic (Combat, Movement, etc.)
        await turn_processor.resolve_turn_logic(map_screen)

        # --- MULTI-TURN OPTIMIZATION ---
        is_multi = session_state.multi_turns_total > 0
        is_last_multi = not is_multi or (session_state.multi_turns_completed >= session_state.multi_turns_total - 1)

        # 2. Define Refresh Tasks
        refresh_steps = [
            ("Refreshing Political Map...", lambda: map_screen.refresh_map_layers("political")),
            ("Refreshing Relations Map...", lambda: map_screen.refresh_map_layers("relations")),
            ("Refreshing Factions Map...", lambda: map_screen.refresh_map_layers("factions")),
            ("Refreshing Core Map...", lambda: map_screen.refresh_map_layers("cores")),
            ("Refreshing Territories...", lambda: map_screen.refresh_map_layers("faction_territories")),
            ("Refreshing Fog of War...", lambda: map_screen.refresh_map_layers("fog")),
            ("Updating Map Labels...", map_screen.update_country_centers)
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

        if hasattr(session_for(map_screen), 'active_players') and len(session_state.active_players) > 1:
            session_state.player_country = session_state.active_players[session_state.current_player_index]
            map_screen.show_player_ready_screen = True

        from screens.menu_screens.map import render_buttons
        render_buttons(map_screen)

        elapsed_seconds = (pygame.time.get_ticks() - session_state.turn_start_time) / 1000.0
        map_screen.show_feedback(f"Turn resolved in {elapsed_seconds:.2f}s")
    except Exception:
        session_state.thread_error = traceback.format_exc()
        print(f"BACKGROUND CRASH CAUGHT:\n{session_state.thread_error}")
        session_state.viewing_ai_moves = False
        session_state.is_refreshing = False
