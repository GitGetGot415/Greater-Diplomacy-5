"""Validate production and own paid queue entries and cancellation effects."""

from dataclasses import dataclass

import data.constants as c
from data import queries
from data.state_access import world_for, session_for
from map_logic.diplomacy import restrictions


@dataclass(frozen=True)
class ProductionPolicy:
    # AI building purchases historically charge no manpower, including factories.
    charge_building_manpower: bool = True
    clamp_administrative_time: bool = False


PLAYER_POLICY = ProductionPolicy()
AI_POLICY = ProductionPolicy(charge_building_manpower=False)
REALTIME_POLICY = ProductionPolicy(clamp_administrative_time=True)
COST_KEYS = tuple(f"cost_{resource}" for resource in c.ECON_RESOURCE_KEYS)


@dataclass(frozen=True)
class ProductionResult:
    queue: str
    order: dict
    cost: dict
    feedback: str
    changed_domains: tuple = ("production", "economy")
    province_id: object = None


def production_permission(context, country_id, province, *, authority="player"):
    if province.get("owner") != country_id:
        return False
    if authority in ("ai", "server", "setup"):
        return True
    session = session_for(context)
    if session.tactical_mode:
        return False
    return (session.player_country == country_id or
            (session.player_country == "Spectator" and c.SPECTATOR_CAN_EDIT_PRODUCTION))


def canonical_queue_entry(queue, *, name, cost, order_type="BUILDING", group=None,
                          clamp_administrative_time=False):
    """Record the actual payment for future refunds and preserve queue schemas."""
    refund = {key: cost.get(key, 0) for key in COST_KEYS}
    if queue == "unit_queue":
        return {"unit_type": name, "turns_remaining": max(1, cost.get("production_time", 1)),
                "refund": refund}
    turns = cost.get("time", 1)
    if order_type == "BUILDING" or clamp_administrative_time:
        turns = max(1, turns)
    return {"order_type": order_type, "item_name": name, "turns_remaining": turns,
            "group": group if group is not None else cost["group"], "refund": refund}


def prepare_production(context, country_id, province, queue, intent, *,
                       policy=PLAYER_POLICY, unit_library=None, building_library=None):
    """Query current legality, cost, and canonical order without changing state."""
    world = world_for(context)
    if province.get("owner") != country_id or country_id not in world.nation_data:
        raise ValueError("Players may only change queues in their own provinces.")
    country = world.nation_data[country_id]
    if not isinstance(intent, dict):
        raise ValueError("Invalid production order.")
    if queue == "unit_queue":
        name = intent.get("unit_type")
        library = queries.get_unit_library(context) if unit_library is None else unit_library
        if not isinstance(name, str) or name not in library:
            raise ValueError("Invalid unit production order.")
        if not queries.has_core(country_id, province):
            raise ValueError("Must core territory before recruiting!")
        stats = library[name]
        requirements = queries.get_unit_metadata(name, library, context=context)["recruitment"]
        if requirements["coastal"] and not province.get("is_coastal", False):
            raise ValueError("Naval units require a coastal province.")
        factory = requirements["industry"]
        if ((factory == "industry" and not queries.has_industry(province)) or
                (factory == "basic_factory" and not queries.has_basic_factory(province))):
            raise ValueError("That province cannot recruit this unit.")
        if not queries.is_unit_unlocked(name, country.get("research", {}), library, context=context):
            raise ValueError("Required unit research is not complete.")
        if not restrictions.can_raise_units(country_id, world.nation_data):
            raise ValueError("That country cannot recruit units under its treaty restrictions.")
        order = canonical_queue_entry(queue, name=name, cost=stats)
        return ProductionResult(queue, order, order["refund"], "recruited", province_id=province.get("id"))
    if queue != "building_queue":
        raise ValueError("Invalid province queue.")
    order_type = intent.get("order_type", "BUILDING")
    if not isinstance(order_type, str):
        raise ValueError("Invalid building order type.")
    if order_type in queries.ADMINISTRATIVE_ACTIONS:
        if not queries.is_administrative_action_enabled(order_type, world.scenario_settings):
            raise ValueError("That administrative action is disabled.")
        if order_type == "CORE":
            if country_id in province.get("cores", []):
                raise ValueError("That territory is already cored.")
            cost = queries.get_core_cost(country_id, world.map_data, world.scenario_settings)
            name = "Core Territory"
        else:
            if not any(core != country_id for core in province.get("cores", [])):
                raise ValueError("That territory has no foreign cores to remove.")
            cost = queries.get_remove_core_cost(country_id, world.map_data, world.scenario_settings)
            name = "Remove Cores"
        group = "administration"
    elif order_type == "BUILDING":
        name = intent.get("item_name")
        library = queries.get_building_library(context) if building_library is None else building_library
        if not isinstance(name, str) or name not in library:
            raise ValueError("Invalid building order.")
        if not queries.has_core(country_id, province):
            raise ValueError("Must core territory before producing!")
        requirement, level = queries.get_building_required_tech(name)
        if requirement and country.get("research", {}).get(requirement, 0) < level:
            raise ValueError("Required building research is not complete.")
        cost = queries.get_building_cost(name, country_id, world.map_data, library)
        if not policy.charge_building_manpower:
            cost = dict(cost, cost_manpower=0)
        group = cost.get("group", "")
    else:
        raise ValueError("Invalid building order.")
    order = canonical_queue_entry(queue, name=name, cost=cost, order_type=order_type, group=group,
                                  clamp_administrative_time=policy.clamp_administrative_time)
    return ProductionResult(queue, order, order["refund"], order_type, province_id=province.get("id"))


