import pygame
import gameState as g
from screens.load_game import Load_Game
from screens.map import Map
from screens.menu import Menu
from screens.new_game import New_Game
from screens.settings import Settings
from screens.map_related_screens.recruit import Recruit_Screen # Renamed from New_Game
from screens.map_related_screens.orders import Orders_Screen   # Renamed from New_Game
from screens.map_related_screens.navy_recruit import Navy_Recruit_Screen
from map_functions.data import keybind_io

pygame.display.set_caption("Greater Diplomacy Pygame Edition")

class Controller:
    def __init__(self):
        pygame.init() # Ensure pygame is init before accessing K_ constants
        self.screen = pygame.display.set_mode((g.SCREEN_WIDTH, g.SCREEN_HEIGHT))
        
        # 1. Define Hardcoded Defaults
        default_keys = {
            "BACK": pygame.K_ESCAPE,
        }

        # 2. Try to load from file, otherwise use defaults
        self.keybinds = keybind_io.load_keybinds(default_keys)

        self.states = {
            "MENU": Menu(),
            "NEW_GAME": New_Game(),
            "LOAD_GAME": Load_Game(),
            "SETTINGS": Settings(self), # Pass 'self' (the controller) here
            "MAP": Map(),
            "RECRUIT": Recruit_Screen(),
            "ORDERS": Orders_Screen(),
            "NAVY": Navy_Recruit_Screen()
        }
        self.active_state = self.states["MENU"]

    def flip_state(self):
        """Unified flip_state logic"""
        previous_state = self.active_state
        next_state_name = self.active_state.next_state
        
        # 1. Data Handoff
        if next_state_name in ["RECRUIT", "ORDERS", "NAVY"]:
            map_ref = self.states["MAP"]
            if map_ref.selected_province:
                self.states[next_state_name].start_with_province(map_ref.selected_province, map_ref)

        # 2. Map Persistence
        if next_state_name == "MAP":
            if hasattr(previous_state, 'selected_save_path'):
                path = previous_state.selected_save_path
                # Check if the path contains 'scenarios' to set the flag
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