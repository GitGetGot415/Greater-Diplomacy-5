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
    if self.is_editor:
        # Save to User's Downloads Folder
        downloads_path = Path(__file__).resolve().parents[2]
        save_path = os.path.join(downloads_path, "scenarios", "map_editor", f"MapExport_{save_name}")
    else:
        # Standard Game Save
        save_path = os.path.join(c.SAVES_DIR, save_name)

    if not os.path.exists(save_path):
        os.makedirs(save_path)

    # 1. Consolidated Data Structure
    save_dict = queries.build_save_dict(self)

    # Actual map data
    with open(os.path.join(save_path, "meta.json"), "w") as f:
        json.dump(save_dict, f, indent=c.SAVE_INDENT)
        
    # Raw structural geometry (so this save is completely self-contained)
    with open(os.path.join(save_path, "map_data.json"), "w") as f:
        json.dump(self.raw_json_data, f, indent=c.SAVE_INDENT)
    
    # History
    if hasattr(self, 'history'):
        # Scrub images from history snapshots before writing (they were skipped at snapshot time for speed)
        for turn_snap in self.history.values():
            nd = turn_snap.get("nation_data")
            if nd:
                queries.scrub_default_images(nd)
        with open(os.path.join(save_path, "history.json"), "w") as f:
            json.dump(self.history, f, indent=c.HISTORY_INDENT)
            
    # Visual states
    pygame.image.save(self.political_map, os.path.join(save_path, "political.png"))
    pygame.image.save(self.terrain_map, os.path.join(save_path, "terrain.png"))
    pygame.image.save(self.id_map, os.path.join(save_path, "id_map.png"))
    pygame.image.save(self.cores_map, os.path.join(save_path, "cores.png"))
    
    self.show_feedback(f"Exported: {save_name}" if self.is_editor else f"Saved: {save_name}")