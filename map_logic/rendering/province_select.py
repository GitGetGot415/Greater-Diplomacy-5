import pygame
import data.constants as c

def draw_province_select(self, surface):
    cx, cy = self.selected_province["center"]
    for offset in [0, -self.map_w, self.map_w]:
        sx = (cx + offset - self.camera.pos.x) * self.camera.zoom
        sy = (cy - self.camera.pos.y) * self.camera.zoom * getattr(self.camera, 'tilt_factor', 1.0) + self.top_ui_height
        if -100 < sx < c.SCREEN_WIDTH + 100:
            radius_x = max(2, int(4 * self.camera.zoom))
            radius_y = int(radius_x * getattr(self.camera, 'tilt_factor', 1.0)) if c.APPLY_TILT_TO_OVERLAYS else radius_x
            pygame.draw.ellipse(surface, (255, 255, 0), pygame.Rect(int(sx) - radius_x, int(sy) - radius_y, radius_x*2, radius_y*2), 2)