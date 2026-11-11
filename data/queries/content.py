"""Cached game content and settings: JSON cache, libraries, scenario flags, settings, keybinds, music choices, and historical leader timelines."""

import re
from data.platform import CHARACTERS_DIR, CUSTOM_SUBDIR
import data.constants as c
import json
import os
import pygame
from data.state_access import world_for
from data.migrations import convert_scenario_settings, normalize_cached_json_names
from data.runtime_rules import rebuild, ActiveLibrary, for_world
from data.io import settings_schema, starting_defaults
from data import queries


# By mapping the path directly to the cache, we can automate loading and saving!
_JSON_CACHE = {
    "settings": {"path": c.SETTINGS_CONFIG_PATH, "data": None, "default": "settings_config.json"},
    "scenario_settings": {"path": "data/json/scenario_settings.json", "data": None, "default": "scenario_settings.json"},
    "unit_library": {"path": c.UNIT_DATA_PATH, "data": None},
    "building_library": {"path": c.BUILDING_DATA_PATH, "data": None},
    "tech_tree": {"path": c.RESEARCH_TEMPLATE_PATH, "data": None},
    "country_data": {"path": c.COUNTRIES_DATA_PATH, "data": None},
    "active_albums": {"path": c.ACTIVE_ALBUMS_PATH, "data": None, "default": "active_albums.json"},
    "shuffle_disabled_tracks": {"path": c.SHUFFLE_DISABLED_TRACKS_PATH, "data": None, "default": "shuffle_disabled_tracks.json"},
    "starting_song": {"path": c.STARTING_SONG_PATH, "data": None, "default": "starting_song.json"},
    "hildehrand_choice": {"path": c.HILDEHRAND_CHOICE_PATH, "data": None, "default": "hildehrand_choice.json"},
    "historical_leaders": {"path": c.HISTORICAL_LEADERS_PATH, "data": None},
    "ai_responses": {"path": c.AI_RESPONSES_PATH, "data": None},
}


def scenario_has_scripted_events(nation_data):
    """Checks if any nation in the scenario has scripted events."""
    for data in nation_data.values():
        if isinstance(data, dict) and data.get("scripted_events"):
            return True
    return False


def get_scenario_flag(flag_name, default=False, scenario_settings=None):
    """Safely resolves a boolean scenario setting from a settings dict.

    The single reader for every on/off scenario rule. Saves written by older
    builds store these as the strings "True"/"False" rather than JSON booleans,
    so both spellings have to resolve the same way -- doing that in one place is
    why no caller should hand-roll `str(x).lower() == "true"` again.

    Pass `scenario_settings` when a screen or map holds its own copy; omitting
    it falls back to the globally cached scenario_settings.json.
    """
    if scenario_settings is None:
        scenario_settings = queries.get_scenario_settings()

    if scenario_settings is None:
        return default

    value = scenario_settings.get(flag_name, default)
    if isinstance(value, str):
        return value.lower() == "true"
    return bool(value)


# Scenario flags that are mirrored onto live constants so gameplay code can read
# them without threading a settings dict everywhere: {setting key: (constant, default)}.
GLOBAL_SCENARIO_FLAGS = {
    "fog_of_war": ("USE_FOG_OF_WAR", c.DEFAULT_FOG_OF_WAR),
    "casus_belli_required": ("CASUS_BELLI_REQUIRED", c.DEFAULT_CASUS_BELLI),
    "battle_royale": ("BATTLE_ROYALE_MODE", c.DEFAULT_BATTLE_ROYALE),
    "disable_factions": ("DISABLE_FACTIONS", c.DEFAULT_DISABLE_FACTIONS),
    "disable_cores": ("DISABLE_CORES", c.DEFAULT_DISABLE_CORES),
}


# Same idea for numeric scenario settings: {setting key: (constant, default, cast)}.
GLOBAL_SCENARIO_VALUES = {
    "damage_at_zero_health": ("DAMAGE_AT_ZERO_HEALTH", c.DAMAGE_AT_ZERO_HEALTH, float),
    "defense_at_zero_health": ("DEFENSE_AT_ZERO_HEALTH", c.DEFENSE_AT_ZERO_HEALTH, float),
    "truce_turns": ("TRUCE_TURNS", c.DEFAULT_TRUCE_TURNS, int),
}


