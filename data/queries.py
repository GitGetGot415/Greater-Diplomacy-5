import collections
import contextlib
import json
import os
import re
import base64
import itertools
import math
import random
import threading
import shutil
import zipfile
from data.platform import run_background, IS_WEB, download_file, downloads_dir, sync_persisted_dir
from datetime import datetime

import pygame

import data.constants as c

# Faction and alliance membership are pure derived data, but resolving either
# means scanning every nation -- and AI pathfinding asks for them hundreds of
# thousands of times per turn. diplomacy_snapshot() memoises those lookups for
# the length of a pass that only reads them. It is deliberately opt-in and
# thread-local: outside the block, and on every other thread, these queries
# recompute exactly as before, so no mutation can ever observe a stale answer.
_DIPLO_LOCAL = threading.local()


@contextlib.contextmanager
def diplomacy_snapshot(freeze_access=True):
    """Memoises faction/friendly lookups for the duration of a read-only pass.

    Only wrap code that leaves "faction", "master", "puppets" and "allied_with"
    alone -- a change to any of those inside the block would be invisible to the
    rest of it.

    freeze_access additionally memoises the "may I stand on this tile" rule,
    which also turns on military_access and on queued war declarations; pass
    False for a pass that edits either while it runs. Nesting is safe, and the
    inner block reuses the outer snapshot as-is.
    """
    if getattr(_DIPLO_LOCAL, "store", None) is not None:
        yield
        return

    _DIPLO_LOCAL.store = {
        "friendly": {},
        "faction_members": None,
        "entry": {} if freeze_access else None,
    }
    try:
        yield
    finally:
        _DIPLO_LOCAL.store = None


def get_imperial_family(nation, nation_data):
    """Returns a set containing the nation, its master (if any), and all related puppets."""
    family = set([nation])
    master = nation_data.get(nation, {}).get("master", "")
    top_dog = master if master else nation
    family.add(top_dog)
    family.update(nation_data.get(top_dog, {}).get("puppets", []))
    return family

def _compute_friendly_nations(nation, nation_data):
    friendly = get_imperial_family(nation, nation_data)
    faction = nation_data.get(nation, {}).get("faction", "")
    if faction:
        friendly.update(get_faction_members(faction, nation_data))
    friendly.update(nation_data.get(nation, {}).get("allied_with", []))
    return friendly

def friendly_nations_view(nation, nation_data):
    """Friendly-nation lookup for membership tests only -- never mutate the result.

    Hands back the snapshot's shared frozenset when one is active, which is what
    makes the movement rules cheap enough to call once per pathfinding edge.
    Callers that need their own mutable copy want get_all_friendly_nations.
    """
    store = getattr(_DIPLO_LOCAL, "store", None)
    if store is None:
        return _compute_friendly_nations(nation, nation_data)

    cached = store["friendly"].get(nation)
    if cached is None:
        cached = frozenset(_compute_friendly_nations(nation, nation_data))
        store["friendly"][nation] = cached
    return cached

def get_all_friendly_nations(nation, nation_data):
    """Unified query to fetch a nation, its faction, imperial family, and allies."""
    return set(friendly_nations_view(nation, nation_data))

def get_unit_combat_owner(unit):
    """The diplomatic side a unit temporarily fights for.

    Volunteer units retain their donor in ``owner`` for commands and vision,
    while their host supplies their movement, combat, and capture allegiance.
    """
    return unit.get("volunteer_host") or unit.get("owner", "")

def _apply_vision_radius(prov, id_to_province, visible_set, partial_set):
    """Standardizes FOW radius expansion."""
    visible_set.add(prov["id"])
    for n1 in prov.get("neighbors", []):
        visible_set.add(n1)
        n1_prov = id_to_province.get(n1)
        if n1_prov:
            partial_set.update(n1_prov.get("neighbors", []))

def get_visible_provinces(map_screen):
    """Calculates and returns sets of province IDs currently visible and partially visible to the player."""
    player_country = map_screen.player_country
    map_data = map_screen.map_data
    nation_data = map_screen.nation_data
    id_to_province = map_screen.id_to_province

    if player_country in ["Spectator", "Editor", "None"] or player_country not in nation_data:
        return None, None # Returns None to signify "Full Visibility / Ignore Fog"
        
    friendly_nations = get_all_friendly_nations(player_country, nation_data)
        
    visible_set = set()
    partial_set = set()
    
    is_tactical = map_screen.tactical_mode and map_screen.player_unit
    tactical_unit = map_screen.player_unit if is_tactical else None
    
    friendly_unit_locations = []
    tactical_location = None
    
    for prov in map_data.values():
        owner = prov.get("owner", "")
        
        # In general, owning a tile only makes that specific tile visible
        if owner in friendly_nations:
            visible_set.add(prov["id"])
            
        for u in prov.get("units", []):
            if u.get("owner") in friendly_nations:
                friendly_unit_locations.append(prov)
            if is_tactical and u is tactical_unit:
                tactical_location = prov
                
    if is_tactical:
        # Override visibility for tactical mode entirely
        visible_set.clear()
        partial_set.clear()
        if tactical_location:
            # 1. Radius around unit
            _apply_vision_radius(tactical_location, id_to_province, visible_set, partial_set)
                    
            # 2. Contiguous landmass check
            if not is_water_province(tactical_location):
                queue = [tactical_location["id"]]
                visited = set([tactical_location["id"]])
                
                while queue:
                    curr_id = queue.pop(0)
                    # DO NOT DELETE THIS COMMENT DO NOT DELETE ANY OTHER COMMENTS
                    partial_set.add(curr_id)
                    # visible_set.add(curr_id)
                    curr_prov = id_to_province.get(curr_id)
                    if curr_prov:
                        for n_id in curr_prov.get("neighbors", []):
                            if n_id not in visited:
                                n_prov = id_to_province.get(n_id)
                                # Must be owned by friendly nations and be land
                                if n_prov and not is_water_province(n_prov) and n_prov.get("owner") in friendly_nations:
                                    visited.add(n_id)
                                    queue.append(n_id)
    else:
        # Standard mode radius parsing
        for prov in friendly_unit_locations:
            _apply_vision_radius(prov, id_to_province, visible_set, partial_set)
                        
    # Filter out anything from partial that is already in the closer full visibility group
    partial_set -= visible_set
    
    return visible_set, partial_set

def is_province_visible(map_screen, prov_id):
    """Standardized check for fog of war visibility."""
    if map_screen and getattr(map_screen, 'visible_provinces', None) is not None:
        return prov_id in map_screen.visible_provinces
    return True

def get_unit_upkeep(stats):
    """Calculates dynamically modified unit upkeep costs."""
    return {
        "manpower": stats.get("cost_manpower", 0) * c.UPKEEP_MODIFIERS["manpower"],
        "materials": stats.get("cost_materials", 0) * c.UPKEEP_MODIFIERS["materials"],
        "fuel": stats.get("cost_fuel", 0) * c.UPKEEP_MODIFIERS["fuel"]
    }

# ==========================================
# UNIFIED CACHE MANAGER
# ==========================================

# By mapping the path directly to the cache, we can automate loading and saving!
_JSON_CACHE = {
    "settings": {"path": c.SETTINGS_CONFIG_PATH, "data": None},
    "scenario_settings": {"path": "data/json/scenario_settings.json", "data": None},
    "unit_library": {"path": c.UNIT_DATA_PATH, "data": None},
    "building_library": {"path": c.BUILDING_DATA_PATH, "data": None},
    "tech_tree": {"path": c.RESEARCH_TEMPLATE_PATH, "data": None},
    "country_data": {"path": c.COUNTRIES_DATA_PATH, "data": None},
    "active_albums": {"path": c.ACTIVE_ALBUMS_PATH, "data": None},
    "starting_song": {"path": c.STARTING_SONG_PATH, "data": None},
    "hildehrand_choice": {"path": c.HILDEHRAND_CHOICE_PATH, "data": None},
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
        scenario_settings = get_scenario_settings()

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
}


def apply_global_scenario_flags(scenario_settings):
    """Pushes the scenario's rules onto their live constants.

    Called on map load and again whenever a save overrides the session settings;
    keeping the flag/value lists in one table each is what stops the two paths
    drifting apart.
    """
    for flag_name, (const_name, default) in GLOBAL_SCENARIO_FLAGS.items():
        setattr(c, const_name, get_scenario_flag(flag_name, default, scenario_settings))

    for key, (const_name, default, cast) in GLOBAL_SCENARIO_VALUES.items():
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
    new_value = not get_scenario_flag(flag_name, default, scenario_settings)
    scenario_settings[flag_name] = new_value
    save_scenario_settings(scenario_settings)
    return new_value


def get_scenario_settings(): 
    return _load_cached_json("scenario_settings")

def get_days_per_turn(scenario_settings):
    """Resolves the number of days that pass per turn."""
    if not scenario_settings:
        return c.DEFAULT_DAYS_PER_TURN
        
    val = scenario_settings.get("days_per_turn", "Default")
    if val == "Default":
        return scenario_settings.get("base_days_per_turn", c.DEFAULT_DAYS_PER_TURN)
    try:
        return int(val)
    except ValueError:
        return c.DEFAULT_DAYS_PER_TURN

def scenario_has_construction_customizations(settings):
    """True if the Construction Turns Editor has anything set away from its
    defaults (a turn override or a disabled unit/building), for the badge on
    its entry-point button in Scenario Settings."""
    if not settings:
        return False
    return bool(settings.get("unit_turn_overrides") or settings.get("building_turn_overrides")
                or settings.get("unit_disabled") or settings.get("building_disabled"))

def save_scenario_settings(data):
    cache_obj = _JSON_CACHE["scenario_settings"]
    
    # 1. Keep full data in memory cache so 'Data Refresh' doesn't wipe custom turn rates
    cache_obj["data"] = data 
    
    # 2. Strip scenario-specific variables before writing to the global file
    safe_data = data.copy()
    safe_data.pop("base_days_per_turn", None)
    
    # 3. Write only the safe data to the JSON on disk
    try:
        with open(cache_obj["path"], "w", encoding="utf-8") as f:
            json.dump(safe_data, f, indent=c.SAVE_INDENT)
    except Exception as e:
        print(f"Error saving {cache_obj['path']}: {e}")

def clear_json_caches():
    """Forces the game to fetch the updated files on the next read."""
    for key in _JSON_CACHE:
        # Prevent the Data Refresh button from wiping active session configurations
        if key not in ["settings", "scenario_settings"]:
            _JSON_CACHE[key]["data"] = None
    print("[SYSTEM] JSON Memory Caches Cleared.")

def _load_cached_json(cache_key):
    """Helper function to handle file reading and caching dynamically."""
    cache_obj = _JSON_CACHE[cache_key]
    
    if cache_obj["data"] is None:
        file_path = cache_obj["path"]
        if os.path.exists(file_path):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    cache_obj["data"] = json.load(f)
            except Exception as e:
                print(f"Error loading {file_path}: {e}")
                cache_obj["data"] = {}
        else:
            cache_obj["data"] = {}
            
    return cache_obj["data"]

def save_cached_json(cache_key, new_data):
    """Saves data to disk AND updates the cache instantly."""
    cache_obj = _JSON_CACHE[cache_key]
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
    from data.io import keybind_io, settings_schema

    keybind_io.save_settings(controller.keybinds,
                             **settings_schema.from_controller(controller))

def get_ai_threads():
    """How many LLM requests to keep in flight, defaulting by provider.

    An explicit slider setting always wins. Without one, a hosted provider gets
    the parallel default and a local Ollama gets one -- four concurrent
    generations against a single local model make the whole batch slower, not
    faster.
    """
    saved = get_settings().get("ai_threads")
    if saved:
        return saved

    from map_logic.ai import ai_settings
    return c.DEFAULT_AI_THREADS_LOCAL if ai_settings.get_ai_mode() == "OLLAMA" else c.DEFAULT_AI_THREADS


def get_ai_turn_budget_seconds():
    """Wall-clock ceiling for one turn's LLM batch; 0 means no limit."""
    return get_settings().get("ai_turn_budget_seconds", c.DEFAULT_AI_TURN_BUDGET_SECONDS)

# --- REFACTORED GETTERS (No paths needed here anymore!) ---
def get_settings(): return _load_cached_json("settings")

def get_keybind(action, default):
    """Resolves a rebindable action (e.g. "BACK") straight from saved settings.

    Reads the persisted keybind rather than any particular screen's in-memory
    controller, since most screens never get a controller reference wired up.
    """
    name = get_settings().get("keybinds", {}).get(action)
    if not name:
        return default
    try:
        return pygame.key.key_code(name)
    except Exception:
        return default

_KEYBIND_CHANGES_SCREEN_KEYS = {
    "ORDERS": "orders_key_changes_screen",
    "ECONOMY": "economy_key_changes_screen",
}

def get_keybind_changes_screen(action):
    """Whether the ORDERS/ECONOMY keybind also jumps straight to the screen
    its view mode implies -- the small toggle beside that row on the Keybinds
    screen. Independent of Settings' Classic/Preemptive map-navigation toggle
    (see ui.event_handler.navigate_view_mode / handle_view_mode_keybind).
    Reads straight from saved settings, same as get_keybind, since most
    screens never get a controller reference wired up. Defaults on.
    """
    key = _KEYBIND_CHANGES_SCREEN_KEYS.get(action)
    if key is None:
        return False
    return bool(get_settings().get(key, True))

def get_unit_library(): return _load_cached_json("unit_library")
def get_building_library(): return _load_cached_json("building_library")
def get_tech_tree(): return _load_cached_json("tech_tree")
def get_country_data(): return _load_cached_json("country_data")
def get_ai_responses(): return _load_cached_json("ai_responses")
def get_historical_leader_timeline(): return _load_cached_json("historical_leaders")

def save_historical_leader_timeline(data):
    """Persists the Historical Leaders Editor's data (country -> sorted list of
    dated {name, adjective, leader_name, leader_title} entries)."""
    save_cached_json("historical_leaders", data)

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

def get_starting_song():
    """Returns the pinned boot-up track path, or None if it's set to random."""
    data = _load_cached_json("starting_song")
    return data.get("track") if isinstance(data, dict) else None

def get_hildehrand_choice():
    """Returns the remembered menu portrait, as a path relative to
    assets/characters/ (e.g. "Hildehrand/F/2.png"), defaulting to Hildehrand F/2
    if unset or if the remembered file no longer exists."""
    from ui.character_select_screen import DEFAULT_PORTRAIT, discover_character_images
    data = _load_cached_json("hildehrand_choice")
    variant = data.get("variant") if isinstance(data, dict) else None
    return variant if variant in discover_character_images() else DEFAULT_PORTRAIT

def get_time_appropriate_research(start_year):
    """Calculates time-appropriate research level mapping for a given start year."""
    struct = get_tech_tree()
    if not struct:
        return {}

    res_template = {tech: (1800 if data.get("max_lvl") == 9999 else 0) for tech, data in struct.items()}
    if "infantry_type" in res_template: res_template["infantry_type"] = 0
    if "cavalry" in res_template: res_template["cavalry"] = 0

    tech_timeline = {tech: data.get("years", [1850]) for tech, data in struct.items()}
    
    if start_year == 1910:
        baseline_tech = getattr(c, 'DEFAULT_1910_TECH', {}).copy()
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

    res = res_template.copy()
    res.update(baseline_tech)
    # DEFAULT_1910_TECH is a hardcoded starting kit unaware of per-scenario
    # disables -- drop anything that isn't actually in the (possibly pruned)
    # tech tree so a disabled tech's default level doesn't get handed back out
    # to every randomly generated nation.
    return {tech: lvl for tech, lvl in res.items() if tech in struct}


def apply_time_appropriate_research_to_map(map_screen, year):
    """Overwrites the map default and every living nation's research with the
    time-appropriate levels for `year`.

    Shared by the research editor's manual toggle and the date editor's
    auto-recompute (when "force_time_appropriate_research" is on), so the two
    can't drift into computing this differently.
    """
    time_app_res = get_time_appropriate_research(year)
    map_screen.default_research = time_app_res.copy()
    for cid in get_living_nations(map_screen.map_data):
        map_screen.nation_data[cid]["research"] = time_app_res.copy()
    return time_app_res


# ==========================================
# DIPLOMACY & COMBAT QUERIES
# ==========================================

def get_combined_enemy_strength(target_nation, map_data, nation_data):
    """Calculates the total military strength of everyone actively fighting the target."""
    total_str = 0
    enemies = get_enemies(target_nation, nation_data)
    for enemy in enemies:
        if enemy in nation_data and enemy not in c.UNPLAYABLE_NATIONS:
            total_str += get_military_strength(enemy, map_data)
    return total_str

def get_total_turns(time_manager):
    """Calculates the total number of turns elapsed since the start of the scenario."""
    return time_manager.total_turns

def get_economic_power(nation, nation_data):
    """Estimates a nation's economic power based on its resource stockpiles."""
    data = nation_data.get(nation, {})
    manpower_val = data.get("manpower", 0) * c.ECONOMY_WEIGHT_MANPOWER
    materials_val = data.get("materials", 0) * c.ECONOMY_WEIGHT_MATERIALS
    fuel_val = data.get("fuel", 0) * c.ECONOMY_WEIGHT_FUEL
    return manpower_val + materials_val + fuel_val

def get_alliance_military_strength(nation, map_data, nation_data):
    """Calculates the combined military strength of a nation and its faction members/allies/subjects."""
    return sum(get_military_strength(member, map_data) for member in get_all_friendly_nations(nation, nation_data))

def get_military_strength(nation, map_data):
    """Calculates rough military strength of a nation based on unit stats."""
    strength = 0
    for prov in map_data.values():
        for u in prov.get("units", []):
            if u.get("owner") == nation:
                strength += calculate_unit_strength(u)
    return strength

def get_nations_holding_our_cores_or_claims(nation, map_data, nation_data):
    """Returns a set of foreign nations that own territory where the given nation has a core or a claim."""
    targets = set()
    claims = nation_data.get(nation, {}).get("claims", [])
    for prov in map_data.values():
        owner = prov.get("owner")
        if owner and owner != nation and owner not in c.UNPLAYABLE_NATIONS:
            if nation in prov.get("cores", []) or prov["id"] in claims:
                targets.add(owner)
    return targets

def get_border_strength(nation_a, nation_b, map_data, id_to_province, nation_data):
    """Calculates the military strength of both nations localized to their shared border zone."""
    combined_border_provs = set()
    
    # Build a single "Front Line" zone that includes BOTH sides of the border
    for prov in map_data.values():
        owner = prov.get("owner")
        if owner == nation_a:
            for n_id in prov.get("neighbors", []):
                n_prov = id_to_province.get(n_id)
                if n_prov and n_prov.get("owner") == nation_b:
                    combined_border_provs.add(prov["id"])
                    combined_border_provs.add(n_id)
                    
    def calc_strength(prov_ids, evaluating_nation, opposing_nation):
        strength = 0
        
        # Include imperial family (puppets), allies, and faction members defending the border
        friendly_nations = get_all_friendly_nations(evaluating_nation, nation_data)
        
        for prov_id in prov_ids:
            prov = id_to_province.get(prov_id)
            if prov:
                # Gather all friendly units on this tile
                friendly_units = [u for u in prov.get("units", []) if u.get("owner") in friendly_nations]
                
                # What this tile can actually bring to bear: a lane's front rank
                # and the relief wave behind it, best units first.
                top_units = get_front_and_relief(friendly_units)
                
                tile_strength = 0
                for u in top_units:
                    base_str = calculate_unit_strength(u)
                    
                    # Reduce strength if this unit is actively fighting someone else on this tile
                    in_combat_with_third_party = False
                    for other_u in prov.get("units", []):
                        other_owner = other_u.get("owner")
                        if other_owner != opposing_nation and are_at_war(u.get("owner"), other_owner, nation_data):
                            in_combat_with_third_party = True
                            break
                            
                    if in_combat_with_third_party:
                        base_str *= c.AI_BORDER_DISTRACTION_MULTIPLIER
                        
                    tile_strength += base_str
                strength += tile_strength
        return strength

    # Both nations now look at the exact same cluster of frontline tiles
    return calc_strength(combined_border_provs, nation_a, nation_b), calc_strength(combined_border_provs, nation_b, nation_a)

