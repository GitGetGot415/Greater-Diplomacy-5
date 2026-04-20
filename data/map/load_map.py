import pygame
import json
import os
import base64
from map_functions.logic.time_handler import TimeHandler
from data.io import country_io
from data.constants import WATER_MAPPING

def _load_default_images(map_obj):
    """Helper to auto-load flags and portraits from the local assets folder."""
    os.makedirs("assets/flags", exist_ok=True)
    os.makedirs("assets/portraits", exist_ok=True)
    
    def encode_surf_to_b64(surf):
        img_str = pygame.image.tostring(surf, "RGB")
        return base64.b64encode(img_str).decode('utf-8')
        
    for country_name, n_data in map_obj.nation_data.items():
        if not n_data.get("flag_data"):
            f_path = f"assets/flags/{country_name}.png"
            d_path = "assets/flags/default_flag.png"
            try:
                if os.path.exists(f_path): img = pygame.image.load(f_path).convert()
                elif os.path.exists(d_path): img = pygame.image.load(d_path).convert()
                else: 
                    img = pygame.Surface((60, 40))
                    img.fill((200, 200, 200))
                img = pygame.transform.scale(img, (60, 40))
                n_data["flag_data"] = encode_surf_to_b64(img)
            except: pass
            
        if not n_data.get("portrait_data"):
            p_path = f"assets/portraits/{country_name}.png"
            d_path = "assets/portraits/default_portrait.png"
            try:
                if os.path.exists(p_path): img = pygame.image.load(p_path).convert()
                elif os.path.exists(d_path): img = pygame.image.load(d_path).convert()
                else:
                    # FIX: Match the 60x60 size used by sidebar_info.py
                    img = pygame.Surface((60, 60))
                    img.fill((200, 200, 200))
                # FIX: Match the 60x60 size used by sidebar_info.py
                img = pygame.transform.scale(img, (60, 60))
                n_data["portrait_data"] = encode_surf_to_b64(img)
            except: pass

def load_map_assets(self, load_path):
    # --- PROCEDURAL INTERCEPT ---
    if load_path == "PROCEDURAL":
        from map_functions.logic import procedural_map_generator
        procedural_map_generator.generate_new_world(self)
        
        # After generating the base geography, setup standard variables
        self.player_country = "None"
        self.active_players = []
        self.current_player_index = 0
        self.loop_map = True
        self.time_manager = TimeHandler(start_year=1850)
        
        # Load the base nation templates so they are ready for the randomizer
        self.nation_data = country_io.load_all_country_data()
        
        _load_default_images(self) # Inject here to catch procedurals
        
        self.nation_colors = {name: tuple(stats["color"]) for name, stats in self.nation_data.items()}
        return # Skip the rest of the normal loading process!
    
    # --- 1. Image Assets ---
    if load_path:
        self.terrain_map = pygame.image.load(os.path.join(load_path, "terrain.png")).convert()
        self.id_map = pygame.image.load(os.path.join(load_path, "id_map.png")).convert()
        # the political map can be regenerated if it doesn't exist, that's fine
        try:
            self.political_map = pygame.image.load(os.path.join(load_path, "political.png")).convert()
        except:
            self.political_map = pygame.image.load(os.path.join(load_path, "id_map.png")).convert()
            
        # --- NEW: Load Cores Map ---
        try:
            self.cores_map = pygame.image.load(os.path.join(load_path, "cores.png")).convert()
        except:
            self.cores_map = self.id_map.copy() 
            
    else:
        self.terrain_map = pygame.image.load("map_tools/terrain_map.png").convert()
        self.id_map = pygame.image.load("map_tools/provinces_id_map.png").convert()
        self.political_map = self.id_map.copy()
        self.cores_map = self.id_map.copy() # <--- NEW: Initialize default

    # --- 2. Load Metadata (The Save File) ---
    save_meta = None
    if load_path:
        meta_path = os.path.join(load_path, "meta.json")
        if os.path.exists(meta_path):
            with open(meta_path, "r") as f:
                save_meta = json.load(f)

    # --- 3. Load Nation Data (The Critical Fix) ---
    base_nation_data = country_io.load_all_country_data()

    if save_meta and "nation_data" in save_meta:
        self.nation_data = save_meta["nation_data"]
        
        # SYNC FIX: Merge any missing research keys from the base template 
        # so old map saves instantly get the updated tech tree.
        for country, base_data in base_nation_data.items():
            if country not in self.nation_data:
                self.nation_data[country] = base_data
            else:
                if "research" in base_data:
                    current_res = self.nation_data[country].setdefault("research", {})
                    for tech_key, tech_val in base_data["research"].items():
                        if tech_key not in current_res:
                            current_res[tech_key] = tech_val
    else:
        # Fallback to default starting data
        self.nation_data = base_nation_data

    # Update visual colors from the loaded data
    _load_default_images(self) # Inject here to catch loaded saves
    self.nation_colors = {name: tuple(stats["color"]) for name, stats in self.nation_data.items()}

    # --- 4. Set Player/Map Properties ---
    if save_meta:
        self.player_country = save_meta.get("player_country", "None")
        
        # --- HOTSEAT FIX ---
        # If we are in selection mode (new scenario/random map), we MUST start with an empty list
        if getattr(self, 'selection_mode', False):
            self.active_players = []
        else:
            # If loading a save, get the active players. Prevent ["None"] bug from older saves.
            loaded_players = save_meta.get("active_players", [self.player_country])
            self.active_players = [] if loaded_players == ["None"] else loaded_players
            
        self.current_player_index = save_meta.get("current_player_index", 0)
        self.loop_map = save_meta.get("loop_map", False)
        self.default_research = save_meta.get("default_research", None) # <-- ADDED THIS
        # Time
        self.time_manager = TimeHandler(start_year=save_meta["date"]["year"])
        self.time_manager.day = save_meta["date"]["day"]
        self.time_manager.month_index = save_meta["date"]["month"]
    else:
        self.player_country = "None"
        self.active_players = []
        self.current_player_index = 0
        self.loop_map = True
        self.default_research = None # <-- ADDED THIS
        self.time_manager = TimeHandler(start_year=1850)

    # --- 5. Province Processing ---
    # Determine which map_data.json to use
    json_path = "map_tools/map_data.json" # Legacy fallback
    
    if load_path and os.path.exists(os.path.join(load_path, "map_data.json")):
        json_path = os.path.join(load_path, "map_data.json")

    with open(json_path, "r") as f:
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
        
        # --- THE WATER FIX ---
        terrain = v.get("terrain", "plains")
        if terrain in WATER_MAPPING:
            v["owner"] = WATER_MAPPING[terrain]
        else:
            v["owner"] = v.get("owner", "None")
        # ---------------------

        v["cores"] = v.get("cores", [])
        v["units"] = v.get("units", [])
        v["deployment_queue"] = v.get("deployment_queue", [])

        res = v.get("resources", {})
        v["resources"] = res if isinstance(res, dict) else {}
        
        v["json_key"], v["map_color"] = k, color_tuple
        
        self.map_data[color_tuple] = v
        self.id_to_province[v["id"]] = v