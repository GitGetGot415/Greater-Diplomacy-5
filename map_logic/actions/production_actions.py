"""Validate production and own paid queue entries and cancellation effects."""

import copy


from dataclasses import dataclass

import data.constants as c
from data import queries
from data.state_access import world_for, session_for
from map_logic.diplomacy import restrictions


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


def canonical_queue_entry(queue, *, name, cost, order_type="BUILDING", group=None):
    """Record the actual payment for future refunds and preserve queue schemas."""
    refund = {key: cost.get(key, 0) for key in COST_KEYS}
    if queue == "unit_queue":
        return {"unit_type": name, "turns_remaining": max(1, cost.get("production_time", 1)),
                "refund": refund}
    # Every order takes at least the turn it is processed in.
    turns = max(1, cost.get("time", 1))
    return {"order_type": order_type, "item_name": name, "turns_remaining": turns,
            "group": group if group is not None else cost["group"], "refund": refund}


def prepare_production(context, country_id, province, queue, intent, *,
                       unit_library=None, building_library=None):
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
        can_reach = queries.province_can_be_cored(country_id, province, world.id_to_province,
                                                  queries.nation_has_any_core(country_id, world.map_data))
        if order_type == "CORE":
            if country_id in province.get("cores", []):
                raise ValueError("That territory is already cored.")
            if not can_reach:
                raise ValueError("That territory must touch the coast or one of your cores.")
            cost = queries.get_core_cost(country_id, world.map_data, world.scenario_settings, world.nation_data)
            name = "Core Territory"
        else:
            if not any(core != country_id for core in province.get("cores", [])):
                raise ValueError("That territory has no foreign cores to remove.")
            if not queries.province_has_garrison(country_id, province):
                raise ValueError("Removing cores requires your units in that territory.")
            if not can_reach:
                raise ValueError("That territory must touch the coast or one of your cores.")
            cost = queries.get_remove_core_cost(country_id, world.map_data, world.scenario_settings, world.nation_data)
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
        cost = queries.get_building_cost(name, country_id, world.map_data, library, world.nation_data)
        group = cost.get("group", "")
    else:
        raise ValueError("Invalid building order.")
    order = canonical_queue_entry(queue, name=name, cost=cost, order_type=order_type, group=group)
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


def _calculate_draft_budget(country, commands):
    """Calculate affordability and settlement from the same draft entries."""
    available = {key: float(country.get(key.removeprefix("cost_"), 0)) for key in COST_KEYS}
    charged = dict.fromkeys(COST_KEYS, 0.0)
    refunds = dict.fromkeys(COST_KEYS, 0)
    costs = dict.fromkeys(COST_KEYS, 0)
    for command in commands:
        kind = command.get("type")
        if kind == "province_queue":
            refund_entries = (item.get("refund", {}) for item in command.get("cancelled", [])
                              if isinstance(item, dict))
            cost_entries = command.get("new_costs", [])
            check_cost = True
        elif kind == "unit_order":
            refund_entries = (command.get("unit_refund", {}),)
            order = command.get("order") or {}
            check_cost = order.get("type") == "REPAIR"
            cost_entries = (order["realtime_cost"] if check_cost else order.get("realtime_cost", {}),)
        else:
            continue

        for refund in refund_entries:
            for key in COST_KEYS:
                amount = refund.get(key, 0)
                refunds[key] += amount
                # Keep the recorded amount for settlement. Only positive
                # production refunds count toward affordability.
                available[key] += max(0, float(amount)) if kind == "province_queue" else float(amount)
        for cost in cost_entries:
            for key in COST_KEYS:
                amount = cost.get(key, 0)
                costs[key] += amount
                if check_cost:
                    available[key] -= float(amount)
                    charged[key] += float(amount)

    # A stockpile already below zero blocks only drafts that charge it.
    if any(available[key] < 0 and charged[key] > 0 for key in COST_KEYS):
        raise ValueError("These production and repair orders exceed available resources.")
    return available, refunds, costs


def validate_queue_budget(country, commands):
    """Check cumulative production and repair costs without changing stockpiles."""
    return _calculate_draft_budget(country, commands)[0]


def settle_draft_budget(country, commands):
    """Settle the validated combined budget before installing domain changes."""
    _, refunds, costs = _calculate_draft_budget(country, commands)
    queries.refund_resources(country, refunds)
    queries.deduct_resources(country, costs)


def apply_queue_change(context, country_id, command, *, payment_settled=False):
    """Apply a validated paid projection, preserving existing orders and progress."""
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


def reconstruct_queue(context, country_id, province, queue, items):
    """Match paid orders once and rebuild new orders under the active rules."""
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
            continue
        result = prepare_production(context, country_id, province, queue, item)
        canonical.append(result.order)
        new_costs.append(result.cost)
    return {"type": "province_queue", "province_id": province["id"], "queue": queue,
            "items": canonical, "cancelled": remaining, "new_costs": new_costs}
