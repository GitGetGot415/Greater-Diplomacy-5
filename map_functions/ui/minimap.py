import pygame

def draw_minimap(self, surface, screen_width, screen_height):
        map_aspect = self.map_h / self.map_w
        mini_w = 240
        mini_h = int(mini_w * map_aspect)
        mx, my = screen_width - mini_w - 20, screen_height - mini_h - 80
        pygame.draw.rect(surface, (10, 10, 10), (mx, my, mini_w, mini_h))
        pygame.draw.rect(surface, (100, 100, 100), (mx, my, mini_w, mini_h), 1)
        vx = (self.camera.pos.x / self.map_w) * mini_w + mx
        vy = (self.camera.pos.y / self.map_h) * mini_h + my
        vw = (screen_width / self.camera.zoom / self.map_w) * mini_w
        vh = ((screen_height - self.total_ui_h) / self.camera.zoom / self.map_h) * mini_h
        if vx + vw > mx + mini_w:
            pygame.draw.rect(surface, (255, 255, 0), (vx, vy, (mx+mini_w)-vx, vh), 1)
            pygame.draw.rect(surface, (255, 255, 0), (mx, vy, vw-((mx+mini_w)-vx), vh), 1)
        else: pygame.draw.rect(surface, (255, 255, 0), (vx, vy, vw, vh), 1)