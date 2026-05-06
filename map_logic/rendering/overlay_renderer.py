import pygame
import math
import data.constants as c
from data import queries
from map_logic.rendering import symbol_loader
from map_logic.rendering.font_manager import fonts

def draw_combat_bubbles(self_map, surface):
    """Draws combat indicators on the map to visualize predicted battles."""
    predictions = queries.get_combat_predictions(self_map.map_data, self_map.nation_data, self_map.id_to_province)
    cam = self_map.camera
    
    # 1. Compile a list of friendly nations to track involvement
    player_country = self_map.player_country
    friendly_nations = {player_country}
    
    player_allies = self_map.nation_data.get(player_country, {}).get("allied_with", [])
    friendly_nations.update(player_allies)
    
    player_faction = self_map.nation_data.get(player_country, {}).get("faction", "")
    if player_faction:
        friendly_nations.update(queries.get_faction_members(player_faction, self_map.nation_data))
    
    for pred in predictions:
        friendly_atk = 0
        enemy_atk = 0
        involved = False
        
        if pred["type"] == "meeting":
            side1 = pred["side1"]
            side2 = pred["side2"]
            atk1 = sum(u.get("attack", 5) for u in side1)
            atk2 = sum(u.get("attack", 5) for u in side2)
            
            s1_owner = side1[0]["owner"] if side1 else ""
            s2_owner = side2[0]["owner"] if side2 else ""
            
            if s1_owner in friendly_nations:
                friendly_atk, enemy_atk, involved = atk1, atk2, True
            elif s2_owner in friendly_nations:
                friendly_atk, enemy_atk, involved = atk2, atk1, True
                
            p1 = self_map.id_to_province[pred["loc"][0]]["center"]
            p2 = self_map.id_to_province[pred["loc"][1]]["center"]
            cx = (p1[0] + p2[0]) / 2
            cy = (p1[1] + p2[1]) / 2
            
        else:
            forces = pred["forces"]
            
            friendly_present = [o for o in forces.keys() if o in friendly_nations]
            if friendly_present:
                involved = True
                for owner, units in forces.items():
                    atk = sum(u.get("attack", 5) for u in units)
                    if owner in friendly_present:
                        friendly_atk += atk
                    else:
                        # Only add to enemy_atk if they are actively hostile to the friendly forces here
                        if any(queries.are_at_war(owner, f, self_map.nation_data) for f in friendly_present):
                            enemy_atk += atk
                            
            prov = self_map.id_to_province[pred["loc"]]
            cx, cy = prov["center"]
            
        # Determine Color Based on Simulation
        if not involved:
            color = (150, 150, 150) # Grey (Unrelated Battle / Spectating)
        elif friendly_atk > enemy_atk:
            color = (0, 255, 0) # Green (Winning)
        elif enemy_atk > friendly_atk:
            color = (255, 0, 0) # Red (Losing)
        else:
            color = (255, 255, 0) # Yellow (Draw)
            
        offsets = [0, -self_map.map_w, self_map.map_w] if self_map.loop_map else [0]
        for offset in offsets:
            sx = int((cx + offset - cam.pos.x) * cam.zoom)
            sy = int((cy - cam.pos.y) * cam.zoom) + self_map.top_ui_height
            
            if -50 < sx < surface.get_width() + 50 and 0 < sy < surface.get_height():
                radius = int(12 * cam.zoom) # Bubble size
                
                # Draw visual effect
                pygame.draw.circle(surface, color, (int(sx), int(sy)), radius, max(1, int(3 * cam.zoom)))
                # Draw semi-transparent inner fill
                inner = pygame.Surface((radius*2, radius*2), pygame.SRCALPHA)
                pygame.draw.circle(inner, color + (80,), (radius, radius), radius)
                surface.blit(inner, (int(sx) - radius, int(sy) - radius))

