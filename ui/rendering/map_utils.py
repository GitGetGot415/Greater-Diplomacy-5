import pygame

import data.constants as c
from ui.rendering import province_pixels

def avoid_chroma(color):
    """Nudges a nation color off the chroma key used as the map's colorkey.

    A nation painted in exactly COLOR_CHROMA_PINK would be punched out as
    transparent when the political map is blitted, so shift it by one bit of
    red. Called wherever a nation color reaches a surface -- conquest,
    core painting and the blended multi-core average all need the same guard.
    """
    if tuple(color) == c.COLOR_CHROMA_PINK:
        r, g, b = c.COLOR_CHROMA_PINK
        return (r - 1, g, b)
    return color

def update_single_province_surface(political_surf, id_map, province_color_id, new_nation_color):
    """
    Paints exactly the pixels of one province, in one flat color.
    Guarantees other tiles remain untouched.

    The province's pixels come from the id map's cached index, so a repaint
    touches only that province instead of scanning the whole id map for its
    color and blitting a map-sized sticker.
    """
    pixels = province_pixels.for_id_map(id_map)
    slot = pixels.slot_for(province_color_id)
    if slot is None:
        return  # No pixel shows this color.
    xs, ys = pixels.pixels_of(slot)
    surface_pixels = pygame.surfarray.pixels3d(political_surf)
    surface_pixels[xs, ys] = tuple(new_nation_color)[:3]
    del surface_pixels  # Unlocks the surface.

def create_glow_surface(id_map, province_color_id):
    """Creates a cropped semi-transparent sticker for the hover effect."""
    mask = pygame.mask.from_threshold(id_map, province_color_id, (1, 1, 1, 255))
    rect = mask.get_bounding_rects()[0]
    
    # Using convert_alpha() is faster for blitting transparent surfaces
    cropped_glow = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA).convert_alpha()
    
    for x in range(rect.width):
        for y in range(rect.height):
            if mask.get_at((rect.x + x, rect.y + y)):
                 # Pure white with 80 alpha
                cropped_glow.set_at((x, y), (255, 255, 255, 80))
                
    return cropped_glow, rect

def apply_tilt(surface, tilt_factor, condition_check=True):
    """Dynamically applies camera tilt compression to a surface."""
    if tilt_factor < 0.99 and condition_check:
        new_w = surface.get_width()
        new_h = max(1, int(surface.get_height() * tilt_factor))
        return pygame.transform.scale(surface, (new_w, new_h))
    return surface
