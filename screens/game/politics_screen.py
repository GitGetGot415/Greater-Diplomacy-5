"""View the four politics axes and set a country's turn-by-turn directions."""
from dataclasses import dataclass

import pygame
import data.constants as c
from data import queries
from ui.background_styles import POLITICS_PANEL_STYLES
from ui.widgets import ui_elements
from ui.widgets.text_utils import wrap_text
from ui.widgets.ui_elements import Button, make_back_button
from ui.bars import ui_bars
from ui.rendering import symbol_loader
from ui.rendering.font_manager import fonts
from ui.navigation.screen import Screen
from map_logic import politics

# The politics screen intentionally keeps both panels the same size.  Change
# these values to retune the whole screen layout without hunting through draw
# calls below.
PANEL_WIDTH = 1000
SCREEN_PANEL_MARGIN_Y = 20
PANEL_GAP = 20

POLITICS_TITLE_OFFSET_Y = 18
TAB_SIZE = (110, 26)
TAB_GAP = 8
TAB_OFFSET_Y = 62
COMPASS_OFFSET = (105, 83)
COMPASS_SIZE = 184
DETAILS_CENTER_X = 682
# Each tab shows two axis blocks: a heading, the direction buttons, then effects.
AXIS_BLOCK_TOP = 98
AXIS_BLOCK_GAP = 112
DRIFT_BUTTON_OFFSET_Y = 20
DRIFT_BUTTON_SIZE = (110, 34)
DRIFT_BUTTON_GAP = 8
EFFECTS_OFFSET_Y = 58
EFFECT_LINE_GAP = 16
EFFECT_COLUMN_LEFTS = (394, 700)
EFFECT_ROWS_PER_COLUMN = 3
POSITION_LINE_GAP = 20
COMPASS_CENTER_X = COMPASS_OFFSET[0] + COMPASS_SIZE // 2
TACTICAL_NOTICE_Y = COMPASS_OFFSET[1] + COMPASS_SIZE + POSITION_LINE_GAP
DECREASE_COLOR = (255, 150, 150)
#: Appended to a tab whose axes are moving.
DRIFT_MARKER = " •"

#: The tabs, and the axes each shows, top block first. The compass plots the
#: second axis across and the first up.
GROUP_TABS = ((politics.CIVILIAN, "Civilian"), (politics.MILITARY, "Military"))
GROUP_AXES = {politics.CIVILIAN: (politics.POLITICAL, politics.ECONOMIC),
              politics.MILITARY: (politics.QUALITY, politics.STRATEGY)}

#: How each effect reads: its label, the unit of an added value (None for a
#: multiplier), and whether a higher value helps the country.
EFFECT_DISPLAY = {
    "coring_turns": ("Coring time", "turns", False),
    "coring_cost": ("Coring cost", None, False),
    "remove_core_cost": ("Core removal cost", None, False),
    "research": ("Research", None, True),
    "reputation": ("Reputation", "", True),
    "factory_output": ("Factory output", None, True),
    "deposit_output": ("Deposits", None, True),
    "building_cost": ("Building cost", None, False),
    "non_core_province_output": ("Non-core land", None, True),
    "non_core_building_output": ("Non-core buildings", None, True),
    "damage": ("Damage", None, True),
    "tile_manpower": ("Province manpower", None, True),
    "unit_upkeep": ("Unit upkeep", None, False),
    "max_health": ("Max health", None, True),
    "research_year_months": ("Research timing", "months", True),
    "aircraft_range": ("Aircraft range", None, True),
    "core_territory_damage": ("Core damage", None, True),
    "non_core_territory_damage": ("Non-core damage", None, True),
    "defense": ("Defense", None, True),
    "fort_cost": ("Fort cost", None, False),
}


def effect_text(effect, value):
    """A multiplier as x1.20; an added value as a signed whole number and its unit."""
    unit = EFFECT_DISPLAY[effect][1]
    if unit is None:
        return f"×{value:.2f}"
    text = f"{round(value):+d}"
    return f"{text} {unit}" if unit else text