def are_at_war(nation_a, nation_b, nation_data):
    """Returns True if nation_b is in nation_a's war list."""
    return nation_b in get_enemies(nation_a, nation_data)

def is_province_in_active_combat(province, nation_data):
    """Returns True if ANY units from mutually hostile nations occupy this province."""
    units = province.get("units", [])
    if len(units) < 2:
        return False
        
    owners_present = list(set(get_unit_combat_owner(u) for u in units
                              if get_unit_combat_owner(u)))
    
    # Optimized check using itertools
    return any(are_at_war(o1, o2, nation_data) for o1, o2 in itertools.combinations(owners_present, 2))


def is_nation_in_combat_here(nation, province, nation_data):
    """Returns True if the specified nation has units in the province that are actively engaged with enemy units."""
    units = province.get("units", [])
    enemies = get_enemies(nation, nation_data)
    return any(get_unit_combat_owner(u) in enemies for u in units)

def is_submarine_unit(unit_type):
    """Checks if a unit belongs to the Submarine family, at any research level."""
    return unit_type.startswith("Submarine")

def is_unit_visible_to(unit, viewer_nation, province, nation_data):
    """Whether `viewer_nation` is allowed to see this unit, on top of ordinary fog of war.

    Submarines stay hidden from everyone outside the owner's imperial family,
    faction, and allies -- unless mutually hostile nations are already trading
    fire in the province, at which point there is no more hiding among them.
    Every other unit type is unaffected.
    """
    if not is_submarine_unit(unit.get("type", "")):
        return True
    if viewer_nation not in nation_data:
        # Spectator/Editor/no-country views ignore fog of war entirely, same as
        # get_visible_provinces -- there's no nation here to keep a secret from.
        return True
    owner = unit.get("owner")
    if owner == viewer_nation or owner in get_all_friendly_nations(viewer_nation, nation_data):
        return True
    return is_province_in_active_combat(province, nation_data)

def filter_visible_units(units, viewer_nation, province, nation_data):
    """Returns `units` with any submarines `viewer_nation` may not see stripped out."""
    return [u for u in units if is_unit_visible_to(u, viewer_nation, province, nation_data)]

def is_hostile_territory(moving_nation, target_owner, nation_data):
    """Checks if a nation is actively at war with the target territory."""
    if target_owner in c.UNPLAYABLE_NATIONS:
        return False
    return are_at_war(moving_nation, target_owner, nation_data)

def are_in_same_faction(nation_a, nation_b, nation_data):
    """Returns True if both nations share a faction string."""
    fac_a = nation_data.get(nation_a, {}).get("faction", "")
    fac_b = nation_data.get(nation_b, {}).get("faction", "")
    return fac_a != "" and fac_a == fac_b

def get_faction_members(faction_name, nation_data):
    """Returns a list of all nations currently in the specified faction."""
    if not faction_name: return []

    store = getattr(_DIPLO_LOCAL, "store", None)
    if store is None:
        return [n for n, d in list(nation_data.items()) if d.get("faction") == faction_name]

    # Under a snapshot, one pass over nation_data answers every faction instead
    # of one pass per question. Still hands back a fresh list each time, since
    # callers do stash and mutate what they get back.
    index = store["faction_members"]
    if index is None:
        index = {}
        for n, d in list(nation_data.items()):
            fac = d.get("faction") if isinstance(d, dict) else None
            if fac:
                index.setdefault(fac, []).append(n)
        store["faction_members"] = index
    return list(index.get(faction_name, ()))

def get_faction_leader(faction_name, nation_data):
    """Returns the leader of the specified faction."""
    if not faction_name: return None
    for n, d in list(nation_data.items()):
        if d.get("faction") == faction_name and d.get("is_faction_leader", False):
            return n
    return None

def is_faction_leader(nation, nation_data):
    """Returns True if the nation is currently a faction leader."""
    return nation_data.get(nation, {}).get("is_faction_leader", False)

def get_historical_owner(province, faction_name, nation_data):
    """Returns the pre-war owner of a tile if a faction war is active, otherwise the primary core."""
    if faction_name and "FACTION_WAR_MAPS" in nation_data and faction_name in nation_data["FACTION_WAR_MAPS"]:
        pre_war = nation_data["FACTION_WAR_MAPS"][faction_name]
        return pre_war.get(str(province["id"])) or pre_war.get(province["id"])
    return province.get("cores", [None])[0] if province.get("cores") else None

def get_faction_core_transfer_target(capturer, province, nation_data):
    """
    Determines if a captured territory should be transferred to a faction member
    who has a core on it, OR who originally owned it before the war began.
    Returns the true owner to assign the province to.
    """
    if capturer in c.UNPLAYABLE_NATIONS:
        return capturer

    faction_name = nation_data.get(capturer, {}).get("faction", "")
    if not faction_name:
        return capturer

    original_owner = get_historical_owner(province, faction_name, nation_data)
    faction_members = get_faction_members(faction_name, nation_data)

    # 1. Check Pre-War Faction Map First
    if original_owner and original_owner != capturer and original_owner in faction_members:
        return original_owner

    # 2. Fallback to standard core logic
    tile_cores = province.get("cores", [])
    faction_cores_on_tile = [m for m in faction_members if m in tile_cores]

    if len(faction_cores_on_tile) == 1:
        return faction_cores_on_tile[0]
    
    return capturer

# --- NEW FACTION WAR BORDER TRACKING QUERIES ---
def is_faction_at_war(faction_name, nation_data):
    """Returns True if any member of the given faction is actively at war."""
    members = get_faction_members(faction_name, nation_data)
    return any(len(get_enemies(m, nation_data)) > 0 for m in members)

def save_faction_pre_war_map(faction_name, map_data, nation_data):
    """Snapshots the faction's borders right before entering a war."""
    if "FACTION_WAR_MAPS" not in nation_data:
        nation_data["FACTION_WAR_MAPS"] = {}

    members = get_faction_members(faction_name, nation_data)
    pre_war_map = {}
    for prov in map_data.values():
        owner = prov.get("owner")
        if owner in members:
            pre_war_map[str(prov["id"])] = owner

    nation_data["FACTION_WAR_MAPS"][faction_name] = pre_war_map

def _modify_pre_war_map(faction_name, nation_data, modify_func):
    """Helper to safely access and modify the pre-war map."""
    if "FACTION_WAR_MAPS" in nation_data and faction_name in nation_data["FACTION_WAR_MAPS"]:
        modify_func(nation_data["FACTION_WAR_MAPS"][faction_name])

def add_member_to_pre_war_map(member_name, faction_name, map_data, nation_data):
    """Adds a newly joined member's territory to the active pre-war map."""
    def _add(pre_war_map):
        for prov in map_data.values():
            if prov.get("owner") == member_name:
                pre_war_map[str(prov["id"])] = member_name
    _modify_pre_war_map(faction_name, nation_data, _add)

def remove_member_from_pre_war_map(member_name, faction_name, nation_data):
    """Removes a leaving member's territory from the active pre-war map."""
    def _remove(pre_war_map):
        keys_to_remove = [prov_id for prov_id, owner in pre_war_map.items() if owner == member_name]
        for k in keys_to_remove:
            del pre_war_map[k]
    _modify_pre_war_map(faction_name, nation_data, _remove)

def clear_faction_pre_war_map_if_peace(faction_name, nation_data):
    """Clears the pre-war map if the faction is no longer at war."""
    if not is_faction_at_war(faction_name, nation_data):
        if "FACTION_WAR_MAPS" in nation_data and faction_name in nation_data["FACTION_WAR_MAPS"]:
            del nation_data["FACTION_WAR_MAPS"][faction_name]

# ==========================================
# MOVEMENT QUERIES
# ==========================================

def has_military_access(moving_nation, target_owner, nation_data):
    """Returns True if the target_owner has granted military access to the moving_nation."""
    return moving_nation in nation_data.get(target_owner, {}).get("military_access", [])

def get_military_access_granted_by(nation, nation_data):
    """Who this nation lets march through its territory."""
    return list(nation_data.get(nation, {}).get("military_access", []))


def get_military_access_granted_to(nation, nation_data):
    """Whose territory this nation may march through.

    Access is stored only on the granting side, so the reverse direction needs a
    sweep -- there is no index for it. Cheap enough for a panel that redraws on
    selection, but do not call it per frame on a large map.
    """
    return sorted(other for other, data in nation_data.items()
                  if isinstance(data, dict) and nation in (data.get("military_access") or ()))


def can_negotiate_peace(nation, other, nation_data):
    """Whether `nation` may settle a war with `other` on its own authority.

    A puppet's wars are its master's business. It may still make peace WITH its
    master, since that is how an independence war ends -- the mirror of the
    existing rule that a puppet may only declare war on its master.

    Nothing enforced this before: thirteen separate paths could initiate or
    accept a peace, and none of them looked at `master`, so a subject could sign
    its own treaty while its overlord was still fighting.
    """
    master = nation_data.get(nation, {}).get("master", "")
    return not master or master == other


def can_choose_own_faction(nation, nation_data):
    """Whether `nation` may join, be invited into, or leave a faction alone.

    A puppet's alignment is its master's, exactly as its wars are -- it follows
    its overlord in and out through pull_puppets_into_faction and its opposite,
    and has no say of its own. Nothing checked this either, so a subject could
    sit in a faction its master had never joined: in saves/Madagascar but not
    France, French Madagascar was in the Axis while Vichy France was in nothing.

    Founding a faction is deliberately not covered. finalize_create_faction
    already redirects to the master, so the puppet is not acting alone there.
    """
    return not nation_data.get(nation, {}).get("master", "")


def needs_military_access_request(moving_nation, target_owner, nation_data):
    """False if moving_nation can already enter target_owner's territory.

    Covers explicit grants as well as implicit access via puppet/master,
    faction, or alliance ties, so the AI doesn't ask for something it
    (or its allies) already has.
    """
    if has_military_access(moving_nation, target_owner, nation_data):
        return False
    if target_owner in friendly_nations_view(moving_nation, nation_data):
        return False
    return True


def can_convoy_enter(current_province, target_province):
    """Convoys on a land tile can only move into water tiles."""
    curr_is_water = is_water_province(current_province)
    dest_is_water = is_water_province(target_province)

    # If they're on a land tile they can only move onto an ocean one
    if not curr_is_water and not dest_is_water:
        return False
    return True

def is_water_province(province):
    """Shorthand to check if a province is a water tile."""
    return province.get("terrain") in c.WATER_TERRAINS

def has_surprise_attack_entry(moving_nation, target_owner, nation_data):
    """True when a queued war declaration lets units pre-position inside the target.

    Only applies while the surprise_attack scenario flag is on. Covers both the
    player's pending_diplomacy entry and the AI's queued_ai_actions list, since
    the two paths queue a declaration differently.
    """
    if not get_scenario_flag("surprise_attack", c.DEFAULT_SURPRISE_ATTACK, get_scenario_settings()):
        return False

    from map_logic.diplomacy import diplomacy_messages
    if diplomacy_messages.get_pending_action(nation_data, moving_nation, target_owner) == "WAR_DECLARATION":
        return True

    queued = nation_data.get(moving_nation, {}).get("queued_ai_actions", [])
    return any(q.get("target") == target_owner and q.get("action") == "WAR_DECLARATION" for q in queued)

def _resolve_owned_tile_entry(moving_nation, target_owner, nation_data):
    if has_surprise_attack_entry(moving_nation, target_owner, nation_data):
        return True
    if has_military_access(moving_nation, target_owner, nation_data):
        return True
    return target_owner in friendly_nations_view(moving_nation, nation_data)

def _can_enter_owned_tile(moving_nation, target_owner, nation_data):
    """The shared tail of the naval and land movement rules."""
    store = getattr(_DIPLO_LOCAL, "store", None)
    entry = store["entry"] if store is not None else None
    if entry is None:
        return _resolve_owned_tile_entry(moving_nation, target_owner, nation_data)

    # The answer turns on who owns the tile, not which tile it is, so a snapshot
    # only has to settle it once per nation pairing instead of once per tile.
    key = (moving_nation, target_owner)
    if key not in entry:
        entry[key] = _resolve_owned_tile_entry(moving_nation, target_owner, nation_data)
    return entry[key]

def can_ships_enter(moving_nation, target_province, nation_data):
    """Centralized rules for naval movement."""
    if is_water_province(target_province): return True
    if not target_province.get("is_coastal", False): return False

    # Ships can dock in a friendly port, but cannot land on unclaimed shores
    # to claim them -- taking territory is a job for land units.
    target_owner = target_province.get("owner", "Unclaimed")
    return _can_enter_owned_tile(moving_nation, target_owner, nation_data)

def can_land_units_enter(moving_nation, target_province, nation_data):
    """Centralized rules for land movement."""
    if is_water_province(target_province): return False

    target_owner = target_province.get("owner", "Unclaimed")
    turn_start_owner = target_province.get("_turn_start_owner", target_owner)

    # If the tile was captured THIS TURN, we evaluate entry based on the original owner
    # to prevent movement execution order from blocking units moving on the exact same turn.
    if current_owner := target_owner:
        if turn_start_owner != current_owner:
            target_owner = turn_start_owner

    if target_owner in c.OWNERLESS_OWNERS: return True
    if are_at_war(moving_nation, target_owner, nation_data): return True

    return _can_enter_owned_tile(moving_nation, target_owner, nation_data)

def get_tactical_speed(unit):
    """Calculates the effective speed of a unit in tactical mode."""
    return unit.get("speed", c.DEFAULT_UNIT_SPD)

def get_tactical_fuel_cost_per_tile(unit, fuel_inc):
    """Calculates the fuel cost per tile moved in tactical mode."""
    calc_speed = get_tactical_speed(unit)
    return math.ceil(fuel_inc / (calc_speed * 0.75)) if calc_speed > 0 else 0

# ==========================================
# PROVINCE & TECH QUERIES
# ==========================================

def get_max_fuel_conversion(nation_data_block):
    """Determines the maximum allowed Mat-to-Fuel conversion slider value based on tech."""
    res = nation_data_block.get("research", {})
    lvl = res.get("fuel_refining", 0)
    return lvl * c.FUEL_REFINING_CONVERSION_PER_LVL

def get_industry(province):
    """Returns the highest level of industry in the province."""
    level = 0
    for b in province.get("buildings", []):
        if b == "Basic Factory":
            level = max(level, 6)
        elif "Factory Lvl" in b:
            lvl = int(b.split()[-1])
            level = max(level, 6 + lvl)
    # The construction site itself counts as Level 1 industry so Militia can be built on it!
    for q in province.get("building_queue", []):
        if q.get("item_name") == "Basic Factory":
            level = max(level, 1)
    return level

def has_industry(province):
    """Returns True if the province contains a Workshop or Factory."""
    return get_industry(province) > 0

def has_basic_factory(province):
    """Returns True if the province contains a Basic Factory or better."""
    return get_industry(province) >= 6

def borders_ocean(province, id_to_province):
    """Returns True if the province borders at least one non-lake water tile."""
    for n_id in province.get("neighbors", []):
        n_prov = id_to_province.get(n_id)
        if n_prov and n_prov.get("terrain") in c.OCEAN_TERRAINS:
            return True
    return False

def get_building_required_tech(b_name):
    """Maps building names to their respective research tree requirements."""
    if "Basic Factory" in b_name:
        return "basic_factory", 1
    if "Factory Lvl" in b_name:
        return "factory", int(b_name.split()[-1])
    if "Synthetic Refinery" in b_name:
        return "fuel_refining", int(b_name.split()[-1])
    if "Basic Recruitment" in b_name:
        return "basic_recruitment", 1
    if "Recruitment Building Lvl" in b_name:
        return "recruitment_buildings", int(b_name.split()[-1])
    return None, 0

def get_fort_level(province):
    """Returns the highest completed fort level on a province, if any."""
    level = 0
    for b_name in province.get("buildings", []):
        match = re.fullmatch(r"Fort Lvl (\d+)", b_name)
        if match:
            level = max(level, int(match.group(1)))
    return level


# Combat locations are always described from one nation's perspective.  These
# names deliberately match the map bubbles, but are rules-facing categories so
# future mechanics do not have to reimplement the fort-territory test.
COMBAT_LOCATION_DEFENSE = "defense"
COMBAT_LOCATION_OFFENSE = "offense"


def is_fort_defended_territory(province, nation, nation_data):
    """Whether ``nation`` would receive a fort's defense on this province.

    This does not require a fort or active combat.  It answers the durable
    territory rule shared by fort bonuses, combat presentation, and any future
    defense-side mechanics: a province protects its owner and faction members.
    """
    owner = province.get("owner")
    return bool(owner and nation and
                (nation == owner or are_in_same_faction(owner, nation, nation_data)))


def get_combat_location_category(province, perspective_nation, nation_data):
    """Classify a battle as defensive or offensive.

    ``perspective_nation`` is normally the local player.  With no nation (for
    example a spectator), real province battles use the neutral defensive
    shape; their outcome color still remains grey because the spectator is not
    participating.
    """
    if (perspective_nation is None or perspective_nation in ("Spectator", "Editor")
            or is_fort_defended_territory(province, perspective_nation, nation_data)):
        return COMBAT_LOCATION_DEFENSE
    return COMBAT_LOCATION_OFFENSE

def damage_fort(province, nation_data, map_data=None):
    """Removes one fort level and cancels/refunds queued fort upgrades.

    The queue belongs to the province, while its construction cost was paid by
    the current tile owner.  Queue entries record the exact amount paid, so
    using ``refund_queue_item`` also keeps old saves and any applicable cost
    modifiers correct.

    Returns the new fort level, or ``None`` when the province had no fort.
    """
    current_level = get_fort_level(province)
    if current_level <= 0:
        return None

    province["buildings"] = [
        b_name for b_name in province.get("buildings", [])
        if not re.fullmatch(r"Fort Lvl (\d+)", b_name)
    ]
    if current_level > 1:
        province["buildings"].append(f"Fort Lvl {current_level - 1}")

    queue = province.get("building_queue", [])
    if queue:
        owner = province.get("owner")
        owner_data = nation_data.get(owner, {}) if owner else {}
        kept_queue = []
        cancelled = False
        for item in queue:
            if (item.get("order_type") == "BUILDING"
                    and re.fullmatch(r"Fort Lvl (\d+)", item.get("item_name", ""))):
                refund_queue_item(owner_data, item, owner, map_data)
                cancelled = True
            else:
                kept_queue.append(item)
        if cancelled:
            province["building_queue"] = kept_queue

    return current_level - 1

