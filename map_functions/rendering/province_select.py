import pygame
from data.constants import SCREEN_WIDTH

def draw_province_select(self, surface):
    cx, cy = self.selected_province["center"]
    for offset in [0, -self.map_w, self.map_w]:
        sx = (cx + offset - self.camera.pos.x) * self.camera.zoom
        sy = (cy - self.camera.pos.y) * self.camera.zoom + self.top_ui_height
        if -100 < sx < SCREEN_WIDTH + 100:
            pygame.draw.circle(surface, (255, 255, 0), (int(sx), int(sy)), max(2, int(4 * self.camera.zoom)), 2)