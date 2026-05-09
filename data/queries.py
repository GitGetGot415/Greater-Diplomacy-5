import json
import os
import re
import base64
import itertools
import pygame
import data.constants as c

# ==========================================
# UNIFIED CACHE MANAGER
# ==========================================

# By mapping the path directly to the cache, we can automate loading and saving!
_JSON_CACHE = {
    "settings": {"path": c.SETTINGS_CONFIG_PATH, "data": None},
    "unit_library": {"path": c.UNIT_DATA_PATH, "data": None},
    "building_library": {"path": c.BUILDING_DATA_PATH, "data": None},
    "tech_tree": {"path": c.RESEARCH_TEMPLATE_PATH, "data": None},
    "country_data": {"path": c.COUNTRIES_DATA_PATH, "data": None},
    "active_albums": {"path": getattr(c, 'ACTIVE_ALBUMS_PATH', "data/json/active_albums.json"), "data": None}
}

def clear_json_caches():
    """Forces the game to fetch the updated files on the next read."""
    for key in _JSON_CACHE:
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
    return getattr(time_manager, 'total_turns', 0)

def get_economic_power(nation, nation_data):
    """Estimates a nation's economic power based on its resource stockpiles."""
    data = nation_data.get(nation, {})
    # CHANGED: Now uses constants instead of hardcoded 10 and 20
    manpower_val = data.get("manpower", 0) * c.ECONOMY_WEIGHT_MANPOWER
    materials_val = data.get("materials", 0) * c.ECONOMY_WEIGHT_MATERIALS
    fuel_val = data.get("fuel", 0) * c.ECONOMY_WEIGHT_FUEL
    return manpower_val + materials_val + fuel_val

def get_alliance_military_strength(nation, map_data, nation_data):
    """Calculates the combined military strength of a nation and its faction members/allies."""
    strength = get_military_strength(nation, map_data)
    
    # Add faction members
    faction = nation_data.get(nation, {}).get("faction", "")
    if faction:
        for member in get_faction_members(faction, nation_data):
            if member != nation:
                strength += get_military_strength(member, map_data)
                
    # Add direct allies if they aren't in the faction
    allies = nation_data.get(nation, {}).get("allied_with", [])
    for ally in allies:
        if not faction or nation_data.get(ally, {}).get("faction", "") != faction:
            strength += get_military_strength(ally, map_data)
            
    return strength

def get_military_strength(nation, map_data):
    """Calculates rough military strength of a nation based on unit stats."""
    strength = 0
    for prov in map_data.values():
        for u in prov.get("units", []):
            if u.get("owner") == nation:
                # CHANGED: Uses constant divisor instead of hardcoded 10
                hp_val = u.get("health", 0) / c.MILITARY_STRENGTH_HEALTH_DIVISOR
                strength += u.get("attack", 0) + u.get("defense", 0) + hp_val
    return strength

def get_nations_holding_our_cores(nation, map_data):
    """Returns a set of foreign nations that own territory where the given nation has a core."""
    targets = set()
    for prov in map_data.values():
        owner = prov.get("owner")
        if owner and owner != nation and owner not in c.UNPLAYABLE_NATIONS:
            if nation in prov.get("cores", []):
                targets.add(owner)
    return targets

def get_border_strength(nation_a, nation_b, map_data, id_to_province):
    """Calculates the military strength of both nations localized to their shared border."""
    border_provs_a = set()
    border_provs_b = set()
    
    for prov in map_data.values():
        owner = prov.get("owner")
        if owner == nation_a:
            for n_id in prov.get("neighbors", []):
                n_prov = id_to_province.get(n_id)
                if n_prov and n_prov.get("owner") == nation_b:
                    border_provs_a.add(prov["id"])
                    border_provs_b.add(n_id)
                    
    def calc_strength(prov_ids, target_nation):
        strength = 0
        for prov_id in prov_ids:
            prov = id_to_province.get(prov_id)
            if prov:
                for u in prov.get("units", []):
                    if u.get("owner") == target_nation:
                        # CHANGED: Uses constant divisor instead of hardcoded 10
                        hp_val = u.get("health", 0) / c.MILITARY_STRENGTH_HEALTH_DIVISOR
                        strength += u.get("attack", 0) + u.get("defense", 0) + hp_val
        return strength

    return calc_strength(border_provs_a, nation_a), calc_strength(border_provs_b, nation_b)

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
    if target_owner in ["None", "Unclaimed", "Ocean", "Lakes"]:
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
    return [n for n, d in nation_data.items() if d.get("faction") == faction_name]

def get_faction_leader(faction_name, nation_data):
    """Returns the leader of the specified faction."""
    if not faction_name: return None
    for n, d in nation_data.items():
        if d.get("faction") == faction_name and d.get("is_faction_leader", False):
            return n
    return None

