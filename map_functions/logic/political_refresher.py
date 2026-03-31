import pygame
import numpy as np

def refresh_political_map(self):
    """Rebuilds the entire political map surface instantly using a NumPy LUT."""
    timer = pygame.time.get_ticks()
    
    # 1. Extract raw 3D pixel data from the ID map
    id_array = pygame.surfarray.pixels3d(self.id_map)
    
    # 2. Pack the RGB values into a single 2D array of 24-bit integers
    id_2d = (id_array[:, :, 0].astype(np.uint32) << 16) | \
            (id_array[:, :, 1].astype(np.uint32) << 8) | \
             id_array[:, :, 2].astype(np.uint32)
             
    # 3. Create Lookup Tables (LUTs) for Colors AND Owners
    lut = np.zeros(16777216, dtype=np.uint32)
    owner_lut = np.zeros(16777216, dtype=np.uint32)
    
    owner_to_int = {}
    next_owner_id = 1 # We reserve 0 for the black border gaps
    
    water_mapping = {
        "ocean": "Ocean", "coastal_sea": "Ocean", 
        "inland_sea": "Ocean", "lakes": "Lakes"
    }
    
    # 4. Populate both LUTs
    for color_key, data in self.map_data.items():
        terrain_type = data.get("terrain", "plains")
        
        if terrain_type in water_mapping:
            owner = water_mapping[terrain_type]
            data["owner"] = owner
        else:
            owner = data.get("owner", "Unclaimed")
            
        # Removed the hardcoded lake color. 
        # It will now pull [10, 20, 40] straight from countries_data.json!
        color = self.nation_colors.get(owner, (255, 255, 255))
            
        # Map string owner to a unique integer
        if owner not in owner_to_int:
            owner_to_int[owner] = next_owner_id
            next_owner_id += 1
            
        packed_key = (color_key[0] << 16) | (color_key[1] << 8) | color_key[2]
        packed_color = (color[0] << 16) | (color[1] << 8) | color[2]
        
        lut[packed_key] = packed_color
        owner_lut[packed_key] = owner_to_int[owner]
        
    # 5. INSTANTLY map every pixel for both colors and ownership
    out_2d = lut[id_2d]
    owner_2d = owner_lut[id_2d]
    
    # --- BORDER HIGHLIGHT LOGIC (Owner-Based) ---
    # Bridge the black gaps on the OWNER array so internal borders are ignored.
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
    ocean_id = owner_to_int.get("Ocean", -1)
    lakes_id = owner_to_int.get("Lakes", -1)
    unclaimed_id = owner_to_int.get("Unclaimed", -1)
    is_land = (filled_owner != ocean_id) & (filled_owner != lakes_id)& (filled_owner != unclaimed_id)

    # Shift arrays to look at neighboring owners
    shift_u = np.roll(filled_owner, 1, axis=1)
    shift_d = np.roll(filled_owner, -1, axis=1)
    shift_l = np.roll(filled_owner, 1, axis=0)
    shift_r = np.roll(filled_owner, -1, axis=0)

    # Edge 1: Pixels that touch a DIFFERENT OWNER (color doesn't matter anymore!)
    edge_1 = is_land & ((filled_owner != shift_u) | (filled_owner != shift_d) | \
                        (filled_owner != shift_l) | (filled_owner != shift_r))

    # Edge 2: Pixels exactly 1 step inward from Edge 1
    edge_2 = is_land & ~edge_1 & (np.roll(edge_1, 1, axis=1) | np.roll(edge_1, -1, axis=1) | \
                                  np.roll(edge_1, 1, axis=0) | np.roll(edge_1, -1, axis=0))

    # Edge 3: Pixels exactly 2 steps inward
    edge_3 = is_land & ~edge_1 & ~edge_2 & (np.roll(edge_2, 1, axis=1) | np.roll(edge_2, -1, axis=1) | \
                                            np.roll(edge_2, 1, axis=0) | np.roll(edge_2, -1, axis=0))

    # Edge 4: Pixels exactly 3 steps inward
    edge_4 = is_land & ~edge_1 & ~edge_2 & ~edge_3 & (np.roll(edge_3, 1, axis=1) | np.roll(edge_3, -1, axis=1) | \
                                                      np.roll(edge_3, 1, axis=0) | np.roll(edge_3, -1, axis=0))

    # Interior: The rest of the country
    interior = is_land & ~edge_1 & ~edge_2 & ~edge_3 & ~edge_4
    # --------------------------------------------------------

    # 6. Unpack back into an RGB 3D array (Using the visual colors!)
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
    # ------------------------------
    
    # 7. Apply to a fresh Pygame Surface
    new_pol_surf = pygame.Surface(self.id_map.get_size(), depth=24)
    pygame.surfarray.blit_array(new_pol_surf, out_3d)
    
    self.political_map = new_pol_surf
    if self.map_mode == "POLITICAL":
        self.active_map = self.political_map
        
    print(f"Political map refreshed in {pygame.time.get_ticks() - timer} ms")

# (Keep your existing refresh_relations_map underneath this)

def refresh_relations_map(self):
    """Rebuilds the relations map surface instantly using a NumPy LUT."""
    timer = pygame.time.get_ticks()
    
    id_array = pygame.surfarray.pixels3d(self.id_map)
    id_2d = (id_array[:, :, 0].astype(np.uint32) << 16) | \
            (id_array[:, :, 1].astype(np.uint32) << 8) | \
             id_array[:, :, 2].astype(np.uint32)
             
    lut = np.zeros(16777216, dtype=np.uint32)
    
    water_mapping = {
        "ocean": "Ocean", "coastal_sea": "Ocean", 
        "inland_sea": "Ocean", "lakes": "Lakes"
    }
    
    player_data = self.nation_data.get(self.player_country, {})
    at_war = player_data.get("at_war_with", [])
    allies = player_data.get("allied_with", [])
    
    for color_key, data in self.map_data.items():
        terrain_type = data.get("terrain", "plains")
        
        if terrain_type in water_mapping:
            # Use water_mapping to get "Lakes" or "Ocean", then fetch from nation_colors
            water_owner = water_mapping[terrain_type]
            color = self.nation_colors.get(water_owner, (10, 20, 40))
        else:
            owner = data.get("owner", "Unclaimed")
            
            if owner in ["Unclaimed", "None", ""]:
                color = (255, 255, 255)
            elif owner == self.player_country:
                color = (0, 0, 255)
            elif owner in at_war:
                color = (255, 0, 0)
            elif owner in allies:
                color = (0, 255, 0)
            else:
                color = (255, 255, 255)
                
        packed_key = (color_key[0] << 16) | (color_key[1] << 8) | color_key[2]
        packed_color = (color[0] << 16) | (color[1] << 8) | color[2]
        lut[packed_key] = packed_color
        
    out_2d = lut[id_2d]
    
    out_3d = np.empty_like(id_array)
    out_3d[:, :, 0] = (out_2d >> 16) & 0xFF
    out_3d[:, :, 1] = (out_2d >> 8) & 0xFF
    out_3d[:, :, 2] = out_2d & 0xFF
    
    new_rel_surf = pygame.Surface(self.id_map.get_size(), depth=24)
    pygame.surfarray.blit_array(new_rel_surf, out_3d)
    
    self.relations_map = new_rel_surf
    
    if self.map_mode == "RELATIONS":
        self.active_map = self.relations_map
        
    print(f"Relations map refreshed in {pygame.time.get_ticks() - timer} ms")