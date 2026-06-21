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
        
        self.refresh_scenarios()

    def set_sub_state(self, state):
        self.sub_state = state
        self.scroll_y = 0
        self.refresh_scenarios()

    def refresh_scenarios(self):
        self.elements = []
        
        if self.sub_state == "CATEGORY":
            self.elements = [
                Button(20, 20, "small", "red", "Back", self.exit_to_menu),
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
        if getattr(self, 'is_refreshing', False):
            for el in self.elements:
                el.visible = False
        else:
            for el in self.elements:
                el.visible = True

    # --- SCROLL LOGIC ---
    def _snap_scroll(self, my):
        self.scroll_y = ui_bars.calculate_scroll_snap(my, self.max_scroll, 200, c.SCREEN_HEIGHT - 200)
        self.refresh_scenarios()

    def additional_events(self, event):
        # 1. Scrolling Logic
        if self.sub_state != "CATEGORY":
            if event.type == pygame.MOUSEWHEEL:
                self.scroll_y += event.y * 40
                self.scroll_y = max(self.max_scroll, min(0, self.scroll_y))
                self.refresh_scenarios()

            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                mx, my = event.pos
                if self.scroll_handle_rect and self.scroll_handle_rect.collidepoint(mx, my):
                    self.is_dragging_scrollbar = True
                elif self.scroll_track_rect and self.scroll_track_rect.collidepoint(mx, my):
                    self.is_dragging_scrollbar = True
                    self._snap_scroll(my)

            elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                self.is_dragging_scrollbar = False

            elif event.type == pygame.MOUSEMOTION and self.is_dragging_scrollbar:
                self._snap_scroll(event.pos[1])

    def handle_events(self, events):
        if getattr(self, 'is_refreshing', False):
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
                surface, self.scroll_y, self.max_scroll, c.SCREEN_WIDTH - 40, 200, c.SCREEN_HEIGHT - 200
            )

        # --- Draw Progress Bar Overlay ---
        if getattr(self, 'is_refreshing', False):
            loading_screen.draw_simple_refresh_bar(surface, self.refresh_status, self.refresh_completed, self.refresh_total)

    def scenario_settings(self):
        from screens.scenario_settings import Scenario_Settings
        Scenario_Settings.return_screen = "NEW_GAME"
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
        
        root = queries.get_transient_tk_root()
        confirm = messagebox.askyesno(
            "Confirm Data Refresh",
            "Are you sure you want to refresh all scenarios?\nThis process may take a while.",
            parent=root
        )
        queries.destroy_tk_root(root)
        
        if confirm:
            dirs_to_check = [c.SCENARIOS_HISTORICAL_DIR, c.SCENARIOS_ALTERNATE_DIR, c.SCENARIOS_CUSTOM_DIR]
            queries.refresh_map_directories(self, dirs_to_check, success_message="Synced scenarios successfully.")

    def map_selected(self):
        self.next_state = "MAP"
        self.done = True

    def exit_to_menu(self):
        self.set_sub_state("CATEGORY")
        self.next_state = "MENU"
        self.done = True
    
    def handle_back_key(self):
        if self.sub_state != "CATEGORY":
            self.set_sub_state("CATEGORY")
        else:
            self.exit_to_menu()

    def start_random_scenario(self):
        self.set_sub_state("CATEGORY")
        self.next_state = "RANDOM_SETUP"
        self.done = True