POLICY_VIEWPORT_MARGIN_X = 20
POLICY_VIEWPORT_TOP_OFFSET_Y = 62
POLICY_CARD_WIDTH = 184
POLICY_CARD_HEIGHT = 196
POLICY_CARD_GAP = 8
POLICY_SCROLL_WHEEL_STEP = 90
POLICY_SCROLLBAR_HEIGHT = 14
POLICY_SCROLLBAR_GAP = 6
POLICY_CARD_PADDING = 10
POLICY_TITLE_CENTER_Y = 19
POLICY_EFFECT_FIRST_Y = 43
POLICY_EFFECT_ROW_GAP = 21
POLICY_EFFECT_ICON_SIZE = (16, 16)
POLICY_EFFECT_LABEL_GAP = 6
POLICY_STATUS_CENTER_Y = 151
POLICY_BUTTON_WIDTH = POLICY_CARD_WIDTH - 2 * POLICY_CARD_PADDING
POLICY_BUTTON_HEIGHT = 24
POLICY_BUTTON_BOTTOM_GAP = 5
POLICY_EFFECT_DISPLAY = {
    "research": ("Research", "Research"),
    "manpower": ("Manpower prod", "Infantry"),
    "materials": ("Materials prod", "Iron"),
    "fuel": ("Fuel prod", "Oil"),
    "damage": ("Unit dmg", "Attack"),
    "aircraft_range": ("Air range", "Biplane Fighter"),
    "fort_cost": ("Fort cost", "Fort Lvl 1"),
    "defense": ("Unit & fort def", c.ICON_DEFENSE),
    "max_health": ("Unit max HP", c.ICON_HEALTH),
    "land_max_health": ("Land max HP", c.ICON_HEALTH),
    "land_speed": ("Land spd", ui_elements.ICON_SPEED),
}


