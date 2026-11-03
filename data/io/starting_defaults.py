"""Read editable distribution defaults without starting the game engines."""

import copy
from functools import lru_cache
import json
from pathlib import Path


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


def read_starting_defaults(path=_DEFAULT_PATH):
    """Read release preferences. Reject invalid sections before packaging."""
    with open(path, encoding="utf-8") as stream:
        defaults = json.load(stream)
    if not isinstance(defaults, dict) or set(defaults) != set(_FILE_TYPES):
        raise ValueError(f"{path}: use these sections: {', '.join(_FILE_TYPES)}")
    for name, expected_type in _FILE_TYPES.items():
        if not isinstance(defaults[name], expected_type):
            raise ValueError(f"{path}: {name} must contain a JSON {expected_type.__name__}")
    return defaults


@lru_cache(maxsize=1)
def _cached_defaults():
    # Startup sets the game folder as the working directory for frozen builds.
    # Editable files remain there, outside the executable's temporary archive.
    return read_starting_defaults(STARTING_DEFAULTS_PATH)


def get_starting_default(filename):
    """Return an independent preference value. Restart after external edits."""
    return copy.deepcopy(_cached_defaults()[filename])
