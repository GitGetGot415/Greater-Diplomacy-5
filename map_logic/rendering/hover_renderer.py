import pygame

def draw_hover_glow(map_screen, surface):
    """Draws the hover sticker snapped to the integer grid of the map."""
    if not map_screen.hover_glow_surf:
        return

    # 1. World coordinates of the province bounding box
    px, py = map_screen.hover_glow_rect.x, map_screen.hover_glow_rect.y
    pw, ph = map_screen.hover_glow_rect.width, map_screen.hover_glow_rect.height

    # 2. Calculate scaled dimensions
    scaled_w = int(pw * map_screen.camera.zoom)
    scaled_h = int(ph * map_screen.camera.zoom * map_screen.camera.tilt_factor)
    
    if scaled_w > 0 and scaled_h > 0:
        scaled_glow = pygame.transform.scale(map_screen.hover_glow_surf, (scaled_w, scaled_h))

        # THE FIX: We use int(self.camera.pos) just like the map blit does.
        # This ensures the glow 'jumps' at the exact same moment the map does.
        cam_x_int = int(map_screen.camera.pos.x)
        cam_y_int = int(map_screen.camera.pos.y)

        for offset in [0, -map_screen.map_w, map_screen.map_w]:
            # Subtract the integer camera pos, THEN multiply by zoom.
            sx = (px + offset - cam_x_int) * map_screen.camera.zoom
            sy = (py - cam_y_int) * map_screen.camera.zoom * map_screen.camera.tilt_factor + map_screen.top_ui_height
            
            # Final cast to int for blitting coordinates
            surface.blit(scaled_glow, (int(sx), int(sy)))