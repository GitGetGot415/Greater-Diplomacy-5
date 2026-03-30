import pygame
import gameState as g
from gameState import GameState
from ui_elements import Button

class Orders_Screen(GameState):
    def __init__(self):
        super().__init__()
        self.bg_color = (20, 20, 40)
        self.target_province = None
        self.map_screen = None
        self.selected_unit_index = None 
        self.cancel_rects = [] # To track "X" button clicks for individual units

    def start_with_province(self, province, map_ref):
        self.target_province = province
        self.map_screen = map_ref
        self.selected_unit_index = None
        self.refresh_ui()

    def refresh_ui(self):
        # Clear elements and start with Back button
        self.elements = [Button(50, 50, "small", "red", "Back", self.exit_to_map)]
        
        # Only allow selecting units that belong to the player
        units = self.target_province.get("units", [])
        for i, unit in enumerate(units):
            if unit.get("owner") != self.map_screen.player_country:
                continue
                
            color = "blue" if self.selected_unit_index == i else "grey"
            unit_name = unit["type"]  # Removed the .split() so the full name shows
            
            # Main button to select the unit for giving a new order
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
                # 1. Check if we clicked an "X" to cancel an order
                for rect, idx in self.cancel_rects:
                    if rect.collidepoint(event.pos):
                        self.cancel_unit_order(idx)
                        return

            # 2. Inherit standard button handling (Back, Select Unit)
            super().handle_events([event])
            self.additional_events(event)

    def additional_events(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN and self.selected_unit_index is not None:
            dest = self.get_clicked_province(event.pos)
            if not dest: return

            unit = self.target_province["units"][self.selected_unit_index]
            
            # --- FIX: Ensure order AND path exist safely ---
            if "order" not in unit or not isinstance(unit["order"], dict):
                unit["order"] = {"type": "MOVE", "path": []}
            
            if "path" not in unit["order"]:
                unit["order"]["path"] = []
            # -----------------------------------------------
            
            current_path = unit["order"]["path"]
            # if speed unknown just set it to 1
            speed_limit = unit.get("speed", 1)

            # Determine "where we are clicking from"
            if not current_path:
                start_node = self.target_province
            else:
                start_node = self.map_screen.id_to_province.get(current_path[-1])

            # Logic Check
            if len(current_path) < speed_limit:
                if dest["id"] in start_node["neighbors"]:
                    # Path Validation (Terrain/Diplomacy)
                    if self.can_unit_enter(unit, dest):
                        current_path.append(dest["id"])
                        self.map_screen.show_feedback(f"Path: {len(current_path)}/{speed_limit}")
                        self.refresh_ui()
            else:
                self.map_screen.show_feedback("Maximum speed reached!")

    def can_unit_enter(self, unit, dest):
        """Helper to check terrain and diplomacy before adding to path."""
        # Terrain
        WATER_TYPES = ["ocean", "coastal_sea", "inland_sea", "lakes"]
        dest_is_water = dest.get("terrain") in WATER_TYPES
        u_type = unit["type"].lower()

        if ("hilux" in u_type or "t-55" in u_type) and dest_is_water:
            self.map_screen.show_feedback("Land units cannot enter water!")
            return False
        
        if ("boat" in u_type or "frigate" in u_type) and not dest_is_water and not dest.get("is_coastal"):
            self.map_screen.show_feedback("Sea units blocked by land!")
            return False

        # Diplomacy
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

    # ... (around line 125)
    def additional_draw(self, surface):
        if not self.map_screen or not self.target_province: 
            return

        # --- THE FIX: Temporarily hide the selected province ---
        # This prevents map_renderer from drawing the dark overlay and sidebars.
        temp_province = self.map_screen.selected_province
        self.map_screen.selected_province = None
        
        # --- NEW FLAG TO HIDE THE RED CORNER UI ---
        self.map_screen.hide_raised_rect = True

        # 1. Draw the actual map underneath (Terrain/Political)
        self.map_screen.additional_draw(surface)

        # Restore the selected province state
        self.map_screen.hide_raised_rect = False
        self.map_screen.selected_province = temp_province

        # Re-draw the yellow selection circle manually so we still know our active target
        from map_functions.rendering import province_select
        province_select.draw_province_select(self.map_screen, surface)
        # -------------------------------------------------------

        # Reset hitboxes for this frame (so they update if units are added/removed)
        self.cancel_rects = []
        from map_functions.rendering import overlay_renderer
        
        # 3. UI Header and Unit List Text
        font = pygame.font.SysFont("Arial", 32)
        small_font = pygame.font.SysFont("Arial", 18)
        
        title = font.render(f"Orders: Province {self.target_province['id']}", True, (255, 255, 255))
        surface.blit(title, (g.SCREEN_WIDTH//2 - title.get_width()//2, 50))
        
        # 4. Draw Paths and "Cancel" buttons for every unit in the province
        units = self.target_province.get("units", [])
        for i, unit in enumerate(units):
            # Only handle player units
            if unit.get("owner") != self.map_screen.player_country:
                continue

            y_pos = 150 + (i * 60)
            order = unit.get("order", {})
            path = order.get("path", [])

            if path:
                # Text feedback next to the button
                txt = small_font.render(f"PATH: {' -> '.join(map(str, path))}", True, (255, 255, 0))
                surface.blit(txt, (310, y_pos + 15))
                
                # Draw the individual Cancel "X" button
                cancel_rect = pygame.Rect(100 + 205, y_pos + 10, 30, 30) # Offset from the unit button
                pygame.draw.rect(surface, (150, 0, 0), cancel_rect)
                x_label = small_font.render("X", True, (255, 255, 255))
                surface.blit(x_label, x_label.get_rect(center=cancel_rect.center))
                self.cancel_rects.append((cancel_rect, i))
                
                # --- RENDER THE CHAIN OF ARROWS ---
                # We start from the province the unit is currently in
                prev_node = self.target_province
                for step_id in path:
                    target_node = self.map_screen.id_to_province.get(step_id)
                    if target_node:
                        # Draw arrow from the previous tile in the chain to this one
                        overlay_renderer.draw_movement_arrow(surface, self.map_screen, prev_node, target_node, color=(255, 255, 0))
                        prev_node = target_node

        # 5. Handle the "Planning Preview" for the currently selected unit
        if self.selected_unit_index is not None:
            active_unit = units[self.selected_unit_index]
            active_path = active_unit.get("order", {}).get("path", [])
            
            # Identify the "Current Tip" of the path to show neighbors
            if not active_path:
                last_node = self.target_province
            else:
                last_node = self.map_screen.id_to_province.get(active_path[-1])

            # Draw green circles on valid neighbors for the next click
            if last_node:
                for n_id in last_node["neighbors"]:
                    neighbor = self.map_screen.id_to_province.get(n_id)
                    if neighbor:
                        cam = self.map_screen.camera
                        cx, cy = neighbor["center"]
                        # Convert world coordinates to screen coordinates
                        sx = (cx - cam.pos.x) * cam.zoom
                        sy = (cy - cam.pos.y) * cam.zoom + self.map_screen.top_ui_height
                        
                        # Only draw if on screen
                        if 0 <= sx <= g.SCREEN_WIDTH and 0 <= sy <= g.SCREEN_HEIGHT:
                            pygame.draw.circle(surface, (0, 255, 0), (int(sx), int(sy)), 12, 3)

            # 6. Draw a "Ghost Arrow" from the last path point to the mouse hover
            mouse_pos = pygame.mouse.get_pos()
            hovered = self.get_clicked_province(mouse_pos)
            if hovered and hovered["id"] in last_node["neighbors"]:
                overlay_renderer.draw_movement_arrow(surface, self.map_screen, last_node, hovered, color=(255, 255, 255))

    def exit_to_map(self):
        self.next_state, self.done = "MAP", True
    
    def handle_back_key(self):
        self.exit_to_map()