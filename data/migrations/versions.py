"""Game version stamps, the version steps, and the conversion entry points.

The game version is the save version. Each version step converts all older data
to the format of one game version. See documentation/data_migrations.txt.
Register each new version's steps in SAVE_STEPS and MOVE_STEPS at the end of this file.
"""

import re

import data.constants as c
from data.migrations import v47


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
    """Convert one loaded save to the current version in place.

    save_meta is meta.json, map_data is map_data.json by JSON key, and history
    holds the decoded turn snapshots. A selected history turn becomes live
    state, so every step also converts every snapshot. Return the saved version.
    """
    version = check_version(save_meta.get("version"))
    for target, step in SAVE_STEPS:
        if version < target:
            step(save_meta, map_data, history)
    save_meta["version"] = c.GAME_VERSION
    return version


#: Move files gained game_version after v46. An unstamped move is from v46 or earlier.
#: v46 is also the oldest move version that converts, because older moves lack the v46 sections.
LAST_UNSTAMPED_VERSION = 46


def move_version(player_data):
    """Return a move's version number. Refuse a move that no step can convert.

    Moves from v46 and every later release convert. MOVE_STEPS run in order.
    """
    version = (check_version(player_data["game_version"], "This move")
               if "game_version" in player_data else LAST_UNSTAMPED_VERSION)
    if version < LAST_UNSTAMPED_VERSION:
        raise ValueError(
            f"This move was made with a game version older than v{LAST_UNSTAMPED_VERSION}. "
            f"The player must update to {c.GAME_VERSION} and export the move again.")
    return version


def upgrade_move(player_data):
    """Convert a move file from any supported older release in place.

    A move from several releases ago runs every step newer than its version.
    The host approves each converted move. The move then passes normal validation.
    """
    version = move_version(player_data)
    for target, step in MOVE_STEPS:
        if version < target:
            step(player_data)
    player_data["game_version"] = c.GAME_VERSION
    return version


SAVE_STEPS = ((47, v47.convert_save),)


MOVE_STEPS = ((47, v47.convert_move),)
