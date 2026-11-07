"""Tactical Orders: the command panel for a tactical player's one division.

A tactical player commands one division while its country stays AI-controlled.
This screen replaces Orders in tactical mode. It shows that division with its
own commands, and lists the other units on the opened tile as read-only rows.
It has no selection, batch, army, or clear-all controls.
"""

import pygame
import data.constants as c
from ui.navigation.screen import Screen
from ui.widgets.ui_elements import Button
from ui.rendering.font_manager import fonts
from data import queries
from ui.widgets.text_utils import fit_text
from ui.bars import ui_bars, resource_hud, view_mode_buttons
from ui.panels import sidebar_info
from ui.panels.unit_commands import (
    UnitCommandControls, PANEL_Y, PANEL_INSET, PANEL_BORDER_COLOR, SCROLLBAR_WIDTH,
    MAP_CLICK_DRAG_THRESHOLD,
)
from screens.game import map_input
from ui.background_styles import ORDERS_PANEL_STYLES
from ui.widgets import ui_elements


# ==========================================
# TACTICAL ORDERS PANEL LAYOUT
# ==========================================

TITLE_OFFSET_Y = 7
BATTLE_BUTTON_OFFSET_Y = 40
HELP_OFFSET_Y = 76
HELP_LINE_GAP = 2
UNIT_ROW_OFFSET_Y = 116
LIST_LABEL_OFFSET_Y = 164
LIST_TOP_OFFSET_Y = 184
LIST_VISIBLE_ROWS = 5
PANEL_BOTTOM_INSET = 8
DIVIDER_COLOR = (80, 85, 95)
ROW_HEIGHT = 40
PANEL_HEIGHT = LIST_TOP_OFFSET_Y + LIST_VISIBLE_ROWS * ROW_HEIGHT + PANEL_BOTTOM_INSET


