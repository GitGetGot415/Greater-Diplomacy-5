import pygame
from math import sqrt
import data.constants as c
from ui.navigation.game_state import GameState, resolve_keybind
from ui.widgets.ui_elements import Button, process_text_input, draw_text_box
from ui.rendering.font_manager import fonts
from data import queries
from map_logic.actions import unit_actions
from ui.widgets.text_utils import fit_text, wrap_text
from ui.rendering import symbol_loader
from ui.rendering import overlay_renderer
from ui.bars import ui_bars, resource_hud, view_mode_buttons
from ui.panels import army_panel, map_top_right_layout
from screens.game import map_input
from screens.game import battle_screen
from ui.navigation.modal_screen import ModalScreen

from ui.dialogs.list_select_screen import ListSelectScreen
from ui.panels import sidebar_info
from ui.rendering import map_utils
from ui.navigation import screen_runner


# ==========================================
# COMPACT ORDERS PANEL LAYOUT
# ==========================================

# The reference layout gets its density from a compact command header and one
# narrow roster row per unit. The second header row holds the unambiguous batch
# commands which operate on the current map selection.
PANEL_Y = 5
PANEL_HEIGHT = c.SCREEN_HEIGHT - 70
PANEL_BOTTOM_INSET = 8
PANEL_INSET = 8
HEADER_TITLE_OFFSET_Y = 7
HEADER_META_OFFSET_Y = 36
TOP_BTN_ROW_OFFSET_Y = 57
HEADER_HELP_OFFSET_Y = 151
HEADER_HELP_LINE_GAP = 2
HEADER_HELP_MAX_LINES = 2
LIST_TOP_OFFSET_Y = 185

TOP_BTN_GAP_X = 6
BATCH_LABEL_INSET = 4
BATCH_BTN_ROW_OFFSET_Y = TOP_BTN_ROW_OFFSET_Y + 31
BATTLE_UNGROUP_ROW_OFFSET_Y = BATCH_BTN_ROW_OFFSET_Y + 31

BATTLE_PANEL_GAP = 8

UNIT_ROW_X_OFFSET = 4
UNIT_ICON_OFFSET_X = 7
UNIT_ICON_OFFSET_Y = 4
UNIT_NAME_OFFSET_X = 46
UNIT_NAME_OFFSET_Y = 1
UNIT_STATUS_OFFSET_Y = 20
UNIT_HEALTH_BAR_OFFSET_Y = 35
UNIT_HEALTH_BAR_HEIGHT = 3

# Six tightly packed icon commands: convert, disband, repair, rename, upgrade,
# bombard (air mission for aircraft). Live status appears in the hovered header.
ACTION_START_OFFSET_X = 242
ACTION_BUTTON_STEP_X = 28
ACTION_BUTTON_OFFSET_Y = 6
ACTION_COL_CONVERT = 0
ACTION_COL_DISBAND = 1
ACTION_COL_REPAIR = 2
ACTION_COL_RENAME = 3
ACTION_COL_UPGRADE = 4
ACTION_COL_BOMBARD = 5
ACTION_ICON_INSET = 2

RENAME_BOX_OFFSET_X = UNIT_NAME_OFFSET_X
RENAME_BOX_OFFSET_Y = 7
RENAME_BOX_SIZE = (ACTION_START_OFFSET_X - UNIT_NAME_OFFSET_X - 8, 26)

# The final slim column cancels whatever order the row currently carries,
# including movement (which has no dedicated command glyph of its own).
CANCEL_BOX_GAP_X = 2
CANCEL_BOX_OFFSET_Y = 11
CANCEL_BOX_SIZE = 16

# Both map panels share the HUD palette; the values used to be typed out
# separately here and in the other panel's module.
PANEL_BG_COLOR = c.HUD_PANEL_BG
PANEL_BORDER_COLOR = c.HUD_PANEL_BORDER
SCROLLBAR_WIDTH = 8

TARGET_MARKER_RADIUS = 12
TARGET_MARKER_THICKNESS = 3
AIR_RANGE_THICKNESS = 2
MOVE_TARGET_COLOR = (0, 255, 0)
BOMBARD_TARGET_COLOR = (255, 200, 50)
BOMBARD_PREVIEW_ALPHA = 160

WHEEL_SCROLL_STEP = 30
UNIT_ICON_ZOOM = 1.5


AIR_MISSION_CHOICES = c.AIR_MISSION_CHOICES
AIR_MISSION_ICONS = {mission: c.AIR_MISSION_ICONS[mission]
                     for mission, _label, _icon in AIR_MISSION_CHOICES}


class _AirMissionSelectScreen(ModalScreen):
    """One click selects an air mission; Back dismisses without changing it."""
    PANEL_SIZE = (620, 522)
    OPTION_TOP = 65
    OPTION_GAP = 48
    OPTION_INSET = 20
    CANCEL_BOTTOM = 46

    def __init__(self, orders, choices, on_select, *, enabled_missions=None):
        super().__init__(orders.map_screen, "Select air mission")
        self.choices = choices
        self.enabled_missions = ({mission for mission, _label, _icon in choices}
                                 if enabled_missions is None else set(enabled_missions))
        self.elements = []
        for row, (mission, label, icon) in enumerate(choices):
            button = self.button(self.panel_rect.x + self.OPTION_INSET,
                self.panel_rect.y + self.OPTION_TOP + row * self.OPTION_GAP,
                self.panel_rect.width - 2 * self.OPTION_INSET, "blue", label,
                lambda selected=mission: self.select(selected, on_select))
            button.right_image = orders._get_action_icon(icon, button.rect.size)
            button.apply_state(enabled=mission in self.enabled_missions, color="blue")
            self.elements.append(button)
        self.elements.append(self.button(self.panel_rect.x + self.OPTION_INSET,
            self.panel_rect.bottom - self.CANCEL_BOTTOM,
            self.panel_rect.width - 2 * self.OPTION_INSET, "red", "Cancel", self.exit_screen))

    def select(self, mission, on_select):
        if mission not in self.enabled_missions:
            return
        self.exit_screen()
        on_select(mission)


class _OrdersRowHitbox(Button):
    """Invisible clickable area covering a row's unit art and text.

    The action glyphs occupy the rest of the row and do not overlap this rect,
    so selecting a unit and issuing one of its commands remain separate clicks.
    It inherits Button's press/click/sound handling while leaving the dense row
    rendering to Orders_Screen.additional_draw.
    """

    def __init__(self, rect, callback, secondary_callback=None):
        super().__init__(rect.x, rect.y, "tiny_square", "grey", "", callback,
                         show_text=False)
        self.rect = pygame.Rect(rect)
        self.secondary_callback = secondary_callback

    def draw(self, surface):
        pass


