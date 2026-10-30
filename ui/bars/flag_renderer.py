import pygame
from functools import lru_cache

import data.constants as c
from ui.widgets import flag_icons

FLAG_RECT = pygame.Rect(20, 20, 120, 80)
FLAG_HOVER_BRIGHTNESS = 35


def displayed_country(map_screen):
    """Use the selected land owner, or the player's country, for the flag."""
    country = map_screen.player_country
    province = map_screen.selected_province
    if province and province.get("owner", "Unclaimed") not in c.UNPLAYABLE_NATIONS:
        country = province.get("owner")
    return country


def summary_country(map_screen):
    """Return the flag's country only while its summary control is available."""
    # Optional attributes support map-input test doubles and older tool screens.
    blocked = ("hide_top_info", "hide_flag", "selection_mode", "show_player_ready_screen",
               "show_exit_confirmation", "is_saving", "ai_is_thinking", "viewing_ai_moves")
    if any(getattr(map_screen, name, False) for name in blocked):
        return None
    country = displayed_country(map_screen)
    if country in c.UNPLAYABLE_NATIONS or country not in map_screen.nation_data:
        return None
    return country


def flag_button_rect(map_screen):
    """Share the visible flag's hitbox between map drawing and input."""
    return FLAG_RECT.copy() if summary_country(map_screen) is not None else None


@lru_cache(maxsize=64)
def _highlighted_flag(flag):
    highlighted = flag.copy()
    highlighted.fill((FLAG_HOVER_BRIGHTNESS,) * 3, special_flags=pygame.BLEND_RGB_ADD)
    return highlighted


def draw_flag(map_screen, surface):
    """Draw the cached flag and highlight its country summary control on hover."""
    if map_screen.hide_top_info or map_screen.hide_flag:
        return
    country = displayed_country(map_screen)
    flag = flag_icons.flag_surface(country, map_screen.nation_data, FLAG_RECT.size)
    button_rect = flag_button_rect(map_screen)
    hovered = button_rect is not None and button_rect.collidepoint(pygame.mouse.get_pos())
    surface.blit(_highlighted_flag(flag) if hovered else flag, FLAG_RECT)
    pygame.draw.rect(surface, c.UI_ACCENT_BLUE if hovered else c.UI_TEXT_LIGHT,
                     FLAG_RECT, 3 if hovered else 1)
