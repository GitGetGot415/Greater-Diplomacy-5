import pygame
from map_functions.rendering import hover_renderer, province_select, overlay_renderer
from map_functions.ui import minimap, tooltip, flag_renderer, top_bar_text, resource_hud
from map_functions.ui import ui_info_popup as unit_info_popup
from data.constants import SCREEN_WIDTH, SCREEN_HEIGHT
from map_functions.rendering.font_manager import fonts

def draw_map_screen(self, surface):
    # --- HOTSEAT MULTIPLAYER OVERRIDE ---
    if getattr(self, 'show_player_ready_screen', False):
        surface.fill((10, 10, 15)) # Deep black/blue
        
        font = fonts.get("title")
        txt = font.render(f"Player {self.current_player_index + 1} ({self.player_country.title()}) Ready?", True, (255, 255, 255))
        surface.blit(txt, txt.get_rect(center=(surface.get_width()//2, surface.get_height()//2 - 50)))

        btn_font = fonts.get("heading2")
        btn_txt = btn_font.render("Click here to start turn", True, (150, 255, 150))
        self.ready_btn_rect = btn_txt.get_rect(center=(surface.get_width()//2, surface.get_height()//2 + 50))
        surface.blit(btn_txt, self.ready_btn_rect)
        
        return # Skip drawing the map and UI completely!
        
    # --- LAYER 1: THE BASE MAP ---
    current_base = self.active_map
    # ... rest of function ...

    vw = surface.get_width() / self.camera.zoom
    vh = (surface.get_height() - self.total_ui_h) / self.camera.zoom
    x1, y1 = int(self.camera.pos.x), int(self.camera.pos.y)

    if self.loop_map:
        w1 = int(min(vw, self.map_w - x1))
        h1 = int(min(vh, self.map_h - y1))
        if w1 > 0 and h1 > 0:
            v1 = current_base.subsurface((x1, y1, w1, h1))
            surface.blit(pygame.transform.scale(v1, (int(w1*self.camera.zoom), int(h1*self.camera.zoom))), (0, self.top_ui_height))
        if w1 < vw and h1 > 0:
            wrap_w = int(vw - w1)
            if wrap_w > 0:
                v2 = current_base.subsurface((0, y1, wrap_w, h1))
                surface.blit(pygame.transform.scale(v2, (int(wrap_w*self.camera.zoom), int(h1*self.camera.zoom))), (int(w1*self.camera.zoom), self.top_ui_height))
    else:
        src_rect = pygame.Rect(x1, y1, int(vw), int(vh))
        clipped = src_rect.clip(current_base.get_rect())
        if clipped.width > 0 and clipped.height > 0:
            view = current_base.subsurface(clipped)
            surface.blit(pygame.transform.scale(view, (int(clipped.width*self.camera.zoom), int(clipped.height*self.camera.zoom))), (0, self.top_ui_height))

    # --- LAYER 2: SELECTION & HOVER ---
    if self.selected_province:
        # Darken everything for the modal effect
        modal_overlay = pygame.Surface((surface.get_width(), surface.get_height() - self.total_ui_h), pygame.SRCALPHA)
        modal_overlay.fill((0, 0, 0, 160)) 
        surface.blit(modal_overlay, (0, self.top_ui_height))
        province_select.draw_province_select(self, surface)
    else:
        hover_renderer.draw_hover_glow(self, surface)

    # --- LAYER 3: OVERLAYS (Units & Movement Arrows) ---
    overlay_renderer.draw_overlay_content(self, surface)
    
    for province in self.map_data.values():
        for unit in province.get("units", []):
            order = unit.get("order")
            if order and order.get("type") == "MOVE":
                path = order.get("path", [])
                if path:
                    prev_node = province
                    for step_id in path:
                        target_node = self.id_to_province.get(step_id)
                        if target_node:
                            overlay_renderer.draw_movement_arrow(surface, self, prev_node, target_node)
                            prev_node = target_node
                            
    # --- LAYER 3.5: COUNTRY NAMES ---
    # Only show names on the Political map to avoid cluttering other modes
    # if self.base_layer == "POLITICAL":
    # if self.secondary_mode == "BLANK":
    if False: # ignore this for now
        
        # 1. Cache text surfaces once to save performance
        if not hasattr(self, 'country_name_surfs'):
            self.country_name_surfs = {}
            # Use your biggest font preset for maximum resolution before scaling down
            name_font = fonts.get("country_name_display") 
            for c_id, data in self.nation_data.items():
                if c_id not in ["Ocean", "Lakes", "Unclaimed", "None"]:
                    disp = data.get("name", c_id).upper()
                    surf = name_font.render(disp, True, (255, 255, 255)).convert_alpha()
                    shadow = name_font.render(disp, True, (20, 20, 20)).convert_alpha()
                    self.country_name_surfs[c_id] = (surf, shadow)

        # 2 & 3. Draw the names with DYNAMIC alpha
        if hasattr(self, 'country_text_blobs'):
            import math
            
            drawn_countries = set()
            # Sort largest spatial spread to smallest so mainlands are always processed first!
            sorted_blobs = sorted(self.country_text_blobs, key=lambda b: b["spread"], reverse=True)
            
            for blob in sorted_blobs:
                country = blob["owner"]
                
                # Skip small island groups ONLY IF the country already has a name on the map
                if blob["count"] <= 1 and country in drawn_countries:
                    continue

                # if blob["count"] <= 3:
                #     continue

                surf, shadow = self.country_name_surfs.get(country, (None, None))
                if not surf: continue

                cx, cy = blob["cx"], blob["cy"]
                
                # Wrap logic for looped maps
                offsets = [0, -self.map_w, self.map_w] if self.loop_map else [0]
                for offset in offsets:
                    sx = (cx + offset - self.camera.pos.x) * self.camera.zoom
                    sy = (cy - self.camera.pos.y) * self.camera.zoom + self.top_ui_height

                    # Frustum Culling: Only draw if it's actually on the screen
                    if -200 < sx < surface.get_width() + 200 and 0 < sy < surface.get_height():
                        
                        # --- THE NEW SCALING LOGIC ---
                        scale_by_length = blob["length"] / surf.get_width()
                        scale_by_thickness = (blob["thickness"] * 0.8) / surf.get_height()
                        
                        land_scale = min(scale_by_length, scale_by_thickness)
                        land_scale = min(max(land_scale, 0.05), 1.0)
                        
                        # --- UNIVERSAL LINEAR FADE LOGIC ---
                        # Every country now fades at the exact same zoom levels.
                        # Tweak these two variables to your liking:
                        fade_start = 9.0   # Zoom level where text begins to fade out (was originally 2.0)
                        fade_window = 1.5  # Additional zoom required to become fully invisible
                        
                        if self.camera.zoom > fade_start:
                            alpha_ratio = 1.0 - min(1.0, (self.camera.zoom - fade_start) / fade_window)
                        else:
                            alpha_ratio = 1.0
                            
                        alpha = int(255 * alpha_ratio)

                        if alpha <= 0:
                            continue # Skip rendering entirely if fully transparent
                        # ---------------------------------------------
                        
                        scaled_w = int(surf.get_width() * self.camera.zoom * land_scale)
                        scaled_h = int(surf.get_height() * self.camera.zoom * land_scale)
                        
                        if scaled_w > 0 and scaled_h > 0:
                            scaled_text = pygame.transform.scale(surf, (scaled_w, scaled_h))
                            scaled_shadow = pygame.transform.scale(shadow, (scaled_w, scaled_h))
                            
                            angle = blob.get("angle", 0)
                            if abs(angle) > 2: 
                                scaled_text = pygame.transform.rotate(scaled_text, angle)
                                scaled_shadow = pygame.transform.rotate(scaled_shadow, angle)
                            
                            scaled_text.set_alpha(alpha)
                            scaled_shadow.set_alpha(alpha)
                            
                            # Center the rotated rect exactly on the calculated coordinates
                            txt_rect = scaled_text.get_rect(center=(int(sx), int(sy)))
                            
                            surface.blit(scaled_shadow, (txt_rect.x + 2, txt_rect.y + 2))
                            surface.blit(scaled_text, txt_rect)
                            
                            # Record that this country has successfully been drawn
                            drawn_countries.add(country)
                            
    # --- LAYER 4: UI BARS & HUD ---
    pygame.draw.rect(surface, (40, 40, 40), self.top_bar_rect)
    pygame.draw.rect(surface, (40, 40, 40), self.bot_bar_rect)
    
    if not self.selection_mode and not getattr(self, 'hide_raised_rect', False):
        pygame.draw.rect(surface, (160, 40, 40), self.raised_rect)
        pygame.draw.rect(surface, (80, 80, 40), self.ui_background_rect)
    
    if not self.selection_mode:
        # Call our clean, separated functions instead!
        flag_renderer.draw_flag(self, surface)
        top_bar_text.draw_top_text(self, surface)
        resource_hud.draw_bottom_text(self, surface)
        
        # Note: Sidebar info and minimap logic goes below here just like before
        if self.selected_province: 
            from map_functions.ui import sidebar_info
            sidebar_info.draw_sidebar_info(self, surface)
            unit_info_popup.draw_unit_info(self, surface)

        hide_mini = getattr(self, 'hide_minimap', False) or self.selected_province
        if not hide_mini:
            minimap.draw_minimap(self, surface, surface.get_width(), surface.get_height())

    # --- LAYER 5: SELECTION MODE ---
    else:
        prompt_txt = "Select a Country to Play As" if not self.pending_selection else f"Play as {self.pending_selection.title()}?"
        big_font = fonts.get("title")
        txt = big_font.render(prompt_txt, True, (255, 255, 255))
        bg_rect = txt.get_rect(center=(surface.get_width()//2, 50))
        pygame.draw.rect(surface, (0, 0, 0, 180), bg_rect.inflate(20, 10))
        surface.blit(txt, bg_rect)

        if self.pending_selection:
            overlay = pygame.Surface((surface.get_width(), surface.get_height()), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 100))
            surface.blit(overlay, (0, 0))
            
            box_rect = pygame.Rect(0, 0, 400, 200)
            box_rect.center = (surface.get_width()//2, surface.get_height()//2)
            pygame.draw.rect(surface, (40, 40, 40), box_rect)
            pygame.draw.rect(surface, (200, 200, 200), box_rect, 2)
            
            confirm_font = fonts.get("heading2")
            instr = confirm_font.render(f"Start Game as {self.pending_selection.title()}?", True, (255, 255, 255))
            surface.blit(instr, instr.get_rect(center=(box_rect.centerx, box_rect.y + 50)))
            
            self.confirm_rect = pygame.Rect(box_rect.x + 50, box_rect.bottom - 70, 120, 40)
            self.cancel_rect = pygame.Rect(box_rect.right - 170, box_rect.bottom - 70, 120, 40)
            
            pygame.draw.rect(surface, (0, 150, 0), self.confirm_rect)
            pygame.draw.rect(surface, (150, 0, 0), self.cancel_rect)
            
            c_txt = confirm_font.render("CONFIRM", True, (255, 255, 255))
            x_txt = confirm_font.render("CANCEL", True, (255, 255, 255))
            surface.blit(c_txt, c_txt.get_rect(center=self.confirm_rect.center))
            surface.blit(x_txt, x_txt.get_rect(center=self.cancel_rect.center))

   # --- LAYER 6: FEEDBACK & TOOLTIPS ---
   # this is the green text stuff
    if self.feedback_text and pygame.time.get_ticks() - self.feedback_timer < 2000:
        tsurf = self.font.render(self.feedback_text, True, (0, 255, 0))
        # Change SCREEN_HEIGHT - 40 to 20
        surface.blit(tsurf, (surface.get_width() - tsurf.get_width() - 1120, 20))

    # Check flag before drawing the tooltip
    # this is the stuff that makes it so that if you select a province you don't display the tooltip
    if self.hovered_province and not self.selected_province and not getattr(self, 'hide_tooltip', False): 
        tooltip.draw_tooltip(self, surface)
        
    # --- LAYER 7: EXIT CONFIRMATION MODAL ---
    if getattr(self, 'show_exit_confirmation', False):
        overlay = pygame.Surface((surface.get_width(), surface.get_height()), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 180))
        surface.blit(overlay, (0, 0))

        box_rect = pygame.Rect(0, 0, 450, 200)
        box_rect.center = (surface.get_width() // 2, surface.get_height() // 2)
        pygame.draw.rect(surface, (40, 40, 40), box_rect)
        pygame.draw.rect(surface, (200, 200, 200), box_rect, 2)

        font = fonts.get("heading2")
        msg = "Quit to Main Menu?"
        sub_msg = "Unsaved progress will be lost."
        
        txt_surf = font.render(msg, True, (255, 255, 255))
        sub_surf = fonts.get("normal").render(sub_msg, True, (200, 200, 200))
        
        surface.blit(txt_surf, txt_surf.get_rect(center=(box_rect.centerx, box_rect.y + 50)))
        surface.blit(sub_surf, sub_surf.get_rect(center=(box_rect.centerx, box_rect.y + 85)))

        yes_rect = pygame.Rect(box_rect.centerx - 130, box_rect.y + 120, 100, 40)
        no_rect = pygame.Rect(box_rect.centerx + 30, box_rect.y + 120, 100, 40)

        mx, my = pygame.mouse.get_pos()
        
        pygame.draw.rect(surface, (150, 0, 0) if yes_rect.collidepoint(mx, my) else (100, 0, 0), yes_rect)
        pygame.draw.rect(surface, (0, 150, 0) if no_rect.collidepoint(mx, my) else (0, 100, 0), no_rect)
        
        btn_font = fonts.get("button")
        surface.blit(btn_font.render("EXIT", True, (255, 255, 255)), (yes_rect.x + 25, yes_rect.y + 8))
        surface.blit(btn_font.render("STAY", True, (255, 255, 255)), (no_rect.x + 25, no_rect.y + 8))