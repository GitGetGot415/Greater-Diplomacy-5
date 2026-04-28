import pygame
import json
import os
import base64
from map_logic.time_handler import TimeHandler
from data.io import country_io
import data.constants as c

def _load_default_images(map_obj):
    """Helper to auto-load flags and portraits from the local assets folder."""
    os.makedirs(c.FLAGS_DIR, exist_ok=True)
    os.makedirs(c.PORTRAITS_DIR, exist_ok=True)
    
    def encode_surf_to_b64(surf):
        img_str = pygame.image.tostring(surf, "RGB")
        return base64.b64encode(img_str).decode('utf-8')
        
    for country_name, n_data in map_obj.nation_data.items():
        # --- FLAG LOGIC ---
        f_path = f"{c.FLAGS_DIR}/{country_name}.png"
        d_path = c.DEFAULT_FLAG_PATH
        
        # 1. Prioritize local file if it exists (overwrites old baked data)
        if os.path.exists(f_path):
            try:
                img = pygame.image.load(f_path).convert()
                img = pygame.transform.scale(img, c.FLAG_SIZE)
                n_data["flag_data"] = encode_surf_to_b64(img)
            except: pass
        # 2. If no local file, but also no baked data, use default
        elif not n_data.get("flag_data"):
            try:
                if os.path.exists(d_path): img = pygame.image.load(d_path).convert()
                else: 
                    img = pygame.Surface(c.FLAG_SIZE)
                    img.fill((200, 200, 200))
                img = pygame.transform.scale(img, c.FLAG_SIZE)
                n_data["flag_data"] = encode_surf_to_b64(img)
            except: pass
            
        # --- PORTRAIT LOGIC ---
        p_path = f"{c.PORTRAITS_DIR}/{country_name}.png"
        d_path = c.DEFAULT_PORTRAIT_PATH
        
        # 1. Prioritize local file if it exists
        if os.path.exists(p_path):
            try:
                img = pygame.image.load(p_path).convert()
                img = pygame.transform.scale(img, c.PORTRAIT_SIZE)
                n_data["portrait_data"] = encode_surf_to_b64(img)
            except: pass
        # 2. If no local file, but also no baked data, use default
        elif not n_data.get("portrait_data"):
            try:
                if os.path.exists(d_path): img = pygame.image.load(d_path).convert()
                else:
                    img = pygame.Surface(c.PORTRAIT_SIZE)
                    img.fill((200, 200, 200))
                img = pygame.transform.scale(img, c.PORTRAIT_SIZE)
                n_data["portrait_data"] = encode_surf_to_b64(img)
            except: pass

def load_map_assets(self, load_path):
    
    import os

    # --- PROCEDURAL INTERCEPT ---
    if load_path == "PROCEDURAL":
        from map_logic.random_map import procedural_map_generator
        procedural_map_generator.generate_new_world(self)
        
        # After generating the base geography, setup standard variables
        self.player_country = "None"
        self.active_players = []
        self.current_player_index = 0
        self.loop_map = True
        self.time_manager = TimeHandler(start_year=1850)
        
        # Load the base nation templates so they are ready for the randomizer
        self.nation_data = country_io.load_all_country_data()
        _load_default_images(self) 
        # --- THE FIX: Use .get() with a fallback color ---
        self.nation_colors = {name: tuple(stats.get("color", [150, 150, 150])) for name, stats in self.nation_data.items()}
        return
        
    # --- DEFAULT FALLBACK LOGIC ---
    # If no path is provided (e.g., on main menu boot), default to the first available base map
    if not load_path:
        if os.path.exists(c.BASE_MAPS_DIR):
            available_maps = [d for d in os.listdir(c.BASE_MAPS_DIR) if os.path.isdir(os.path.join(c.BASE_MAPS_DIR, d))]
            if available_maps:
                load_path = os.path.join(c.BASE_MAPS_DIR, available_maps[0])
                
    if not load_path or not os.path.exists(load_path):
        raise FileNotFoundError(f"CRITICAL: No valid map found. Make sure {c.BASE_MAPS_DIR} contains at least one map folder.")

    # --- 1. Image Assets ---
    # We no longer need the 'if load_path:' check because we guaranteed a path above
    self.terrain_map = pygame.image.load(os.path.join(load_path, "terrain.png")).convert()
    self.id_map = pygame.image.load(os.path.join(load_path, "id_map.png")).convert()
    
    try:
        self.political_map = pygame.image.load(os.path.join(load_path, "political.png")).convert()
    except:
        self.political_map = pygame.image.load(os.path.join(load_path, "id_map.png")).convert()
        
    try:
        self.cores_map = pygame.image.load(os.path.join(load_path, "cores.png")).convert()
    except:
        self.cores_map = self.id_map.copy() 

    # --- 2. Load Metadata (The Save File) ---
    save_meta = None
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
                # --- RELATIONS INIT ---
                if "relations" not in self.nation_data[country]:
                    self.nation_data[country]["relations"] = {}
                # ----------------------

                if "research" in base_data:
                    current_res = self.nation_data[country].setdefault("research", {})
                    for tech_key, tech_val in base_data["research"].items():
                        if tech_key not in current_res:
                            current_res[tech_key] = tech_val
    else:
        # Fallback to default starting data
        self.nation_data = base_nation_data

    # --- FIX: INITIALIZE RELATIONS FOR STARTING WARS & FACTIONS ---
    for c_name, c_data in self.nation_data.items():
        for enemy in c_data.get("at_war_with", []):
            c_data.setdefault("relations", {})[enemy] = -100
        
        fac = c_data.get("faction", "")
        if fac:
            for other_c, other_d in self.nation_data.items():
                if other_c != c_name and other_d.get("faction", "") == fac:
                    c_data.setdefault("relations", {})[other_c] = 100
    # --------------------------------------------------------------

    _load_default_images(self)
    # --- THE FIX: Use .get() with a fallback color ---
    self.nation_colors = {name: tuple(stats.get("color", [150, 150, 150])) for name, stats in self.nation_data.items()}

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
        self.default_research = save_meta.get("default_research", None)
        
        self.time_manager = TimeHandler(start_year=save_meta["date"]["year"])
        self.time_manager.day = save_meta["date"]["day"]
        self.time_manager.month_index = save_meta["date"]["month"]
    else:
        self.player_country = "None"
        self.active_players = []
        self.current_player_index = 0
        self.loop_map = True
        self.default_research = None
        self.time_manager = TimeHandler(start_year=1850)

    # --- 5. Province Processing ---
    json_path = os.path.join(load_path, "map_data.json")
    if not os.path.exists(json_path):
        raise FileNotFoundError(f"CRITICAL: map_data.json is missing from {load_path}")

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
                v.update(saved_province)
        
        # --- THE WATER FIX ---
        terrain = v.get("terrain", "plains")
        if terrain in c.WATER_MAPPING:
            v["owner"] = c.WATER_MAPPING[terrain]
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