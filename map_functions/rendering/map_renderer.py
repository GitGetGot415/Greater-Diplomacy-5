import pygame
from map_functions.rendering import hover_renderer, province_select, overlay_renderer
from map_functions.ui import minimap, tooltip
from map_functions.ui import ui_info_popup as unit_info_popup
from gameState import SCREEN_WIDTH, SCREEN_HEIGHT

def draw_map_screen(self, surface):
    # --- LAYER 1: THE BASE MAP ---
    current_base = self.active_map

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
                            
    # --- LAYER 4: UI BARS & HUD ---
    pygame.draw.rect(surface, (40, 40, 40), self.top_bar_rect)
    pygame.draw.rect(surface, (40, 40, 40), self.bot_bar_rect)
    
    if not self.selection_mode and not getattr(self, 'hide_raised_rect', False):
        pygame.draw.rect(surface, (160, 40, 40), self.raised_rect)
    
    if not self.selection_mode:
        # Check flag before drawing Date
        if not getattr(self, 'hide_top_info', False):
            date_surf = self.font.render(self.time_manager.get_date_string(), True, (255, 255, 255))
            surface.blit(date_surf, (SCREEN_WIDTH // 2 - date_surf.get_width() // 2, 20))

        # Check if we should hide the HUD (active if a province is selected or explicitly hidden)
        hide_hud = getattr(self, 'hide_resource_hud', False) or self.selected_province
        
        if not hide_hud:
            # --- NEW CLEAN RESOURCE HUD WITH NET INCOME ---
            hud_y = SCREEN_HEIGHT - 85
            
            if not hasattr(self, 'econ_cache_time') or pygame.time.get_ticks() - getattr(self, 'econ_cache_time', 0) > 1000:
                self.econ_cache = self.get_player_economy_projections()
                self.econ_cache_time = pygame.time.get_ticks()
                
            total_inc, total_upkeep = getattr(self, 'econ_cache', (
                {"money":0, "manpower":0, "materials":0, "fuel":0}, 
                {"money":0, "manpower":0, "materials":0, "fuel":0}
            ))

            def fmt_net(inc, exp):
                net = int(inc - exp)
                return f"+{net}" if net >= 0 else str(net)

            resources = [
                (f"Money: {int(self.player_money)} ({fmt_net(total_inc['money'], total_upkeep['money'])})", (255, 215, 0)),
                (f"Manpower: {int(self.player_manpower)} ({fmt_net(total_inc['manpower'], total_upkeep['manpower'])})", (100, 200, 255)),
                (f"Materials: {int(self.player_materials)} ({fmt_net(total_inc['materials'], total_upkeep['materials'])})", (180, 180, 180)),
                (f"Fuel: {int(self.player_fuel)} ({fmt_net(total_inc['fuel'], total_upkeep['fuel'])})", (200, 100, 255))
            ]
            
            start_x = 250
            spacing = 240
            
            bg_width = (len(resources) * spacing) - 40
            bg_surf = pygame.Surface((bg_width, 30), pygame.SRCALPHA)
            bg_surf.fill((0, 0, 0, 200))
            
            bg_rect = pygame.Rect(start_x - 15, hud_y - 5, bg_width, 30)
            surface.blit(bg_surf, bg_rect.topleft)
            pygame.draw.rect(surface, (100, 100, 100), bg_rect, 1) 

            for i, (text, color) in enumerate(resources):
                surface.blit(self.font.render(text, True, color), (start_x + (i * spacing), hud_y))

        # Check flag before drawing "Playing as" text
        if not getattr(self, 'hide_top_info', False):
            player_display = self.nation_data.get(self.player_country, {}).get("name", self.player_country)
            name_surf = self.font.render(f"{player_display.title()}", True, (200, 200, 200))
            # surface.blit(name_surf, (surface.get_width() - name_surf.get_width() - 220, 20))
            surface.blit(name_surf, (200, 20))
        
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
        big_font = pygame.font.SysFont("Arial", 40)
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
            
            confirm_font = pygame.font.SysFont("Arial", 24)
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

        font = pygame.font.SysFont("Arial", 26, bold=True)
        msg = "Quit to Main Menu?"
        sub_msg = "Unsaved progress will be lost."
        
        txt_surf = font.render(msg, True, (255, 255, 255))
        sub_surf = pygame.font.SysFont("Arial", 18).render(sub_msg, True, (200, 200, 200))
        
        surface.blit(txt_surf, txt_surf.get_rect(center=(box_rect.centerx, box_rect.y + 50)))
        surface.blit(sub_surf, sub_surf.get_rect(center=(box_rect.centerx, box_rect.y + 85)))

        yes_rect = pygame.Rect(box_rect.centerx - 130, box_rect.y + 120, 100, 40)
        no_rect = pygame.Rect(box_rect.centerx + 30, box_rect.y + 120, 100, 40)

        mx, my = pygame.mouse.get_pos()
        
        pygame.draw.rect(surface, (150, 0, 0) if yes_rect.collidepoint(mx, my) else (100, 0, 0), yes_rect)
        pygame.draw.rect(surface, (0, 150, 0) if no_rect.collidepoint(mx, my) else (0, 100, 0), no_rect)
        
        btn_font = pygame.font.SysFont("Arial", 20, bold=True)
        surface.blit(btn_font.render("EXIT", True, (255, 255, 255)), (yes_rect.x + 25, yes_rect.y + 8))
        surface.blit(btn_font.render("STAY", True, (255, 255, 255)), (no_rect.x + 25, no_rect.y + 8))