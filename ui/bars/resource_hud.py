import pygame
import data.constants as c
from data import queries
from map_logic.rendering.font_manager import fonts

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

# --- Full-width bar (Production / Orders / diplomacy sub-screens) ---
BAR_HEIGHT = 60
BAR_BG_COLOR = (30, 30, 30)
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
    bg_surf = pygame.Surface((bg_width, HUD_BOX_HEIGHT), pygame.SRCALPHA)
    bg_surf.fill((0, 0, 0, HUD_BG_ALPHA))

    bg_rect = pygame.Rect(HUD_START_X - HUD_BOX_PAD_X, hud_y - HUD_BOX_PAD_Y, bg_width, HUD_BOX_HEIGHT)
    surface.blit(bg_surf, bg_rect.topleft)
    pygame.draw.rect(surface, BAR_LINE_COLOR, bg_rect, 1)

    # Draw Text using the dedicated preset
    hud_font = fonts.get("resource_hud")
    for i, (text, color) in enumerate(resources):
        surface.blit(hud_font.render(text, True, color), (HUD_START_X + (i * HUD_SPACING), hud_y))


def draw_resource_bar(surface, map_screen, target_nation=None):
    """Draws the full-width resource bar pinned to the bottom of a sub-screen.

    The Production, Orders and diplomacy overlay screens all show this exact
    bar; keeping it here means a tweak to its height or spacing lands on all
    three at once instead of the three copies drifting apart.
    """
    bar_rect = pygame.Rect(0, c.SCREEN_HEIGHT - BAR_HEIGHT, c.SCREEN_WIDTH, BAR_HEIGHT)
    pygame.draw.rect(surface, BAR_BG_COLOR, bar_rect)
    pygame.draw.line(surface, BAR_LINE_COLOR, (0, bar_rect.y), (c.SCREEN_WIDTH, bar_rect.y), 2)

    res_font = fonts.get("production_hud")
    resources = queries.get_resource_hud_strings(map_screen, include_net=False, target_nation=target_nation)
    for i, (text, color) in enumerate(resources):
        surface.blit(res_font.render(text, True, color),
                     (BAR_START_X + (i * BAR_SPACING), bar_rect.y + BAR_TEXT_OFFSET_Y))

    return bar_rect
