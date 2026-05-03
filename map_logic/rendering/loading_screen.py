import pygame
import math
import data.constants as c
from map_logic.rendering.font_manager import fonts

def draw_turn_loading_screen(map_screen, surface):
    """Draws a dynamic overlay informing the player the turn is processing."""
    overlay = pygame.Surface((c.SCREEN_WIDTH, c.SCREEN_HEIGHT), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 200))
    surface.blit(overlay, (0, 0))

    center_x = c.SCREEN_WIDTH // 2
    center_y = c.SCREEN_HEIGHT // 2

    # 1. Draw Title Text
    font = fonts.get("title")
    txt = font.render(map_screen.loading_status_text, True, (255, 255, 255))
    surface.blit(txt, txt.get_rect(center=(center_x, center_y - 120)))

    # 2. Draw Progress Bars (Only if we have tasks to track)
    if map_screen.proactive_tasks_total > 0 or map_screen.responsive_tasks_total > 0:
        bar_w = 400
        bar_h = 30
        bar_x = center_x - (bar_w // 2)
        
        def draw_bar(y_pos, label, completed, total):
            # Label
            lbl_txt = fonts.get("normal").render(label, True, (200, 200, 200))
            surface.blit(lbl_txt, (bar_x, y_pos - 25))

            # Background
            pygame.draw.rect(surface, (40, 40, 60), (bar_x, y_pos, bar_w, bar_h), border_radius=5)

            # Safely calculate fill width even if total is currently 0
            progress_ratio = (completed / float(total)) if total > 0 else 0.0
            fill_w = int(bar_w * progress_ratio)
            
            if fill_w > 0:
                pygame.draw.rect(surface, (100, 200, 100), (bar_x, y_pos, fill_w, bar_h), border_radius=5)

            # Show exact numerical progress (e.g., 0/26) instead of percentage
            pct_txt = fonts.get("normal").render(f"{completed}/{total}", True, (255, 255, 255))
            surface.blit(pct_txt, pct_txt.get_rect(center=(center_x, y_pos + 15)))

            # Outline
            pygame.draw.rect(surface, (200, 200, 200), (bar_x, y_pos, bar_w, bar_h), 2, border_radius=5)

        # Always draw both bars side-by-side regardless of whether they have started yet
        draw_bar(center_y - 40, "Generating Grand Strategy:", map_screen.proactive_tasks_completed, map_screen.proactive_tasks_total)
        draw_bar(center_y + 40, "Generating Responses:", map_screen.responsive_tasks_completed, map_screen.responsive_tasks_total)
        
    else:
        # 3. Draw a spinning loading wheel if we are just doing general processing
        map_screen.loading_spinner_angle = (map_screen.loading_spinner_angle + 5) % 360
        radius = 20
        
        # Calculate a pulsing arc
        start_rad = math.radians(map_screen.loading_spinner_angle)
        end_rad = math.radians(map_screen.loading_spinner_angle + 270) # 3/4 circle
        
        arc_rect = pygame.Rect(center_x - radius, center_y - radius, radius * 2, radius * 2)
        pygame.draw.arc(surface, (100, 200, 255), arc_rect, start_rad, end_rad, 5)