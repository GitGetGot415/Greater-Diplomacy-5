import pygame
import os
import sys

# --- NEW: Tell Python 3.8+ to trust the current folder for DLLs ---
if os.name == 'nt':
    os.add_dll_directory(os.path.dirname(os.path.abspath(__file__)))

from soloud import Soloud, Wav, WavStream 
from screens.map_related_screens.messages import Messages_Screen
from map_logic.rendering.font_manager import fonts
import ui_elements
import data.constants as c
from screens.load_game import Load_Game
from screens.map import Map
from screens.menu import Menu
from screens.new_game import New_Game
from screens.settings import Settings
from screens.music_player import Music_Player
from screens.map_related_screens.orders import Orders_Screen
from data.io import keybind_io
from map_logic.rendering import symbol_loader
from screens.map_related_screens.research import Research_Screen
from screens.map_related_screens.economy import Economy_Screen
from screens.map_related_screens.edit_country import Edit_Country_Screen
from screens.map_related_screens.production import Production_Screen
from screens.select_base_map import Select_Base_Map
from screens.random_setup import Random_Setup

pygame.display.set_caption("Greater Diplomacy 5")

class Controller:
    def __init__(self):
        pygame.init() 
        pygame.key.set_repeat(c.KEY_REPEAT_DELAY, c.KEY_REPEAT_INTERVAL)
        
        # --- FPS CLOCK FIX ---
        self.clock = pygame.time.Clock()
        
        # --- INITIALIZE SOLOUD INSTEAD OF PYGAME.MIXER ---
        self.soloud = Soloud()
        self.soloud.init()
        
        # Keep track of active audio streams
        self.music_handle = None 
        self.music_stream = WavStream()
        
        # Share the engine with the UI module
        ui_elements.soloud_engine = self.soloud

        # Initialize fonts
        font_path = c.FONT_PATH_DEFAULT
        fonts.init_fonts(font_path)

        self.screen = pygame.display.set_mode((c.SCREEN_WIDTH, c.SCREEN_HEIGHT))
        
        # Load the sound into the ui_elements module using SoLoud Wav()
        try:
            ui_elements.click_sound = Wav()
            ui_elements.click_sound.load(c.SOUND_CLICK_PATH)
        except:
            print(f"Warning: {c.SOUND_CLICK_PATH} not found in assets folder")

        try:
            ui_elements.slider_sound = Wav()
            ui_elements.slider_sound.load(c.SOUND_SLIDER_PATH)
        except:
            print(f"Warning: {c.SOUND_SLIDER_PATH} not found in assets folder")

        self.screen = pygame.display.set_mode((c.SCREEN_WIDTH, c.SCREEN_HEIGHT))
        
        # 0. Load symbols
        try:
            icon = pygame.image.load('assets/icon/icon.png')
            pygame.display.set_icon(icon)
        except FileNotFoundError:
            print("Icon not found")

        symbol_loader.load_symbols()

        ui_elements.UI_ICONS = {
            "unit": symbol_loader.get_symbol("Infantry", 2),
            "industry": symbol_loader.get_symbol("Factory", 2),
            "star": symbol_loader.get_symbol("Star", 2),
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
            "eraser": symbol_loader.get_symbol("Eraser", 1.5),
            "red_line": symbol_loader.get_symbol("Red Line", 1.5),
            "color_picker": symbol_loader.get_symbol("Color Picker", 1.5),
            "export": symbol_loader.get_symbol("Export", 1.5),
            "import": symbol_loader.get_symbol("Import", 1.5),
            "circle": symbol_loader.get_symbol("Circle", 1.5),
            "triangle": symbol_loader.get_symbol("Triangle", 1.5),
            "line": symbol_loader.get_symbol("Line", 1.5),
            "paper": symbol_loader.get_symbol("Paper", 3),
            "economy(the_economy_of_a_country_to_be_unusually_specific)": symbol_loader.get_symbol("Money", 0.5)
        }

        # 1. Define Hardcoded Defaults
        default_keys = {
            "BACK": pygame.K_ESCAPE,
            "ORDERS": pygame.K_q
        }

        # 2. Load settings (Safely handle old saves that might not have pitch/speed)
        loaded_data = keybind_io.load_settings(default_keys, c.DEFAULT_SFX_VOLUME, c.DEFAULT_MUSIC_VOLUME)
        
        self.keybinds = loaded_data[0]
        self.sfx_volume = loaded_data[1]
        self.music_volume = loaded_data[2]
        self.num_players = loaded_data[3]
        self.ai_mode = loaded_data[4]
        self.gemini_api_key = loaded_data[5]
        self.chatgpt_api_key = loaded_data[6]
        self.claude_api_key = loaded_data[7]
        self.ollama_api_key = loaded_data[8]
        self.gemini_model = loaded_data[9]
        self.chatgpt_model = loaded_data[10]
        self.claude_model = loaded_data[11]
        self.ollama_model = loaded_data[12]
        self.ai_immersion_level = loaded_data[13]
        
        # New Audio Settings
        self.music_pitch = loaded_data[14] if len(loaded_data) > 14 else getattr(c, 'DEFAULT_AUDIO_PITCH', 0.5)
        self.sfx_pitch = loaded_data[15] if len(loaded_data) > 15 else getattr(c, 'DEFAULT_AUDIO_PITCH', 0.5)

        # 3. Apply volume to global sounds on boot
        ui_elements.global_sfx_volume = self.sfx_volume
        ui_elements.global_sfx_pitch = self.sfx_pitch

        self.all_albums = {}
        self.active_albums = []
        self.playlist = []
        self.now_playing = "None"
        
        self.load_music_data()
        self.play_random_song()

        self.states = {
            "MENU": Menu(),
            "NEW_GAME": New_Game(),
            "RANDOM_SETUP": Random_Setup(),
            "LOAD_GAME": Load_Game(),
            "SETTINGS": Settings(self), 
            "MUSIC_PLAYER": Music_Player(self),
            "SELECT_BASE_MAP": Select_Base_Map(),
            "MAP": None,
            "PRODUCTION": Production_Screen(),
            "ORDERS": Orders_Screen(),
            "RESEARCH": Research_Screen(),
            "ECONOMY": Economy_Screen(),
            "EDIT_COUNTRY": Edit_Country_Screen(),
            "MESSAGES": Messages_Screen()
        }
        self.active_state = self.states["MENU"]

    def flip_state(self):
        """Unified flip_state logic"""
        previous_state = self.active_state
        next_state_name = self.active_state.next_state
        
        # 1. Data Handoff
        if next_state_name in ["PRODUCTION", "ORDERS", "NAVY", "EDIT_COUNTRY"]:
            map_ref = self.states["MAP"]
            if next_state_name == "EDIT_COUNTRY":
                self.states["EDIT_COUNTRY"].start_editor(map_ref)
            elif map_ref.selected_province:
                self.states[next_state_name].start_with_province(map_ref.selected_province, map_ref)
        
        if next_state_name in ["RESEARCH", "ECONOMY", "MESSAGES"]:
            map_ref = self.states["MAP"]
            if next_state_name == "RESEARCH":
                self.states["RESEARCH"].start_research(map_ref)
            elif next_state_name == "ECONOMY":
                self.states["ECONOMY"].start_economy(map_ref)
            elif next_state_name == "MESSAGES":
                self.states["MESSAGES"].start_messages(map_ref)

        if next_state_name in ["SETTINGS", "MUSIC_PLAYER"]:
            if previous_state == self.states["MAP"]:
                self.states[next_state_name].return_state = "MAP"
            else:
                self.states[next_state_name].return_state = "MENU"

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
                    is_map_editor = (previous_state == self.states["SELECT_BASE_MAP"])
                    
                    self.states["MAP"] = Map(load_path=path, is_scenario=is_scen, force_editor=is_map_editor, num_players=self.num_players)
                    
            elif previous_state in [self.states["MENU"], self.states["NEW_GAME"]]:
                self.states["MAP"] = Map(num_players=self.num_players)

        # 3. Load Game Refresh
        if next_state_name == "LOAD_GAME":
            self.states["LOAD_GAME"].refresh_save_list()

        self.active_state.done = False
        self.active_state = self.states[next_state_name]

    def load_music_data(self):
        import os, json
        # Scan the hard drive to find whatever is actually there!
        synced_albums = {}
        if os.path.exists(c.MUSIC_DIR):
            for item in os.listdir(c.MUSIC_DIR):
                album_dir = os.path.join(c.MUSIC_DIR, item)
                if os.path.isdir(album_dir):
                    synced_albums[item] = []
                    for file in os.listdir(album_dir):
                        if file.lower().endswith(('.mp3', '.wav', '.ogg')):
                            track_path = os.path.join(album_dir, file).replace("\\", "/")
                            synced_albums[item].append(track_path)
                            
        self.all_albums = synced_albums
        
        # Load the user's active playlist toggles
        try:
            with open("data/json/active_albums.json", "r") as f:
                self.active_albums = json.load(f)
        except:
            self.active_albums = []
            
        # Clean up any active albums that were deleted from the disk
        self.active_albums = [a for a in self.active_albums if a in self.all_albums]
        self.build_playlist()

    def save_active_albums(self):
        import json
        with open("data/json/active_albums.json", "w") as f:
            json.dump(self.active_albums, f, indent=4)

    def build_playlist(self):
        self.playlist = []
        for album in self.active_albums:
            if album in self.all_albums:
                self.playlist.extend(self.all_albums[album])

    def play_random_song(self):
        if not self.playlist:
            self.now_playing = "None"
            if self.music_handle is not None:
                self.soloud.stop(self.music_handle)
            return
            
        import random
        track = random.choice(self.playlist)
        self.play_specific_song(track)

    def play_specific_song(self, track_path):
        try:
            if self.music_handle is not None:
                self.soloud.stop(self.music_handle)
                
            self.music_stream.load(track_path)
            self.music_handle = self.soloud.play(self.music_stream)
            
            # Apply volume and speed dynamically!
            self.soloud.set_volume(self.music_handle, self.music_volume)
            speed_mult = 0.5 + (self.music_pitch * 1.5) # Scale 0.0-1.0 to 0.5x-2.0x
            self.soloud.set_relative_play_speed(self.music_handle, speed_mult)
            
            self.now_playing = track_path
        except Exception as e:
            print(f"Error playing track {track_path}: {e}")

    def run(self):
        while True:
            # --- THE MAGIC CPU FIX ---
            self.clock.tick(60) 
            
            # --- SOLOUD SONG END CHECK ---
            if self.music_handle is not None:
                if not self.soloud.is_valid_voice_handle(self.music_handle):
                    self.play_random_song()
                    if self.active_state == self.states.get("MUSIC_PLAYER"):
                        self.states["MUSIC_PLAYER"].refresh_ui()

            events = pygame.event.get()
            for event in events:
                if event.type == pygame.QUIT:
                    # Clean up C++ engine safely before closing
                    self.soloud.deinit()
                    os._exit(0) # Instantly kills hanging background threads
                
                # GLOBAL KEYBOARD HANDLING
                if event.type == pygame.KEYDOWN:
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
    game = Controller()
    game.run()