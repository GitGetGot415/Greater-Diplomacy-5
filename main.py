# /// script
# dependencies = [
#   "numpy",
# ]
# ///
# The block above is PEP 723 metadata read by pygbag: it pre-fetches numpy's
# WASM wheel before running this script. Without it, pygbag only discovers the
# missing import mid-execution and retries via a path it marks buggy for
# non-interactive scripts (main.py), which hangs instead of resuming. Harmless
# comment for desktop Python.

import asyncio
import os
import sys

# Only the module object, not install() -- see _import_project_modules()
# below for why that call had to move.
import mod_loader


def _import_project_modules():
    """Calls mod_loader.install() and imports every other project module --
    deferred from plain top-level code (where all of this used to live) into
    a function called from _bootstrap(), after that function has awaited
    mod_loader.restore_mods_dir_from_indexeddb().

    On web, mod_loader.install() has to run after mods/ has actually been
    pulled back out of IndexedDB into pygbag's in-memory filesystem, or it
    permanently mistakes "player has no mods" for "player's mod hasn't been
    restored into the virtual filesystem yet" -- and that pull is
    unavoidably asynchronous (no synchronous browser API for IndexedDB
    exists). But nothing async can actually complete during a script's own
    top-level synchronous execution: control has to return to the browser's
    event loop at least once first (single-threaded JS, same as any other
    browser context) -- see restore_mods_dir_from_indexeddb()'s docstring for
    how this was confirmed. So install(), and every project module below (it
    has to run before them too, per install()'s own docstring, or none of
    them could ever be patched), waits for _bootstrap() to actually be
    running as a task the browser's own frame loop is driving, past its
    first real `await`.

    Moving these here doesn't change what any of them do: Controller's
    methods only look these names up in this module's globals when they're
    actually called, well after this function has already run -- Python
    resolves free variables in a function/method body at call time, not when
    the enclosing class statement first executes.
    """
    global IS_WEB, restore_persisted_dir, platform, pygame
    global Messages_Screen, dispatch_global_keys, fonts, ui_elements, c, queries
    global Load_Game, Map, Menu, New_Game, Settings, Credits, Music_Player, View_Assets, Mods, Unit_Art, Keybinds
    global Translate
    global Orders_Screen, keybind_io, settings_schema, symbol_loader, modal_stack
    global Research_Screen, Economy_Screen, Edit_Country_Screen, Production_Screen
    global Faction_Screen, Faction_Territories_Screen
    global Select_Base_Map, Random_Setup, Scenario_Settings
    global Multiplayer_Hub, Multiplayer_Host, Multiplayer_Join, Multiplayer_New

    # Must run before any other project module is imported below -- see
    # mod_loader's own docstring for why. Applies enabled .py mods in memory
    # only; nothing on disk is touched.
    mod_loader.install()

    from data.platform import IS_WEB, restore_persisted_dir

    # py2app / PyInstaller bundle fix: set working directory.
    #
    # mod_loader.BASE_DIR is already the answer -- it is the game folder for
    # every build shape, worked out once with the packaging caveats spelled out
    # in its docstring. This used to restate the same frozen/PyInstaller/py2app
    # branch with a py2app arm written a different way (dirname(__file__)),
    # which happens to land in the same place only because py2app leaves this
    # script loose in Contents/Resources rather than zipping it.
    if getattr(sys, 'frozen', False):
        os.chdir(mod_loader.BASE_DIR)

    import platform
    import pygame

    # The macOS Tkinter/NSApplication claim that used to happen here is gone: no
    # screen the game opens is a Tk window any more, so pygame owns the app outright.

    # Tell Python 3.8+ to trust the current folder for DLLs
    if os.name == 'nt':
        os.add_dll_directory(os.path.dirname(os.path.abspath(__file__)))

    from screens.map_related_screens.messages import Messages_Screen
    from gameState import dispatch_global_keys
    from map_logic.rendering.font_manager import fonts
    import ui_elements
    import data.constants as c
    from data import queries
    from screens.menu_screens.load_game import Load_Game
    from screens.menu_screens.map import Map
    from screens.menu_screens.menu import Menu
    from screens.menu_screens.new_game import New_Game
    from screens.menu_screens.settings import Settings
    from screens.menu_screens.credits import Credits
    from screens.menu_screens.translate import Translate
    from screens.menu_screens.music_player import Music_Player
    from screens.menu_screens.view_assets import View_Assets
    from screens.menu_screens.mods import Mods
    from screens.menu_screens.unit_art import Unit_Art
    from screens.menu_screens.keybinds import Keybinds
    from screens.map_related_screens.orders import Orders_Screen
    from data.io import keybind_io, settings_schema
    from map_logic.rendering import symbol_loader
    from ui import modal_stack
    from screens.map_related_screens.research import Research_Screen
    from screens.map_related_screens.economy import Economy_Screen
    from screens.map_related_screens.edit_country import Edit_Country_Screen
    from screens.map_related_screens.production import Production_Screen
    from screens.map_related_screens.faction import Faction_Screen, Faction_Territories_Screen
    from screens.menu_screens.select_base_map import Select_Base_Map
    from screens.menu_screens.random_setup import Random_Setup
    from screens.menu_screens.scenario_settings import Scenario_Settings
    from screens.menu_screens.multiplayer_hub import Multiplayer_Hub
    from screens.menu_screens.multiplayer_host import Multiplayer_Host
    from screens.menu_screens.multiplayer_join import Multiplayer_Join
    from screens.menu_screens.multiplayer_new import Multiplayer_New

    pygame.display.set_caption("Greater Diplomacy 5")


