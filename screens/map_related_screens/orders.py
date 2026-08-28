import pygame
import data.constants as c
from gameState import GameState, resolve_keybind
from ui_elements import Button, process_text_input, draw_text_box
from map_logic.rendering.font_manager import fonts
from data import queries
from ui.text_utils import fit_text
from map_logic.rendering import symbol_loader
from map_logic.rendering import province_select
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
        self.cancel_rects = []
        self.action_buttons = []
        self.unit_row_icons = {}
        self.action_icons = {}
        self.battle_screen = None

        self.renaming_unit_index = None
        self.rename_text = ""

        # Index of the unit currently waiting for the player to click a tile to shell
        self.bombarding_unit_index = None

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
        self.battle_screen = None
        self.scroll_y = 0
        self.bombarding_unit_index = None
        self.renaming_unit_index = None
        self.rename_text = ""

        # Shift the camera left so this panel doesn't cover the unit it's showing orders for.
        camera_handler.center_camera_on_province(
            self.map_screen.camera, province["center"], c.SCREEN_WIDTH, c.SCREEN_HEIGHT,
            self.map_screen.total_ui_h, x_offset=c.ORDERS_PANEL_CAMERA_X_OFFSET)

        # --- Auto-select logic ---
        units = queries.units_on_province(self.target_province)

        # A province you command nothing in is still worth reading -- what is
        # standing on the front you are about to walk into, and what orders it
        # already has. The panel shows every unit there and edits none of them.
        self.read_only = not any(u.get("owner") == self.map_screen.player_country
                                 for u in units)
        
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

        self.refresh_ui()

    def exit_screen(self):
        # The battle inspector is an optional child panel now, so leaving
        # Orders removes both windows in one transition back to the map.
        self.battle_screen = None
        # Undo the left shift applied in start_with_province so the map isn't
        # left off-center once the orders panel is gone.
        if self.map_screen and self.target_province:
            camera_handler.center_camera_on_province(
                self.map_screen.camera, self.target_province["center"], c.SCREEN_WIDTH, c.SCREEN_HEIGHT,
                self.map_screen.total_ui_h)

        if c.MAP_NAVIGATION_MODE == "CLASSIC":
            # Classic: Back lands on the plain province menu, tile still
            # selected. (The view-mode row only ever switches the map overlay
            # in Classic -- see navigate_view_mode -- so this is the only path
            # that leaves Orders at all.)
            super().exit_screen()
            return

        # Preemptive: Back means leaving this province's screens entirely --
        # land on the bare map, not back on its province menu. (Resources/Blank
        # in the view-mode row go through navigate_view_mode instead, which
        # keeps the tile selected -- that's the "regular province menu" path.)
        if self.map_screen:
            self.map_screen.deselect_province()
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
        return pygame.Rect(x, self.panel_rect.y, max(1, width), self.panel_rect.height)

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
        self.selected_unit_index = index
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

    def _build_unit_action_buttons(self, index, unit, row_y, row_guard,
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
                index, row_y, slot, color, help_text, callback, icon_name,
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
                           lambda idx=index: self.cancel_unit_order(idx), convert_icon)
        elif in_combat:
            btn_conv = add(ACTION_COL_CONVERT, "grey", "Convert: unavailable in combat",
                           lambda: None, convert_icon, enabled=False)
        elif is_convoy:
            if not is_water:
                btn_conv = add(ACTION_COL_CONVERT, "blue", "Convert convoy to land unit",
                               lambda idx=index: self.convert_unit(idx), convert_icon)
            else:
                btn_conv = add(ACTION_COL_CONVERT, "grey", "Convert: convoy needs land",
                               lambda: None, convert_icon, enabled=False)
        elif is_truck:
            if is_coastal or is_water:
                btn_conv = add(ACTION_COL_CONVERT, "blue", "Convert truck to ship",
                               lambda idx=index: self.convert_unit(idx), convert_icon)
            else:
                btn_conv = add(ACTION_COL_CONVERT, "grey", "Convert: requires a coast",
                               lambda: None, convert_icon, enabled=False)
        elif not is_naval:
            if is_coastal or is_water:
                btn_conv = add(ACTION_COL_CONVERT, "blue", "Convert land unit to convoy",
                               lambda idx=index: self.convert_unit(idx), convert_icon)
            else:
                btn_conv = add(ACTION_COL_CONVERT, "grey", "Convert: requires a coast",
                               lambda: None, convert_icon, enabled=False)
        elif player_research.get("trucks", 0) < 1:
            btn_conv = add(ACTION_COL_CONVERT, "grey", "Convert: requires Trucks research",
                           lambda: None, convert_icon, enabled=False)
        elif is_coastal or not is_water:
            btn_conv = add(ACTION_COL_CONVERT, "blue", "Convert ship to truck",
                           lambda idx=index: self.convert_unit(idx), convert_icon)
        else:
            btn_conv = add(ACTION_COL_CONVERT, "grey", "Convert: requires a coast",
                           lambda: None, convert_icon, enabled=False)

        if order_type == "DISBAND":
            btn_disband = add(ACTION_COL_DISBAND, "red", "Cancel disband order",
                              lambda idx=index: self.cancel_unit_order(idx), "Disbanding")
        elif is_tactical and unit is self.map_screen.player_unit:
            btn_disband = add(ACTION_COL_DISBAND, "grey", "Disband: unavailable in tactical mode",
                              lambda: None, "Disbanding", enabled=False)
        else:
            btn_disband = add(ACTION_COL_DISBAND, "red", "Disband unit",
                              lambda idx=index: self.disband_unit(idx), "Disbanding")

        hp = int(unit.get("health", 0))
        max_hp = int(unit.get("max_health", 1))
        if order_type == "REPAIR":
            btn_repair = add(ACTION_COL_REPAIR, "orange", "Cancel repair order",
                             lambda idx=index: self.cancel_unit_order(idx), "Repairing")
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
                             lambda idx=index: self.repair_unit(idx), "Repairing")

        if self.renaming_unit_index == index:
            btn_rename = add(ACTION_COL_CONVERT, "green", "Save unit name (Enter)",
                             lambda idx=index: self.save_unit_name(idx), "Text")
        else:
            btn_rename = add(ACTION_COL_RENAME, "blue", "Rename unit",
                             lambda idx=index: self.start_renaming(idx), "Text")

        if order_type == "UPGRADE":
            btn_upgrade = add(ACTION_COL_UPGRADE, "red", "Cancel upgrade order",
                              lambda idx=index: self.cancel_unit_order(idx), "Upgrading")
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
                    lambda idx=index, target=upgrade_target: self.upgrade_unit(idx, target),
                    "Upgrading")

        if order_type == "BOMBARD":
            btn_bombard = add(ACTION_COL_BOMBARD, "red", "Cancel bombardment",
                              lambda idx=index: self.cancel_unit_order(idx),
                              "Bombardment Arrows")
        elif not queries.can_bombard(unit_name):
            btn_bombard = add(ACTION_COL_BOMBARD, "grey", "Bombard: unit has no bombardment",
                              lambda: None, "Bombardment Arrows", enabled=False)
        elif is_water and not is_naval:
            btn_bombard = add(ACTION_COL_BOMBARD, "grey", "Bombard: land guns cannot fire at sea",
                              lambda: None, "Bombardment Arrows", enabled=False)
        elif self.bombarding_unit_index == index:
            btn_bombard = add(ACTION_COL_BOMBARD, "orange", "Choose target (click to cancel)",
                              self.cancel_bombard_targeting, "Bombardment Arrows")
        else:
            btn_bombard = add(ACTION_COL_BOMBARD, "yellow", "Choose bombardment target",
                              lambda idx=index: self.start_bombard_targeting(idx),
                              "Bombardment Arrows")

        # Rename gets the name field and one Save glyph to itself. This is the
        # compact counterpart of the old row hiding its other five buttons.
        if self.renaming_unit_index == index:
            for button in buttons:
                if button is not btn_rename:
                    button.apply_state(visible=False)

    def _visible_rows(self):
        """(index, unit) pairs to list on the roster: every unit fog of war
        lets the player see on this tile. A tile fully hidden by fog still
        lists the player's own units on it -- never hidden from their owner
        -- but nothing belonging to anyone else.
        """
        units = queries.units_on_province(self.target_province)
        player_country = self.map_screen.player_country
        is_visible = queries.is_province_visible(
            self.map_screen, self.target_province["id"])
        if not is_visible:
            return [(i, u) for i, u in enumerate(units)
                   if u.get("owner") == player_country]

        visible = queries.filter_visible_units(
            units, player_country, self.target_province, self.map_screen.nation_data)
        visible_ids = {id(u) for u in visible}
        return [(i, u) for i, u in enumerate(units) if id(u) in visible_ids]

    def refresh_ui(self):
        self.view_mode_buttons = view_mode_buttons.build(
            lambda mode: event_handler.navigate_view_mode(self.map_screen, mode, origin=self))
        view_mode_buttons.sync_highlight(self.view_mode_buttons, self.map_screen.secondary_mode)

        close_button = Button(self.panel_rect.right - 38, self.panel_rect.y + 7,
                              "tiny_square", "red", "X", self.exit_screen,
                              font_preset="tiny")
        self.elements = [*self.view_mode_buttons, close_button]
        self.action_buttons = []
        self.unit_row_icons = {}

        units = queries.units_on_province(self.target_province)
        is_tactical = self.map_screen.tactical_mode
        player_country = self.map_screen.player_country
        player_research = self.map_screen.nation_data.get(player_country, {}).get("research", {})
        player_units = [u for u in units if u.get("owner") == player_country]
        rows = self._visible_rows()

        # Battle is deliberately a child of Orders.  Keep this available for
        # observers as well as participants: a read-only Orders view can still
        # inspect the fight, but no unit commands are enabled there.
        in_battle = queries.is_province_in_active_combat(
            self.target_province, self.map_screen.nation_data)
        if in_battle:
            battle_label = ("Close Battle" if self.battle_screen is not None else
                            ("Manage Battle" if player_units else "View Battle"))
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
            if len(player_units) > 1:
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

        in_combat = queries.is_nation_in_combat_here(
            player_country, self.target_province, self.map_screen.nation_data)
        is_water = queries.is_water_province(self.target_province)
        is_coastal = self.target_province.get("is_coastal", False)
        is_factory = queries.has_industry(self.target_province)

        for display_index, (index, unit) in enumerate(rows):
            row_y = self.panel_top + (display_index * self.row_height) + self.scroll_y
            row_rect = pygame.Rect(
                self.PANEL_X + UNIT_ROW_X_OFFSET, row_y,
                self.PANEL_WIDTH - SCROLLBAR_WIDTH - UNIT_ROW_X_OFFSET - 2,
                self.row_height)

            if not row_rect.colliderect(self.scroll_content_rect):
                continue

            unit_name = unit.get("type", "")
            unit_owner = unit.get("owner")
            row_owner_color = self.map_screen.nation_colors.get(unit_owner, (200, 200, 200))
            icon = symbol_loader.get_symbol(
                unit_name, zoom=UNIT_ICON_ZOOM, color=row_owner_color, country=unit_owner)
            self.unit_row_icons[index] = self.fit_icon(
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
                lambda idx=index: self.select_unit(idx))
            hitbox.is_scrollable = True
            hitbox.click_guard = row_guard
            self.elements.append(hitbox)

            self._build_unit_action_buttons(
                index, unit, row_y, row_guard, in_combat, is_water,
                is_coastal, is_factory, player_research)

    def start_renaming(self, index):
        units = queries.units_on_province(self.target_province)
        if 0 <= index < len(units):
            if self._command_blocked(units[index]):
                return
            self.rename_text = units[index].get("custom_name", "")
        self.renaming_unit_index = index
        self.refresh_ui()

    def save_unit_name(self, index):
        units = queries.units_on_province(self.target_province)
        if 0 <= index < len(units):
            if self._command_blocked(units[index]):
                return
            if self.rename_text.strip():
                units[index]["custom_name"] = self.rename_text.strip()
            else:
                units[index].pop("custom_name", None)
        self.renaming_unit_index = None
        self.refresh_ui()

    def repair_unit(self, index):
        in_combat = queries.is_nation_in_combat_here(self.map_screen.player_country, self.target_province, self.map_screen.nation_data)
        if in_combat:
            self.map_screen.show_feedback("Cannot repair during combat!")
            return

        units = queries.units_on_province(self.target_province)
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

    def upgrade_unit(self, index, target_type):
        in_combat = queries.is_nation_in_combat_here(self.map_screen.player_country, self.target_province, self.map_screen.nation_data)
        if in_combat:
            self.map_screen.show_feedback("Cannot upgrade during combat!")
            return

        # The button is already greyed out as "Needs Factory" without one; this
        # is the same check standing behind it, so the rule holds whatever
        # reaches this method.
        if not queries.has_industry(self.target_province):
            self.map_screen.show_feedback("Cannot upgrade without a factory!")
            return

        units = queries.units_on_province(self.target_province)
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

    def start_bombard_targeting(self, index):
        """Arms a gun and waits for the player to click the tile it should shell."""
        units = queries.units_on_province(self.target_province)
        if not (0 <= index < len(units)): return

        if self._command_blocked(units[index]):
            return

        self.bombarding_unit_index = index
        self.map_screen.show_feedback("Select a tile within range to bombard.")
        self.refresh_ui()

    def cancel_bombard_targeting(self):
        self.bombarding_unit_index = None
        self.refresh_ui()

    def set_bombard_target(self, index, dest):
        units = queries.units_on_province(self.target_province)
        if not (0 <= index < len(units)):
            self.bombarding_unit_index = None
            return

        unit = units[index]
        u_type = unit.get("type", "")

        # The same rule process_bombardments applies: guns fire from land, and
        # ships that carry them (Battleship, Dreadnought, Carrier) fire from the
        # water by design.
        if (queries.is_water_province(self.target_province)
                and not (unit.get("naval_unit") or queries.is_naval_unit(u_type))):
            self.map_screen.show_feedback("This unit cannot bombard from the water!")
            self.bombarding_unit_index = None
            self.refresh_ui()
            return

        bomb_range = queries.get_bombardment_range(u_type)
        in_range = queries.get_bombardment_targets(self.target_province, self.map_screen.id_to_province, bomb_range)

        if dest["id"] not in in_range:
            self.map_screen.show_feedback("Target out of bombardment range!")
            return

        # A gun that is firing stays put, so any queued movement is dropped
        unit["order"] = {"type": "BOMBARD", "target_id": dest["id"]}
        self.bombarding_unit_index = None
        self.map_screen.show_feedback(f"Bombarding Province {dest['id']} (cannot move this turn)")
        self.refresh_ui()

    def disband_unit(self, index):
        units = queries.units_on_province(self.target_province)
        if 0 <= index < len(units):
            unit = units[index]
            if self._command_blocked(unit):
                return
            unit["order"] = {"type": "DISBAND", "turns_left": 1}
            self.map_screen.show_feedback(f"Disbanding {unit.get('type')} (1 turn)")
            self.refresh_ui()

    def convert_unit(self, index):
        # --- Prevent conversion during combat just in case ---
        player_country = self.map_screen.player_country
        in_combat = queries.is_nation_in_combat_here(player_country, self.target_province, self.map_screen.nation_data)
        if in_combat:
            self.map_screen.show_feedback("Cannot convert during combat!")
            return
        # -----------------------------------------------------

        units = queries.units_on_province(self.target_province)
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

    def cancel_unit_order(self, index):
        units = queries.units_on_province(self.target_province)
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
        units = queries.units_on_province(self.target_province)
        cleared_any = False
        cancelled_targeting = self.bombarding_unit_index is not None
        self.bombarding_unit_index = None

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
                    self.save_unit_name(self.renaming_unit_index)
                elif event.key == resolve_keybind(self, "BACK", pygame.K_ESCAPE):
                    self.renaming_unit_index = None
                    self.refresh_ui()
                else:
                    self.rename_text, _ = process_text_input(event, self.rename_text, max_length=c.UNIT_NAME_MAX_LENGTH)
                return

            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                # Guarded to the visible panel so a cancel box scrolled behind
                # the panel's edge (clipped, no longer drawn) can't fire.
                panel_rect = getattr(self, 'scroll_content_rect', None)
                if panel_rect is None or panel_rect.collidepoint(event.pos):
                    for rect, idx in self.cancel_rects:
                        if rect.collidepoint(event.pos):
                            self.cancel_unit_order(idx)
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
        on_ui = panel_rect.collidepoint(mx, my)
                
        # Pass scroll and pan events to your centralized map camera
        if event.type in (pygame.MOUSEWHEEL, pygame.MOUSEMOTION):
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
                self.set_bombard_target(self.bombarding_unit_index, dest)
            return

        # --- Standard Order Placement Click ---
        if getattr(self, "read_only", False):
            return

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and self.selected_unit_index is not None:
            # If the click is inside the panel, ignore it completely
            if panel_rect.collidepoint(event.pos):
                return

            dest = queries.get_clicked_province(event.pos, self.map_screen)
            if not dest: return

        # --- Dynamic Map Hover Update ---
        if event.type == pygame.MOUSEMOTION:
            self.map_screen.hovered_province = queries.get_clicked_province(event.pos, self.map_screen)
            
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

        # --- Standard Order Placement Click ---
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and self.selected_unit_index is not None:
            dest = queries.get_clicked_province(event.pos, self.map_screen)
            if not dest: return

            units = queries.units_on_province(self.target_province)

            if self.selected_unit_index == "ALL":
                target_units = [u for u in units if u.get("owner") == self.map_screen.player_country]
            elif 0 <= self.selected_unit_index < len(units):
                target_units = [units[self.selected_unit_index]]
            else:
                target_units = []

            if not target_units: return

            if any(isinstance(u.get("order"), dict) and u["order"].get("type") in c.ORDERS_BLOCKING_MOVEMENT for u in target_units):
                self.map_screen.show_feedback("Cannot move while converting, disbanding, repairing, upgrading, or bombarding!")
                return
            
            for unit in target_units:
                if "order" not in unit or not isinstance(unit["order"], dict):
                    unit["order"] = {"type": "MOVE", "path": []}
                if "path" not in unit["order"]:
                    unit["order"]["path"] = []

            current_path = target_units[0]["order"]["path"]
            
            # Use the min() generator to find the slowest unit out of all selected
            speed_limit = min(u.get("speed", 1) for u in target_units)

            if not current_path:
                start_node = self.target_province
            else:
                start_node = self.map_screen.id_to_province.get(current_path[-1])

            # --- Unlimited Queueing Logic ---
            if dest["id"] in start_node["neighbors"]:
                if all(self.can_unit_enter(u, dest) for u in target_units):
                    
                    # --- TACTICAL FUEL LIMIT CHECK ---
                    if self.map_screen.tactical_mode and self.selected_unit_index != "ALL":
                        unit = target_units[0]
                        if unit is self.map_screen.player_unit:
                            speed = queries.get_tactical_speed(unit)
                            # If this step would execute this turn
                            if len(current_path) < speed:
                                fuel_inc = self.map_screen.unit_economy.get("fuel_inc", 0)
                                cost_per_tile = queries.get_tactical_fuel_cost_per_tile(unit, fuel_inc)
                                if self.map_screen.player_fuel < cost_per_tile:
                                    self.map_screen.show_feedback("Not enough fuel!")
                                    return
                    # ---------------------------------
                    
                    # Generate a single new path baseline so Python doesn't cross-contaminate lists in memory
                    new_path = current_path.copy()
                    new_path.append(dest["id"])
                    
                    for unit in target_units:
                        unit["order"]["path"] = new_path.copy()
                        
                    # Feedback update based on if it's immediate or queued
                    status_str = "Queued" if len(new_path) > speed_limit else "Added"
                    self.map_screen.show_feedback(f"Path {status_str}: {len(new_path)} steps (Speed: {speed_limit})")
                    self.refresh_ui()

    def can_unit_enter(self, unit, dest):
        dest_is_water = queries.is_water_province(dest)
        
        # Look up the actual unit stats using its type name
        u_type = unit.get("type", "")
        is_convoy = u_type.startswith("Convoy")
        is_truck = u_type.startswith("Truck")
        is_naval = queries.is_naval_unit(u_type)

        # Enforce Land Unit Rules
        if not is_naval and dest_is_water:
            self.map_screen.show_feedback("Land units cannot enter water!")
            return False
        
        # Enforce Naval Unit Rules
        if is_naval and not dest_is_water:
            if not dest.get("is_coastal"):
                self.map_screen.show_feedback("Naval units blocked by land!")
                return False

            # Ships can only dock at friendly coasts
            if not is_convoy and not queries.can_ships_enter(unit["owner"], dest, self.map_screen.nation_data):
                self.map_screen.show_feedback("Ships can only enter friendly/owned coastal tiles!")
                return False

        # Convoy Movement Rules
        if is_convoy:
            current_path = unit.get("order", {}).get("path", [])
            if not current_path:
                start_node = self.target_province
            else:
                start_node = self.map_screen.id_to_province.get(current_path[-1])

            if start_node and not queries.can_convoy_enter(start_node, dest):
                self.map_screen.show_feedback("Convoys on land can only move to ocean!")
                return False
                
            if not dest_is_water and not queries.can_land_units_enter(unit["owner"], dest, self.map_screen.nation_data):
                self.map_screen.show_feedback(f"Neutral territory!")
                return False

        # Enforce Diplomacy/Border Rules
        dest_owner = dest.get("owner", "Unclaimed")
        
        # Combat Lock (Player UI Check)
        current_path = unit.get("order", {}).get("path", [])
        if not current_path: # First step of the move order
            in_combat = queries.is_nation_in_combat_here(unit["owner"], self.target_province, self.map_screen.nation_data)
            if in_combat and queries.is_hostile_territory(unit["owner"], dest_owner, self.map_screen.nation_data):
                self.map_screen.show_feedback("Cannot advance into enemy territory while in combat! (Retreat only)")
                return False

        if not is_naval and not queries.can_land_units_enter(unit["owner"], dest, self.map_screen.nation_data):
            self.map_screen.show_feedback(f"Neutral {dest_owner} territory!")
            return False
            
        return True

    def _order_summary(self, unit_index, unit):
        """Short status text and color for a compact roster row."""
        if self.bombarding_unit_index == unit_index:
            return "Choose bombard target", BOMBARD_TARGET_COLOR

        order = unit.get("order", {})
        if not isinstance(order, dict) or not order:
            return "Ready", c.UI_TEXT_MUTED

        path = order.get("path", [])
        if path:
            step_word = "step" if len(path) == 1 else "steps"
            return f"Move: {len(path)} {step_word} to P{path[-1]}", (255, 225, 80)

        order_type = order.get("type", "")
        turns = order.get("turns_left")
        turn_suffix = f" | {turns}t" if turns is not None else ""
        if order_type == "MOVE":
            return "Move: choose destination", (255, 225, 80)
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

    def _draw_unit_row(self, surface, unit_index, unit, row_y, display_index,
                       owner_color, small_font, tiny_font):
        """Draws one 40px roster row underneath its transparent hitbox/icons."""
        row_rect = pygame.Rect(
            self.PANEL_X + UNIT_ROW_X_OFFSET, row_y,
            self.PANEL_WIDTH - SCROLLBAR_WIDTH - UNIT_ROW_X_OFFSET - 2,
            self.row_height)
        is_own = unit.get("owner") == self.map_screen.player_country
        selectable = is_own and not self._command_blocked_silent(unit)
        selected = selectable and self.selected_unit_index in (unit_index, "ALL")

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

        row_owner_color = self.map_screen.nation_colors.get(unit.get("owner"), owner_color)
        strip_color = row_owner_color if selected else tuple(max(35, channel // 2)
                                                              for channel in row_owner_color)
        pygame.draw.rect(surface, strip_color,
                         (row_rect.x, row_rect.y, 4, row_rect.height))

        icon_box = pygame.Rect(
            self.PANEL_X + UNIT_ICON_OFFSET_X, row_y + UNIT_ICON_OFFSET_Y,
            32, 32)
        pygame.draw.rect(surface, (20, 22, 26), icon_box)
        pygame.draw.rect(surface, (90, 95, 105), icon_box, 1)
        icon = self.unit_row_icons.get(unit_index)
        if icon:
            surface.blit(icon, icon.get_rect(center=icon_box.center))

        name_x = self.PANEL_X + UNIT_NAME_OFFSET_X
        action_x = self.PANEL_X + ACTION_START_OFFSET_X
        text_width = action_x - name_x - 7

        if self.renaming_unit_index == unit_index:
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
                summary, summary_color = self._order_summary(unit_index, unit)
            else:
                owner_id = unit.get("owner", "Unknown")
                summary = self.map_screen.nation_data.get(owner_id, {}).get("name", owner_id)
                summary_color = c.UI_TEXT_MUTED
            status = fit_text(f"HP {int(hp_ratio * 100)}% | {summary}",
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
        has_order = isinstance(order, dict) and bool(order)
        if is_own and has_order and not self._command_blocked_silent(unit):
            cancel_x = (self.PANEL_X + ACTION_START_OFFSET_X
                        + (6 * ACTION_BUTTON_STEP_X) + CANCEL_BOX_GAP_X)
            cancel_rect = pygame.Rect(cancel_x, row_y + CANCEL_BOX_OFFSET_Y,
                                      CANCEL_BOX_SIZE, CANCEL_BOX_SIZE)
            pygame.draw.rect(surface, (145, 25, 25), cancel_rect)
            pygame.draw.rect(surface, (230, 120, 120), cancel_rect, 1)
            x_label = tiny_font.render("X", True, (255, 255, 255))
            surface.blit(x_label, x_label.get_rect(center=cancel_rect.center))
            self.cancel_rects.append((cancel_rect, unit_index))

    def _draw_panel_header(self, surface, rows, player_units, read_only):
        title_font = fonts.get("heading2")
        tiny_font = fonts.get("tiny")
        title = fit_text(f"ORDERS | PROVINCE {self.target_province['id']}",
                         title_font, self.PANEL_WIDTH - 62)
        surface.blit(title_font.render(title, True, (255, 255, 255)),
                     (self.PANEL_X + PANEL_INSET,
                      PANEL_Y + HEADER_TITLE_OFFSET_Y))

        if read_only:
            meta = f"READ ONLY | {len(rows)} unit{'s' if len(rows) != 1 else ''}"
        elif self.selected_unit_index == "ALL":
            meta = f"{len(player_units)} UNITS | ALL SELECTED"
        elif isinstance(self.selected_unit_index, int):
            meta = f"{len(player_units)} UNITS | 1 SELECTED"
        else:
            meta = f"{len(player_units)} UNIT{'S' if len(player_units) != 1 else ''}"
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
                help_text = "No commandable units in this province"
            else:
                help_text = "Hover a command icon for details | click unit art/name to select"

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

        province_select.draw_province_select(self.map_screen, surface)

        self.cancel_rects = []
        small_font = fonts.get("small")
        tiny_font = fonts.get("tiny")

        units = queries.units_on_province(self.target_province)
        read_only = getattr(self, "read_only", False)
        player_units = [u for u in units if u.get("owner") == self.map_screen.player_country]
        owner_color = self.map_screen.nation_colors.get(self.map_screen.player_country, (255, 255, 0))
        rows = self._visible_rows()

        # Force the selected province's orders through fog-of-war before the
        # opaque roster is painted, so arrows stay visible on the map without
        # ever drawing across the panel itself.
        for unit in player_units:
            order = unit.get("order", {})
            if not isinstance(order, dict):
                continue
            path = order.get("path", [])
            if path:
                overlay_renderer.draw_split_movement_path(
                    surface, self.map_screen, self.target_province, path,
                    unit.get("speed", 1), owner_color, force_visible=True)
            elif order.get("type") == "BOMBARD":
                target_id = order.get("target_id")
                bomb_range = queries.get_bombardment_range(unit.get("type", ""))
                overlay_renderer.draw_bombardment_arrow(
                    surface, self.map_screen, self.target_province, target_id,
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
                is_visible = queries.is_province_visible(self.map_screen, self.target_province["id"])
                empty_text = "(Hidden by Fog of War)" if not is_visible else "(No units here)"
                surface.blit(tiny_font.render(empty_text, True, c.UI_TEXT_MUTED),
                             (self.PANEL_X + PANEL_INSET, self.panel_top + self.scroll_y))
            else:
                for display_index, (index, unit) in enumerate(rows):
                    y_pos = self.panel_top + (display_index * self.row_height) + self.scroll_y
                    row_rect = pygame.Rect(
                        self.PANEL_X + UNIT_ROW_X_OFFSET, y_pos,
                        self.PANEL_WIDTH - SCROLLBAR_WIDTH - UNIT_ROW_X_OFFSET - 2,
                        self.row_height)
                    if row_rect.colliderect(content_rect):
                        self._draw_unit_row(
                            surface, index, unit, y_pos, display_index,
                            owner_color, small_font, tiny_font)

        self.draw_list_scrollbar(
            surface, self.panel_rect.right - SCROLLBAR_WIDTH, self.panel_top,
            self.panel_max_h, width=SCROLLBAR_WIDTH, limit_attr="max_scroll_y")

        # --- Bombardment Targeting Preview ---
        if self.bombarding_unit_index is not None and self.bombarding_unit_index < len(units):
            aiming_unit = units[self.bombarding_unit_index]
            bomb_range = queries.get_bombardment_range(aiming_unit.get("type", ""))
            in_range = queries.get_bombardment_targets(self.target_province, self.map_screen.id_to_province, bomb_range)
            self.draw_target_markers(surface, self.target_province, in_range, BOMBARD_TARGET_COLOR)

            hovered = queries.get_clicked_province(pygame.mouse.get_pos(), self.map_screen)
            if hovered and hovered["id"] in in_range:
                overlay_renderer.draw_bombardment_arrow(surface, self.map_screen, self.target_province, hovered["id"], bomb_range, alpha=BOMBARD_PREVIEW_ALPHA, force_visible=True)

        # Hidden while aiming a barrage so the two previews don't fight over the same tiles
        if self.selected_unit_index is not None and self.bombarding_unit_index is None:
            if self.selected_unit_index == "ALL":
                # Find the first player unit to act as the reference for drawing the path preview
                active_unit = player_units[0] if player_units else None
            else:
                active_unit = units[self.selected_unit_index]
                
            if active_unit:
                active_path = active_unit.get("order", {}).get("path", [])
                
                if not active_path:
                    last_node = self.target_province
                else:
                    last_node = self.map_screen.id_to_province.get(active_path[-1])

                if last_node:
                    self.draw_target_markers(surface, last_node, last_node["neighbors"], MOVE_TARGET_COLOR)

                    mouse_pos = pygame.mouse.get_pos()
                    hovered = queries.get_clicked_province(mouse_pos, self.map_screen)
                    if hovered and hovered["id"] in last_node["neighbors"]:
                        
                        # Calculate speed limit based on group or individual selection
                        if self.selected_unit_index == "ALL":
                            speed_limit = min(u.get("speed", 1) for u in player_units)
                        else:
                            speed_limit = active_unit.get("speed", 1)
                        
                        # Determine styling based on if this specific hover step exceeds the speed
                        is_queued = len(active_path) >= speed_limit
                        
                        preview_color = owner_color
                        preview_alpha = 255
                        
                        if is_queued:
                            preview_color = (min(255, owner_color[0] + 150), min(255, owner_color[1] + 150), min(255, owner_color[2] + 150))
                            preview_alpha = 120
                            
                        # Use the owner's color to draw the cursor hover with correct alpha logic
                        overlay_renderer.draw_movement_path(surface, self.map_screen, last_node, [hovered["id"]], color=preview_color, alpha=preview_alpha, force_visible=True)

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
