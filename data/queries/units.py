"""Unit instances: stats refresh, owner changes, health loss, bombardment, view filters, and settings families."""

import re

import data.constants as c
from data.state_access import world_for
from data.queries.unit_info import (
    UNIT_GROUP_TANKS,
    air_unit_mission_icon,
    classify_unit_group,
    get_base_unit_name,
    get_bombardment_range,
    get_formatted_division_name,
    get_ordinal,
    is_air_unit,
    is_naval_unit,
    unit_display_domain,
    units_with_air_cargo,
)
from data import queries
from map_logic import politics


def is_in_transport(unit):
    """Return True if this unit is currently converted into a Convoy or Truck."""
    if not isinstance(unit, dict):
        return False
    if unit.get("transport_mode"):
        return True
    return "original_type" in unit or unit.get("type", "").startswith(("Convoy (", "Truck ("))


def get_transport_mode(unit):
    """Return 'convoy', 'truck', or None for the unit's active transport mode."""
    if not isinstance(unit, dict):
        return None
    mode = unit.get("transport_mode")
    if mode:
        return mode.lower()
    t = unit.get("type", "")
    if "original_type" in unit or t.startswith(("Convoy (", "Truck (")):
        if t.startswith("Convoy ("):
            return "convoy"
        if t.startswith("Truck ("):
            return "truck"
    return None


def get_base_unit_type(unit):
    """Return the underlying unit type, stripping any Convoy/Truck transport wrapper."""
    if isinstance(unit, str):
        if unit.startswith(("Convoy (", "Truck (")) and unit.endswith(")"):
            inner = unit[unit.find("(") + 1:-1].strip()
            return inner if inner else unit
        return unit
    if not isinstance(unit, dict):
        return ""
    if "original_type" in unit and unit["original_type"]:
        return unit["original_type"]
    t = unit.get("type", "")
    if t.startswith(("Convoy (", "Truck (")) and t.endswith(")"):
        inner = t[t.find("(") + 1:-1].strip()
        return inner if inner else t
    return t


def get_stored_unit_family(unit):
    """Return the settings family of a stored unit. A Convoy or Truck uses the unit it carries.

    This reads the complete default library. A world's active library omits disabled families,
    and a name alone gives the wrong family for stage names such as "Flintlock Infantry I".
    """
    unit_type = get_base_unit_type(unit)
    return queries.get_base_item_name(unit_type)


def find_units_of_families(map_data, families):
    """Return (province, unit) for each unit and carried aircraft whose settings family is in `families`."""
    return [(province, unit) for province in map_data.values()
            for unit in units_with_air_cargo(province.get("units", []))
            if get_stored_unit_family(unit) in families]


def remove_units_of_families(province, families):
    """Remove a province's units and carried aircraft whose settings family is in `families`."""
    for unit in province.get("units", []):
        cargo = unit.get("air_cargo")
        if isinstance(cargo, list):
            unit["air_cargo"] = [carried for carried in cargo if get_stored_unit_family(carried) not in families]
    province["units"] = [unit for unit in province.get("units", []) if get_stored_unit_family(unit) not in families]


def held_volunteer_units(nation_data):
    for country in nation_data.values():
        if not isinstance(country, dict):
            continue
        for mission in country.get("volunteer_missions", {}).values():
            for entry in mission.get("held_units", []):
                yield entry["unit"]


def can_bombard(unit_type, *, context=None):
    """Returns True if this unit class can shell a nearby tile instead of moving."""
    return get_bombardment_range(unit_type, context=context) > 0


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


def generate_unit_custom_name(unit, unit_counters, *, context=None):
    """Generates a dynamic custom name for a unit based on its type and country count."""
    owner = unit.get("owner", "Unclaimed")
    unit_type = unit.get("type", "Infantry")
    
    label = queries.get_unit_metadata(unit_type, context=context).get("division_suffix", "")
    suffix = f" ({label})" if label else ""

    # Clean up the base name using our new unified string parser
    base_name = get_formatted_division_name(unit_type, context=context)
    
    # Track count per owner per base type
    count = unit_counters.setdefault(owner, {}).get(base_name, 0) + 1
    unit_counters[owner][base_name] = count
    
    ordinal = get_ordinal(count)
    return f"{ordinal} {base_name}{suffix}"


def build_active_unit_counters(map_data, *, context=None):
    """Sweeps the map and returns a dictionary of current unit counts for accurate naming."""
    unit_counters = {}
    for prov in map_data.values():
        for unit in units_with_air_cargo(prov.get("units", [])):
            owner = unit.get("owner", "Unclaimed")
            base_name = get_formatted_division_name(unit.get("type", "Infantry"), context=context)
            unit_counters.setdefault(owner, {})[base_name] = unit_counters.setdefault(owner, {}).get(base_name, 0) + 1
    return unit_counters