def is_faction_leader(nation, nation_data):
    """Returns True if the nation is currently a faction leader."""
    return nation_data.get(nation, {}).get("is_faction_leader", False)

def get_faction_core_transfer_target(capturer, province, nation_data):
    """
    Determines if a captured territory should be transferred to a faction member
    who has a core on it. Returns the true owner to assign the province to.
    """
    if capturer in c.UNPLAYABLE_NATIONS:
        return capturer

    faction_name = nation_data.get(capturer, {}).get("faction", "")
    if not faction_name:
        return capturer

    faction_members = get_faction_members(faction_name, nation_data)
    tile_cores = province.get("cores", [])

    # Find how many active faction members have a core on this specific tile
    faction_cores_on_tile = [member for member in faction_members if member in tile_cores]

    # Only transfer if EXACTLY ONE faction member has a core on this territory
    if len(faction_cores_on_tile) == 1:
        return faction_cores_on_tile[0]

    # If multiple faction members have a core, or nobody does, the capturer keeps it
    return capturer

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
    
    return target_owner == moving_nation or is_faction or is_ally or target_owner == "Unclaimed"

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
        
        if not (is_enemy or is_faction or is_ally):
            return False

    return True


# ==========================================
# PROVINCE & TECH QUERIES
# ==========================================

def get_industry(province):
    """Returns the highest level of industry in the province."""
    level = 0
    for b in province.get("buildings", []):
        if "Workshop Lvl" in b:
            lvl = int(b.split()[-1])
            level = max(level, lvl)
        elif b == "Basic Factory":
            level = max(level, 6)
        elif "Factory Lvl" in b:
            lvl = int(b.split()[-1])
            level = max(level, 6 + lvl)
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
    if "Experimental Refinery" in b_name:
        return "synthetic_fuel_experiments", 1
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
        
    if tech_key == "general_recruitment":
        bonus = getattr(c, 'GENERAL_RECRUITMENT_BONUS', 5)
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
            if base_pref in ["Cavalry", "WW1 Armored Car", "WW1 Tank", "Dreadnought"]:
                return base_pref

            # For numbered tiers, find the highest roman numeral available
            romans = {1: "I", 2: "II", 3: "III", 4: "IV", 5: "V", 6: "VI", 7: "VII", 8: "VIII"}
            for check_lvl in range(res_lvl, 0, -1):
                test_name = f"{base_pref} {romans.get(check_lvl, str(check_lvl))}"
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
    return any("unit_type" in q for q in province.get("deployment_queue", []))

def is_constructing_building(province):
    """Returns True if the province has any buildings in its deployment queue."""
    return any(q.get("order_type") == "BUILDING" for q in province.get("deployment_queue", []))

