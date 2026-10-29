import struct

from data.state_access import world_for, session_for, replace_mapping
import pygame
import json
import os
import re
import copy
from map_logic.system32.time_handler import TimeHandler
from data.io import country_io
import data.constants as c
from data import migrations, queries
# Preserve older imports without duplicate conversion rules.
from data.migrations import repair_faction_rosters
from data.map import history_io
from data.map.map_cache import OPTIONAL_LAYER_FILES

from data.runtime_rules import rebuild
from data.state_access import BackendState
from map_logic.random_map import procedural_map_generator
from map_logic.system32 import unit_events, movement_processor, economy_processor
from map_logic.diplomacy import diplomacy_lifecycle, faction_records, faction_leadership
from map_logic.territory import ownership as edit_province_ownership


def read_save_files(load_path):
    """Read meta.json, map_data.json, and the history of one save folder.

    Return (save_meta, map_data, history). save_meta is None for a map without
    meta.json. The files are not converted. See migrations.upgrade_save.
    """
    save_meta = None
    meta_path = os.path.join(load_path, "meta.json")
    if os.path.exists(meta_path):
        with open(meta_path, "r") as f:
            save_meta = json.load(f)
    json_path = os.path.join(load_path, "map_data.json")
    if not os.path.exists(json_path):
        raise FileNotFoundError(f"CRITICAL: map_data.json is missing from {load_path}")
    with open(json_path, "r") as f:
        map_data = json.load(f)
    # Prefers the compressed form, falls back to the plain history.json that
    # every save made before compression still carries.
    return save_meta, map_data, history_io.read(load_path)


def newer_version_message(load_path):
    """Return the update message for a save from a newer game, or None."""
    meta_path = os.path.join(load_path, "meta.json")
    if not os.path.exists(meta_path):
        return None
    try:
        with open(meta_path, "r") as f:
            version = json.load(f).get("version")
        migrations.check_version(version)
    except migrations.NewerVersionError as error:
        return str(error)
    except (OSError, ValueError, AttributeError):
        # The full load reports unreadable files with their own errors.
        return None
    return None


def _saved_player_view(save_meta):
    """Return the offline viewing identity and active-player list for a save.

    Real-time matches save the authoritative server map. That map correctly
    uses ``None`` during the live session, but a completed result loaded from
    disk is an ordinary offline spectator replay.
    """
    realtime_match = save_meta.get("realtime_match")
    if isinstance(realtime_match, dict) and realtime_match.get("offline_view") == "spectator":
        return "Spectator", []
    player_country = save_meta.get("player_country", "None")
    loaded_players = save_meta.get("active_players", [player_country])
    return player_country, [] if loaded_players == ["None"] else loaded_players


def _repair_province(province, building_library):
    """Give a loaded province its queue lists and drop buildings the active library lacks."""
    province.setdefault("unit_queue", [])
    province.setdefault("building_queue", [])
    province["buildings"] = [name for name in province.get("buildings", []) if name in building_library]
    resources = province.get("resources", {})
    province["resources"] = resources if isinstance(resources, dict) else {}

def _load_default_images(map_obj, *, scrub_images=True):
    """Helper to ensure image data keys exist."""
    os.makedirs(c.FLAGS_DIR, exist_ok=True)
    os.makedirs(c.PORTRAITS_DIR, exist_ok=True)

    # Scrub existing massive b64 strings that match defaults instantly upon load to free RAM
    if scrub_images:
        queries.scrub_default_images(map_obj.nation_data)

    for country_name, n_data in map_obj.nation_data.items():
        if not n_data.get("flag_data"):
            n_data["flag_data"] = "DEFAULT"
        if not n_data.get("portrait_data"):
            n_data["portrait_data"] = "DEFAULT"


