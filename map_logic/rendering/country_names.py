import pygame
import math
import data.constants as c
from map_logic.rendering.font_manager import fonts

def clear_country_name_cache(map_screen):
    """Clears cached name surfaces so they are re-rendered on the next update."""
    if hasattr(map_screen, 'country_name_surfs'):
        delattr(map_screen, 'country_name_surfs')
    if hasattr(map_screen, 'faction_name_surfs'):
        delattr(map_screen, 'faction_name_surfs')

def draw_country_names(map_screen, surface):
    # --- LAYER 3.5: COUNTRY NAMES ---
    # Only show names on the Political map to avoid cluttering other modes
    if getattr(map_screen, 'show_country_names', True): 
        
        # 1. Cache text surfaces once to save performance
        if not hasattr(map_screen, 'country_name_surfs'):
            map_screen.country_name_surfs = {}
            map_screen.faction_name_surfs = {} # Cache faction text globally
            
            # Use your biggest font preset for maximum resolution before scaling down
            name_font = fonts.get("country_name_display") 
            for c_id, data in map_screen.nation_data.items():
                if c_id not in c.UNPLAYABLE_NATIONS:
                    # Cache normal country name
                    disp = data.get("name", c_id).upper()
                    surf = name_font.render(disp, True, (255, 255, 255)).convert_alpha()
                    shadow = name_font.render(disp, True, (20, 20, 20)).convert_alpha()
                    map_screen.country_name_surfs[c_id] = (surf, shadow)

                    # Cache faction name
                    fac = data.get("faction", "").upper()
                    if fac:
                        f_surf = name_font.render(fac, True, (255, 255, 255)).convert_alpha()
                        f_shadow = name_font.render(fac, True, (20, 20, 20)).convert_alpha()
                        map_screen.faction_name_surfs[c_id] = (f_surf, f_shadow)

        # 2 & 3. Draw the names with DYNAMIC alpha
        if hasattr(map_screen, 'country_text_blobs'):
            import math
            
            drawn_countries = set()
            drawn_factions = set() # Keep track of which factions have already been drawn!
            
            # Pick which blobs to use based on map mode
            if map_screen.base_layer == "CORES" and hasattr(map_screen, 'core_text_blobs'):
                active_blobs = map_screen.core_text_blobs
            else:
                active_blobs = map_screen.country_text_blobs
            
            # Sort largest spatial spread to smallest so mainlands are always processed first!
            sorted_blobs = sorted(active_blobs, key=lambda b: b["spread"], reverse=True)
            
            for blob in sorted_blobs:
                country = blob["owner"]
                
                # Check which mode we are in to swap the lookup table
                if map_screen.base_layer == "FACTIONS":
                    # If we are in Faction mode, skip countries without factions
                    fac_name = map_screen.nation_data.get(country, {}).get("faction", "").upper()
                    if not fac_name:
                        continue
                        
                    # Skip small island groups based on the toggle and if the country already has a name
                    # This allows the faction name to appear on EVERY country in the faction, 
                    # rather than just once for the whole faction!
                    if blob["count"] <= 3:
                        if country in drawn_countries:
                            continue
                        if blob["count"] < 2 and not c.SHOW_SMALL_TERRITORY_NAMES:
                            continue
                        
                    surf, shadow = map_screen.faction_name_surfs.get(country, (None, None))
                else:
                    # Skip small island groups based on the toggle and if the country already has a name
                    if blob["count"] <= 3:
                        if country in drawn_countries:
                            continue
                        if blob["count"] < 2 and not c.SHOW_SMALL_TERRITORY_NAMES:
                            continue
                    
                    surf, shadow = map_screen.country_name_surfs.get(country, (None, None))
                    
                if not surf: continue

                cx, cy = blob["cx"], blob["cy"]
                
                # Wrap logic for looped maps
                offsets = [0, -map_screen.map_w, map_screen.map_w] if map_screen.loop_map else [0]
                for offset in offsets:
                    sx = (cx + offset - map_screen.camera.pos.x) * map_screen.camera.zoom
                    sy = (cy - map_screen.camera.pos.y) * map_screen.camera.zoom * getattr(map_screen.camera, 'tilt_factor', 1.0) + map_screen.top_ui_height

                    # Frustum Culling: Only draw if it's actually on the screen
                    if -200 < sx < surface.get_width() + 200 and 0 < sy < surface.get_height():
                        
                        # --- THE NEW SCALING LOGIC ---
                        scale_by_length = blob["length"] / surf.get_width()
                        scale_by_thickness = (blob["thickness"] * 0.8) / surf.get_height()
                        
                        land_scale = min(scale_by_length, scale_by_thickness)
                        land_scale = min(max(land_scale, 0.05), 1.0)
                        
                        # --- UNIVERSAL LINEAR FADE LOGIC ---
                        fade_start = c.NAME_FADE_START 
                        fade_window = c.NAME_FADE_WINDOW  
                        
                        if map_screen.camera.zoom > fade_start:
                            alpha_ratio = 1.0 - min(1.0, (map_screen.camera.zoom - fade_start) / fade_window)
                        else:
                            alpha_ratio = 1.0
                            
                        alpha = int(255 * alpha_ratio)

                        if alpha <= 0:
                            continue 
                        
                        scaled_w = int(surf.get_width() * map_screen.camera.zoom * land_scale)
                        scaled_h = int(surf.get_height() * map_screen.camera.zoom * land_scale)
                        
                        if scaled_w > 0 and scaled_h > 0:
                            # 1. Apply Uniform Scaling First
                            scaled_text = pygame.transform.scale(surf, (scaled_w, scaled_h))
                            scaled_shadow = pygame.transform.scale(shadow, (scaled_w, scaled_h))
                            
                            # 2. Rotate the Text
                            angle = blob.get("angle", 0)
                            if abs(angle) > 2: 
                                scaled_text = pygame.transform.rotate(scaled_text, angle)
                                scaled_shadow = pygame.transform.rotate(scaled_shadow, angle)

                            # 3. Apply Tilt Compression to Text AFTER Rotation
                            if getattr(map_screen.camera, 'tilt_factor', 1.0) < 0.99 and getattr(c, 'APPLY_TILT_TO_TEXT', True):
                                final_w = scaled_text.get_width()
                                final_h = max(1, int(scaled_text.get_height() * map_screen.camera.tilt_factor))
                                scaled_text = pygame.transform.scale(scaled_text, (final_w, final_h))
                                scaled_shadow = pygame.transform.scale(scaled_shadow, (final_w, final_h))
                            
                            scaled_text.set_alpha(alpha)
                            scaled_shadow.set_alpha(alpha)
                            
                            # Center the rotated rect exactly on the calculated coordinates
                            txt_rect = scaled_text.get_rect(center=(int(sx), int(sy)))
                            
                            surface.blit(scaled_shadow, (txt_rect.x + 2, txt_rect.y + 2))
                            surface.blit(scaled_text, txt_rect)
                            
                            # Record that this text block has successfully been drawn
                            drawn_countries.add(country)
                            if map_screen.base_layer == "FACTIONS":
                                fac_name = map_screen.nation_data.get(country, {}).get("faction", "").upper()
                                drawn_factions.add(fac_name)

