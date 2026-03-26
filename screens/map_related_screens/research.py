import pygame
from gameState import GameState, SCREEN_WIDTH, SCREEN_HEIGHT
from ui_elements import Button

# Configuration for how long levels take (e.g., Level 1 = 20 days, Level 2 = 40 days)
RESEARCH_BASE_TIME = 20 

class Research_Screen(GameState):
    def __init__(self):
        super().__init__()
        self.bg_color = (20, 20, 30)
        self.map_screen = None

    def start_research(self, map_ref):
        self.map_screen = map_ref
        self.refresh_ui()

    def refresh_ui(self):
        self.elements = [
            Button(50, 50, "small", "red", "Back", self.exit_to_map)
        ]
        
        player = self.map_screen.player_country
        country_data = self.map_screen.nation_data.get(player, {})
        
        # Ensure data structures exist
        if "research" not in country_data:
            country_data["research"] = {"cavalry": 0, "destroyer": 0, "armored_car": 0}
        if "research_queue" not in country_data:
            country_data["research_queue"] = []
        
        res = country_data["research"]
        queue = country_data["research_queue"]
        queue_count = len(queue)

        y_pos = 150
        for tech, level in res.items():
            # Check if this tech is specifically in the queue
            queued_item = next((item for item in queue if item["tech_name"] == tech), None)
            
            if queued_item:
                status_text = f"{tech.title()}: Researching... ({queued_item['days_remaining']} days)"
                color = "green" # Changed to green to show it's active
                callback = lambda: None
            elif queue_count >= 2:
                # Slot limit reached
                status_text = f"{tech.title()} (Research Slots Full)"
                color = "grey"
                callback = lambda: self.map_screen.show_feedback("Maximum 2 research projects allowed!")
            else:
                status_text = f"Research {tech.title()} (Lvl {level} -> {level+1})"
                color = "blue"
                callback = lambda t=tech: self.add_to_research_queue(t)

            btn = Button("centered", y_pos, "large", color, status_text, callback)
            self.elements.append(btn)
            y_pos += 90

    def add_to_research_queue(self, tech_name):
        player = self.map_screen.player_country
        country_data = self.map_screen.nation_data[player]
        
        # Final safety check for the 2-slot limit
        if len(country_data.get("research_queue", [])) >= 2:
            self.map_screen.show_feedback("Research slots full!")
            return

        current_level = country_data["research"].get(tech_name, 0)
        # Using 30 days as a base for this example
        duration = 30 + (current_level * 15) 
        
        new_project = {
            "tech_name": tech_name,
            "days_remaining": duration
        }
        
        country_data["research_queue"].append(new_project)
        self.map_screen.show_feedback(f"Started {tech_name.title()}")
        self.refresh_ui()

    def exit_to_map(self):
        self.next_state = "MAP"
        self.done = True

    def additional_draw(self, surface):
        font = pygame.font.SysFont("Arial", 32)
        title = font.render(f"NATIONAL RESEARCH - {self.map_screen.player_country.upper()}", True, (255, 255, 255))
        surface.blit(title, (SCREEN_WIDTH//2 - title.get_width()//2, 50))

    def handle_back_key(self):
        self.exit_to_map()