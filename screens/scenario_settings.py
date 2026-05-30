import os
from gameState import GameState
from ui_elements import Button
import data.constants as c
from data import queries

class Scenario_Settings(GameState):
    def __init__(self):
        super().__init__()
        self.bg_color = (80, 20, 60)
        # Load persistent settings instead of creating defaults
        self.settings = queries.get_scenario_settings()
        if not self.settings:
            self.settings = {"fog_of_war": c.DEFAULT_FOG_OF_WAR}
        self.refresh_ui()

    def refresh_ui(self):
        self.elements = [
            Button(20, 20, "small", "red", "Back", self.exit_to_menu),
        ]
        
        # Toggle Button
        fog_color = "green" if self.settings.get("fog_of_war") else "red"
        fog_text = "Fog of War: ON" if self.settings.get("fog_of_war") else "Fog of War: OFF"
        
        self.elements.append(
            Button("centered", 200, "medium", fog_color, fog_text, self.toggle_fog)
        )

    def toggle_fog(self):
        self.settings["fog_of_war"] = not self.settings.get("fog_of_war", True)
        # Save immediately to the cache/file
        queries.save_scenario_settings(self.settings)
        self.refresh_ui()

    def exit_to_menu(self):
        self.next_state = "NEW_GAME"
        self.done = True

    def handle_back_key(self):
        self.exit_to_menu()