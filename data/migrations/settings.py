"""Older settings names and mouse-button controls.

Current settings fields and defaults stay in data/io/settings_schema.py.
"""


SETTING_ALIASES = {
    "show_strategic_intro_popup": ("show_intro_popup",),
    "show_tactical_intro_popup": ("show_intro_popup",),
    "gemini_api_key": ("api_key",),
    "ollama_base_url": ("ollama_api_key",),
    "music_pitch": ("music_speed",),
    "sfx_pitch": ("sfx_speed",),
    "openrouter_api_key": ("ling_api_key",),
    "openrouter_model": ("ling_model",),
}


LEGACY_SETTINGS_KEYWORD_NAMES = frozenset(
    alias for key in ("ollama_base_url", "openrouter_api_key", "openrouter_model", "show_strategic_intro_popup")
    for alias in SETTING_ALIASES[key])


def setting_keys(name):
    """Return the current key first, followed by supported older keys."""
    return (name,) + SETTING_ALIASES.get(name, ())


def read_setting_value(saved, name):
    """Read a saved value. A current key takes priority, including an empty value."""
    return next((saved[key] for key in setting_keys(name) if key in saved), None)


def controller_setting_values(controller, names):
    """Read current or older attributes from controllers and lightweight test doubles."""
    return {key: getattr(controller, key)
            for name in names for key in setting_keys(name)
            if hasattr(controller, key)}


def normalize_ai_mode(value):
    """Read the older provider ID as OpenRouter."""
    return "OPENROUTER" if value == "LING" else value


def migrate_setting_names(saved):
    """Update cached names in place. Keep unrelated and unknown settings."""
    for name, aliases in SETTING_ALIASES.items():
        for old_key in aliases:
            if old_key in saved:
                saved.setdefault(name, saved[old_key])
    # One older preference can supply both mode-specific tutorial preferences.
    for aliases in SETTING_ALIASES.values():
        for old_key in aliases:
            saved.pop(old_key, None)
    if "ai_mode" in saved:
        saved["ai_mode"] = normalize_ai_mode(saved["ai_mode"])
    return saved


def migrate_mouse_button_actions(value):
    """Convert older pan controls without changing the caller's mapping."""
    # pan_map_outside_orders was the first saved form of Pan + Exclude Orders.
    # An explicit current checkbox takes priority when both fields exist.
    if not isinstance(value, dict):
        return value
    result = dict(value)
    for button, actions in value.items():
        if not isinstance(actions, dict):
            continue
        legacy = actions.get("pan_map_outside_orders")
        if isinstance(legacy, bool) and "exclude_orders" not in actions:
            result[button] = dict(actions, exclude_orders=legacy)
            if legacy:
                result[button]["pan_map"] = True
    return result
