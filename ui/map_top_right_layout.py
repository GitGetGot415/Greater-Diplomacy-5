"""Shared geometry for map UI that occupies the top-right map viewport."""

import pygame

import data.constants as c


PANEL_WIDTH = 260
PANEL_RIGHT_MARGIN = 10
PANEL_GAP = 8
CARD_HEIGHT = 42
TRAY_HEADER_HEIGHT = 23


def realtime_status_rect(connection_error=False):
    """The live-match status reservation beneath the top toolbar."""
    return pygame.Rect(c.SCREEN_WIDTH - 330, 58, 320,
                       86 if connection_error else 67)


def army_tray_rect(map_screen, army_count=0):
    """Content-sized army tray below all active top-right consumers."""
    top = c.TOP_UI_HEIGHT + PANEL_GAP
    details = getattr(map_screen, "btn_realtime_details", None)
    if getattr(map_screen, "realtime_multiplayer", False):
        connection_error = bool(getattr(map_screen, "realtime_connection_error", ""))
        status = realtime_status_rect(connection_error)
        top = max(top, status.bottom + PANEL_GAP)
        if details and details.visible:
            top = max(top, details.rect.bottom + PANEL_GAP)
    bottom = c.SCREEN_HEIGHT - c.BOT_UI_HEIGHT - PANEL_GAP
    available_height = max(1, bottom - top)
    wanted_height = (TRAY_HEADER_HEIGHT + 8
                     + max(1, army_count) * (CARD_HEIGHT + 5))
    return pygame.Rect(c.SCREEN_WIDTH - PANEL_WIDTH - PANEL_RIGHT_MARGIN,
                       top, PANEL_WIDTH, min(available_height, wanted_height))


def card_rect(tray_rect, index, scroll_y=0):
    return pygame.Rect(tray_rect.x, tray_rect.y + TRAY_HEADER_HEIGHT + index * (CARD_HEIGHT + 5) + scroll_y,
                       tray_rect.width, CARD_HEIGHT)
