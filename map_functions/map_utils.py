import pygame

def update_single_province_surface(political_surf, id_map, province_color_id, new_nation_color):
    """
    Updates exactly one province using a clean mask blit. 
    Guarantees other tiles remain untouched.
    """
    # 1. Create a Mask of where the province is in the id_map
    # from_threshold finds the exact pixels matching the ID color
    mask = pygame.mask.from_threshold(id_map, province_color_id, (1, 1, 1, 255))
    
    # 2. Convert that Mask into a Surface
    # setcolor: The color of the province (your new nation color)
    # unsetcolor: Fully transparent (0 alpha), so it doesn't touch other tiles
    province_sticker = mask.to_surface(
        setcolor=new_nation_color, 
        unsetcolor=(0, 0, 0, 0)
    )
    
    # 3. Blit the sticker onto the political map
    # Since the background of the sticker is (0,0,0,0), 
    # only the nation color pixels are transferred.
    political_surf.blit(province_sticker, (0, 0))

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