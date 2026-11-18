import os
import pygame
import data.constants as c
from data import migrations, queries
from data.io import settings_schema, starting_defaults

CONFIG_PATH = c.SETTINGS_CONFIG_PATH

# The positional writer stopped at show_tactical_intro_popup. Its earlier
# tutorial slot supplied both modes, so keep the old name for that slot.
_LEGACY_POSITIONAL_SETTINGS = tuple(
    "show_intro_popup" if name == "show_strategic_intro_popup" else name
    for name in settings_schema.SETTINGS_ORDER[2:settings_schema.SETTINGS_ORDER.index("show_tactical_intro_popup") + 1]
)


def save_settings(keybind_dict, sfx_volume, music_volume, *positional, **values):
    """Adapt older positional and keyword callers to the named writer."""
    unexpected = set(values) - set(settings_schema.SETTINGS_ORDER) - migrations.LEGACY_SETTINGS_KEYWORD_NAMES
    if unexpected:
        raise TypeError(f"Unknown settings arguments: {', '.join(sorted(unexpected))}")
    if len(positional) > len(_LEGACY_POSITIONAL_SETTINGS):
        raise TypeError("Too many positional settings arguments.")
    for name, value in zip(_LEGACY_POSITIONAL_SETTINGS, positional):
        if name in values:
            raise TypeError(f"Multiple values for settings argument {name!r}.")
        values[name] = value
    values.update(sfx_volume=sfx_volume, music_volume=music_volume)
    save_settings_values(keybind_dict, values)


def save_settings_values(keybind_dict, values):
    """Write keybinds and named settings using the current JSON schema."""
    # A missing current preference can still fall back to its legacy alias.
    nullable_aliases = migrations.LEGACY_SETTINGS_KEYWORD_NAMES - {"show_intro_popup"}
    values = {name: value for name, value in values.items()
              if value is not None or name in nullable_aliases}

    # ``None`` is an intentional, persistent "unassigned" binding.  Omitting
    # it would make load restore the action's default, which prevents players
    # from clearing an existing default keybind.
    data_to_save = {"keybinds": {action: (pygame.key.name(code)
                                             if code is not None else None)
                                 for action, code in keybind_dict.items()}}
    data_to_save.update(settings_schema.to_json_dict(values))
    queries.save_cached_json("settings", data_to_save)


def default_keybind(action):
    """Return a configured pygame key code, including an unassigned None."""
    name = starting_defaults.get_starting_value("settings_config.json", "keybinds")[action]
    return pygame.key.key_code(name) if name is not None else None


def default_keybinds():
    """Return independent keyboard defaults for startup and reset controls."""
    names = starting_defaults.get_starting_value("settings_config.json", "keybinds")
    return {action: pygame.key.key_code(name) if name is not None else None
            for action, name in names.items()}


def _load_keybinds(saved_data, default_binds):
    """Key names back to pygame codes, with any action missing from the file
    left at its default."""
    # Older files can be a bare binding map. A partial settings dictionary
    # without "keybinds" must not interpret volume/model values as key names.
    saved_binds = (saved_data.get("keybinds", {}) if "keybinds" in saved_data else
                   {action: name for action, name in saved_data.items() if action in default_binds})
    binds = dict(default_binds)
    for action, key_name in saved_binds.items():
        if key_name is None:
            binds[action] = None
            continue
        # Deliberately unguarded: an unparseable key name propagates to
        # load_settings' handler, which falls back to defaults for the whole
        # file. Preserved from the original -- treating a corrupt keybind as
        # "this settings file is not trustworthy" is a judgement call, not an
        # accident, so it is not something to change while refactoring.
        binds[action] = pygame.key.key_code(key_name)
    return binds


def load_settings_result(default_binds, default_volume=None, default_music_volume=None):
    """Load named settings and retain caller volume defaults and keybind behavior."""
    fallback = settings_schema.defaults()
    if default_volume is None:
        default_volume = fallback["sfx_volume"]
    if default_music_volume is None:
        default_music_volume = fallback["music_volume"]
    fallback["sfx_volume"] = default_volume
    fallback["music_volume"] = default_music_volume

    try:
        saved_data = (queries.get_settings() if os.path.exists(CONFIG_PATH)
                      else starting_defaults.get_starting_default("settings_config.json"))
        saved_data = saved_data if isinstance(saved_data, dict) else {}

        values = settings_schema.from_json_dict(saved_data)
        # The two volumes fall back to the caller's arguments rather than the
        # schema defaults -- a settings file that predates them, or one that is
        # a bare keybind map, must not reset the player's audio to full.
        if "sfx_volume" not in saved_data:
            values["sfx_volume"] = default_volume
        if "music_volume" not in saved_data:
            values["music_volume"] = default_music_volume

        return settings_schema.SettingsLoadResult(_load_keybinds(saved_data, default_binds), values)
    except Exception as e:
        print(f"Error loading settings: {e}")
        return settings_schema.SettingsLoadResult(dict(default_binds), fallback)


def load_settings(default_binds, default_volume=None, default_music_volume=None):
    """Preserve the positional interface for older callers."""
    return load_settings_result(default_binds, default_volume, default_music_volume).as_tuple()
