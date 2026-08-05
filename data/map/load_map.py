import pygame
import json
import os
import re
import copy
from map_logic.system32.time_handler import TimeHandler
from data.io import country_io
import data.constants as c
from data import queries

def _load_default_images(map_obj):
    """Helper to ensure image data keys exist."""
    os.makedirs(c.FLAGS_DIR, exist_ok=True)
    os.makedirs(c.PORTRAITS_DIR, exist_ok=True)
    
    # Scrub existing massive b64 strings that match defaults instantly upon load to free RAM
    queries.scrub_default_images(map_obj.nation_data)
        
    for country_name, n_data in map_obj.nation_data.items():
        if not n_data.get("flag_data"):
            n_data["flag_data"] = "DEFAULT"
        if not n_data.get("portrait_data"):
            n_data["portrait_data"] = "DEFAULT"

def load_map_assets(self, load_path):
    # Ensure no residual data from a previous map persists during the load
    self.map_data = {}
    self.id_to_province = {}
    self.nation_data = {}
    self.history = {}
    self.raw_json_data = {}
    
    # --- UNIFIED SETTINGS LOADING ---
    scenario_settings = queries.get_scenario_settings()
    # Ensure we always have a dictionary to reference
    self.scenario_settings = copy.deepcopy(scenario_settings) if scenario_settings is not None else {
        "fog_of_war": c.DEFAULT_FOG_OF_WAR,
        "fog_of_war_strength": c.DEFAULT_FOG_OF_WAR_STRENGTH,
        "casus_belli_required": c.DEFAULT_CASUS_BELLI
    }
    queries.apply_global_scenario_flags(self.scenario_settings)
    print(f"[SYSTEM] Fog of War set to: {c.USE_FOG_OF_WAR}")

    # --- PROCEDURAL INTERCEPT ---
    if load_path == "PROCEDURAL":
        from map_logic.random_map import procedural_map_generator
        procedural_map_generator.generate_new_world(self)
        
        # After generating the base geography, setup standard variables
        self.player_country = "None"
        self.active_players = []
        self.current_player_index = 0
        self.loop_map = True
        self.time_manager = TimeHandler(start_year=c.START_YEAR)
        
        # Load the base nation templates so they are ready for the randomizer
        self.nation_data = copy.deepcopy(country_io.load_all_country_data())
        _load_default_images(self) 
        # --- THE FIX: Use .get() with a fallback color ---
        self.nation_colors = {name: tuple(stats.get("color", [150, 150, 150])) for name, stats in self.nation_data.items()}
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

    # --- 1. Image Assets ---
    # We no longer need the 'if load_path:' check because we guaranteed a path above
    self.terrain_map = pygame.image.load(os.path.join(load_path, "terrain.png")).convert()
    self.id_map = pygame.image.load(os.path.join(load_path, "id_map.png")).convert()
    
    # --- ADD THIS: Update map dimensions and camera constraints ---
    self.map_w, self.map_h = self.id_map.get_size()
    self.min_zoom = (c.SCREEN_HEIGHT - 120) / self.map_h
    
    try:
        self.political_map = pygame.image.load(os.path.join(load_path, "political.png")).convert()
    except:
        self.political_map = pygame.image.load(os.path.join(load_path, "id_map.png")).convert()
        
    try:
        self.cores_map = pygame.image.load(os.path.join(load_path, "cores.png")).convert()
    except:
        self.cores_map = self.id_map.copy() 

   # 2. Load Metadata (The Save File)
    save_meta = None
    meta_path = os.path.join(load_path, "meta.json")
    if os.path.exists(meta_path):
        with open(meta_path, "r") as f:
            save_meta = json.load(f)
            
    # 3. OVERRIDE: If we are loading an existing save file, prefer settings from inside the save
    # Do NOT override if we are in selection mode (starting a new scenario), so player UI choices are respected.
    if save_meta and "scenario_settings" in save_meta:
        if not getattr(self, 'selection_mode', False):
            # Scenario settings -- including unit/building disables -- only ever
            # apply when starting a NEW scenario. A save already in progress
            # keeps exactly what was baked in at creation, full stop; the Turn
            # Editor's current state (whatever it's since been changed to) must
            # never reach back into an already-played save.
            self.scenario_settings = save_meta["scenario_settings"]
            queries.apply_global_scenario_flags(self.scenario_settings)
        else:
            # Inject built-in scenario constants that shouldn't be wiped by the user's UI settings
            if "base_days_per_turn" in save_meta["scenario_settings"]:
                self.scenario_settings["base_days_per_turn"] = save_meta["scenario_settings"]["base_days_per_turn"]
            if "use_scripted_events" in save_meta["scenario_settings"]:
                self.scenario_settings["use_scripted_events"] = save_meta["scenario_settings"]["use_scripted_events"]

    # --- APPLY TURN OVERRIDES ---
    # Clear and reload libraries to ensure a clean slate before applying overrides
    # We MUST mutate the dictionaries inplace because UI screens hold pointers to them!
    unit_lib = queries.get_unit_library()
    building_lib = queries.get_building_library()
    
    with open(c.UNIT_DATA_PATH, "r") as f:
        unit_lib.clear()
        unit_lib.update(json.load(f))
        
    with open(c.BUILDING_DATA_PATH, "r") as f:
        building_lib.clear()
        building_lib.update(json.load(f))
    
    # Same family-name rule the turn editor writes these overrides with, so the
    # keys it saves always match the ones looked up here.
    for library, overrides, time_key in (
        (unit_lib, self.scenario_settings.get("unit_turn_overrides", {}), "production_time"),
        (building_lib, self.scenario_settings.get("building_turn_overrides", {}), "time"),
    ):
        for name, data in library.items():
            btype = queries.get_base_item_name(name)
            if btype in overrides:
                data[time_key] = overrides[btype]

    # --- APPLY DISABLED UNITS/BUILDINGS ---
    # A disabled base type is simply dropped from its library, which is already
    # how the rest of the codebase treats "doesn't exist" for buildability
    # (see the building filter below, and is_unit_unlocked's bare library
    # membership checks) -- there is no separate buildable/researchable flag.
    # Every tech key a removed variant would have unlocked is collected so the
    # tech tree can be pruned to match.
    disabled_units = set(self.scenario_settings.get("unit_disabled", []))
    disabled_buildings = set(self.scenario_settings.get("building_disabled", []))
    disabled_tech_keys = set()

    for name in [n for n in unit_lib if queries.get_base_item_name(n) in disabled_units]:
        tech_key = queries.get_unit_tech_key(queries.get_base_unit_name(name))
        if tech_key:
            disabled_tech_keys.add(tech_key)
        del unit_lib[name]

    for name in [n for n in building_lib if queries.get_base_item_name(n) in disabled_buildings]:
        tech_key, _lvl = queries.get_building_required_tech(name)
        if tech_key:
            disabled_tech_keys.add(tech_key)
        del building_lib[name]

    # Always reload tech_tree fresh from disk first, exactly like unit_lib/
    # building_lib above -- otherwise re-enabling a previously-disabled tech
    # leaves it pruned forever (this block would only ever repair keys that
    # are *currently* disabled, never undo a prune from an earlier load where
    # they weren't), and it'd keep looking that way until the app restarts
    # and the cache gets rebuilt from scratch.
    tech_tree = queries.get_tech_tree()
    with open(c.RESEARCH_TEMPLATE_PATH, "r") as f:
        tech_tree.clear()
        tech_tree.update(json.load(f))

    if disabled_tech_keys:
        for key in disabled_tech_keys:
            tech_tree.pop(key, None)

        # Any other tech that required a now-disabled tech has that leaf
        # bypassed (assumed fulfilled) rather than becoming permanently stuck.
        for tech_data in tech_tree.values():
            tech_data["req"] = queries.strip_disabled_tech_requirements(
                tech_data.get("req", {}), disabled_tech_keys)

    if load_path:
        history_path = os.path.join(load_path, "history.json")
        if os.path.exists(history_path):
            try:
                with open(history_path, "r") as f:
                    self.history = json.load(f)
            except Exception as e:
                print(f"Error loading history.json: {e}")

    if self.history_turn is not None and save_meta:
        turn_key = str(self.history_turn)
        if turn_key in self.history:
            snap = self.history[turn_key]
            save_meta["nation_data"] = snap.get("nation_data", save_meta.get("nation_data", {}))
            if "provinces" in snap:
                save_meta["provinces"] = snap["provinces"]
            
            if "date" not in save_meta:
                save_meta["date"] = {}
            save_meta["date"]["day"] = snap.get("day", save_meta["date"].get("day", 1))
            save_meta["date"]["month"] = snap.get("month", save_meta["date"].get("month", 0))
            save_meta["date"]["year"] = snap.get("year", save_meta["date"].get("year", 1910))
            save_meta["date"]["total_turns"] = int(self.history_turn)
            
            # Branches timeline by truncating future history to prevent paradoxes
            keys_to_delete = [k for k in self.history.keys() if int(k) > int(self.history_turn)]
            for k in keys_to_delete:
                del self.history[k]

    # --- 3. Load Nation Data (The Critical Fix) ---
    base_nation_data = copy.deepcopy(country_io.load_all_country_data())

    if save_meta and "nation_data" in save_meta:
        self.nation_data = save_meta["nation_data"]
        
        # SYNC FIX: Merge any missing research keys from the base template 
        # so old map saves instantly get the updated tech tree.
        for country, base_data in base_nation_data.items():
            if country not in self.nation_data:
                self.nation_data[country] = base_data
            else:
                # RELATIONS INIT
                if "relations" not in self.nation_data[country]:
                    self.nation_data[country]["relations"] = {}

                # SYNC FIX: Merge any missing top-level keys from the base template
                for base_key, base_val in base_data.items():
                    if base_key not in self.nation_data[country]:
                        self.nation_data[country][base_key] = base_val

                if "research" in base_data:
                    current_res = self.nation_data[country].setdefault("research", {})
                    for tech_key, tech_val in base_data["research"].items():
                        if tech_key not in current_res:
                            current_res[tech_key] = tech_val
    else:
        # Fallback to default starting data
        self.nation_data = base_nation_data

    # INITIALIZE RELATIONS FOR STARTING WARS & FACTIONS
    if c.DISABLE_FACTIONS:
        for c_name, c_data in self.nation_data.items():
            c_data["faction"] = ""
            c_data["allied_with"] = []

    if c.BATTLE_ROYALE_MODE:
        playable_nations = [n for n in self.nation_data.keys() if queries.is_playable(n, self.nation_data)]
        for c_name in playable_nations:
            c_data = self.nation_data[c_name]
            c_data["faction"] = ""
            c_data["allied_with"] = []
            if "master" in c_data:
                c_data["master"] = ""
            c_data["puppets"] = []
            c_data.setdefault("relations", {})
            c_data["at_war_with"] = [other for other in playable_nations if other != c_name]
            for other in c_data["at_war_with"]:
                c_data["relations"][other] = -100
    else:
        for c_name, c_data in self.nation_data.items():
            for enemy in c_data.get("at_war_with", []):
                c_data.setdefault("relations", {})[enemy] = -100
            
            fac = c_data.get("faction", "")
            if fac:
                for other_c, other_d in self.nation_data.items():
                    if other_c != c_name and other_d.get("faction", "") == fac:
                        c_data.setdefault("relations", {})[other_c] = 100

    if self.random_settings and "base_days_per_turn" in self.random_settings:
        self.scenario_settings["base_days_per_turn"] = self.random_settings["base_days_per_turn"]

    if disabled_tech_keys:
        # Every country template starts with a handful of techs pre-researched
        # (e.g. "infantry_type": 1, so basic Infantry is buildable turn one) --
        # if one of those is now disabled, that stale level has to go too, or
        # code that resolves "current researched year" from it (e.g.
        # get_infantry_family_year) falls back to a phantom unit name that was
        # just deleted from the library.
        for nation in self.nation_data.values():
            research = nation.get("research")
            if research:
                for key in disabled_tech_keys:
                    research.pop(key, None)

    _load_default_images(self)
    # --- THE FIX: Use .get() with a fallback color ---
    self.nation_colors = {name: tuple(stats.get("color", [150, 150, 150])) for name, stats in self.nation_data.items()}

    # --- 4. Set Player/Map Properties ---
    if save_meta:
        self.player_country = save_meta.get("player_country", "None")
        
        # --- HOTSEAT FIX ---
        # If we are in selection mode (new scenario/random map), we MUST start with an empty list
        if self.selection_mode:
            self.active_players = []
        else:
            # If loading a save, get the active players. Prevent ["None"] bug from older saves.
            loaded_players = save_meta.get("active_players", [self.player_country])
            self.active_players = [] if loaded_players == ["None"] else loaded_players
            
        self.current_player_index = save_meta.get("current_player_index", 0)
        self.loop_map = save_meta.get("loop_map", False)
        self.default_research = save_meta.get("default_research", None)
        self.script_variables = save_meta.get("script_variables", [])
        
        self.time_manager = TimeHandler(start_year=save_meta["date"]["year"])
        self.time_manager.day = save_meta["date"]["day"]
        self.time_manager.month_index = save_meta["date"]["month"]
        self.time_manager.total_turns = save_meta["date"].get("total_turns", 0)
    else:
        self.player_country = "None"
        self.active_players = []
        self.current_player_index = 0
        self.loop_map = True
        self.default_research = None
        self.script_variables = []
        self.time_manager = TimeHandler(start_year=c.START_YEAR)

    # --- 5. Province Processing ---
    json_path = os.path.join(load_path, "map_data.json")
    if not os.path.exists(json_path):
        raise FileNotFoundError(f"CRITICAL: map_data.json is missing from {load_path}")

    with open(json_path, "r") as f:
        self.raw_json_data = json.load(f)

    # Load building library to scrub removed buildings (like fuel refineries) from old saves
    bldg_lib = queries.get_building_library()

    def _unit_base_type(unit):
        """Resolves a stored unit's real type down to its turn-editor base type,
        unwrapping Convoy/Truck transports the same way sync_units_to_data does."""
        u_type = unit.get("original_type") or unit.get("type", "")
        if u_type.startswith("Convoy (") or u_type.startswith("Truck ("):
            match = re.search(r'\((.*?)\)', u_type)
            if match:
                u_type = match.group(1).strip()
        return queries.get_base_item_name(u_type)

    for k, v in self.raw_json_data.items():
        color_tuple = tuple(map(int, k.strip("()").split(",")))
        
        # Overlay save data onto provinces if it exists
        if save_meta and "provinces" in save_meta:
            saved_province = save_meta["provinces"].get(k)
            if saved_province:
                v.update(saved_province)
        
        # --- THE WATER FIX ---
        terrain = v.get("terrain", "plains")
        if terrain in c.WATER_MAPPING:
            v["owner"] = c.WATER_MAPPING[terrain]
        else:
            v["owner"] = v.get("owner", "None")
        # ---------------------

        v["cores"] = v.get("cores", [])
        # Removes any starting instance of a unit type this scenario has disabled.
        v["units"] = [u for u in v.get("units", []) if _unit_base_type(u) not in disabled_units]
        v["unit_queue"] = v.get("unit_queue", [])
        v["building_queue"] = v.get("building_queue", [])
        
        # Legacy save migration
        if "deployment_queue" in v:
            for q in v["deployment_queue"]:
                if q.get("order_type") == "BUILDING":
                    v["building_queue"].append(q)
                else:
                    v["unit_queue"].append(q)
            del v["deployment_queue"]
        
        # Clean obsolete buildings (Removes fuel buildings from older saves automatically)
        v["buildings"] = [b for b in v.get("buildings", []) if b in bldg_lib]

        res = v.get("resources", {})
        v["resources"] = res if isinstance(res, dict) else {}
        
        v["json_key"], v["map_color"] = k, color_tuple
        
        self.map_data[color_tuple] = v
        self.id_to_province[v["id"]] = v

    # --- CONVOY/TRUCK DEFENSE FIX ---
    # Older saves may have baked in a nonzero defense (inherited from whatever
    # unit was converted) onto Convoy/Truck transports. Transports should
    # always have 0 defense, so force it regardless of save version.
    for province in self.map_data.values():
        for unit in province.get("units", []):
            u_type = unit.get("type", "")
            if u_type.startswith("Convoy ("):
                unit["defense"] = c.CONVOY_DEF
            elif u_type.startswith("Truck ("):
                unit["defense"] = c.TRUCK_DEF

    # --- VERSION MIGRATION ---
    # Old (or version-less) saves carry unit stats baked in from whatever
    # balance patch they were created under. Rescale them to match the
    # currently loaded unit_data.json, preserving each unit's HP percentage.
    save_version = save_meta.get("version") if save_meta else None
    if save_version != c.GAME_VERSION:
        queries.migrate_units_to_current_stats(self.map_data, unit_lib)
        print(f"[SYSTEM] Migrated save from version '{save_version or 'unversioned'}' to '{c.GAME_VERSION}'.")

    # Init Pre-War Maps for Factions starting at war
    self.nation_data.setdefault("FACTION_WAR_MAPS", {})
    for c_name, c_data in self.nation_data.items():
        fac = c_data.get("faction", "")
        if fac and queries.is_faction_at_war(fac, self.nation_data):
            if fac not in self.nation_data["FACTION_WAR_MAPS"]:
                queries.save_faction_pre_war_map(fac, self.map_data, self.nation_data)

    # --- INITIALIZE SPAWNED TERRITORIES FOR INTEGRATED PUPPETS ---
    for c_name, c_data in self.nation_data.items():
        if c_data.get("puppet_type") == getattr(c, 'PUPPET_TYPE_INTEGRATED', 'INTEGRATED'):
            if "spawned_territories" not in c_data:
                c_data["spawned_territories"] = []
                for prov in self.map_data.values():
                    if prov.get("owner") == c_name:
                        c_data["spawned_territories"].append(prov["id"])

    # --- AUTO NAME STARTING UNITS ---
    unit_counters = {}
    for prov in self.map_data.values():
        for unit in prov.get("units", []):
            if not unit.get("custom_name"):
                unit["custom_name"] = queries.generate_unit_custom_name(unit, unit_counters)