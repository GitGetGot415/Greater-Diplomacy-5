"""One declaration of what a saved setting is.

The settings schema used to be written out five times in parallel: as
save_settings' 26-parameter signature, as the dict it builds, twice more as
fallback tuples, and once more as load_settings' 26-element return -- plus the
25 positional attribute reads in queries.save_global_settings and the
`len(loaded_data) > N` ladder in main.py that unpacks it again. Adding one
setting meant editing seven places in lockstep, and getting the order wrong
anywhere silently mixed up unrelated settings.

Two contracts have to survive, and both are now derived from SETTINGS_FIELDS
rather than restated:

- the JSON key set written to data/json/settings_config.json
- the positional order of load_settings' return, which main.py unpacks by index

Keybinds are not in the table: they need the caller's defaults and a round trip
through pygame key names, so they stay explicit in keybind_io.

Kept a leaf -- data.constants only -- so it can be imported from anywhere.
"""

from collections import namedtuple

import data.constants as c

#: name    -- the attribute name on Controller, and the key in the values dict
#: json_key-- what it is called on disk
#: default -- a zero-argument callable; several defaults live on data.constants
#:            and are overwritten at runtime, so they must be read when asked
#:            for rather than captured at import
#: coerce  -- applied to whatever comes off disk (JSON has no tuples)
#: legacy  -- older key names still found in players' settings files
SettingField = namedtuple("SettingField", "name json_key default coerce legacy")


def _field(name, json_key, default, coerce=None, legacy=()):
    return SettingField(name, json_key, default, coerce, legacy)


# ORDER IS THE PERSISTED CONTRACT. main.py unpacks load_settings' return by
# index, so appending is safe and reordering is not.
SETTINGS_FIELDS = (
    _field("sfx_volume", "sfx_volume", lambda: c.DEFAULT_SFX_VOLUME),
    _field("music_volume", "music_volume", lambda: c.DEFAULT_MUSIC_VOLUME),
    _field("num_players", "num_players", lambda: 1),
    _field("ai_mode", "ai_mode", lambda: c.DEFAULT_AI_MODE),
    _field("gemini_api_key", "gemini_api_key", lambda: "", legacy=("api_key",)),
    _field("chatgpt_api_key", "chatgpt_api_key", lambda: ""),
    _field("claude_api_key", "claude_api_key", lambda: ""),
    _field("ollama_api_key", "ollama_api_key", lambda: ""),
    _field("gemini_model", "gemini_model", lambda: c.DEFAULT_GEMINI_MODEL),
    _field("chatgpt_model", "chatgpt_model", lambda: c.DEFAULT_CHATGPT_MODEL),
    _field("claude_model", "claude_model", lambda: c.DEFAULT_CLAUDE_MODEL),
    _field("ollama_model", "ollama_model", lambda: c.DEFAULT_OLLAMA_MODEL),
    _field("ai_immersion_level", "ai_immersion_level", lambda: "LITE"),
    _field("music_pitch", "music_pitch", lambda: c.DEFAULT_AUDIO_PITCH, legacy=("music_speed",)),
    _field("sfx_pitch", "sfx_pitch", lambda: c.DEFAULT_AUDIO_PITCH, legacy=("sfx_speed",)),
    _field("target_fps", "target_fps", lambda: c.TARGET_FPS),
    _field("ai_threads", "ai_threads", lambda: c.DEFAULT_AI_THREADS),
    _field("show_fps", "show_fps", lambda: c.SHOW_FPS),
    _field("drag_mouse_toggle", "drag_mouse_toggle", lambda: c.DRAG_MOUSE_BUTTON_TOGGLE),
    _field("saves_dir", "saves_dir", lambda: c.DEFAULT_SAVES_DIR),
    _field("custom_scenarios_dir", "custom_scenarios_dir",
           lambda: c.DEFAULT_SCENARIOS_CUSTOM_DIR),
    _field("ocean_light_color", "ocean_light_color",
           lambda: c.DEFAULT_OCEAN_LIGHT_BLUE, coerce=tuple),
    _field("ocean_dark_color", "ocean_dark_color",
           lambda: c.DEFAULT_OCEAN_DARK_BLUE, coerce=tuple),
    _field("tournament_saves_dir", "tournament_saves_dir",
           lambda: c.DEFAULT_TOURNAMENT_SAVES_DIR),
    _field("checkerboard_water", "checkerboard_water", lambda: c.CHECKERBOARD_WATER),
    _field("deepseek_api_key", "deepseek_api_key", lambda: ""),
    _field("kimi_api_key", "kimi_api_key", lambda: ""),
    _field("deepseek_model", "deepseek_model", lambda: c.DEFAULT_DEEPSEEK_MODEL),
    _field("kimi_model", "kimi_model", lambda: c.DEFAULT_KIMI_MODEL),
    _field("ai_turn_budget_seconds", "ai_turn_budget_seconds",
           lambda: c.DEFAULT_AI_TURN_BUDGET_SECONDS),
    _field("unit_art_style", "unit_art_style", lambda: c.DEFAULT_UNIT_ART_STYLE),
    _field("map_navigation_mode", "map_navigation_mode", lambda: c.DEFAULT_MAP_NAVIGATION_MODE),
    # Per-keybind "change screen with this keybind" toggle next to the Orders/
    # Production rows on the Keybinds screen -- independent of
    # map_navigation_mode, see ui.event_handler.handle_view_mode_keybind.
    # On by default, and Keybinds' "Reset Keybinds" restores that.
    _field("orders_key_changes_screen", "orders_key_changes_screen", lambda: True),
    _field("economy_key_changes_screen", "economy_key_changes_screen", lambda: True),
)

