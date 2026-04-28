import pygame
from screens.map_related_screens.messages import Messages_Screen
from map_logic.rendering.font_manager import fonts
import ui_elements
import data.constants as c
from screens.load_game import Load_Game
from screens.map import Map
from screens.menu import Menu
from screens.new_game import New_Game
from screens.settings import Settings
from screens.map_related_screens.recruit import Recruit_Screen
from screens.map_related_screens.orders import Orders_Screen
from data.io import keybind_io
from map_logic.rendering import symbol_loader
from screens.map_related_screens.research import Research_Screen
from screens.map_related_screens.construction import Construction_Screen
from screens.map_related_screens.economy import Economy_Screen
from screens.map_related_screens.edit_country import Edit_Country_Screen
from screens.select_base_map import Select_Base_Map
from screens.random_setup import Random_Setup

pygame.display.set_caption("Greater Diplomacy Pygame Edition")

class Controller:
    def __init__(self):
        pygame.init() # Ensure pygame is init before accessing K_ constants
        pygame.key.set_repeat(400, 40) # 400ms delay, repeats every 40ms when typing
        pygame.mixer.init() # Initialize sound engine

        # Initialize fonts (Optionally pass a path here: fonts.init_fonts("assets/my_font.ttf"))
        font_path = c.FONT_PATH_DEFAULT
        # font_path = "assets/fonts/hemi head bd it.otf"
        fonts.init_fonts(font_path)

        self.screen = pygame.display.set_mode((c.SCREEN_WIDTH, c.SCREEN_HEIGHT))
        
        # Load the sound into the ui_elements module
        try:
            ui_elements.click_sound = pygame.mixer.Sound(c.SOUND_CLICK_PATH)
        except:
            print(f"Warning: {c.SOUND_CLICK_PATH} not found in assets folder")

        try:
            ui_elements.slider_sound = pygame.mixer.Sound(c.SOUND_SLIDER_PATH)
        except:
            print(f"Warning: {c.SOUND_SLIDER_PATH} not found in assets folder")

        self.screen = pygame.display.set_mode((c.SCREEN_WIDTH, c.SCREEN_HEIGHT))
        
        # 0. Load symbols
        symbol_loader.load_symbols()

        ui_elements.UI_ICONS = {
            "unit": symbol_loader.get_symbol("Infantry", 2),
            "industry": symbol_loader.get_symbol("Factory", 2),
            "blank": symbol_loader.get_symbol("Star", 2),
            "terrain": symbol_loader.get_symbol("Mountains", 1.5),
            "political": symbol_loader.get_symbol("Flag", 1.5),
            "relations": symbol_loader.get_symbol("Heart", 2),
            "research": symbol_loader.get_symbol("Research", 2),
            "mail": symbol_loader.get_symbol("Mail", 2),
            "save": symbol_loader.get_symbol("Save", 2),
            "core": symbol_loader.get_symbol("Star", 2),
            "resource": symbol_loader.get_symbol("Iron", 2),
            "faction": symbol_loader.get_symbol("Pawn", 2),
            "settings": symbol_loader.get_symbol("Gear", 1.5),
            "names": symbol_loader.get_symbol("Text", 0.5),
            "paint": symbol_loader.get_symbol("Paint", 1.5),
            "brush": symbol_loader.get_symbol("Brush", 1.5),
            "economy(the_economy_of_a_country_to_be_unusually_specific)": symbol_loader.get_symbol("Money", 0.5)
        }

        # 1. Define Hardcoded Defaults
        default_keys = {
            "BACK": pygame.K_ESCAPE,
            "ORDERS": pygame.K_q
        }

        # 2. Load settings (Keybinds, Volume, Players, AI Mode, API Key, & Immersion Level)
        self.keybinds, self.volume, self.num_players, self.ai_mode, self.api_key, self.ai_immersion_level = keybind_io.load_settings(default_keys, 0.5)

        # 3. Apply volume to global sounds on boot
        if ui_elements.click_sound:
            ui_elements.click_sound.set_volume(self.volume)
        if ui_elements.slider_sound:
            ui_elements.slider_sound.set_volume(self.volume)

        self.states = {
            "MENU": Menu(),
            "NEW_GAME": New_Game(),
            "RANDOM_SETUP": Random_Setup(),
            "LOAD_GAME": Load_Game(),
            "SETTINGS": Settings(self), 
            "SELECT_BASE_MAP": Select_Base_Map(),
            "MAP": Map(),
            "RECRUIT": Recruit_Screen(),
            "ORDERS": Orders_Screen(),
            "RESEARCH": Research_Screen(),
            "ECONOMY": Economy_Screen(),
            "EDIT_COUNTRY": Edit_Country_Screen(),
            "MESSAGES": Messages_Screen()
        }
        self.states["CONSTRUCTION"] = Construction_Screen()
        self.active_state = self.states["MENU"]

    def flip_state(self):
        """Unified flip_state logic"""
        previous_state = self.active_state
        next_state_name = self.active_state.next_state
        
        # 1. Data Handoff
        if next_state_name in ["RECRUIT", "ORDERS", "NAVY", "CONSTRUCTION", "EDIT_COUNTRY"]:
            map_ref = self.states["MAP"]
            if next_state_name == "EDIT_COUNTRY":
                self.states["EDIT_COUNTRY"].start_editor(map_ref)
            elif map_ref.selected_province:
                self.states[next_state_name].start_with_province(map_ref.selected_province, map_ref)
        
        # NEW: Separate handoff for Research since it doesn't care about provinces
        # Look for the block handling RESEARCH and ECONOMY and change it to this:
        if next_state_name in ["RESEARCH", "ECONOMY", "MESSAGES"]:
            map_ref = self.states["MAP"]
            if next_state_name == "RESEARCH":
                self.states["RESEARCH"].start_research(map_ref)
            elif next_state_name == "ECONOMY":
                self.states["ECONOMY"].start_economy(map_ref)
            elif next_state_name == "MESSAGES":
                self.states["MESSAGES"].start_messages(map_ref)

        # 2. Map Persistence
        if next_state_name == "MAP":
            if previous_state == self.states["RANDOM_SETUP"]:
                self.states["MAP"] = Map(is_scenario=True, is_random=True, random_settings=previous_state.random_settings, num_players=self.num_players)
            
            elif hasattr(previous_state, 'selected_save_path'):
                path = previous_state.selected_save_path
                
                if path == "RANDOM":
                    self.states["MAP"] = Map(load_path=None, is_scenario=True, is_random=True, num_players=self.num_players)
                else:
                    is_scen = "scenarios" in path
                    
                    # --- THE FIX ---
                    # Check if we just came from the Map Editor selection screen
                    is_map_editor = (previous_state == self.states["SELECT_BASE_MAP"])
                    
                    self.states["MAP"] = Map(load_path=path, is_scenario=is_scen, force_editor=is_map_editor, num_players=self.num_players)
                    
            elif previous_state in [self.states["MENU"], self.states["NEW_GAME"]]:
                self.states["MAP"] = Map(num_players=self.num_players)

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
                        if event.key == self.keybinds.get("BACK", pygame.K_ESCAPE):
                            if hasattr(self.active_state, "handle_back_key"):
                                self.active_state.handle_back_key()
                        elif event.key == self.keybinds.get("ORDERS", pygame.K_q):
                            if hasattr(self.active_state, "handle_orders_key"):
                                self.active_state.handle_orders_key()

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