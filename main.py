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

import json
import random

import asyncio
import os
import sys


def _relaunch_with_project_venv():
    """Run source launches with this checkout's dependency-complete venv.

    macOS commonly opens a ``.py`` file with the framework ``python3`` rather
    than VS Code's selected project interpreter.  That Python can launch most
    of GD5 but lacks the optional native BeepBox runtimes, making every JSON
    album appear empty.  Re-exec before importing project modules so opening
    or running main.py directly behaves the same as ``venv/bin/python main.py``.
    Frozen desktop builds and the web build have no source-tree venv and are
    deliberately left alone.
    """
    if getattr(sys, "frozen", False) or os.environ.get("GD5_VENV_REEXEC"):
        return

    project_root = os.path.dirname(os.path.abspath(__file__))
    venv_python = os.path.join(
        project_root,
        "venv",
        "Scripts" if os.name == "nt" else "bin",
        "python.exe" if os.name == "nt" else "python",
    )
    if not os.path.isfile(venv_python):
        return
    if os.path.normcase(os.path.abspath(sys.executable)) == os.path.normcase(venv_python):
        return

    environment = os.environ.copy()
    environment["GD5_VENV_REEXEC"] = "1"
    os.execve(venv_python, [venv_python, os.path.abspath(__file__), *sys.argv[1:]], environment)


if __name__ == "__main__":
    _relaunch_with_project_venv()

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
    global Messages_Screen, dispatch_global_keys, synthesize_keybind_mouse_events, keyboard_input_is_captured, fonts, ui_elements, ui_bars, c, queries
    global music_playback
    global Load_Game, Map, Menu, New_Game, Settings, Credits, Music_Player, View_Assets, Mods, Unit_Art, Keybinds, Mouse_Settings, Edit_Portrait, default_keybinds
    global Translate, Translation_Menu, Greater_Diplomacy_4_Translation, Greater_Diplomacy_Hex_Translation
    global Orders_Screen, Tactical_Orders_Screen, keybind_io, settings_schema, symbol_loader, modal_stack, screen_runner
    global BattleEditorScreen
    global CustomBattleScreen, Tactical_Retreat_Screen
    global Research_Screen, Economy_Screen, Edit_Country_Screen, Production_Screen
    global Faction_Screen, Faction_Territories_Screen
    global Map_Editor_Menu, Select_Base_Map, Random_Setup, Scenario_Settings
    global Multiplayer_Menu, Real_Time_Multiplayer
    global Multiplayer_Hub, Multiplayer_Host, Multiplayer_Join, Multiplayer_New
    global Realtime_Host_Setup, Realtime_Scenario_Select, Realtime_Lobby, Realtime_Join, Realtime_Lan_Browser, Realtime_Remote_Lobby
    global Realtime_Relay_Setup, Realtime_Relay_Provision
    global ai_handler

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

    from screens.game.messages import Messages_Screen
    from ui.navigation.screen import (dispatch_global_keys, synthesize_keybind_mouse_events,
                           keyboard_input_is_captured)
    from ui.rendering.font_manager import fonts
    from ui.widgets import ui_elements
    from ui import music_playback
    from ui.bars import ui_bars
    import data.constants as c
    from data import queries
    from screens.menus.load_game import Load_Game
    from screens.game.map import Map
    from screens.menus.menu import Menu
    from screens.setup.new_game import New_Game
    from screens.menus.settings import Settings
    from screens.menus.credits import Credits
    from screens.menus.translate import Translate
    from screens.menus.translation_menu import (
        Translation_Menu,
        Greater_Diplomacy_4_Translation,
        Greater_Diplomacy_Hex_Translation,
    )
    from screens.menus.music_player import Music_Player
    from screens.menus.view_assets import View_Assets
    from screens.menus.mods import Mods
    from screens.menus.unit_art import Unit_Art
    from screens.menus.keybinds import Keybinds, default_keybinds
    from screens.menus.mouse_settings import Mouse_Settings
    from screens.menus.edit_portrait import Edit_Portrait
    from screens.game.orders import Orders_Screen
    from screens.game.tactical_orders import Tactical_Orders_Screen
    from screens.game.battle_editor import BattleEditorScreen
    from screens.game.custom_battle import CustomBattleScreen
    from screens.game.tactical_retreat import Tactical_Retreat_Screen
    from data.io import keybind_io, settings_schema
    from ui.rendering import symbol_loader
    from ui.navigation import modal_stack, screen_runner
    from screens.game.research import Research_Screen
    from screens.game.economy import Economy_Screen
    from screens.editors.edit_country import Edit_Country_Screen
    from screens.game.production import Production_Screen
    from screens.game.faction import Faction_Screen, Faction_Territories_Screen
    from screens.setup.select_base_map import Map_Editor_Menu, Select_Base_Map
    from screens.setup.random_setup import Random_Setup
    from screens.setup.scenario_settings import Scenario_Settings
    from screens.multiplayer.multiplayer_menu import Multiplayer_Menu, Real_Time_Multiplayer
    from screens.multiplayer.multiplayer_hub import Multiplayer_Hub
    from screens.multiplayer.multiplayer_host import Multiplayer_Host
    from screens.multiplayer.multiplayer_join import Multiplayer_Join
    from screens.multiplayer.multiplayer_new import Multiplayer_New
    from screens.multiplayer.realtime_multiplayer import (
        Realtime_Host_Setup,
        Realtime_Scenario_Select,
        Realtime_Lobby,
        Realtime_Join,
        Realtime_Lan_Browser,
        Realtime_Remote_Lobby,
        Realtime_Relay_Setup,
        Realtime_Relay_Provision,
    )
    from map_logic.ai import ai_handler

    pygame.display.set_caption("Greater Diplomacy 5")


