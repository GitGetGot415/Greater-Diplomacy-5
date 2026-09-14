import pygame
import data.constants as c
from gameState import GameState, resolve_keybind
from ui_elements import Button, process_text_input, draw_text_box
from map_logic.rendering.font_manager import fonts
from data import queries
from ui.text_utils import fit_text
from map_logic.rendering import symbol_loader
from map_logic.rendering import overlay_renderer
from ui.bars import ui_bars, resource_hud, view_mode_buttons
from ui import event_handler
from map_logic.camera import camera_handler
from screens.map_related_screens import battle_screen

# ==========================================
# COMPACT ORDERS PANEL LAYOUT
# ==========================================

# The reference layout gets its density from a shallow command header and one
# narrow roster row per unit. Commands stay on their unit's row, so none of the
# existing per-unit semantics need to become ambiguous batch actions when
# Select All is active.
PANEL_Y = 5
PANEL_HEIGHT = c.SCREEN_HEIGHT - 70
PANEL_BOTTOM_INSET = 8
PANEL_INSET = 8
HEADER_TITLE_OFFSET_Y = 7
HEADER_META_OFFSET_Y = 36
TOP_BTN_ROW_OFFSET_Y = 57
HEADER_HELP_OFFSET_Y = 91
LIST_TOP_OFFSET_Y = 110

TOP_BTN_GAP_X = 6

BATTLE_PANEL_GAP = 8
BATTLE_PANEL_RIGHT_MARGIN = 8

UNIT_ROW_X_OFFSET = 4
UNIT_ICON_OFFSET_X = 7
UNIT_ICON_OFFSET_Y = 4
UNIT_NAME_OFFSET_X = 46
UNIT_NAME_OFFSET_Y = 1
UNIT_STATUS_OFFSET_Y = 20
UNIT_HEALTH_BAR_OFFSET_Y = 35
UNIT_HEALTH_BAR_HEIGHT = 3

# Six tightly packed icon commands: convert, disband, repair, rename, upgrade,
# bombard. Their full live status is shown in the header when hovered.
ACTION_START_OFFSET_X = 242
ACTION_BUTTON_STEP_X = 28
ACTION_BUTTON_OFFSET_Y = 6
ACTION_COL_CONVERT = 0
ACTION_COL_DISBAND = 1
ACTION_COL_REPAIR = 2
ACTION_COL_RENAME = 3
ACTION_COL_UPGRADE = 4
ACTION_COL_BOMBARD = 5
ACTION_ICON_ZOOM = 0.65

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
MOVE_TARGET_COLOR = (0, 255, 0)
BOMBARD_TARGET_COLOR = (255, 200, 50)
BOMBARD_PREVIEW_ALPHA = 160

WHEEL_SCROLL_STEP = 30
UNIT_ICON_ZOOM = 1.5