def get_truce_turns(scenario_settings=None):
    """Returns the configured post-peace truce length within its legal range.

    Calls that do not have a map's scenario settings yet retain the live
    constant for compatibility with older diplomacy helpers and tests. Once a
    scenario settings dictionary is available, a missing field uses the
    configured starting default.
    """
    default = c.TRUCE_TURNS if scenario_settings is None else c.DEFAULT_TRUCE_TURNS
    raw = (scenario_settings or {}).get("truce_turns", default)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = default
    return max(c.MIN_TRUCE_TURNS, min(c.MAX_TRUCE_TURNS, value))


def world_truce_turns(nation_data):
    # Plain country dictionaries retain the supported no-world behavior.
    world = world_for(nation_data)
    return get_truce_turns(None if isinstance(world, dict) else world.scenario_settings)


def apply_global_scenario_flags(scenario_settings):
    """Preserve constant updates for older no-context callers.

    Active world loading and gameplay use explicit world settings instead.
    """
    for flag_name, (const_name, default) in GLOBAL_SCENARIO_FLAGS.items():
        setattr(c, const_name, queries.get_scenario_flag(flag_name, default, scenario_settings))

    for key, (const_name, default, cast) in GLOBAL_SCENARIO_VALUES.items():
        if key == "truce_turns":
            setattr(c, const_name, get_truce_turns(scenario_settings))
            continue
        raw = (scenario_settings or {}).get(key, default)
        try:
            setattr(c, const_name, cast(raw))
        except (TypeError, ValueError):
            setattr(c, const_name, default)


def toggle_scenario_flag(scenario_settings, flag_name, default=False):
    """Flips a scenario flag in-place, saves it, and returns the new value.

    Counterpart to get_scenario_flag, so the settings screens never have to
    re-derive the current value themselves before inverting it.
    """
    new_value = not queries.get_scenario_flag(flag_name, default, scenario_settings)
    scenario_settings[flag_name] = new_value
    queries.save_scenario_settings(scenario_settings)
    return new_value


#: The scenario settings that each Unit / Building Stats category owns.
EDITOR_CATEGORY_SETTINGS = {
    "units": ("unit_turn_overrides", "unit_disabled"),
    "buildings": ("building_stat_overrides", "building_turn_overrides", "building_disabled"),
    "range": ("unit_range_overrides",),
    "other": ("administrative_turn_overrides", "administrative_disabled", "conversion_turn_overrides"),
}

#: The Use Defaults setting of each category. On, the category uses the map's defaults.
USE_MAP_DEFAULTS_KEYS = {category: f"use_default_{category}" for category in EDITOR_CATEGORY_SETTINGS}

#: The map-owned block of default values, with the same setting names as the player's settings.
MAP_DEFAULTS_KEY = "map_defaults"

_SETTING_CATEGORIES = {key: category for category, keys in EDITOR_CATEGORY_SETTINGS.items() for key in keys}


def uses_map_defaults(settings, category):
    """True when a category uses the map's defaults instead of the player's values."""
    key = USE_MAP_DEFAULTS_KEYS[category]
    return get_scenario_flag(key, starting_defaults.get_starting_value("scenario_settings.json", key),
                             settings or {})


def get_category_setting(settings, key, default, *, map_editor=False):
    """Return the value of one editor setting that applies: the map's default or the player's value.

    The map editor always edits and shows the map's own defaults.
    A value that the map does not set uses `default`, which means the library value.
    """
    settings = settings or {}
    if map_editor or uses_map_defaults(settings, _SETTING_CATEGORIES[key]):
        settings = settings.get(MAP_DEFAULTS_KEY)
        if not isinstance(settings, dict):
            return default
    return settings.get(key, default)


def effective_scenario_settings(settings, *, map_editor=False):
    """Return a copy of settings whose editor settings hold the values that apply."""
    effective = dict(settings or {})
    for key in _SETTING_CATEGORIES:
        effective.pop(key, None)
        value = get_category_setting(settings, key, None, map_editor=map_editor)
        if value is not None:
            effective[key] = value
    return effective


def get_scenario_settings(): 
    return _load_cached_json("scenario_settings")


def get_default_scenario_settings():
    """Return editable starting rules without changing saved world settings."""
    return starting_defaults.get_starting_default("scenario_settings.json")