class Controller:
    def __init__(self):
        pygame.init()
        if IS_WEB:
            # pygame.init() auto-inits the mixer subsystem as one of its defaults,
            # which creates the browser AudioContext immediately -- before any
            # click ever happens. Undo that here so init_web_audio() (called from
            # the first real user gesture in run()) is the actual first mixer init.
            pygame.mixer.quit()
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
        # On web, defer this entirely to the first real user gesture (see run()) --
        # calling pygame.mixer.init() at boot creates the browser AudioContext before
        # any click, and it never resumes even after later clicks.
        if not c.USE_SOLOUD and not IS_WEB:
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
            "blank": symbol_loader.get_symbol("Nothing", 1),
            "terrain": symbol_loader.get_symbol("Mountains", 1.5),
            "political": symbol_loader.get_symbol("Flag", 1.5),
            "relations": symbol_loader.get_symbol("Heart", 2),
            "research": symbol_loader.get_symbol("Research", 1.5),
            "mail": symbol_loader.get_symbol("Mail", 2),
            "save": symbol_loader.get_symbol("Save", 2),
            "core": symbol_loader.get_symbol("Star", 2),
            "resource": symbol_loader.get_symbol("Iron", 2),
            "faction": symbol_loader.get_symbol("Faction", 2),
            "puppet": symbol_loader.get_symbol("Pawn", 2),
            "music": symbol_loader.get_symbol("Music", 1),
            "settings": symbol_loader.get_symbol("Gear", 1.0),
            "tophat": symbol_loader.get_symbol("Tophat", 1.0),
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
            "battle": symbol_loader.get_symbol("Attack", 2),
            "economy(the_economy_of_a_country_to_be_unusually_specific)": symbol_loader.get_symbol("Money", 0.5),
            "load_game": symbol_loader.get_symbol("Load Game", 1),
            "new_game": symbol_loader.get_symbol("New Game", 1),
            "map_editor": symbol_loader.get_symbol("Map Editor", 1),
            "credits": symbol_loader.get_symbol("Credits", 1),
            "clock": symbol_loader.get_symbol("Clock", 1.6),
            "mods": symbol_loader.get_symbol("Hammer", 1.5),
        }

        # 1. Define Hardcoded Defaults
        default_keys = {
            "BACK": pygame.K_ESCAPE,
            "ORDERS": pygame.K_q,
            "FULLSCREEN": pygame.K_F11,
            "ECONOMY": pygame.K_w,
            "CLEAR_ORDERS": pygame.K_DELETE,
        }

        # 2. Load settings (Safely handle old saves that might not have pitch/speed)
        loaded_data = keybind_io.load_settings(default_keys, c.DEFAULT_SFX_VOLUME, c.DEFAULT_MUSIC_VOLUME)
        
        # The positional tuple, its per-setting defaults and the chain of
        # `len(loaded_data) > N` guards that used to be written out here all
        # live in data/io/settings_schema.py now -- a tuple saved by an older
        # build simply stops early and the rest fall back.
        self.keybinds = loaded_data[0]
        settings = settings_schema.from_tuple(loaded_data)
        settings_schema.apply_to_controller(self, settings)
        c.apply_runtime_settings(settings)

        # 3. Apply volume to global sounds on boot
        ui_elements.global_sfx_volume = self.sfx_volume
        ui_elements.global_sfx_pitch = self.sfx_pitch

        self.all_albums = {}
        self.active_albums = []
        self.playlist = []
        self.now_playing = "None"
        self.starting_song = None
        self.track_start_times = {} # Keeps track of offsets specified in start_times.json

        self.load_music_data()
        # Browsers block audio until it starts from within a genuine user gesture
        # (per pygbag's own guidance: "remove startup sounds and/or wait for a
        # mouse click"). Playing immediately at boot means the browser silently
        # ignores it and the AudioContext never resumes. Deferred to the first
        # real input event in run() on web; unaffected on desktop.
        self._web_audio_unlocked = False
        if not IS_WEB:
            self.play_startup_song()

        # Say where this game is, for anything that wants to translate a map
        # into it. Best effort and never fatal -- see map_logic/odtl.py.
        try:
            from map_logic import odtl
            odtl.write_locator()
        except Exception:
            pass

        self.states = {
            "MENU": Menu(),
            "NEW_GAME": New_Game(),
            "RANDOM_SETUP": Random_Setup(),
            "LOAD_GAME": Load_Game(),
            "SETTINGS": Settings(self),
            "UNIT_ART": Unit_Art(self),
            "KEYBINDS": Keybinds(self),
            "CREDITS": Credits(),
            "MUSIC_PLAYER": Music_Player(self),
            "VIEW_ASSETS": View_Assets(),
            "MODS": Mods(),
            "TRANSLATE": Translate(),
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
            "SCENARIO_SETTINGS": Scenario_Settings(),
            "MULTIPLAYER_HUB": Multiplayer_Hub(),
            "MULTIPLAYER_HOST": Multiplayer_Host(),
            "MULTIPLAYER_JOIN": Multiplayer_Join(),
            "MULTIPLAYER_NEW": Multiplayer_New(),
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
                self.states[next_state_name].back_state = "MAP"
            # Returning from a Settings sub-screen (e.g. Unit Art, Keybinds)
            # isn't a fresh entry into Settings -- it must not overwrite the
            # MAP/MENU back_state Settings already picked up when it was
            # first opened, or Back from the sub-screen would dump the
            # player at the menu even when they opened Settings from a live game.
            elif previous_state not in (self.states.get("UNIT_ART"), self.states.get("KEYBINDS")):
                self.states[next_state_name].back_state = "MENU"

        # 2. Map Persistence
        if next_state_name == "MAP":
            if previous_state == self.states["RANDOM_SETUP"]:
                self.states["MAP"] = Map(is_scenario=True, is_random=True, random_settings=previous_state.random_settings, num_players=self.num_players)
            
            elif hasattr(previous_state, 'selected_tournament_path'):
                path = previous_state.selected_tournament_path
                key = previous_state.selected_tournament_key
                
                from data.io import multiplayer_io
                res = multiplayer_io.load_tournament(path, key)
                if len(res) >= 8:
                    success, role, cid, temp_dir, keys_dict, msg, session_key, ver_table = res[:8]
                else:
                    success, role, cid, temp_dir, keys_dict, msg = res[:6]
                    session_key, ver_table = None, {}

                if success:
                    self.states["MAP"] = Map(load_path=temp_dir, is_scenario=False, force_editor=False, num_players=self.num_players)
                    self.states["MAP"].loaded_tournament_path = path
                    self.states["MAP"].multiplayer_tournament_dir = os.path.dirname(path)
                    self.states["MAP"].multiplayer_session_key = session_key
                    
                    player_enc_cache = {}
                    if ver_table:
                        for h, v_entry in ver_table.items():
                            if v_entry.get("role") == "PLAYER":
                                r_cid = v_entry.get("country_id")
                                if r_cid and r_cid in keys_dict:
                                    player_enc_cache[r_cid] = (keys_dict[r_cid], h, v_entry["enc_session"])
                    self.states["MAP"].multiplayer_player_enc_cache = player_enc_cache

                    if role == "HOST":
                        self.states["MAP"].multiplayer_host_mode = True
                        self.states["MAP"].player_country = "Spectator"
                        self.states["MAP"].multiplayer_master_key = key
                        self.states["MAP"].multiplayer_keys_dict = keys_dict
                    elif role == "PLAYER":
                        self.states["MAP"].multiplayer_player_key = key
                        multiplayer_io.strip_sensitive_data_for_player(self.states["MAP"], cid)
                        
                    import shutil
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    
                    self.states["MAP"].refresh_all_maps()
                    from screens.menu_screens.map import render_buttons
                    render_buttons(self.states["MAP"])
                else:
                    print(f"Failed to load tournament: {msg}")

                    # Show popup to user
                    from ui import confirm_dialog
                    confirm_dialog.show_error("Load Failed", msg)

                    # Abort transition
                    self.active_state.done = False
                    self.active_state.next_state = "MULTIPLAYER_HUB"
                    return
            
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
            self.states["LOAD_GAME"].refresh_ui()

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
                    
                    # Check for start_times.json
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
                            
                            # Map the start time if defined
                            file_stem = os.path.splitext(file)[0]
                            if file in album_start_times:
                                self.track_start_times[track_path] = float(album_start_times[file])
                            elif file_stem in album_start_times:
                                self.track_start_times[track_path] = float(album_start_times[file_stem])
                            
        self.all_albums = synced_albums
        
        # Load the user's active playlist toggles.
        # Returns {} by default if empty, so ensure it's a list
        loaded_albums = queries.get_active_albums()
        self.active_albums = loaded_albums if isinstance(loaded_albums, list) else []
            
        # Clean up any active albums that were deleted from the disk
        self.active_albums = [a for a in self.active_albums if a in self.all_albums]
        self.build_playlist()

        # Load the pinned boot-up track, if any, and drop it if its file has
        # since been deleted or renamed. Independent of active_albums, since
        # it's meant to play at boot regardless of which albums are toggled on.
        self.starting_song = queries.get_starting_song()
        all_tracks = {track for tracks in self.all_albums.values() for track in tracks}
        if self.starting_song not in all_tracks:
            self.starting_song = None

    def save_active_albums(self):
        queries.save_cached_json("active_albums", self.active_albums)

    def save_starting_song(self):
        queries.save_cached_json("starting_song", {"track": self.starting_song})

    def play_startup_song(self):
        """Plays the pinned starting song if one is set, else falls back to random."""
        if self.starting_song:
            self.play_specific_song(self.starting_song)
        else:
            self.play_random_song()

    def init_web_audio(self):
        """Deferred pygame.mixer bootstrap for web -- see the IS_WEB guard in __init__."""
        pygame.mixer.init()
        try:
            ui_elements.pygame_click_sound = pygame.mixer.Sound(c.SOUND_CLICK_PATH)
            ui_elements.pygame_slider_sound = pygame.mixer.Sound(c.SOUND_SLIDER_PATH)
        except:
            print("Warning: Sound files not found in assets folder")

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

    def _load_soloud_stream_unicode_safe(self, track_path):
        # WavStream.load() passes the path through fopen() via the C runtime,
        # which reads it in the OS ANSI codepage instead of UTF-8 on Windows --
        # non-ASCII filenames/titles (e.g. Japanese) silently fail to open.
        # Reading the bytes with Python (Unicode-path-safe) and streaming them
        # in via load_mem() avoids that codepage round-trip.
        import ctypes
        with open(track_path, 'rb') as f:
            data = f.read()
        buf = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
        self.music_stream.load_mem(buf, len(data), aCopy=True, aTakeOwnership=False)

    def play_specific_song(self, track_path):
        try:
            # Fetch the defined start time, default to 0.0 if not listed
            start_time = self.track_start_times.get(track_path, 0.0)

            if c.USE_SOLOUD:
                if hasattr(self, 'music_handle') and self.music_handle is not None:
                    self.soloud.stop(self.music_handle)

                self._load_soloud_stream_unicode_safe(track_path)
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

    def toggle_fullscreen(self):
        current_time = pygame.time.get_ticks()
        # Debounce: prevent toggling if less than 500ms has elapsed since the last toggle finished
        if hasattr(self, 'last_toggle_time') and current_time - self.last_toggle_time < 500:
            return
            
        self.is_fullscreen = not getattr(self, 'is_fullscreen', False)
        if self.is_fullscreen:
            try:
                self.screen = pygame.display.set_mode((c.SCREEN_WIDTH, c.SCREEN_HEIGHT), pygame.FULLSCREEN)
            except pygame.error:
                info = pygame.display.Info()
                self.screen = pygame.display.set_mode((info.current_w, info.current_h), pygame.NOFRAME)
        else:
            self.screen = pygame.display.set_mode((c.SCREEN_WIDTH, c.SCREEN_HEIGHT))
            
        # Update toggle time AFTER transition, so cooldown starts when screen is ready
        self.last_toggle_time = pygame.time.get_ticks()
        # Clear any accumulated KEYDOWN events (like F11 being held) that queued up while display was resetting
        pygame.event.clear(pygame.KEYDOWN)

    async def run(self):
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

            if IS_WEB and not self._web_audio_unlocked:
                for event in events:
                    if event.type in (pygame.MOUSEBUTTONDOWN, pygame.KEYDOWN):
                        self._web_audio_unlocked = True
                        self.init_web_audio()
                        self.play_startup_song()
                        break

            for event in events:
                if event.type == pygame.QUIT:
                    # Clean up safely before closing
                    if c.USE_SOLOUD and hasattr(self, 'soloud'):
                        self.soloud.deinit()
                    elif not c.USE_SOLOUD:
                        pygame.mixer.quit()
                    if IS_WEB:
                        # os._exit() isn't meaningful in a browser tab; just stop the loop.
                        return
                    os._exit(0) # Instantly kills hanging background threads

            # MODAL STACK: dialogs/prompts/sub-screens (ui/modal_stack.py) take over
            # events/update/draw from active_state while any are open, instead of
            # running their own nested blocking loop (see modal_stack.py's docstring
            # for why -- a nested loop never yields back to asyncio.sleep(0) below).
            top_modal = modal_stack.active()

            # FULLSCREEN toggles the display itself, not an action routed to
            # whichever screen currently owns events, so unlike
            # BACK/ORDERS/ECONOMY/CLEAR_ORDERS
            # below it has to work even while a modal (dialog, sub-screen) is on
            # top -- gated on *that* screen's listening_for, same as modal_stack.push
            # resolves the real screen out of a _ScreenModal wrapper.
            listening_screen = self.active_state if top_modal is None else getattr(top_modal, "screen", top_modal)
            for event in events:
                if (event.type == pygame.KEYDOWN and not getattr(listening_screen, "listening_for", None)
                        and event.key == self.keybinds.get("FULLSCREEN", pygame.K_F11)):
                    self.toggle_fullscreen()

            if top_modal is None:
                # GLOBAL KEYBOARD HANDLING
                for event in events:
                    if event.type == pygame.KEYDOWN and not getattr(self.active_state, "listening_for", None):
                        dispatch_global_keys(self.active_state, event)

                self.active_state.handle_events(events)
            else:
                top_modal.handle_events(events)

            # Re-check: handle_events above may have just pushed or popped a modal
            # (e.g. a button click opened a confirm dialog). Whatever is on top now
            # is what gets updated/drawn this frame, matching how the old blocking
            # dialogs took over instantly, within the same call, with no extra frame
            # of the screen underneath rendering first.
            top_modal = modal_stack.active()

            # Same idea for an ordinary state switch: a button clicked just above
            # (change_state/exit_screen/go_to) may have already marked active_state
            # done. Flip now, in the same frame, so the screen being left never
            # draws once more with post-click state (a newly selected province, a
            # changed view mode) before the screen it is switching to appears.
            if top_modal is None and self.active_state.done:
                self.flip_state()
                top_modal = modal_stack.active()

            if top_modal is not None:
                top_modal.update()
                top_modal.draw(self.screen)
            else:
                self.active_state.update()
                self.active_state.draw(self.screen)

                if self.active_state.done:
                    self.flip_state()

            if self.show_fps:
                fps_surface = self.fps_font.render(f"FPS: {int(self.clock.get_fps())}", True, (255, 255, 255))
                self.screen.blit(fps_surface, (c.SCREEN_WIDTH - 75, 10))

            pygame.display.flip()
            await asyncio.sleep(0)  # yield to the browser tab / event loop every frame

async def _bootstrap():
    # Web only: pull mods/ back out of IndexedDB before mod_loader.install()
    # (called from _import_project_modules() below) decides what to patch --
    # this has to be a real `await`, inside a coroutine _bootstrap() is
    # actually driving, not a second asyncio.run() call from synchronous code
    # (which silently never completes on web). See
    # mod_loader.restore_mods_dir_from_indexeddb()'s docstring.
    if sys.platform == "emscripten":
        await mod_loader.restore_mods_dir_from_indexeddb()

    _import_project_modules()

    # Web only: pull saves back out of IndexedDB before anything reads them
    # (Load_Game's directory listing, a save overwrite check, ...) -- pygbag's
    # in-memory FS otherwise starts every tab empty. See data/platform.py.
    if IS_WEB:
        await restore_persisted_dir(c.SAVES_DIR)
        await restore_persisted_dir(c.TOURNAMENT_SAVES_DIR)
        from ui.character_select_screen import CHARACTERS_DIR, CUSTOM_SUBDIR
        await restore_persisted_dir(os.path.join(CHARACTERS_DIR, CUSTOM_SUBDIR))
    game = Controller()
    await game.run()

def _write_crash_log():
    """Writes a crash report to ~/GD5_crash.log and pops up a dialog telling
    the player where it is, so they can find and send it without needing a
    console window -- a windowed/frozen build doesn't show one, so without
    this a crash would otherwise just silently vanish from their view.

    Deliberately self-contained (own imports, no reliance on project
    modules) since this runs from the top-level except block, which can be
    reached before _import_project_modules() has set anything up -- e.g. if
    mod_loader.install() itself raised.
    """
    import datetime
    import platform as _platform
    import re
    import traceback

    # Frozen builds compile to bytecode on the dev's own machine, and Python
    # bakes that absolute source path into each code object (co_filename) --
    # it travels with the exe and shows up in every player's traceback
    # regardless of where they installed the game. Collapse it to a generic
    # stand-in so a report a player sends back doesn't expose the dev's local
    # folder layout.
    build_path_re = re.compile(
        r'(?P<prefix>[A-Za-z]:\\Users\\|/Users/|/home/)[^\\/]+'
        r'(?:[\\/][^\\/\r\n]+)*?(?P<sep>[\\/])Greater-Diplomacy-5(?P<sep2>[\\/])'
    )

    def _scrub_build_paths(text):
        return build_path_re.sub(
            lambda m: f"{m.group('prefix')}...{m.group('sep')}Greater-Diplomacy-5{m.group('sep2')}",
            text,
        )

    crash_log_path = os.path.expanduser("~/GD5_crash.log")

    header_lines = [
        "Greater Diplomacy 5 crash report",
        f"Time: {datetime.datetime.now().isoformat(timespec='seconds')}",
        f"OS: {_platform.platform()}",
        f"Python: {sys.version}",
    ]
    try:
        header_lines.append(f"Version: {sys.modules['data.constants'].GAME_VERSION}")
    except Exception:
        pass
    try:
        header_lines.append(f"Pygame: {sys.modules['pygame'].version.ver}")
    except Exception:
        pass

    tb_text = _scrub_build_paths(traceback.format_exc())
    with open(crash_log_path, "w") as f:
        f.write("\n".join(header_lines) + "\n\n")
        f.write(tb_text)

    # Best-effort: an environment without a display (or without tkinter)
    # just misses the popup, not the crash log itself.
    try:
        import tkinter
        from tkinter import messagebox
        root = tkinter.Tk()
        root.withdraw()
        messagebox.showerror(
            "Greater Diplomacy 5 crashed",
            "Sorry, the game ran into an error and had to close.\n\n"
            f"A crash report was saved to:\n{crash_log_path}\n\n"
            "Please send this file to the developer so they can figure out what went wrong."
        )
        root.destroy()
    except Exception:
        pass


if __name__ == "__main__":
    try:
        asyncio.run(_bootstrap())
    except Exception:
        import traceback
        # sys.platform, not IS_WEB -- if _import_project_modules() itself
        # blew up (e.g. mod_loader.install() raised), IS_WEB was never set,
        # and referencing it here would mask the real exception with a
        # NameError.
        if sys.platform == "emscripten":
            # ~/GD5_crash.log isn't reachable from a browser sandbox, so the
            # traceback has to find the player some other way -- and
            # print_exc() alone does NOT do it. Under pygbag stderr only
            # reaches its own in-page xterm overlay, which web_index.tmpl
            # hides on every non-#debug load (custom_onload's
            # `pyconsole.hidden = debug_hidden`), so a startup crash renders
            # as a black canvas with an empty devtools console and no other
            # clue. Confirmed the hard way by a WebP-mislabelled-as-.png file
            # in assets/hanskolmer/ that killed symbol_loader on web only:
            # nothing surfaced anywhere until that hidden terminal was
            # scraped by hand. Mirror it to window.console.error -- the same
            # route, for the same reason, as mod_loader._log().
            traceback.print_exc()
            try:
                import platform  # stdlib `platform`, patched by pygbag with `.window`
                platform.window.console.error(
                    "[gd5] fatal error during startup:\n" + traceback.format_exc()
                )
            except Exception:
                # A logging failure must never be what replaces the real
                # traceback, same guard mod_loader puts around its own.
                pass
        else:
            _write_crash_log()
            raise
