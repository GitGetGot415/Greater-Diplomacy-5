import pygame
import data.constants as c
from gameState import GameState, resolve_keybind
from ui_elements import Button, process_text_input
from map_logic.rendering.font_manager import fonts
from data import queries
from map_logic.rendering import symbol_loader
from map_logic.rendering import province_select
from map_logic.rendering import overlay_renderer
from ui.bars import ui_bars, resource_hud
from map_logic.camera import camera_handler

# ==========================================
# LAYOUT
# ==========================================

BACK_BTN_X = 50
TOP_BTN_ROW_Y = 90
TOP_BTN_OFFSET_X = 20
TOP_BTN_STEP_X = 100

# Per-unit row: icon button on the left, then the action buttons.
UNIT_ICON_OFFSET_X = 20
UNIT_ROW_TEXT_OFFSET_Y = -5
UNIT_NAME_OFFSET_X = 10
UNIT_STATS_OFFSET_X = 80
UNIT_STATS_OFFSET_Y = 15
UNIT_ICON_OFFSET_Y = 15

# X of each action button, measured from ACTION_START_OFFSET_X. Every entry after
# the first is an "orders_panel_button_2"; the conversion button is the wider
# "orders_panel_button", which is why the first gap is bigger than the rest.
ACTION_START_OFFSET_X = 200
ACTION_COL_CONVERT = 0
ACTION_COL_DISBAND = 80
ACTION_COL_REPAIR = 140
ACTION_COL_RENAME = 200
ACTION_COL_UPGRADE = 260
ACTION_COL_BOMBARD = 320

# Inline rename box, anchored off the rename button's column.
RENAME_BOX_OFFSET_X = ACTION_COL_RENAME + 80
RENAME_BOX_SIZE = (120, 25)

# Path / bombardment footer inside a unit row.
PATH_TEXT_OFFSET_X = 60
PATH_ROW_OFFSET_Y = -20
CANCEL_BOX_OFFSET_X = 20
CANCEL_BOX_OFFSET_Y = -25
CANCEL_BOX_SIZE = 25

PANEL_BG_COLOR = (30, 30, 50)
PANEL_BORDER_COLOR = (100, 100, 250)
SCROLLBAR_OFFSET_X = -10
SCROLLBAR_WIDTH = 10

TARGET_MARKER_RADIUS = 12
TARGET_MARKER_THICKNESS = 3
MOVE_TARGET_COLOR = (0, 255, 0)
BOMBARD_TARGET_COLOR = (255, 200, 50)
BOMBARD_PREVIEW_ALPHA = 160

WHEEL_SCROLL_STEP = 30
UNIT_ICON_ZOOM = 1.5