def draw_movement_path(surface, map_screen, start_province, path_ids, color=(255, 255, 0), alpha=255):
    """Draws a multi-segment path with lines underneath circles and a triangle at the end."""
    if not path_ids: return

    cam = map_screen.camera
    
    # 1. Convert to Screen Coordinates
    def world_to_screen(pos):
        sx = (pos[0] - cam.pos.x) * cam.zoom
        sy = (pos[1] - cam.pos.y) * cam.zoom + map_screen.top_ui_height
        return sx, sy

    # Build an ordered list of all nodes in the path
    nodes = [start_province]
    for step_id in path_ids:
        target_node = map_screen.id_to_province.get(step_id)
        if target_node:
            nodes.append(target_node)

    if len(nodes) < 2: return

    # Grab the UI symbols (Base scale is tweaked for zoom)
    line_base = symbol_loader.get_symbol("Line", cam.zoom * 1, color)
    circle_img = symbol_loader.get_symbol("Circle", cam.zoom * 1, color)
    triangle_img = symbol_loader.get_symbol("Triangle", cam.zoom * 1, color)

    # PASS 1: Draw all lines FIRST so they render underneath the shapes
    for i in range(len(nodes) - 1):
        p1 = nodes[i]["center"]
        p2 = nodes[i+1]["center"]
        start_pos = world_to_screen(p1)
        end_pos = world_to_screen(p2)

        dx = end_pos[0] - start_pos[0]
        dy = end_pos[1] - start_pos[1]
        dist = math.hypot(dx, dy)
        angle = math.degrees(math.atan2(-dy, dx))

        if line_base and int(dist) > 0:
            # Stretch the line image to fit the exact distance between the nodes
            thickness = max(2, int(4 * cam.zoom))
            scaled_line = pygame.transform.scale(line_base, (int(dist), thickness))
            rotated_line = pygame.transform.rotate(scaled_line, angle)
            
            # --- NEW: Alpha Transparency ---
            if alpha < 255:
                rotated_line.set_alpha(alpha)
                
            rect = rotated_line.get_rect(center=((start_pos[0] + end_pos[0])/2, (start_pos[1] + end_pos[1])/2))
            surface.blit(rotated_line, rect)
        else:
            # Fallback
            pygame.draw.line(surface, color, start_pos, end_pos, max(1, int(3 * cam.zoom)))

    # PASS 2: Draw the node markers on top of the lines
    for i in range(1, len(nodes)):
        p1 = nodes[i-1]["center"]
        p2 = nodes[i]["center"]
        start_pos = world_to_screen(p1)
        end_pos = world_to_screen(p2)

        is_last = (i == len(nodes) - 1)

        dx = end_pos[0] - start_pos[0]
        dy = end_pos[1] - start_pos[1]
        angle = math.degrees(math.atan2(-dy, dx))

        if is_last:
            if triangle_img:
                # Rotate the triangle so it points along the trajectory of the line
                rotated_tri = pygame.transform.rotate(triangle_img, angle)
                
                # --- NEW: Alpha Transparency ---
                if alpha < 255:
                    rotated_tri.set_alpha(alpha)
                    
                rect = rotated_tri.get_rect(center=end_pos)
                surface.blit(rotated_tri, rect)
            else:
                # Fallback Triangle
                head_size = 15 * cam.zoom
                angle_rad = math.atan2(dy, dx)
                left_wing = (end_pos[0] - head_size * math.cos(angle_rad - math.pi / 6),
                             end_pos[1] - head_size * math.sin(angle_rad - math.pi / 6))
                right_wing = (end_pos[0] - head_size * math.cos(angle_rad + math.pi / 6),
                               end_pos[1] - head_size * math.sin(angle_rad + math.pi / 6))
                pygame.draw.polygon(surface, color, [end_pos, left_wing, right_wing])
        else:
            if circle_img:
                # --- NEW: Alpha Transparency (Requires copying to not corrupt the cache) ---
                draw_circle = circle_img.copy() if alpha < 255 else circle_img
                if alpha < 255:
                    draw_circle.set_alpha(alpha)
                    
                # Plop the circle right on the intermediate coordinate
                rect = draw_circle.get_rect(center=end_pos)
                surface.blit(draw_circle, rect)
            else:
                # Fallback Circle
                pygame.draw.circle(surface, color, (int(end_pos[0]), int(end_pos[1])), max(3, int(4 * cam.zoom)))

