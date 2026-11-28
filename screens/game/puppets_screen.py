import pygame
import data.constants as c
from data import queries
from ui.dialogs import pickers
from ui.widgets import flag_icons
from ui.navigation.screen import MapOverlayScreen, Screen
from ui.widgets.ui_elements import Button, Slider, make_back_button, make_toggle_button, on_off_color
from ui.rendering.font_manager import fonts
from ui.rendering import refresh_map
from ui.bars import ui_bars
from ui.background_styles import PUPPET_PANEL_STYLES
from ui.navigation.screen_runner import _run_pygame_sub_screen
from ui.widgets.text_utils import fit_text, wrap_text

from data.io import country_io
from map_logic.diplomacy.player_diplomacy_actions import can_edit_diplomacy
from map_logic.diplomacy import puppet_actions


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
    CREATE_BUTTON_WIDTH = 180
    ROW_HEIGHT = 60
    ROW_GAP = 6
    ROW_TEXT_PADDING = 24
    ROW_FLAG_SIZE = (30, 20)
    ROW_FLAG_GAP = 10
    SCROLLBAR_WIDTH = 12
    SCROLLBAR_GAP = 8
    NAME_HEIGHT = 64
    HEADER_FLAG_SIZE = (72, 48)
    HEADER_FLAG_GAP = 16
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
        self.player = map_screen.session.player_country
        self.back_state = "MAP"
        self.bg_color = (25, 30, 40)
        self.panel_rect = pygame.Rect((0, 0), self.PANEL_SIZE)
        self.panel_rect.center = (c.SCREEN_WIDTH // 2, c.SCREEN_HEIGHT // 2)
        inner = self.panel_rect.inflate(-2 * self.PADDING, -2 * self.PADDING)
        body_top = self.panel_rect.top + self.HEADER_HEIGHT
        self.list_rect = pygame.Rect(inner.left, body_top, self.LIST_WIDTH,
                                     inner.bottom - body_top - self.CONTROL_HEIGHT - self.CONTROL_GAP)
        self.scroll.content_rect = self.list_rect
        detail_left = self.list_rect.right + self.COLUMN_GAP
        self.detail_rect = pygame.Rect(detail_left, body_top, inner.right - detail_left,
                                      inner.bottom - body_top)
        self.selected_subject = None
        self.scroll.value = 0
        self._projection = None
        self.resource_totals = []
        self.refresh_ui()

    def subjects(self):
        return self.map_screen.world.nation_data.get(self.player, {}).get("puppets", [])

    def owns_subject(self, subject, integrated=False):
        data = self.map_screen.world.nation_data.get(subject, {})
        return (self.player == self.map_screen.session.player_country
                and subject in self.subjects() and data.get("master") == self.player
                and (not integrated or data.get("puppet_type") == c.PUPPET_TYPE_INTEGRATED))

    def can_edit_realtime(self):
        return (not (self.map_screen.session.is_editor or self.map_screen.session.tactical_mode)
                and self.player == self.map_screen.session.player_country
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
        create = Button(p.right - self.PADDING - self.CREATE_BUTTON_WIDTH, header_y,
                        (self.CREATE_BUTTON_WIDTH, self.CONTROL_HEIGHT),
                        "blue", "Create Nation", self.open_create_puppet)
        editable = (not (self.map_screen.session.is_editor or self.map_screen.session.tactical_mode)
                    and self.player == self.map_screen.session.player_country
                    and queries.realtime_turn_open(self.map_screen))
        create.apply_state(enabled=editable and queries.can_release_nations_for(self.map_screen, self.player), color="blue")
        self.elements.append(create)
        self.master_label = None
        player_data = self.map_screen.world.nation_data.get(self.player, {})
        master = player_data.get("master", "")
        if master:
            font = fonts.get("normal")
            name = queries.get_country_display_name(master, self.map_screen.world.nation_data)
            text = f"{player_data.get('puppet_type', c.PUPPET_TYPE_AUTONOMOUS)} subject of: {name}"
            self.master_label = font.render(fit_text(text, font, p.width - 2 * self.PADDING),
                                            True, c.UI_TEXT_MUTED)

        subjects = self.subjects()
        if self.selected_subject not in subjects:
            self.selected_subject = subjects[0] if subjects else None
            self._projection = None
        self.scroll.limit = min(0, self.list_rect.height - len(subjects) * self.ROW_HEIGHT)
        self.scroll.value = max(self.scroll.limit, min(0, self.scroll.value))
        row_width = self.list_rect.width - self.SCROLLBAR_WIDTH - self.SCROLLBAR_GAP
        guard = self.content_hover_guard()
        font = fonts.get("normal")
        for index, subject in enumerate(subjects):
            y = self.list_rect.top + index * self.ROW_HEIGHT + self.scroll.value
            if y + self.ROW_HEIGHT <= self.list_rect.top or y >= self.list_rect.bottom:
                continue
            data = self.map_screen.world.nation_data.get(subject, {})
            name = queries.get_country_display_name(subject, self.map_screen.world.nation_data)
            text_width = row_width - self.ROW_TEXT_PADDING - self.ROW_FLAG_SIZE[0] - self.ROW_FLAG_GAP
            label = fit_text(name, font, text_width)
            label += "\n" + data.get("puppet_type", c.PUPPET_TYPE_AUTONOMOUS)
            button = Button(self.list_rect.left, y, (row_width, self.ROW_HEIGHT - self.ROW_GAP),
                            "blue", label, lambda nation=subject: self.select_subject(nation), font_preset="normal",
                            image=flag_icons.flag_surface(subject, self.map_screen.world.nation_data, self.ROW_FLAG_SIZE),
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
        self.scroll.track, self.scroll.handle = ui_bars.get_standard_scrollbar_rects(
            self.scroll.value, self.scroll.limit, self.list_rect.right - self.SCROLLBAR_WIDTH,
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

        data = self.map_screen.world.nation_data[subject]
        integrated = data.get("puppet_type") == c.PUPPET_TYPE_INTEGRATED
        name = queries.get_country_display_name(subject, self.map_screen.world.nation_data)
        heading = fonts.get("heading2")
        flag = flag_icons.flag_surface(subject, self.map_screen.world.nation_data, self.HEADER_FLAG_SIZE)
        self.detail_surface.blit(flag, (0, (self.NAME_HEIGHT - flag.get_height()) // 2))
        name_x = self.HEADER_FLAG_SIZE[0] + self.HEADER_FLAG_GAP
        name_width = detail.width - name_x
        lines = wrap_text(name, heading, name_width, break_long_words=True)
        line_height = self.NAME_HEIGHT // 2
        for index, line in enumerate(lines[:2]):
            if index == 1 and len(lines) > 2:
                line = fit_text(" ".join(lines[1:]), heading, name_width)
            self.detail_surface.blit(heading.render(line, True, c.UI_TEXT_BRIGHT), (name_x, index * line_height))

        subject_count = len(data.get("puppets", []))
        info = f"{data.get('puppet_type', c.PUPPET_TYPE_AUTONOMOUS)} | Subjects: {subject_count}"
        self.detail_surface.blit(font.render(info, True, c.COLOR_GOLD_HIGHLIGHT if integrated else c.UI_TEXT_LIGHT),
                                 (0, self.NAME_HEIGHT))
        pending, turns = queries.get_diplomatic_status(self.player, subject, self.map_screen.world.nation_data)
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
                self.selected_subject, self.map_screen.world.map_data, self.map_screen.world.nation_data, context=self.map_screen)
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
        queries.get_siphon_rates(self.map_screen.world.nation_data[puppet])[res] = slider_val
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
            self.scroll.value = min(-row_top, max(self.scroll.value,
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
                or not self.map_screen.world.nation_data[puppet].get("puppets")):
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
        self.handle_list_scroll(event, content=True)

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
    # Keep the land visible beside the nation creation controls.
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
    ROW_DIVIDER_COLOR = (80, 85, 95)
    CONTENT_TOP = 160
    CONTENT_BOTTOM_GAP = 30
    ROW_TEXT_WIDTH = 272
    ROW_BUTTON_SIZE = (64, 42)
    ROW_BUTTON_GAP = 4
    ROW_BUTTON_HOVER_LIGHTEN = 20
    ROW_ACTION_LABELS = {
        puppet_actions.RELEASE_RESTORE: "Spawn",
        puppet_actions.RELEASE_ADD_LAND: "Add Land",
        puppet_actions.RELEASE_RETURN_LAND: "Return Land",
        puppet_actions.RELEASE_CREATE: "Create Seperate",
    }
    RELEASE_TYPE_COLORS = {
        c.PUPPET_TYPE_INTEGRATED: c.COLOR_GOLD_HIGHLIGHT,
        c.PUPPET_TYPE_AUTONOMOUS: c.COLOR_SUCCESS_GREEN,
        c.PUPPET_RELEASE_INDEPENDENT: c.UI_ACCENT_BLUE,
    }
    RELEASE_COLORS = ((255, 105, 180), (105, 255, 180), (105, 180, 255), (255, 255, 105), (255, 150, 100))

    def __init__(self, map_screen, country_id=None):
        super().__init__(map_screen, pygame.Rect(80, 120, 450, c.SCREEN_HEIGHT - 240))
        self.releasing_country = self.player if country_id is None else country_id
        self.keep_cores = False
        self.release_type = c.PUPPET_TYPE_INTEGRATED
        self._preview_inputs = None
        self.refresh_ui()

    def get_panel_title(self):
        return "Create Nation: " + queries.get_country_display_name(
            self.releasing_country, self.map_screen.world.nation_data)

    def can_edit_realtime(self):
        if not queries.can_release_nations_for(self.map_screen, self.releasing_country):
            self.map_screen.show_feedback("You cannot create nations from this country.")
            return False
        return can_edit_diplomacy(self.map_screen)

    def set_release_type(self, release_type):
        if not self.can_edit_realtime():
            return
        if release_type not in c.PUPPET_RELEASE_TYPES:
            raise ValueError("Unknown nation creation type.")
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

        self.scroll.content_rect = pygame.Rect(self.panel_rect.x + 5, self.panel_rect.y + self.CONTENT_TOP,
                                               self.panel_rect.width - 10,
                                               self.panel_rect.height - self.CONTENT_TOP - self.CONTENT_BOTTOM_GAP)
        world = self.map_screen.world
        queue = world.nation_data.get(self.releasing_country, {}).get("release_puppet_queue", [])
        queued = {entry["core_nation"]: entry for entry in queue}
        self.valid_subjects = sorted(queries.puppet_release_candidates(self.releasing_country, world.map_data,
                                                                       world.nation_data) | set(queued))
        plans, reserved = puppet_actions.queued_puppet_release_plans(world.map_data, world.nation_data,
                                                                    self.releasing_country, queue)
        self.refresh_preview(queue, plans)
        self.scroll.limit = min(0, self.scroll.content_rect.height - len(self.valid_subjects) * self.ROW_HEIGHT)
        self.scroll.value = max(self.scroll.limit, min(0, self.scroll.value))

        self.release_row_surfaces = []
        row_font = fonts.get("normal")
        detail_font = fonts.get("small")
        button_width, button_height = self.ROW_BUTTON_SIZE
        create_x = self.panel_rect.right - button_width - 20
        primary_x = create_x - button_width - self.ROW_BUTTON_GAP
        for index, subject in enumerate(self.valid_subjects):
            entry = queued.get(subject)
            release_type = entry["release_type"] if entry else self.release_type
            plan = plans[subject] if entry else self.plan_release(subject, reserved)
            choose_recipient = not entry and len(plan.matching_subjects) > 1
            display_country = subject if choose_recipient else plan.country or subject
            name = queries.get_country_display_name(display_country, world.nation_data, use_library=True)
            y = self.panel_rect.y + self.ROW_TOP + index * self.ROW_HEIGHT + (self.ROW_HEIGHT - button_height) // 2
            detail = self.release_description(plan, release_type)
            release_color = self.RELEASE_TYPE_COLORS[release_type]
            text_color = release_color if entry else c.UI_TEXT_LIGHT
            destination = entry.get("destination") if entry else None
            cancel_on_right = isinstance(destination, dict) and destination.get("action") == puppet_actions.RELEASE_CREATE
            primary_action = plan.blocked_action if cancel_on_right else plan.action or plan.blocked_action
            primary_label = self.ROW_ACTION_LABELS.get(primary_action, "Release").replace(" Land", "\nLand")
            create_label = self.ROW_ACTION_LABELS[puppet_actions.RELEASE_CREATE].replace(" ", "\n")
            primary_callback = create_callback = None

            if entry:
                if not plan.action and isinstance(destination, dict):
                    action = self.ROW_ACTION_LABELS.get(destination.get("action"), "Release")
                    target = queries.get_country_display_name(destination.get("country") or subject,
                                                              world.nation_data, use_library=True)
                    name = f"{action} {target}"
                cancel = lambda value=subject: self.cancel_queue(value)
                if cancel_on_right:
                    create_label, create_callback = "Cancel", cancel
                else:
                    primary_label, primary_callback = "Cancel", cancel
            else:
                separate = plan.separate_destination()
                if choose_recipient:
                    primary_callback = lambda value=subject, options=plan: self.choose_release_recipient(value, options)
                elif plan.action:
                    primary_callback = lambda value=subject, target=plan.destination(): self.queue_creation(value, target)
                if separate:
                    create_callback = lambda value=subject, target=separate: self.queue_creation(value, target)
                    if not plan.action:
                        detail = f"{plan.reason} {self.release_count(plan)}."

            self.add_release_button(primary_x, y, primary_label, primary_callback, enabled and primary_callback is not None,
                                    release_color, cancel=bool(entry) and not cancel_on_right)
            self.add_release_button(create_x, y, create_label, create_callback, enabled and create_callback is not None,
                                    release_color, cancel=cancel_on_right, font_preset="button_small" if cancel_on_right else "small")

            self.release_row_surfaces.append((
                row_font.render(fit_text(name, row_font, self.ROW_TEXT_WIDTH), True, text_color),
                detail_font.render(fit_text(detail, detail_font, self.ROW_TEXT_WIDTH), True, text_color),
            ))

    def plan_release(self, subject, reserved):
        world = self.map_screen.world
        return puppet_actions.plan_puppet_release(world.map_data, world.nation_data, self.releasing_country, subject,
                                                  self.release_type, self.keep_cores, reserved=reserved)

    def choose_release_recipient(self, subject, plan):
        if not self.can_edit_realtime():
            return

        def selected(country):
            self.queue_creation(subject, {"action": puppet_actions.RELEASE_ADD_LAND, "country": country})

        items = queries.country_picker_items(plan.matching_subjects, self.map_screen.world.nation_data)
        pickers.open_listbox_selector(self, "Add Land", f"Transfer {self.release_count(plan)}. Select the recipient.", items, selected)

    def add_release_button(self, x, y, label, callback, enabled, release_color, *, cancel=False, font_preset="button_small"):
        palette = "red" if cancel else "grey"
        button = Button(x, y + self.scroll.value, self.ROW_BUTTON_SIZE, palette, label, callback, font_preset=font_preset)
        button.apply_state(enabled=enabled, color=palette)
        if enabled and not cancel:
            hover_color = tuple(min(255, channel + self.ROW_BUTTON_HOVER_LIGHTEN) for channel in release_color)
            button.set_colors(release_color, hover_color)
        button.is_scrollable = True
        button.click_guard = self.content_hover_guard()
        button.base_y = y
        self.elements.append(button)

    @staticmethod
    def release_count(plan):
        count = len(plan.provinces)
        return f"{count} {'province' if count == 1 else 'provinces'}"

    def release_description(self, plan, release_type):
        if not plan.action:
            return plan.reason
        kind = f" · {release_type}" if plan.action != puppet_actions.RELEASE_RETURN_LAND else ""
        return f"{self.ROW_ACTION_LABELS[plan.action]} · {self.release_count(plan)}{kind}"

    def refresh_preview(self, queue, plans):
        if not queue:
            self._preview_inputs = None
            self.preview_map = None
            return
        world = self.map_screen.world
        master = self.releasing_country
        master_color = world.nation_data.get(master, {}).get("color", country_io.DEFAULT_NATION_COLOR)[:3]
        palette = sorted(self.RELEASE_COLORS, reverse=True,
                         key=lambda color: sum((channel - base) ** 2 for channel, base in zip(color, master_color)))
        colors = {entry["core_nation"]: palette[index % len(palette)] for index, entry in enumerate(queue)}
        owner_colors = {master: master_color}
        transfers = {}
        for subject, plan in plans.items():
            if not plan.action:
                continue
            owner = plan.country or ("release", subject)
            owner_colors.setdefault(owner, colors[subject])
            transfers.update((province["id"], owner) for province in plan.provinces)
        if not transfers:
            self._preview_inputs = None
            self.preview_map = None
            return

        inputs = (self.map_screen.id_map, self.map_screen._presentation_cache_revision, owner_colors, transfers)
        if inputs == self._preview_inputs:
            return
        self.preview_map = refresh_map.build_ownership_preview_map(self.map_screen, owner_colors, transfers)
        self._preview_inputs = inputs

    def update(self):
        super().update()
        for element in self.elements:
            if getattr(element, "is_scrollable", False):
                element.rect.y = element.base_y + self.scroll.value

    def queue_creation(self, subject, destination=None):
        if not self.can_edit_realtime():
            return
        country = self.map_screen.world.nation_data[self.releasing_country]
        queue = country.get("release_puppet_queue", [])
        order = {"core_nation": subject, "keep_cores": self.keep_cores, "release_type": self.release_type}
        if destination is not None:
            order["destination"] = destination
        try:
            canonical = puppet_actions.canonical_puppet_release_queue(
                self.map_screen.world.map_data, self.map_screen.world.nation_data,
                self.releasing_country, queue + [order], queue)
        except ValueError as error:
            self.map_screen.show_feedback(str(error))
            self.refresh_ui()
            return
        country.setdefault("release_puppet_queue", [])[:] = canonical
        self.map_screen.show_feedback("Release queued (1 turn).")
        self.refresh_ui()

    def cancel_queue(self, subject):
        if not self.can_edit_realtime():
            return
        queue = self.map_screen.world.nation_data[self.releasing_country].get("release_puppet_queue", [])
        queue[:] = [entry for entry in queue if entry["core_nation"] != subject]
        self.refresh_ui()

    def draw_overlay_map(self, surface):
        if self.preview_map is None:
            super().draw_overlay_map(surface)
        else:
            refresh_map.draw_ownership_preview_map(surface, self.map_screen, self.preview_map, show_names=False)

    def draw_content(self, surface):
        self.draw_panel(surface)
        if not self.valid_subjects:
            font = fonts.get("normal")
            surface.blit(font.render("No nations available to create.", True, c.UI_TEXT_MUTED),
                         (self.panel_rect.x + 30, self.panel_rect.y + self.ROW_TOP))
        else:
            with ui_bars.clip_scroll_region(surface, self.scroll.content_rect,
                                            draw_top=self.scroll.value != 0, draw_bottom=self.scroll.value > self.scroll.limit):
                for index, (name, detail) in enumerate(self.release_row_surfaces):
                    y = self.panel_rect.y + self.ROW_TOP + index * self.ROW_HEIGHT + self.scroll.value
                    surface.blit(name, (self.panel_rect.x + 20, y + 3))
                    surface.blit(detail, (self.panel_rect.x + 20, y + 24))
                    if index < len(self.release_row_surfaces) - 1:
                        divider_y = y + self.ROW_HEIGHT - 1
                        pygame.draw.line(surface, self.ROW_DIVIDER_COLOR,
                                         (self.panel_rect.left + 20, divider_y), (self.panel_rect.right - 20, divider_y))
        self.draw_list_scrollbar(surface, self.panel_rect.right - 15, self.scroll.content_rect.y,
                                 self.scroll.content_rect.height, width=10)


# Preserve the older screen name for callers and mods.
Create_Integrated_Puppet_Screen = Create_Puppet_Screen


def open_puppets_menu(map_screen):
    if map_screen.session.player_country == "Spectator":
        if (map_screen.session.is_networked
                or map_screen.session.is_editor or map_screen.session.tactical_mode):
            map_screen.show_feedback("Spectators can create nations only in a local strategic game.")
            return

        def selected(country_id):
            if queries.can_release_nations_for(map_screen, country_id):
                _run_pygame_sub_screen(map_screen, Create_Puppet_Screen(map_screen, country_id))

        countries = sorted(queries.get_living_nations(map_screen.world.map_data))
        pickers.open_listbox_selector(map_screen, "Create Nation", "Choose a country to create a nation from:",
                                      queries.country_picker_items(countries, map_screen.world.nation_data), selected,
                                      close_on_select=False)
        return
    _run_pygame_sub_screen(map_screen, Puppets_Screen(map_screen))
