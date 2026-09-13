"""The player's half of the political axis: one line, one marker, three buttons.

The value itself is not editable here -- picking a direction is, and the country
walks one step per processed turn. That is the whole mechanic: a choice you make
now and live with for ten turns, not a slider you drag to whatever you need this
turn.

The axis is drawn rather than built from the Slider widget for exactly that
reason. A Slider invites a drag, and dragging is the one thing this must not
allow. The map editor's version of this screen (screens/editor_screens/
politics_editor.py) *does* use a Slider, because authoring a starting position
is the case where dragging is right. Tactical mode keeps the player-facing
axis readable but locks its direction controls while the player commands a
single unit.
"""
import pygame
import data.constants as c
from ui_elements import Button, make_back_button
from ui.bars import ui_bars
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

# The politics screen intentionally keeps both panels the same size.  Change
# these values to retune the whole screen layout without hunting through draw
# calls below.
PANEL_WIDTH = 800
SCREEN_PANEL_MARGIN_Y = 20
PANEL_GAP = 20

POLITICS_TITLE_OFFSET_Y = 18
POLITICS_TRACK_OFFSET_Y = 112
POLITICS_EFFECTS_OFFSET_Y = 170
POLITICS_BUTTON_OFFSET_Y = 205
POLITICS_CAPTION_OFFSET_Y = 267
POLITICS_NOTE_OFFSET_FROM_BOTTOM = 34

POLICY_VIEWPORT_MARGIN_X = 20
POLICY_VIEWPORT_TOP_OFFSET_Y = 62
POLICY_VIEWPORT_BOTTOM_OFFSET_Y = 38
POLICY_CARD_WIDTH = 250
POLICY_CARD_GAP = 16
POLICY_SCROLL_WHEEL_STEP = 90
POLICY_SCROLLBAR_HEIGHT = 14
POLICY_CARD_PADDING = 12


