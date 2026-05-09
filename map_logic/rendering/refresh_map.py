import pygame
import numpy as np
import data.constants as c
from data import queries

def apply_border_shading(out_2d, owner_2d, id_array, water_ids):
    """
    Helper function that applies HoI4-style inner borders and gradient shading.
    Used by Political, Relations, and Cores maps.
    """
    # Bridge the black gaps on the OWNER array so internal province borders are ignored.
    filled_owner = np.copy(owner_2d)
    for _ in range(2): 
        is_gap = (filled_owner == 0)
        filled_owner[is_gap] = np.roll(filled_owner, 1, axis=1)[is_gap]
        is_gap = (filled_owner == 0)
        filled_owner[is_gap] = np.roll(filled_owner, -1, axis=1)[is_gap]
        is_gap = (filled_owner == 0)
        filled_owner[is_gap] = np.roll(filled_owner, 1, axis=0)[is_gap]
        is_gap = (filled_owner == 0)
        filled_owner[is_gap] = np.roll(filled_owner, -1, axis=0)[is_gap]

    # Identify water IDs and unclaimed IDs to exclude them from shading
    is_land = ~np.isin(filled_owner, water_ids) & (filled_owner != 0)

    # Shift arrays to look at neighboring owners
    shift_u = np.roll(filled_owner, 1, axis=1)
    shift_d = np.roll(filled_owner, -1, axis=1)
    shift_l = np.roll(filled_owner, 1, axis=0)
    shift_r = np.roll(filled_owner, -1, axis=0)

    # Calculate Edge Depths
    edge_1 = is_land & ((filled_owner != shift_u) | (filled_owner != shift_d) | \
                        (filled_owner != shift_l) | (filled_owner != shift_r))
    edge_2 = is_land & ~edge_1 & (np.roll(edge_1, 1, axis=1) | np.roll(edge_1, -1, axis=1) | \
                                  np.roll(edge_1, 1, axis=0) | np.roll(edge_1, -1, axis=0))
    edge_3 = is_land & ~edge_1 & ~edge_2 & (np.roll(edge_2, 1, axis=1) | np.roll(edge_2, -1, axis=1) | \
                                            np.roll(edge_2, 1, axis=0) | np.roll(edge_2, -1, axis=0))
    edge_4 = is_land & ~edge_1 & ~edge_2 & ~edge_3 & (np.roll(edge_3, 1, axis=1) | np.roll(edge_3, -1, axis=1) | \
                                                      np.roll(edge_3, 1, axis=0) | np.roll(edge_3, -1, axis=0))

    interior = is_land & ~edge_1 & ~edge_2 & ~edge_3 & ~edge_4

    # Unpack back into an RGB 3D array
    out_3d = np.empty_like(id_array)
    out_3d[:, :, 0] = (out_2d >> 16) & 0xFF
    out_3d[:, :, 1] = (out_2d >> 8) & 0xFF
    out_3d[:, :, 2] = out_2d & 0xFF
    
    # --- APPLY GRADIENT SHADING ---
    out_3d[edge_1] = (out_3d[edge_1] * 0.7).astype(np.uint8)
    # edge_2 remains untouched (100% brightness)
    out_3d[edge_3] = (out_3d[edge_3] * 0.8).astype(np.uint8)
    out_3d[edge_4] = (out_3d[edge_4] * 0.6).astype(np.uint8)
    out_3d[interior] = (out_3d[interior] * 0.4).astype(np.uint8)
    
    return out_3d


def get_id_2d_array(id_map):
    """Helper to avoid duplicating the 3D-to-2D bitwise array extraction."""
    id_array = pygame.surfarray.pixels3d(id_map)
    id_2d = (id_array[:, :, 0].astype(np.uint32) << 16) | \
            (id_array[:, :, 1].astype(np.uint32) << 8) | \
             id_array[:, :, 2].astype(np.uint32)
    return id_array, id_2d