def update_country_centers(map_screen):
    # Calculates the visual center, rotation, and physical spread for every country landmass.
    
    timer = pygame.time.get_ticks()

    # Clear name surface caches to force reconstruction with updated faction info
    if hasattr(map_screen, 'country_name_surfs'):
        delattr(map_screen, 'country_name_surfs')
    if hasattr(map_screen, 'faction_name_surfs'):
        delattr(map_screen, 'faction_name_surfs')

    def get_blobs(grouping_key_func):
        blobs = []
        visited = set()
        
        # Iterate through every province by ID
        for prov_id, prov in map_screen.id_to_province.items():
            group_val = grouping_key_func(prov)
            if not group_val or group_val in c.UNPLAYABLE_NATIONS:
                continue
            
            # If we haven't checked this province yet, it's a new landmass
            if prov_id not in visited:
                comp = []
                queue = [prov]
                visited.add(prov_id)
                
                # Flood-fill to find all connected provinces with the SAME grouping key
                while queue:
                    curr = queue.pop(0)
                    comp.append(curr)
                    for n_id in curr.get("neighbors", []):
                        if n_id not in visited:
                            n_prov = map_screen.id_to_province.get(n_id)
                            if n_prov and grouping_key_func(n_prov) == group_val:
                                visited.add(n_id)
                                queue.append(n_prov)
                
                count = len(comp)
                if count == 0: continue
                
                # 1. Average center (Mean)
                avg_x = sum(ch["center"][0] for ch in comp) / count
                avg_y = sum(ch["center"][1] for ch in comp) / count
                
                # 2. Covariance Matrix calculations (for rotation and scale)
                c_xx = sum((ch["center"][0] - avg_x)**2 for ch in comp) / count
                c_yy = sum((ch["center"][1] - avg_y)**2 for ch in comp) / count
                c_xy = sum((ch["center"][0] - avg_x) * (ch["center"][1] - avg_y) for ch in comp) / count
                
                # Calculate angle (math.atan2 handles division by zero safely)
                # atan2 returns radians, we need degrees. Pygame rotates counter-clockwise.
                angle_rad = 0.5 * math.atan2(2 * c_xy, c_xx - c_yy)
                display_angle = -math.degrees(angle_rad) 
                
                # 3. Calculate Principal Axes (Length and Thickness) via Eigenvalues
                W = (c_xx + c_yy) / 2.0
                D = math.sqrt(((c_xx - c_yy) / 2.0)**2 + c_xy**2)
                
                major_variance = W + D
                minor_variance = max(W - D, 1.0)
                
                # Convert variance to spatial distance. 
                # 3.0 is a tuning constant (adjust if all text is globally too big/small)
                country_length = math.sqrt(major_variance) * 3.0
                country_thickness = math.sqrt(minor_variance) * 3.0
                
                # Snap to the closest actual province in this component
                closest_prov = min(comp, key=lambda ch: (ch["center"][0] - avg_x)**2 + (ch["center"][1] - avg_y)**2)
                
                blobs.append({
                    "owner": group_val, # Reusing "owner" key so the renderer accepts it generically
                    "cx": closest_prov["center"][0],
                    "cy": closest_prov["center"][1],
                    "length": country_length,
                    "thickness": country_thickness,
                    "spread": math.sqrt(c_xx + c_yy),
                    "count": count, 
                    "angle": display_angle
                })
        return blobs

    # Generate separate blobs for political owners and primary cores
    map_screen.country_text_blobs = get_blobs(lambda p: p.get("owner"))
    map_screen.core_text_blobs = get_blobs(lambda p: p.get("cores")[0] if p.get("cores") else None)

    print(f"Country centers / names refreshed in {pygame.time.get_ticks() - timer} ms")