@dataclass
class _PolicyCard:
    rect: pygame.Rect
    face: pygame.Surface


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
        self.player = country_id or map_screen.session.player_country
        self.is_read_only = country_id is not None and country_id != map_screen.session.player_country
        self.group = politics.CIVILIAN
        self._set_panel_rects()

        self.is_valid_player = (self.player in self.map_screen.world.nation_data
                                and self.player not in c.UNPLAYABLE_NATIONS + ["Editor"])
        self._title = (f"{queries.get_country_display_name(self.player, map_screen.world.nation_data)} Politics"
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
        return politics.value(self.map_screen.world.nation_data, self.player)

    @property
    def drift(self):
        return politics.drift(self.map_screen.world.nation_data, self.player)

    @property
    def can_edit(self):
        """Whether this screen may change the player's political direction."""
        if (self.is_read_only or not self.is_valid_player or self.player != self.map_screen.session.player_country
                or self.map_screen.session.tactical_mode):
            return False
        return queries.realtime_turn_open(self.map_screen)

    @property
    def policy_scroll(self):
        """The horizontal pane of policy cards."""
        return self.scroll_state("policies", "x")

    def select_group(self, group):
        """Show the selected axes and their policy cards."""
        if group != self.group:
            self.cancel_active_drags()
            self.policy_scroll.value = 0
            self.policy_scroll.track = self.policy_scroll.handle = None
        self.group = group
        self.refresh_ui()

    def set_drift(self, direction, axis=politics.POLITICAL):
        if not self.can_edit:
            return
        nation_data = self.map_screen.world.nation_data
        if not politics.can_shift(politics.axis_value(nation_data, self.player, axis), direction):
            self.map_screen.show_feedback("Already as far as this country can go.")
            return
        politics.set_axis_drift(nation_data, self.player, axis, direction)
        self.map_screen.invalidate_map_presentation_cache()
        self.refresh_ui()

    # ------------------------------------------------------------------ #
    #                               LAYOUT                               #
    # ------------------------------------------------------------------ #

    def refresh_ui(self):
        self.elements = [make_back_button(self.exit_screen, style="map")]
        self._policy_cards = []
        policies = politics.policies_for_group(self.group)
        self.policy_scroll.content_rect = self._policy_viewport_rect()
        self._update_policy_scroll_bounds(len(policies))

        if not self.is_valid_player:
            return

        # Requirements may change outside this screen (for example, in the map
        # editor), so an editable country's panel reconciles them before it is
        # drawn.  Inspection of a foreign country is strictly read-only.
        if self.can_edit:
            politics.reconcile_policy(self.map_screen.world.nation_data, self.player)

        nation_data = self.map_screen.world.nation_data
        self._positions = {axis["id"]: politics.axis_value(nation_data, self.player, axis["id"])
                           for axis in politics.AXES}
        # Directions are private, so a foreign country shows only where it is.
        self._drifts = {axis["id"]: 0 if self.is_read_only else politics.axis_drift(nation_data, self.player, axis["id"])
                        for axis in politics.AXES}
        self._previews = {axis: politics.advance(position, self._drifts[axis])
                          for axis, position in self._positions.items()}
        self._compass_details = self._build_compass_details()
        tabs_width = len(GROUP_TABS) * TAB_SIZE[0] + (len(GROUP_TABS) - 1) * TAB_GAP
        tab_x = self.politics_rect.centerx - tabs_width // 2
        for index, (group, label) in enumerate(GROUP_TABS):
            moving = any(self._drifts[axis] for axis in GROUP_AXES[group])
            tab = Button(tab_x + index * (TAB_SIZE[0] + TAB_GAP), self.politics_rect.y + TAB_OFFSET_Y, TAB_SIZE,
                         "green" if group == self.group else "light_blue", label + (DRIFT_MARKER if moving else ""),
                         lambda g=group: self.select_group(g), font_preset="small", sound_kind="select_category")
            tab.is_selected = group == self.group
            tab.politics_group = group
            self.elements.append(tab)

        if not self.is_read_only:
            center_x = self.politics_rect.x + DETAILS_CENTER_X
            stride = DRIFT_BUTTON_SIZE[0] + DRIFT_BUTTON_GAP
            for row, axis_id in enumerate(GROUP_AXES[self.group]):
                ends = politics.AXES_BY_ID[axis_id]["ends"]
                y = self.politics_rect.y + AXIS_BLOCK_TOP + row * AXIS_BLOCK_GAP + DRIFT_BUTTON_OFFSET_Y
                for drift, label in zip((-1, 0, 1), (ends[0], "Hold", ends[1])):
                    button = Button(center_x + stride * drift - DRIFT_BUTTON_SIZE[0] // 2, y,
                                    DRIFT_BUTTON_SIZE, "blue" if drift else "grey", label,
                                    lambda d=drift, axis=axis_id: self.set_drift(d, axis),
                                    font_preset="small")
                    button.politics_axis, button.politics_direction = axis_id, drift
                    button.is_selected = self._drifts[axis_id] == drift
                    button.disabled = not self.can_edit or not politics.can_shift(self._positions[axis_id], drift)
                    self.elements.append(button)

        scroll_guard = self.content_hover_guard(self.policy_scroll) if self.policy_scroll.limit < 0 else None
        for index, definition in enumerate(policies):
            policy_id = definition["id"]
            state = politics.policy_state(nation_data, self.player, policy_id)
            eligible = politics.requirements_met(nation_data, self.player, policy_id)
            card = self._policy_card_rect(index)
            self._policy_cards.append(self._build_policy_card(card, definition, state, eligible))
            if not self.is_read_only:
                button = self._make_policy_button(card, policy_id, state, eligible)
                button.is_scrollable = True
                button.click_guard = scroll_guard
                self.elements.append(button)

    def _policy_viewport_rect(self):
        return pygame.Rect(
            self.policies_rect.x + POLICY_VIEWPORT_MARGIN_X,
            self.policies_rect.y + POLICY_VIEWPORT_TOP_OFFSET_Y,
            self.policies_rect.width - 2 * POLICY_VIEWPORT_MARGIN_X,
            POLICY_CARD_HEIGHT,
        )

    def _update_policy_scroll_bounds(self, count):
        content_width = count * POLICY_CARD_WIDTH + max(0, count - 1) * POLICY_CARD_GAP
        self.policy_scroll.limit = min(0, self.policy_scroll.content_rect.width - content_width)
        self.policy_scroll.value = max(self.policy_scroll.limit, min(0, self.policy_scroll.value))

    def _policy_card_rect(self, index):
        viewport = self.policy_scroll.content_rect
        return pygame.Rect(viewport.x + self.policy_scroll.value + index * (POLICY_CARD_WIDTH + POLICY_CARD_GAP),
                           viewport.y,
                           POLICY_CARD_WIDTH, POLICY_CARD_HEIGHT)

    def _make_policy_button(self, card, policy_id, state, eligible):
        label, color, disabled = self._policy_button_appearance(state, eligible)
        button = Button(card.x + POLICY_CARD_PADDING,
                        card.bottom - POLICY_BUTTON_HEIGHT - POLICY_BUTTON_BOTTOM_GAP,
                        (POLICY_BUTTON_WIDTH, POLICY_BUTTON_HEIGHT), color, label,
                        lambda: self.toggle_policy(policy_id), font_preset="small")
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
        before = politics.policy_state(self.map_screen.world.nation_data, self.player, policy_id)
        definition = politics.policy(policy_id)
        if not definition or not self.can_edit:
            return
        stat_policies = politics.unit_stat_policies(self.map_screen.world.nation_data, self.player)
        if not politics.activate_or_cancel_policy(self.map_screen.world.nation_data, self.player, policy_id):
            self.map_screen.show_feedback(politics.requirement_text(policy_id))
            return

        queries.refresh_policy_unit_stats(self.map_screen, self.player, stat_policies)
        after = politics.policy_state(self.map_screen.world.nation_data, self.player, policy_id)
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

    def _build_compass_details(self):
        details = pygame.Surface(self.politics_rect.size, pygame.SRCALPHA)
        y_axis, x_axis = GROUP_AXES[self.group]
        compass = pygame.Rect(*COMPASS_OFFSET, COMPASS_SIZE, COMPASS_SIZE)
        ui_elements.draw_political_compass(
            details, compass, (self._positions[x_axis], self._positions[y_axis]),
            (self._previews[x_axis], self._previews[y_axis]),
            labels=(politics.AXES_BY_ID[x_axis]["ends"], politics.AXES_BY_ID[y_axis]["ends"]))

        def draw_line(text, y, color=c.UI_TEXT_LIGHT, *, center_x=DETAILS_CENTER_X, font="small"):
            line = fonts.get(font).render(text, True, color)
            details.blit(line, line.get_rect(centerx=center_x, y=y))

        for row, axis_id in enumerate(GROUP_AXES[self.group]):
            top = AXIS_BLOCK_TOP + row * AXIS_BLOCK_GAP
            current, projected = self._positions[axis_id], self._previews[axis_id]
            heading = f"{politics.AXES_BY_ID[axis_id]['name']}  {politics.axis_label(axis_id, current)} ({current:+d})"
            if projected != current:
                heading += f"  →  {projected:+d}"
            draw_line(heading, top, c.COLOR_GOLD_HIGHLIGHT)
            self._draw_axis_effects(details, axis_id, top + EFFECTS_OFFSET_Y)

        if self.is_read_only:
            draw_line("Read-only", TACTICAL_NOTICE_Y, c.UI_TEXT_DIM, center_x=COMPASS_CENTER_X)
            return details
        if self.map_screen.session.tactical_mode:
            draw_line("Directions are locked in Tactical Mode.", TACTICAL_NOTICE_Y, c.UI_TEXT_DIM,
                      center_x=COMPASS_CENTER_X)
        nation_data = self.map_screen.world.nation_data
        damage = politics.damage_multiplier(nation_data, self.player)
        research = politics.research_multiplier(nation_data, self.player)
        if (damage != politics.axis_effect(nation_data, self.player, "damage")
                or research != politics.axis_effect(nation_data, self.player, "research")):
            draw_line(f"Current with policies  Damage ×{damage:.2f}  Base research ×{research:.2f}",
                      TACTICAL_NOTICE_Y + POSITION_LINE_GAP, c.UI_TEXT_DIM, center_x=COMPASS_CENTER_X, font="tiny")
        return details

    def _draw_axis_effects(self, surface, axis_id, top):
        """Each effect at the current position, and where next turn's step takes it."""
        font = fonts.get("tiny")
        for index, effect in enumerate(c.POLITICS_AXIS_EFFECTS[axis_id]):
            column, row = divmod(index, EFFECT_ROWS_PER_COLUMN)
            center_y = top + row * EFFECT_LINE_GAP + EFFECT_LINE_GAP // 2
            label, _unit, higher_is_better = EFFECT_DISPLAY[effect]
            current = politics.effect_at(effect, self._positions[axis_id])
            projected = politics.effect_at(effect, self._previews[axis_id])
            current_text = font.render(f"{label} {effect_text(effect, current)}", True, c.UI_TEXT_LIGHT)
            x = EFFECT_COLUMN_LEFTS[column]
            surface.blit(current_text, current_text.get_rect(midleft=(x, center_y)))
            if projected != current:
                arrow = " ↑" if projected > current else " ↓"
                color = c.COLOR_SUCCESS_GREEN if (projected > current) == higher_is_better else DECREASE_COLOR
                next_text = font.render(f" → {effect_text(effect, projected)}{arrow}", True, color)
                surface.blit(next_text, next_text.get_rect(midleft=(x + current_text.get_width(), center_y)))

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
        viewport = self.policy_scroll.content_rect
        with ui_bars.clip_scroll_region(surface, viewport):
            for card in self._policy_cards:
                surface.blit(card.face, card.rect)

        # Moving the handle left shifts the cards right.
        self.policy_scroll.draw_scrollbar(surface, viewport.x, viewport.bottom + POLICY_SCROLLBAR_GAP,
                                          viewport.width, POLICY_SCROLLBAR_HEIGHT)

    @staticmethod
    def _build_policy_card(card, definition, state, eligible):
        if state and state["status"] == politics.POLICY_ACTIVE:
            border = c.COLOR_GOLD_HIGHLIGHT
        elif state:
            border = (120, 170, 255)
        else:
            border = c.COLOR_DIM_BORDER
        style = POLITICS_PANEL_STYLES["policy_card"]
        face = pygame.Surface(card.size, pygame.SRCALPHA)
        ui_elements.draw_pixel_panel(face, face.get_rect(), style["color"], border,
                                     gradient_strength=style["gradient_strength"])

        title_font = fonts.get("small")
        title_lines = wrap_text(definition["name"], title_font, POLICY_BUTTON_WIDTH)
        title_y = POLICY_TITLE_CENTER_Y - len(title_lines) * title_font.get_height() // 2
        for line in title_lines:
            heading = title_font.render(line, True, c.UI_TEXT_LIGHT)
            face.blit(heading, heading.get_rect(midtop=(card.width // 2, title_y)))
            title_y += title_font.get_height()

        font = fonts.get("small")
        label_x = POLICY_CARD_PADDING + POLICY_EFFECT_ICON_SIZE[0] + POLICY_EFFECT_LABEL_GAP
        value_x = card.width - POLICY_CARD_PADDING
        for row, (effect, amount) in enumerate(definition["effects"].items()):
            label, symbol = POLICY_EFFECT_DISPLAY[effect]
            y = POLICY_EFFECT_FIRST_Y + row * POLICY_EFFECT_ROW_GAP
            icon = symbol_loader.get_symbol(symbol, 1, style="classic", fit_size=POLICY_EFFECT_ICON_SIZE)
            if icon is not None:
                icon_center_x = POLICY_CARD_PADDING + POLICY_EFFECT_ICON_SIZE[0] // 2
                face.blit(icon, icon.get_rect(center=(icon_center_x, y)))
            label_surf = font.render(label, True, c.UI_TEXT_LIGHT)
            face.blit(label_surf, label_surf.get_rect(midleft=(label_x, y)))
            additive = effect == "land_speed"
            change = amount if additive else amount - 1.0
            is_benefit = change < 0 if effect == "fort_cost" else change > 0
            color = c.COLOR_SUCCESS_GREEN if is_benefit else DECREASE_COLOR
            value = font.render(f"{change:+d}" if additive else f"{change:+.0%}", True, color)
            face.blit(value, value.get_rect(midright=(value_x, y)))

        if state:
            status = Politics_Screen._policy_status_text(state)
            status_color = c.COLOR_GOLD_HIGHLIGHT
        else:
            status = politics.requirement_text(definition["id"], compact=True)
            status_color = c.UI_TEXT_DIM if eligible else DECREASE_COLOR
        status_surf = fonts.get("tiny").render(status, True, status_color)
        face.blit(status_surf, status_surf.get_rect(center=(card.width // 2, POLICY_STATUS_CENTER_Y)))

        return _PolicyCard(card, face)

    @staticmethod
    def _policy_status_text(state):
        if state["status"] == politics.POLICY_ACTIVE:
            return "Active"
        if state["status"] == politics.POLICY_CANCELLING:
            return f"Cancelling · {state.get('turns_remaining', 1)}t"
        return f"Activating · {state.get('turns_remaining', 0)}t"

    def additional_events(self, event):
        scroll = self.policy_scroll
        if scroll.limit >= 0:
            return
        if event.type == pygame.MOUSEWHEEL:
            if scroll.content_rect.collidepoint(pygame.mouse.get_pos()):
                self.scroll_by(event, scroll, POLICY_SCROLL_WHEEL_STEP)
            return
        self.handle_list_scroll(event, scroll, content=True)
