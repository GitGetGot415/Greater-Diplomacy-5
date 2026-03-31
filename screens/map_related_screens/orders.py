import pygame
import gameState as g
from gameState import GameState
from ui_elements import Button
from map_functions.rendering.font_manager import fonts

class Orders_Screen(GameState):
    def __init__(self):
        super().__init__()
        self.bg_color = (20, 20, 40)
        self.target_province = None
        self.map_screen = None
        self.selected_unit_index = None 
        self.cancel_rects = []

    def start_with_province(self, province, map_ref):
        self.target_province = province
        self.map_screen = map_ref
        self.selected_unit_index = None
        self.refresh_ui()

    def refresh_ui(self):
        self.elements = [Button(50, 50, "small", "red", "Back", self.exit_to_map)]
        
        units = self.target_province.get("units", [])
        for i, unit in enumerate(units):
            if unit.get("owner") != self.map_screen.player_country:
                continue
                
            color = "blue" if self.selected_unit_index == i else "grey"
            unit_name = unit["type"]
            
            btn = Button(100, 150 + (i * 60), "medium", color, f"{unit_name}", lambda idx=i: self.select_unit(idx))
            self.elements.append(btn)

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
            if event.type == pygame.MOUSEBUTTONDOWN:
                for rect, idx in self.cancel_rects:
                    if rect.collidepoint(event.pos):
                        self.cancel_unit_order(idx)
                        return

            super().handle_events([event])
            self.additional_events(event)

    def additional_events(self, event):
        # --- NEW: Dynamic Map Hover Update ---
        if event.type == pygame.MOUSEMOTION:
            mx, my = event.pos
            cam = self.map_screen.camera
            wx = ((mx / cam.zoom) + cam.pos.x) % self.map_screen.map_w
            wy = ((my - self.map_screen.top_ui_height) / cam.zoom) + cam.pos.y
            
            if 0 <= wy < self.map_screen.map_h:
                color = self.map_screen.id_map.get_at((int(wx), int(wy)))
                self.map_screen.hovered_province = self.map_screen.map_data.get((color.r, color.g, color.b))
                
                if self.map_screen.hovered_province:
                    curr_id = self.map_screen.hovered_province["id"]
                    if curr_id != self.map_screen.last_hovered_id:
                        from map_functions.logic import map_utils
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
        if event.type == pygame.MOUSEBUTTONDOWN and self.selected_unit_index is not None:
            dest = self.get_clicked_province(event.pos)
            if not dest: return

            unit = self.target_province["units"][self.selected_unit_index]
            
            if "order" not in unit or not isinstance(unit["order"], dict):
                unit["order"] = {"type": "MOVE", "path": []}
            
            if "path" not in unit["order"]:
                unit["order"]["path"] = []
            
            current_path = unit["order"]["path"]
            speed_limit = unit.get("speed", 1)

            if not current_path:
                start_node = self.target_province
            else:
                start_node = self.map_screen.id_to_province.get(current_path[-1])

            if len(current_path) < speed_limit:
                if dest["id"] in start_node["neighbors"]:
                    if self.can_unit_enter(unit, dest):
                        current_path.append(dest["id"])
                        self.map_screen.show_feedback(f"Path: {len(current_path)}/{speed_limit}")
                        self.refresh_ui()
            else:
                self.map_screen.show_feedback("Maximum speed reached!")

    def can_unit_enter(self, unit, dest):
        WATER_TYPES = ["ocean", "coastal_sea", "inland_sea", "lakes"]
        dest_is_water = dest.get("terrain") in WATER_TYPES
        u_type = unit["type"].lower()

        if ("hilux" in u_type or "t-55" in u_type) and dest_is_water:
            self.map_screen.show_feedback("Land units cannot enter water!")
            return False
        
        if ("boat" in u_type or "frigate" in u_type) and not dest_is_water and not dest.get("is_coastal"):
            self.map_screen.show_feedback("Sea units blocked by land!")
            return False

        dest_owner = dest.get("owner", "Unclaimed")
        player_country = self.map_screen.player_country
        if dest_owner not in ["Unclaimed", "None", player_country]:
            player_data = self.map_screen.nation_data.get(player_country, {})
            if not (dest_owner in player_data.get("at_war_with", []) or dest_owner in player_data.get("allied_with", [])):
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
        self.map_screen.hide_resource_hud = True # NEW
        self.map_screen.hide_minimap = True      # NEW

        self.map_screen.additional_draw(surface)

        # Restore original map states
        self.map_screen.hide_raised_rect = False
        self.map_screen.hide_top_info = False
        self.map_screen.hide_tooltip = False
        self.map_screen.hide_resource_hud = False # NEW
        self.map_screen.hide_minimap = False      # NEW
        self.map_screen.selected_province = temp_province

        from map_functions.rendering import province_select
        province_select.draw_province_select(self.map_screen, surface)

        self.cancel_rects = []
        from map_functions.rendering import overlay_renderer
        
        font = fonts.get("heading1")
        small_font = fonts.get("normal")
        
        title = font.render(f"Orders: Province {self.target_province['id']}", True, (255, 255, 255))
        surface.blit(title, (g.SCREEN_WIDTH//2 - title.get_width()//2, 50))
        
        # --- NEW: Draw Background Panel for Units ---
        units = self.target_province.get("units", [])
        player_units = [u for u in units if u.get("owner") == self.map_screen.player_country]
        
        if player_units:
            # Dynamically size the height based on how many units there are
            bg_rect = pygame.Rect(80, 130, 500, len(player_units) * 60 + 40)
            
            # Draw semi-transparent panel
            panel_surf = pygame.Surface((bg_rect.width, bg_rect.height), pygame.SRCALPHA)
            panel_surf.fill((30, 30, 50, 200))
            surface.blit(panel_surf, bg_rect.topleft)
            
            # Draw border
            pygame.draw.rect(surface, (100, 100, 250), bg_rect, 2)
        # --------------------------------------------
        
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
                
                prev_node = self.target_province
                for step_id in path:
                    target_node = self.map_screen.id_to_province.get(step_id)
                    if target_node:
                        overlay_renderer.draw_movement_arrow(surface, self.map_screen, prev_node, target_node, color=(255, 255, 0))
                        prev_node = target_node

        if self.selected_unit_index is not None:
            active_unit = units[self.selected_unit_index]
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
                        
                        if 0 <= sx <= g.SCREEN_WIDTH and 0 <= sy <= g.SCREEN_HEIGHT:
                            pygame.draw.circle(surface, (0, 255, 0), (int(sx), int(sy)), 12, 3)

            mouse_pos = pygame.mouse.get_pos()
            hovered = self.get_clicked_province(mouse_pos)
            if hovered and hovered["id"] in last_node["neighbors"]:
                overlay_renderer.draw_movement_arrow(surface, self.map_screen, last_node, hovered, color=(255, 255, 255))

    def exit_to_map(self):
        self.next_state, self.done = "MAP", True
    
    def handle_back_key(self):
        self.exit_to_map()