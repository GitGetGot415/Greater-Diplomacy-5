"""Declare distributed sources and explicit platform differences.

This module must remain safe to import without game or packaging engines.
"""

SOURCE_PACKAGES = ("data", "ui", "screens", "map_logic")
SOURCE_FILES = ("main.py", "mod_loader.py", "gameState.py", "ui_elements.py", "beepbox_audio.py")
DESKTOP_SOURCE_FILES = SOURCE_FILES + ("soloud.py",)
WEB_SOURCE_FILES = SOURCE_FILES + ("libdragoman.so",)
DATA_DIRS = ("assets", "base_maps", "scenarios")
EMPTY_DIRS = ("saves", "tournament_saves", "mods")
WEB_EXCLUDED_SUBPACKAGES = ("data.editors",)
DEV_ONLY_PACKAGES = ("data.generators",)
DEV_ONLY_FILES = ("run_tests.py", "simulate_crash.py", "temp_multiplayer_io.py")

# Keep each dynamic import explicit. Package discovery previously omitted screens
# from Windows archives even when discovery reported them.
HIDDEN_IMPORTS = (
    "screens.map_related_screens.automation_screen",
    "screens.map_related_screens.declare_independence",
    "screens.map_related_screens.politics_screen",
    "screens.map_related_screens.unit_events_screen",
    "screens.map_related_screens.country_summary",
    "screens.editor_screens.unit_stats_editor",
    "map_logic.turn_processing.unit_events",
    "map_logic.turn_processing.air_processor",
    "data.migrations",
    "map_logic.diplomacy.diplomacy_lifecycle",
    "map_logic.production_actions",
    "map_logic.unit_actions", "map_logic.player_actions",
    "map_logic.diplomacy.action_definitions", "map_logic.diplomacy.faction_records",
    "data.runtime_rules", "data.world_nations",
    "data.game_state", "data.session_state", "data.state_access",
)
RUNTIME_PACKAGES = (
    "screens", "screens.menu_screens", "screens.map_related_screens", "screens.editor_screens",
    "map_logic", "map_logic.ai", "map_logic.camera", "map_logic.diplomacy",
    "map_logic.random_map", "map_logic.rendering", "map_logic.setup", "map_logic.turn_processing",
    "ui", "ui.bars", "ui.information", "ui.confirm_dialog",
    "data", "data.editors", "data.io", "data.map",
)
NATIVE_PACKAGES = ("dragoman", "cryptography", "quickjs", "py_mini_racer")
MAC_INCLUDES = tuple(dict.fromkeys(("gameState", "ui_elements", "soloud", "pygame", "tkinter") + HIDDEN_IMPORTS))
NATIVE_BINARIES = ("win64-libsoloud.dll", "mac64-libsoloud.dylib", "lin64-libsoloud.so")
RUNTIME_JSON_DEFAULTS = {
    "active_albums.json": [], "shuffle_disabled_tracks.json": [],
    "scenario_settings.json": {}, "settings_config.json": {},
    "starting_song.json": {}, "hildehrand_choice.json": {},
}


def windows_arguments():
    """Return explicit PyInstaller arguments, preserving native dependencies."""
    args = ["--clean", "--onefile"]
    for package in NATIVE_PACKAGES:
        args.extend(("--collect-all", package))
    for module in HIDDEN_IMPORTS:
        args.extend(("--hidden-import", module))
    for binary in NATIVE_BINARIES:
        args.extend(("--add-binary", binary + ";."))
    return args + ["main.py"]