# i don't know if this would really count as a query...
def load_transport(unit, target, *, context=None):
    """Puts a unit aboard a Convoy or into a Truck, remembering what it was.

    The mirror of revert_transport, and the other half of what used to live
    inline in movement_processor.process_conversions -- pulled out so the
    stranded-at-sea sweep can re-embark a unit without duplicating the stat
    bookkeeping that makes the round trip lossless.
    """
    if target not in ("Convoy", "Truck"):
        return
    if target == "Truck" and is_air_unit(unit, context=context):
        raise ValueError("Air units can only be loaded into Convoys.")

    base_type = get_base_unit_type(unit)
    unit["original_type"] = base_type
    unit["original_speed"] = unit.get("speed", 1)
    unit["original_max_health"] = unit.get("max_health", c.DEFAULT_UNIT_HP)
    unit["original_attack"] = unit.get("attack", c.DEFAULT_UNIT_ATK)
    unit["original_defense"] = unit.get("defense", c.DEFAULT_UNIT_DEF)
    unit["transport_mode"] = target.lower()

    pct = unit.get("health", 1) / max(1, unit.get("max_health", 1))

    unit["type"] = f"{target} ({base_type})"
    nation_data = getattr(world_for(context), "nation_data", None)
    unit.update(_transport_stats(target, nation_data, unit.get("owner")))
    unit["health"] = unit["max_health"] * pct


def set_unit_owner(unit, country_id, *, context=None):
    """Transfer a unit and all its cargo to the same country."""
    for member in units_with_air_cargo([unit]):
        old_owner = member.get("owner")
        member["owner"] = country_id
        if context is not None and country_id != old_owner:
            nation_data = world_for(context).nation_data
            if politics.unit_stat_policies(nation_data, old_owner) or politics.unit_stat_policies(nation_data, country_id):
                apply_library_stats(member, queries.get_unit_library(context), nation_data)


def apply_unit_health_loss(unit, damage, *, sources=None, tile=None):
    """Cargo loses the same fraction of current health as its carrier."""
    from map_logic.system32 import unit_events
    health = max(0, unit.get("health", 0))
    loss = min(health, max(0, damage))
    unit_events.record_damage(unit, loss, sources, tile)
    if health:
        for cargo in unit.get("air_cargo", []):
            apply_unit_health_loss(cargo, cargo.get("health", 0) * loss / health,
                                   sources=sources, tile=tile)
    unit["health"] = health - loss
    return loss


UNIT_VIEW_FILTERS = ("NAVAL", "LAND", "AIR", "ALL")


DEFAULT_UNIT_VIEW_FILTER = "ALL"


def unit_map_stack_key(unit, *, context=None):
    """Keep map boxes separate by current domain and aircraft mission."""
    domain = unit_display_domain(unit, context=context)
    return domain, air_unit_mission_icon(unit) if domain == "AIR" else None


def can_view_unit_orders(unit, player_country, viewing_ai_moves=False):
    """Use the same order visibility for map arrows and mission badges."""
    return (unit.get("owner") == player_country or player_country == "Spectator"
            or viewing_ai_moves)


def unit_matches_view_filter(unit, view_filter, *, context=None):
    """Classify the current form, including carried units, for map display."""
    if view_filter == "ALL":
        return True
    if view_filter not in UNIT_VIEW_FILTERS:
        raise ValueError(f"Unknown unit view filter: {view_filter}")
    return view_filter == unit_display_domain(unit, context=context)


def unit_target_damage_multiplier(attacker, target, air_to_air=False, *, unit_library=None, context=None):
    """Target-specific damage, shared by combat, bombardment and previews."""
    library = queries.get_unit_library(context) if unit_library is None else unit_library
    if not library.get(target.get("type", ""), {}).get("air_role"):
        return 1.0
    name = attacker.get("type", "")
    stats = library.get(name, {})
    if classify_unit_group(get_base_unit_name(name, context=context), stats) == UNIT_GROUP_TANKS:
        return 0.0
    return (stats.get("air_attack_multiplier", 1.0)
            if air_to_air and stats.get("air_role") else 1.0)


def ground_combat_profile(unit, *, context=None):
    """Non-mutating casualty profile for UI/AI estimates of a caught aircraft."""
    if not is_air_unit(unit, context=context):
        return unit
    profile = dict(unit)
    profile.update(health=0, attack=0, defense=0)
    return profile


def revert_transport(unit, *, context=None):
    """Reverts a transport (like a Convoy) back to its original unit type."""
    if not is_in_transport(unit):
        return

    base_type = get_base_unit_type(unit)
    pct = unit.get("health", 1) / max(1, unit.get("max_health", 1))

    unit["type"] = base_type
    unit["speed"] = unit.get("original_speed", 1)
    unit["max_health"] = unit.get("original_max_health", c.DEFAULT_UNIT_HP)
    unit["attack"] = unit.get("original_attack", c.DEFAULT_UNIT_ATK)
    unit["defense"] = unit.get("original_defense", c.DEFAULT_UNIT_DEF)

    unit["health"] = unit["max_health"] * pct
    unit["naval_unit"] = is_naval_unit(unit["type"], context=context)
    unit.pop("transport_mode", None)

    for key in ["original_type", "original_speed", "original_max_health", "original_attack", "original_defense"]:
        if key in unit: del unit[key]