def _apply_history_snapshot(save_meta, history, history_turn):
    """Apply a selected turn to metadata before province state is loaded."""
    turn_key = str(history_turn)
    if turn_key not in history:
        return False

    snap = history[turn_key]
    if not isinstance(snap, dict):
        return False

    # Keep the selected turn immutable.  Loading a snapshot adds defaults and
    # may later resolve a turn, so sharing these objects with history would
    # silently rewrite the timeline that the player selected.
    if isinstance(snap.get("nation_data"), dict):
        save_meta["nation_data"] = copy.deepcopy(snap["nation_data"])
    if isinstance(snap.get("provinces"), dict):
        save_meta["provinces"] = copy.deepcopy(snap["provinces"])
    if "factions" in snap:
        save_meta["factions"] = copy.deepcopy(snap["factions"])
    else:
        save_meta.pop("factions", None)

    if "date" not in save_meta:
        save_meta["date"] = {}
    save_meta["date"]["day"] = snap.get("day", save_meta["date"].get("day", 1))
    save_meta["date"]["month"] = snap.get("month", save_meta["date"].get("month", 0))
    save_meta["date"]["year"] = snap.get("year", save_meta["date"].get("year", 1910))
    save_meta["date"]["total_turns"] = int(history_turn)

    # Branch the timeline by discarding future turns, as before.
    keys_to_delete = [key for key in history if int(key) > int(history_turn)]
    for key in keys_to_delete:
        del history[key]
    return True