class Tactical_Orders_Screen(UnitCommandControls, Screen):
    back_state = "MAP"
    PANEL_X = 10
    PANEL_WIDTH = 440

    def __init__(self):
        super().__init__()
        self._init_unit_commands()
        self.row_height = ROW_HEIGHT
        # (unit, province, index) for the tactical division, or None when it
        # is not on the map.
        self._player_record = None
        self._player_row_key = None
        self._other_rows = []
        # (position, button, clicked stack) for a pending map click.
        self._map_click = None
        self.panel_rect = pygame.Rect(self.PANEL_X, PANEL_Y, self.PANEL_WIDTH, PANEL_HEIGHT)
        self.scroll_content_rect = pygame.Rect(
            self.PANEL_X + 2, PANEL_Y + LIST_TOP_OFFSET_Y,
            self.PANEL_WIDTH - SCROLLBAR_WIDTH - 2, LIST_VISIBLE_ROWS * ROW_HEIGHT)

    def _player_unit_record(self):
        player_unit = self.map_screen.player_unit
        if player_unit is None:
            return None
        for province in self.map_screen.map_data.values():
            for index, unit in enumerate(province.get("units", [])):
                if unit is player_unit:
                    return unit, province, index
        return None

    def _select_player_unit(self, sound_kind="select_unit"):
        """Keep the division selected. Movement orders follow the map selection."""
        record = self._player_unit_record()
        if record is not None and not self.map_screen.is_unit_selected(record[0]):
            self.map_screen.select_map_units([record[0]], sound_kind=sound_kind)

    def start_with_province(self, province, map_ref):
        open_battle_on_entry = self._begin_command_session(province, map_ref)
        self._map_click = None
        # A combat bubble plays its own sound for this activation.
        self._select_player_unit(None if open_battle_on_entry else "select_unit")
        self.refresh_ui()
        if (open_battle_on_entry and queries.is_province_in_active_combat(
                self.target_province, self.map_screen.nation_data)):
            self.open_battle_panel()

    def inspect_province(self, province, preserve_scroll=False):
        """List the units of another tile without leaving the screen."""
        self.target_province = province
        self.map_screen.selected_province = province
        self.battle_screen = None
        if not preserve_scroll:
            self.scroll_y = 0
        self.cancel_bombard_targeting(refresh=False)
        self._select_player_unit(None)
        self.refresh_ui()

    def refresh_ui(self):
        map_ref = self.map_screen
        player_country = map_ref.player_country
        if self.target_province is not None:
            sidebar_info.prepare_unit_roster(map_ref, self.target_province)
        self._player_record = self._player_unit_record()
        self.read_only = self._player_record is None
        self._air_range_records = [(unit, base)
            for unit, base in map_ref.selected_unit_records() if queries.is_air_unit(unit, context=map_ref)]
        self._air_range_input_key = None
        self._refresh_air_range_previews(self._air_range_hover_target)

        self.view_mode_buttons = view_mode_buttons.build(
            lambda mode: map_input.navigate_view_mode(map_ref, mode, origin=self))
        view_mode_buttons.sync_highlight(self.view_mode_buttons, map_ref.secondary_mode)
        close_button = Button(self.panel_rect.right - 38, self.panel_rect.y + 7,
                              "tiny_square", "red", "X", self.exit_screen,
                              font_preset="tiny", sound_kind="back")
        self.elements = [*self.view_mode_buttons, close_button]
        self.action_buttons = []
        self.unit_row_icons = {}
        self._row_order_summaries = {}

        if self.target_province is not None and queries.is_province_in_active_combat(
                self.target_province, map_ref.nation_data):
            here = self._player_record is not None and self._player_record[1] is self.target_province
            battle_label = ("Close Battle" if self.battle_screen is not None else
                            ("Manage Battle" if here else "View Battle"))
            battle_callback = (self.close_battle_panel if self.battle_screen is not None
                               else self.go_to_battle)
            self.elements.append(Button(
                self.panel_rect.right - PANEL_INSET - c.SIZES["orders_header_button"][0],
                PANEL_Y + BATTLE_BUTTON_OFFSET_Y,
                "orders_header_button", "red", battle_label,
                battle_callback, font_preset="tiny"))

        self._player_row_key = None
        if self._player_record is not None:
            unit, province, index = self._player_record
            row_key = (province["id"], index)
            self._player_row_key = row_key
            self._cache_row_icon(row_key, unit)
            self._row_order_summaries[row_key] = self._order_summary(row_key, unit)
            research = map_ref.nation_data.get(player_country, {}).get("research", {})
            # A fixed row passes no scroll guard.
            self._build_unit_action_buttons(
                row_key, index, unit, province, PANEL_Y + UNIT_ROW_OFFSET_Y, None,
                queries.is_nation_in_combat_here(player_country, province, map_ref.nation_data),
                queries.is_water_province(province), province.get("is_coastal", False),
                queries.has_industry(province), research)

        target = self.target_province
        player_unit = self._player_record[0] if self._player_record else None
        self._other_rows = [] if target is None else [
            ((target["id"], index), unit, target, index)
            for index, unit in enumerate(target.get("units", []))
            if unit is not player_unit]
        for row_key, unit, _province, _index in self._other_rows:
            self._cache_row_icon(row_key, unit)
            if unit.get("owner") == player_country:
                self._row_order_summaries[row_key] = self._order_summary(row_key, unit)

        list_height = self.scroll_content_rect.height
        self.max_scroll_y = min(0, list_height - len(self._other_rows) * self.row_height)
        self.scroll_y = max(self.max_scroll_y, min(0, self.scroll_y))
        self._presentation_state = self._current_presentation_state()

    def _cancel_box_region(self):
        # Only the division's own fixed row has a cancel box.
        return self.panel_rect

    def _handle_map_selection_event(self, event, on_ui):
        # A short click on a unit stack lists that tile's units here. A short
        # click on empty map returns to that province's menu. There is no box
        # selection: the division is the only unit a tactical player commands.
        if (event.type == pygame.MOUSEBUTTONDOWN and not on_ui
                and map_input.mouse_button_has_action(event.button, "select_units")):
            stack = next((stack for stack in reversed(self.map_screen.unit_stack_hitboxes)
                          if stack["rect"].collidepoint(event.pos)), None)
            self._map_click = (event.pos, event.button, stack)
            return True

        if (event.type == pygame.MOUSEBUTTONUP and self._map_click is not None
                and event.button == self._map_click[1]):
            start, _button, stack = self._map_click
            self._map_click = None
            if (abs(event.pos[0] - start[0]) >= MAP_CLICK_DRAG_THRESHOLD
                    or abs(event.pos[1] - start[1]) >= MAP_CLICK_DRAG_THRESHOLD):
                return True
            if stack is None:
                self._return_to_clicked_province(event.pos)
            else:
                self.inspect_province(stack["province"])
            return True
        return False

    def _draw_header(self, surface):
        title_font = fonts.get("heading2")
        tiny_font = fonts.get("tiny")
        title = fit_text("TACTICAL ORDERS", title_font, self.PANEL_WIDTH - 62)
        surface.blit(title_font.render(title, True, (255, 255, 255)),
                     (self.PANEL_X + PANEL_INSET, PANEL_Y + TITLE_OFFSET_Y))

        help_text = self._hovered_action_help(pygame.mouse.get_pos())
        if help_text is None:
            help_text = self._active_command_help()
        if help_text is None and self._player_record is not None:
            help_text = "Right-click the map to move | hover a command icon for details"
        if help_text:
            help_y = PANEL_Y + HELP_OFFSET_Y
            for line in self._header_help_lines(help_text, tiny_font):
                surface.blit(tiny_font.render(line, True, c.UI_TEXT_MUTED),
                             (self.PANEL_X + PANEL_INSET, help_y))
                help_y += tiny_font.get_height() + HELP_LINE_GAP

        pygame.draw.line(surface, DIVIDER_COLOR,
                         (self.PANEL_X + 1, PANEL_Y + UNIT_ROW_OFFSET_Y - 4),
                         (self.panel_rect.right - 1, PANEL_Y + UNIT_ROW_OFFSET_Y - 4), 1)

    def additional_draw(self, surface):
        if not self.map_screen or not self.target_province:
            return
        map_ref = self.map_screen
        map_ref.draw_clean_map_background(surface)

        # Range outlines sit on the map below the command-panel controls.
        self.draw_range_previews(surface)

        self.cancel_rects = []
        small_font = fonts.get("small")
        tiny_font = fonts.get("tiny")
        owner_color = map_ref.nation_colors.get(map_ref.player_country, (255, 255, 0))

        if self._player_record is not None:
            unit, province, _index = self._player_record
            self._draw_selected_order_paths(surface, [(unit, province)], owner_color)

        style = ORDERS_PANEL_STYLES["main"]
        ui_elements.draw_pixel_panel(
            surface, self.panel_rect, style["color"], PANEL_BORDER_COLOR,
            gradient_strength=style["gradient_strength"])
        self._draw_header(surface)

        unit_row_y = PANEL_Y + UNIT_ROW_OFFSET_Y
        if self._player_record is not None:
            unit, province, index = self._player_record
            self._draw_unit_row(
                surface, self._player_row_key, unit, province, index, unit_row_y, 0,
                owner_color, small_font, tiny_font, map_ref.is_unit_selected(unit))
        else:
            surface.blit(tiny_font.render("(No unit to command)", True, c.UI_TEXT_MUTED),
                         (self.PANEL_X + PANEL_INSET, unit_row_y))

        label = f"OTHER UNITS | P{self.target_province['id']}"
        surface.blit(tiny_font.render(label, True, c.UI_TEXT_LIGHT),
                     (self.PANEL_X + PANEL_INSET, PANEL_Y + LIST_LABEL_OFFSET_Y))
        list_rect = self.scroll_content_rect
        pygame.draw.line(surface, DIVIDER_COLOR,
                         (self.PANEL_X + 1, list_rect.y - 1),
                         (self.panel_rect.right - 1, list_rect.y - 1), 1)

        # Other units are read-only: rows draw without commands or cancel boxes.
        with ui_bars.clip_scroll_region(surface, list_rect,
                                        draw_top=self.scroll_y != 0,
                                        draw_bottom=self.scroll_y > self.max_scroll_y):
            if not self._other_rows:
                surface.blit(tiny_font.render("(No other units)", True, c.UI_TEXT_MUTED),
                             (self.PANEL_X + PANEL_INSET, list_rect.y))
            for display_index, (row_key, unit, province, index) in enumerate(self._other_rows):
                row_y = list_rect.y + display_index * self.row_height + self.scroll_y
                if row_y + self.row_height < list_rect.y or row_y > list_rect.bottom:
                    continue
                self._draw_unit_row(
                    surface, row_key, unit, province, index, row_y, display_index,
                    owner_color, small_font, tiny_font, False)

        self.draw_list_scrollbar(
            surface, self.panel_rect.right - SCROLLBAR_WIDTH, list_rect.y,
            list_rect.height, width=SCROLLBAR_WIDTH, limit_attr="max_scroll_y")

        resource_hud.draw_resource_bar(surface, map_ref,
                                       start_x=view_mode_buttons.RESOURCE_BAR_OFFSET_X)

        if self.battle_screen is not None:
            self.battle_screen.draw_embedded(surface)
