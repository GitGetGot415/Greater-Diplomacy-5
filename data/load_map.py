import pygame
import json
import os
from map_functions.logic.time_handler import TimeHandler
from data import country_io

def load_map_assets(self, load_path):
    # --- 1. Image Assets ---
    if load_path:
        self.terrain_map = pygame.image.load(os.path.join(load_path, "terrain.png")).convert()
        self.id_map = pygame.image.load(os.path.join(load_path, "id_map.png")).convert()
        # the political map can be regenerated if it doesn't exist, that's fine
        try:
            self.political_map = pygame.image.load(os.path.join(load_path, "political.png")).convert()
        except:
            self.political_map = pygame.image.load(os.path.join(load_path, "id_map.png")).convert()
    else:
        self.terrain_map = pygame.image.load("map_tools/terrain_map.png").convert()
        self.id_map = pygame.image.load("map_tools/provinces_id_map.png").convert()
        self.political_map = self.id_map.copy()

    # --- 2. Load Metadata (The Save File) ---
    save_meta = None
    if load_path:
        meta_path = os.path.join(load_path, "meta.json")
        if os.path.exists(meta_path):
            with open(meta_path, "r") as f:
                save_meta = json.load(f)

    # --- 3. Load Nation Data (The Critical Fix) ---
    # We load the dictionary FIRST, then extract player info
    if save_meta and "nation_data" in save_meta:
        self.nation_data = save_meta["nation_data"]
    else:
        # Fallback to default starting data
        self.nation_data = country_io.load_all_country_data()

    # Update visual colors from the loaded data
    self.nation_colors = {name: tuple(stats["color"]) for name, stats in self.nation_data.items()}

    # --- 4. Set Player/Map Properties ---
    if save_meta:
        self.player_country = save_meta.get("player_country", "None")
        self.loop_map = save_meta.get("loop_map", False)
        self.default_research = save_meta.get("default_research", None) # <-- ADDED THIS
        # Time
        self.time_manager = TimeHandler(start_year=save_meta["date"]["year"])
        self.time_manager.day = save_meta["date"]["day"]
        self.time_manager.month_index = save_meta["date"]["month"]
    else:
        self.player_country = "None"
        self.loop_map = True
        self.default_research = None # <-- ADDED THIS
        self.time_manager = TimeHandler(start_year=1900)

    # --- 5. Province Processing ---
    with open("map_tools/map_data.json", "r") as f:
        self.raw_json_data = json.load(f) 

    self.map_data = {}
    self.id_to_province = {}
    
    for k, v in self.raw_json_data.items():
        color_tuple = tuple(map(int, k.strip("()").split(",")))
        
        # Overlay save data onto provinces if it exists
        if save_meta and "provinces" in save_meta:
            saved_province = save_meta["provinces"].get(k)
            if saved_province:
                v.update(saved_province) # Merges owner, units, etc.
        
        # Standardize defaults
        v["owner"] = v.get("owner", "None")
        v["cores"] = v.get("cores", [])
        v["units"] = v.get("units", [])
        v["deployment_queue"] = v.get("deployment_queue", [])
        v["json_key"], v["map_color"] = k, color_tuple
        
        self.map_data[color_tuple] = v
        self.id_to_province[v["id"]] = v