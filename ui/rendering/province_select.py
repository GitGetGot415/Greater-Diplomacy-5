import pygame
import data.constants as c
from data import queries

def draw_province_select(map_screen, surface):
    cx, cy = map_screen.selected_province["center"]
    for offset in [0, -map_screen.map_w, map_screen.map_w]:
        sx, sy = queries.world_to_screen((cx, cy), map_screen, offset)
        if -100 < sx < c.SCREEN_WIDTH + 100:
            radius_x = max(2, int(4 * map_screen.camera.zoom))
            radius_y = int(radius_x * map_screen.camera.tilt_factor) if c.APPLY_TILT_TO_OVERLAYS else radius_x
            pygame.draw.ellipse(surface, (255, 255, 0), pygame.Rect(int(sx) - radius_x, int(sy) - radius_y, radius_x*2, radius_y*2), 2)