SETTINGS_ORDER = tuple(field.name for field in SETTINGS_FIELDS)

#: load_settings returns keybinds first, then SETTINGS_FIELDS in order.
TUPLE_LENGTH = len(SETTINGS_FIELDS) + 1


def defaults():
    """Every setting at its shipped value."""
    return {field.name: field.default() for field in SETTINGS_FIELDS}


def to_json_dict(values):
    """The on-disk shape, minus keybinds (keybind_io adds those)."""
    filled = defaults()
    filled.update({k: v for k, v in values.items() if k in filled})
    return {field.json_key: filled[field.name] for field in SETTINGS_FIELDS}


def from_json_dict(saved):
    """Reads a settings file, honouring legacy key names and coercions."""
    saved = saved if isinstance(saved, dict) else {}
    values = {}
    for field in SETTINGS_FIELDS:
        if field.json_key in saved:
            raw = saved[field.json_key]
        else:
            raw = next((saved[key] for key in field.legacy if key in saved), None)
        if raw is None:
            values[field.name] = field.default()
        else:
            values[field.name] = field.coerce(raw) if field.coerce else raw
    return values


def to_tuple(values, keybinds):
    """The positional form load_settings has always returned."""
    filled = defaults()
    filled.update({k: v for k, v in values.items() if k in filled})
    return (keybinds,) + tuple(filled[field.name] for field in SETTINGS_FIELDS)


def from_tuple(sequence):
    """Unpacks that positional form, tolerating one saved by an older build.

    Anything the sequence is too short to carry falls back to its default,
    which is what main.py's chain of `len(loaded_data) > N` guards did by hand.
    """
    values = defaults()
    for index, field in enumerate(SETTINGS_FIELDS, start=1):
        if index < len(sequence):
            values[field.name] = sequence[index]
    return values


def from_controller(controller):
    """Reads the live settings back off the Controller."""
    return {field.name: getattr(controller, field.name, field.default())
            for field in SETTINGS_FIELDS}


def apply_to_controller(controller, values):
    """Writes settings onto the Controller under their canonical names."""
    filled = defaults()
    filled.update({k: v for k, v in values.items() if k in filled})
    for field in SETTINGS_FIELDS:
        setattr(controller, field.name, filled[field.name])
    return filled
