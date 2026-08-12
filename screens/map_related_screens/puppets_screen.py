import pygame
import data.constants as c
from data import queries
from gameState import MapOverlayScreen
from ui_elements import Button, Slider, make_back_button
from map_logic.rendering.font_manager import fonts
from map_logic.rendering import overlay_renderer
from ui.bars import ui_bars
from ui.screen_runner import _run_pygame_sub_screen


class Puppets_Screen(MapOverlayScreen):
    # The panel covers most of the screen, so the wheel always drives the list.
    scroll_anywhere = True
    pans_camera = False
    PANEL_BG, PANEL_BORDER, PANEL_BORDER_WIDTH = c.PANEL_THEME_INFO
    PANEL_TITLE = "Your Subjects"

    def __init__(self, map_screen):
        super().__init__(map_screen, pygame.Rect(c.SCREEN_WIDTH//2 - 400, 100, 800, c.SCREEN_HEIGHT - 200))
        self.bg_color = (30, 35, 40)
        self.back_state = "MAP"
        self.y_space_between_puppets = 120
        self.refresh_ui()

    def refresh_ui(self):
        self.elements = [make_back_button(self.exit_screen, style="map")]
        self.elements.append(Button(c.SCREEN_WIDTH - 300, c.TOP_BAR_UI_CENTER_Y, "large", "blue", "Create Integrated Puppet", self.open_create_puppet))



        puppets = self.map_screen.nation_data.get(self.player, {}).get("puppets", [])

        self.scroll_content_rect = pygame.Rect(self.panel_rect.x + 5, self.panel_rect.y + 90,
                                               self.panel_rect.width - 10, self.panel_rect.height - 100)
        row_guard = self.content_hover_guard()

        y_pos = self.panel_rect.y + 100 + self.scroll_y
        for idx, p in enumerate(puppets):
            p_data = self.map_screen.nation_data.get(p, {})
            p_type = p_data.get("puppet_type", c.PUPPET_TYPE_AUTONOMOUS)
            siphon = queries.get_siphon_rates(p_data)

            pending_action, _ = queries.get_diplomatic_status(self.player, p, self.map_screen.nation_data)

            # Reorder Arrows
            btn_up = Button(self.panel_rect.x + 15, y_pos, "tiny_square", "blue", "^", lambda i=idx: self.move_puppet(i, -1), font_preset="normal")
            if idx == 0:
                btn_up.apply_state(enabled=False)

            btn_down = Button(self.panel_rect.x + 15, y_pos + 35, "tiny_square", "blue", "v", lambda i=idx: self.move_puppet(i, 1), font_preset="normal")
            if idx == len(puppets) - 1:
                btn_down.apply_state(enabled=False)

            rel_txt = "Undo Release" if pending_action == "RELEASE_PUPPET" else "Release"
            rel_col = "red" if pending_action == "RELEASE_PUPPET" else "orange"
            btn_release = Button(self.panel_rect.x + 680, y_pos, "puppet_option", rel_col, rel_txt, lambda nation=p: self.queue_release(nation), font_preset="normal")

            # --- Make all buttons visible but greyscaled out if requirements aren't met ---

            # Edit Button
            btn_edit = Button(self.panel_rect.x + 570, y_pos, "puppet_option", "blue", "Edit", lambda nation=p: self.edit_puppet(nation), font_preset="normal")
            if p_type != c.PUPPET_TYPE_INTEGRATED:
                btn_edit.apply_state(enabled=False, text="Can't Edit!")

            # Annex Button
            anx_txt = "Undo Annex" if pending_action == "ANNEX_PUPPET" else "Annex"
            anx_col = "orange" if pending_action == "ANNEX_PUPPET" else "red"
            btn_annex = Button(self.panel_rect.x + 570, y_pos + 45, "puppet_option", anx_col, anx_txt, lambda nation=p: self.queue_annex(nation), font_preset="normal")
            if p_type != c.PUPPET_TYPE_INTEGRATED:
                btn_annex.apply_state(enabled=False, text="Can't Annex!")

            # Take Puppets Button
            take_txt = "Undo Take" if pending_action == "TAKE_PUPPETS" else "Take Puppets"
            btn_take = Button(self.panel_rect.x + 680, y_pos + 45, "puppet_option", "purple", take_txt, lambda nation=p: self.queue_take_puppets(nation), font_preset="normal")
            has_puppets = len(p_data.get("puppets", [])) > 0
            if p_type != c.PUPPET_TYPE_INTEGRATED or not has_puppets:
                btn_take.apply_state(enabled=False,
                                     text="Can't Take Puppets!" if p_type != c.PUPPET_TYPE_INTEGRATED
                                     else "They have 0 Puppets!")

            row_els = [btn_up, btn_down, btn_release, btn_edit, btn_annex, btn_take]

            if p_type == c.PUPPET_TYPE_INTEGRATED:
                s_man = Slider(self.panel_rect.x + 200, y_pos + 50, 100, "Siphon Man", min(siphon["manpower"], c.MAX_PUPPET_SIPHON), lambda val, n=p: self.set_siphon(n, "manpower", val), visual_max=c.MAX_PUPPET_SIPHON, allowed_max=c.MAX_PUPPET_SIPHON)
                s_mat = Slider(self.panel_rect.x + 320, y_pos + 50, 100, "Siphon Mat", min(siphon["materials"], c.MAX_PUPPET_SIPHON), lambda val, n=p: self.set_siphon(n, "materials", val), visual_max=c.MAX_PUPPET_SIPHON, allowed_max=c.MAX_PUPPET_SIPHON)
                s_fuel = Slider(self.panel_rect.x + 440, y_pos + 50, 100, "Siphon Fuel", min(siphon["fuel"], c.MAX_PUPPET_SIPHON), lambda val, n=p: self.set_siphon(n, "fuel", val), visual_max=c.MAX_PUPPET_SIPHON, allowed_max=c.MAX_PUPPET_SIPHON)
                row_els += [s_man, s_mat, s_fuel]

            for el in row_els:
                el.is_scrollable = True
                el.click_guard = row_guard
            self.elements.extend(row_els)

            y_pos += self.y_space_between_puppets

        self.max_scroll = min(0, self.panel_rect.height - (y_pos - self.scroll_y - self.panel_rect.y) - 20)

    def set_siphon(self, puppet, res, slider_val):
        self.map_screen.nation_data[puppet]["siphon_rates"][res] = slider_val

    def move_puppet(self, index, direction):
        puppets = self.map_screen.nation_data.get(self.player, {}).get("puppets", [])
        new_index = index + direction
        if 0 <= new_index < len(puppets):
            puppets[index], puppets[new_index] = puppets[new_index], puppets[index]
        self.refresh_ui()

    def edit_puppet(self, puppet):
        self.map_screen.editing_country = puppet
        self.map_screen.change_state("EDIT_COUNTRY")
        self.done = True

    def queue_annex(self, puppet):
        self.queue_diplomacy_action(puppet, "ANNEX_PUPPET")

    def queue_take_puppets(self, puppet):
        self.queue_diplomacy_action(puppet, "TAKE_PUPPETS")

    def queue_release(self, puppet):
        self.queue_diplomacy_action(puppet, "RELEASE_PUPPET")

    def open_create_puppet(self):
        screen = Create_Integrated_Puppet_Screen(self.map_screen)
        _run_pygame_sub_screen(self.map_screen, screen, on_done=self.refresh_ui)

    def draw_content(self, surface):
        self.draw_panel(surface)

        font_body = fonts.get("heading2")

        master = self.map_screen.nation_data.get(self.player, {}).get("master", "")
        if master:
            master_name = self.map_screen.nation_data.get(master, {}).get("name", master)
            p_type = self.map_screen.nation_data.get(self.player, {}).get("puppet_type", c.PUPPET_TYPE_AUTONOMOUS)
            prefix = "an" if p_type.lower().startswith(('a', 'e', 'i', 'o', 'u')) else "a"
            master_txt = fonts.get("normal").render(f"You are {prefix} {p_type.lower()} puppet of: {master_name}", True, (255, 150, 150))
            surface.blit(master_txt, (self.panel_rect.centerx - master_txt.get_width()//2, self.panel_rect.y + 60))

        clip_rect = self.scroll_content_rect or pygame.Rect(
            self.panel_rect.x + 5, self.panel_rect.y + 90, self.panel_rect.width - 10, self.panel_rect.height - 100)

        puppets = self.map_screen.nation_data.get(self.player, {}).get("puppets", [])
        if not puppets:
            txt = font_body.render("You currently control no subjects.", True, c.UI_TEXT_MUTED)
            surface.blit(txt, (self.panel_rect.centerx - txt.get_width()//2, self.panel_rect.y + 130))
        else:
            with ui_bars.clip_scroll_region(surface, clip_rect,
                                            draw_top=self.scroll_y != 0, draw_bottom=self.scroll_y > self.max_scroll):
                y_pos = self.panel_rect.y + 100 + self.scroll_y
                for p in puppets:
                    p_data = self.map_screen.nation_data.get(p, {})
                    p_name = p_data.get("name", p)
                    p_type = p_data.get("puppet_type", c.PUPPET_TYPE_AUTONOMOUS)

                    # Formatted Puppet Sub-text
                    name_txt = font_body.render(p_name, True, (255, 255, 255))
                    type_txt = fonts.get("normal").render(f"({p_type})", True, c.COLOR_GOLD_HIGHLIGHT if p_type == c.PUPPET_TYPE_INTEGRATED else c.UI_TEXT_LIGHT)

                    surface.blit(name_txt, (self.panel_rect.x + 60, y_pos))
                    surface.blit(type_txt, (self.panel_rect.x + 60, y_pos + 30))

                    # Show siphoned amounts below sliders
                    if p_type == c.PUPPET_TYPE_INTEGRATED:
                        econ_tuple = queries.get_economy_projections(p, self.map_screen.map_data, self.map_screen.nation_data)
                        if len(econ_tuple) == 3:
                            _, _, breakdown = econ_tuple
                            siphoned_man = abs(breakdown.get('manpower', {}).get('siphon', 0))
                            siphoned_mats = abs(breakdown.get('materials', {}).get('siphon', 0))
                            siphoned_fuel = abs(breakdown.get('fuel', {}).get('siphon', 0))

                            tiny_font = fonts.get("tiny")
                            man_txt = tiny_font.render(f"Taking: {queries.format_number(siphoned_man)}", True, c.UI_TEXT_LIGHT)
                            mat_txt = tiny_font.render(f"Taking: {queries.format_number(siphoned_mats)}", True, c.UI_TEXT_LIGHT)
                            fuel_txt = tiny_font.render(f"Taking: {queries.format_number(siphoned_fuel)}", True, c.UI_TEXT_LIGHT)

                            surface.blit(man_txt, (self.panel_rect.x + 200, y_pos + 75))
                            surface.blit(mat_txt, (self.panel_rect.x + 320, y_pos + 75))
                            surface.blit(fuel_txt, (self.panel_rect.x + 440, y_pos + 75))

                    y_pos += self.y_space_between_puppets


class Create_Integrated_Puppet_Screen(MapOverlayScreen):
    overlay_alpha = 0
    # Docked to the left so the cores being carved out stay visible, and
    # translucent for the same reason.
    CENTER_PANEL = False
    PANEL_BG, PANEL_BORDER, PANEL_BORDER_WIDTH = c.PANEL_THEME_INFO_OVER_MAP
    PANEL_TITLE = "Create Integrated Puppet"

    def __init__(self, map_screen):
        super().__init__(map_screen, pygame.Rect(80, 120, 450, c.SCREEN_HEIGHT - 240))
        self.bg_color = (20, 20, 30)
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
        self.elements = [make_back_button(self.exit_screen, style="map")]

        btn_keep_cores_color = "green" if self.keep_cores else "red"
        btn_keep_cores_text = f"Keep Cores: {'ON' if self.keep_cores else 'OFF'}"
        self.elements.append(Button(self.panel_rect.centerx - 100, self.panel_rect.y + 60, "medium", btn_keep_cores_color, btn_keep_cores_text, self.toggle_keep_cores))

        y_pos = self.panel_rect.y + 120 + self.scroll_y

        self.scroll_content_rect = pygame.Rect(self.panel_rect.x + 5, self.panel_rect.y + 110,
                                               self.panel_rect.width - 10, self.panel_rect.height - 120)
        row_guard = self.content_hover_guard()

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
                        btn.apply_state(enabled=False, text="No Land")

                btn.is_scrollable = True
                btn.click_guard = row_guard
                btn.base_y = y_pos - self.scroll_y
                self.elements.append(btn)
            y_pos += 50

        self.max_scroll = min(0, self.panel_rect.height - (y_pos - self.scroll_y - self.panel_rect.y) - 20)

    def update(self):
        super().update()
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

    def draw_content(self, surface):
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

        self.draw_panel(surface)

        tiny_font = fonts.get("normal")

        clip_rect = self.scroll_content_rect or pygame.Rect(
            self.panel_rect.x + 5, self.panel_rect.y + 110, self.panel_rect.width - 10, self.panel_rect.height - 120)

        if not self.valid_subjects:
            y_off = self.panel_rect.y + 120 + self.scroll_y
            surface.blit(tiny_font.render("No potential subjects available.", True, c.UI_TEXT_MUTED), (self.panel_rect.x + 30, y_off))
        else:
            with ui_bars.clip_scroll_region(surface, clip_rect,
                                            draw_top=self.scroll_y != 0, draw_bottom=self.scroll_y > self.max_scroll):
                y_off = self.panel_rect.y + 120 + self.scroll_y
                for subject in self.valid_subjects:
                    try:
                        if subject in self.map_screen.nation_data:
                            subject_name = self.map_screen.nation_data[subject].get("name", subject)
                        else:
                            from data.io import country_io
                            subject_name = country_io.get_country_stats(subject).get("name", subject)
                    except Exception:
                        subject_name = subject

                    is_queued = subject in queued_cores
                    color = c.COLOR_GOLD_HIGHLIGHT if is_queued else (200, 200, 200)
                    status = " (Queued)" if is_queued else ""
                    txt = tiny_font.render(f"- {subject_name}{status}", True, color)
                    surface.blit(txt, (self.panel_rect.x + 20, y_off + 15))
                    y_off += 50

        # No max_scroll guard here: draw_list_scrollbar already returns nothing
        # when the list fits, and going through it also clears last frame's
        # track/handle rects instead of leaving them stale.
        viewport_h = self.panel_rect.height - 110
        self.draw_list_scrollbar(surface, self.panel_rect.right - 15, self.panel_rect.y + 100,
                                 viewport_h, width=10)


def open_puppets_menu(map_screen):
    _run_pygame_sub_screen(map_screen, Puppets_Screen(map_screen))
