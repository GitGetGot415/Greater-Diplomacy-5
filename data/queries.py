import json
import os
import re
import base64
import itertools
import math
import threading

import pygame

import data.constants as c

def get_imperial_family(nation, nation_data):
    """Returns a set containing the nation, its master (if any), and all related puppets."""
    family = set([nation])
    master = nation_data.get(nation, {}).get("master", "")
    top_dog = master if master else nation
    family.add(top_dog)
    family.update(nation_data.get(top_dog, {}).get("puppets", []))
    return family

def get_visible_provinces(player_country, map_data, nation_data):
    """Calculates and returns a set of province IDs currently visible to the player."""
    if player_country in ["Spectator", "Editor", "None"] or player_country not in nation_data:
        return None # Returns None to signify "Full Visibility / Ignore Fog"
        
    friendly_nations = set()
    friendly_nations.update(get_imperial_family(player_country, nation_data))
    
    player_faction = nation_data[player_country].get("faction", "")
    if player_faction:
        friendly_nations.update(get_faction_members(player_faction, nation_data))
        
    visible_set = set()
    
    for prov in map_data.values():
        owner = prov.get("owner", "")
        
        has_friendly_unit = False
        for u in prov.get("units", []):
            if u.get("owner") in friendly_nations:
                has_friendly_unit = True
                break
                
        # If we own it, or a friendly unit is on it, it (and its neighbors) are visible
        if owner in friendly_nations or has_friendly_unit:
            visible_set.add(prov["id"])
            visible_set.update(prov.get("neighbors", []))
                
    return visible_set

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
    "active_albums": {"path": c.ACTIVE_ALBUMS_PATH, "data": None}
}

def scenario_has_scripted_events(nation_data):
    """Checks if any nation in the scenario has scripted events."""
    for data in nation_data.values():
        if isinstance(data, dict) and data.get("scripted_events"):
            return True
    return False

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
            json.dump(safe_data, f, indent=4)
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
            json.dump(new_data, f, indent=4)
    except Exception as e:
        print(f"Error saving {cache_obj['path']}: {e}")

def save_global_settings(controller):
    """Unified helper to save all settings directly from the controller state."""
    from data.io import keybind_io
    import data.constants as c
    
    keybind_io.save_settings(
        controller.keybinds,
        controller.sfx_volume,
        controller.music_volume,
        controller.num_players,
        controller.ai_mode,
        controller.gemini_api_key,
        controller.chatgpt_api_key,
        controller.claude_api_key,
        controller.ollama_api_key,
        controller.gemini_model,
        controller.chatgpt_model,
        controller.claude_model,
        controller.ollama_model,
        controller.ai_immersion_level,
        controller.music_pitch,
        controller.sfx_pitch,
        controller.target_fps,
        controller.ai_threads,
        controller.show_fps,
        controller.drag_mouse_button_toggle
    )

def get_ai_threads():
    return get_settings().get("ai_threads", c.DEFAULT_AI_THREADS)

# --- REFACTORED GETTERS (No paths needed here anymore!) ---
def get_settings(): return _load_cached_json("settings")
def get_unit_library(): return _load_cached_json("unit_library")
def get_building_library(): return _load_cached_json("building_library")
def get_tech_tree(): return _load_cached_json("tech_tree")
def get_country_data(): return _load_cached_json("country_data")
def get_active_albums(): return _load_cached_json("active_albums")

# ==========================================
# DIPLOMACY & COMBAT QUERIES
# ==========================================

def get_combined_enemy_strength(target_nation, map_data, nation_data):
    """Calculates the total military strength of everyone actively fighting the target."""
    total_str = 0
    enemies = nation_data.get(target_nation, {}).get("at_war_with", [])
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
    strength = 0
    counted = set()
    
    # Add faction members
    faction = nation_data.get(nation, {}).get("faction", "")
    if faction:
        for member in get_faction_members(faction, nation_data):
            if member not in counted:
                strength += get_military_strength(member, map_data)
                counted.add(member)
                
    # Add Imperial Family (Master & Puppets)
    family = get_imperial_family(nation, nation_data)
    for fam_member in family:
        if fam_member not in counted:
            strength += get_military_strength(fam_member, map_data)
            counted.add(fam_member)
                
    # Add direct allies if they aren't already counted
    allies = nation_data.get(nation, {}).get("allied_with", [])
    for ally in allies:
        if ally not in counted:
            strength += get_military_strength(ally, map_data)
            counted.add(ally)
            
    return strength

def get_military_strength(nation, map_data):
    """Calculates rough military strength of a nation based on unit stats."""
    strength = 0
    for prov in map_data.values():
        for u in prov.get("units", []):
            if u.get("owner") == nation:
                hp_val = u.get("health", 0) / c.MILITARY_STRENGTH_HEALTH_DIVISOR
                strength += u.get("attack", 0) + u.get("defense", 0) + hp_val
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
        friendly_nations = set([evaluating_nation])
        faction = nation_data.get(evaluating_nation, {}).get("faction", "")
        if faction:
            friendly_nations.update(get_faction_members(faction, nation_data))
        friendly_nations.update(get_imperial_family(evaluating_nation, nation_data))
        friendly_nations.update(nation_data.get(evaluating_nation, {}).get("allied_with", []))
        
        for prov_id in prov_ids:
            prov = id_to_province.get(prov_id)
            if prov:
                # Gather all friendly units on this tile
                friendly_units = [u for u in prov.get("units", []) if u.get("owner") in friendly_nations]
                
                # Cap by combat width (MAX_COMBAT_ATTACKERS) prioritizing best units
                top_units = sorted(friendly_units, key=lambda x: x.get("attack", 0) + x.get("defense", 0), reverse=True)[:c.MAX_COMBAT_ATTACKERS]
                
                tile_strength = 0
                for u in top_units:
                    hp_val = u.get("health", 0) / c.MILITARY_STRENGTH_HEALTH_DIVISOR
                    base_str = u.get("attack", 0) + u.get("defense", 0) + hp_val
                    
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
    return nation_b in nation_data.get(nation_a, {}).get("at_war_with", [])

