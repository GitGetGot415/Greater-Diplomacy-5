"""Declare distributed sources and explicit platform differences.

This module must remain safe to import without game or packaging engines.
"""

from data.io.game_files import DESKTOP_SOURCE_FILES, EXPORTS_DIR, NATIVE_BINARIES, SOURCE_FILES, SOURCE_PACKAGES
from data.io.starting_defaults import PREFERENCE_FILES, STARTING_DEFAULTS_PATH, read_starting_defaults

WINDOWS_DIST_DIR = "dist/windows"
LINUX_DIST_DIR = "dist/linux"
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
    "app/src/main/java/org/greaterdiplomacy/gd5/AndroidFiles.java",
)
ANDROID_APPLICATION_ID = "org.greaterdiplomacy.gd5"


def android_apk():
    """Return the APK path, named after the game version like the other platforms' exports."""
    # data.constants loads game modules; importing it here keeps this module free of them.
    from data.constants import GAME_VERSION
    return f"dist/android/GD5 ANDROID {GAME_VERSION}.apk"


ANDROID_ICON = "assets/icon/icon.png"
# Android loads the gzip game bundle. Pygbag's ZIP-format .apk is only for web hosting.
ANDROID_WEB_EXCLUDED_PATTERNS = ("*.apk",)
# Mirror the tested Pygbag runtime inside the APK. Verify cached downloads too:
# the public CDN can change independently of the installed build-time Pygbag.
ANDROID_RUNTIME_CDN = "https://pygame-web.github.io/cdn/"
ANDROID_RUNTIME_LOADER = "0.9.3/pythons.js"
ANDROID_RUNTIME_PYTHON = "python3.12"
ANDROID_RUNTIME_FILES = {
    ANDROID_RUNTIME_LOADER: "6da43e3e62c3db933421b99681e8ef99ed9b0ce1589ed8a0c69b88443278e019",
    "0.9.3/cpythonrc.py": "b8a0b8168b58ef7c38c17d4705c9cbe1751fa667a0a6d26ed26f0537134735de",
    "0.9.3/cpython312/main.js": "01c4e4dc7145a482ad259d8272ce73d97b58ec2a141bfb57e620347730d159c7",
    "0.9.3/cpython312/main.data": "b068df4d59b06b113cfc3c4d6419bdf699d2c2eeb547c9119e2044c98cdc4a59",
    "0.9.3/cpython312/main.wasm": "3cfb882de90feeb367325f0c58731932880c8f424fb5a670b98d035ae862b280",
    "0.9.3/empty.html": "b0693dc92f76e08bf1485b3dd9b514a2e31dfd6f39422a6b60edb722671dc98f",
    "index-0.9.3-cp312.json": "ec6edacc1b95700c99b8daecb8ce3949e58e96a1da5234c81d8a0071aa537213",
    "cp312/numpy-2.0.2-cp312-cp312-pyodide_2024_0_wasm32.whl": "ebfa5de0256e98fcd4ece4546e054dea50b73ecf735ec836237fd45bcc5eab1f",
    "cp312/pygame_ce-2.5.7-cp312-cp312-wasm32_bi_emscripten.whl": "4f2caa3020592950565f3649c41e2eeacd001be93da892d60e5a4a43d893a323",
    "vtx.js": "9c5f4de60a85dad9093862715094d67d9c8065872657ad3effa1a6cac6834797",
    "vt/xterm.js": "f0aea0f75f48559013ae6643c2479dd737d26da42d5524e6d2b70915ae6523c7",
    "vt/xterm.css": "832f3f2c603b43ad4351ff04970150cc7a873014276db126a6065c6dd81e4872",
    "vt/xterm-addon-image.js": "a4795cf0998c595de120f79a69c6e522db5fff28dba7c50c1e872ea81a89fd81",
}
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
    "map_logic.naval_battle",
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


def frozen_arguments(dist_dir, binary_separator):
    """Return explicit PyInstaller arguments, preserving native dependencies.

    PyInstaller separates an --add-binary source from its destination with the
    host operating system's path separator, which is a semicolon on Windows and
    a colon everywhere else. Each caller passes the separator for the operating
    system that caller builds on, because neither PyInstaller build cross-compiles.
    """
    args = ["--clean", "--onefile", "--distpath", dist_dir]
    for package in NATIVE_PACKAGES:
        args.extend(("--collect-all", package))
    for module in HIDDEN_IMPORTS:
        args.extend(("--hidden-import", module))
    for binary in NATIVE_BINARIES:
        args.extend(("--add-binary", binary + binary_separator + "."))
    return args + ["main.py"]


def windows_arguments():
    """Return the PyInstaller arguments for the Windows build, which runs on Windows."""
    return frozen_arguments(WINDOWS_DIST_DIR, ";")


def linux_arguments():
    """Return the PyInstaller arguments for the Linux build, which runs on Linux."""
    return frozen_arguments(LINUX_DIST_DIR, ":")
