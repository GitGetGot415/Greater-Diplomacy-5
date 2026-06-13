import pygame
import data.constants as c
from map_logic.rendering.font_manager import fonts

def draw_recruitment_overlay(surface, target_province):
    """Draws the separated building and unit queues."""
    cancel_buttons = []
    
    panel_rect = pygame.Rect(c.SCREEN_WIDTH - 480, 100, 460, c.SCREEN_HEIGHT - 200)
    pygame.draw.rect(surface, (30, 30, 50), panel_rect)
    pygame.draw.rect(surface, (100, 100, 250), panel_rect, 2)
    pygame.draw.line(surface, (100, 100, 250), (panel_rect.x + 230, panel_rect.y), (panel_rect.x + 230, panel_rect.bottom), 2)

    font = fonts.get("heading1")
    small_font = fonts.get("button")
    
    title_b = font.render("Buildings", True, (255, 255, 255))
    title_u = font.render("Units", True, (255, 255, 255))
    surface.blit(title_b, (panel_rect.x + 20, panel_rect.y + 20))
    surface.blit(title_u, (panel_rect.x + 250, panel_rect.y + 20))

    b_queue = target_province.get("building_queue", [])
    u_queue = target_province.get("unit_queue", [])
    
    def render_half(queue_list, q_type, start_x):
        for i, item in enumerate(queue_list):
            y_pos = panel_rect.y + 70 + (i * 35)
            raw_name = item.get('unit_type', item.get('item_name', 'Unknown Order'))
            display_name = raw_name.replace("Chadian ", "").replace("Synthetic ", "Syn. ")
            
            # Truncate to fit column width
            if len(display_name) > 13:
                display_name = display_name[:11] + ".."
                
            turns_val = item.get('turns_remaining', max(1, item.get('days_remaining', c.DEFAULT_DAYS_PER_TURN) // c.DEFAULT_DAYS_PER_TURN))
            
            txt = small_font.render(f"{display_name} ({turns_val}t)", True, (255, 200, 50))
            surface.blit(txt, (start_x, y_pos))
            
            cancel_rect = pygame.Rect(start_x + 185, y_pos, 25, 25)
            pygame.draw.rect(surface, (150, 0, 0), cancel_rect)
            x_txt = small_font.render("X", True, (255, 255, 255))
            surface.blit(x_txt, (cancel_rect.x + 7, cancel_rect.y + 2))
            
            cancel_buttons.append((cancel_rect, i, q_type))

    render_half(b_queue, "building", panel_rect.x + 10)
    render_half(u_queue, "unit", panel_rect.x + 240)
        
    return cancel_buttons

def draw_map_queue_overlay(surface, target_province, map_screen=None):
    """Draws a read-only split queue under the construction button on the map screen."""
    b_queue = target_province.get("building_queue", [])
    u_queue = target_province.get("unit_queue", [])
    
    # --- FOG OF WAR VISIBILITY CHECK ---
    is_visible = True
    if map_screen and getattr(map_screen, 'visible_provinces', None) is not None:
        if target_province["id"] not in map_screen.visible_provinces:
            is_visible = False

    # Removed the early return here so it doesn't vanish when the queue is empty
    # if is_visible and not b_queue and not u_queue: return
    
    # Make the box wider to fit two columns seamlessly underneath the Production button
    # If hidden by fog, fix height to just show the hidden text
    # Wrapped the visible calculation in a max() so the panel never shrinks below 80px
    panel_height = 80 if not is_visible else max(80, min(400, max(len(b_queue), len(u_queue)) * 35 + 40))
    panel_rect = pygame.Rect(c.MAP_QUEUE_OVERLAY_X, c.MAP_QUEUE_OVERLAY_Y, c.MAP_QUEUE_OVERLAY_WIDTH, panel_height)
    
    panel_surf = pygame.Surface((panel_rect.width, panel_rect.height), pygame.SRCALPHA)
    panel_surf.fill((30, 30, 50, 200))
    surface.blit(panel_surf, panel_rect.topleft)
    pygame.draw.rect(surface, (100, 100, 250), panel_rect, 2)
    pygame.draw.line(surface, (100, 100, 250), (panel_rect.centerx, panel_rect.y), (panel_rect.centerx, panel_rect.bottom), 2)
    
    font = fonts.get("normal")
    small_font = fonts.get("tiny")
    
    title_b = font.render("Buildings", True, (255, 255, 255))
    title_u = font.render("Units", True, (255, 255, 255))
    surface.blit(title_b, (panel_rect.x + 10, panel_rect.y + 10))
    surface.blit(title_u, (panel_rect.centerx + 10, panel_rect.y + 10))
    
    # If the province is hidden by fog, draw the hidden text under both columns and stop
    if not is_visible:
        hidden_txt = font.render("(Hidden by Fog of War)", True, (150, 150, 150))
        surface.blit(hidden_txt, (panel_rect.x + 10, panel_rect.y + 40))
        surface.blit(hidden_txt, (panel_rect.centerx + 10, panel_rect.y + 40))
        return

    def render_map_half(queue_list, start_x):
        # If this specific queue is empty, draw the empty text and skip rendering items
        if not queue_list:
            empty_txt = font.render("(Queue Empty)", True, (150, 150, 150))
            surface.blit(empty_txt, (start_x, panel_rect.y + 40))
            return

        for i, item in enumerate(queue_list):
            y_pos = panel_rect.y + 35 + (i * 35)
            if y_pos + 30 > panel_rect.bottom: 
                more_txt = small_font.render(f"+{len(queue_list) - i} more...", True, (150, 150, 150))
                surface.blit(more_txt, (start_x, y_pos))
                break
            
            raw_name = item.get('unit_type', item.get('item_name', 'Unknown Order'))
            display_name = raw_name.replace("Chadian ", "").replace("Synthetic ", "Syn. ")
            if len(display_name) > 13:
                display_name = display_name[:11] + ".."
                
            turns_val = item.get('turns_remaining', max(1, item.get('days_remaining', c.DEFAULT_DAYS_PER_TURN) // c.DEFAULT_DAYS_PER_TURN))
            txt = small_font.render(f"{display_name} ({turns_val}t)", True, (255, 200, 50))
            surface.blit(txt, (start_x, y_pos))

    render_map_half(b_queue, panel_rect.x + 10)
    render_map_half(u_queue, panel_rect.centerx + 10)