import pygame
import data.constants as c
from map_logic.rendering.font_manager import fonts
from ui.bars import ui_bars

# ==========================================
# LAYOUT
# ==========================================

TOP_BAR_COUNTRY_X = 180
TOP_BAR_COUNTRY_Y = 15
TOP_BAR_TEXT_BG_PADDING = 10
TOP_BAR_TEXT_BG_ALPHA = 180
TOP_BAR_TEXT_BG_COLOR = (30, 30, 40)
TOP_BAR_TEXT_BORDER_COLOR = (100, 100, 100)

# The date sits above the bottom bar rather than in the top one.
DATE_X = 300
DATE_Y_OFFSET = -50

def draw_top_text(map_screen, surface):
    """Draws the current date/time and the 'Playing As' country name."""
    if map_screen.hide_top_info:
        return

    def draw_with_bg(surf_text, x, y):
        """Helper to draw a semi-transparent background box behind text."""
        bg_rect = pygame.Rect(
            x - TOP_BAR_TEXT_BG_PADDING, 
            y - TOP_BAR_TEXT_BG_PADDING // 2, 
            surf_text.get_width() + TOP_BAR_TEXT_BG_PADDING * 2, 
            surf_text.get_height() + TOP_BAR_TEXT_BG_PADDING
        )
        ui_bars.draw_translucent_panel(surface, bg_rect,
                                       (*TOP_BAR_TEXT_BG_COLOR, TOP_BAR_TEXT_BG_ALPHA),
                                       border_color=TOP_BAR_TEXT_BORDER_COLOR, border_width=1)
        surface.blit(surf_text, (x, y))

    # 1. Draw Date (Centered)
    date_str = map_screen.time_manager.get_date_string()
    date_surf = fonts.get("date_bar").render(date_str, True, (255, 255, 255))
    draw_with_bg(date_surf, DATE_X, c.BOTTOM_BAR_UI_CENTER_Y + DATE_Y_OFFSET)

    # 2. Draw "Playing As" Name / Selected Province Owner / Tactical Unit Name
    if map_screen.tactical_mode and map_screen.player_unit:
        if map_screen.selected_province:
            display_id = map_screen.selected_province.get("owner", "Unclaimed")
            player_display = map_screen.nation_data.get(display_id, {}).get("name", display_id)
        else:
            player_display = map_screen.player_unit.get("custom_name", map_screen.player_unit.get("type", "Unknown Unit"))
    else:
        # Check if we have a province selected first, otherwise default to the player country
        if map_screen.selected_province:
            display_id = map_screen.selected_province.get("owner", "Unclaimed")
        else:
            display_id = map_screen.player_country
            
        player_display = map_screen.nation_data.get(display_id, {}).get("name", display_id)
    
    # Grab our new dedicated top bar font preset
    big_font = fonts.get("top_bar_country")
    name_surf = big_font.render(f"{player_display}", True, c.UI_TEXT_LIGHT)

    # Position it
    draw_with_bg(name_surf, TOP_BAR_COUNTRY_X, TOP_BAR_COUNTRY_Y)