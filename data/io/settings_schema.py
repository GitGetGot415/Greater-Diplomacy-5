"""Define setting names, defaults, and current-value conversions in one table.

Writers use current names. Readers accept older names.
Current keys take priority when both names exist.
The positional settings order is a compatibility contract. Do not reorder it.
main.py applies the returned settings through this schema.

Keybinds use the caller's defaults and pygame key names in keybind_io.
Older names and their conversion rules belong to data.migrations.
"""

from collections import namedtuple
from dataclasses import dataclass

import data.constants as c
from data import migrations
# Preserve older imports. The rules have one owner in data.migrations.
from data.migrations import migrate_setting_names, normalize_ai_mode

#: name    -- the attribute name on Controller, and the key in the values dict
#: json_key-- what it is called on disk
#: default -- a zero-argument callable; several defaults live on data.constants
#:            and are overwritten at runtime, so they must be read when asked
#:            for rather than captured at import
#: coerce  -- applied to whatever comes off disk (JSON has no tuples)
#: legacy  -- older key names still found in players' settings files
SettingField = namedtuple("SettingField", "name json_key default coerce legacy")


def _field(name, json_key, default, coerce=None):
    return SettingField(name, json_key, default, coerce, migrations.setting_keys(json_key)[1:])


def _coerce_music_pitch_timeline(value):
    """Keep malformed or future timeline settings safe at the static default."""
    if value in (c.MUSIC_PITCH_TIMELINE_STATIC, c.MUSIC_PITCH_TIMELINE_DYNAMIC):
        return value
    return c.DEFAULT_MUSIC_PITCH_TIMELINE


# Keep positional compatibility for older callers. JSON settings use named keys.
SETTINGS_FIELDS = (
    _field("sfx_volume", "sfx_volume", lambda: c.DEFAULT_SFX_VOLUME),
    _field("music_volume", "music_volume", lambda: c.DEFAULT_MUSIC_VOLUME),
    _field("num_players", "num_players", lambda: 1),
    _field("ai_mode", "ai_mode", lambda: c.DEFAULT_AI_MODE, coerce=normalize_ai_mode),
    _field("gemini_api_key", "gemini_api_key", lambda: ""),
    _field("chatgpt_api_key", "chatgpt_api_key", lambda: ""),
    _field("claude_api_key", "claude_api_key", lambda: ""),
    _field("ollama_base_url", "ollama_base_url", lambda: ""),
    _field("gemini_model", "gemini_model", lambda: c.DEFAULT_GEMINI_MODEL),
    _field("chatgpt_model", "chatgpt_model", lambda: c.DEFAULT_CHATGPT_MODEL),
    _field("claude_model", "claude_model", lambda: c.DEFAULT_CLAUDE_MODEL),
    _field("ollama_model", "ollama_model", lambda: c.DEFAULT_OLLAMA_MODEL),
    _field("ai_immersion_level", "ai_immersion_level", lambda: "LITE"),
    _field("music_pitch", "music_pitch", lambda: c.DEFAULT_AUDIO_PITCH),
    _field("sfx_pitch", "sfx_pitch", lambda: c.DEFAULT_AUDIO_PITCH),
    _field("target_fps", "target_fps", lambda: c.TARGET_FPS),
    _field("ai_threads", "ai_threads", lambda: c.DEFAULT_AI_THREADS),
    _field("show_fps", "show_fps", lambda: c.SHOW_FPS),
    _field("show_intro_popup", "show_intro_popup", lambda: True),
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
    # map_navigation_mode, see screens.game.map_input.handle_view_mode_keybind.
    # On by default, and Keybinds' "Reset Keybinds" restores that.
    _field("orders_key_changes_screen", "orders_key_changes_screen", lambda: True),
    _field("economy_key_changes_screen", "economy_key_changes_screen", lambda: True),
    _field("battle_display_mode", "battle_display_mode", lambda: c.DEFAULT_BATTLE_DISPLAY_MODE),
    _field("mouse_button_actions", "mouse_button_actions",
           c.default_mouse_button_actions, coerce=c.normalize_mouse_button_actions),
    _field("army_group_animations", "army_group_animations",
           lambda: c.DEFAULT_ARMY_GROUP_ANIMATIONS),
    _field("music_pitch_timeline", "music_pitch_timeline",
           lambda: c.DEFAULT_MUSIC_PITCH_TIMELINE,
           coerce=_coerce_music_pitch_timeline),
    _field("show_unclaimed", "show_unclaimed", lambda: c.DEFAULT_SHOW_UNCLAIMED),
    _field("openrouter_api_key", "openrouter_api_key", lambda: ""),
    _field("openrouter_model", "openrouter_model", lambda: c.DEFAULT_OPENROUTER_MODEL),
)

SETTINGS_ORDER = tuple(field.name for field in SETTINGS_FIELDS)

#: The legacy tuple adapter returns keybinds before the ordered settings.
TUPLE_LENGTH = len(SETTINGS_FIELDS) + 1

_FIELDS_BY_NAME = {field.name: field for field in SETTINGS_FIELDS}


def read_setting(saved, name, default=None):
    """Read one setting. A current key takes priority over an older key."""
    field = _FIELDS_BY_NAME[name]
    raw = migrations.read_setting_value(saved, field.json_key)
    if raw is None:
        return field.default() if default is None else default
    return field.coerce(raw) if field.coerce else raw


def defaults():
    """Every setting at its shipped value."""
    return {field.name: field.default() for field in SETTINGS_FIELDS}


def _filled_values(values):
    """Fill missing runtime values without applying file-load conversions."""
    current = migrate_setting_names(dict(values))
    filled = defaults()
    filled.update({key: value for key, value in current.items() if key in filled})
    return filled


def to_json_dict(values):
    """The on-disk shape, minus keybinds (keybind_io adds those)."""
    filled = _filled_values(values)
    return {field.json_key: filled[field.name] for field in SETTINGS_FIELDS}


def from_json_dict(saved):
    """Reads a settings file, honouring legacy key names and coercions."""
    saved = saved if isinstance(saved, dict) else {}
    return {field.name: read_setting(saved, field.name) for field in SETTINGS_FIELDS}


def to_tuple(values, keybinds):
    """The positional form load_settings has always returned."""
    filled = _filled_values(values)
    return (keybinds,) + tuple(filled[field.name] for field in SETTINGS_FIELDS)


def from_tuple(sequence):
    """Accept shorter positional results from older callers and fill missing defaults."""
    values = defaults()
    for index, field in enumerate(SETTINGS_FIELDS, start=1):
        if index < len(sequence):
            values[field.name] = sequence[index]
    return _filled_values(values)


def from_controller(controller):
    """Reads the live settings back off the Controller."""
    # Older controllers and lightweight test doubles can still have legacy attributes.
    saved = migrations.controller_setting_values(controller, SETTINGS_ORDER)
    return _filled_values(saved)


def apply_to_controller(controller, values):
    """Writes settings onto the Controller under their canonical names."""
    filled = _filled_values(values)
    for field in SETTINGS_FIELDS:
        setattr(controller, field.name, filled[field.name])
    return filled


@dataclass(frozen=True)
class SettingsLoadResult:
    """Return keybinds and schema-normalized values without positional conversion."""
    keybinds: dict
    values: dict

    def as_tuple(self):
        return to_tuple(self.values, self.keybinds)
