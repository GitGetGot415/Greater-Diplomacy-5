"""Native pygame replacements for the map editor's date and starting-economy
tkinter tool windows -- see screens/editors/__init__.py."""
import pygame
import data.constants as c
from ui.background_styles import EDITOR_PANEL_STYLES
from data import queries
from ui.navigation.screen import EditorFormScreen, NationListOverlayScreen
from ui.widgets.ui_elements import Button, TextField
from ui import dialogs
from ui.navigation.screen_runner import _run_pygame_sub_screen
from screens.editors.unit_stats_editor import MapUnitBuildingStatsScreen


class Editor_Metadata_Screen(EditorFormScreen):
    """Edit scenario information as a draft until Apply is selected."""
    PANEL_BG, PANEL_BORDER, PANEL_BORDER_WIDTH = c.PANEL_THEME_EDIT
    PANEL_STYLE = EDITOR_PANEL_STYLES["metadata"]
    PANEL_TITLE = "Metadata"
    PANEL_WIDTH, PANEL_HEIGHT = 780, 360
    FIELD_LEFT, FIELD_HEIGHT = 205, 40
    FIELD_CENTER_OFFSET = FIELD_LEFT - PANEL_WIDTH // 2
    ACTION_LABEL = "Apply Metadata"

    def __init__(self, map_screen):
        super().__init__(map_screen, pygame.Rect(0, 0, self.PANEL_WIDTH, self.PANEL_HEIGHT))
        metadata = queries.normalized_scenario_metadata(map_screen.scenario_metadata)
        values = (("name", "Scenario Name:", map_screen.editor_scenario_name),
                  ("author", "Author:", metadata["author"]),
                  ("description", "Description:", metadata["description"]))
        self.fields = {key: TextField(0, 0, self.PANEL_WIDTH - self.FIELD_LEFT - 30,
                                     self.FIELD_HEIGHT, value, label=label)
                       for key, label, value in values}
        self.refresh_ui()

    def apply(self):
        try:
            queries.set_editor_metadata(self.map_screen, *(self.fields[key].text
                                        for key in ("name", "author", "description")))
        except ValueError as error:
            dialogs.show_error("Metadata", str(error))
            return
        self.map_screen.show_feedback("Scenario metadata updated. Save the map to write it to disk.")
        self.done = True

# ==========================================
# SET START DATE
# ==========================================

class Editor_Date_Screen(EditorFormScreen):
    PANEL_BG, PANEL_BORDER, PANEL_BORDER_WIDTH = c.PANEL_THEME_EDIT
    PANEL_STYLE = EDITOR_PANEL_STYLES["date"]
    PANEL_TITLE = "Set Start Date"
    FIELD_CENTER_OFFSET = -30
    ACTION_LABEL = "Apply Date"
    ACTION_COLOR = "orange"

    def __init__(self, map_screen):
        super().__init__(map_screen, pygame.Rect(0, 0, 440, 420))

        tm = map_screen.time_manager
        dpt = queries.get_days_per_turn(map_screen.scenario_settings)
        values = (("day", "Day (1-30):", tm.day), ("month", "Month (1-12):", tm.month_index + 1),
                  ("year", "Year:", tm.year), ("days_per_turn", "Days/Turn:", dpt))
        self.fields = {key: TextField(0, 0, 160, 40, str(value), numeric=True, label=label)
                       for key, label, value in values}

        self.refresh_ui()

    def apply(self):
        try:
            d = int(self.fields["day"].text)
            m = int(self.fields["month"].text) - 1
            y = int(self.fields["year"].text)
            b_dpt = int(self.fields["days_per_turn"].text)
        except ValueError:
            dialogs.show_error("Error", "Please enter valid integers.")
            return

        if not (1 <= d <= 30):
            dialogs.show_error("Error", "Day must be between 1 and 30.")
            return
        if not (0 <= m <= 11):
            dialogs.show_error("Error", "Month must be between 1 and 12.")
            return
        if b_dpt <= 0:
            dialogs.show_error("Error", "Days per turn must be positive.")
            return

        tm = self.map_screen.time_manager
        tm.day, tm.month_index, tm.year = d, m, y
        self.map_screen.scenario_settings["base_days_per_turn"] = b_dpt
        self.map_screen.scenario_settings["days_per_turn"] = "Default"
        queries.save_scenario_settings(self.map_screen.scenario_settings)

        feedback = "Date & Turn Rate set!"
        if queries.get_scenario_flag("force_time_appropriate_research",
                                     c.DEFAULT_FORCE_TIME_APPROPRIATE_RESEARCH,
                                     self.map_screen.scenario_settings):
            queries.apply_time_appropriate_research_to_map(self.map_screen, y)
            feedback = f"Date & Turn Rate set! Research re-aligned to {y}."

        self.map_screen.show_feedback(feedback)
        self.done = True

