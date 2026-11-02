import os
from ui.navigation.game_state import ButtonMenuScreen, RefreshingMenuListScreen
from ui.widgets.ui_elements import play_ui_sound
from ui.widgets.ui_elements import Button, make_back_button
import data.constants as c
from data import queries
from ui.dialogs import pickers
from screens.setup import map_refresh
from screens.setup.scenario_settings import Scenario_Settings
from screens.editors.historical_leaders_editor import open_historical_leaders_editor
from ui.dialogs.checkbox_list_screen import CheckboxItem


class New_Game(RefreshingMenuListScreen):
    back_state = "MENU"

    # sub_state -> (header text, scenario directory). None means the category menu.
    CATEGORIES = {
        "CATEGORY": ("NEW GAME", None),
        "HISTORICAL": ("HISTORICAL SCENARIOS", "SCENARIOS_HISTORICAL_DIR"),
        "ALTERNATE": ("ALTERNATE SCENARIOS", "SCENARIOS_ALTERNATE_DIR"),
        "MAP_EDITOR": ("MAP EDITOR SCENARIOS", "SCENARIOS_CUSTOM_DIR"),
    }

    def __init__(self):
        super().__init__()
        self.bg_color = (0, 50, 0)
        self.selected_scenario_path = None
        self.settings_data = {"fog_of_war": c.DEFAULT_FOG_OF_WAR}
        self.sub_state = "CATEGORY" # "CATEGORY", "HISTORICAL", "ALTERNATE"
        self.refresh_ui()

    def get_title(self):
        return self.CATEGORIES[self.sub_state][0]

    def has_menu_list(self):
        return self.sub_state != "CATEGORY"

    @property
    def scenario_dir(self):
        """Directory for the current sub-state, or None on the category menu.

        Resolved off `c` by name each time so the Settings screen's live
        directory overrides are picked up.
        """
        attr = self.CATEGORIES[self.sub_state][1]
        return getattr(c, attr) if attr else None

    def refresh_ui(self):
        settings_btn = Button(c.SCREEN_WIDTH - 220, c.SCREEN_HEIGHT - 80, "medium", "pink",
                              "Scenario Settings", self.scenario_settings)

        if self.sub_state == "CATEGORY":
            self.elements = [
                make_back_button(self.exit_screen),
                *ButtonMenuScreen.build_menu_buttons([
                    ("Historical Scenarios", "blue", lambda: self.set_sub_state("HISTORICAL")),
                    ("Alternate Scenarios", "purple", lambda: self.set_sub_state("ALTERNATE")),
                    ("Map Editor Scenarios", "green", lambda: self.set_sub_state("MAP_EDITOR")),
                    ("Random Scenario", "orange", self.start_random_scenario),
                ]),
                Button(c.SCREEN_WIDTH - 220, c.SCREEN_HEIGHT - 160, "medium", "purple", "Data Refresh", self.trigger_global_data_refresh),
                settings_btn,
            ]
            return

        self.elements = [
            make_back_button(lambda: self.set_sub_state("CATEGORY")),
            settings_btn,
        ]

        if self.sub_state == "HISTORICAL":
            history_btn = Button(c.SCREEN_WIDTH - 240, 20, "medium", "purple", "Historical Leaders",
                                 self.open_historical_leaders_editor)
            self.elements.append(history_btn)

        scenario_dir = self.scenario_dir
        if not os.path.exists(scenario_dir):
            os.makedirs(scenario_dir)
        scenarios = [s for s in os.listdir(scenario_dir) if not s.startswith(".")]

        # Standard centered layout for all playable scenarios
        self.add_menu_list([(name, name) for name in scenarios],
                           lambda name, d=scenario_dir: self.start_scenario(name, d))

    def scenario_settings(self):
        Scenario_Settings.back_state = "NEW_GAME"
        self.go_to("SCENARIO_SETTINGS")

    def open_historical_leaders_editor(self):
        open_historical_leaders_editor(on_done=lambda screen: self.refresh_ui())

    def start_scenario(self, scenario_name, directory):
        self.selected_save_path = os.path.join(directory, scenario_name)
        # Pass the settings to the Map class
        self.map_settings = queries.get_scenario_settings() 
        self.set_sub_state("CATEGORY")
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

            map_refresh.refresh_map_directories(self, dirs_to_check,
                                            success_message="Synced scenarios successfully.", options=options)

        pickers.open_checkbox_list(
            self, "Refresh Options", "Select what to forcefully reset:",
            [CheckboxItem(key, label) for key, label in self.REFRESH_FIELDS],
            on_picked,
            footnote="If you don't know what you're doing, this might ruin your saved maps!")

    def exit_screen(self):
        self.set_sub_state("CATEGORY")
        super().exit_screen()

    def handle_back_key(self):
        # Escape steps back up the category tree before it leaves the screen.
        if self.sub_state != "CATEGORY":
            play_ui_sound("back")
            self.set_sub_state("CATEGORY")
        else:
            self.go_back()

    def start_random_scenario(self):
        self.set_sub_state("CATEGORY")
        self.go_to("RANDOM_SETUP")
