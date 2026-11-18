"""View the political compass and set a country's turn-by-turn direction."""
import pygame
import data.constants as c
from data import queries
from ui.background_styles import POLITICS_PANEL_STYLES
from ui.widgets import ui_elements
from ui.widgets.ui_elements import Button, make_back_button
from ui.bars import ui_bars
from ui.rendering.font_manager import fonts
from ui.navigation.screen import Screen
from map_logic import politics

# The politics screen intentionally keeps both panels the same size.  Change
# these values to retune the whole screen layout without hunting through draw
# calls below.
PANEL_WIDTH = 800
SCREEN_PANEL_MARGIN_Y = 20
PANEL_GAP = 20

POLITICS_TITLE_OFFSET_Y = 18
COMPASS_OFFSET = (105, 83)
COMPASS_SIZE = 184
DETAILS_CENTER_X = 588
POSITION_OFFSET_Y = 69
POSITION_LINE_GAP = 20
DRIFT_ROW_TOP = 139
DRIFT_ROW_GAP = 63
DRIFT_BUTTON_SIZE = (110, 34)
DRIFT_BUTTON_GAP = 8
EFFECTS_OFFSET_Y = 283
DRIFT_ROWS = (
    ("Political Direction", ("Liberalise", "Hold", "Centralise")),
    ("Economic Direction", ("Toward Planned", "Hold", "Toward Market")),
)

POLICY_VIEWPORT_MARGIN_X = 20
POLICY_VIEWPORT_TOP_OFFSET_Y = 62
POLICY_VIEWPORT_BOTTOM_OFFSET_Y = 38
POLICY_CARD_WIDTH = 250
POLICY_CARD_GAP = 16
POLICY_SCROLL_WHEEL_STEP = 90
POLICY_SCROLLBAR_HEIGHT = 14
POLICY_CARD_PADDING = 12
POLICY_TITLE_FONT = "normal"
POLICY_BUTTON_WIDTH = POLICY_CARD_WIDTH - 2 * POLICY_CARD_PADDING
POLICY_BUTTON_HEIGHT = c.SIZES["small"][1]
POLICY_BUTTON_BOTTOM_GAP = 8


