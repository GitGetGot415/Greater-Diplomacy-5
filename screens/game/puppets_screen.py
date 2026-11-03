import pygame
import data.constants as c
from data import queries
from ui.dialogs import pickers
from ui.navigation.screen import MapOverlayScreen, Screen
from ui.widgets.ui_elements import Button, Slider, make_back_button, make_toggle_button, on_off_color
from ui.rendering.font_manager import fonts
from ui.rendering import overlay_renderer
from ui.bars import ui_bars
from ui.background_styles import PUPPET_PANEL_STYLES
from ui.navigation.screen_runner import _run_pygame_sub_screen
from ui.widgets.text_utils import fit_text, wrap_text

from data.io import country_io
from map_logic.diplomacy.player_diplomacy_actions import can_edit_diplomacy
from map_logic.diplomacy.puppet_actions import canonical_puppet_release_queue


class Puppets_Screen(Screen):
    PANEL_BG, PANEL_BORDER, PANEL_BORDER_WIDTH = c.PANEL_THEME_INFO
    PANEL_STYLE = PUPPET_PANEL_STYLES["subjects"]
    TITLE_PRESET = "heading1"
    TITLE_Y_OFFSET = 20
    PANEL_SIZE = (960, 520)
    PADDING = 24
    HEADER_HEIGHT = 84
    LIST_WIDTH = 280
    COLUMN_GAP = 24
    CONTROL_GAP = 16
    CONTROL_HEIGHT = 40
    RELEASE_BUTTON_WIDTH = 180
    ROW_HEIGHT = 60
    ROW_GAP = 6
    ROW_TEXT_PADDING = 24
    SCROLLBAR_WIDTH = 12
    SCROLLBAR_GAP = 8
    NAME_HEIGHT = 64
    STATUS_HEIGHT = 26
    RESOURCE_TOP = 146
    RESOURCE_ROW_HEIGHT = 56
    SLIDER_WIDTH = 320
    RESOURCE_TOTAL_GAP = 24
    ACTIONS = (
        ("Edit", None, "blue", "edit_puppet"),
        ("Release", "RELEASE_PUPPET", "orange", "queue_release"),
        ("Annex", "ANNEX_PUPPET", "red", "queue_annex"),
        ("Take Puppets", "TAKE_PUPPETS", "purple", "queue_take_puppets"),
    )

    def __init__(self, map_screen):
        super().__init__()
        self.map_screen = map_screen
        self.player = map_screen.player_country
        self.back_state = "MAP"
        self.bg_color = (25, 30, 40)
        self.panel_rect = pygame.Rect((0, 0), self.PANEL_SIZE)
        self.panel_rect.center = (c.SCREEN_WIDTH // 2, c.SCREEN_HEIGHT // 2)
        inner = self.panel_rect.inflate(-2 * self.PADDING, -2 * self.PADDING)
        body_top = self.panel_rect.top + self.HEADER_HEIGHT
        self.list_rect = pygame.Rect(inner.left, body_top, self.LIST_WIDTH,
                                     inner.bottom - body_top - self.CONTROL_HEIGHT - self.CONTROL_GAP)
        self.scroll_content_rect = self.list_rect
        detail_left = self.list_rect.right + self.COLUMN_GAP
        self.detail_rect = pygame.Rect(detail_left, body_top, inner.right - detail_left,
                                      inner.bottom - body_top)
        self.selected_subject = None
        self.scroll_y = 0
        self._projection = None
        self.resource_totals = []
        self.refresh_ui()

    def subjects(self):
        return self.map_screen.nation_data.get(self.player, {}).get("puppets", [])

    def owns_subject(self, subject, integrated=False):
        data = self.map_screen.nation_data.get(subject, {})
        return (self.player == self.map_screen.player_country
                and subject in self.subjects() and data.get("master") == self.player
                and (not integrated or data.get("puppet_type") == c.PUPPET_TYPE_INTEGRATED))

    def can_edit_realtime(self):
        return (not (self.map_screen.is_editor or self.map_screen.tactical_mode)
                and self.player == self.map_screen.player_country
                and queries.require_realtime_turn_open(self.map_screen, "subjects"))

    def can_edit_subject(self, subject, integrated=False):
        return self.can_edit_realtime() and self.owns_subject(subject, integrated)

    def select_subject(self, subject):
        if subject not in self.subjects() or subject == self.selected_subject:
            return
        self.selected_subject = subject
        self._projection = None
        self.refresh_ui()

    def refresh_ui(self):
        p = self.panel_rect
        header_y = p.top + self.TITLE_Y_OFFSET
        self.elements = [make_back_button(self.exit_screen, pos=(p.left + self.PADDING, header_y))]
        release = Button(p.right - self.PADDING - self.RELEASE_BUTTON_WIDTH, header_y,
                         (self.RELEASE_BUTTON_WIDTH, self.CONTROL_HEIGHT),
                         "blue", "Release Nation", self.open_create_puppet)
        editable = (not (self.map_screen.is_editor or self.map_screen.tactical_mode)
                    and self.player == self.map_screen.player_country
                    and queries.realtime_turn_open(self.map_screen))
        release.apply_state(enabled=editable and queries.can_release_nations_for(self.map_screen, self.player), color="blue")
        self.elements.append(release)
        self.master_label = None
        player_data = self.map_screen.nation_data.get(self.player, {})
        master = player_data.get("master", "")
        if master:
            font = fonts.get("normal")
            name = queries.get_country_display_name(master, self.map_screen.nation_data)
            text = f"{player_data.get('puppet_type', c.PUPPET_TYPE_AUTONOMOUS)} subject of: {name}"
            self.master_label = font.render(fit_text(text, font, p.width - 2 * self.PADDING),
                                            True, c.UI_TEXT_MUTED)

        subjects = self.subjects()
        if self.selected_subject not in subjects:
            self.selected_subject = subjects[0] if subjects else None
            self._projection = None
        self.max_scroll = min(0, self.list_rect.height - len(subjects) * self.ROW_HEIGHT)
        self.scroll_y = max(self.max_scroll, min(0, self.scroll_y))
        row_width = self.list_rect.width - self.SCROLLBAR_WIDTH - self.SCROLLBAR_GAP
        guard = self.content_hover_guard()
        font = fonts.get("normal")
        for index, subject in enumerate(subjects):
            y = self.list_rect.top + index * self.ROW_HEIGHT + self.scroll_y
            if y + self.ROW_HEIGHT <= self.list_rect.top or y >= self.list_rect.bottom:
                continue
            data = self.map_screen.nation_data.get(subject, {})
            name = queries.get_country_display_name(subject, self.map_screen.nation_data)
            label = fit_text(name, font, row_width - self.ROW_TEXT_PADDING)
            label += "\n" + data.get("puppet_type", c.PUPPET_TYPE_AUTONOMOUS)
            button = Button(self.list_rect.left, y, (row_width, self.ROW_HEIGHT - self.ROW_GAP),
                            "blue", label, lambda nation=subject: self.select_subject(nation), font_preset="normal",
                            sound_kind="select_category")
            button.text_align = "left"
            button.is_selected = subject == self.selected_subject
            button.is_scrollable = True
            button.click_guard = guard
            self.elements.append(button)

        width = (self.list_rect.width - self.CONTROL_GAP) // 2
        for column, (label, direction) in enumerate((("Move Up", -1), ("Move Down", 1))):
            button = Button(self.list_rect.left + column * (width + self.CONTROL_GAP),
                            self.detail_rect.bottom - self.CONTROL_HEIGHT, (width, self.CONTROL_HEIGHT),
                            "blue", label, lambda step=direction: self.move_selected(step), font_preset="normal")
            index = subjects.index(self.selected_subject) if self.selected_subject else -1
            button.apply_state(enabled=editable and self.owns_subject(self.selected_subject)
                               and 0 <= index + direction < len(subjects), color="blue")
            self.elements.append(button)
        self.scroll_track_rect, self.scroll_handle_rect = ui_bars.get_standard_scrollbar_rects(
            self.scroll_y, self.max_scroll, self.list_rect.right - self.SCROLLBAR_WIDTH,
            self.list_rect.top, self.list_rect.height, self.SCROLLBAR_WIDTH)
        self._prepare_details(editable)

    def _prepare_details(self, editable):
        detail = self.detail_rect
        self.detail_surface = pygame.Surface(detail.size, pygame.SRCALPHA)
        self.resource_totals = []
        subject = self.selected_subject
        font = fonts.get("normal")
        if subject is None:
            text = font.render("You currently control no subjects.", True, c.UI_TEXT_MUTED)
            self.detail_surface.blit(text, (0, 0))
            return

        data = self.map_screen.nation_data[subject]
        integrated = data.get("puppet_type") == c.PUPPET_TYPE_INTEGRATED
        name = queries.get_country_display_name(subject, self.map_screen.nation_data)
        heading = fonts.get("heading2")
        lines = wrap_text(name, heading, detail.width, break_long_words=True)
        line_height = self.NAME_HEIGHT // 2
        for index, line in enumerate(lines[:2]):
            if index == 1 and len(lines) > 2:
                line = fit_text(" ".join(lines[1:]), heading, detail.width)
            self.detail_surface.blit(heading.render(line, True, c.UI_TEXT_BRIGHT), (0, index * line_height))

        subject_count = len(data.get("puppets", []))
        info = f"{data.get('puppet_type', c.PUPPET_TYPE_AUTONOMOUS)} | Subjects: {subject_count}"
        self.detail_surface.blit(font.render(info, True, c.COLOR_GOLD_HIGHLIGHT if integrated else c.UI_TEXT_LIGHT),
                                 (0, self.NAME_HEIGHT))
        pending, turns = queries.get_diplomatic_status(self.player, subject, self.map_screen.nation_data)
        if pending:
            status = "Pending: " + pending.replace("_", " ").title()
            if turns:
                status += f" ({turns} turns)"
            self.detail_surface.blit(font.render(fit_text(status, font, detail.width), True, c.UI_TEXT_MUTED),
                                     (0, self.NAME_HEIGHT + self.STATUS_HEIGHT))

        if integrated:
            siphon = queries.get_siphon_rates(data)
            for index, resource in enumerate(c.ECON_RESOURCE_KEYS):
                slider = Slider(detail.left, detail.top + self.RESOURCE_TOP + index * self.RESOURCE_ROW_HEIGHT,
                                self.SLIDER_WIDTH, resource.title(), min(siphon[resource], c.MAX_PUPPET_SIPHON),
                                lambda value, nation=subject, key=resource: self.set_siphon(nation, key, value),
                                visual_max=c.MAX_PUPPET_SIPHON, allowed_max=c.MAX_PUPPET_SIPHON)
                slider.disabled = not (editable and self.owns_subject(subject, integrated=True))
                self.elements.append(slider)
            self._prepare_resource_totals()

        action_width = (detail.width - self.CONTROL_GAP) // 2
        actions_top = detail.bottom - 2 * self.CONTROL_HEIGHT - self.CONTROL_GAP
        for index, (label, action, color, method) in enumerate(self.ACTIONS):
            undo = action is not None and pending == action
            text = ("Undo Take" if action == "TAKE_PUPPETS" else "Undo " + label) if undo else label
            button = Button(detail.left + (index % 2) * (action_width + self.CONTROL_GAP),
                            actions_top + (index // 2) * (self.CONTROL_HEIGHT + self.CONTROL_GAP),
                            (action_width, self.CONTROL_HEIGHT), color, text,
                            lambda callback=getattr(self, method), nation=subject: callback(nation))
            allowed = self.owns_subject(subject, integrated=label != "Release")
            if action == "TAKE_PUPPETS":
                allowed = allowed and bool(subject_count)
            button.apply_state(enabled=editable and allowed, color=color)
            button.fit_text = True
            button.fit_single_line = True
            self.elements.append(button)

    def _prepare_resource_totals(self):
        # The modal pauses map processing. Selection, slider input, and return from release invalidate this cache.
        if self._projection is None:
            self._projection = queries.get_economy_projections(
                self.selected_subject, self.map_screen.map_data, self.map_screen.nation_data, context=self.map_screen)
        _, _, breakdown = self._projection
        font = fonts.get("normal")
        width = self.detail_rect.width - self.SLIDER_WIDTH - self.RESOURCE_TOTAL_GAP
        self.resource_totals = [font.render(fit_text(
            f"Taking: {queries.format_number(abs(breakdown.get(resource, {}).get('siphon', 0)))}", font, width),
            True, c.UI_TEXT_LIGHT) for resource in c.ECON_RESOURCE_KEYS]

    def set_siphon(self, puppet, res, slider_val):
        if (not self.can_edit_subject(puppet, integrated=True)
                or res not in c.ECON_RESOURCE_KEYS or not 0 <= slider_val <= c.MAX_PUPPET_SIPHON):
            return
        queries.get_siphon_rates(self.map_screen.nation_data[puppet])[res] = slider_val
        self._projection = None
        self._prepare_resource_totals()

    def move_selected(self, direction):
        subjects = self.subjects()
        if self.selected_subject in subjects:
            self.move_puppet(subjects.index(self.selected_subject), direction)

    def move_puppet(self, index, direction):
        if not self.can_edit_realtime():
            return
        puppets = self.subjects()
        new_index = index + direction
        if (0 <= index < len(puppets) and 0 <= new_index < len(puppets)
                and self.owns_subject(puppets[index])):
            puppets[index], puppets[new_index] = puppets[new_index], puppets[index]
            row_top = new_index * self.ROW_HEIGHT
            self.scroll_y = min(-row_top, max(self.scroll_y,
                self.list_rect.height - row_top - self.ROW_HEIGHT))
        self.refresh_ui()

    def edit_puppet(self, puppet):
        if not self.can_edit_subject(puppet, integrated=True):
            return
        self.map_screen.editing_country = puppet
        self.map_screen.change_state("EDIT_COUNTRY")
        self.done = True

    def queue_annex(self, puppet):
        if not self.can_edit_subject(puppet, integrated=True):
            return
        self.queue_diplomacy_action(puppet, "ANNEX_PUPPET")

    def queue_take_puppets(self, puppet):
        if (not self.can_edit_subject(puppet, integrated=True)
                or not self.map_screen.nation_data[puppet].get("puppets")):
            return
        self.queue_diplomacy_action(puppet, "TAKE_PUPPETS")

    def queue_release(self, puppet):
        if not self.can_edit_subject(puppet):
            return
        self.queue_diplomacy_action(puppet, "RELEASE_PUPPET")

    def open_create_puppet(self):
        if (not self.can_edit_realtime()
                or not queries.can_release_nations_for(self.map_screen, self.player)):
            return
        screen = Create_Puppet_Screen(self.map_screen)
        _run_pygame_sub_screen(self.map_screen, screen, on_done=self.return_from_release)

    def return_from_release(self):
        self._projection = None
        self.refresh_ui()

    def additional_events(self, event):
        if event.type == pygame.MOUSEWHEEL and not self.list_rect.collidepoint(pygame.mouse.get_pos()):
            return
        self.handle_list_scroll(event, content_rect_attr="scroll_content_rect")

    def additional_draw(self, surface):
        ui_bars.draw_screen_panel(surface, self, "Puppets")
        if self.master_label:
            surface.blit(self.master_label, self.master_label.get_rect(
                midtop=(self.panel_rect.centerx, self.list_rect.top - self.PADDING)))
        surface.blit(self.detail_surface, self.detail_rect)
        for index, label in enumerate(self.resource_totals):
            surface.blit(label, (self.detail_rect.left + self.SLIDER_WIDTH + self.RESOURCE_TOTAL_GAP,
                                 self.detail_rect.top + self.RESOURCE_TOP + index * self.RESOURCE_ROW_HEIGHT))
        self.draw_list_scrollbar(surface, self.list_rect.right - self.SCROLLBAR_WIDTH,
                                 self.list_rect.top, self.list_rect.height, self.SCROLLBAR_WIDTH)


class Create_Puppet_Screen(MapOverlayScreen):
    overlay_alpha = 0
    # Keep the land visible beside the release controls.
    CENTER_PANEL = False
    PANEL_BG, PANEL_BORDER, PANEL_BORDER_WIDTH = c.PANEL_THEME_INFO_OVER_MAP
    PANEL_STYLE = PUPPET_PANEL_STYLES["release_nations"]
    TITLE_PRESET = "heading2"
    RELEASE_TYPE_Y = 60
    RELEASE_TYPE_BUTTON_SIZE = (125, 40)
    RELEASE_TYPE_BUTTON_GAP = 10
    KEEP_CORES_Y = 110
    ROW_TOP = 170
    ROW_HEIGHT = 50
    CONTENT_TOP = 160
    CONTENT_BOTTOM_GAP = 30
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

    def get_panel_title(self):
        return "Release Nations: " + queries.get_country_display_name(
            self.releasing_country, self.map_screen.nation_data)

    def can_edit_realtime(self):
        if not queries.can_release_nations_for(self.map_screen, self.releasing_country):
            self.map_screen.show_feedback("You cannot release nations for this country.")
            return False
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
        keep = make_toggle_button(self.centered_x("medium"), self.panel_rect.y + self.KEEP_CORES_Y,
                                  "medium", "Keep Cores", self.keep_cores, self.toggle_keep_cores)
        keep.apply_state(enabled=enabled, color=on_off_color(self.keep_cores))
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
                name = country_io.get_country_stats(subject).get("name", name)
            entry = queued.get(subject)
            available = queries.get_puppet_release_provinces(
                self.releasing_country, subject, self.map_screen.map_data, self.keep_cores, queue)
            status = f" ({entry['release_type']} queued)" if entry else ""
            self.release_rows.append((name + status, entry is not None))
            row_text = fit_text(name + status, row_font, self.ROW_TEXT_WIDTH)
            text_color = (self.QUEUED_TEXT_COLORS[entry["release_type"]]
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
        if (map_screen.multiplayer_mode
                or map_screen.realtime_multiplayer
                or map_screen.is_editor or map_screen.tactical_mode):
            map_screen.show_feedback("Spectator releases are available only in a local strategic game.")
            return

        def selected(country_id):
            if queries.can_release_nations_for(map_screen, country_id):
                _run_pygame_sub_screen(map_screen, Create_Puppet_Screen(map_screen, country_id))

        countries = sorted(queries.get_living_nations(map_screen.map_data))
        pickers.open_listbox_selector(map_screen, "Release Nations", "Choose a country to release nations for:",
                                      queries.country_picker_items(countries, map_screen.nation_data), selected,
                                      close_on_select=False)
        return
    _run_pygame_sub_screen(map_screen, Puppets_Screen(map_screen))
