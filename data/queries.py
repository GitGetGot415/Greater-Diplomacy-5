import json
import os
import data.constants as c
import re
import base64
import pygame

# --- CACHE LIBRARIES ---
_cached_unit_library = None
_cached_building_library = None
_cached_tech_tree = None
_cached_country_data = None

def get_unit_library(): 
    global _cached_unit_library
    if _cached_unit_library is None:
        _cached_unit_library = json.load(open(c.UNIT_DATA_PATH)) if os.path.exists(c.UNIT_DATA_PATH) else {}
    return _cached_unit_library

def get_building_library(): 
    global _cached_building_library
    if _cached_building_library is None:
        _cached_building_library = json.load(open(c.BUILDING_DATA_PATH)) if os.path.exists(c.BUILDING_DATA_PATH) else {}
    return _cached_building_library

def get_tech_tree():
    global _cached_tech_tree
    if _cached_tech_tree is None:
        _cached_tech_tree = json.load(open(c.RESEARCH_TEMPLATE_PATH)) if os.path.exists(c.RESEARCH_TEMPLATE_PATH) else {}
    return _cached_tech_tree

def get_country_data():
    global _cached_country_data
    if _cached_country_data is None:
        if os.path.exists(c.COUNTRIES_DATA_PATH):
            with open(c.COUNTRIES_DATA_PATH, "r") as f:
                _cached_country_data = json.load(f)
        else:
            _cached_country_data = {}
    return _cached_country_data
# ==========================================
# DIPLOMACY & COMBAT QUERIES
# ==========================================

def are_at_war(nation_a, nation_b, nation_data):
    """Returns True if nation_b is in nation_a's war list."""
    return nation_b in nation_data.get(nation_a, {}).get("at_war_with", [])

def is_province_in_active_combat(province, nation_data):
    """Returns True if ANY units from mutually hostile nations occupy this province."""
    units = province.get("units", [])
    if len(units) < 2:
        return False
        
    owners_present = list(set(u.get("owner") for u in units if u.get("owner")))
    
    for i in range(len(owners_present)):
        for j in range(i + 1, len(owners_present)):
            if are_at_war(owners_present[i], owners_present[j], nation_data):
                return True
    return False

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
    return target_owner == moving_nation or are_in_same_faction(moving_nation, target_owner, nation_data) or target_owner == "Unclaimed"

def can_land_units_enter(moving_nation, target_province, nation_data):
    """Centralized rules for land movement."""
    if target_province.get("terrain") in c.WATER_TERRAINS:
        return False

    target_owner = target_province.get("owner", "Unclaimed")

    # Whitelist neutral water countries so they act as open international waters
    allowed_owners = ["Unclaimed", "None", moving_nation, "Ocean", "Lakes"]

    if target_owner not in allowed_owners:
        if not (are_at_war(moving_nation, target_owner, nation_data) or are_in_same_faction(moving_nation, target_owner, nation_data)):
            return False

    return True


# ==========================================
# PROVINCE & TECH QUERIES
# ==========================================

def get_industry(province):
    """Returns the highest level of industry in the province."""
    # 1-5 workshop
    # 6 basic factory
    # 7-11 factory
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
    return None, 0

def get_highest_infantry(nation_data_block, tech_tree, unit_library):
    """Finds the highest level infantry unit the nation has researched."""
    res_lvl = nation_data_block.get("research", {}).get("infantry_type", 1)
    inf_years = tech_tree.get("infantry_type", {}).get("years", [c.START_YEAR])
    
    # --- UPDATED: Safer index bounds checking ---
    target_index = max(0, min(res_lvl - 1, len(inf_years) - 1))
    year_val = inf_years[target_index]
    u_name = f"Infantry Type {year_val}"
    
    if u_name in unit_library:
        return u_name
    return f"Infantry Type {c.START_YEAR}"

def check_tech_requirements(res_levels, reqs):
    """Centralized tech requirement checker."""
    if not reqs: return True
    if "OR" in reqs:
        return any(res_levels.get(k, 0) >= v for sub in reqs["OR"] for k, v in sub.items())
    return all(res_levels.get(k, 0) >= v for k, v in reqs.items())

# ==========================================
# ECONOMY QUERIES
# ==========================================

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
    YIELD_MANPOWER = c.BASE_YIELDS["manpower"]
    YIELD_MATERIALS = c.BASE_YIELDS["materials"]
    YIELD_FUEL = c.BASE_YIELDS["fuel"]

    unit_lib = get_unit_library()
    bldg_lib = get_building_library()

    # Initialize data structure for all active nations
    econ_data = {}
    for name in nation_data.keys():
        econ_data[name] = {
            "breakdown": {
                "manpower": {"core": 0, "non_core": 0, "buildings": 0, "resources": 0},
                "materials": {"core": 0, "non_core": 0, "buildings": 0, "resources": 0},
                "fuel": {"core": 0, "non_core": 0, "buildings": 0, "resources": 0}
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

            bd["manpower"][cat] += man_mult * YIELD_MANPOWER
            bd["materials"][cat] += mat_mult * YIELD_MATERIALS
            bd["fuel"][cat] += fuel_mult * YIELD_FUEL

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
                econ_data[u_owner]["upkeep"]["manpower"] += stats.get("cost_manpower", 0) * c.UPKEEP_MODIFIER
                econ_data[u_owner]["upkeep"]["materials"] += stats.get("cost_materials", 0) * c.UPKEEP_MODIFIER
                econ_data[u_owner]["upkeep"]["fuel"] += stats.get("cost_fuel", 0) * c.UPKEEP_MODIFIER

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
    is_unilateral = action in ["WAR_DECLARATION", "JOIN_WARS", "BREAK_ALLIANCE", "KICK_FACTION_MEMBER", "LEAVE_FACTION", "DISBAND_FACTION"]
    
    if is_unilateral and turns > 0:
        return False
        
    # Allow queueing new messages/actions if the current action is just a message in transit
    #if str(action).startswith("MSG:") and turns > 0:
    #    return False
        
    if turns > 0: 
        return True
    return False

def get_unread_message_count(nation, nation_data):
    """Returns the total number of unread messages for a nation."""
    inbox = nation_data.get(nation, {}).get("inbox", [])
    return sum(1 for msg in inbox if not msg.get("read", False))

def has_free_research_slots(nation, nation_data):
    """Returns True if the nation is researching fewer than 2 techs."""
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
    stats = get_unit_library().get(unit_type, {})
    return stats.get("naval_unit", False)

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
    
    for name, data in map_screen.nation_data.items():
        if name not in human_players and name not in c.UNPLAYABLE_NATIONS and data.get("is_playable"):
            ai_nations.append(name)
            
    return ai_nations

def is_unit_obsolete(group_name, player_research):
    """Checks if a unit group is obsolete based on researched techs."""
    obsoleting_techs = c.OBSOLESCENCE_RULES.get(group_name, [])
    return any(player_research.get(tech, 0) >= 1 for tech in obsoleting_techs)

# ==========================================
# PREDICTION QUERIES (UI & RENDERING)
# ==========================================

def get_combat_predictions(map_data, nation_data, id_to_province):
    """Generates predictions for meeting engagements and province clashes."""
    predictions = []
    incoming = {} # dest_id -> list of (unit, origin_id)
    
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
    """Encodes a pygame surface to a Base64 string."""
    img_str = pygame.image.tostring(surf, fmt)
    return base64.b64encode(img_str).decode('utf-8')

def decode_b64_to_surf(b64_str, size):
    """Decodes a Base64 string back into a pygame surface."""
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