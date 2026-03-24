import pygame

def refresh_political_map(self):
    """Rebuilds the entire political map surface from map_data."""
    timer = pygame.time.get_ticks()
    
    # Create a fresh canvas
    new_pol_surf = self.id_map.copy()
    px = pygame.PixelArray(new_pol_surf)
    
    # Define mapping for water terrain types to their 'pseudo-country' names
    # This matches the terrain types generated in your automatic_map_painter.py
    water_mapping = {
        "ocean": "ocean",
        "coastal_sea": "ocean",
        "inland_sea": "ocean",
        "lakes": "lakes"
    }
    
    for color_key, data in self.map_data.items():
        terrain_type = data.get("terrain", "plains")
        
        # 1. Determine the visual owner
        if terrain_type in water_mapping:
            if (terrain_type == "lakes"):
                print(terrain_type)
            # If it's water, assign it to the visual 'Ocean' or 'Lakes' nation
            owner = water_mapping[terrain_type]
            # Optional: sync the logic data so they aren't 'owned' by None
            data["owner"] = owner
        else:
            # Otherwise, use the standard nation owner
            owner = data.get("owner", "empty")
            
        # 2. Get the color from your nation_colors dictionary
        # Fallback to white if the nation name isn't found
        if not (owner == "ocean" or owner == "empty"):
            print(owner)
        if (owner == "Lakes" or owner == "lakes"):
            # idk why this isn't working im just gonna bandaid this
            color = (40, 80, 160)
        else:
            color = self.nation_colors.get(owner, (255, 255, 255))
        
        # 3. Replace the unique ID color with the Nation color
        px.replace(new_pol_surf.map_rgb(color_key), new_pol_surf.map_rgb(color))
    
    del px # Unlock surface
    self.political_map = new_pol_surf
    
    if self.map_mode == "POLITICAL":
        self.active_map = self.political_map
        
    print(f"Political map refreshed in {pygame.time.get_ticks() - timer} ms")