import pygame
import os

# --- NEW: macOS Tkinter/Pygame NSApplication Clash Fix ---
import platform
import tkinter as tk
if platform.system() == "Darwin":
    # Initialize Tkinter FIRST so it claims the macOS NSApplication.
    # Pygame is polite enough to share, but Tkinter is not.
    _mac_tk_fix = tk.Tk()
    _mac_tk_fix.withdraw()

# --- NEW: Tell Python 3.8+ to trust the current folder for DLLs ---
if os.name == 'nt':
    os.add_dll_directory(os.path.dirname(os.path.abspath(__file__)))

from screens.map_related_screens.messages import Messages_Screen
from map_logic.rendering.font_manager import fonts
import ui_elements
import data.constants as c
from data import queries
from screens.load_game import Load_Game
from screens.map import Map
from screens.menu import Menu
from screens.new_game import New_Game
from screens.settings import Settings
from screens.credits import Credits
from screens.music_player import Music_Player
from screens.map_related_screens.orders import Orders_Screen
from data.io import keybind_io
from map_logic.rendering import symbol_loader
from screens.map_related_screens.research import Research_Screen
from screens.map_related_screens.economy import Economy_Screen
from screens.map_related_screens.edit_country import Edit_Country_Screen
from screens.map_related_screens.production import Production_Screen
from screens.map_related_screens.faction import Faction_Screen, Faction_Territories_Screen
from screens.select_base_map import Select_Base_Map
from screens.random_setup import Random_Setup
from screens.scenario_settings import Scenario_Settings

pygame.display.set_caption("Greater Diplomacy 5 Prototype")

