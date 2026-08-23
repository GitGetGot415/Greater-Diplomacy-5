"""The player's half of the political axis: one line, one marker, three buttons.

The value itself is not editable here -- picking a direction is, and the country
walks one step per processed turn. That is the whole mechanic: a choice you make
now and live with for ten turns, not a slider you drag to whatever you need this
turn.

The axis is drawn rather than built from the Slider widget for exactly that
reason. A Slider invites a drag, and dragging is the one thing this must not
allow. The map editor's version of this screen (screens/editor_screens/
politics_editor.py) *does* use a Slider, because authoring a starting position
is the case where dragging is right.
"""
import pygame
import data.constants as c
from ui_elements import Button, make_back_button
from map_logic.rendering.font_manager import fonts
from gameState import GameState
from map_logic import politics

#: Direction, button face, and the word under it.
DRIFT_OPTIONS = (
    (-1, "<", "Liberalise"),
    (0, "=", "Hold"),
    (1, ">", "Centralise"),
)

TRACK_WIDTH = 520
TRACK_HEIGHT = 8
BUTTON_STEP_X = 130


class Politics_Screen(GameState):
    def __init__(self, map_screen):
        super().__init__()
        # Deep blue-grey; this is the domestic screen, not a war one.
        self.bg_color = (24, 26, 44)
        self.map_screen = map_screen
        self.player = map_screen.player_country
        self.panel_rect = pygame.Rect(c.SCREEN_WIDTH // 2 - 400, 100, 800, c.SCREEN_HEIGHT - 200)

        self.is_valid_player = (self.player in self.map_screen.nation_data
                                and self.player not in ["Spectator", "None", "Editor"])

        self.refresh_ui()

    # ------------------------------------------------------------------ #
    #                               STATE                                #
    # ------------------------------------------------------------------ #

    @property
    def value(self):
        return politics.value(self.map_screen.nation_data, self.player)

    @property
    def drift(self):
        return politics.drift(self.map_screen.nation_data, self.player)

    def set_drift(self, direction):
        if not self.is_valid_player:
            return
        # Refuse a direction there is no axis left to travel in. Accepting it
        # would put the arrow badge back on the map button for a move that can
        # never happen, which is exactly the state the badge exists to rule out.
        if ((direction > 0 and self.value >= c.POLITICS_MAX)
                or (direction < 0 and self.value <= c.POLITICS_MIN)):
            self.map_screen.show_feedback("Already as far as this country can go.")
            return
        politics.set_drift(self.map_screen.nation_data, self.player, direction)
        self.refresh_ui()

    # ------------------------------------------------------------------ #
    #                               LAYOUT                               #
    # ------------------------------------------------------------------ #

    def refresh_ui(self):
        self.elements = [make_back_button(self.exit_screen, style="map")]

        if not self.is_valid_player:
            return

        current = self.drift
        centre_x = self.panel_rect.centerx
        y = self.panel_rect.bottom - 160

        for direction, face, _caption in DRIFT_OPTIONS:
            btn = Button(centre_x + BUTTON_STEP_X * direction - 25, y,
                         "medium_square", "blue" if direction else "grey",
                         face, lambda d=direction: self.set_drift(d))
            btn.is_selected = (current == direction)
            self.elements.append(btn)

    # ------------------------------------------------------------------ #
    #                              DRAWING                               #
    # ------------------------------------------------------------------ #

    def _track_rect(self):
        return pygame.Rect(self.panel_rect.centerx - TRACK_WIDTH // 2,
                           self.panel_rect.centery - TRACK_HEIGHT // 2,
                           TRACK_WIDTH, TRACK_HEIGHT)

    def _x_for(self, political_value):
        """Where a value sits along the track."""
        track = self._track_rect()
        span = float(c.POLITICS_MAX - c.POLITICS_MIN)
        return track.x + int(track.width * (political_value - c.POLITICS_MIN) / span)

    def additional_draw(self, surface):
        pygame.draw.rect(surface, (34, 38, 58), self.panel_rect)
        pygame.draw.rect(surface, c.COLOR_DIM_BORDER, self.panel_rect, 3)

        title_surf = fonts.get("title").render("Politics", True, c.COLOR_GOLD_HIGHLIGHT)
        surface.blit(title_surf, (self.panel_rect.centerx - title_surf.get_width() // 2,
                                  self.panel_rect.y + 20))

        if not self.is_valid_player:
            msg = fonts.get("normal").render("Politics is not available in Spectator Mode.",
                                             True, (255, 150, 150))
            surface.blit(msg, (self.panel_rect.centerx - msg.get_width() // 2,
                               self.panel_rect.centery))
            return

        self._draw_axis(surface)
        self._draw_effects(surface)
        self._draw_captions(surface)

    def _draw_axis(self, surface):
        track = self._track_rect()
        normal, small = fonts.get("normal"), fonts.get("small")

        pygame.draw.rect(surface, c.COLOR_SLIDER_TRACK, track)

        # Ticks at both ends and dead centre, so the marker reads as a position
        # on a line rather than as a bar filling up.
        for tick_value in (c.POLITICS_MIN, 0, c.POLITICS_MAX):
            tick_x = self._x_for(tick_value)
            pygame.draw.line(surface, c.UI_TEXT_MUTED,
                             (tick_x, track.y - 10), (tick_x, track.bottom + 10), 2)

        marker_x = self._x_for(self.value)
        pygame.draw.circle(surface, c.COLOR_GOLD_HIGHLIGHT, (marker_x, track.centery), 12)
        pygame.draw.circle(surface, (255, 255, 255), (marker_x, track.centery), 12, 2)

        left = normal.render("Libertarian", True, c.UI_TEXT_LIGHT)
        right = normal.render("Authoritarian", True, c.UI_TEXT_LIGHT)
        surface.blit(left, (track.x - left.get_width() - 20,
                            track.centery - left.get_height() // 2))
        surface.blit(right, (track.right + 20, track.centery - right.get_height() // 2))

        reading = small.render("%s  (%+d)" % (politics.label(self.value), self.value),
                               True, c.COLOR_GOLD_HIGHLIGHT)
        surface.blit(reading, (marker_x - reading.get_width() // 2, track.bottom + 26))

    def _draw_effects(self, surface):
        normal = fonts.get("normal")
        nation_data = self.map_screen.nation_data
        damage = politics.damage_multiplier(nation_data, self.player)
        research = politics.research_multiplier(nation_data, self.player)

        text = "Damage dealt  x%.2f          Research speed  x%.2f" % (damage, research)
        line = normal.render(text, True, c.UI_TEXT_LIGHT)
        surface.blit(line, (self.panel_rect.centerx - line.get_width() // 2,
                            self.panel_rect.centery + 60))

    def _draw_captions(self, surface):
        small = fonts.get("small")
        centre_x = self.panel_rect.centerx
        caption_y = self.panel_rect.bottom - 100

        for direction, _face, caption in DRIFT_OPTIONS:
            surf = small.render(caption, True, c.UI_TEXT_MUTED)
            surface.blit(surf, (centre_x + BUTTON_STEP_X * direction - surf.get_width() // 2,
                                caption_y))

        if self.drift:
            note = ("Moving %s one step per turn until you stop it or it reaches the end."
                    % ("left" if self.drift < 0 else "right"))
        else:
            note = "Holding position. Nothing changes until you pick a direction."
        surf = small.render(note, True, c.UI_TEXT_DIM)
        surface.blit(surf, (centre_x - surf.get_width() // 2, self.panel_rect.bottom - 60))
