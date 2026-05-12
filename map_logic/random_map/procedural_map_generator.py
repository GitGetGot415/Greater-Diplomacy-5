import pygame
import random
import numpy as np
import data.constants as c

def generate_new_world(map_screen):
    """Generates the geometric map surfaces and data structures from scratch."""
    
    # 1. Gather variables from settings or constants
    width = getattr(c, 'PROCEDURAL_MAP_WIDTH', 600)
    height = getattr(c, 'PROCEDURAL_MAP_HEIGHT', 200)
    num_provinces = getattr(c, 'PROCEDURAL_PROVINCE_COUNT', 300)
    
    proc_type = getattr(map_screen, 'random_settings', {}).get("procedural_type", "Grid")

    # 2. Route to the requested algorithm
    if proc_type == "Voronoi":
        _generate_voronoi(map_screen, width, height, num_provinces)
    elif proc_type == "Cellular Automata":
        _generate_tectonic(map_screen, width, height, num_provinces)
    else:
        _generate_grid(map_screen, width, height, num_provinces)

def _generate_grid(map_screen, width, height, num_provinces):
    """Option A: Evenly spaced grid distribution"""
    rows = max(1, int(np.sqrt(num_provinces * height / width)))
    cols = max(1, num_provinces // rows)
    actual_num = rows * cols
    
    grid = np.zeros((height, width), dtype=np.int32)
    cell_w = width / cols
    cell_h = height / rows
    
    for r in range(rows):
        for c_idx in range(cols):
            idx = r * cols + c_idx + 1
            y_start, y_end = int(r * cell_h), int((r + 1) * cell_h)
            x_start, x_end = int(c_idx * cell_w), int((c_idx + 1) * cell_w)
            grid[y_start:y_end, x_start:x_end] = idx
            
    _process_grid_to_map(map_screen, grid, width, height, actual_num)

def _generate_voronoi(map_screen, width, height, num_provinces):
    """Option B: Pure NumPy Voronoi mapping via point distancing"""
    seeds_y = np.random.randint(0, height, num_provinces)
    seeds_x = np.random.randint(0, width, num_provinces)
    
    Y, X = np.mgrid[0:height, 0:width]
    grid = np.zeros((height, width), dtype=np.int32)
    min_dist = np.full((height, width), np.inf)
    
    for i in range(num_provinces):
        dist = (Y - seeds_y[i])**2 + (X - seeds_x[i])**2
        mask = dist < min_dist
        min_dist[mask] = dist[mask]
        grid[mask] = i + 1
        
    _process_grid_to_map(map_screen, grid, width, height, num_provinces)

def _generate_tectonic(map_screen, width, height, num_provinces):
    """Option C: Tectonic plates using cellular automata (organic iterative dilation)"""
    grid = np.zeros((height, width), dtype=np.int32)
    seeds_y = np.random.randint(0, height, num_provinces)
    seeds_x = np.random.randint(0, width, num_provinces)
    
    for i in range(num_provinces):
        grid[seeds_y[i], seeds_x[i]] = i + 1
        
    empty_mask = grid == 0
    while np.any(empty_mask):
        shifts = [(0, 1), (0, -1), (1, 0), (-1, 0)]
        random.shuffle(shifts)
        
        for dy, dx in shifts:
            shifted = np.roll(grid, shift=(dy, dx), axis=(0, 1))
            fill_mask = (grid == 0) & (shifted != 0)
            
            # Apply organic boundary noise 30% of the time to avoid rigid expansion squares
            random_mask = np.random.rand(height, width) > 0.3
            apply_mask = fill_mask & random_mask
            grid[apply_mask] = shifted[apply_mask]
            
        empty_mask = grid == 0
        
    _process_grid_to_map(map_screen, grid, width, height, num_provinces)

def _process_grid_to_map(map_screen, grid, width, height, num_provinces):
    """Takes a generated ID map and securely converts it to Pygame surfarrays & game dictionaries."""
    colors = {}
    centers = {}
    terrains = {}
    ocean_ids = set()
    
    # 1. Roll to detect boundary edges and capture neighbor data quickly
    shift_u = np.roll(grid, 1, axis=0)
    shift_d = np.roll(grid, -1, axis=0)
    shift_l = np.roll(grid, 1, axis=1)
    shift_r = np.roll(grid, -1, axis=1)
    
    neighbor_pairs = set()
    for shifted in [shift_u, shift_d, shift_l, shift_r]:
        mask = grid != shifted
        pairs = np.unique(np.c_[grid[mask], shifted[mask]], axis=0)
        for p1, p2 in pairs:
            if p1 != 0 and p2 != 0 and p1 != p2:
                neighbor_pairs.add((p1, p2))
                neighbor_pairs.add((p2, p1))
                
    # --- 1-PIXEL TILE GAPS ---
    # Compare current pixel to right and bottom neighbors. 
    # If they belong to a different province, erase the current pixel (turn it into a 0).
    border_mask = (grid != shift_r) | (grid != shift_d)
    grid[border_mask] = 0
                
    # 2. Extract base province properties
    for i in range(1, num_provinces + 1):
        # Prevent completely black colors matching Ocean
        r = max(1, (i & 0x0000FF))
        g = (i & 0x00FF00) >> 8
        b = (i & 0xFF0000) >> 16
        colors[i] = (r, g, b)
        
        ys, xs = np.where(grid == i)
        if len(ys) > 0:
            centers[i] = (int(np.mean(xs)), int(np.mean(ys)))
            if np.any(xs == 0) or np.any(xs == width - 1) or np.any(ys == 0) or np.any(ys == height - 1):
                terrains[i] = "ocean"
                ocean_ids.add(i)
            else:
                terrains[i] = random.choice(["plains", "forest", "hills", "desert"])
        else:
            centers[i] = (0, 0)
            terrains[i] = "ocean"
            ocean_ids.add(i)
            
    # 3. Apply to engine map_data structure
    map_screen.map_data = {}
    map_screen.id_to_province = {}
    
    for i in range(1, num_provinces + 1):
        color_id = colors[i]
        prov_neighbors = [int(n2) for n1, n2 in neighbor_pairs if n1 == i]
        
        prov_data = {
            "id": int(i),
            "terrain": terrains[i],
            "is_coastal": False,
            "center": centers[i],
            "neighbors": prov_neighbors,
            "owner": "Ocean" if terrains[i] == "ocean" else "Unclaimed",
            "units": [],
            "deployment_queue": [],
            "orders": [],
            "buildings": [],
            "resources": {},
            "cores": [],
            "json_key": f"({color_id[0]}, {color_id[1]}, {color_id[2]})",
            "map_color": color_id
        }
        map_screen.map_data[color_id] = prov_data
        map_screen.id_to_province[int(i)] = prov_data
        
    for p_data in map_screen.map_data.values():
        if p_data["terrain"] != "ocean":
            if any(n_id in ocean_ids for n_id in p_data["neighbors"]):
                p_data["is_coastal"] = True
                
    # 4. Burn data into pure arrays for instantaneous visual Pygame surface construction
    id_lut = np.zeros((num_provinces + 1, 3), dtype=np.uint8)
    terrain_lut = np.zeros((num_provinces + 1, 3), dtype=np.uint8)
    
    # --- THE FIX: DYNAMIC TERRAIN COLORS ---
    terrain_colors = {
        "ocean": (40, 100, 180),   # Deep Blue
        "plains": (144, 238, 144), # Light Green
        "forest": (34, 139, 34),   # Dark Green
        "hills": (160, 140, 120),  # Grey-Brown
        "desert": (238, 214, 175)  # Sand
    }
    
    for i in range(1, num_provinces + 1):
        id_lut[i] = colors[i]
        terrain_lut[i] = terrain_colors.get(terrains[i], (144, 238, 144))
    # ---------------------------------------
        
    grid_w_h = grid.T
    id_surf_array = id_lut[grid_w_h]
    terrain_surf_array = terrain_lut[grid_w_h]
    
    id_surf = pygame.surfarray.make_surface(id_surf_array)
    terrain_surf = pygame.surfarray.make_surface(terrain_surf_array)
    
    # 5. Connect cleanly to the game pipeline
    map_screen.terrain_map = terrain_surf
    map_screen.id_map = id_surf
    map_screen.political_map = id_surf.copy()
    map_screen.cores_map = id_surf.copy()
    map_screen.raw_json_data = map_screen.map_data