def submit_production(context, country_id, province, queue, intent, *, authority="player", **options):
    """Recheck permission and resources before applying one paid order."""
    if not production_permission(context, country_id, province, authority=authority):
        raise ValueError("Production editing is not permitted.")
    result = prepare_production(context, country_id, province, queue, intent, **options)
    country = world_for(context).nation_data[country_id]
    if not queries.can_afford(country, result.cost):
        raise ValueError("Insufficient resources!")
    queries.deduct_resources(country, result.cost)
    province.setdefault(queue, []).append(result.order)
    return result


def cancel_production(context, country_id, province, queue, index, *, authority="player",
                      recorded_refund_only=False):
    if not production_permission(context, country_id, province, authority=authority):
        raise ValueError("Production editing is not permitted.")
    if queue not in ("building_queue", "unit_queue"):
        raise ValueError("Invalid province queue.")
    items = province.get(queue, [])
    if type(index) is not int or not 0 <= index < len(items):
        raise ValueError("The production order no longer exists.")
    world = world_for(context)
    item = items.pop(index)
    if not recorded_refund_only or "refund" in item:
        queries.refund_queue_item(world.nation_data[country_id], item, country_id, world.map_data, context=context)
    return ProductionResult(queue, item, item.get("refund", {}), "cancelled", province_id=province.get("id"))


def validate_queue_budget(country, commands):
    """Check cumulative production and repair costs without changing stockpiles."""
    available = {key: float(country.get(key.removeprefix("cost_"), 0)) for key in COST_KEYS}
    for command in commands:
        if command.get("type") == "province_queue":
            for item in command.get("cancelled", []):
                refund = item.get("refund", {}) if isinstance(item, dict) else {}
                for key in available:
                    available[key] += max(0, float(refund.get(key, 0)))
            for cost in command.get("new_costs", []):
                for key in available:
                    available[key] -= float(cost.get(key, 0))
        elif command.get("type") == "unit_order":
            for key in available:
                available[key] += float(command.get("unit_refund", {}).get(key, 0))
            order = command.get("order")
            if isinstance(order, dict) and order.get("type") == "REPAIR":
                for key in available:
                    available[key] -= float(order["realtime_cost"].get(key, 0))
    if any(value < 0 for value in available.values()):
        raise ValueError("These production and repair orders exceed available resources.")
    return available


def settle_draft_budget(country, commands):
    """Settle the validated combined budget before installing domain changes."""
    validate_queue_budget(country, commands)
    refunds = dict.fromkeys(COST_KEYS, 0)
    costs = dict.fromkeys(COST_KEYS, 0)
    for command in commands:
        if command.get("type") == "province_queue":
            for item in command.get("cancelled", []):
                for key in COST_KEYS:
                    refunds[key] += item.get("refund", {}).get(key, 0)
            for cost in command.get("new_costs", []):
                for key in COST_KEYS:
                    costs[key] += cost.get(key, 0)
        elif command.get("type") == "unit_order":
            order = command.get("order") or {}
            for key in COST_KEYS:
                refunds[key] += command.get("unit_refund", {}).get(key, 0)
                costs[key] += order.get("realtime_cost", {}).get(key, 0)
    queries.refund_resources(country, refunds)
    queries.deduct_resources(country, costs)


def apply_queue_change(context, country_id, command, *, payment_settled=False):
    """Apply a validated paid projection, preserving existing orders and progress."""
    import copy
    world = world_for(context)
    province = queries.province_for_order(context, command["province_id"])
    if province.get("owner") != country_id:
        raise ValueError("Players may only change queues in their own provinces.")
    country = world.nation_data[country_id]
    if not payment_settled:
        for item in command.get("cancelled", []):
            queries.refund_queue_item(country, item, country_id, world.map_data, context=context)
        for cost in command.get("new_costs", []):
            queries.deduct_resources(country, cost)
    province[command["queue"]] = copy.deepcopy(command["items"])


def reconstruct_queue(context, country_id, province, queue, items, *, policy=PLAYER_POLICY):
    """Match paid orders once and rebuild only new intent from active libraries."""
    import copy
    if queue not in ("building_queue", "unit_queue") or not isinstance(items, list):
        raise ValueError("Invalid province queue.")
    if any(not isinstance(item, dict) for item in items):
        raise ValueError("Invalid province queue contents.")
    remaining = [copy.deepcopy(item) for item in province.get(queue, []) if isinstance(item, dict)]
    canonical, new_costs = [], []
    for item in items:
        index = next((i for i, existing in enumerate(remaining) if existing == item), None)
        if index is not None:
            canonical.append(remaining.pop(index))
        else:
            result = prepare_production(context, country_id, province, queue, item, policy=policy)
            canonical.append(result.order)
            new_costs.append(result.cost)
    return {"type": "province_queue", "province_id": province["id"], "queue": queue,
            "items": canonical, "cancelled": remaining, "new_costs": new_costs}