class Controller:
    soloud = None
    # The playback object for the current track: see ui/music_playback.py.
    music = None
    last_toggle_time = None
    is_fullscreen = False

    def __init__(self):
        ui_elements.load_sound_volumes()
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
                self.music_stream = WavStream()
                ui_elements.soloud_engine = self.soloud

                try:
                    ui_elements.click_sound = Wav()
                    ui_elements.click_sound.load(c.SOUND_CLICK_PATH)
                    ui_elements.slider_sound = Wav()
                    ui_elements.slider_sound.load(c.SOUND_SLIDER_PATH)
                    ui_elements.load_music_ui_sounds(Wav, soloud=True)
                except Exception:
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
            ui_elements.load_pygame_ui_sounds()

        # Initialize fonts
        font_path = c.FONT_PATH_DEFAULT
        fonts.init_fonts(font_path)

        self.screen = ui_bars.set_display_mode((c.SCREEN_WIDTH, c.SCREEN_HEIGHT))

        # 0. Load symbols
        try:
            icon = pygame.image.load('assets/icon/icon.png')
            pygame.display.set_icon(icon)
        except FileNotFoundError:
            print("Icon not found")

        symbol_loader.load_symbols()

        ui_elements.UI_ICONS = {
            # Map controls fit these native-size sources to their button bounds.
            "naval": symbol_loader.get_symbol("Naval", 2),
            "land": symbol_loader.get_symbol("Land", 2),
            "air": symbol_loader.get_symbol("Air", 2),
            "all": symbol_loader.get_symbol("All", 2),
            "unit": symbol_loader.get_symbol("Infantry", 2),
            "industry": symbol_loader.get_symbol("Factory", 2),
            "blank": symbol_loader.get_symbol("Nothing", 1),
            "terrain": symbol_loader.get_symbol("Mountains", 1.5),
            "political": symbol_loader.get_symbol("Flag", 1.5),
            "relations": symbol_loader.get_symbol("Heart", 2),
            "research": symbol_loader.get_symbol("Research", 2.5),
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
            "stack": pygame.image.load("assets/images/Stack.png").convert_alpha(),
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
        default_keys = default_keybinds()

        # 2. Load settings (Safely handle old saves that might not have pitch/speed)
        loaded_data = keybind_io.load_settings_result(default_keys, c.DEFAULT_SFX_VOLUME, c.DEFAULT_MUSIC_VOLUME)
        self.keybinds = loaded_data.keybinds
        settings = loaded_data.values
        settings_schema.apply_to_controller(self, settings)
        c.apply_runtime_settings(settings)

        # 3. Apply volume to global sounds on boot
        ui_elements.global_sfx_volume = self.sfx_volume
        ui_elements.global_sfx_pitch = self.sfx_pitch

        self.all_albums = {}
        self.active_albums = []
        self.playlist = []
        self.shuffle_disabled_tracks = set()
        self.now_playing = "None"
        self._failed_music_tracks = set()
        self.starting_song = None
        # The settings name of the tactical song list that is playing, or None.
        self._tactical_song_setting = None
        self.track_start_times = {} # Keeps track of offsets specified in start_times.json

        self.load_music_data()
        # Browsers block audio until it starts from within a genuine user gesture
        # (per pygbag's own guidance: "remove startup sounds and/or wait for a
        # mouse click"). Playing immediately at boot means the browser silently
        # ignores it and the AudioContext never resumes. Deferred to the first
        # real input event in run() on web. Desktop playback waits for its first frame.
        self._web_audio_unlocked = False

        # Say where this game is, for anything that wants to translate a map
        # into it. Best effort and never fatal -- see map_logic/imports/odtl.py.
        try:
            from map_logic.imports import odtl
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
            "MOUSE_SETTINGS": Mouse_Settings(self),
            "EDIT_PORTRAIT": Edit_Portrait(self),
            "CREDITS": Credits(),
            "MUSIC_PLAYER": Music_Player(self),
            "VIEW_ASSETS": View_Assets(),
            "MODS": Mods(),
            "TRANSLATE": Translate(),
            "TRANSLATION_MENU": Translation_Menu(),
            "TRANSLATE_GD4": Greater_Diplomacy_4_Translation(),
            "TRANSLATE_GDHEX": Greater_Diplomacy_Hex_Translation(),
            "MAP_EDITOR_MENU": Map_Editor_Menu(),
            "NEW_MAP": Select_Base_Map(choosing_sources=True),
            "SELECT_BASE_MAP": Select_Base_Map(),
            "MAP": None,
            "PRODUCTION": Production_Screen(),
            "ORDERS": Orders_Screen(),
            "TACTICAL_ORDERS": Tactical_Orders_Screen(),
            "BATTLE_EDITOR": BattleEditorScreen(),
            "CUSTOM_BATTLE": CustomBattleScreen(),
            "TACTICAL_RETREAT": Tactical_Retreat_Screen(),
            "RESEARCH": Research_Screen(),
            "ECONOMY": Economy_Screen(),
            "EDIT_COUNTRY": Edit_Country_Screen(),
            "MESSAGES": Messages_Screen(),
            "FACTION": Faction_Screen(),
            "FACTION_TERRITORIES": Faction_Territories_Screen(),
            "SCENARIO_SETTINGS": Scenario_Settings(),
            "MULTIPLAYER_MENU": Multiplayer_Menu(),
            "MULTIPLAYER_HUB": Multiplayer_Hub(),
            "MULTIPLAYER_HOST": Multiplayer_Host(),
            "MULTIPLAYER_JOIN": Multiplayer_Join(),
            "MULTIPLAYER_NEW": Multiplayer_New(),
            "REAL_TIME_MULTIPLAYER": Real_Time_Multiplayer(),
            "REALTIME_HOST_SETUP": Realtime_Host_Setup(),
            "REALTIME_SCENARIO_SELECT": Realtime_Scenario_Select(),
            "REALTIME_RELAY_SETUP": Realtime_Relay_Setup(),
            "REALTIME_RELAY_PROVISION": Realtime_Relay_Provision(),
            "REALTIME_LOBBY": Realtime_Lobby(),
            "REALTIME_JOIN": Realtime_Join(),
            "REALTIME_LAN_BROWSER": Realtime_Lan_Browser(),
            "REALTIME_REMOTE_LOBBY": Realtime_Remote_Lobby(),
        }
        self.active_state = self.states["MENU"]

    def flip_state(self):
        """Switch to the screen that the active screen asked for."""
        previous_state = self.active_state
        next_state_name = previous_state.next_state
        if next_state_name == "MAP":
            steps = previous_state.prepare_map_steps(self)
            if steps is not None:
                previous_state.done = False

                def loaded(success):
                    if success:
                        next_state = self.states["MAP"]
                        next_state.on_enter(self, previous_state)
                        self.active_state = next_state

                screen_runner.run_loading(steps, "Loading Map...", on_done=loaded)
                return
        if next_state_name == "MAP" and not previous_state.prepare_map(self):
            return
        next_state = self.states[next_state_name]
        if previous_state is self.states.get("CUSTOM_BATTLE") and next_state is not previous_state:
            self.set_tactical_battle_music(False)
        next_state.on_enter(self, previous_state)
        previous_state.done = False
        self.active_state = next_state

    def load_music_data(self):
        import beepbox_audio
        # Scan the hard drive to find whatever is actually there!
        synced_albums = {}
        self.track_start_times = {} # Clear start times whenever we scan
        # Web uses the bundled BeepBox and UltraBox synths. Desktop needs the
        # packaged V8 runtime. QuickJS can parse a song but cannot keep dense
        # tracks synthesized fast enough for real-time playback.
        prefer_beepbox = IS_WEB or beepbox_audio.is_available()
        if not prefer_beepbox:
            print(
                "BeepBox and UltraBox JSON tracks are unavailable because this Python interpreter "
                f"has no V8 JavaScript runtime: {sys.executable}. "
                "Select the project venv or install requirements.txt."
            )

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

                    files = os.listdir(album_dir)
                    beepbox_stems = {
                        os.path.splitext(file)[0].casefold()
                        for file in files
                        if prefer_beepbox and file.lower().endswith(".json")
                        and beepbox_audio.is_beepbox_song(os.path.join(album_dir, file))
                    }
                    for file in files:
                        file_path = os.path.join(album_dir, file)
                        track_path = None
                        if (prefer_beepbox and file.lower().endswith(".json")
                                and beepbox_audio.is_beepbox_song(file_path)):
                            track_path = file_path.replace("\\", "/")
                        elif file.lower().endswith(c.MUSIC_AUDIO_EXTENSIONS):
                            if prefer_beepbox and os.path.splitext(file)[0].casefold() in beepbox_stems:
                                continue
                            track_path = os.path.join(album_dir, file).replace("\\", "/")
                        if track_path is not None:
                            synced_albums[item].append(track_path)

                            # Map the start time if defined for either audio or JSON tracks.
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

        # Exclusions are independent of album membership. Keep entries for a
        # temporarily absent custom track so it stays excluded if the player
        # puts that album back later. They only affect automatic random play;
        # manual selection remains available for every playlist track.
        self.shuffle_disabled_tracks = {
            track.replace("\\", "/")
            for track in queries.get_shuffle_disabled_tracks()
            if isinstance(track, str) and track
        }

        # Load the pinned boot-up track, if any, and drop it if its file has
        # since been deleted or renamed. Independent of active_albums, since
        # it's meant to play at boot regardless of which albums are toggled on.
        self.starting_song = queries.get_starting_song()
        all_tracks = {track for tracks in self.all_albums.values() for track in tracks}
        if self.starting_song not in all_tracks:
            previous_track = (self.starting_song or "").replace("\\", "/")
            replacement = os.path.splitext(previous_track)[0] + ".json"
            if replacement in all_tracks:
                self.starting_song = replacement
                self.save_starting_song()
            else:
                self.starting_song = None

    def save_active_albums(self):
        queries.save_cached_json("active_albums", self.active_albums)

    def save_shuffle_disabled_tracks(self):
        queries.save_cached_json(
            "shuffle_disabled_tracks", sorted(self.shuffle_disabled_tracks)
        )

    def is_shuffle_disabled(self, track_path):
        return track_path.replace("\\", "/") in self.shuffle_disabled_tracks

    def toggle_shuffle_disabled_track(self, track_path):
        """Exclude/include one track in automatic random selection."""
        track_path = track_path.replace("\\", "/")
        if track_path in self.shuffle_disabled_tracks:
            self.shuffle_disabled_tracks.remove(track_path)
        else:
            self.shuffle_disabled_tracks.add(track_path)
        self.save_shuffle_disabled_tracks()

    def save_starting_song(self):
        queries.save_cached_json("starting_song", {"track": self.starting_song})

    def set_tactical_battle_music(self, active, tanks=False):
        """Switch between tactical battle songs and normal playlist selection.

        A battle with any tank uses the tank songs. Any other battle uses the
        infantry songs. An empty song list keeps normal playlist selection.
        """
        setting = None
        if active:
            setting = "tactical_tank_songs" if tanks else "tactical_infantry_songs"
            if not getattr(self, setting):
                setting = None
        if self._tactical_song_setting == setting:
            return
        self._tactical_song_setting = setting
        self.play_random_song()

    def tactical_song_candidates(self):
        """Playable songs of the active tactical song list.

        Tactical songs ignore active albums and shuffle exclusions. A missing
        file fails once when played and is skipped afterward.
        """
        songs = getattr(self, self._tactical_song_setting) if self._tactical_song_setting else []
        candidates = []
        for track in songs:
            if track in self._failed_music_tracks and track.lower().endswith(".json"):
                track = self._beepbox_audio_fallback(track)
            if track and track not in self._failed_music_tracks and track not in candidates:
                candidates.append(track)
        return candidates

    def play_startup_song(self):
        """Plays the pinned starting song if one is set, else falls back to random."""
        if self.starting_song:
            self.play_specific_song(self.starting_song)
        else:
            self.play_random_song()

    def init_web_audio(self):
        """Deferred pygame.mixer bootstrap for web -- see the IS_WEB guard in __init__."""
        pygame.mixer.init()
        ui_elements.load_pygame_ui_sounds()

    def build_playlist(self):
        self.playlist = []
        for album in self.active_albums:
            if album in self.all_albums:
                self.playlist.extend(self.all_albums[album])

    def play_random_song(self):
        available_tracks = self.tactical_song_candidates() or [
            track for track in self.playlist
            if (track not in self._failed_music_tracks
                and not self.is_shuffle_disabled(track))
        ]
        if not available_tracks:
            self.now_playing = "None"
            if self.music is not None:
                self.music.stop()
                self.music = None
            return


        # Check if we have more than one song and if the current song is in the playlist
        if len(available_tracks) > 1 and self.now_playing in available_tracks:
            # Create a temporary list of all songs EXCEPT the one that just played
            other_tracks = [track for track in available_tracks if track != self.now_playing]
            track = random.choice(other_tracks)
        else:
            # Fallback for playlists with only 1 song, or if nothing is playing yet
            track = random.choice(available_tracks)

        self.play_specific_song(track)

    @staticmethod
    def _beepbox_audio_fallback(song_path):
        """Find a packaged audio counterpart when a BeepBox synth cannot start."""
        extensions = (".ogg", ".mp3", ".wav") if IS_WEB else (".mp3", ".wav", ".ogg")
        stem = os.path.splitext(song_path)[0]
        return next((stem + ext for ext in extensions if os.path.exists(stem + ext)), None)

    def play_specific_song(self, track_path):
        try:
            # Fetch the defined start time, default to 0.0 if not listed
            start_time = self.track_start_times.get(track_path, 0.0)

            import beepbox_audio
            speed = 0.5 + self.music_pitch
            # A track that fails to start leaves the stopped playback here. It
            # reports that it finished, so run() moves on to another song.
            if self.music is not None:
                self.music.stop()
            if track_path.lower().endswith(".json") and beepbox_audio.is_beepbox_song(track_path):
                stream_type = (
                    beepbox_audio.WebBeepBoxStream if IS_WEB
                    else beepbox_audio.BeepBoxStream
                )
                # start_times.json is authored in the source track's seconds.
                # BeepBox's stream position is elapsed playback seconds, which
                # differs when the user elected the static source-time timeline.
                beepbox_start_time = start_time
                if self.music_pitch_timeline == c.MUSIC_PITCH_TIMELINE_STATIC:
                    beepbox_start_time /= speed
                self.music = music_playback.BeepBoxPlayback(stream_type(
                    track_path,
                    volume=self.music_volume,
                    speed=speed,
                    start_time=beepbox_start_time,
                ))
            elif (IS_WEB and track_path.lower().endswith('.mp3')
                  and music_playback.pygame_audio_path(track_path) == track_path):
                self.music = music_playback.WebMP3Playback(
                    track_path, start_time, self.music_volume)
            elif c.USE_SOLOUD:
                self.music = music_playback.SoLoudPlayback(
                    self.soloud, self.music_stream, track_path,
                    start_time, self.music_volume, speed)
            else:
                self.music = music_playback.PygamePlayback(
                    track_path, start_time, self.music_volume)

            self.now_playing = track_path
        except Exception as e:
            print(f"Error playing track {track_path}: {e}")
            # A failed temporary battle song must not be retried every frame.
            # Cache the failure before trying its audio counterpart as well.
            self._failed_music_tracks.add(track_path)
            self.music = None
            if track_path.lower().endswith(".json"):
                fallback = self._beepbox_audio_fallback(track_path)
                if fallback and fallback not in self._failed_music_tracks:
                    extension = os.path.splitext(fallback)[1][1:].upper()
                    print(f"Falling back to the matching {extension} track.")
                    self.play_specific_song(fallback)
                    return
            self.play_random_song()

    def _shutdown_audio(self):
        if not IS_WEB:
            # Desktop audio backends can block while synchronously stopping
            # their audio thread. This process already exits with os._exit, so
            # skip teardown that can deadlock and terminate directly instead.
            os._exit(0)

        if self.music is not None:
            self.music.stop()
        if c.USE_SOLOUD and self.soloud is not None:
            self.soloud.deinit()
        elif not c.USE_SOLOUD:
            pygame.mixer.quit()

    def toggle_fullscreen(self):
        current_time = pygame.time.get_ticks()
        # Debounce: prevent toggling if less than 500ms has elapsed since the last toggle finished
        if self.last_toggle_time is not None and current_time - self.last_toggle_time < 500:
            return

        self.is_fullscreen = not self.is_fullscreen
        if self.is_fullscreen:
            try:
                self.screen = ui_bars.set_display_mode((c.SCREEN_WIDTH, c.SCREEN_HEIGHT), pygame.FULLSCREEN)
            except pygame.error:
                info = pygame.display.Info()
                self.screen = ui_bars.set_display_mode((info.current_w, info.current_h), pygame.NOFRAME)
        else:
            self.screen = ui_bars.set_display_mode((c.SCREEN_WIDTH, c.SCREEN_HEIGHT))

        # Update toggle time AFTER transition, so cooldown starts when screen is ready
        self.last_toggle_time = pygame.time.get_ticks()
        # Clear any accumulated KEYDOWN events (like F11 being held) that queued up while display was resetting
        pygame.event.clear(pygame.KEYDOWN)

    async def run(self):
        startup_music_pending = not IS_WEB
        while True:
            # --- THE MAGIC CPU FIX ---
            self.clock.tick(self.target_fps)

            # --- SONG END CHECK ---
            music = self.music
            if music is not None:
                music.update()
                if music.error is not None:
                    # Synths and browser MP3 decoding can fail asynchronously.
                    failed_track = self.now_playing
                    music.stop()
                    self.music = None
                    self._failed_music_tracks.add(failed_track)
                    fallback = (self._beepbox_audio_fallback(failed_track)
                                if failed_track.lower().endswith('.json') else None)
                    if fallback:
                        extension = os.path.splitext(fallback)[1][1:].upper()
                        print(f"BeepBox playback failed ({music.error}); using the {extension} fallback.")
                        self.play_specific_song(fallback)
                    else:
                        print(f"Music playback failed: {music.error}")
                        self.play_random_song()
                    if self.active_state == self.states.get("MUSIC_PLAYER"):
                        self.states["MUSIC_PLAYER"].refresh_ui()
                elif music.finished:
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
                    # Ollama runs as its own program, so its model would stay
                    # loaded after the game closes. This runs before
                    # _shutdown_audio, which ends a desktop process at once.
                    ai_handler.unload_ollama_models()
                    self._shutdown_audio()
                    # In a browser, os._exit() isn't meaningful; cleanup above
                    # and stop the game loop instead.
                    return

            # MODAL STACK: dialogs/prompts/sub-screens (ui/navigation/modal_stack.py) take over
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
            events = synthesize_keybind_mouse_events(
                events, self.keybinds,
                allow_keydown=not keyboard_input_is_captured(listening_screen),
                reserved_keys=getattr(listening_screen, "reserved_keys", ()))
            for event in events:
                if (event.type == pygame.KEYDOWN and not getattr(listening_screen, "listening_for", None)
                        and event.key not in getattr(listening_screen, "reserved_keys", ())
                        and event.key == self.keybinds.get("FULLSCREEN", pygame.K_F11)):
                    ui_elements.play_ui_sound("click")
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
            if startup_music_pending:
                startup_music_pending = False
                if self.now_playing == "None":
                    self.play_startup_song()
            await asyncio.sleep(0)  # yield to the browser tab / event loop every frame