def refresh_unit_stats(map_data, nation_data, unit_library, owners=None):
    """Apply library stats to every map unit, carried unit, and held volunteer unit.

    Runs on load for every unit. The politics step limits refreshes to affected owners.
    """
    units = [unit for province in map_data.values() for unit in units_with_air_cargo(province.get("units", []))]
    for unit in units + list(held_volunteer_units(nation_data)):
        if owners is None or unit.get("owner") in owners:
            apply_library_stats(unit, unit_library, nation_data)


def refresh_policy_unit_stats(context, owner, previous):
    """Refresh stored stats when a planning change alters the owner's active stat policies."""
    world = world_for(context)
    if previous != politics.unit_stat_policies(world.nation_data, owner):
        refresh_unit_stats(world.map_data, world.nation_data, queries.get_unit_library(context), owners={owner})


def library_unit_stats(stats, health_multiplier=1.0):
    """Return the combat fields a unit record copies from its library entry."""
    health = stats.get("health", c.DEFAULT_UNIT_HP)
    return {"max_health": health if health_multiplier == 1.0 or health <= 0 else max(1, round(health * health_multiplier)),
            "attack": stats.get("attack", c.DEFAULT_UNIT_ATK),
            "defense": stats.get("defense", c.DEFAULT_UNIT_DEF),
            "speed": stats.get("speed", c.DEFAULT_UNIT_SPD)}


def max_health_multiplier(nation_data, owner):
    """Maximum health from Quality and any policies that cover every domain."""
    return politics.axis_policy_multiplier(nation_data, owner, "max_health") if nation_data is not None else 1.0


def country_unit_stats(stats, nation_data, owner, *, transport=False):
    """Derive effective record stats from the library or a transport's own base stats."""
    land = not (stats.get("naval_unit") or stats.get("air_role"))
    multiplier = (politics.effect_multiplier(nation_data, owner, "max_health") if transport
                  else max_health_multiplier(nation_data, owner))
    if land:
        multiplier *= politics.effect_multiplier(nation_data, owner, "land_max_health")
    values = library_unit_stats(stats, multiplier)
    if land:
        values["speed"] += politics.effect_bonus(nation_data, owner, "land_speed")
    return values


def _transport_stats(carrier, nation_data, owner):
    naval = carrier == "Convoy"
    if naval:
        stats = {"health": c.CONVOY_MAX_HP, "attack": c.CONVOY_ATK, "defense": c.CONVOY_DEF, "speed": 1, "naval_unit": True}
    else:
        stats = {"health": c.TRUCK_MAX_HP, "attack": c.TRUCK_ATK, "defense": c.TRUCK_DEF, "speed": 1}
    return {**country_unit_stats(stats, nation_data, owner, transport=True), "naval_unit": naval}


def apply_library_stats(unit, unit_library, nation_data=None):
    """Set a unit's combat stats from the unit library and keep its health fraction.

    Library entries supply the base stats. Unit records hold the effective
    values and refresh on load, type changes, and relevant politics changes.
    With ``nation_data``, Quality and active policies modify the combat stats.
    A Convoy or Truck takes its own stats from the shared constants and keeps
    the carried unit's library stats in its original_* fields.
    Return False for a type that is not in the library, and leave the unit unchanged.
    """
    unit_type = unit.get("type", "")
    carrier = next((name for name in ("Convoy", "Truck") if unit_type.startswith(name + " (")), None)
    stats = unit_library.get(unit.get("original_type") if carrier else unit_type)
    if stats is None:
        return False
    old_max = unit.get("max_health")
    owner = unit.get("owner")
    values = country_unit_stats(stats, nation_data, owner)
    if carrier:
        unit.update({"original_" + field: value for field, value in values.items()})
        values = _transport_stats(carrier, nation_data, owner)
    else:
        values["naval_unit"] = bool(stats.get("naval_unit", False))
    # Rescale only a changed maximum. Repeated loads keep exact health values.
    if "health" not in unit:
        unit["health"] = values["max_health"]
    elif values["max_health"] != old_max:
        unit["health"] = values["max_health"] * unit["health"] / max(1, old_max or 1)
    unit.update(values)
    return True


def has_units_in_province(nation, province):
    """Returns True if the given nation has any units in the target province."""
    return any(u.get("owner") == nation for u in province.get("units", []))


def get_best_unit(units, sort_keys):
    """Generic helper to find the unit with the highest combination of given stats."""
    if not units:
        return None
    # Tuple sorting automatically evaluates primary, secondary, and tertiary keys dynamically
    return max(units, key=lambda u: tuple(u.get(key, 0) for key in sort_keys))


def get_best_unit_by_defense_then_attack_then_speed(units): return get_best_unit(units, ["defense", "attack", "speed"])
