import os
import pygame
from gameState import GameState
from ui_elements import Button, make_back_button
import data.constants as c
from data import queries
from map_logic.system32 import loading_screen

class New_Game(GameState):
    back_state = "MENU"

    ROW_HEIGHT = 60
    ROW_TOP = 200
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

        # --- REFRESH STATE ---
        self.is_refreshing = False
        self.refresh_total = 0
        self.refresh_completed = 0
        self.refresh_status = ""

        self.refresh_ui()

    def get_title(self):
        return self.CATEGORIES[self.sub_state][0]

    @property
    def scenario_dir(self):
        """Directory for the current sub-state, or None on the category menu.

        Resolved off `c` by name each time so the Settings screen's live
        directory overrides are picked up.
        """
        attr = self.CATEGORIES[self.sub_state][1]
        return getattr(c, attr) if attr else None

    def set_sub_state(self, state):
        self.sub_state = state
        self.scroll_y = 0
        self.refresh_ui()

    def refresh_ui(self):
        settings_btn = Button(c.SCREEN_WIDTH - 220, c.SCREEN_HEIGHT - 80, "medium", "pink",
                              "Scenario Settings", self.scenario_settings)

        if self.sub_state == "CATEGORY":
            self.elements = [
                make_back_button(self.exit_screen),
                Button("centered", 200, "large", "blue", "Historical Scenarios", lambda: self.set_sub_state("HISTORICAL")),
                Button("centered", 300, "large", "purple", "Alternate Scenarios", lambda: self.set_sub_state("ALTERNATE")),
                Button("centered", 400, "large", "green", "Map Editor Scenarios", lambda: self.set_sub_state("MAP_EDITOR")),
                Button("centered", 500, "large", "orange", "Random Scenario", self.start_random_scenario),
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
        scenarios = os.listdir(scenario_dir)

        # Standard centered layout for all playable scenarios
        self.scroll_content_rect = pygame.Rect(0, 100, c.SCREEN_WIDTH, (c.SCREEN_HEIGHT - 50) - 100)
        for i, btn_y in self.layout_list_rows(len(scenarios), self.ROW_HEIGHT, self.ROW_TOP, pad=20):
            btn = Button("centered", btn_y, "new_game", "blue", scenarios[i],
                        lambda n=scenarios[i], d=scenario_dir: self.start_scenario(n, d))
            btn.is_scrollable = True
            btn.click_guard = self.scroll_click_guard
            self.elements.append(btn)

    def update(self):
        super().update()

        # Forcefully hide all UI buttons while the loading screen is active
        for el in self.elements:
            el.visible = not self.is_refreshing

    def additional_events(self, event):
        if self.sub_state != "CATEGORY":
            self.handle_list_scroll(event, content_rect_attr="scroll_content_rect")

    def handle_events(self, events):
        # GameState.handle_events already dispatches additional_events, so this
        # only adds the "ignore input while refreshing" gate.
        if self.is_refreshing:
            return
        super().handle_events(events)

    def additional_draw(self, surface):
        if self.sub_state != "CATEGORY":
            self.draw_list_scrollbar(surface, 40, 160, c.SCREEN_HEIGHT - 200)

        # --- Draw Progress Bar Overlay ---
        if self.is_refreshing:
            loading_screen.draw_simple_refresh_bar(surface, self.refresh_status, self.refresh_completed, self.refresh_total)

    def scenario_settings(self):
        from screens.menu_screens.scenario_settings import Scenario_Settings
        Scenario_Settings.back_state = "NEW_GAME"
        self.go_to("SCENARIO_SETTINGS")

    def open_historical_leaders_editor(self):
        from ui.historical_leaders_editor import open_historical_leaders_editor
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
        from data import queries
        import data.constants as c
        from ui.checkbox_list_screen import CheckboxItem

        def on_picked(picked):
            if picked is None:
                return

            options = {key: key in picked for key, _label in self.REFRESH_FIELDS}

            dirs_to_check = [c.SCENARIOS_HISTORICAL_DIR, c.SCENARIOS_ALTERNATE_DIR]
            if options["include_custom"]:
                dirs_to_check.append(c.SCENARIOS_CUSTOM_DIR)

            queries.refresh_map_directories(self, dirs_to_check,
                                            success_message="Synced scenarios successfully.", options=options)

        queries.open_checkbox_list(
            self, "Refresh Options", "Select what to forcefully reset:",
            [CheckboxItem(key, label, checked=True) for key, label in self.REFRESH_FIELDS],
            on_picked,
            footnote="If you don't know what you're doing, this might ruin your saved maps!")

    def exit_screen(self):
        self.set_sub_state("CATEGORY")
        super().exit_screen()

    def handle_back_key(self):
        # Escape steps back up the category tree before it leaves the screen.
        if self.sub_state != "CATEGORY":
            self.set_sub_state("CATEGORY")
        else:
            self.exit_screen()

    def start_random_scenario(self):
        self.set_sub_state("CATEGORY")
        self.go_to("RANDOM_SETUP")