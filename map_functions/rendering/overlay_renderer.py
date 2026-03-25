import pygame
import math

from map_functions.rendering import symbol_loader

def draw_movement_arrow(surface, map_screen, start_province, end_province, color=(255, 255, 0)):
    """Draws a scaled arrow between two province centers based on camera zoom/pos."""
    cam = map_screen.camera
    
    # 1. Get World Centers
    p1 = start_province["center"]
    p2 = end_province["center"]
    
    # 2. Convert to Screen Coordinates
    def world_to_screen(pos):
        sx = (pos[0] - cam.pos.x) * cam.zoom
        sy = (pos[1] - cam.pos.y) * cam.zoom + map_screen.top_ui_height
        return sx, sy

    start_pos = world_to_screen(p1)
    end_pos = world_to_screen(p2)

    # 3. Draw the Main Line
    pygame.draw.line(surface, color, start_pos, end_pos, max(1, int(3 * cam.zoom)))

    # 4. Calculate and Draw the Arrow Head
    angle = math.atan2(start_pos[1] - end_pos[1], start_pos[0] - end_pos[0])
    
    # Arrow head size scales with zoom
    head_size = 15 * cam.zoom
    
    # Points for the triangle head
    left_wing = (end_pos[0] + head_size * math.cos(angle + math.pi / 6),
                 end_pos[1] + head_size * math.sin(angle + math.pi / 6))
    right_wing = (end_pos[0] + head_size * math.cos(angle - math.pi / 6),
                  end_pos[1] + head_size * math.sin(angle - math.pi / 6))
    
    pygame.draw.polygon(surface, color, [end_pos, left_wing, right_wing])

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
                    # Future: draw factories or resource icons
                    if province.get("resources"):
                        pygame.draw.rect(surface, (255, 215, 0), (sx-5, sy-5, 10, 10))

                # --- MILITARY VIEW ---
                elif self.secondary_mode == "MILITARY":
                    # Future: draw forts or trenches
                    pass

def draw_unit_icon(self, surface, sx, sy, province):
    # Units are now dictionaries: {"type": "...", "owner": "..."}
    primary_unit_data = province["units"][0]
    unit_type = primary_unit_data["type"]
    unit_owner = primary_unit_data["owner"]
    
    # Determine icon by type
    # symbol_name = "hilux_icon" if "Toyota" in unit_type else "tank_icon"
    symbol_name = unit_type
    symbol = symbol_loader.get_symbol(symbol_name, self.camera.zoom)
    
    if symbol:
        # Center the image on the sx, sy coordinates
        rect = symbol.get_rect(center=(sx, sy))
        surface.blit(symbol, rect)
        
        # Optional: Draw a tiny flag or color dot representing the owner country
        owner_color = self.nation_colors.get(unit_owner, (200, 200, 200))
        pygame.draw.circle(surface, owner_color, (sx - 10, sy + 10), 5)
    else:
        # Fallback circle colored by owner nation
        owner_color = self.nation_colors.get(unit_owner, (0, 100, 255))
        pygame.draw.circle(surface, owner_color, (sx, sy), int(7 * self.camera.zoom))