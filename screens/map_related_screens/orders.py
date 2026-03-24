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
        
        units = self.target_province.get("units", [])
        for i, unit in enumerate(units):
            color = "blue" if self.selected_unit_index == i else "grey"
            unit_name = unit["type"].split(" ")[-1]
            
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
            clicked_province = self.get_clicked_province(event.pos)
            
            if clicked_province and clicked_province["id"] in self.target_province["neighbors"]:
                unit = self.target_province["units"][self.selected_unit_index]
                unit["order"] = {"type": "MOVE", "target_id": clicked_province["id"]}
                self.map_screen.show_feedback(f"Move to {clicked_province['id']}")
                self.selected_unit_index = None 
                self.refresh_ui()

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
        if not self.map_screen or not self.target_province: return
        self.map_screen.additional_draw(surface)
        
        overlay = pygame.Surface((g.SCREEN_WIDTH, g.SCREEN_HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 120)) 
        surface.blit(overlay, (0, 0))

        # Reset hitboxes for this frame
        self.cancel_rects = []
        from map_functions.rendering import overlay_renderer
        
        # 1. Draw UI text and Cancel buttons
        font = pygame.font.SysFont("Arial", 32)
        small_font = pygame.font.SysFont("Arial", 18)
        
        title = font.render(f"Orders: Province {self.target_province['id']}", True, (255, 255, 255))
        surface.blit(title, (g.SCREEN_WIDTH//2 - title.get_width()//2, 50))
        
        units = self.target_province.get("units", [])
        for i, unit in enumerate(units):
            y_pos = 150 + (i * 60)
            
            # Show order text next to the unit button
            if "order" in unit:
                dest_id = unit["order"]["target_id"]
                txt = small_font.render(f"MOVING TO: {dest_id}", True, (255, 255, 0))
                surface.blit(txt, (310, y_pos + 15))
                
                # Draw the individual Cancel "X" button
                cancel_rect = pygame.Rect(500, y_pos + 10, 30, 30)
                pygame.draw.rect(surface, (150, 0, 0), cancel_rect)
                x_label = small_font.render("X", True, (255, 255, 255))
                surface.blit(x_label, x_label.get_rect(center=cancel_rect.center))
                self.cancel_rects.append((cancel_rect, i))
                
                # Also draw the map arrow
                target_obj = self.map_screen.id_to_province.get(dest_id)
                if target_obj:
                    overlay_renderer.draw_movement_arrow(surface, self.map_screen, self.target_province, target_obj)

        # 2. Draw Hover Preview Arrow
        if self.selected_unit_index is not None:
            mouse_pos = pygame.mouse.get_pos()
            hovered = self.get_clicked_province(mouse_pos)
            if hovered and hovered["id"] in self.target_province["neighbors"]:
                overlay_renderer.draw_movement_arrow(surface, self.map_screen, self.target_province, hovered, color=(255, 255, 255))
                
            # Draw neighbor circles to guide the player
            for n_id in self.target_province["neighbors"]:
                neighbor = self.map_screen.id_to_province.get(n_id)
                if neighbor:
                    cam = self.map_screen.camera
                    cx, cy = neighbor["center"]
                    sx = (cx - cam.pos.x) * cam.zoom
                    sy = (cy - cam.pos.y) * cam.zoom + self.map_screen.top_ui_height
                    pygame.draw.circle(surface, (0, 255, 0), (int(sx), int(sy)), 10, 2)

    def exit_to_map(self):
        self.next_state, self.done = "MAP", True