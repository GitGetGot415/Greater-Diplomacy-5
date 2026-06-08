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
        # --- FOG OF WAR COMBAT VISIBILITY CHECK ---
        if getattr(self_map, 'visible_provinces', None) is not None:
            if pred["type"] == "meeting":
                if pred["loc"][0] not in self_map.visible_provinces and pred["loc"][1] not in self_map.visible_provinces:
                    continue
            else:
                if pred["loc"] not in self_map.visible_provinces:
                    continue
    
        friendly_atk = 0
        enemy_atk = 0
        involved = False
        
        if pred["type"] == "meeting":
            side1 = pred["side1"]
            side2 = pred["side2"]
            
            # Incorporate combat scaling rules here too
            atk1 = sum(u.get("attack", 5) for u in sorted(side1, key=lambda x: x.get("attack", 5), reverse=True)[:c.MAX_COMBAT_ATTACKERS])
            atk2 = sum(u.get("attack", 5) for u in sorted(side2, key=lambda x: x.get("attack", 5), reverse=True)[:c.MAX_COMBAT_ATTACKERS])
            
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
                    # Incorporate combat scaling rules
                    atk = sum(u.get("attack", 5) for u in sorted(units, key=lambda x: x.get("attack", 5), reverse=True)[:c.MAX_COMBAT_ATTACKERS])
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
            sy = int((cy - cam.pos.y) * cam.zoom * getattr(cam, 'tilt_factor', 1.0)) + self_map.top_ui_height
            
            if -50 < sx < surface.get_width() + 50 and 0 < sy < surface.get_height():
                radius_x = int(12 * cam.zoom) # Bubble size
                radius_y = int(radius_x * getattr(cam, 'tilt_factor', 1.0)) if getattr(c, 'APPLY_TILT_TO_OVERLAYS', False) else radius_x
                
                # Draw visual effect
                if getattr(cam, 'tilt_factor', 1.0) < 0.99 and getattr(c, 'APPLY_TILT_TO_OVERLAYS', False):
                    rect = pygame.Rect(int(sx) - radius_x, int(sy) - radius_y, radius_x * 2, radius_y * 2)
                    pygame.draw.ellipse(surface, color, rect, max(1, int(3 * cam.zoom)))
                else:
                    pygame.draw.circle(surface, color, (int(sx), int(sy)), radius_x, max(1, int(3 * cam.zoom)))
                
                # Draw semi-transparent inner fill
                inner = pygame.Surface((radius_x*2, radius_x*2), pygame.SRCALPHA)
                pygame.draw.circle(inner, color + (80,), (radius_x, radius_x), radius_x)
                
                if getattr(cam, 'tilt_factor', 1.0) < 0.99 and getattr(c, 'APPLY_TILT_TO_OVERLAYS', False):
                    inner = pygame.transform.scale(inner, (radius_x * 2, radius_y * 2))
                    
                surface.blit(inner, (int(sx) - radius_x, int(sy) - radius_y))