def get_days_per_turn(scenario_settings):
    """Resolves the number of days that pass per turn."""
    if not scenario_settings:
        return c.DEFAULT_DAYS_PER_TURN
        
    val = scenario_settings.get("days_per_turn", starting_defaults.get_starting_value("scenario_settings.json", "days_per_turn"))
    if val == "Default":
        return scenario_settings.get("base_days_per_turn", c.DEFAULT_DAYS_PER_TURN)
    try:
        return int(val)
    except ValueError:
        return c.DEFAULT_DAYS_PER_TURN


#: Editor settings that scenario_has_unit_stat_customizations checks against library values.
_STAT_SETTINGS = ("unit_range_overrides", "building_stat_overrides")


def scenario_has_construction_customizations(settings):
    """True if the player's construction turns or enabled families differ from their defaults.

    A category that uses the map's defaults does not count.
    The Edit Unit / Building Stats badge in Scenario Settings uses this with
    scenario_has_unit_stat_customizations."""
    if not settings:
        return False
    return any(settings.get(key) for category, keys in EDITOR_CATEGORY_SETTINGS.items()
               if not uses_map_defaults(settings, category)
               for key in keys if key not in _STAT_SETTINGS)


def save_scenario_settings(data):
    cache_obj = queries._JSON_CACHE["scenario_settings"]
    
    # 1. Keep full data in memory cache so 'Data Refresh' doesn't wipe custom turn rates
    cache_obj["data"] = data 
    
    # 2. Strip scenario-specific variables before writing to the global file
    safe_data = data.copy()
    safe_data.pop("base_days_per_turn", None)
    safe_data.pop(MAP_DEFAULTS_KEY, None)
    
    # 3. Write only the safe data to the JSON on disk
    try:
        with open(cache_obj["path"], "w", encoding="utf-8") as f:
            json.dump(safe_data, f, indent=c.SAVE_INDENT)
    except Exception as e:
        print(f"Error saving {cache_obj['path']}: {e}")


def clear_json_caches():
    """Forces the game to fetch the updated files on the next read."""
    queries.invalidate_unit_metadata()
    for key in queries._JSON_CACHE:
        # Prevent the Data Refresh button from wiping active session configurations
        if key not in ["settings", "scenario_settings"]:
            queries._JSON_CACHE[key]["data"] = None
    print("[SYSTEM] JSON Memory Caches Cleared.")


def _load_cached_json(cache_key, *, reload=False):
    """Helper function to handle file reading and caching dynamically."""
    cache_obj = queries._JSON_CACHE[cache_key]
    
    if cache_obj["data"] is None or reload:
        previous_data = cache_obj["data"]
        file_path = cache_obj["path"]
        if reload:
            with open(file_path, "r", encoding="utf-8") as f:
                cache_obj["data"] = json.load(f)
        elif os.path.exists(file_path):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    cache_obj["data"] = json.load(f)
            except (OSError, ValueError) as e:
                print(f"Error loading {file_path}: {e}")
                cache_obj["data"] = {}
        else:
            default_file = cache_obj.get("default")
            cache_obj["data"] = starting_defaults.get_starting_default(default_file) if default_file else {}

        normalize_cached_json_names(cache_key, cache_obj["data"])
        if cache_key == "scenario_settings":
            # The player's file can predate the Use Defaults settings, as saves can.
            convert_scenario_settings(cache_obj["data"])
        if reload and isinstance(previous_data, dict):
            previous_data.clear()
            previous_data.update(cache_obj["data"])
            cache_obj["data"] = previous_data
            
    return cache_obj["data"]


def reload_game_library(cache_key, context=None):
    """Reload a game library and preserve references held by screens."""
    if cache_key not in ("unit_library", "building_library", "tech_tree"):
        raise ValueError(f"Not a game library: {cache_key}")
    if context is not None:
        return rebuild(context, reload_defaults=True).libraries[cache_key]
    return _load_cached_json(cache_key, reload=True)


def save_cached_json(cache_key, new_data):
    """Saves data to disk AND updates the cache instantly."""
    cache_obj = queries._JSON_CACHE[cache_key]
    normalize_cached_json_names(cache_key, new_data)
    if cache_key in ("unit_library", "tech_tree"):
        queries.invalidate_unit_metadata()
    cache_obj["data"] = new_data
    
    try:
        with open(cache_obj["path"], "w", encoding="utf-8") as f:
            json.dump(new_data, f, indent=c.SAVE_INDENT)
    except Exception as e:
        print(f"Error saving {cache_obj['path']}: {e}")


