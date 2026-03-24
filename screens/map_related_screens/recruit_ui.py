# screens/map_related_screens/recruit_ui.py
import pygame
from gameState import SCREEN_WIDTH, SCREEN_HEIGHT

def draw_recruitment_overlay(surface, target_province):
    """Draws the deployment queue and returns a list of (rect, index) for cancellation."""
    cancel_buttons = []
    
    panel_rect = pygame.Rect(SCREEN_WIDTH - 400, 100, 350, SCREEN_HEIGHT - 200)
    pygame.draw.rect(surface, (30, 30, 50), panel_rect)
    pygame.draw.rect(surface, (100, 100, 250), panel_rect, 2)

    font = pygame.font.SysFont("Arial", 28)
    small_font = pygame.font.SysFont("Arial", 20)
    
    title = font.render("Deployment Queue", True, (255, 255, 255))
    surface.blit(title, (panel_rect.x + 20, panel_rect.y + 20))

    queue = target_province.get("deployment_queue", [])
    
    for i, item in enumerate(queue):
        y_pos = panel_rect.y + 70 + (i * 35)
        
        # Draw the unit info
        name = item['unit_type'].replace("Chadian ", "")
        txt = small_font.render(f"{name} ({item['days_remaining']}d)", True, (255, 200, 50))
        surface.blit(txt, (panel_rect.x + 20, y_pos))
        
        # Draw a small Red "X" button for cancellation
        cancel_rect = pygame.Rect(panel_rect.right - 40, y_pos, 25, 25)
        pygame.draw.rect(surface, (150, 0, 0), cancel_rect)
        x_txt = small_font.render("X", True, (255, 255, 255))
        surface.blit(x_txt, (cancel_rect.x + 7, cancel_rect.y + 2))
        
        # Store the rect and the index of the item it represents
        cancel_buttons.append((cancel_rect, i))
        
    return cancel_buttons