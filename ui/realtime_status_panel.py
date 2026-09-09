"""Persistent status chrome for an authoritative real-time match."""

import time
import pygame

import data.constants as c
from map_logic.rendering.font_manager import fonts


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
    rect = pygame.Rect(c.SCREEN_WIDTH - 330, 8, 320, 67)
    panel = pygame.Surface(rect.size, pygame.SRCALPHA)
    panel.fill((5, 10, 25, 220))
    surface.blit(panel, rect.topleft)
    pygame.draw.rect(surface, (110, 160, 230), rect, 1, border_radius=4)
    font = fonts.get("tiny")
    for index, line in enumerate(lines):
        surface.blit(font.render(line, True, (240, 240, 245)), (rect.x + 8, rect.y + 6 + index * 19))
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