def save_global_settings(controller):
    """Writes every setting straight off the Controller.

    The attribute reads this used to spell out positionally are now one
    settings_schema lookup -- which also means tournament_saves_dir is actually
    saved. It was missing from the old list, so saving any setting quietly reset
    the tournament folder to its default.
    """
    from data.io import keybind_io

    keybind_io.save_settings(controller.keybinds,
                             **settings_schema.from_controller(controller))


def get_ai_threads():
    """How many LLM requests to keep in flight, defaulting by provider.

    An explicit slider setting always wins. Without one, a hosted provider gets
    the parallel default and a local Ollama gets one -- four concurrent
    generations against a single local model make the whole batch slower, not
    faster.
    """
    saved = queries.get_settings().get("ai_threads")
    if saved:
        return saved

    from map_logic.ai import ai_settings
    return c.DEFAULT_AI_THREADS_LOCAL if ai_settings.get_ai_mode() == "OLLAMA" else c.DEFAULT_AI_THREADS


def get_ai_turn_budget_seconds():
    """Wall-clock ceiling for one turn's LLM batch; 0 means no limit."""
    return queries.get_settings().get("ai_turn_budget_seconds", c.DEFAULT_AI_TURN_BUDGET_SECONDS)


# --- REFACTORED GETTERS (No paths needed here anymore!) ---
def get_settings(): return _load_cached_json("settings")


def get_keybind(action, default):
    """Resolves a rebindable action (e.g. "BACK") straight from saved settings.

    Reads the persisted keybind rather than any particular screen's in-memory
    controller, since most screens never get a controller reference wired up.
    """
    # Older preference files may omit an action. Use the distribution binding.
    names = starting_defaults.get_starting_value("settings_config.json", "keybinds")
    if action in names:
        name = names[action]
        default = pygame.key.key_code(name) if name is not None else None
    keybinds = queries.get_settings().get("keybinds", {})
    if action not in keybinds:
        return default
    name = keybinds[action]
    if name is None:
        return None
    try:
        return pygame.key.key_code(name)
    except (ValueError, TypeError):
        return default


_KEYBIND_CHANGES_SCREEN_KEYS = {
    "ORDERS": "orders_key_changes_screen",
    "ECONOMY": "economy_key_changes_screen",
}


def get_keybind_changes_screen(action):
    """Whether the ORDERS/ECONOMY keybind also jumps straight to the screen
    its view mode implies -- the small toggle beside that row on the Keybinds
    screen. Independent of Settings' Classic/Preemptive map-navigation toggle
    (see screens.game.map_input.navigate_view_mode / handle_view_mode_keybind).
    Reads saved settings, same as get_keybind, since most screens have no
    controller reference. Missing values use the configured starting default.
    """
    key = _KEYBIND_CHANGES_SCREEN_KEYS.get(action)
    if key is None:
        return False
    return bool(settings_schema.read_setting(queries.get_settings(), key))


def _game_library(name, context):
    # No-context callers edit or inspect default content, never an active world.
    if isinstance(context, ActiveLibrary):
        return context.runtime_rules.libraries[name]
    if context is None or isinstance(context, dict) and world_for(context) is context:
        return _load_cached_json(name)
    return for_world(context).libraries[name]


def get_unit_library(context=None): return _game_library("unit_library", context)


def get_building_library(context=None): return _game_library("building_library", context)


def get_tech_tree(context=None): return _game_library("tech_tree", context)


def get_country_data(): return _load_cached_json("country_data")


def get_ai_responses(): return _load_cached_json("ai_responses")


def get_historical_leader_timeline(): return _load_cached_json("historical_leaders")


def save_historical_leader_timeline(data):
    """Persists the Historical Leaders Editor's data (country -> sorted list of
    dated {name, adjective, leader_name, leader_title} entries)."""
    queries.save_cached_json("historical_leaders", data)


