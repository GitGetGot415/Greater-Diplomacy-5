import os
from screens.game import map_launch
from ui.widgets.ui_elements import play_ui_sound
from ui.widgets.ui_elements import Button, make_back_button
from ui.widgets.content_browser import ScenarioLibraryScreen
import data.constants as c
from data import queries
from ui.dialogs import pickers
from screens.setup import map_refresh
from screens.setup.scenario_settings import Scenario_Settings
from screens.editors.historical_leaders_editor import open_historical_leaders_editor
from ui.dialogs.checkbox_list_screen import CheckboxItem


class New_Game(ScenarioLibraryScreen):
    back_state = "MENU"
    title = "NEW GAME"
    content_label = "scenarios"
    CORNER_BUTTON_SIZE = (220, 40)
    CORNER_MARGIN = 24
    SORTS = ScenarioLibraryScreen.SORTS[1:] + ScenarioLibraryScreen.SORTS[:1]

    # Resolve directory settings when the browser refreshes.
    CATEGORIES = {
        "HISTORICAL": ("Historical Scenarios", "SCENARIOS_HISTORICAL_DIR"),
        "ALTERNATE": ("Alternate Scenarios", "SCENARIOS_ALTERNATE_DIR"),
        "MAP_EDITOR": ("Custom Scenarios", "SCENARIOS_CUSTOM_DIR"),
    }

    def __init__(self):
        super().__init__()
        self.bg_color = (0, 50, 0)
        self.selected_save_path = None
        self.sub_state = "HISTORICAL"
        self.refresh_ui()

    def on_enter(self, app, previous):
        if previous is not app.states.get("SCENARIO_SETTINGS"):
            self.selected_entry = None
        self.reload_entries()

    def prepare_map(self, app):
        map_launch.open_saved_map(app, self.selected_save_path)
        return True

    def prepare_map_steps(self, app):
        return map_launch.open_saved_map_steps(app, self.selected_save_path)

    @property
    def scenario_dir(self):
        """Use the current directory override for the selected category."""
        attr = self.CATEGORIES[self.sub_state][1]
        return getattr(c, attr)

    def refresh_ui(self):
        self.build_browser(self.scenario_dir, "No scenarios in this category.")
        corner_x = c.SCREEN_WIDTH - self.CORNER_MARGIN - self.CORNER_BUTTON_SIZE[0]
        leaders_button = Button(corner_x, self.CORNER_MARGIN, self.CORNER_BUTTON_SIZE, "blue", "Historical Leaders",
                                self.open_historical_leaders_editor, font_preset="button_small")
        leaders_button.apply_state(enabled=self.sub_state == "HISTORICAL", color="blue")
        random_rect = self.category_button_rect(len(self.library_categories))
        random_button = Button(random_rect.x, random_rect.y, random_rect.size, "orange", "Random Scenario",
                               self.start_random_scenario, font_preset="button_small", sound_kind="select_category")
        random_button.fit_text = True
        random_button.fit_single_line = True
        self.elements.extend([
            make_back_button(self.exit_screen),
            leaders_button,
            random_button,
        ])
        self.add_category_footer_action("Scenario Settings", self.scenario_settings, "pink", slot=1)
        self.add_category_footer_action("Data Refresh", self.trigger_global_data_refresh, "purple")
        self.open_button = self.add_primary_action("Start Game")

    def activate_selected(self):
        if self.selection_can_open:
            play_ui_sound("click")
            entry = self.selected_entry
            self.start_scenario(entry.name, os.path.dirname(entry.path))

    def scenario_settings(self):
        Scenario_Settings.back_state = "NEW_GAME"
        self.go_to("SCENARIO_SETTINGS")

    def open_historical_leaders_editor(self):
        open_historical_leaders_editor(on_done=lambda screen: self.refresh_ui())

    def start_scenario(self, scenario_name, directory):
        self.selected_save_path = os.path.join(directory, scenario_name)
        # Pass the settings to the Map class
        self.map_settings = queries.get_scenario_settings() 
        self.go_to("MAP")

    REFRESH_FIELDS = [
        ("reset_names", "Country Names"),
        ("reset_colors", "Country Color"),
        ("reset_adjectives", "Adjectives"),
        ("reset_leaders", "Leader Names & Titles"),
        ("reset_flags", "Flags & Portraits"),
        ("reset_resources", "Starting Money (Manpower/Materials/Fuel)"),
        ("include_custom", "Include Scenarios in Custom/Editor Dir"),
    ]

    def trigger_global_data_refresh(self):
        """Calls the unified data refresh query for playable scenarios."""

        def on_picked(picked):
            if picked is None:
                return

            options = {key: key in picked for key, _label in self.REFRESH_FIELDS}

            dirs_to_check = [c.SCENARIOS_HISTORICAL_DIR, c.SCENARIOS_ALTERNATE_DIR]
            if options["include_custom"]:
                dirs_to_check.append(c.SCENARIOS_CUSTOM_DIR)

            # Confirm is silent so that an empty result plays only the popup's sound.
            if map_refresh.refresh_map_directories(self, dirs_to_check,
                                                   success_message="Synced scenarios successfully.", options=options):
                play_ui_sound("click")

        pickers.open_checkbox_list(
            self, "Refresh Options", "Select what to forcefully reset:",
            [CheckboxItem(key, label) for key, label in self.REFRESH_FIELDS],
            on_picked,
            footnote="If you don't know what you're doing, this might ruin your saved maps!",
            confirm_sound=None)

    def start_random_scenario(self):
        self.go_to("RANDOM_SETUP")
