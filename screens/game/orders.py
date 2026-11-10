import pygame
import data.constants as c
from ui.navigation.screen import Screen
from ui.widgets.ui_elements import Button
from ui.rendering.font_manager import fonts
from data import queries
from map_logic.actions import unit_actions
from ui.widgets.text_utils import fit_text
from ui.bars import ui_bars, resource_hud, view_mode_buttons
from ui.panels import army_panel
from ui.panels.unit_commands import (
    UnitCommandControls, _AirMissionSelectScreen,
    PANEL_Y, PANEL_HEIGHT, PANEL_INSET, PANEL_BORDER_COLOR, SCROLLBAR_WIDTH,
    UNIT_ROW_X_OFFSET, ACTION_START_OFFSET_X, MAP_CLICK_DRAG_THRESHOLD,
    AIR_MISSION_CHOICES, AIR_MISSION_ICONS,
)
from screens.game import map_input
from ui.background_styles import ORDERS_PANEL_STYLES
from ui.widgets import ui_elements

from ui.dialogs.list_select_screen import ListSelectScreen
from ui.panels import sidebar_info
from ui.navigation import screen_runner


# ==========================================
# COMPACT ORDERS PANEL LAYOUT
# ==========================================

# The reference layout gets its density from a compact command header and one
# narrow roster row per unit. The second header row holds the unambiguous batch
# commands which operate on the current map selection. Row and command icon
# layout is shared with Tactical Orders in ui.panels.unit_commands.
PANEL_BOTTOM_INSET = 8
HEADER_TITLE_OFFSET_Y = 7
HEADER_META_OFFSET_Y = 36
TOP_BTN_ROW_OFFSET_Y = 57
HEADER_HELP_OFFSET_Y = 151
HEADER_HELP_LINE_GAP = 2
LIST_TOP_OFFSET_Y = 185

TOP_BTN_GAP_X = 6
BATCH_LABEL_INSET = 4
BATCH_BTN_ROW_OFFSET_Y = TOP_BTN_ROW_OFFSET_Y + 31
BATTLE_UNGROUP_ROW_OFFSET_Y = BATCH_BTN_ROW_OFFSET_Y + 31


class _OrdersRowHitbox(Button):
    """Invisible clickable area covering a row's unit art and text.

    The action glyphs occupy the rest of the row and do not overlap this rect,
    so selecting a unit and issuing one of its commands remain separate clicks.
    It inherits Button's press and release handling. Shared map selection plays
    the sound. Orders_Screen.additional_draw draws the row.
    """

    def __init__(self, rect, callback, secondary_callback=None):
        super().__init__(rect.x, rect.y, "tiny_square", "grey", "", callback,
                         show_text=False, sound_kind=None)
        self.rect = pygame.Rect(rect)
        self.secondary_callback = secondary_callback

    def draw(self, surface):
        pass