def refresh_political_map(self):
    """Rebuilds the entire political map surface instantly using a NumPy LUT."""
    timer = pygame.time.get_ticks()
    
    id_array, id_2d = get_id_2d_array(self.id_map)
             
    lut = np.zeros(16777216, dtype=np.uint32)
    owner_lut = np.zeros(16777216, dtype=np.uint32)
    
    owner_to_int = {}
    next_owner_id = 1 
    
    for color_key, data in self.map_data.items():
        terrain_type = data.get("terrain", "plains")
        
        if terrain_type in c.VISUAL_WATER_MAPPING:
            owner = c.VISUAL_WATER_MAPPING[terrain_type]
            color = c.COLOR_CHROMA_PINK # Magic pink
        else:
            owner = data.get("owner", "Unclaimed")
            color = self.nation_colors.get(owner, (255, 255, 255))
            
            # Prevent colorkey collision
            if tuple(color) == c.COLOR_CHROMA_PINK:
                color = (254, 0, 255) 
        
        if owner not in owner_to_int:
            owner_to_int[owner] = next_owner_id
            next_owner_id += 1
            
        packed_key = (color_key[0] << 16) | (color_key[1] << 8) | color_key[2]
        packed_color = (color[0] << 16) | (color[1] << 8) | color[2]
        
        lut[packed_key] = packed_color
        owner_lut[packed_key] = owner_to_int[owner]
        
    out_2d = lut[id_2d]
    owner_2d = owner_lut[id_2d]
    
    # Process Shading
    water_ids = [owner_to_int.get("Ocean", -1), owner_to_int.get("Lakes", -1), owner_to_int.get("Unclaimed", -1)]
    out_3d = apply_border_shading(out_2d, owner_2d, id_array, water_ids)
    
    new_pol_surf = pygame.Surface(self.id_map.get_size(), depth=24)
    pygame.surfarray.blit_array(new_pol_surf, out_3d)
    new_pol_surf.set_colorkey(c.COLOR_CHROMA_PINK) 
    
    self.political_map = new_pol_surf
    if self.map_mode == "POLITICAL":
        self.active_map = self.political_map
        
    print(f"Political map refreshed in {pygame.time.get_ticks() - timer} ms")


def refresh_relations_map(self):
    """Rebuilds the relations map surface instantly using a NumPy LUT."""
    timer = pygame.time.get_ticks()
    
    id_array, id_2d = get_id_2d_array(self.id_map)
             
    lut = np.zeros(16777216, dtype=np.uint32)
    owner_lut = np.zeros(16777216, dtype=np.uint32)
    
    owner_to_int = {}
    next_owner_id = 1
    
    player_data = self.nation_data.get(self.player_country, {})
    at_war = player_data.get("at_war_with", [])
    
    # --- NEW: Faction Tracking ---
    player_fac = player_data.get("faction", "")
    faction_members = queries.get_faction_members(player_fac, self.nation_data) if player_fac else []
    # -----------------------------
    
    for color_key, data in self.map_data.items():
        terrain_type = data.get("terrain", "plains")
        
        if terrain_type in c.VISUAL_WATER_MAPPING:
            owner = c.VISUAL_WATER_MAPPING[terrain_type]
            color = c.COLOR_CHROMA_PINK 
        else:
            # We track the owner for the borders...
            owner = data.get("owner", "Unclaimed")
            
            # ...But we override the colors based on relations
            if owner in ["Unclaimed", "None", ""]:
                color = (255, 255, 255)
            elif owner == self.player_country:
                color = (0, 0, 255)
            else:
                # Safely fetch the relation score (defaults to 0)
                relation = player_data.get("relations", {}).get(owner, 0)
                
                # Interpolate from -100 (Red) to 0 (Yellow) to +100 (Green)
                if relation < 0:
                    g_val = int(255 * (100 + relation) / 100.0)
                    color = (255, max(0, min(255, g_val)), 0)
                else:
                    r_val = int(255 * (100 - relation) / 100.0)
                    color = (max(0, min(255, r_val)), 255, 0)
                
        if owner not in owner_to_int:
            owner_to_int[owner] = next_owner_id
            next_owner_id += 1
            
        packed_key = (color_key[0] << 16) | (color_key[1] << 8) | color_key[2]
        packed_color = (color[0] << 16) | (color[1] << 8) | color[2]
        
        lut[packed_key] = packed_color
        owner_lut[packed_key] = owner_to_int[owner]
        
    out_2d = lut[id_2d]
    owner_2d = owner_lut[id_2d]
    
    # Process Shading
    water_ids = [owner_to_int.get("Ocean", -1), owner_to_int.get("Lakes", -1), owner_to_int.get("Unclaimed", -1)]
    out_3d = apply_border_shading(out_2d, owner_2d, id_array, water_ids)
    
    new_rel_surf = pygame.Surface(self.id_map.get_size(), depth=24)
    pygame.surfarray.blit_array(new_rel_surf, out_3d)
    new_rel_surf.set_colorkey((255, 0, 255)) 
    
    self.relations_map = new_rel_surf
    if self.map_mode == "RELATIONS":
        self.active_map = self.relations_map
        
    print(f"Relations map refreshed in {pygame.time.get_ticks() - timer} ms")


