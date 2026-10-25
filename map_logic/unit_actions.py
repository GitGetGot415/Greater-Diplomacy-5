"""Prepare and apply unit orders with shared payment and cancellation rules."""

import copy
from dataclasses import dataclass

import data.constants as c
from data import queries
from data.state_access import world_for, session_for

COST_KEYS = tuple("cost_" + resource for resource in c.ECON_RESOURCE_KEYS)


@dataclass(frozen=True)
class UnitActionResult:
    order: object
    cost: dict
    refund: dict
    changed: bool


def order_refund(unit):
    order = unit.get("order")
    return dict(order.get("refund", {})) if isinstance(order, dict) else {}


def payment_account(context, country_id, unit, *, authority="player"):
    session = session_for(context)
    if authority == "player" and session.tactical_mode and unit is session.player_unit:
        return session.unit_economy
    return world_for(context).nation_data[country_id]


def unit_permission(context, country_id, unit, *, authority="player"):
    if unit.get("owner") != country_id:
        return False
    if authority in ("ai", "server", "setup"):
        return True
    session = session_for(context)
    if getattr(session, "tactical_mode", False):
        return unit is session.player_unit
    return session.player_country == country_id


def prepare_action(context, country_id, province, unit, order):
    """Derive an order and payment delta without modifying the unit or resources."""
    if unit.get("owner") != country_id:
        raise ValueError("Players may only order their own units.")
    existing = unit.get("order")
    if isinstance(existing, dict) and isinstance(order, dict):
        kind = order.get("type")
        if not isinstance(kind, str):
            raise ValueError("Invalid unit order type.")
        identity_keys = {"UPGRADE": ("target_type",), "CONVERT": ("to",)}.get(kind, ())
        if (kind in ("REPAIR", "UPGRADE", "CONVERT", "DISBAND") and existing.get("type") == kind
                and all(existing.get(key) == order.get(key) for key in identity_keys)):
            # Progress and paid escrow belong to the existing order.
            return UnitActionResult(copy.deepcopy(existing), {}, {}, False)
    canonical = canonical_order(context, country_id, province, unit, order)
    cost = canonical.pop("realtime_cost", {}) if isinstance(canonical, dict) else {}
    return UnitActionResult(canonical, cost, order_refund(unit), canonical != existing)


def apply_action(context, country_id, province, unit, order, *, authority="player", payment_settled=False):
    """Recheck authority, state, and affordability before replacing an order."""
    if not unit_permission(context, country_id, unit, authority=authority):
        raise ValueError("You cannot command that unit.")
    if not any(current is unit for current in province.get("units", [])):
        raise ValueError("The unit is no longer in that province.")
    result = prepare_action(context, country_id, province, unit, order)
    account = (payment_account(context, country_id, unit, authority=authority)
               if result.cost or result.refund else {})
    available = dict(account)
    queries.refund_resources(available, result.refund)
    if not payment_settled and not queries.can_afford(available, result.cost):
        raise ValueError("Cannot afford this unit order.")
    if result.changed:
        if not payment_settled:
            queries.refund_resources(account, result.refund)
            queries.deduct_resources(account, result.cost)
        if result.order is None:
            unit.pop("order", None)
        else:
            unit["order"] = copy.deepcopy(result.order)
    return result


def cancel_action(context, country_id, province, unit, *, authority="player"):
    return apply_action(context, country_id, province, unit, None, authority=authority)


def apply_batch(context, country_id, choices, *, authority="player"):
    """Preserve aggregate repair affordability and refund-before-payment order."""
    prepared = []
    for unit, province, order in choices:
        if not unit_permission(context, country_id, unit, authority=authority):
            raise ValueError("You cannot command that unit.")
        if not any(current is unit for current in province.get("units", [])):
            raise ValueError("The selected unit moved.")
        prepared.append((unit, prepare_action(context, country_id, province, unit, order)))
    if not prepared:
        return []
    account = payment_account(context, country_id, prepared[0][0], authority=authority)
    cost = {key: sum(result.cost.get(key, 0) for _, result in prepared) for key in COST_KEYS}
    refund = {key: sum(result.refund.get(key, 0) for _, result in prepared) for key in COST_KEYS}
    available = dict(account)
    queries.refund_resources(available, refund)
    if not queries.can_afford(available, cost):
        raise ValueError("Cannot afford repairs for all selected units!")
    queries.refund_resources(account, refund)
    queries.deduct_resources(account, cost)
    for unit, result in prepared:
        if result.changed:
            if result.order is None:
                unit.pop("order", None)
            else:
                unit["order"] = copy.deepcopy(result.order)
    return [result for _, result in prepared]


def repair_costs(context, unit, unit_library=None):
    world = world_for(context)
    if queries.get_scenario_flag("free_repairs", c.DEFAULT_FREE_REPAIRS, world.scenario_settings):
        return dict.fromkeys(COST_KEYS, 0)
    library = queries.get_unit_library(context) if unit_library is None else unit_library
    stats = library.get(unit.get("original_type", unit.get("type", "")), {})
    maximum = unit.get("max_health", 1)
    missing = (maximum - unit.get("health", 0)) / max(1, maximum)
    return {key: int(stats.get(key, 0) * missing) for key in COST_KEYS}


