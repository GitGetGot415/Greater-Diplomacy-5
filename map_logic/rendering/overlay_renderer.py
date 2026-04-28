import pygame
import math

from map_logic.rendering import symbol_loader

def draw_movement_path(surface, map_screen, start_province, path_ids, color=(255, 255, 0)):
    """Draws a multi-segment path with lines underneath circles and a triangle at the end."""
    if not path_ids: return

    cam = map_screen.camera
    
    # 1. Convert to Screen Coordinates
    def world_to_screen(pos):
        sx = (pos[0] - cam.pos.x) * cam.zoom
        sy = (pos[1] - cam.pos.y) * cam.zoom + map_screen.top_ui_height
        return sx, sy

    # Build an ordered list of all nodes in the path
    nodes = [start_province]
    for step_id in path_ids:
        target_node = map_screen.id_to_province.get(step_id)
        if target_node:
            nodes.append(target_node)

    if len(nodes) < 2: return

    # Grab the UI symbols (Base scale is tweaked for zoom)
    line_base = symbol_loader.get_symbol("Line", cam.zoom * 1, color)
    circle_img = symbol_loader.get_symbol("Circle", cam.zoom * 1, color)
    triangle_img = symbol_loader.get_symbol("Triangle", cam.zoom * 1, color)

    # PASS 1: Draw all lines FIRST so they render underneath the shapes
    for i in range(len(nodes) - 1):
        p1 = nodes[i]["center"]
        p2 = nodes[i+1]["center"]
        start_pos = world_to_screen(p1)
        end_pos = world_to_screen(p2)

        dx = end_pos[0] - start_pos[0]
        dy = end_pos[1] - start_pos[1]
        dist = math.hypot(dx, dy)
        angle = math.degrees(math.atan2(-dy, dx))

        if line_base and int(dist) > 0:
            # Stretch the line image to fit the exact distance between the nodes
            thickness = max(2, int(4 * cam.zoom))
            scaled_line = pygame.transform.scale(line_base, (int(dist), thickness))
            rotated_line = pygame.transform.rotate(scaled_line, angle)
            rect = rotated_line.get_rect(center=((start_pos[0] + end_pos[0])/2, (start_pos[1] + end_pos[1])/2))
            surface.blit(rotated_line, rect)
        else:
            # Fallback
            pygame.draw.line(surface, color, start_pos, end_pos, max(1, int(3 * cam.zoom)))

    # PASS 2: Draw the node markers on top of the lines
    for i in range(1, len(nodes)):
        p1 = nodes[i-1]["center"]
        p2 = nodes[i]["center"]
        start_pos = world_to_screen(p1)
        end_pos = world_to_screen(p2)

        is_last = (i == len(nodes) - 1)

        dx = end_pos[0] - start_pos[0]
        dy = end_pos[1] - start_pos[1]
        angle = math.degrees(math.atan2(-dy, dx))

        if is_last:
            if triangle_img:
                # Rotate the triangle so it points along the trajectory of the line
                rotated_tri = pygame.transform.rotate(triangle_img, angle)
                rect = rotated_tri.get_rect(center=end_pos)
                surface.blit(rotated_tri, rect)
            else:
                # Fallback Triangle
                head_size = 15 * cam.zoom
                angle_rad = math.atan2(dy, dx)
                left_wing = (end_pos[0] - head_size * math.cos(angle_rad - math.pi / 6),
                             end_pos[1] - head_size * math.sin(angle_rad - math.pi / 6))
                right_wing = (end_pos[0] - head_size * math.cos(angle_rad + math.pi / 6),
                              end_pos[1] - head_size * math.sin(angle_rad + math.pi / 6))
                pygame.draw.polygon(surface, color, [end_pos, left_wing, right_wing])
        else:
            if circle_img:
                # Plop the circle right on the intermediate coordinate
                rect = circle_img.get_rect(center=end_pos)
                surface.blit(circle_img, rect)
            else:
                # Fallback Circle
                pygame.draw.circle(surface, color, (int(end_pos[0]), int(end_pos[1])), max(3, int(4 * cam.zoom)))

