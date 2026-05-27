# screens/new_game.py
import os
from gameState import GameState
from ui_elements import Button
import data.constants as c

class New_Game(GameState):
    def __init__(self):
        super().__init__()
        self.bg_color = (0, 50, 0)
        self.selected_scenario_path = None
        self.refresh_scenarios()

    def refresh_scenarios(self):
        self.elements = [
            Button(20, 20, "small", "red", "Back", self.exit_to_menu),
            Button("centered", "centered + 200", "new_game", "orange", "RANDOM SCENARIO", self.start_random_scenario),
            # Button for global data refresh positioned via configuration anchors
            Button(c.SCREEN_WIDTH - 220, c.SCREEN_HEIGHT - 80, "small", "blue", "Data Refresh", self.trigger_global_data_refresh),
        ]
        
        # Look for scenarios in the scenarios folder
        scenario_dir = c.SCENARIOS_DIR
        if not os.path.exists(scenario_dir):
            os.makedirs(scenario_dir)
            
        scenarios = os.listdir(scenario_dir)
        for i, name in enumerate(scenarios):
            btn_y = 200 + (i * 60)
            # Create a button for each scenario
            self.elements.append(
                Button("centered", btn_y, "new_game", "blue", name, 
                       lambda n=name: self.start_scenario(n))
            )

    def trigger_global_data_refresh(self):
        """Headlessly instantiates each map scenario to execute its native validation, scrubbing, and data rewrite pipelines."""
        from screens.map import Map
        
        scenario_dir = c.SCENARIOS_DIR
        if not os.path.exists(scenario_dir):
            return

        scenarios = os.listdir(scenario_dir)
        scenarios_processed = 0

        for name in scenarios:
            scenario_path = os.path.join(scenario_dir, name)
            
            # Boundary guard to ensure it's a valid directory file structure containing a scenario anchor
            if not os.path.isdir(scenario_path) or not os.path.exists(os.path.join(scenario_path, "map_data.json")):
                continue
                
            try:
                # 1. Instantiate the working Map engine pointing directly at the scenario directory
                # This headlessly runs load_map_assets behind the scenes without drawing onto the display canvas
                temp_map_context = Map(load_path=scenario_path, is_scenario=True)
                
                # 2. Leverage your master resync function (includes sub-modules like sync_units_to_data)
                temp_map_context.refresh_nation_data()
                print(f"refreshed")
                # 3. Leverage the map's native disk writer to serialize cleanly onto the disk
                temp_map_context.save_map_data()
                
                scenarios_processed += 1
            except Exception as e:
                print(f"[REFRESH ERROR] Failed to automatically sync structural data profiles for scenario '{name}': {e}")

        # Post an alert back onto the UI layout template frame
        print(f"Synced {scenarios_processed} scenarios!")

    def map_selected(self):
        self.next_state = "MAP"
        self.done = True
    
    def start_scenario(self, scenario_name):
        # We pass the path to the scenario folder

        # selected save path not scenario path because scenario path doesn't seem to be working
        self.selected_save_path = os.path.join(c.SCENARIOS_DIR, scenario_name)
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