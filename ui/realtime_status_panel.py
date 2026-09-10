"""Persistent status chrome for an authoritative real-time match."""

import time
import pygame

import data.constants as c
from gameState import GameState
from map_logic.rendering.font_manager import fonts
from ui_elements import make_back_button
from ui.flag_icons import draw_flag


def _ping_text(player, host_id):
    if not getattr(player, "connected", True):
        return "Offline"
    if player.player_id == host_id:
        return "Local"
    ping = getattr(player, "ping_ms", None)
    return f"{ping} ms" if isinstance(ping, int) else "Checking..."


class _MatchDetails(GameState):
    """Read-only live-match roster shown over the map without pausing it."""
    title = "Real-Time Match Details"
    title_y = 105

    def __init__(self, map_screen):
        super().__init__()
        self.map_screen = map_screen
        self.bg_color = (8, 14, 31)
        self.elements = [make_back_button(self.exit_screen, style="map")]

    def additional_draw(self, surface):
        session = getattr(self.map_screen, "realtime_session", None)
        if not session:
            return
        panel = pygame.Rect(c.SCREEN_WIDTH // 2 - 390, 140, 780,
                            min(470, 115 + 48 * max(1, len(session.players))))
        pygame.draw.rect(surface, (16, 25, 52), panel, border_radius=7)
        pygame.draw.rect(surface, (105, 160, 235), panel, 2, border_radius=7)
        heading_font, row_font = fonts.get("normal"), fonts.get("tiny")
        headings = ("Player", "Country", "Turn status", "Connection", "Ping")
        columns = (panel.x + 24, panel.x + 210, panel.x + 365, panel.x + 555, panel.x + 675)
        for heading, x in zip(headings, columns):
            surface.blit(heading_font.render(heading, True, (180, 210, 255)), (x, panel.y + 18))
        for index, player in enumerate(session.players.values()):
            y = panel.y + 56 + index * 45
            submitted = "Eliminated / spectating" if player.eliminated else (
                "Submitted" if player.submitted else "Not submitted")
            connection = "Connected" if player.connected else "Disconnected"
            values = (player.name, submitted, connection, _ping_text(player, session.host_id))
            color = (240, 240, 245) if player.connected else (185, 150, 150)
            surface.blit(row_font.render(str(values[0]), True, color), (columns[0], y))
            country = player.country_id or "No country"
            country_x = columns[1]
            if player.country_id and player.country_id in getattr(self.map_screen, "nation_data", {}):
                country_x = draw_flag(surface, player.country_id, self.map_screen.nation_data,
                                      country_x, y + 1)
            surface.blit(row_font.render(str(country), True, color), (country_x, y))
            for value, x in zip(values[1:], columns[2:]):
                surface.blit(row_font.render(str(value), True, color), (x, y))


def show_details(map_screen):
    """Open the roster without blocking the map or networking event loop."""
    from ui.screen_runner import _run_pygame_sub_screen
    _run_pygame_sub_screen(map_screen, _MatchDetails(map_screen))


def draw(map_screen, surface):
    if not getattr(map_screen, "realtime_multiplayer", False):
        return
    session = getattr(map_screen, "realtime_session", None)
    player = getattr(session, "players", {}).get(getattr(map_screen, "realtime_player_id", None))
    if not session or not player:
        return
    remaining = max(0, session.config.max_turns - session.turn_number + 1)
    seconds = max(0, int((session.deadline or time.monotonic()) - time.monotonic()))
    countdown = f"{seconds // 60}:{seconds % 60:02d}"
    submitted = sum(1 for item in session.players.values() if item.submitted or item.eliminated)
    active = sum(1 for item in session.players.values() if not item.eliminated)
    if session.phase == "GAME_OVER":
        state = "MATCH OVER"
    elif session.phase == "PROCESSING":
        state = "PROCESSING TURN..."
    elif player.eliminated:
        state = "ELIMINATED — SPECTATING"
    else:
        state = "SUBMITTED" if player.submitted else "NOT SUBMITTED"
    lines = [f"Turn {session.turn_number} / {session.config.max_turns}  •  {remaining} remaining",
             f"Time: {countdown}  •  {submitted} / {active} players submitted", state]
    connection_error = getattr(map_screen, "realtime_connection_error", "")
    if connection_error:
        lines.append("CONNECTION LOST - actions disabled; rejoin from the menu")
    # The top-right map controls, including Exit, occupy the first toolbar
    # row. Keep live-match status immediately below that row instead.
    rect = pygame.Rect(c.SCREEN_WIDTH - 330, 58, 320, 86 if connection_error else 67)
    panel = pygame.Surface(rect.size, pygame.SRCALPHA)
    panel.fill((5, 10, 25, 220))
    surface.blit(panel, rect.topleft)
    pygame.draw.rect(surface, (220, 100, 75) if connection_error else (110, 160, 230),
                     rect, 1, border_radius=4)
    font = fonts.get("tiny")
    for index, line in enumerate(lines):
        color = (255, 175, 135) if connection_error and index == len(lines) - 1 else (240, 240, 245)
        surface.blit(font.render(line, True, color), (rect.x + 8, rect.y + 6 + index * 19))
    if session.phase == "GAME_OVER":
        overlay = pygame.Rect(c.SCREEN_WIDTH // 2 - 220, c.SCREEN_HEIGHT // 2 - 125, 440, 250)
        panel = pygame.Surface(overlay.size, pygame.SRCALPHA)
        panel.fill((8, 12, 28, 240))
        surface.blit(panel, overlay.topleft)
        pygame.draw.rect(surface, (215, 175, 75), overlay, 2, border_radius=7)
        heading = fonts.get("heading2").render("REAL-TIME MATCH OVER", True, (255, 225, 135))
        surface.blit(heading, heading.get_rect(midtop=(overlay.centerx, overlay.y + 16)))
        standings = []
        for item in session.players.values():
            provinces = sum(1 for province in map_screen.map_data.values()
                            if province.get("owner") == item.country_id)
            units = sum(1 for province in map_screen.map_data.values()
                        for unit in province.get("units", []) if unit.get("owner") == item.country_id)
            standings.append((provinces, units, item.name, item.country_id))
        for index, (provinces, units, name, country) in enumerate(sorted(standings, reverse=True)):
            row = f"{index + 1}. {name} ({country}) — {provinces} provinces, {units} units"
            surface.blit(font.render(row, True, (240, 240, 245)), (overlay.x + 20, overlay.y + 62 + index * 21))
        note = fonts.get("tiny").render("Save to keep the result, or Exit to Multiplayer.", True, (190, 200, 220))
        surface.blit(note, note.get_rect(midbottom=(overlay.centerx, overlay.bottom - 15)))
