import pygame
from data.constants import (
    SCREEN_WIDTH, 
    TOP_BAR_DATE_Y, 
    TOP_BAR_COUNTRY_X, 
    TOP_BAR_COUNTRY_Y,
    TOP_BAR_TEXT_BG_PADDING,
    TOP_BAR_TEXT_BG_ALPHA
)

def draw_top_text(map_screen, surface):
    """Draws the current date/time and the 'Playing As' country name."""
    if getattr(map_screen, 'hide_top_info', False):
        return

    def draw_with_bg(surf_text, x, y):
        """Helper to draw a semi-transparent background box behind text."""
        bg_rect = pygame.Rect(
            x - TOP_BAR_TEXT_BG_PADDING, 
            y - TOP_BAR_TEXT_BG_PADDING // 2, 
            surf_text.get_width() + TOP_BAR_TEXT_BG_PADDING * 2, 
            surf_text.get_height() + TOP_BAR_TEXT_BG_PADDING
        )
        bg_surf = pygame.Surface((bg_rect.width, bg_rect.height), pygame.SRCALPHA)
        bg_surf.fill((30, 30, 40, TOP_BAR_TEXT_BG_ALPHA)) # Matches your UI color scheme
        surface.blit(bg_surf, bg_rect.topleft)
        pygame.draw.rect(surface, (100, 100, 100), bg_rect, 1) # Clean UI border
        surface.blit(surf_text, (x, y))

    # 1. Draw Date (Centered)
    date_str = map_screen.time_manager.get_date_string()
    date_surf = map_screen.font.render(date_str, True, (255, 255, 255))
    date_x = SCREEN_WIDTH // 2 - date_surf.get_width() // 2
    draw_with_bg(date_surf, date_x, TOP_BAR_DATE_Y)

    # 2. Draw "Playing As" Name
    player_display = map_screen.nation_data.get(map_screen.player_country, {}).get("name", map_screen.player_country)
    name_surf = map_screen.font.render(f"{player_display.title()}", True, (200, 200, 200))

    # Position it
    draw_with_bg(name_surf, TOP_BAR_COUNTRY_X, TOP_BAR_COUNTRY_Y)