# ==========================================
# ECONOMY QUERIES
# ==========================================

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
    for name, n_data in nation_data.items():
        # Fetch Bergius bonus
        bergius_bonus = 0
        research_data = n_data.get("research", {})
        if research_data.get("bergius_process", 0) > 0:
            bergius_bonus = c.BERGIUS_FUEL_BONUS

        # Fetch General Recruitment bonus
        gen_rec_lvl = research_data.get("general_recruitment", 0)
        manpower_bonus = gen_rec_lvl * getattr(c, 'GENERAL_RECRUITMENT_BONUS', 5)

        econ_data[name] = {
            "dynamic_yields": {
                "manpower": c.BASE_YIELDS["manpower"] + manpower_bonus,
                "materials": c.BASE_YIELDS["materials"],
                "fuel": c.BASE_YIELDS["fuel"] 
            },
            "breakdown": {
                "manpower": {"base": c.COUNTRY_BASE_YIELDS["manpower"], "core": 0, "non_core": 0, "buildings": 0, "resources": 0},
                "materials": {"base": c.COUNTRY_BASE_YIELDS["materials"], "core": 0, "non_core": 0, "buildings": 0, "resources": 0},
                "fuel": {"base": c.COUNTRY_BASE_YIELDS["fuel"] + bergius_bonus, "core": 0, "non_core": 0, "buildings": 0, "resources": 0}
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

    # Finalize totals
    for data in econ_data.values():
        data["total_inc"]["manpower"] = sum(data["breakdown"]["manpower"].values())
        data["total_inc"]["materials"] = sum(data["breakdown"]["materials"].values())
        data["total_inc"]["fuel"] = sum(data["breakdown"]["fuel"].values())

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


# ==========================================
# MAP & ENTITY QUERIES
# ==========================================

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

def get_unread_message_count(nation, nation_data):
    """Returns the total number of unread messages and unanswered requests for a nation."""
    # If the user is the spectator, count unread messages across ALL playable nations
    if nation == "Spectator":
        total_unread = 0
        for n_name, n_data in nation_data.items():
            if n_data.get("is_playable", False):
                inbox = n_data.get("inbox", [])
                total_unread += sum(1 for msg in inbox if not msg.get("spectator_read", False))
                
                my_pending = n_data.get("pending_diplomacy", {})
                for other_nation, other_data in nation_data.items():
                    if other_nation == n_name: continue
                    req = other_data.get("pending_diplomacy", {}).get(n_name)
                    if isinstance(req, dict) and req.get("turns", 0) > 0 and req.get("action") in c.BILATERAL_ACTIONS:
                        my_response = my_pending.get(other_nation)
                        if not (isinstance(my_response, dict) and (my_response.get("action", "").startswith("ACCEPT_") or my_response.get("action", "").startswith("REJECT_"))):
                            total_unread += 1
        return total_unread
        
    # Standard logic for normal players
    inbox = nation_data.get(nation, {}).get("inbox", [])
    unread_count = sum(1 for msg in inbox if not msg.get("read", False))
    
    my_pending = nation_data.get(nation, {}).get("pending_diplomacy", {})
    for other_nation, other_data in nation_data.items():
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
    return len(get_units_in_province(nation, province)) > 0

def get_active_ai_nations(map_screen):
    """Returns a list of all playable, active AI nations (excluding the human player)."""
    ai_nations = []
    # Account for potential hotseat active_players lists or standard player_country setups
    human_players = getattr(map_screen, 'active_players', [map_screen.player_country])
    
    # Cross-reference with nations that actually own territory
    living_nations = get_living_nations(map_screen.map_data)
    
    for name, data in map_screen.nation_data.items():
        if name in living_nations and name not in human_players and name not in c.UNPLAYABLE_NATIONS and data.get("is_playable"):
            ai_nations.append(name)
            
    return ai_nations

def is_unit_obsolete(group_name, player_research):
    """Checks if a unit group is obsolete based on researched techs."""
    obsoleting_techs = c.OBSOLESCENCE_RULES.get(group_name, [])
    return any(player_research.get(tech, 0) >= 1 for tech in obsoleting_techs)

# --- CHANGED: Renamed the misleading function and added its counterpart ---
def get_best_unit_by_defense_then_attack(units):
    """Finds the unit with the highest defense stat, tiebreaking with attack."""
    if not units:
        return None
    # Tuple sorting: (Primary Sort, Secondary Sort)
    return max(units, key=lambda u: (u.get("defense", 0), u.get("attack", 0)))

def get_best_unit_by_attack_then_defense(units):
    """Finds the unit with the highest attack stat, tiebreaking with defense."""
    if not units:
        return None
    return max(units, key=lambda u: (u.get("attack", 0), u.get("defense", 0)))


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

def encode_surf_to_b64(surf, fmt="RGBA"):
    #Encodes a pygame surface to a Base64 string.
    img_str = pygame.image.tostring(surf, fmt)
    return base64.b64encode(img_str).decode('utf-8')

def decode_b64_to_surf(b64_str, size):
    # Decodes a Base64 string back into a pygame surface.
    try:
        img_bytes = base64.b64decode(b64_str)
        # Check if the save file is using the new RGBA format or the old RGB format
        if len(img_bytes) == size[0] * size[1] * 4:
            return pygame.image.fromstring(img_bytes, size, "RGBA")
        else:
            return pygame.image.fromstring(img_bytes, size, "RGB").convert_alpha()
    except:
        surf = pygame.Surface(size, pygame.SRCALPHA)
        surf.fill((255, 255, 255, 255))
        return surf

# ==========================================
# DIPLOMATIC SPAM/REACHABILITY QUERIES
# ==========================================

def is_nation_reachable(nation_a, target_nation, map_data, id_to_province, nation_data):
    # Determines if a nation can physically reach another via land borders (including faction borders) or sea.
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
    # Checks if a specific proactive diplomatic action is on cooldown.
    cooldowns = nation_data.get(sender, {}).get("diplo_cooldowns", {})
    target_cooldowns = cooldowns.get(target, {})
    return target_cooldowns.get(action, 0) != 0

def set_ai_diplo_cooldown(sender, target, action, nation_data, duration=None):
    # Sets a cooldown for a proactive diplomatic action to prevent spamming.
    if duration is None:
        duration = c.AI_DIPLO_COOLDOWN
    
    cooldowns = nation_data.setdefault(sender, {}).setdefault("diplo_cooldowns", {})
    target_cooldowns = cooldowns.setdefault(target, {})
    target_cooldowns[action] = duration

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