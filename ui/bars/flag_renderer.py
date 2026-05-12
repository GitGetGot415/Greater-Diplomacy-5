import pygame
import data.constants as c
from data import queries

def draw_flag(map_screen, surface):
    """Handles decoding and drawing the nation's flag in the top UI bar."""
    if getattr(map_screen, 'hide_top_info', False):
        return
        
    # Determine which country to display
    display_country = map_screen.player_country
    if map_screen.selected_province:
        owner = map_screen.selected_province.get("owner", "Unclaimed")
        if owner not in c.UNPLAYABLE_NATIONS:
            display_country = owner
            
    player_data = map_screen.nation_data.get(display_country, {})
    flag_str = player_data.get("flag_data", "DEFAULT")
    
    flag_surf = queries.decode_b64_to_surf(flag_str, c.FLAG_SIZE, is_portrait=False)
    flag_surf = pygame.transform.scale(flag_surf, (120, 80))
    
    # Position it (Adjust X here if you want it further right)
    surface.blit(flag_surf, (20, 20))
    pygame.draw.rect(surface, (200, 200, 200), (20, 20, 120, 80), 1)