import pygame
import data.constants as c
from data import queries
from ui.rendering.font_manager import fonts
from ui.widgets import ui_elements
from ui.background_styles import RESOURCE_BAR_STYLES

# ==========================================
# LAYOUT
# ==========================================

# --- Map screen strip (the compact one inside the bottom UI bar) ---
HUD_START_X = 300
HUD_SPACING = 200
HUD_HEIGHT_OFFSET = 40
HUD_BG_ALPHA = 200
HUD_BOX_HEIGHT = 30
HUD_BOX_PAD_X = 15
HUD_BOX_PAD_Y = 5
HUD_BOX_TRIM = 40 # Trailing slack shaved off the background box
EVENT_BUTTON_GAP = 10


def unit_event_button_rect():
    """Place the square report button beside the resource panel."""
    size = c.SIZES["small_square"]
    right = HUD_START_X - HUD_BOX_PAD_X + len(c.ECON_RESOURCE_KEYS) * HUD_SPACING - HUD_BOX_TRIM
    center_y = c.SCREEN_HEIGHT - HUD_HEIGHT_OFFSET - HUD_BOX_PAD_Y + HUD_BOX_HEIGHT // 2
    return pygame.Rect(right + EVENT_BUTTON_GAP, center_y - size[1] // 2, *size)

# --- Full-width bar (Production / Orders / diplomacy sub-screens) ---
BAR_HEIGHT = 60
BAR_LINE_COLOR = (100, 100, 100)
BAR_START_X = 50
BAR_SPACING = 300
BAR_TEXT_OFFSET_Y = 15


def draw_bottom_text(map_screen, surface):
    """Draws the map screen's bottom resource strip with net income overlays."""
    if map_screen.hide_resource_hud or map_screen.is_editor:
        return

    hud_y = c.SCREEN_HEIGHT - HUD_HEIGHT_OFFSET

    resources = queries.get_resource_hud_strings(map_screen, include_net=True)

    # Draw Background Box
    bg_width = (len(resources) * HUD_SPACING) - HUD_BOX_TRIM
    bg_rect = pygame.Rect(HUD_START_X - HUD_BOX_PAD_X, hud_y - HUD_BOX_PAD_Y, bg_width, HUD_BOX_HEIGHT)
    ui_elements.draw_pixel_panel(surface, bg_rect, (0, 0, 0, HUD_BG_ALPHA),
                                 BAR_LINE_COLOR, border_width=1)

    # Draw Text using the dedicated preset
    hud_font = fonts.get("resource_hud")
    for i, (text, color) in enumerate(resources):
        surface.blit(hud_font.render(text, True, color), (HUD_START_X + (i * HUD_SPACING), hud_y))


def draw_resource_bar(surface, map_screen, target_nation=None, start_x=None):
    """Draws the full-width resource bar pinned to the bottom of a sub-screen.

    The Production and Orders screens both show this exact bar; keeping it
    here means a tweak to its height or spacing lands on both at once instead
    of the two copies drifting apart.

    `start_x` overrides where the first resource is drawn -- Production and
    Orders pass ui.bars.view_mode_buttons.RESOURCE_BAR_OFFSET_X so their copy
    of the view-mode button row (drawn at the same bottom-left corner) doesn't
    sit under the first entry or two.
    """
    bar_rect = pygame.Rect(0, c.SCREEN_HEIGHT - BAR_HEIGHT, c.SCREEN_WIDTH, BAR_HEIGHT)
    style = RESOURCE_BAR_STYLES["full_width"]
    ui_elements.draw_pixel_panel(surface, bar_rect, style["color"], BAR_LINE_COLOR,
                                 gradient_strength=style["gradient_strength"])

    res_font = fonts.get("production_hud")
    resources = queries.get_resource_hud_strings(map_screen, include_net=False, target_nation=target_nation)
    x0 = BAR_START_X if start_x is None else start_x
    for i, (text, color) in enumerate(resources):
        surface.blit(res_font.render(text, True, color),
                     (x0 + (i * BAR_SPACING), bar_rect.y + BAR_TEXT_OFFSET_Y))

    return bar_rect
