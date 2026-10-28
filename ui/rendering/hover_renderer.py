import pygame


_HOVER_GLOW_CACHE_LIMIT = 16


def _scaled_hover_glow(map_screen, size):
    """Reuse the hover sticker while its province and camera scale are stable."""
    cache = getattr(map_screen, '_hover_glow_scale_cache', None)
    if cache is None:
        cache = {}
        map_screen._hover_glow_scale_cache = cache
    key = (id(map_screen.hover_glow_surf), tuple(size))
    cached = cache.get(key)
    if cached is not None:
        return cached
    scaled = pygame.transform.scale(map_screen.hover_glow_surf, size)
    if len(cache) >= _HOVER_GLOW_CACHE_LIMIT:
        cache.clear()
    cache[key] = scaled
    return scaled


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
        scaled_glow = _scaled_hover_glow(map_screen, (scaled_w, scaled_h))

        # THE FIX: We use int(self.camera.pos) just like the map blit does.
        # This ensures the glow 'jumps' at the exact same moment the map does.
        cam_x_int = int(map_screen.camera.pos.x)
        cam_y_int = int(map_screen.camera.pos.y)

        offsets = [0, -map_screen.map_w, map_screen.map_w] if map_screen.loop_map else [0]
        for offset in offsets:
            # Subtract the integer camera pos, THEN multiply by zoom.
            sx = (px + offset - cam_x_int) * map_screen.camera.zoom
            sy = (py - cam_y_int) * map_screen.camera.zoom * map_screen.camera.tilt_factor + map_screen.top_ui_height
            
            # Final cast to int for blitting coordinates
            surface.blit(scaled_glow, (int(sx), int(sy)))