def is_province_in_active_combat(province, nation_data):
    """Returns True if ANY units from mutually hostile nations occupy this province."""
    units = province.get("units", [])
    if len(units) < 2:
        return False
        
    owners_present = list(set(u.get("owner") for u in units if u.get("owner")))
    
    # Optimized check using itertools
    return any(are_at_war(o1, o2, nation_data) for o1, o2 in itertools.combinations(owners_present, 2))

def is_nation_in_combat_here(nation, province, nation_data):
    """Returns True if the specified nation has units in the province that are actively engaged with enemy units."""
    units = province.get("units", [])
    enemies = nation_data.get(nation, {}).get("at_war_with", [])
    return any(u.get("owner") in enemies for u in units)

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
    return [n for n, d in list(nation_data.items()) if d.get("faction") == faction_name]

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

    # --- NEW: Check Pre-War Faction Map First ---
    if "FACTION_WAR_MAPS" in nation_data and faction_name in nation_data["FACTION_WAR_MAPS"]:
        pre_war_map = nation_data["FACTION_WAR_MAPS"][faction_name]
        original_owner = pre_war_map.get(str(province["id"])) or pre_war_map.get(province["id"])
        
        # If the original owner is still in the faction, they get it back!
        if original_owner and original_owner != capturer:
            if original_owner in get_faction_members(faction_name, nation_data):
                return original_owner

    # Fallback to standard core logic
    faction_members = get_faction_members(faction_name, nation_data)
    tile_cores = province.get("cores", [])

    # Find how many active faction members have a core on this specific tile
    faction_cores_on_tile = [member for member in faction_members if member in tile_cores]

    # Only transfer if EXACTLY ONE faction member has a core on this territory
    if len(faction_cores_on_tile) == 1:
        return faction_cores_on_tile[0]
    
    # If 2 or more faction members have a core, or nobody does, the capturer keeps the tile
    return capturer

# --- NEW FACTION WAR BORDER TRACKING QUERIES ---
def is_faction_at_war(faction_name, nation_data):
    """Returns True if any member of the given faction is actively at war."""
    members = get_faction_members(faction_name, nation_data)
    return any(len(nation_data.get(m, {}).get("at_war_with", [])) > 0 for m in members)

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

def add_member_to_pre_war_map(member_name, faction_name, map_data, nation_data):
    """Adds a newly joined member's territory to the active pre-war map."""
    if "FACTION_WAR_MAPS" in nation_data and faction_name in nation_data["FACTION_WAR_MAPS"]:
        for prov in map_data.values():
            if prov.get("owner") == member_name:
                nation_data["FACTION_WAR_MAPS"][faction_name][str(prov["id"])] = member_name

def remove_member_from_pre_war_map(member_name, faction_name, nation_data):
    """Removes a leaving member's territory from the active pre-war map."""
    if "FACTION_WAR_MAPS" in nation_data and faction_name in nation_data["FACTION_WAR_MAPS"]:
        pre_war_map = nation_data["FACTION_WAR_MAPS"][faction_name]
        keys_to_remove = [prov_id for prov_id, owner in pre_war_map.items() if owner == member_name]
        for k in keys_to_remove:
            del pre_war_map[k]

def clear_faction_pre_war_map_if_peace(faction_name, nation_data):
    """Clears the pre-war map if the faction is no longer at war."""
    if not is_faction_at_war(faction_name, nation_data):
        if "FACTION_WAR_MAPS" in nation_data and faction_name in nation_data["FACTION_WAR_MAPS"]:
            del nation_data["FACTION_WAR_MAPS"][faction_name]

# ==========================================
# MOVEMENT QUERIES
# ==========================================

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

def can_ships_enter(moving_nation, target_province, nation_data):
    """Centralized rules for naval movement."""
    is_water = target_province.get("terrain") in c.WATER_TERRAINS
    if is_water:
        return True
        
    if not target_province.get("is_coastal", False):
        return False
        
    target_owner = target_province.get("owner", "Unclaimed")
    
    # Ships can only enter friendly or unowned ports
    is_faction = are_in_same_faction(moving_nation, target_owner, nation_data)
    is_ally = target_owner in nation_data.get(moving_nation, {}).get("allied_with", [])
    is_family = target_owner in get_imperial_family(moving_nation, nation_data)
    
    return target_owner == moving_nation or is_faction or is_ally or is_family or target_owner == "Unclaimed"

def can_land_units_enter(moving_nation, target_province, nation_data):
    """Centralized rules for land movement."""
    if target_province.get("terrain") in c.WATER_TERRAINS:
        return False

    target_owner = target_province.get("owner", "Unclaimed")

    # Whitelist neutral water countries so they act as open international waters
    allowed_owners = ["Unclaimed", "None", moving_nation, "Ocean", "Lakes"]

    if target_owner not in allowed_owners:
        is_enemy = are_at_war(moving_nation, target_owner, nation_data)
        is_faction = are_in_same_faction(moving_nation, target_owner, nation_data)
        is_ally = target_owner in nation_data.get(moving_nation, {}).get("allied_with", [])
        is_family = target_owner in get_imperial_family(moving_nation, nation_data)
        
        if not (is_enemy or is_faction or is_ally or is_family):
            return False

    return True

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
        
    return unlocks

def get_highest_infantry(nation_data_block, tech_tree, unit_library, allow_fuel_units=True):
    """Finds the highest level infantry unit the nation has researched, prioritizing mechanized/motorized upgrades."""
    res_levels = nation_data_block.get("research", {})
    
    if allow_fuel_units:
        mech_lvl = res_levels.get("mechanized_infantry", 0)
        if mech_lvl > 0:
            mech_years = tech_tree.get("mechanized_infantry", {}).get("years", [c.START_YEAR])
            target_index = max(0, min(mech_lvl - 1, len(mech_years) - 1))
            year_val = mech_years[target_index]
            u_name = f"Mechanized Infantry Type {year_val}"
            if u_name in unit_library: return u_name

        mot_lvl = res_levels.get("motorized_infantry", 0)
        if mot_lvl > 0:
            mot_years = tech_tree.get("motorized_infantry", {}).get("years", [c.START_YEAR])
            target_index = max(0, min(mot_lvl - 1, len(mot_years) - 1))
            year_val = mot_years[target_index]
            u_name = f"Motorized Infantry Type {year_val}"
            if u_name in unit_library: return u_name

    # Fallback to standard (fuel-free) infantry
    res_lvl = res_levels.get("infantry_type", 1)
    inf_years = tech_tree.get("infantry_type", {}).get("years", [c.START_YEAR])
    
    target_index = max(0, min(res_lvl - 1, len(inf_years) - 1))
    year_val = inf_years[target_index]
    u_name = f"Infantry Type {year_val}"
    
    if u_name in unit_library:
        return u_name
    return f"Infantry Type {c.START_YEAR}"

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