def draw_movement_path(surface, map_screen, start_province, path_ids, color=(255, 255, 0), alpha=255, force_visible=False):
    """Draws a multi-segment path with lines underneath circles and a triangle at the end."""
    if not path_ids: return

    cam = map_screen.camera
    
    # 1. Convert to Screen Coordinates (Added offset support for looped rendering)
    def world_to_screen(pos, offset=0):
        sx = (pos[0] + offset - cam.pos.x) * cam.zoom
        sy = (pos[1] - cam.pos.y) * cam.zoom * getattr(cam, 'tilt_factor', 1.0) + map_screen.top_ui_height
        return sx, sy

    # Build an ordered list of all nodes in the path
    nodes = [start_province]
    for step_id in path_ids:
        target_node = map_screen.id_to_province.get(step_id)
        if target_node:
            nodes.append(target_node)

    if len(nodes) < 2: return
    
    # --- FOG OF WAR VISIBILITY CHECK ---
    visible_provs = getattr(map_screen, 'visible_provinces', None)
    def is_segment_visible(n1, n2):
        if force_visible or visible_provs is None:
            return True
        # If EITHER the start or end of this specific segment is visible, draw the segment!
        return n1["id"] in visible_provs or n2["id"] in visible_provs

    # Grab the UI symbols (Base scale is tweaked for zoom)
    line_base = symbol_loader.get_symbol("Line", cam.zoom * 1, color)
    circle_img = symbol_loader.get_symbol("Circle", cam.zoom * 1, color)
    triangle_img = symbol_loader.get_symbol("Triangle", cam.zoom * 1, color)

    offsets = [0, -map_screen.map_w, map_screen.map_w] if map_screen.loop_map else [0]

    # PASS 1: Draw all lines FIRST so they render underneath the shapes
    for i in range(len(nodes) - 1):
        n1 = nodes[i]
        n2 = nodes[i+1]
        
        # --- Apply the fog mask ---
        if not is_segment_visible(n1, n2):
            continue
            
        p1 = list(n1["center"])
        p2 = list(n2["center"])

        # Account for map wrap to get the shortest continuous distance
        if map_screen.loop_map:
            world_dx = p2[0] - p1[0]
            if world_dx > map_screen.map_w / 2:
                p2[0] -= map_screen.map_w
            elif world_dx < -map_screen.map_w / 2:
                p2[0] += map_screen.map_w

        for offset in offsets:
            # 1. Get the actual tilted screen coordinates for final placement
            start_pos = world_to_screen(p1, offset)
            end_pos = world_to_screen(p2, offset)

            # Basic culling to avoid drawing off-screen lines
            min_x = min(start_pos[0], end_pos[0])
            max_x = max(start_pos[0], end_pos[0])
            if max_x < 0 or min_x > surface.get_width():
                continue

            # 2. Calculate un-tilted logic for the raw rotation and length
            usx1 = (p1[0] + offset - cam.pos.x) * cam.zoom
            usy1 = (p1[1] - cam.pos.y) * cam.zoom
            usx2 = (p2[0] + offset - cam.pos.x) * cam.zoom
            usy2 = (p2[1] - cam.pos.y) * cam.zoom

            udx = usx2 - usx1
            udy = usy2 - usy1
            udist = math.hypot(udx, udy)
            uangle = math.degrees(math.atan2(-udy, udx))

            if line_base and int(udist) > 0:
                thickness = max(2, int(4 * cam.zoom))
                
                # Scale base image to the UN-TILTED distance
                scaled_line = pygame.transform.scale(line_base, (int(udist), thickness))
                
                # Rotate by the UN-TILTED angle
                rotated_line = pygame.transform.rotate(scaled_line, uangle)
                
                if alpha < 255:
                    rotated_line.set_alpha(alpha)
                    
                # --- THE FIX: Apply the tilt compression to the final rotated block ---
                if getattr(cam, 'tilt_factor', 1.0) < 0.99 and c.APPLY_TILT_TO_ARROWS:
                    rotated_line = pygame.transform.scale(
                        rotated_line, 
                        (rotated_line.get_width(), int(rotated_line.get_height() * cam.tilt_factor))
                    )
                
                # Place it at the TILTED midpoint
                rect = rotated_line.get_rect(center=((start_pos[0] + end_pos[0])/2, (start_pos[1] + end_pos[1])/2))
                surface.blit(rotated_line, rect)
            else:
                pygame.draw.line(surface, color, start_pos, end_pos, max(1, int(3 * cam.zoom)))

    # PASS 2: Draw the node markers on top of the lines
    for i in range(1, len(nodes)):
        n1 = nodes[i-1]
        n2 = nodes[i]
        
        # --- Apply the fog mask ---
        if not is_segment_visible(n1, n2):
            continue

        p1 = list(n1["center"])
        p2 = list(n2["center"])

        is_last = (i == len(nodes) - 1)

        # Apply the exact same map wrap logic to the endpoints
        if map_screen.loop_map:
            world_dx = p2[0] - p1[0]
            if world_dx > map_screen.map_w / 2:
                p2[0] -= map_screen.map_w
            elif world_dx < -map_screen.map_w / 2:
                p2[0] += map_screen.map_w

        for offset in offsets:
            start_pos = world_to_screen(p1, offset)
            end_pos = world_to_screen(p2, offset)

            # Culling Check
            if end_pos[0] < -50 or end_pos[0] > surface.get_width() + 50:
                continue

            dx = end_pos[0] - start_pos[0]
            dy = end_pos[1] - start_pos[1]
            angle = math.degrees(math.atan2(-dy, dx))

            if is_last:
                if triangle_img:
                    rotated_tri = pygame.transform.rotate(triangle_img, angle)
                    if alpha < 255:
                        rotated_tri.set_alpha(alpha)
                    if getattr(cam, 'tilt_factor', 1.0) < 0.99 and getattr(c, 'APPLY_TILT_TO_ARROWS', False):
                        rotated_tri = pygame.transform.scale(rotated_tri, (rotated_tri.get_width(), int(rotated_tri.get_height() * cam.tilt_factor)))
                    rect = rotated_tri.get_rect(center=end_pos)
                    surface.blit(rotated_tri, rect)
                else:
                    head_size = 15 * cam.zoom
                    angle_rad = math.atan2(dy, dx)
                    left_wing = (end_pos[0] - head_size * math.cos(angle_rad - math.pi / 6),
                                 end_pos[1] - head_size * math.sin(angle_rad - math.pi / 6))
                    right_wing = (end_pos[0] - head_size * math.cos(angle_rad + math.pi / 6),
                                   end_pos[1] - head_size * math.sin(angle_rad + math.pi / 6))
                    pygame.draw.polygon(surface, color, [end_pos, left_wing, right_wing])
            else:
                if circle_img:
                    draw_circle = circle_img.copy() if alpha < 255 else circle_img
                    if alpha < 255:
                        draw_circle.set_alpha(alpha)
                    if getattr(cam, 'tilt_factor', 1.0) < 0.99 and getattr(c, 'APPLY_TILT_TO_ARROWS', False):
                        draw_circle = pygame.transform.scale(draw_circle, (draw_circle.get_width(), int(draw_circle.get_height() * cam.tilt_factor)))
                    rect = draw_circle.get_rect(center=end_pos)
                    surface.blit(draw_circle, rect)
                else:
                    radius_x = max(3, int(4 * cam.zoom))
                    radius_y = int(radius_x * getattr(cam, 'tilt_factor', 1.0)) if getattr(c, 'APPLY_TILT_TO_ARROWS', False) else radius_x
                    pygame.draw.ellipse(surface, color, pygame.Rect(int(end_pos[0]) - radius_x, int(end_pos[1]) - radius_y, radius_x*2, radius_y*2))

