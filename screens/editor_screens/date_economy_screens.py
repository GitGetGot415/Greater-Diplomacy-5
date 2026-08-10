"""Native pygame replacements for the map editor's date and starting-economy
tkinter tool windows -- see screens/editor_screens/__init__.py."""
import pygame
import data.constants as c
from data import queries
from gameState import MapOverlayScreen
from ui_elements import Button, TextField, make_back_button
from ui import confirm_dialog
from ui.bars import ui_bars
from ui.screen_runner import _run_pygame_sub_screen

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
            make_back_button(self.exit_screen, style="map"),
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
            make_back_button(self.exit_screen, style="map"),
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
            make_back_button(self.exit_screen, style="map"),
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