class Orders_Screen(GameState):
    back_state = "MAP"
    PANEL_X = 20
    # Wide enough to cover the whole button row (Bombard is the rightmost),
    # so clicking a button never doubles as a click on the map underneath.
    PANEL_WIDTH = 600
    PANEL_TRANSPARENCY = 255
    bottom_vanish_y = 20

    def __init__(self):
        super().__init__()
        self.target_province = None
        self.map_screen = None
        self.selected_unit_index = None
        self.cancel_rects = []

        self.renaming_unit_index = None
        self.rename_text = ""

        # Index of the unit currently waiting for the player to click a tile to shell
        self.bombarding_unit_index = None

        self.scroll_y = 0
        self.max_scroll_y = 0
        self.row_height = 80
        self.panel_top = 180
        self.panel_max_h = 420
        
        self.unit_library = queries.get_unit_library()

    def start_with_province(self, province, map_ref):
        self.target_province = province
        self.map_screen = map_ref
        self.scroll_y = 0
        self.bombarding_unit_index = None

        # Shift the camera left so this panel doesn't cover the unit it's showing orders for.
        camera_handler.center_camera_on_province(
            self.map_screen.camera, province["center"], c.SCREEN_WIDTH, c.SCREEN_HEIGHT,
            self.map_screen.total_ui_h, x_offset=c.ORDERS_PANEL_CAMERA_X_OFFSET)

        # --- Auto-select logic ---
        units = self.target_province.get("units", [])
        
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
            
        self.refresh_ui()

    def exit_screen(self):
        # Undo the left shift applied in start_with_province so the map isn't
        # left off-center once the orders panel is gone.
        if self.map_screen and self.target_province:
            camera_handler.center_camera_on_province(
                self.map_screen.camera, self.target_province["center"], c.SCREEN_WIDTH, c.SCREEN_HEIGHT,
                self.map_screen.total_ui_h)
        super().exit_screen()

    def select_unit(self, index):
        if self.map_screen.tactical_mode:
            self.map_screen.show_feedback("Tactical Mode: You can only command your specific unit!")
            return
        self.selected_unit_index = index
        self.bombarding_unit_index = None
        self.refresh_ui()

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

    def refresh_ui(self):
        self.elements = [Button(BACK_BTN_X, c.TOP_BAR_UI_CENTER_Y, "small", "red", "Back", self.exit_screen)]
        
        units = self.target_province.get("units", [])
        is_tactical = self.map_screen.tactical_mode
        player_research = self.map_screen.nation_data.get(self.map_screen.player_country, {}).get("research", {})

        # Display all units owned by the player, regardless of mode
        player_units = [u for u in units if u.get("owner") == self.map_screen.player_country]
        
        total_content_h = len(player_units) * self.row_height
        self.max_scroll_y = min(0, self.panel_max_h - total_content_h - 20)

        self.scroll_content_rect = pygame.Rect(self.PANEL_X, self.panel_top, self.PANEL_WIDTH, self.panel_max_h)
        row_guard = lambda rect=self.scroll_content_rect: rect.collidepoint(pygame.mouse.get_pos())

        # --- Select All & Clear Orders Buttons ---
        if player_units:
            if len(player_units) > 1:
                all_color = "grey" if is_tactical else ("blue" if self.selected_unit_index == "ALL" else "grey")
                btn_all = Button(self.PANEL_X + TOP_BTN_OFFSET_X, TOP_BTN_ROW_Y, "top_orders_panel_button", all_color, "Select All", lambda: self.select_unit("ALL"), font_preset="normal")
                if is_tactical: btn_all.disabled = True
                self.elements.append(btn_all)

                btn_clear = Button(self.PANEL_X + TOP_BTN_OFFSET_X + TOP_BTN_STEP_X, TOP_BTN_ROW_Y, "top_orders_panel_button", "red", "Clear Orders", self.clear_all_orders, font_preset="normal")
                self.elements.append(btn_clear)
            else:
                # If there's only 1 unit, just put the clear orders button where select all would have been
                btn_clear = Button(self.PANEL_X + TOP_BTN_OFFSET_X, TOP_BTN_ROW_Y, "top_orders_panel_button", "red", "Clear Orders", self.clear_all_orders, font_preset="normal")
                self.elements.append(btn_clear)

        display_index = 0
        for i, unit in enumerate(units):
            if unit.get("owner") != self.map_screen.player_country:
                continue
                
            is_tactical_other = is_tactical and unit is not self.map_screen.player_unit
                
            y_pos = self.panel_top + (display_index * self.row_height) + self.scroll_y
            y_pos = y_pos + UNIT_ICON_OFFSET_Y
            
            if self.panel_top - 10 < y_pos < self.panel_top + self.panel_max_h - self.bottom_vanish_y:
                color = "blue" if self.selected_unit_index == i or self.selected_unit_index == "ALL" else "grey"
                unit_name = unit["type"]
                
                # Fetch the icon using the symbol_loader (zoom 1.5 is a standard starting scale)
                unit_icon = self.fit_icon(symbol_loader.get_symbol(unit_name, zoom=UNIT_ICON_ZOOM), "medium_square")

                # Create the button with the icon and set show_text=False
                btn_sel = Button(self.PANEL_X + UNIT_ICON_OFFSET_X, y_pos, "medium_square", color, "",
                                lambda idx=i: self.select_unit(idx), 
                                image=unit_icon, 
                                show_text=False)
                self.elements.append(btn_sel)
                
                order = unit.get("order", {})
                order_type = order.get("type", "")

                # Combat / Location checks
                player_country = self.map_screen.player_country
                in_combat = queries.is_nation_in_combat_here(player_country, self.target_province, self.map_screen.nation_data)
                is_water = queries.is_water_province(self.target_province)
                is_coastal = self.target_province.get("is_coastal", False)
                
                is_convoy = unit_name.startswith("Convoy")
                is_truck = unit_name.startswith("Truck")
                is_naval = queries.is_naval_unit(unit_name)

                x_pos = self.PANEL_X + ACTION_START_OFFSET_X

                # 2. Inline Convoy Conversion Button
                if order_type == "CONVERT":
                    btn_conv = Button(x_pos + ACTION_COL_CONVERT, y_pos, "orders_panel_button", "red", "Cancel Conversion", lambda idx=i: self.cancel_unit_order(idx), font_preset="normal")
                elif in_combat:
                    btn_conv = Button(x_pos + ACTION_COL_CONVERT, y_pos, "orders_panel_button", "grey", "In Combat", lambda: None, font_preset="normal")
                elif is_convoy:
                    if not is_water:
                        btn_conv = Button(x_pos + ACTION_COL_CONVERT, y_pos, "orders_panel_button", "blue", "To Land", lambda idx=i: self.convert_unit(idx), font_preset="normal")
                    else:
                        btn_conv = Button(x_pos + ACTION_COL_CONVERT, y_pos, "orders_panel_button", "grey", "Need Land", lambda: None, font_preset="normal")
                elif is_truck:
                    if is_coastal or is_water:
                        btn_conv = Button(x_pos + ACTION_COL_CONVERT, y_pos, "orders_panel_button", "blue", "To Ship", lambda idx=i: self.convert_unit(idx), font_preset="normal")
                    else:
                        btn_conv = Button(x_pos + ACTION_COL_CONVERT, y_pos, "orders_panel_button", "grey", "Req Coast", lambda: None, font_preset="normal")
                elif not is_naval:
                    if is_coastal or is_water:
                        btn_conv = Button(x_pos + ACTION_COL_CONVERT, y_pos, "orders_panel_button", "blue", "To Convoy", lambda idx=i: self.convert_unit(idx), font_preset="normal")
                    else:
                        btn_conv = Button(x_pos + ACTION_COL_CONVERT, y_pos, "orders_panel_button", "grey", "Req Coast", lambda: None, font_preset="normal")
                else: # is_naval
                    if player_research.get("trucks", 0) < 1:
                        btn_conv = Button(x_pos + ACTION_COL_CONVERT, y_pos, "orders_panel_button", "grey", "Req Trucks", lambda: None, font_preset="normal")
                    elif is_coastal or not is_water:
                        btn_conv = Button(x_pos + ACTION_COL_CONVERT, y_pos, "orders_panel_button", "blue", "To Truck", lambda idx=i: self.convert_unit(idx), font_preset="normal")
                    else:
                        btn_conv = Button(x_pos + ACTION_COL_CONVERT, y_pos, "orders_panel_button", "grey", "Req Coast", lambda: None, font_preset="normal")
                
                self.elements.append(btn_conv)

                # 3. Inline Disband Button
                if order_type == "DISBAND":
                    btn_disband = Button(x_pos + ACTION_COL_DISBAND, y_pos, "orders_panel_button_2", "red", "Cancel Disband", lambda idx=i: self.cancel_unit_order(idx), font_preset="normal")
                else:
                    if is_tactical and unit is self.map_screen.player_unit:
                        btn_disband = Button(x_pos + ACTION_COL_DISBAND, y_pos, "orders_panel_button_2", "grey", "Cannot Disband", lambda: None, font_preset="normal")
                    else:
                        btn_disband = Button(x_pos + ACTION_COL_DISBAND, y_pos, "orders_panel_button_2", "red", "Disband", lambda idx=i: self.disband_unit(idx), font_preset="normal")
                
                self.elements.append(btn_disband)

                hp = int(unit.get("health", 0))
                m_hp = int(unit.get("max_health", 1))
                is_factory = queries.has_industry(self.target_province)

                if order_type == "REPAIR":
                    btn_repair = Button(x_pos + ACTION_COL_REPAIR, y_pos, "orders_panel_button_2", "orange", "Cancel Repair", lambda idx=i: self.cancel_unit_order(idx), font_preset="normal")
                elif hp < m_hp:
                    if in_combat:
                        btn_repair = Button(x_pos + ACTION_COL_REPAIR, y_pos, "orders_panel_button_2", "grey", "In Combat", lambda: None, font_preset="normal")
                    elif is_factory:
                        btn_repair = Button(x_pos + ACTION_COL_REPAIR, y_pos, "orders_panel_button_2", "green", "Repair", lambda idx=i: self.repair_unit(idx), font_preset="normal")
                    else:
                        btn_repair = Button(x_pos + ACTION_COL_REPAIR, y_pos, "orders_panel_button_2", "grey", "Needs Factory", lambda: None, font_preset="normal")
                else:
                    btn_repair = Button(x_pos + ACTION_COL_REPAIR, y_pos, "orders_panel_button_2", "grey", "Full HP", lambda: None, font_preset="normal")

                self.elements.append(btn_repair)

                if self.renaming_unit_index == i:
                    btn_rename = Button(x_pos + ACTION_COL_RENAME, y_pos, "orders_panel_button_2", "green", "Save Name", lambda idx=i: self.save_unit_name(idx), font_preset="normal")
                else:
                    btn_rename = Button(x_pos + ACTION_COL_RENAME, y_pos, "orders_panel_button_2", "blue", "Rename", lambda idx=i: self.start_renaming(idx), font_preset="normal")

                self.elements.append(btn_rename)

                # Upgrade Button Logic
                if order_type == "UPGRADE":
                    btn_upgrade = Button(x_pos + ACTION_COL_UPGRADE, y_pos, "orders_panel_button_2", "red", "Cancel Upgrade", lambda idx=i: self.cancel_unit_order(idx), font_preset="normal")
                else:
                    upgrade_target = queries.get_upgrade_target(unit_name, self.map_screen.nation_data.get(self.map_screen.player_country, {}).get("research", {}), self.unit_library, queries.get_tech_tree())
                    if upgrade_target:
                        if in_combat:
                            btn_upgrade = Button(x_pos + ACTION_COL_UPGRADE, y_pos, "orders_panel_button_2", "grey", "In Combat", lambda: None, font_preset="normal")
                        elif is_factory:
                            btn_upgrade = Button(x_pos + ACTION_COL_UPGRADE, y_pos, "orders_panel_button_2", "orange", "Upgrade", lambda idx=i, tgt=upgrade_target: self.upgrade_unit(idx, tgt), font_preset="normal")
                        else:
                            btn_upgrade = Button(x_pos + ACTION_COL_UPGRADE, y_pos, "orders_panel_button_2", "grey", "Needs Factory", lambda: None, font_preset="normal")
                    else:
                        btn_upgrade = Button(x_pos + ACTION_COL_UPGRADE, y_pos, "orders_panel_button_2", "grey", "Max Level", lambda: None, font_preset="normal")

                self.elements.append(btn_upgrade)

                # Bombardment Button Logic
                # Every unit shows the button so the option is discoverable; only the
                # classes in c.BOMBARDMENT_UNITS (artillery) get a live one.
                if order_type == "BOMBARD":
                    btn_bombard = Button(x_pos + ACTION_COL_BOMBARD, y_pos, "orders_panel_button_2", "red", "Cancel Bomb.", lambda idx=i: self.cancel_unit_order(idx), font_preset="normal")
                elif not queries.can_bombard(unit_name):
                    btn_bombard = Button(x_pos + ACTION_COL_BOMBARD, y_pos, "orders_panel_button_2", "grey", "No Bombard", lambda: None, font_preset="normal")
                elif self.bombarding_unit_index == i:
                    btn_bombard = Button(x_pos + ACTION_COL_BOMBARD, y_pos, "orders_panel_button_2", "orange", "Pick Tile", lambda: self.cancel_bombard_targeting(), font_preset="normal")
                else:
                    btn_bombard = Button(x_pos + ACTION_COL_BOMBARD, y_pos, "orders_panel_button_2", "yellow", "Bombard", lambda idx=i: self.start_bombard_targeting(idx), font_preset="normal")

                if not queries.can_bombard(unit_name):
                    btn_bombard.disabled = True

                self.elements.append(btn_bombard)

                if is_tactical_other:
                    for b in [btn_sel, btn_conv, btn_disband, btn_repair, btn_rename, btn_bombard]:
                        b.apply_state(enabled=False)

                for b in (btn_sel, btn_conv, btn_disband, btn_repair, btn_rename, btn_bombard):
                    b.is_scrollable = True
                    b.click_guard = row_guard

            display_index += 1

    def start_renaming(self, index):
        self.renaming_unit_index = index
        units = self.target_province.get("units", [])
        if 0 <= index < len(units):
            self.rename_text = units[index].get("custom_name", "")
        self.refresh_ui()

    def save_unit_name(self, index):
        units = self.target_province.get("units", [])
        if 0 <= index < len(units):
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

        units = self.target_province.get("units", [])
        if not (0 <= index < len(units)): return

        unit = units[index]
        u_type = unit.get("original_type", unit.get("type", ""))
        stats = self.unit_library.get(u_type, {})

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

        units = self.target_province.get("units", [])
        if not (0 <= index < len(units)): return

        unit = units[index]
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
        units = self.target_province.get("units", [])
        if not (0 <= index < len(units)): return

        if self.map_screen.tactical_mode and units[index] is not self.map_screen.player_unit:
            self.map_screen.show_feedback("Tactical Mode: You can only command your specific unit!")
            return

        self.bombarding_unit_index = index
        self.map_screen.show_feedback("Select a tile within range to bombard.")
        self.refresh_ui()

    def cancel_bombard_targeting(self):
        self.bombarding_unit_index = None
        self.refresh_ui()

    def set_bombard_target(self, index, dest):
        units = self.target_province.get("units", [])
        if not (0 <= index < len(units)):
            self.bombarding_unit_index = None
            return

        unit = units[index]
        bomb_range = queries.get_bombardment_range(unit.get("type", ""))
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
        units = self.target_province.get("units", [])
        if 0 <= index < len(units):
            unit = units[index]
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

        units = self.target_province.get("units", [])
        if 0 <= index < len(units):
            unit = units[index]
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
        units = self.target_province.get("units", [])
        if 0 <= index < len(units):
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
        units = self.target_province.get("units", [])
        cleared_any = False
        self.bombarding_unit_index = None

        for unit in units:
            if unit.get("owner") == self.map_screen.player_country:
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
            self.refresh_ui()

    def handle_back_key(self):
        # Escape drops a pending bombardment target before it leaves the screen.
        if self.bombarding_unit_index is not None:
            self.cancel_bombard_targeting()
        else:
            self.exit_screen()

    def handle_events(self, events):
        for event in events:
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
                # Only scroll if mouse is over the orders panel
                mx, my = pygame.mouse.get_pos()
                units = self.target_province.get("units", [])

                if self.map_screen.tactical_mode:
                    player_units = [u for u in units if u is self.map_screen.player_unit]
                else:
                    player_units = [u for u in units if u.get("owner") == self.map_screen.player_country]

                # Check for collision if units exist
                if player_units:
                    bg_rect = pygame.Rect(self.PANEL_X, self.panel_top, self.PANEL_WIDTH, self.panel_max_h)
                    if bg_rect.collidepoint(mx, my):
                        self.scroll_by(event, attr="scroll_y", limit_attr="max_scroll_y", speed=WHEEL_SCROLL_STEP)

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

        # --- Block clicks inside the Orders Panel ---
        # Define the panel area
        panel_rect = pygame.Rect(self.PANEL_X, self.panel_top, self.PANEL_WIDTH, self.panel_max_h)
        
        # Camera Controls (Zooming and Panning) 
        on_ui = False
        units = self.target_province.get("units", [])
        
        if self.map_screen.tactical_mode:
            player_units = [u for u in units if u is self.map_screen.player_unit]
        else:
            player_units = [u for u in units if u.get("owner") == self.map_screen.player_country]
            
        if player_units:
            bg_rect = pygame.Rect(self.PANEL_X, self.panel_top, self.PANEL_WIDTH, self.panel_max_h)
            if bg_rect.collidepoint(mx, my):
                on_ui = True
                
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

            units = self.target_province.get("units", [])

            if self.selected_unit_index == "ALL":
                target_units = [u for u in units if u.get("owner") == self.map_screen.player_country]
            elif 0 <= self.selected_unit_index < len(units):
                target_units = [units[self.selected_unit_index]]
            else:
                target_units = []

            if not target_units: return

            if any(isinstance(u.get("order"), dict) and u["order"].get("type") in ["CONVERT", "DISBAND", "REPAIR", "BOMBARD"] for u in target_units):
                self.map_screen.show_feedback("Cannot move while converting, disbanding, repairing, or bombarding!")
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

    def draw_order_footer(self, surface, font, unit_index, y_pos, text, color):
        """Draws a unit row's order line (path or barrage) and its cancel box."""
        footer_y = y_pos + self.row_height
        surface.blit(font.render(text, True, color), (self.PANEL_X + PATH_TEXT_OFFSET_X, footer_y + PATH_ROW_OFFSET_Y))

        cancel_rect = pygame.Rect(self.PANEL_X + CANCEL_BOX_OFFSET_X, footer_y + CANCEL_BOX_OFFSET_Y, CANCEL_BOX_SIZE, CANCEL_BOX_SIZE)
        pygame.draw.rect(surface, (150, 0, 0), cancel_rect)
        x_label = font.render("X", True, (255, 255, 255))
        surface.blit(x_label, x_label.get_rect(center=cancel_rect.center))
        self.cancel_rects.append((cancel_rect, unit_index))

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

        self.map_screen.draw_clean_map_background(surface)

        province_select.draw_province_select(self.map_screen, surface)

        self.cancel_rects = []
        
        font = fonts.get("heading1")
        small_font = fonts.get("normal")
        
        ui_bars.draw_centered_title(surface, f"Orders: Province {self.target_province['id']}", c.TOP_BAR_UI_CENTER_Y)
        
        # --- Draw Background Panel for Units ---
        units = self.target_province.get("units", [])
        player_units = [u for u in units if u.get("owner") == self.map_screen.player_country]
        
        # Dynamically fetch the player's color
        owner_color = self.map_screen.nation_colors.get(self.map_screen.player_country, (255, 255, 0))
        
        if player_units:
            bg_rect = pygame.Rect(self.PANEL_X, self.panel_top, self.PANEL_WIDTH, self.panel_max_h)
            
            # Draw semi-transparent panel
            panel_surf = pygame.Surface((bg_rect.width, bg_rect.height), pygame.SRCALPHA)
            panel_surf.fill((*PANEL_BG_COLOR, self.PANEL_TRANSPARENCY))
            surface.blit(panel_surf, bg_rect.topleft)
            
            # Draw border
            pygame.draw.rect(surface, PANEL_BORDER_COLOR, bg_rect, 2)
            
            # --- NEW: Scroll Bar Rendering ---
            self.scroll_track_rect, self.scroll_handle_rect = ui_bars.draw_standard_scrollbar(
                surface, self.scroll_y, self.max_scroll_y, self.PANEL_X + SCROLLBAR_OFFSET_X, self.panel_top, self.panel_max_h, width=SCROLLBAR_WIDTH
            )

        display_index = 0
        content_rect = getattr(self, 'scroll_content_rect', None) or pygame.Rect(
            self.PANEL_X, self.panel_top, self.PANEL_WIDTH, self.panel_max_h)
        with ui_bars.clip_scroll_region(surface, content_rect,
                                        draw_top=self.scroll_y != 0, draw_bottom=self.scroll_y > self.max_scroll_y):
            for i, unit in enumerate(units):
                if unit.get("owner") != self.map_screen.player_country:
                    continue

                y_pos = self.panel_top + (display_index * self.row_height) + self.scroll_y

                # Replaced the hardcoded '20' with 'self.row_height' to match refresh_ui
                if self.panel_top - 10 < y_pos < self.panel_top + self.panel_max_h - self.bottom_vanish_y:
                    hp = int(unit.get("health", 0))
                    m_hp = int(unit.get("max_health", 0))

                    name_txt = unit.get("custom_name", unit.get("type", "Unit"))
                    name_surf = small_font.render(name_txt, True, (255, 255, 255))
                    surface.blit(name_surf, (self.PANEL_X + UNIT_NAME_OFFSET_X, y_pos + UNIT_ROW_TEXT_OFFSET_Y))

                    stats_txt = f"HP: {queries.format_number(hp)}/{queries.format_number(m_hp)}"
                    txt_surf = small_font.render(stats_txt, True, (200, 200, 200))

                    surface.blit(txt_surf, (self.PANEL_X + UNIT_STATS_OFFSET_X, y_pos + UNIT_STATS_OFFSET_Y))

                    if self.renaming_unit_index == i:
                        box_rect = pygame.Rect(self.PANEL_X + ACTION_START_OFFSET_X + RENAME_BOX_OFFSET_X, y_pos, *RENAME_BOX_SIZE)
                        pygame.draw.rect(surface, (60, 60, 80), box_rect)
                        pygame.draw.rect(surface, (150, 150, 150), box_rect, 1)
                        txt = small_font.render(self.rename_text + "|", True, (255, 255, 255))
                        surface.blit(txt, (box_rect.x + 5, box_rect.y + 4))

                    order = unit.get("order", {})
                    path = order.get("path", [])

                    # An active path and an active barrage show the same footer
                    # line plus a cancel box, so they share one draw call.
                    if path:
                        self.draw_order_footer(surface, small_font, i, y_pos,
                                               f"PATH: {' -> '.join(map(str, path))}", (255, 255, 0))

                        # Split draw using the helper function
                        overlay_renderer.draw_split_movement_path(surface, self.map_screen, self.target_province, path, unit.get("speed", 1), owner_color, force_visible=True)

                    elif order.get("type") == "BOMBARD":
                        target_id = order.get("target_id")
                        self.draw_order_footer(surface, small_font, i, y_pos,
                                               f"BOMBARDING: {target_id}", BOMBARD_TARGET_COLOR)

                        bomb_range = queries.get_bombardment_range(unit.get("type", ""))
                        overlay_renderer.draw_bombardment_arrow(surface, self.map_screen, self.target_province, target_id, bomb_range, force_visible=True)

                display_index += 1

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

        resource_hud.draw_resource_bar(surface, self.map_screen)

    def update(self):
        super().update()
        # Ensure the camera keeps running its smooth zoom/pan lerp math 
        # even when the Orders screen is the active state
        if self.map_screen:
            self.map_screen.camera.update(self.map_screen, c.SCREEN_HEIGHT)

