import pygame
import data.constants as c
from data import queries
from gameState import MapOverlayScreen
from ui_elements import Button, Slider, make_back_button
from map_logic.rendering.font_manager import fonts
from map_logic.rendering import overlay_renderer
from ui.bars import ui_bars
from ui.screen_runner import _run_pygame_sub_screen
from ui.text_utils import fit_text


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
        self.elements.append(Button(c.SCREEN_WIDTH - 300, c.TOP_BAR_UI_CENTER_Y, "large", "blue", "Release Nation", self.open_create_puppet))



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

    def can_edit_realtime(self):
        if not getattr(self.map_screen, "realtime_multiplayer", False):
            return True
        session = getattr(self.map_screen, "realtime_session", None)
        player = session.players.get(getattr(self.map_screen, "realtime_player_id", "")) if session else None
        if session and session.phase == "TURN" and player and not player.submitted and not player.eliminated:
            return True
        self.map_screen.show_feedback("Turn submitted or unavailable; unsubmit to change subjects.")
        return False

    def set_siphon(self, puppet, res, slider_val):
        if not self.can_edit_realtime():
            return
        self.map_screen.nation_data[puppet]["siphon_rates"][res] = slider_val

    def move_puppet(self, index, direction):
        if not self.can_edit_realtime():
            return
        puppets = self.map_screen.nation_data.get(self.player, {}).get("puppets", [])
        new_index = index + direction
        if 0 <= new_index < len(puppets):
            puppets[index], puppets[new_index] = puppets[new_index], puppets[index]
        self.refresh_ui()

    def edit_puppet(self, puppet):
        if not self.can_edit_realtime():
            return
        self.map_screen.editing_country = puppet
        self.map_screen.change_state("EDIT_COUNTRY")
        self.done = True

    def queue_annex(self, puppet):
        if not self.can_edit_realtime():
            return
        self.queue_diplomacy_action(puppet, "ANNEX_PUPPET")

    def queue_take_puppets(self, puppet):
        if not self.can_edit_realtime():
            return
        self.queue_diplomacy_action(puppet, "TAKE_PUPPETS")

    def queue_release(self, puppet):
        if not self.can_edit_realtime():
            return
        self.queue_diplomacy_action(puppet, "RELEASE_PUPPET")

    def open_create_puppet(self):
        if not self.can_edit_realtime():
            return
        screen = Create_Puppet_Screen(self.map_screen)
        _run_pygame_sub_screen(self.map_screen, screen, on_done=self.refresh_ui)

    def draw_content(self, surface):
        self.draw_panel(surface)

        font_body = fonts.get("heading2")

        master = self.map_screen.nation_data.get(self.player, {}).get("master", "")
        if master:
            master_name = queries.get_country_display_name(
                master, self.map_screen.nation_data)
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
                    p_name = queries.get_country_display_name(
                        p, self.map_screen.nation_data)
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