def _as_int(value, default=0):
    """Best-effort int coercion for a timeline date component.

    Entry dates are meant to be plain ints on disk (the editor's own Save
    enforces that), but this is a hot path hit on every historical scenario
    load -- a stray string (hand-edited JSON, a future format change, a bug
    upstream) must never crash the whole game with a str/int comparison
    TypeError. Anything that can't be read as a number quietly falls back to
    `default` instead.
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _historical_entry_date(entry):
    return (_as_int(entry.get("year", 0)), _as_int(entry.get("month", 0)), _as_int(entry.get("day", 0)))


def apply_historical_leader_timeline(nation_data, year, month, day):
    """Overrides name/adjective/color/flag_data/portrait_data/leader_name/
    leader_title on every nation that has a saved historical timeline entry
    at or before (year, month, day).

    Called every time a scenario under scenarios/historical loads (including
    the Data Refresh sync pass), so a country's identity always reflects
    whatever the Historical Leaders Editor last saved for that scenario's own
    date -- editing the timeline later re-applies on the next load with no
    need to touch any scenario file by hand. Each field is resolved
    independently to the latest entry (at or before the date) that actually
    set it, so a later entry can change just the leader without blanking out
    an earlier entry's name/adjective/color/flag/portrait. A country with no
    color (or flag, or portrait) set on any applicable entry keeps whatever
    it already had.
    """
    timeline = get_historical_leader_timeline()
    if not timeline:
        return

    current = (_as_int(year), _as_int(month), _as_int(day))
    fields = ("name", "adjective", "color", "flag_data", "portrait_data", "leader_name", "leader_title")

    for country, entries in timeline.items():
        if not entries or country not in nation_data:
            continue

        applicable = sorted(
            (e for e in entries if _historical_entry_date(e) <= current),
            key=_historical_entry_date,
        )
        if not applicable:
            continue

        data = nation_data[country]
        for field in fields:
            for entry in reversed(applicable):
                value = entry.get(field, "")
                if value:
                    data[field] = value
                    break


def get_active_albums(): return _load_cached_json("active_albums")


def get_shuffle_disabled_tracks():
    """Returns tracks excluded from automatic shuffle, never manual playback."""
    data = _load_cached_json("shuffle_disabled_tracks")
    return data if isinstance(data, list) else []


def get_starting_song():
    """Returns the pinned boot-up track path, or None if it's set to random."""
    data = _load_cached_json("starting_song")
    return data.get("track") if isinstance(data, dict) else None


#: Fallback portrait -- the game's original default look.
DEFAULT_PORTRAIT = starting_defaults.get_starting_value("hildehrand_choice.json", "variant")
DEFAULT_PORTRAIT_DITHERING = starting_defaults.get_starting_value("hildehrand_choice.json", "gradient_dithering")

#: Extensions accepted both when scanning assets/characters/ and when
#: importing a new custom portrait. Broader than the curated set's plain
#: .png so a photo dragged in from Downloads doesn't need converting first.
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg")

_DIGIT_RE = re.compile(r"(\d+)")
# Lower-cased for the comparison in is_custom_portrait() below: Windows'
# filesystem is case-insensitive, so os.walk() can (and, on at least one
# real machine, does) hand back the on-disk folder as "custom" even though
# it was created by writing to a path spelled "Custom" -- a case-sensitive
# prefix check against CUSTOM_SUBDIR would then silently fail to recognise
# a real custom portrait as custom at all.
_CUSTOM_PREFIX_LOWER = f"{CUSTOM_SUBDIR.lower()}/"


def _natural_key(path):
    """Sorts "Hildehrand/F/2.png" before "Hildehrand/F/10.png" -- plain string
    sorting would put "10" before "2"."""
    return [int(part) if part.isdigit() else part.lower() for part in _DIGIT_RE.split(path)]


def is_custom_portrait(rel_path):
    """True for anything imported via the "+ Add New" tile (assets/characters/Custom/...).

    Compares case-insensitively -- see the _CUSTOM_PREFIX_LOWER comment above."""
    return rel_path.replace(os.sep, "/").lower().startswith(_CUSTOM_PREFIX_LOWER)


def discover_character_images():
    """Every image under assets/characters/, recursively, as forward-slash
    paths relative to CHARACTERS_DIR (e.g. "Hildehrand/F/2.png").

    Custom (user-imported) portraits are sorted first among themselves, ahead
    of the curated set, so a newly-added photo doesn't get lost several pages
    into an alphabetical scan."""
    results = []
    if not os.path.isdir(CHARACTERS_DIR):
        return results
    for dirpath, _dirs, files in os.walk(CHARACTERS_DIR):
        for name in files:
            if name.lower().endswith(IMAGE_EXTENSIONS):
                rel = os.path.relpath(os.path.join(dirpath, name), CHARACTERS_DIR)
                results.append(rel.replace(os.sep, "/"))
    custom = sorted((p for p in results if is_custom_portrait(p)), key=_natural_key)
    curated = sorted((p for p in results if not is_custom_portrait(p)), key=_natural_key)
    return custom + curated


