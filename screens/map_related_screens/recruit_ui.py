import pygame
import data.constants as c
from map_logic.rendering.font_manager import fonts

def draw_recruitment_overlay(surface, target_province):
    """Draws the combined deployment and construction queue."""
    cancel_buttons = []
    
    panel_rect = pygame.Rect(c.SCREEN_WIDTH - 400, 100, 350, c.SCREEN_HEIGHT - 200)
    pygame.draw.rect(surface, (30, 30, 50), panel_rect)
    pygame.draw.rect(surface, (100, 100, 250), panel_rect, 2)

    font = fonts.get("heading1")
    small_font = fonts.get("button")
    
    title = font.render("Queued Orders", True, (255, 255, 255))
    surface.blit(title, (panel_rect.x + 20, panel_rect.y + 20))

    queue = target_province.get("deployment_queue", [])
    
    for i, item in enumerate(queue):
        y_pos = panel_rect.y + 70 + (i * 35)
        
        # --- THE FIX: Handle both Units and Buildings ---
        # Look for 'unit_type' first, then 'item_name', fallback to 'Order'
        raw_name = item.get('unit_type', item.get('item_name', 'Unknown Order'))
        
        # Clean up the display name
        display_name = raw_name.replace("Chadian ", "").replace("Synthetic ", "Syn. ")
        
        # Safely determine the turns, fallback to converting legacy days format
        turns_val = item.get('turns_remaining', max(1, item.get('days_remaining', c.DEFAULT_DAYS_PER_TURN) // c.DEFAULT_DAYS_PER_TURN))
        
        # Draw the info text
        txt = small_font.render(f"{display_name} ({turns_val} turns)", True, (255, 200, 50))
        surface.blit(txt, (panel_rect.x + 20, y_pos))
        
        # Draw a small Red "X" button for cancellation
        cancel_rect = pygame.Rect(panel_rect.right - 40, y_pos, 25, 25)
        pygame.draw.rect(surface, (150, 0, 0), cancel_rect)
        x_txt = small_font.render("X", True, (255, 255, 255))
        surface.blit(x_txt, (cancel_rect.x + 7, cancel_rect.y + 2))
        
        # Store the rect and the index for the click handler
        cancel_buttons.append((cancel_rect, i))
        
    return cancel_buttons


# --- NEW FUNCTION FOR THE READ-ONLY MAP VIEW QUEUE ---
def draw_map_queue_overlay(surface, target_province):
    """Draws a read-only queue under the construction button on the map screen."""
    queue = target_province.get("deployment_queue", [])
    if not queue: return
    
    # Construction button is at x=1380, y=190, width=200, height=50.
    # Start the panel at y = 250 so it's seamlessly below the buttons
    panel_rect = pygame.Rect(1380, 250, 200, min(400, len(queue) * 35 + 40))
    
    # Draw semi-transparent background
    panel_surf = pygame.Surface((panel_rect.width, panel_rect.height), pygame.SRCALPHA)
    panel_surf.fill((30, 30, 50, 200))
    surface.blit(panel_surf, panel_rect.topleft)
    pygame.draw.rect(surface, (100, 100, 250), panel_rect, 2)
    
    font = fonts.get("normal")
    small_font = fonts.get("tiny")
    
    title = font.render("Queued Orders", True, (255, 255, 255))
    surface.blit(title, (panel_rect.x + 10, panel_rect.y + 10))
    
    for i, item in enumerate(queue):
        y_pos = panel_rect.y + 35 + (i * 35)
        if y_pos + 30 > panel_rect.bottom: 
            # If it exceeds the box, just show a "+X more" and break
            more_txt = small_font.render(f"+{len(queue) - i} more...", True, (150, 150, 150))
            surface.blit(more_txt, (panel_rect.x + 10, y_pos))
            break
        
        raw_name = item.get('unit_type', item.get('item_name', 'Unknown Order'))
        display_name = raw_name.replace("Chadian ", "").replace("Synthetic ", "Syn. ")
        
       # Truncate long names to fit in the 200px width window
        if len(display_name) > 16:
            display_name = display_name[:14] + ".."
            
        turns_val = item.get('turns_remaining', max(1, item.get('days_remaining', c.DEFAULT_DAYS_PER_TURN) // c.DEFAULT_DAYS_PER_TURN))
            
        txt = small_font.render(f"{display_name} ({turns_val} turns)", True, (255, 200, 50))
        surface.blit(txt, (panel_rect.x + 10, y_pos))