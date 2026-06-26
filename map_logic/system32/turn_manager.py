import pygame
import threading
from map_logic.system32 import turn_processor
from map_logic.system32 import loading_screen
from ui import buttons, diplomatic_popups
from map_logic.ai import ai_handler
from data import queries

import traceback

def advance_time(map_screen):
    diplomatic_popups.clear_popups(map_screen)
    
    map_screen.turn_start_time = pygame.time.get_ticks()
    
    # PHASE 2: Resolve the turn (Synchronous execution with UI updates for refreshes)
    if map_screen.viewing_ai_moves:
        map_screen.is_refreshing = True
        map_screen.loading_status_text = "Resolving Orders & Map Refreshes..."

        # Force a frame update so the loading screen appears BEFORE the heavy logic freezes the thread
        map_screen.draw(pygame.display.get_surface())
        pygame.display.flip()
        
        # 1. Run the heavy logic (Combat, Movement, etc.)
        turn_processor.resolve_turn_logic(map_screen)
        
        # --- MULTI-TURN OPTIMIZATION ---
        is_multi = getattr(map_screen, 'multi_turns_total', 0) > 0
        is_last_multi = not is_multi or (getattr(map_screen, 'multi_turns_completed', 0) >= getattr(map_screen, 'multi_turns_total', 0) - 1)
        
        # 2. Define Refresh Tasks
        refresh_steps = [
            ("Refreshing Political Map...", map_screen.refresh_political_map),
            ("Refreshing Relations Map...", map_screen.refresh_relations_map),
            ("Refreshing Factions Map...", map_screen.refresh_factions_map),
            ("Refreshing Core Map...", map_screen.refresh_cores_map),
            ("Refreshing Territories...", map_screen.refresh_faction_territories_map),
            ("Refreshing Fog of War...", map_screen.refresh_fog_map),
            ("Updating Map Labels...", map_screen.update_country_centers)
        ]
        
        map_screen.refresh_tasks_total = len(refresh_steps)
        map_screen.refresh_tasks_completed = 0
        
        # 3. Process each refresh step and flip the display to animate the bar
        for label, func in refresh_steps:
            map_screen.loading_status_text = label
            
            if is_multi and not is_last_multi:
                # Skip heavy Numpy visual rebuilds until the final turn
                map_screen.refresh_tasks_completed += 1
                continue
                
            func() # Execute the refresh
            map_screen.refresh_tasks_completed += 1
            
            # Re-draw the full screen so UI bars stay on top
            map_screen.draw(pygame.display.get_surface())
            pygame.display.flip()
            
        if is_multi and not is_last_multi:
            # We skipped the inner loop drawing, so draw once per turn to update the multi-turn progress bar
            map_screen.draw(pygame.display.get_surface())
            pygame.display.flip()
            
        map_screen.viewing_ai_moves = False
        map_screen.is_refreshing = False

        if hasattr(map_screen, 'active_players') and len(map_screen.active_players) > 1:
            map_screen.player_country = map_screen.active_players[map_screen.current_player_index]
            map_screen.show_player_ready_screen = True

        buttons.render_buttons(map_screen)
        
        elapsed_seconds = (pygame.time.get_ticks() - map_screen.turn_start_time) / 1000.0
        map_screen.show_feedback(f"Turn resolved in {elapsed_seconds:.2f}s")
        return

    # PHASE 1: Prepare the turn and generate AI moves
    if hasattr(map_screen, 'active_players') and len(map_screen.active_players) > 1:
        map_screen.current_player_index += 1
        
        if map_screen.current_player_index < len(map_screen.active_players):
            # Next player's turn to issue orders
            map_screen.player_country = map_screen.active_players[map_screen.current_player_index]
            map_screen.show_player_ready_screen = True
        else:
            # All players have gone, loop back to player 1 and PREPARE the turn!
            map_screen.current_player_index = 0
            map_screen.player_country = "n/a"
            trigger_ai_thread(map_screen)
    else:
        trigger_ai_thread(map_screen)
        
def trigger_ai_thread(map_screen):
    """Helper to lock the UI and start the background thread."""
    map_screen.ai_is_thinking = True
    map_screen.loading_status_text = "Initializing Turn..."
    map_screen.force_skip_llm = False # Reset the skip flag
    
    # --- IMPORTANT: Reset the module-level abort flag so APIs work again ---
    ai_handler.FORCE_SKIP = False
    ai_handler.CURRENT_TURN_ID += 1
        
    # Pre-calculate determinable totals so the UI instantly knows the workload
    map_screen.proactive_tasks_total = len(queries.get_active_ai_nations(map_screen))
    map_screen.proactive_tasks_completed = 0
    
    # Dynamic LLM tasks cannot be known until previous phases finish. Mark as -1 (Pending)
    map_screen.proactive_llm_tasks_total = -1 
    map_screen.proactive_llm_tasks_completed = 0
    map_screen.proactive_llm_tasks = []
    
    map_screen.responsive_tasks_total = -1
    map_screen.responsive_tasks_completed = 0
    
    # Map Refresh always executes exactly 7 background render passes now
    map_screen.refresh_tasks_total = 7
    map_screen.refresh_tasks_completed = 0
    
    # Fire and forget the background process
    threading.Thread(target=run_ai_processing_thread, args=(map_screen,), daemon=True).start()

def run_ai_processing_thread(map_screen):
    """This runs in the background. Pygame keeps running!"""
    try:
        turn_processor.prepare_turn(map_screen)
    except Exception as e:
        map_screen.thread_error = traceback.format_exc()
        print(f"BACKGROUND CRASH CAUGHT:\n{map_screen.thread_error}")
    finally:
        map_screen.ai_processing_complete = True # Always signal the main thread we are done