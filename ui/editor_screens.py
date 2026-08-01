"""Native pygame replacements for the map editor's tkinter tool windows.

Each class here is a MapOverlayScreen launched with _run_pygame_sub_screen,
mirroring the pattern already established in ui/player_diplomacy_menus.py for
the diplomacy popups. The scripted events editor is intentionally left alone
(it's still a tkinter window) -- everything else the map editor bottom/side
bars open lives here or has already been converted to a TableScreen.
"""
import pygame
import data.constants as c
from data import queries
from gameState import MapOverlayScreen
from ui_elements import Button, TextField
from ui import confirm_dialog
from ui.bars import ui_bars
from ui.player_diplomacy_menus import _run_pygame_sub_screen
from map_logic.rendering.font_manager import fonts

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
        for i, y in self.layout_list_rows(len(self.active_countries), 40, row_top, view_h=view_h,
                                          cull_top=p.y + 80, cull_bottom=p.bottom - 20):
            cid = self.active_countries[i]
            is_modified = any(self.map_screen.nation_data.get(cid, {}).get(res, 0) != 0 for res in c.ECON_RESOURCE_KEYS)
            label = f"[MODIFIED] {cid}" if is_modified else cid
            self.elements.append(Button(row_x, y, "list_row", "blue", label, lambda cc=cid: self.edit(cc)))

        self.list_view_h = view_h

    def edit(self, cid):
        _run_pygame_sub_screen(self.map_screen, Starting_Economy_Edit_Screen(self.map_screen, cid))
        self.refresh_ui()

    def reset_all(self):
        if not confirm_dialog.ask_yes_no("Confirm Reset", "Are you sure you want to reset every starting economy to 0?"):
            return
        for cid in self.active_countries:
            if cid in self.map_screen.nation_data:
                for res in c.ECON_RESOURCE_KEYS:
                    self.map_screen.nation_data[cid][res] = 0
        self.map_screen.show_feedback("Reset starting economy for all nations!")
        self.done = True

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
        for i, y in self.layout_list_rows(len(self.techs), self.ROW_HEIGHT, row_top, view_h=view_h,
                                          cull_top=p.y + 60, cull_bottom=p.bottom - 70):
            tech = self.techs[i]
            kind = self.tech_state[tech]
            if kind[0] == "checkbox":
                checked = kind[1]
                btn = Button(p.right - 100, y, "tiny_square", "green" if checked else "grey",
                            "ON" if checked else "OFF", lambda t=tech: self.toggle_checkbox(t), font_preset="tiny")
                self.elements.append(btn)
            else:
                _, text, _max_lvl = kind
                field = TextField(p.right - 160, y, 100, 30, text, numeric=True)
                field.tech_key = tech
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
        clip_rect = pygame.Rect(p.x + 5, p.y + 60, p.width - 10, p.height - 140)
        old_clip = surface.get_clip()
        surface.set_clip(clip_rect)

        row_top = p.y + 70
        view_h = p.height - 140
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
        for i, y in self.layout_list_rows(len(self.active_countries), 40, row_top, view_h=view_h,
                                          cull_top=p.y + 160, cull_bottom=p.bottom - 20):
            cid = self.active_countries[i]
            c_res = self.map_screen.nation_data.get(cid, {}).get("research", {})
            is_diff = any(c_res.get(k, v) != v for k, v in self.default_research.items())
            label = f"[MODIFIED] {cid}" if is_diff else cid
            btn = Button(row_x, y, "list_row", "blue", label, lambda cc=cid: self.edit_country(cc))
            btn.rect.width = row_w
            self.elements.append(btn)

        self.list_view_h = view_h

    def _open_editor(self, title, base_data, on_save):
        for k, v in self.default_research.items():
            base_data.setdefault(k, v)
        screen = Research_Edit_Screen(self.map_screen, title, base_data, queries.get_tech_tree(), on_save)
        _run_pygame_sub_screen(self.map_screen, screen)
        self.refresh_ui()

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
        if not confirm_dialog.ask_yes_no("Force Time Appropriate Research", msg):
            return

        time_app_res = queries.get_time_appropriate_research(current_year)
        self.map_screen.default_research = time_app_res.copy()
        self.default_research = time_app_res.copy()
        for cid in self.active_countries:
            self.map_screen.nation_data[cid]["research"] = time_app_res.copy()
        self.map_screen.show_feedback(f"Forced Time Appropriate Research for {current_year}")
        self.refresh_ui()

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
        for i, y in self.layout_list_rows(len(units), 40, row_top, view_h=view_h,
                                          cull_top=p.y + 60, cull_bottom=p.bottom - 70):
            unit = units[i]
            name = unit.get("original_type", unit.get("type", "Unknown"))
            is_naval = self.unit_lib.get(name, {}).get("naval_unit", False)
            suffix = "(Convoy)" if not is_naval else "(Truck)"
            checked = i in self.selected
            label = f"{'[X]' if checked else '[ ]'} {name} {suffix}"
            btn = Button(row_x, y, "list_row", "green" if checked else "grey", label, lambda ii=i: self.toggle(ii))
            btn.rect.width = row_w
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

        if not confirm_dialog.ask_yes_no("Confirm Clear", msg):
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

    def draw_content(self, surface):
        ui_bars.draw_modal_box(surface, self.panel_rect, bg_color=(40, 20, 20), border_color=(244, 67, 54), border_width=2)
        ui_bars.draw_centered_title(surface, "Clear Map Items", self.panel_rect.y + 20, "heading2")
