import pygame
import data.constants as c
from gameState import MapOverlayScreen
from ui_elements import make_back_button, Button
from map_logic.rendering.font_manager import fonts
from map_logic.rendering import overlay_renderer
from ui.bars import ui_bars
from ui.screen_runner import _run_pygame_sub_screen


class Claims_Screen(MapOverlayScreen):
    """The map view of who claims what, and where a claim is made.

    Two lives now. In the scenario editor it is still the browsable overview of
    every claim on the map, which is authoring work and belongs there. In an
    actual game there is no Claims tab any more: a claim is something you
    fabricate as a justification for a specific war, so this opens from the
    declare-war window pointed at one nation, and clicking their provinces is
    how you build a case against them.

    `target_nation` is what tells the two apart.
    """

    # Docked to the left so the claimed provinces stay visible beside it.
    CENTER_PANEL = False
    overlay_alpha = 0

    # Panel list metrics, shared by the drawing pass and the scroll measurement.
    SECTION_HEADER_H = 30
    SECTION_ROW_H = 25
    SECTION_GAP = 10

    def __init__(self, map_screen, target_nation=None):
        super().__init__(map_screen, pygame.Rect(80, 120, 380, c.SCREEN_HEIGHT - 240))

        self.target_nation = target_nation
        self.is_picker = target_nation is not None

        # Determine if we have global viewing privileges
        self.is_global_viewer = (map_screen.is_editor or self.player in ["Spectator", "None"]) \
            and not self.is_picker
        self.view_mode = "YOURS" if self.is_picker else (
            "GLOBAL" if self.is_global_viewer else "YOURS")

        self.refresh_ui()

    def set_view_mode(self, mode):
        self.view_mode = mode
        self.scroll_y = 0
        self.refresh_ui()

    def refresh_ui(self):
        self.elements = [make_back_button(self.exit_screen, style="map")]

        # Pointed at one nation there is nothing to switch between: the only
        # question on screen is which of their provinces you want.
        if not self.is_picker:
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
            if not dest or dest.get("owner") in c.UNPLAYABLE_NATIONS:
                self.map_screen.show_feedback("Can only edit claims on valid nations.")
                return

            if self.is_picker:
                # A justification is built against one nation, so a claim on
                # somebody else is not a case for this war.
                if dest.get("owner") == self.target_nation:
                    self.toggle_claim(dest)
                else:
                    self.map_screen.show_feedback(
                        f"Pick territory held by {self.target_nation}.")
            elif self.view_mode == "YOURS" and dest.get("owner") != self.player:
                self.toggle_claim(dest)
            elif self.view_mode == "THEIRS" and dest.get("owner") == self.player:
                self.return_foreign_claim(dest)

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

    # ------------------------------------------------------------------ #
    #                          PANEL CONTENTS                            #
    # ------------------------------------------------------------------ #

    def _nation_label(self, tag):
        return self.map_screen.nation_data.get(tag, {}).get("name", tag)

    def _nation_color(self, tag):
        return self.map_screen.nation_colors.get(tag, (255, 255, 255))

    def _panel_sections(self):
        """The panel's contents, as a list of (header, header color, rows,
        empty-state text) where each row is (text, color).

        Drawing and scroll measurement both walk this one list. They used to be
        a drawing loop and a parallel `40 + len(...) * 25` expression sitting
        next to each other, so the scrollbar could be sized from a height the
        rows on screen didn't actually add up to.
        """
        if self.view_mode == "GLOBAL":
            rows = [(f"- Prov {item['prov_id']} ({self._nation_label(item['nation'])})",
                     self._nation_color(item["nation"]))
                    for item in self.global_claims_list]
            return [("All Map Claims:", c.COLOR_GOLD_HIGHLIGHT, rows, "No claims on the map.")]

        if self.view_mode == "YOURS":
            queued = []
            for q in self.queue:
                prov = self.map_screen.id_to_province.get(q["prov_id"])
                owner = prov.get("owner", "Unknown") if prov else "Unknown"
                queued.append((f"- Prov {q['prov_id']} ({self._nation_label(owner)}): "
                               f"{q['turns_left']} turns left", c.UI_TEXT_LIGHT))

            active = []
            for pid in self.display_claims:
                prov = self.map_screen.id_to_province.get(pid)
                owner = prov.get("owner", "Unknown") if prov else "Unknown"

                revoke_item = next((r for r in self.revoke_queue if r["prov_id"] == pid), None)
                if revoke_item:
                    status_text = f" (Revoking in {revoke_item['turns_left']})"
                    color = (255, 100, 100)
                elif pid in self.core_ids:
                    status_text = " (Auto-Claimed Core)"
                    color = (255, 150, 200)
                else:
                    status_text = ""
                    color = (200, 200, 200)

                active.append((f"- Prov {pid} ({self._nation_label(owner)}){status_text}", color))

            return [
                ("Queued Claims:", c.MENU_BOTTOM_TEXT_LINK_COLOR, queued, "No claims queued."),
                ("Active Claims:", c.COLOR_GOLD_HIGHLIGHT, active, "No active claims."),
            ]

        # THEIRS: what other nations are claiming off us, justified or standing.
        def foreign_row(item, label):
            color = self._nation_color(item["nation"])
            text = f"- Prov {item['prov_id']} ({self._nation_label(item['nation'])}): {label}"
            if item["prov_id"] in self.return_ids:
                text += " (Returning in 1 turn)"
                color = c.COLOR_SUCCESS_GREEN
            return text, color

        justifying = [foreign_row(item, f"Actively Justifying ({item['turns']}t)")
                      for item in self.foreign_claims_list if item["type"] == "QUEUE"]
        standing = [foreign_row(item, "Auto-Claimed Core" if item["type"] == "CORE" else "Active Claim")
                    for item in self.foreign_claims_list if item["type"] != "QUEUE"]

        return [
            ("Actively Justifying:", c.MENU_BOTTOM_TEXT_LINK_COLOR, justifying,
             "No nations are actively justifying claims on you."),
            ("Claims on You:", (255, 100, 100), standing,
             "No foreign claims on your territory."),
        ]

    def _sections_height(self, sections):
        """How tall _draw_section will render the whole list. Same constants,
        so the scrollbar and the rows can never disagree."""
        total = 0
        for i, (_header, _color, rows, _empty) in enumerate(sections):
            if i:
                total += self.SECTION_GAP
            total += self.SECTION_HEADER_H
            total += len(rows) * self.SECTION_ROW_H if rows else self.SECTION_ROW_H
        return total

    def _draw_section(self, surface, y, section):
        """Draws one header plus its rows (or its empty-state line). Returns the
        y the next section starts at."""
        header, header_color, rows, empty_text = section
        surface.blit(fonts.get("heading2").render(header, True, header_color),
                     (self.panel_rect.x + 20, y))
        y += self.SECTION_HEADER_H

        tiny_font = fonts.get("normal")
        if not rows:
            surface.blit(tiny_font.render(empty_text, True, c.UI_TEXT_MUTED),
                         (self.panel_rect.x + 30, y))
            return y + self.SECTION_ROW_H

        for text, color in rows:
            surface.blit(tiny_font.render(text, True, color), (self.panel_rect.x + 30, y))
            y += self.SECTION_ROW_H
        return y

    def draw_content(self, surface):
        # Draw territorial highlights (data is rebuilt in _refresh_claims_data(),
        # not here, since it only changes on claim mutations / view-mode switches)
        claims = self.claims
        queue = self.queue
        revoke_ids = self.revoke_ids
        return_ids = self.return_ids
        core_ids = self.core_ids
        foreign_claims_map = self.foreign_claims_map
        global_claims_list = self.global_claims_list

        if self.view_mode == "GLOBAL":
            for item in global_claims_list:
                color = self._nation_color(item["nation"])
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
                    color = self._nation_color(claim_info["nation"])
                    is_just = (claim_info["type"] == "QUEUE")

                    if pid in return_ids:
                        color = c.COLOR_SUCCESS_GREEN # Green highlight for returning tiles

                    overlay_renderer.draw_map_highlight(surface, self.map_screen, pid, color, base_radius=4, inset=i, is_justifying=is_just)

        # Draw Information Panel
        ui_bars.draw_translucent_panel(surface, self.panel_rect, (*c.HUD_PANEL_BG, 230),
                                       border_color=c.MODAL_BORDER)

        font = fonts.get("heading1")
        heading = f"Justify: {self.target_nation}" if self.is_picker else "Territory Claims"
        title = font.render(heading, True, (255, 255, 255))
        surface.blit(title, (self.panel_rect.centerx - title.get_width()//2, self.panel_rect.y + 10))

        if self.is_picker:
            hint = fonts.get("small").render(
                f"Click {self.target_nation}'s provinces to build a case.",
                True, c.COLOR_GOLD_HIGHLIGHT)
            surface.blit(hint, (self.panel_rect.centerx - hint.get_width() // 2,
                                self.panel_rect.y + 48))

        sections = self._panel_sections()

        viewport_h = self.panel_rect.height - 95
        self.max_scroll = min(0, viewport_h - self._sections_height(sections) - 20)
        self.scroll_y = max(self.max_scroll, min(0, self.scroll_y))

        clip_rect = pygame.Rect(self.panel_rect.x + 5, self.panel_rect.y + 90, self.panel_rect.width - 10, viewport_h)
        self.scroll_content_rect = clip_rect
        with ui_bars.clip_scroll_region(surface, clip_rect,
                                        draw_top=self.scroll_y != 0, draw_bottom=self.scroll_y > self.max_scroll):
            y_off = self.panel_rect.y + 100 + self.scroll_y
            for i, section in enumerate(sections):
                if i:
                    y_off += self.SECTION_GAP
                y_off = self._draw_section(surface, y_off, section)

        # Draws nothing when the content fits inside the box.
        self.draw_list_scrollbar(surface, self.panel_rect.right - 15, self.panel_rect.y + 90,
                                 viewport_h, width=10)


def open_claims_menu(map_screen):
    """The editor's overview of every claim on the map."""
    _run_pygame_sub_screen(map_screen, Claims_Screen(map_screen))


def open_claim_picker(map_screen, target_nation):
    """Build a justification against one nation, from the declare-war window."""
    _run_pygame_sub_screen(map_screen, Claims_Screen(map_screen, target_nation))