def load_map_assets(map_screen, load_path, scenario_settings=None, *, load_presentation=True):
    # Ensure no residual data from a previous map persists during the load
    world_state = world_for(map_screen)
    session_state = session_for(map_screen)
    replace_mapping(world_state, "map_data", {})
    replace_mapping(world_state, "id_to_province", {})
    replace_mapping(world_state, "nation_data", {})
    world_state.factions = {}
    world_state.factions_initialized = False
    map_screen.country_economy_summaries = {}
    replace_mapping(world_state, "history", {})
    replace_mapping(world_state, "raw_json_data", {})

    # --- UNIFIED SETTINGS LOADING ---
    if scenario_settings is None:
        scenario_settings = queries.get_scenario_settings()
    # Ensure we always have a dictionary to reference
    replace_mapping(world_state, "scenario_settings", copy.deepcopy(scenario_settings) if scenario_settings is not None else {
        "fog_of_war": c.DEFAULT_FOG_OF_WAR,
        "fog_of_war_strength": c.DEFAULT_FOG_OF_WAR_STRENGTH,
        "casus_belli_required": c.DEFAULT_CASUS_BELLI,
        "truce_turns": c.DEFAULT_TRUCE_TURNS,
        "force_time_appropriate_research": c.DEFAULT_FORCE_TIME_APPROPRIATE_RESEARCH,
    })

    # --- PROCEDURAL INTERCEPT ---
    if load_path == "PROCEDURAL":
        procedural_map_generator.generate_new_world(map_screen)

        # After generating the base geography, setup standard variables
        session_state.player_country = "None"
        session_state.active_players = []
        session_state.current_player_index = 0
        world_state.loop_map = True
        world_state.time_manager = TimeHandler(start_year=c.START_YEAR)

        # Load the base nation templates so they are ready for the randomizer
        replace_mapping(world_state, "nation_data", copy.deepcopy(country_io.load_all_country_data()))
        _load_default_images(map_screen, scrub_images=load_presentation)
        map_screen.nation_colors = country_io.nation_colors_from(world_state.nation_data)
        rebuild(map_screen)
        return

    # --- ZIP FILE INTERCEPT ---
    if load_path and str(load_path).lower().endswith(".zip"):
        extract_target = str(load_path)[:-4] # Strip the .zip extension
        queries.extract_and_flatten_zip(load_path, extract_target)
        load_path = extract_target

    # --- DEFAULT FALLBACK LOGIC ---
    # If no path is provided (e.g., on main menu boot), default to the first available base map
    if not load_path:
        if os.path.exists(c.BASE_MAPS_DIR):
            available_maps = [d for d in os.listdir(c.BASE_MAPS_DIR) if os.path.isdir(os.path.join(c.BASE_MAPS_DIR, d))]
            if available_maps:
                load_path = os.path.join(c.BASE_MAPS_DIR, available_maps[0])

    if not load_path or not os.path.exists(load_path):
        raise FileNotFoundError(f"CRITICAL: No valid map found. Make sure {c.BASE_MAPS_DIR} contains at least one map folder.")

    if load_presentation:
        # --- 1. Image Assets ---
        # We no longer need the 'if load_path:' check because we guaranteed a path above
        map_screen.terrain_map = pygame.image.load(os.path.join(load_path, "terrain.png")).convert()
        map_screen.id_map = pygame.image.load(os.path.join(load_path, "id_map.png")).convert()

        # --- ADD THIS: Update map dimensions and camera constraints ---
        world_state.map_w, world_state.map_h = map_screen.id_map.get_size()
        map_screen.min_zoom = (c.SCREEN_HEIGHT - 120) / world_state.map_h

        try:
            map_screen.political_map = pygame.image.load(
                os.path.join(load_path, OPTIONAL_LAYER_FILES["political"])).convert()
        except Exception:
            map_screen.political_map = pygame.image.load(os.path.join(load_path, "id_map.png")).convert()

        try:
            map_screen.cores_map = pygame.image.load(
                os.path.join(load_path, OPTIONAL_LAYER_FILES["cores"])).convert()
        except Exception:
            map_screen.cores_map = map_screen.id_map.copy()

    else:
        with open(os.path.join(load_path, "id_map.png"), "rb") as stream:
            header = stream.read(24)
        if len(header) != 24 or not header.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("The map id_map.png must be a PNG image.")
        world_state.map_w, world_state.map_h = struct.unpack(">II", header[16:24])

    # 2. Read the save and convert it to the current version before any of it is used.
    save_meta, raw_map_data, history = read_save_files(load_path)
    migrations.upgrade_save(save_meta if save_meta is not None else {}, raw_map_data, history)

    # 3. OVERRIDE: If we are loading an existing save file, prefer settings from inside the save
    # Do NOT override if we are in selection mode (starting a new scenario), so player UI choices are respected.
    if save_meta and "scenario_settings" in save_meta:
        if not getattr(session_for(map_screen), 'selection_mode', False):
            # Scenario settings -- including unit/building disables -- only ever
            # apply when starting a NEW scenario. A save already in progress
            # keeps exactly what was baked in at creation, full stop; the Turn
            # Editor's current state (whatever it's since been changed to) must
            # never reach back into an already-played save.
            replace_mapping(world_state, "scenario_settings", save_meta["scenario_settings"])
        else:
            # Inject built-in scenario constants that shouldn't be wiped by the user's UI settings
            if "base_days_per_turn" in save_meta["scenario_settings"]:
                world_state.scenario_settings["base_days_per_turn"] = save_meta["scenario_settings"]["base_days_per_turn"]
            if "use_scripted_events" in save_meta["scenario_settings"]:
                world_state.scenario_settings["use_scripted_events"] = save_meta["scenario_settings"]["use_scripted_events"]
            if "force_time_appropriate_research" in save_meta["scenario_settings"]:
                world_state.scenario_settings["force_time_appropriate_research"] = save_meta["scenario_settings"]["force_time_appropriate_research"]
    elif save_meta and not session_state.selection_mode:
        # Saves from before scenario settings must not inherit new range preferences.
        world_state.scenario_settings.pop("unit_range_overrides", None)

    # Base maps and older scenarios may not have stored this setting yet. Add
    # the effective default to the live settings so an editor save writes it
    # explicitly to the new map's meta.json.
    world_state.scenario_settings.setdefault(
        "force_time_appropriate_research",
        c.DEFAULT_FORCE_TIME_APPROPRIATE_RESEARCH,
    )

    # Active libraries and indexes belong to this world.
    runtime = rebuild(map_screen)
    unit_lib = runtime.libraries["unit_library"]
    building_lib = runtime.libraries["building_library"]
    tech_tree = runtime.libraries["tech_tree"]
    disabled_tech_keys = runtime.disabled_tech_keys
    disabled_units = set(world_state.scenario_settings.get("unit_disabled", []))
    disabled_buildings = set(world_state.scenario_settings.get("building_disabled", []))

    replace_mapping(world_state, "history", history)

    if save_meta:
        # This compares saved research years with the active tree, so it runs on every load.
        migrations.migrate_infantry_research(save_meta, tech_tree, world_state.history)

    if map_screen.history_turn is not None and save_meta:
        _apply_history_snapshot(save_meta, world_state.history, map_screen.history_turn)

    # --- 3. Load Nation Data (The Critical Fix) ---
    if save_meta and "nation_data" in save_meta:
        replace_mapping(world_state, "nation_data", save_meta["nation_data"])
        map_screen.country_economy_summaries = save_meta.get("country_economy_summaries", {})
    else:
        # Fallback to default starting data
        replace_mapping(world_state, "nation_data", {})
    # Restore empty template references and retain the legacy missing-field/
    # research migration through one shared path. Editor countries remain
    # fully available even when their saved records contain no duplicated data.
    queries.merge_country_templates(world_state.nation_data)

    # Relation scores are derived on demand by queries.get_relation_score from
    # at_war_with / faction / master / temp_modifiers / claims, so there is no
    # stored table to seed here.
    if queries.get_scenario_flag("disable_factions", c.DEFAULT_DISABLE_FACTIONS, world_state.scenario_settings):
        for c_name, c_data in world_state.nation_data.items():
            c_data["faction"] = ""

    if queries.get_scenario_flag("battle_royale", c.DEFAULT_BATTLE_ROYALE, world_state.scenario_settings):
        playable_nations = [n for n in world_state.nation_data.keys() if queries.is_playable(n, world_state.nation_data)]
        for c_name in playable_nations:
            c_data = world_state.nation_data[c_name]
            c_data["faction"] = ""
            if "master" in c_data:
                c_data["master"] = ""
            c_data["puppets"] = []
            c_data["at_war_with"] = [other for other in playable_nations if other != c_name]

    if map_screen.random_settings and "base_days_per_turn" in map_screen.random_settings:
        world_state.scenario_settings["base_days_per_turn"] = map_screen.random_settings["base_days_per_turn"]

    if disabled_tech_keys:
        # Every country template starts with a handful of techs pre-researched
        # (e.g. "infantry_type": 1, so basic Infantry is buildable turn one) --
        # if one of those is now disabled, that stale level has to go too, or
        # code that resolves "current researched year" from it (e.g.
        # get_infantry_family_year) falls back to a phantom unit name that was
        # just deleted from the library.
        for nation in world_state.nation_data.values():
            research = nation.get("research")
            if research:
                for key in disabled_tech_keys:
                    research.pop(key, None)

    _load_default_images(map_screen, scrub_images=load_presentation)
    # --- THE FIX: Use .get() with a fallback color ---
    map_screen.nation_colors = country_io.nation_colors_from(world_state.nation_data)

    # --- 4. Set Player/Map Properties ---
    if save_meta:
        saved_player_country, saved_active_players = _saved_player_view(save_meta)
        session_state.player_country = saved_player_country

        # --- HOTSEAT FIX ---
        # If we are in selection mode (new scenario/random map), we MUST start with an empty list
        if session_state.selection_mode:
            session_state.active_players = []
        else:
            session_state.active_players = saved_active_players

        session_state.current_player_index = save_meta.get("current_player_index", 0)
        world_state.loop_map = save_meta.get("loop_map", False)
        world_state.default_research = save_meta.get("default_research", None)
        world_state.script_variables = save_meta.get("script_variables", [])

        world_state.time_manager = TimeHandler(start_year=save_meta["date"]["year"])
        world_state.time_manager.day = save_meta["date"]["day"]
        world_state.time_manager.month_index = save_meta["date"]["month"]
        world_state.time_manager.total_turns = save_meta["date"].get("total_turns", 0)
    else:
        session_state.player_country = "None"
        session_state.active_players = []
        session_state.current_player_index = 0
        world_state.loop_map = True
        world_state.default_research = None
        world_state.script_variables = []
        world_state.time_manager = TimeHandler(start_year=c.START_YEAR)

    unit_events.restore(map_screen, {} if session_state.selection_mode or session_state.is_editor else save_meta or {})

    # Loading a scenario supplies its saved/default player metadata, which is
    # deliberately ``None`` for an unstarted map.  The editor is not an
    # unstarted player session, though: it owns no nation and must retain its
    # distinct sentinel after both its initial load and a later Load action.
    if session_state.is_editor:
        session_state.player_country = "Editor"
        session_state.active_players = []
        session_state.current_player_index = 0
        session_state.selection_mode = False

    # --- HISTORICAL LEADERS TIMELINE ---
    # Only scenarios launched straight out of scenarios/historical get the
    # Historical Leaders Editor's dated overrides -- alternate/custom/random
    # maps and in-progress saves (which live under saves/) are untouched.
    if load_path and c.SCENARIOS_HISTORICAL_DIR.replace("\\", "/") in str(load_path).replace("\\", "/"):
        tm = world_state.time_manager
        queries.apply_historical_leader_timeline(world_state.nation_data, tm.year, tm.month_index, tm.day)

    # --- 5. Province Processing ---
    replace_mapping(world_state, "raw_json_data", raw_map_data)
    bldg_lib = queries.get_building_library(map_screen)

    def _unit_base_type(unit):
        """Resolves a stored unit's real type down to its turn-editor base type,
        unwrapping Convoy/Truck transports the same way sync_units_to_data does."""
        u_type = unit.get("original_type") or unit.get("type", "")
        if u_type.startswith("Convoy (") or u_type.startswith("Truck ("):
            match = re.search(r'\((.*?)\)', u_type)
            if match:
                u_type = match.group(1).strip()
        return queries.get_base_item_name(u_type, context=map_screen)

    # Older saves kept mutable province values in meta.json. New saves store
    # those values directly in map_data.json; this overlay remains for old saves
    # and history snapshots that still include a per-turn province block.
    if save_meta and "provinces" in save_meta:
        queries.overlay_saved_province_data(
            world_state.raw_json_data, save_meta["provinces"])

    for k, v in world_state.raw_json_data.items():
        color_tuple = tuple(map(int, k.strip("()").split(",")))

        # --- THE WATER FIX ---
        terrain = v.get("terrain", "plains")
        if terrain in c.WATER_MAPPING:
            v["owner"] = c.WATER_MAPPING[terrain]
        else:
            v["owner"] = v.get("owner", "None")
        # ---------------------

        v["cores"] = v.get("cores", [])
        # Remove disabled units from provinces and transport cargo.
        for unit in v.get("units", []):
            cargo = unit.get("air_cargo")
            if isinstance(cargo, list):
                unit["air_cargo"] = [carried for carried in cargo
                                     if _unit_base_type(carried) not in disabled_units]
        v["units"] = [u for u in v.get("units", []) if _unit_base_type(u) not in disabled_units]
        _repair_province(v, bldg_lib)

        v["json_key"], v["map_color"] = k, color_tuple

        world_state.map_data[color_tuple] = v
        world_state.id_to_province[v["id"]] = v

    # Units always take their stats from the active library.
    queries.refresh_unit_stats(world_state.map_data, world_state.nation_data, unit_lib)
    queries.normalize_air_orders(world_state.map_data)
    if load_presentation:
        queries.build_air_geometry(map_screen)
    else:
        # Geometry needs pixels, but a backend retains no display surface.
        queries.build_air_geometry(map_screen, pygame.image.load(os.path.join(load_path, "id_map.png")))

    # --- REPAIR FACTION ROSTERS ---
    # Runs before the pre-war maps below, which are built off the rosters.
    diplomacy_lifecycle.normalize_diplomacy_channels(world_state.nation_data)
    if save_meta and "factions" in save_meta:
        faction_records.restore(map_screen, save_meta["factions"])
    else:
        # Preserve the established repair order before converting old country fields.
        migrations.repair_faction_rosters(dict(world_state.nation_data), world_state.map_data)
        faction_records.restore(map_screen)
    if (queries.get_scenario_flag("disable_factions", c.DEFAULT_DISABLE_FACTIONS, world_state.scenario_settings)
            or queries.get_scenario_flag("battle_royale", c.DEFAULT_BATTLE_ROYALE, world_state.scenario_settings)):
        world_state.factions.clear()
        faction_records.project(map_screen)

    # A saved game can be written immediately after the last territorial
    # faction member falls. Do not revive that exhausted bloc on load: without
    # a member that owns land, its exiles have no path back into the world.
    if not session_state.is_editor:
        exhausted_factions = edit_province_ownership.retire_exhausted_factions(map_screen)
        if exhausted_factions:
            # Retiring a normal nation removes its diplomacy immediately; this
            # completes the other half of ordinary cleanup for former exiles.
            movement_processor.process_dead_nations(map_screen)

    # A faction needs a chair before any screen, peace negotiation, or AI can
    # reason about it.  Turn processing heals this state too, but a loaded save
    # must already be internally consistent before its first turn.
    faction_leadership.repair_leaderless_factions(map_screen)

    # Init Pre-War Maps for Factions starting at war
    world_state.nation_data.setdefault("FACTION_WAR_MAPS", {})
    for c_name, c_data in world_state.nation_data.items():
        fac = c_data.get("faction", "")
        if fac and queries.is_faction_at_war(fac, world_state.nation_data):
            if fac not in world_state.nation_data["FACTION_WAR_MAPS"]:
                queries.save_faction_pre_war_map(fac, world_state.map_data, world_state.nation_data)

    queries.repair_spawned_territories(world_state.nation_data, world_state.map_data)

    # --- AUTO NAME STARTING UNITS ---
    unit_counters = {}
    for prov in world_state.map_data.values():
        for unit in queries.units_with_air_cargo(prov.get("units", [])):
            if not unit.get("custom_name"):
                unit["custom_name"] = queries.generate_unit_custom_name(unit, unit_counters, context=map_screen)

    # Army rosters are saved on countries while their members live in
    # provinces.  Repair both ends together after every map load, including
    # legacy maps which need persistent unit IDs generated for the first time.
    queries.normalize_armies(world_state.nation_data, world_state.map_data)

    # --- FORCE TIME-APPROPRIATE RESEARCH ---
    # Only when actually starting a fresh game from a scenario (selection_mode) --
    # never on a save already in progress, where research has since moved on
    # through normal play, and never on an editor load, which drives this itself
    # (see research_screens.py / date_economy_screens.py) so manual per-nation
    # edits between those triggers aren't clobbered on every re-open.
    if getattr(session_for(map_screen), 'selection_mode', False) and queries.get_scenario_flag(
            "force_time_appropriate_research", c.DEFAULT_FORCE_TIME_APPROPRIATE_RESEARCH,
            world_state.scenario_settings):
        queries.apply_time_appropriate_research_to_map(map_screen, world_state.time_manager.year)


def load_backend_state(load_path, *, is_scenario=False, scenario_settings=None, history_turn=None,
                       skip_initial_income=False, feedback=None):
    """Load the same world rules without surfaces, widgets, or a map screen."""
    context = BackendState(feedback=feedback)
    context.load_path = load_path
    context.history_turn = history_turn
    context.session.selection_mode = is_scenario
    load_map_assets(context, load_path, scenario_settings, load_presentation=False)
    economy_processor.initialize_income(context, skip=skip_initial_income)
    return context