class Politics_Screen(Screen):
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
                                and self.player not in c.UNPLAYABLE_NATIONS + ["Editor"])
        self._title = (f"{queries.get_country_display_name(self.player, map_screen.nation_data)} Politics"
                       if self.is_read_only else "Politics")

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
        if (self.is_read_only or not self.is_valid_player or self.player != self.map_screen.player_country
                or self.map_screen.tactical_mode):
            return False
        return queries.realtime_turn_open(self.map_screen)

    def set_drift(self, direction, *, economic=False):
        if not self.can_edit:
            return
        nation_data = self.map_screen.nation_data
        position = politics.economic_value(nation_data, self.player) if economic else self.value
        if not politics.can_shift(position, direction):
            self.map_screen.show_feedback("Already as far as this country can go.")
            return
        setter = politics.set_economic_drift if economic else politics.set_drift
        setter(nation_data, self.player, direction)
        self.map_screen.invalidate_map_presentation_cache()
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

        nation_data = self.map_screen.nation_data
        position = (politics.economic_value(nation_data, self.player), self.value)
        direction = (politics.economic_drift(nation_data, self.player), self.drift)
        self._preview = (tuple(politics.advance(value, drift) for value, drift in zip(position, direction))
                         if not self.is_read_only else position)
        self._compass_details = self._build_compass_details(position)
        self._policy_rows = [(definition, politics.policy_state(nation_data, self.player, definition["id"]),
                              politics.requirements_met(nation_data, self.player, definition["id"]))
                             for definition in politics.POLICIES]

        if not self.is_read_only:
            center_x = self.politics_rect.x + DETAILS_CENTER_X
            stride = DRIFT_BUTTON_SIZE[0] + DRIFT_BUTTON_GAP
            for row, (_heading, labels) in enumerate(DRIFT_ROWS):
                axis = 1 - row  # Compass stores x, y. Controls show politics first.
                y = self.politics_rect.y + DRIFT_ROW_TOP + row * DRIFT_ROW_GAP + 19
                for drift, label in zip((-1, 0, 1), labels):
                    button = Button(center_x + stride * drift - DRIFT_BUTTON_SIZE[0] // 2, y,
                                    DRIFT_BUTTON_SIZE, "blue" if drift else "grey", label,
                                    lambda d=drift, economic=axis == 0: self.set_drift(d, economic=economic),
                                    font_preset="small")
                    button.is_selected = direction[axis] == drift
                    button.disabled = not self.can_edit or not politics.can_shift(position[axis], drift)
                    self.elements.append(button)

            for index, (definition, state, eligible) in enumerate(self._policy_rows):
                button = self._make_policy_button(index, definition, state, eligible)
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

    def _make_policy_button(self, index, definition, state, eligible):
        card = self._policy_card_rect(index)
        label, color, disabled = self._policy_button_appearance(state, eligible)
        button = Button(card.x + POLICY_CARD_PADDING,
                        card.bottom - POLICY_BUTTON_HEIGHT - POLICY_BUTTON_BOTTOM_GAP,
                        (POLICY_BUTTON_WIDTH, POLICY_BUTTON_HEIGHT), color, label,
                        lambda policy_id=definition["id"]: self.toggle_policy(policy_id))
        button.disabled = disabled
        return button

    def _policy_button_appearance(self, state, eligible):
        if state:
            if state["status"] == politics.POLICY_CANCELLING:
                return "Undo Cancel", "green", not self.can_edit
            return "Cancel", "red", not self.can_edit
        if not eligible:
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
        self.map_screen.invalidate_map_presentation_cache()
        self.refresh_ui()

    # ------------------------------------------------------------------ #
    #                              DRAWING                               #
    # ------------------------------------------------------------------ #

    def _build_compass_details(self, position):
        details = pygame.Surface(self.politics_rect.size, pygame.SRCALPHA)
        compass = pygame.Rect(*COMPASS_OFFSET, COMPASS_SIZE, COMPASS_SIZE)
        ui_elements.draw_political_compass(details, compass, position, self._preview)

        def draw_line(text, y, color=c.UI_TEXT_LIGHT):
            line = fonts.get("small").render(text, True, color)
            details.blit(line, line.get_rect(centerx=DETAILS_CENTER_X, y=y))

        economic, political = position
        draw_line(f"Politics  {politics.label(political)} ({political:+d})", POSITION_OFFSET_Y, c.COLOR_GOLD_HIGHLIGHT)
        draw_line(f"Economy  {politics.economic_label(economic)} ({economic:+d})",
                  POSITION_OFFSET_Y + POSITION_LINE_GAP, c.COLOR_GOLD_HIGHLIGHT)
        if self._preview != position:
            next_economic, next_political = self._preview
            draw_line(f"Next turn  ({next_economic:+d}, {next_political:+d})",
                      POSITION_OFFSET_Y + 2 * POSITION_LINE_GAP)

        if self.is_read_only:
            draw_line("Read-only", DRIFT_ROW_TOP, c.UI_TEXT_DIM)
        else:
            for row, (heading, _labels) in enumerate(DRIFT_ROWS):
                draw_line(heading, DRIFT_ROW_TOP + row * DRIFT_ROW_GAP)
            if self.map_screen.tactical_mode:
                draw_line("Political direction is locked in Tactical Mode.", EFFECTS_OFFSET_Y - 20, c.UI_TEXT_DIM)

        nation_data = self.map_screen.nation_data
        damage = politics.damage_multiplier(nation_data, self.player)
        research = politics.research_multiplier(nation_data, self.player)
        draw_line(f"Damage modifier  x{damage:.2f}      Research speed  x{research:.2f}",
                  DRIFT_ROW_TOP + DRIFT_ROW_GAP if self.is_read_only else EFFECTS_OFFSET_Y)
        return details

    def additional_draw(self, surface):
        self._draw_panel(surface, self.politics_rect)
        self._draw_panel(surface, self.policies_rect)

        title_surf = fonts.get("title").render(self._title, True, c.COLOR_GOLD_HIGHLIGHT)
        surface.blit(title_surf, (self.politics_rect.centerx - title_surf.get_width() // 2,
                                  self.politics_rect.y + POLITICS_TITLE_OFFSET_Y))

        policies_title = fonts.get("title").render("Policies", True, c.COLOR_GOLD_HIGHLIGHT)
        surface.blit(policies_title, (self.policies_rect.centerx - policies_title.get_width() // 2,
                                      self.policies_rect.y + POLITICS_TITLE_OFFSET_Y))

        if not self.is_valid_player:
            msg = fonts.get("normal").render("Politics is not available in Spectator Mode.",
                                             True, (255, 150, 150))
            surface.blit(msg, (self.politics_rect.centerx - msg.get_width() // 2,
                               self.politics_rect.centery))
            return

        surface.blit(self._compass_details, self.politics_rect)
        self._draw_policies(surface)

    @staticmethod
    def _draw_panel(surface, rect):
        style = POLITICS_PANEL_STYLES["main"]
        ui_elements.draw_pixel_panel(surface, rect, style["color"], c.COLOR_DIM_BORDER,
                                     border_width=3, gradient_strength=style["gradient_strength"])

    def _draw_policies(self, surface):
        viewport = self._policy_viewport_rect()
        with ui_bars.clip_scroll_region(surface, viewport):
            for index, (definition, state, eligible) in enumerate(self._policy_rows):
                self._draw_policy_card(surface, self._policy_card_rect(index), definition, state, eligible)

        track, handle = ui_bars.draw_standard_scrollbar_horizontal(
            # The policy cards themselves retain conventional direct-drag
            # behavior, but the scrollbar is intentionally reversed: moving
            # its handle left shifts the cards right, as requested for this
            # horizontally arranged policy carousel.
            surface, self.policy_scroll_min_x - self.policy_scroll_x,
            self.policy_scroll_min_x, 0,
            viewport.x, self.policies_rect.bottom - POLICY_SCROLLBAR_HEIGHT - 10,
            viewport.width, POLICY_SCROLLBAR_HEIGHT)
        self.policy_scroll_track_rect = track
        self.policy_scroll_handle_rect = handle

    def _draw_policy_card(self, surface, card, definition, state, eligible):
        if state and state["status"] == politics.POLICY_ACTIVE:
            border = c.COLOR_GOLD_HIGHLIGHT
        elif state:
            border = (120, 170, 255)
        else:
            border = c.COLOR_DIM_BORDER
        style = POLITICS_PANEL_STYLES["policy_card"]
        ui_elements.draw_pixel_panel(surface, card, style["color"], border,
                                     gradient_strength=style["gradient_strength"])

        heading = fonts.get(POLICY_TITLE_FONT).render(definition["name"], True, c.UI_TEXT_LIGHT)
        surface.blit(heading, heading.get_rect(centerx=card.centerx,
                                                y=card.y + POLICY_CARD_PADDING))
        y = card.y + POLICY_CARD_PADDING + heading.get_height() + 8
        small = fonts.get("small")
        for line in definition["effect_lines"]:
            effect = small.render(line, True, c.UI_TEXT_MUTED)
            surface.blit(effect, (card.x + POLICY_CARD_PADDING, y))
            y += effect.get_height() + 3

        requirement = small.render(politics.requirement_text(definition["id"]), True,
                                   c.UI_TEXT_DIM if eligible else (255, 150, 150))
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
            handle_value = ui_bars.calculate_scroll_snap_horizontal(
                mouse_x, self.policy_scroll_min_x, 0, track.x, track.width)
            self.policy_scroll_x = self.policy_scroll_min_x - handle_value