class _OrdersRowHitbox(Button):
    """Invisible clickable area covering a row's unit art and text.

    The action glyphs occupy the rest of the row and do not overlap this rect,
    so selecting a unit and issuing one of its commands remain separate clicks.
    It inherits Button's press/click/sound handling while leaving the dense row
    rendering to Orders_Screen.additional_draw.
    """

    def __init__(self, rect, callback):
        super().__init__(rect.x, rect.y, "tiny_square", "grey", "", callback,
                         show_text=False)
        self.rect = pygame.Rect(rect)

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
        # The panel remembers the group that opened (or was last box-selected
        # in) this Orders session.  Its rows remain available when the player
        # focuses one member, while map selection alone controls movement.
        self.roster_unit_ids = set()
        self.cancel_rects = []
        self.action_buttons = []
        self.unit_row_icons = {}
        self.action_icons = {}
        self.battle_screen = None
        self.entered_from_combat_bubble = False
        self.return_to_province_menu = True

        self.renaming_unit_index = None
        self.renaming_unit_province = None
        self.renaming_unit_actual_index = None
        self.rename_text = ""

        # Index of the unit currently waiting for the player to click a tile to shell
        self.bombarding_unit_index = None
        self.bombarding_unit_province = None
        self.bombarding_unit_actual_index = None

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

        self.unit_library = queries.get_unit_library()

    def start_with_province(self, province, map_ref):
        self.target_province = province
        self.map_screen = map_ref
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
        self.bombarding_unit_index = None
        self.bombarding_unit_province = None
        self.bombarding_unit_actual_index = None
        self.renaming_unit_index = None
        self.renaming_unit_province = None
        self.renaming_unit_actual_index = None
        self.rename_text = ""

        # Give the player an initially useful view when Orders is opened, but
        # never keep recentering it afterwards: this is a map-wide command
        # workspace, not a province-locked popup.
        camera_handler.center_camera_on_province(
            self.map_screen.camera, province["center"], c.SCREEN_WIDTH, c.SCREEN_HEIGHT,
            self.map_screen.total_ui_h, x_offset=c.ORDERS_PANEL_CAMERA_X_OFFSET)

        # --- Auto-select logic ---
        units = self.target_province.get("units", [])

        # A province you command nothing in is still worth reading -- what is
        # standing on the front you are about to walk into, and what orders it
        # already has. The panel shows every unit there and edits none of them.
        self.read_only = (not any(u.get("owner") == self.map_screen.player_country
                                  for u in units)
                          or (getattr(self.map_screen, "realtime_multiplayer", False)
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

        self._replace_roster_with_selection()
        self.refresh_ui()
        if (open_battle_on_entry and queries.is_province_in_active_combat(
                self.target_province, self.map_screen.nation_data)):
            self.open_battle_panel()

    def inspect_province(self, province):
        """Retarget the live Orders workspace to another visible stack."""
        self.target_province = province
        self.map_screen.selected_province = province
        self.battle_screen = None
        self.scroll_y = 0
        self.bombarding_unit_index = None
        self.bombarding_unit_province = None
        units = province.get("units", [])
        own_indices = [i for i, unit in enumerate(units)
                       if unit.get("owner") == self.map_screen.player_country]
        selected_indices = [i for i in own_indices
                            if self.map_screen.is_unit_selected(units[i])]
        if len(selected_indices) > 1:
            self.selected_unit_index = "ALL"
        elif selected_indices:
            self.selected_unit_index = selected_indices[0]
        elif len(own_indices) > 1:
            self.selected_unit_index = "ALL"
        else:
            self.selected_unit_index = own_indices[0] if own_indices else None
        self.read_only = not self.map_screen.selected_unit_records()
        self._replace_roster_with_selection()
        self.refresh_ui()

    def _replace_roster_with_selection(self):
        """Make the visible Orders roster match the current map selection."""
        self.roster_unit_ids = {
            id(unit) for unit, _province in self.map_screen.selected_unit_records()
        }

    def _remember_roster_selection(self):
        """Keep the current group visible while focusing one of its members."""
        if not hasattr(self, "roster_unit_ids"):
            self.roster_unit_ids = set()
        self.roster_unit_ids.update(
            id(unit) for unit, _province in self.map_screen.selected_unit_records())

    def exit_screen(self):
        # The battle inspector is an optional child panel now, so leaving
        # Orders removes both windows in one transition back to the map.
        self.battle_screen = None
        # Selection belongs to this Orders session.  Returning to the map or
        # province menu must not leave a group armed for an accidental move.
        if self.map_screen:
            self.map_screen.clear_map_unit_selection()
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
        """The clear right-hand space beside the compact Orders panel."""
        x = self.panel_rect.right + BATTLE_PANEL_GAP
        width = c.SCREEN_WIDTH - x - BATTLE_PANEL_RIGHT_MARGIN
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
        ui.event_handler.handle_view_mode_keybind."""
        event_handler.handle_view_mode_keybind(self.map_screen, "UNITS", "ORDERS", origin=self)

    def handle_economy_key(self):
        """W. Same as clicking the Economy button in the view-mode row; also
        jumps screens when the Keybinds screen's per-key toggle is on -- see
        ui.event_handler.handle_view_mode_keybind."""
        event_handler.handle_view_mode_keybind(self.map_screen, "ECONOMY", "ECONOMY", origin=self)

    def handle_clear_orders_key(self):
        """Runs the same action as the Clear Orders button.

        The shortcut is deliberately unavailable everywhere the button is:
        foreign/read-only rosters and tactical mode. A key press also belongs
        to the rename field while that field is active, even if the player has
        rebound Clear Orders to a printable character.
        """
        if (self.renaming_unit_index is not None
                or getattr(self, "read_only", False)
                or not self.map_screen
                or self.map_screen.tactical_mode):
            return
        self.clear_all_orders()

    def select_unit(self, index):
        if getattr(self, "read_only", False):
            return
        if self.map_screen.tactical_mode:
            self.map_screen.show_feedback("Tactical Mode: You can only command your specific unit!")
            return
        units = self.target_province.get("units", [])
        if index == "ALL":
            local_units = [unit for unit in units
                           if unit.get("owner") == self.map_screen.player_country]
            if local_units and all(self.map_screen.is_unit_selected(unit) for unit in local_units):
                self.map_screen.deselect_map_units(local_units)
                self.selected_unit_index = None
            else:
                self.map_screen.select_map_units(local_units)
                self.selected_unit_index = index
        elif isinstance(index, int) and 0 <= index < len(units):
            unit = units[index]
            if self.map_screen.is_unit_selected(unit):
                self.map_screen.deselect_map_units([unit])
                self.selected_unit_index = None
            else:
                self.map_screen.select_map_units([unit])
                self.selected_unit_index = index
        self.bombarding_unit_index = None
        self._replace_roster_with_selection()
        self.refresh_ui()

    def toggle_selected_unit(self, unit):
        """Focus a group member, or deselect the sole selected unit."""
        if getattr(self, "read_only", False) or self._command_blocked(unit):
            return
        self._remember_roster_selection()
        self.roster_unit_ids.add(id(unit))
        if self.map_screen.is_unit_selected(unit):
            if len(self.map_screen.selected_unit_records()) > 1:
                self.map_screen.select_map_units([unit])
            else:
                self.map_screen.deselect_map_units([unit])
        else:
            self.map_screen.select_map_units([unit], additive=True)
        self.bombarding_unit_index = None
        self.refresh_ui()

    def _command_blocked_silent(self, unit):
        """True if tactical mode forbids acting on this unit.

        A tactical player pilots one specific unit, not their whole nation, so
        other units they own in the same stack must be rejected the same way
        foreign units are -- every order-issuing method needs this check, not
        just the buttons that call it.
        """
        return self.map_screen.tactical_mode and unit is not self.map_screen.player_unit

    def _command_blocked(self, unit):
        """Like _command_blocked_silent, but also surfaces feedback to the player."""
        if self._command_blocked_silent(unit):
            self.map_screen.show_feedback("Tactical Mode: You can only command your specific unit!")
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

    def _get_action_icon(self, name):
        """Returns one cached command glyph fitted to a compact action cell."""
        if name not in self.action_icons:
            icon = symbol_loader.get_symbol(name, zoom=ACTION_ICON_ZOOM)
            self.action_icons[name] = self.fit_icon(icon, "orders_action_icon", padding=5)
        return self.action_icons[name]

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
        is_naval = queries.is_naval_unit(unit_name)
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
                unit_name, player_research, self.unit_library, queries.get_tech_tree())
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

        if order_type == "BOMBARD":
            btn_bombard = add(ACTION_COL_BOMBARD, "red", "Cancel bombardment",
                              lambda idx=index, p=province: self.cancel_unit_order(idx, p),
                              "Bombardment Arrows")
        elif not queries.can_bombard(unit_name):
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

    def _visible_rows(self):
        """Orders-session units, with their live province and index.

        The roster retains units that were selected together even after the
        player focuses one of them.  That leaves the other rows visible and
        unselected, while only the focused unit receives map move orders.
        The row key stays an integer for the focused province for compatibility
        with its single-unit action controls; cross-province rows use a stable
        tuple so identically numbered stack slots never collide in the UI.
        """
        selected_records = self.map_screen.selected_unit_records()
        if not getattr(self, "roster_unit_ids", set()):
            self.roster_unit_ids = {id(unit) for unit, _province in selected_records}

        map_data = getattr(self.map_screen, "map_data", None)
        if map_data is None:
            # Lightweight callers and focused tests can provide only the
            # selected-record query; the live Map always provides map_data.
            map_data = {province["id"]: province
                        for _unit, province in selected_records}

        rows, live_ids = [], set()
        for province in map_data.values():
            for index, unit in enumerate(province.get("units", [])):
                unit_id = id(unit)
                if unit_id not in self.roster_unit_ids:
                    continue
                live_ids.add(unit_id)
                row_key = index if province is self.target_province else (province["id"], index)
                rows.append((row_key, unit, province, index))
        self.roster_unit_ids.intersection_update(live_ids)
        return rows

    def refresh_ui(self):
        if getattr(self.map_screen, "realtime_multiplayer", False):
            player = self.map_screen.realtime_session.players.get(self.map_screen.realtime_player_id)
            self.read_only = (self.map_screen.realtime_session.phase != "TURN" or not player
                              or player.submitted or player.eliminated)
        self.view_mode_buttons = view_mode_buttons.build(
            lambda mode: event_handler.navigate_view_mode(self.map_screen, mode, origin=self))
        view_mode_buttons.sync_highlight(self.view_mode_buttons, self.map_screen.secondary_mode)

        # Keep the command box no taller than its current roster requires.
        # Once the roster reaches the normal map-panel limit it uses the
        # existing scroll region exactly as before.
        initial_rows = self._visible_rows()
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
        rows = self._visible_rows()
        player_units = [unit for _key, unit, _province, _index in rows]
        target_player_units = [unit for unit in self.target_province.get("units", [])
                               if unit.get("owner") == player_country]

        # Keep a focused province for the battle pane and a single unit's
        # targeting preview, but action buttons below always receive their
        # own row province.  Multi-selection therefore remains safe.
        single_row = rows[0] if len(rows) == 1 else None
        if single_row and single_row[2] is not self.target_province:
            self.target_province = single_row[2]
            rows = self._visible_rows()
            single_row = rows[0] if len(rows) == 1 else None

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

        if player_units:
            button_x = self.PANEL_X + PANEL_INSET
            local_units = [unit for unit in self.target_province.get("units", [])
                           if unit.get("owner") == player_country]
            if len(local_units) > 1:
                all_color = "grey" if is_tactical else (
                    "blue" if self.selected_unit_index == "ALL" else "grey")
                btn_all = Button(button_x, PANEL_Y + TOP_BTN_ROW_OFFSET_Y,
                                 "orders_header_button", all_color, "Select All",
                                 lambda: self.select_unit("ALL"), font_preset="tiny")
                btn_all.disabled = is_tactical
                btn_all.is_selected = self.selected_unit_index == "ALL" and not is_tactical
                self.elements.append(btn_all)
                button_x = btn_all.rect.right + TOP_BTN_GAP_X

            btn_clear = Button(button_x, PANEL_Y + TOP_BTN_ROW_OFFSET_Y,
                               "orders_clear_button", "red",
                               "Clear ALL Orders", self.clear_all_orders,
                               font_preset="tiny")
            btn_clear.disabled = is_tactical
            self.elements.append(btn_clear)

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
                lambda selected_unit=unit: self.toggle_selected_unit(selected_unit))
            hitbox.is_scrollable = True
            hitbox.click_guard = row_guard
            self.elements.append(hitbox)

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
        u_type = unit.get("original_type", unit.get("type", ""))
        stats = self.unit_library.get(u_type, {})

        if queries.get_scenario_flag("free_repairs", c.DEFAULT_FREE_REPAIRS, self.map_screen.scenario_settings):
            costs = {"cost_materials": 0, "cost_manpower": 0, "cost_fuel": 0}
        else:
            hp = unit.get("health", 0)
            m_hp = unit.get("max_health", 1)

            missing_pct = (m_hp - hp) / max(1, m_hp)

            cost_mat = int(stats.get("cost_materials", 0) * missing_pct)
            cost_man = int(stats.get("cost_manpower", 0) * missing_pct)
            cost_fuel = int(stats.get("cost_fuel", 0) * missing_pct)

            costs = {"cost_materials": cost_mat, "cost_manpower": cost_man, "cost_fuel": cost_fuel}

        is_tactical = self.map_screen.tactical_mode and unit is self.map_screen.player_unit
        if is_tactical:
            p_data = self.map_screen.unit_economy
        else:
            p_data = self.map_screen.nation_data[self.map_screen.player_country]

        if queries.can_afford(p_data, costs):
            queries.deduct_resources(p_data, costs)
            unit["order"] = {
                "type": "REPAIR",
                "turns_left": 1,
                "refund": costs
            }
            self.map_screen.show_feedback("Repair ordered (1 turn).")
            self.refresh_ui()
        else:
            self.map_screen.show_feedback("Cannot afford repair!")

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
        unit["order"] = {
            "type": "UPGRADE",
            "turns_left": 1,
            "target_type": target_type,
            "refund": {}
        }
        self.map_screen.show_feedback(f"Upgrade to {target_type} ordered (1 turn).")
        self.refresh_ui()

    def start_bombard_targeting(self, index, province=None, row_key=None):
        """Arms a gun and waits for the player to click the tile it should shell."""
        province = province or self.target_province
        units = province.get("units", [])
        if not (0 <= index < len(units)): return

        if self._command_blocked(units[index]):
            return

        self.bombarding_unit_index = index if row_key is None else row_key
        self.bombarding_unit_province = province
        self.bombarding_unit_actual_index = index
        self.map_screen.show_feedback("Select a tile within range to bombard.")
        self.refresh_ui()

    def cancel_bombard_targeting(self):
        self.bombarding_unit_index = None
        self.bombarding_unit_province = None
        self.bombarding_unit_actual_index = None
        self.refresh_ui()

    def set_bombard_target(self, index, dest, province=None):
        province = province or self.bombarding_unit_province or self.target_province
        units = province.get("units", [])
        if not (0 <= index < len(units)):
            self.bombarding_unit_index = None
            self.bombarding_unit_province = None
            self.bombarding_unit_actual_index = None
            return

        unit = units[index]
        u_type = unit.get("type", "")

        # The same rule process_bombardments applies: guns fire from land, and
        # ships that carry them (Battleship, Dreadnought, Carrier) fire from the
        # water by design.
        if (queries.is_water_province(province)
                and not (unit.get("naval_unit") or queries.is_naval_unit(u_type))):
            self.map_screen.show_feedback("This unit cannot bombard from the water!")
            self.bombarding_unit_index = None
            self.bombarding_unit_province = None
            self.bombarding_unit_actual_index = None
            self.refresh_ui()
            return

        bomb_range = queries.get_bombardment_range(u_type)
        in_range = queries.get_bombardment_targets(province, self.map_screen.id_to_province, bomb_range)

        if dest["id"] not in in_range:
            self.map_screen.show_feedback("Target out of bombardment range!")
            return

        # A gun that is firing stays put, so any queued movement is dropped
        unit["order"] = {"type": "BOMBARD", "target_id": dest["id"]}
        self.bombarding_unit_index = None
        self.bombarding_unit_province = None
        self.bombarding_unit_actual_index = None
        self.map_screen.show_feedback(f"Bombarding Province {dest['id']} (cannot move this turn)")
        self.refresh_ui()

    def disband_unit(self, index, province=None):
        province = province or self.target_province
        units = province.get("units", [])
        if 0 <= index < len(units):
            unit = units[index]
            if self._command_blocked(unit):
                return
            unit["order"] = {"type": "DISBAND", "turns_left": 1}
            self.map_screen.show_feedback(f"Disbanding {unit.get('type')} (1 turn)")
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

            if u_type.startswith("Convoy"):
                target_type = "Land Unit"
                turns = 1
            elif u_type.startswith("Truck"):
                target_type = "Ship"
                turns = c.TRUCK_CONVERT_TURNS
            elif queries.is_naval_unit(u_type):
                player_research = self.map_screen.nation_data.get(player_country, {}).get("research", {})
                if player_research.get("trucks", 0) < 1:
                    self.map_screen.show_feedback("Requires Trucks research!")
                    return
                target_type = "Truck"
                turns = c.TRUCK_CONVERT_TURNS
            else:
                target_type = "Convoy"
                turns = 1

            unit["order"] = {"type": "CONVERT", "turns_left": turns, "to": target_type}

            self.map_screen.show_feedback(f"Converting to {target_type} ({turns} turns)")
            self.refresh_ui()

    def cancel_unit_order(self, index, province=None):
        province = province or self.target_province
        units = province.get("units", [])
        if 0 <= index < len(units):
            if self._command_blocked(units[index]):
                return
            order = units[index].get("order", {})
            if "order" in units[index]:
                if isinstance(order, dict) and "refund" in order:
                    unit = units[index]
                    is_tactical = self.map_screen.tactical_mode and unit is self.map_screen.player_unit
                    if is_tactical:
                        p_data = self.map_screen.unit_economy
                    else:
                        p_data = self.map_screen.nation_data[self.map_screen.player_country]
                    queries.refund_resources(p_data, order["refund"])
                del units[index]["order"]
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
        self.bombarding_unit_index = None
        self.bombarding_unit_province = None
        self.bombarding_unit_actual_index = None

        for unit in units:
            if unit.get("owner") == self.map_screen.player_country and not self._command_blocked_silent(unit):
                if "order" in unit:
                    order = unit["order"]
                    if isinstance(order, dict) and "refund" in order:
                        is_tactical = self.map_screen.tactical_mode and unit is self.map_screen.player_unit
                        if is_tactical:
                            p_data = self.map_screen.unit_economy
                        else:
                            p_data = self.map_screen.nation_data[self.map_screen.player_country]
                        queries.refund_resources(p_data, order["refund"])
                    del unit["order"]
                    cleared_any = True

        if cleared_any:
            self.map_screen.show_feedback("All orders cleared")
        if cleared_any or cancelled_targeting:
            self.refresh_ui()

    def handle_back_key(self):
        # Inline editing and bombardment targeting each consume Escape before
        # it is allowed to close the whole panel.
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

            super().handle_events([event])
            self.additional_events(event)

    def additional_events(self, event):
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
        on_ui = panel_rect.collidepoint(event_pos)

        # A left-click starts a stack selection, a province interaction, or a
        # panel action.  It always cancels an unfinished right-drag rectangle
        # without changing the existing unit selection.
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self.map_screen.unit_selection_drag = None

        # The Orders panel is a live map workspace.  Stacks update the shared
        # selection without opening another screen or recentering the camera.
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and not on_ui:
            for stack in getattr(self.map_screen, "unit_stack_hitboxes", []):
                if stack["rect"].collidepoint(event.pos):
                    self.map_screen.select_map_units(
                        stack["units"],
                        additive=bool(pygame.key.get_mods() & pygame.KMOD_SHIFT))
                    self.target_province = stack["province"]
                    self.selected_unit_index = None
                    self.read_only = not bool(self.map_screen.selected_unit_records())
                    self._replace_roster_with_selection()
                    self.refresh_ui()
                    return

        if (event.type == pygame.MOUSEBUTTONDOWN and event.button == 3
                and not on_ui and self.map_screen.can_select_map_units()):
            self.map_screen.unit_selection_drag = {
                "start": event.pos, "current": event.pos,
                "additive": bool(pygame.key.get_mods() & pygame.KMOD_SHIFT),
            }
            return

        if event.type == pygame.MOUSEMOTION and self.map_screen.unit_selection_drag:
            self.map_screen.unit_selection_drag["current"] = event.pos
            return

        if event.type == pygame.MOUSEBUTTONUP and event.button == 3:
            drag = self.map_screen.unit_selection_drag
            self.map_screen.unit_selection_drag = None
            if not drag:
                return
            rect = pygame.Rect(
                drag["start"],
                (event.pos[0] - drag["start"][0], event.pos[1] - drag["start"][1]))
            rect.normalize()
            if rect.width < 4 and rect.height < 4:
                if not self.read_only:
                    destination = queries.get_clicked_province(event.pos, self.map_screen)
                    if destination and self.map_screen.selected_unit_records():
                        if self.map_screen.issue_selected_move_orders(
                                destination,
                                append=bool(pygame.key.get_mods() & pygame.KMOD_SHIFT)):
                            self.refresh_ui()
                return
            if rect.width >= 4 or rect.height >= 4:
                selected = []
                for stack in getattr(self.map_screen, "unit_stack_hitboxes", []):
                    if rect.colliderect(stack["rect"]):
                        selected.extend(stack["units"])
                self.map_screen.select_map_units(selected, additive=drag["additive"])
                self.selected_unit_index = None
                self.read_only = not bool(self.map_screen.selected_unit_records())
                self._replace_roster_with_selection()
                self.refresh_ui()
            return

        # Pass scroll and pan events to your centralized map camera
        if event.type in (pygame.MOUSEWHEEL, pygame.MOUSEMOTION,
                          pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP):
            # Only allow camera zoom/pan if not scrolling the unit list
            if event.type == pygame.MOUSEWHEEL and on_ui:
                pass
            else:
                self.map_screen.camera.handle_input(event, self.map_screen, on_ui)

        # --- Bombardment Target Click ---
        # Takes priority over move orders while a gun is armed
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and self.bombarding_unit_index is not None:
            if panel_rect.collidepoint(event.pos):
                return

            dest = queries.get_clicked_province(event.pos, self.map_screen)
            if dest:
                self.set_bombard_target(self.bombarding_unit_actual_index, dest,
                                        self.bombarding_unit_province)
            return

        # Left-clicking open map space is the quick way out of the Orders
        # workspace.  A visible unit stack remains an interaction target even
        # when it belongs to another country, so it never accidentally closes
        # the screen underneath the cursor.
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and not on_ui:
            if event_handler._unit_stack_at(self.map_screen, event.pos) is None:
                self.exit_screen()
                return

        # --- Dynamic Map Hover Update ---
        if event.type == pygame.MOUSEMOTION:
            self.map_screen.hovered_unit_stack = event_handler._unit_stack_at(
                self.map_screen, event.pos)
            self.map_screen.hovered_province = (
                None if self.map_screen.hovered_unit_stack
                else queries.get_clicked_province(event.pos, self.map_screen))

            if self.map_screen.hovered_province:
                curr_id = self.map_screen.hovered_province["id"]
                if curr_id != self.map_screen.last_hovered_id:
                    from map_logic.rendering import map_utils
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
        return queries.can_unit_move_step(unit, current, dest, self.map_screen.nation_data)

    def _order_summary(self, unit_index, unit):
        """Short status text and color for a compact roster row."""
        if self.bombarding_unit_index == unit_index:
            return "Choose bombard target", BOMBARD_TARGET_COLOR

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
        if order_type == "CONVERT":
            return f"Convert to {order.get('to', '?')}{turn_suffix}", (100, 180, 255)
        if order_type == "UPGRADE":
            return f"Upgrade to {order.get('target_type', '?')}{turn_suffix}", (255, 170, 70)
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
                unit.get("custom_name", unit.get("type", "Unit")),
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
                summary, summary_color = self._order_summary(row_key, unit)
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
        title = fit_text("ORDERS | MAP COMMAND",
                         title_font, self.PANEL_WIDTH - 62)
        surface.blit(title_font.render(title, True, (255, 255, 255)),
                     (self.PANEL_X + PANEL_INSET,
                      PANEL_Y + HEADER_TITLE_OFFSET_Y))

        if read_only:
            meta = "READ ONLY | NO COMMANDABLE UNITS SELECTED"
        else:
            meta = f"{len(rows)} UNIT{'S' if len(rows) != 1 else ''} SELECTED"
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
                help_text = "Click a highlighted province to set the bombardment target"
            elif read_only:
                help_text = "Intelligence view: orders cannot be changed here"
            elif not player_units:
                help_text = "Click a unit stack, or right-drag a box around stacks to select units"
            elif len(player_units) > 1:
                help_text = "Right-click a province to move the selected group | Shift+right-click queues a waypoint"
            else:
                help_text = "Click the map to move | click the row to deselect | hover a command icon for details"

        help_text = fit_text(help_text, tiny_font, self.PANEL_WIDTH - (PANEL_INSET * 2))
        surface.blit(tiny_font.render(help_text, True, c.UI_TEXT_MUTED),
                     (self.PANEL_X + PANEL_INSET,
                      PANEL_Y + HEADER_HELP_OFFSET_Y))

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
        previous_hide_flag = getattr(self.map_screen, "hide_flag", False)
        self.map_screen.hide_flag = True
        try:
            self.map_screen.draw_clean_map_background(surface)
        finally:
            self.map_screen.hide_flag = previous_hide_flag

        # Do not draw the province inspector here.  Orders is deliberately a
        # free-roaming map workspace; the left panel is driven by the current
        # unit selection rather than whichever province happened to be opened.

        self.cancel_rects = []
        small_font = fonts.get("small")
        tiny_font = fonts.get("tiny")

        read_only = getattr(self, "read_only", False)
        owner_color = self.map_screen.nation_colors.get(self.map_screen.player_country, (255, 255, 0))
        rows = self._visible_rows()
        player_units = [unit for _key, unit, _province, _index in rows]

        # Force every selected unit's own path through fog-of-war before the
        # opaque roster is painted.  Each path begins at its own province and
        # keeps its own speed, even when the group spans the map.
        for _key, unit, origin, _index in rows:
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
                bomb_range = queries.get_bombardment_range(unit.get("type", ""))
                overlay_renderer.draw_bombardment_arrow(
                    surface, self.map_screen, origin, target_id,
                    bomb_range, force_visible=True)

        ui_bars.draw_translucent_panel(
            surface, self.panel_rect, (*PANEL_BG_COLOR, self.PANEL_TRANSPARENCY),
            border_color=PANEL_BORDER_COLOR, radius=3)
        self._draw_panel_header(surface, rows, player_units, read_only)

        content_rect = getattr(self, 'scroll_content_rect', None) or pygame.Rect(
            self.PANEL_X + 2, self.panel_top,
            self.PANEL_WIDTH - SCROLLBAR_WIDTH - 2, self.panel_max_h)

        # One roster, always: every unit fog of war lets the player see on
        # this tile gets a row (icon/name/health). Only rows for units the
        # player can actually command -- built in refresh_ui -- carry a
        # selection hitbox and the command column to their right.
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
                            owner_color, small_font, tiny_font, True)

        self.draw_list_scrollbar(
            surface, self.panel_rect.right - SCROLLBAR_WIDTH, self.panel_top,
            self.panel_max_h, width=SCROLLBAR_WIDTH, limit_attr="max_scroll_y")

        # --- Bombardment Targeting Preview ---
        aiming_province = self.bombarding_unit_province or self.target_province
        focused_units = aiming_province.get("units", [])
        aiming_index = self.bombarding_unit_actual_index
        if (self.bombarding_unit_index is not None
                and isinstance(aiming_index, int)
                and 0 <= aiming_index < len(focused_units)):
            aiming_unit = focused_units[aiming_index]
            bomb_range = queries.get_bombardment_range(aiming_unit.get("type", ""))
            in_range = queries.get_bombardment_targets(aiming_province, self.map_screen.id_to_province, bomb_range)
            self.draw_target_markers(surface, aiming_province, in_range, BOMBARD_TARGET_COLOR)

            hovered = queries.get_clicked_province(pygame.mouse.get_pos(), self.map_screen)
            if hovered and hovered["id"] in in_range:
                overlay_renderer.draw_bombardment_arrow(surface, self.map_screen, aiming_province, hovered["id"], bomb_range, alpha=BOMBARD_PREVIEW_ALPHA, force_visible=True)

        # Show the same live right-drag rectangle as the map screen.  The
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

        if self.battle_screen is not None:
            self.battle_screen.draw_embedded(surface)

    def update(self):
        super().update()
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