# ==========================================
# STARTING ECONOMY EDITOR
# ==========================================

class Starting_Economy_Edit_Screen(EditorFormScreen):
    PANEL_BG, PANEL_BORDER, PANEL_BORDER_WIDTH = c.PANEL_THEME_INFO
    PANEL_STYLE = EDITOR_PANEL_STYLES["starting_economy"]
    FIELD_CENTER_OFFSET = -20
    FIELD_TOP = 90
    FIELD_GAP = 60
    ACTION_LABEL = "Save Economy"

    def __init__(self, map_screen, country_id):
        super().__init__(map_screen, pygame.Rect(0, 0, 400, 360))
        self.country_id = country_id

        data = map_screen.nation_data.get(country_id, {})
        self.fields = {}
        for res in c.ECON_RESOURCE_KEYS:
            self.fields[res] = TextField(0, 0, 160, 40, str(int(data.get(res, 0))), numeric=True,
                                         label=f"{res.capitalize()}:")

        self.refresh_ui()

    def apply(self):
        data = self.map_screen.nation_data.get(self.country_id)
        if data:
            for res, field in self.fields.items():
                try:
                    data[res] = int(field.text)
                except ValueError:
                    pass
            self.map_screen.show_feedback("Saved economy for " + queries.get_country_display_name(
                self.country_id, self.map_screen.nation_data))
        self.done = True

    def get_panel_title(self):
        return queries.get_country_display_name(self.country_id, self.map_screen.nation_data) + " Economy"

STATS_BUTTON_SIZE = (150, 40)


class Starting_Economy_List_Screen(NationListOverlayScreen):
    PANEL_BG, PANEL_BORDER, PANEL_BORDER_WIDTH = c.PANEL_THEME_CONFIRM
    PANEL_STYLE = EDITOR_PANEL_STYLES["starting_economy_list"]
    PANEL_TITLE = "Starting Economy Editor"
    EDIT_SCREEN = Starting_Economy_Edit_Screen

    def list_header_elements(self):
        p = self.panel_rect
        return [
            Button(p.right - 120, p.y + 20, "small", "red", "Reset All", self.reset_all),
            Button(p.x + 20, p.y + 20, STATS_BUTTON_SIZE, "purple", "Unit / Building Stats",
                   self.open_unit_building_stats, font_preset="small"),
        ]

    def open_unit_building_stats(self):
        _run_pygame_sub_screen(self.map_screen, MapUnitBuildingStatsScreen(self.map_screen))

    def country_button(self, country_id, x, y):
        is_modified = any(self.map_screen.nation_data.get(country_id, {}).get(res, 0) != 0
                          for res in c.ECON_RESOURCE_KEYS)
        country_name = queries.get_country_display_name(country_id, self.map_screen.nation_data)
        label = f"[MODIFIED] {country_name}" if is_modified else country_name
        return Button(x, y, "list_row", "blue", label,
                      lambda cid=country_id: self.edit(cid))

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

        dialogs.ask_yes_no("Confirm Reset", "Are you sure you want to reset every starting economy to 0?", on_confirm)