class Orders_Screen(GameState):
    back_state = "MAP"
    PANEL_X = 10
    PANEL_WIDTH = 440
    PANEL_TRANSPARENCY = 255

    def __init__(self):
        super().__init__()
        self.target_province = None
        self.map_screen = None
        self.selected_unit_index = None
        # Rows normally follow selection.  When any selected division belongs
        # to an army, its unselected peers are included as read-only roster
        # context so a player can see the army without accidentally ordering
        # every member.
        self.cancel_rects = []
        self.action_buttons = []
        self.unit_row_icons = {}
        self.action_icons = {}
        self._roster_rows = []
        self._selected_display_records = []
        self._selected_display_ids = frozenset()
        self._row_order_summaries = {}
        self._panel_title_text = "ORDERS | MAP COMMAND"
        self._presentation_state = None
        self.battle_screen = None
        self.entered_from_combat_bubble = False
        self.return_to_province_menu = True
        self.renaming_unit_index = None
        self.renaming_unit_province = None
        self.renaming_unit_actual_index = None
        self.rename_text = ""

        # Capture live unit references while waiting for an aircraft target.
        self._air_target_records = []
        self._air_target_mission = None
        self.bombarding_unit_index = None
        self.bombarding_unit_province = None
        self.bombarding_unit_actual_index = None
        self._consume_bombard_target_release = False
        self.air_range_previews = []
        self.air_strike_range_previews = []
        self._air_range_records = []
        self._air_range_hover_target = None
        self._air_range_input_key = None
        self._air_range_preview_key = ()
        self._air_range_layer = None
        self._air_range_layer_key = None
        self.bombard_target_preview = set()
        self.targeting_label = "bombardment"

        # True on a province where the player commands nothing: every unit is
        # listed, none of them is editable. Set per province in
        # start_with_province, but defined here so a screen built and painted
        # before its first handoff is not a special case.
        self.read_only = False

        self.scroll_y = 0
        self.max_scroll_y = 0
        self.row_height = 40
        self.panel_rect = pygame.Rect(self.PANEL_X, PANEL_Y, self.PANEL_WIDTH, PANEL_HEIGHT)
        self.panel_top = PANEL_Y + LIST_TOP_OFFSET_Y
        self.panel_max_h = self.panel_rect.bottom - self.panel_top

        self.unit_library = queries.get_unit_library(self.map_screen)

    def _mark_draft_changed(self):
        """Publish one order-edit boundary to the hosting map cache/sync path."""
        self.map_screen.invalidate_map_presentation_cache()

    def _panel_title(self, player_units):
        """Name the selected army when its membership is unambiguous."""
        army = queries.common_army_for_units(
            player_units, self.map_screen.nation_data)
        if army is not None and army.get("name"):
            return f"ORDERS | {army['name']}"
        return "ORDERS | MAP COMMAND"

    def start_with_province(self, province, map_ref):
        self.target_province = province
        self.map_screen = map_ref
        map_ref.army_panel_visible_in_orders = True
        self.return_to_province_menu = getattr(
            map_ref, "_orders_return_to_province_menu", True)
        if hasattr(map_ref, "_orders_return_to_province_menu"):
            delattr(map_ref, "_orders_return_to_province_menu")
        open_battle_on_entry = bool(
            getattr(map_ref, "_orders_entered_from_combat_bubble", False))
        self.entered_from_combat_bubble = open_battle_on_entry
        if hasattr(map_ref, "_orders_entered_from_combat_bubble"):
            delattr(map_ref, "_orders_entered_from_combat_bubble")
        self.battle_screen = None
        self.scroll_y = 0
        self.cancel_bombard_targeting(refresh=False)
        self.renaming_unit_index = None
        self.renaming_unit_province = None
        self.renaming_unit_actual_index = None
        self.rename_text = ""

        # --- Auto-select logic ---
        units = self.target_province.get("units", [])

        # A province you command nothing in is still worth reading -- what is
        # standing on the front you are about to walk into, and what orders it
        # already has. The panel shows every unit there and edits none of them.
        self.read_only = (not any(u.get("owner") == self.map_screen.player_country
                                  for u in units)
                          or (self.map_screen.realtime_multiplayer
                              and (self.map_screen.realtime_session.phase != "TURN"
                                   or self.map_screen.realtime_session.players[
                                       self.map_screen.realtime_player_id].submitted)))

        if self.map_screen.tactical_mode:
            # TACTICAL MODE: Lock to player unit
            player_unit_indices = [i for i, u in enumerate(units) if u is self.map_screen.player_unit]
            self.selected_unit_index = player_unit_indices[0] if player_unit_indices else None
        else:
            player_unit_indices = [i for i, u in enumerate(units) if u.get("owner") == self.map_screen.player_country]

            if len(player_unit_indices) > 1:
                self.selected_unit_index = "ALL"
            elif len(player_unit_indices) == 1:
                self.selected_unit_index = player_unit_indices[0]
            else:
                self.selected_unit_index = None

        if self.read_only:
            self.selected_unit_index = None
        elif self.map_screen.selected_unit_records():
            # A map click or box drag may already have selected a group across
            # several provinces.  Orders must retain that group verbatim.
            self.selected_unit_index = None
        elif self.selected_unit_index == "ALL":
            self.map_screen.select_map_units(
                [unit for unit in units if unit.get("owner") == self.map_screen.player_country])
        elif isinstance(self.selected_unit_index, int):
            self.map_screen.select_map_units([units[self.selected_unit_index]])

        self.refresh_ui()
        if (open_battle_on_entry and queries.is_province_in_active_combat(
                self.target_province, self.map_screen.nation_data)):
            self.open_battle_panel()

    def inspect_province(self, province, preserve_scroll=False):
        """Retarget the live Orders workspace to another visible stack."""
        self.target_province = province
        self.map_screen.selected_province = province
        self.battle_screen = None
        if not preserve_scroll:
            self.scroll_y = 0
        self.cancel_bombard_targeting(refresh=False)
        units = province.get("units", [])
        own_indices = [i for i, unit in enumerate(units)
                       if unit.get("owner") == self.map_screen.player_country]
        selected_indices = [i for i in own_indices
                            if self.map_screen.is_unit_selected(units[i])]
        if len(selected_indices) > 1:
            self.selected_unit_index = "ALL"
        elif selected_indices:
            self.selected_unit_index = selected_indices[0]
        else:
            self.selected_unit_index = None
        self.read_only = not self.map_screen.selected_unit_records()
        self.refresh_ui()

    def exit_screen(self):
        # The battle inspector is an optional child panel now, so leaving
        # Orders removes both windows in one transition back to the map.
        self.battle_screen = None
        # Selection belongs to this Orders session.  Returning to the map or
        # province menu must not leave a group armed for an accidental move.
        if self.map_screen:
            self.map_screen.clear_map_unit_selection()
            self.map_screen.army_panel_visible_in_orders = False
        if self.entered_from_combat_bubble or not self.return_to_province_menu:
            # A combat bubble is a direct map entry point, so Back should
            # return to the map rather than reopen the selected province menu.
            if self.map_screen:
                self.map_screen.deselect_province()
            super().exit_screen()
            return

        # Orders entered from the province menu deliberately keeps that menu
        # alive regardless of the global navigation-mode preference.
        super().exit_screen()

    def go_to_battle(self):
        """Opens the battle inspector beside Orders without leaving it."""
        if not self.map_screen or not self.target_province:
            return
        if not queries.is_province_in_active_combat(
                self.target_province, self.map_screen.nation_data):
            self.refresh_ui()
            return
        self.open_battle_panel()

    def battle_panel_rect(self):
        """The clear right-hand space beside Orders while a battle is open."""
        x = self.panel_rect.right + BATTLE_PANEL_GAP
        width = c.SCREEN_WIDTH - map_top_right_layout.PANEL_RIGHT_MARGIN - x
        # A battle inspector needs room for its lane rows even when Orders is
        # currently compact because the selected roster is short.
        return pygame.Rect(x, self.panel_rect.y, max(1, width), PANEL_HEIGHT)

    def open_battle_panel(self):
        """Creates the optional in-Orders battle panel for this province."""
        if not self.map_screen or not self.target_province:
            return
        if not queries.is_province_in_active_combat(
                self.target_province, self.map_screen.nation_data):
            self.refresh_ui()
            return
        if self.battle_screen is None:
            self.battle_screen = battle_screen.Battle_Screen(
                self.map_screen, self.target_province, origin_screen=self,
                embedded_rect=self.battle_panel_rect())
        self.refresh_ui()

    def close_battle_panel(self, panel=None):
        """Removes the battle pane while keeping Orders open."""
        if panel is not None and panel is not self.battle_screen:
            return
        self.battle_screen = None
        self.refresh_ui()

    def handle_orders_key(self):
        """Q. Same as clicking the Units button in the view-mode row; also
        jumps screens when the Keybinds screen's per-key toggle is on -- see
        screens.game.map_input.handle_view_mode_keybind."""
        map_input.handle_view_mode_keybind(self.map_screen, "UNITS", "ORDERS", origin=self)

    def handle_economy_key(self):
        """W. Same as clicking the Economy button in the view-mode row; also
        jumps screens when the Keybinds screen's per-key toggle is on -- see
        screens.game.map_input.handle_view_mode_keybind."""
        map_input.handle_view_mode_keybind(self.map_screen, "ECONOMY", "ECONOMY", origin=self)

    def handle_clear_orders_key(self):
        """Runs the same action as the Clear Orders button.

        The shortcut is deliberately unavailable everywhere the button is:
        foreign/read-only rosters and tactical mode. A key press also belongs
        to the rename field while that field is active, even if the player has
        rebound Clear Orders to a printable character.
        """
        if (self.renaming_unit_index is not None
                or self.read_only
                or not self.map_screen
                or self.map_screen.tactical_mode):
            return
        self.clear_all_orders()

    def select_unit(self, index):
        if self.read_only:
            return
        if self.map_screen.tactical_mode:
            self.map_screen.show_feedback("Tactical Mode: You can only command your specific unit!")
            return
        units = self.target_province.get("units", [])
        if index == "ALL":
            # Orders is map-wide: all means every commandable owned unit, not
            # merely the stack that opened this workspace.
            all_units = [unit for province in self.map_screen.map_data.values()
                         for unit in province.get("units", [])
                         if unit.get("owner") == self.map_screen.player_country]
            if all_units and all(self.map_screen.is_unit_selected(unit) for unit in all_units):
                self.map_screen.deselect_map_units(all_units)
                self.selected_unit_index = None
            else:
                self.map_screen.select_map_units(all_units)
                self.selected_unit_index = index
        elif isinstance(index, int) and 0 <= index < len(units):
            unit = units[index]
            selected = self.map_screen.click_select_map_units(
                [unit], additive=bool(pygame.key.get_mods() & pygame.KMOD_SHIFT))
            self.selected_unit_index = index if selected else None
        self.cancel_bombard_targeting(refresh=False)
        self.refresh_ui()

    def toggle_selected_unit(self, unit, province=None, additive=False):
        """Apply the shared map click behavior to one Orders roster row."""
        if self.read_only or self._command_blocked(unit):
            return
        if additive:
            if not self.map_screen.can_select_map_units():
                return
            if self.map_screen.is_unit_selected(unit):
                self.map_screen.deselect_map_units([unit])
            else:
                self.map_screen.select_map_units([unit], additive=True)
            selected = self.map_screen.is_unit_selected(unit)
        else:
            selected = self.map_screen.click_select_map_units(
                [unit], additive=bool(pygame.key.get_mods() & pygame.KMOD_SHIFT))
        self.selected_unit_index = None
        self.cancel_bombard_targeting(refresh=False)
        if selected and province is not None:
            # Selecting another roster member keeps the same army roster open,
            # so preserve its current scroll position while refreshing rows.
            self.inspect_province(province, preserve_scroll=True)
        else:
            self.refresh_ui()

    def ungroup_selected(self):
        self.map_screen.ungroup_selection()
        self.refresh_ui()

    def _batch_command_candidates(self, command, records=None):
        """Return selected units which can use one batch command.

        Repair, upgrade, and disband replace current orders.
        Mission buttons can replace active missions through the selector.
        Return reserved repair resources before replacing an order.
        """
        candidates = []
        combat_by_province = {}
        launch_by_base = {}
        indexes_by_province = {}
        player_research = self.map_screen.nation_data.get(
            self.map_screen.player_country, {}).get("research", {})
        if records is None:
            records = self.map_screen.selected_unit_records()
        for unit, province in records:
            if (unit.get("owner") != self.map_screen.player_country
                    or self._command_blocked_silent(unit)):
                continue
            province_key = id(province)
            if command in ("REPAIR", "UPGRADE"):
                if province_key not in combat_by_province:
                    combat_by_province[province_key] = queries.is_nation_in_combat_here(
                        self.map_screen.player_country, province, self.map_screen.nation_data)
                in_combat = combat_by_province[province_key]
            if command == "DISBAND":
                if not unit.get("air_cargo"):
                    candidates.append((unit, province))
            elif command == "REPAIR":
                if (not in_combat and queries.has_industry(province)
                        and unit.get("health", 0) < unit.get("max_health", 1)):
                    candidates.append((unit, province))
            elif command == "UPGRADE":
                target = queries.get_upgrade_target(
                    unit.get("type", ""), player_research, self.unit_library,
                    queries.get_tech_tree(self.map_screen))
                if not in_combat and queries.has_industry(province) and target:
                    candidates.append((unit, province, target))
            elif command == "MISSION":
                if not queries.is_air_unit(unit, context=self.map_screen):
                    continue
                if province_key not in indexes_by_province:
                    indexes_by_province[province_key] = {
                        id(current): index for index, current in enumerate(province.get("units", []))}
                if self._air_mission_unit_index(
                        unit, province, indexes_by_province[province_key]) is None:
                    continue
                # Launch legality depends on the base and combat owner. Keep
                # this result only for this snapshot; callbacks check again.
                launch_key = (province_key, queries.get_unit_combat_owner(unit))
                if queries.air_unit_has_mission(unit, context=self.map_screen):
                    candidates.append((unit, province))
                    continue
                if launch_key not in launch_by_base:
                    launch_by_base[launch_key] = queries.air_unit_can_launch(self.map_screen, unit, province)
                if launch_by_base[launch_key]:
                    candidates.append((unit, province))
        return candidates

    def _selected_units_with_order(self, order_type, records=None):
        """Selected commandable units currently carrying one named order."""
        if records is None:
            records = self.map_screen.selected_unit_records()
        return [
            (unit, province)
            for unit, province in records
            if (unit.get("owner") == self.map_screen.player_country
                and not self._command_blocked_silent(unit)
                and isinstance(unit.get("order"), dict)
                and unit["order"].get("type") == order_type)
        ]

    def cancel_selected_batch_orders(self, order_type):
        """Cancel one matching order across the current selection at once."""
        ordered_units = self._selected_units_with_order(order_type)
        if not ordered_units:
            return
        unit_actions.apply_batch(self.map_screen, self.map_screen.player_country,
                                 [(unit, province, None) for unit, province in ordered_units])
        self._mark_draft_changed()
        self.map_screen.show_feedback(
            f"Cancelled {order_type.lower()} for {len(ordered_units)} selected "
            f"unit{'s' if len(ordered_units) != 1 else ''}.")
        self.refresh_ui()

    def disband_selected_units(self):
        candidates = self._batch_command_candidates("DISBAND")
        unit_actions.apply_batch(self.map_screen, self.map_screen.player_country,
            [(unit, province, {"type": "DISBAND"}) for unit, province in candidates])
        self._finish_batch_command("Disband", len(candidates))

    def repair_selected_units(self):
        candidates = self._batch_command_candidates("REPAIR")
        try:
            unit_actions.apply_batch(self.map_screen, self.map_screen.player_country,
                [(unit, province, {"type": "REPAIR"}) for unit, province in candidates])
        except ValueError as error:
            self.map_screen.show_feedback(str(error))
            return
        self._finish_batch_command("Repair", len(candidates))

    def upgrade_selected_units(self):
        candidates = self._batch_command_candidates("UPGRADE")
        unit_actions.apply_batch(self.map_screen, self.map_screen.player_country,
            [(unit, province, {"type": "UPGRADE", "target_type": target})
             for unit, province, target in candidates])
        self._finish_batch_command("Upgrade", len(candidates))

    def _finish_batch_command(self, label, count):
        if not count:
            self.map_screen.show_feedback(f"No selected units can {label.lower()} now.")
            return
        self._mark_draft_changed()
        self.map_screen.show_feedback(f"{label} ordered for {count} selected unit{'s' if count != 1 else ''}.")
        self.refresh_ui()

    def open_selected_air_mission_select(self):
        records = self._batch_command_candidates("MISSION")
        if not records:
            return
        if len(records) == 1 and self._open_loaded_transport_menu(*records[0]):
            return
        # Keep the original selection. A later snapshot/selection change must
        # not redirect this popup's callback to different units.
        popup = _AirMissionSelectScreen(self, AIR_MISSION_CHOICES,
            lambda mission: self.set_selected_air_mission(mission, records),
            enabled_missions=set().union(*(queries.available_air_missions(
                self.map_screen, unit, base) for unit, base in records)))
        screen_runner._run_pygame_sub_screen(self.map_screen, popup)

    def set_selected_air_mission(self, mission, records=None):
        if mission not in AIR_MISSION_ICONS:
            return
        if records is None:
            records = self._batch_command_candidates("MISSION")
        if mission == "TRANSPORT":
            eligible = [(unit, base) for unit, base in records
                        if self._air_mission_unit_index(unit, base) is not None
                        and mission in queries.available_air_missions(self.map_screen, unit, base)]
            if len(eligible) == 1:
                self.open_air_transport(*eligible[0])
            elif eligible:
                items = [(f"{unit.get('custom_name') or queries.get_unit_display_name(unit['type'], context=self.map_screen)} (tile {base['id']})", (unit, base))
                         for unit, base in eligible]
                screen_runner._run_pygame_sub_screen(self.map_screen, ListSelectScreen(
                    self.map_screen, "Select transport aircraft", "Choose an aircraft", items,
                    lambda record: self.open_air_transport(*record)))
            return
        if mission in queries.AIR_TARGET_MISSION_TYPES:
            self.start_air_targeting(records, mission)
            return
        self._apply_selected_air_mission(records, mission)

    def _open_loaded_transport_menu(self, plane, province):
        if (not plane.get("air_cargo")
                or "TRANSPORT" not in queries.available_air_missions(self.map_screen, plane, province)):
            return False
        self.open_air_transport(plane, province)
        return True

    def _apply_selected_air_mission(self, records, mission):
        count = 0
        for unit, province in records:
            if self._air_mission_unit_index(unit, province) is None:
                continue
            try:
                order = self._air_mission_order(unit, province, mission)
            except ValueError:
                # Mixed groups skip unsupported defense choices or invalid bases.
                # Keep those units' orders and reserved payment.
                continue
            unit_actions.apply_action(self.map_screen, unit["owner"], province, unit, order)
            count += 1
        self.cancel_bombard_targeting(refresh=False)
        self._finish_batch_command("Air mission", count)
        if not count:
            self.refresh_ui()

    def _command_blocked_silent(self, unit):
        """True if tactical mode forbids acting on this unit.

        A tactical player pilots one specific unit, not their whole nation, so
        other units they own in the same stack must be rejected the same way
        foreign units are -- every order-issuing method needs this check, not
        just the buttons that call it.
        """
        # Lightweight UI test doubles omit optional mode/controller hooks.
        map_ref = self.map_screen
        if queries.unit_is_air_drop_recovering(unit):
            return True
        if self.read_only:
            return True
        if hasattr(map_ref, "player_country") and unit.get("owner") != map_ref.player_country:
            return True
        can_command = getattr(map_ref, "can_select_map_units", None)
        if can_command and not can_command():
            return True
        return map_ref.tactical_mode and unit is not map_ref.player_unit

    def _command_blocked(self, unit):
        """Like _command_blocked_silent, but also surfaces feedback to the player."""
        if self._command_blocked_silent(unit):
            self.map_screen.show_feedback(
                "This unit is recovering from an air drop and cannot be controlled."
                if queries.unit_is_air_drop_recovering(unit) else
                "Tactical Mode: You can only command your specific unit!")
            return True
        return False

    def fit_icon(self, icon, size_preset, padding=6):
        """Shrinks an oversized unit sprite so it stays inside its button.

        Unit art is drawn at roughly real-world scale, so a Railroad Gun or a
        Battleship is many times the size of an infantryman and would otherwise
        spill out over the neighbouring rows.
        """
        if not icon:
            return icon

        box_w, box_h = c.SIZES.get(size_preset, (50, 50))
        box_w, box_h = box_w - padding, box_h - padding
        w, h = icon.get_size()

        if w <= box_w and h <= box_h:
            return icon

        ratio = min(box_w / w, box_h / h)
        return pygame.transform.smoothscale(icon, (max(1, int(w * ratio)), max(1, int(h * ratio))))

    def _get_action_icon(self, name, button_size=None):
        """Fill the button's icon area, scaling small glyphs up as well as down."""
        button_size = button_size or c.SIZES["orders_action_icon"]
        icon_side = max(1, min(button_size) - 2 * ACTION_ICON_INSET)
        key = (name, icon_side)
        if key not in self.action_icons:
            self.action_icons[key] = symbol_loader.get_symbol(
                name, zoom=1, fit_size=(icon_side, icon_side))
        return self.action_icons[key]

    @staticmethod
    def _fit_batch_button(button, width):
        """Keep complete action/count labels inside the four-column header."""
        button.rect.width = width
        size = fonts.presets["tiny"]["size"]
        while size > 1 and button.font.size(button.text)[0] > width - 2 * BATCH_LABEL_INSET:
            size -= 1
            button.font = fonts.get_size(size)

    def _add_action_button(self, unit_index, row_y, slot, color, help_text,
                           callback, icon_name, row_guard, *, enabled=True):
        x = self.PANEL_X + ACTION_START_OFFSET_X + (slot * ACTION_BUTTON_STEP_X)
        button = Button(x, row_y + ACTION_BUTTON_OFFSET_Y, "orders_action_icon",
                        color, "", callback, image=self._get_action_icon(icon_name),
                        show_text=False)
        button.help_text = help_text
        button.unit_index = unit_index
        button.action_slot = slot
        button.is_scrollable = True
        button.click_guard = row_guard
        if not enabled:
            button.apply_state(enabled=False)
        self.elements.append(button)
        self.action_buttons.append(button)
        return button

    def _build_unit_action_buttons(self, row_key, index, unit, province, row_y, row_guard,
                                   in_combat, is_water, is_coastal,
                                   is_factory, player_research):
        """Builds the six HOI-style icon commands for one visible roster row."""
        unit_name = unit.get("type", "")
        order = unit.get("order", {})
        if not isinstance(order, dict):
            order = {}
        order_type = order.get("type", "")
        is_convoy = unit_name.startswith("Convoy")
        is_truck = unit_name.startswith("Truck")
        is_naval = queries.is_naval_unit(unit_name, context=self.map_screen)
        is_tactical = self.map_screen.tactical_mode
        buttons = []

        def add(slot, color, help_text, callback, icon_name, enabled=True):
            button = self._add_action_button(
                row_key, row_y, slot, color, help_text, callback, icon_name,
                row_guard, enabled=enabled)
            buttons.append(button)
            return button

        # Convert between land, convoy, truck and ship forms.
        if is_convoy:
            convert_icon = "Unconvoying"
        elif is_truck:
            convert_icon = "Untrucking"
        elif is_naval:
            convert_icon = "Trucking"
        else:
            convert_icon = "Convoying"

        if order_type == "CONVERT":
            btn_conv = add(ACTION_COL_CONVERT, "red", "Cancel conversion",
                           lambda idx=index, p=province: self.cancel_unit_order(idx, p), convert_icon)
        elif in_combat:
            btn_conv = add(ACTION_COL_CONVERT, "grey", "Convert: unavailable in combat",
                           lambda: None, convert_icon, enabled=False)
        elif queries.air_conversion_order(unit, context=self.map_screen):
            conversion = queries.air_conversion_order(unit, context=self.map_screen)
            enabled = not is_water and (is_convoy or is_coastal)
            btn_conv = add(ACTION_COL_CONVERT, "blue" if enabled else "grey",
                           f"Convert to {conversion['to']} ({conversion['turns_left']} turn)"
                           if enabled else "Aircraft Convoy conversion requires a coast; unloading requires land",
                           lambda idx=index, p=province: self.convert_unit(idx, p), convert_icon,
                           enabled=enabled)
        elif is_convoy:
            if not is_water:
                btn_conv = add(ACTION_COL_CONVERT, "blue", "Convert convoy to land unit",
                               lambda idx=index, p=province: self.convert_unit(idx, p), convert_icon)
            else:
                btn_conv = add(ACTION_COL_CONVERT, "grey", "Convert: convoy needs land",
                               lambda: None, convert_icon, enabled=False)
        elif is_truck:
            if is_coastal or is_water:
                btn_conv = add(ACTION_COL_CONVERT, "blue", "Convert truck to ship",
                               lambda idx=index, p=province: self.convert_unit(idx, p), convert_icon)
            else:
                btn_conv = add(ACTION_COL_CONVERT, "grey", "Convert: requires a coast",
                               lambda: None, convert_icon, enabled=False)
        elif not is_naval:
            if is_coastal or is_water:
                btn_conv = add(ACTION_COL_CONVERT, "blue", "Convert land unit to convoy",
                               lambda idx=index, p=province: self.convert_unit(idx, p), convert_icon)
            else:
                btn_conv = add(ACTION_COL_CONVERT, "grey", "Convert: requires a coast",
                               lambda: None, convert_icon, enabled=False)
        elif player_research.get("trucks", 0) < 1:
            btn_conv = add(ACTION_COL_CONVERT, "grey", "Convert: requires Trucks research",
                           lambda: None, convert_icon, enabled=False)
        elif is_coastal or not is_water:
            btn_conv = add(ACTION_COL_CONVERT, "blue", "Convert ship to truck",
                           lambda idx=index, p=province: self.convert_unit(idx, p), convert_icon)
        else:
            btn_conv = add(ACTION_COL_CONVERT, "grey", "Convert: requires a coast",
                           lambda: None, convert_icon, enabled=False)

        if order_type == "DISBAND":
            btn_disband = add(ACTION_COL_DISBAND, "red", "Cancel disband order",
                              lambda idx=index, p=province: self.cancel_unit_order(idx, p), "Disbanding")
        elif is_tactical and unit is self.map_screen.player_unit:
            btn_disband = add(ACTION_COL_DISBAND, "grey", "Disband: unavailable in tactical mode",
                              lambda: None, "Disbanding", enabled=False)
        elif unit.get("air_cargo"):
            btn_disband = add(ACTION_COL_DISBAND, "grey", "Disband: release cargo first",
                              lambda: None, "Disbanding", enabled=False)
        else:
            btn_disband = add(ACTION_COL_DISBAND, "red", "Disband unit",
                              lambda idx=index, p=province: self.disband_unit(idx, p), "Disbanding")

        hp = int(unit.get("health", 0))
        max_hp = int(unit.get("max_health", 1))
        if order_type == "REPAIR":
            btn_repair = add(ACTION_COL_REPAIR, "orange", "Cancel repair order",
                             lambda idx=index, p=province: self.cancel_unit_order(idx, p), "Repairing")
        elif hp >= max_hp:
            btn_repair = add(ACTION_COL_REPAIR, "grey", "Repair: unit is at full HP",
                             lambda: None, "Repairing", enabled=False)
        elif in_combat:
            btn_repair = add(ACTION_COL_REPAIR, "grey", "Repair: unavailable in combat",
                             lambda: None, "Repairing", enabled=False)
        elif not is_factory:
            btn_repair = add(ACTION_COL_REPAIR, "grey", "Repair: requires a factory",
                             lambda: None, "Repairing", enabled=False)
        else:
            btn_repair = add(ACTION_COL_REPAIR, "green", "Repair unit",
                             lambda idx=index, p=province: self.repair_unit(idx, p), "Repairing")

        if self.renaming_unit_index == row_key:
            btn_rename = add(ACTION_COL_CONVERT, "green", "Save unit name (Enter)",
                             lambda idx=index, p=province: self.save_unit_name(idx, p), "Text")
        else:
            btn_rename = add(ACTION_COL_RENAME, "blue", "Rename unit",
                             lambda idx=index, p=province, key=row_key: self.start_renaming(idx, p, key), "Text")

        if order_type == "UPGRADE":
            btn_upgrade = add(ACTION_COL_UPGRADE, "red", "Cancel upgrade order",
                              lambda idx=index, p=province: self.cancel_unit_order(idx, p), "Upgrading")
        else:
            upgrade_target = queries.get_upgrade_target(
                unit_name, player_research, self.unit_library, queries.get_tech_tree(self.map_screen))
            if not upgrade_target:
                btn_upgrade = add(ACTION_COL_UPGRADE, "grey", "Upgrade: maximum level reached",
                                  lambda: None, "Upgrading", enabled=False)
            elif in_combat:
                btn_upgrade = add(ACTION_COL_UPGRADE, "grey", "Upgrade: unavailable in combat",
                                  lambda: None, "Upgrading", enabled=False)
            elif not is_factory:
                btn_upgrade = add(ACTION_COL_UPGRADE, "grey", "Upgrade: requires a factory",
                                  lambda: None, "Upgrading", enabled=False)
            else:
                btn_upgrade = add(
                    ACTION_COL_UPGRADE, "orange", f"Upgrade to {upgrade_target}",
                    lambda idx=index, target=upgrade_target, p=province: self.upgrade_unit(idx, target, p),
                    "Upgrading")

        if queries.is_air_unit(unit, context=self.map_screen):
            mission = queries.air_unit_mission_icon(unit)
            targeting = any(current is unit for current, _base in self._air_target_records)
            if targeting and not unit.get("air_cargo"):
                mission = self._air_target_mission
            add(ACTION_COL_BOMBARD, "orange" if targeting else "yellow",
                "Choose a map target; click to change mission" if targeting
                else "Select air mission: move, strike, transport, defend area, or no mission",
                lambda idx=index, p=province, key=row_key: self.open_air_mission_select(idx, p, key),
                c.AIR_MISSION_ICONS[mission])
        elif order_type == "BOMBARD":
            btn_bombard = add(ACTION_COL_BOMBARD, "red", "Cancel bombardment",
                              lambda idx=index, p=province: self.cancel_unit_order(idx, p),
                              "Bombardment Arrows")
        elif not queries.can_bombard(unit_name, context=self.map_screen):
            btn_bombard = add(ACTION_COL_BOMBARD, "grey", "Bombard: unit has no bombardment",
                              lambda: None, "Bombardment Arrows", enabled=False)
        elif is_water and not is_naval:
            btn_bombard = add(ACTION_COL_BOMBARD, "grey", "Bombard: land guns cannot fire at sea",
                              lambda: None, "Bombardment Arrows", enabled=False)
        elif self.bombarding_unit_index == row_key:
            btn_bombard = add(ACTION_COL_BOMBARD, "orange", "Choose target (click to cancel)",
                              self.cancel_bombard_targeting, "Bombardment Arrows")
        else:
            btn_bombard = add(ACTION_COL_BOMBARD, "yellow", "Choose bombardment target",
                              lambda idx=index, p=province, key=row_key: self.start_bombard_targeting(idx, p, key),
                              "Bombardment Arrows")

        # Rename gets the name field and one Save glyph to itself. This is the
        # compact counterpart of the old row hiding its other five buttons.
        if self.renaming_unit_index == row_key:
            for button in buttons:
                if button is not btn_rename:
                    button.apply_state(visible=False)

    def _visible_rows(self, selected_records=None):
        """Selected units plus their army peers in each army's saved order."""
        if selected_records is None:
            selected_records = self.map_screen.selected_unit_records()
        if self.read_only and not selected_records:
            selected_records = [(unit, self.target_province)
                                for unit in self.target_province.get("units", [])]
        visible_records = list(selected_records)
        if selected_records and not self.read_only:
            nation_data = self.map_screen.nation_data
            map_data = self.map_screen.map_data
            if isinstance(nation_data, dict) and isinstance(map_data, dict):
                records_by_id = {
                    unit.get("unit_id"): (unit, province)
                    for province in map_data.values()
                    for unit in province.get("units", [])
                    if (unit.get("owner") == self.map_screen.player_country
                        and isinstance(unit.get("unit_id"), str))
                }
                ordered_records = []
                visible_ids = set()
                visible_armies = set()

                def include(record):
                    unit, _province = record
                    unit_id = unit.get("unit_id")
                    record_id = unit_id if isinstance(unit_id, str) else id(unit)
                    if record_id not in visible_ids:
                        ordered_records.append(record)
                        visible_ids.add(record_id)

                for unit, _province in selected_records:
                    army = queries.army_for_unit(unit, nation_data)
                    if army:
                        if army["id"] in visible_armies:
                            continue
                        visible_armies.add(army["id"])
                        # Selection must not reorder a group's card roster:
                        # a member stays at its persistent army position even
                        # when it is the only selected division.
                        for unit_id in army.get("unit_ids", []):
                            record = records_by_id.get(unit_id)
                            if record is not None:
                                include(record)
                    else:
                        include((unit, _province))
                visible_records = ordered_records
        rows = []
        indexes_by_province = {}
        for unit, province in visible_records:
            province_key = id(province)
            if province_key not in indexes_by_province:
                indexes_by_province[province_key] = {
                    id(current): index for index, current in enumerate(province.get("units", []))}
            index = indexes_by_province[province_key].get(id(unit))
            if index is None:
                continue
            row_key = index if province is self.target_province else (province["id"], index)
            rows.append((row_key, unit, province, index))
        return rows

    def _refresh_air_range_previews(self, destination=None):
        """Cache one outline per aircraft at selection, order, or hover changes."""
        self.air_range_previews = []
        self.air_strike_range_previews = []
        seen_ranges = set()
        preview_rules = {}
        records = self._air_target_records or self._air_range_records
        for unit, base in records:
            order = unit.get("order")
            # Cargo eligibility depends on each carrier's live cargo records.
            # Empty aircraft share rules by type, combat owner, and current order.
            profile = (unit.get("type"), queries.get_unit_combat_owner(unit),
                       order.get("type") if isinstance(order, dict) else None,
                       id(unit) if unit.get("air_cargo") else None)
            if profile not in preview_rules:
                if self._air_target_records:
                    if (self._air_target_mission == "MOVE"
                            and queries.air_unit_can_move_on_ground(unit, context=self.map_screen)):
                        preview_rules[profile] = None
                        continue
                    kind = queries.AIR_TARGET_MISSION_TYPES[self._air_target_mission]
                else:
                    kind = queries.air_range_preview_kind(self.map_screen, unit, destination)
                preview_rules[profile] = kind, queries.air_order_radius(unit, kind, context=self.map_screen)
            preview = preview_rules[profile]
            if preview is None:
                continue
            kind, radius = preview
            previews = (self.air_range_previews if kind == "AIR_REPOSITION"
                        else self.air_strike_range_previews)
            key = (kind == "AIR_REPOSITION", tuple(base["center"]), radius)
            if key not in seen_ranges:
                previews.append((base, radius))
                seen_ranges.add(key)

        preview_key = tuple((tuple(base["center"]), radius, MOVE_TARGET_COLOR)
                            for base, radius in self.air_range_previews)
        preview_key += tuple((tuple(base["center"]), radius, BOMBARD_TARGET_COLOR)
                             for base, radius in self.air_strike_range_previews)
        if preview_key != self._air_range_preview_key:
            self._air_range_preview_key = preview_key
            self._air_range_layer_key = None
            if not preview_key:
                self._air_range_layer = None

    def _refresh_air_range_hover(self, position):
        """Recheck hover after mouse or camera input, retaining cached outlines."""
        camera = self.map_screen.camera
        input_key = (tuple(position), tuple(camera.pos), camera.zoom, camera.tilt_factor)
        if input_key == self._air_range_input_key:
            return
        self._air_range_input_key = input_key
        if not self._air_range_records:
            return
        on_ui = (self.panel_rect.collidepoint(position)
                 or map_input.map_ui_bar_at_position(self.map_screen, position))
        destination = None if on_ui else queries.get_clicked_province(position, self.map_screen)
        # Empty map space and UI retain the last territory's range preview.
        if destination is not None and destination is not self._air_range_hover_target:
            self._air_range_hover_target = destination
            self._refresh_air_range_previews(destination)

    def refresh_ui(self):
        selected_records = self.map_screen.selected_unit_records()
        if self.target_province is not None:
            sidebar_info.prepare_unit_roster(self.map_screen, self.target_province)
        self._air_range_records = [(unit, base)
            for unit, base in selected_records if queries.is_air_unit(unit, context=self.map_screen)]
        self._air_range_input_key = None
        self._refresh_air_range_previews(self._air_range_hover_target)
        if self.map_screen.realtime_multiplayer:
            player = self.map_screen.realtime_session.players.get(self.map_screen.realtime_player_id)
            self.read_only = (self.map_screen.realtime_session.phase != "TURN" or not player
                              or player.submitted or player.eliminated)
        self.view_mode_buttons = view_mode_buttons.build(
            lambda mode: map_input.navigate_view_mode(self.map_screen, mode, origin=self))
        view_mode_buttons.sync_highlight(self.view_mode_buttons, self.map_screen.secondary_mode)

        # Keep the command box no taller than its current roster requires.
        # Once the roster reaches the normal map-panel limit it uses the
        # existing scroll region exactly as before.
        initial_rows = self._visible_rows(selected_records)
        desired_height = (LIST_TOP_OFFSET_Y
                          + max(1, len(initial_rows)) * self.row_height
                          + PANEL_BOTTOM_INSET)
        self.panel_rect.height = min(PANEL_HEIGHT, desired_height)
        self.panel_max_h = self.panel_rect.bottom - self.panel_top

        close_button = Button(self.panel_rect.right - 38, self.panel_rect.y + 7,
                              "tiny_square", "red", "X", self.exit_screen,
                              font_preset="tiny")
        self.elements = [*self.view_mode_buttons, close_button]
        self.action_buttons = []
        self.unit_row_icons = {}

        is_tactical = self.map_screen.tactical_mode
        player_country = self.map_screen.player_country
        player_research = self.map_screen.nation_data.get(player_country, {}).get("research", {})
        rows = initial_rows
        player_units = [unit for _key, unit, _province, _index in rows
                        if self.map_screen.is_unit_selected(unit)]
        all_player_units = [unit for province in self.map_screen.map_data.values()
                            for unit in province.get("units", [])
                            if unit.get("owner") == player_country]
        target_player_units = [unit for unit in self.target_province.get("units", [])
                               if unit.get("owner") == player_country]

        # Keep a focused province for the battle pane and a single unit's
        # targeting preview, but action buttons below always receive their
        # own row province.  Multi-selection therefore remains safe.
        single_row = rows[0] if len(rows) == 1 else None
        if single_row and single_row[2] is not self.target_province:
            self.target_province = single_row[2]
            rows = self._visible_rows(selected_records)
            single_row = rows[0] if len(rows) == 1 else None

        # Build roster data at input and state changes. Frames draw these records.
        self._roster_rows = rows
        self._selected_display_records = selected_records
        self._selected_display_ids = frozenset(
            unit["unit_id"] for unit, _province in selected_records
            if isinstance(unit.get("unit_id"), str))
        self._panel_title_text = self._panel_title(player_units)
        self._row_order_summaries = {
            key: self._order_summary(key, unit)
            for key, unit, _province, _index in rows
            if unit.get("owner") == player_country}
        self._presentation_state = self._current_presentation_state()

        # Battle is deliberately a child of Orders.  Keep this available for
        # observers as well as participants: a read-only Orders view can still
        # inspect the fight, but no unit commands are enabled there.
        in_battle = queries.is_province_in_active_combat(
            self.target_province, self.map_screen.nation_data)
        if in_battle:
            battle_label = ("Close Battle" if self.battle_screen is not None else
                            ("Manage Battle" if target_player_units else "View Battle"))
            battle_callback = (self.close_battle_panel if self.battle_screen is not None
                               else self.go_to_battle)
            battle_button = Button(
                self.panel_rect.right - PANEL_INSET - 112,
                PANEL_Y + TOP_BTN_ROW_OFFSET_Y,
                "orders_header_button", "red", battle_label,
                battle_callback, font_preset="tiny")
            self.elements.append(battle_button)

        total_content_h = len(rows) * self.row_height
        self.max_scroll_y = min(0, self.panel_max_h - total_content_h)
        self.scroll_y = max(self.max_scroll_y, min(0, self.scroll_y))
        self.scroll_content_rect = pygame.Rect(
            self.PANEL_X + 2, self.panel_top,
            self.PANEL_WIDTH - SCROLLBAR_WIDTH - 2, self.panel_max_h)
        row_guard = self.content_hover_guard()

        if not self.read_only:
            button_x = self.PANEL_X + PANEL_INSET
            all_selected = bool(all_player_units) and all(
                self.map_screen.is_unit_selected(unit) for unit in all_player_units)
            all_color = "grey" if is_tactical else (
                "blue" if all_selected else "grey")
            btn_all = Button(button_x, PANEL_Y + TOP_BTN_ROW_OFFSET_Y,
                             "orders_header_button", all_color, "Select All",
                             lambda: self.select_unit("ALL"), font_preset="tiny")
            btn_all.disabled = is_tactical
            btn_all.is_selected = all_selected and not is_tactical
            self.elements.append(btn_all)
            button_x = btn_all.rect.right + TOP_BTN_GAP_X

            btn_clear = Button(button_x, PANEL_Y + TOP_BTN_ROW_OFFSET_Y,
                               "orders_clear_button", "red",
                               "Clear ALL Orders", self.clear_all_orders,
                               font_preset="tiny")
            btn_clear.disabled = is_tactical
            self.elements.append(btn_clear)
            button_x = btn_clear.rect.right + TOP_BTN_GAP_X

            if player_units:
                # A battle command occupies the top-right slot only during
                # combat. Keep the normal three controls on one line, while
                # using a third header row in that exceptional view.
                ungroup_y = PANEL_Y + (BATTLE_UNGROUP_ROW_OFFSET_Y if in_battle
                                        else TOP_BTN_ROW_OFFSET_Y)
                btn_ungroup = Button(button_x, ungroup_y,
                                     "orders_header_button", "grey", "Ungroup",
                                     self.ungroup_selected, font_preset="tiny")
                self.elements.append(btn_ungroup)

            if len(player_units) > 1:
                batch_actions = (
                    ("Disband", "DISBAND", self.disband_selected_units),
                    ("Repair", "REPAIR", self.repair_selected_units),
                    ("Upgrade", "UPGRADE", self.upgrade_selected_units),
                )
                batch_count = len(batch_actions) + 1  # Includes Set Mission.
                batch_width = ((self.PANEL_WIDTH - 2 * PANEL_INSET
                                - (batch_count - 1) * TOP_BTN_GAP_X) // batch_count)
                batch_x = self.PANEL_X + PANEL_INSET
                for label, order_type, start_order in batch_actions:
                    active_orders = self._selected_units_with_order(order_type, selected_records)
                    candidates = self._batch_command_candidates(order_type, selected_records)
                    active_ids = {id(unit) for unit, _province in active_orders}
                    action_scope_ids = active_ids | {
                        id(candidate[0]) for candidate in candidates}
                    # A mixed selection can include units which cannot repair
                    # or upgrade. Once every unit that this action covers is
                    # already carrying it, offer the matching batch cancel.
                    is_active_for_every_selection = bool(active_ids) and all(
                        unit_id in active_ids for unit_id in action_scope_ids)
                    count = len(active_orders) if is_active_for_every_selection else len(candidates)
                    button_label = (f"Cancel {label} ({count})"
                                    if is_active_for_every_selection
                                    else f"{label} ({count})")
                    callback = (
                        (lambda action=order_type: self.cancel_selected_batch_orders(action))
                        if is_active_for_every_selection else start_order)
                    color = ("red" if is_active_for_every_selection else
                             "green" if count else "grey")
                    button = Button(batch_x, PANEL_Y + BATCH_BTN_ROW_OFFSET_Y,
                                    "orders_header_button", color,
                                    button_label, callback,
                                    font_preset="tiny")
                    self._fit_batch_button(button, batch_width)
                    button.apply_state(enabled=bool(count), color=color)
                    button.help_text = (
                        f"Cancel {label.lower()} for {count} selected units."
                        if is_active_for_every_selection else
                        f"{label} every eligible selected unit, replacing its current order.")
                    self.elements.append(button)
                    batch_x = button.rect.right + TOP_BTN_GAP_X
                mission_records = self._batch_command_candidates("MISSION", selected_records)
                mission_count = len(mission_records)
                mission_label = f"Set Mission ({mission_count})"
                mission_button = Button(batch_x, PANEL_Y + BATCH_BTN_ROW_OFFSET_Y,
                    "orders_header_button", "blue", mission_label,
                    self.open_selected_air_mission_select, font_preset="tiny")
                self._fit_batch_button(mission_button, batch_width)
                mission_button.apply_state(enabled=bool(mission_count))
                mission_button.help_text = "Choose a mission for selected aircraft. No mission cancels their orders."
                self.elements.append(mission_button)

        for display_index, (row_key, unit, province, index) in enumerate(rows):
            row_y = self.panel_top + (display_index * self.row_height) + self.scroll_y
            row_rect = pygame.Rect(
                self.PANEL_X + UNIT_ROW_X_OFFSET, row_y,
                self.PANEL_WIDTH - SCROLLBAR_WIDTH - UNIT_ROW_X_OFFSET - 2,
                self.row_height)

            if not row_rect.colliderect(self.scroll_content_rect):
                continue

            unit_name = unit.get("type", "")
            unit_owner = unit.get("owner")
            combat_owner = queries.get_unit_combat_owner(unit)
            row_owner_color = self.map_screen.nation_colors.get(combat_owner, (200, 200, 200))
            icon = symbol_loader.get_symbol(
                unit_name, zoom=UNIT_ICON_ZOOM, color=row_owner_color, country=combat_owner)
            self.unit_row_icons[row_key] = self.fit_icon(
                icon, "small_square", padding=8)

            # Not this player's unit, or (Tactical Mode) one of their own
            # units that isn't the one they're piloting -- still listed with
            # its icon/name/health, just nothing to click and no command
            # column to the right of it.
            selectable = (unit.get("owner") == player_country
                         and not self._command_blocked_silent(unit))
            if not selectable:
                continue

            hitbox = _OrdersRowHitbox(
                pygame.Rect(row_rect.x, row_rect.y,
                            ACTION_START_OFFSET_X - UNIT_ROW_X_OFFSET - 2,
                            self.row_height),
                lambda selected_unit=unit, selected_province=province:
                self.toggle_selected_unit(selected_unit, selected_province),
                lambda selected_unit=unit, selected_province=province:
                self.toggle_selected_unit(selected_unit, selected_province,
                                          additive=True))
            hitbox.is_scrollable = True
            hitbox.click_guard = row_guard
            self.elements.append(hitbox)

            # Army peers are intentionally visible but unselected.  Their
            # row remains a selection target, while individual orders and
            # clear buttons remain exclusive to actively selected divisions.
            if not self.map_screen.is_unit_selected(unit):
                continue

            row_in_combat = queries.is_nation_in_combat_here(
                player_country, province, self.map_screen.nation_data)
            self._build_unit_action_buttons(
                row_key, index, unit, province, row_y, row_guard,
                row_in_combat, queries.is_water_province(province),
                province.get("is_coastal", False), queries.has_industry(province),
                player_research)

    def start_renaming(self, index, province=None, row_key=None):
        province = province or self.target_province
        units = province.get("units", [])
        if 0 <= index < len(units):
            if self._command_blocked(units[index]):
                return
            self.rename_text = units[index].get("custom_name", "")
        self.renaming_unit_index = index if row_key is None else row_key
        self.renaming_unit_province = province
        self.renaming_unit_actual_index = index
        self.refresh_ui()

    def save_unit_name(self, index, province=None):
        province = province or self.renaming_unit_province or self.target_province
        units = province.get("units", [])
        if 0 <= index < len(units):
            if self._command_blocked(units[index]):
                return
            if self.rename_text.strip():
                units[index]["custom_name"] = self.rename_text.strip()
            else:
                units[index].pop("custom_name", None)
            self._mark_draft_changed()
        self.renaming_unit_index = None
        self.renaming_unit_province = None
        self.renaming_unit_actual_index = None
        self.refresh_ui()

    def repair_unit(self, index, province=None):
        province = province or self.target_province
        in_combat = queries.is_nation_in_combat_here(self.map_screen.player_country, province, self.map_screen.nation_data)
        if in_combat:
            self.map_screen.show_feedback("Cannot repair during combat!")
            return

        units = province.get("units", [])
        if not (0 <= index < len(units)): return

        unit = units[index]
        if self._command_blocked(unit):
            return
        try:
            unit_actions.apply_action(self.map_screen, self.map_screen.player_country,
                                      province, unit, {"type": "REPAIR"})
        except ValueError as error:
            self.map_screen.show_feedback(str(error))
            return
        self._mark_draft_changed()
        self.map_screen.show_feedback("Repair ordered (1 turn).")
        self.refresh_ui()

    def upgrade_unit(self, index, target_type, province=None):
        province = province or self.target_province
        in_combat = queries.is_nation_in_combat_here(self.map_screen.player_country, province, self.map_screen.nation_data)
        if in_combat:
            self.map_screen.show_feedback("Cannot upgrade during combat!")
            return

        # The button is already greyed out as "Needs Factory" without one; this
        # is the same check standing behind it, so the rule holds whatever
        # reaches this method.
        if not queries.has_industry(province):
            self.map_screen.show_feedback("Cannot upgrade without a factory!")
            return

        units = province.get("units", [])
        if not (0 <= index < len(units)): return

        unit = units[index]
        if self._command_blocked(unit):
            return
        research = self.map_screen.nation_data[unit["owner"]].get("research", {})
        expected = queries.get_upgrade_target(unit.get("type", ""), research,
                                             self.unit_library, queries.get_tech_tree(self.map_screen))
        if expected is None or target_type != expected:
            self.map_screen.show_feedback("No legal numbered-unit upgrade is available.")
            return
        unit_actions.apply_action(self.map_screen, unit["owner"], province, unit, {
            "type": "UPGRADE",
            "turns_left": 1,
            "target_type": target_type,
            "refund": {}
        })
        self._mark_draft_changed()
        self.map_screen.show_feedback(f"Upgrade to {queries.get_unit_display_name(target_type, self.unit_library)} ordered (1 turn).")
        self.refresh_ui()

    def start_bombard_targeting(self, index, province=None, row_key=None):
        """Arms a gun and waits for the player to click the tile it should shell."""
        province = province or self.target_province
        units = province.get("units", [])
        if not (0 <= index < len(units)): return

        if self._command_blocked(units[index]):
            return

        unit = units[index]
        if queries.is_air_unit(unit, context=self.map_screen):
            self.set_air_mission(unit, province, "STRIKE", row_key)
            return
        self.cancel_bombard_targeting(refresh=False)
        self.targeting_label = "bombardment"
        self.bombard_target_preview = queries.get_bombardment_targets(
            province, self.map_screen.id_to_province, queries.get_bombardment_range(unit.get("type", ""), context=self.map_screen))

        self.bombarding_unit_index = index if row_key is None else row_key
        self.bombarding_unit_province = province
        self.bombarding_unit_actual_index = index
        self.map_screen.show_feedback("Select a tile within range to bombard.")
        self.refresh_ui()

    def cancel_bombard_targeting(self, refresh=True):
        self._air_target_records = []
        self._air_target_mission = None
        self.bombarding_unit_index = None
        self.bombarding_unit_province = None
        self.bombarding_unit_actual_index = None
        if refresh:
            self.refresh_ui()

    def set_bombard_target(self, index, dest, province=None):
        if self._air_target_records:
            self.set_air_target(dest)
            return
        province = province or self.bombarding_unit_province or self.target_province
        units = province.get("units", [])
        if not (0 <= index < len(units)):
            self.cancel_bombard_targeting(refresh=False)
            return

        unit = units[index]
        u_type = unit.get("type", "")
        if self._command_blocked(unit):
            return
        if queries.is_air_unit(unit, context=self.map_screen):
            return

        # The same rule process_bombardments applies: guns fire from land, and
        # ships that carry them (Battleship, Dreadnought, Carrier) fire from the
        # water by design.
        if (queries.is_water_province(province)
                and not (unit.get("naval_unit") or queries.is_naval_unit(u_type, context=self.map_screen))):
            self.map_screen.show_feedback("This unit cannot bombard from the water!")
            self.cancel_bombard_targeting(refresh=False)
            self.refresh_ui()
            return

        bomb_range = queries.get_bombardment_range(u_type, context=self.map_screen)
        in_range = queries.get_bombardment_targets(province, self.map_screen.id_to_province, bomb_range)

        if dest["id"] not in in_range:
            self.map_screen.show_feedback("Target out of bombardment range!")
            return

        # A gun that is firing stays put, so any queued movement is dropped
        unit_actions.apply_action(self.map_screen, unit["owner"], province, unit, {"type": "BOMBARD", "target_id": dest["id"]})
        self._mark_draft_changed()
        self.cancel_bombard_targeting(refresh=False)
        self.map_screen.show_feedback(f"Bombarding Province {dest['id']} (cannot move this turn)")
        self.refresh_ui()

    def disband_unit(self, index, province=None):
        province = province or self.target_province
        units = province.get("units", [])
        if 0 <= index < len(units):
            unit = units[index]
            if self._command_blocked(unit):
                return
            if unit.get("air_cargo"):
                self.map_screen.show_feedback("Release cargo before disbanding its carrier.")
                return
            unit_actions.apply_action(self.map_screen, unit["owner"], province, unit, {"type": "DISBAND", "turns_left": 1})
            self._mark_draft_changed()
            self.map_screen.show_feedback(f"Disbanding {queries.get_unit_display_name(unit.get('type'), self.unit_library)} (1 turn)")
            self.refresh_ui()

    def convert_unit(self, index, province=None):
        province = province or self.target_province
        # --- Prevent conversion during combat just in case ---
        player_country = self.map_screen.player_country
        in_combat = queries.is_nation_in_combat_here(player_country, province, self.map_screen.nation_data)
        if in_combat:
            self.map_screen.show_feedback("Cannot convert during combat!")
            return
        # -----------------------------------------------------

        units = province.get("units", [])
        if 0 <= index < len(units):
            unit = units[index]
            if self._command_blocked(unit):
                return
            u_type = unit.get("type", "")

            air_conversion = queries.air_conversion_order(unit, context=self.map_screen)
            if air_conversion:
                try:
                    air_conversion = queries.canonical_unit_order(
                        self.map_screen, unit["owner"], province, unit, air_conversion)
                except ValueError as exc:
                    self.map_screen.show_feedback(str(exc))
                    return
                target_type, turns = air_conversion["to"], air_conversion["turns_left"]
            elif u_type.startswith("Convoy"):
                target_type = "Land Unit"
                turns = 1
            elif (conversion := queries.truck_ship_conversion_order(unit, self.map_screen.scenario_settings, context=self.map_screen)):
                try:
                    conversion = queries.canonical_unit_order(
                        self.map_screen, unit["owner"], province, unit, conversion)
                except ValueError as exc:
                    self.map_screen.show_feedback(str(exc))
                    return
                target_type, turns = conversion["to"], conversion["turns_left"]
            else:
                target_type = "Convoy"
                turns = 1

            unit_actions.apply_action(self.map_screen, unit["owner"], province, unit, {"type": "CONVERT", "turns_left": turns, "to": target_type})

            self._mark_draft_changed()
            self.map_screen.show_feedback(f"Converting to {target_type} ({turns} turns)")
            self.refresh_ui()

    def open_air_mission_select(self, index, province, row_key=None):
        units = province.get("units", [])
        if not 0 <= index < len(units):
            return
        unit = units[index]
        if self._command_blocked(unit) or not queries.is_air_unit(unit, context=self.map_screen):
            return
        if self._open_loaded_transport_menu(unit, province):
            return
        enabled_missions = queries.available_air_missions(self.map_screen, unit, province)
        popup = _AirMissionSelectScreen(self, AIR_MISSION_CHOICES,
            lambda mission: self.set_air_mission(unit, province, mission, row_key),
            enabled_missions=enabled_missions)
        screen_runner._run_pygame_sub_screen(self.map_screen, popup)

    def _air_mission_unit_index(self, unit, province, unit_indexes=None):
        # The selector may outlive a snapshot, a country switch, or a unit's
        # current form. Recheck its live identity and permissions on selection.
        if self.map_screen.id_to_province.get(province["id"]) is not province:
            return None
        index = (unit_indexes.get(id(unit)) if unit_indexes is not None else
                 next((i for i, current in enumerate(province.get("units", [])) if current is unit), None))
        if index is None or not queries.is_air_unit(unit, context=self.map_screen) or self._command_blocked_silent(unit):
            return None
        return index

    def _air_mission_order(self, unit, province, mission):
        if mission == "NONE":
            return {"type": "MOVE", "path": []}
        if mission not in queries.AIR_INTERCEPTION_PRIORITIES:
            raise ValueError("Choose No mission or a Defend area priority.")
        order = {"type": "AIR_PATROL", "priority": mission}
        return queries.canonical_air_order(self.map_screen, unit, province, order)

    def set_air_mission(self, unit, province, mission, row_key=None):
        index = self._air_mission_unit_index(unit, province)
        if index is None or mission not in AIR_MISSION_ICONS:
            return
        if mission == "TRANSPORT":
            self.open_air_transport(unit, province)
            return
        if mission in queries.AIR_TARGET_MISSION_TYPES:
            self.start_air_targeting([(unit, province)], mission, row_key)
            return
        try:
            order = self._air_mission_order(unit, province, mission)
        except ValueError as exc:
            self.map_screen.show_feedback(str(exc))
            return
        unit_actions.apply_action(self.map_screen, unit["owner"], province, unit, order)
        self.cancel_bombard_targeting(refresh=False)
        self._mark_draft_changed()
        self.refresh_ui()

    def open_air_transport(self, plane, province):
        if (self._air_mission_unit_index(plane, province) is None
                or "TRANSPORT" not in queries.available_air_missions(self.map_screen, plane, province)):
            return
        queries.ensure_unit_ids(self.map_screen.map_data)
        capacity = queries.air_transport_capacity(plane, context=self.map_screen)

        def picker_items():
            cargo = plane.get("air_cargo", [])
            items = [(f"Release: {unit.get('custom_name') or queries.get_unit_display_name(unit['type'], context=self.map_screen)}", ("RELEASE", unit["unit_id"]))
                     for unit in cargo]
            items.extend((f"Load: {unit.get('custom_name') or queries.get_unit_display_name(unit['type'], context=self.map_screen)}", ("LOAD", unit["unit_id"]))
                         for unit in province.get("units", []) if queries.air_cargo_is_eligible(plane, unit, context=self.map_screen)
                         and not self._command_blocked_silent(unit))
            if queries.air_unit_can_air_drop(plane, context=self.map_screen):
                items.append(("Air Drop (select enemy land)", ("AIR_DROP", None)))
            return items

        popup = None

        def select_cargo(choice):
            if choice[0] == "AIR_DROP":
                self.start_air_targeting([(plane, province)], "AIR_DROP")
                popup.exit_screen()
                return
            if self.change_air_transport(plane, province, *choice):
                popup.prompt = (f"Cargo: {len(plane.get('air_cargo', []))} / {capacity}. "
                                "Choose a unit to load or release.")
                popup.set_items(picker_items())

        popup = ListSelectScreen(self.map_screen, "Air transport",
            f"Cargo: {len(plane.get('air_cargo', []))} / {capacity}. Choose a unit to load or release.",
            picker_items(), select_cargo,
            is_enabled=lambda item: item[1][0] != "LOAD" or len(plane.get('air_cargo', [])) < capacity,
            close_on_select=False)
        screen_runner._run_pygame_sub_screen(self.map_screen, popup)

    def change_air_transport(self, plane, province, action, unit_id):
        if self._air_mission_unit_index(plane, province) is None:
            return False
        cargo_ids = [unit["unit_id"] for unit in plane.get("air_cargo", [])]
        if action == "RELEASE" and unit_id in cargo_ids:
            cargo_ids.remove(unit_id)
        elif action == "LOAD" and unit_id not in cargo_ids:
            unit = next((u for u in province.get("units", []) if u.get("unit_id") == unit_id), None)
            if unit is None or self._command_blocked_silent(unit):
                return
            cargo_ids.append(unit_id)
        else:
            return False
        try:
            queries.set_air_cargo(self.map_screen, self.map_screen.player_country, plane, province, cargo_ids)
        except ValueError as exc:
            self.map_screen.show_feedback(str(exc))
            return False
        self.cancel_bombard_targeting(refresh=False)
        self._mark_draft_changed()
        self.refresh_ui()
        return True

    def start_air_targeting(self, records, mission, row_key=None):
        records = [(unit, base) for unit, base in records
                   if self._air_mission_unit_index(unit, base) is not None
                   and mission in queries.available_air_missions(self.map_screen, unit, base)]
        if not records:
            self.map_screen.show_feedback("No selected aircraft can perform that mission now.")
            return
        self.cancel_bombard_targeting(refresh=False)
        self._air_target_records = records
        self._air_target_mission = mission
        self.bombarding_unit_index = "GROUP_AIR" if row_key is None else row_key
        self.targeting_label = {"MOVE": "movement", "STRIKE": "strike", "AIR_DROP": "air drop"}[mission]
        self.map_screen.show_feedback(
            f"Select a {self.targeting_label} target. Existing orders stay until a valid target is chosen. Esc cancels targeting.")
        self.refresh_ui()

    def set_air_target(self, destination):
        """Validate the captured selection before replacing any aircraft orders."""
        if not self._air_target_records:
            return
        planned = []
        for unit, base in self._air_target_records:
            if self._air_mission_unit_index(unit, base) is None:
                self.map_screen.show_feedback("The aircraft selection changed. Select the mission again.")
                self.cancel_bombard_targeting()
                return
            try:
                order = queries.air_move_order(self.map_screen, unit, base, destination,
                                               mission=self._air_target_mission)
            except ValueError as exc:
                self.map_screen.show_feedback(str(exc))
                return
            planned.append((unit, base, order))
        for unit, base, order in planned:
            unit_actions.apply_action(self.map_screen, unit["owner"], base, unit, order)
        self.cancel_bombard_targeting(refresh=False)
        self._finish_batch_command("Air mission", len(planned))

    def cancel_unit_order(self, index, province=None):
        province = province or self.target_province
        units = province.get("units", [])
        if 0 <= index < len(units):
            if self._command_blocked(units[index]):
                return
            if any(unit is units[index] for unit, _base in self._air_target_records):
                self.cancel_bombard_targeting(refresh=False)
            if "order" in units[index]:
                unit_actions.cancel_action(self.map_screen, units[index]["owner"], province, units[index])
                self._mark_draft_changed()
                self.map_screen.show_feedback("Order Cancelled")
                self.refresh_ui()

    def clear_all_orders(self):
        selected_records = self.map_screen.selected_unit_records()
        # Orders normally clears exactly the units displayed in its roster.
        # Retain the province fallback for a read-only inspection opened by an
        # older caller that has no map selection.
        units = ([unit for unit, _province in selected_records]
                 if selected_records else self.target_province.get("units", []))
        cleared_any = False
        cancelled_targeting = self.bombarding_unit_index is not None
        self.cancel_bombard_targeting(refresh=False)

        for unit in units:
            if unit.get("owner") == self.map_screen.player_country and not self._command_blocked_silent(unit):
                if "order" in unit:
                    province = next(province for province in self.map_screen.map_data.values()
                                    if any(current is unit for current in province.get("units", [])))
                    unit_actions.cancel_action(self.map_screen, unit["owner"], province, unit)
                    cleared_any = True

        if cleared_any:
            self._mark_draft_changed()
            self.map_screen.show_feedback("All orders cleared")
        if cleared_any or cancelled_targeting:
            self.refresh_ui()

    def handle_back_key(self):
        # Inline editing and bombardment targeting each consume Escape before
        # it is allowed to close the whole panel.
        if self.map_screen and army_panel.handle_back_key(self.map_screen):
            return
        if self.renaming_unit_index is not None:
            self.renaming_unit_index = None
            self.renaming_unit_province = None
            self.renaming_unit_actual_index = None
            self.refresh_ui()
        elif self.bombarding_unit_index is not None:
            self.cancel_bombard_targeting()
        else:
            self.exit_screen()

    def handle_events(self, events):
        for event in events:
            # Battle is a child pane, not a modal stacked over Orders. Route
            # events in its rectangle first so its lane rows and scrollbars
            # remain interactive while the left Orders panel stays live.
            if self.battle_screen is not None and event.type in (
                    pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP,
                    pygame.MOUSEMOTION, pygame.MOUSEWHEEL):
                event_pos = getattr(event, "pos", pygame.mouse.get_pos())
                if self.battle_screen.panel_rect.collidepoint(event_pos):
                    self.battle_screen.handle_events([event])
                    continue

            if army_panel.handle_event(self.map_screen, event, orders_screen=self):
                continue

            # A right-click on a visible roster row toggles only that unit's
            # membership in the map-wide selection. Right-clicks elsewhere
            # retain their normal map movement-order behavior.
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 3:
                row_hitbox = next((element for element in self.elements
                                   if isinstance(element, _OrdersRowHitbox)
                                   and element.secondary_callback is not None
                                   and element.visible
                                   and element.rect.collidepoint(event.pos)), None)
                if row_hitbox is not None:
                    if (row_hitbox.click_guard is None
                            or row_hitbox.click_guard()):
                        row_hitbox.secondary_callback()
                    continue

            if event.type == pygame.KEYDOWN and self.renaming_unit_index is not None:
                if event.key == pygame.K_RETURN:
                    self.save_unit_name(self.renaming_unit_actual_index,
                                        self.renaming_unit_province)
                elif event.key == resolve_keybind(self, "BACK", pygame.K_ESCAPE):
                    self.renaming_unit_index = None
                    self.renaming_unit_province = None
                    self.renaming_unit_actual_index = None
                    self.refresh_ui()
                else:
                    self.rename_text, _ = process_text_input(event, self.rename_text, max_length=c.UNIT_NAME_MAX_LENGTH)
                return

            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                # Guarded to the visible panel so a cancel box scrolled behind
                # the panel's edge (clipped, no longer drawn) can't fire.
                panel_rect = getattr(self, 'scroll_content_rect', None)
                if panel_rect is None or panel_rect.collidepoint(event.pos):
                    for rect, idx, province in self.cancel_rects:
                        if rect.collidepoint(event.pos):
                            self.cancel_unit_order(idx, province)
                            return

            # --- Scrollbar click/drag (grab the handle or jump via the track),
            # or grab the panel's own content and drag it directly ---
            if event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP) and event.button == 1:
                if self.handle_list_scroll(event, attr="scroll_y", limit_attr="max_scroll_y",
                                           content_rect_attr="scroll_content_rect"):
                    return

            # --- Handle Mousewheel Scrolling ---
            if event.type == pygame.MOUSEWHEEL:
                # The header stays fixed; only the roster viewport takes the wheel.
                if self.scroll_content_rect.collidepoint(pygame.mouse.get_pos()):
                    self.scroll_by(event, attr="scroll_y", limit_attr="max_scroll_y",
                                   speed=WHEEL_SCROLL_STEP)

            # GameState dispatches additional_events after the widgets. Doing
            # it again can overwrite a mission with movement on the same click.
            super().handle_events([event])

    def additional_events(self, event):
        map_input.resolve_map_mouse_gesture_conflict(self.map_screen, event)
        if self.map_screen._ignore_left_until_release:
            if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                self.map_screen._ignore_left_until_release = False
                return
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                return
        if self.map_screen._ignore_right_until_release:
            if event.type == pygame.MOUSEBUTTONUP and event.button == 3:
                self.map_screen._ignore_right_until_release = False
                return
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 3:
                return

        # Dragging the scrollbar handle (or the panel's own content) takes
        # priority over camera panning/hover.
        if event.type == pygame.MOUSEMOTION and (getattr(self, "is_dragging_scrollbar", False)
                                                  or self.is_content_dragging("scroll_y")):
            self.handle_list_scroll(event, attr="scroll_y", limit_attr="max_scroll_y",
                                    content_rect_attr="scroll_content_rect")
            return

        mx, my = pygame.mouse.get_pos()

        # The entire compact panel is UI, including its fixed header. Keeping
        # one rect for drawing, clipping and input prevents map clicks leaking
        # through a gap between the controls and roster.
        panel_rect = self.panel_rect
        event_pos = getattr(event, "pos", (mx, my))
        on_ui = (panel_rect.collidepoint(event_pos)
                 or map_input.map_ui_bar_at_position(self.map_screen, event_pos))

        # Exclude Orders turns a map-pan binding into main-map-only panning,
        # leaving that button free for the normal Orders move gesture.
        pan_buttons = map_input.mouse_buttons_for_map_panning(in_orders=True)
        # ``camera`` is optional only for lightweight Orders test doubles;
        # every playable map supplies it.
        camera = self.map_screen.camera
        if camera is not None and not (event.type == pygame.MOUSEWHEEL and on_ui):
            camera.handle_input(event, self.map_screen, on_ui, pan_buttons=pan_buttons)
            if (event.type == pygame.MOUSEBUTTONUP
                    and camera.finish_pan_drag(event.button)
                    and map_input.mouse_button_has_action(event.button, "issue_orders")):
                return

        if camera is not None and event.type in (
                pygame.MOUSEMOTION, pygame.MOUSEWHEEL, pygame.MOUSEBUTTONUP):
            self._refresh_air_range_hover(event_pos)

        # Targeting is a modal map action. It must run before the normal
        # left-click selection gesture below, otherwise every target click is
        # consumed as the start of a selection rectangle.
        if (event.type == pygame.MOUSEBUTTONDOWN and event.button == 1
                and self.bombarding_unit_index is not None):
            # A mouse press has a matching release. Consume both halves of
            # this modal click so the release cannot fall through to the
            # ordinary empty-map exit gesture after the target is assigned.
            self._consume_bombard_target_release = True
            self.map_screen.unit_selection_drag = None
            if not on_ui:
                dest = queries.get_clicked_province(event.pos, self.map_screen)
                if dest:
                    self.set_bombard_target(self.bombarding_unit_actual_index, dest,
                                            self.bombarding_unit_province)
            return

        if (event.type == pygame.MOUSEBUTTONUP and event.button == 1
                and self._consume_bombard_target_release):
            self._consume_bombard_target_release = False
            self.map_screen.unit_selection_drag = None
            return

        # An armed strike/barrage also accepts the configured order gesture.
        # Let the camera finish a pan first, then consume both press/release so
        # a right-click cannot fall through to full-range air repositioning.
        if (event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP)
                and self.bombarding_unit_index is not None
                and map_input.mouse_button_has_action(event.button, "issue_orders")):
            self.map_screen.unit_selection_drag = None
            if event.type == pygame.MOUSEBUTTONUP and not on_ui:
                destination = queries.get_clicked_province(event.pos, self.map_screen)
                if destination:
                    self.set_bombard_target(self.bombarding_unit_actual_index, destination,
                                            self.bombarding_unit_province)
            return

        # The Orders panel is a live map workspace. A short left-click on a
        # stack toggles it; an actual left-drag box-selects stacks, matching
        # the map screen and HOI4's primary selection gesture.
        if (event.type == pygame.MOUSEBUTTONDOWN and not on_ui
                and (map_input.mouse_button_has_action(event.button, "select_units")
                     or map_input.mouse_button_has_action(event.button, "box_select_units"))):
            clicked_stack = next((stack for stack in reversed(
                self.map_screen.unit_stack_hitboxes)
                if stack["rect"].collidepoint(event.pos)), None)
            # Defer an empty-space click too, so a selection rectangle can
            # begin anywhere on the live map workspace.
            self.map_screen.unit_selection_drag = {
                "start": event.pos, "current": event.pos,
                "additive": bool(pygame.key.get_mods() & pygame.KMOD_SHIFT),
                "stack": clicked_stack,
                "button": event.button,
                "select_units": map_input.mouse_button_has_action(
                    event.button, "select_units"),
                "box_select_units": map_input.mouse_button_has_action(
                    event.button, "box_select_units"),
            }
            return

        if event.type == pygame.MOUSEMOTION and self.map_screen.unit_selection_drag:
            self.map_screen.unit_selection_drag["current"] = event.pos
            return

        if (event.type == pygame.MOUSEBUTTONUP and self.map_screen.unit_selection_drag
                and event.button == self.map_screen.unit_selection_drag.get("button")):
            drag = self.map_screen.unit_selection_drag
            self.map_screen.unit_selection_drag = None
            if not drag:
                return
            rect = pygame.Rect(
                drag["start"],
                (event.pos[0] - drag["start"][0], event.pos[1] - drag["start"][1]))
            rect.normalize()
            if rect.width < 4 and rect.height < 4:
                if not drag["select_units"]:
                    return
                stack = drag["stack"]
                if stack is None:
                    # Outside an armed modal command, a short map click
                    # returns to the clicked province's menu. Do not let the
                    # ordinary Map view-mode navigation run here: this handoff
                    # is explicitly back to the province inspector.
                    if map_input._select_map_province(
                            self.map_screen, event.pos, navigate=False):
                        self.return_to_province_menu = True
                        self.entered_from_combat_bubble = False
                    self.exit_screen()
                    return
                if self.map_screen.click_select_map_units(
                        stack["units"], additive=drag["additive"]):
                    self.inspect_province(stack["province"])
                return
            if (rect.width >= 4 or rect.height >= 4) and drag["box_select_units"]:
                selected = []
                for stack in self.map_screen.unit_stack_hitboxes:
                    if rect.colliderect(stack["rect"]):
                        selected.extend(stack["units"])
                self.map_screen.select_map_units(selected, additive=drag["additive"])
                self.selected_unit_index = None
                target = self.target_province
                self.read_only = bool(target) and not any(
                    unit.get("owner") == self.map_screen.player_country
                    for unit in target.get("units", []))
                self.refresh_ui()
            return

        if (event.type == pygame.MOUSEBUTTONDOWN
                and map_input.mouse_button_has_action(event.button, "issue_orders")):
            return

        if (event.type == pygame.MOUSEBUTTONUP
                and map_input.mouse_button_has_action(event.button, "issue_orders")):
            if not on_ui and not self.read_only:
                destination = queries.get_clicked_province(event.pos, self.map_screen)
                if destination and self.map_screen.selected_unit_records():
                    if self.map_screen.issue_selected_move_orders(
                            destination,
                            append=bool(pygame.key.get_mods() & pygame.KMOD_SHIFT)):
                        self.refresh_ui()
            return

        # --- Dynamic Map Hover Update ---
        if event.type == pygame.MOUSEMOTION:
            self.map_screen.hovered_unit_stack = map_input._unit_stack_at(
                self.map_screen, event.pos)
            self.map_screen.hovered_province = (
                None if self.map_screen.hovered_unit_stack
                else queries.get_clicked_province(event.pos, self.map_screen))

            if self.map_screen.hovered_province:
                curr_id = self.map_screen.hovered_province["id"]
                if curr_id != self.map_screen.last_hovered_id:
                    self.map_screen.hover_glow_surf, self.map_screen.hover_glow_rect = map_utils.create_glow_surface(
                        self.map_screen.id_map, self.map_screen.hovered_province["map_color"]
                    )
                    self.map_screen.last_hovered_id = curr_id
            else:
                self.map_screen.last_hovered_id = None
                self.map_screen.hover_glow_surf = None

    def can_unit_enter(self, unit, dest):
        """Compatibility wrapper for callers of the former Orders-only rule.

        Map routing and real-time validation now share the canonical query;
        retaining this narrow wrapper keeps integrations such as volunteers
        from recreating the old local implementation.
        """
        order = unit.get("order", {})
        path = order.get("path", []) if isinstance(order, dict) else []
        current = self.map_screen.id_to_province.get(path[-1]) if path else self.target_province
        return queries.can_unit_move_step(unit, current, dest, self.map_screen.nation_data, context=self.map_screen)

    def _order_summary(self, unit_index, unit):
        """Short status text and color for a compact roster row."""
        if queries.unit_is_air_drop_recovering(unit):
            return f"{queries.air_drop_recovery_turns(unit)}t recovery", c.UI_TEXT_MUTED
        if self.bombarding_unit_index == unit_index:
            return f"Choose {self.targeting_label} target", BOMBARD_TARGET_COLOR

        order = unit.get("order", {})
        if not self._has_active_order(order):
            return "Ready", c.UI_TEXT_MUTED

        path = order.get("path", [])
        if path:
            step_word = "step" if len(path) == 1 else "steps"
            return f"Move: {len(path)} {step_word} to P{path[-1]}", (255, 225, 80)

        order_type = order.get("type", "")
        turns = order.get("turns_left")
        turn_suffix = f" | {turns}t" if turns is not None else ""
        if order_type == "MOVE":
            # An empty MOVE is the engine's normal idle placeholder, not an
            # order waiting for a destination.  _has_active_order filters it,
            # but keep this fallback neutral for malformed legacy data.
            return "Ready", c.UI_TEXT_MUTED
        if order_type == "BOMBARD":
            return f"Bombard: P{order.get('target_id', '?')}", BOMBARD_TARGET_COLOR
        if order_type in queries.AIR_ORDER_TYPES:
            radius = queries.air_order_radius(unit, order_type)
            target_labels = {"AIR_ATTACK": "Strike", "AIR_REPOSITION": "Reposition", "AIR_DROP": "Air Drop"}
            label = (f"Defend area: {order.get('priority', queries.AIR_DEFAULT_PRIORITY).lower()} first"
                     if order_type == "AIR_PATROL" else
                     f"{target_labels[order_type]}: P{order.get('target_id', '?')}")
            return f"{label} | {radius:g}px", BOMBARD_TARGET_COLOR
        if order_type == "CONVERT":
            return f"Convert to {order.get('to', '?')}{turn_suffix}", (100, 180, 255)
        if order_type == "UPGRADE":
            return f"Upgrade to {queries.get_unit_display_name(order.get('target_type', '?'))}{turn_suffix}", (255, 170, 70)
        if order_type == "REPAIR":
            return f"Repairing{turn_suffix}", (100, 255, 120)
        if order_type == "DISBAND":
            return f"Disbanding{turn_suffix}", (255, 100, 100)
        if order_type:
            return order_type.title(), c.UI_TEXT_LIGHT
        return "Order queued", c.UI_TEXT_LIGHT

    @staticmethod
    def _has_active_order(order):
        """Whether an order warrants status color and an individual cancel X.

        Movement resolution retains an empty MOVE dictionary as an idle
        placeholder.  It has no destination or effect, so it must look and
        behave exactly like a unit with no order at all.
        """
        if not isinstance(order, dict) or not order:
            return False
        return order.get("type") != "MOVE" or bool(order.get("path"))

    @classmethod
    def _header_help_lines(cls, help_text, font):
        """Wrap header guidance without letting it intrude into the roster."""
        return wrap_text(
            help_text, font, cls.PANEL_WIDTH - (PANEL_INSET * 2),
            max_lines=HEADER_HELP_MAX_LINES, ellipsis=c.ELLIPSIS)

    def _draw_unit_row(self, surface, row_key, unit, province, unit_index, row_y, display_index,
                       owner_color, small_font, tiny_font, show_actions):
        """Draws one 40px roster row underneath its transparent hitbox/icons."""
        row_rect = pygame.Rect(
            self.PANEL_X + UNIT_ROW_X_OFFSET, row_y,
            self.PANEL_WIDTH - SCROLLBAR_WIDTH - UNIT_ROW_X_OFFSET - 2,
            self.row_height)
        is_own = unit.get("owner") == self.map_screen.player_country
        selectable = is_own and not self._command_blocked_silent(unit)
        selected = selectable and self.map_screen.is_unit_selected(unit)

        if selected:
            row_color = (45, 68, 68)
        elif display_index % 2:
            row_color = (37, 40, 46)
        else:
            row_color = (29, 32, 38)
        pygame.draw.rect(surface, row_color, row_rect)
        pygame.draw.rect(surface,
                         c.COLOR_GOLD_HIGHLIGHT if selected else (62, 66, 74),
                         row_rect, 1)

        row_owner_color = self.map_screen.nation_colors.get(
            queries.get_unit_combat_owner(unit), owner_color)
        strip_color = row_owner_color if selected else tuple(max(35, channel // 2)
                                                              for channel in row_owner_color)
        pygame.draw.rect(surface, strip_color,
                         (row_rect.x, row_rect.y, 4, row_rect.height))

        icon_box = pygame.Rect(
            self.PANEL_X + UNIT_ICON_OFFSET_X, row_y + UNIT_ICON_OFFSET_Y,
            32, 32)
        pygame.draw.rect(surface, (20, 22, 26), icon_box)
        pygame.draw.rect(surface, (90, 95, 105), icon_box, 1)
        icon = self.unit_row_icons.get(row_key)
        if icon:
            surface.blit(icon, icon.get_rect(center=icon_box.center))

        name_x = self.PANEL_X + UNIT_NAME_OFFSET_X
        action_x = self.PANEL_X + ACTION_START_OFFSET_X
        text_width = action_x - name_x - 7

        if self.renaming_unit_index == row_key:
            box_rect = pygame.Rect(
                self.PANEL_X + RENAME_BOX_OFFSET_X,
                row_y + RENAME_BOX_OFFSET_Y,
                *RENAME_BOX_SIZE)
            draw_text_box(surface, box_rect, self.rename_text, active=True,
                          font=tiny_font, pad_x=5)
        else:
            name_color = (245, 245, 245) if selectable else c.UI_TEXT_MUTED
            name = fit_text(
                unit.get("custom_name") or queries.get_unit_display_name(unit.get("type", "Unit"), self.unit_library),
                small_font, text_width)
            name_surf = small_font.render(name, True, name_color)
            surface.blit(name_surf,
                         (name_x, row_y + UNIT_NAME_OFFSET_Y))

            try:
                hp = float(unit.get("health", 0))
                max_hp = max(1.0, float(unit.get("max_health", 1)))
            except (TypeError, ValueError):
                hp, max_hp = 0.0, 1.0
            hp_ratio = max(0.0, min(1.0, hp / max_hp))
            if is_own:
                # A foreign unit's order (where it's headed, what it's doing)
                # is never shown -- that would leak private intel the player
                # has no business seeing. Its owner is fair game, same as the
                # map/sidebar already reveal.
                summary, summary_color = self._row_order_summaries[row_key]
            else:
                owner_id = unit.get("owner", "Unknown")
                summary = queries.get_country_display_name(owner_id, self.map_screen.nation_data)
                summary_color = c.UI_TEXT_MUTED
            volunteer_note = (" | Volunteer: " + queries.get_country_display_name(
                                  unit["volunteer_host"], self.map_screen.nation_data)
                              if unit.get("volunteer_host") else "")
            location = f"P{province['id']} | "
            status = fit_text(f"{location}HP {int(hp_ratio * 100)}% | {summary}{volunteer_note}",
                              tiny_font, text_width)
            surface.blit(tiny_font.render(status, True, summary_color),
                         (name_x, row_y + UNIT_STATUS_OFFSET_Y))

            bar_rect = pygame.Rect(name_x, row_y + UNIT_HEALTH_BAR_OFFSET_Y,
                                   text_width, UNIT_HEALTH_BAR_HEIGHT)
            pygame.draw.rect(surface, (65, 25, 25), bar_rect)
            if hp_ratio > 0:
                if hp_ratio > 0.6:
                    health_color = (50, 175, 70)
                elif hp_ratio > 0.3:
                    health_color = (205, 155, 40)
                else:
                    health_color = (195, 55, 45)
                fill_rect = bar_rect.copy()
                fill_rect.width = max(1, int(bar_rect.width * hp_ratio))
                pygame.draw.rect(surface, health_color, fill_rect)

        order = unit.get("order")
        has_order = self._has_active_order(order)
        if (show_actions and is_own and has_order
                and not self._command_blocked_silent(unit)):
            cancel_x = (self.PANEL_X + ACTION_START_OFFSET_X
                        + (6 * ACTION_BUTTON_STEP_X) + CANCEL_BOX_GAP_X)
            cancel_rect = pygame.Rect(cancel_x, row_y + CANCEL_BOX_OFFSET_Y,
                                      CANCEL_BOX_SIZE, CANCEL_BOX_SIZE)
            pygame.draw.rect(surface, (145, 25, 25), cancel_rect)
            pygame.draw.rect(surface, (230, 120, 120), cancel_rect, 1)
            x_label = tiny_font.render("X", True, (255, 255, 255))
            surface.blit(x_label, x_label.get_rect(center=cancel_rect.center))
            self.cancel_rects.append((cancel_rect, unit_index, province))

    def _draw_panel_header(self, surface, rows, player_units, read_only):
        title_font = fonts.get("heading2")
        tiny_font = fonts.get("tiny")
        title = fit_text(self._panel_title_text,
                         title_font, self.PANEL_WIDTH - 62)
        surface.blit(title_font.render(title, True, (255, 255, 255)),
                     (self.PANEL_X + PANEL_INSET,
                      PANEL_Y + HEADER_TITLE_OFFSET_Y))

        if read_only:
            meta = "READ ONLY | NO COMMANDABLE UNITS SELECTED"
        else:
            selected_count = len(self._selected_display_records)
            meta = f"{selected_count} SELECTED"
        surface.blit(tiny_font.render(meta, True, c.UI_TEXT_LIGHT),
                     (self.PANEL_X + PANEL_INSET,
                      PANEL_Y + HEADER_META_OFFSET_Y))

        mouse_pos = pygame.mouse.get_pos()
        help_text = None
        if self.scroll_content_rect.collidepoint(mouse_pos):
            for button in self.action_buttons:
                if button.visible and button.rect.collidepoint(mouse_pos):
                    help_text = button.help_text
                    break

        if help_text is None:
            if self.renaming_unit_index is not None:
                help_text = "Type a name | Enter saves | Esc cancels"
            elif self.bombarding_unit_index is not None:
                help_text = (f"Click a province to set the {self.targeting_label} target | Esc cancels targeting"
                    if self._air_target_records else "Click a highlighted province to set the bombardment target")
            elif read_only:
                help_text = "Intelligence view: orders cannot be changed here"
            elif not player_units:
                help_text = "Click a unit stack, or left-drag a box around stacks to select units"
            elif len(player_units) > 1:
                help_text = "Right-click a province to move selected units. Shift+right-click queues a waypoint."
            else:
                help_text = "Right-click the map to move | click the row to deselect | hover a command icon for details"

        help_lines = self._header_help_lines(help_text, tiny_font)
        help_y = PANEL_Y + HEADER_HELP_OFFSET_Y
        for line in help_lines:
            surface.blit(tiny_font.render(line, True, c.UI_TEXT_MUTED),
                         (self.PANEL_X + PANEL_INSET, help_y))
            help_y += tiny_font.get_height() + HEADER_HELP_LINE_GAP

        pygame.draw.line(surface, (80, 85, 95),
                         (self.PANEL_X + 1, self.panel_top - 1),
                         (self.panel_rect.right - 1, self.panel_top - 1), 1)

    def draw_target_markers(self, surface, origin_node, prov_ids, color):
        """Rings every tile the player is currently allowed to click (move steps or bombard targets)."""
        for p_id in prov_ids:
            prov = self.map_screen.id_to_province.get(p_id)
            if not prov:
                continue

            cx, cy = list(prov["center"])

            # Account for map wrap to get the shortest distance
            if self.map_screen.loop_map:
                world_dx = cx - origin_node["center"][0]
                if world_dx > self.map_screen.map_w / 2:
                    cx -= self.map_screen.map_w
                elif world_dx < -self.map_screen.map_w / 2:
                    cx += self.map_screen.map_w

            # Loop the pathmaking circles so they draw on the seam
            offsets = [0, -self.map_screen.map_w, self.map_screen.map_w] if self.map_screen.loop_map else [0]
            for offset in offsets:
                sx, sy = queries.world_to_screen([cx, cy], self.map_screen, offset)

                if 0 <= sx <= c.SCREEN_WIDTH and 0 <= sy <= c.SCREEN_HEIGHT:
                    pygame.draw.circle(surface, color, (int(sx), int(sy)), TARGET_MARKER_RADIUS, TARGET_MARKER_THICKNESS)

    def draw_air_range(self, surface, base, radius, color):
        """Draw one range boundary onto the shared aircraft overlay.

        Tilt changes the displayed shape, never gameplay reach. Clip to each
        map copy so the outline cannot imply flight across the wrapping seam.
        Close clipped arcs along map edges: on small maps the circle itself
        can lie entirely outside the image even though the whole map is covered.
        """
        map_ref = self.map_screen
        camera = map_ref.camera
        previous_clip = surface.get_clip()
        radius_x = radius * camera.zoom
        radius_y = radius_x * camera.tilt_factor
        offsets = (0, -map_ref.map_w, map_ref.map_w) if map_ref.loop_map else (0,)
        cx, cy = base["center"]
        edges = []
        for x in (0, map_ref.map_w):
            remaining = radius * radius - (x - cx) ** 2
            if remaining >= 0:
                span = sqrt(remaining)
                low, high = max(0, cy - span), min(map_ref.map_h, cy + span)
                if low <= high:
                    edges.append(((x, low), (x, high)))
        for y in (0, map_ref.map_h):
            remaining = radius * radius - (y - cy) ** 2
            if remaining >= 0:
                span = sqrt(remaining)
                low, high = max(0, cx - span), min(map_ref.map_w, cx + span)
                if low <= high:
                    edges.append(((low, y), (high, y)))
        for offset in offsets:
            sx, sy = queries.world_to_screen(base["center"], map_ref, offset)
            rect = pygame.Rect(round(sx - radius_x), round(sy - radius_y),
                               max(1, round(2 * radius_x)), max(1, round(2 * radius_y)))
            left, top = queries.world_to_screen((0, 0), map_ref, offset)
            right, bottom = queries.world_to_screen((map_ref.map_w, map_ref.map_h), map_ref, offset)
            map_rect = pygame.Rect(round(left), round(top), round(right - left), round(bottom - top))
            clip = previous_clip.clip(map_rect).clip(pygame.Rect(
                0, map_ref.top_ui_height, surface.get_width(), surface.get_height() - map_ref.total_ui_h))
            if rect.colliderect(clip):
                surface.set_clip(clip)
                pygame.draw.ellipse(surface, color, rect, AIR_RANGE_THICKNESS)
                for start, end in edges:
                    # The bottom/right world edges fall just outside pygame's
                    # exclusive Rect bounds; keep their strokes inside the image.
                    points = []
                    for point in (start, end):
                        x, y = queries.world_to_screen(point, map_ref, offset)
                        points.append((max(map_rect.left, min(map_rect.right - 1, round(x))),
                                       max(map_rect.top, min(map_rect.bottom - 1, round(y)))))
                    pygame.draw.line(surface, color, *points, AIR_RANGE_THICKNESS)
        surface.set_clip(previous_clip)

    def _draw_cached_air_ranges(self, surface):
        """Cache all selected ranges in one reusable viewport surface."""
        if not self._air_range_preview_key:
            return
        map_ref = self.map_screen
        camera = map_ref.camera
        clip = surface.get_clip()
        key = (self._air_range_preview_key, camera.zoom, camera.tilt_factor,
               tuple(camera.pos), map_ref.map_w, map_ref.map_h, map_ref.loop_map,
               map_ref.top_ui_height, map_ref.total_ui_h, surface.get_size(), tuple(clip))
        if key != self._air_range_layer_key:
            layer = self._air_range_layer
            if layer is None or layer.get_size() != surface.get_size():
                layer = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
                self._air_range_layer = layer
            else:
                layer.set_clip(None)
                layer.fill((0, 0, 0, 0))
            layer.set_clip(clip)
            # Separate range bitmaps require a viewport-sized scan, copy, and
            # alpha blit per base. Draw every outline into this one layer instead.
            for base, radius in self.air_range_previews:
                self.draw_air_range(layer, base, radius, MOVE_TARGET_COLOR)
            for base, radius in self.air_strike_range_previews:
                self.draw_air_range(layer, base, radius, BOMBARD_TARGET_COLOR)
            self._air_range_layer_key = key
        surface.blit(self._air_range_layer, (0, 0))

    def draw_range_previews(self, surface):
        aiming_province = self.bombarding_unit_province or self.target_province
        focused_units = aiming_province.get("units", [])
        aiming_index = self.bombarding_unit_actual_index
        targeting = (self.bombarding_unit_index is not None and isinstance(aiming_index, int)
                     and 0 <= aiming_index < len(focused_units))
        self._draw_cached_air_ranges(surface)
        if not targeting or self._air_target_records:
            return
        self.draw_target_markers(surface, aiming_province, self.bombard_target_preview, BOMBARD_TARGET_COLOR)
        hovered = queries.get_clicked_province(pygame.mouse.get_pos(), self.map_screen)
        if hovered and hovered["id"] in self.bombard_target_preview:
            bomb_range = queries.get_bombardment_range(focused_units[aiming_index].get("type", ""), context=self.map_screen)
            overlay_renderer.draw_bombardment_arrow(surface, self.map_screen, aiming_province,
                hovered["id"], bomb_range, alpha=BOMBARD_PREVIEW_ALPHA, force_visible=True)

    def draw_background(self, surface):
        # Defer to Map_Screen's own background (flat fill or checkerboard,
        # per the Settings toggle, tinted to the live zoom-based ocean color)
        # instead of the generic always-on checkerboard every other screen
        # without a bg_image_path gets -- Orders is just the map plus a panel.
        if self.map_screen:
            self.map_screen.draw_background(surface)
        else:
            super().draw_background(surface)

    def additional_draw(self, surface):
        if not self.map_screen or not self.target_province:
            return

        # Orders owns the top-left command panel, so the map's large nation
        # flag is intentionally suppressed for this embedded draw only. The
        # independent flag guard leaves the country/date text behavior alone.
        previous_hide_flag = self.map_screen.hide_flag
        self.map_screen.hide_flag = True
        try:
            self.map_screen.draw_clean_map_background(surface)
        finally:
            self.map_screen.hide_flag = previous_hide_flag

        # Range outlines sit on the map below the command-panel controls.
        self.draw_range_previews(surface)

        # Do not draw the province inspector here.  Orders is deliberately a
        # free-roaming map workspace; the left panel is driven by the current
        # unit selection rather than whichever province happened to be opened.

        self.cancel_rects = []
        small_font = fonts.get("small")
        tiny_font = fonts.get("tiny")

        read_only = self.read_only
        owner_color = self.map_screen.nation_colors.get(self.map_screen.player_country, (255, 255, 0))
        rows = self._roster_rows
        player_units = [unit for _key, unit, _province, _index in rows
                        if self.map_screen.is_unit_selected(unit)]

        # Force every selected unit's own path through fog-of-war before the
        # opaque roster is painted.  Each path begins at its own province and
        # keeps its own speed, even when the group spans the map.
        for _key, unit, origin, _index in rows:
            if not self.map_screen.is_unit_selected(unit):
                continue
            order = unit.get("order", {})
            if not isinstance(order, dict):
                continue
            path = order.get("path", [])
            if path:
                overlay_renderer.draw_split_movement_path(
                    surface, self.map_screen, origin, path,
                    unit.get("speed", 1), owner_color, force_visible=True)
            elif order.get("type") == "BOMBARD":
                target_id = order.get("target_id")
                bomb_range = queries.get_bombardment_range(unit.get("type", ""), context=self.map_screen)
                overlay_renderer.draw_bombardment_arrow(
                    surface, self.map_screen, origin, target_id,
                    bomb_range, force_visible=True)
            elif order.get("type") in queries.AIR_TARGET_MISSION_TYPES.values():
                overlay_renderer.draw_split_movement_path(surface, self.map_screen, origin,
                    [order["target_id"]], 1, owner_color, force_visible=True)

        ui_bars.draw_translucent_panel(
            surface, self.panel_rect, (*PANEL_BG_COLOR, self.PANEL_TRANSPARENCY),
            border_color=PANEL_BORDER_COLOR, radius=3)
        self._draw_panel_header(surface, rows, player_units, read_only)

        content_rect = getattr(self, 'scroll_content_rect', None) or pygame.Rect(
            self.PANEL_X + 2, self.panel_top,
            self.PANEL_WIDTH - SCROLLBAR_WIDTH - 2, self.panel_max_h)

        # One roster, always: selected units appear alongside any unselected
        # peers in their persistent armies. Every commandable row can be
        # clicked to change selection, but only selected rows receive command
        # controls on their right.
        with ui_bars.clip_scroll_region(surface, content_rect,
                                        draw_top=self.scroll_y != 0, draw_bottom=self.scroll_y > self.max_scroll_y):
            if not rows:
                empty_text = "(No units selected)"
                surface.blit(tiny_font.render(empty_text, True, c.UI_TEXT_MUTED),
                             (self.PANEL_X + PANEL_INSET, self.panel_top + self.scroll_y))
            else:
                for display_index, (row_key, unit, province, unit_index) in enumerate(rows):
                    y_pos = self.panel_top + (display_index * self.row_height) + self.scroll_y
                    row_rect = pygame.Rect(
                        self.PANEL_X + UNIT_ROW_X_OFFSET, y_pos,
                        self.PANEL_WIDTH - SCROLLBAR_WIDTH - UNIT_ROW_X_OFFSET - 2,
                        self.row_height)
                    if row_rect.colliderect(content_rect):
                        self._draw_unit_row(
                            surface, row_key, unit, province, unit_index, y_pos, display_index,
                            owner_color, small_font, tiny_font,
                            self.map_screen.is_unit_selected(unit))

        self.draw_list_scrollbar(
            surface, self.panel_rect.right - SCROLLBAR_WIDTH, self.panel_top,
            self.panel_max_h, width=SCROLLBAR_WIDTH, limit_attr="max_scroll_y")

        # Show the same live left-drag rectangle as the map screen.  The
        # rectangle must be normalized in-place; pygame returns None from
        # Rect.normalize().
        if self.map_screen.unit_selection_drag:
            drag = self.map_screen.unit_selection_drag
            rect = pygame.Rect(
                drag["start"],
                (drag["current"][0] - drag["start"][0],
                 drag["current"][1] - drag["start"][1]))
            rect.normalize()
            pygame.draw.rect(surface, (220, 210, 80), rect, 2)

        resource_hud.draw_resource_bar(surface, self.map_screen,
                                       start_x=view_mode_buttons.RESOURCE_BAR_OFFSET_X)
        army_panel.draw(self.map_screen, surface, orders_screen=self,
                        draw_editors=False, selected_ids=self._selected_display_ids)

        if self.battle_screen is not None:
            self.battle_screen.draw_embedded(surface)

    def _current_presentation_state(self):
        """Track map state boundaries, including authoritative multiplayer snapshots."""
        map_ref = self.map_screen
        # Lightweight UI test maps can omit the map's cache revision and selection IDs.
        state = (map_ref._presentation_cache_revision,
                 map_ref.player_country, map_ref.time_manager.total_turns,
                 map_ref.tactical_mode, frozenset(map_ref.selected_unit_ids))
        if map_ref.realtime_multiplayer:
            player = map_ref.realtime_session.players.get(map_ref.realtime_player_id)
            state += (map_ref.realtime_session.phase,
                      (player.submitted, player.eliminated) if player else None)
        return state

    def update(self):
        super().update()
        if (self.map_screen and self.target_province
                and self._presentation_state != self._current_presentation_state()):
            self.refresh_ui()
        if self.battle_screen is not None:
            if not queries.is_province_in_active_combat(
                    self.target_province, self.map_screen.nation_data):
                self.battle_screen = None
            else:
                self.battle_screen.update()
        # Ensure the camera keeps running its smooth zoom/pan lerp math
        # even when the Orders screen is the active state
        if self.map_screen:
            self.map_screen.camera.update(self.map_screen, c.SCREEN_HEIGHT)
            self._refresh_air_range_hover(pygame.mouse.get_pos())

    def draw(self, surface):
        """Draw army editing modals after Orders' button elements.

        GameState draws elements after ``additional_draw``.  The army tray is
        map content, but its editor is modal UI and must sit over the command
        buttons rather than behind them.
        """
        super().draw(surface)
        army_panel.draw_editors_over_map(self.map_screen, surface)