def draw_overlay_content(self, surface):
    """Orchestrates what icons/symbols to draw over the map."""
    if self.secondary_mode == "BLANK":
        return

    # --- Render Combat Prediction Bubbles ---
    if self.secondary_mode == "UNITS" or self.map_mode == "POLITICAL":
        draw_combat_bubbles(self, surface)
    # ---------------------------------------------

    for color_key, province in self.map_data.items():
        cx, cy = province["center"]
        
        # Wrapping logic for screen coordinates
        offsets = [0, -self.map_w, self.map_w] if self.loop_map else [0]
        
        for offset in offsets:
            sx = int((cx + offset - self.camera.pos.x) * self.camera.zoom)
            sy = int((cy - self.camera.pos.y) * self.camera.zoom) + self.top_ui_height
            
            # Culling: only draw if within screen width
            if -50 < sx < surface.get_width() + 50:
                
                # --- UNIT VIEW ---
                if self.secondary_mode == "UNITS":
                    if province["units"]:
                        draw_unit_icon(self, surface, sx, sy, province)
                        
                    if queries.is_training_troops(province):
                        training_sym = symbol_loader.get_symbol(c.ICON_TRAINING, self.camera.zoom * c.OVERLAY_STATUS_ICON_SCALE)
                        if training_sym:
                            training_sym.set_alpha(c.OVERLAY_STATUS_ICON_ALPHA)
                            rect = training_sym.get_rect(center=(sx, sy))
                            surface.blit(training_sym, rect)

                    # --- Disband Indicator ---
                    if any(u.get("order", {}).get("type") == "DISBAND" for u in province.get("units", [])):
                        disband_sym = symbol_loader.get_symbol(c.ICON_DISBANDING, self.camera.zoom * c.OVERLAY_STATUS_ICON_SCALE)
                        if disband_sym:
                            disband_sym.set_alpha(c.OVERLAY_STATUS_ICON_ALPHA)
                            # Shifted slightly right to avoid overlapping completely with training
                            rect = disband_sym.get_rect(center=(sx, sy))
                            surface.blit(disband_sym, rect)

                # --- ECONOMY VIEW ---
                elif self.secondary_mode == "ECONOMY":
                    # Draw standard resources first (your existing logic)
                    # hahaha NO don't do that we have a dedicated tab for that now
                    """if province.get("resources"):
                        pygame.draw.rect(surface, (255, 215, 0), (sx-15, sy-15, 10, 10))"""
                    # ne touche pas cette chose!
                    # passe, sil te plait
                    
                    # Draw Buildings
                    buildings = province.get("buildings", [])
                    for i, b_name in enumerate(buildings):
                        # Offset building icons so they don't stack perfectly
                        offset_x = (i % 2) * 20
                        offset_y = (i // 2) * 20
                        
                        # Try to load a symbol (e.g., "workshop_icon") or use a colored square
                        # sym_name = b_name.lower().replace(" ", "_")
                        sym_name = b_name
                        symbol = symbol_loader.get_symbol(sym_name, self.camera.zoom * 0.8)
                        
                        if symbol:
                            surface.blit(symbol, (sx + offset_x, sy + offset_y))
                        else:
                            # Fallback colored squares for different types
                            color = (150, 150, 150) # Grey for workshop
                            if "Factory" in b_name: color = (100, 100, 200) # Blue-ish for factory
                            if "Refinery" in b_name: color = (200, 100, 100) # Red-ish for refinery
                            
                            rect = pygame.Rect(sx + offset_x, sy + offset_y, 12 * self.camera.zoom, 12 * self.camera.zoom)
                            pygame.draw.rect(surface, color, rect)
                            pygame.draw.rect(surface, (255, 255, 255), rect, 1) # Border
                    
                    # Draw Construction Hammer
                    if queries.is_constructing_building(province):
                        hammer_sym = symbol_loader.get_symbol(c.ICON_CONSTRUCTION, self.camera.zoom * c.OVERLAY_STATUS_ICON_SCALE)
                        if hammer_sym:
                            hammer_sym.set_alpha(c.OVERLAY_STATUS_ICON_ALPHA)
                            rect = hammer_sym.get_rect(center=(sx, sy))
                            surface.blit(hammer_sym, rect)
                
                # --- RESOURCES VIEW ---
                elif self.secondary_mode == "RESOURCES":
                    resources = province.get("resources", {})
                    if isinstance(resources, dict) and resources:
                        offset_x = 0
                        for res_type, amount in resources.items():
                            if amount > 0:
                                # Fetch icon, your symbol_loader automatically drops '.png' so it expects "Iron", "Coal", "Oil"
                                sym = symbol_loader.get_symbol(res_type, self.camera.zoom * 0.8)
                                if sym:
                                    surface.blit(sym, (sx + offset_x, sy))
                                else:
                                    # Fallback colored square
                                    c_col = (200, 200, 200)
                                    if res_type == "Iron": c_col = (180, 180, 180)
                                    if res_type == "Coal": c_col = (50, 50, 50)
                                    if res_type == "Oil": c_col = (30, 30, 30)
                                    pygame.draw.rect(surface, c_col, (sx + offset_x, sy, int(15 * self.camera.zoom), int(15 * self.camera.zoom)))
                                
                                # Shift right so multiple icons stack side-by-side
                                offset_x += 20 * self.camera.zoom


def draw_unit_icon(self, surface, sx, sy, province):
    units = province.get("units", [])
    if not units:
        return

    # 1. Group units by owner so we can draw stacked boxes for each nation
    units_by_owner = {}
    for u in units:
        owner = u.get("owner", "Unclaimed")
        units_by_owner.setdefault(owner, []).append(u)

    # Base high-res rendering dimensions
    internal_w = getattr(c, 'UNIT_BOX_WIDTH', 120)
    internal_h = getattr(c, 'UNIT_BOX_HEIGHT', 48)
    
    # Dampened Scaling rules
    display_scale = 0.25 + (self.camera.zoom * 0.12)
    scaled_w = max(20, int(internal_w * display_scale))
    scaled_h = max(8, int(internal_h * display_scale))
    gap = max(2, int(4 * display_scale)) # Spacing between stacked boxes

    # 2. Calculate the vertical offset to perfectly center the entire stack over the province
    total_boxes = len(units_by_owner)
    total_stack_height = (scaled_h * total_boxes) + (gap * (total_boxes - 1))
    
    # Start drawing from the top of the stack and move down
    current_sy = sy - (total_stack_height // 2) + (scaled_h // 2)

    # --- NEW: Sort owners by Total HP descending ---
    sorted_owners = sorted(
        units_by_owner.keys(), 
        key=lambda o: (-sum(u.get("health", 0) for u in units_by_owner[o]), o)
    )

    for owner in sorted_owners:
        owner_units = units_by_owner[owner]
        best_unit = queries.get_best_unit_by_defense_then_attack(owner_units)
        
        if not best_unit:
            continue

        unit_count = len(owner_units)
        unit_type = best_unit.get("type", "")
        owner_color = self.nation_colors.get(owner, (200, 200, 200))
        
        # Check if it's a dynamic convoy or truck
        if unit_type.startswith("Convoy"):
            symbol_name = "Convoy"
        elif unit_type.startswith("Truck"):
            symbol_name = "Truck"
        else:
            symbol_name = unit_type
            
        # Create unscaled, high-res subsurface to preserve crispness
        box_surf = pygame.Surface((internal_w, internal_h), pygame.SRCALPHA)
        box_surf.fill(getattr(c, 'UNIT_BOX_BG_COLOR', (40, 40, 40, 200)))
        pygame.draw.rect(box_surf, owner_color, box_surf.get_rect(), 4)
        
        # Grab symbol
        symbol = symbol_loader.get_symbol(symbol_name, 2.5, color=owner_color)
        text_x = 10
        if symbol:
            # Constrain the symbol itself if it's too wide
            max_sym_w = int(internal_w * 0.6) # Limit symbol to 60% of box width
            if symbol.get_width() > max_sym_w:
                ratio = max_sym_w / symbol.get_width()
                new_h = max(1, int(symbol.get_height() * ratio))
                symbol = pygame.transform.smoothscale(symbol, (max_sym_w, new_h))
            # -------------------------------------------------------------
                
            sym_rect = symbol.get_rect(midleft=(8, internal_h // 2))
            box_surf.blit(symbol, sym_rect)
            text_x = sym_rect.right + 8
            
        # Draw Unit Count Text
        font = fonts.get("button")
        count_str = str(unit_count)
        count_txt = font.render(count_str, True, getattr(c, 'UNIT_BOX_TEXT_COLOR', (255, 255, 255)))
        shadow_txt = font.render(count_str, True, (0, 0, 0))

        # --- TEXT COMPRESSION FIX (UNIFORM SCALE) ---
        # Ensure we never pass a 0 or negative width to smoothscale
        max_text_w = max(1, internal_w - text_x - 6) 
        
        # If the text is wider than the space we have, scale it down uniformly to fit
        if count_txt.get_width() > max_text_w:
            scale_ratio = max_text_w / count_txt.get_width()
            new_w = int(max_text_w)
            new_h = max(1, int(count_txt.get_height() * scale_ratio))
            count_txt = pygame.transform.smoothscale(count_txt, (new_w, new_h))
            shadow_txt = pygame.transform.smoothscale(shadow_txt, (new_w, new_h))
        
        txt_y = (internal_h // 2) - (count_txt.get_height() // 2)
        box_surf.blit(shadow_txt, (text_x + 2, txt_y + 2))
        box_surf.blit(count_txt, (text_x, txt_y))
        
        # Supersampling/Anti-aliasing final stretch down
        final_surf = pygame.transform.smoothscale(box_surf, (scaled_w, scaled_h))
        
        # Blit using the stacked Y coordinate
        rect = final_surf.get_rect(center=(sx, int(current_sy)))
        surface.blit(final_surf, rect)

        # Move the offset down for the next owner's box in the stack
        current_sy += scaled_h + gap