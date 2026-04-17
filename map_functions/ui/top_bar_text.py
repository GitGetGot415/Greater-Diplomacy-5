import pygame
from data.constants import SCREEN_WIDTH

def draw_top_text(map_screen, surface):
    """Draws the current date/time and the 'Playing As' country name."""
    if getattr(map_screen, 'hide_top_info', False):
        return

    # 1. Draw Date (Centered)
    date_str = map_screen.time_manager.get_date_string()
    date_surf = map_screen.font.render(date_str, True, (255, 255, 255))
    surface.blit(date_surf, (SCREEN_WIDTH // 2 - date_surf.get_width() // 2, 20))

    # 2. Draw "Playing As" Name
    player_display = map_screen.nation_data.get(map_screen.player_country, {}).get("name", map_screen.player_country)
    name_surf = map_screen.font.render(f"{player_display.title()}", True, (200, 200, 200))
    
    # Position it
    surface.blit(name_surf, (350, 20))