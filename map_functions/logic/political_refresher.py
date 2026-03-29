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
        "ocean": "Ocean",
        "coastal_sea": "Ocean",
        "inland_sea": "Ocean",
        "lakes": "Lakes"
    }
    
    for color_key, data in self.map_data.items():
        terrain_type = data.get("terrain", "plains")
        
        # 1. Determine the visual owner
        if terrain_type in water_mapping:
            if (terrain_type == "Lakes"):
                print(terrain_type)
            # If it's water, assign it to the visual 'Ocean' or 'Lakes' nation
            owner = water_mapping[terrain_type]
            # Optional: sync the logic data so they aren't 'owned' by None
            data["owner"] = owner
        else:
            # Otherwise, use the standard nation owner
            owner = data.get("owner", "Unclaimed")
            
        # 2. Get the color from your nation_colors dictionary
        # Fallback to white if the nation name isn't found
        if not (owner == "Ocean" or owner == "Unclaimed"):
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

def refresh_relations_map(self):
    """Rebuilds the relations map surface based on diplomacy."""
    timer = pygame.time.get_ticks()
    new_rel_surf = self.id_map.copy()
    px = pygame.PixelArray(new_rel_surf)
    
    water_mapping = {
        "ocean": "Ocean", "coastal_sea": "Ocean", "inland_sea": "Ocean", "lakes": "Lakes"
    }
    
    player_data = self.nation_data.get(self.player_country, {})
    at_war = player_data.get("at_war_with", [])
    allies = player_data.get("allied_with", [])
    
    for color_key, data in self.map_data.items():
        terrain_type = data.get("terrain", "plains")
        
        if terrain_type in water_mapping:
            color = (40, 80, 160) if terrain_type == "lakes" else (20, 40, 80)
        else:
            owner = data.get("owner", "Unclaimed")
            
            if owner == "Unclaimed" or owner == "None":
                color = (255, 255, 255)  # Neutral / Unclaimed (White)
            elif owner == self.player_country:
                color = (0, 0, 255)      # Self (Blue)
            elif owner in at_war:
                color = (255, 0, 0)      # Enemies (Red)
            elif owner in allies:
                color = (0, 255, 0)      # Allies (Green)
            else:
                color = (255, 255, 255)  # Other Neutrals (White)
        
        px.replace(new_rel_surf.map_rgb(color_key), new_rel_surf.map_rgb(color))
    
    del px
    self.relations_map = new_rel_surf
    
    if self.map_mode == "RELATIONS":
        self.active_map = self.relations_map
        
    print(f"Relations map refreshed in {pygame.time.get_ticks() - timer} ms")