def canonical_order(map_screen, country_id, province, unit, order):
    """Host/server validation shared with tournament aircraft commands."""
    world_state = world_for(map_screen)
    if queries.unit_is_air_drop_recovering(unit):
        queries.validate_air_drop_recovery_draft(unit, {"order": order})
        return copy.deepcopy(unit["order"])
    if order is not None and not isinstance(order, dict):
        raise ValueError("Invalid unit order.")
    if order is None or order == {}:
        return None
    kind = order.get("type")
    if not isinstance(kind, str):
        raise ValueError("Invalid unit order type.")
    if kind in queries.AIR_ORDER_TYPES:
        return queries.canonical_air_order(map_screen, unit, province, order)
    if kind == "MOVE":
        path = order.get("path", [])
        if (not isinstance(path, list) or len(path) > queries.MAX_UNIT_ORDER_PATH
                or any(isinstance(province_id, bool) or not isinstance(province_id, int)
                       for province_id in path)):
            raise ValueError("Invalid movement path.")
        previous = province
        for province_id in path:
            destination = queries.province_for_order(map_screen, province_id)
            if not queries.can_unit_move_step(
                    unit, previous, destination, world_state.nation_data, context=map_screen):
                raise ValueError("That unit cannot enter a province in this path.")
            previous = destination
        return {"type": "MOVE", "path": list(path)}
    if kind == "BOMBARD":
        if queries.is_air_unit(unit, context=map_screen):
            raise ValueError("Aircraft must use a supported air mission.")
        target = queries.province_for_order(map_screen, order.get("target_id"))
        unit_type = unit.get("type", "")
        if (queries.is_water_province(province)
                and not (unit.get("naval_unit") or queries.is_naval_unit(unit_type, context=map_screen))):
            raise ValueError("That unit cannot bombard from water.")
        targets = queries.get_bombardment_targets(
            province, world_state.id_to_province, queries.get_bombardment_range(unit_type, context=map_screen))
        if target["id"] not in targets:
            raise ValueError("Bombardment target is out of range.")
        return {"type": "BOMBARD", "target_id": target["id"]}
    if kind == "DISBAND":
        if unit.get("air_cargo"):
            raise ValueError("Release cargo before disbanding its carrier.")
        return {"type": "DISBAND", "turns_left": 1}
    if kind == "REPAIR":
        if queries.is_nation_in_combat_here(country_id, province, world_state.nation_data):
            raise ValueError("Units cannot repair in combat.")
        cost = repair_costs(map_screen, unit)
        return {"type": "REPAIR", "turns_left": 1, "refund": cost, "realtime_cost": cost}
    if kind == "UPGRADE":
        target_type = order.get("target_type")
        unit_library = queries.get_unit_library(map_screen)
        research = world_state.nation_data[country_id].get("research", {})
        if (not isinstance(target_type, str) or target_type not in unit_library
                or target_type != queries.get_upgrade_target(unit.get("type", ""), research,
                                                     unit_library, queries.get_tech_tree(map_screen))
                or not queries.is_unit_unlocked(target_type, research, context=map_screen)
                or not queries.has_industry(province)
                or queries.is_nation_in_combat_here(country_id, province, world_state.nation_data)):
            raise ValueError("Invalid unit upgrade.")
        return {"type": "UPGRADE", "turns_left": 1, "target_type": target_type, "refund": {}}
    if kind == "CONVERT":
        source = unit.get("type", "")
        if queries.is_nation_in_combat_here(country_id, province, world_state.nation_data):
            raise ValueError("Units cannot convert in combat.")
        air_conversion = queries.air_conversion_order(unit, context=map_screen)
        if air_conversion:
            if queries.is_water_province(province):
                raise ValueError("Aircraft conversion requires land.")
            if queries.is_air_unit(unit, context=map_screen) and not province.get("is_coastal", False):
                raise ValueError("Convoy conversion requires a coast.")
            expected, turns = air_conversion["to"], air_conversion["turns_left"]
        elif source.startswith("Convoy"):
            expected, turns = "Land Unit", 1
        elif source.startswith("Truck") or queries.is_naval_unit(source, context=map_screen):
            conversion = queries.truck_ship_conversion_order(unit, world_state.scenario_settings, context=map_screen)
            if (conversion["to"] == "Truck"
                    and world_state.nation_data[country_id].get("research", {}).get("trucks", 0) < 1):
                raise ValueError("Trucks research is required for this conversion.")
            expected, turns = conversion["to"], conversion["turns_left"]
        else:
            expected, turns = "Convoy", 1
        if order.get("to") != expected:
            raise ValueError("Invalid unit conversion.")
        existing = unit.get("order")
        if (expected in ("Truck", "Ship") and isinstance(existing, dict)
                and existing.get("type") == "CONVERT" and existing.get("to") == expected
                and type(existing.get("turns_left")) is int and existing["turns_left"] > 0):
            # A new draft cannot shorten or restart host-owned progress.
            return copy.deepcopy(existing)
        return {"type": "CONVERT", "turns_left": turns, "to": expected}
    raise ValueError("Unknown unit order.")
