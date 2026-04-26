import pygame
import data.constants as c

def draw_minimap(self, surface, screen_width, screen_height):
    map_aspect = self.map_h / self.map_w
    mini_w = 240
    mini_h = int(mini_w * map_aspect)
    
    # Position of the minimap background
    mx, my = screen_width - mini_w - 20, screen_height - mini_h - 80
    
    # Draw Background
    pygame.draw.rect(surface, (10, 10, 10), (mx, my, mini_w, mini_h))
    pygame.draw.rect(surface, (100, 100, 100), (mx, my, mini_w, mini_h), 1)
    
    # --- UI Offset Logic ---
    visible_map_width = screen_width - c.UI_LEFT_OFFSET

    # 1. Calculate how many 'world pixels' the red bar covers
    world_ui_offset = c.UI_LEFT_OFFSET / self.camera.zoom
    
    # 2. Wrap the shifted X coordinate so it seamlessly loops around the globe
    wrapped_x = (self.camera.pos.x + world_ui_offset) % self.map_w
    
    # 3. Calculate the Start Position (vx)
    vx = (wrapped_x / self.map_w) * mini_w + mx
    vy = (self.camera.pos.y / self.map_h) * mini_h + my
    
    # 4. Calculate the Width (vw)
    vw = (visible_map_width / self.camera.zoom / self.map_w) * mini_w
    vh = ((screen_height - self.total_ui_h) / self.camera.zoom / self.map_h) * mini_h
    
    # --- Draw with Wrap-around support ---
    vx_relative = vx - mx
    
    if vx_relative + vw > mini_w:
        # Part A: Draws from vx to the right edge of the minimap
        first_part_w = mini_w - vx_relative
        if first_part_w > 0:
            pygame.draw.rect(surface, (255, 255, 0), (vx, vy, first_part_w, vh), 1)
        
        # Part B: Draws the remainder starting from the left edge (mx)
        second_part_w = vw - first_part_w
        pygame.draw.rect(surface, (255, 255, 0), (mx, vy, second_part_w, vh), 1)
    else:
        pygame.draw.rect(surface, (255, 255, 0), (vx, vy, vw, vh), 1)