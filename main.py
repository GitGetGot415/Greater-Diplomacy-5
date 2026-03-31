import pygame
from map_functions.rendering.font_manager import fonts # <-- Import the manager
import ui_elements
import gameState as g
from screens.load_game import Load_Game
from screens.map import Map
from screens.menu import Menu
from screens.new_game import New_Game
from screens.settings import Settings
from screens.map_related_screens.recruit import Recruit_Screen # Renamed from New_Game
from screens.map_related_screens.orders import Orders_Screen   # Renamed from New_Game
from map_functions.data import keybind_io
from map_functions.rendering import symbol_loader
from screens.map_related_screens.research import Research_Screen
from screens.map_related_screens.construction import Construction_Screen
from screens.map_related_screens.economy import Economy_Screen

pygame.display.set_caption("Greater Diplomacy Pygame Edition")

class Controller:
    def __init__(self):
        pygame.init() # Ensure pygame is init before accessing K_ constants
        pygame.mixer.init() # Initialize sound engine

        # Initialize fonts (Optionally pass a path here: fonts.init_fonts("assets/my_font.ttf"))
        fonts.init_fonts("assets/fonts/Anime_Inept.otf")

        self.screen = pygame.display.set_mode((g.SCREEN_WIDTH, g.SCREEN_HEIGHT))
        
        # Load the sound into the ui_elements module
        try:
            ui_elements.click_sound = pygame.mixer.Sound("assets/click.mp3")
        except:
            print("Warning: click.mp3 not found in assets folder")

        try:
            ui_elements.slider_sound = pygame.mixer.Sound("assets/slider.wav")
        except:
            print("Warning: slider.wav not found in assets folder")

        self.screen = pygame.display.set_mode((g.SCREEN_WIDTH, g.SCREEN_HEIGHT))
        
        # 0. Load symbols
        symbol_loader.load_symbols()

        # 1. Define Hardcoded Defaults
        default_keys = {
            "BACK": pygame.K_ESCAPE,
        }

        # 2. Load settings (Keybinds & Volume)
        self.keybinds, self.volume = keybind_io.load_settings(default_keys, 0.5)

        # 3. Apply volume to global sounds on boot
        if ui_elements.click_sound:
            ui_elements.click_sound.set_volume(self.volume)
        if ui_elements.slider_sound:
            ui_elements.slider_sound.set_volume(self.volume)

        self.states = {
            "MENU": Menu(),
            "NEW_GAME": New_Game(),
            "LOAD_GAME": Load_Game(),
            "SETTINGS": Settings(self), 
            "MAP": Map(),
            "RECRUIT": Recruit_Screen(),
            "ORDERS": Orders_Screen(),
            "RESEARCH": Research_Screen(),
            "ECONOMY": Economy_Screen()  # <--- Add this
        }
        self.states["CONSTRUCTION"] = Construction_Screen()
        self.active_state = self.states["MENU"]

    def flip_state(self):
        """Unified flip_state logic"""
        previous_state = self.active_state
        next_state_name = self.active_state.next_state
        
        # 1. Data Handoff
        if next_state_name in ["RECRUIT", "ORDERS", "NAVY", "CONSTRUCTION"]:
            map_ref = self.states["MAP"]
            if map_ref.selected_province:
                self.states[next_state_name].start_with_province(map_ref.selected_province, map_ref)
        
        # NEW: Separate handoff for Research since it doesn't care about provinces
        if next_state_name in ["RESEARCH", "ECONOMY"]:
            map_ref = self.states["MAP"]
            if next_state_name == "RESEARCH":
                self.states["RESEARCH"].start_research(map_ref)
            else:
                self.states["ECONOMY"].start_economy(map_ref)

        # 2. Map Persistence
        if next_state_name == "MAP":
            if hasattr(previous_state, 'selected_save_path'):
                path = previous_state.selected_save_path
                
                if path == "RANDOM":
                    # Pass a new flag called is_random
                    from screens.map import Map
                    self.states["MAP"] = Map(load_path=None, is_scenario=True, is_random=True)
                else:
                    is_scen = "scenarios" in path
                    from screens.map import Map
                    self.states["MAP"] = Map(load_path=path, is_scenario=is_scen)
            elif previous_state in [self.states["MENU"], self.states["NEW_GAME"]]:
                from screens.map import Map
                self.states["MAP"] = Map()

        # 3. Load Game Refresh
        if next_state_name == "LOAD_GAME":
            self.states["LOAD_GAME"].refresh_save_list()

        self.active_state.done = False
        self.active_state = self.states[next_state_name]

    def run(self):
        while True:
            events = pygame.event.get()
            for event in events:
                if event.type == pygame.QUIT:
                    return
                
                # GLOBAL KEYBOARD HANDLING
                if event.type == pygame.KEYDOWN:
                    # Check if the current state is busy "listening" for a key rebind
                    is_listening = getattr(self.active_state, "listening_for", None)
                    
                    if not is_listening:
                        if event.key == self.keybinds["BACK"]:
                            if hasattr(self.active_state, "handle_back_key"):
                                self.active_state.handle_back_key()

            self.active_state.handle_events(events)
            self.active_state.update()
            self.active_state.draw(self.screen)

            if self.active_state.done:
                self.flip_state()

            pygame.display.flip()

if __name__ == "__main__":
    pygame.init()
    game = Controller()
    game.run()