import pygame
from map_logic.rendering import hover_renderer, province_select, overlay_renderer, country_names
from ui import minimap
from ui.information import feedback_text
import data.constants as c
from map_logic.rendering.font_manager import fonts
from ui.bars import flag_renderer
from ui.information import tooltip, ui_info_popup as unit_info_popup
from ui.bars import resource_hud, top_bar_text, ui_bars
from data import queries

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
    if not self.selected_province:
        hover_renderer.draw_hover_glow(self, surface)

    # --- LAYER 3: OVERLAYS (Units & Movement Arrows) ---
    overlay_renderer.draw_overlay_content(self, surface)
    
    for province in self.map_data.values():
        for unit in province.get("units", []):
            order = unit.get("order")
            if order and order.get("type") == "MOVE":
                path = order.get("path", [])
                if path:
                    # --- NEW VISIBILITY CHECK ---
                    owner = unit.get("owner")
                    is_player_unit = owner in getattr(self, 'active_players', [self.player_country])
                    is_spectator = self.player_country == "Spectator"
                    
                    # Hide the arrows if it's not the player's unit, the player isn't spectating,
                    # and the game isn't actively resolving AI turns.
                    if not is_player_unit and not is_spectator and not getattr(self, 'viewing_ai_moves', False):
                        continue
                    # ----------------------------

                    # Dynamically pull the color of the unit's owner (fallback to yellow)
                    owner_color = self.nation_colors.get(unit.get("owner", "Unclaimed"), (255, 255, 0))
                    
                    # --- NEW: Split paths to render queued segments differently ---
                    speed = unit.get("speed", 1)
                    immediate_path = path[:speed]
                    queued_path = path[speed:]
                    
                    if immediate_path:
                        overlay_renderer.draw_movement_path(surface, self, province, immediate_path, color=owner_color)
                        
                    if queued_path:
                        # Brighten the owner color heavily for the queue overlay
                        bright_color = (min(255, owner_color[0] + 150), min(255, owner_color[1] + 150), min(255, owner_color[2] + 150))
                        
                        # Start the queued line from the end of the immediate path
                        q_start = self.id_to_province.get(immediate_path[-1]) if immediate_path else province
                        overlay_renderer.draw_movement_path(surface, self, q_start, queued_path, color=bright_color, alpha=120)
                            
    # --- LAYER 3.5: COUNTRY NAMES ---
    country_names.draw_country_names(self, surface)
    
    # --- LAYER 3.8: PROVINCE MENU OVERLAYS ---
    if self.selected_province:
        if self.selection_mode:
            # Use the transparent black for country selection confirmation
            modal_overlay = pygame.Surface((surface.get_width(), surface.get_height() - self.total_ui_h), pygame.SRCALPHA)
            modal_overlay.fill((0, 0, 0, 160)) 
            surface.blit(modal_overlay, (0, self.top_ui_height))
        else:
            # Use the custom transparent PNG for the actual province menu
            # Pass the backgrounds directory to the image loader!
            province_bg = ui_bars.get_ui_image(c.PROVINCE_BG_FILE, directory=c.BACKGROUNDS_DIR)
            if province_bg.get_size() != surface.get_size():
                province_bg = pygame.transform.scale(province_bg, surface.get_size())
            surface.blit(province_bg, (0, 0))
            
        province_select.draw_province_select(self, surface)
            
    # --- LAYER 4: UI BARS & HUD ---
    ui_bars.draw_ui_bars(self, surface)
    
    if not self.selection_mode:
        # Call our clean, separated functions instead!
        flag_renderer.draw_flag(self, surface)
        top_bar_text.draw_top_text(self, surface)
        resource_hud.draw_bottom_text(self, surface)
        
        # Note: Sidebar info and minimap logic goes below here just like before
        if self.selected_province: 
            from ui import sidebar_info
            sidebar_info.draw_sidebar_info(self, surface)
            sidebar_info.draw_owner_portrait(self, surface)
            unit_info_popup.draw_unit_info(self, surface)
            
            # --- MODIFIED: Draw the queue if it's the player's province OR spectator ---
            if self.selected_province.get("owner") == self.player_country or self.player_country == "Spectator":
                from screens.map_related_screens import recruit_ui
                recruit_ui.draw_map_queue_overlay(surface, self.selected_province)

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
    feedback_text.draw_feedback(self, surface)

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
    
def draw_badges(self, surface):
    """Draws notification badges on top of buttons after the main UI renders."""
    if not self.selection_mode and not getattr(self, 'hide_raised_rect', False):
        from data import queries
        import data.constants as c
        
        # Get counts
        unread_msgs = queries.get_unread_message_count(self.player_country, self.nation_data)
        free_research = queries.has_free_research_slots(self.player_country, self.nation_data)
        
        badge_font = fonts.get("tiny")
        
        def draw_badge(btn, text):
            if not btn.visible: return
            # Draw badge in the top right corner of the button
            bx, by = btn.rect.right - 10, btn.rect.top + 10
            pygame.draw.circle(surface, c.MSG_NOTIFICATION_COLOR, (bx, by), 12)
            pygame.draw.circle(surface, (255, 255, 255), (bx, by), 12, 1)
            txt_surf = badge_font.render(str(text), True, (255, 255, 255))
            surface.blit(txt_surf, txt_surf.get_rect(center=(bx, by)))

        # Draw the badges on the respective buttons
        if unread_msgs > 0:
            draw_badge(self.btn_gp_msgs, unread_msgs)
            
        if free_research:
            draw_badge(self.btn_gp_rd, "!")