async def _run_game():
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
        await restore_persisted_dir(c.SCENARIOS_CUSTOM_DIR)
        await restore_persisted_dir(c.MUSIC_DIR)
        from ui.dialogs.character_select_screen import CHARACTERS_DIR, CUSTOM_SUBDIR
        await restore_persisted_dir(os.path.join(CHARACTERS_DIR, CUSTOM_SUBDIR))
    game = Controller()
    await game.run()


async def _bootstrap():
    # Pygbag schedules asyncio.run() and returns immediately. Catch failures
    # inside the task; a synchronous handler around asyncio.run() misses them.
    try:
        await _run_game()
    except Exception:
        if sys.platform != "emscripten":
            raise
        _report_web_crash()


def _report_web_crash():
    # Keep crash reporting independent of project imports: startup may fail
    # before IS_WEB or the UI modules have been initialized.
    import traceback

    traceback.print_exc()
    try:
        import platform  # Pygbag supplies platform.window in the browser.

        platform.window.console.error(
            "[gd5] fatal error during startup:\n" + traceback.format_exc()
        )
        # Pygbag's terminal normally stays hidden outside #debug. Reveal the
        # existing traceback so a failed startup does not leave a blank canvas.
        platform.window.pyconsole.hidden = False
    except Exception:
        # A logging failure must never replace the original traceback.
        pass


def _write_crash_log(crash_log_path=None):
    """Writes a crash report and tells the player where it is.

    Reports normally go to ``~/GD5_crash.log``.  ``crash_log_path`` is an
    internal test hook that lets callers choose a writable location without
    changing the player's crash-report location.

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

    if crash_log_path is None:
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
    with open(crash_log_path, "w", encoding="utf-8") as f:
        f.write("\n".join(header_lines) + "\n\n")
        f.write(tb_text)

    # Tk is not part of the running game UI.  On current macOS releases,
    # creating its first NSApplication after SDL has started can itself abort
    # the process, replacing the useful Python error with a huge OS report.
    # The file above is the reliable report on macOS.
    if sys.platform == "darwin":
        return

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
        # sys.platform, not IS_WEB -- if _import_project_modules() itself
        # blew up (e.g. mod_loader.install() raised), IS_WEB was never set,
        # and referencing it here would mask the real exception with a
        # NameError.
        if sys.platform == "emscripten":
            _report_web_crash()
        else:
            _write_crash_log()
            raise
