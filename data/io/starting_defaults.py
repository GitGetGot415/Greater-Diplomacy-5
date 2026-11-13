"""Read editable distribution defaults without starting the game engines."""

import copy
from functools import lru_cache
import json
from pathlib import Path
import sys


STARTING_DEFAULTS_PATH = "data/json/starting_defaults.json"
_DEFAULT_PATH = Path(__file__).resolve().parents[2] / STARTING_DEFAULTS_PATH
_FILE_TYPES = {
    "scenario_settings.json": dict,
    "settings_config.json": dict,
    "active_albums.json": list,
    "shuffle_disabled_tracks.json": list,
    "starting_song.json": dict,
    "hildehrand_choice.json": dict,
}
PREFERENCE_FILES = tuple(_FILE_TYPES)
_SECTION_TYPES = dict(_FILE_TYPES, random_setup=dict, ai_defaults=dict)


def read_starting_defaults(path=_DEFAULT_PATH):
    """Read release preferences. Reject invalid sections before packaging."""
    with open(path, encoding="utf-8") as stream:
        defaults = json.load(stream)
    if not isinstance(defaults, dict) or set(defaults) != set(_SECTION_TYPES):
        raise ValueError(f"{path}: use these sections: {', '.join(_SECTION_TYPES)}")
    for name, expected_type in _SECTION_TYPES.items():
        if not isinstance(defaults[name], expected_type):
            raise ValueError(f"{path}: {name} must contain a JSON {expected_type.__name__}")
    return defaults


def write_preference_defaults(json_dir):
    """Replace a copied game's preference files with the release defaults in its starting_defaults.json."""
    json_dir = Path(json_dir)
    defaults = read_starting_defaults(json_dir / Path(STARTING_DEFAULTS_PATH).name)
    for name in PREFERENCE_FILES:
        (json_dir / name).write_text(json.dumps(defaults[name], indent=4) + "\n", encoding="utf-8")


@lru_cache(maxsize=1)
def _cached_defaults():
    # Startup sets the game folder as the working directory for frozen builds.
    # Editable files remain there, outside the executable's temporary archive.
    # Source tools can import constants before changing their working directory.
    path = STARTING_DEFAULTS_PATH if getattr(sys, "frozen", False) else _DEFAULT_PATH
    return read_starting_defaults(path)


def get_starting_default(filename):
    """Return an independent preference value. Restart after external edits."""
    return copy.deepcopy(_cached_defaults()[filename])


def get_starting_value(section, key):
    """Read one default without copying unrelated settings or reading disk again."""
    return copy.deepcopy(_cached_defaults()[section][key])