def get_best_offensive_unit(player_research, unit_library):
    """Finds the highest preference offensive unit the nation has unlocked."""
    return get_best_preferred_unit(player_research, unit_library, c.AI_OFFENSIVE_UNIT_PREFERENCE)

def get_best_naval_unit(player_research, unit_library):
    """Finds the highest preference naval unit the nation has unlocked."""
    return get_best_preferred_unit(player_research, unit_library, c.AI_NAVAL_UNIT_PREFERENCE)

def check_tech_requirements(res_levels, reqs, target_lvl=1):
    """Centralized tech requirement checker."""
    if not reqs: return True
    
    def get_req_val(v):
        if isinstance(v, str) and v.startswith("MATCH_LEVEL"):
            val = target_lvl
            if "+" in v: val += int(v.split("+")[1])
            elif "-" in v: val -= int(v.split("-")[1])
            return val
        return v
        
    if "OR" in reqs:
        return any(res_levels.get(k, 0) >= get_req_val(v) for sub in reqs["OR"] for k, v in sub.items())
    return all(res_levels.get(k, 0) >= get_req_val(v) for k, v in reqs.items())

def is_training_troops(province):
    """Returns True if the province has any troops in its deployment queue."""
    return any("unit_type" in q for q in province.get("unit_queue", []))

def is_constructing_building(province):
    """Returns True if the province has any buildings in its deployment queue."""
    return any(q.get("order_type") == "BUILDING" for q in province.get("building_queue", []))

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

def get_building_cost(b_name, nation, map_data, bldg_lib):
    """Dynamically scales the building cost, bypassing the JSON for Basic Factories."""
    stats = bldg_lib.get(b_name, {}).copy()
    if b_name == "Basic Factory":
        count = get_factory_count(nation, map_data)
        x = c.BASIC_FACTORY_BASE_COST_X + (c.BASIC_FACTORY_COST_MULTIPLIER * count)
        stats["cost_materials"] = x * 2
        stats["cost_manpower"] = x
        stats["cost_fuel"] = 0
        stats["time"] = c.BASIC_FACTORY_TURNS
    return stats

def get_nation_manpower(nation, nation_data):
    return nation_data.get(nation, {}).get("manpower", 0)

def get_nation_materials(nation, nation_data):
    return nation_data.get(nation, {}).get("materials", 0)

def get_nation_fuel(nation, nation_data):
    return nation_data.get(nation, {}).get("fuel", 0)

def refund_resources(nation_data_block, costs_dict):
    """Adds refunded costs back to a nation's resource pools safely."""
    nation_data_block["materials"] = nation_data_block.get("materials", 0) + costs_dict.get("cost_materials", 0)
    nation_data_block["manpower"] = nation_data_block.get("manpower", 0) + costs_dict.get("cost_manpower", 0)
    nation_data_block["fuel"] = nation_data_block.get("fuel", 0) + costs_dict.get("cost_fuel", 0)

def deduct_resources(nation_data_block, costs_dict):
    """Subtracts costs from a nation's resource pools, preventing negative values."""
    nation_data_block["materials"] = max(0, nation_data_block.get("materials", 0) - costs_dict.get("cost_materials", 0))
    nation_data_block["manpower"] = max(0, nation_data_block.get("manpower", 0) - costs_dict.get("cost_manpower", 0))
    nation_data_block["fuel"] = max(0, nation_data_block.get("fuel", 0) - costs_dict.get("cost_fuel", 0))

def can_afford(nation_data_block, costs_dict):
    """Returns True if the nation has enough resources to cover the costs."""
    return (nation_data_block.get("materials", 0) >= costs_dict.get("cost_materials", 0) and
            nation_data_block.get("manpower", 0) >= costs_dict.get("cost_manpower", 0) and
            nation_data_block.get("fuel", 0) >= costs_dict.get("cost_fuel", 0))

