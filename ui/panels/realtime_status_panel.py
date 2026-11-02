"""Persistent status chrome for an authoritative real-time match."""

import time
import pygame

import data.constants as c
from data import queries
from ui.rendering.font_manager import fonts
from ui.widgets import ui_elements
from ui.widgets.flag_icons import flag_surface
from ui.widgets.table_screen import TableColumn, TableScreen
from ui.panels.map_top_right_layout import realtime_status_rect

from ui.navigation import screen_runner


def _ping_text(player, host_id):
    if not getattr(player, "connected", True):
        return "Offline"
    if player.player_id == host_id:
        return "Local"
    ping = getattr(player, "ping_ms", None)
    return f"{ping} ms" if isinstance(ping, int) else "Checking..."


# (row key, column label, column width)
MATCH_DETAIL_COLUMNS = (("player", "Player", 190), ("country", "Country", 220), ("turn", "Turn status", 220),
                        ("connection", "Connection", 140), ("ping", "Ping", 110))
MATCH_DETAIL_CONNECTED_COLOR = (240, 240, 245)
MATCH_DETAIL_DISCONNECTED_COLOR = (185, 150, 150)


class _MatchDetails(TableScreen):
    """Read-only live-match roster. The rows follow the session while it is open."""

    def __init__(self, map_screen):
        columns = [TableColumn(key, label, width, align="left",
                               render=lambda row, k=key: row["cells"][k],
                               icon=(lambda row: row["flag"]) if key == "country" else None)
                   for key, label, width in MATCH_DETAIL_COLUMNS]
        self.sorted_column = None
        self.rows_signature = self._signature(map_screen)
        super().__init__(map_screen, "Real-Time Match Details", columns, self._build_rows(map_screen),
                         empty_message="No match is running.")
        self.bg_color = (8, 14, 31)

    @staticmethod
    def _player_values(map_screen):
        """One dict of displayed text and flag owner per player."""
        session = map_screen.realtime_session
        if not session:
            return []
        values = []
        for player in session.players.values():
            turn = "Eliminated / spectating" if player.eliminated else (
                "Submitted" if player.submitted else "Not submitted")
            values.append({
                "player": str(player.name),
                "country": (queries.get_country_display_name(player.country_id, map_screen.nation_data)
                            if player.country_id else "No country"),
                "turn": turn,
                "connection": "Connected" if player.connected else "Disconnected",
                "ping": _ping_text(player, session.host_id),
                "country_id": player.country_id,
                "connected": player.connected,
            })
        return values

    @classmethod
    def _signature(cls, map_screen):
        return [tuple(values.values()) for values in cls._player_values(map_screen)]

    @classmethod
    def _build_rows(cls, map_screen):
        font = fonts.get("small")
        rows = []
        for values in cls._player_values(map_screen):
            color = MATCH_DETAIL_CONNECTED_COLOR if values["connected"] else MATCH_DETAIL_DISCONNECTED_COLOR
            country_id = values["country_id"]
            rows.append({**values,
                         "cells": {key: font.render(values[key], True, color)
                                   for key, _label, _width in MATCH_DETAIL_COLUMNS},
                         "flag": (flag_surface(country_id, map_screen.nation_data)
                                  if country_id and country_id in map_screen.nation_data else None)})
        return rows

    def sort_by(self, col):
        self.sorted_column = col
        super().sort_by(col)

    def update(self):
        signature = self._signature(self.map_screen)
        if signature == self.rows_signature:
            return
        self.rows_signature = signature
        self.rows = self._build_rows(self.map_screen)
        if self.sorted_column:
            # sort_by stores the direction for the next click, so this one is its opposite.
            self.rows.sort(key=self.sorted_column.sort_key,
                           reverse=not self.sort_reverse[self.sorted_column.key])


def show_details(map_screen):
    """Open the roster without blocking the map or networking event loop."""
    screen_runner._run_pygame_sub_screen(map_screen, _MatchDetails(map_screen))


def draw(map_screen, surface):
    if not map_screen.realtime_multiplayer:
        return
    session = map_screen.realtime_session
    player = getattr(session, "players", {}).get(map_screen.realtime_player_id)
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
    connection_error = map_screen.realtime_connection_error
    if connection_error:
        lines.append("CONNECTION LOST - actions disabled; rejoin from the menu")
    # The top-right map controls, including Exit, occupy the first toolbar
    # row. Keep live-match status immediately below that row instead.
    rect = realtime_status_rect(bool(connection_error))
    ui_elements.draw_pixel_panel(surface, rect, (5, 10, 25, 220),
                                 (220, 100, 75) if connection_error else (110, 160, 230))
    font = fonts.get("tiny")
    for index, line in enumerate(lines):
        color = (255, 175, 135) if connection_error and index == len(lines) - 1 else (240, 240, 245)
        surface.blit(font.render(line, True, color), (rect.x + 8, rect.y + 6 + index * 19))
    if session.phase == "GAME_OVER":
        overlay = pygame.Rect(c.SCREEN_WIDTH // 2 - 220, c.SCREEN_HEIGHT // 2 - 125, 440, 250)
        ui_elements.draw_pixel_panel(surface, overlay, (8, 12, 28, 240), (215, 175, 75))
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
            country_name = (queries.get_country_display_name(country, map_screen.nation_data)
                            if country else "No country")
            row = f"{index + 1}. {name} ({country_name}) — {provinces} provinces, {units} units"
            surface.blit(font.render(row, True, (240, 240, 245)), (overlay.x + 20, overlay.y + 62 + index * 21))
        note = fonts.get("tiny").render("Save to keep the result, or Exit to Multiplayer.", True, (190, 200, 220))
        surface.blit(note, note.get_rect(midbottom=(overlay.centerx, overlay.bottom - 15)))
