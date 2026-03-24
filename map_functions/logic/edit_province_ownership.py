import pygame
from map_functions.data import country_io
from map_functions.logic import map_utils

def conquer_province(self, province, new_owner):
    """Annexes a specific province to a specific country and updates visuals."""
    if province:
        # 1. Logic Update
        province["owner"] = new_owner
        
        # 2. Visual Update
        nations_dict = country_io.get_nation_colors() 
        new_color = nations_dict.get(new_owner, (255, 255, 255)) # Fallback to white if empty
        
        map_utils.update_single_province_surface(
            self.political_map, 
            self.id_map, 
            province["map_color"], 
            new_color
        )
        
        # 3. Sync the active view
        if self.map_mode == "POLITICAL":
            self.active_map = self.political_map