def get_fort_defense_bonus(province, unit, nation_data, combat_active=None):
    """Returns the fort defense bonus for a unit defending this province.

    Forts protect the province owner and nations in the owner's faction.  The
    bonus only exists while the tile is under attack; callers such as
    bombardment can pass ``combat_active=True`` because the attacker is not
    physically present in the province.
    """
    level = get_fort_level(province)
    if level <= 0:
        return 0

    if combat_active is None:
        combat_active = is_province_in_active_combat(province, nation_data)
    if not combat_active:
        return 0

    if not is_fort_defended_territory(province, unit.get("owner"), nation_data):
        return 0
    return level * c.FORT_DEFENSE_PER_LEVEL

def get_tech_unlocks(tech_key, level):
    """Returns a list of strings detailing what this tech unlocks."""
    unlocks = []
    bldg_lib = get_building_library()
    for b_name in bldg_lib.keys():
        req_tech, req_lvl = get_building_required_tech(b_name)
        if req_tech == tech_key and req_lvl == level:
            unlocks.append(b_name)
            
    # Hardcoded logic bonuses
    if tech_key == "bergius_process" and level == 1:
        unlocks.append(f"+{c.BERGIUS_FUEL_BONUS} Base Fuel/Turn")
    elif tech_key == "fuel_refining":
        limit = int(level * c.FUEL_REFINING_CONVERSION_PER_LVL * 100)
        unlocks.append(f"Max Mat-to-Fuel Conversion: {limit}%")
        
    if tech_key == "general_recruitment":
        bonus = c.GENERAL_RECRUITMENT_BONUS
        unlocks.append(f"+{bonus} Base Manpower/Tile")

    if tech_key == "resource_refining":
        mult = 1.0 + level * c.RESOURCE_REFINING_BONUS_PER_LVL
        unlocks.append(f"Resource Income x{mult:.1f}")

    if tech_key == "trucks" and level == 1:
        unlocks.append("Motorized Infantry (buildable up to your current Infantry tech)")
        unlocks.append("Naval units can now be loaded into Trucks")

    if tech_key == "armored_personnel_carriers" and level == 1:
        unlocks.append("Mechanized Infantry (buildable up to your current Infantry tech)")

    if tech_key == "infantry_fighting_vehicle" and level == 1:
        unlocks.append("Infantry Fighting Vehicle (buildable up to your current Infantry tech)")

    if tech_key == "submarine":
        unlocks.append("Invisible to neutral/enemy nations unless engaged in active combat")

    return unlocks

def get_infantry_family_year(family_key, player_research, tech_tree):
    """Returns the highest year unlocked for infantry_type/motorized_infantry/
    mechanized_infantry/infantry_fighting_vehicle, or None if nothing is unlocked yet.

    motorized_infantry, mechanized_infantry, and infantry_fighting_vehicle aren't
    leveled techs of their own (see c.VEHICLE_INFANTRY_GATES) - owning the
    one-time "trucks"/"armored_personnel_carriers"/"infantry_fighting_vehicle"
    unlock lets a nation build that unit family up to whatever year its
    infantry_type research has reached, rather than requiring a separate
    multi-decade research track for each.
    """
    gate_tech = c.VEHICLE_INFANTRY_GATES.get(family_key)
    if gate_tech is not None:
        if player_research.get(gate_tech, 0) < 1:
            return None
        year_source = "infantry_type"
    else:
        year_source = family_key

    lvl = player_research.get(year_source, 0)
    if lvl <= 0:
        return None
    years = tech_tree.get(year_source, {}).get("years", [c.START_YEAR])
    return years[max(0, min(lvl - 1, len(years) - 1))]

def get_highest_infantry(nation_data_block, tech_tree, unit_library, allow_fuel_units=True):
    """Finds the highest level infantry unit the nation has researched, prioritizing mechanized/motorized upgrades."""
    res_levels = nation_data_block.get("research", {})

    def check_upgrade(family_key, name_fmt):
        year_val = get_infantry_family_year(family_key, res_levels, tech_tree)
        if year_val is not None:
            u_name = name_fmt.format(year_val)
            if u_name in unit_library: return u_name
        return None

    if allow_fuel_units:
        for tech, fmt in [("infantry_fighting_vehicle", "Infantry Fighting Vehicle Type {}"),
                          ("mechanized_infantry", "Mechanized Infantry Type {}"),
                          ("motorized_infantry", "Motorized Infantry Type {}")]:
            found = check_upgrade(tech, fmt)
            if found: return found

    # Fallback to standard (fuel-free) infantry -- but only if that's actually
    # buildable. A scenario that disabled Infantry entirely removes every
    # "Infantry Type <year>" entry from unit_library, so blindly returning the
    # START_YEAR name here would hand callers a unit that doesn't exist,
    # silently falling back to placeholder stats when they build it.
    default_name = f"Infantry Type {c.START_YEAR}"
    return check_upgrade("infantry_type", "Infantry Type {}") or (default_name if default_name in unit_library else None)

def get_upgrade_target(unit_type, player_research, unit_library, tech_tree):
    """Determines if a higher level of the current unit type is unlocked and returns its name."""
    base_name = get_base_unit_name(unit_type)
    
    # Strip "Type" to get the pure class ("Infantry", "Motorized Infantry") so string formatting doesn't duplicate it
    clean_base = re.sub(r'(?i)\s+type', '', base_name).strip()
    tech_key = get_unit_tech_key(clean_base)

    if clean_base == "Infantry":
        tech_key = "infantry_type"

    # Handle Year-based units (Infantry Type variants use "Type <year>"; Artillery
    # is roman-numeral leveled like Militia and falls through to the branch below)
    if tech_key in ["infantry_type", "motorized_infantry", "mechanized_infantry", "infantry_fighting_vehicle"]:
        year_val = get_infantry_family_year(tech_key, player_research, tech_tree)
        if year_val is None:
            return None

        target_name = f"{clean_base} Type {year_val}"

        if target_name in unit_library and target_name != unit_type:
            curr_year_match = re.search(r'\b(\d{4})\b', unit_type)
            if curr_year_match and int(year_val) > int(curr_year_match.group(1)):
                return target_name
        return None

    res_lvl = player_research.get(tech_key, 0)
    if res_lvl <= 0:
        return None

    # Handle Roman Numeral units
    target_name = f"{clean_base} {c.ROMAN_NUMERALS.get(res_lvl, str(res_lvl))}"
    if target_name in unit_library and target_name != unit_type:
        curr_lvl = roman_to_int(unit_type.replace(base_name, "").strip())
        if res_lvl > curr_lvl:
            return target_name

    return None

def get_best_preferred_unit(player_research, unit_library, preference_list):
    """Generic helper to find the highest preference unit unlocked."""
    for base_pref in reversed(preference_list):
        tech_key = base_pref.lower().replace(" ", "_")
        res_lvl = player_research.get(tech_key, 0)

        if res_lvl > 0:
            if base_pref in ["WW1 Armored Car", "WW1 Tank", "Dreadnought"]:
                return base_pref

            # Uses the constant rather than rebuilding the dict every call
            for check_lvl in range(res_lvl, 0, -1):
                test_name = f"{base_pref} {c.ROMAN_NUMERALS.get(check_lvl, str(check_lvl))}"
                if test_name in unit_library:
                    return test_name
    return None

def _best_unit_for_role(player_research, unit_library, role, preference_list):
    """Highest-scoring unlocked unit filling a role, by stats rather than by name.

    These two used to walk a hand-written list in constants.py backwards, so the
    last entry won: Main Battle Tanks and Destroyers the moment either was
    researched, whatever they cost, and Heavy Tanks, Artillery, Submarines and
    Carriers never. They keep their signatures because the random map generator
    seeds starting armies with them and mods may call them, but the answer now
    comes from map_logic.ai.ai_unit_eval like every other unit decision.

    The old preference list survives as the fallback for a caller with no
    research at all, where there is nothing to score.
    """
    from map_logic.ai import ai_unit_eval

    candidates = ai_unit_eval.buildable_units(player_research, unit_library)
    if candidates:
        prices = {res: 1.0 for res in ai_unit_eval.RESOURCES}
        ctx = ai_unit_eval.context(prices, volley=1000.0, stack=c.LANE_SLOTS_TYPICAL)
        best = ai_unit_eval.best_by_role(
            ai_unit_eval.evaluate(candidates, unit_library, ctx), role)
        if best:
            return best
    return get_best_preferred_unit(player_research, unit_library, preference_list)

def get_best_offensive_unit(player_research, unit_library):
    """Finds the best offensive unit the nation has unlocked."""
    from map_logic.ai import ai_unit_eval
    return _best_unit_for_role(player_research, unit_library,
                               ai_unit_eval.ROLE_ASSAULT, c.AI_OFFENSIVE_UNIT_PREFERENCE)

def get_best_naval_unit(player_research, unit_library):
    """Finds the best naval unit the nation has unlocked."""
    from map_logic.ai import ai_unit_eval
    return _best_unit_for_role(player_research, unit_library,
                               ai_unit_eval.ROLE_NAVAL, c.AI_NAVAL_UNIT_PREFERENCE)

REQ_GROUP_KEYS = ("OR", "AND")

def check_tech_requirements(res_levels, reqs, target_lvl=1):
    """Centralized tech requirement checker.

    A plain {tech: lvl, ...} mapping means every entry has to be met. "OR" and
    "AND" each take a LIST of such mappings and may be nested inside each other:
        {"AND": [{"heavy_tank": 4}, {"OR": [{"light_tank": 1}, {"armored_car": 1}]}]}
    Anything that is not a group key is read as a tech name.
    """
    if not reqs: return True

    def get_req_val(v):
        if isinstance(v, str) and v.startswith("MATCH_LEVEL"):
            val = target_lvl
            if "+" in v: val += int(v.split("+")[1])
            elif "-" in v: val -= int(v.split("-")[1])
            return val
        return v

    if "OR" in reqs:
        return any(check_tech_requirements(res_levels, sub, target_lvl) for sub in reqs["OR"])
    if "AND" in reqs:
        return all(check_tech_requirements(res_levels, sub, target_lvl) for sub in reqs["AND"])
    return all(res_levels.get(k, 0) >= get_req_val(v) for k, v in reqs.items())

def walk_tech_requirements(reqs):
    """Yields every (tech_name, required_level) leaf in a req block, at any nesting depth."""
    for key, val in (reqs or {}).items():
        if key in REQ_GROUP_KEYS:
            for sub in val:
                yield from walk_tech_requirements(sub)
        else:
            yield key, val

def strip_disabled_tech_requirements(reqs, disabled_techs):
    """Rebuilds a req block with every leaf naming a disabled tech bypassed
    (treated as already satisfied), so a scenario that disables a unit/building
    never leaves some other tech permanently unresearchable behind it.

    Mirrors the OR/AND walk in check_tech_requirements/walk_tech_requirements,
    but returns a smaller req tree instead of a bool: a satisfied AND clause is
    dropped, and an OR satisfied by one clause collapses the whole group.
    """
    if not reqs or not disabled_techs:
        return reqs or {}

    if "OR" in reqs:
        subs = [strip_disabled_tech_requirements(sub, disabled_techs) for sub in reqs["OR"]]
        if any(not sub for sub in subs):
            return {}
        return {"OR": subs}

    if "AND" in reqs:
        subs = [strip_disabled_tech_requirements(sub, disabled_techs) for sub in reqs["AND"]]
        subs = [sub for sub in subs if sub]
        if not subs:
            return {}
        if len(subs) == 1:
            return subs[0]
        return {"AND": subs}

    return {k: v for k, v in reqs.items() if k not in disabled_techs}

def is_training_troops(province):
    """Returns True if the province has any troops in its deployment queue."""
    return any("unit_type" in q for q in province.get("unit_queue", []))

def is_constructing_building(province):
    """Returns True if the province has any buildings in its deployment queue."""
    return any(q.get("order_type") == "BUILDING" for q in province.get("building_queue", []))

# ==========================================
# UNIFIED COMBAT & RENDERING HELPERS
# ==========================================

def calculate_unit_strength(unit):
    """Unified heuristic for a unit's military power."""
    return unit.get("attack", 0) + unit.get("defense", 0) + (unit.get("health", 0) / c.MILITARY_STRENGTH_HEALTH_DIVISOR)

def format_health_percent(unit):
    """Current health as a rounded percent of max, e.g. '(50%)' -- shown beside
    a unit's name so its reduced damage output (see combat_rules.
    health_damage_multiplier) has a visible cause."""
    max_hp = unit.get("max_health") or c.DEFAULT_UNIT_HP
    pct = max(0, round(unit.get("health", 0) / max_hp * 100))
    return f"({pct}%)"

def get_top_attackers(units, count=None):
    """The highest-attack units in a list, capped at a typical lane's front rank.

    An ESTIMATE, for the AI and the UI. It is not what the resolver does and
    must never be used to decide a fight: how many of these units actually fire
    depends on how many ways the tile splits into lanes, which only
    combat_rules.build_battle can answer. This used to be the one place combat
    width was applied, which is why the drift is worth naming here.
    """
    if count is None: count = c.LANE_SLOTS_TYPICAL
    return sorted(units, key=lambda x: x.get("attack", c.DEFAULT_UNIT_ATK), reverse=True)[:count]

def get_group_attack_sum(units, count=None):
    """Combined attack of a typical front rank. An estimate -- see get_top_attackers."""
    return sum(u.get("attack", c.DEFAULT_UNIT_ATK) for u in get_top_attackers(units, count))

def get_front_and_relief(units, count=None):
    """The front rank plus one relief wave: what a tile is worth reinforcing to.

    Measuring a tile by its top LANE_SLOTS_TYPICAL alone undercounts it, since
    the units behind the front are what replace it as it dies. Measuring by the
    whole stack overcounts it, since everything past the relief wave will not
    reach a slot before the tile resolves.
    """
    if count is None: count = int(c.LANE_SLOTS_TYPICAL * c.AI_RESERVE_DEPTH)
    return sorted(units, key=calculate_unit_strength, reverse=True)[:count]

def is_warship(unit_type):
    """Returns True if the unit is a combat naval vessel."""
    return is_naval_unit(unit_type) and not unit_type.startswith("Convoy")

def get_wrapped_x(x1, x2, map_w, loop_map):
    """Returns the modified x2 to account for shortest map wrap distance."""
    if loop_map:
        dx = x2 - x1
        if dx > map_w / 2: return x2 - map_w
        elif dx < -map_w / 2: return x2 + map_w
    return x2

# ==========================================
# ECONOMY QUERIES
# ==========================================

def get_factory_count(nation, map_data):
    """Counts the total number of factories a nation has (built and in-progress)."""
    count = 0
    for prov in map_data.values():
        if prov.get("owner") == nation:
            for b in prov.get("buildings", []):
                if "Factory" in b: count += 1
            for q in prov.get("building_queue", []):
                if "Factory" in q.get("item_name", ""): count += 1
    return count

def has_core(nation, province):
    """True if `nation` should be treated as cored on `province`.

    Under the "Disable Cores" scenario rule, every nation counts as cored on
    every tile it owns -- no non-core penalties, and nothing left to manually
    core or decore. This only affects that own-territory reading; it doesn't
    touch the underlying `cores` list on the province, which other systems
    (claims, puppet release, etc.) still rely on.
    """
    if getattr(c, "DISABLE_CORES", False):
        return True
    return nation in province.get("cores", [])

def get_core_cost(nation, map_data):
    """Calculates the cost to core a territory dynamically."""
    core_count = sum(1 for p in map_data.values() if nation in p.get("cores", []))
    
    base_cost = c.CORE_BASE_COST_MANPOWER
    scaling_cost = c.CORE_SCALING_COST_MANPOWER
    
    return {
        "cost_manpower": base_cost + (scaling_cost * core_count),
        "cost_materials": 0,
        "cost_fuel": 0,
        "time": c.CORE_CONSTRUCTION_TURNS,
        "group": "administration"
    }

