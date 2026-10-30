"""Load cached research presentation settings without initializing the UI."""

from functools import lru_cache
import json
import math


CONFIG_PATH = "data/json/research_display.json"


def _positive(value, location):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or value <= 0):
        raise ValueError(f"{location} must be a finite number greater than zero.")


def button_dimensions(size, config=None):
    """Resolve a named preset or an explicit pixel pair."""
    if config is None:
        config = get_config()
    if isinstance(size, str):
        if size not in config["button_sizes"]:
            raise ValueError(f"Unknown research button_size {size!r}; add it to button_sizes.")
        size = config["button_sizes"][size]
    if not isinstance(size, (tuple, list)) or len(size) != 2:
        raise ValueError("Research button_size must name a preset or contain [width, height].")
    for value in size:
        _positive(value, "Research button dimension")
        if int(value) != value:
            raise ValueError("Research button dimensions must be whole pixels.")
    return tuple(int(value) for value in size)


def _validate_settings(settings, config):
    if not isinstance(settings, dict):
        raise ValueError("Research display settings must be JSON objects.")
    if "button_size" in settings:
        button_dimensions(settings["button_size"], config)
    for field in ("icon_scale", "large_icon_scale"):
        if field in settings:
            _positive(settings[field], field)


@lru_cache(maxsize=None)
def get_config(path=CONFIG_PATH):
    """Read settings once per path. Restart the game after file edits."""
    try:
        with open(path, encoding="utf-8") as source:
            config = json.load(source)
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Cannot load {path}. Correct the research display file: {error}") from error

    try:
        for size in config["button_sizes"].values():
            if not isinstance(size, list):
                raise ValueError("button_sizes presets must contain [width, height] pixel pairs.")
            button_dimensions(size, config)
        _validate_settings(config["defaults"], config)
        for field in ("button_size", "icon_scale", "large_icon_scale"):
            config["defaults"][field]
        for settings in config.get("categories", {}).values():
            _validate_settings(settings, config)
        for settings in config.get("technologies", {}).values():
            _validate_settings(settings, config)
            for level in settings.get("levels", {}).values():
                _validate_settings(level, config)
        layout = config["layout"]
        if len(layout["row_y"]) != 6:
            raise ValueError("layout.row_y must contain six row positions.")
        for value in layout["row_y"]:
            _positive(value, "layout.row_y")
        for field in ("default_row_y", "row_center_offset", "pixels_per_year", "modal_icon_box"):
            _positive(layout[field], f"layout.{field}")
        for tech_key, settings in config.get("technologies", {}).items():
            if settings.get("row", 1) not in range(1, len(layout["row_y"]) + 1):
                raise ValueError(f"{tech_key} row must name a position in layout.row_y.")
        for style in config.get("styles", {}).values():
            _positive(style.get("button_scale", 1.0), "style.button_scale")
            for scale in style.get("icon_scales", {}).values():
                _positive(scale, "style.icon_scales")
            for override in style.get("button_scale_overrides", {}).values():
                for field in ("width", "height"):
                    _positive(override.get(field, 1.0), f"style.{field}")
    except (KeyError, TypeError, AttributeError, ValueError) as error:
        raise ValueError(f"Invalid {path}: {error}") from error
    return config


def technology_row_y(tech_key):
    """Return the screen row for a technology. Technologies without a row use the default row."""
    config = get_config()
    layout = config["layout"]
    row = config.get("technologies", {}).get(tech_key, {}).get("row")
    return layout["default_row_y"] if row is None else layout["row_y"][row - 1]


def node_settings(tech_key, category, level, *, large_icon=False):
    """Apply defaults, category, technology, then exact-level settings."""
    config = get_config()
    settings = dict(config["defaults"])
    if large_icon:
        settings["icon_scale"] = settings["large_icon_scale"]
    settings.update(config.get("categories", {}).get(category, {}))
    technology = config.get("technologies", {}).get(tech_key, {})
    settings.update({key: value for key, value in technology.items() if key not in ("levels", "row")})
    settings.update(technology.get("levels", {}).get(str(level), {}))
    return settings
