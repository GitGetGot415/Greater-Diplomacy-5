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
        
        has_wg = queries.has_wargoal(map_screen.player_country, target_nation, map_screen.nation_data, map_screen.map_data)
        
        # Safely parse the setting in case it was saved as a string in the JSON
        raw_cb_setting = map_screen.scenario_settings.get("casus_belli_required", getattr(c, 'CASUS_BELLI_REQUIRED', True))
        cb_required = False if str(raw_cb_setting).lower() == "false" else bool(raw_cb_setting)

        # Spectator / Override catch: if it's the spectator, let them force it anyway
        if map_screen.player_country == "Spectator":
            has_wg = True
            cb_required = False

        self.wargoal_options = [
            {"label": getattr(c, 'WARGOAL_TAKE_CLAIMS', "Take Claims"), "enabled": has_wg},
            {"label": getattr(c, 'WARGOAL_NO_CB', "No Casus Belli"), "enabled": not cb_required},
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
# CLAIMS SCREEN
# ==========================================

class Claims_Screen(GameState):
    def __init__(self, map_screen):
        super().__init__()
        self.map_screen = map_screen
        self.player = map_screen.player_country
        self.panel_rect = pygame.Rect(80, 120, 380, c.SCREEN_HEIGHT - 240)
        self.refresh_ui()

    def refresh_ui(self):
        self.elements = [Button(50, c.TOP_BAR_UI_CENTER_Y, "small", "red", "Back", self.exit_screen)]
        
    def exit_screen(self):
        self.done = True

    def handle_events(self, events):
        for event in events:
            for el in self.elements:
                el.handle_event(event)

            on_ui = self.panel_rect.collidepoint(pygame.mouse.get_pos()) or self.map_screen.top_bar_rect.collidepoint(pygame.mouse.get_pos())
            
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if not on_ui:
                    dest = self.get_clicked_province(event.pos)
                    if dest and dest.get("owner") != self.player and dest.get("owner") not in c.UNPLAYABLE_NATIONS:
                        self.toggle_claim(dest)
                        
            elif event.type in (pygame.MOUSEWHEEL, pygame.MOUSEMOTION):
                self.map_screen.camera.handle_input(event, self.map_screen, on_ui)

    def get_clicked_province(self, mouse_pos):
        cam = self.map_screen.camera
        mx, my = mouse_pos
        wx = ((mx / cam.zoom) + cam.pos.x) % self.map_screen.map_w
        wy = ((my - self.map_screen.top_ui_height) / (cam.zoom * getattr(cam, 'tilt_factor', 1.0))) + cam.pos.y
        if 0 <= wy < self.map_screen.map_h:
            color = self.map_screen.id_map.get_at((int(wx), int(wy)))
            return self.map_screen.map_data.get((color.r, color.g, color.b))
        return None

    def toggle_claim(self, dest):
        pid = dest["id"]
        data = self.map_screen.nation_data.get(self.player)
        if not data: return
        
        claims = data.setdefault("claims", [])
        queue = data.setdefault("claim_queue", [])
        revoke_queue = data.setdefault("revoke_queue", [])
        
        # Check if it's currently being revoked
        for i, rq in enumerate(revoke_queue):
            if rq["prov_id"] == pid:
                revoke_queue.pop(i)
                self.map_screen.show_feedback("Revoke cancelled. Claim retained.")
                self.refresh_ui()
                return

        # Revoke existing claim (takes 1 turn)
        if pid in claims:
            revoke_queue.append({"prov_id": pid, "turns_left": 1})
            self.map_screen.show_feedback("Revoking claim (1 turn).")
            self.refresh_ui()
            return
        
        # Cancel claim in progress
        for i, q in enumerate(queue):
            if q["prov_id"] == pid:
                queue.pop(i)
                self.map_screen.show_feedback("Claim removed from queue.")
                self.refresh_ui()
                return
        
        # Begin fabricating a new claim
        is_core = self.player in dest.get("cores", [])
        turns = getattr(c, 'CLAIM_TURN_CORE', 1) if is_core else getattr(c, 'CLAIM_TURN_NON_CORE', 2)
        queue.append({"prov_id": pid, "turns_left": turns})
        self.map_screen.show_feedback(f"Claim queued ({turns} turns).")
        self.refresh_ui()

    def update(self):
        super().update()
        self.map_screen.camera.update(self.map_screen, c.SCREEN_HEIGHT)

    def draw(self, surface):
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

        # Draw territorial highlights
        data = self.map_screen.nation_data.get(self.player, {})
        claims = data.get("claims", [])
        queue = data.get("claim_queue", [])
        revoke_queue = data.get("revoke_queue", [])
        
        revoke_ids = [rq["prov_id"] for rq in revoke_queue]
        
        for pid in claims:
            if pid in revoke_ids:
                self.draw_highlight(surface, pid, (255, 50, 50)) # Red (Revoking)
            else:
                self.draw_highlight(surface, pid, (255, 215, 0)) # Gold (Claimed)
            
        for i, q in enumerate(queue):
            if i == 0:
                self.draw_highlight(surface, q["prov_id"], (0, 255, 0)) # Green (Actively Justifying)
            else:
                self.draw_highlight(surface, q["prov_id"], (0, 150, 255)) # Blue (Waiting in Queue)
            
        # Draw Information Panel
        panel_surf = pygame.Surface((self.panel_rect.width, self.panel_rect.height), pygame.SRCALPHA)
        panel_surf.fill((30, 30, 50, 230))
        surface.blit(panel_surf, self.panel_rect.topleft)
        pygame.draw.rect(surface, (100, 150, 255), self.panel_rect, 2)

        font = fonts.get("heading1")
        sub_font = fonts.get("heading2")
        tiny_font = fonts.get("normal")

        title = font.render("Territory Claims", True, (255, 255, 255))
        surface.blit(title, (self.panel_rect.centerx - title.get_width()//2, self.panel_rect.y + 20))
        
        y_off = self.panel_rect.y + 70
        surface.blit(sub_font.render("Queued Claims:", True, (150, 200, 255)), (self.panel_rect.x + 20, y_off))
        y_off += 30
        
        if not queue:
            surface.blit(tiny_font.render("No claims queued.", True, (150, 150, 150)), (self.panel_rect.x + 30, y_off))
            y_off += 25
        else:
            for q in queue:
                prov = self.map_screen.id_to_province.get(q["prov_id"])
                owner = prov.get("owner", "Unknown") if prov else "Unknown"
                owner_name = self.map_screen.nation_data.get(owner, {}).get("name", owner)
                txt = tiny_font.render(f"- Prov {q['prov_id']} ({owner_name}): {q['turns_left']} turns left", True, (200, 200, 200))
                surface.blit(txt, (self.panel_rect.x + 30, y_off))
                y_off += 25
                
        y_off += 10
        surface.blit(sub_font.render("Active Claims:", True, (255, 215, 0)), (self.panel_rect.x + 20, y_off))
        y_off += 30
        
        if not claims:
            surface.blit(tiny_font.render("No active claims.", True, (150, 150, 150)), (self.panel_rect.x + 30, y_off))
        else:
            display_claims = claims[:15]
            for pid in display_claims:
                prov = self.map_screen.id_to_province.get(pid)
                owner = prov.get("owner", "Unknown") if prov else "Unknown"
                owner_name = self.map_screen.nation_data.get(owner, {}).get("name", owner)
                
                revoke_item = next((r for r in revoke_queue if r["prov_id"] == pid), None)
                if revoke_item:
                    status_text = f" (Revoking in {revoke_item['turns_left']})"
                    color = (255, 100, 100)
                else:
                    status_text = ""
                    color = (200, 200, 200)

                txt = tiny_font.render(f"- Prov {pid} ({owner_name}){status_text}", True, color)
                surface.blit(txt, (self.panel_rect.x + 30, y_off))
                y_off += 25
            if len(claims) > 15:
                txt = tiny_font.render(f"...and {len(claims)-15} more", True, (150, 150, 150))
                surface.blit(txt, (self.panel_rect.x + 30, y_off))

        for el in self.elements:
            if getattr(el, 'visible', True):
                el.draw(surface)

    def draw_highlight(self, surface, pid, color):
        prov = self.map_screen.id_to_province.get(pid)
        if not prov: return
        cx, cy = prov["center"]
        for offset in [0, -self.map_screen.map_w, self.map_screen.map_w]:
            sx = (cx + offset - self.map_screen.camera.pos.x) * self.map_screen.camera.zoom
            sy = (cy - self.map_screen.camera.pos.y) * self.map_screen.camera.zoom * getattr(self.map_screen.camera, 'tilt_factor', 1.0) + self.map_screen.top_ui_height
            if -100 < sx < c.SCREEN_WIDTH + 100:
                radius_x = max(2, int(4 * self.map_screen.camera.zoom))
                radius_y = int(radius_x * getattr(self.map_screen.camera, 'tilt_factor', 1.0)) if getattr(c, 'APPLY_TILT_TO_OVERLAYS', False) else radius_x
                pygame.draw.ellipse(surface, color, pygame.Rect(int(sx) - radius_x, int(sy) - radius_y, radius_x*2, radius_y*2), max(2, int(2*self.map_screen.camera.zoom)))

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

def open_claims_menu(map_screen):
    screen = Claims_Screen(map_screen)
    _run_pygame_sub_screen(map_screen, screen)

def open_peace_menu(map_screen, target_nation):
    screen = Peace_Screen(map_screen, target_nation)
    _run_pygame_sub_screen(map_screen, screen)