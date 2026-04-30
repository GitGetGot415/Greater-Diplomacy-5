import pygame
import json
import os
import gameState as g
import data.constants as c
from gameState import GameState
from ui_elements import Button
from map_logic.rendering.font_manager import fonts
from data import queries

class Orders_Screen(GameState):
    def __init__(self):
        super().__init__()
        self.bg_color = (20, 20, 40)
        self.target_province = None
        self.map_screen = None
        self.selected_unit_index = None 
        self.cancel_rects = []
        
        # Load unit library so we can check unit stats (like naval_unit) dynamically
        self.unit_library = self.load_unit_data()

    def load_unit_data(self):
        path = c.UNIT_DATA_PATH
        if os.path.exists(path):
            with open(path, 'r') as f: return json.load(f)
        return {}
    
    def start_with_province(self, province, map_ref):
        self.target_province = province
        self.map_screen = map_ref
        
        # --- NEW: Auto-select logic ---
        # Gather the exact list indices of the units you own on this tile
        units = self.target_province.get("units", [])
        player_unit_indices = [i for i, u in enumerate(units) if u.get("owner") == self.map_screen.player_country]
        
        if len(player_unit_indices) > 1:
            self.selected_unit_index = "ALL"
        elif len(player_unit_indices) == 1:
            self.selected_unit_index = player_unit_indices[0]
        else:
            self.selected_unit_index = None
            
        self.refresh_ui()

    def refresh_ui(self):
        self.elements = [Button(50, c.TOP_BAR_UI_CENTER_Y, "small", "red", "Back", self.exit_to_map)]
        
        units = self.target_province.get("units", [])
        player_units = [u for u in units if u.get("owner") == self.map_screen.player_country]
        
        # --- NEW: Select All Button ---
        if len(player_units) > 1:
            all_color = "blue" if self.selected_unit_index == "ALL" else "grey"
            btn_all = Button(100, 90, "medium", all_color, "Select All", lambda: self.select_unit("ALL"))
            self.elements.append(btn_all)

        for i, unit in enumerate(units):
            if unit.get("owner") != self.map_screen.player_country:
                continue
                
            color = "blue" if self.selected_unit_index == i else "grey"
            unit_name = unit["type"]
            
            btn = Button(100, 150 + (i * 50), "medium_square", color, f"{unit_name}", lambda idx=i: self.select_unit(idx))
            self.elements.append(btn)

        # --- THE NEW UI BUTTONS ---
        if self.selected_unit_index is not None:
            if self.selected_unit_index == "ALL":
                target_units = player_units
            elif 0 <= self.selected_unit_index < len(units):
                target_units = [units[self.selected_unit_index]]
            else:
                target_units = []

            if target_units:
                order_type = target_units[0].get("order", {}).get("type", "")

                # Disband Button using standard action button position
                btn_disband = Button(c.ORDER_BTN_X, 150, "medium", "red", "Disband", self.disband_unit)
                self.elements.append(btn_disband)

                # --- Combat Check ---
                player_country = self.map_screen.player_country
                in_combat = queries.is_nation_in_combat_here(player_country, self.target_province, self.map_screen.nation_data)

                # Convoy Conversion Logic (Enforce coastal/port rules)
                is_water = self.target_province.get("terrain") in c.WATER_TERRAINS
                is_coastal = self.target_province.get("is_coastal", False)
                
                # Check if group is pure land or pure convoy to avoid mixed conversion states
                all_convoy = all(u.get("type", "").startswith("Convoy") for u in target_units)
                all_land = all(not u.get("type", "").startswith("Convoy") and not queries.is_naval_unit(u.get("type", "")) for u in target_units)

                if order_type == "CONVERT":
                    txt = f"Cancel Convert"
                    btn_conv = Button(c.ORDER_BTN_X, 220, "medium", "red", txt, self.cancel_conversion)
                    self.elements.append(btn_conv)
                elif all_convoy:
                    if in_combat:
                        btn_conv = Button(c.ORDER_BTN_X, 220, "medium", "grey", "In Combat!", lambda: None)
                    elif not is_water:
                        btn_conv = Button(c.ORDER_BTN_X, 220, "medium", "blue", "To Land Unit", self.convert_unit)
                    else:
                        btn_conv = Button(c.ORDER_BTN_X, 220, "medium", "grey", "Must be on Land", lambda: None)
                    self.elements.append(btn_conv)
                elif all_land:
                    if in_combat:
                        btn_conv = Button(c.ORDER_BTN_X, 220, "medium", "grey", "In Combat!", lambda: None)
                    elif is_coastal or is_water:
                        btn_conv = Button(c.ORDER_BTN_X, 220, "medium", "blue", "To Convoy", self.convert_unit)
                    else:
                        btn_conv = Button(c.ORDER_BTN_X, 220, "medium", "grey", "Must be Coastal", lambda: None)
                    self.elements.append(btn_conv)
                else:
                    btn_conv = Button(c.ORDER_BTN_X, 220, "medium", "grey", "Cannot Convert Mixed Group", lambda: None)
                    self.elements.append(btn_conv)

    def disband_unit(self):
        units = self.target_province.get("units", [])
        p_data = self.map_screen.nation_data[self.map_screen.player_country]

        if self.selected_unit_index == "ALL":
            # Loop backwards to safely pop multiple elements
            for i in reversed(range(len(units))):
                if units[i].get("owner") == self.map_screen.player_country:
                    unit = units.pop(i)
                    u_type = unit.get("original_type", unit.get("type"))
                    stats = self.unit_library.get(u_type, {})
                    queries.refund_resources(p_data, stats)
            
            self.map_screen.show_feedback("Disbanded all units & Refunded")
            self.selected_unit_index = None
            self.refresh_ui()

        elif self.selected_unit_index is not None and 0 <= self.selected_unit_index < len(units):
            unit = units.pop(self.selected_unit_index)
            
            # Refund based on the original unit type
            u_type = unit.get("original_type", unit.get("type"))
            stats = self.unit_library.get(u_type, {})
            
            queries.refund_resources(p_data, stats)

            self.map_screen.show_feedback(f"Disbanded {u_type} & Refunded")
            self.selected_unit_index = None
            self.refresh_ui()

    def convert_unit(self):
        # --- Prevent conversion during combat just in case ---
        player_country = self.map_screen.player_country
        in_combat = queries.is_nation_in_combat_here(player_country, self.target_province, self.map_screen.nation_data)
        if in_combat:
            self.map_screen.show_feedback("Cannot convert during combat!")
            return
        # -----------------------------------------------------

        units = self.target_province.get("units", [])
        
        if self.selected_unit_index == "ALL":
            for unit in units:
                if unit.get("owner") == player_country:
                    u_type = unit.get("type", "")
                    if not queries.is_naval_unit(u_type) or u_type.startswith("Convoy"):
                        target_type = "Land Unit" if u_type.startswith("Convoy") else "Convoy"
                        unit["order"] = {"type": "CONVERT", "turns_left": 1, "to": target_type}
            self.map_screen.show_feedback("Converting group (1 turn)")
            self.refresh_ui()

        elif self.selected_unit_index is not None and 0 <= self.selected_unit_index < len(units):
            unit = units[self.selected_unit_index]
            u_type = unit.get("type", "")

            target_type = "Land Unit" if u_type.startswith("Convoy") else "Convoy"
            unit["order"] = {"type": "CONVERT", "turns_left": 1, "to": target_type}
            
            self.map_screen.show_feedback(f"Converting to {target_type} (1 turn)")
            self.refresh_ui()

    def cancel_conversion(self):
        units = self.target_province.get("units", [])
        
        if self.selected_unit_index == "ALL":
            for unit in units:
                if unit.get("owner") == self.map_screen.player_country:
                    if "order" in unit and unit["order"].get("type") == "CONVERT":
                        del unit["order"]
            self.map_screen.show_feedback("Group Conversion Cancelled")
            self.refresh_ui()

        elif self.selected_unit_index is not None and 0 <= self.selected_unit_index < len(units):
            unit = units[self.selected_unit_index]
            if "order" in unit and unit["order"].get("type") == "CONVERT":
                del unit["order"]
                self.map_screen.show_feedback("Conversion Cancelled")
                self.refresh_ui()

    def select_unit(self, index):
        self.selected_unit_index = index
        self.refresh_ui()

    def cancel_unit_order(self, index):
        units = self.target_province.get("units", [])
        if 0 <= index < len(units):
            if "order" in units[index]:
                del units[index]["order"]
                self.map_screen.show_feedback("Order Cancelled")
                self.refresh_ui()

    def handle_events(self, events):
        for event in events:
            # FIX: Added 'and event.button == 1' so scrolling the wheel doesn't cancel orders
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                for rect, idx in self.cancel_rects:
                    if rect.collidepoint(event.pos):
                        self.cancel_unit_order(idx)
                        return

            super().handle_events([event])
            self.additional_events(event)

    def additional_events(self, event):
        mx, my = pygame.mouse.get_pos()
        
        # --- NEW: Camera Controls (Zooming and Panning) ---
        on_ui = False
        units = self.target_province.get("units", [])
        player_units = [u for u in units if u.get("owner") == self.map_screen.player_country]
        if player_units:
            # Use the same background rect math from additional_draw to mask the UI
            bg_rect = pygame.Rect(80, 130, 500, len(player_units) * 60 + 40)
            if bg_rect.collidepoint(mx, my):
                on_ui = True
                
        # Pass scroll and pan events to your centralized map camera
        if event.type in (pygame.MOUSEWHEEL, pygame.MOUSEMOTION):
            self.map_screen.camera.handle_input(event, self.map_screen, on_ui)

        # --- Dynamic Map Hover Update ---
        if event.type == pygame.MOUSEMOTION:
            cam = self.map_screen.camera
            wx = ((mx / cam.zoom) + cam.pos.x) % self.map_screen.map_w
            wy = ((my - self.map_screen.top_ui_height) / cam.zoom) + cam.pos.y
            
            if 0 <= wy < self.map_screen.map_h:
                color = self.map_screen.id_map.get_at((int(wx), int(wy)))
                self.map_screen.hovered_province = self.map_screen.map_data.get((color.r, color.g, color.b))
                
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
            else:
                self.map_screen.hovered_province = None
                self.map_screen.hover_glow_surf = None

        # --- Standard Order Placement Click ---
        # FIX: Added 'and event.button == 1' to ignore scroll wheel (buttons 4/5) and right clicks
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and self.selected_unit_index is not None:
            dest = self.get_clicked_province(event.pos)
            if not dest: return

            units = self.target_province.get("units", [])

            if self.selected_unit_index == "ALL":
                target_units = [u for u in units if u.get("owner") == self.map_screen.player_country]
            elif 0 <= self.selected_unit_index < len(units):
                target_units = [units[self.selected_unit_index]]
            else:
                target_units = []

            if not target_units: return

            # --- THE FIX ---
            if any(isinstance(u.get("order"), dict) and u["order"].get("type") == "CONVERT" for u in target_units):
                self.map_screen.show_feedback("Cannot move while converting!")
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

            # --- NEW: Unlimited Queueing Logic ---
            if dest["id"] in start_node["neighbors"]:
                if all(self.can_unit_enter(u, dest) for u in target_units):
                    
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

            # --- NEW: Ships can only dock at friendly coasts ---
            if not is_convoy and not queries.can_ships_enter(unit["owner"], dest, self.map_screen.nation_data):
                self.map_screen.show_feedback("Ships can only enter friendly/owned coastal tiles!")
                return False
            # ---------------------------------------------------

        # Enforce Diplomacy/Border Rules
        dest_owner = dest.get("owner", "Unclaimed")
        
        # --- NEW: Combat Lock (Player UI Check) ---
        current_path = unit.get("order", {}).get("path", [])
        if not current_path: # First step of the move order
            in_combat = queries.is_nation_in_combat_here(unit["owner"], self.target_province, self.map_screen.nation_data)
            if in_combat and queries.is_hostile_territory(unit["owner"], dest_owner, self.map_screen.nation_data):
                self.map_screen.show_feedback("Cannot advance into enemy territory while in combat! (Retreat only)")
                return False
        # ------------------------------------------

        if not is_naval and not queries.can_land_units_enter(unit["owner"], dest, self.map_screen.nation_data):
            self.map_screen.show_feedback(f"Neutral {dest_owner} territory!")
            return False
            
        return True
    
    def get_clicked_province(self, mouse_pos):
        cam = self.map_screen.camera
        mx, my = mouse_pos
        wx = ((mx / cam.zoom) + cam.pos.x) % self.map_screen.map_w
        wy = ((my - self.map_screen.top_ui_height) / cam.zoom) + cam.pos.y
        if 0 <= wy < self.map_screen.map_h:
            color = self.map_screen.id_map.get_at((int(wx), int(wy)))
            return self.map_screen.map_data.get((color.r, color.g, color.b))
        return None

    def additional_draw(self, surface):
        if not self.map_screen or not self.target_province: 
            return

        temp_province = self.map_screen.selected_province
        self.map_screen.selected_province = None
        
        # Add flags to temporarily disable UI noise
        self.map_screen.hide_raised_rect = True
        self.map_screen.hide_top_info = True
        self.map_screen.hide_tooltip = True
        self.map_screen.hide_resource_hud = True
        self.map_screen.hide_minimap = True

        self.map_screen.additional_draw(surface)

        # Restore original map states
        self.map_screen.hide_raised_rect = False
        self.map_screen.hide_top_info = False
        self.map_screen.hide_tooltip = False
        self.map_screen.hide_resource_hud = False
        self.map_screen.hide_minimap = False
        self.map_screen.selected_province = temp_province

        from map_logic.rendering import province_select
        province_select.draw_province_select(self.map_screen, surface)

        self.cancel_rects = []
        from map_logic.rendering import overlay_renderer
        
        font = fonts.get("heading1")
        small_font = fonts.get("normal")
        
        title = font.render(f"Orders: Province {self.target_province['id']}", True, (255, 255, 255))
        surface.blit(title, (c.SCREEN_WIDTH//2 - title.get_width()//2, c.TOP_BAR_UI_CENTER_Y))
        
        # --- Draw Background Panel for Units ---
        units = self.target_province.get("units", [])
        player_units = [u for u in units if u.get("owner") == self.map_screen.player_country]
        
        # Dynamically fetch the player's color
        owner_color = self.map_screen.nation_colors.get(self.map_screen.player_country, (255, 255, 0))
        
        if player_units:
            # Dynamically size the height based on how many units there are
            bg_rect = pygame.Rect(80, 130, 500, len(player_units) * 60 + 40)
            
            # Draw semi-transparent panel
            panel_surf = pygame.Surface((bg_rect.width, bg_rect.height), pygame.SRCALPHA)
            panel_surf.fill((30, 30, 50, 200))
            surface.blit(panel_surf, bg_rect.topleft)
            
            # Draw border
            pygame.draw.rect(surface, (100, 100, 250), bg_rect, 2)
        
        # --- Helper for Split Path Drawing ---
        def draw_split_path(start_prov, path, speed, base_color):
            if not path: return
            
            immediate_path = path[:speed]
            queued_path = path[speed:]
            
            if immediate_path:
                overlay_renderer.draw_movement_path(surface, self.map_screen, start_prov, immediate_path, color=base_color)
                
            if queued_path:
                bright_color = (min(255, base_color[0] + 150), min(255, base_color[1] + 150), min(255, base_color[2] + 150))
                q_start = self.map_screen.id_to_province.get(immediate_path[-1]) if immediate_path else start_prov
                overlay_renderer.draw_movement_path(surface, self.map_screen, q_start, queued_path, color=bright_color, alpha=120)
        
        for i, unit in enumerate(units):
            if unit.get("owner") != self.map_screen.player_country:
                continue

            y_pos = 150 + (i * 60)
            order = unit.get("order", {})
            path = order.get("path", [])

            if path:
                txt = small_font.render(f"PATH: {' -> '.join(map(str, path))}", True, (255, 255, 0))
                surface.blit(txt, (310, y_pos + 15))
                
                cancel_rect = pygame.Rect(100 + 205, y_pos + 10, 30, 30)
                pygame.draw.rect(surface, (150, 0, 0), cancel_rect)
                x_label = small_font.render("X", True, (255, 255, 255))
                surface.blit(x_label, x_label.get_rect(center=cancel_rect.center))
                self.cancel_rects.append((cancel_rect, i))
                
                # Split draw using the helper function
                draw_split_path(self.target_province, path, unit.get("speed", 1), owner_color)

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
                            cx, cy = neighbor["center"]
                            sx = (cx - cam.pos.x) * cam.zoom
                            sy = (cy - cam.pos.y) * cam.zoom + self.map_screen.top_ui_height
                            
                            if 0 <= sx <= c.SCREEN_WIDTH and 0 <= sy <= c.SCREEN_HEIGHT:
                                pygame.draw.circle(surface, (0, 255, 0), (int(sx), int(sy)), 12, 3)

                mouse_pos = pygame.mouse.get_pos()
                hovered = self.get_clicked_province(mouse_pos)
                if hovered and hovered["id"] in last_node["neighbors"]:
                    
                    # Calculate speed limit based on group or individual selection
                    speed_limit = min(u.get("speed", 1) for u in player_units) if self.selected_unit_index == "ALL" else active_unit.get("speed", 1)
                    
                    # Determine styling based on if this specific hover step exceeds the speed
                    is_queued = len(active_path) >= speed_limit
                    
                    preview_color = owner_color
                    preview_alpha = 255
                    
                    if is_queued:
                        preview_color = (min(255, owner_color[0] + 150), min(255, owner_color[1] + 150), min(255, owner_color[2] + 150))
                        preview_alpha = 120
                        
                    # Use the owner's color to draw the cursor hover with correct alpha logic
                    overlay_renderer.draw_movement_path(surface, self.map_screen, last_node, [hovered["id"]], color=preview_color, alpha=preview_alpha)
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