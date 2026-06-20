import pygame
import data.constants as c
from data import queries
from map_logic.diplomacy import diplomacy_logic
from gameState import GameState
from ui_elements import Button, Slider
from map_logic.rendering.font_manager import fonts
from map_logic.rendering import overlay_renderer

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
        
        clock.tick(c.TARGET_FPS)
        
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
        raw_cb_setting = map_screen.scenario_settings.get("casus_belli_required", c.CASUS_BELLI_REQUIRED)
        cb_required = False if str(raw_cb_setting).lower() == "false" else bool(raw_cb_setting)

        # Spectator / Override catch: if it's the spectator, let them force it anyway
        if map_screen.player_country == "Spectator":
            has_wg = True
            cb_required = False
            
        my_master = map_screen.nation_data.get(map_screen.player_country, {}).get("master", "")
        their_master = map_screen.nation_data.get(target_nation, {}).get("master", "")
        
        is_independence = (my_master == target_nation)
        is_preemptive = (their_master == map_screen.player_country)
        
        if is_independence:
            puppet_cb_label = c.WARGOAL_INDEPENDENCE
            puppet_cb_enabled = True
        elif is_preemptive:
            puppet_cb_label = c.WARGOAL_PREEMPTIVE
            puppet_cb_enabled = True
        else:
            puppet_cb_label = c.WARGOAL_INDEPENDENCE
            puppet_cb_enabled = False

        self.wargoal_options = [
            {"label": c.WARGOAL_TAKE_CLAIMS, "enabled": has_wg},
            {"label": puppet_cb_label, "enabled": puppet_cb_enabled},
            {"label": c.WARGOAL_NO_CB, "enabled": not cb_required},
            {"label": "Don't Declare War", "enabled": True}
        ]
            
        self.selected_wargoal_idx = 3 # Default to Don't Declare War
        
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
                if opt["enabled"] and i != 3:
                    self.selected_wargoal_idx = i
                    break

        # Widen the panel to fit buttons side-by-side
        self.panel_rect = pygame.Rect(c.SCREEN_WIDTH//2 - 250, c.SCREEN_HEIGHT//2 - 160, 500, 320)
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
                
            # Place the first two buttons left and right, and the 3rd/4th centered below
            if i == 0:
                btn_x = self.panel_rect.centerx - 210
                btn_y = self.panel_rect.y + 80
                btn_size = "medium"
            elif i == 1:
                btn_x = self.panel_rect.centerx + 10
                btn_y = self.panel_rect.y + 80
                btn_size = "medium"
            elif i == 2:
                btn_x = self.panel_rect.centerx - 210
                btn_y = self.panel_rect.y + 150
                btn_size = "medium"
            else:
                btn_x = self.panel_rect.centerx + 10
                btn_y = self.panel_rect.y + 150
                btn_size = "medium"

            btn = Button(btn_x, btn_y, btn_size, color, opt["label"], lambda idx=i: self.select_wg(idx))
            if not opt["enabled"]:
                btn.disabled = True
                
            # Add the gold/yellow highlight outline
            if self.selected_wargoal_idx == i:
                btn.is_selected = True
                
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

    def additional_draw(self, surface):
        # Wipe the frame clean to prevent the "Solitaire Effect" smearing through the transparent oceans
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
            if el.visible:
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
        
        self.scroll_y = 0
        self.max_scroll = 0
        
        # Determine if we have global viewing privileges
        self.is_global_viewer = map_screen.is_editor or self.player in ["Spectator", "None"]
        self.view_mode = "GLOBAL" if self.is_global_viewer else "YOURS"
        
        self.refresh_ui()

    def set_view_mode(self, mode):
        self.view_mode = mode
        self.scroll_y = 0
        self.refresh_ui()

    def refresh_ui(self):
        self.elements = [Button(50, c.TOP_BAR_UI_CENTER_Y, "small", "red", "Back", self.exit_screen)]
        
        if self.is_global_viewer:
            btn_global = Button(self.panel_rect.x + 20, self.panel_rect.y + 40, "medium", "blue" if self.view_mode == "GLOBAL" else "grey", "Global Claims", lambda: self.set_view_mode("GLOBAL"))
            btn_global.is_selected = (self.view_mode == "GLOBAL")
            self.elements.append(btn_global)
        else:
            btn_yours = Button(self.panel_rect.x + 20, self.panel_rect.y + 40, "medium", "blue" if self.view_mode == "YOURS" else "grey", "Your Claims", lambda: self.set_view_mode("YOURS"))
            btn_theirs = Button(self.panel_rect.x + 200, self.panel_rect.y + 40, "medium", "blue" if self.view_mode == "THEIRS" else "grey", "Claims On You", lambda: self.set_view_mode("THEIRS"))
            btn_yours.is_selected = (self.view_mode == "YOURS")
            btn_theirs.is_selected = (self.view_mode == "THEIRS")
            self.elements.extend([btn_yours, btn_theirs])
        
    def exit_screen(self):
        self.done = True

    def handle_events(self, events):
        for event in events:
            for el in self.elements:
                el.handle_event(event)

            on_ui = self.panel_rect.collidepoint(pygame.mouse.get_pos()) or self.map_screen.top_bar_rect.collidepoint(pygame.mouse.get_pos())
            
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if not on_ui:
                    if getattr(self.map_screen, 'tactical_mode', False):
                        self.map_screen.show_feedback("Tactical Mode: Cannot modify claims.")
                        continue
                        
                    dest = self.get_clicked_province(event.pos)
                    if dest and dest.get("owner") not in c.UNPLAYABLE_NATIONS:
                        if self.view_mode == "YOURS":
                            if dest.get("owner") != self.player:
                                self.toggle_claim(dest)
                        elif self.view_mode == "THEIRS":
                            if dest.get("owner") == self.player:
                                self.return_foreign_claim(dest)
                    else:
                        self.map_screen.show_feedback("Can only edit claims on valid nations.")
                        
            elif event.type == pygame.MOUSEWHEEL:
                if on_ui:
                    self.scroll_y += event.y * 30
                    self.scroll_y = max(self.max_scroll, min(0, self.scroll_y))
                else:
                    self.map_screen.camera.handle_input(event, self.map_screen, on_ui)
                    
            elif event.type == pygame.MOUSEMOTION:
                self.map_screen.camera.handle_input(event, self.map_screen, on_ui)

    def get_clicked_province(self, mouse_pos):
        cam = self.map_screen.camera
        mx, my = mouse_pos
        wx = ((mx / cam.zoom) + cam.pos.x) % self.map_screen.map_w
        wy = ((my - self.map_screen.top_ui_height) / (cam.zoom * cam.tilt_factor)) + cam.pos.y
        if 0 <= wy < self.map_screen.map_h:
            color = self.map_screen.id_map.get_at((int(wx), int(wy)))
            return self.map_screen.map_data.get((color.r, color.g, color.b))
        return None

    def toggle_claim(self, dest):
        pid = dest["id"]
        data = self.map_screen.nation_data.get(self.player)
        if not data: return
        
        is_core = self.player in dest.get("cores", [])
        
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

        # Revoke existing claim or core (takes 1 turn)
        if pid in claims or is_core:
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
        
        # Begin fabricating a new claim (Cores are instant, so queued claims are always non-cores)
        turns = c.CLAIM_TURN_NON_CORE
        queue.append({"prov_id": pid, "turns_left": turns})
        self.map_screen.show_feedback(f"Claim queued ({turns} turns).")
        self.refresh_ui()

    def return_foreign_claim(self, dest):
        """Allows returning territory to foreign nations that hold a core or claim on it."""
        pid = dest["id"]
        data = self.map_screen.nation_data.get(self.player)
        if not data: return

        # Find valid recipients who have a claim or core on this tile
        valid_recipients = []
        for n_name, n_data in self.map_screen.nation_data.items():
            if n_name == self.player or n_name in c.UNPLAYABLE_NATIONS: 
                continue
            
            is_core = n_name in dest.get("cores", [])
            has_claim = pid in n_data.get("claims", [])
            
            if is_core or has_claim:
                # Prioritize cores by placing them at the front of the list
                if is_core:
                    valid_recipients.insert(0, n_name)
                else:
                    valid_recipients.append(n_name)

        if not valid_recipients:
            self.map_screen.show_feedback("No foreign nation has a valid claim on this territory.")
            return

        # Give it to the most valid claimant (Prioritizes Cores, then Claims)
        recipient = valid_recipients[0]

        # Start the return process taking 1 turn. (Stored under the player's data to process)
        return_queue = data.setdefault("return_queue", [])
        
        # Check if it's currently being returned, if so, cancel it
        for i, rq in enumerate(return_queue):
            if rq["prov_id"] == pid:
                return_queue.pop(i)
                self.map_screen.show_feedback("Return cancelled. Territory retained.")
                self.refresh_ui()
                return
                
        return_queue.append({"prov_id": pid, "recipient": recipient, "turns_left": 1})
        self.map_screen.show_feedback(f"Returning territory to {recipient} (1 turn).")
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
        return_queue = data.get("return_queue", [])
        
        revoke_ids = [rq["prov_id"] for rq in revoke_queue]
        return_ids = [rq["prov_id"] for rq in return_queue]
        
        # Identify foreign cores for the distinct pink rendering
        core_ids = [prov["id"] for prov in self.map_screen.map_data.values() 
                    if self.player in prov.get("cores", []) 
                    and prov.get("owner") != self.player 
                    and prov.get("owner") not in c.UNPLAYABLE_NATIONS]
                    
        foreign_claims_list = []
        foreign_claims_map = {}
        for n, d in self.map_screen.nation_data.items():
            if n == self.player or n in c.UNPLAYABLE_NATIONS: continue
            
            for pid in d.get("claims", []):
                prov = self.map_screen.id_to_province.get(pid)
                if prov and prov.get("owner") == self.player:
                    info = {"nation": n, "type": "CLAIM", "turns": 0, "prov_id": pid}
                    foreign_claims_list.append(info)
                    foreign_claims_map.setdefault(pid, []).append(info)
                    
            for prov in self.map_screen.map_data.values():
                if prov.get("owner") == self.player and n in prov.get("cores", []) and prov["id"] not in d.get("claims", []):
                    info = {"nation": n, "type": "CORE", "turns": 0, "prov_id": prov["id"]}
                    foreign_claims_list.append(info)
                    foreign_claims_map.setdefault(prov["id"], []).append(info)
                    
            for q in d.get("claim_queue", []):
                if q.get("turns_left", 0) < c.CLAIM_TURN_NON_CORE: # Don't show if made this turn
                    pid = q["prov_id"]
                    prov = self.map_screen.id_to_province.get(pid)
                    if prov and prov.get("owner") == self.player:
                        info = {"nation": n, "type": "QUEUE", "turns": q["turns_left"], "prov_id": pid}
                        foreign_claims_list.append(info)
                        foreign_claims_map.setdefault(pid, []).append(info)
        
        foreign_claims_list.sort(key=lambda x: (x["prov_id"], x["nation"]))
        
        global_claims_list = []
        if self.view_mode == "GLOBAL":
            for n, d in self.map_screen.nation_data.items():
                if n in c.UNPLAYABLE_NATIONS and n != "None": continue
                for pid in d.get("claims", []):
                    global_claims_list.append({"nation": n, "prov_id": pid})
            global_claims_list.sort(key=lambda x: (x["nation"], x["prov_id"]))
            
            for item in global_claims_list:
                color = self.map_screen.nation_colors.get(item["nation"], (255, 255, 255))
                overlay_renderer.draw_map_highlight(surface, self.map_screen, item["prov_id"], color, base_radius=4)

        elif self.view_mode == "YOURS":
            for pid in core_ids:
                overlay_renderer.draw_map_highlight(surface, self.map_screen, pid, (255, 105, 180), base_radius=4)
            
            for pid in claims:
                if pid in revoke_ids:
                    overlay_renderer.draw_map_highlight(surface, self.map_screen, pid, (255, 50, 50), base_radius=4)
                else:
                    overlay_renderer.draw_map_highlight(surface, self.map_screen, pid, (255, 215, 0), base_radius=4)
                
            for i, q in enumerate(queue):
                if i == 0:
                    overlay_renderer.draw_map_highlight(surface, self.map_screen, q["prov_id"], (0, 255, 0), base_radius=4)
                else:
                    overlay_renderer.draw_map_highlight(surface, self.map_screen, q["prov_id"], (0, 150, 255), base_radius=4)
        else:
            for pid, claims_on_tile in foreign_claims_map.items():
                for i, claim_info in enumerate(claims_on_tile):
                    color = self.map_screen.nation_colors.get(claim_info["nation"], (255, 255, 255))
                    is_just = (claim_info["type"] == "QUEUE")
                    
                    if pid in return_ids:
                        color = (100, 255, 100) # Green highlight for returning tiles
                        
                    overlay_renderer.draw_map_highlight(surface, self.map_screen, pid, color, base_radius=4, inset=i, is_justifying=is_just)
        
        # Draw Information Panel
        panel_surf = pygame.Surface((self.panel_rect.width, self.panel_rect.height), pygame.SRCALPHA)
        panel_surf.fill((30, 30, 50, 230))
        surface.blit(panel_surf, self.panel_rect.topleft)
        pygame.draw.rect(surface, (100, 150, 255), self.panel_rect, 2)

        font = fonts.get("heading1")
        sub_font = fonts.get("heading2")
        tiny_font = fonts.get("normal")

        title = font.render("Territory Claims", True, (255, 255, 255))
        surface.blit(title, (self.panel_rect.centerx - title.get_width()//2, self.panel_rect.y + 10))
        
        display_claims = claims + [c_id for c_id in core_ids if c_id not in claims]
        
        if self.view_mode == "GLOBAL":
            content_h = 40 + (len(global_claims_list) * 25 if global_claims_list else 25)
        elif self.view_mode == "YOURS":
            content_h = 40 + (len(queue) * 25 if queue else 25) + 40 + (len(display_claims) * 25 if display_claims else 25)
        else:
            content_h = 40 + (len(foreign_claims_list) * 25 if foreign_claims_list else 25)
            
        viewport_h = self.panel_rect.height - 95
        self.max_scroll = min(0, viewport_h - content_h - 20)
        self.scroll_y = max(self.max_scroll, min(0, self.scroll_y))
        
        clip_rect = pygame.Rect(self.panel_rect.x + 5, self.panel_rect.y + 90, self.panel_rect.width - 10, viewport_h)
        old_clip = surface.get_clip()
        surface.set_clip(clip_rect)
        
        y_off = self.panel_rect.y + 100 + self.scroll_y
        
        if self.view_mode == "GLOBAL":
            surface.blit(sub_font.render("All Map Claims:", True, (255, 215, 0)), (self.panel_rect.x + 20, y_off))
            y_off += 30
            
            if not global_claims_list:
                surface.blit(tiny_font.render("No claims on the map.", True, (150, 150, 150)), (self.panel_rect.x + 30, y_off))
            else:
                for item in global_claims_list:
                    nation_name = self.map_screen.nation_data.get(item["nation"], {}).get("name", item["nation"])
                    color = self.map_screen.nation_colors.get(item["nation"], (255, 255, 255))
                    
                    txt = tiny_font.render(f"- Prov {item['prov_id']} ({nation_name})", True, color)
                    surface.blit(txt, (self.panel_rect.x + 30, y_off))
                    y_off += 25

        elif self.view_mode == "YOURS":
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
            
            if not display_claims:
                surface.blit(tiny_font.render("No active claims.", True, (150, 150, 150)), (self.panel_rect.x + 30, y_off))
            else:
                for pid in display_claims:
                    prov = self.map_screen.id_to_province.get(pid)
                    owner = prov.get("owner", "Unknown") if prov else "Unknown"
                    owner_name = self.map_screen.nation_data.get(owner, {}).get("name", owner)
                    
                    is_core = pid in core_ids
                    revoke_item = next((r for r in revoke_queue if r["prov_id"] == pid), None)
                    
                    if revoke_item:
                        status_text = f" (Revoking in {revoke_item['turns_left']})"
                        color = (255, 100, 100)
                    elif is_core:
                        status_text = " (Auto-Claimed Core)"
                        color = (255, 150, 200)
                    else:
                        status_text = ""
                        color = (200, 200, 200)

                    txt = tiny_font.render(f"- Prov {pid} ({owner_name}){status_text}", True, color)
                    surface.blit(txt, (self.panel_rect.x + 30, y_off))
                    y_off += 25
        else:
            surface.blit(sub_font.render("Claims on You:", True, (255, 100, 100)), (self.panel_rect.x + 20, y_off))
            y_off += 30
            
            if not foreign_claims_list:
                surface.blit(tiny_font.render("No foreign claims on your territory.", True, (150, 150, 150)), (self.panel_rect.x + 30, y_off))
            else:
                for item in foreign_claims_list:
                    nation_name = self.map_screen.nation_data.get(item["nation"], {}).get("name", item["nation"])
                    color = self.map_screen.nation_colors.get(item["nation"], (255, 255, 255))
                    
                    if item["type"] == "QUEUE":
                        txt_str = f"- Prov {item['prov_id']} ({nation_name}): Actively Justifying ({item['turns']}t)"
                    elif item["type"] == "CORE":
                        txt_str = f"- Prov {item['prov_id']} ({nation_name}): Auto-Claimed Core"
                    else:
                        txt_str = f"- Prov {item['prov_id']} ({nation_name}): Active Claim"
                        
                    if item["prov_id"] in return_ids:
                        txt_str += f" (Returning in 1 turn)"
                        color = (100, 255, 100)
                        
                    txt = tiny_font.render(txt_str, True, color)
                    surface.blit(txt, (self.panel_rect.x + 30, y_off))
                    y_off += 25
                    
        surface.set_clip(old_clip)

        # Draw a custom scrollbar if the content exceeds the box height
        if self.max_scroll < 0:
            track_rect = pygame.Rect(self.panel_rect.right - 15, self.panel_rect.y + 90, 10, viewport_h)
            pygame.draw.rect(surface, (50, 50, 70), track_rect)
            
            ratio = self.scroll_y / self.max_scroll
            handle_h = max(20, viewport_h * (viewport_h / (viewport_h - self.max_scroll)))
            handle_y = track_rect.y + ratio * (track_rect.height - handle_h)
            
            pygame.draw.rect(surface, (150, 150, 150), pygame.Rect(track_rect.x, handle_y, 10, handle_h), border_radius=5)

        for el in self.elements:
            if el.visible:
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
            c.PEACE_SURRENDER,
            c.PEACE_DEMAND_CLAIMS,
            c.PEACE_WHITE_PEACE
        ]
        
        self.terms_enabled = [
            True, # Surrender is always an option if at war
            my_wargoal in [c.WARGOAL_TAKE_CLAIMS, c.WARGOAL_NO_CB] or their_wargoal != "", # Allowed if we claimed, No CB, or if it's a defensive war!
            True
        ]
        
        # Check for existing peace offer
        pending = map_screen.nation_data.get(map_screen.player_country, {}).get("pending_diplomacy", {}).get(target_nation, {})
        self.is_editing = isinstance(pending, dict) and pending.get("action") in ["PEACE_TREATY", "CEASEFIRE"]
        
        if self.is_editing:
            pending_msg = pending.get("message", "")
            self.selected_term_idx = 2 # Default to Ceasefire
            for i, term in enumerate(self.terms):
                if pending_msg.startswith(term) and self.terms_enabled[i]:
                    self.selected_term_idx = i
                    break
            
            # Catch raw CEASEFIRE actions from legacy behavior
            if pending.get("action") == "CEASEFIRE":
                self.selected_term_idx = 2
        else:
            self.selected_term_idx = 2 # Default to Ceasefire
            
        # Restructured to be a wide, short banner docked cleanly above the bottom UI bar
        self.panel_rect = pygame.Rect(c.SCREEN_WIDTH//2 - 350, c.SCREEN_HEIGHT - 250, 700, 190)
        self.refresh_ui()

    def refresh_ui(self):
        self.elements = [Button(50, c.TOP_BAR_UI_CENTER_Y, "small", "red", "Cancel", self.exit_screen)]
        
        term = self.terms[self.selected_term_idx]
        is_human = self.target_nation in getattr(self.map_screen, 'active_players', [])
        
        if is_human:
            self.acceptance_text = "This is another player, whether they accept this deal or not is up to them."
            self.acceptance_color = (200, 200, 200)
        else:
            will_accept = queries.will_ai_accept_peace(self.target_nation, self.map_screen.player_country, term, self.map_screen.map_data, self.map_screen.nation_data)
            if will_accept:
                self.acceptance_text = "The AI will accept this peace deal."
                self.acceptance_color = (100, 255, 100)
            else:
                self.acceptance_text = "The AI will REJECT this peace deal."
                self.acceptance_color = (255, 100, 100)

        for i, term_str in enumerate(self.terms):
            is_enabled = self.terms_enabled[i]
            if is_enabled:
                color = "green" if self.selected_term_idx == i else "blue"
            else:
                color = "grey"
                
            # Place the 3 main terms left-to-right
            btn_x = self.panel_rect.centerx - 330 + (i * 220)
            btn_y = self.panel_rect.y + 80
            
            btn = Button(btn_x, btn_y, "medium", color, term_str, lambda idx=i: self.select_term(idx))
            if not is_enabled:
                btn.disabled = True
                
            # Add the gold/yellow highlight outline
            if self.selected_term_idx == i:
                btn.is_selected = True
                
            self.elements.append(btn)

        confirm_text = "Update Offer" if self.is_editing else "Send Proposal"
        self.elements.append(Button(self.panel_rect.centerx - 100, self.panel_rect.y + 140, "medium", "green", confirm_text, self.confirm))
        
        if self.is_editing:
            self.elements.append(Button(self.panel_rect.right - 140, self.panel_rect.y + 140, "small", "red", "Cancel Offer", self.revoke_offer))

    def select_term(self, idx):
        if self.terms_enabled[idx]:
            self.selected_term_idx = idx
            self.refresh_ui()

    def revoke_offer(self):
        pending = self.map_screen.nation_data[self.map_screen.player_country].get("pending_diplomacy", {})
        if self.target_nation in pending and pending[self.target_nation].get("action") in ["PEACE_TREATY", "CEASEFIRE"]:
            del pending[self.target_nation]
        self.map_screen.show_feedback("Peace Offer Cancelled.")
        self.done = True

    def confirm(self):
        term = self.terms[self.selected_term_idx]
        action_type = "CEASEFIRE" if term == c.PEACE_WHITE_PEACE else "PEACE_TREATY"
        
        proposer = self.map_screen.player_country
        target = self.target_nation
        
        # Calculate and freeze territories into the message string
        frozen_ids = []
        if term == c.PEACE_DEMAND_CLAIMS:
            claims = self.map_screen.nation_data.get(proposer, {}).get("claims", [])
            for prov in self.map_screen.map_data.values():
                if prov.get("owner") == target and (prov["id"] in claims or proposer in prov.get("cores", [])):
                    frozen_ids.append(str(prov["id"]))
            if frozen_ids:
                term += f" (Territories demanded: {', '.join(frozen_ids)} + cores)"
            else:
                term += " (No territories demanded)"
                
        elif term == c.PEACE_SURRENDER:
            claims = self.map_screen.nation_data.get(target, {}).get("claims", [])
            for prov in self.map_screen.map_data.values():
                if prov.get("owner") == proposer and (prov["id"] in claims or target in prov.get("cores", [])):
                    frozen_ids.append(str(prov["id"]))
            if frozen_ids:
                term += f" (Territories surrendered: {', '.join(frozen_ids)} + cores)"
            else:
                term += " (No territories surrendered)"
        
        # Overwrite directly to bypass toggle
        pending = self.map_screen.nation_data[self.map_screen.player_country].setdefault("pending_diplomacy", {})
        pending[self.target_nation] = {
            "action": action_type,
            "turns": 0,
            "timer": 0,
            "parameters": term,
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
                
            on_ui = self.panel_rect.collidepoint(pygame.mouse.get_pos()) or self.map_screen.top_bar_rect.collidepoint(pygame.mouse.get_pos())
            if event.type in (pygame.MOUSEWHEEL, pygame.MOUSEMOTION):
                self.map_screen.camera.handle_input(event, self.map_screen, on_ui)

    def update(self):
        super().update()
        self.map_screen.camera.update(self.map_screen, c.SCREEN_HEIGHT)

    def get_projected_owner(self, prov, peace_type):
        """Simulates the execution of the peace treaty to find who gets what."""
        curr = prov.get("owner")
        proj = curr
        proposer = self.map_screen.player_country
        target = self.target_nation

        if peace_type == c.PEACE_WHITE_PEACE:
            pass # A ceasefire freezes the map exactly as it is right now.
        elif peace_type == c.PEACE_DEMAND_CLAIMS:
            claims = self.map_screen.nation_data.get(proposer, {}).get("claims", [])
            # Proposer gets their claims/cores that the target currently owns
            if curr == target and (prov["id"] in claims or proposer in prov.get("cores", [])):
                proj = proposer
        elif peace_type == c.PEACE_SURRENDER:
            claims = self.map_screen.nation_data.get(target, {}).get("claims", [])
            # Target gets their claims/cores that the proposer currently owns
            if curr == proposer and (prov["id"] in claims or target in prov.get("cores", [])):
                proj = target
        return proj

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

        # --- DRAW MAP PREVIEW HIGHLIGHTS ---
        peace_type = self.terms[self.selected_term_idx]
        proposer = self.map_screen.player_country
        target = self.target_nation
        p_color = self.map_screen.nation_colors.get(proposer, (0, 255, 0))
        t_color = self.map_screen.nation_colors.get(target, (255, 0, 0))
        
        for prov in self.map_screen.map_data.values():
            curr = prov.get("owner")
            if curr in [proposer, target]:
                # Use the centralized query
                proj = queries.get_projected_owner(prov, peace_type, proposer, target, self.map_screen.nation_data)
                if proj != curr:
                    if proj == proposer:
                        overlay_renderer.draw_map_highlight(surface, self.map_screen, prov["id"], p_color, base_radius=10)
                    elif proj == target:
                        overlay_renderer.draw_map_highlight(surface, self.map_screen, prov["id"], t_color, base_radius=10)

        # Draw the Banner
        panel_surf = pygame.Surface((self.panel_rect.width, self.panel_rect.height), pygame.SRCALPHA)
        panel_surf.fill((30, 40, 30, 230))
        surface.blit(panel_surf, self.panel_rect.topleft)
        pygame.draw.rect(surface, (50, 255, 50), self.panel_rect, 3)

        font = fonts.get("heading1")
        small_font = fonts.get("normal")
        title = font.render(f"Peace Terms: {self.target_nation}", True, (255, 255, 255))
        surface.blit(title, (self.panel_rect.centerx - title.get_width()//2, self.panel_rect.y + 15))

        acc_surf = small_font.render(self.acceptance_text, True, self.acceptance_color)
        surface.blit(acc_surf, (self.panel_rect.centerx - acc_surf.get_width()//2, self.panel_rect.y + 50))

        for el in self.elements:
            if el.visible:
                el.draw(surface)

# ==========================================
# VIEW PEACE TREATY SCREEN
# ==========================================

class View_Peace_Treaty_Screen(GameState):
    def __init__(self, map_screen, proposer):
        super().__init__()
        self.map_screen = map_screen
        self.proposer = proposer
        self.target = map_screen.player_country
        
        # Read the parameters directly from the proposed diplomacy message
        pending = map_screen.nation_data.get(self.proposer, {}).get("pending_diplomacy", {}).get(self.target, {})
        self.peace_type = pending.get("parameters", pending.get("message", c.PEACE_WHITE_PEACE))
        
        self.elements = [Button(50, c.TOP_BAR_UI_CENTER_Y, "small", "red", "Back", self.exit_screen)]
        
    def exit_screen(self):
        self.done = True

    def handle_events(self, events):
        for event in events:
            for el in self.elements:
                el.handle_event(event)
            
            on_ui = self.map_screen.top_bar_rect.collidepoint(pygame.mouse.get_pos())
            if event.type in (pygame.MOUSEWHEEL, pygame.MOUSEMOTION):
                self.map_screen.camera.handle_input(event, self.map_screen, on_ui)

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

        p_color = self.map_screen.nation_colors.get(self.proposer, (0, 255, 0))
        t_color = self.map_screen.nation_colors.get(self.target, (255, 0, 0))
        
        for prov in self.map_screen.map_data.values():
            curr = prov.get("owner")
            if curr in [self.proposer, self.target]:
                # Use the centralized query
                proj = queries.get_projected_owner(prov, self.peace_type, self.proposer, self.target, self.map_screen.nation_data)
                if proj != curr:
                    if proj == self.proposer:
                        overlay_renderer.draw_map_highlight(surface, self.map_screen, prov["id"], p_color, base_radius=10)
                    elif proj == self.target:
                        overlay_renderer.draw_map_highlight(surface, self.map_screen, prov["id"], t_color, base_radius=10)

        font = fonts.get("heading1")
        title = font.render(f"Projected Map: Peace Treaty from {self.proposer}", True, (255, 255, 255))
        bg_rect = title.get_rect(center=(c.SCREEN_WIDTH//2, 30))
        pygame.draw.rect(surface, (0, 0, 0, 180), bg_rect.inflate(20, 10))
        surface.blit(title, bg_rect)
        
        for el in self.elements:
            if el.visible:
                el.draw(surface)

# ==========================================
# TRADE SCREEN
# ==========================================

class Trade_Screen(GameState):
    def __init__(self, map_screen, target_nation):
        super().__init__()
        self.map_screen = map_screen
        self.target_nation = target_nation
        
        self.panel_rect = pygame.Rect(c.SCREEN_WIDTH//2 - 300, c.SCREEN_HEIGHT//2 - 220, 600, 420)
        
        # State tracking for inputs
        self.give_mats_str = "0"
        self.give_fuel_str = "0"
        self.take_mats_str = "0"
        self.take_fuel_str = "0"
        
        self.puppet_state = "NONE" # "SENDER", "NONE", "RECEIVER"
        
        # Escrow trackers (resources removed from the player while the offer is pending)
        self.escrow_mats = 0
        self.escrow_fuel = 0
        
        self.active_input = None
        self.refresh_ui()

    def set_puppet_state(self, state):
        self.puppet_state = state
        self.refresh_ui()

    def refresh_ui(self):
        self.elements = [Button(50, c.TOP_BAR_UI_CENTER_Y, "small", "red", "Cancel", self.cancel_trade)]
        self.elements.append(Button(self.panel_rect.centerx - 100, self.panel_rect.bottom - 60, "medium", "green", "Confirm Trade", self.confirm_trade))
        
        # Puppet Options
        y_pos = self.panel_rect.y + 220
        
        my_master = self.map_screen.nation_data.get(self.map_screen.player_country, {}).get("master", "")
        their_master = self.map_screen.nation_data.get(self.target_nation, {}).get("master", "")
        is_either_puppet = bool(my_master) or bool(their_master)
        
        btn_sender = Button(self.panel_rect.x + 30, y_pos, "medium", "blue" if self.puppet_state != "SENDER" else "green", "Make Them Puppet", lambda: self.set_puppet_state("SENDER"))
        if self.puppet_state == "SENDER": btn_sender.is_selected = True
        
        btn_none = Button(self.panel_rect.centerx - 100, y_pos, "medium", "blue" if self.puppet_state != "NONE" else "green", "No Puppeting", lambda: self.set_puppet_state("NONE"))
        if self.puppet_state == "NONE": btn_none.is_selected = True
        
        btn_recv = Button(self.panel_rect.right - 230, y_pos, "medium", "blue" if self.puppet_state != "RECEIVER" else "green", "Become Their Puppet", lambda: self.set_puppet_state("RECEIVER"))
        if self.puppet_state == "RECEIVER": btn_recv.is_selected = True
        
        if is_either_puppet:
            btn_sender.disabled = True
            btn_sender.color, btn_sender.hover_color = c.UI_COLORS["grey"]
            btn_recv.disabled = True
            btn_recv.color, btn_recv.hover_color = c.UI_COLORS["grey"]
        
        self.elements.extend([btn_sender, btn_none, btn_recv])

    def evaluate_input(self):
        """Processes typed text, applies clamps, and secures/refunds the escrow safely."""
        p_data = self.map_screen.nation_data[self.map_screen.player_country]

        # Give Materials
        try:
            val_mats = int(self.give_mats_str)
            if val_mats < 0: val_mats = 0
        except ValueError:
            val_mats = 0

        p_data["materials"] = p_data.get("materials", 0) + self.escrow_mats
        taken_mats = min(val_mats, p_data["materials"])
        p_data["materials"] -= taken_mats
        self.escrow_mats = taken_mats
        self.give_mats_str = str(taken_mats)

        # Give Fuel
        try:
            val_fuel = int(self.give_fuel_str)
            if val_fuel < 0: val_fuel = 0
        except ValueError:
            val_fuel = 0

        p_data["fuel"] = p_data.get("fuel", 0) + self.escrow_fuel
        taken_fuel = min(val_fuel, p_data["fuel"])
        p_data["fuel"] -= taken_fuel
        self.escrow_fuel = taken_fuel
        self.give_fuel_str = str(taken_fuel)

        # Take Inputs (No limits, they can ask for a billion if they want)
        try:
            val_take_mats = int(self.take_mats_str)
            if val_take_mats < 0: val_take_mats = 0
            self.take_mats_str = str(val_take_mats)
        except ValueError:
            self.take_mats_str = "0"

        try:
            val_take_fuel = int(self.take_fuel_str)
            if val_take_fuel < 0: val_take_fuel = 0
            self.take_fuel_str = str(val_take_fuel)
        except ValueError:
            self.take_fuel_str = "0"

    def confirm_trade(self):
        
        self.evaluate_input()
        
        # Don't allow empty trades
        if self.escrow_mats == 0 and self.escrow_fuel == 0 and self.take_mats_str == "0" and self.take_fuel_str == "0" and self.puppet_state == "NONE":
            self.map_screen.show_feedback("Cannot send an empty trade offer!")
            return

        pending = self.map_screen.nation_data[self.map_screen.player_country].setdefault("pending_diplomacy", {})
        
        pending[self.target_nation] = {
            "action": "TRADE",
            "turns": 0,
            "timer": 0,
            "parameters": {
                "give_materials": self.escrow_mats,
                "give_fuel": self.escrow_fuel,
                "take_materials": int(self.take_mats_str),
                "take_fuel": int(self.take_fuel_str),
                "puppet_state": self.puppet_state
            },
            "message": f"TRADE PROPOSAL:\nGive: {self.escrow_mats} Mat, {self.escrow_fuel} Fuel\nTake: {self.take_mats_str} Mat, {self.take_fuel_str} Fuel\nPuppet Terms: {self.puppet_state}"
        }
        
        self.map_screen.show_feedback("Trade Offer Sent!")
        self.done = True

    def cancel_trade(self):
        # Refund any held resources
        p_data = self.map_screen.nation_data[self.map_screen.player_country]
        p_data["materials"] = p_data.get("materials", 0) + self.escrow_mats
        p_data["fuel"] = p_data.get("fuel", 0) + self.escrow_fuel
        self.done = True

    def handle_events(self, events):
        from ui_elements import process_text_input
        
        for event in events:
            for el in self.elements:
                el.handle_event(event)

            on_ui = self.panel_rect.collidepoint(pygame.mouse.get_pos())
            if event.type in (pygame.MOUSEWHEEL, pygame.MOUSEMOTION):
                self.map_screen.camera.handle_input(event, self.map_screen, on_ui)

            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                mx, my = event.pos
                
                # Check bounding boxes for the 4 inputs
                if pygame.Rect(self.panel_rect.x + 130, self.panel_rect.y + 100, 120, 30).collidepoint(mx, my):
                    self.active_input = "GIVE_MATS"
                elif pygame.Rect(self.panel_rect.x + 130, self.panel_rect.y + 150, 120, 30).collidepoint(mx, my):
                    self.active_input = "GIVE_FUEL"
                elif pygame.Rect(self.panel_rect.x + 430, self.panel_rect.y + 100, 120, 30).collidepoint(mx, my):
                    self.active_input = "TAKE_MATS"
                elif pygame.Rect(self.panel_rect.x + 430, self.panel_rect.y + 150, 120, 30).collidepoint(mx, my):
                    self.active_input = "TAKE_FUEL"
                else:
                    self.evaluate_input()
                    self.active_input = None

            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_RETURN:
                    self.evaluate_input()
                    self.active_input = None
                elif self.active_input:
                    # Input routing
                    val_func = lambda c: c.isdigit() or c == "-"
                    if self.active_input == "GIVE_MATS":
                        self.give_mats_str, _ = process_text_input(event, self.give_mats_str, validation_func=val_func)
                    elif self.active_input == "GIVE_FUEL":
                        self.give_fuel_str, _ = process_text_input(event, self.give_fuel_str, validation_func=val_func)
                    elif self.active_input == "TAKE_MATS":
                        self.take_mats_str, _ = process_text_input(event, self.take_mats_str, validation_func=val_func)
                    elif self.active_input == "TAKE_FUEL":
                        self.take_fuel_str, _ = process_text_input(event, self.take_fuel_str, validation_func=val_func)

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

        overlay = pygame.Surface((c.SCREEN_WIDTH, c.SCREEN_HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 180))
        surface.blit(overlay, (0, 0))

        # Main Panel
        pygame.draw.rect(surface, (40, 40, 50), self.panel_rect)
        pygame.draw.rect(surface, (100, 200, 100), self.panel_rect, 3)

        font_large = fonts.get("heading1")
        font_med = fonts.get("heading2")
        font_small = fonts.get("normal")

        title = font_large.render(f"Trade Agreement: {self.target_nation}", True, (255, 255, 255))
        surface.blit(title, (self.panel_rect.centerx - title.get_width()//2, self.panel_rect.y + 15))

        # You Give Section
        surface.blit(font_med.render("You Give:", True, (255, 100, 100)), (self.panel_rect.x + 30, self.panel_rect.y + 60))
        surface.blit(font_small.render("Materials:", True, (200, 200, 200)), (self.panel_rect.x + 30, self.panel_rect.y + 105))
        surface.blit(font_small.render("Fuel:", True, (200, 200, 200)), (self.panel_rect.x + 30, self.panel_rect.y + 155))

        # They Give Section
        surface.blit(font_med.render("They Give:", True, (100, 255, 100)), (self.panel_rect.centerx + 30, self.panel_rect.y + 60))
        surface.blit(font_small.render("Materials:", True, (200, 200, 200)), (self.panel_rect.centerx + 30, self.panel_rect.y + 105))
        surface.blit(font_small.render("Fuel:", True, (200, 200, 200)), (self.panel_rect.centerx + 30, self.panel_rect.y + 155))

        # Puppet Header
        surface.blit(font_med.render("Puppeting Terms:", True, (255, 215, 0)), (self.panel_rect.centerx - 80, self.panel_rect.y + 190))

        # Draw Input Boxes
        def draw_box(x, y, text, is_active):
            rect = pygame.Rect(x, y, 120, 30)
            pygame.draw.rect(surface, (20, 20, 30) if not is_active else (60, 60, 80), rect)
            pygame.draw.rect(surface, (150, 150, 150), rect, 1)
            display = text + ("|" if is_active else "")
            surface.blit(font_small.render(display, True, (255, 255, 255)), (rect.x + 5, rect.y + 5))

        draw_box(self.panel_rect.x + 130, self.panel_rect.y + 100, self.give_mats_str, self.active_input == "GIVE_MATS")
        draw_box(self.panel_rect.x + 130, self.panel_rect.y + 150, self.give_fuel_str, self.active_input == "GIVE_FUEL")
        draw_box(self.panel_rect.x + 430, self.panel_rect.y + 100, self.take_mats_str, self.active_input == "TAKE_MATS")
        draw_box(self.panel_rect.x + 430, self.panel_rect.y + 150, self.take_fuel_str, self.active_input == "TAKE_FUEL")

        for el in self.elements:
            if el.visible:
                el.draw(surface)

        # Resource HUD (Replicating Production Screen Logic)
        hud_rect = pygame.Rect(0, c.SCREEN_HEIGHT - 60, c.SCREEN_WIDTH, 60)
        pygame.draw.rect(surface, (30, 30, 30), hud_rect)
        pygame.draw.line(surface, (100, 100, 100), (0, hud_rect.y), (c.SCREEN_WIDTH, hud_rect.y), 2)

        p_data = self.map_screen.nation_data.get(self.map_screen.player_country, {})
        res_font = fonts.get("production_hud")
        resources = [
            (f"Manpower: {p_data.get('manpower', 0)}", (100, 200, 255)),
            (f"Materials: {p_data.get('materials', 0)}", (180, 180, 180)),
            (f"Fuel: {p_data.get('fuel', 0)}", (200, 100, 255))
        ]
        for i, (text, color) in enumerate(resources):
            surface.blit(res_font.render(text, True, color), (50 + (i * 300), hud_rect.y + 15))

# ==========================================
# PUPPETS SCREEN
# ==========================================

class Puppets_Screen(GameState):
    def __init__(self, map_screen):
        super().__init__()
        self.bg_color = (30, 35, 40)
        self.map_screen = map_screen
        self.player = map_screen.player_country
        self.panel_rect = pygame.Rect(c.SCREEN_WIDTH//2 - 400, 100, 800, c.SCREEN_HEIGHT - 200)
        self.scroll_y = 0
        self.max_scroll = 0
        self.y_space_between_puppets = 120
        self.refresh_ui()

    def refresh_ui(self):
        self.elements = [Button(50, c.TOP_BAR_UI_CENTER_Y, "small", "red", "Back", self.exit_screen)]
        self.elements.append(Button(c.SCREEN_WIDTH - 300, c.TOP_BAR_UI_CENTER_Y, "large", "blue", "Create Integrated Puppet", self.open_create_puppet))
        
        

        puppets = self.map_screen.nation_data.get(self.player, {}).get("puppets", [])
        
        y_pos = self.panel_rect.y + 100 + self.scroll_y
        for p in puppets:
            p_data = self.map_screen.nation_data.get(p, {})
            p_type = p_data.get("puppet_type", c.PUPPET_TYPE_AUTONOMOUS)
            siphon = p_data.setdefault("siphon_rates", {"manpower": 0.0, "materials": 0.0, "fuel": 0.0})
            
            pending_action, _ = queries.get_diplomatic_status(self.player, p, self.map_screen.nation_data)
            
            rel_txt = "Undo Release" if pending_action == "RELEASE_PUPPET" else "Release"
            rel_col = "red" if pending_action == "RELEASE_PUPPET" else "orange"
            btn_release = Button(self.panel_rect.x + 750, y_pos, "puppet_option", rel_col, rel_txt, lambda nation=p: self.queue_release(nation), font_preset="normal")
            self.elements.append(btn_release)
            
            # --- Make all buttons visible but greyscaled out if requirements aren't met ---
            
            # Edit Button
            btn_edit = Button(self.panel_rect.x + 570, y_pos, "puppet_option", "blue", "Edit", lambda nation=p: self.edit_puppet(nation), font_preset="normal")
            if p_type != c.PUPPET_TYPE_INTEGRATED:
                btn_edit.disabled = True
                btn_edit.text = "Can't Edit!"
                btn_edit.color, btn_edit.hover_color = c.UI_COLORS["grey"]
            self.elements.append(btn_edit)
            
            # Annex Button
            anx_txt = "Undo Annex" if pending_action == "ANNEX_PUPPET" else "Annex"
            anx_col = "orange" if pending_action == "ANNEX_PUPPET" else "red"
            btn_annex = Button(self.panel_rect.x + 570, y_pos + 45, "puppet_option", anx_col, anx_txt, lambda nation=p: self.queue_annex(nation), font_preset="normal")
            if p_type != c.PUPPET_TYPE_INTEGRATED:
                btn_annex.disabled = True
                btn_annex.text = "Can't Annex!"
                btn_annex.color, btn_annex.hover_color = c.UI_COLORS["grey"]
            self.elements.append(btn_annex)
            
            # Take Puppets Button
            take_txt = "Undo Take" if pending_action == "TAKE_PUPPETS" else "Take Puppets"
            btn_take = Button(self.panel_rect.x + 750, y_pos + 45, "puppet_option", "purple", take_txt, lambda nation=p: self.queue_take_puppets(nation), font_preset="normal")
            has_puppets = len(p_data.get("puppets", [])) > 0
            if p_type != c.PUPPET_TYPE_INTEGRATED or not has_puppets:
                btn_take.disabled = True
                btn_take.text = "Can't Take Puppets!" if p_type != c.PUPPET_TYPE_INTEGRATED else "They have 0 Puppets!"
                btn_take.color, btn_take.hover_color = c.UI_COLORS["grey"]
            self.elements.append(btn_take)
            
            # if you ever want to add this
            s_man = Slider(self.panel_rect.x + 200, y_pos + 50, 100, "Siphon Man", min(siphon["manpower"], c.MAX_PUPPET_SIPHON), lambda val, n=p: self.set_siphon(n, "manpower", val), visual_max=c.MAX_PUPPET_SIPHON, allowed_max=c.MAX_PUPPET_SIPHON)
            s_mat = Slider(self.panel_rect.x + 320, y_pos + 50, 100, "Siphon Mat", min(siphon["materials"], c.MAX_PUPPET_SIPHON), lambda val, n=p: self.set_siphon(n, "materials", val), visual_max=c.MAX_PUPPET_SIPHON, allowed_max=c.MAX_PUPPET_SIPHON)
            s_fuel = Slider(self.panel_rect.x + 440, y_pos + 50, 100, "Siphon Fuel", min(siphon["fuel"], c.MAX_PUPPET_SIPHON), lambda val, n=p: self.set_siphon(n, "fuel", val), visual_max=c.MAX_PUPPET_SIPHON, allowed_max=c.MAX_PUPPET_SIPHON)
            if p_type == c.PUPPET_TYPE_INTEGRATED:
                self.elements.extend([s_man, s_mat, s_fuel])
            
            y_pos += self.y_space_between_puppets
            
        self.max_scroll = min(0, self.panel_rect.height - (y_pos - self.scroll_y - self.panel_rect.y) - 20)

    def set_siphon(self, puppet, res, slider_val):
        self.map_screen.nation_data[puppet]["siphon_rates"][res] = slider_val

    def edit_puppet(self, puppet):
        self.map_screen.editing_country = puppet
        self.map_screen.change_state("EDIT_COUNTRY")
        self.done = True
        
    def queue_annex(self, puppet):
        msg = diplomacy_logic.toggle_diplomacy_action(self.map_screen.nation_data, self.map_screen.player_country, puppet, "ANNEX_PUPPET", "")
        self.map_screen.show_feedback(msg)
        self.refresh_ui()

    def queue_take_puppets(self, puppet):
        msg = diplomacy_logic.toggle_diplomacy_action(self.map_screen.nation_data, self.map_screen.player_country, puppet, "TAKE_PUPPETS", "")
        self.map_screen.show_feedback(msg)
        self.refresh_ui()

    def queue_release(self, puppet):
        msg = diplomacy_logic.toggle_diplomacy_action(self.map_screen.nation_data, self.map_screen.player_country, puppet, "RELEASE_PUPPET", "")
        self.map_screen.show_feedback(msg)
        self.refresh_ui()

    def open_create_puppet(self):
        screen = Create_Integrated_Puppet_Screen(self.map_screen)
        _run_pygame_sub_screen(self.map_screen, screen)
        self.refresh_ui()

    def exit_screen(self):
        self.next_state, self.done = "MAP", True

    def update(self):
        super().update()
        self.map_screen.camera.update(self.map_screen, c.SCREEN_HEIGHT)

    def handle_events(self, events):
        for event in events:
            for el in self.elements:
                el.handle_event(event)
            if event.type == pygame.MOUSEWHEEL:
                self.scroll_y += event.y * 30
                self.scroll_y = max(self.max_scroll, min(0, self.scroll_y))
                self.refresh_ui()

    def draw(self, surface):
        surface.fill(self.map_screen.bg_color)
        
        self.map_screen.hide_raised_rect = True
        self.map_screen.hide_tooltip = True
        self.map_screen.hide_resource_hud = True
        self.map_screen.hide_minimap = True
        self.map_screen.additional_draw(surface)
        self.map_screen.hide_raised_rect = False
        self.map_screen.hide_tooltip = False
        self.map_screen.hide_resource_hud = False
        self.map_screen.hide_minimap = False
        
        overlay = pygame.Surface((c.SCREEN_WIDTH, c.SCREEN_HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 180))
        surface.blit(overlay, (0, 0))

        pygame.draw.rect(surface, (40, 40, 50), self.panel_rect)
        pygame.draw.rect(surface, (100, 150, 255), self.panel_rect, 2)
        
        font_title = fonts.get("heading1")
        font_body = fonts.get("heading2")
        title = font_title.render("Your Subjects", True, (255, 255, 255))
        surface.blit(title, (self.panel_rect.centerx - title.get_width()//2, self.panel_rect.y + 15))

        master = self.map_screen.nation_data.get(self.player, {}).get("master", "")
        if master:
            master_name = self.map_screen.nation_data.get(master, {}).get("name", master)
            p_type = self.map_screen.nation_data.get(self.player, {}).get("puppet_type", c.PUPPET_TYPE_AUTONOMOUS)
            prefix = "an" if p_type.lower().startswith(('a', 'e', 'i', 'o', 'u')) else "a"
            master_txt = fonts.get("normal").render(f"You are {prefix} {p_type.lower()} puppet of: {master_name}", True, (255, 150, 150))
            surface.blit(master_txt, (self.panel_rect.centerx - master_txt.get_width()//2, self.panel_rect.y + 60))

        clip_rect = pygame.Rect(self.panel_rect.x + 5, self.panel_rect.y + 90, self.panel_rect.width - 10, self.panel_rect.height - 100)
        old_clip = surface.get_clip()
        surface.set_clip(clip_rect)
        
        puppets = self.map_screen.nation_data.get(self.player, {}).get("puppets", [])
        if not puppets:
            txt = font_body.render("You currently control no subjects.", True, (150, 150, 150))
            surface.blit(txt, (self.panel_rect.centerx - txt.get_width()//2, self.panel_rect.y + 130))
        else:
            y_pos = self.panel_rect.y + 100 + self.scroll_y
            for p in puppets:
                p_data = self.map_screen.nation_data.get(p, {})
                p_name = p_data.get("name", p)
                p_type = p_data.get("puppet_type", c.PUPPET_TYPE_AUTONOMOUS)
                
                # Formatted Puppet Sub-text
                name_txt = font_body.render(p_name, True, (255, 255, 255))
                type_txt = fonts.get("normal").render(f"({p_type})", True, (255, 215, 0) if p_type == c.PUPPET_TYPE_INTEGRATED else (200, 200, 200))
                
                surface.blit(name_txt, (self.panel_rect.x + 20, y_pos))
                surface.blit(type_txt, (self.panel_rect.x + 20, y_pos + 30))
                
                # Show exact siphoned amounts below sliders
                if p_type == c.PUPPET_TYPE_INTEGRATED:
                    econ_tuple = queries.get_economy_projections(p, self.map_screen.map_data, self.map_screen.nation_data)
                    if len(econ_tuple) == 3:
                        _, _, breakdown = econ_tuple
                        siphoned_man = abs(breakdown.get('manpower', {}).get('siphon', 0))
                        siphoned_mats = abs(breakdown.get('materials', {}).get('siphon', 0))
                        siphoned_fuel = abs(breakdown.get('fuel', {}).get('siphon', 0))
                        
                        tiny_font = fonts.get("tiny")
                        man_txt = tiny_font.render(f"Taking: {siphoned_man}", True, (200, 200, 200))
                        mat_txt = tiny_font.render(f"Taking: {siphoned_mats}", True, (200, 200, 200))
                        fuel_txt = tiny_font.render(f"Taking: {siphoned_fuel}", True, (200, 200, 200))
                        
                        surface.blit(man_txt, (self.panel_rect.x + 200, y_pos + 75))
                        surface.blit(mat_txt, (self.panel_rect.x + 320, y_pos + 75))
                        surface.blit(fuel_txt, (self.panel_rect.x + 440, y_pos + 75))

                y_pos += self.y_space_between_puppets

        surface.set_clip(old_clip)
        
        for el in self.elements:
            if el.visible:
                el.draw(surface)

class Create_Integrated_Puppet_Screen(GameState):
    def __init__(self, map_screen):
        super().__init__()
        self.bg_color = (20, 20, 30)
        self.map_screen = map_screen
        self.player = map_screen.player_country
        self.panel_rect = pygame.Rect(80, 120, 450, c.SCREEN_HEIGHT - 240)
        self.scroll_y = 0
        self.max_scroll = 0
        self.keep_cores = False
        
        self.valid_subjects = set()
        for prov in self.map_screen.map_data.values():
            if prov.get("owner") == self.player:
                for core in prov.get("cores", []):
                    if core != self.player and core not in c.UNPLAYABLE_NATIONS:
                        self.valid_subjects.add(core)
        self.valid_subjects = sorted(list(self.valid_subjects))
        self.refresh_ui()

    def toggle_keep_cores(self):
        self.keep_cores = not self.keep_cores
        self.refresh_ui()

    def refresh_ui(self):
        self.elements = [Button(50, c.TOP_BAR_UI_CENTER_Y, "small", "red", "Back", self.exit_screen)]
        
        btn_keep_cores_color = "green" if self.keep_cores else "red"
        btn_keep_cores_text = f"Keep Cores: {'ON' if self.keep_cores else 'OFF'}"
        self.elements.append(Button(self.panel_rect.centerx - 100, self.panel_rect.y + 60, "medium", btn_keep_cores_color, btn_keep_cores_text, self.toggle_keep_cores))
        
        y_pos = self.panel_rect.y + 120 + self.scroll_y
        
        queue = self.map_screen.nation_data.get(self.player, {}).get("release_puppet_queue", [])
        queued_cores = [q["core_nation"] for q in queue]

        for subject in self.valid_subjects:
            if y_pos > self.panel_rect.y + 100 and y_pos < self.panel_rect.bottom - 40:
                
                # Calculate if creating this puppet would leave it with 0 territories
                territory_count = 0
                for prov in self.map_screen.map_data.values():
                    if prov.get("owner") == self.player and subject in prov.get("cores", []):
                        if self.keep_cores and self.player in prov.get("cores", []):
                            continue
                            
                        # Account for previously queued puppets taking the land first
                        taken_by_queue = False
                        for q in queue:
                            q_core = q["core_nation"]
                            q_keep_cores = q.get("keep_cores", False)
                            
                            if q_core in prov.get("cores", []):
                                if q_keep_cores and self.player in prov.get("cores", []):
                                    continue
                                taken_by_queue = True
                                break
                                
                        if taken_by_queue:
                            continue

                        territory_count += 1
                
                if subject in queued_cores:
                    btn = Button(self.panel_rect.x + 320, y_pos, "small", "red", "Cancel", lambda s=subject: self.cancel_queue(s))
                else:
                    btn = Button(self.panel_rect.x + 320, y_pos, "small", "green", "Create", lambda s=subject: self.queue_creation(s))
                    if territory_count == 0:
                        btn.disabled = True
                        btn.color, btn.hover_color = c.UI_COLORS["grey"]
                        btn.text = "No Land"

                btn.is_scrollable = True
                btn.base_y = y_pos - self.scroll_y
                self.elements.append(btn)
            y_pos += 50
        
        self.max_scroll = min(0, self.panel_rect.height - (y_pos - self.scroll_y - self.panel_rect.y) - 20)

    def update(self):
        super().update()
        self.map_screen.camera.update(self.map_screen, c.SCREEN_HEIGHT)
        for el in self.elements:
            if getattr(el, 'is_scrollable', False):
                el.rect.y = el.base_y + self.scroll_y

    def queue_creation(self, subject):
        queue = self.map_screen.nation_data[self.player].setdefault("release_puppet_queue", [])
        queue.append({"core_nation": subject, "turns_left": 1, "keep_cores": self.keep_cores})
        self.map_screen.show_feedback(f"Creation of {subject} queued (1 turn).")
        self.refresh_ui()

    def cancel_queue(self, subject):
        queue = self.map_screen.nation_data[self.player].setdefault("release_puppet_queue", [])
        for i, q in enumerate(queue):
            if q["core_nation"] == subject:
                queue.pop(i)
                self.map_screen.show_feedback(f"Creation of {subject} cancelled.")
                self.refresh_ui()
                return

    def exit_screen(self):
        self.done = True

    def handle_events(self, events):
        for event in events:
            for el in self.elements:
                el.handle_event(event)
            on_ui = self.panel_rect.collidepoint(pygame.mouse.get_pos()) or self.map_screen.top_bar_rect.collidepoint(pygame.mouse.get_pos())
            if event.type in (pygame.MOUSEWHEEL, pygame.MOUSEMOTION):
                self.map_screen.camera.handle_input(event, self.map_screen, on_ui)
            if event.type == pygame.MOUSEWHEEL and on_ui:
                self.scroll_y += event.y * 30
                self.scroll_y = max(self.max_scroll, min(0, self.scroll_y))
                self.refresh_ui()

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

        # Highlight queued core provinces
        queue = self.map_screen.nation_data.get(self.player, {}).get("release_puppet_queue", [])
        queued_cores = [q["core_nation"] for q in queue]
        
        colors = [(255, 105, 180), (105, 255, 180), (105, 180, 255), (255, 255, 105), (255, 150, 100)]
        color_map = {}
        for i, qc in enumerate(queued_cores):
            color_map[qc] = colors[i % len(colors)]

        for prov in self.map_screen.map_data.values():
            if prov.get("owner") == self.player:
                for qc in queued_cores:
                    if qc in prov.get("cores", []):
                        overlay_renderer.draw_map_highlight(surface, self.map_screen, prov["id"], color_map[qc], base_radius=10)
                        break

        panel_surf = pygame.Surface((self.panel_rect.width, self.panel_rect.height), pygame.SRCALPHA)
        panel_surf.fill((30, 30, 50, 230))
        surface.blit(panel_surf, self.panel_rect.topleft)
        pygame.draw.rect(surface, (100, 150, 255), self.panel_rect, 2)

        font = fonts.get("heading1")
        tiny_font = fonts.get("normal")

        title = font.render("Create Integrated Puppet", True, (255, 255, 255))
        surface.blit(title, (self.panel_rect.centerx - title.get_width()//2, self.panel_rect.y + 10))

        clip_rect = pygame.Rect(self.panel_rect.x + 5, self.panel_rect.y + 110, self.panel_rect.width - 10, self.panel_rect.height - 120)
        old_clip = surface.get_clip()
        surface.set_clip(clip_rect)
        
        y_off = self.panel_rect.y + 120 + self.scroll_y
        if not self.valid_subjects:
            surface.blit(tiny_font.render("No potential subjects available.", True, (150, 150, 150)), (self.panel_rect.x + 30, y_off))
        else:
            for subject in self.valid_subjects:
                s_name = self.map_screen.nation_data.get(subject, {}).get("name", subject)
                is_queued = subject in queued_cores
                color = (255, 215, 0) if is_queued else (200, 200, 200)
                status = " (Queued)" if is_queued else ""
                txt = tiny_font.render(f"- {s_name}{status}", True, color)
                surface.blit(txt, (self.panel_rect.x + 20, y_off + 15))
                y_off += 50

        surface.set_clip(old_clip)

        if self.max_scroll < 0:
            viewport_h = self.panel_rect.height - 110
            track_rect = pygame.Rect(self.panel_rect.right - 15, self.panel_rect.y + 100, 10, viewport_h)
            pygame.draw.rect(surface, (50, 50, 70), track_rect)
            ratio = self.scroll_y / self.max_scroll
            handle_h = max(20, viewport_h * (viewport_h / (viewport_h - self.max_scroll)))
            handle_y = track_rect.y + ratio * (track_rect.height - handle_h)
            pygame.draw.rect(surface, (150, 150, 150), pygame.Rect(track_rect.x, handle_y, 10, handle_h), border_radius=5)

        for el in self.elements:
            if el.visible:
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

def open_view_peace_treaty_menu(map_screen, proposer):
    screen = View_Peace_Treaty_Screen(map_screen, proposer)
    _run_pygame_sub_screen(map_screen, screen)

def open_trade_menu(map_screen, target_nation):
    screen = Trade_Screen(map_screen, target_nation)
    _run_pygame_sub_screen(map_screen, screen)

def open_puppets_menu(map_screen):
    screen = Puppets_Screen(map_screen)
    _run_pygame_sub_screen(map_screen, screen)