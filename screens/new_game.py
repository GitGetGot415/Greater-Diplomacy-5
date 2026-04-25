# screens/new_game.py
import os
from gameState import GameState
from ui_elements import Button
from data.constants import SCENARIOS_DIR

class New_Game(GameState):
    def __init__(self):
        super().__init__()
        self.bg_color = (0, 50, 0)
        self.selected_scenario_path = None
        self.refresh_scenarios()

    def refresh_scenarios(self):
        self.elements = [
            Button(50, 50, "small", "red", "Back", self.exit_to_menu),
            # Added the Random button here
            Button("centered", "centered + 200", "large", "orange", "RANDOM SCENARIO", self.start_random_scenario),
            # Button("centered", "centered", "big", "red", "Check map tools", self.map_selected),
        ]
        
        # Look for scenarios in the scenarios folder
        scenario_dir = SCENARIOS_DIR
        if not os.path.exists(scenario_dir):
            os.makedirs(scenario_dir)
            
        scenarios = os.listdir(scenario_dir)
        for i, name in enumerate(scenarios):
            btn_y = 200 + (i * 100)
            # Create a button for each scenario
            self.elements.append(
                Button("centered", btn_y, "large", "blue", name, 
                       lambda n=name: self.start_scenario(n))
            )

    def map_selected(self):
        self.next_state = "MAP"
        self.done = True
    
    def start_scenario(self, scenario_name):
        # We pass the path to the scenario folder

        # selected save path not scenario path because scenario path doesn't seem to be working
        self.selected_save_path = os.path.join(SCENARIOS_DIR, scenario_name)
        self.next_state = "MAP"
        self.done = True

    def exit_to_menu(self):
        self.next_state = "MENU"
        self.done = True

    def handle_back_key(self):
        self.exit_to_menu()

    def start_random_scenario(self):
        self.next_state = "RANDOM_SETUP"
        self.done = True