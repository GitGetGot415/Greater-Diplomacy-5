"""Game version stamps and the conversion entry points.

The version stamp records which game wrote a file. It refuses files from a newer game,
matches real-time players, and tells a tournament host that a move needs approval.
Conversion never depends on it. Every rule in conversions.py runs on every load.
See data/migrations/MIGRATIONS.md.
"""

import re

import data.constants as c
from data.migrations import conversions


class NewerVersionError(ValueError):
    """Data from a newer game version. Only an update can read it."""


def version_number(version):
    """Read "v46" as 46. Data from before version stamps reads as 0."""
    if isinstance(version, str):
        match = re.fullmatch(r"v(\d+)", version.strip())
        if match:
            return int(match.group(1))
    return 0


CURRENT_VERSION = version_number(c.GAME_VERSION)


def check_version(version, subject="This save"):
    """Return the version number. Refuse data that a newer game wrote."""
    number = version_number(version)
    if number > CURRENT_VERSION:
        raise NewerVersionError(
            f"{subject} was made with game version {version}. "
            f"This game is version {c.GAME_VERSION}. Update the game to open it.")
    return number


def upgrade_save(save_meta, map_data, history):
    """Convert one loaded save to the current format in place.

    save_meta is meta.json, map_data is map_data.json by JSON key, and history
    holds the decoded turn snapshots. Every conversion rule runs, whatever version
    wrote the save. Return the saved version number.
    """
    version = check_version(save_meta.get("version"))
    conversions.convert_save(save_meta, map_data, history)
    save_meta["version"] = c.GAME_VERSION
    return version


def move_version(player_data):
    """Return a move's version number, or 0 for an unstamped move. Refuse a newer move."""
    return check_version(player_data.get("game_version"), "This move")


def upgrade_move(player_data):
    """Convert a tournament move to the current format in place.

    Every conversion rule runs, whatever version wrote the move. The host approves
    a move from another version first. The move then passes normal validation.
    """
    version = move_version(player_data)
    conversions.convert_move(player_data)
    player_data["game_version"] = c.GAME_VERSION
    return version
