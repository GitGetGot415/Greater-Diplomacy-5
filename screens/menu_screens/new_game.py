from tkinter import ttk
import os
import pygame
from gameState import GameState
from ui_elements import Button
import data.constants as c
from data import queries
from map_logic.rendering.font_manager import fonts
from ui.bars import ui_bars
from map_logic.system32 import loading_screen

class New_Game(GameState):
    back_state = "MENU"

    def __init__(self):
        super().__init__()
        self.bg_color = (0, 50, 0)
        self.selected_scenario_path = None
        self.settings_data = {"fog_of_war": c.DEFAULT_FOG_OF_WAR}
        self.sub_state = "CATEGORY" # "CATEGORY", "HISTORICAL", "ALTERNATE"
        
        # --- SCROLLING STATE ---
        self.scroll_y = 0
        self.max_scroll = 0
        self.is_dragging_scrollbar = False
        self.scroll_track_rect = None
        self.scroll_handle_rect = None
        
        # --- REFRESH STATE ---
        self.is_refreshing = False
        self.refresh_total = 0
        self.refresh_completed = 0
        self.refresh_status = ""
        
        self.refresh_ui()

    def set_sub_state(self, state):
        self.sub_state = state
        self.scroll_y = 0
        self.refresh_ui()

    def refresh_ui(self):
        self.elements = []
        
        if self.sub_state == "CATEGORY":
            self.elements = [
                Button(20, 20, "small", "red", "Back", self.exit_screen),
                Button("centered", 200, "large", "blue", "Historical Scenarios", lambda: self.set_sub_state("HISTORICAL")),
                Button("centered", 300, "large", "purple", "Alternate Scenarios", lambda: self.set_sub_state("ALTERNATE")),
                Button("centered", 400, "large", "green", "Map Editor Scenarios", lambda: self.set_sub_state("MAP_EDITOR")),
                Button("centered", 500, "large", "orange", "Random Scenario", self.start_random_scenario),
                Button(c.SCREEN_WIDTH - 220, c.SCREEN_HEIGHT - 160, "medium", "purple", "Data Refresh", self.trigger_global_data_refresh),
                Button(c.SCREEN_WIDTH - 220, c.SCREEN_HEIGHT - 80, "medium", "pink", "Scenario Settings", self.scenario_settings),
            ]
        else:
            self.elements = [
                Button(20, 20, "small", "red", "Back", lambda: self.set_sub_state("CATEGORY")),
                Button(c.SCREEN_WIDTH - 220, c.SCREEN_HEIGHT - 80, "medium", "pink", "Scenario Settings", self.scenario_settings),
            ]
            
            if self.sub_state == "HISTORICAL":
                scenario_dir = c.SCENARIOS_HISTORICAL_DIR  
            elif self.sub_state ==  "ALTERNATE":
                scenario_dir = c.SCENARIOS_ALTERNATE_DIR
            else:
                scenario_dir = c.SCENARIOS_CUSTOM_DIR
            if not os.path.exists(scenario_dir):
                os.makedirs(scenario_dir)
                
            scenarios = os.listdir(scenario_dir)
            
            # Calculate scroll boundaries
            total_content_height = len(scenarios) * 60
            self.max_scroll = min(0, (c.SCREEN_HEIGHT - 200) - total_content_height - 20)

            for i, name in enumerate(scenarios):
                btn_y = 200 + (i * 60) + self.scroll_y
                
                # Simple Y-based culling so we don't draw off-screen buttons
                if not (100 < btn_y < c.SCREEN_HEIGHT - 50):
                    continue

                # Standard centered layout for all playable scenarios
                self.elements.append(
                    Button("centered", btn_y, "new_game", "blue", name, 
                           lambda n=name, d=scenario_dir: self.start_scenario(n, d))
                )

    def update(self):
        super().update()
        
        # Forcefully hide all UI buttons while the loading screen is active
        if self.is_refreshing:
            for el in self.elements:
                el.visible = False
        else:
            for el in self.elements:
                el.visible = True

    def additional_events(self, event):
        if self.sub_state != "CATEGORY":
            self.handle_list_scroll(event)

    def handle_events(self, events):
        if self.is_refreshing:
            return
        for event in events:
            super().handle_events([event])
            self.additional_events(event)

    def additional_draw(self, surface):
        if self.sub_state == "CATEGORY":
            title_text = "NEW GAME"
        elif self.sub_state == "HISTORICAL":
            title_text = "HISTORICAL SCENARIOS"
        elif self.sub_state == "ALTERNATE":
            title_text = "ALTERNATE SCENARIOS"
        else:
            title_text = "MAP EDITOR SCENARIOS"
            
        ui_bars.draw_centered_title(surface, title_text, 40)

        if self.sub_state != "CATEGORY":
            # --- Draw Scrollbar ---
            self.scroll_track_rect, self.scroll_handle_rect = ui_bars.draw_standard_scrollbar(
                surface, self.scroll_y, self.max_scroll, 40, 160, c.SCREEN_HEIGHT - 200
            )

        # --- Draw Progress Bar Overlay ---
        if self.is_refreshing:
            loading_screen.draw_simple_refresh_bar(surface, self.refresh_status, self.refresh_completed, self.refresh_total)

    def scenario_settings(self):
        from screens.menu_screens.scenario_settings import Scenario_Settings
        Scenario_Settings.back_state = "NEW_GAME"
        self.next_state = "SCENARIO_SETTINGS"
        self.done = True

    def start_scenario(self, scenario_name, directory):
        self.selected_save_path = os.path.join(directory, scenario_name)
        # Pass the settings to the Map class
        self.map_settings = queries.get_scenario_settings() 
        self.set_sub_state("CATEGORY")
        self.next_state = "MAP"
        self.done = True

    def trigger_global_data_refresh(self):
        """Calls the unified data refresh query for playable scenarios."""
        import tkinter as tk
        from tkinter import messagebox
        from data import queries
        import data.constants as c
        
        dialog, close_menu = queries.create_managed_tk_window(self, "Refresh Options", "400x320")
        
        # Center the window
        dialog.update_idletasks()
        width = dialog.winfo_width()
        height = dialog.winfo_height()
        x = (dialog.winfo_screenwidth() // 2) - (width // 2)
        y = (dialog.winfo_screenheight() // 2) - (height // 2)
        dialog.geometry('{}x{}+{}+{}'.format(width, height, x, y))
        
        var_names = tk.BooleanVar(value=True)
        var_adj = tk.BooleanVar(value=True)
        var_leader = tk.BooleanVar(value=True)
        var_flags = tk.BooleanVar(value=True)
        var_custom = tk.BooleanVar(value=True)
        
        tk.Label(dialog, text="Select what to forcefully reset:", font=("Arial", 12, "bold")).pack(pady=10)
        
        tk.Checkbutton(dialog, text="Country Names", variable=var_names, font=("Arial", 11)).pack(anchor="w", padx=40)
        tk.Checkbutton(dialog, text="Adjectives", variable=var_adj, font=("Arial", 11)).pack(anchor="w", padx=40)
        tk.Checkbutton(dialog, text="Leader Names & Titles", variable=var_leader, font=("Arial", 11)).pack(anchor="w", padx=40)
        tk.Checkbutton(dialog, text="Flags & Portraits", variable=var_flags, font=("Arial", 11)).pack(anchor="w", padx=40)
        tk.Checkbutton(dialog, text="Include Scenarios in Custom/Editor Dir", variable=var_custom, font=("Arial", 11)).pack(anchor="w", padx=40)
        
        tk.Label(dialog, text="", font=("Arial", 8)).pack()
        tk.Label(dialog, text="If you don't know what you're doing, this might ruin your saved maps!", font=("Arial", 8)).pack()
        
        def on_confirm():
            options = {
                "reset_names": var_names.get(),
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

    def map_selected(self):
        self.next_state = "MAP"
        self.done = True

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
        self.next_state = "RANDOM_SETUP"
        self.done = True