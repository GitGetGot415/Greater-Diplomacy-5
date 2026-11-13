"""Standalone games: a copy of GD5 that plays one scenario.

The map editor exports a standalone game to exports/<scenario name>/.
That folder holds the game's source, the assets it shows, one scenario, and game.json.
When game.json is next to the game at startup, the game runs in standalone mode.
Standalone mode removes every way to reach another map, the editor, multiplayer, mods, tactical mode,
unit art other than classic, and the GD5 version check. The music player stays, with no songs exported.
"""

import json
import os
import shutil
import sys

import data.constants as c
from data import queries
from data.map import load_map
from data.io.game_files import DESKTOP_SOURCE_FILES, EXPORTS_DIR, LICENSE_FILE, NATIVE_BINARIES, SOURCE_PACKAGES
from data.io.starting_defaults import write_preference_defaults
from data.platform import CHARACTERS_DIR, LoadingSteps

GAME_FILE = "game.json"
# Packages keep only Python source, except data/, which also keeps its JSON libraries.
DATA_PACKAGE = "data"
SKIPPED_DIRS = ("__pycache__",)
# Tactical mode is not exported. Turn processing still imports map_logic/custom_battle.py and map_logic/battle_terrain.py.
EXCLUDED_SOURCE_FILES = ("screens/game/custom_battle.py", "screens/game/tactical_orders.py",
                         "screens/game/tactical_retreat.py")
# Assets that a standalone game never shows: songs, the BeepBox and UltraBox synths that play them,
# the GD5 menu's title, scenery, and portraits, every unit art style except classic, tactical battle art,
# and the Assets screen's art and copyright notes.
EXCLUDED_ASSETS = (
    c.MUSIC_DIR, "assets/beepbox", "assets/ultrabox",
    "assets/backgrounds/Title.png", "assets/images/The Sign.png", "assets/images/Left Ground.png",
    "assets/images/Right Ground.png", CHARACTERS_DIR,
    "assets/battles", "assets/art", "assets/copyright", "assets/unused",
) + tuple(os.path.join(c.ASSETS_ROOT_DIR, style).replace(os.sep, "/") for style in c.UNIT_ART_STYLES if style != "classic")


def _read_game():
    # Startup makes the game folder the working directory before screens import this module.
    try:
        with open(GAME_FILE, encoding="utf-8") as stream:
            return json.load(stream)
    except FileNotFoundError:
        return None


GAME = _read_game()
IS_STANDALONE = GAME is not None


def title():
    return GAME["title"]


def scenario_path():
    return GAME["scenario"]


def export_settings():
    """Return the export settings for this standalone game. Older exports use the defaults."""
    return queries.normalized_standalone_export_settings(GAME.get("standalone_export_settings"))


def export_dir(name):
    return os.path.join(EXPORTS_DIR, name)


def clear_export_dir(name):
    """Delete everything inside an older export so a new export can replace it.

    The folder itself stays. Windows refuses to delete a folder that another process uses
    as its working directory, such as the exported game while it runs.
    """
    for entry in os.scandir(export_dir(name)):
        if entry.is_dir(follow_symlinks=False):
            shutil.rmtree(entry.path)
        else:
            os.remove(entry.path)


def _walk_files(root):
    for parent, directories, filenames in os.walk(root):
        directories[:] = [name for name in directories if name not in SKIPPED_DIRS]
        for filename in filenames:
            yield os.path.join(parent, filename)


def _wanted_package_file(path, package):
    if path.replace(os.sep, "/") in EXCLUDED_SOURCE_FILES:
        return False
    extension = os.path.splitext(path)[1]
    return extension == ".py" or (package == DATA_PACKAGE and extension == ".json")


def _scenario_flags(scenario_dir):
    """Return the flag files that this scenario can show.

    A country uses assets/flags/<country id>.png unless its scenario record stores its own image.
    The flags kept are for countries that exist (including governments in exile), countries that cores
    can release (puppet releases and rebellions copy a core country's flag), the non-country
    flags such as Spectator, and the default flag.
    """
    save_meta, map_data, _history = load_map.read_save_files(scenario_dir)
    nation_data = (save_meta or {}).get("nation_data", {})
    countries = queries.get_politically_active_nations(map_data, nation_data)
    countries.update(core for province in map_data.values() for core in province.get("cores", []))
    countries.update(c.UNPLAYABLE_NATIONS)
    flags = {f"{c.FLAGS_DIR}/{country}.png" for country in countries}
    flags.add(c.DEFAULT_FLAG_PATH)
    return flags


def _wanted_asset(path, flags):
    path = path.replace(os.sep, "/")
    if path.startswith(c.FLAGS_DIR + "/"):
        return path in flags
    return not any(path == excluded or path.startswith(excluded + "/") for excluded in EXCLUDED_ASSETS)


def _export_copies(scenario_dir, destination, scenario_target):
    """List (source, target) pairs for every file a standalone game needs."""
    copies = [(name, os.path.join(destination, name))
              for name in DESKTOP_SOURCE_FILES + NATIVE_BINARIES + (LICENSE_FILE,) if os.path.isfile(name)]
    for package in SOURCE_PACKAGES:
        copies.extend((path, os.path.join(destination, path)) for path in _walk_files(package)
                      if _wanted_package_file(path, package))
    flags = _scenario_flags(scenario_dir)
    copies.extend((path, os.path.join(destination, path)) for path in _walk_files("assets") if _wanted_asset(path, flags))
    copies.extend((path, os.path.join(scenario_target, os.path.relpath(path, scenario_dir)))
                  for path in _walk_files(scenario_dir))
    return copies


def export_steps(scenario_dir, name, settings):
    """Copy this game and one saved scenario into exports/<name>/ as loading steps.

    settings are the map editor's standalone export settings. game.json stores them.

    A frozen Windows game also copies its executable as <name>.exe.
    A game run from source exports a folder that runs with `python main.py`.
    The caller clears an older export of the same name first (see clear_export_dir).
    """
    destination = export_dir(name)
    scenario_relative = os.path.join("scenarios", name)
    scenario_target = os.path.join(destination, scenario_relative)
    copies = _export_copies(scenario_dir, destination, scenario_target)
    executable = getattr(sys, "frozen", False) and os.name == "nt"

    def steps():
        for source, target in copies:
            yield f"Copying {source}..."
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copy2(source, target)
        yield "Writing game files..."
        write_preference_defaults(os.path.join(destination, "data", "json"))
        os.makedirs(os.path.join(destination, c.DEFAULT_SAVES_DIR), exist_ok=True)
        with open(os.path.join(destination, GAME_FILE), "w", encoding="utf-8") as stream:
            json.dump({"title": name, "scenario": scenario_relative.replace(os.sep, "/"),
                       "standalone_export_settings": queries.normalized_standalone_export_settings(settings)},
                      stream, indent=4)
        if executable:
            yield "Copying the game executable..."
            shutil.copy2(sys.executable, os.path.join(destination, name + ".exe"))
        return os.path.abspath(destination)

    return LoadingSteps(steps(), len(copies) + 1 + executable)
