import pygame
import random
from data.constants import VISUAL_WATER_MAPPING

def generate_new_world(map_screen):
    """Generates the geometric map surfaces and data structures from scratch."""
    
    # 1. Define dimensions for the random world
    width, height = 6000, 2000
    num_provinces = 300
    
    # 2. Create blank surfaces
    terrain_surf = pygame.Surface((width, height))
    id_surf = pygame.Surface((width, height))
    
    # Fill with ocean initially
    terrain_surf.fill((0, 0, 255)) # Ocean blue
    id_surf.fill((0, 0, 0)) # Blank ID
    
    map_screen.map_data = {}
    map_screen.id_to_province = {}
    
    # ------------------------------------------------------------------
    # TODO: THE HARD PART - PROCEDURAL GENERATION ALGORITHM
    # 
    # Option A: Draw a grid of squares (Easiest to program, but looks rigid)
    # Option B: Scatter random points, and use a Voronoi library (like scipy.spatial.Voronoi) 
    #           to draw polygons for provinces.
    # Option C: Cellular Automata (Simulate tectonic plates growing)
    # 
    # Once you draw the province shapes onto id_surf using unique RGB colors,
    # you must calculate their neighbors and centers.
    # ------------------------------------------------------------------
    
    # --- EXAMPLE SKELETON (Using a fake grid approach for testing) ---
    prov_id = 1
    cols, rows = 45, 15
    cell_w, cell_h = width // cols, height // rows
    
    for row in range(rows):
        for col in range(cols):
            # 1. Assign a unique RGB ID
            r = (prov_id & 0x0000FF)
            g = (prov_id & 0x00FF00) >> 8
            b = (prov_id & 0xFF0000) >> 16
            color_id = (r, g, b)
            
            # 2. Draw the province to the ID map
            rect = pygame.Rect(col * cell_w, row * cell_h, cell_w, cell_h)
            pygame.draw.rect(id_surf, color_id, rect)
            
            # 3. Determine Terrain (Make edges ocean, middle land)
            if row == 0 or row == rows - 1 or col == 0 or col == cols - 1:
                terrain = "ocean"
                pygame.draw.rect(terrain_surf, (0, 0, 255), rect)
            else:
                terrain = random.choice(["plains", "forest", "hills", "desert"])
                pygame.draw.rect(terrain_surf, (144, 238, 144), rect) # Paint it all plains-green for now
                
            # 4. Find Neighbors (Grid math is easy)
            neighbors = []
            if row > 0: neighbors.append(prov_id - cols)
            if row < rows - 1: neighbors.append(prov_id + cols)
            if col > 0: neighbors.append(prov_id - 1)
            if col < cols - 1: neighbors.append(prov_id + 1)
            
            # 5. Populate Data Dictionary
            prov_data = {
                "id": prov_id,
                "terrain": terrain,
                "is_coastal": False, # Would need actual logic to check if neighbor is ocean
                "center": (rect.centerx, rect.centery),
                "neighbors": neighbors,
                "owner": "Ocean" if terrain == "ocean" else "Unclaimed",
                "units": [],
                "deployment_queue": [],
                "orders": [],
                "buildings": [],
                "resources": {},
                "cores": [],
                "json_key": f"({r}, {g}, {b})",
                "map_color": color_id
            }
            
            map_screen.map_data[color_id] = prov_data
            map_screen.id_to_province[prov_id] = prov_data
            
            prov_id += 1

    # --- FINAL HANDOFF ---
    # Assign the generated surfaces to the Map class just like load_map.py does
    map_screen.terrain_map = terrain_surf
    map_screen.id_map = id_surf
    map_screen.political_map = id_surf.copy()
    map_screen.cores_map = id_surf.copy()
    map_screen.raw_json_data = map_screen.map_data # Mocking the raw JSON load