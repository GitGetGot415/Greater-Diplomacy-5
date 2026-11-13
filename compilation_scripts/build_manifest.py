"""Declare distributed sources and explicit platform differences.

This module must remain safe to import without game or packaging engines.
"""

from data.io.game_files import DESKTOP_SOURCE_FILES, EXPORTS_DIR, NATIVE_BINARIES, SOURCE_FILES, SOURCE_PACKAGES
from data.io.starting_defaults import PREFERENCE_FILES, STARTING_DEFAULTS_PATH, read_starting_defaults

WINDOWS_DIST_DIR = "dist/windows"
MACOS_DIST_DIR = "dist/macos"
MACOS_BUILD_DIR = "build/macos"
WEB_DIST_DIR = "dist/web"
WEB_CONTENT_DIR = WEB_DIST_DIR + "/package"
WEB_SOURCE_FILES = SOURCE_FILES + ("libdragoman.so",)
# Android runs the web distribution. Keep its native wrapper out of desktop/web archives.
ANDROID_PROJECT_DIR = "compilation_scripts/android"
ANDROID_PROJECT_FILES = (
    "settings.gradle", "build.gradle", "gradle.properties", "gradlew", "gradlew.bat",
    "gradle/wrapper/gradle-wrapper.jar", "gradle/wrapper/gradle-wrapper.properties",
    "app/build.gradle", "app/src/main/AndroidManifest.xml",
    "app/src/main/java/org/greaterdiplomacy/gd5/MainActivity.java",
)
ANDROID_APPLICATION_ID = "org.greaterdiplomacy.gd5"
ANDROID_APK = "dist/android/GD5 Android.apk"
ANDROID_ICON = "assets/icon/icon.png"
# Android loads the gzip game bundle. Pygbag's ZIP-format .apk is only for web hosting.
ANDROID_WEB_EXCLUDED_PATTERNS = ("*.apk",)
DATA_DIRS = ("assets", "base_maps", "scenarios")
EMPTY_DIRS = ("saves", "tournament_saves", "mods", EXPORTS_DIR)
WEB_EXCLUDED_SUBPACKAGES = ()
DEV_ONLY_PACKAGES = ("data.generators",)
DEV_ONLY_FILES = ("run_tests.py",)

# Keep each dynamic import explicit. Package discovery previously omitted screens
# from Windows archives even when discovery reported them.
HIDDEN_IMPORTS = (
    "screens.game.automation_screen",
    "screens.game.declare_independence",
    "screens.game.politics_screen",
    "screens.game.unit_events_screen",
    "screens.game.country_summary",
    "screens.game.battle_editor",
    "screens.game.custom_battle",
    "screens.game.tactical_retreat",
    "map_logic.custom_battle",
    "map_logic.battle_terrain",
    "screens.game.tactical_orders",
    "screens.editors.unit_stats_editor",
    "map_logic.system32.unit_events",
    "map_logic.system32.air_processor",
    "data.migrations",
    "data.migrations.validation",
    "data.migrations.released_content",
    "map_logic.diplomacy.diplomacy_lifecycle",
    "map_logic.actions.production_actions",
    "map_logic.actions.unit_actions", "map_logic.actions.player_actions",
    "map_logic.diplomacy.action_definitions", "map_logic.diplomacy.faction_records",
    "data.runtime_rules", "data.world_nations",
    "data.game_state", "data.session_state", "data.state_access",
    "data.research_display",
    "data.io.starting_defaults",
    "data.io.standalone_music",
    "ui.background_styles",
    "ui.music_playback",
    "ui.widgets.content_browser",
    "ui.navigation.touch_input",
)
RUNTIME_PACKAGES = (
    "screens", "screens.menus", "screens.setup", "screens.multiplayer",
    "screens.game", "screens.editors",
    "map_logic", "map_logic.actions", "map_logic.ai", "map_logic.diplomacy",
    "map_logic.imports", "map_logic.random_map", "map_logic.territory",
    "map_logic.system32",
    "ui", "ui.bars", "ui.camera", "ui.dialogs", "ui.information",
    "ui.navigation", "ui.panels", "ui.rendering", "ui.widgets",
    "data", "data.io", "data.map", "data.migrations", "data.queries", "data.multiplayer",
    "data.multiplayer.tournament", "data.multiplayer.realtime",
)
NATIVE_PACKAGES = ("dragoman", "cryptography", "quickjs", "py_mini_racer")
MAC_INCLUDES = tuple(dict.fromkeys(("soloud", "pygame", "tkinter") + HIDDEN_IMPORTS))
RUNTIME_JSON_DEFAULTS = {name: value for name, value in read_starting_defaults().items()
                        if name in PREFERENCE_FILES}


def windows_arguments():
    """Return explicit PyInstaller arguments, preserving native dependencies."""
    args = ["--clean", "--onefile", "--distpath", WINDOWS_DIST_DIR]
    for package in NATIVE_PACKAGES:
        args.extend(("--collect-all", package))
    for module in HIDDEN_IMPORTS:
        args.extend(("--hidden-import", module))
    for binary in NATIVE_BINARIES:
        args.extend(("--add-binary", binary + ";."))
    return args + ["main.py"]
