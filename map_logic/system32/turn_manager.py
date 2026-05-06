import pygame
import threading
from map_logic.system32 import turn_processor
from map_logic.system32 import loading_screen
from ui import buttons
import traceback

def advance_time(map_screen):
    map_screen.turn_start_time = pygame.time.get_ticks() 
    
    # PHASE 2: Resolve the turn if we are currently viewing AI moves (Runs Synchronously)
    if getattr(map_screen, 'viewing_ai_moves', False):
        map_screen.loading_status_text = "Resolving Orders..."
        loading_screen.draw_turn_loading_screen(map_screen, pygame.display.get_surface())
        pygame.display.flip()
        
        turn_processor.resolve_turn(map_screen)
        map_screen.refresh_political_map()
        map_screen.refresh_relations_map()
        map_screen.refresh_factions_map()
        
        # Only refresh country centers ONCE after the turn finishes
        if getattr(map_screen, 'centers_need_update', False):
            map_screen.update_country_centers()
            map_screen.centers_need_update = False
            
        map_screen.viewing_ai_moves = False

        # If playing multiplayer, show the ready screen for Player 1 again
        if hasattr(map_screen, 'active_players') and len(map_screen.active_players) > 1:
            map_screen.show_player_ready_screen = True

        buttons.render_buttons(map_screen) 
        
        # --- TIMER FEEDBACK ---
        elapsed_seconds = (pygame.time.get_ticks() - map_screen.turn_start_time) / 1000.0
        map_screen.show_feedback(f"Turn resolved in {elapsed_seconds:.2f}s")
        print(f"[PERFORMANCE] Phase 2 completed in {elapsed_seconds:.2f} seconds.")
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
            map_screen.player_country = map_screen.active_players[0]
            trigger_ai_thread(map_screen)
    else:
        trigger_ai_thread(map_screen)
        
def trigger_ai_thread(map_screen):
    """Helper to lock the UI and start the background thread."""
    map_screen.ai_is_thinking = True
    map_screen.loading_status_text = "Initializing Turn..."
    
    # Reset trackers for the new turn
    map_screen.proactive_tasks_total = 0
    map_screen.proactive_tasks_completed = 0
    map_screen.responsive_tasks_total = 0
    map_screen.responsive_tasks_completed = 0
    
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