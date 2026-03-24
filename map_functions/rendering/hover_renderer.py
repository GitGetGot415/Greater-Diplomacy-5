import pygame

def draw_hover_glow(self, surface):
    """Draws the hover sticker snapped to the integer grid of the map."""
    if not self.hover_glow_surf:
        return

    # 1. World coordinates of the province bounding box
    px, py = self.hover_glow_rect.x, self.hover_glow_rect.y
    pw, ph = self.hover_glow_rect.width, self.hover_glow_rect.height

    # 2. Calculate scaled dimensions
    scaled_w = int(pw * self.camera.zoom)
    scaled_h = int(ph * self.camera.zoom)
    
    if scaled_w > 0 and scaled_h > 0:
        scaled_glow = pygame.transform.scale(self.hover_glow_surf, (scaled_w, scaled_h))

        # THE FIX: We use int(self.camera.pos) just like the map blit does.
        # This ensures the glow 'jumps' at the exact same moment the map does.
        cam_x_int = int(self.camera.pos.x)
        cam_y_int = int(self.camera.pos.y)

        for offset in [0, -self.map_w, self.map_w]:
            # Subtract the integer camera pos, THEN multiply by zoom.
            sx = (px + offset - cam_x_int) * self.camera.zoom
            sy = (py - cam_y_int) * self.camera.zoom + self.top_ui_height
            
            # Final cast to int for blitting coordinates
            surface.blit(scaled_glow, (int(sx), int(sy)))