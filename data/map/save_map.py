import json
import pygame
import os
from datetime import datetime
from pathlib import Path
import data.constants as c
from data import queries

def save_map_data(self, save_name=None):
    """Saves logical data and visual state."""
    queries.scrub_default_images(self.nation_data)
    
    if not save_name:
        save_name = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    
    # --- CONDITIONAL PATH LOGIC ---
    if getattr(self, 'is_editor', False):
        # Save to User's Downloads Folder
        downloads_path = Path(__file__).resolve().parents[2]
        save_path = os.path.join(downloads_path, "scenarios", "map_editor", f"MapExport_{save_name}")
    else:
        # Standard Game Save
        save_path = os.path.join(c.SAVES_DIR, save_name)

    if not os.path.exists(save_path):
        os.makedirs(save_path)

    # 1. Consolidated Data Structure
    save_dict = {
        "date": {
            "day": self.time_manager.day,
            "month": self.time_manager.month_index,
            "year": self.time_manager.year,
            "total_turns": getattr(self.time_manager, 'total_turns', 0)
        },
        "loop_map": self.loop_map,
        "player_country": self.player_country,
        "active_players": getattr(self, "active_players", [self.player_country]),
        "current_player_index": getattr(self, "current_player_index", 0),
        "default_research": getattr(self, "default_research", None),
        "nation_data": self.nation_data,
        "provinces": {},
        "scenario_settings": getattr(self, "scenario_settings", {
            "fog_of_war": c.DEFAULT_FOG_OF_WAR,
            "casus_belli_required": c.DEFAULT_CASUS_BELLI
        })
    }
    
    for data in self.map_data.values():
        # Store all associated lists and variables inside one key per province
        save_dict["provinces"][data["json_key"]] = {
            "owner": data["owner"],
            "cores": data.get("cores", []),
            "is_coastal": data.get("is_coastal", False),
            "units": data.get("units", []),
            "unit_queue": data.get("unit_queue", []),
            "building_queue": data.get("building_queue", []),
            "orders": data.get("orders", []),
            "resources": data.get("resources", []),
            "buildings": data.get("buildings", [])
        }

    # Actual map data
    with open(os.path.join(save_path, "meta.json"), "w") as f:
        json.dump(save_dict, f, indent=c.SAVE_INDENT)
        
    # Raw structural geometry (so this save is completely self-contained)
    with open(os.path.join(save_path, "map_data.json"), "w") as f:
        json.dump(self.raw_json_data, f, indent=c.SAVE_INDENT)
    
    # History
    if hasattr(self, 'history'):
        with open(os.path.join(save_path, "history.json"), "w") as f:
            json.dump(self.history, f, indent=c.HISTORY_INDENT)
            
    # Visual states
    pygame.image.save(self.political_map, os.path.join(save_path, "political.png"))
    pygame.image.save(self.terrain_map, os.path.join(save_path, "terrain.png"))
    pygame.image.save(self.id_map, os.path.join(save_path, "id_map.png"))
    pygame.image.save(self.cores_map, os.path.join(save_path, "cores.png"))
    
    self.show_feedback(f"Exported: {save_name}" if self.is_editor else f"Saved: {save_name}")