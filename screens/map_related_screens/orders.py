import pygame
import json
import os
import gameState as g
import data.constants as c
from gameState import GameState
from ui_elements import Button, process_text_input
from map_logic.rendering.font_manager import fonts
from data import queries
from map_logic.rendering import symbol_loader
from map_logic.rendering import province_select
from map_logic.rendering import overlay_renderer
from ui.bars import ui_bars

class Orders_Screen(GameState):
    PANEL_X = 80
    PANEL_WIDTH = 600
    PANEL_TRANSPARENCY = 255
    bottom_vanish_y = 20

    def __init__(self):
        super().__init__()
        self.bg_color = (20, 20, 40)
        self.target_province = None
        self.map_screen = None
        self.selected_unit_index = None 
        self.cancel_rects = []
        
        self.renaming_unit_index = None
        self.rename_text = ""
        
        self.scroll_y = 0
        self.max_scroll_y = 0
        self.row_height = 80
        self.panel_top = 180
        self.panel_max_h = 420
        
        self.unit_library = queries.get_unit_library()

    def draw(self, surface):
        super().draw(surface)
        from ui.information import feedback_text
        feedback_text.draw_feedback(self.map_screen, surface)

    def start_with_province(self, province, map_ref):
        self.target_province = province
        self.map_screen = map_ref
        self.scroll_y = 0 
        
        # --- Auto-select logic ---
        units = self.target_province.get("units", [])
        
        if getattr(self.map_screen, 'tactical_mode', False):
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

    def select_unit(self, index):
        if getattr(self.map_screen, 'tactical_mode', False):
            self.map_screen.show_feedback("Tactical Mode: You can only command your specific unit!")
            return
        self.selected_unit_index = index
        self.refresh_ui()

    def refresh_ui(self):
        self.elements = [Button(50, c.TOP_BAR_UI_CENTER_Y, "small", "red", "Back", self.exit_to_map)]
        
        units = self.target_province.get("units", [])
        is_tactical = getattr(self.map_screen, 'tactical_mode', False)
        
        # Display all units owned by the player, regardless of mode
        player_units = [u for u in units if u.get("owner") == self.map_screen.player_country]
        
        total_content_h = len(player_units) * self.row_height
        self.max_scroll_y = min(0, self.panel_max_h - total_content_h - 20)

        # --- Select All & Clear Orders Buttons ---
        if player_units:
            if len(player_units) > 1:
                all_color = "grey" if is_tactical else ("blue" if self.selected_unit_index == "ALL" else "grey")
                btn_all = Button(100, 90, "top_orders_panel_button", all_color, "Select All", lambda: self.select_unit("ALL"), font_preset="normal")
                if is_tactical: btn_all.disabled = True
                self.elements.append(btn_all)
                
                btn_clear = Button(200, 90, "top_orders_panel_button", "red", "Clear Orders", self.clear_all_orders, font_preset="normal")
                self.elements.append(btn_clear)
            else:
                # If there's only 1 unit, just put the clear orders button where select all would have been
                btn_clear = Button(100, 90, "top_orders_panel_button", "red", "Clear Orders", self.clear_all_orders, font_preset="normal")
                self.elements.append(btn_clear)

        display_index = 0
        for i, unit in enumerate(units):
            if unit.get("owner") != self.map_screen.player_country:
                continue
                
            is_tactical_other = is_tactical and unit is not self.map_screen.player_unit
                
            y_pos = self.panel_top + (display_index * self.row_height) + self.scroll_y
            y_pos = y_pos + 15
            
            if self.panel_top - 10 < y_pos < self.panel_top + self.panel_max_h - self.bottom_vanish_y:
                color = "blue" if self.selected_unit_index == i or self.selected_unit_index == "ALL" else "grey"
                unit_name = unit["type"]
                
                # Fetch the icon using the symbol_loader (zoom 1.5 is a standard starting scale)
                unit_icon = symbol_loader.get_symbol(unit_name, zoom=1.5)
                
                # Create the button with the icon and set show_text=False
                btn_sel = Button(100, y_pos, "medium_square", color, "", 
                                lambda idx=i: self.select_unit(idx), 
                                image=unit_icon, 
                                show_text=False)
                self.elements.append(btn_sel)
                
                order = unit.get("order", {})
                order_type = order.get("type", "")

                # Combat / Location checks
                player_country = self.map_screen.player_country
                in_combat = queries.is_nation_in_combat_here(player_country, self.target_province, self.map_screen.nation_data)
                is_water = self.target_province.get("terrain") in c.WATER_TERRAINS
                is_coastal = self.target_province.get("is_coastal", False)
                
                is_convoy = unit_name.startswith("Convoy")
                is_truck = unit_name.startswith("Truck")
                is_naval = queries.is_naval_unit(unit_name)

                x_pos = 280

                # 2. Inline Convoy Conversion Button
                if order_type == "CONVERT":
                    btn_conv = Button(x_pos, y_pos, "orders_panel_button", "red", "Cancel Conversion", lambda idx=i: self.cancel_unit_order(idx), font_preset="normal")
                elif in_combat:
                    btn_conv = Button(x_pos, y_pos, "orders_panel_button", "grey", "In Combat", lambda: None, font_preset="normal")
                elif is_convoy:
                    if not is_water:
                        btn_conv = Button(x_pos, y_pos, "orders_panel_button", "blue", "To Land", lambda idx=i: self.convert_unit(idx), font_preset="normal")
                    else:
                        btn_conv = Button(x_pos, y_pos, "orders_panel_button", "grey", "Need Land", lambda: None, font_preset="normal")
                elif is_truck:
                    if is_coastal or is_water:
                        btn_conv = Button(x_pos, y_pos, "orders_panel_button", "blue", "To Ship", lambda idx=i: self.convert_unit(idx), font_preset="normal")
                    else:
                        btn_conv = Button(x_pos, y_pos, "orders_panel_button", "grey", "Req Coast", lambda: None, font_preset="normal")
                elif not is_naval:
                    if is_coastal or is_water:
                        btn_conv = Button(x_pos, y_pos, "orders_panel_button", "blue", "To Convoy", lambda idx=i: self.convert_unit(idx), font_preset="normal")
                    else:
                        btn_conv = Button(x_pos, y_pos, "orders_panel_button", "grey", "Req Coast", lambda: None, font_preset="normal")
                else: # is_naval
                    if is_coastal or not is_water:
                        btn_conv = Button(x_pos, y_pos, "orders_panel_button", "blue", "To Truck", lambda idx=i: self.convert_unit(idx), font_preset="normal")
                    else:
                        btn_conv = Button(x_pos, y_pos, "orders_panel_button", "grey", "Req Coast", lambda: None, font_preset="normal")
                
                self.elements.append(btn_conv)

                # 3. Inline Disband Button
                if order_type == "DISBAND":
                    btn_disband = Button(x_pos + 85, y_pos, "orders_panel_button_2", "red", "Cancel Disband", lambda idx=i: self.cancel_unit_order(idx), font_preset="normal")
                else:
                    if is_tactical and unit is self.map_screen.player_unit:
                        btn_disband = Button(x_pos + 85, y_pos, "orders_panel_button_2", "grey", "Cannot Disband", lambda: None, font_preset="normal")
                    else:
                        btn_disband = Button(x_pos + 85, y_pos, "orders_panel_button_2", "red", "Disband", lambda idx=i: self.disband_unit(idx), font_preset="normal")
                
                self.elements.append(btn_disband)

                hp = int(unit.get("health", 0))
                m_hp = int(unit.get("max_health", 1))
                is_factory = queries.has_industry(self.target_province)

                if order_type == "REPAIR":
                    btn_repair = Button(x_pos + 160, y_pos, "orders_panel_button_2", "orange", "Cancel Repair", lambda idx=i: self.cancel_unit_order(idx), font_preset="normal")
                elif hp < m_hp:
                    if in_combat:
                        btn_repair = Button(x_pos + 160, y_pos, "orders_panel_button_2", "grey", "In Combat", lambda: None, font_preset="normal")
                    elif is_factory:
                        btn_repair = Button(x_pos + 160, y_pos, "orders_panel_button_2", "green", "Repair", lambda idx=i: self.repair_unit(idx), font_preset="normal")
                    else:
                        btn_repair = Button(x_pos + 160, y_pos, "orders_panel_button_2", "grey", "Needs Factory", lambda: None, font_preset="normal")
                else:
                    btn_repair = Button(x_pos + 160, y_pos, "orders_panel_button_2", "grey", "Full HP", lambda: None, font_preset="normal")

                self.elements.append(btn_repair)

                if self.renaming_unit_index == i:
                    btn_rename = Button(x_pos + 235, y_pos, "orders_panel_button_2", "green", "Save Name", lambda idx=i: self.save_unit_name(idx), font_preset="normal")
                else:
                    btn_rename = Button(x_pos + 235, y_pos, "orders_panel_button_2", "blue", "Rename", lambda idx=i: self.start_renaming(idx), font_preset="normal")

                self.elements.append(btn_rename)

                # Upgrade Button Logic
                if order_type == "UPGRADE":
                    btn_upgrade = Button(x_pos + 310, y_pos, "orders_panel_button_2", "red", "Cancel Upgrade", lambda idx=i: self.cancel_unit_order(idx), font_preset="normal")
                else:
                    upgrade_target = queries.get_upgrade_target(unit_name, self.map_screen.nation_data.get(self.map_screen.player_country, {}).get("research", {}), self.unit_library, queries.get_tech_tree())
                    if upgrade_target:
                        if in_combat:
                            btn_upgrade = Button(x_pos + 310, y_pos, "orders_panel_button_2", "grey", "In Combat", lambda: None, font_preset="normal")
                        elif is_factory:
                            btn_upgrade = Button(x_pos + 310, y_pos, "orders_panel_button_2", "orange", "Upgrade", lambda idx=i, tgt=upgrade_target: self.upgrade_unit(idx, tgt), font_preset="normal")
                        else:
                            btn_upgrade = Button(x_pos + 310, y_pos, "orders_panel_button_2", "grey", "Needs Factory", lambda: None, font_preset="normal")
                    else:
                        btn_upgrade = Button(x_pos + 310, y_pos, "orders_panel_button_2", "grey", "Max Level", lambda: None, font_preset="normal")

                self.elements.append(btn_upgrade)

                if is_tactical_other:
                    for b in [btn_sel, btn_conv, btn_disband, btn_repair, btn_rename]:
                        b.disabled = True
                        b.color = b.hover_color = c.UI_COLORS["grey"]
            
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
        
        is_tactical = getattr(self.map_screen, 'tactical_mode', False) and unit is getattr(self.map_screen, 'player_unit', None)
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
                    is_tactical = getattr(self.map_screen, 'tactical_mode', False) and unit is getattr(self.map_screen, 'player_unit', None)
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
        
        for unit in units:
            if unit.get("owner") == self.map_screen.player_country:
                if "order" in unit:
                    order = unit["order"]
                    if isinstance(order, dict) and "refund" in order:
                        is_tactical = getattr(self.map_screen, 'tactical_mode', False) and unit is getattr(self.map_screen, 'player_unit', None)
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

    def handle_events(self, events):
        for event in events:
            if event.type == pygame.KEYDOWN and self.renaming_unit_index is not None:
                if event.key == pygame.K_RETURN:
                    self.save_unit_name(self.renaming_unit_index)
                elif event.key == pygame.K_ESCAPE:
                    self.renaming_unit_index = None
                    self.refresh_ui()
                else:
                    self.rename_text, _ = process_text_input(event, self.rename_text, max_length=50)
                return

            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                for rect, idx in self.cancel_rects:
                    if rect.collidepoint(event.pos):
                        self.cancel_unit_order(idx)
                        return
            
            # --- Handle Mousewheel Scrolling ---
            if event.type == pygame.MOUSEWHEEL:
                # Only scroll if mouse is over the orders panel
                mx, my = pygame.mouse.get_pos()
                units = self.target_province.get("units", [])
                
                if getattr(self.map_screen, 'tactical_mode', False):
                    player_units = [u for u in units if u is self.map_screen.player_unit]
                else:
                    player_units = [u for u in units if u.get("owner") == self.map_screen.player_country]
                
                # Check for collision if units exist
                if player_units:
                    bg_rect = pygame.Rect(self.PANEL_X, self.panel_top, self.PANEL_WIDTH, self.panel_max_h)
                    if bg_rect.collidepoint(mx, my):
                        self.scroll_y += event.y * 30
                        self.scroll_y = max(self.max_scroll_y, min(0, self.scroll_y))
                        self.refresh_ui()

            super().handle_events([event])
            self.additional_events(event)

    def additional_events(self, event):
        mx, my = pygame.mouse.get_pos()
        
        # --- Block clicks inside the Orders Panel ---
        # Define the panel area
        panel_rect = pygame.Rect(self.PANEL_X, self.panel_top, self.PANEL_WIDTH, self.panel_max_h)
        
        # Camera Controls (Zooming and Panning) 
        on_ui = False
        units = self.target_province.get("units", [])
        
        if getattr(self.map_screen, 'tactical_mode', False):
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

            if any(isinstance(u.get("order"), dict) and u["order"].get("type") in ["CONVERT", "DISBAND", "REPAIR"] for u in target_units):
                self.map_screen.show_feedback("Cannot move while converting, disbanding, or repairing!")
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
                    if getattr(self.map_screen, 'tactical_mode', False) and self.selected_unit_index != "ALL":
                        unit = target_units[0]
                        if unit is getattr(self.map_screen, 'player_unit', None):
                            speed = queries.get_tactical_speed(unit, self.unit_library)
                            # If this step would execute this turn
                            if len(current_path) < speed:
                                fuel_inc = self.map_screen.unit_economy.get("fuel_inc", 0)
                                cost_per_tile = queries.get_tactical_fuel_cost_per_tile(unit, fuel_inc, self.unit_library)
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
        # Use the constant imported from data.constants
        dest_is_water = dest.get("terrain") in c.WATER_TERRAINS
        
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
            panel_surf.fill((30, 30, 50, self.PANEL_TRANSPARENCY))
            surface.blit(panel_surf, bg_rect.topleft)
            
            # Draw border
            pygame.draw.rect(surface, (100, 100, 250), bg_rect, 2)
            
            # --- NEW: Scroll Bar Rendering ---
            self.scroll_track_rect, self.scroll_handle_rect = ui_bars.draw_standard_scrollbar(
                surface, self.scroll_y, self.max_scroll_y, 70, self.panel_top, self.panel_max_h, width=10
            )

        display_index = 0
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
                surface.blit(name_surf, (90, y_pos - 5))

                stats_txt = f"HP: {hp}/{m_hp}"
                txt_surf = small_font.render(stats_txt, True, (200, 200, 200))
                
                surface.blit(txt_surf, (160, y_pos + 15))

                if self.renaming_unit_index == i:
                    box_rect = pygame.Rect(280 + 315, y_pos, 120, 25)
                    pygame.draw.rect(surface, (60, 60, 80), box_rect)
                    pygame.draw.rect(surface, (150, 150, 150), box_rect, 1)
                    txt = small_font.render(self.rename_text + "|", True, (255, 255, 255))
                    surface.blit(txt, (box_rect.x + 5, box_rect.y + 4))

                order = unit.get("order", {})
                path = order.get("path", [])

                if path:
                    txt = small_font.render(f"PATH: {' -> '.join(map(str, path))}", True, (255, 255, 0))
                    surface.blit(txt, (140, y_pos + self.row_height - 20))
                    
                    cancel_rect = pygame.Rect(100, y_pos + self.row_height - 25, 25, 25)
                    pygame.draw.rect(surface, (150, 0, 0), cancel_rect)
                    x_label = small_font.render("X", True, (255, 255, 255))
                    surface.blit(x_label, x_label.get_rect(center=cancel_rect.center))
                    self.cancel_rects.append((cancel_rect, i))
                    
                    # Split draw using the helper function
                    overlay_renderer.draw_split_movement_path(surface, self.map_screen, self.target_province, path, unit.get("speed", 1), owner_color, force_visible=True)

            display_index += 1

        if self.selected_unit_index is not None:
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
                    for n_id in last_node["neighbors"]:
                        neighbor = self.map_screen.id_to_province.get(n_id)
                        if neighbor:
                            cam = self.map_screen.camera
                            cx, cy = list(neighbor["center"])
                            
                            # Account for map wrap to get the shortest distance
                            if self.map_screen.loop_map:
                                world_dx = cx - last_node["center"][0]
                                if world_dx > self.map_screen.map_w / 2:
                                    cx -= self.map_screen.map_w
                                elif world_dx < -self.map_screen.map_w / 2:
                                    cx += self.map_screen.map_w

                            # Loop the green pathmaking circles so they draw on the seam
                            offsets = [0, -self.map_screen.map_w, self.map_screen.map_w] if self.map_screen.loop_map else [0]
                            for offset in offsets:
                                sx, sy = queries.world_to_screen([cx, cy], self.map_screen, offset)
                                
                                if 0 <= sx <= c.SCREEN_WIDTH and 0 <= sy <= c.SCREEN_HEIGHT:
                                    pygame.draw.circle(surface, (0, 255, 0), (int(sx), int(sy)), 12, 3)

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

        # --- Resource HUD ---
        hud_rect = pygame.Rect(0, c.SCREEN_HEIGHT - 60, c.SCREEN_WIDTH, 60)
        pygame.draw.rect(surface, (30, 30, 30), hud_rect)
        pygame.draw.line(surface, (100, 100, 100), (0, hud_rect.y), (c.SCREEN_WIDTH, hud_rect.y), 2)

        res_font = fonts.get("production_hud")
        
        resources = queries.get_resource_hud_strings(self.map_screen, include_net=False)
        for i, (text, color) in enumerate(resources):
            surface.blit(res_font.render(text, True, color), (50 + (i * 300), hud_rect.y + 15))

    def update(self):
        super().update()
        # Ensure the camera keeps running its smooth zoom/pan lerp math 
        # even when the Orders screen is the active state
        if self.map_screen:
            self.map_screen.camera.update(self.map_screen, c.SCREEN_HEIGHT)

    def exit_to_map(self):
        self.next_state, self.done = "MAP", True

    def handle_back_key(self):
        self.exit_to_map()