def draw_overlay_content(self, surface):
    """Orchestrates what icons/symbols to draw over the map."""
    if self.secondary_mode == "BLANK":
        return

    # --- Render Combat Prediction Bubbles ---
    if self.secondary_mode == "UNITS" or self.map_mode == "POLITICAL":
        draw_combat_bubbles(self, surface)
    # ---------------------------------------------

    for color_key, province in self.map_data.items():
        
        # --- FOG OF WAR VISIBILITY CHECK ---
        if getattr(self, 'visible_provinces', None) is not None and province["id"] not in self.visible_provinces:
            continue
            
        cx, cy = province["center"]
        
        # Wrapping logic for screen coordinates
        offsets = [0, -self.map_w, self.map_w] if self.loop_map else [0]
        
        for offset in offsets:
            sx = int((cx + offset - self.camera.pos.x) * self.camera.zoom)
            sy = int((cy - self.camera.pos.y) * self.camera.zoom * getattr(self.camera, 'tilt_factor', 1.0)) + self.top_ui_height
            
            # Culling: only draw if within screen width
            if -50 < sx < surface.get_width() + 50:
                
                # --- UNIT VIEW ---
                if self.secondary_mode == "UNITS":
                    if province["units"]:
                        draw_unit_icon(self, surface, sx, sy, province)
                        
                    if queries.is_training_troops(province):
                        training_sym = symbol_loader.get_symbol(c.ICON_TRAINING, self.camera.zoom * c.OVERLAY_STATUS_ICON_SCALE)
                        if training_sym:
                            if getattr(self.camera, 'tilt_factor', 1.0) < 0.99 and getattr(c, 'APPLY_TILT_TO_STATUS_ICONS', False):
                                training_sym = pygame.transform.scale(training_sym, (training_sym.get_width(), int(training_sym.get_height() * self.camera.tilt_factor)))
                            training_sym.set_alpha(c.OVERLAY_STATUS_ICON_ALPHA)
                            rect = training_sym.get_rect(center=(sx, sy))
                            surface.blit(training_sym, rect)

                    # --- Disband Indicator ---
                    if any(u.get("order", {}).get("type") == "DISBAND" for u in province.get("units", [])):
                        disband_sym = symbol_loader.get_symbol(c.ICON_DISBANDING, self.camera.zoom * c.OVERLAY_STATUS_ICON_SCALE)
                        if disband_sym:
                            if getattr(self.camera, 'tilt_factor', 1.0) < 0.99 and getattr(c, 'APPLY_TILT_TO_STATUS_ICONS', False):
                                disband_sym = pygame.transform.scale(disband_sym, (disband_sym.get_width(), int(disband_sym.get_height() * self.camera.tilt_factor)))
                            disband_sym.set_alpha(c.OVERLAY_STATUS_ICON_ALPHA)
                            # Shifted slightly right to avoid overlapping completely with training
                            rect = disband_sym.get_rect(center=(sx, sy))
                            surface.blit(disband_sym, rect)

                # --- ECONOMY VIEW ---
                elif self.secondary_mode == "ECONOMY":
                    # Draw Buildings
                    buildings = province.get("buildings", [])
                    
                    # Sort buildings to ensure recruitment centers render on top
                    # Grouping is retrieved from building_library via queries
                    b_lib = queries.get_building_library()
                    buildings = sorted(buildings, key=lambda b: 1 if b_lib.get(b, {}).get("group") == "recruitment" else 0)
                    
                    for i, b_name in enumerate(buildings):

                        # Just in case we want to offset it for some reason
                        offset_x = 0
                        offset_y = 0
                        
                        sym_name = b_name
                        symbol = symbol_loader.get_symbol(sym_name, self.camera.zoom * c.BUILDING_ICON_SCALE)
                        
                        if symbol:
                            if getattr(self.camera, 'tilt_factor', 1.0) < 0.99 and getattr(c, 'APPLY_TILT_TO_OVERLAYS', False):
                                symbol = pygame.transform.scale(symbol, (symbol.get_width(), int(symbol.get_height() * self.camera.tilt_factor)))
                            
                            # Center the symbol based on the calculated sx/sy
                            draw_x = sx + offset_x - (symbol.get_width() // 2)
                            draw_y = sy + offset_y - (symbol.get_height() // 2)
                            surface.blit(symbol, (draw_x, draw_y))
                        else:
                            # Fallback colored squares for different types
                            color = (150, 150, 150) # Grey for workshop
                            if "Factory" in b_name: color = (100, 100, 200) # Blue-ish for factory
                            if "Refinery" in b_name: color = (200, 100, 100) # Red-ish for refinery
                            
                            w_scaled = int(12 * self.camera.zoom)
                            h_scaled = int(12 * self.camera.zoom * (getattr(self.camera, 'tilt_factor', 1.0) if getattr(c, 'APPLY_TILT_TO_OVERLAYS', False) else 1.0))
                            
                            # Center the rect using the same logic
                            rect = pygame.Rect(
                                sx + offset_x - (w_scaled // 2), 
                                sy + offset_y - (h_scaled // 2), 
                                w_scaled, 
                                h_scaled
                            )
                            pygame.draw.rect(surface, color, rect)
                            pygame.draw.rect(surface, (255, 255, 255), rect, 1) # Border
                    
                    # Draw Construction Hammer
                    if queries.is_constructing_building(province):
                        hammer_sym = symbol_loader.get_symbol(c.ICON_CONSTRUCTION, self.camera.zoom * c.OVERLAY_STATUS_ICON_SCALE)
                        if hammer_sym:
                            if getattr(self.camera, 'tilt_factor', 1.0) < 0.99 and getattr(c, 'APPLY_TILT_TO_STATUS_ICONS', False):
                                hammer_sym = pygame.transform.scale(hammer_sym, (hammer_sym.get_width(), int(hammer_sym.get_height() * self.camera.tilt_factor)))
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
                                sym = symbol_loader.get_symbol(res_type, self.camera.zoom * 0.8)
                                if sym:
                                    if getattr(self.camera, 'tilt_factor', 1.0) < 0.99 and getattr(c, 'APPLY_TILT_TO_OVERLAYS', False):
                                        sym = pygame.transform.scale(sym, (sym.get_width(), int(sym.get_height() * self.camera.tilt_factor)))
                                    surface.blit(sym, (sx + offset_x, sy))
                                else:
                                    # Fallback colored square
                                    c_col = (200, 200, 200)
                                    if res_type == "Iron": c_col = (180, 180, 180)
                                    if res_type == "Coal": c_col = (50, 50, 50)
                                    if res_type == "Oil": c_col = (30, 30, 30)
                                    h_scaled = int(15 * self.camera.zoom * (getattr(self.camera, 'tilt_factor', 1.0) if getattr(c, 'APPLY_TILT_TO_OVERLAYS', False) else 1.0))
                                    pygame.draw.rect(surface, c_col, (sx + offset_x, sy, int(15 * self.camera.zoom), h_scaled))
                                
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
    internal_w = c.UNIT_BOX_WIDTH
    internal_h = c.UNIT_BOX_HEIGHT
    
    # Dampened Scaling rules
    display_scale = 0.25 + (self.camera.zoom * 0.12)
    scaled_w = max(20, int(internal_w * display_scale))
    scaled_h = max(8, int(internal_h * display_scale))
    if getattr(self.camera, 'tilt_factor', 1.0) < 0.99 and c.APPLY_TILT_TO_OVERLAYS:
        scaled_h = max(8, int(scaled_h * self.camera.tilt_factor))
        
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
        best_unit = queries.get_best_unit_by_defense_then_attack_then_speed(owner_units)
        
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
        box_surf.fill(c.UNIT_BOX_BG_COLOR)
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