class Politics_Screen(GameState):
    def __init__(self, map_screen, country_id=None):
        super().__init__()
        # Deep blue-grey; this is the domestic screen, not a war one.
        self.bg_color = (24, 26, 44)
        self.map_screen = map_screen
        # ``player`` remains the country whose data this screen displays so
        # the rendering and policy helpers have one subject throughout.  A
        # foreign subject is deliberately read-only: seeing a country's
        # politics must never let an observer steer it or alter its policies.
        self.player = country_id or map_screen.player_country
        self.is_read_only = country_id is not None and country_id != map_screen.player_country
        self._set_panel_rects()
        self.policy_scroll_x = 0
        self.policy_scroll_min_x = 0
        self.policy_scrollbar_dragging = False
        self.policy_scroll_track_rect = None
        self.policy_scroll_handle_rect = None

        self.is_valid_player = (self.player in self.map_screen.nation_data
                                and self.player not in ["Spectator", "None", "Editor"])

        self.refresh_ui()

    def _set_panel_rects(self):
        """Lay out two equally sized panels in the screen's usable height."""
        available_height = c.SCREEN_HEIGHT - 2 * SCREEN_PANEL_MARGIN_Y - PANEL_GAP
        politics_height = available_height // 2
        policies_height = available_height - politics_height
        panel_x = c.SCREEN_WIDTH // 2 - PANEL_WIDTH // 2

        self.politics_rect = pygame.Rect(panel_x, SCREEN_PANEL_MARGIN_Y,
                                         PANEL_WIDTH, politics_height)
        self.policies_rect = pygame.Rect(panel_x, self.politics_rect.bottom + PANEL_GAP,
                                         PANEL_WIDTH, policies_height)
        # Kept as the politics panel for code outside this screen that may use
        # the established attribute name.
        self.panel_rect = self.politics_rect

    # ------------------------------------------------------------------ #
    #                               STATE                                #
    # ------------------------------------------------------------------ #

    @property
    def value(self):
        return politics.value(self.map_screen.nation_data, self.player)

    @property
    def drift(self):
        return politics.drift(self.map_screen.nation_data, self.player)

    @property
    def can_edit(self):
        """Whether this screen may change the player's political direction."""
        if (self.is_read_only or not self.is_valid_player
                or getattr(self.map_screen, "tactical_mode", False)):
            return False
        if getattr(self.map_screen, "realtime_multiplayer", False):
            session = getattr(self.map_screen, "realtime_session", None)
            player = getattr(session, "players", {}).get(
                getattr(self.map_screen, "realtime_player_id", None))
            return bool(session and session.phase == "TURN" and player and not player.submitted and not player.eliminated)
        return True

    def set_drift(self, direction):
        if not self.can_edit:
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
        self._update_policy_scroll_bounds()
        self.scroll_content_rect = self._policy_viewport_rect()

        if not self.is_valid_player:
            return

        # Requirements may change outside this screen (for example, in the map
        # editor), so an editable country's panel reconciles them before it is
        # drawn.  Inspection of a foreign country is strictly read-only.
        if self.can_edit:
            politics.reconcile_policy(self.map_screen.nation_data, self.player)

        current = self.drift
        centre_x = self.politics_rect.centerx
        y = self.politics_rect.y + POLITICS_BUTTON_OFFSET_Y

        if not self.is_read_only:
            for direction, face, _caption in DRIFT_OPTIONS:
                btn = Button(centre_x + BUTTON_STEP_X * direction - 25, y,
                             "medium_square", "blue" if direction else "grey",
                             face, lambda d=direction: self.set_drift(d))
                btn.is_selected = (current == direction)
                btn.disabled = not self.can_edit
                self.elements.append(btn)

        if not self.is_read_only:
            for definition in politics.POLICIES:
                button = self._make_policy_button(definition)
                button.is_scrollable = True
                viewport = self._policy_viewport_rect()
                button.click_guard = lambda rect=viewport: rect.collidepoint(pygame.mouse.get_pos())
                self.elements.append(button)

    def _policy_viewport_rect(self):
        return pygame.Rect(
            self.policies_rect.x + POLICY_VIEWPORT_MARGIN_X,
            self.policies_rect.y + POLICY_VIEWPORT_TOP_OFFSET_Y,
            self.policies_rect.width - 2 * POLICY_VIEWPORT_MARGIN_X,
            self.policies_rect.height - POLICY_VIEWPORT_TOP_OFFSET_Y - POLICY_VIEWPORT_BOTTOM_OFFSET_Y,
        )

    def _policy_content_width(self):
        return (len(politics.POLICIES) * POLICY_CARD_WIDTH
                + max(0, len(politics.POLICIES) - 1) * POLICY_CARD_GAP)

    def _update_policy_scroll_bounds(self):
        viewport = self._policy_viewport_rect()
        self.policy_scroll_min_x = min(0, viewport.width - self._policy_content_width())
        self.policy_scroll_x = max(self.policy_scroll_min_x, min(0, self.policy_scroll_x))

    def _policy_card_rect(self, index):
        viewport = self._policy_viewport_rect()
        return pygame.Rect(viewport.x + self.policy_scroll_x
                           + index * (POLICY_CARD_WIDTH + POLICY_CARD_GAP),
                           viewport.y, POLICY_CARD_WIDTH, viewport.height)

    def _make_policy_button(self, definition):
        index = politics.POLICIES.index(definition)
        card = self._policy_card_rect(index)
        label, color, disabled = self._policy_button_appearance(definition)
        button = Button(card.centerx - 50, card.bottom - 48, "small", color, label,
                        lambda policy_id=definition["id"]: self.toggle_policy(policy_id))
        button.disabled = disabled
        return button

    def _policy_button_appearance(self, definition):
        state = politics.policy_state(self.map_screen.nation_data, self.player, definition["id"])
        if state:
            if state["status"] == politics.POLICY_CANCELLING:
                return "Undo Cancel", "green", not self.can_edit
            return "Cancel", "red", not self.can_edit
        if not politics.requirements_met(self.map_screen.nation_data, self.player, definition["id"]):
            return "Requirements Unmet", "grey", True
        return "Activate", "blue", not self.can_edit

    def toggle_policy(self, policy_id):
        before = politics.policy_state(self.map_screen.nation_data, self.player, policy_id)
        definition = politics.policy(policy_id)
        if not definition or not self.can_edit:
            return
        if not politics.activate_or_cancel_policy(self.map_screen.nation_data, self.player, policy_id):
            self.map_screen.show_feedback("This policy's political requirement is not met.")
            return

        after = politics.policy_state(self.map_screen.nation_data, self.player, policy_id)
        if before and before["status"] == politics.POLICY_CANCELLING:
            message = "%s cancellation undone." % definition["name"]
        elif before and before["status"] == politics.POLICY_ACTIVATING and after is None:
            message = "%s activation cancelled." % definition["name"]
        elif after and after["status"] == politics.POLICY_CANCELLING:
            message = "%s will cancel next turn." % definition["name"]
        else:
            message = "%s activates in %d turns." % (definition["name"],
                                                        politics.POLICY_ACTIVATION_TURNS)
        self.map_screen.show_feedback(message)
        self.refresh_ui()

    # ------------------------------------------------------------------ #
    #                              DRAWING                               #
    # ------------------------------------------------------------------ #

    def _track_rect(self):
        return pygame.Rect(self.politics_rect.centerx - TRACK_WIDTH // 2,
                           self.politics_rect.y + POLITICS_TRACK_OFFSET_Y,
                           TRACK_WIDTH, TRACK_HEIGHT)

    def _x_for(self, political_value):
        """Where a value sits along the track."""
        track = self._track_rect()
        span = float(c.POLITICS_MAX - c.POLITICS_MIN)
        return track.x + int(track.width * (political_value - c.POLITICS_MIN) / span)

    def additional_draw(self, surface):
        self._draw_panel(surface, self.politics_rect)
        self._draw_panel(surface, self.policies_rect)

        title = ("%s Politics" % self.map_screen.nation_data.get(
            self.player, {}).get("name", self.player)
                 if self.is_read_only else "Politics")
        title_surf = fonts.get("title").render(title, True, c.COLOR_GOLD_HIGHLIGHT)
        surface.blit(title_surf, (self.politics_rect.centerx - title_surf.get_width() // 2,
                                  self.politics_rect.y + POLITICS_TITLE_OFFSET_Y))

        subtitle = ("Viewing this country's internal political position and policies."
                    if self.is_read_only else
                    "Liberalising raises research speed but weakens army damage; "
                    "centralising does the reverse.")
        subtitle_surf = fonts.get("small").render(subtitle, True, c.UI_TEXT_DIM)
        surface.blit(subtitle_surf, (self.politics_rect.centerx - subtitle_surf.get_width() // 2,
                                     self.politics_rect.y + POLITICS_TITLE_OFFSET_Y
                                     + title_surf.get_height() + 6))

        policies_title = fonts.get("title").render("Policies", True, c.COLOR_GOLD_HIGHLIGHT)
        surface.blit(policies_title, (self.policies_rect.centerx - policies_title.get_width() // 2,
                                      self.policies_rect.y + POLITICS_TITLE_OFFSET_Y))

        if not self.is_valid_player:
            msg = fonts.get("normal").render("Politics is not available in Spectator Mode.",
                                             True, (255, 150, 150))
            surface.blit(msg, (self.politics_rect.centerx - msg.get_width() // 2,
                               self.politics_rect.centery))
            return

        self._draw_axis(surface)
        self._draw_effects(surface)
        self._draw_captions(surface)
        self._draw_policies(surface)

    @staticmethod
    def _draw_panel(surface, rect):
        pygame.draw.rect(surface, (34, 38, 58), rect)
        pygame.draw.rect(surface, c.COLOR_DIM_BORDER, rect, 3)

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
        surface.blit(line, (self.politics_rect.centerx - line.get_width() // 2,
                            self.politics_rect.y + POLITICS_EFFECTS_OFFSET_Y))

    def _draw_policies(self, surface):
        viewport = self._policy_viewport_rect()
        with ui_bars.clip_scroll_region(surface, viewport):
            for index, definition in enumerate(politics.POLICIES):
                self._draw_policy_card(surface, self._policy_card_rect(index), definition)

        track, handle = ui_bars.draw_standard_scrollbar_horizontal(
            surface, self.policy_scroll_x, self.policy_scroll_min_x, 0,
            viewport.x, self.policies_rect.bottom - POLICY_SCROLLBAR_HEIGHT - 10,
            viewport.width, POLICY_SCROLLBAR_HEIGHT)
        self.policy_scroll_track_rect = track
        self.policy_scroll_handle_rect = handle

    def _draw_policy_card(self, surface, card, definition):
        state = politics.policy_state(self.map_screen.nation_data, self.player, definition["id"])
        if state and state["status"] == politics.POLICY_ACTIVE:
            border = c.COLOR_GOLD_HIGHLIGHT
        elif state:
            border = (120, 170, 255)
        else:
            border = c.COLOR_DIM_BORDER
        pygame.draw.rect(surface, (27, 31, 49), card)
        pygame.draw.rect(surface, border, card, 2)

        heading = fonts.get("heading2").render(definition["name"], True, c.UI_TEXT_LIGHT)
        surface.blit(heading, heading.get_rect(centerx=card.centerx,
                                                y=card.y + POLICY_CARD_PADDING))
        y = card.y + POLICY_CARD_PADDING + heading.get_height() + 8
        small = fonts.get("small")
        for line in definition["effect_lines"]:
            effect = small.render(line, True, c.UI_TEXT_MUTED)
            surface.blit(effect, (card.x + POLICY_CARD_PADDING, y))
            y += effect.get_height() + 3

        requirement = small.render(politics.requirement_text(definition["id"]), True,
                                   c.UI_TEXT_DIM if politics.requirements_met(
                                       self.map_screen.nation_data, self.player, definition["id"])
                                   else (255, 150, 150))
        surface.blit(requirement, (card.x + POLICY_CARD_PADDING, y + 4))

        status = self._policy_status_text(definition, state)
        status_surf = small.render(status, True, c.COLOR_GOLD_HIGHLIGHT if state else c.UI_TEXT_MUTED)
        surface.blit(status_surf, (card.x + POLICY_CARD_PADDING, card.bottom - 74))

    @staticmethod
    def _policy_status_text(definition, state):
        if not state:
            return "Inactive"
        if state["status"] == politics.POLICY_ACTIVE:
            return "Active"
        if state["status"] == politics.POLICY_CANCELLING:
            return "Cancelling: %d turn remaining" % state.get("turns_remaining", 1)
        return "Activating: %d turns remaining" % state.get("turns_remaining", 0)

    def additional_events(self, event):
        viewport = self._policy_viewport_rect()
        if event.type == pygame.MOUSEWHEEL and viewport.collidepoint(pygame.mouse.get_pos()):
            self.policy_scroll_x = max(self.policy_scroll_min_x,
                                       min(0, self.policy_scroll_x + event.y * POLICY_SCROLL_WHEEL_STEP))
            self.refresh_ui()
            return

        if self._handle_policy_scrollbar(event):
            return
        self.handle_content_drag(event, attr="policy_scroll_x", limit_attr="policy_scroll_min_x",
                                 rect_attr="scroll_content_rect", axis="x")

    def _handle_policy_scrollbar(self, event):
        if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            was_dragging = self.policy_scrollbar_dragging
            self.policy_scrollbar_dragging = False
            return was_dragging

        track = self.policy_scroll_track_rect
        handle = self.policy_scroll_handle_rect
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and track:
            if (handle and handle.collidepoint(event.pos)) or track.collidepoint(event.pos):
                self.policy_scrollbar_dragging = True
                self._cancel_pressed_elements()
                self._snap_policy_scroll(event.pos[0])
                self.refresh_ui()
                return True
        elif event.type == pygame.MOUSEMOTION and self.policy_scrollbar_dragging:
            self._snap_policy_scroll(event.pos[0])
            self.refresh_ui()
            return True
        return False

    def _snap_policy_scroll(self, mouse_x):
        track = self.policy_scroll_track_rect
        if track:
            self.policy_scroll_x = ui_bars.calculate_scroll_snap_horizontal(
                mouse_x, self.policy_scroll_min_x, 0, track.x, track.width)

    def _draw_captions(self, surface):
        small = fonts.get("small")
        centre_x = self.politics_rect.centerx
        caption_y = self.politics_rect.y + POLITICS_CAPTION_OFFSET_Y

        if not self.is_read_only:
            for direction, _face, caption in DRIFT_OPTIONS:
                surf = small.render(caption, True, c.UI_TEXT_MUTED)
                surface.blit(surf, (centre_x + BUTTON_STEP_X * direction - surf.get_width() // 2,
                                    caption_y))

        if self.is_read_only:
            note = "Read-only: this country's political choices cannot be changed here."
        elif getattr(self.map_screen, "tactical_mode", False):
            note = "Political direction cannot be changed in Tactical Mode."
        elif self.drift:
            note = ("Moving %s one step per turn until you stop it or it reaches the end."
                    % ("left" if self.drift < 0 else "right"))
        else:
            note = "Holding position. Nothing changes until you pick a direction."
        surf = small.render(note, True, c.UI_TEXT_DIM)
        surface.blit(surf, (centre_x - surf.get_width() // 2,
                            self.politics_rect.bottom - POLITICS_NOTE_OFFSET_FROM_BOTTOM))
