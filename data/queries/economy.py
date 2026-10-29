"""Resources, costs, production output, administrative actions, and economy projections."""

import data.constants as c
import math
import pygame
import random
from data.state_access import session_for, world_for
from map_logic import politics
from data.queries.geometry import is_water_province
from data.queries.unit_info import get_base_item_name, is_naval_unit, units_with_air_cargo
from data import queries


def get_unit_upkeep(stats):
    """Calculates dynamically modified unit upkeep costs."""
    return {
        "manpower": stats.get("cost_manpower", 0) * c.UPKEEP_MODIFIERS["manpower"],
        "materials": stats.get("cost_materials", 0) * c.UPKEEP_MODIFIERS["materials"],
        "fuel": stats.get("cost_fuel", 0) * c.UPKEEP_MODIFIERS["fuel"]
    }


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


def is_training_troops(province, view_filter=None, *, context=None):
    """Return whether the deployment queue contains a matching unit category."""
    return any("unit_type" in item and (view_filter is None or queries.unit_matches_view_filter(
        {"type": item["unit_type"]}, view_filter, context=context)) for item in province.get("unit_queue", []))


def is_constructing_building(province):
    """Returns True if the province has any buildings in its deployment queue."""
    return any(q.get("order_type") == "BUILDING" for q in province.get("building_queue", []))


def get_factory_count(nation, map_data):
    """Counts a nation's existing factories and new Basic Factories in progress."""
    count = 0
    for prov in map_data.values():
        if prov.get("owner") == nation:
            for b in prov.get("buildings", []):
                if "Factory" in b: count += 1
            for q in prov.get("building_queue", []):
                # This is the number of factories that exist on the map. A
                # queued Factory Lvl upgrade improves an existing factory; it
                # does not create another one. A Basic Factory is the one
                # exception, because its construction creates a new factory.
                if q.get("item_name") == "Basic Factory": count += 1
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


ADMINISTRATIVE_ACTIONS = {
    "CORE": ("Core Territory", "CORE_CONSTRUCTION_TURNS"),
    "REMOVE_CORE": ("Remove Cores", "REMOVE_CORE_TURNS"),
}


def get_administrative_library():
    """Editor rows and historical durations from the canonical core constants."""
    return {name: {"time": getattr(c, constant)}
            for name, constant in ADMINISTRATIVE_ACTIONS.values()}


def get_administrative_turns(order_type, scenario_settings=None):
    name, constant = ADMINISTRATIVE_ACTIONS[order_type]
    default = getattr(c, constant)
    raw = (scenario_settings or {}).get("administrative_turn_overrides", {}).get(name, default)
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return default


CONVERSION_ACTIONS = {
    "TRUCK_SHIP": ("Truck / Ship Conversion", "TRUCK_CONVERT_TURNS"),
    "AIR_DROP_RECOVERY": ("Air Drop Recovery", "AIR_DROP_RECOVERY_TURNS"),
}


def get_conversion_turns(action, scenario_settings=None):
    """Read a scenario timer within the editor's limits. Older saves use defaults."""
    name, constant = CONVERSION_ACTIONS[action]
    overrides = (scenario_settings or {}).get("conversion_turn_overrides", {})
    raw = overrides.get(name) if isinstance(overrides, dict) else None
    # Settings can come from older saves or manually edited scenario files.
    if type(raw) is not int:
        raw = getattr(c, constant)
    return max(c.MIN_CONVERSION_TURNS, min(c.MAX_CONVERSION_TURNS, raw))


def get_conversion_library():
    """Supply editor rows from the shared timing defaults."""
    return {name: {"time": get_conversion_turns(action)}
            for action, (name, _constant) in CONVERSION_ACTIONS.items()}


def truck_ship_conversion_order(unit, scenario_settings=None, *, context=None):
    """Use one timer for both directions. Aircraft and Convoys have separate rules."""
    source = unit.get("type", "")
    if source.startswith("Truck"):
        target = "Ship"
    elif not source.startswith("Convoy") and is_naval_unit(source, context=context):
        target = "Truck"
    else:
        return None
    return {"type": "CONVERT", "to": target,
            "turns_left": get_conversion_turns("TRUCK_SHIP", scenario_settings)}


def is_administrative_action_enabled(order_type, scenario_settings=None):
    """Disabling an action leaves existing cores and their penalties intact."""
    settings = scenario_settings or {}
    name, _constant = ADMINISTRATIVE_ACTIONS[order_type]
    default = c.DISABLE_CORES if scenario_settings is None else c.DEFAULT_DISABLE_CORES
    return (not queries.get_scenario_flag("disable_cores", default, settings)
            and name not in settings.get("administrative_disabled", []))


def get_core_cost(nation, map_data, scenario_settings=None):
    """Calculates the cost to core a territory dynamically."""
    core_count = sum(1 for p in map_data.values() if nation in p.get("cores", []))
    
    base_cost = c.CORE_BASE_COST_MANPOWER
    scaling_cost = c.CORE_SCALING_COST_MANPOWER
    
    return {
        "cost_manpower": base_cost + (scaling_cost * core_count),
        "cost_materials": 0,
        "cost_fuel": 0,
        "time": get_administrative_turns("CORE", scenario_settings),
        "group": "administration"
    }