class Controller:
    def __init__(self):
        pygame.init() 
        pygame.key.set_repeat(c.KEY_REPEAT_DELAY, c.KEY_REPEAT_INTERVAL)
        
        self.clock = pygame.time.Clock()
        self.fps_font = pygame.font.Font(None, 24)
        
        # --- OS COMPATIBILITY CHECK ---
        system = platform.system()
        arch = platform.machine().lower()
        
        # Determine if the current machine can safely run our provided binaries
        soloud_compatible = False
        if system == "Windows" and arch in ["x86_64", "amd64"]:
            soloud_compatible = True # Windows can use the x64 .dll
        elif system == "Darwin" and arch in ["x86_64", "amd64"]:
            soloud_compatible = True # Intel Macs can use the x64 .dylib
        elif system == "Linux" and arch in ["x86_64", "amd64"]:
            soloud_compatible = True # Linux usually uses the x64 .so
            
        # If the user requested SoLoud, but their hardware isn't compatible (like an M1 Mac),
        # gracefully override their setting and force Pygame Mixer.
        if c.USE_SOLOUD and not soloud_compatible:
            print(f"Notice: SoLoud is not compatible with {system} ({arch}). Auto-switching to Pygame Mixer.")
            c.USE_SOLOUD = False

        # --- HYBRID AUDIO ENGINE INITIALIZATION ---
        if c.USE_SOLOUD:
            try:
                from soloud import Soloud, Wav, WavStream 
                self.soloud = Soloud()
                self.soloud.init()
                self.music_handle = None 
                self.music_stream = WavStream()
                ui_elements.soloud_engine = self.soloud
                
                try:
                    ui_elements.click_sound = Wav()
                    ui_elements.click_sound.load(c.SOUND_CLICK_PATH)
                    ui_elements.slider_sound = Wav()
                    ui_elements.slider_sound.load(c.SOUND_SLIDER_PATH)
                except:
                    print("Warning: Sound files not found in assets folder")
                    
            except Exception as e:
                print(f"Failed to load SoLoud DLL: {e}. Auto-switching to Pygame Mixer.")
                c.USE_SOLOUD = False # Fallback triggered!

        # If SoLoud is disabled, or if it failed the try/except block above, boot Pygame.
        if not c.USE_SOLOUD:
            pygame.mixer.init()
            try:
                ui_elements.pygame_click_sound = pygame.mixer.Sound(c.SOUND_CLICK_PATH)
                ui_elements.pygame_slider_sound = pygame.mixer.Sound(c.SOUND_SLIDER_PATH)
            except:
                print("Warning: Sound files not found in assets folder")

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
            "research": symbol_loader.get_symbol("Research", 1.5),
            "mail": symbol_loader.get_symbol("Mail", 2),
            "save": symbol_loader.get_symbol("Save", 2),
            "core": symbol_loader.get_symbol("Star", 2),
            "resource": symbol_loader.get_symbol("Iron", 2),
            "faction": symbol_loader.get_symbol("Pawn", 2),
            "music": symbol_loader.get_symbol("Music", 1),
            "settings": symbol_loader.get_symbol("Gear", 1.0),
            "names": symbol_loader.get_symbol("Text", 0.5),
            "paint": symbol_loader.get_symbol("Paint", 1.5),
            "brush": symbol_loader.get_symbol("Brush", 1.5),
            "eraser": symbol_loader.get_symbol("Eraser", 1.5),
            "colors": symbol_loader.get_symbol("Colors", 2),
            "red_line": symbol_loader.get_symbol("Red Line", 1.5),
            "color_picker": symbol_loader.get_symbol("Color Picker", 1.5),
            "export": symbol_loader.get_symbol("Export", 1.5),
            "import": symbol_loader.get_symbol("Import", 1.5),
            "circle": symbol_loader.get_symbol("Circle", 1.5),
            "triangle": symbol_loader.get_symbol("Triangle", 1.5),
            "line": symbol_loader.get_symbol("Line", 1.5),
            "paper": symbol_loader.get_symbol("Paper", 3),
            "economy(the_economy_of_a_country_to_be_unusually_specific)": symbol_loader.get_symbol("Money", 0.5),
            "load_game": symbol_loader.get_symbol("Load Game", 1),
            "new_game": symbol_loader.get_symbol("New Game", 1),
            "map_editor": symbol_loader.get_symbol("Map Editor", 1),
            "credits": symbol_loader.get_symbol("Credits", 1)
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
        self.music_pitch = loaded_data[14] if len(loaded_data) > 14 else c.DEFAULT_AUDIO_PITCH
        self.sfx_pitch = loaded_data[15] if len(loaded_data) > 15 else c.DEFAULT_AUDIO_PITCH
        self.target_fps = loaded_data[16] if len(loaded_data) > 16 else c.TARGET_FPS
        self.ai_threads = loaded_data[17] if len(loaded_data) > 17 else c.DEFAULT_AI_THREADS
        self.show_fps = loaded_data[18] if len(loaded_data) > 18 else c.SHOW_FPS
        
        # --- FIXED MOUSE TOGGLE LOADING BLOCKS ---
        self.drag_mouse_button_toggle = loaded_data[19] if len(loaded_data) > 19 else c.DRAG_MOUSE_BUTTON_TOGGLE
        c.DRAG_MOUSE_BUTTON_TOGGLE = self.drag_mouse_button_toggle

        # 3. Apply volume to global sounds on boot
        ui_elements.global_sfx_volume = self.sfx_volume
        ui_elements.global_sfx_pitch = self.sfx_pitch

        self.all_albums = {}
        self.active_albums = []
        self.playlist = []
        self.now_playing = "None"
        self.track_start_times = {} # Keeps track of offsets specified in start_times.json
        
        self.load_music_data()
        self.play_random_song()

        self.states = {
            "MENU": Menu(),
            "NEW_GAME": New_Game(),
            "RANDOM_SETUP": Random_Setup(),
            "LOAD_GAME": Load_Game(),
            "SETTINGS": Settings(self), 
            "CREDITS": Credits(), 
            "MUSIC_PLAYER": Music_Player(self),
            "SELECT_BASE_MAP": Select_Base_Map(),
            "MAP": None,
            "PRODUCTION": Production_Screen(),
            "ORDERS": Orders_Screen(),
            "RESEARCH": Research_Screen(),
            "ECONOMY": Economy_Screen(),
            "EDIT_COUNTRY": Edit_Country_Screen(),
            "MESSAGES": Messages_Screen(),
            "FACTION": Faction_Screen(),
            "FACTION_TERRITORIES": Faction_Territories_Screen(),
            "SCENARIO_SETTINGS": Scenario_Settings()
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
        
        if next_state_name in ["RESEARCH", "ECONOMY", "MESSAGES", "FACTION", "FACTION_TERRITORIES"]:
            map_ref = self.states["MAP"]
            if next_state_name == "RESEARCH":
                self.states["RESEARCH"].start_research(map_ref)
            elif next_state_name == "ECONOMY":
                self.states["ECONOMY"].start_economy(map_ref)
            elif next_state_name == "MESSAGES":
                self.states["MESSAGES"].start_messages(map_ref)
            elif next_state_name == "FACTION":
                self.states["FACTION"].start_faction(map_ref)
            elif next_state_name == "FACTION_TERRITORIES":
                self.states["FACTION_TERRITORIES"].start_view(map_ref)

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
                    
                    history_turn = getattr(previous_state, 'selected_history_turn', None)
                    
                    self.states["MAP"] = Map(load_path=path, is_scenario=is_scen, force_editor=is_map_editor, num_players=self.num_players, history_turn=history_turn)
                    
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
        self.track_start_times = {} # Clear start times whenever we scan
        
        if os.path.exists(c.MUSIC_DIR):
            for item in os.listdir(c.MUSIC_DIR):
                album_dir = os.path.join(c.MUSIC_DIR, item)
                if os.path.isdir(album_dir):
                    synced_albums[item] = []
                    
                    # --- NEW: Check for start_times.json ---
                    album_start_times = {}
                    start_times_path = os.path.join(album_dir, "start_times.json")
                    if os.path.exists(start_times_path):
                        try:
                            with open(start_times_path, "r") as f:
                                album_start_times = json.load(f)
                        except Exception as e:
                            print(f"Error loading start_times.json for {item}: {e}")
                    
                    for file in os.listdir(album_dir):
                        if file.lower().endswith(('.mp3', '.wav', '.ogg')):
                            track_path = os.path.join(album_dir, file).replace("\\", "/")
                            synced_albums[item].append(track_path)
                            
                            # --- NEW: Map the start time if defined ---
                            file_stem = os.path.splitext(file)[0]
                            if file in album_start_times:
                                self.track_start_times[track_path] = float(album_start_times[file])
                            elif file_stem in album_start_times:
                                self.track_start_times[track_path] = float(album_start_times[file_stem])
                            
        self.all_albums = synced_albums
        
        # Load the user's active playlist toggles
        from data import queries
        # Returns {} by default if empty, so ensure it's a list
        loaded_albums = queries.get_active_albums()
        self.active_albums = loaded_albums if isinstance(loaded_albums, list) else []
            
        # Clean up any active albums that were deleted from the disk
        self.active_albums = [a for a in self.active_albums if a in self.all_albums]
        self.build_playlist()

    def save_active_albums(self):
        from data import queries
        queries.save_cached_json("active_albums", self.active_albums)

    def build_playlist(self):
        self.playlist = []
        for album in self.active_albums:
            if album in self.all_albums:
                self.playlist.extend(self.all_albums[album])

    def play_random_song(self):
        if not self.playlist:
            self.now_playing = "None"
            if c.USE_SOLOUD and hasattr(self, 'music_handle') and self.music_handle is not None:
                self.soloud.stop(self.music_handle)
            elif not c.USE_SOLOUD:
                pygame.mixer.music.stop()
            return
            
        import random
        
        # Check if we have more than one song and if the current song is in the playlist
        if len(self.playlist) > 1 and self.now_playing in self.playlist:
            # Create a temporary list of all songs EXCEPT the one that just played
            available_tracks = [track for track in self.playlist if track != self.now_playing]
            track = random.choice(available_tracks)
        else:
            # Fallback for playlists with only 1 song, or if nothing is playing yet
            track = random.choice(self.playlist)
            
        self.play_specific_song(track)

    def play_specific_song(self, track_path):
        try:
            # Fetch the defined start time, default to 0.0 if not listed
            start_time = self.track_start_times.get(track_path, 0.0)
            
            if c.USE_SOLOUD:
                if hasattr(self, 'music_handle') and self.music_handle is not None:
                    self.soloud.stop(self.music_handle)
                    
                self.music_stream.load(track_path)
                self.music_handle = self.soloud.play(self.music_stream)
                
                # Apply SoLoud Seek
                if start_time > 0:
                    self.soloud.seek(self.music_handle, start_time)
                
                self.soloud.set_volume(self.music_handle, self.music_volume)
                # Mathematical tweak to center speed variance directly on 0.5 input
                speed_mult = 0.5 + self.music_pitch 
                self.soloud.set_relative_play_speed(self.music_handle, speed_mult)
            else:
                pygame.mixer.music.load(track_path)
                # Apply Pygame Mixer Seek
                pygame.mixer.music.play(start=start_time)
                pygame.mixer.music.set_volume(self.music_volume)
                
            self.now_playing = track_path
        except Exception as e:
            print(f"Error playing track {track_path}: {e}")

    def run(self):
        while True:
            # --- THE MAGIC CPU FIX ---
            self.clock.tick(self.target_fps) 
            
            # --- HYBRID SONG END CHECK ---
            if c.USE_SOLOUD:
                # FIX: Check self.now_playing != "None" to prevent infinite loops when playlist is empty
                if hasattr(self, 'music_handle') and self.music_handle is not None and self.now_playing != "None":
                    if not self.soloud.is_valid_voice_handle(self.music_handle):
                        self.play_random_song()
                        if self.active_state == self.states.get("MUSIC_PLAYER"):
                            self.states["MUSIC_PLAYER"].refresh_ui()
            else:
                if self.now_playing != "None" and not pygame.mixer.music.get_busy():
                    self.play_random_song()
                    if self.active_state == self.states.get("MUSIC_PLAYER"):
                        self.states["MUSIC_PLAYER"].refresh_ui()

            events = pygame.event.get()
            for event in events:
                if event.type == pygame.QUIT:
                    # Clean up safely before closing
                    if c.USE_SOLOUD and hasattr(self, 'soloud'):
                        self.soloud.deinit()
                    elif not c.USE_SOLOUD:
                        pygame.mixer.quit()
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

            if self.show_fps:
                fps_surface = self.fps_font.render(f"FPS: {int(self.clock.get_fps())}", True, (255, 255, 255))
                self.screen.blit(fps_surface, (c.SCREEN_WIDTH - 75, 10))

            if self.active_state.done:
                self.flip_state()
                
            pygame.display.flip()

if __name__ == "__main__":
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    
    # Mod Handler
    for filename in os.listdir(os.getcwd()):
        if filename.endswith(".GD5MOD"):
            with open(os.path.join(BASE_DIR, filename), "r") as mod:
                lines = mod.readlines()
                target = os.path.join(BASE_DIR, lines[0].strip())
                content = "".join(lines[1:])

                with open(target, "w") as target_file: # Cut off the last character from the file name (\n)
                    target_file.write(content) # We only want everything after the first line (filename)

    game = Controller()
    game.run()