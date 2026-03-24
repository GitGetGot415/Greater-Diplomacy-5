import json
import pygame
import os
from datetime import datetime

def save_map_data(self, save_name=None):
    """Saves logical data and visual state into a named folder."""
    if not save_name:
        save_name = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    
    save_path = os.path.join("saves", save_name)
    if not os.path.exists(save_path):
        os.makedirs(save_path)

    # 1. Consolidated Data Structure
    save_dict = {
        "date": {
            "day": self.time_manager.day,
            "month": self.time_manager.month_index,
            "year": self.time_manager.year
        },
        "loop_map": self.loop_map, # Save the preference here
        "player_country": self.player_country, # <--- ADD THIS LINE
        "nation_data": self.nation_data, # <--- Save the whole dictionary here!
        "provinces": {} # All data for a specific province goes here
    }
    
    for data in self.map_data.values():
        # Store all associated lists and variables inside one key per province
        save_dict["provinces"][data["json_key"]] = {
            "owner": data["owner"],
            "is_coastal": data.get("is_coastal", False),
            "units": data.get("units", []),
            "deployment_queue": data.get("deployment_queue", []),
            "orders": data.get("orders", []),
            "resources": data.get("resources", [])
        }

    with open(os.path.join(save_path, "meta.json"), "w") as f:
        json.dump(save_dict, f, indent=4)
        
    # Visual states
    pygame.image.save(self.political_map, os.path.join(save_path, "political.png"))
    pygame.image.save(self.terrain_map, os.path.join(save_path, "terrain.png"))
    pygame.image.save(self.id_map, os.path.join(save_path, "id_map.png"))
    
    self.show_feedback(f"Saved: {save_name}")