class Orders_Screen(UnitCommandControls, Screen):
    back_state = "MAP"
    PANEL_X = 10
    PANEL_WIDTH = 440

    def __init__(self):
        super().__init__()
        self._init_unit_commands()
        self.selected_unit_index = None
        # Rows normally follow selection.  When any selected division belongs
        # to an army, its unselected peers are included as read-only roster
        # context so a player can see the army without accidentally ordering
        # every member.
        self._roster_rows = []
        self._selected_display_records = []
        self._selected_display_ids = frozenset()
        self._panel_title_text = "ORDERS | MAP COMMAND"
        self.panel_rect = pygame.Rect(self.PANEL_X, PANEL_Y, self.PANEL_WIDTH, PANEL_HEIGHT)
        self.panel_top = PANEL_Y + LIST_TOP_OFFSET_Y
        self.panel_max_h = self.panel_rect.bottom - self.panel_top

    def _panel_title(self, player_units):
        """Name the selected army when its membership is unambiguous."""
        army = queries.common_army_for_units(
            player_units, self.map_screen.nation_data)
        if army is not None and army.get("name"):
            return f"ORDERS | {army['name']}"
        return "ORDERS | MAP COMMAND"

    def start_with_province(self, province, map_ref):
        map_ref.army_panel_visible_in_orders = True
        open_battle_on_entry = self._begin_command_session(province, map_ref)

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
        elif self.map_screen.selected_unit_records() or open_battle_on_entry:
            # A map click or box drag may already have selected a group across
            # several provinces, or the battle-click handler selected the
            # clicked tile's troops. Retain that selection verbatim.
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
        if self.map_screen:
            self.map_screen.army_panel_visible_in_orders = False
        super().exit_screen()

    def handle_back_key(self):
        if self.map_screen and army_panel.handle_back_key(self.map_screen):
            return
        super().handle_back_key()

    def _handle_panel_event(self, event):
        if army_panel.handle_event(self.map_screen, event, orders_screen=self):
            return True

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
                return True
        return False

    def _handle_map_selection_event(self, event, on_ui):
        # The Orders panel is a live map workspace. A short left-click on a
        # stack toggles it; an actual left-drag box-selects stacks, matching
        # the map screen and HOI4's primary selection gesture.
        if (event.type == pygame.MOUSEBUTTONDOWN and not on_ui
                and (map_input.mouse_button_has_action(event, "select_units")
                     or map_input.mouse_button_has_action(event, "box_select_units"))):
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
                    event, "select_units"),
                "box_select_units": map_input.mouse_button_has_action(
                    event, "box_select_units"),
            }
            return True

        if event.type == pygame.MOUSEMOTION and self.map_screen.unit_selection_drag:
            self.map_screen.unit_selection_drag["current"] = event.pos
            return True

        if (event.type == pygame.MOUSEBUTTONUP and self.map_screen.unit_selection_drag
                and event.button == self.map_screen.unit_selection_drag.get("button")):
            drag = self.map_screen.unit_selection_drag
            self.map_screen.unit_selection_drag = None
            if not drag:
                return True
            rect = pygame.Rect(
                drag["start"],
                (event.pos[0] - drag["start"][0], event.pos[1] - drag["start"][1]))
            rect.normalize()
            if rect.width < MAP_CLICK_DRAG_THRESHOLD and rect.height < MAP_CLICK_DRAG_THRESHOLD:
                if not drag["select_units"]:
                    return True
                stack = drag["stack"]
                if stack is None:
                    self._return_to_clicked_province(event.pos)
                    return True
                if self.map_screen.click_select_map_units(
                        stack["units"], additive=drag["additive"]):
                    self.inspect_province(stack["province"])
                return True
            if drag["box_select_units"]:
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
            return True
        return False

    def handle_clear_orders_key(self):
        """Runs the same action as the Clear Orders button.

        The shortcut is deliberately unavailable everywhere the button is:
        foreign/read-only rosters and tactical mode. A key press also belongs
        to the rename field while that field is active, even if the player has
        rebound Clear Orders to a printable character.

        Where it is available the key always answers with the cancel sound,
        even when there was nothing to clear.
        """
        if (self.renaming_unit_index is not None
                or self.read_only
                or not self.map_screen
                or self.map_screen.tactical_mode):
            return
        if not self.clear_all_orders():
            ui_elements.play_ui_sound("cancel_orders")

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
        results = unit_actions.apply_batch(self.map_screen, self.map_screen.player_country,
                                 [(unit, province, None) for unit, province in ordered_units])
        self._play_order_sound("cancel_orders", results)
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

    def _apply_selected_air_mission(self, records, mission):
        count = 0
        cancelled_orders = []
        for unit, province in records:
            if self._air_mission_unit_index(unit, province) is None:
                continue
            try:
                order = self._air_mission_order(unit, province, mission)
            except ValueError:
                # Mixed groups skip unsupported defense choices or invalid bases.
                # Keep those units' orders and reserved payment.
                continue
            had_order = bool(unit.get("order"))
            result = unit_actions.apply_action(self.map_screen, unit["owner"], province, unit, order)
            if mission == "NONE" and had_order:
                cancelled_orders.append(result)
            count += 1
        self._play_order_sound("cancel_orders", cancelled_orders)
        self.cancel_bombard_targeting(refresh=False)
        self._finish_batch_command("Air mission", count)
        if not count:
            self.refresh_ui()

    @staticmethod
    def _fit_batch_button(button, width):
        """Keep complete action/count labels inside the four-column header."""
        button.rect.width = width
        size = fonts.presets["tiny"]["size"]
        while size > 1 and button.font.size(button.text)[0] > width - 2 * BATCH_LABEL_INSET:
            size -= 1
            button.font = fonts.get_size(size)

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
                              font_preset="tiny", sound_kind="back")
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
                             lambda: self.select_unit("ALL"), font_preset="tiny", sound_kind=None)
            btn_all.disabled = is_tactical
            btn_all.is_selected = all_selected and not is_tactical
            self.elements.append(btn_all)
            button_x = btn_all.rect.right + TOP_BTN_GAP_X

            btn_clear = Button(button_x, PANEL_Y + TOP_BTN_ROW_OFFSET_Y,
                               "orders_clear_button", "red",
                               "Clear ALL Orders", self.clear_all_orders,
                               font_preset="tiny", sound_kind=None)
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
                                    font_preset="tiny",
                                    sound_kind=None if is_active_for_every_selection else "click")
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

            self._cache_row_icon(row_key, unit)

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

    def clear_all_orders(self):
        """Cancels the displayed units' orders. Returns whether the cancel sound played."""
        selected_records = self.map_screen.selected_unit_records()
        # Orders normally clears exactly the units displayed in its roster.
        # Retain the province fallback for a read-only inspection opened by an
        # older caller that has no map selection.
        units = ([unit for unit, _province in selected_records]
                 if selected_records else self.target_province.get("units", []))
        cleared_any = False
        cancelled_orders = []
        cancelled_targeting = self.bombarding_unit_index is not None
        self.cancel_bombard_targeting(refresh=False)
        played_sound = False

        for unit in units:
            if unit.get("owner") == self.map_screen.player_country and not self._command_blocked_silent(unit):
                if "order" in unit:
                    province = next(province for province in self.map_screen.map_data.values()
                                    if any(current is unit for current in province.get("units", [])))
                    had_order = bool(unit["order"])
                    result = unit_actions.cancel_action(self.map_screen, unit["owner"], province, unit)
                    if had_order:
                        cancelled_orders.append(result)
                    cleared_any = True

        if cleared_any:
            played_sound = self._play_order_sound("cancel_orders", cancelled_orders)
            self._mark_draft_changed()
            self.map_screen.show_feedback("All orders cleared")
        if cleared_any or cancelled_targeting:
            self.refresh_ui()
        return played_sound

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
            help_text = self._hovered_action_help(mouse_pos)

        if help_text is None:
            help_text = self._active_command_help()
        if help_text is None:
            if read_only:
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

    def additional_draw(self, surface):
        if not self.map_screen or not self.target_province:
            return

        self.map_screen.draw_clean_map_background(surface)

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
        # opaque roster is painted.
        self._draw_selected_order_paths(
            surface, [(unit, origin) for _key, unit, origin, _index in rows], owner_color)

        style = ORDERS_PANEL_STYLES["main"]
        ui_elements.draw_pixel_panel(
            surface, self.panel_rect, style["color"], PANEL_BORDER_COLOR,
            gradient_strength=style["gradient_strength"])
        self._draw_panel_header(surface, rows, player_units, read_only)

        content_rect = self.scroll_content_rect or pygame.Rect(
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

    def draw(self, surface):
        """Draw army editing modals after Orders' button elements.

        Screen draws elements after ``additional_draw``.  The army tray is
        map content, but its editor is modal UI and must sit over the command
        buttons rather than behind them.
        """
        super().draw(surface)
        army_panel.draw_editors_over_map(self.map_screen, surface)