class Create_Puppet_Screen(MapOverlayScreen):
    overlay_alpha = 0
    # Keep the land visible beside the release controls.
    CENTER_PANEL = False
    PANEL_BG, PANEL_BORDER, PANEL_BORDER_WIDTH = c.PANEL_THEME_INFO_OVER_MAP
    RELEASE_TYPE_Y = 60
    RELEASE_TYPE_BUTTON_SIZE = (125, 40)
    RELEASE_TYPE_BUTTON_GAP = 10
    KEEP_CORES_Y = 110
    ROW_TOP = 170
    ROW_HEIGHT = 50
    CONTENT_TOP = 160
    CONTENT_BOTTOM_GAP = 30
    TITLE_MARGIN = 20
    ROW_TEXT_WIDTH = 280
    QUEUED_TEXT_COLORS = {
        c.PUPPET_TYPE_INTEGRATED: c.COLOR_GOLD_HIGHLIGHT,
        c.PUPPET_TYPE_AUTONOMOUS: c.COLOR_SUCCESS_GREEN,
        c.PUPPET_RELEASE_INDEPENDENT: c.UI_ACCENT_BLUE,
    }

    def __init__(self, map_screen, country_id=None):
        super().__init__(map_screen, pygame.Rect(80, 120, 450, c.SCREEN_HEIGHT - 240))
        self.releasing_country = self.player if country_id is None else country_id
        self.keep_cores = False
        self.release_type = c.PUPPET_TYPE_INTEGRATED
        self.refresh_ui()

    def can_edit_realtime(self):
        if not queries.can_release_nations_for(self.map_screen, self.releasing_country):
            self.map_screen.show_feedback("You cannot release nations for this country.")
            return False
        from map_logic.diplomacy.player_diplomacy_actions import can_edit_diplomacy
        return can_edit_diplomacy(self.map_screen)

    def set_release_type(self, release_type):
        if not self.can_edit_realtime():
            return
        if release_type not in c.PUPPET_RELEASE_TYPES:
            raise ValueError("Unknown nation release type.")
        self.release_type = release_type
        self.refresh_ui()

    def toggle_keep_cores(self):
        if not self.can_edit_realtime():
            return
        self.keep_cores = not self.keep_cores
        self.refresh_ui()

    def refresh_ui(self):
        self.elements = [make_back_button(self.exit_screen, style="map")]
        name = queries.get_country_display_name(self.releasing_country, self.map_screen.nation_data)
        title_font = fonts.get("heading2")
        title = fit_text(f"Release Nations: {name}", title_font, self.panel_rect.width - 2 * self.TITLE_MARGIN)
        self.release_title = title_font.render(title, True, c.UI_TEXT_LIGHT)
        enabled = queries.can_release_nations_for(self.map_screen, self.releasing_country)
        width, height = self.RELEASE_TYPE_BUTTON_SIZE
        group_width = len(c.PUPPET_RELEASE_TYPES) * width + (len(c.PUPPET_RELEASE_TYPES) - 1) * self.RELEASE_TYPE_BUTTON_GAP
        start_x = self.panel_rect.centerx - group_width // 2
        for index, release_type in enumerate(c.PUPPET_RELEASE_TYPES):
            button = Button(start_x + index * (width + self.RELEASE_TYPE_BUTTON_GAP),
                            self.panel_rect.y + self.RELEASE_TYPE_Y, (width, height), "blue", release_type,
                            lambda value=release_type: self.set_release_type(value))
            button.apply_state(enabled=enabled, color="blue")
            button.is_selected = enabled and self.release_type == release_type
            self.elements.append(button)
        keep = Button(self.panel_rect.centerx - 100, self.panel_rect.y + self.KEEP_CORES_Y,
                      "medium", "green" if self.keep_cores else "red",
                      f"Keep Cores: {'ON' if self.keep_cores else 'OFF'}", self.toggle_keep_cores)
        keep.apply_state(enabled=enabled, color="green" if self.keep_cores else "red")
        self.elements.append(keep)

        self.scroll_content_rect = pygame.Rect(self.panel_rect.x + 5, self.panel_rect.y + self.CONTENT_TOP,
                                               self.panel_rect.width - 10,
                                               self.panel_rect.height - self.CONTENT_TOP - self.CONTENT_BOTTOM_GAP)
        queue = self.map_screen.nation_data.get(self.releasing_country, {}).get("release_puppet_queue", [])
        queued = {entry["core_nation"]: entry for entry in queue}
        self.valid_subjects = sorted({core for province in self.map_screen.map_data.values()
                                      if province.get("owner") == self.releasing_country
                                      and not queries.is_water_province(province)
                                      for core in province.get("cores", [])
                                      if core != self.releasing_country and core not in c.UNPLAYABLE_NATIONS}
                                     | set(queued))
        self.release_rows = []
        self.release_row_surfaces = []
        row_font = fonts.get("normal")
        for index, subject in enumerate(self.valid_subjects):
            name = queries.get_country_display_name(subject, self.map_screen.nation_data)
            if subject not in self.map_screen.nation_data:
                from data.io import country_io
                name = country_io.get_country_stats(subject).get("name", name)
            entry = queued.get(subject)
            available = queries.get_puppet_release_provinces(
                self.releasing_country, subject, self.map_screen.map_data, self.keep_cores, queue)
            status = f" ({entry.get('release_type', c.PUPPET_TYPE_INTEGRATED)} queued)" if entry else ""
            self.release_rows.append((name + status, entry is not None))
            row_text = fit_text(name + status, row_font, self.ROW_TEXT_WIDTH)
            text_color = (self.QUEUED_TEXT_COLORS[entry.get("release_type", c.PUPPET_TYPE_INTEGRATED)]
                          if entry else c.UI_TEXT_LIGHT)
            self.release_row_surfaces.append(row_font.render(
                row_text, True, text_color))
            y_pos = self.panel_rect.y + self.ROW_TOP + index * self.ROW_HEIGHT + self.scroll_y
            button = Button(self.panel_rect.x + 320, y_pos, "small", "red" if entry else "green",
                            "Cancel" if entry else "Release",
                            lambda value=subject, cancel=bool(entry): self.cancel_queue(value) if cancel else self.queue_creation(value))
            button.apply_state(enabled=enabled and (entry is not None or bool(available)),
                               color="red" if entry else "green",
                               text="No Land" if entry is None and not available else None)
            button.is_scrollable = True
            button.click_guard = self.content_hover_guard()
            button.base_y = y_pos - self.scroll_y
            self.elements.append(button)

        # Cache the map highlights in release order, using the same territory rule.
        self.queued_highlights = []
        colors = ((255, 105, 180), (105, 255, 180), (105, 180, 255), (255, 255, 105), (255, 150, 100))
        prior = []
        for index, entry in enumerate(queue):
            provinces = queries.get_puppet_release_provinces(
                self.releasing_country, entry["core_nation"], self.map_screen.map_data,
                entry.get("keep_cores", False), prior)
            self.queued_highlights.extend((province["id"], colors[index % len(colors)]) for province in provinces)
            prior.append(entry)
        self.max_scroll = min(0, self.scroll_content_rect.height - len(self.valid_subjects) * self.ROW_HEIGHT)

    def update(self):
        super().update()
        for element in self.elements:
            if getattr(element, "is_scrollable", False):
                element.rect.y = element.base_y + self.scroll_y

    def queue_creation(self, subject):
        if not self.can_edit_realtime():
            return
        from map_logic.diplomacy.puppet_actions import canonical_puppet_release_queue
        country = self.map_screen.nation_data[self.releasing_country]
        queue = country.get("release_puppet_queue", [])
        requested = queue + [{"core_nation": subject, "keep_cores": self.keep_cores,
                              "release_type": self.release_type}]
        try:
            canonical = canonical_puppet_release_queue(self.map_screen.map_data, self.map_screen.nation_data,
                                                        self.releasing_country, requested, queue)
        except ValueError as error:
            self.map_screen.show_feedback(str(error))
            self.refresh_ui()
            return
        country.setdefault("release_puppet_queue", [])[:] = canonical
        name = queries.get_country_display_name(subject, self.map_screen.nation_data)
        self.map_screen.show_feedback(f"{self.release_type} release of {name} queued (1 turn).")
        self.refresh_ui()

    def cancel_queue(self, subject):
        if not self.can_edit_realtime():
            return
        queue = self.map_screen.nation_data[self.releasing_country].get("release_puppet_queue", [])
        queue[:] = [entry for entry in queue if entry["core_nation"] != subject]
        self.refresh_ui()

    def draw_content(self, surface):
        for province_id, color in self.queued_highlights:
            overlay_renderer.draw_map_highlight(surface, self.map_screen, province_id, color, base_radius=10)
        self.draw_panel(surface)
        surface.blit(self.release_title, self.release_title.get_rect(
            midtop=(self.panel_rect.centerx, self.panel_rect.y + self.TITLE_Y_OFFSET)))
        font = fonts.get("normal")
        if not self.release_rows:
            surface.blit(font.render("No potential subjects available.", True, c.UI_TEXT_MUTED),
                         (self.panel_rect.x + 30, self.panel_rect.y + self.ROW_TOP))
        else:
            with ui_bars.clip_scroll_region(surface, self.scroll_content_rect,
                                            draw_top=self.scroll_y != 0, draw_bottom=self.scroll_y > self.max_scroll):
                for index, text in enumerate(self.release_row_surfaces):
                    y = self.panel_rect.y + self.ROW_TOP + index * self.ROW_HEIGHT + self.scroll_y
                    surface.blit(text, (self.panel_rect.x + 20, y + 15))
        self.draw_list_scrollbar(surface, self.panel_rect.right - 15, self.scroll_content_rect.y,
                                 self.scroll_content_rect.height, width=10)


# Preserve the older screen name for callers and mods.
Create_Integrated_Puppet_Screen = Create_Puppet_Screen


def open_puppets_menu(map_screen):
    if map_screen.player_country == "Spectator":
        if (getattr(map_screen, "multiplayer_mode", False)
                or getattr(map_screen, "realtime_multiplayer", False)
                or map_screen.is_editor or map_screen.tactical_mode):
            map_screen.show_feedback("Spectator releases are available only in a local strategic game.")
            return

        def selected(country_id):
            if queries.can_release_nations_for(map_screen, country_id):
                _run_pygame_sub_screen(map_screen, Create_Puppet_Screen(map_screen, country_id))

        countries = sorted(queries.get_living_nations(map_screen.map_data))
        queries.open_listbox_selector(map_screen, "Release Nations", "Choose a country to release nations for:",
                                      queries.country_picker_items(countries, map_screen.nation_data), selected,
                                      close_on_select=False)
        return
    _run_pygame_sub_screen(map_screen, Puppets_Screen(map_screen))