def get_remove_core_cost(nation, map_data, scenario_settings=None):
    """Returns the cost dictionary for removing foreign cores."""
    core_cost = get_core_cost(nation, map_data, scenario_settings)
    manpower_cost = max(0, core_cost.get("cost_manpower", 0) // 2)
    return {
        "cost_manpower": manpower_cost,
        "cost_materials": max(0, manpower_cost // 2),
        "cost_fuel": max(0, core_cost.get("cost_fuel", 0) // 2),
        "time": get_administrative_turns("REMOVE_CORE", scenario_settings),
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


def refund_queue_item(nation_data_block, item, owner=None, map_data=None, *, context=None):
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
        stats = queries.get_building_cost(item.get("item_name"), owner, map_data, queries.get_building_library(context))
    elif "unit_type" in item:
        stats = queries.get_unit_library(context).get(item["unit_type"], {})
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


def get_conscription_damage_bonus(country_data):
    """Return the extra damage fraction from reduced conscription.

    Two exponential segments meet smoothly at half conscription.
    Full, half, quarter, and zero conscription give zero, quarter, half, and full bonus.
    Missing slider values use full conscription for older saves.
    """
    conscription = max(0.0, min(1.0, country_data.get("conscription_slider", 1.0)))
    bonus_at_half = c.CONSCRIPTION_MAX_DAMAGE_BONUS / 4.0
    if conscription <= 0.5:
        return c.CONSCRIPTION_MAX_DAMAGE_BONUS * 2.0 ** (-4.0 * conscription)
    return bonus_at_half * (2.0 ** (2.0 * (1.0 - conscription)) - 1.0)


def get_country_damage_multiplier(country_id, nation_data):
    """Return national damage modifiers without any unit health penalty."""
    country = nation_data.get(country_id, {})
    return (politics.damage_multiplier(nation_data, country_id)
            * (1.0 + queries.get_conscription_damage_bonus(country)))


def get_siphon_rates(nation_data_block):
    """Returns a puppet's per-resource siphon rates, creating the block if missing."""
    return nation_data_block.setdefault("siphon_rates", {res: 0.0 for res in c.ECON_RESOURCE_KEYS})


def get_building_output_modifiers(research, building_library=None, *, context=None):
    """Prepare percentage multipliers and flat additions for each building output."""
    if context is None:
        context = building_library
    if building_library is None:
        building_library = queries.get_building_library(context)
    tree = queries.get_tech_tree(context)
    bonuses = [(bonus, min(level, tree[tech]["max_lvl"]))
               for tech, level in research.items() if level > 0 and tech in tree
               for bonus in tree[tech].get("building_output_bonuses", [])]
    multipliers = {}
    additions = {}
    if not bonuses:
        return {"multipliers": multipliers, "additions": additions}
    for name, stats in building_library.items():
        values = {res: 1.0 for res in c.ECON_RESOURCE_KEYS}
        flat = {res: 0.0 for res in c.ECON_RESOURCE_KEYS}
        family = get_base_item_name(name, context=context)
        for bonus, level in bonuses:
            if (family in bonus.get("building_families", [])
                    or stats.get("group") in bonus.get("building_groups", [])):
                for resource, amount in bonus.get("outputs", {}).items():
                    values[resource] *= (1.0 + amount) ** level
                for resource, amount in bonus.get("flat_outputs", {}).items():
                    flat[resource] += amount * level
        multipliers[name] = values
        additions[name] = flat
    return {"multipliers": multipliers, "additions": additions}


def get_building_output_multipliers(research, building_library=None, *, context=None):
    """Return percentage multipliers for callers that use the existing interface."""
    return get_building_output_modifiers(research, building_library, context=context)["multipliers"]


def get_building_output(building_name, research, building_library=None, *, context=None, multipliers=None, modifiers=None):
    """Return building yields with national research bonuses before territory penalties."""
    if building_library is None:
        building_library = queries.get_building_library(context)
    if modifiers is None:
        modifiers = get_building_output_modifiers(research, building_library, context=context)
    if multipliers is None:
        multipliers = modifiers["multipliers"]
    stats = building_library.get(building_name, {})
    values = multipliers.get(building_name, {})
    additions = modifiers["additions"].get(building_name, {})
    return {res: (stats.get(f"prod_{res}", 0) + additions.get(res, 0)) * values.get(res, 1.0)
            for res in c.ECON_RESOURCE_KEYS}


def get_province_building_output(province, research, building_library=None, *, context=None, multipliers=None, modifiers=None):
    """Apply building bonuses and territory penalties, including factory construction yields."""
    if building_library is None:
        building_library = queries.get_building_library(context)
    if modifiers is None:
        modifiers = get_building_output_modifiers(research, building_library, context=context)
    if multipliers is None:
        multipliers = modifiers["multipliers"]
    territory_mult = 1.0 if queries.has_core(province.get("owner"), province) else c.NON_CORE_BUILDING_MULTIPLIER
    output = {res: 0 for res in c.ECON_RESOURCE_KEYS}
    for name in province.get("buildings", []):
        yields = queries.get_building_output(name, research, building_library, context=context,
                                    multipliers=multipliers, modifiers=modifiers)
        for res in c.ECON_RESOURCE_KEYS:
            output[res] += int(yields[res] * territory_mult)
    for project in province.get("building_queue", []):
        if project.get("item_name") == "Basic Factory":
            remaining = project.get("turns_remaining", c.BASIC_FACTORY_TURNS)
            fractions = c.BASIC_FACTORY_CONSTRUCTION_OUTPUT_FRACTIONS
            stage_turns = max(1, c.BASIC_FACTORY_TURNS // len(fractions))
            stage = int(max(0, min(len(fractions) - 1, (c.BASIC_FACTORY_TURNS - remaining) // stage_turns)))
            materials = queries.get_building_output("Basic Factory", research, building_library, context=context,
                                           multipliers=multipliers, modifiers=modifiers)["materials"]
            output["materials"] += int(materials * fractions[stage] * territory_mult)
    return output


def calculate_all_economies(map_data, nation_data, *, context=None):
    """Standardized economy calculator. Single source of truth for UI and Turn Processor."""
    if context is None:
        context = nation_data
    unit_lib = queries.get_unit_library(context)
    bldg_lib = queries.get_building_library(context)
    building_modifiers = {}

    # Initialize data structure for all active nations
    econ_data = {}
    for name, n_data in list(nation_data.items()):
        res_data = n_data.get("research", {})
        building_modifiers[name] = get_building_output_modifiers(res_data, bldg_lib, context=context)
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
                  "conversion": 0, "conscription": 0, "policy": 0,
                  "siphon": 0, "siphon_income": 0}
            for res in c.ECON_RESOURCE_KEYS
        }

        econ_data[name] = {"dynamic_yields": dyn_yields, "breakdown": breakdown, "upkeep": {r: 0 for r in c.ECON_RESOURCE_KEYS}, "total_inc": {r: 0 for r in c.ECON_RESOURCE_KEYS}, "resource_mult": resource_refining_mult}

    # Single efficient pass over the map
    for province in map_data.values():
        owner = province.get("owner")
        
        # --- INCOME LOGIC ---
        if owner and owner in econ_data and owner not in c.UNPLAYABLE_NATIONS:
            is_core = queries.has_core(owner, province)
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
            building_output = queries.get_province_building_output(
                province, nation_data[owner].get("research", {}), bldg_lib,
                modifiers=building_modifiers[owner])
            for res in c.ECON_RESOURCE_KEYS:
                bd[res]["buildings"] += building_output[res]

        # --- UPKEEP LOGIC ---
        for unit in units_with_air_cargo(province.get("units", [])):
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
        _process_conversion(data, "materials", "fuel", "conversion", min(n_data.get("mat_to_fuel_slider", 0.0), queries.get_max_fuel_conversion(n_data)), c.FUEL_CONVERSION_RATIO)

        for res in c.ECON_RESOURCE_KEYS:
            produced_income = sum(data["breakdown"][res].values())
            policy_multiplier = politics.resource_multiplier(nation_data, name, res)
            # A policy changes what the country produces, never standing-army
            # upkeep.  Store the difference in the same breakdown that powers
            # the economy panel, so its displayed total matches the turn result.
            data["breakdown"][res]["policy"] = produced_income * (policy_multiplier - 1.0)
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
    world_state = world_for(map_screen)
    session_state = session_for(map_screen)
    is_tactical = session_state.tactical_mode and session_state.player_unit

    if target_nation is None:
        target_nation = session_state.player_country
        
    if is_tactical and target_nation == session_state.player_country:
        manpower = int(map_screen.player_manpower)
        materials = int(map_screen.player_materials)
        fuel = int(map_screen.player_fuel)
    else:
        n_data = world_state.nation_data.get(target_nation, {})
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
        if is_tactical and target_nation == session_state.player_country:
            u_type = session_state.player_unit.get("original_type", session_state.player_unit.get("type"))
            stats = queries.get_unit_library(map_screen).get(u_type, {})
            total_inc = get_unit_upkeep(stats)
            morale = session_state.player_unit.get("morale", c.DEFAULT_UNIT_MORALE)
            desertion_cost = total_inc.get("manpower", 0) * ((100.0 - float(morale)) / 100.0)
            total_upkeep["manpower"] = desertion_cost
        else:
            if not hasattr(map_screen, 'econ_cache_time') or pygame.time.get_ticks() - map_screen.econ_cache_time > 1000 or getattr(map_screen, 'econ_cache_target', None) != target_nation:
                map_screen.econ_cache = queries.get_economy_projections(target_nation, world_state.map_data, world_state.nation_data, context=map_screen)
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

        if is_tactical and target_nation == session_state.player_country:
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


def get_economy_projections(target_nation, map_data, nation_data, *, context=None):
    """Pulls a specific nation's UI data from the unified calculator."""
    if context is None:
        context = nation_data
    all_econ = queries.calculate_all_economies(map_data, nation_data, context=context)
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
