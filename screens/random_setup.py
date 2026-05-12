import os
from gameState import GameState
import data.constants as c
from ui_elements import Button, Slider
from map_logic.rendering.font_manager import fonts
from data import queries

class Random_Setup(GameState):
    def __init__(self):
        # Track if we are doing a procedural world
        self.procedural_world = False
        
        # Track the active procedural algorithm
        self.procedural_types = ["Grid", "Voronoi", "Cellular Automata"]
        self.proc_type_index = 0

        super().__init__()
        self.bg_color = (20, 50, 20)
        
        # Load maps and calculate max countries
        self.available_maps = os.listdir(c.BASE_MAPS_DIR) if os.path.exists(c.BASE_MAPS_DIR) else []
        self.map_index = 0
        
        self.max_countries = self.calculate_max_countries()
        
        self.reset_to_defaults()
        self.refresh_ui()

    def calculate_max_countries(self):
        data = queries.get_country_data()
        playable = sum(1 for n, d in data.items() if d.get("is_playable"))
        return max(1, playable) # Fallback to 1

    def reset_to_defaults(self):
        """Sets default year to START_YEAR and countries to ~10% of the map."""
        self.current_year = c.START_YEAR
        # Dynamically calculate the slider range
        self.year_slider_val = (self.current_year - c.START_YEAR) / (c.END_YEAR - c.START_YEAR)
        
        self.current_countries = min(20, self.max_countries)
        self.country_slider_val = self.current_countries / self.max_countries
        
        self.map_index = 0

    def toggle_procedural_type(self):
        self.proc_type_index = (self.proc_type_index + 1) % len(self.procedural_types)
        self.refresh_ui()

    def refresh_ui(self):
        self.elements = [
            Button(50, 50, "small", "red", "Back", self.go_back),
            
            # Sliders 
            Slider((c.SCREEN_WIDTH/2) - 100, 300, 200, f"Countries: {self.current_countries}", self.country_slider_val, self.update_countries),
            Slider((c.SCREEN_WIDTH/2) - 100, 400, 200, f"Start Year: {self.current_year}", self.year_slider_val, self.update_year),
            
            # Controls
            Button("centered", 500, "medium", "grey", "Reset Defaults", self.do_reset),
            Button("centered", 600, "large", "green", "START GAME", self.start_game),
            
            # --- NEW: The Procedural Generation Button ---
            Button(100, 100, "large", "orange" if self.procedural_world else "grey", 
                "RANDOM NEW WORLD (PROCEDURAL)", self.toggle_procedural)
        ]
        
        # Hide the map selection grid if procedural world is checked
        if self.procedural_world:
            map_type_str = self.procedural_types[self.proc_type_index]
            self.elements.append(
                Button(100, 180, "large", "blue", f"Type: {map_type_str}", self.toggle_procedural_type)
            )
        else:
            if not self.available_maps:
                self.elements.append(Button("centered", 200, "large", "grey", "No Maps Found", lambda: None))
            else:
                cols = min(5, len(self.available_maps))
                grid_width = cols * 220
                start_x = (c.SCREEN_WIDTH - grid_width) // 2 + 10 
                start_y = 180
                
                for i, map_name in enumerate(self.available_maps):
                    col = i % cols
                    row = i // cols
                    btn = Button(start_x + (col * 220), start_y + (row * 60), "medium", "blue", map_name, lambda idx=i: self.select_map(idx))
                    if i == self.map_index:
                        btn.is_selected = True 
                    self.elements.append(btn)

    def select_map(self, idx):
        self.map_index = idx
        self.refresh_ui()

    def update_countries(self, val):
        self.country_slider_val = val
        self.current_countries = max(1, int(val * self.max_countries))
        # Directly update the text on the existing slider at Index 1
        self.elements[1].text = f"Countries: {self.current_countries}"

    def update_year(self, val):
        self.year_slider_val = val
        # Dynamically scale the value based on the total timeline gap
        self.current_year = int(c.START_YEAR + (val * (c.END_YEAR - c.START_YEAR)))
        self.elements[2].text = f"Start Year: {self.current_year}"

    def do_reset(self):
        self.reset_to_defaults()
        self.refresh_ui()
        
    def additional_draw(self, surface):
        title = fonts.get("heading1").render("RANDOM SCENARIO SETUP", True, (255, 255, 255))
        surface.blit(title, (c.SCREEN_WIDTH // 2 - title.get_width() // 2, 40))
        
        map_title = fonts.get("heading2").render("Select Base Map", True, (200, 200, 200))
        surface.blit(map_title, (c.SCREEN_WIDTH // 2 - map_title.get_width() // 2, 130))

    def toggle_procedural(self):
        self.procedural_world = not self.procedural_world
        self.refresh_ui()

    def start_game(self):
        if not self.procedural_world and not self.available_maps: return
        
        selected_path = "PROCEDURAL" if self.procedural_world else os.path.join(c.BASE_MAPS_DIR, self.available_maps[self.map_index])
        
        self.random_settings = {
            "map_path": selected_path,
            "countries": self.current_countries,
            "year": self.current_year,
            "procedural_type": self.procedural_types[self.proc_type_index]
        }
        self.next_state = "MAP"
        self.done = True

    def go_back(self):
        self.next_state = "NEW_GAME"
        self.done = True
        
    def handle_back_key(self):
        self.go_back()