def refresh_cores_map(self):
    """Rebuilds the cores map surface instantly using a NumPy LUT."""
    timer = pygame.time.get_ticks()
    
    id_array, id_2d = get_id_2d_array(self.id_map)
             
    lut = np.zeros(16777216, dtype=np.uint32)
    owner_lut = np.zeros(16777216, dtype=np.uint32)
    
    owner_to_int = {}
    next_owner_id = 1 
        
    for color_key, data in self.map_data.items():
        terrain_type = data.get("terrain", "plains")
        
        if terrain_type in c.VISUAL_WATER_MAPPING:
            owner = c.VISUAL_WATER_MAPPING[terrain_type]
            color = (255, 0, 255) 
        else:
            cores = data.get("cores", [])
            
            if not cores:
                owner = "Unclaimed"
                color = self.nation_colors.get(owner, (255, 255, 255))
            elif len(cores) == 1:
                owner = cores[0]
                color = self.nation_colors.get(owner, (255, 255, 255))
            else:
                owner = ",".join(sorted(cores)) 
                
                r = g = b = valid = 0
                for core_name in cores:
                    c_color = self.nation_colors.get(core_name)
                    if c_color:
                        r += c_color[0]
                        g += c_color[1]
                        b += c_color[2]
                        valid += 1
                
                color = (r // valid, g // valid, b // valid) if valid > 0 else (255, 255, 255)
            
            if tuple(color) == (255, 0, 255):
                color = (254, 0, 255)
        
        if owner not in owner_to_int:
            owner_to_int[owner] = next_owner_id
            next_owner_id += 1
            
        packed_key = (color_key[0] << 16) | (color_key[1] << 8) | color_key[2]
        packed_color = (color[0] << 16) | (color[1] << 8) | color[2]
        
        lut[packed_key] = packed_color
        owner_lut[packed_key] = owner_to_int[owner]
        
    out_2d = lut[id_2d]
    owner_2d = owner_lut[id_2d]
    
    # Process Shading
    water_ids = [owner_to_int.get("Ocean", -1), owner_to_int.get("Lakes", -1), owner_to_int.get("Unclaimed", -1)]
    out_3d = apply_border_shading(out_2d, owner_2d, id_array, water_ids)
    
    new_pol_surf = pygame.Surface(self.id_map.get_size(), depth=24)
    pygame.surfarray.blit_array(new_pol_surf, out_3d)
    new_pol_surf.set_colorkey((255, 0, 255)) 
    
    self.cores_map = new_pol_surf
    if self.map_mode == "CORES":
        self.active_map = self.cores_map
        
    print(f"Cores map refreshed in {pygame.time.get_ticks() - timer} ms")

def refresh_factions_map(self):
    """Rebuilds the factions map surface instantly using a NumPy LUT."""
    timer = pygame.time.get_ticks()
    
    id_array, id_2d = get_id_2d_array(self.id_map)
             
    lut = np.zeros(16777216, dtype=np.uint32)
    owner_lut = np.zeros(16777216, dtype=np.uint32)
    
    owner_to_int = {}
    next_owner_id = 1
    
    faction_colors = {}
    
    def get_faction_color(fac_name):
        # Deterministic pseudo-random color based on faction name string
        h = sum(ord(c) * (i+1) for i, c in enumerate(fac_name))
        return ((h * 123) % 200 + 55, (h * 321) % 200 + 55, (h * 213) % 200 + 55)
    
    for color_key, data in self.map_data.items():
        terrain_type = data.get("terrain", "plains")
        
        if terrain_type in c.VISUAL_WATER_MAPPING:
            owner = c.VISUAL_WATER_MAPPING[terrain_type]
            color = (255, 0, 255) 
        else:
            owner = data.get("owner", "Unclaimed")
            fac = self.nation_data.get(owner, {}).get("faction", "")
            
            if owner in ["Unclaimed", "None", ""]:
                color = (255, 255, 255)
            elif not fac:
                color = (150, 150, 150) # Neutral grey for non-faction countries
            else:
                leader = queries.get_faction_leader(fac, self.nation_data)
                if leader and leader in self.nation_colors:
                    faction_colors[fac] = self.nation_colors[leader]
                elif fac not in faction_colors:
                    faction_colors[fac] = get_faction_color(fac)
                color = faction_colors[fac]
                
        if owner not in owner_to_int:
            owner_to_int[owner] = next_owner_id
            next_owner_id += 1
            
        packed_key = (color_key[0] << 16) | (color_key[1] << 8) | color_key[2]
        packed_color = (color[0] << 16) | (color[1] << 8) | color[2]
        
        lut[packed_key] = packed_color
        owner_lut[packed_key] = owner_to_int[owner]
        
    out_2d = lut[id_2d]
    owner_2d = owner_lut[id_2d]
    
    # Process Shading
    water_ids = [owner_to_int.get("Ocean", -1), owner_to_int.get("Lakes", -1), owner_to_int.get("Unclaimed", -1)]
    out_3d = apply_border_shading(out_2d, owner_2d, id_array, water_ids)
    
    new_fac_surf = pygame.Surface(self.id_map.get_size(), depth=24)
    pygame.surfarray.blit_array(new_fac_surf, out_3d)
    new_fac_surf.set_colorkey((255, 0, 255)) 
    
    self.factions_map = new_fac_surf
    if self.map_mode == "FACTIONS":
        self.active_map = self.factions_map
        
    print(f"Factions map refreshed in {pygame.time.get_ticks() - timer} ms")