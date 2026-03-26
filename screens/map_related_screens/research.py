import pygame
from gameState import GameState, SCREEN_WIDTH, SCREEN_HEIGHT
from ui_elements import Button

class Research_Screen(GameState):
    def __init__(self):
        super().__init__()
        self.bg_color = (20, 20, 30)
        self.map_screen = None

    def start_research(self, map_ref):
        """Standard handoff for national-level menus."""
        self.map_screen = map_ref
        self.refresh_ui()

    def refresh_ui(self):
        self.elements = [
            Button(50, 50, "small", "red", "Back", self.exit_to_map)
        ]
        
        player = self.map_screen.player_country
        country_data = self.map_screen.nation_data.get(player, {})
        
        # Ensure the research dict exists
        if "research" not in country_data:
            country_data["research"] = {"cavalry": 0, "destroyer": 0, "armored_car": 0}
        
        res = country_data["research"]

        # Build buttons dynamically
        y_pos = 200
        for tech, level in res.items():
            txt = f"{tech.replace('_', ' ').title()}: Level {level}"
            # Using t=tech to preserve scope in the lambda
            btn = Button("centered", y_pos, "large", "blue", txt, lambda t=tech: self.upgrade_tech(t))
            self.elements.append(btn)
            y_pos += 90

    def upgrade_tech(self, tech_name):
        player = self.map_screen.player_country
        self.map_screen.nation_data[player]["research"][tech_name] += 1
        self.refresh_ui()

    def exit_to_map(self):
        self.next_state = "MAP"
        self.done = True
    
    def handle_back_key(self):
        self.exit_to_map()