def calculate_all_economies(map_data, nation_data):
    """Standardized economy calculator. Single source of truth for UI and Turn Processor."""
    unit_lib = get_unit_library()
    bldg_lib = get_building_library()

    # Initialize data structure for all active nations
    econ_data = {}
    for name, n_data in list(nation_data.items()):
        # Fetch Bergius bonus
        bergius_bonus = 0
        research_data = n_data.get("research", {})
        if research_data.get("bergius_process", 0) > 0:
            bergius_bonus = c.BERGIUS_FUEL_BONUS

        # Fetch General Recruitment bonus
        gen_rec_lvl = research_data.get("general_recruitment", 0)
        manpower_bonus = gen_rec_lvl * c.GENERAL_RECRUITMENT_BONUS

        econ_data[name] = {
            "dynamic_yields": {
                "manpower": c.BASE_YIELDS["manpower"] + manpower_bonus,
                "materials": c.BASE_YIELDS["materials"],
                "fuel": c.BASE_YIELDS["fuel"] 
            },
            "breakdown": {
                "manpower": {"base": c.COUNTRY_BASE_YIELDS["manpower"], "core": 0, "non_core": 0, "buildings": 0, "resources": 0, "conversion": 0, "conscription": 0, "siphon": 0, "siphon_income": 0},
                "materials": {"base": c.COUNTRY_BASE_YIELDS["materials"], "core": 0, "non_core": 0, "buildings": 0, "resources": 0, "conversion": 0, "conscription": 0, "siphon": 0, "siphon_income": 0},
                "fuel": {"base": c.COUNTRY_BASE_YIELDS["fuel"] + bergius_bonus, "core": 0, "non_core": 0, "buildings": 0, "resources": 0, "conversion": 0, "conscription": 0, "siphon": 0, "siphon_income": 0}
            },
            "upkeep": {"manpower": 0, "materials": 0, "fuel": 0},
            "total_inc": {"manpower": 0, "materials": 0, "fuel": 0}
        }

    # Single efficient pass over the map
    for province in map_data.values():
        owner = province.get("owner")
        
        # --- INCOME LOGIC ---
        if owner and owner in econ_data and owner not in c.UNPLAYABLE_NATIONS:
            is_core = owner in province.get("cores", [])

            mat_mult = 1.0 if is_core else c.NON_CORE_MULTIPLIERS["materials"]
            fuel_mult = 1.0 if is_core else c.NON_CORE_MULTIPLIERS["fuel"]
            man_mult = 1.0 if is_core else c.NON_CORE_MULTIPLIERS["manpower"]

            cat = "core" if is_core else "non_core"
            bd = econ_data[owner]["breakdown"]
            dyn_yields = econ_data[owner]["dynamic_yields"]

            # Use the dynamic yields per nation instead of the global constants
            bd["manpower"][cat] += man_mult * dyn_yields["manpower"]
            bd["materials"][cat] += mat_mult * dyn_yields["materials"]
            bd["fuel"][cat] += fuel_mult * dyn_yields["fuel"]

            # Natural Resources
            res = province.get("resources", {})
            if isinstance(res, dict):
                bd["materials"]["resources"] += int(res.get("Iron", 0)) * mat_mult
                bd["fuel"]["resources"] += (int(res.get("Coal", 0)) + int(res.get("Oil", 0))) * fuel_mult

            # Buildings
            for b_name in province.get("buildings", []):
                stats = bldg_lib.get(b_name, {})
                bd["manpower"]["buildings"] += stats.get("prod_manpower", 0) 
                bd["materials"]["buildings"] += stats.get("prod_materials", 0) 
                bd["fuel"]["buildings"] += stats.get("prod_fuel", 0) 

            # Basic Factory transitional construction yields
            for q in province.get("building_queue", []):
                if q.get("item_name") == "Basic Factory":
                    rem = q.get("turns_remaining", c.BASIC_FACTORY_TURNS)
                    
                    if rem >= 17: yield_mat = 80
                    elif rem >= 13: yield_mat = 160
                    elif rem >= 9: yield_mat = 240
                    elif rem >= 5: yield_mat = 320
                    else: yield_mat = 400
                    
                    if owner in econ_data:
                        econ_data[owner]["breakdown"]["materials"]["buildings"] += yield_mat

        # --- UPKEEP LOGIC ---
        for unit in province.get("units", []):
            u_owner = unit.get("owner")
            if u_owner in econ_data:
                # FETCH ORIGINAL TYPE SO WE KEEP CHARGING UPKEEP DURING TRANSIT
                u_type = unit.get("original_type", unit.get("type"))
                stats = unit_lib.get(u_type, {})
                econ_data[u_owner]["upkeep"]["manpower"] += stats.get("cost_manpower", 0) * c.UPKEEP_MODIFIERS["manpower"]
                econ_data[u_owner]["upkeep"]["materials"] += stats.get("cost_materials", 0) * c.UPKEEP_MODIFIERS["materials"]
                econ_data[u_owner]["upkeep"]["fuel"] += stats.get("cost_fuel", 0) * c.UPKEEP_MODIFIERS["fuel"]

    # Finalize totals and calculate conversions
    for name, data in econ_data.items():
        n_data = nation_data.get(name, {})
        conv_rate = min(n_data.get("mat_to_fuel_slider", 0.0), get_max_fuel_conversion(n_data))
        conscript_rate = n_data.get("conscription_slider", 1.0)
        
        # Calculate raw material income BEFORE conscription so fuel strictly ignores it
        raw_inc_mat = sum(data["breakdown"]["materials"].values())
        raw_inc_man = sum(data["breakdown"]["manpower"].values())

        # Conscription is based on Gross Manpower Income (1.0 = keep all, 0.0 = convert all)
        man_ratio = c.CONSCRIPTION_RATIO
        man_divisor = max(1, int(1 / man_ratio) if man_ratio > 0 else 1)
        
        if conscript_rate < 1.0 and raw_inc_man >= man_divisor:
            convert_man_amount = int(raw_inc_man * (1.0 - conscript_rate))
            convert_man_amount = (convert_man_amount // man_divisor) * man_divisor
            mat_gained = int(convert_man_amount * man_ratio)
            
            data["breakdown"]["manpower"]["conscription"] = -convert_man_amount
            data["breakdown"]["materials"]["conscription"] = mat_gained
            
        # Conversion is based on Gross Income, not Net Income (Expenses are ignored)
        fuel_ratio = c.FUEL_CONVERSION_RATIO
        fuel_divisor = max(1, int(1 / fuel_ratio) if fuel_ratio > 0 else 1)
        
        if conv_rate > 0 and raw_inc_mat >= fuel_divisor:
            convert_amount = int(raw_inc_mat * conv_rate)
            convert_amount = (convert_amount // fuel_divisor) * fuel_divisor
            fuel_gained = int(convert_amount * fuel_ratio)
            
            # Treat materials consumed as an expense, and fuel generated as an income
            data["breakdown"]["materials"]["conversion"] = -convert_amount
            data["breakdown"]["fuel"]["conversion"] = fuel_gained

        data["total_inc"]["manpower"] = sum(data["breakdown"]["manpower"].values())
        data["total_inc"]["materials"] = sum(data["breakdown"]["materials"].values())
        data["total_inc"]["fuel"] = sum(data["breakdown"]["fuel"].values())

    # --- PUPPET SIPHONING LOGIC ---
    for name, data in econ_data.items():
        n_data = nation_data.get(name, {})
        master = n_data.get("master", "")
        
        if master and master in econ_data and n_data.get("puppet_type") == c.PUPPET_TYPE_INTEGRATED:
            siphon_rates = n_data.setdefault("siphon_rates", {"manpower": 0.0, "materials": 0.0, "fuel": 0.0})
            
            for res in ["manpower", "materials", "fuel"]:
                rate = min(c.MAX_PUPPET_SIPHON, siphon_rates.get(res, 0.0))
                siphon_amt = int(max(0, data["total_inc"][res]) * rate)
                
                # Apply transfers
                data["total_inc"][res] -= siphon_amt
                econ_data[master]["total_inc"][res] += siphon_amt
                
                # Tag it in breakdowns for the UI
                data["breakdown"][res]["siphon"] = -siphon_amt
                econ_data[master]["breakdown"][res]["siphon_income"] = econ_data[master]["breakdown"][res].get("siphon_income", 0) + siphon_amt

    return econ_data

def get_economy_projections(target_nation, map_data, nation_data):
    """Pulls a specific nation's UI data from the unified calculator."""
    all_econ = calculate_all_economies(map_data, nation_data)
    p_econ = all_econ.get(target_nation, {})
    
    if not p_econ:
        return (
            {"manpower": 0, "materials": 0, "fuel": 0},
            {"manpower": 0, "materials": 0, "fuel": 0},
            {"manpower": {}, "materials": {}, "fuel": {}}
        )
        
    return p_econ.get("total_inc"), p_econ.get("upkeep"), p_econ.get("breakdown")

def get_minimum_tank_count(material_income):
    """Calculates the baseline number of tanks an AI should force itself to field."""
    count = math.ceil((material_income - c.AI_TANK_MIN_BASE_THRESHOLD) / c.AI_TANK_MIN_DIVISOR)
    return max(0, count)

# ==========================================
# MAP & ENTITY QUERIES
# ==========================================

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
    return nation_data.get(nation, {}).get("at_war_with", [])

def get_allies(nation, nation_data):
    return nation_data.get(nation, {}).get("allied_with", [])

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
    pending = nation_data.get(sender, {}).get("pending_diplomacy", {}).get(target, {})
    if isinstance(pending, dict) and pending.get("turns", 0) == 0:
        if "message" in pending:
            return pending["message"]
        # Legacy fallback
        action = pending.get("action", "")
        if isinstance(action, str) and action.startswith("MSG:"):
            return action[4:]
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

def get_unread_message_count(nation, nation_data):
    """Returns the total number of unread messages and unanswered requests for a nation."""
    # If the user is the spectator, count unread messages across ALL playable nations
    if nation == "Spectator":
        total_unread = 0
        for n_name, n_data in list(nation_data.items()):
            if n_data.get("is_playable", False):
                inbox = n_data.get("inbox", [])
                total_unread += sum(1 for msg in inbox if not msg.get("spectator_read", False))
                
                my_pending = n_data.get("pending_diplomacy", {})
                for other_nation, other_data in list(nation_data.items()):
                    if other_nation == n_name: continue
                    req = other_data.get("pending_diplomacy", {}).get(n_name)
                    if isinstance(req, dict) and req.get("turns", 0) > 0 and req.get("action") in c.BILATERAL_ACTIONS:
                        my_response = my_pending.get(other_nation)
                        if not (isinstance(my_response, dict) and (my_response.get("action", "").startswith("ACCEPT_") or my_response.get("action", "").startswith("REJECT_"))):
                            total_unread += 1
        return total_unread
        
    # Standard logic for normal players
    inbox = nation_data.get(nation, {}).get("inbox", [])
    # Ignore messages where the sender is the nation itself
    unread_count = sum(1 for msg in inbox if not msg.get("read", False) and msg.get("sender") != nation)
    
    my_pending = nation_data.get(nation, {}).get("pending_diplomacy", {})
    for other_nation, other_data in list(nation_data.items()):
        if other_nation == nation: continue
        req = other_data.get("pending_diplomacy", {}).get(nation)
        if isinstance(req, dict) and req.get("turns", 0) > 0 and req.get("action") in c.BILATERAL_ACTIONS:
            my_response = my_pending.get(other_nation)
            if not (isinstance(my_response, dict) and (my_response.get("action", "").startswith("ACCEPT_") or my_response.get("action", "").startswith("REJECT_"))):
                unread_count += 1
                
    return unread_count

def has_free_research_slots(nation, nation_data):
    """Returns True if the nation is researching fewer than 2 techs."""
    # Prevent the research notification from popping up for the Spectator or Ocean
    if nation in c.UNPLAYABLE_NATIONS:
        return False
        
    queue = nation_data.get(nation, {}).get("research_queue", [])
    return len(queue) < 2

def has_active_truce(nation_a, nation_b, nation_data):
    """Returns True if there is an active non-aggression pact/truce between the two nations."""
    if nation_a not in nation_data: return False
    return nation_data[nation_a].get("truces", {}).get(nation_b, 0) > 0

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
        score += 50
    elif master_a == nation_b:
        score += 20
                
    # Apply all decaying temporary modifiers
    temp_mods = nation_data.get(nation_a, {}).get("temp_modifiers", {}).get(nation_b, {})
    for mod_val in temp_mods.values():
        score += mod_val
        
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

def add_temporary_modifier(nation_a, nation_b, mod_name, value, nation_data):
    """Adds or updates a temporary relation modifier. General opinions stack."""
    if nation_a not in nation_data: return
    mods = nation_data.setdefault(nation_a, {}).setdefault("temp_modifiers", {}).setdefault(nation_b, {})
    
    if mod_name == "general":
        mods["general"] = mods.get("general", 0) + value
    else:
        mods[mod_name] = value

def get_relation_color(score):
    """Returns a dynamic color mapped to the relation score (-200 to 200)."""
    score = max(-200, min(200, score))
    
    def lerp_color(c1, c2, t):
        return (int(c1[0] + (c2[0] - c1[0]) * t),
                int(c1[1] + (c2[1] - c1[1]) * t),
                int(c1[2] + (c2[2] - c1[2]) * t))
                
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
    return owner != player_country and owner in nation_data and nation_data[owner].get("is_playable", False)

def get_base_unit_name(unit_name):
    """Strips years and roman numerals to return the base unit class (e.g. 'Infantry Type 1850' -> 'Infantry')."""
    base = re.sub(r'\s+\d{4}$', '', unit_name)
    return re.sub(r'\s+[IVXLCDM]+$', '', base).strip()

def roman_to_int(s):
    """Converts a roman numeral string to an integer."""
    if not s: return 0
    rom_val = {'I': 1, 'V': 5, 'X': 10}
    res, i = 0, 0
    while i < len(s):
        s1 = rom_val.get(s[i], 0)
        if i + 1 < len(s):
            s2 = rom_val.get(s[i+1], 0)
            if s1 >= s2: res += s1; i += 1
            else: res += s2 - s1; i += 2
        else: res += s1; i += 1
    return res

def is_naval_unit(unit_type):
    """Checks if a unit is a naval unit based on its type name or unit library stats."""
    if unit_type.startswith("Convoy"):
        return True
    if unit_type.startswith("Truck"):
        return False
    stats = get_unit_library().get(unit_type, {})
    return stats.get("naval_unit", False)

# i don't know if this would really count as a query...
def revert_transport(unit):
    """Reverts a transport (like a Convoy) back to its original unit type."""
    if "original_type" not in unit:
        return

    pct = unit.get("health", 1) / max(1, unit.get("max_health", 1))

    unit["type"] = unit.get("original_type", "Infantry")
    unit["speed"] = unit.get("original_speed", 1)
    unit["max_health"] = unit.get("original_max_health", c.DEFAULT_UNIT_HP)
    unit["attack"] = unit.get("original_attack", c.DEFAULT_UNIT_ATK)

    unit["health"] = unit["max_health"] * pct
    unit["naval_unit"] = is_naval_unit(unit["type"])

    for key in ["original_type", "original_speed", "original_max_health", "original_attack"]:
        if key in unit: del unit[key]

def get_units_in_province(nation, province):
    """Returns a list of units the given nation has in the target province."""
    return [u for u in province.get("units", []) if u.get("owner") == nation]

def has_units_in_province(nation, province):
    """Returns True if the given nation has any units in the target province."""
    return any(u.get("owner") == nation for u in province.get("units", []))

def get_active_ai_nations(map_screen):
    """Returns a list of all playable, active AI nations (excluding the human player)."""
    ai_nations = []
    # Account for potential hotseat active_players lists or standard player_country setups
    human_players = map_screen.active_players if map_screen.active_players else [map_screen.player_country]
    
    # Cross-reference with nations that actually own territory
    living_nations = get_living_nations(map_screen.map_data)
    
    for name, data in map_screen.nation_data.items():
        if name in living_nations and name not in human_players and name not in c.UNPLAYABLE_NATIONS and data.get("is_playable"):
            ai_nations.append(name)
            
    # Randomize the order the AI processes countries
    import random
    random.shuffle(ai_nations)
    
    return ai_nations

def is_unit_obsolete(group_name, player_research):
    """Checks if a unit group is obsolete based on researched techs."""
    obsoleting_techs = c.OBSOLESCENCE_RULES.get(group_name, [])
    return any(player_research.get(tech, 0) >= 1 for tech in obsoleting_techs)

def get_best_unit_by_defense_then_attack_then_speed(units):
    """Finds the unit with the highest defense stat, tiebreaking with attack, then speed."""
    if not units:
        return None
    # Tuple sorting: (Primary Sort, Secondary Sort, Tertiary Sort)
    return max(units, key=lambda u: (
        u.get("defense", c.DEFAULT_UNIT_DEF), 
        u.get("attack", c.DEFAULT_UNIT_ATK),
        u.get("speed", c.DEFAULT_UNIT_SPD)
    ))
def get_best_unit_by_attack_then_defense(units):
    """Finds the unit with the highest attack stat, tiebreaking with defense."""
    if not units:
        return None
    return max(units, key=lambda u: (u.get("attack", 0), u.get("defense", 0)))

def get_best_unit_by_attack_then_speed(units):
    """Finds the unit with the highest attack stat, tiebreaking with speed."""
    if not units:
        return None
    # Tuple sorting: (Primary Sort: Attack, Secondary Sort: Speed)
    return max(units, key=lambda u: (u.get("attack", 0), u.get("speed", 0)))

# ==========================================
# PREDICTION QUERIES (UI & RENDERING)
# ==========================================

def get_combat_predictions(map_data, nation_data, id_to_province):
    """Generates predictions for meeting engagements and province clashes."""
    predictions = []
    incoming = {} 
    
    # 1. Map all incoming movements
    for prov in map_data.values():
        for u in prov.get("units", []):
            order = u.get("order")
            if order and order.get("type") == "MOVE" and order.get("path"):
                dest_id = order["path"][0]
                incoming.setdefault(dest_id, []).append((u, prov["id"]))
                
    # 2. Find Meeting Engagements (Crossing Paths)
    processed_pairs = set()
    for dest_id, attackers in incoming.items():
        for u_a, origin_a_id in attackers:
            crossers = [u_b for u_b, orig_b in incoming.get(origin_a_id, []) 
                        if orig_b == dest_id and are_at_war(u_a["owner"], u_b["owner"], nation_data)]
            if crossers:
                pair = tuple(sorted([origin_a_id, dest_id]))
                if pair not in processed_pairs:
                    processed_pairs.add(pair)
                    side1 = [u for u, o in incoming.get(dest_id, []) if o == origin_a_id]
                    side2 = [u for u, o in incoming.get(origin_a_id, []) if o == dest_id]
                    predictions.append({
                        "type": "meeting",
                        "loc": pair,
                        "side1": side1,
                        "side2": side2
                    })
                    
    # 3. Find Province Clashes (Static Defenders vs Incoming Attackers)
    for prov in map_data.values():
        prov_id = prov["id"]
        defenders = prov.get("units", [])
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
    global _dynamic_image_cache
    _dynamic_image_cache.clear()

def get_default_b64(is_portrait=False):
    global _default_flag_b64, _default_port_b64
    if is_portrait:
        if _default_port_b64 is None:
            try:
                img = pygame.image.load(c.DEFAULT_PORTRAIT_PATH).convert_alpha()
                img = pygame.transform.scale(img, c.PORTRAIT_SIZE)
                _default_port_b64 = encode_surf_to_b64(img)
            except:
                _default_port_b64 = "ERROR"
        return _default_port_b64
    else:
        if _default_flag_b64 is None:
            try:
                img = pygame.image.load(c.DEFAULT_FLAG_PATH).convert_alpha()
                img = pygame.transform.scale(img, c.FLAG_SIZE)
                _default_flag_b64 = encode_surf_to_b64(img)
            except:
                _default_flag_b64 = "ERROR"
        return _default_flag_b64

def scrub_default_images(nation_data_block):
    """Replaces large Base64 strings with 'DEFAULT' if they match the default images or local files."""
    def_flag = get_default_b64(is_portrait=False)
    def_port = get_default_b64(is_portrait=True)
    
    for country, data in nation_data_block.items():
        if data.get("flag_data") == def_flag:
            data["flag_data"] = "DEFAULT"
        if data.get("portrait_data") == def_port:
            data["portrait_data"] = "DEFAULT"
            
        # Check against local country-specific files to scrub custom imports that are already on disk
        f_path = os.path.join(c.FLAGS_DIR, f"{country}.png")
        if data.get("flag_data") != "DEFAULT" and os.path.exists(f_path):
            try:
                img = pygame.image.load(f_path).convert_alpha()
                img = pygame.transform.scale(img, c.FLAG_SIZE)
                if data["flag_data"] == encode_surf_to_b64(img):
                    data["flag_data"] = "DEFAULT"
            except: pass
            
        p_path = os.path.join(c.PORTRAITS_DIR, f"{country}.png")
        if data.get("portrait_data") != "DEFAULT" and os.path.exists(p_path):
            try:
                img = pygame.image.load(p_path).convert_alpha()
                img = pygame.transform.scale(img, c.PORTRAIT_SIZE)
                if data["portrait_data"] == encode_surf_to_b64(img):
                    data["portrait_data"] = "DEFAULT"
            except: pass

def encode_surf_to_b64(surf, fmt="RGBA"):
    """Encodes a pygame surface to a Base64 string."""
    img_str = pygame.image.tostring(surf, fmt)
    return base64.b64encode(img_str).decode('utf-8')

def decode_b64_to_surf(b64_str, size, is_portrait=False, country_name=None):
    """Decodes a Base64 string back into a pygame surface."""
    global _dynamic_image_cache
    
    cache_key = (b64_str, size, is_portrait, country_name)
    if cache_key in _dynamic_image_cache:
        return _dynamic_image_cache[cache_key] # Optimized: Removed .copy()

    if not b64_str or b64_str == "DEFAULT":
        # --- Check for country-specific local file first ---
        if country_name:
            base_dir = c.PORTRAITS_DIR if is_portrait else c.FLAGS_DIR
            file_path = os.path.join(base_dir, f"{country_name}.png")
            if os.path.exists(file_path):
                try:
                    img = pygame.image.load(file_path).convert_alpha()
                    scaled = pygame.transform.scale(img, size)
                    _dynamic_image_cache[cache_key] = scaled
                    return scaled # Optimized: Removed .copy()
                except:
                    pass # Fallback to absolute default
        
        # --- Fallback to absolute default ---
        path = c.DEFAULT_PORTRAIT_PATH if is_portrait else c.DEFAULT_FLAG_PATH
        try:
            img = pygame.image.load(path).convert_alpha()
            scaled = pygame.transform.scale(img, size)
            _dynamic_image_cache[cache_key] = scaled
            return scaled # Optimized: Removed .copy()
        except:
            surf = pygame.Surface(size, pygame.SRCALPHA)
            surf.fill((200, 200, 200, 255))
            _dynamic_image_cache[cache_key] = surf
            return surf # Optimized: Removed .copy()

    try:
        img_bytes = base64.b64decode(b64_str)
        if len(img_bytes) == size[0] * size[1] * 4:
            scaled = pygame.image.fromstring(img_bytes, size, "RGBA")
        else:
            scaled = pygame.image.fromstring(img_bytes, size, "RGB").convert_alpha()
        _dynamic_image_cache[cache_key] = scaled
        return scaled # Optimized: Removed .copy()
    except:
        surf = pygame.Surface(size, pygame.SRCALPHA)
        surf.fill((255, 255, 255, 255))
        _dynamic_image_cache[cache_key] = surf
        return surf # Optimized: Removed .copy()

# ==========================================
# DIPLOMATIC SPAM/REACHABILITY QUERIES
# ==========================================

def is_nation_reachable(nation_a, target_nation, map_data, id_to_province, nation_data):
    """Determines if a nation can physically reach another via land borders (including faction borders) or sea."""
    nation_a_faction = nation_data.get(nation_a, {}).get("faction", "")
    friendly_nations = {nation_a}
    if nation_a_faction:
        friendly_nations.update(get_faction_members(nation_a_faction, nation_data))
        
    target_faction = nation_data.get(target_nation, {}).get("faction", "")
    enemy_nations = {target_nation}
    if target_faction:
        enemy_nations.update(get_faction_members(target_faction, nation_data))
        
    friendly_has_coast = False
    target_has_coast = False
    
    for prov in map_data.values():
        owner = prov.get("owner")
        
        # Check if any friendly nation touches any enemy nation
        if owner in friendly_nations:
            if prov.get("is_coastal", False):
                friendly_has_coast = True
                
            for n_id in prov.get("neighbors", []):
                n_prov = id_to_province.get(n_id)
                if n_prov and n_prov.get("owner") in enemy_nations:
                    return True 
                    
        # Keep an eye out for enemy coasts globally too
        if owner in enemy_nations and prov.get("is_coastal", False):
            target_has_coast = True
            
    if friendly_has_coast and target_has_coast:
        return True 
        
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

def calculate_justification_time(nation, target_prov_ids, id_to_province):
    """Calculates the time needed to justify a wargoal. 1 turn + non-cores."""
    time = 1
    for pid in target_prov_ids:
        prov = id_to_province.get(pid)
        if prov and nation not in prov.get("cores", []):
            time += 1
    return time

def has_wargoal(nation, target_nation, nation_data, map_data=None):
    """Returns True if the nation has active claims on the target, or a justified wargoal."""
    if map_data:
        claims = nation_data.get(nation, {}).get("claims", [])
        for prov in map_data.values():
            # If target owns the tile, and the attacker either claimed it or has a core on it
            if prov.get("owner") == target_nation and (prov["id"] in claims or nation in prov.get("cores", [])):
                return True
    return target_nation in nation_data.get(nation, {}).get("wargoals", {})

def ai_thinks_it_can_win(ai_nation, target_nation, map_data, nation_data, id_to_province=None):
    """Calculates if the AI believes it is strong enough to defeat the target (CTW)."""
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
    
    # AI needs local border superiority AND overall global viability
    return my_border_str >= (target_border_str * c.AI_WAR_STRENGTH_THRESHOLD) and my_total_power >= (target_total_power * c.AI_GLOBAL_STRENGTH_THRESHOLD)

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
    """Evaluates if the AI will accept the proposed peace deal."""
    # The AI declines peace deals where the other side demands claims.
    if peace_type.startswith(c.PEACE_DEMAND_CLAIMS):
        return False
        
    if peace_type.startswith(c.PEACE_WHITE_PEACE):
        if map_data:
            # If CTW is True, the AI thinks it can win, so it refuses the ceasefire.
            if ai_thinks_it_can_win(target_nation, proposer_nation, map_data, nation_data):
                return False
            # If CTW is False, the AI thinks it could lose, so it accepts the ceasefire.
            else:
                return True
        else:
            return True

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
import threading

def refresh_map_directories(screen, dirs_to_check, success_message="Data refreshed successfully!"):
    """Headlessly instantiates maps on a background thread to prevent UI freezing."""
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
        import tkinter as tk
        from tkinter import messagebox
        root = get_transient_tk_root()
        messagebox.showinfo("Data Refresh", "No maps found to refresh.", parent=root)
        destroy_tk_root(root)
        return

    # Setup screen state for UI
    screen.is_refreshing = True
    screen.refresh_total = total_maps
    screen.refresh_completed = 0
    screen.refresh_status = "Initializing..."

    def _refresh_thread():
        from screens.map import Map
        maps_processed = 0

        for scenario_dir, name, scenario_path, map_json_path in valid_scenarios:
            try:
                screen.refresh_status = f"Syncing: {name}..."
                # 1. Instantiate Map with standard singleplayer configurations to pull existing meta/map data into memory
                temp_map_context = Map(load_path=scenario_path, is_scenario=True)

                # 2. Execute the official resync pipeline
                temp_map_context.refresh_nation_data()
                print(f"refreshed {name}")

                # Set all playable country resources to 0 before compounding income calculations
                for nation_name, stats in temp_map_context.nation_data.items():
                    if nation_name != "GLOBAL_EVENTS" and nation_name not in c.UNPLAYABLE_NATIONS:
                        stats["manpower"] = 0
                        stats["materials"] = 0
                        stats["fuel"] = 0

                # 3. Clean country flags/portraits inside memory before serializing
                scrub_default_images(temp_map_context.nation_data)

                # 4. Reconstruct the exact structural configuration payload
                save_dict = {
                    "date": {
                        "day": temp_map_context.time_manager.day,
                        "month": temp_map_context.time_manager.month_index,
                        "year": temp_map_context.time_manager.year,
                        "total_turns": temp_map_context.time_manager.total_turns
                    },
                    "loop_map": temp_map_context.loop_map,
                    "player_country": temp_map_context.player_country,
                    "active_players": temp_map_context.active_players,
                    "current_player_index": temp_map_context.current_player_index,
                    "scenario_settings": temp_map_context.scenario_settings,
                    "default_research": temp_map_context.default_research,
                    "nation_data": temp_map_context.nation_data,
                    "provinces": {}
                }

                for data in temp_map_context.map_data.values():
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

                # 5. Perform the manual write operations in-place
                with open(os.path.join(scenario_path, "meta.json"), "w") as f:
                    json.dump(save_dict, f, indent=c.SAVE_INDENT)

                with open(map_json_path, "w") as f:
                    json.dump(temp_map_context.raw_json_data, f, indent=c.SAVE_INDENT)

                if hasattr(temp_map_context, 'history'):
                    with open(os.path.join(scenario_path, "history.json"), "w") as f:
                        json.dump(temp_map_context.history, f, indent=c.HISTORY_INDENT)

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
    threading.Thread(target=_refresh_thread, daemon=True).start()

# ==========================================
# TKINTER DIALOG HELPERS
# ==========================================

def get_transient_tk_root():
    """Creates a hidden, top-most Tkinter root for native dialogs (file picking, color picking)."""
    import tkinter as tk
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    return root

def destroy_tk_root(root):
    """Destroys the Tk root and pumps Pygame events to clear phantom inputs."""
    import pygame
    root.destroy()
    pygame.event.pump()

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

def get_ordered_unit_groups(unit_library):
    """Categorizes and sorts units into Infantry, Tanks, and Navy groups."""
    infantry_groups, tank_groups, navy_groups = [], [], []
    for name, stats in unit_library.items():
        base = get_base_unit_name(name)
        if stats.get("naval_unit", False):
            if base not in navy_groups: navy_groups.append(base)
        elif "Tank" in base or "Armored Car" in base:
            if base not in tank_groups: tank_groups.append(base)
        else:
            if base not in infantry_groups: infantry_groups.append(base)
    return infantry_groups, tank_groups, navy_groups

def get_projected_owner(prov, peace_type, proposer, target, nation_data):
    """Simulates the execution of a peace treaty to find who gets what territory."""
    curr = prov.get("owner")
    proj = curr

    def was_original_owner(prov, nation):
        fac = nation_data.get(nation, {}).get("faction", "")
        if fac and "FACTION_WAR_MAPS" in nation_data and fac in nation_data["FACTION_WAR_MAPS"]:
            pre_war = nation_data["FACTION_WAR_MAPS"][fac]
            if str(prov["id"]) in pre_war:
                return pre_war[str(prov["id"])] == nation
        return nation in prov.get("cores", [])

    # Extract frozen_ids safely using regex to support pre-formatted strings
    frozen_ids = []
    match = re.search(r'\(Territories (?:demanded|surrendered): ([\d, ]+)', peace_type)
    if match:
        frozen_ids = [int(x.strip()) for x in match.group(1).split(",") if x.strip().isdigit()]

    if peace_type.startswith(c.PEACE_WHITE_PEACE):
        pass
    elif peace_type.startswith(c.PEACE_DEMAND_CLAIMS):
        claims = nation_data.get(proposer, {}).get("claims", [])
        if (prov["id"] in frozen_ids and curr == target) or (curr == target and (prov["id"] in claims or was_original_owner(prov, proposer))):
            proj = proposer
    elif peace_type.startswith(c.PEACE_SURRENDER):
        claims = nation_data.get(target, {}).get("claims", [])
        if (prov["id"] in frozen_ids and curr == proposer) or (curr == proposer and (prov["id"] in claims or was_original_owner(prov, target))):
            proj = target
            
    return proj