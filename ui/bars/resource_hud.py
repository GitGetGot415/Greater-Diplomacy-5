import pygame
import data.constants as c
from data import queries
from map_logic.rendering.font_manager import fonts

def draw_bottom_text(map_screen, surface):
    """Draws the bottom resource bar with net income overlays."""
    hide_hud = map_screen.hide_resource_hud or map_screen.is_editor
    
    if hide_hud:
        return

    hud_y = c.SCREEN_HEIGHT - c.RESOURCE_HUD_HEIGHT_OFFSET

    resources = queries.get_resource_hud_strings(map_screen, include_net=True)
    
    # Draw Background Box
    bg_width = (len(resources) * c.RESOURCE_HUD_SPACING) - 40
    bg_surf = pygame.Surface((bg_width, 30), pygame.SRCALPHA)
    bg_surf.fill((0, 0, 0, c.RESOURCE_HUD_BG_ALPHA))
    
    bg_rect = pygame.Rect(c.RESOURCE_HUD_START_X - 15, hud_y - 5, bg_width, 30)
    surface.blit(bg_surf, bg_rect.topleft)
    pygame.draw.rect(surface, (100, 100, 100), bg_rect, 1) 

    # Draw Text using the dedicated preset
    hud_font = fonts.get("resource_hud")
    for i, (text, color) in enumerate(resources):
        surface.blit(hud_font.render(text, True, color), (c.RESOURCE_HUD_START_X + (i * c.RESOURCE_HUD_SPACING), hud_y))