import pygame
import data.constants as c
from map_logic.rendering.font_manager import fonts

def draw_top_text(map_screen, surface):
    """Draws the current date/time and the 'Playing As' country name."""
    if getattr(map_screen, 'hide_top_info', False):
        return

    def draw_with_bg(surf_text, x, y):
        """Helper to draw a semi-transparent background box behind text."""
        bg_rect = pygame.Rect(
            x - c.TOP_BAR_TEXT_BG_PADDING, 
            y - c.TOP_BAR_TEXT_BG_PADDING // 2, 
            surf_text.get_width() + c.TOP_BAR_TEXT_BG_PADDING * 2, 
            surf_text.get_height() + c.TOP_BAR_TEXT_BG_PADDING
        )
        bg_surf = pygame.Surface((bg_rect.width, bg_rect.height), pygame.SRCALPHA)
        bg_surf.fill((30, 30, 40, c.TOP_BAR_TEXT_BG_ALPHA)) # Matches your UI color scheme
        surface.blit(bg_surf, bg_rect.topleft)
        pygame.draw.rect(surface, (100, 100, 100), bg_rect, 1) # Clean UI border
        surface.blit(surf_text, (x, y))

    # 1. Draw Date (Centered)
    date_str = map_screen.time_manager.get_date_string()
    date_surf = fonts.get("top_bar_date").render(date_str, True, (255, 255, 255))
    date_x = c.SCREEN_WIDTH // 2 - date_surf.get_width() // 2
    draw_with_bg(date_surf, date_x, c.TOP_BAR_DATE_Y)

    # 2. Draw "Playing As" Name / Selected Province Owner
    # Check if we have a province selected first, otherwise default to the player country
    if map_screen.selected_province:
        display_id = map_screen.selected_province.get("owner", "Unclaimed")
    else:
        display_id = map_screen.player_country
        
    player_display = map_screen.nation_data.get(display_id, {}).get("name", display_id)
    
    # Grab our new dedicated top bar font preset
    big_font = fonts.get("top_bar_country")
    name_surf = big_font.render(f"{player_display.title()}", True, (200, 200, 200))

    # Position it
    draw_with_bg(name_surf, c.TOP_BAR_COUNTRY_X, c.TOP_BAR_COUNTRY_Y)