import pygame
import data.constants as c
from gameState import MapOverlayScreen
from ui_elements import make_back_button, Button
from map_logic.rendering.font_manager import fonts
from map_logic.rendering import overlay_renderer
from ui.bars import ui_bars
from ui.screen_runner import _run_pygame_sub_screen


class Claims_Screen(MapOverlayScreen):
    overlay_alpha = 0

    def __init__(self, map_screen):
        super().__init__(map_screen, pygame.Rect(80, 120, 380, c.SCREEN_HEIGHT - 240))

        # Determine if we have global viewing privileges
        self.is_global_viewer = map_screen.is_editor or self.player in ["Spectator", "None"]
        self.view_mode = "GLOBAL" if self.is_global_viewer else "YOURS"

        self.refresh_ui()

    def set_view_mode(self, mode):
        self.view_mode = mode
        self.scroll_y = 0
        self.refresh_ui()

    def refresh_ui(self):
        self.elements = [make_back_button(self.exit_screen, style="map")]

        row_y = self.panel_rect.y + 40
        if self.is_global_viewer:
            modes = [(self.panel_rect.x + 20, row_y, "GLOBAL", "Global Claims")]
        else:
            modes = [(self.panel_rect.x + 20, row_y, "YOURS", "Your Claims"),
                     (self.panel_rect.x + 200, row_y, "THEIRS", "Claims On You")]

        # This row greys the inactive entries rather than showing them blue
        for x, y, mode, label in modes:
            btn = Button(x, y, "brick", "blue" if self.view_mode == mode else "grey", label,
                         lambda m=mode: self.set_view_mode(m))
            btn.is_selected = (self.view_mode == mode)
            self.elements.append(btn)

        self._refresh_claims_data()

    def _refresh_claims_data(self):
        """Rebuilds the claims lists consumed by draw_content. Only called from
        refresh_ui() (on init, view-mode switch, or a claim/queue mutation) rather
        than every frame, since none of this data changes while the screen is open
        except through those actions."""
        data = self.map_screen.nation_data.get(self.player, {})
        self.claims = data.get("claims", [])
        self.queue = data.get("claim_queue", [])
        self.revoke_queue = data.get("revoke_queue", [])
        self.return_queue = data.get("return_queue", [])
        self.revoke_ids = [rq["prov_id"] for rq in self.revoke_queue]
        self.return_ids = [rq["prov_id"] for rq in self.return_queue]

        self.core_ids = []
        self.foreign_claims_list = []
        self.foreign_claims_map = {}
        self.global_claims_list = []
        self.display_claims = []

        if self.view_mode == "YOURS":
            self.core_ids = [prov["id"] for prov in self.map_screen.map_data.values()
                              if self.player in prov.get("cores", [])
                              and prov.get("owner") != self.player
                              and prov.get("owner") not in c.UNPLAYABLE_NATIONS]
            self.display_claims = self.claims + [c_id for c_id in self.core_ids if c_id not in self.claims]

        elif self.view_mode == "THEIRS":
            for n, d in self.map_screen.nation_data.items():
                if n == self.player or n in c.UNPLAYABLE_NATIONS: continue

                for pid in d.get("claims", []):
                    prov = self.map_screen.id_to_province.get(pid)
                    if prov and prov.get("owner") == self.player:
                        info = {"nation": n, "type": "CLAIM", "turns": 0, "prov_id": pid}
                        self.foreign_claims_list.append(info)
                        self.foreign_claims_map.setdefault(pid, []).append(info)

                for prov in self.map_screen.map_data.values():
                    if prov.get("owner") == self.player and n in prov.get("cores", []) and prov["id"] not in d.get("claims", []):
                        info = {"nation": n, "type": "CORE", "turns": 0, "prov_id": prov["id"]}
                        self.foreign_claims_list.append(info)
                        self.foreign_claims_map.setdefault(prov["id"], []).append(info)

                for q in d.get("claim_queue", []):
                    if q.get("turns_left", 0) < c.CLAIM_TURN_NON_CORE: # Don't show if made this turn
                        pid = q["prov_id"]
                        prov = self.map_screen.id_to_province.get(pid)
                        if prov and prov.get("owner") == self.player:
                            info = {"nation": n, "type": "QUEUE", "turns": q["turns_left"], "prov_id": pid}
                            self.foreign_claims_list.append(info)
                            self.foreign_claims_map.setdefault(pid, []).append(info)

            self.foreign_claims_list.sort(key=lambda x: (x["prov_id"], x["nation"]))

        elif self.view_mode == "GLOBAL":
            for n, d in self.map_screen.nation_data.items():
                if n in c.UNPLAYABLE_NATIONS and n != "None": continue
                for pid in d.get("claims", []):
                    self.global_claims_list.append({"nation": n, "prov_id": pid})
            self.global_claims_list.sort(key=lambda x: (x["nation"], x["prov_id"]))

    def additional_events(self, event):
        super().additional_events(event)

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and not self.is_over_ui():
            if self.map_screen.tactical_mode:
                self.map_screen.show_feedback("Tactical Mode: Cannot modify claims.")
                return

            dest = self.get_clicked_province(event.pos)
            if dest and dest.get("owner") not in c.UNPLAYABLE_NATIONS:
                if self.view_mode == "YOURS" and dest.get("owner") != self.player:
                    self.toggle_claim(dest)
                elif self.view_mode == "THEIRS" and dest.get("owner") == self.player:
                    self.return_foreign_claim(dest)
            else:
                self.map_screen.show_feedback("Can only edit claims on valid nations.")

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

    def draw_content(self, surface):
        # Draw territorial highlights (data is rebuilt in _refresh_claims_data(),
        # not here, since it only changes on claim mutations / view-mode switches)
        claims = self.claims
        queue = self.queue
        revoke_queue = self.revoke_queue
        return_queue = self.return_queue
        revoke_ids = self.revoke_ids
        return_ids = self.return_ids
        core_ids = self.core_ids
        foreign_claims_list = self.foreign_claims_list
        foreign_claims_map = self.foreign_claims_map
        global_claims_list = self.global_claims_list

        if self.view_mode == "GLOBAL":
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
                    overlay_renderer.draw_map_highlight(surface, self.map_screen, pid, c.COLOR_GOLD_HIGHLIGHT, base_radius=4)

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
                        color = c.COLOR_SUCCESS_GREEN # Green highlight for returning tiles

                    overlay_renderer.draw_map_highlight(surface, self.map_screen, pid, color, base_radius=4, inset=i, is_justifying=is_just)

        # Draw Information Panel
        ui_bars.draw_translucent_panel(surface, self.panel_rect, (*c.HUD_PANEL_BG, 230),
                                       border_color=c.MODAL_BORDER)

        font = fonts.get("heading1")
        sub_font = fonts.get("heading2")
        tiny_font = fonts.get("normal")

        title = font.render("Territory Claims", True, (255, 255, 255))
        surface.blit(title, (self.panel_rect.centerx - title.get_width()//2, self.panel_rect.y + 10))

        display_claims = self.display_claims

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
        self.scroll_content_rect = clip_rect
        with ui_bars.clip_scroll_region(surface, clip_rect,
                                        draw_top=self.scroll_y != 0, draw_bottom=self.scroll_y > self.max_scroll):
            y_off = self.panel_rect.y + 100 + self.scroll_y

            if self.view_mode == "GLOBAL":
                surface.blit(sub_font.render("All Map Claims:", True, c.COLOR_GOLD_HIGHLIGHT), (self.panel_rect.x + 20, y_off))
                y_off += 30

                if not global_claims_list:
                    surface.blit(tiny_font.render("No claims on the map.", True, c.UI_TEXT_MUTED), (self.panel_rect.x + 30, y_off))
                else:
                    for item in global_claims_list:
                        nation_name = self.map_screen.nation_data.get(item["nation"], {}).get("name", item["nation"])
                        color = self.map_screen.nation_colors.get(item["nation"], (255, 255, 255))

                        txt = tiny_font.render(f"- Prov {item['prov_id']} ({nation_name})", True, color)
                        surface.blit(txt, (self.panel_rect.x + 30, y_off))
                        y_off += 25

            elif self.view_mode == "YOURS":
                surface.blit(sub_font.render("Queued Claims:", True, c.MENU_BOTTOM_TEXT_LINK_COLOR), (self.panel_rect.x + 20, y_off))
                y_off += 30

                if not queue:
                    surface.blit(tiny_font.render("No claims queued.", True, c.UI_TEXT_MUTED), (self.panel_rect.x + 30, y_off))
                    y_off += 25
                else:
                    for q in queue:
                        prov = self.map_screen.id_to_province.get(q["prov_id"])
                        owner = prov.get("owner", "Unknown") if prov else "Unknown"
                        owner_name = self.map_screen.nation_data.get(owner, {}).get("name", owner)
                        txt = tiny_font.render(f"- Prov {q['prov_id']} ({owner_name}): {q['turns_left']} turns left", True, c.UI_TEXT_LIGHT)
                        surface.blit(txt, (self.panel_rect.x + 30, y_off))
                        y_off += 25

                y_off += 10

                surface.blit(sub_font.render("Active Claims:", True, c.COLOR_GOLD_HIGHLIGHT), (self.panel_rect.x + 20, y_off))
                y_off += 30

                if not display_claims:
                    surface.blit(tiny_font.render("No active claims.", True, c.UI_TEXT_MUTED), (self.panel_rect.x + 30, y_off))
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
                queued_foreign = [item for item in foreign_claims_list if item["type"] == "QUEUE"]
                active_foreign = [item for item in foreign_claims_list if item["type"] != "QUEUE"]

                surface.blit(sub_font.render("Actively Justifying:", True, c.MENU_BOTTOM_TEXT_LINK_COLOR), (self.panel_rect.x + 20, y_off))
                y_off += 30

                if not queued_foreign:
                    surface.blit(tiny_font.render("No nations are actively justifying claims on you.", True, c.UI_TEXT_MUTED), (self.panel_rect.x + 30, y_off))
                    y_off += 25
                else:
                    for item in queued_foreign:
                        nation_name = self.map_screen.nation_data.get(item["nation"], {}).get("name", item["nation"])
                        color = self.map_screen.nation_colors.get(item["nation"], (255, 255, 255))

                        txt_str = f"- Prov {item['prov_id']} ({nation_name}): Actively Justifying ({item['turns']}t)"
                        if item["prov_id"] in return_ids:
                            txt_str += f" (Returning in 1 turn)"
                            color = c.COLOR_SUCCESS_GREEN

                        txt = tiny_font.render(txt_str, True, color)
                        surface.blit(txt, (self.panel_rect.x + 30, y_off))
                        y_off += 25

                y_off += 10

                surface.blit(sub_font.render("Claims on You:", True, (255, 100, 100)), (self.panel_rect.x + 20, y_off))
                y_off += 30

                if not active_foreign:
                    surface.blit(tiny_font.render("No foreign claims on your territory.", True, c.UI_TEXT_MUTED), (self.panel_rect.x + 30, y_off))
                else:
                    for item in active_foreign:
                        nation_name = self.map_screen.nation_data.get(item["nation"], {}).get("name", item["nation"])
                        color = self.map_screen.nation_colors.get(item["nation"], (255, 255, 255))

                        if item["type"] == "CORE":
                            txt_str = f"- Prov {item['prov_id']} ({nation_name}): Auto-Claimed Core"
                        else:
                            txt_str = f"- Prov {item['prov_id']} ({nation_name}): Active Claim"

                        if item["prov_id"] in return_ids:
                            txt_str += f" (Returning in 1 turn)"
                            color = c.COLOR_SUCCESS_GREEN

                        txt = tiny_font.render(txt_str, True, color)
                        surface.blit(txt, (self.panel_rect.x + 30, y_off))
                        y_off += 25


        # Draws nothing when the content fits inside the box.
        self.draw_list_scrollbar(surface, self.panel_rect.right - 15, self.panel_rect.y + 90,
                                 viewport_h, width=10)


def open_claims_menu(map_screen):
    _run_pygame_sub_screen(map_screen, Claims_Screen(map_screen))
