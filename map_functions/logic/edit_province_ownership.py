import pygame
import random
from map_functions.data import country_io
from map_functions.logic import map_utils

def conquer_province(self):
    """Logic for changing province ownership and updating visuals instantly."""
    if self.selected_province:
        # 1. Logic Update
        # Get the dictionary {Name: Color}
        nations_dict = country_io.get_nation_colors() 
        
        # Convert dictionary keys to a list so random.choice can use it
        # nations_list = list(nations_dict.keys())
        nations_list = ["rome", "gaul"]
        
        # Pick a random country name
        new_owner = random.choice(nations_list)
        self.selected_province["owner"] = new_owner
        
        # 2. Visual Update (Targeted Masked Blit)
        # We pull the color from our freshly loaded nations_dict
        new_color = nations_dict[new_owner]
        
        map_utils.update_single_province_surface(
            self.political_map, 
            self.id_map, 
            self.selected_province["map_color"], 
            new_color
        )
        
        # 3. View Sync
        if self.map_mode == "POLITICAL":
            self.active_map = self.political_map
            
        # Optional: Show feedback so you know who took it!
        self.show_feedback(f"Province {self.selected_province['id']} conquered by {new_owner}!")