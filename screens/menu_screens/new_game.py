import os
from gameState import GameState
from ui_elements import Button
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
                Button(20, 20, "small", "red", "Back", self.exit_screen),
                Button("centered", 200, "large", "blue", "Historical Scenarios", lambda: self.set_sub_state("HISTORICAL")),
                Button("centered", 300, "large", "purple", "Alternate Scenarios", lambda: self.set_sub_state("ALTERNATE")),
                Button("centered", 400, "large", "green", "Map Editor Scenarios", lambda: self.set_sub_state("MAP_EDITOR")),
                Button("centered", 500, "large", "orange", "Random Scenario", self.start_random_scenario),
                Button(c.SCREEN_WIDTH - 220, c.SCREEN_HEIGHT - 160, "medium", "purple", "Data Refresh", self.trigger_global_data_refresh),
                settings_btn,
            ]
            return

        self.elements = [
            Button(20, 20, "small", "red", "Back", lambda: self.set_sub_state("CATEGORY")),
            settings_btn,
        ]

        scenario_dir = self.scenario_dir
        if not os.path.exists(scenario_dir):
            os.makedirs(scenario_dir)
        scenarios = os.listdir(scenario_dir)

        # Standard centered layout for all playable scenarios
        for i, btn_y in self.layout_list_rows(len(scenarios), self.ROW_HEIGHT, self.ROW_TOP, pad=20):
            self.elements.append(
                Button("centered", btn_y, "new_game", "blue", scenarios[i],
                       lambda n=scenarios[i], d=scenario_dir: self.start_scenario(n, d))
            )

    def update(self):
        super().update()

        # Forcefully hide all UI buttons while the loading screen is active
        for el in self.elements:
            el.visible = not self.is_refreshing

    def additional_events(self, event):
        if self.sub_state != "CATEGORY":
            self.handle_list_scroll(event)

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

    def start_scenario(self, scenario_name, directory):
        self.selected_save_path = os.path.join(directory, scenario_name)
        # Pass the settings to the Map class
        self.map_settings = queries.get_scenario_settings() 
        self.set_sub_state("CATEGORY")
        self.go_to("MAP")

    def trigger_global_data_refresh(self):
        """Calls the unified data refresh query for playable scenarios."""
        import tkinter as tk
        from tkinter import messagebox
        from data import queries
        import data.constants as c
        
        dialog, close_menu = queries.create_managed_tk_window(self, "Refresh Options", "400x350")
        
        # Center the window
        dialog.update_idletasks()
        width = dialog.winfo_width()
        height = dialog.winfo_height()
        x = (dialog.winfo_screenwidth() // 2) - (width // 2)
        y = (dialog.winfo_screenheight() // 2) - (height // 2)
        dialog.geometry('{}x{}+{}+{}'.format(width, height, x, y))
        
        var_names = tk.BooleanVar(value=True)
        var_color = tk.BooleanVar(value=True)
        var_adj = tk.BooleanVar(value=True)
        var_leader = tk.BooleanVar(value=True)
        var_flags = tk.BooleanVar(value=True)
        var_custom = tk.BooleanVar(value=True)

        tk.Label(dialog, text="Select what to forcefully reset:", font=("Arial", 12, "bold")).pack(pady=10)

        tk.Checkbutton(dialog, text="Country Names", variable=var_names, font=("Arial", 11)).pack(anchor="w", padx=40)
        tk.Checkbutton(dialog, text="Country Color", variable=var_color, font=("Arial", 11)).pack(anchor="w", padx=40)
        tk.Checkbutton(dialog, text="Adjectives", variable=var_adj, font=("Arial", 11)).pack(anchor="w", padx=40)
        tk.Checkbutton(dialog, text="Leader Names & Titles", variable=var_leader, font=("Arial", 11)).pack(anchor="w", padx=40)
        tk.Checkbutton(dialog, text="Flags & Portraits", variable=var_flags, font=("Arial", 11)).pack(anchor="w", padx=40)
        tk.Checkbutton(dialog, text="Include Scenarios in Custom/Editor Dir", variable=var_custom, font=("Arial", 11)).pack(anchor="w", padx=40)
        
        tk.Label(dialog, text="", font=("Arial", 8)).pack()
        tk.Label(dialog, text="If you don't know what you're doing, this might ruin your saved maps!", font=("Arial", 8)).pack()
        
        def on_confirm():
            options = {
                "reset_names": var_names.get(),
                "reset_colors": var_color.get(),
                "reset_adjectives": var_adj.get(),
                "reset_leaders": var_leader.get(),
                "reset_flags": var_flags.get(),
                "include_custom": var_custom.get(),
            }
            close_menu()
            
            dirs_to_check = [c.SCENARIOS_HISTORICAL_DIR, c.SCENARIOS_ALTERNATE_DIR]
            if options["include_custom"]:
                dirs_to_check.append(c.SCENARIOS_CUSTOM_DIR)
                
            queries.refresh_map_directories(self, dirs_to_check, success_message="Synced scenarios successfully.", options=options)
            
        btn_frame = tk.Frame(dialog)
        btn_frame.pack(pady=20)
        tk.Button(btn_frame, text="Confirm", command=on_confirm, width=12, bg="#4CAF50", fg="white", font=("Arial", 10, "bold")).pack(side="left", padx=15)
        tk.Button(btn_frame, text="Cancel", command=close_menu, width=12, bg="#f44336", fg="white", font=("Arial", 10, "bold")).pack(side="left", padx=15)
        
        queries.run_tk_loop(self, dialog)

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