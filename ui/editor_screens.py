"""Native pygame replacements for the map editor's tkinter tool windows.

Each class here is a MapOverlayScreen launched with _run_pygame_sub_screen,
mirroring the pattern already established in ui/player_diplomacy_menus.py for
the diplomacy popups. Everything the map editor's bottom/side bars open lives
here, has become a TableScreen, or -- for the scripted events editor -- has its
own module.
"""
import pygame
import data.constants as c
from data import queries
from gameState import MapOverlayScreen
from ui_elements import Button, TextField
from ui import confirm_dialog
from ui.bars import ui_bars
from ui.player_diplomacy_menus import _run_pygame_sub_screen
from ui.table_screen import truncate
from map_logic.rendering.font_manager import fonts
from map_logic.diplomacy.diplomacy_agreements import assign_puppet

# ==========================================
# SET START DATE
# ==========================================

class Editor_Date_Screen(MapOverlayScreen):
    pans_camera = False

    def __init__(self, map_screen):
        super().__init__(map_screen, pygame.Rect(0, 0, 440, 420))
        self.panel_rect.center = (c.SCREEN_WIDTH // 2, c.SCREEN_HEIGHT // 2)
        self.back_state = "MAP"

        tm = map_screen.time_manager
        field_x = self.panel_rect.centerx - 30
        field_w, field_h = 160, 40
        self.day_field = TextField(field_x, 0, field_w, field_h, str(tm.day), numeric=True, label="Day (1-30):")
        self.month_field = TextField(field_x, 0, field_w, field_h, str(tm.month_index + 1), numeric=True, label="Month (1-12):")
        self.year_field = TextField(field_x, 0, field_w, field_h, str(tm.year), numeric=True, label="Year:")
        dpt = queries.get_days_per_turn(map_screen.scenario_settings)
        self.dpt_field = TextField(field_x, 0, field_w, field_h, str(dpt), numeric=True, label="Days/Turn:")

        self.refresh_ui()

    def refresh_ui(self):
        p = self.panel_rect
        self.day_field.rect.topleft = (p.centerx - 30, p.y + 80)
        self.month_field.rect.topleft = (p.centerx - 30, p.y + 150)
        self.year_field.rect.topleft = (p.centerx - 30, p.y + 220)
        self.dpt_field.rect.topleft = (p.centerx - 30, p.y + 290)

        self.elements = [
            Button(50, c.TOP_BAR_UI_CENTER_Y, "small", "red", "Back", self.exit_screen),
            Button(p.centerx - 90, p.bottom - 55, "medium", "orange", "Apply Date", self.apply_date),
            self.day_field, self.month_field, self.year_field, self.dpt_field,
        ]

    def apply_date(self):
        try:
            d = int(self.day_field.text)
            m = int(self.month_field.text) - 1
            y = int(self.year_field.text)
            b_dpt = int(self.dpt_field.text)
        except ValueError:
            confirm_dialog.show_error("Error", "Please enter valid integers.")
            return

        if not (1 <= d <= 30):
            confirm_dialog.show_error("Error", "Day must be between 1 and 30.")
            return
        if not (0 <= m <= 11):
            confirm_dialog.show_error("Error", "Month must be between 1 and 12.")
            return
        if b_dpt <= 0:
            confirm_dialog.show_error("Error", "Days per turn must be positive.")
            return

        tm = self.map_screen.time_manager
        tm.day, tm.month_index, tm.year = d, m, y
        self.map_screen.scenario_settings["base_days_per_turn"] = b_dpt
        self.map_screen.scenario_settings["days_per_turn"] = "Default"
        queries.save_scenario_settings(self.map_screen.scenario_settings)
        self.map_screen.show_feedback("Date & Turn Rate set!")
        self.done = True

    def draw_content(self, surface):
        ui_bars.draw_modal_box(surface, self.panel_rect, bg_color=(40, 40, 40), border_color=(255, 152, 0), border_width=2)
        ui_bars.draw_centered_title(surface, "Set Start Date", self.panel_rect.y + 20, "heading2")

# ==========================================
# STARTING ECONOMY EDITOR
# ==========================================

class Starting_Economy_Edit_Screen(MapOverlayScreen):
    pans_camera = False

    def __init__(self, map_screen, country_id):
        super().__init__(map_screen, pygame.Rect(0, 0, 400, 360))
        self.panel_rect.center = (c.SCREEN_WIDTH // 2, c.SCREEN_HEIGHT // 2)
        self.back_state = "MAP"
        self.country_id = country_id

        data = map_screen.nation_data.get(country_id, {})
        self.fields = {}
        for res in c.ECON_RESOURCE_KEYS:
            self.fields[res] = TextField(0, 0, 160, 40, str(int(data.get(res, 0))), numeric=True,
                                         label=f"{res.capitalize()}:")

        self.refresh_ui()

    def refresh_ui(self):
        p = self.panel_rect
        y = p.y + 90
        for field in self.fields.values():
            field.rect.topleft = (p.centerx - 20, y)
            y += 60

        self.elements = [
            Button(50, c.TOP_BAR_UI_CENTER_Y, "small", "red", "Back", self.exit_screen),
            Button(p.centerx - 100, p.bottom - 55, "medium", "green", "Save Economy", self.save),
        ] + list(self.fields.values())

    def save(self):
        data = self.map_screen.nation_data.get(self.country_id)
        if data:
            for res, field in self.fields.items():
                try:
                    data[res] = int(field.text)
                except ValueError:
                    pass
            self.map_screen.show_feedback(f"Saved economy for {self.country_id}")
        self.done = True

    def draw_content(self, surface):
        ui_bars.draw_modal_box(surface, self.panel_rect, bg_color=(30, 40, 30), border_color=(33, 150, 243), border_width=2)
        ui_bars.draw_centered_title(surface, f"{self.country_id} Economy", self.panel_rect.y + 20, "heading2")

class Starting_Economy_List_Screen(MapOverlayScreen):
    pans_camera = False
    scroll_anywhere = True

    def __init__(self, map_screen):
        super().__init__(map_screen, pygame.Rect(0, 0, 620, 560))
        self.panel_rect.center = (c.SCREEN_WIDTH // 2, c.SCREEN_HEIGHT // 2)
        self.back_state = "MAP"
        self.active_countries = sorted(queries.get_living_nations(map_screen.map_data))
        self.refresh_ui()

    def refresh_ui(self):
        p = self.panel_rect
        self.elements = [
            Button(50, c.TOP_BAR_UI_CENTER_Y, "small", "red", "Back", self.exit_screen),
            Button(p.right - 120, p.y + 20, "small", "red", "Reset All", self.reset_all),
        ]

        row_top = p.y + 90
        view_h = p.height - 110
        row_x = p.centerx - (c.SIZES["list_row"][0] // 2)
        cull_top, cull_bottom = p.y + 80, p.bottom - 20
        self.scroll_content_rect = pygame.Rect(p.x, cull_top, p.width, cull_bottom - cull_top)
        for i, y in self.layout_list_rows(len(self.active_countries), 40, row_top, view_h=view_h,
                                          cull_top=cull_top, cull_bottom=cull_bottom):
            cid = self.active_countries[i]
            is_modified = any(self.map_screen.nation_data.get(cid, {}).get(res, 0) != 0 for res in c.ECON_RESOURCE_KEYS)
            label = f"[MODIFIED] {cid}" if is_modified else cid
            btn = Button(row_x, y, "list_row", "blue", label, lambda cc=cid: self.edit(cc))
            btn.is_scrollable = True
            btn.click_guard = self.scroll_click_guard
            self.elements.append(btn)

        self.list_view_h = view_h

    def edit(self, cid):
        _run_pygame_sub_screen(self.map_screen, Starting_Economy_Edit_Screen(self.map_screen, cid), on_done=self.refresh_ui)

    def reset_all(self):
        def on_confirm(ok):
            if not ok:
                return
            for cid in self.active_countries:
                if cid in self.map_screen.nation_data:
                    for res in c.ECON_RESOURCE_KEYS:
                        self.map_screen.nation_data[cid][res] = 0
            self.map_screen.show_feedback("Reset starting economy for all nations!")
            self.done = True

        confirm_dialog.ask_yes_no("Confirm Reset", "Are you sure you want to reset every starting economy to 0?", on_confirm)

    def draw_content(self, surface):
        ui_bars.draw_modal_box(surface, self.panel_rect, bg_color=(30, 40, 30), border_color=(76, 175, 80), border_width=2)
        ui_bars.draw_centered_title(surface, "Starting Economy Editor", self.panel_rect.y + 20, "heading2")
        self.draw_list_scrollbar(surface, self.panel_rect.right - 15, self.panel_rect.y + 90, self.list_view_h)

# ==========================================
# MAP RESEARCH (TECH) EDITOR
# ==========================================

class Research_Edit_Screen(MapOverlayScreen):
    """Shared editor for a single country, all countries in bulk, or the map default."""
    pans_camera = False
    scroll_anywhere = True
    ROW_HEIGHT = 36

    def __init__(self, map_screen, screen_title, base_data, tech_tree, on_save):
        super().__init__(map_screen, pygame.Rect(0, 0, 640, c.SCREEN_HEIGHT - 100))
        self.panel_rect.center = (c.SCREEN_WIDTH // 2, c.SCREEN_HEIGHT // 2)
        self.back_state = "MAP"
        self.screen_title = screen_title
        self.tech_tree = tech_tree
        self.on_save = on_save

        # tech -> ("checkbox", bool) or ("entry", str, max_lvl)
        self.tech_state = {}
        for tech, val in base_data.items():
            max_lvl = tech_tree.get(tech, {}).get("max_lvl", 1)
            if max_lvl == 1:
                self.tech_state[tech] = ("checkbox", val >= 1)
            else:
                self.tech_state[tech] = ("entry", str(val), max_lvl)
        self.techs = sorted(self.tech_state.keys())

        self.refresh_ui()

    def toggle_checkbox(self, tech):
        self.tech_state[tech] = ("checkbox", not self.tech_state[tech][1])
        self.refresh_ui()

    def _sync_entries(self):
        """Pulls live text out of on-screen entry fields before they get rebuilt or saved."""
        for el in self.elements:
            tech = getattr(el, "tech_key", None)
            if tech is not None:
                _, _, max_lvl = self.tech_state[tech]
                self.tech_state[tech] = ("entry", el.text, max_lvl)

    def refresh_ui(self):
        self._sync_entries()
        p = self.panel_rect
        self.elements = [
            Button(50, c.TOP_BAR_UI_CENTER_Y, "small", "red", "Back", self.exit_screen),
            Button(p.right - 170, p.bottom - 55, "medium", "green", "Save", self.save),
        ]

        row_top = p.y + 70
        view_h = p.height - 140
        cull_top, cull_bottom = p.y + 60, p.bottom - 70
        self.scroll_content_rect = pygame.Rect(p.x + 5, cull_top, p.width - 10, cull_bottom - cull_top)
        for i, y in self.layout_list_rows(len(self.techs), self.ROW_HEIGHT, row_top, view_h=view_h,
                                          cull_top=cull_top, cull_bottom=cull_bottom):
            tech = self.techs[i]
            kind = self.tech_state[tech]
            if kind[0] == "checkbox":
                checked = kind[1]
                btn = Button(p.right - 100, y, "tiny_square", "green" if checked else "grey",
                            "ON" if checked else "OFF", lambda t=tech: self.toggle_checkbox(t), font_preset="tiny")
                btn.is_scrollable = True
                btn.click_guard = self.scroll_click_guard
                self.elements.append(btn)
            else:
                _, text, _max_lvl = kind
                field = TextField(p.right - 160, y, 100, 30, text, numeric=True)
                field.tech_key = tech
                field.is_scrollable = True
                field.click_guard = self.scroll_click_guard
                self.elements.append(field)

        self.list_view_h = view_h

    def save(self):
        self._sync_entries()
        new_data = {}
        for tech, state in self.tech_state.items():
            if state[0] == "checkbox":
                new_data[tech] = 1 if state[1] else 0
            else:
                _, text, max_lvl = state
                try:
                    val = int(text)
                except ValueError:
                    val = 0
                new_data[tech] = max(0, min(val, max_lvl))
        self.on_save(new_data)
        self.done = True

    def draw_content(self, surface):
        p = self.panel_rect
        ui_bars.draw_modal_box(surface, p, bg_color=(30, 30, 45), border_color=(255, 152, 0), border_width=2)
        ui_bars.draw_centered_title(surface, self.screen_title, p.y + 15, "heading2")

        font = fonts.get("normal")
        small_font = fonts.get("small")
        row_top = p.y + 70
        view_h = p.height - 140
        clip_rect = self.scroll_content_rect or pygame.Rect(p.x + 5, p.y + 60, p.width - 10, p.height - 140)

        with ui_bars.clip_scroll_region(surface, clip_rect,
                                        draw_top=self.scroll_y != 0, draw_bottom=self.scroll_y > self.max_scroll):
            for i, y in self.layout_list_rows(len(self.techs), self.ROW_HEIGHT, row_top, view_h=view_h,
                                              cull_top=p.y + 60, cull_bottom=p.bottom - 70):
                tech = self.techs[i]
                label = font.render(tech.replace("_", " ").title(), True, (220, 220, 220))
                surface.blit(label, (p.x + 20, y + 4))

                kind = self.tech_state[tech]
                if kind[0] == "entry":
                    hint = small_font.render(f"(0-{kind[2]})", True, (150, 150, 150))
                    surface.blit(hint, (p.right - 250, y + 8))

        surface.set_clip(old_clip)
        self.draw_list_scrollbar(surface, p.right - 15, p.y + 60, view_h)

class Research_List_Screen(MapOverlayScreen):
    pans_camera = False
    scroll_anywhere = True

    def __init__(self, map_screen):
        super().__init__(map_screen, pygame.Rect(0, 0, 500, c.SCREEN_HEIGHT - 120))
        self.panel_rect.center = (c.SCREEN_WIDTH // 2, c.SCREEN_HEIGHT // 2)
        self.back_state = "MAP"
        self.active_countries = sorted(queries.get_living_nations(map_screen.map_data))
        self.default_research = self._get_default_research()
        self.refresh_ui()

    def _get_default_research(self):
        map_screen = self.map_screen
        struct = queries.get_tech_tree()
        fresh_template = {tech: (1800 if data["max_lvl"] == 9999 else 0) for tech, data in struct.items()}
        if "infantry_type" in fresh_template: fresh_template["infantry_type"] = 1
        if "cavalry" in fresh_template: fresh_template["cavalry"] = 1

        if getattr(map_screen, "default_research", None) is not None:
            for k, v in fresh_template.items():
                if k not in map_screen.default_research:
                    map_screen.default_research[k] = v
            obsolete_keys = [k for k in map_screen.default_research.keys() if k not in fresh_template]
            for k in obsolete_keys:
                del map_screen.default_research[k]
            return map_screen.default_research

        return fresh_template

    def refresh_ui(self):
        p = self.panel_rect
        self.elements = [
            Button(50, c.TOP_BAR_UI_CENTER_Y, "small", "red", "Back", self.exit_screen),
            Button(p.x + 20, p.y + 60, "medium", "red", "Edit ALL (Bulk)", self.edit_all),
            Button(p.right - 220, p.y + 60, "medium", "orange", "Edit Map Default", self.edit_default),
            Button(p.centerx - 200, p.y + 115, "FTAP", "green", "Force Time-Appropriate Research",
                  self.force_time_appropriate),
        ]

        row_top = p.y + 170
        view_h = p.height - 190
        row_x = p.x + 20
        row_w = p.width - 40
        cull_top, cull_bottom = p.y + 160, p.bottom - 20
        self.scroll_content_rect = pygame.Rect(p.x, cull_top, p.width, cull_bottom - cull_top)
        for i, y in self.layout_list_rows(len(self.active_countries), 40, row_top, view_h=view_h,
                                          cull_top=cull_top, cull_bottom=cull_bottom):
            cid = self.active_countries[i]
            c_res = self.map_screen.nation_data.get(cid, {}).get("research", {})
            is_diff = any(c_res.get(k, v) != v for k, v in self.default_research.items())
            label = f"[MODIFIED] {cid}" if is_diff else cid
            btn = Button(row_x, y, "list_row", "blue", label, lambda cc=cid: self.edit_country(cc))
            btn.rect.width = row_w
            btn.is_scrollable = True
            btn.click_guard = self.scroll_click_guard
            self.elements.append(btn)

        self.list_view_h = view_h

    def _open_editor(self, title, base_data, on_save):
        for k, v in self.default_research.items():
            base_data.setdefault(k, v)
        screen = Research_Edit_Screen(self.map_screen, title, base_data, queries.get_tech_tree(), on_save)
        _run_pygame_sub_screen(self.map_screen, screen, on_done=self.refresh_ui)

    def edit_country(self, cid):
        base_data = dict(self.map_screen.nation_data.get(cid, {}).get("research", self.default_research))

        def save(new_data):
            nd = self.map_screen.nation_data[cid]
            nd.setdefault("research", {}).update(new_data)
            self.map_screen.show_feedback(f"Saved research for {cid}")

        self._open_editor(cid, base_data, save)

    def edit_all(self):
        base_data = self.default_research.copy()

        def save(new_data):
            self.map_screen.default_research = new_data.copy()
            self.default_research = new_data.copy()
            for cid in self.active_countries:
                self.map_screen.nation_data[cid].setdefault("research", {}).update(new_data)
            self.map_screen.show_feedback("Saved research for ALL & Set Default")

        self._open_editor("ALL COUNTRIES", base_data, save)

    def edit_default(self):
        base_data = self.default_research.copy()

        def save(new_data):
            self.map_screen.default_research = new_data.copy()
            self.default_research = new_data.copy()
            self.map_screen.show_feedback("Updated Map Default Tech")

        self._open_editor("MAP DEFAULT", base_data, save)

    def force_time_appropriate(self):
        current_year = getattr(self.map_screen.time_manager, "year", c.START_YEAR)
        msg = (
            f"This will reset and edit the research of ALL nations on the map to match "
            f"the time-appropriate research levels for year {current_year} (the current year of this map), "
            f"exactly as if a random scenario was created in {current_year}.\n\n"
            f"Are you sure you want to force time-appropriate research for all nations?"
        )

        def on_confirm(ok):
            if not ok:
                return
            time_app_res = queries.get_time_appropriate_research(current_year)
            self.map_screen.default_research = time_app_res.copy()
            self.default_research = time_app_res.copy()
            for cid in self.active_countries:
                self.map_screen.nation_data[cid]["research"] = time_app_res.copy()
            self.map_screen.show_feedback(f"Forced Time Appropriate Research for {current_year}")
            self.refresh_ui()

        confirm_dialog.ask_yes_no("Force Time Appropriate Research", msg, on_confirm)

    def draw_content(self, surface):
        p = self.panel_rect
        ui_bars.draw_modal_box(surface, p, bg_color=(30, 30, 45), border_color=(255, 152, 0), border_width=2)
        ui_bars.draw_centered_title(surface, "Map Research Editor", p.y + 20, "heading2")
        self.draw_list_scrollbar(surface, p.right - 15, p.y + 170, self.list_view_h)

# ==========================================
# CONVOY / TRUCK CONVERTER
# ==========================================

class Convoy_Converter_Screen(MapOverlayScreen):
    pans_camera = False
    scroll_anywhere = True

    def __init__(self, map_screen, province):
        super().__init__(map_screen, pygame.Rect(0, 0, 560, c.SCREEN_HEIGHT - 160))
        self.panel_rect.center = (c.SCREEN_WIDTH // 2, c.SCREEN_HEIGHT // 2)
        self.back_state = "MAP"
        self.province = province
        self.unit_lib = queries.get_unit_library()
        self.selected = {i for i, unit in enumerate(province.get("units", [])) if "original_type" in unit}
        self.refresh_ui()

    def toggle(self, idx):
        if idx in self.selected:
            self.selected.discard(idx)
        else:
            self.selected.add(idx)
        self.refresh_ui()

    def refresh_ui(self):
        p = self.panel_rect
        self.elements = [
            Button(50, c.TOP_BAR_UI_CENTER_Y, "small", "red", "Back", self.exit_screen),
            Button(p.centerx - 110, p.bottom - 55, "medium", "green", "Save Changes", self.save),
        ]

        units = self.province.get("units", [])
        row_top = p.y + 70
        view_h = p.height - 140
        row_x = p.x + 20
        row_w = p.width - 40
        cull_top, cull_bottom = p.y + 60, p.bottom - 70
        self.scroll_content_rect = pygame.Rect(p.x, cull_top, p.width, cull_bottom - cull_top)
        for i, y in self.layout_list_rows(len(units), 40, row_top, view_h=view_h,
                                          cull_top=cull_top, cull_bottom=cull_bottom):
            unit = units[i]
            name = unit.get("original_type", unit.get("type", "Unknown"))
            is_naval = self.unit_lib.get(name, {}).get("naval_unit", False)
            suffix = "(Convoy)" if not is_naval else "(Truck)"
            checked = i in self.selected
            label = f"{'[X]' if checked else '[ ]'} {name} {suffix}"
            btn = Button(row_x, y, "list_row", "green" if checked else "grey", label, lambda ii=i: self.toggle(ii))
            btn.rect.width = row_w
            btn.is_scrollable = True
            btn.click_guard = self.scroll_click_guard
            self.elements.append(btn)

        self.list_view_h = view_h

    def save(self):
        units = self.province.get("units", [])
        for i, unit in enumerate(units):
            want = i in self.selected
            if want and "original_type" not in unit:
                name = unit.get("type", "Unknown")
                is_naval = self.unit_lib.get(name, {}).get("naval_unit", False)
                target = "Convoy" if not is_naval else "Truck"

                unit["original_type"] = unit["type"]
                unit["original_speed"] = unit.get("speed", 1)
                unit["original_max_health"] = unit.get("max_health", c.DEFAULT_UNIT_HP)
                unit["original_attack"] = unit.get("attack", c.DEFAULT_UNIT_ATK)

                pct = unit.get("health", 1) / max(1, unit.get("max_health", 1))
                unit["type"] = f"{target} ({unit['type']})"
                unit["speed"] = 1

                if target == "Convoy":
                    unit["naval_unit"] = True
                    unit["max_health"] = c.CONVOY_MAX_HP
                    unit["attack"] = c.CONVOY_ATK
                else:
                    unit["naval_unit"] = False
                    unit["max_health"] = c.TRUCK_MAX_HP
                    unit["attack"] = c.TRUCK_ATK

                unit["health"] = unit["max_health"] * pct
            elif not want and "original_type" in unit:
                queries.revert_transport(unit)

        self.map_screen.show_feedback("Unit transport status updated!")
        self.done = True

    def draw_content(self, surface):
        p = self.panel_rect
        ui_bars.draw_modal_box(surface, p, bg_color=(30, 30, 45), border_color=(76, 175, 80), border_width=2)
        ui_bars.draw_centered_title(surface, "Convert Units", p.y + 20, "heading2")
        self.draw_list_scrollbar(surface, p.right - 15, p.y + 70, self.list_view_h)

# ==========================================
# RESOURCE BRUSH
# ==========================================

class Resource_Brush_Screen(MapOverlayScreen):
    pans_camera = False
    RESOURCE_TYPES = ["Iron", "Coal", "Oil", "Wheat", "None"]

    def __init__(self, map_screen):
        super().__init__(map_screen, pygame.Rect(0, 0, 400, 300))
        self.panel_rect.center = (c.SCREEN_WIDTH // 2, c.SCREEN_HEIGHT // 2)
        self.back_state = "MAP"
        self.selected_resource = "Iron"
        self.amount_field = TextField(0, 0, 150, 40, "50", numeric=True)
        self.refresh_ui()

    def refresh_ui(self):
        p = self.panel_rect
        self.amount_field.rect.topleft = (p.centerx - 75, p.y + 190)

        self.elements = [
            Button(50, c.TOP_BAR_UI_CENTER_Y, "small", "red", "Back", self.exit_screen),
            Button(p.centerx - 130, p.y + 90, "medium", "blue", f"Resource: {self.selected_resource}", self.pick_resource),
            Button(p.centerx - 100, p.bottom - 55, "medium", "purple", "Confirm Selection", self.confirm),
            self.amount_field,
        ]

    def pick_resource(self):
        def on_pick(val):
            self.selected_resource = val
            self.refresh_ui()
        queries.open_listbox_selector(self.map_screen, "Select Resource Type", "Choose a resource type:",
                                      self.RESOURCE_TYPES, on_pick)
        self.refresh_ui()

    def confirm(self):
        try:
            amt = int(self.amount_field.text)
        except ValueError:
            confirm_dialog.show_error("Error", "Amount must be a whole number.")
            return

        self.map_screen.brush_resource_type = self.selected_resource
        self.map_screen.brush_resource_amount = amt
        self.map_screen.editor_mode = "RESOURCE"

        if self.selected_resource == "None":
            self.map_screen.show_feedback("Brush: Erase Resources")
        else:
            self.map_screen.show_feedback(f"Brush: {self.selected_resource} ({amt})")

        self.done = True

    def draw_content(self, surface):
        p = self.panel_rect
        ui_bars.draw_modal_box(surface, p, bg_color=(35, 20, 45), border_color=(156, 39, 176), border_width=2)
        ui_bars.draw_centered_title(surface, "Resource Brush", p.y + 20, "heading2")

        label = fonts.get("normal").render("Amount:", True, (220, 220, 220))
        surface.blit(label, label.get_rect(midright=(p.centerx - 85, p.y + 210)))

# ==========================================
# CLEAR MAP ITEMS
# ==========================================

class Clear_Map_Screen(MapOverlayScreen):
    pans_camera = False

    OPTIONS = [
        "all units", "all buildings", "all resources",
        "all units from (x) country", "all buildings on (x) countries territory",
        "all resources on (x) countries territory", "all (x) units", "all (x) resources",
        "all (x) units from country (x)", "all (x) resources on (x) countries territory",
    ]
    RESOURCE_TYPES = ["Iron", "Coal", "Oil", "Wheat"]

    def __init__(self, map_screen):
        super().__init__(map_screen, pygame.Rect(0, 0, 600, 420))
        self.panel_rect.center = (c.SCREEN_WIDTH // 2, c.SCREEN_HEIGHT // 2)
        self.back_state = "MAP"

        self.selected_option = self.OPTIONS[0]
        self.selected_country = ""
        self.selected_unit_type = ""
        self.selected_resource_type = ""

        existing_owners = {p.get("owner") for p in map_screen.map_data.values()}
        self.available_countries = sorted(n for n in existing_owners if n and n not in ["Unclaimed", "The Rot"])

        existing_unit_types = set()
        for prov in map_screen.map_data.values():
            for unit in prov.get("units", []):
                if "type" in unit:
                    existing_unit_types.add(unit["type"])
        self.available_unit_types = sorted(existing_unit_types)

        self.refresh_ui()

    def needs_country(self):
        return "country" in self.selected_option or "countries" in self.selected_option

    def needs_unit_type(self):
        return self.selected_option in ("all (x) units", "all (x) units from country (x)")

    def needs_resource_type(self):
        return self.selected_option in ("all (x) resources", "all (x) resources on (x) countries territory")

    def refresh_ui(self):
        p = self.panel_rect
        opt_btn = Button(p.x + 30, p.y + 90, "large", "blue", self.selected_option, self.pick_option)
        opt_btn.rect.width = p.width - 60

        self.elements = [
            Button(50, c.TOP_BAR_UI_CENTER_Y, "small", "red", "Back", self.exit_screen),
            Button(p.centerx - 130, p.bottom - 55, "editor_ui", "red", "Confirm Clear", self.confirm_clear),
            opt_btn,
        ]

        y = p.y + 190
        if self.needs_country():
            label = self.selected_country or "Select Country..."
            btn = Button(p.x + 30, y, "editor_ui", "orange", f"Country: {label}", self.pick_country)
            btn.rect.width = p.width - 60
            self.elements.append(btn)
            y += 60
        if self.needs_unit_type():
            label = self.selected_unit_type or "Select Unit..."
            btn = Button(p.x + 30, y, "editor_ui", "orange", f"Unit: {label}", self.pick_unit_type)
            btn.rect.width = p.width - 60
            self.elements.append(btn)
            y += 60
        if self.needs_resource_type():
            label = self.selected_resource_type or "Select Resource..."
            btn = Button(p.x + 30, y, "editor_ui", "orange", f"Resource: {label}", self.pick_resource_type)
            btn.rect.width = p.width - 60
            self.elements.append(btn)
            y += 60

    def pick_option(self):
        def on_pick(val):
            self.selected_option = val
            self.refresh_ui()
        queries.open_listbox_selector(self.map_screen, "Select What to Clear", "Choose an option:", self.OPTIONS, on_pick)
        self.refresh_ui()

    def pick_country(self):
        def on_pick(val):
            self.selected_country = val
            self.refresh_ui()
        queries.open_listbox_selector(self.map_screen, "Select Country", "Choose a country:",
                                      self.available_countries, on_pick)
        self.refresh_ui()

    def pick_unit_type(self):
        def on_pick(val):
            self.selected_unit_type = val
            self.refresh_ui()
        queries.open_listbox_selector(self.map_screen, "Select Unit Type", "Choose a unit type:",
                                      self.available_unit_types, on_pick)
        self.refresh_ui()

    def pick_resource_type(self):
        def on_pick(val):
            self.selected_resource_type = val
            self.refresh_ui()
        queries.open_listbox_selector(self.map_screen, "Select Resource", "Choose a resource:",
                                      self.RESOURCE_TYPES, on_pick)
        self.refresh_ui()

    def confirm_clear(self):
        opt = self.selected_option
        c_val = self.selected_country
        u_val = self.selected_unit_type
        r_val = self.selected_resource_type

        if self.needs_country() and not c_val:
            confirm_dialog.show_error("Error", "Please select a country.")
            return
        if self.needs_unit_type() and not u_val:
            confirm_dialog.show_error("Error", "Please select a unit type.")
            return
        if self.needs_resource_type() and not r_val:
            confirm_dialog.show_error("Error", "Please select a resource type.")
            return

        msg = f"Are you sure you want to clear:\n{opt}"
        if c_val and self.needs_country(): msg += f"\nCountry: {c_val}"
        if u_val and self.needs_unit_type(): msg += f"\nUnit: {u_val}"
        if r_val and self.needs_resource_type(): msg += f"\nResource: {r_val}"

        def on_confirm(ok):
            if not ok:
                return

            map_data = self.map_screen.map_data
            for prov_id, prov_data in map_data.items():
                owner = prov_data.get("owner", "Unclaimed")

                if "countries territory" in opt and owner != c_val:
                    continue

                if "units" in opt:
                    if opt in ("all units", "all units from (x) country"):
                        if opt == "all units from (x) country":
                            prov_data["units"] = [u for u in prov_data.get("units", []) if u.get("owner") != c_val]
                        else:
                            prov_data["units"] = []
                    elif opt == "all (x) units":
                        prov_data["units"] = [u for u in prov_data.get("units", []) if u.get("type") != u_val]
                    elif opt == "all (x) units from country (x)":
                        prov_data["units"] = [u for u in prov_data.get("units", [])
                                              if not (u.get("type") == u_val and u.get("owner") == c_val)]

                if "buildings" in opt:
                    prov_data["buildings"] = []

                if "resources" in opt:
                    if opt in ("all resources", "all resources on (x) countries territory"):
                        prov_data["resources"] = {}
                        if "resource" in prov_data:
                            del prov_data["resource"]
                    elif opt in ("all (x) resources", "all (x) resources on (x) countries territory"):
                        if isinstance(prov_data.get("resources"), dict) and r_val in prov_data["resources"]:
                            del prov_data["resources"][r_val]
                        if prov_data.get("resource", {}).get("type") == r_val:
                            del prov_data["resource"]

            self.map_screen.refresh_all_maps()
            self.map_screen.show_feedback("Map cleared according to criteria.")
            self.done = True

        confirm_dialog.ask_yes_no("Confirm Clear", msg, on_confirm)

    def draw_content(self, surface):
        ui_bars.draw_modal_box(surface, self.panel_rect, bg_color=(40, 20, 20), border_color=(244, 67, 54), border_width=2)
        ui_bars.draw_centered_title(surface, "Clear Map Items", self.panel_rect.y + 20, "heading2")

# ==========================================
# GLOBAL DIPLOMACY & FACTIONS EDITOR
# ==========================================

class Diplomacy_Editor_Screen(MapOverlayScreen):
    """Wars, factions and puppets for the whole map on a single screen.

    Keeps the shape of the tkinter original: nations down the left, and the
    selected nation's relations laid out live to the right. Picking a nation
    only swaps what the right-hand side is editing -- and, like the original,
    reloads from nation_data, so switching away drops unsaved edits. Saving
    leaves the screen open so several nations can be edited in a row.
    """
    pans_camera = False
    overlay_alpha = 220

    ROW_HEIGHT = 30
    NAT_W = 260
    COL_W = 296
    COL_GAP = 10
    LIST_VIEW_H = 390
    # Each scrollable region keeps its own offset/track attributes so the four
    # lists on screen scroll independently.
    REGIONS = ("nations", "wars", "members", "master")
    PUPPET_TYPES = (c.PUPPET_TYPE_AUTONOMOUS, c.PUPPET_TYPE_INTEGRATED)

    def __init__(self, map_screen):
        super().__init__(map_screen, pygame.Rect(0, 0, 1240, 660))
        self.panel_rect.center = (c.SCREEN_WIDTH // 2, c.SCREEN_HEIGHT // 2)
        self.back_state = "MAP"

        self.countries = sorted(queries.get_living_nations(map_screen.map_data))
        self.target = None
        self.others = []
        self.wars = set()
        self.members = set()
        self.is_leader = False
        self.master = "None"
        self.puppet_type = c.PUPPET_TYPE_AUTONOMOUS

        for name in self.REGIONS:
            setattr(self, f"_scroll_{name}", 0)

        self.faction_field = TextField(0, 0, 300, 36, "", label="Faction Name:")
        self._layout()

        if self.countries:
            self.select_nation(self.countries[0])
        else:
            self.refresh_ui()

    def _layout(self):
        p = self.panel_rect
        self.nat_x = p.x + 16
        self.nations_top = p.y + 108
        self.nations_view_h = p.bottom - 16 - self.nations_top

        self.cols_x = self.nat_x + self.NAT_W + 20
        self.lists_top = p.y + 132
        self.row_a_y = self.lists_top + self.LIST_VIEW_H + 20
        self.row_b_y = self.row_a_y + 56

        self.regions = {"nations": pygame.Rect(self.nat_x, self.nations_top, self.NAT_W, self.nations_view_h)}
        for i, name in enumerate(("wars", "members", "master")):
            self.regions[name] = pygame.Rect(self._col_x(i), self.lists_top, self.COL_W, self.LIST_VIEW_H)

        # Published per-region so _scroll_attrs's content_rect_attr can point
        # handle_content_drag/draw_elements at each region's own rect by name.
        for name, rect in self.regions.items():
            setattr(self, f"_content_{name}", rect)

    def _col_x(self, index):
        return self.cols_x + index * (self.COL_W + self.COL_GAP)

    def _scroll_attrs(self, name):
        """Per-region scroll state names.

        Underscore-prefixed so a region can never shadow a method: a region
        called "events" would otherwise publish its scrollbar handle as
        self.handle_events and overwrite GameState.handle_events.
        """
        return {"attr": f"_scroll_{name}", "limit_attr": f"_max_{name}",
                "track_attr": f"_track_{name}", "handle_attr": f"_handle_{name}",
                "drag_attr": f"_drag_{name}", "content_rect_attr": f"_content_{name}"}

    @property
    def listening_for(self):
        """Keeps the global BACK keybind from closing the editor mid-edit."""
        return self.faction_field.active

    # ------------------------------------------------------------------ #
    #                             SELECTION                              #
    # ------------------------------------------------------------------ #

    def select_nation(self, cid):
        """Loads a nation into the right-hand side, discarding unsaved edits."""
        data = self.map_screen.nation_data.get(cid, {})
        self.target = cid
        self.others = [n for n in self.countries if n != cid]

        self.wars = {n for n in data.get("at_war_with", []) if n in self.others}
        self.is_leader = bool(data.get("is_faction_leader", False))
        self.master = data.get("master", "") or "None"
        self.puppet_type = data.get("puppet_type", "") or c.PUPPET_TYPE_AUTONOMOUS

        faction = data.get("faction", "")
        self.faction_field.text = faction
        self.faction_field.active = False
        self.members = {n for n in self.others
                        if faction and self.map_screen.nation_data.get(n, {}).get("faction", "") == faction}

        for name in ("wars", "members", "master"):
            setattr(self, f"_scroll_{name}", 0)
        self.refresh_ui()

    def toggle_membership(self, group, name):
        group.symmetric_difference_update({name})
        self.refresh_ui()

    def set_master(self, name):
        self.master = name
        self.refresh_ui()

    def toggle_leader(self):
        self.is_leader = not self.is_leader
        self.refresh_ui()

    def cycle_puppet_type(self):
        i = self.PUPPET_TYPES.index(self.puppet_type) if self.puppet_type in self.PUPPET_TYPES else 0
        self.puppet_type = self.PUPPET_TYPES[(i + 1) % len(self.PUPPET_TYPES)]
        self.refresh_ui()

    # ------------------------------------------------------------------ #
    #                               SAVING                               #
    # ------------------------------------------------------------------ #

    def save(self):
        if not self.target:
            return

        nation_data = self.map_screen.nation_data
        target = self.target
        data = nation_data.get(target, {})

        # 1. Wars, kept bidirectional -- drop target from everyone, then re-add the picks.
        for name in self.countries:
            if target in nation_data[name].get("at_war_with", []):
                nation_data[name]["at_war_with"].remove(target)
        data["at_war_with"] = sorted(self.wars)
        for enemy in self.wars:
            if target not in nation_data[enemy].get("at_war_with", []):
                nation_data[enemy].setdefault("at_war_with", []).append(target)

        # 2. Faction membership.
        new_faction = self.faction_field.text.strip()
        data["faction"] = new_faction
        data["is_faction_leader"] = self.is_leader

        for name in self.others:
            if name in self.members:
                nation_data[name]["faction"] = new_faction
                if new_faction:
                    nation_data[name]["is_faction_leader"] = False
            elif new_faction and nation_data[name].get("faction", "") == new_faction:
                nation_data[name]["faction"] = ""
                nation_data[name]["is_faction_leader"] = False

        # 3. Puppet state.
        old_master = data.get("master", "")
        if old_master and old_master != "None" and old_master in nation_data:
            if target in nation_data[old_master].get("puppets", []):
                nation_data[old_master]["puppets"].remove(target)

        if self.master and self.master != "None" and self.master != target:
            assign_puppet(self.map_screen.map_data, nation_data, self.master, target, self.puppet_type)
        else:
            data["master"] = ""
            data["puppet_type"] = ""

        self.map_screen.refresh_diplomacy_maps()
        self.map_screen.show_feedback(f"Diplomacy saved for {target}")
        self.refresh_ui()

    # ------------------------------------------------------------------ #
    #                             RENDERING                              #
    # ------------------------------------------------------------------ #

    def _row(self, x, y, width, color, text, callback):
        btn = Button(x, y, "list_row", color, text, callback, font_preset="button_small")
        btn.rect.width = width
        return btn

    def _rows_of(self, name, count, top, view_h):
        attrs = self._scroll_attrs(name)
        return self.layout_list_rows(count, self.ROW_HEIGHT, top, view_h=view_h,
                                     cull_top=top - 1,
                                     cull_bottom=top + view_h - self.ROW_HEIGHT + 2,
                                     attr=attrs["attr"], limit_attr=attrs["limit_attr"],
                                     guard_attr=f"_guard_{name}")

    def _columns(self):
        """(region, header, rows, is_checked, on_click) for the three right-hand lists."""
        return [
            ("wars", "At War With", self.others,
             lambda n: n in self.wars, lambda n: self.toggle_membership(self.wars, n)),
            ("members", "Faction Members", self.others,
             lambda n: n in self.members, lambda n: self.toggle_membership(self.members, n)),
            ("master", "Master Nation", ["None"] + self.others,
             lambda n: n == self.master, self.set_master),
        ]

    def refresh_ui(self):
        p = self.panel_rect
        self.elements = [Button(self.nat_x, p.y + 10, "small", "red", "Back", self.exit_screen)]

        for i, y in self._rows_of("nations", len(self.countries), self.nations_top, self.nations_view_h):
            cid = self.countries[i]
            btn = self._row(self.nat_x, y, self.NAT_W - 24, "blue", truncate(cid, 26),
                            lambda cc=cid: self.select_nation(cc))
            btn.is_selected = cid == self.target
            btn.pane = "nations"
            btn.click_guard = self._guard_nations
            self.elements.append(btn)

        if not self.target:
            return

        for idx, (region, _header, rows, is_checked, on_click) in enumerate(self._columns()):
            col_x = self._col_x(idx)
            single = region == "master"
            for i, y in self._rows_of(region, len(rows), self.lists_top, self.LIST_VIEW_H):
                name = rows[i]
                checked = is_checked(name)
                label = truncate(name, 28) if single else f"{'[X]' if checked else '[  ]'} {truncate(name, 24)}"
                btn = self._row(col_x, y, self.COL_W - 24, "green" if checked else "blue", label,
                                lambda n=name, cb=on_click: cb(n))
                btn.is_selected = checked
                btn.pane = region
                btn.click_guard = getattr(self, f"_guard_{region}")
                self.elements.append(btn)

        self.faction_field.rect.topleft = (self.cols_x + 130, self.row_a_y)
        self.elements.append(self.faction_field)

        leader_btn = Button(self.cols_x + 470, self.row_a_y - 2, "editor_ui",
                            "green" if self.is_leader else "grey",
                            f"Faction Leader: {'Yes' if self.is_leader else 'No'}",
                            self.toggle_leader, font_preset="button_small")
        leader_btn.is_selected = self.is_leader
        self.elements.append(leader_btn)

        self.elements.append(Button(self.cols_x, self.row_b_y, "editor_ui", "blue",
                                    f"Puppet Type: {self.puppet_type}", self.cycle_puppet_type,
                                    font_preset="button_small"))
        self.elements.append(Button(self.cols_x + 470, self.row_b_y - 5, "medium", "green",
                                    "Save Changes", self.save))

    def additional_events(self, event):
        # The wheel drives whichever list the cursor is over; scrollbar presses and
        # drags are offered to every region, which each ignore what is not theirs.
        if event.type == pygame.MOUSEWHEEL:
            pos = pygame.mouse.get_pos()
            for name, rect in self.regions.items():
                if rect.collidepoint(pos):
                    self.handle_list_scroll(event, **self._scroll_attrs(name))
                    return
            return

        for name in self.REGIONS:
            if self.handle_list_scroll(event, **self._scroll_attrs(name)):
                return

    def draw_elements(self, surface):
        """Four independent scrolling regions (nations + the three columns),
        each cropped to its own rect -- see View_Assets.draw_elements for the
        same pattern with three panes."""
        fixed = [el for el in self.elements if not getattr(el, "pane", None)]
        for name, rect in self.regions.items():
            scroll = getattr(self, f"_scroll_{name}", 0)
            limit = getattr(self, f"_max_{name}", 0)
            region_els = [el for el in self.elements if getattr(el, "pane", None) == name]
            with ui_bars.clip_scroll_region(surface, rect, draw_top=scroll != 0, draw_bottom=scroll > limit):
                for el in region_els:
                    el.draw(surface)

        for el in fixed:
            el.draw(surface)

    def draw_content(self, surface):
        p = self.panel_rect
        ui_bars.draw_modal_box(surface, p, bg_color=(30, 30, 45), border_color=(33, 150, 243), border_width=2)
        ui_bars.draw_centered_title(surface, "Global Diplomacy & Factions", p.y + 14, "heading2")

        small = fonts.get("small")
        surface.blit(small.render("Nations:", True, (170, 170, 210)), (self.nat_x, self.nations_top - 20))
        pygame.draw.line(surface, (70, 70, 95), (self.cols_x - 10, p.y + 60),
                         (self.cols_x - 10, p.bottom - 16), 1)

        if not self.target:
            msg = fonts.get("heading2").render("Select a nation...", True, (200, 200, 200))
            surface.blit(msg, msg.get_rect(center=(self.cols_x + 450, p.centery)))
            return

        heading = fonts.get("heading2").render(f"Editing: {self.target}", True, c.COLOR_GOLD_HIGHLIGHT)
        surface.blit(heading, (self.cols_x, p.y + 66))

        for idx, (region, header, rows, _is_checked, _on_click) in enumerate(self._columns()):
            col_x = self._col_x(idx)
            surface.blit(small.render(header, True, (170, 170, 210)), (col_x, self.lists_top - 20))
            if not rows:
                surface.blit(small.render("None available.", True, (150, 150, 150)),
                             (col_x + 4, self.lists_top + 6))
            self.draw_list_scrollbar(surface, col_x + self.COL_W - 18, self.lists_top, self.LIST_VIEW_H,
                                     **self._scroll_attrs(region))

        self.draw_list_scrollbar(surface, self.nat_x + self.NAT_W - 18, self.nations_top,
                                 self.nations_view_h, **self._scroll_attrs("nations"))