def draw_overlay_content(self, surface):
    """Orchestrates what icons/symbols to draw over the map."""
    if self.secondary_mode == "BLANK":
        return

    for color_key, province in self.map_data.items():
        cx, cy = province["center"]
        
        # Wrapping logic for screen coordinates
        offsets = [0, -self.map_w, self.map_w] if self.loop_map else [0]
        
        for offset in offsets:
            sx = int((cx + offset - self.camera.pos.x) * self.camera.zoom)
            sy = int((cy - self.camera.pos.y) * self.camera.zoom) + self.top_ui_height
            
            # Culling: only draw if within screen width
            if -50 < sx < surface.get_width() + 50:
                
                # --- UNIT VIEW ---
                if self.secondary_mode == "UNITS" and province["units"]:
                    draw_unit_icon(self, surface, sx, sy, province)

                # --- ECONOMY VIEW ---
                elif self.secondary_mode == "ECONOMY":
                    # Draw standard resources first (your existing logic)
                    # hahaha NO don't do that we have a dedicated tab for that now
                    """if province.get("resources"):
                        pygame.draw.rect(surface, (255, 215, 0), (sx-15, sy-15, 10, 10))"""
                    
                    # Draw Buildings
                    buildings = province.get("buildings", [])
                    for i, b_name in enumerate(buildings):
                        # Offset building icons so they don't stack perfectly
                        offset_x = (i % 2) * 20
                        offset_y = (i // 2) * 20
                        
                        # Try to load a symbol (e.g., "workshop_icon") or use a colored square
                        # sym_name = b_name.lower().replace(" ", "_")
                        sym_name = b_name
                        symbol = symbol_loader.get_symbol(sym_name, self.camera.zoom * 0.8)
                        
                        if symbol:
                            surface.blit(symbol, (sx + offset_x, sy + offset_y))
                        else:
                            # Fallback colored squares for different types
                            color = (150, 150, 150) # Grey for workshop
                            if "Factory" in b_name: color = (100, 100, 200) # Blue-ish for factory
                            if "Refinery" in b_name: color = (200, 100, 100) # Red-ish for refinery
                            
                            rect = pygame.Rect(sx + offset_x, sy + offset_y, 12 * self.camera.zoom, 12 * self.camera.zoom)
                            pygame.draw.rect(surface, color, rect)
                            pygame.draw.rect(surface, (255, 255, 255), rect, 1) # Border
                
                # --- RESOURCES VIEW ---
                elif self.secondary_mode == "RESOURCES":
                    resources = province.get("resources", {})
                    if isinstance(resources, dict) and resources:
                        offset_x = 0
                        for res_type, amount in resources.items():
                            if amount > 0:
                                # Fetch icon, your symbol_loader automatically drops '.png' so it expects "Iron", "Coal", "Oil"
                                sym = symbol_loader.get_symbol(res_type, self.camera.zoom * 0.8)
                                if sym:
                                    surface.blit(sym, (sx + offset_x, sy))
                                else:
                                    # Fallback colored square
                                    c = (200, 200, 200)
                                    if res_type == "Iron": c = (180, 180, 180)
                                    if res_type == "Coal": c = (50, 50, 50)
                                    if res_type == "Oil": c = (30, 30, 30)
                                    pygame.draw.rect(surface, c, (sx + offset_x, sy, int(15 * self.camera.zoom), int(15 * self.camera.zoom)))
                                
                                # Shift right so multiple icons stack side-by-side
                                offset_x += 20 * self.camera.zoom

def draw_unit_icon(self, surface, sx, sy, province):
    # Units are now dictionaries: {"type": "...", "owner": "..."}
    primary_unit_data = province["units"][0]
    unit_type = primary_unit_data["type"]
    unit_owner = primary_unit_data["owner"]
    
    # Fetch the owner's color
    owner_color = self.nation_colors.get(unit_owner, (200, 200, 200))
    
    # Check if it's a dynamic convoy, otherwise use the standard type
    symbol_name = "Convoy" if unit_type.startswith("Convoy") else unit_type
    symbol = symbol_loader.get_symbol(symbol_name, self.camera.zoom * 0.5, color=owner_color)
    
    if symbol:
        # Center the image on the sx, sy coordinates
        rect = symbol.get_rect(center=(sx, sy))
        surface.blit(symbol, rect)
    else:
        # Fallback circle colored by owner nation
        pygame.draw.circle(surface, owner_color, (sx, sy), int(7 * self.camera.zoom))