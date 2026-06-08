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
        
        self.current_island_size = getattr(c, 'RANDOM_SCENARIO_DEFAULT_ISLAND_FILTER', 5)
        max_island = getattr(c, 'RANDOM_SCENARIO_MAX_ISLAND_FILTER', 50)
        self.island_size_slider_val = (self.current_island_size - 1) / (max_island - 1)
        
        self.single_tile_start = getattr(c, 'RANDOM_SCENARIO_SINGLE_TILE_START', False)
        self.resource_chance = getattr(c, 'RANDOM_SCENARIO_DEFAULT_RESOURCE_CHANCE', 0.15)
        self.resource_slider_val = self.resource_chance
        
        self.base_days_per_turn = getattr(c, 'DEFAULT_DAYS_PER_TURN', 15)
        self.map_index = 0

    def toggle_procedural_type(self):
        self.proc_type_index = (self.proc_type_index + 1) % len(self.procedural_types)
        self.refresh_ui()

    def toggle_procedural(self):
        self.procedural_world = True
        self.refresh_ui()

    def select_map(self, idx):
        self.procedural_world = False
        self.map_index = idx
        self.refresh_ui()

    def update_countries(self, val):
        self.country_slider_val = val
        self.current_countries = max(1, int(val * self.max_countries))
        if hasattr(self, 'country_slider'):
            self.country_slider.text = f"Countries: {self.current_countries}"

    def update_year(self, val):
        self.year_slider_val = val
        self.current_year = int(c.START_YEAR + (val * (c.END_YEAR - c.START_YEAR)))
        if hasattr(self, 'year_slider'):
            self.year_slider.text = f"Start Year: {self.current_year}"

    def update_island_size(self, val):
        self.island_size_slider_val = val
        max_island = getattr(c, 'RANDOM_SCENARIO_MAX_ISLAND_FILTER', 50)
        self.current_island_size = 1 + int(val * (max_island - 1))
        if hasattr(self, 'island_slider'):
            self.island_slider.text = f"Island Filter Size: {self.current_island_size}"

    def update_resource_chance(self, val):
        self.resource_slider_val = val
        self.resource_chance = val
        if hasattr(self, 'resource_slider'):
            self.resource_slider.text = f"Resource Spawn: {int(self.resource_chance * 100)}%"

    def toggle_single_tile(self):
        self.single_tile_start = not self.single_tile_start
        self.refresh_ui()

    def toggle_days_per_turn(self):
        options = [5, 10, 15, 30]
        if self.base_days_per_turn in options:
            idx = options.index(self.base_days_per_turn)
            self.base_days_per_turn = options[(idx + 1) % len(options)]
        else:
            self.base_days_per_turn = 15
        self.refresh_ui()

    def scenario_settings(self):
        from screens.scenario_settings import Scenario_Settings
        Scenario_Settings.return_screen = "RANDOM_SETUP"
        self.next_state = "SCENARIO_SETTINGS"
        self.done = True

    def refresh_ui(self):
        self.country_slider = Slider((c.SCREEN_WIDTH/2) - 100, 300, 200, f"Countries: {self.current_countries}", self.country_slider_val, self.update_countries)
        self.year_slider = Slider((c.SCREEN_WIDTH/2) - 100, 360, 200, f"Start Year: {self.current_year}", self.year_slider_val, self.update_year)
        self.island_slider = Slider((c.SCREEN_WIDTH/2) - 100, 420, 200, f"Island Filter Size: {self.current_island_size}", self.island_size_slider_val, self.update_island_size)
        self.resource_slider = Slider((c.SCREEN_WIDTH/2) - 100, 480, 200, f"Resource Spawn: {int(self.resource_chance * 100)}%", self.resource_slider_val, self.update_resource_chance)
        
        self.elements = [
            Button(20, 20, "small", "red", "Back", self.go_back),
            Button(c.SCREEN_WIDTH - 220, c.SCREEN_HEIGHT - 80, "medium", "pink", "Scenario Settings", self.scenario_settings),
            
            # Sliders 
            self.country_slider,
            self.year_slider,
            self.island_slider,
            self.resource_slider,
            
            # Controls
            Button((c.SCREEN_WIDTH/2) + 120, 470, "medium", "green" if self.single_tile_start else "red", f"1-Tile Start: {'ON' if self.single_tile_start else 'OFF'}", self.toggle_single_tile),
            Button("centered", 550, "medium", "blue", f"Base Days Per Turn: {self.base_days_per_turn}", self.toggle_days_per_turn),
            Button("centered", 630, "medium", "grey", "Reset Defaults", self.do_reset),
            Button("centered", 710, "large", "green", "START GAME", self.start_game),
        ]
        
        random_map_x = 100
        random_map_y = 120

        # 1. Isolated Procedural Options (Placed above the table display)
        if self.procedural_world:
            # Side-by-side positioning when procedural is active
            proc_x = (c.SCREEN_WIDTH // 2) - 210
            type_x = (c.SCREEN_WIDTH // 2) + 10
            
            proc_btn = Button(random_map_x, random_map_y, "medium", "blue", "Random Map", self.toggle_procedural)
            proc_btn.is_selected = True
            self.elements.append(proc_btn)
            
            map_type_str = self.procedural_types[self.proc_type_index]
            self.elements.append(
                Button(random_map_x + 220, random_map_y, "medium", "red", f"Type: {map_type_str}", self.toggle_procedural_type)
            )
        else:
            # Perfectly centered when it's the lone option
            proc_btn = Button(random_map_x, random_map_y, "medium", "blue", "Random Map", self.toggle_procedural)
            self.elements.append(proc_btn)
        
        # 2. Base Maps Table Layout
        total_items = len(self.available_maps)
        cols = min(5, max(1, total_items))
        grid_width = cols * 220
        start_x = (c.SCREEN_WIDTH - grid_width) // 2 + 10 
        start_y = 180
        
        for i, map_name in enumerate(self.available_maps):
            grid_idx = i  # Reset to 0 base since Random Map isn't taking slot 0 anymore
            col = grid_idx % cols
            row = grid_idx // cols
            btn = Button(start_x + (col * 220), start_y + (row * 60), "medium", "blue", map_name, lambda idx=i: self.select_map(idx))
            if not self.procedural_world and i == self.map_index:
                btn.is_selected = True 
            self.elements.append(btn)

    def do_reset(self):
        self.reset_to_defaults()
        self.refresh_ui()
        
    def additional_draw(self, surface):
        title = fonts.get("heading1").render("RANDOM SCENARIO SETUP", True, (255, 255, 255))
        surface.blit(title, (c.SCREEN_WIDTH // 2 - title.get_width() // 2, 40))
        
        # Adjusted y-position slightly to sit clean right above the map table grid
        map_title = fonts.get("heading2").render("Select Base Map", True, (200, 200, 200))
        surface.blit(map_title, (c.SCREEN_WIDTH // 2 - map_title.get_width() // 2, 145))

    def start_game(self):
        if not self.procedural_world and not self.available_maps: return
        
        selected_path = "PROCEDURAL" if self.procedural_world else os.path.join(c.BASE_MAPS_DIR, self.available_maps[self.map_index])
        
        self.random_settings = {
            "map_path": selected_path,
            "countries": self.current_countries,
            "year": self.current_year,
            "island_filter_size": self.current_island_size,
            "procedural_type": self.procedural_types[self.proc_type_index],
            "single_tile_start": getattr(self, "single_tile_start", False),
            "resource_chance": getattr(self, "resource_chance", 0.15),
            "base_days_per_turn": getattr(self, "base_days_per_turn", 15)
        }
        self.next_state = "MAP"
        self.done = True

    def go_back(self):
        self.next_state = "NEW_GAME"
        self.done = True
        
    def handle_back_key(self):
        self.go_back()