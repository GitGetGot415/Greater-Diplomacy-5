import os
import pygame
import data.constants as c
from data import queries
from data.io import settings_schema

CONFIG_PATH = c.SETTINGS_CONFIG_PATH

def save_settings(keybind_dict, sfx_volume, music_volume, num_players=1, ai_mode="GEMINI",
                  gemini_api_key="", chatgpt_api_key="", claude_api_key="", ollama_api_key="",
                  gemini_model="", chatgpt_model="", claude_model="", ollama_model="",
                  ai_immersion_level="LITE", music_pitch=0.5, sfx_pitch=0.5, target_fps=60,
                  ai_threads=1, show_fps=True, drag_mouse_toggle="RIGHT",
                  saves_dir=c.DEFAULT_SAVES_DIR, custom_scenarios_dir=c.DEFAULT_SCENARIOS_CUSTOM_DIR,
                  ocean_light_color=c.DEFAULT_OCEAN_LIGHT_BLUE, ocean_dark_color=c.DEFAULT_OCEAN_DARK_BLUE,
                  tournament_saves_dir=c.DEFAULT_TOURNAMENT_SAVES_DIR, checkerboard_water=c.CHECKERBOARD_WATER,
                  deepseek_api_key="", kimi_api_key="",
                  deepseek_model=c.DEFAULT_DEEPSEEK_MODEL, kimi_model=c.DEFAULT_KIMI_MODEL,
                  ai_turn_budget_seconds=c.DEFAULT_AI_TURN_BUDGET_SECONDS,
                  unit_art_style=c.DEFAULT_UNIT_ART_STYLE,
                  map_navigation_mode=c.DEFAULT_MAP_NAVIGATION_MODE,
                  orders_key_changes_screen=True, economy_key_changes_screen=True):
    """Converts key codes to strings and saves all config data to JSON.

    The explicit signature is kept -- callers (and any mod) pass these
    positionally -- but the body no longer restates the schema: the JSON keys
    come from settings_schema.SETTINGS_FIELDS.
    """
    values = {name: value for name, value in locals().items()
              if name in settings_schema.SETTINGS_ORDER}

    data_to_save = {"keybinds": {action: pygame.key.name(code)
                                 for action, code in keybind_dict.items()}}
    data_to_save.update(settings_schema.to_json_dict(values))
    queries.save_cached_json("settings", data_to_save)


def _load_keybinds(saved_data, default_binds):
    """Key names back to pygame codes, with any action missing from the file
    left at its default."""
    saved_binds = saved_data if "keybinds" not in saved_data else saved_data.get("keybinds", {})
    binds = dict(default_binds)
    for action, key_name in saved_binds.items():
        # Deliberately unguarded: an unparseable key name propagates to
        # load_settings' handler, which falls back to defaults for the whole
        # file. Preserved from the original -- treating a corrupt keybind as
        # "this settings file is not trustworthy" is a judgement call, not an
        # accident, so it is not something to change while refactoring.
        binds[action] = pygame.key.key_code(key_name)
    return binds


def load_settings(default_binds, default_volume=0.5, default_music_volume=0.5):
    """Loads all settings, falling back to defaults for anything missing.

    Returns the same positional tuple it always has -- keybinds first, then
    settings_schema.SETTINGS_FIELDS in order -- because main.py unpacks it by
    index. The order lives in one place now instead of five.
    """
    fallback = settings_schema.defaults()
    fallback["sfx_volume"] = default_volume
    fallback["music_volume"] = default_music_volume

    if not os.path.exists(CONFIG_PATH):
        return settings_schema.to_tuple(fallback, default_binds)

    try:
        saved_data = queries.get_settings()
        saved_data = saved_data if isinstance(saved_data, dict) else {}

        values = settings_schema.from_json_dict(saved_data)
        # The two volumes fall back to the caller's arguments rather than the
        # schema defaults -- a settings file that predates them, or one that is
        # a bare keybind map, must not reset the player's audio to full.
        if "sfx_volume" not in saved_data:
            values["sfx_volume"] = default_volume
        if "music_volume" not in saved_data:
            values["music_volume"] = default_music_volume

        return settings_schema.to_tuple(values, _load_keybinds(saved_data, default_binds))
    except Exception as e:
        print(f"Error loading settings: {e}")
        return settings_schema.to_tuple(fallback, default_binds)