def get_hildehrand_choice():
    """Returns the remembered menu portrait, as a path relative to
    assets/characters/. Use the distribution default if unset or if the
    remembered file no longer exists."""
    data = _load_cached_json("hildehrand_choice")
    variant = data.get("variant") if isinstance(data, dict) else None
    return variant if variant in discover_character_images() else starting_defaults.get_starting_value("hildehrand_choice.json", "variant")


def get_hildehrand_gradient():
    """Returns (enabled, strength, stepped, bands) for the menu portrait's button gradient.
    Missing saved values use starting_defaults.json."""
    data = _load_cached_json("hildehrand_choice")
    if not isinstance(data, dict):
        data = {}
    defaults = starting_defaults.get_starting_default("hildehrand_choice.json")
    strength = data.get("gradient_strength", defaults["gradient_strength"])
    strength = max(0.0, min(float(strength), c.HILDEHRAND_GRADIENT_MAX_STRENGTH))
    stepped = bool(data.get("gradient_stepped", defaults["gradient_stepped"]))
    bands = int(data.get("gradient_bands", defaults["gradient_bands"]))
    bands = max(c.HILDEHRAND_GRADIENT_MIN_BANDS, min(bands, c.HILDEHRAND_GRADIENT_MAX_BANDS))
    return bool(data.get("gradient", defaults["gradient"])), strength, stepped, bands


def get_hildehrand_dithering():
    """Read portrait dithering, or use the default when it is not saved."""
    data = _load_cached_json("hildehrand_choice")
    default = starting_defaults.get_starting_value("hildehrand_choice.json", "gradient_dithering")
    return bool(data.get("gradient_dithering", default)) if isinstance(data, dict) else default


def save_hildehrand_portrait(variant, gradient, gradient_strength, gradient_stepped,
                             gradient_bands, *, gradient_dithering=None):
    """Remembers the menu portrait and its gradient: on or off, strength, and stepped or smooth, and band count."""
    if gradient_dithering is None:
        gradient_dithering = starting_defaults.get_starting_value("hildehrand_choice.json", "gradient_dithering")
    save_cached_json("hildehrand_choice", {"variant": variant, "gradient": gradient,
                                           "gradient_strength": gradient_strength,
                                           "gradient_stepped": gradient_stepped,
                                           "gradient_bands": gradient_bands,
                                           "gradient_dithering": gradient_dithering})


def get_research_years(*, context=None):
    """Copy equipment research dates for saves and snapshots."""
    tree = queries.get_tech_tree(context)
    return {key: list(tree[key]["years"]) for key in c.DATED_UNIT_RESEARCH_TRACKS if key in tree}


def get_time_appropriate_research(start_year, *, context=None):
    """Calculates time-appropriate research level mapping for a given start year."""
    struct = queries.get_tech_tree(context)
    if not struct:
        return {}

    res_template = {tech: (1800 if data.get("max_lvl") == 9999 else 0) for tech, data in struct.items()}
    if "infantry_type" in res_template: res_template["infantry_type"] = 0
    if "cavalry" in res_template: res_template["cavalry"] = 0

    tech_timeline = {tech: data.get("years", [1850]) for tech, data in struct.items()}
    
    if start_year == c.DEFAULT_EQUIPMENT_YEAR:
        baseline_tech = {
            tech: (sum(year <= start_year for year in tech_timeline.get(tech, []))
                   if struct.get(tech, {}).get("category") == "INFANTRY" else level)
            for tech, level in c.DEFAULT_1910_TECH.items()}
    else:
        baseline_tech = {}
        for tech, years in tech_timeline.items():
            is_infantry = struct.get(tech, {}).get("category") == "INFANTRY"
            if is_infantry:
                lvl = sum(1 for y in years if y <= start_year)
            else:
                lvl = sum(1 for y in years if y < start_year)
            if lvl > 0:
                baseline_tech[tech] = lvl

    # The first timeline year needs the factory technology used for army recruitment.
    if start_year == c.START_YEAR and "basic_factory" in struct:
        baseline_tech["basic_factory"] = sum(year <= start_year for year in tech_timeline["basic_factory"])

    res = res_template.copy()
    res.update(baseline_tech)
    # DEFAULT_1910_TECH is a hardcoded starting kit unaware of per-scenario
    # disables -- drop anything that isn't actually in the (possibly pruned)
    # tech tree so a disabled tech's default level doesn't get handed back out
    # to every randomly generated nation.
    return {tech: lvl for tech, lvl in res.items() if tech in struct}
