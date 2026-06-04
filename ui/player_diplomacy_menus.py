import pygame
import data.constants as c
from data import queries
from map_logic.diplomacy import diplomacy_logic
from gameState import GameState
from ui_elements import Button
from map_logic.rendering.font_manager import fonts

def _run_pygame_sub_screen(map_screen, screen_obj):
    """Runs a blocking PyGame loop that acts like a GameState to bypass the main state machine."""
    screen_obj.done = False
    clock = pygame.time.Clock()
    surface = pygame.display.get_surface()
    
    while not screen_obj.done:
        events = pygame.event.get()
        for event in events:
            if event.type == pygame.QUIT:
                import sys
                pygame.quit()
                sys.exit()
        
        screen_obj.handle_events(events)
        screen_obj.update()
        
        # The background is safely filled by the map rendering itself.
        screen_obj.draw(surface)
        pygame.display.flip()
        
        clock.tick(getattr(c, 'TARGET_FPS', 60))
        
    # Clear any phantom hovering from the sub-screen
    map_screen.hovered_province = None

# ==========================================
# DECLARE WAR SCREEN
# ==========================================

class Declare_War_Screen(GameState):
    def __init__(self, map_screen, target_nation):
        super().__init__()
        self.map_screen = map_screen
        self.target_nation = target_nation
        
        wargoals = map_screen.nation_data.get(map_screen.player_country, {}).get("wargoals", {}).get(target_nation, {})
        has_wg = queries.has_wargoal(map_screen.player_country, target_nation, map_screen.nation_data)
        wg_type = wargoals.get("type", "") if has_wg else ""
        
        # Determine available wargoals to choose from
        take_claims_enabled = has_wg and (wg_type == getattr(c, 'WARGOAL_TAKE_CLAIMS', "Take Claims") or not wg_type)
        
        # Spectator / Override catch: if it's the spectator, let them force it anyway
        if map_screen.player_country == "Spectator":
            take_claims_enabled = True

        self.wargoal_options = [
            {"label": getattr(c, 'WARGOAL_TAKE_CLAIMS', "Take Claims"), "enabled": take_claims_enabled},
            {"label": getattr(c, 'WARGOAL_NO_CB', "No Casus Belli"), "enabled": not c.CASUS_BELLI_REQUIRED},
            {"label": "Don't Declare War", "enabled": True}
        ]
            
        self.selected_wargoal_idx = 2 # Default to Don't Declare War
        
        # Check if a war declaration is already queued
        pending = map_screen.nation_data.get(map_screen.player_country, {}).get("pending_diplomacy", {}).get(target_nation, {})
        self.is_editing = isinstance(pending, dict) and pending.get("action") == "WAR_DECLARATION"
        
        if self.is_editing:
            pending_msg = pending.get("message", "")
            for i, opt in enumerate(self.wargoal_options):
                if opt["label"] == pending_msg and opt["enabled"]:
                    self.selected_wargoal_idx = i
                    break
        else:
            # Auto-select the first enabled wargoal that actually declares war if available
            for i, opt in enumerate(self.wargoal_options):
                if opt["enabled"] and i != 2:
                    self.selected_wargoal_idx = i
                    break

        self.panel_rect = pygame.Rect(c.SCREEN_WIDTH//2 - 200, c.SCREEN_HEIGHT//2 - 150, 400, 300)
        self.refresh_ui()

    def refresh_ui(self):
        self.elements = [Button(50, c.TOP_BAR_UI_CENTER_Y, "small", "red", "Cancel", self.exit_screen)]
        
        confirm_text = "Update Declaration" if self.is_editing else "Confirm"
        btn_confirm = Button(self.panel_rect.centerx - 150, self.panel_rect.bottom - 70, "new_game", "red", confirm_text, self.confirm)
        self.elements.append(btn_confirm)
        
        for i, opt in enumerate(self.wargoal_options):
            if opt["enabled"]:
                color = "green" if self.selected_wargoal_idx == i else "blue"
            else:
                color = "grey"
                
            btn = Button(self.panel_rect.centerx - 150, self.panel_rect.y + 60 + (i * 55), "new_game", color, opt["label"], lambda idx=i: self.select_wg(idx))
            if not opt["enabled"]:
                btn.disabled = True
            self.elements.append(btn)

    def select_wg(self, idx):
        if self.wargoal_options[idx]["enabled"]:
            self.selected_wargoal_idx = idx
            self.refresh_ui()

    def confirm(self):
        wg = self.wargoal_options[self.selected_wargoal_idx]["label"]
        
        if wg == "Don't Declare War":
            pending = self.map_screen.nation_data[self.map_screen.player_country].get("pending_diplomacy", {})
            if self.target_nation in pending and pending[self.target_nation].get("action") == "WAR_DECLARATION":
                del pending[self.target_nation]
            self.map_screen.show_feedback("War Declaration Cancelled.")
            self.done = True
        else:
            # Overwrite any existing declaration natively without triggering the toggle/delete logic
            pending = self.map_screen.nation_data[self.map_screen.player_country].setdefault("pending_diplomacy", {})
            
            pending[self.target_nation] = {
                "action": "WAR_DECLARATION",
                "turns": 0,
                "timer": 0,
                "message": wg
            }
            self.map_screen.show_feedback("War Declaration Queued!" if not self.is_editing else "War Declaration Updated!")
            self.done = True

    def exit_screen(self):
        self.done = True

    def handle_events(self, events):
        for event in events:
            for el in self.elements:
                el.handle_event(event)

    def draw(self, surface):
        # FIX: Wipe the frame clean to prevent the "Solitaire Effect" smearing through the transparent oceans
        surface.fill(self.map_screen.bg_color)
        
        temp_prov = self.map_screen.selected_province
        self.map_screen.selected_province = None
        self.map_screen.hide_raised_rect = True

        self.map_screen.hide_tooltip = True
        self.map_screen.hide_resource_hud = True
        self.map_screen.hide_minimap = True
        
        self.map_screen.additional_draw(surface)
        
        self.map_screen.hide_raised_rect = False
        self.map_screen.hide_tooltip = False
        self.map_screen.hide_resource_hud = False
        self.map_screen.hide_minimap = False
        self.map_screen.selected_province = temp_prov

        overlay = pygame.Surface((c.SCREEN_WIDTH, c.SCREEN_HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 180))
        surface.blit(overlay, (0, 0))

        pygame.draw.rect(surface, (40, 30, 30), self.panel_rect)
        pygame.draw.rect(surface, (255, 50, 50), self.panel_rect, 3)

        font = fonts.get("heading1")
        title = font.render(f"Declare War: {self.target_nation}", True, (255, 255, 255))
        surface.blit(title, (self.panel_rect.centerx - title.get_width()//2, self.panel_rect.y + 20))

        # Draw UI elements manually to prevent super().draw() from filling the screen with a solid background color
        for el in self.elements:
            if getattr(el, 'visible', True):
                el.draw(surface)

# ==========================================
# JUSTIFY WARGOAL SCREEN
# ==========================================

class Justify_Screen(GameState):
    def __init__(self, map_screen, target_nation):
        super().__init__()
        self.map_screen = map_screen
        self.target_nation = target_nation
        
        self.at_war = queries.are_at_war(map_screen.player_country, target_nation, map_screen.nation_data)
        self.has_wargoal = queries.has_wargoal(map_screen.player_country, target_nation, map_screen.nation_data)
        
        self.valid_targets = queries.get_valid_claim_targets(map_screen.player_country, target_nation, map_screen.map_data)
        self.valid_ids = [p["id"] for p in self.valid_targets]
        
        # Check for existing justification
        self.is_editing = False
        self.original_selected_ids = []
        self.remaining_turns = 0
        self.original_total_turns = 0
        
        pending = map_screen.nation_data.get(map_screen.player_country, {}).get("pending_diplomacy", {}).get(target_nation, {})
        player_claims = map_screen.nation_data.get(map_screen.player_country, {}).get("claims", [])
        
        self.view_only_mode = False
        
        if isinstance(pending, dict) and pending.get("action") == "JUSTIFY_WARGOAL":
            self.is_editing = True
            self.selected_ids = [int(x) for x in pending.get("message", "").split(",") if x]
            self.original_selected_ids = list(self.selected_ids)
            self.remaining_turns = pending.get("timer", 0)
            self.original_total_turns = queries.calculate_justification_time(map_screen.player_country, self.original_selected_ids, map_screen.id_to_province)
            self.view_only_mode = True # Default to view-only when opening a processing justification
        elif self.has_wargoal:
            self.selected_ids = [pid for pid in self.valid_ids if pid in player_claims]
            self.original_selected_ids = list(self.selected_ids)
            self.view_only_mode = True # Default to view-only when opening a completed wargoal
        else:
            self.selected_ids = []
            
        if self.at_war:
            self.view_only_mode = True # Always view-only during war
        
        # Left Panel mimic
        self.panel_rect = pygame.Rect(80, 120, 380, c.SCREEN_HEIGHT - 240)
        self.refresh_ui()

    def refresh_ui(self):
        self.elements = [Button(50, c.TOP_BAR_UI_CENTER_Y, "small", "red", "Back", self.exit_screen)]
        
        if self.at_war:
            # Read-only mode, no confirm buttons
            pass
        elif self.is_editing:
            # btn_confirm = Button(self.panel_rect.centerx - 150, self.panel_rect.bottom - 130, "new_game", "orange", "Update Justification", self.confirm)
            btn_cancel = Button(self.panel_rect.centerx - 150, self.panel_rect.bottom - 70, "new_game", "red", "Cancel Justification", self.cancel_justification)
            self.elements.extend([btn_cancel])
        elif self.has_wargoal:
            if self.view_only_mode:
                btn_edit = Button(self.panel_rect.centerx - 150, self.panel_rect.bottom - 70, "new_game", "blue", "Edit Justification", self.enable_editing)
                self.elements.append(btn_edit)
            else:
                btn_confirm = Button(self.panel_rect.centerx - 150, self.panel_rect.bottom - 130, "new_game", "orange", "Confirm Edit", self.confirm)
                btn_cancel = Button(self.panel_rect.centerx - 150, self.panel_rect.bottom - 70, "new_game", "red", "Cancel", self.cancel_edit)
                self.elements.extend([btn_confirm, btn_cancel])
        else:
            btn_confirm = Button(self.panel_rect.centerx - 150, self.panel_rect.bottom - 70, "new_game", "orange", "Start Justification", self.confirm)
            self.elements.append(btn_confirm)
            
    def enable_editing(self):
        self.view_only_mode = False
        self.refresh_ui()
        
    def cancel_edit(self):
        self.view_only_mode = True
        self.selected_ids = list(self.original_selected_ids)
        self.refresh_ui()
                
    def confirm(self):
        if not self.selected_ids and not self.has_wargoal and not self.is_editing:
            self.map_screen.show_feedback("Select at least one province!")
            return
            
        new_total_turns = queries.calculate_justification_time(self.map_screen.player_country, self.selected_ids, self.map_screen.id_to_province)
        if self.is_editing:
            elapsed = self.original_total_turns - self.remaining_turns
            final_timer = max(1, new_total_turns - elapsed)
        elif self.has_wargoal:
            # Calculate the time for ONLY the new provinces being added
            original_total_turns = queries.calculate_justification_time(self.map_screen.player_country, self.original_selected_ids, self.map_screen.id_to_province)
            final_timer = max(1, new_total_turns - original_total_turns + 1)
        else:
            final_timer = new_total_turns
            
        pending = self.map_screen.nation_data[self.map_screen.player_country].setdefault("pending_diplomacy", {})

        # Manually set the dictionary to bypass the toggle/delete logic in toggle_diplomacy_action
        pending[self.target_nation] = {
            "action": "JUSTIFY_WARGOAL",
            "turns": 0,
            "timer": final_timer,
            "message": ",".join(map(str, self.selected_ids))
        }
        self.map_screen.show_feedback("Justification Updated!" if self.is_editing else "Justification Started!")
        self.done = True

    def cancel_justification(self):
        pending = self.map_screen.nation_data[self.map_screen.player_country].get("pending_diplomacy", {})
        if self.target_nation in pending:
            del pending[self.target_nation]
        self.map_screen.show_feedback("Justification Cancelled.")
        self.done = True

    def exit_screen(self):
        self.done = True

    def get_clicked_province(self, mouse_pos):
        cam = self.map_screen.camera
        mx, my = mouse_pos
        wx = ((mx / cam.zoom) + cam.pos.x) % self.map_screen.map_w
        wy = ((my - self.map_screen.top_ui_height) / (cam.zoom * getattr(cam, 'tilt_factor', 1.0))) + cam.pos.y
        if 0 <= wy < self.map_screen.map_h:
            color = self.map_screen.id_map.get_at((int(wx), int(wy)))
            return self.map_screen.map_data.get((color.r, color.g, color.b))
        return None

    def handle_events(self, events):
        for event in events:
            # Sub-UI Logic checks
            on_ui = self.panel_rect.collidepoint(pygame.mouse.get_pos()) or self.map_screen.top_bar_rect.collidepoint(pygame.mouse.get_pos())
            
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if not on_ui and not self.view_only_mode:
                    dest = self.get_clicked_province(event.pos)
                    if dest and dest["id"] in self.valid_ids:
                        if dest["id"] in self.selected_ids:
                            self.selected_ids.remove(dest["id"])
                        else:
                            self.selected_ids.append(dest["id"])
                        self.refresh_ui()
            
            # Map Hover feedback
            elif event.type == pygame.MOUSEMOTION:
                dest = self.get_clicked_province(event.pos)
                if dest and dest["id"] in self.valid_ids and not self.panel_rect.collidepoint(event.pos):
                    self.hovered_prov = dest
                else:
                    self.hovered_prov = None

            # Route panning and scrolling back to the active world map camera
            if event.type in (pygame.MOUSEWHEEL, pygame.MOUSEMOTION):
                self.map_screen.camera.handle_input(event, self.map_screen, on_ui)

            for el in self.elements:
                el.handle_event(event)

    def update(self):
        super().update()
        self.map_screen.camera.update(self.map_screen, c.SCREEN_HEIGHT)

    def draw(self, surface):
        # FIX: Wipe the frame clean to prevent the "Solitaire Effect" smearing through the transparent oceans
        surface.fill(self.map_screen.bg_color)
        
        temp_prov = self.map_screen.selected_province
        self.map_screen.selected_province = None
        self.map_screen.hide_raised_rect = True

        self.map_screen.hide_tooltip = True
        self.map_screen.hide_resource_hud = True
        self.map_screen.hide_minimap = True
        
        self.map_screen.additional_draw(surface)
        
        self.map_screen.hide_raised_rect = False
        self.map_screen.hide_tooltip = False
        self.map_screen.hide_resource_hud = False
        self.map_screen.hide_minimap = False
        self.map_screen.selected_province = temp_prov

        # Draw Ellipse target highlights for claimed targets
        for pid in self.selected_ids:
            prov = self.map_screen.id_to_province.get(pid)
            if prov:
                cx, cy = prov["center"]
                for offset in [0, -self.map_screen.map_w, self.map_screen.map_w]:
                    sx = (cx + offset - self.map_screen.camera.pos.x) * self.map_screen.camera.zoom
                    sy = (cy - self.map_screen.camera.pos.y) * self.map_screen.camera.zoom * getattr(self.map_screen.camera, 'tilt_factor', 1.0) + self.map_screen.top_ui_height
                    if -100 < sx < c.SCREEN_WIDTH + 100:
                        radius_x = max(2, int(4 * self.map_screen.camera.zoom))
                        radius_y = int(radius_x * getattr(self.map_screen.camera, 'tilt_factor', 1.0)) if getattr(c, 'APPLY_TILT_TO_OVERLAYS', False) else radius_x
                        pygame.draw.ellipse(surface, (255, 165, 0), pygame.Rect(int(sx) - radius_x, int(sy) - radius_y, radius_x*2, radius_y*2), max(2, int(2*self.map_screen.camera.zoom)))

        # Draw Hovered target
        if getattr(self, 'hovered_prov', None):
            cx, cy = self.hovered_prov["center"]
            for offset in [0, -self.map_screen.map_w, self.map_screen.map_w]:
                sx = (cx + offset - self.map_screen.camera.pos.x) * self.map_screen.camera.zoom
                sy = (cy - self.map_screen.camera.pos.y) * self.map_screen.camera.zoom * getattr(self.map_screen.camera, 'tilt_factor', 1.0) + self.map_screen.top_ui_height
                if -100 < sx < c.SCREEN_WIDTH + 100:
                    radius_x = max(6, int(8 * self.map_screen.camera.zoom))
                    radius_y = int(radius_x * getattr(self.map_screen.camera, 'tilt_factor', 1.0)) if getattr(c, 'APPLY_TILT_TO_OVERLAYS', False) else radius_x
                    pygame.draw.ellipse(surface, (255, 255, 255), pygame.Rect(int(sx) - radius_x, int(sy) - radius_y, radius_x*2, radius_y*2), max(2, int(2*self.map_screen.camera.zoom)))

        # Title
        font = fonts.get("heading1")
        title_str = f"View War Goal: {self.target_nation}" if self.view_only_mode else f"Justify Wargoal: {self.target_nation}"
        title = font.render(title_str, True, (255, 255, 255))
        surface.blit(title, (c.SCREEN_WIDTH//2 - title.get_width()//2, c.TOP_BAR_UI_CENTER_Y))

        # Panel
        panel_surf = pygame.Surface((self.panel_rect.width, self.panel_rect.height), pygame.SRCALPHA)
        panel_surf.fill((30, 30, 50, 230))
        surface.blit(panel_surf, self.panel_rect.topleft)
        pygame.draw.rect(surface, (200, 150, 50), self.panel_rect, 2)

        sub_font = fonts.get("heading2")
        tiny_font = fonts.get("normal")

        surface.blit(sub_font.render("Selected Provinces:", True, (255, 255, 255)), (self.panel_rect.x + 20, self.panel_rect.y + 20))
        
        y_off = self.panel_rect.y + 60
        if not self.selected_ids:
            surface.blit(tiny_font.render("No provinces selected.", True, (150, 150, 150)), (self.panel_rect.x + 30, y_off))
        else:
            # Cut down max items to 10 to ensure it doesn't overlap our newly placed buttons!
            for i, pid in enumerate(self.selected_ids[:10]):
                is_core = self.map_screen.player_country in self.map_screen.id_to_province[pid].get("cores", [])
                core_str = " (CORE)" if is_core else ""
                txt = tiny_font.render(f"- Province {pid}{core_str}", True, (200, 200, 200))
                surface.blit(txt, (self.panel_rect.x + 30, y_off))
                y_off += 25
            
            if len(self.selected_ids) > 10:
                txt = tiny_font.render(f"...and {len(self.selected_ids)-10} more", True, (150, 150, 150))
                surface.blit(txt, (self.panel_rect.x + 30, y_off))

        if self.at_war:
            time_txt = sub_font.render("War Goal Active (Read-Only)", True, (200, 200, 200))
            time_y = self.panel_rect.bottom - 110
        # ADDED 'and not self.is_editing' so it shows the edit timer instead of "War Goal Ready"
        elif self.has_wargoal and self.view_only_mode and not self.is_editing: 
            time_txt = sub_font.render("War Goal Ready", True, (100, 255, 100))
            time_y = self.panel_rect.bottom - 110
        else:
            if not self.selected_ids and not self.has_wargoal and not self.is_editing:
                current_estimated_turns = 0
            else:
                new_total_turns = queries.calculate_justification_time(self.map_screen.player_country, self.selected_ids, self.map_screen.id_to_province)
                if self.is_editing:
                    elapsed = self.original_total_turns - self.remaining_turns
                    current_estimated_turns = max(1, new_total_turns - elapsed)
                elif self.has_wargoal:
                    original_total_turns = queries.calculate_justification_time(self.map_screen.player_country, self.original_selected_ids, self.map_screen.id_to_province)
                    current_estimated_turns = max(1, new_total_turns - original_total_turns + 1)
                else:
                    current_estimated_turns = new_total_turns
                    
            if self.is_editing and self.selected_ids == self.original_selected_ids:
                time_txt = sub_font.render(f"Time Remaining: {self.remaining_turns} turns", True, (255, 100, 100))
            else:
                time_txt = sub_font.render(f"Estimated Time: {current_estimated_turns} turns", True, (255, 100, 100))
                
            is_two_buttons = (self.has_wargoal and not self.view_only_mode)
            time_y = self.panel_rect.bottom - (170 if is_two_buttons else 110)

        surface.blit(time_txt, (self.panel_rect.centerx - time_txt.get_width()//2, time_y))

        # Draw UI elements manually to prevent super().draw() from filling the screen with a solid background color
        for el in self.elements:
            if getattr(el, 'visible', True):
                el.draw(surface)

# ==========================================
# CEASEFIRE / PEACE SCREEN
# ==========================================

class Peace_Screen(GameState):
    def __init__(self, map_screen, target_nation):
        super().__init__()
        self.map_screen = map_screen
        self.target_nation = target_nation
        
        my_wargoal = map_screen.nation_data.get(map_screen.player_country, {}).get("wargoals", {}).get(target_nation, {}).get("type", "")
        their_wargoal = map_screen.nation_data.get(target_nation, {}).get("wargoals", {}).get(map_screen.player_country, {}).get("type", "")
        
        self.terms = [
            getattr(c, 'PEACE_WHITE_PEACE', "Ceasefire (White Peace)"),
            getattr(c, 'PEACE_DEMAND_CLAIMS', "Demand Claims"),
            getattr(c, 'PEACE_SURRENDER', "Surrender"),
            "Don't offer peace"
        ]
        
        self.terms_enabled = [
            True,
            my_wargoal == getattr(c, 'WARGOAL_TAKE_CLAIMS', "Take Claims"),
            my_wargoal != getattr(c, 'WARGOAL_NO_CB', "No Casus Belli") and their_wargoal != getattr(c, 'WARGOAL_NO_CB', "No Casus Belli"),
            True
        ]
        
        # Check for existing peace offer
        pending = map_screen.nation_data.get(map_screen.player_country, {}).get("pending_diplomacy", {}).get(target_nation, {})
        self.is_editing = isinstance(pending, dict) and pending.get("action") in ["PEACE_TREATY", "CEASEFIRE"]
        
        if self.is_editing:
            pending_msg = pending.get("message", "")
            self.selected_term_idx = 3 # Default to Don't offer peace
            for i, term in enumerate(self.terms):
                if term == pending_msg and self.terms_enabled[i]:
                    self.selected_term_idx = i
                    break
            
            # Catch raw CEASEFIRE actions from legacy behavior
            if self.selected_term_idx == 3 and pending.get("action") == "CEASEFIRE":
                self.selected_term_idx = 0
        else:
            self.selected_term_idx = 0
            
        self.panel_rect = pygame.Rect(c.SCREEN_WIDTH//2 - 200, c.SCREEN_HEIGHT//2 - 190, 400, 380)
        self.refresh_ui()

    def refresh_ui(self):
        self.elements = [Button(50, c.TOP_BAR_UI_CENTER_Y, "small", "red", "Cancel", self.exit_screen)]
        
        confirm_text = "Update Offer" if self.is_editing else "Send Proposal"
        self.elements.append(Button(self.panel_rect.centerx - 150, self.panel_rect.bottom - 70, "new_game", "green", confirm_text, self.confirm))
        
        for i, term in enumerate(self.terms):
            is_enabled = self.terms_enabled[i]
            if is_enabled:
                color = "green" if self.selected_term_idx == i else "blue"
            else:
                color = "grey"
                
            btn = Button(self.panel_rect.centerx - 150, self.panel_rect.y + 60 + (i * 55), "new_game", color, term, lambda idx=i: self.select_term(idx))
            if not is_enabled:
                btn.disabled = True
            self.elements.append(btn)

    def select_term(self, idx):
        if self.terms_enabled[idx]:
            self.selected_term_idx = idx
            self.refresh_ui()

    def confirm(self):
        term = self.terms[self.selected_term_idx]
        
        if term == "Don't offer peace":
            pending = self.map_screen.nation_data[self.map_screen.player_country].get("pending_diplomacy", {})
            if self.target_nation in pending and pending[self.target_nation].get("action") in ["PEACE_TREATY", "CEASEFIRE"]:
                del pending[self.target_nation]
            self.map_screen.show_feedback("Peace Offer Cancelled.")
            self.done = True
        else:
            action_type = "CEASEFIRE" if term == getattr(c, 'PEACE_WHITE_PEACE', "Ceasefire (White Peace)") else "PEACE_TREATY"
            
            # Overwrite directly to bypass toggle
            pending = self.map_screen.nation_data[self.map_screen.player_country].setdefault("pending_diplomacy", {})
            pending[self.target_nation] = {
                "action": action_type,
                "turns": 0,
                "timer": 0,
                "message": term
            }
            self.map_screen.show_feedback("Peace Offer Updated!" if self.is_editing else "Peace Offer Queued!")
            self.done = True

    def exit_screen(self):
        self.done = True

    def handle_events(self, events):
        for event in events:
            for el in self.elements:
                el.handle_event(event)

    def draw(self, surface):
        # FIX: Wipe the frame clean to prevent the "Solitaire Effect" smearing through the transparent oceans
        surface.fill(self.map_screen.bg_color)
        
        temp_prov = self.map_screen.selected_province
        self.map_screen.selected_province = None
        self.map_screen.hide_raised_rect = True

        self.map_screen.hide_tooltip = True
        self.map_screen.hide_resource_hud = True
        self.map_screen.hide_minimap = True
        
        self.map_screen.additional_draw(surface)
        
        self.map_screen.hide_raised_rect = False
        self.map_screen.hide_tooltip = False
        self.map_screen.hide_resource_hud = False
        self.map_screen.hide_minimap = False
        self.map_screen.selected_province = temp_prov

        overlay = pygame.Surface((c.SCREEN_WIDTH, c.SCREEN_HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 180))
        surface.blit(overlay, (0, 0))

        pygame.draw.rect(surface, (30, 40, 30), self.panel_rect)
        pygame.draw.rect(surface, (50, 255, 50), self.panel_rect, 3)

        font = fonts.get("heading1")
        title = font.render(f"Peace Terms: {self.target_nation}", True, (255, 255, 255))
        surface.blit(title, (self.panel_rect.centerx - title.get_width()//2, self.panel_rect.y + 20))

        # Draw UI elements manually to prevent super().draw() from filling the screen with a solid background color
        for el in self.elements:
            if getattr(el, 'visible', True):
                el.draw(surface)

# ==========================================
# PUBLIC INTERCEPT LAUNCHERS
# ==========================================

def open_wargoal_selection_menu(map_screen, target_nation):
    screen = Declare_War_Screen(map_screen, target_nation)
    _run_pygame_sub_screen(map_screen, screen)

def open_justify_menu(map_screen, target_nation):
    screen = Justify_Screen(map_screen, target_nation)
    _run_pygame_sub_screen(map_screen, screen)

def open_peace_menu(map_screen, target_nation):
    screen = Peace_Screen(map_screen, target_nation)
    _run_pygame_sub_screen(map_screen, screen)