def get_remove_core_cost(nation, map_data):
    """Returns the cost dictionary for removing foreign cores."""
    core_cost = get_core_cost(nation, map_data)
    manpower_cost = max(0, core_cost.get("cost_manpower", 0) // 2)
    return {
        "cost_manpower": manpower_cost,
        "cost_materials": max(0, manpower_cost // 2),
        "cost_fuel": max(0, core_cost.get("cost_fuel", 0) // 2),
        "time": c.REMOVE_CORE_TURNS,
        "group": "administration"
    }

def find_nearby_matching_core_tiles(origin_id, core_nation, current_owner, map_data, id_to_province, max_distance):
    """BFS from origin province to find tiles within max_distance that have core_nation as a core and are owned by current_owner."""
    candidates = []
    visited = {origin_id}
    queue = [(origin_id, 0)]
    
    while queue:
        current_id, dist = queue.pop(0)
        if dist >= max_distance:
            continue
            
        current_prov = id_to_province.get(current_id)
        if not current_prov:
            continue
            
        for n_id in current_prov.get("neighbors", []):
            if n_id in visited:
                continue
            visited.add(n_id)
            
            n_prov = id_to_province.get(n_id)
            if not n_prov:
                continue
            
            # Skip water tiles
            if is_water_province(n_prov):
                continue
                
            next_dist = dist + 1
            
            # Check if this tile qualifies as a rebellion spread target
            if (n_id != origin_id 
                and core_nation in n_prov.get("cores", []) 
                and n_prov.get("owner") == current_owner
                and not n_prov.get("units", [])):
                candidates.append(n_prov)
            
            if next_dist < max_distance:
                queue.append((n_id, next_dist))
    
    random.shuffle(candidates)
    return candidates

def generate_rebellion_name(cores_on_tile, nation_data):
    """Generates a thematic rebellion name from core adjectives and a random term.
    Returns (rebel_id, rebel_display_name)."""
    
    # Build combined adjective from all cores on the tile
    adjectives = []
    for core in cores_on_tile:
        core_data = nation_data.get(core, {})
        if core_data.get("is_rebellion", False):
            continue
            
        adj = core_data.get("adjective", "")
        if not adj:
            # Fallback: try loading from disk
            from data.io import country_io
            disk_data = country_io.get_country_stats(core)
            adj = disk_data.get("adjective", core)
        if adj:
            adjectives.append(adj)
    
    combined_adj = "-".join(adjectives) if adjectives else "Unknown"
    
    # Pick a random term
    term = random.choice(c.REBELLION_TERMS)
    
    base_name = f"{combined_adj} {term}"
    
    # Check for name collisions — only add number if needed, starting at 2
    existing_names = {d.get("name", "") for d in nation_data.values() if isinstance(d, dict)}
    
    if base_name not in existing_names:
        final_name = base_name
    else:
        suffix = 2
        while f"{base_name} {suffix}" in existing_names:
            suffix += 1
        final_name = f"{base_name} {suffix}"
    
    # Generate a safe ID (lowercase)
    rebel_id = final_name.lower()
    # Ensure ID uniqueness too
    if rebel_id in nation_data:
        suffix = 2
        while f"{rebel_id} {suffix}" in nation_data:
            suffix += 1
        rebel_id = f"{rebel_id} {suffix}"
    
    return rebel_id, final_name

def get_building_cost(b_name, nation, map_data, bldg_lib):
    """Dynamically scales the building cost, bypassing the JSON for Basic Factories.

    Time is left untouched -- it comes straight from bldg_lib, so it already
    reflects both the recipes.py default and any Construction Turns Editor override.
    """
    stats = bldg_lib.get(b_name, {}).copy()
    if b_name == "Basic Factory":
        count = get_factory_count(nation, map_data)
        x = c.BASIC_FACTORY_BASE_COST_X + (c.BASIC_FACTORY_COST_MULTIPLIER * count)
        stats["cost_materials"] = x * 2
        stats["cost_manpower"] = x
        stats["cost_fuel"] = 0
    return stats

def _modify_resources(nation_data_block, costs_dict, is_refund=False):
    """Unified helper to add or subtract resources from a nation."""
    modifier = 1 if is_refund else -1
    for res in c.ECON_RESOURCE_KEYS:
        new_val = nation_data_block.get(res, 0) + (costs_dict.get(f"cost_{res}", 0) * modifier)
        nation_data_block[res] = max(0, new_val) if not is_refund else new_val

def refund_resources(nation_data_block, costs_dict): _modify_resources(nation_data_block, costs_dict, is_refund=True)
def deduct_resources(nation_data_block, costs_dict): _modify_resources(nation_data_block, costs_dict, is_refund=False)

def refund_queue_item(nation_data_block, item, owner=None, map_data=None):
    """Refunds one cancelled production/construction queue entry.

    Entries carry a "refund" dict recording what was actually paid, which is
    what a cancellation should hand back -- the library price can have changed
    since (a discount, a tech, a different owner). Older saves predate that
    field, so fall back to pricing the item from the libraries.

    Callers used to spell this out themselves, and one of them
    (map_logic/ai/automation_logic.py) read a "building_type" key that queue
    entries never had, so cancelling a building queue refunded nothing at all.
    """
    if "refund" in item:
        refund_resources(nation_data_block, item["refund"])
        return

    stats = {}
    if item.get("order_type") == "BUILDING":
        stats = get_building_cost(item.get("item_name"), owner, map_data, get_building_library())
    elif "unit_type" in item:
        stats = get_unit_library().get(item["unit_type"], {})
    refund_resources(nation_data_block, stats)


def can_afford(nation_data_block, costs_dict):
    """Returns True if the nation has enough resources to cover the costs."""
    return all(nation_data_block.get(res, 0) >= costs_dict.get(f"cost_{res}", 0) for res in c.ECON_RESOURCE_KEYS)

def execute_trade_transfer(proposer_data, target_data, params):
    """Executes a trade transfer between two nations, exchanging escrowed and requested resources."""
    for res in c.TRADE_RESOURCE_KEYS:
        # Target gains proposer's escrow
        target_data[res] = target_data.get(res, 0) + params.get(f"give_{res}", 0)
        # Target pays their side
        actual_take = min(params.get(f"take_{res}", 0), target_data.get(res, 0))
        target_data[res] -= actual_take
        # Proposer receives their side
        proposer_data[res] = proposer_data.get(res, 0) + actual_take

def cancel_trade_escrow(proposer_data, params):
    """Refunds escrowed resources from a pending trade proposal."""
    for res in c.TRADE_RESOURCE_KEYS:
        proposer_data[res] = proposer_data.get(res, 0) + params.get(f"give_{res}", 0)

def get_siphon_rates(nation_data_block):
    """Returns a puppet's per-resource siphon rates, creating the block if missing."""
    return nation_data_block.setdefault("siphon_rates", {res: 0.0 for res in c.ECON_RESOURCE_KEYS})

def calculate_all_economies(map_data, nation_data):
    """Standardized economy calculator. Single source of truth for UI and Turn Processor."""
    unit_lib = get_unit_library()
    bldg_lib = get_building_library()

    # Initialize data structure for all active nations
    econ_data = {}
    for name, n_data in list(nation_data.items()):
        res_data = n_data.get("research", {})
        bergius_bonus = c.BERGIUS_FUEL_BONUS if res_data.get("bergius_process", 0) > 0 else 0
        manpower_bonus = res_data.get("general_recruitment", 0) * c.GENERAL_RECRUITMENT_BONUS
        resource_refining_mult = 1.0 + res_data.get("resource_refining", 0) * c.RESOURCE_REFINING_BONUS_PER_LVL

        dyn_yields = {
            "manpower": c.BASE_YIELDS["manpower"] + manpower_bonus,
            "materials": c.BASE_YIELDS["materials"],
            "fuel": c.BASE_YIELDS["fuel"] 
        }
        
        breakdown = {
            res: {"base": c.COUNTRY_BASE_YIELDS[res] + (bergius_bonus if res == "fuel" else 0), 
                  "core": 0, "non_core": 0, "buildings": 0, "resources": 0, 
                  "conversion": 0, "conscription": 0, "siphon": 0, "siphon_income": 0}
            for res in c.ECON_RESOURCE_KEYS
        }

        econ_data[name] = {"dynamic_yields": dyn_yields, "breakdown": breakdown, "upkeep": {r: 0 for r in c.ECON_RESOURCE_KEYS}, "total_inc": {r: 0 for r in c.ECON_RESOURCE_KEYS}, "resource_mult": resource_refining_mult}

    # Single efficient pass over the map
    for province in map_data.values():
        owner = province.get("owner")
        
        # --- INCOME LOGIC ---
        if owner and owner in econ_data and owner not in c.UNPLAYABLE_NATIONS:
            is_core = has_core(owner, province)
            cat = "core" if is_core else "non_core"
            bd = econ_data[owner]["breakdown"]
            dyn_yields = econ_data[owner]["dynamic_yields"]

            # Base tile yields based on ownership tier
            for res in c.ECON_RESOURCE_KEYS:
                mult = 1.0 if is_core else c.NON_CORE_MULTIPLIERS[res]
                bd[res][cat] += mult * dyn_yields[res]

            # Natural Resources
            res = province.get("resources", {})
            if isinstance(res, dict):
                refining_mult = econ_data[owner]["resource_mult"]
                bd["materials"]["resources"] += int(res.get("Iron", 0)) * (1.0 if is_core else c.NON_CORE_MULTIPLIERS["materials"]) * refining_mult
                bd["fuel"]["resources"] += (int(res.get("Coal", 0)) + int(res.get("Oil", 0))) * (1.0 if is_core else c.NON_CORE_MULTIPLIERS["fuel"]) * refining_mult
                bd["manpower"]["resources"] += int(res.get("Wheat", 0)) * (1.0 if is_core else c.NON_CORE_MULTIPLIERS["manpower"]) * refining_mult

            # Buildings
            building_mult = 1.0 if is_core else c.NON_CORE_BUILDING_MULTIPLIER
            for b_name in province.get("buildings", []):
                stats = bldg_lib.get(b_name, {})
                for res in c.ECON_RESOURCE_KEYS:
                    bd[res]["buildings"] += int(stats.get(f"prod_{res}", 0) * building_mult)

            # Basic Factory transitional construction yields
            for q in province.get("building_queue", []):
                if q.get("item_name") == "Basic Factory":
                    rem = q.get("turns_remaining", c.BASIC_FACTORY_TURNS)
                    yield_mat = 400 if rem < 5 else (320 if rem < 9 else (240 if rem < 13 else (160 if rem < 17 else 80)))
                    bd["materials"]["buildings"] += int(yield_mat * building_mult)

        # --- UPKEEP LOGIC ---
        for unit in province.get("units", []):
            u_owner = unit.get("owner")
            if u_owner in econ_data:
                # FETCH ORIGINAL TYPE SO WE KEEP CHARGING UPKEEP DURING TRANSIT
                u_type = unit.get("original_type", unit.get("type"))
                upkeep = get_unit_upkeep(unit_lib.get(u_type, {}))
                for res in c.ECON_RESOURCE_KEYS:
                    econ_data[u_owner]["upkeep"][res] += upkeep[res]

    # Helper for converting one resource to another via the dynamic sliders
    def _process_conversion(data, src, tgt, tag, rate, ratio):
        raw_inc = sum(data["breakdown"][src].values())
        divisor = max(1, int(1 / ratio) if ratio > 0 else 1)
        if rate > 0 and raw_inc >= divisor:
            convert_amount = int(raw_inc * rate)
            convert_amount = (convert_amount // divisor) * divisor
            data["breakdown"][src][tag] = -convert_amount
            data["breakdown"][tgt][tag] = int(convert_amount * ratio)

    # Finalize totals and calculate conversions
    for name, data in econ_data.items():
        n_data = nation_data.get(name, {})
        
        # Conscription (1.0 = keep all, 0.0 = convert all)
        _process_conversion(data, "manpower", "materials", "conscription", 1.0 - n_data.get("conscription_slider", 1.0), c.CONSCRIPTION_RATIO)
        # Fuel Conversion
        _process_conversion(data, "materials", "fuel", "conversion", min(n_data.get("mat_to_fuel_slider", 0.0), get_max_fuel_conversion(n_data)), c.FUEL_CONVERSION_RATIO)

        for res in c.ECON_RESOURCE_KEYS:
            data["total_inc"][res] = sum(data["breakdown"][res].values())

        # --- PUPPET SIPHONING LOGIC ---
        master = n_data.get("master", "")
        if master and master in econ_data and n_data.get("puppet_type") == c.PUPPET_TYPE_INTEGRATED:
            siphon_rates = get_siphon_rates(n_data)

            for res in c.ECON_RESOURCE_KEYS:
                siphon_amt = int(max(0, data["total_inc"][res]) * min(c.MAX_PUPPET_SIPHON, siphon_rates.get(res, 0.0)))
                data["total_inc"][res] -= siphon_amt
                econ_data[master]["total_inc"][res] += siphon_amt
                data["breakdown"][res]["siphon"] = -siphon_amt
                econ_data[master]["breakdown"][res]["siphon_income"] = econ_data[master]["breakdown"][res].get("siphon_income", 0) + siphon_amt

    return econ_data

_NUMBER_ABBREV_TIERS = [
    (1_000_000_000_000, "T"),
    (1_000_000_000, "B"),
    (1_000_000, "M"),
    (1_000, "K"),
]

def format_number(value):
    """Abbreviates a number to at most 3 significant digits (e.g. 1543 -> '1.54K',
    1234567 -> '1.23M'). Used for in-game resource/unit displays; economy screens
    that need exact figures should format their own values instead of calling this."""
    try:
        num = float(value)
    except (TypeError, ValueError):
        return str(value)

    sign = "-" if num < 0 else ""
    num = abs(num)

    if num < 1000:
        return f"{sign}{int(round(num))}"

    divisor, suffix = next(d_s for d_s in _NUMBER_ABBREV_TIERS if num >= d_s[0])
    scaled = num / divisor
    decimals = 0 if scaled >= 100 else (1 if scaled >= 10 else 2)
    scaled = round(scaled, decimals)

    # Rounding can push into the next tier (e.g. 999.995K -> "1000K"); bump up
    # a tier when one exists. The top tier (T) has none, so it just grows digits,
    # e.g. "1000T", as intended once numbers run past the trillions.
    if scaled >= 1000 and suffix != "T":
        idx = next(i for i, d_s in enumerate(_NUMBER_ABBREV_TIERS) if d_s[1] == suffix)
        divisor, suffix = _NUMBER_ABBREV_TIERS[idx - 1]
        scaled = num / divisor
        decimals = 0 if scaled >= 100 else (1 if scaled >= 10 else 2)
        scaled = round(scaled, decimals)

    text = f"{scaled:.{decimals}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")

    return f"{sign}{text}{suffix}"

def get_resource_hud_strings(map_screen, include_net=False, target_nation=None):
    """Generates unified resource tracking strings and colors for all UI HUDs."""
    is_tactical = map_screen.tactical_mode and map_screen.player_unit

    if target_nation is None:
        target_nation = map_screen.player_country
        
    if is_tactical and target_nation == map_screen.player_country:
        manpower = int(map_screen.player_manpower)
        materials = int(map_screen.player_materials)
        fuel = int(map_screen.player_fuel)
    else:
        n_data = map_screen.nation_data.get(target_nation, {})
        manpower = int(n_data.get("manpower", 0))
        materials = int(n_data.get("materials", 0))
        fuel = int(n_data.get("fuel", 0))

    res_order = [
        ("manpower", "Manpower", c.COLOR_RESOURCE_MANPOWER, manpower),
        ("materials", "Materials", c.COLOR_RESOURCE_MATERIALS, materials),
        ("fuel", "Fuel", c.COLOR_RESOURCE_FUEL, fuel)
    ]
    
    total_inc = {r: 0 for r in c.ECON_RESOURCE_KEYS}
    total_upkeep = {r: 0 for r in c.ECON_RESOURCE_KEYS}

    if include_net:
        if is_tactical and target_nation == map_screen.player_country:
            u_type = map_screen.player_unit.get("original_type", map_screen.player_unit.get("type"))
            stats = get_unit_library().get(u_type, {})
            total_inc = get_unit_upkeep(stats)
            morale = map_screen.player_unit.get("morale", c.DEFAULT_UNIT_MORALE)
            desertion_cost = total_inc.get("manpower", 0) * ((100.0 - float(morale)) / 100.0)
            total_upkeep["manpower"] = desertion_cost
        else:
            if not hasattr(map_screen, 'econ_cache_time') or pygame.time.get_ticks() - map_screen.econ_cache_time > 1000 or getattr(map_screen, 'econ_cache_target', None) != target_nation:
                map_screen.econ_cache = get_economy_projections(target_nation, map_screen.map_data, map_screen.nation_data)
                map_screen.econ_cache_time = pygame.time.get_ticks()
                map_screen.econ_cache_target = target_nation
                
            cached = map_screen.econ_cache
            if cached and len(cached) == 3:
                total_inc, total_upkeep, _ = cached

    def fmt_net(inc, exp):
        net = int(inc - exp)
        return f" (+{format_number(net)})" if net >= 0 else f" ({format_number(net)})"

    hud_strings = []
    for res_key, name, color, p_val in res_order:
        net_str = fmt_net(total_inc.get(res_key, 0), total_upkeep.get(res_key, 0)) if include_net else ""

        if is_tactical and target_nation == map_screen.player_country:
            if res_key == "manpower":
                max_val = c.TACTICAL_MAX_MANPOWER
            elif res_key == "materials":
                max_val = c.TACTICAL_MAX_MATERIALS
            else:
                max_val = c.TACTICAL_MAX_FUEL

            hud_strings.append((f"{name}: {format_number(p_val)}/{format_number(int(max_val))}{net_str}", color))
        else:
            hud_strings.append((f"{name}: {format_number(p_val)}{net_str}", color))
            
    return hud_strings

def get_economy_projections(target_nation, map_data, nation_data):
    """Pulls a specific nation's UI data from the unified calculator."""
    all_econ = calculate_all_economies(map_data, nation_data)
    p_econ = all_econ.get(target_nation, {})
    
    if not p_econ:
        return (
            {r: 0 for r in c.ECON_RESOURCE_KEYS},
            {r: 0 for r in c.ECON_RESOURCE_KEYS},
            {r: {} for r in c.ECON_RESOURCE_KEYS}
        )
        
    return p_econ.get("total_inc"), p_econ.get("upkeep"), p_econ.get("breakdown")

def get_minimum_tank_count(material_income):
    """Calculates the baseline number of tanks an AI should force itself to field."""
    count = math.ceil((material_income - c.AI_TANK_MIN_BASE_THRESHOLD) / c.AI_TANK_MIN_DIVISOR)
    return max(0, count)

# ==========================================
# MAP & ENTITY QUERIES
# ==========================================

def create_unit_dict(unit_type, owner, unit_library):
    """Generates a standard base unit dictionary to avoid redundant stat parsing."""
    stats = unit_library.get(unit_type, {})
    hp = stats.get("health", c.DEFAULT_UNIT_HP)
    return {
        "type": unit_type,
        "owner": owner,
        "health": hp,
        "max_health": hp,
        "morale": stats.get("morale", c.DEFAULT_UNIT_MORALE),
        "speed": stats.get("speed", c.DEFAULT_UNIT_SPD),
        "attack": stats.get("attack", c.DEFAULT_UNIT_ATK),
        "defense": stats.get("defense", c.DEFAULT_UNIT_DEF),
        "level": 0,
        "order": {"type": "MOVE", "path": []}
    }

def migrate_units_to_current_stats(map_data, unit_library):
    """
    Rescales every unit's frozen stats (max_health/attack/defense/speed/naval_unit)
    to match the currently loaded unit_library, preserving each unit's current
    health as a percentage of its (possibly changed) max health.

    Used when a save/map's version doesn't match c.GAME_VERSION (or has no
    version at all), since older saves carry stat values baked in at whatever
    balance patch they were created under.
    """
    for province in map_data.values():
        for unit in province.get("units", []):
            stats = unit_library.get(unit.get("type"))
            if not stats:
                continue

            old_max_health = unit.get("max_health", 1)
            hp_pct = unit.get("health", old_max_health) / max(1, old_max_health)

            unit["max_health"] = stats.get("health", c.DEFAULT_UNIT_HP)
            unit["attack"] = stats.get("attack", c.DEFAULT_UNIT_ATK)
            unit["defense"] = stats.get("defense", c.DEFAULT_UNIT_DEF)
            unit["speed"] = stats.get("speed", c.DEFAULT_UNIT_SPD)
            unit["naval_unit"] = stats.get("naval_unit", is_naval_unit(unit.get("type", "")))

            unit["health"] = unit["max_health"] * hp_pct

def build_save_dict(map_screen):
    """Standardizes the construction of the map save state dictionary."""
    save_dict = {
        "version": c.GAME_VERSION,
        "generated_at": datetime.now().isoformat(),
        "date": {
            "day": map_screen.time_manager.day,
            "month": map_screen.time_manager.month_index,
            "year": map_screen.time_manager.year,
            "total_turns": map_screen.time_manager.total_turns
        },
        "loop_map": getattr(map_screen, 'loop_map', False),
        "player_country": map_screen.player_country,
        "active_players": map_screen.active_players,
        "current_player_index": getattr(map_screen, 'current_player_index', 0),
        "scenario_settings": getattr(map_screen, 'scenario_settings', {}),
        "script_variables": getattr(map_screen, 'script_variables', []),
        "default_research": getattr(map_screen, 'default_research', None),
        "nation_data": map_screen.nation_data,
        "provinces": {}
    }
    
    for data in map_screen.map_data.values():
        save_dict["provinces"][data["json_key"]] = {
            "owner": data["owner"],
            "cores": data.get("cores", []),
            "is_coastal": data.get("is_coastal", False),
            "units": data.get("units", []),
            "building_queue": data.get("building_queue", []),
            "unit_queue": data.get("unit_queue", []),
            "orders": data.get("orders", []),
            "resources": data.get("resources", []),
            "buildings": data.get("buildings", [])
        }
    return save_dict

def get_clicked_province(mouse_pos, map_screen):
    """Resolves the province dictionary corresponding to a screen click."""
    mx, my = mouse_pos
    cam = map_screen.camera
    wx = ((mx / cam.zoom) + cam.pos.x) % map_screen.map_w
    wy = ((my - map_screen.top_ui_height) / (cam.zoom * cam.tilt_factor)) + cam.pos.y
    
    if 0 <= wy < map_screen.map_h:
        safe_x = max(0, min(int(wx), map_screen.map_w - 1))
        safe_y = max(0, min(int(wy), map_screen.map_h - 1))
        color = map_screen.id_map.get_at((safe_x, safe_y))
        return map_screen.map_data.get((color.r, color.g, color.b))
    return None

def world_to_screen(world_pos, map_screen, offset=0):
    """Converts world map coordinates to screen pixel coordinates."""
    cam = map_screen.camera
    sx = (world_pos[0] + offset - cam.pos.x) * cam.zoom
    sy = (world_pos[1] - cam.pos.y) * cam.zoom * cam.tilt_factor + map_screen.top_ui_height
    return sx, sy

def get_neighboring_nations(nation, map_data, id_to_province):
    """Scans the map and returns a set of all nations bordering the specified nation."""
    neighbors = set()
    for prov in map_data.values():
        if prov.get("owner") == nation:
            for n_id in prov.get("neighbors", []):
                n_prov = id_to_province.get(n_id)
                if n_prov and n_prov.get("owner") not in c.UNPLAYABLE_NATIONS and n_prov.get("owner") != nation:
                    neighbors.add(n_prov.get("owner"))
    return neighbors

def get_nation_provinces_and_units(nation, map_data):
    """Returns a tuple of (list_of_provinces, list_of_units) owned by the nation."""
    owned_provs = []
    owned_units = []
    for prov in map_data.values():
        if prov.get("owner") == nation:
            owned_provs.append(prov)
        for unit in prov.get("units", []):
            if unit.get("owner") == nation:
                owned_units.append((unit, prov))
    return owned_provs, owned_units

def get_living_nations(map_data):
    """Scans the map and returns a set of all nations that currently own at least one province."""
    active_nations = set()
    for prov in map_data.values():
        owner = prov.get("owner")
        if owner and owner not in c.UNPLAYABLE_NATIONS:
            active_nations.add(owner)
    return active_nations

def get_active_playable_nations(map_data, nation_data):
    """Returns the sorted-by-id list of playable nations that currently own at least one province."""
    if not map_data:
        return []
    active_owners = set(p.get("owner") for p in map_data.values())
    return [cid for cid, data in nation_data.items() if data.get("is_playable") and cid in active_owners]

def cleanup_ghost_wars(nation_data, living_nations):
    """Wipes at_war_with lists for dead nations and strips dead enemies from living nations' lists."""
    for nation, data in nation_data.items():
        if "at_war_with" in data:
            if nation not in living_nations:
                data["at_war_with"] = []
            else:
                data["at_war_with"] = [enemy for enemy in data["at_war_with"] if enemy in living_nations]

def is_occupying_all_cores(nation, target_nation, map_data):
    """Returns True if 'nation' occupies ALL cores of 'target_nation'."""
    has_cores = False
    for prov in map_data.values():
        if target_nation in prov.get("cores", []):
            has_cores = True
            if prov.get("owner") != nation:
                return False
    return has_cores

def is_occupying_tiles(nation, tile_ids_str, id_to_province):
    """Returns True if 'nation' occupies all of the specified tile IDs."""
    if not tile_ids_str: return False
    t_ids = [tid.strip() for tid in str(tile_ids_str).split(",") if tid.strip()]
    if not t_ids: return False
    
    for tid in t_ids:
        try:
            prov_id = int(tid)
        except ValueError:
            continue
        prov = id_to_province.get(prov_id)
        if not prov or prov.get("owner") != nation:
            return False
    return True

# ==========================================
# TIME & RESEARCH QUERIES
# ==========================================

def get_exact_year(time_manager):
    """Calculates the exact fractional year based on the game's 360-day calendar."""
    return time_manager.year + (time_manager.month_index / 12.0) + (time_manager.day / 360.0)

def get_research_multiplier(current_exact_year, target_year):
    """Calculates the ahead-of-time penalty multiplier."""
    years_ahead = target_year - current_exact_year
    if years_ahead > 0:
        return 0.5 ** years_ahead
    return 1.0


# ==========================================
# DIPLOMATIC STATUS & UI QUERIES
# ==========================================

def is_playable(nation, nation_data):
    """Safely checks if a nation exists and is a playable entity."""
    if nation in c.UNPLAYABLE_NATIONS:
        return False
    return nation_data.get(nation, {}).get("is_playable", False)

def get_enemies(nation, nation_data):
    """Who a nation is at war with. The one place the key name is spelled out."""
    return nation_data.get(nation, {}).get("at_war_with", [])

def get_diplomatic_status(sender, target, nation_data):
    """Safely unpacks the pending diplomacy dictionary. Returns (action_string, turns_int)."""
    pending = nation_data.get(sender, {}).get("pending_diplomacy", {}).get(target, {})
    
    # Handle legacy saves where it might just be a string
    action = pending.get("action", "") if isinstance(pending, dict) else pending
    turns = pending.get("turns", 0) if isinstance(pending, dict) else 0
    
    # Failsafe
    if isinstance(action, dict): 
        action = ""
        
    return action, turns

def get_message_draft(sender, target, nation_data):
    """Returns the draft text if one exists and hasn't been sent."""
    draft_list = nation_data.get(sender, {}).get("draft_lists", {}).get(target, [])
    if draft_list:
        return "\n".join(draft_list)

    pending = nation_data.get(sender, {}).get("pending_diplomacy", {}).get(target, {})
    if isinstance(pending, dict) and pending.get("turns", 0) == 0:
        action = pending.get("action", "")
        if isinstance(action, str) and action.startswith("MSG:"):
            return action[4:]
        if not action and "message" in pending:
            return pending["message"]
    return ""

def is_diplomat_busy(sender, target, nation_data):
    """Returns True if the diplomat is currently traveling."""
    action, turns = get_diplomatic_status(sender, target, nation_data)
    is_unilateral = action in c.UNILATERAL_ACTIONS

    if is_unilateral and turns > 0:
        return False
        
    # Allow queueing new messages/actions if the current action is just a message in transit
    #if str(action).startswith("MSG:") and turns > 0:
    #   return False
        
    if turns > 0: 
        return True
    return False

def get_incoming_justifications_count(nation, nation_data, id_to_province):
    """Returns the number of active claim justifications against the given nation."""
    count = 0
    for other_nation, data in list(nation_data.items()):
        if other_nation == nation: continue
        queue = data.get("claim_queue", [])
        if queue:
            q = queue[0]  # Only check the active justification
            if q.get("turns_left", 0) < c.CLAIM_TURN_NON_CORE: # Hide if made this turn
                prov = id_to_province.get(q["prov_id"])
                if prov and prov.get("owner") == nation:
                    count += 1
    return count

def has_unanswered_request(nation, other_nation, nation_data):
    """True if other_nation has a live proposal waiting on nation's answer.

    The single source of truth for "this contact needs your attention" -- the map
    badge and the per-contact badge in the messages screen both read it, so they
    can never disagree about what is outstanding.
    """
    req = nation_data.get(other_nation, {}).get("pending_diplomacy", {}).get(nation)
    if not isinstance(req, dict):
        return False
    if req.get("turns", 0) <= 0 or req.get("action", "") not in c.BILATERAL_ACTIONS:
        return False

    # Already answered this turn -- the reply just hasn't been processed yet.
    my_response = nation_data.get(nation, {}).get("diplo_responses", {}).get(other_nation)
    if isinstance(my_response, dict) and my_response.get("verdict"):
        return False
    return True

def get_pending_request_senders(nation, nation_data):
    """Every nation currently waiting on an answer from `nation`.

    Iterates a snapshot of the keys: this runs from the badge-drawing path, which
    can land mid-turn while nation_data is still growing (faction war maps, newly
    released nations), and a live iterator would blow up there.
    """
    return [other for other in list(nation_data)
            if other != nation and has_unanswered_request(nation, other, nation_data)]

def get_unread_message_count(nation, nation_data):
    """Returns the total number of unread messages and unanswered requests for a nation."""
    # If the user is the spectator, count unread messages across ALL playable nations
    if nation == "Spectator":
        # Calling get_pending_request_senders() once per playable nation -- as this
        # used to -- reruns its full nation_data scan every time, which makes the
        # whole thing O(nations^2). Every pending request lives as one entry in its
        # sender's own pending_diplomacy dict, so a single pass building a
        # recipient -> count map does the exact same accounting in O(nations +
        # pending requests) instead, with identical results.
        pending_counts = {}
        for sender, sender_data in nation_data.items():
            for recipient, req in sender_data.get("pending_diplomacy", {}).items():
                if not isinstance(req, dict):
                    continue
                if req.get("turns", 0) <= 0 or req.get("action", "") not in c.BILATERAL_ACTIONS:
                    continue
                my_response = nation_data.get(recipient, {}).get("diplo_responses", {}).get(sender)
                if isinstance(my_response, dict) and my_response.get("verdict"):
                    continue
                pending_counts[recipient] = pending_counts.get(recipient, 0) + 1

        total_unread = 0
        for n_name, n_data in nation_data.items():
            if n_data.get("is_playable", False):
                inbox = n_data.get("inbox", [])
                total_unread += sum(1 for msg in inbox if not msg.get("spectator_read", False))
                total_unread += pending_counts.get(n_name, 0)
        return total_unread

    # Standard logic for normal players
    inbox = nation_data.get(nation, {}).get("inbox", [])
    # Ignore messages where the sender is the nation itself
    unread_count = sum(1 for msg in inbox if not msg.get("read", False) and msg.get("sender") != nation)
    unread_count += len(get_pending_request_senders(nation, nation_data))

    return unread_count

def has_free_research_slots(nation, nation_data):
    """Returns True if the nation is researching fewer than c.RESEARCH_SLOTS techs."""
    # Prevent the research notification from popping up for the Spectator or Ocean
    if nation in c.UNPLAYABLE_NATIONS:
        return False

    queue = nation_data.get(nation, {}).get("research_queue", [])
    return len(queue) < c.RESEARCH_SLOTS

def has_active_truce(nation_a, nation_b, nation_data):
    """Returns True if there is an active non-aggression pact/truce between the two nations."""
    if nation_a not in nation_data: return False
    return nation_data[nation_a].get("truces", {}).get(nation_b, 0) > 0

def get_active_truces(nation, nation_data):
    """Nations this one currently holds a truce with, mapped to turns remaining."""
    truces = nation_data.get(nation, {}).get("truces", {})
    return {other: turns for other, turns in truces.items() if turns > 0}

def get_relation_score(nation_a, nation_b, nation_data, id_to_province=None):
    """Calculates dynamic relations based on flat state modifiers and temporary modifiers."""
    if nation_a == nation_b:
        return 0
        
    score = 0
    if are_at_war(nation_a, nation_b, nation_data):
        score += c.REL_MOD_AT_WAR
    elif are_in_same_faction(nation_a, nation_b, nation_data):
        score += c.REL_MOD_IN_FACTION
        
    # Common Enemy Bonus
    enemies_a = set(get_enemies(nation_a, nation_data))
    enemies_b = set(get_enemies(nation_b, nation_data))
    
    # If the intersection contains anything, they share at least one enemy.
    # The flat bonus is applied once, capping the effect.
    if enemies_a & enemies_b:
        score += c.REL_MOD_COMMON_ENEMY
        
    # master and puppet mechanics
    master_a = nation_data.get(nation_a, {}).get("master", "")
    master_b = nation_data.get(nation_b, {}).get("master", "")
    if master_b == nation_a:
        score += c.REL_MOD_MASTER_OF
    elif master_a == nation_b:
        score += c.REL_MOD_PUPPET_OF
                
    # Apply all decaying temporary modifiers
    temp_mods = nation_data.get(nation_a, {}).get("temp_modifiers", {}).get(nation_b, {})
    for entry in temp_mods.values():
        score += modifier_value(entry)
        
    if id_to_province:
        claims_a = nation_data.get(nation_a, {}).get("claims", [])
        claims_b = nation_data.get(nation_b, {}).get("claims", [])
        
        a_claims_b = 0
        b_claims_a = 0
        
        for prov in id_to_province.values():
            owner = prov.get("owner")
            if owner == nation_b:
                if nation_a in prov.get("cores", []) or prov["id"] in claims_a:
                    a_claims_b += 1
            elif owner == nation_a:
                if nation_b in prov.get("cores", []) or prov["id"] in claims_b:
                    b_claims_a += 1
        
        penalty_per_claim = abs(c.REL_MOD_PER_CLAIM)
        max_penalty = abs(c.REL_MOD_MAX_CLAIM_PENALTY)
        
        claim_penalty = min(max_penalty, (a_claims_b + b_claims_a) * penalty_per_claim)
        score -= claim_penalty
        
    return score

# A relation modifier is stored either as a bare int -- every modifier written
# before this existed, and every one in an old save -- or as a dict carrying how
# fast it fades and how long it lasts:
#
#     -40                                              decays 1/turn, as always
#     {"value": -40, "decay": 0, "turns": 60, ...}     durable: 60 turns, no fade
#
# Nothing migrates in place. An int keeps behaving exactly as it always has, for
# as long as it exists, and a mixed dict is fine. Grudges that actually last are
# what make a betrayal cost something later.

def modifier_value(entry):
    """The score contribution of a modifier, in either storage form."""
    if isinstance(entry, dict):
        try:
            return int(entry.get("value", 0))
        except (TypeError, ValueError):
            return 0
    try:
        return int(entry)
    except (TypeError, ValueError):
        return 0


def modifier_decay(entry):
    """How much this modifier fades toward zero per turn. 0 means never."""
    if isinstance(entry, dict):
        try:
            return max(0, int(entry.get("decay", 1)))
        except (TypeError, ValueError):
            return 1
    return 1


def modifier_turns(entry):
    """Turns left before it expires outright, or None for no expiry."""
    if isinstance(entry, dict) and entry.get("turns") is not None:
        try:
            return int(entry["turns"])
        except (TypeError, ValueError):
            return None
    return None


def add_temporary_modifier(nation_a, nation_b, mod_name, value, nation_data,
                           decay=1, turns=None, reason=""):
    """Adds or updates a temporary relation modifier. General opinions stack.

    decay/turns/reason are keyword arguments with the old behaviour as their
    defaults, so every existing call site is unchanged.
    """
    if nation_a not in nation_data: return
    mods = nation_data.setdefault(nation_a, {}).setdefault("temp_modifiers", {}).setdefault(nation_b, {})

    if mod_name == "general":
        value = modifier_value(mods.get("general", 0)) + value

    if decay == 1 and turns is None and not reason:
        # Plain form for a plain modifier, so saves stay readable and old builds
        # can still make sense of the common case.
        mods[mod_name] = value
    else:
        mods[mod_name] = {"value": value, "decay": decay, "turns": turns, "reason": reason}

def lerp_color(c1, c2, t):
    """Linearly interpolates between two RGB color tuples by factor t (0.0-1.0)."""
    return (int(c1[0] + (c2[0] - c1[0]) * t),
            int(c1[1] + (c2[1] - c1[1]) * t),
            int(c1[2] + (c2[2] - c1[2]) * t))

def get_relation_color(score):
    """Returns a dynamic color mapped to the relation score (-200 to 200)."""
    score = max(-200, min(200, score))

    if score > 100:
        return lerp_color(c.COLOR_REL_POS, c.COLOR_REL_MAX_POS, (score - 100) / 100.0)
    elif score > 0:
        return lerp_color(c.COLOR_REL_NEU, c.COLOR_REL_POS, score / 100.0)
    elif score < -100:
        return lerp_color(c.COLOR_REL_NEG, c.COLOR_REL_MAX_NEG, (-score - 100) / 100.0)
    elif score < 0:
        return lerp_color(c.COLOR_REL_NEU, c.COLOR_REL_NEG, -score / 100.0)
        
    return c.COLOR_REL_NEU

# ==========================================
# STRING & UNIT QUERIES
# ==========================================

def is_foreign_playable(owner, player_country, nation_data):
    """Returns True if the owner is a valid, playable foreign nation."""
    if player_country not in nation_data:
        return False
    return owner != player_country and owner in nation_data and nation_data[owner].get("is_playable", False)

def get_base_unit_name(unit_name):
    """Strips years and roman numerals to return the base unit class (e.g. 'Infantry Type 1850' -> 'Infantry')."""
    base = re.sub(r'\s+\d{4}$', '', unit_name)
    return re.sub(r'\s+[IVXLCDM]+$', '', base).strip()

# Word-for-word shorthand used ONLY by get_condensed_unit_name, for the tightly
# spaced production unit list and garrison rosters. Every other screen shows
# the full proper name. "Type" is dropped outright since it's a redundant
# connector word before the year/tier (e.g. "Infantry Type 1940" -> "Inf 1940").
CONDENSED_UNIT_NAME_WORDS = {
    "Type": "",
    "Mechanized": "Mech",
    "Motorized": "Mot",
    "Infantry": "Inf",
    "Armored": "Armd",
    "Artillery": "Arty",
    "Cavalry": "Cav",
    "Medium": "Med",
    "Heavy": "Hvy",
    "Light": "Lt",
    "Tank": "Tnk",
    "Super": "Sup",
    "Aircraft": "Acft",
    "Carrier": "Carr",
    "Destroyer": "Dstr",
    "Submarine": "Sub",
    "Dreadnought": "Dread",
    "Railroad": "RR",
    "Landkreuzer": "LK",
    "P.1000": "",
    "P.1500": "",
}

# Multi-word unit-class names collapsed to a single acronym, checked before the
# per-word substitution above. A per-word map can't express these cleanly:
# "Infantry"/"Tank" already have their own one-word shorthand used by several
# *other* families (Infantry Type, Medium/Heavy/Light Tank, ...), so remapping
# either word on its own would wrongly shorten those too. Keyed by the exact
# leading class name (i.e. get_base_unit_name's output), matched as a whole.
CONDENSED_UNIT_NAME_PHRASES = {
    "Infantry Fighting Vehicle": "IFV",
    "Main Battle Tank": "MBT",
}

def _condense_words(name, word_map):
    """Shared word-for-word substitution behind get_condensed_unit_name and
    get_condensed_building_name: splits on spaces, swaps any word found in
    word_map, and drops words mapped to "" (connector words like "Type")."""
    words = [word_map.get(w, w) for w in name.split(" ")]
    return " ".join(w for w in words if w)

def get_condensed_unit_name(unit_name):
    """Shortens a unit name via CONDENSED_UNIT_NAME_WORDS for space-constrained
    displays (production unit list, garrison rosters). e.g. 'Mechanized
    Infantry Type 1940' -> 'Mech Inf 1940', 'Medium Tank III' -> 'Med Tank III'.
    Everywhere else should keep showing the full name."""
    # Convoys/Trucks wrap the carried unit's name in parens (e.g.
    # "Convoy (Infantry Type 1940)"); condense the inner name and keep the
    # wrapper, rather than leaving it untouched because the parens break the
    # plain word-for-word lookup below.
    carrier_match = re.match(r'^(Convoy|Truck) \((.+)\)$', unit_name)
    if carrier_match:
        carrier, inner = carrier_match.groups()
        return f"{carrier} ({get_condensed_unit_name(inner)})"

    for phrase, short in CONDENSED_UNIT_NAME_PHRASES.items():
        if unit_name == phrase or unit_name.startswith(phrase + " "):
            unit_name = short + unit_name[len(phrase):]
            break

    return _condense_words(unit_name, CONDENSED_UNIT_NAME_WORDS)

# Word-for-word shorthand used ONLY by get_condensed_building_name, mirroring
# CONDENSED_UNIT_NAME_WORDS. "Building" is dropped as a connector word the
# same way "Type" is for units (e.g. "Recruitment Building Lvl 3" -> "Rcrt
# Lvl 3"); "Lvl" is kept since it's already short.
CONDENSED_BUILDING_NAME_WORDS = {
    "Building": "",
    "Recruitment": "Rcrt",
    "Factory": "Fac",
    "Center": "Ctr",
    "Refinery": "Rfn",
    "Workshop": "Wkshp",
}

def get_condensed_building_name(building_name):
    """Shortens a building name via CONDENSED_BUILDING_NAME_WORDS for the same
    space-constrained displays as get_condensed_unit_name. e.g. 'Basic
    Recruitment Center' -> 'Basic Rcrt Ctr', 'Factory Lvl 5' -> 'Fac Lvl 5'.
    Names with no recognized words (e.g. "Core Territory") pass through
    unchanged. Everywhere else should keep showing the full name."""
    return _condense_words(building_name, CONDENSED_BUILDING_NAME_WORDS)

def get_base_item_name(name):
    """Collapses a unit OR building name down to the family the turn overrides key off.

    Unlike get_base_unit_name this also folds the tier separators away, so
    "Infantry Type 1936" and "Factory Lvl 3" both come back as "Infantry" and
    "Factory". The trailing-numeral test runs through roman_to_int rather than a
    hardcoded numeral list, so it keeps working past whatever tier someone adds.
    """
    if " Type " in name: return name.split(" Type ")[0]
    if " Lvl " in name: return name.split(" Lvl ")[0]

    parts = name.split(" ")
    if len(parts) > 1 and re.fullmatch(r'[IVXLCDM]+', parts[-1]) and roman_to_int(parts[-1]) > 0:
        return " ".join(parts[:-1])
    return name

# Production/research columns a unit family belongs to, in the order the UI shows them.
UNIT_GROUP_INFANTRY = "Infantry"
UNIT_GROUP_TANKS = "Tanks"
UNIT_GROUP_NAVY = "Navy"

def classify_unit_group(base_name, stats):
    """Sorts a unit family into its Infantry / Tanks / Navy column.

    One rule for the production list, the custom-production picker and anything
    added later, so a unit can never land in different columns in two screens.
    """
    if stats.get("naval_unit", False):
        return UNIT_GROUP_NAVY
    if "Tank" in base_name or "Armored Car" in base_name or base_name in c.TANK_GROUP_EXTRAS:
        return UNIT_GROUP_TANKS
    return UNIT_GROUP_INFANTRY

#: The buckets the AI balances its army across.
#:
#: Deliberately NOT the same rule as classify_unit_group above, which sorts the
#: production screen's Infantry / Tanks / Navy columns. The two genuinely
#: disagree -- the production list files Cavalry under Infantry and Railroad
#: Guns under Tanks, the AI does the opposite -- and reconciling them would
#: change what the AI builds, i.e. the game. They are two named rules now
#: rather than one rule and four inline copies of the other.
AI_FORCE_INFANTRY = "INFANTRY"
AI_FORCE_TANKS = "TANKS"
AI_FORCE_NAVY = "NAVY"


def is_ai_tank(unit_type):
    """Whether the AI counts this unit towards its armour quota."""
    return "Tank" in unit_type or "Armored" in unit_type or unit_type == "Cavalry"


def ai_force_category(unit_type):
    """Which column of the AI's army balance a unit counts in, or None.

    The tests run in this order in every copy this replaces: infantry before
    armour, so a hypothetical "Infantry Tank" counts as infantry. Anything that
    matches none of the three -- convoys, trucks, artillery -- is not counted
    at all, which is why None is a real answer rather than a default bucket.
    """
    if not unit_type:
        return None
    if "Infantry" in unit_type or get_base_unit_name(unit_type) == "Militia":
        return AI_FORCE_INFANTRY
    if is_ai_tank(unit_type):
        return AI_FORCE_TANKS
    if is_naval_unit(unit_type) and not unit_type.startswith("Convoy"):
        return AI_FORCE_NAVY
    return None


def get_formatted_division_name(unit_type):
    """Standardizes parsing unit names into division categories while preserving case."""
    # Use regex to strip out " type" case-insensitively, without lowercasing the entire string
    base_name = re.sub(r'(?i)\s+type', '', get_base_unit_name(unit_type))
    
    # Use a lowercase check for the logic, but append to the preserved case string
    check_name = base_name.lower()
    if "division" not in check_name and not is_naval_unit(unit_type) and "convoy" not in check_name and "truck" not in check_name:
        base_name += " Division"
        
    return base_name

def get_unit_tech_key(base_name):
    """Maps a base unit class name to the research key that unlocks it.

    Punctuation is dropped rather than turned into a separator, so
    "Landkreuzer P.1000 Ratte" resolves to landkreuzer_p1000_ratte and not
    landkreuzer_p.1000_ratte - which matched no tech, leaving the unit
    permanently unbuildable.
    """
    key = re.sub(r'[^a-z0-9 ]', '', base_name.lower())
    key = re.sub(r'\s+', '_', key.strip())
    return c.UNIT_TECH_KEY_OVERRIDES.get(key, key)

def roman_to_int(s):
    """Converts a roman numeral string to an integer.

    Reads its symbol table from constants, so it understands exactly the
    numerals _gen_roman can produce. It used to carry its own {I, V, X} and
    score everything else as zero, which disagreed with both the generator and
    with get_base_item_name's [IVXLCDM]+ regex above.
    """
    if not s: return 0
    rom_val = c.ROMAN_LETTER_VALUES
    res, i = 0, 0
    while i < len(s):
        s1 = rom_val.get(s[i], 0)
        if i + 1 < len(s):
            s2 = rom_val.get(s[i+1], 0)
            if s1 >= s2: res += s1; i += 1
            else: res += s2 - s1; i += 2
        else: res += s1; i += 1
    return res

def get_unit_research_requirement(unit_name):
    """Returns (tech_key, required_level) needed to unlock an exact unit tier by name.

    Infantry Type (year-suffixed) keys off the tech's position in its 'years' list;
    everything else - including Artillery, which is roman-numeral leveled like
    Militia - keys off its trailing roman numeral, mirroring the tier logic in
    production.py's unit rendering. Motorized/Mechanized Infantry aren't leveled
    techs of their own (see c.VEHICLE_INFANTRY_GATES) so they're not representable
    as a single (tech_key, level) pair - is_unit_unlocked handles them directly
    instead of going through this function.
    """
    base_name = get_base_unit_name(unit_name)
    tech_key = get_unit_tech_key(base_name)

    if tech_key == "infantry_type":
        years = get_tech_tree().get(tech_key, {}).get("years", [])
        year_match = re.search(r'(\d{4})$', unit_name)
        if year_match and years:
            year = int(year_match.group(1))
            if year in years:
                return tech_key, years.index(year) + 1
        return tech_key, 1

    lvl_str = unit_name.replace(base_name, "").strip()
    return tech_key, max(1, roman_to_int(lvl_str))

def is_unit_unlocked(unit_name, player_research):
    """Returns True if player_research meets the requirement for this exact unit tier,
    independent of whether it's the group's currently-highest tier (see Custom production)."""
    base_name = get_base_unit_name(unit_name)
    tech_key = get_unit_tech_key(base_name)

    if tech_key in c.VEHICLE_INFANTRY_GATES:
        unlocked_year = get_infantry_family_year(tech_key, player_research, get_tech_tree())
        year_match = re.search(r'(\d{4})$', unit_name)
        if unlocked_year is None or not year_match:
            return False
        return int(year_match.group(1)) <= unlocked_year

    tech_key, required_lvl = get_unit_research_requirement(unit_name)
    return player_research.get(tech_key, 0) >= required_lvl

def is_naval_unit(unit_type):
    """Checks if a unit is a naval unit based on its type name or unit library stats."""
    if unit_type.startswith("Convoy"):
        return True
    if unit_type.startswith("Truck"):
        return False
    stats = get_unit_library().get(unit_type, {})
    return stats.get("naval_unit", False)

def get_bombardment_range(unit_type):
    """Returns how many tiles this unit class can shell, or 0 if it cannot bombard.

    The unit's own bombard_range wins, so adding one in unit_data.json is all it
    takes to give something a gun -- the AI already valued that stat, and the two
    answers disagreeing meant it could price a barrage the unit could not fire.
    The constant table is the fallback, matched on the base class name so every
    level of a family qualifies.

    A unit riding a Convoy/Truck ("Convoy (Artillery III)") still cannot shell:
    that name is not in the unit library, so the stat lookup misses, and it is
    not in the table either.
    """
    from_stats = (get_unit_library().get(unit_type) or {}).get("bombard_range")
    if from_stats:
        return int(from_stats)
    return c.BOMBARDMENT_UNITS.get(get_base_unit_name(unit_type), 0)

def can_bombard(unit_type):
    """Returns True if this unit class can shell a nearby tile instead of moving."""
    return get_bombardment_range(unit_type) > 0

def get_bombardment_arrow_icon(bomb_range):
    """Picks the barrage sprite matching a gun's reach (long guns get their own art)."""
    icons = c.BOMBARDMENT_ARROW_ICONS
    eligible = [r for r in icons if r <= bomb_range]
    return icons[max(eligible)] if eligible else icons[min(icons)]

def get_bombardment_targets(province, id_to_province, max_range=None):
    """Returns the set of province ids a gun sitting on this tile can shell."""
    if max_range is None:
        max_range = c.DEFAULT_BOMBARDMENT_RANGE

    in_range = set()
    visited = {province["id"]}
    frontier = [province["id"]]

    for _ in range(max(0, max_range)):
        next_frontier = []
        for pid in frontier:
            prov = id_to_province.get(pid)
            if not prov: continue
            for n_id in prov.get("neighbors", []):
                if n_id in visited: continue
                visited.add(n_id)
                next_frontier.append(n_id)
                in_range.add(n_id)
        frontier = next_frontier

    return in_range

def get_ordinal(n):
    """Returns the ordinal string for an integer."""
    if 11 <= (n % 100) <= 13:
        return str(n) + "th"
    return str(n) + {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")

def generate_unit_custom_name(unit, unit_counters):
    """Generates a dynamic custom name for a unit based on its type and country count."""
    owner = unit.get("owner", "Unclaimed")
    unit_type = unit.get("type", "Infantry")
    
    # Extract year or level for suffix
    suffix = ""
    year_match = re.search(r'\b(\d{4})\b', unit_type)
    if year_match:
        suffix = f" ({year_match.group(1)})"
    else:
        # Match roman numerals at the end of the string
        numeral_match = re.search(r'\b([IVXLCDM]+)$', unit_type)
        if numeral_match:
            suffix = f" ({numeral_match.group(1)})"
    
    # Clean up the base name using our new unified string parser
    base_name = get_formatted_division_name(unit_type)
    
    # Track count per owner per base type
    count = unit_counters.setdefault(owner, {}).get(base_name, 0) + 1
    unit_counters[owner][base_name] = count
    
    ordinal = get_ordinal(count)
    return f"{ordinal} {base_name}{suffix}"

def build_active_unit_counters(map_data):
    """Sweeps the map and returns a dictionary of current unit counts for accurate naming."""
    unit_counters = {}
    for prov in map_data.values():
        for unit in prov.get("units", []):
            owner = unit.get("owner", "Unclaimed")
            base_name = get_formatted_division_name(unit.get("type", "Infantry"))
            unit_counters.setdefault(owner, {})[base_name] = unit_counters.setdefault(owner, {}).get(base_name, 0) + 1
    return unit_counters

# i don't know if this would really count as a query...
def load_transport(unit, target):
    """Puts a unit aboard a Convoy or into a Truck, remembering what it was.

    The mirror of revert_transport, and the other half of what used to live
    inline in movement_processor.process_conversions -- pulled out so the
    stranded-at-sea sweep can re-embark a unit without duplicating the stat
    bookkeeping that makes the round trip lossless.
    """
    if target not in ("Convoy", "Truck"):
        return

    unit["original_type"] = unit["type"]
    unit["original_speed"] = unit.get("speed", 1)
    unit["original_max_health"] = unit.get("max_health", c.DEFAULT_UNIT_HP)
    unit["original_attack"] = unit.get("attack", c.DEFAULT_UNIT_ATK)
    unit["original_defense"] = unit.get("defense", c.DEFAULT_UNIT_DEF)

    pct = unit.get("health", 1) / max(1, unit.get("max_health", 1))

    unit["type"] = f"{target} ({unit['type']})"
    unit["speed"] = 1

    if target == "Convoy":
        unit["naval_unit"] = True
        unit["max_health"] = c.CONVOY_MAX_HP
        unit["attack"] = c.CONVOY_ATK
        unit["defense"] = c.CONVOY_DEF
    else:
        unit["naval_unit"] = False
        unit["max_health"] = c.TRUCK_MAX_HP
        unit["attack"] = c.TRUCK_ATK
        unit["defense"] = c.TRUCK_DEF

    unit["health"] = unit["max_health"] * pct

def revert_transport(unit):
    """Reverts a transport (like a Convoy) back to its original unit type."""
    if "original_type" not in unit:
        return

    pct = unit.get("health", 1) / max(1, unit.get("max_health", 1))

    unit["type"] = unit.get("original_type", "Infantry")
    unit["speed"] = unit.get("original_speed", 1)
    unit["max_health"] = unit.get("original_max_health", c.DEFAULT_UNIT_HP)
    unit["attack"] = unit.get("original_attack", c.DEFAULT_UNIT_ATK)
    unit["defense"] = unit.get("original_defense", c.DEFAULT_UNIT_DEF)

    unit["health"] = unit["max_health"] * pct
    unit["naval_unit"] = is_naval_unit(unit["type"])

    for key in ["original_type", "original_speed", "original_max_health", "original_attack", "original_defense"]:
        if key in unit: del unit[key]

def has_units_in_province(nation, province):
    """Returns True if the given nation has any units in the target province."""
    return any(u.get("owner") == nation for u in province.get("units", []))

def get_active_ai_nations(map_screen):
    """Returns a list of all playable, active AI nations (excluding the human player)."""
    ai_nations = []
    # Account for potential hotseat active_players lists or standard player_country setups
    human_players = map_screen.active_players if map_screen.active_players else [map_screen.player_country]
    
    # --- TACTICAL OVERRIDE ---
    # Give the AI full command of the country's macro strategy
    if map_screen.tactical_mode:
        human_players = []
    
    # Cross-reference with nations that actually own territory
    living_nations = get_living_nations(map_screen.map_data)
    
    submitted = getattr(map_screen, 'submitted_moves', set())
    protected = getattr(map_screen, 'multiplayer_protected_countries', set())

    for name, data in map_screen.nation_data.items():
        if (submitted and name in submitted) or (protected and name in protected):
            continue
        if name in living_nations and name not in human_players and name not in c.UNPLAYABLE_NATIONS and data.get("is_playable"):
            ai_nations.append(name)
            
    # Randomize the order the AI processes countries
    random.shuffle(ai_nations)
    
    return ai_nations

def is_unit_obsolete(group_name, player_research):
    """Checks if a unit group is obsolete based on researched techs."""
    obsoleting_techs = c.OBSOLESCENCE_RULES.get(group_name, [])
    return any(player_research.get(tech, 0) >= 1 for tech in obsoleting_techs)

def get_best_unit(units, sort_keys):
    """Generic helper to find the unit with the highest combination of given stats."""
    if not units:
        return None
    # Tuple sorting automatically evaluates primary, secondary, and tertiary keys dynamically
    return max(units, key=lambda u: tuple(u.get(key, 0) for key in sort_keys))

def get_best_unit_by_defense_then_attack_then_speed(units): return get_best_unit(units, ["defense", "attack", "speed"])

# ==========================================
# PREDICTION QUERIES (UI & RENDERING)
# ==========================================

def get_combat_predictions(map_screen):
    """Generates predictions for meeting engagements and province clashes."""
    map_data = map_screen.map_data
    nation_data = map_screen.nation_data

    player_country = map_screen.player_country
    is_spectator = player_country == "Spectator" or map_screen.is_editor
    
    predictions = []

    # 1. Meeting engagements: use the same rule as the turn resolver, but only
    #    with movement orders the player is allowed to know. Faction and
    #    alliance membership does not disclose another nation's plans.
    from map_logic.turn_processing import combat_rules
    visible_to = None if is_spectator else {player_country}

    # Layers hidden submarines out of the bubble the same way the map/sidebar
    # do. Spectators and the editor keep the full, unfiltered truth.
    def sub_visible(units, prov):
        if is_spectator:
            return units
        return filter_visible_units(units, player_country, prov, nation_data)

    meeting_unit_ids = set()
    for pair in combat_rules.find_meeting_pairs(map_data, nation_data, visible_to):
        prov_a, prov_b, side1, side2 = combat_rules.meeting_sides(
            map_screen.id_to_province, pair, visible_to)
        # A head-on swap is resolved between its two origin tiles, so it has no
        # province bubble of its own. Keep those movers out of the ordinary
        # incoming/static pass below to avoid duplicate endpoint bubbles.
        meeting_unit_ids.update(id(unit) for unit in side1 + side2)
        predictions.append({
            "type": "meeting",
            "loc": pair,
            "side1": sub_visible(side1, prov_a),
            "side2": sub_visible(side2, prov_b)
        })

    # 2. Incoming movements, for the province clashes below.
    incoming = {}
    for prov in map_data.values():
        for u in prov.get("units", []):
            if id(u) in meeting_unit_ids:
                continue
            order = u.get("order")
            if order and order.get("type") == "MOVE" and order.get("path"):
                if visible_to is not None and u.get("owner") not in visible_to:
                    continue
                if not is_spectator and not is_unit_visible_to(u, player_country, prov, nation_data):
                    continue
                incoming.setdefault(order["path"][0], []).append((u, prov["id"]))

    # 3. Find Province Clashes (Static Defenders vs Incoming Attackers)
    for prov in map_data.values():
        prov_id = prov["id"]
        defenders = sub_visible([unit for unit in prov.get("units", [])
                                 if id(unit) not in meeting_unit_ids], prov)
        attackers = [u for u, o in incoming.get(prov_id, [])]
        
        forces_by_owner = {}
        for u in defenders + attackers:
            forces_by_owner.setdefault(u["owner"], []).append(u)
            
        owners = list(forces_by_owner.keys())
        clash = False
        for i in range(len(owners)):
            for j in range(i+1, len(owners)):
                if are_at_war(owners[i], owners[j], nation_data):
                    clash = True
                    break
        if clash:
            predictions.append({
                "type": "province",
                "loc": prov_id,
                "forces": forces_by_owner
            })
            
    return predictions

# ==========================================
# IMAGE ENCODING / DECODING
# ==========================================

_default_flag_b64 = None
_default_port_b64 = None
_dynamic_image_cache = {}

def clear_image_cache():
    _dynamic_image_cache.clear()

def _load_and_scale_local_image(file_path, size):
    """Helper to safely load and scale a local image file."""
    if os.path.exists(file_path):
        try:
            img = pygame.image.load(file_path).convert_alpha()
            return pygame.transform.scale(img, size)
        except:
            pass
    return None

def get_default_b64(is_portrait=False):
    global _default_flag_b64, _default_port_b64
    cached = _default_port_b64 if is_portrait else _default_flag_b64
    
    if cached is None:
        path = c.DEFAULT_PORTRAIT_PATH if is_portrait else c.DEFAULT_FLAG_PATH
        size = c.PORTRAIT_SIZE if is_portrait else c.FLAG_SIZE
        img = _load_and_scale_local_image(path, size)
        
        cached = encode_surf_to_b64(img) if img else "ERROR"
        
        if is_portrait: _default_port_b64 = cached
        else: _default_flag_b64 = cached
        
    return cached

#: country -> (flag_b64, portrait_b64) for the on-disk assets, or None where
#: there is no file. Answering this needs a disk load, an alpha conversion, a
#: rescale and a full-buffer base64 per country, and the answer cannot change
#: while the game runs -- but scrub_default_images is called once per nation per
#: history snapshot, so on a 130-turn 752-nation save it was being computed
#: ~98,000 times and cost 8.9 seconds of every save.
_local_image_b64_cache = {}


def _local_image_b64(country):
    """Base64 of this country's own flag/portrait files, memoised for the process."""
    cached = _local_image_b64_cache.get(country)
    if cached is None:
        f_img = _load_and_scale_local_image(os.path.join(c.FLAGS_DIR, f"{country}.png"), c.FLAG_SIZE)
        p_img = _load_and_scale_local_image(os.path.join(c.PORTRAITS_DIR, f"{country}.png"), c.PORTRAIT_SIZE)
        cached = (encode_surf_to_b64(f_img) if f_img else None,
                  encode_surf_to_b64(p_img) if p_img else None)
        _local_image_b64_cache[country] = cached
    return cached


def scrub_default_images(nation_data_block):
    """Replaces large Base64 strings with 'DEFAULT' if they match the default images or local files."""
    def_flag = get_default_b64(is_portrait=False)
    def_port = get_default_b64(is_portrait=True)

    for country, data in nation_data_block.items():
        flag_b64, port_b64 = _local_image_b64(country)

        # 'DEFAULT' means "rebuild it from the country's own file, or failing
        # that the global default" -- so both comparisons collapse to the same
        # replacement, and neither is worth storing. Guarded on truthiness so a
        # nation with no flag_data at all does not gain the key here, which is
        # what a bare `in` test would have done when the local file is absent.
        stored_flag = data.get("flag_data")
        if stored_flag and stored_flag in (def_flag, flag_b64):
            data["flag_data"] = "DEFAULT"

        stored_port = data.get("portrait_data")
        if stored_port and stored_port in (def_port, port_b64):
            data["portrait_data"] = "DEFAULT"

def encode_surf_to_b64(surf, fmt="RGBA"):
    """Encodes a pygame surface to a Base64 string."""
    img_str = pygame.image.tostring(surf, fmt)
    return base64.b64encode(img_str).decode('utf-8')

def decode_b64_to_surf(b64_str, size, is_portrait=False, country_name=None):
    """Decodes a Base64 string back into a pygame surface."""
    cache_key = (b64_str, size, is_portrait, country_name)
    if cache_key in _dynamic_image_cache:
        return _dynamic_image_cache[cache_key]

    scaled = None
    if not b64_str or b64_str == "DEFAULT":
        # --- Check for country-specific local file first ---
        if country_name:
            base_dir = c.PORTRAITS_DIR if is_portrait else c.FLAGS_DIR
            scaled = _load_and_scale_local_image(os.path.join(base_dir, f"{country_name}.png"), size)
            
        # --- Fallback to absolute default ---
        if not scaled:
            path = c.DEFAULT_PORTRAIT_PATH if is_portrait else c.DEFAULT_FLAG_PATH
            scaled = _load_and_scale_local_image(path, size)
            
        if not scaled: # Failsafe
            scaled = pygame.Surface(size, pygame.SRCALPHA)
            scaled.fill((200, 200, 200, 255))
    else:
        try:
            img_bytes = base64.b64decode(b64_str)
            if len(img_bytes) == size[0] * size[1] * 4:
                scaled = pygame.image.fromstring(img_bytes, size, "RGBA")
            else:
                scaled = pygame.image.fromstring(img_bytes, size, "RGB").convert_alpha()
        except:
            scaled = pygame.Surface(size, pygame.SRCALPHA)
            scaled.fill((255, 255, 255, 255))

    _dynamic_image_cache[cache_key] = scaled
    return scaled

# ==========================================
# DIPLOMATIC SPAM/REACHABILITY QUERIES
# ==========================================

def build_national_border_graph(map_data, id_to_province):
    """Builds the world adjacency graph is_nation_reachable walks.

    Nodes are nation names, plus one "WATER_<id>" node per sea tile. Derived
    purely from tile ownership and terrain, so a caller asking about several
    nations in a row should build this once and pass it to every call rather
    than paying for a full map sweep each time.
    """
    borders = {}

    def add_edge(u, v):
        if u not in borders: borders[u] = set()
        if v not in borders: borders[v] = set()
        borders[u].add(v)
        borders[v].add(u)

    for prov_id, prov in map_data.items():
        is_water = is_water_province(prov)
        owner = prov.get("owner")

        node_u = f"WATER_{prov_id}" if is_water else owner
        if not node_u: continue

        for n_id in prov.get("neighbors", []):
            n_prov = id_to_province.get(n_id)
            if not n_prov: continue

            n_is_water = is_water_province(n_prov)
            n_owner = n_prov.get("owner")

            node_v = f"WATER_{n_id}" if n_is_water else n_owner
            if not node_v: continue

            if node_u != node_v:
                add_edge(node_u, node_v)

    return borders

def is_nation_reachable(nation_a, target_nation, map_data, id_to_province, nation_data, borders=None):
    """Determines if a nation can physically reach another via land borders (including passable nations) or connected water."""
    friendly_a = get_all_friendly_nations(nation_a, nation_data)
    at_war_a = set(get_enemies(nation_a, nation_data))

    friendly_b = get_all_friendly_nations(target_nation, nation_data)
    at_war_b = set(get_enemies(target_nation, nation_data))

    target_faction = nation_data.get(target_nation, {}).get("faction", "")
    enemy_nations = {target_nation}
    if target_faction:
        enemy_nations.update(get_faction_members(target_faction, nation_data))

    passable_nations = set(friendly_a) | at_war_a | set(friendly_b) | at_war_b | enemy_nations

    if borders is None:
        borders = build_national_border_graph(map_data, id_to_province)

    visited = set(friendly_a)
    queue = collections.deque(friendly_a)

    while queue:
        curr = queue.popleft()

        if curr in enemy_nations:
            return True

        for neighbor in borders.get(curr, ()):
            if neighbor not in visited:
                is_water_node = str(neighbor).startswith("WATER_")
                if neighbor in enemy_nations:
                    return True
                if is_water_node or neighbor in passable_nations:
                    visited.add(neighbor)
                    queue.append(neighbor)

    return False

def is_ai_diplo_on_cooldown(sender, target, action, nation_data):
    """Checks if a specific proactive diplomatic action is on cooldown."""
    cooldowns = nation_data.get(sender, {}).get("diplo_cooldowns", {})
    target_cooldowns = cooldowns.get(target, {})
    return target_cooldowns.get(action, 0) != 0

def set_ai_diplo_cooldown(sender, target, action, nation_data, duration=None):
    """Sets a cooldown for a proactive diplomatic action to prevent spamming."""
    if duration is None:
        # Check if this is a war declaration to use the specific override
        if action == "WAR_DECLARATION":
            duration = c.AI_WAR_COOLDOWN
        else:
            duration = c.AI_DIPLO_COOLDOWN
    
    cooldowns = nation_data.setdefault(sender, {}).setdefault("diplo_cooldowns", {})
    target_cooldowns = cooldowns.setdefault(target, {})
    target_cooldowns[action] = duration

def get_valid_claim_targets(nation, target_nation, map_data):
    """Returns a list of province dicts owned by target_nation that can be claimed."""
    targets = []
    for prov in map_data.values():
        if prov.get("owner") == target_nation:
            targets.append(prov)
    return targets

def has_wargoal(nation, target_nation, nation_data, map_data=None):
    """Returns True if the nation has active claims on the target, or a justified wargoal."""
    if map_data:
        claims = nation_data.get(nation, {}).get("claims", [])
        for prov in map_data.values():
            # If target owns the tile, and the attacker either claimed it or has a core on it
            if prov.get("owner") == target_nation and (prov["id"] in claims or nation in prov.get("cores", [])):
                return True
    return target_nation in nation_data.get(nation, {}).get("wargoals", {})

def power_ratio(ai_nation, target_nation, map_data, nation_data, id_to_province=None):
    """(border_ratio, global_ratio) between two nations.

    The two quantities ai_thinks_it_can_win compares against its thresholds,
    exposed as numbers so a caller can reason in degrees instead of a yes/no --
    which is what lets a bold nation gamble on odds a careful one turns down.
    ai_thinks_it_can_win is written in terms of this so the two cannot drift.
    """
    if not id_to_province:
        id_to_province = {prov["id"]: prov for prov in map_data.values()}

    my_border_str, target_border_str = get_border_strength(ai_nation, target_nation, map_data, id_to_province, nation_data)

    # Prevent division by zero if they have literally no troops on the border
    target_border_str = max(1, target_border_str)

    # Consider total alliance strength, economy, and distractions
    my_alliance_str = get_alliance_military_strength(ai_nation, map_data, nation_data)
    target_alliance_str = get_alliance_military_strength(target_nation, map_data, nation_data)

    my_econ_power = get_economic_power(ai_nation, nation_data) / 100.0
    target_econ_power = get_economic_power(target_nation, nation_data) / 100.0

    # Factor in how distracted the target is by their existing wars
    target_distraction_str = get_combined_enemy_strength(target_nation, map_data, nation_data) * (c.AI_ENEMY_DISTRACTION_WEIGHT)

    # Add the target's distraction to our perceived power
    my_total_power = my_alliance_str + my_econ_power + target_distraction_str
    target_total_power = max(1.0, target_alliance_str + target_econ_power)

    return my_border_str / target_border_str, my_total_power / target_total_power

def ai_thinks_it_can_win(ai_nation, target_nation, map_data, nation_data, id_to_province=None):
    """Calculates if the AI believes it is strong enough to defeat the target (CTW)."""
    border_ratio, global_ratio = power_ratio(ai_nation, target_nation, map_data, nation_data, id_to_province)

    # AI needs local border superiority AND overall global viability
    return border_ratio >= c.AI_WAR_STRENGTH_THRESHOLD and global_ratio >= c.AI_GLOBAL_STRENGTH_THRESHOLD

def is_weaker_neighbor(ai_nation, target_nation, map_data, nation_data):
    """Returns True if the target nation's total power is significantly lower than the AI's."""
    my_alliance_str = get_alliance_military_strength(ai_nation, map_data, nation_data)
    my_econ_power = get_economic_power(ai_nation, nation_data) / 100.0
    my_total_power = my_alliance_str + my_econ_power
    
    target_alliance_str = get_alliance_military_strength(target_nation, map_data, nation_data)
    target_econ_power = get_economic_power(target_nation, nation_data) / 100.0
    target_total_power = max(1.0, target_alliance_str + target_econ_power)
    
    return target_total_power < (my_total_power * c.AI_WEAK_NEIGHBOR_STRENGTH_RATIO)

def will_ai_accept_peace(target_nation, proposer_nation, peace_type, map_data, nation_data):
    """DEPRECATED. Forwards to ai_opinion.accepts_peace, which is the real rule.

    This function's own logic refused any demand for claims unconditionally, so
    no AI war ever ended with territory changing hands -- and because the peace
    screen called this while the engine called accepts_peace, the screen could
    tell a player "the AI will REJECT this" and then watch the AI accept it. The
    body is gone rather than fixed: two implementations of one judgement is what
    caused the disagreement, and a second one would only drift again.

    Kept, with its signature untouched, because a mod may be calling it -- see
    the note in map_logic/ai/ai_world.py about mods shadowing this whole file.
    """
    from map_logic.ai import ai_opinion, ai_world

    world = ai_world.AIWorld(map_data or {}, nation_data,
                             {prov["id"]: prov for prov in (map_data or {}).values()})
    return ai_opinion.accepts_peace(world, target_nation, proposer_nation, peace_type)

    if peace_type.startswith(c.PEACE_SURRENDER):
        gains_territory = False
        
        # Dynamically check the map data instead of relying on the UI text string.
        # The UI evaluates this BEFORE appending the specific territory data to the string.
        if map_data:
            ai_claims = nation_data.get(target_nation, {}).get("claims", [])
            for prov in map_data.values():
                if prov.get("owner") == proposer_nation and (prov["id"] in ai_claims or target_nation in prov.get("cores", [])):
                    gains_territory = True
                    break
        else:
            # Fallback if map_data is missing
            # This "fallback" just makes the ai always accept
            gains_territory = "No territories surrendered" not in peace_type

        # AI shouldn't accept a surrender unless they gain territory OR if they'll also accept a ceasefire
        if gains_territory:
            return True
            
        war_dur = nation_data.get(target_nation, {}).get("war_durations", {}).get(proposer_nation, 0)
        if war_dur < c.MIN_TURNS_FOR_CEASEFIRE:
            return False
            
        if map_data:
            if not ai_thinks_it_can_win(target_nation, proposer_nation, map_data, nation_data):
                return True
        else:
            return True
            
        return False
            
    # This query acts as a centralized place to expand logic later (e.g. check war score).
    return True

# ==========================================
# DATA SYNC & REFRESH
# ==========================================

def refresh_map_directories(screen, dirs_to_check, success_message="Data refreshed successfully!", options=None):
    """Headlessly instantiates maps on a background thread to prevent UI freezing."""
    # An empty dict behaves the same as None below (every lookup defaults to True),
    # so this also keeps refresh_nation_data's own default-options branch out of play.
    options = options or {}
    # Count total maps first
    total_maps = 0
    valid_scenarios = []
    for scenario_dir in dirs_to_check:
        if not os.path.exists(scenario_dir):
            continue
        for name in os.listdir(scenario_dir):
            scenario_path = os.path.join(scenario_dir, name)
            map_json_path = os.path.join(scenario_path, "map_data.json")
            if os.path.isdir(scenario_path) and os.path.exists(map_json_path):
                valid_scenarios.append((scenario_dir, name, scenario_path, map_json_path))
                total_maps += 1
    
    if total_maps == 0:
        from ui import confirm_dialog
        confirm_dialog.show_info("Data Refresh", "No maps found to refresh.")
        return

    # Setup screen state for UI
    screen.is_refreshing = True
    screen.refresh_total = total_maps
    screen.refresh_completed = 0
    screen.refresh_status = "Initializing..."

    def _refresh_thread():
        from screens.menu_screens.map import Map
        maps_processed = 0

        for scenario_dir, name, scenario_path, map_json_path in valid_scenarios:
            try:
                screen.refresh_status = f"Syncing: {name}..."
                # 1. Instantiate Map with standard singleplayer configurations to pull existing meta/map data into memory
                temp_map_context = Map(load_path=scenario_path, is_scenario=True, skip_initial_income=True)

                # --- BUG FIX: Restore scenario settings wiped by selection_mode ---
                meta_path = os.path.join(scenario_path, "meta.json")
                if os.path.exists(meta_path):
                    try:
                        with open(meta_path, "r", encoding="utf-8") as f:
                            old_meta = json.load(f)
                            if "scenario_settings" in old_meta:
                                temp_map_context.scenario_settings = old_meta["scenario_settings"]
                    except Exception as e:
                        print(f"Error reading meta.json for settings restoration: {e}")
                # ------------------------------------------------------------------

                # 2. Execute the official resync pipeline
                temp_map_context.refresh_nation_data(options=options)
                print(f"refreshed {name}")

                # Re-apply the historical timeline on top -- refresh_nation_data
                # just reset name/adjective/leader fields to their generic base
                # template, which would otherwise blank out anything the
                # Historical Leaders Editor set for this scenario's date.
                if c.SCENARIOS_HISTORICAL_DIR.replace("\\", "/") in scenario_dir.replace("\\", "/"):
                    tm = temp_map_context.time_manager
                    apply_historical_leader_timeline(temp_map_context.nation_data, tm.year, tm.month_index, tm.day)

                # Set all playable country resources to 0 before compounding income calculations
                if options.get("reset_resources", True):
                    for nation_name, stats in temp_map_context.nation_data.items():
                        if nation_name != "GLOBAL_EVENTS" and nation_name not in c.UNPLAYABLE_NATIONS:
                            stats["manpower"] = 0
                            stats["materials"] = 0
                            stats["fuel"] = 0

                # 3. Clean country flags/portraits inside memory before serializing
                scrub_default_images(temp_map_context.nation_data)

                # --- BUG FIX: Fix lowercase unit types and custom names ---
                unit_lib = get_unit_library()
                for prov in temp_map_context.map_data.values():
                    for unit in prov.get("units", []):
                        u_type = unit.get("type", "")
                        if u_type:
                            # Match exact casing from unit library if possible
                            for correct_name in unit_lib.keys():
                                if correct_name.lower() == u_type.lower():
                                    unit["type"] = correct_name
                                    break
                            else:
                                words = unit["type"].split()
                                unit["type"] = " ".join(w.capitalize() if w.islower() else w for w in words)
                        
                        c_name = unit.get("custom_name", "")
                        if c_name:
                            words = c_name.split()
                            unit["custom_name"] = " ".join(w.capitalize() if w.islower() else w for w in words)
                # ----------------------------------------------------------

                # 4. Reconstruct the exact structural configuration payload
                save_dict = build_save_dict(temp_map_context)

                # 5. Perform the manual write operations in-place
                from data.map import history_io

                with open(os.path.join(scenario_path, "meta.json"), "w") as f:
                    f.write(history_io.dump_text(save_dict, indent=c.SAVE_INDENT))

                with open(map_json_path, "w") as f:
                    f.write(history_io.dump_text(temp_map_context.raw_json_data, indent=c.SAVE_INDENT))

                if hasattr(temp_map_context, 'history'):
                    history_io.write(scenario_path, temp_map_context.history)

                pygame.image.save(temp_map_context.political_map, os.path.join(scenario_path, "political.png"))
                pygame.image.save(temp_map_context.terrain_map, os.path.join(scenario_path, "terrain.png"))
                pygame.image.save(temp_map_context.id_map, os.path.join(scenario_path, "id_map.png"))
                pygame.image.save(temp_map_context.cores_map, os.path.join(scenario_path, "cores.png"))

                maps_processed += 1
                screen.refresh_completed = maps_processed

            except Exception as e:
                print(f"[REFRESH ERROR] Failed to automatically sync structural data profiles for '{name}': {e}")

        screen.refresh_status = f"{success_message} Processed {maps_processed} maps."
        # Allow a short delay for the user to read the success message before closing the bar
        import time
        time.sleep(1.5)
        screen.is_refreshing = False

    # Fire and forget the background process
    run_background(_refresh_thread)

def open_listbox_selector(game_state, title, prompt, items, on_confirm_callback):
    """In-engine listbox picker for editor tools and spectators: dims and freezes
    the current frame, then shows a clickable list of rows in a modal panel."""
    from ui.list_select_screen import ListSelectScreen
    from ui.screen_runner import _run_pygame_sub_screen
    screen = ListSelectScreen(game_state, title, prompt, items, on_confirm_callback)
    _run_pygame_sub_screen(game_state, screen)

def _clear_phantom_hover(game_state):
    """Drops the hover a blocking sub-screen left behind, like _run_pygame_sub_screen does."""
    host = getattr(game_state, "map_screen", None) or game_state
    if hasattr(host, "hovered_province"):
        host.hovered_province = None

def open_checkbox_list(game_state, title, prompt, items, on_result, confirm_label="Confirm",
                       show_select_all=True, extra_buttons=None, footnote=None):
    """In-engine multi-toggle picker: replaces the scrollable tk.Checkbutton panels.

    `items` are ui.checkbox_list_screen CheckboxItem / SectionHeader objects.
    Answers on_result with the list of checked keys -- empty when nothing was
    ticked, None when the user cancelled, so the two cases stay distinguishable.
    """
    from ui.checkbox_list_screen import CheckboxListScreen
    from ui.screen_runner import run_screen
    result = {}
    def _on_done(screen):
        _clear_phantom_hover(game_state)
        on_result(result.get("keys"))
    run_screen(lambda: CheckboxListScreen(game_state, title, prompt, items,
                                          lambda keys: result.setdefault("keys", keys),
                                          confirm_label=confirm_label,
                                          show_select_all=show_select_all,
                                          extra_buttons=extra_buttons, footnote=footnote),
               on_done=_on_done, caption=title)

def open_color_picker(game_state, title, initial_color, on_confirm_callback):
    """In-engine RGB/hex color picker: replaces tkinter.colorchooser.askcolor."""
    from ui.color_picker_screen import ColorPickerScreen
    from ui.screen_runner import _run_pygame_sub_screen
    screen = ColorPickerScreen(game_state, title, initial_color, on_confirm_callback)
    _run_pygame_sub_screen(game_state, screen)

def open_character_picker(game_state, current_path, on_confirm_callback):
    """In-engine grid picker for choosing a character portrait: shows a
    thumbnail for every image under assets/characters/."""
    from ui.character_select_screen import CharacterSelectScreen
    from ui.screen_runner import _run_pygame_sub_screen
    screen = CharacterSelectScreen(game_state, current_path, on_confirm_callback)
    _run_pygame_sub_screen(game_state, screen)

def open_file_browser(game_state, title, start_dir=None, mode="open_file", extensions=None,
                      on_confirm_callback=None, tk_parent=None, on_result=None):
    """In-engine file/folder picker: replaces filedialog.askopenfilename,
    askopenfilenames and askdirectory.

    Browses the whole machine -- `start_dir` is only where it opens, never a
    fence. `mode` is "open_file", "open_files" (multi-select) or "select_folder".
    Answers on_result with the pick (a path, a list of paths, or None when
    cancelled); on_confirm_callback, when given, fires only on a real pick.
    """
    def _on_result(picked):
        if picked is not None and on_confirm_callback:
            on_confirm_callback(picked)
        _clear_phantom_hover(game_state)
        if on_result:
            on_result(picked)

    if IS_WEB:
        if mode == "select_folder":
            # There's no native browser equivalent of "pick a folder on my
            # real disk" (a browser sandbox has no notion of an arbitrary
            # host path) -- not supported on web.
            from ui import confirm_dialog
            confirm_dialog.show_error("Not Available", "Choosing a folder isn't supported in the browser build.", tk_parent=tk_parent)
            _on_result(None)
            return
        from data.platform import pick_upload_file
        pick_upload_file(_on_result, extensions=extensions, multiple=(mode == "open_files"))
        return

    from ui.file_browser_screen import run_file_browser
    run_file_browser(title, start_dir, mode=mode, extensions=extensions,
                     game_state=game_state, tk_parent=tk_parent, on_result=_on_result)

def copy_to_clipboard(text):
    """Pushes text to the OS clipboard via SDL's clipboard (pygame.scrap)."""
    try:
        if not pygame.scrap.get_init():
            pygame.scrap.init()
        pygame.scrap.put(pygame.SCRAP_TEXT, text.encode("utf-8"))
        return True
    except Exception as e:
        print(f"Failed to copy to clipboard: {e}")
        return False

def play_click_sound():
    """Plays the UI click sound. Thin alias kept for non-UI callers."""
    import ui_elements
    ui_elements.play_ui_sound("click")

# ==========================================
# EDITOR UNDO / REDO LOGIC
# ==========================================

def _get_current_map_state(map_screen):
    import copy
    state = {}
    for color_key, prov in map_screen.map_data.items():
        state[color_key] = {
            "owner": prov.get("owner"),
            "cores": copy.deepcopy(prov.get("cores", [])),
            "buildings": copy.deepcopy(prov.get("buildings", [])),
            "resources": copy.deepcopy(prov.get("resources", {})),
            "units": copy.deepcopy(prov.get("units", []))
        }
    return state

def _apply_map_state(map_screen, state):
    import copy
    for color_key, saved_prov in state.items():
        prov = map_screen.map_data.get(color_key)
        if prov:
            prov["owner"] = saved_prov["owner"]
            prov["cores"] = copy.deepcopy(saved_prov["cores"])
            prov["buildings"] = copy.deepcopy(saved_prov["buildings"])
            prov["resources"] = copy.deepcopy(saved_prov["resources"])
            prov["units"] = copy.deepcopy(saved_prov["units"])
            
    # Apply the changes visually
    map_screen.refresh_all_maps()

def save_editor_state(map_screen):
    """Snapshots the current map data for the undo feature, clearing redo history."""
    if not hasattr(map_screen, 'editor_history'):
        map_screen.editor_history = []
    
    # Any new physical edit destroys the active redo-timeline
    map_screen.editor_redo_history = []
        
    map_screen.editor_history.append(_get_current_map_state(map_screen))
    
    if len(map_screen.editor_history) > c.MAX_EDITOR_HISTORY:
        map_screen.editor_history.pop(0)

def restore_editor_state(map_screen):
    """Restores the last map state from the editor history (Undo)."""
    if not getattr(map_screen, 'editor_history', []):
        map_screen.show_feedback("Nothing to undo!")
        return
        
    if not hasattr(map_screen, 'editor_redo_history'):
        map_screen.editor_redo_history = []
        
    # Save the current state to the redo stack before replacing it
    map_screen.editor_redo_history.append(_get_current_map_state(map_screen))
        
    last_state = map_screen.editor_history.pop()
    _apply_map_state(map_screen, last_state)
    map_screen.show_feedback("Undo Successful")

def redo_editor_state(map_screen):
    """Restores the next map state from the redo history (Redo)."""
    if not getattr(map_screen, 'editor_redo_history', []):
        map_screen.show_feedback("Nothing to redo!")
        return
        
    if not hasattr(map_screen, 'editor_history'):
        map_screen.editor_history = []
        
    # Save the current state to the undo stack before replacing it
    map_screen.editor_history.append(_get_current_map_state(map_screen))
        
    next_state = map_screen.editor_redo_history.pop()
    _apply_map_state(map_screen, next_state)
    map_screen.show_feedback("Redo Successful")

# ==========================================
# UI ABSTRACTION QUERIES
# ==========================================

def get_grouped_units(unit_library, by_family=True, unit_filter=None):
    """Buckets a unit library into {Infantry/Tanks/Navy: [names]} via classify_unit_group.

    `by_family=True` lists each base class once (the production columns);
    False lists every individual tier (the custom-production picker).
    `unit_filter(name, stats)` drops units the caller doesn't want listed.
    """
    groups = {UNIT_GROUP_INFANTRY: [], UNIT_GROUP_TANKS: [], UNIT_GROUP_NAVY: []}
    for name, stats in unit_library.items():
        if unit_filter and not unit_filter(name, stats):
            continue
        base = get_base_unit_name(name)
        entry = base if by_family else name
        bucket = groups[classify_unit_group(base, stats)]
        if entry not in bucket:
            bucket.append(entry)
    return groups

def get_ordered_unit_groups(unit_library):
    """Categorizes and sorts unit families into Infantry, Tanks, and Navy groups."""
    groups = get_grouped_units(unit_library)
    return groups[UNIT_GROUP_INFANTRY], groups[UNIT_GROUP_TANKS], groups[UNIT_GROUP_NAVY]

def was_original_owner(prov, nation, nation_data):
    """True if the tile belonged to `nation` before the current war started.

    Prefers the faction's pre-war border snapshot; without one it falls back to
    cores. Shared by the projected-peace preview and the treaty execution in
    diplomacy_agreements, which used to keep separate copies of this rule and
    could therefore disagree about what a treaty was going to do.
    """
    fac = nation_data.get(nation, {}).get("faction", "")
    if fac and "FACTION_WAR_MAPS" in nation_data and fac in nation_data["FACTION_WAR_MAPS"]:
        pre_war = nation_data["FACTION_WAR_MAPS"][fac]
        if str(prov["id"]) in pre_war:
            return pre_war[str(prov["id"])] == nation
    return nation in prov.get("cores", [])

def parse_peace_frozen_ids(peace_type):
    """Pulls the explicitly demanded/surrendered province ids out of a peace string."""
    match = re.search(r'\(Territories (?:demanded|surrendered): ([\d, ]+)', peace_type)
    if not match:
        return []
    return [int(x.strip()) for x in match.group(1).split(",") if x.strip().isdigit()]

def get_peace_winner_loser(peace_type, proposer, target):
    """Returns (winner, loser) for a treaty type, so the preview and the
    execution can never disagree about which side is taking territory."""
    return (proposer, target) if peace_type.startswith(c.PEACE_DEMAND_CLAIMS) else (target, proposer)

def get_projected_owner(prov, peace_type, proposer, target, nation_data):
    """Simulates the execution of a peace treaty to find who gets what territory."""
    curr = prov.get("owner")

    if peace_type.startswith(c.PEACE_WHITE_PEACE):
        return curr

    frozen_ids = parse_peace_frozen_ids(peace_type)
    winner, loser = get_peace_winner_loser(peace_type, proposer, target)
    claims = nation_data.get(winner, {}).get("claims", [])

    if curr == loser and (prov["id"] in frozen_ids or prov["id"] in claims
                          or was_original_owner(prov, winner, nation_data)):
        return winner

    return curr

# ==========================================
# FILE & ZIP IMPORT QUERIES
# ==========================================

def _export_to_downloads(file_name, produce, parent=None):
    """Sends a file to the user, however it gets made.

    Desktop: written straight into the real Downloads folder. Web: there is no
    real filesystem to write into, so it is built in the browser's virtual FS
    and then handed to platform.download_file(), which uses pygbag's JS bridge
    to push it out to the user's real Downloads folder as a browser download.

    `produce(dest_path)` is the only part that differs between exporting a
    zipped folder and copying one file -- the destination, the web/desktop
    split and the success/error dialogs were written out twice, identically.
    """
    from ui import confirm_dialog
    try:
        dest_path = file_name if IS_WEB else os.path.join(downloads_dir(), file_name)
        produce(dest_path)

        if IS_WEB:
            download_file(dest_path)
            confirm_dialog.show_success("Export Success", f"{file_name} downloaded.", tk_parent=parent)
        else:
            confirm_dialog.show_success("Export Success", f"Exported to Downloads as {file_name}", tk_parent=parent)
        return dest_path
    except Exception as e:
        confirm_dialog.show_error("Export Error", str(e), tk_parent=parent)
        return None

def export_dir_as_zip(source_dir, zip_name, parent=None):
    """Zips a folder and sends it to the user.

    Counterpart to extract_and_flatten_zip, and the single implementation
    behind every "Export" button (saves, scenarios).
    """
    def zip_it(dest_path):
        with zipfile.ZipFile(dest_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root_dir, _dirs, files in os.walk(source_dir):
                for file in files:
                    full = os.path.join(root_dir, file)
                    zipf.write(full, os.path.relpath(full, source_dir))

    return _export_to_downloads(zip_name, zip_it, parent)

def export_json_file(source_path, file_name, parent=None):
    """Copies a single JSON file to the user's Downloads folder."""
    return _export_to_downloads(file_name, lambda dest: shutil.copy2(source_path, dest), parent)

def import_json_file(game_state, title, on_loaded):
    """Prompts for a .json file, parses it, and hands the parsed object to
    on_loaded(data). Validating the shape and writing it anywhere is left to
    the caller -- different JSON files have different schemas, this just
    covers the shared "pick a file, parse it, report a read error" part.
    """
    from ui import confirm_dialog

    def _after_pick(file_path):
        if not file_path:
            return
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            confirm_dialog.show_error("Import Error", f"Couldn't read that file as JSON: {e}")
            return
        on_loaded(data)

    open_file_browser(game_state, title, downloads_dir(),
                      extensions=[".json"], on_result=_after_pick)

def import_zip_to_dir(game_state, target_parent_dir, on_success=None):
    """Prompts for a .zip and unpacks it into a folder named after the archive.

    Shared by the save and scenario import buttons; both used to open their own
    transient Tk root and duplicate the "_imported" collision suffix logic.
    """
    from pathlib import Path
    from ui import confirm_dialog

    def _after_pick(file_path):
        if not file_path:
            return
        target_dir = os.path.join(target_parent_dir, Path(file_path).stem)
        if os.path.exists(target_dir):
            target_dir += "_imported"
        try:
            extract_and_flatten_zip(file_path, target_dir)
            # Web only: mirror the imported save into IndexedDB (no-op unless
            # target_parent_dir is one of the persisted directories).
            sync_persisted_dir(target_parent_dir)
            confirm_dialog.show_success("Import Success", "Imported successfully.")
            if on_success:
                on_success()
        except Exception as e:
            confirm_dialog.show_error("Import Error", str(e))

    open_file_browser(game_state, "Select Zip File", downloads_dir(),
                      extensions=[".zip"], on_result=_after_pick)

def import_mod_file(game_state, on_success=None):
    """Prompts for a .py mod file and copies it into mods/, after a warning that
    it can run arbitrary code with the user's own permissions on next launch --
    a mod's first line just names the whole Python module it replaces (see
    mod_loader.py). Picking one isn't a fully sandboxed action even though the
    file itself looks like ordinary source: mods are sandboxed by *default*
    (mod_loader.is_mod_sandboxed falls back to True for anything with no entry
    yet, matching the Mods screen's default for a freshly imported mod), which
    blocks filesystem/process access but is a best-effort guard, not a
    hardened security boundary -- see mod_loader.py's "Sandboxing" section.

    The mod is also enabled by default (mod_loader.is_mod_enabled falls back
    to True for anything with no entry yet) but doesn't take effect until the
    game is restarted -- Python only imports a module once per process, so
    anything already running has already loaded the unmodded version.
    """
    from ui import confirm_dialog

    def _do_copy(file_path):
        target_name = os.path.basename(file_path)
        os.makedirs(c.MODS_DIR, exist_ok=True)
        dest = os.path.join(c.MODS_DIR, target_name)
        if os.path.exists(dest):
            stem, ext = os.path.splitext(target_name)
            dest = os.path.join(c.MODS_DIR, f"{stem}_imported{ext}")
        try:
            shutil.copy2(file_path, dest)
            sync_persisted_dir(c.MODS_DIR)
            confirm_dialog.show_success("Import Success",
                "Mod imported. Restart the game for it to take effect.")
            if on_success:
                on_success()
        except Exception as e:
            confirm_dialog.show_error("Import Error", str(e))

    def _after_pick(file_path):
        if not file_path:
            return
        confirm_dialog.ask_yes_no(
            "Install Mod?",
            "This mod replaces part of the game's own code. It will run "
            "sandboxed by default (no file or process access, see the Mods "
            "screen to change that) -- but sandboxing is a best-effort guard, "
            "not a hard security boundary.\n\n"
            "Only install mods from sources you trust.",
            lambda confirmed: _do_copy(file_path) if confirmed else None,
        )

    open_file_browser(game_state, "Select Mod (.py) File", downloads_dir(),
                      extensions=[".py"], on_result=_after_pick)

def import_character_portrait(game_state, on_success=None):
    """Prompts for an image file (starting in Downloads) and copies it into
    assets/characters/custom/, where the portrait picker's discover_character_images()
    picks it up like any curated portrait. Unlike import_mod_file, this needs no
    trust warning first -- an image can't run code, it can only be displayed.

    on_success, if given, is called with the new portrait's path relative to
    CHARACTERS_DIR (e.g. "Custom/photo.png").
    """
    from ui import confirm_dialog
    from ui.character_select_screen import CHARACTERS_DIR, CUSTOM_SUBDIR, IMAGE_EXTENSIONS

    custom_dir = os.path.join(CHARACTERS_DIR, CUSTOM_SUBDIR)

    def _after_pick(file_path):
        if not file_path:
            return
        target_name = os.path.basename(file_path)
        os.makedirs(custom_dir, exist_ok=True)
        dest = os.path.join(custom_dir, target_name)
        if os.path.exists(dest):
            stem, ext = os.path.splitext(target_name)
            dest = os.path.join(custom_dir, f"{stem}_imported{ext}")
        try:
            shutil.copy2(file_path, dest)
            sync_persisted_dir(custom_dir)
            if on_success:
                on_success(f"{CUSTOM_SUBDIR}/{os.path.basename(dest)}")
        except Exception as e:
            confirm_dialog.show_error("Import Error", str(e))

    open_file_browser(game_state, "Select a Portrait Image", downloads_dir(),
                      extensions=list(IMAGE_EXTENSIONS), on_result=_after_pick)

def ask_directory(game_state, title, initialdir, on_result):
    """Native folder picker; answers on_result with the chosen path, or None if cancelled."""
    open_file_browser(game_state, title, initialdir, mode="select_folder", on_result=on_result)

def ask_color(game_state, title, initial, on_result):
    """Native color picker; answers on_result with an (r, g, b) tuple, or None if cancelled."""
    from ui.color_picker_screen import ColorPickerScreen
    from ui.screen_runner import _run_pygame_sub_screen
    result = {}
    screen = ColorPickerScreen(game_state, title, initial, lambda color: result.setdefault("color", color))
    _run_pygame_sub_screen(game_state, screen, on_done=lambda: on_result(result.get("color")))

def extract_and_flatten_zip(zip_path, extract_target_dir):
    """
    Extracts a zip file and flattens it if the archiver created a redundant root directory.
    This fixes the issue where importing a map/mod creates folder/folder/data.json.
    """
    # Ensure the target directory exists before unpacking
    os.makedirs(extract_target_dir, exist_ok=True)

    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(extract_target_dir)

    # Remove macOS junk folder which often breaks the single directory check
    macosx_path = os.path.join(extract_target_dir, "__MACOSX")
    if os.path.exists(macosx_path):
        shutil.rmtree(macosx_path)

    # Filter out OS junk files (like .DS_Store on Mac) to see if there's only one REAL item
    valid_items = [item for item in os.listdir(extract_target_dir) if not item.startswith('.')]

    # If the only valid item extracted is a single directory, it's been nested. Let's flatten it.
    if len(valid_items) == 1:
        single_folder_path = os.path.join(extract_target_dir, valid_items[0])
        
        if os.path.isdir(single_folder_path):
            # Move all internal contents up one level into the target directory
            for item in os.listdir(single_folder_path):
                shutil.move(os.path.join(single_folder_path, item), extract_target_dir)
            
            # Clean up the now-empty redundant folder
            try:
                os.rmdir(single_folder_path)
            except OSError:
                shutil.rmtree(single_folder_path)
    else:
        # Fallback: If there are multiple items but map_data.json is hiding inside a subdirectory
        if not os.path.exists(os.path.join(extract_target_dir, "map_data.json")):
            for item in valid_items:
                potential_path = os.path.join(extract_target_dir, item)
                if os.path.isdir(potential_path) and os.path.exists(os.path.join(potential_path, "map_data.json")):
                    # Found the true map folder, flatten it!
                    for sub_item in os.listdir(potential_path):
                        shutil.move(os.path.join(potential_path, sub_item), extract_target_dir)
                    
                    try:
                        os.rmdir(potential_path)
                    except OSError:
                        shutil.rmtree(potential_path) # Fallback if hidden files got left behind
                    break
