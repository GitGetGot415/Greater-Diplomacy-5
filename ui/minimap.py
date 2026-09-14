import pygame
import data.constants as c

# ==========================================
# LAYOUT
# ==========================================

MINIMAP_WIDTH = 240
MINIMAP_MARGIN_X = 20
MINIMAP_MARGIN_Y = 80
MINIMAP_BG_COLOR = (10, 10, 10)
MINIMAP_BORDER_COLOR = (100, 100, 100)
MINIMAP_VIEWBOX_COLOR = (255, 255, 0)


def minimap_rect(map_screen, screen_width, screen_height):
    """Return the shared minimap bounds used by drawing and top-right layout."""
    map_aspect = map_screen.map_h / map_screen.map_w
    mini_w = MINIMAP_WIDTH
    mini_h = int(mini_w * map_aspect)
    return pygame.Rect(screen_width - mini_w - MINIMAP_MARGIN_X,
                       screen_height - mini_h - MINIMAP_MARGIN_Y,
                       mini_w, mini_h)


def _map_image(map_screen, size, ocean_color):
    """Return a cached miniaturized active map layer, refreshing on layer changes."""
    source = getattr(map_screen, "active_map", None)
    if source is None:
        return None
    key = (id(source), source.get_size(), tuple(size), tuple(ocean_color))
    cached = getattr(map_screen, "_minimap_image_cache", None)
    if not cached or cached[0] != key:
        # Composite the chroma-key source *before* smoothing. Smoothscale
        # turns #ff00ff into near-pink edge/interior pixels (#fd00fd, etc.),
        # which a colorkey applied afterwards cannot remove.
        composite = pygame.Surface(source.get_size())
        composite.fill(ocean_color)
        composite.blit(source, (0, 0))
        image = pygame.transform.smoothscale(composite, size)
        cached = (key, image)
        map_screen._minimap_image_cache = cached
    return cached[1]


def draw_minimap(map_screen, surface, screen_width, screen_height):
    rect = minimap_rect(map_screen, screen_width, screen_height)
    mx, my, mini_w, mini_h = rect

    # Match the main renderer: chroma-key water in political layers reveals
    # the normal dynamic ocean color rather than a pink/black backing surface.
    ocean_color = getattr(map_screen, "bg_color", c.OCEAN_DARK_BLUE)
    pygame.draw.rect(surface, ocean_color, rect)
    # Show the same political/terrain layer as the main map.  The fallback is
    # retained for lightweight tools that do not construct an active surface.
    image = _map_image(map_screen, rect.size, ocean_color)
    if image is not None:
        surface.blit(image, rect.topleft)
    pygame.draw.rect(surface, MINIMAP_BORDER_COLOR, rect, 1)
    
    # --- UI Offset Logic ---
    visible_map_width = screen_width - c.UI_LEFT_OFFSET

    # 1. Calculate how many 'world pixels' the red bar covers
    world_ui_offset = c.UI_LEFT_OFFSET / map_screen.camera.zoom
    
    # 2. Wrap the shifted X coordinate so it seamlessly loops around the globe
    wrapped_x = (map_screen.camera.pos.x + world_ui_offset) % map_screen.map_w
    
    # 3. Calculate the Start Position (vx)
    vx = (wrapped_x / map_screen.map_w) * mini_w + mx
    vy = (map_screen.camera.pos.y / map_screen.map_h) * mini_h + my
    
    # 4. Calculate the Width (vw)
    vw = (visible_map_width / map_screen.camera.zoom / map_screen.map_w) * mini_w
    vh = ((screen_height - map_screen.total_ui_h) / (map_screen.camera.zoom * map_screen.camera.tilt_factor) / map_screen.map_h) * mini_h
    
    # --- Draw with Wrap-around support & Clamping ---
    vx_relative = vx - mx
    
    # Clamp vertical rendering so the yellow box doesn't draw up into the sky/void
    draw_vy = max(my, vy)
    draw_vh = vh - (draw_vy - vy) # Shrink height if we clamped Y
    
    if draw_vh > 0:
        if vx_relative + vw > mini_w:
            # Part A: Draws from vx to the right edge of the minimap
            first_part_w = mini_w - vx_relative
            if first_part_w > 0:
                pygame.draw.rect(surface, (255, 255, 0), (vx, draw_vy, first_part_w, draw_vh), 1)
            
            # Part B: Draws the remainder starting from the left edge (mx)
            second_part_w = vw - first_part_w
            pygame.draw.rect(surface, (255, 255, 0), (mx, draw_vy, second_part_w, draw_vh), 1)
        else:
            pygame.draw.rect(surface, (255, 255, 0), (vx, draw_vy, vw, draw_vh), 1)
