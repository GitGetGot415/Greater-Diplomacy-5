# --- START OF FILE CHANGES ---
from data.state_access import world_for, session_for
from collections import defaultdict, deque
from itertools import combinations, product
import heapq
from math import ceil, inf
import data.constants as c
from map_logic.ai import ai_tuning
from data import queries
from map_logic.actions import unit_actions
from map_logic.ai import ai_supply, ai_unit_eval, ai_world
from map_logic.diplomacy import deal as deal_mod
from map_logic.system32 import combat_forecast, combat_rules
from map_logic.territory import ownership


def _health_fraction(unit):
    return unit.get("health", 0) / max(1.0, unit.get("max_health", 1))


def _is_wounded(unit):
    """Hurt badly enough to be sent to repair rather than into a fight."""
    return _health_fraction(unit) < ai_tuning.AI_REPAIR_HEALTH_FRACTION


def _is_combat_ship(unit_type, *, context):
    return queries.is_warship(unit_type, context=context)


def _order_move(context, ai_name, prov, unit, path):
    """Issue a MOVE through the shared order owner. False if the rules refuse it.

    Every AI move goes through unit_actions, which checks each step with
    queries.can_unit_move_step. A refusal is an expected planning outcome --
    a pending war target that is not yet enemy land, for example -- so the
    caller tries something else instead of the turn failing.
    """
    try:
        unit_actions.apply_action(context, ai_name, prov, unit,
                                  {"type": "MOVE", "path": list(path)}, authority="ai")
    except ValueError:
        return False
    return True


def _visible_hostiles(context, ai_name, prov):
    """Visible units on `prov` that are at war with `ai_name`."""
    nation_data = world_for(context).nation_data
    return [unit for unit in queries.filter_visible_units(prov.get("units", ()), ai_name,
                                                          prov, nation_data)
            if unit.get("health", 0) > 0
            and queries.are_at_war(ai_name, queries.get_unit_combat_owner(unit), nation_data)]


def _factory_objectives(context, country, visible, provinces_by_owner):
    """Visible completed factories, scored by lost and gained industrial output."""
    nations = world_for(context).nation_data
    own = queries.ProvinceProduction(nations, context)
    foreign = queries.ProvinceProduction({name: {} for name in nations}, context) if visible is not None else own
    scores = {}
    for enemy in queries.get_enemies(country, nations):
        for province in provinces_by_owner.get(enemy, ()):
            tile = province["id"]
            if ((visible is not None and tile not in visible) or queries.is_water_province(province)
                    or not queries.has_basic_factory(province)):
                continue
            buildings = [name for name in province.get("buildings", ()) if own.library.get(name, {}).get("group") == "industry"]
            factory = dict(province, buildings=buildings, building_queue=())
            recipient = ownership.conquest_owner(context, province, queries.get_faction_core_transfer_target(country, province, nations))
            loss = foreign.building_output(factory)
            producer = own if recipient == country else foreign
            gain = producer.building_output(dict(factory, owner=recipient))
            value = sum((loss[key] + gain[key]) * price for key, price in c.DEAL_VALUE_RESOURCE_PRICES.items())
            if value > 0:
                scores[tile] = (value, recipient)
    return scores


def legal_air_candidates(context, unit, base, *, range_cache=None):
    """Only canonical orders are ever offered to heuristic/model consumers."""
    world_state = world_for(context)
    candidates = []
    if not queries.air_unit_can_launch(context, unit, base):
        return candidates
    if queries.air_unit_can_patrol(unit, context=context):
        candidates.append(queries.canonical_air_order(context, unit, base,
            {"type": "AIR_PATROL", "priority": queries.AIR_DEFAULT_PRIORITY}))
    for kind in queries.AIR_TARGET_MISSION_TYPES.values():
        for target_id in sorted(queries.get_air_targets(context, unit, base, kind, cache=range_cache)):
            target = world_state.id_to_province[target_id]
            if kind == "AIR_ATTACK" and not queries.air_target_is_hostile(
                    unit, target, world_state.nation_data, visible_only=True):
                continue
            if kind == "AIR_REPOSITION" and not queries.air_unit_can_land(unit, target, world_state.nation_data):
                continue
            if kind == "AIR_DROP" and not queries.air_drop_target_is_legal(unit, target, world_state.nation_data):
                continue
            candidates.append(queries.canonical_air_order(context, unit, base,
                {"type": kind, "target_id": target_id}))
    return candidates


def _air_base_threats(context, country, visible):
    """Visible ground units threaten every base they can reach this turn.

    Do not read enemy orders. Aircraft die when hostile troops arrive, even
    when friendly defenders survive. Reach is therefore sufficient warning.
    """
    world_state = world_for(context)
    threatened = set()
    for province in world_state.map_data.values():
        if visible is not None and province["id"] not in visible:
            continue
        for unit in queries.filter_visible_units(province.get("units", []), country,
                                                 province, world_state.nation_data):
            if (unit.get("health", 0) <= 0 or queries.is_air_unit(unit, context=context)
                    or not queries.are_at_war(country, queries.get_unit_combat_owner(unit), world_state.nation_data)):
                continue
            reached = {province["id"]}
            frontier = [province]
            for _step in range(queries.unit_movement_speed(unit)):
                next_frontier = []
                for current in frontier:
                    for target_id in current.get("neighbors", []):
                        if target_id in reached:
                            continue
                        target = world_state.id_to_province.get(target_id)
                        if target and queries.can_unit_move_step(unit, current, target, world_state.nation_data, context=context):
                            reached.add(target_id)
                            next_frontier.append(target)
                frontier = next_frontier
                if not frontier:
                    break
            threatened.update(reached)
    return threatened


def _air_exchange_value(context, wings, opponents, *, air_combat=False, target=None):
    """Compare projected equipment losses through the shared combat rules."""
    world_state = world_for(context)
    if not wings:
        return 0.0
    sides = [wings + opponents] if air_combat else [wings, opponents]
    battle = combat_rules.build_battle(sides, world_state.nation_data,
        air_combat=air_combat, convert_aircraft=False,
        air_mission_sides=None if air_combat else {0},
        terrain=target.get("terrain") if target else None,
        tiles=(target,) * len(sides) if target else ())
    opponent_ids = {id(unit) for unit in opponents}

    def fort_bonus(unit):
        return (queries.get_fort_defense_bonus(target, unit, world_state.nation_data, combat_active=True)
                if target and id(unit) in opponent_ids else 0)
    damage = combat_rules.projected_incoming_damage(battle, world_state.nation_data, fort_bonus)
    prices = dict.fromkeys(ai_unit_eval.RESOURCES, 1.0)

    def losses(units):
        return sum(min(unit.get("health", 0), damage.get(id(unit), 0))
                   / max(1, unit.get("max_health", c.DEFAULT_UNIT_HP))
                   * ai_unit_eval.unit_pain(queries.air_unit_stats(unit, context=context), prices) for unit in units)
    value = losses(opponents) - losses(wings)
    if target:
        hits = sum(queries.air_unit_can_damage_forts(unit, context=context) and queries.are_at_war(
            queries.get_unit_combat_owner(unit), target.get("owner"), world_state.nation_data) for unit in wings)
        level = queries.get_fort_level(target)
        library = queries.get_building_library(context)
        for lost_level in range(level, max(0, level - hits), -1):
            stats = queries.get_building_cost(f"Fort Lvl {lost_level}", target.get("owner"),
                                             world_state.map_data, library, world_state.nation_data)
            value += sum(stats.get(f"cost_{resource}", 0) for resource in ai_unit_eval.RESOURCES)
    return value


def _air_patrol_threats(context, country, visible, *, range_cache=None):
    """Possible strikes on our land or troops, without reading enemy orders."""
    world_state = world_for(context)
    protected = {province["id"] for province in world_state.map_data.values()
                 if province.get("owner") == country or any(
                     queries.get_unit_combat_owner(unit) == country and unit.get("health", 0) > 0
                     for unit in province.get("units", []))}
    threats = {}
    for base in world_state.map_data.values():
        if visible is not None and base["id"] not in visible:
            continue
        for unit in queries.filter_visible_units(base.get("units", []), country, base, world_state.nation_data):
            if (unit.get("health", 0) <= 0 or not queries.is_air_unit(unit, context=context)
                    or queries.air_unit_stats(unit, context=context).get("air_interception_immune")
                    or not queries.are_at_war(country, queries.get_unit_combat_owner(unit), world_state.nation_data)
                    or not queries.air_unit_can_launch(context, unit, base)):
                continue
            for target_id in protected.intersection(queries.get_air_targets(context, unit, base, "AIR_ATTACK", cache=range_cache)):
                threats.setdefault(target_id, []).append(unit)
    return threats


def _after_interception(context, wings, threats):
    """Copies of `threats` with the damage `wings` would deal them when intercepting."""
    world_state = world_for(context)
    if not wings:
        return list(threats)
    battle = combat_rules.build_battle([list(wings) + list(threats)], world_state.nation_data,
                                       air_combat=True, convert_aircraft=False)
    damage = combat_rules.projected_incoming_damage(battle, world_state.nation_data)
    survivors = []
    for unit in threats:
        health = unit.get("health", 0) - damage.get(id(unit), 0)
        if health > 0:
            survivors.append(dict(unit, health=health))
    return survivors


def _patrol_protection_value(context, country, wings, threats, tile):
    """What a patrol over `tile` is worth: the air battle plus the strike it blunts.

    Interception happens before a strike, and only the surviving attackers
    strike. So a patrol earns the
    equipment it trades in the air *and* the damage the enemy would otherwise
    have done to the garrison and forts below -- valued as the enemy's own
    strike, unopposed, minus the same strike flown by the survivors. Valuing
    the air battle alone is why AI aircraft almost never chose to defend.
    """
    world_state = world_for(context)
    if not wings:
        return 0.0
    friendly = queries.get_all_friendly_nations(country, world_state.nation_data)
    garrison = [unit for unit in tile.get("units", ())
                if unit.get("health", 0) > 0
                and queries.get_unit_combat_owner(unit) in friendly]
    value = _air_exchange_value(context, wings, threats, air_combat=True)
    if garrison or tile.get("owner") == country:
        unopposed = _air_exchange_value(context, threats, garrison, target=tile)
        blunted = _air_exchange_value(context, _after_interception(context, wings, threats),
                                      garrison, target=tile)
        value += max(0.0, unopposed - blunted)
    return value


def _aircraft_repair_order(context, country, unit, base, threatened, candidates):
    """A repair, or a flight to a safe factory base, for a wounded aircraft.

    The same rule the ground units follow: a unit below
    AI_REPAIR_ON_SITE_FRACTION standing on its own factory repairs. An aircraft
    elsewhere flies to the nearest factory base of ours that no visible enemy
    can reach this turn. Returns the order, or None to fly missions instead.
    """
    world_state = world_for(context)
    if _health_fraction(unit) >= ai_tuning.AI_REPAIR_ON_SITE_FRACTION:
        return None
    if (base.get("owner") == country and base["id"] not in threatened
            and not unit_actions.repair_site_error(context, country, base)):
        repair = {"type": "REPAIR"}
        result = unit_actions.prepare_action(context, country, base, unit, repair)
        return repair if queries.can_afford(world_state.nation_data[country], result.cost) else None
    factories = [order for order in candidates
                 if order["type"] == "AIR_REPOSITION" and order["target_id"] not in threatened
                 and world_state.id_to_province[order["target_id"]].get("owner") == country
                 and not unit_actions.repair_site_error(context, country, world_state.id_to_province[order["target_id"]])]
    if not factories:
        return None
    return min(factories, key=lambda order: (
        queries.air_distance_squared(context, base, order["target_id"]), order["target_id"]))


def _assign_air_orders(context, country, units_info, *, factories=None, known_supply=None, actual_supply=None):
    """Reusable aircraft fly; one-use weapons relocate through legal land paths.

    Three passes over the aircraft that are free for a mission:

    1. Housekeeping: leave threatened bases, carry cargo, repair the wounded,
       upgrade the rest at a factory.
    2. Patrols, strongest air-to-air first: an aircraft patrols when the
       protection it adds over a threatened tile (_patrol_protection_value)
       beats what it adds to the strike group it would otherwise join.
    3. Strikes, planned target-first in groups: for every reachable target the
       best group of in-range aircraft is found by projected exchange value,
       the best group overall flies, and the rest are planned again. A strike
       that would cost more than it destroys is never flown, so a warship that
       out-trades its attackers is left alone while a convoy is not.

    Aircraft left over move to a base nearer the enemy, or patrol.
    """
    world_state = world_for(context)
    all_units_info = units_info
    units_info = [(unit, base) for unit, base in units_info
                  if queries.is_air_unit(unit, context=context) or queries.is_air_transport(unit, context=context)]
    if not units_info:
        return
    world = ai_world.for_screen(context)
    # The turn's cached fog view. None when fog is off, where every use below
    # already skips its fog filter.
    visible = world.visible_provinces(country)
    enemies = [province for province in world_state.map_data.values()
               if (visible is None or province["id"] in visible)
               and queries.air_target_is_hostile({"owner": country}, province,
                   world_state.nation_data, visible_only=True)]
    threatened = _air_base_threats(context, country, visible)
    logistics = None
    cargo_changed = False
    unit_library = queries.get_unit_library(context)
    tech_tree = queries.get_tech_tree(context)
    range_cache = {}
    patrol_threats = _air_patrol_threats(context, country, visible, range_cache=range_cache)
    patrol_cover = {}
    strike_cover = {}
    protection_scores = {}
    strike_scores = {}
    for unit, base in units_info:
        if not queries.is_tactical_player_unit(context, unit):
            continue
        order = unit.get("order") or {}
        if order.get("type") == "AIR_PATROL":
            for target_id in queries.get_air_targets(context, unit, base, "AIR_PATROL", cache=range_cache):
                patrol_cover.setdefault(target_id, []).append(unit)
        elif order.get("type") == "AIR_ATTACK":
            strike_cover.setdefault(order["target_id"], []).append(unit)

    enemy_ids = {province["id"] for province in enemies}
    target_values = {province["id"]: sum(queries.calculate_unit_strength(unit) for unit in
                   queries.filter_visible_units(province.get("units", []), country,
                                                province, world_state.nation_data)
                   if queries.are_at_war(country, queries.get_unit_combat_owner(unit), world_state.nation_data))
                   for province in enemies}

    def value(province):
        return target_values[province["id"]]

    def wing_key(wings):
        return tuple(sorted((wing["type"], combat_rules.single_attacker_signature(wing))
                            for wing in wings))

    def strike_value(wings, target_id):
        """Projected exchange of `wings` plus committed cover against a target."""
        target = world_state.id_to_province[target_id]
        wings = strike_cover.get(target_id, []) + list(wings)
        key = (wing_key(wings), target_id)
        if key not in strike_scores:
            opponents = _visible_hostiles(context, country, target)
            strike_scores[key] = _air_exchange_value(context, wings, opponents, target=target)
        return strike_scores[key]

    def protection(wings, target_id):
        key = (tuple(id(unit) for unit in wings), target_id)
        if key not in protection_scores:
            protection_scores[key] = _patrol_protection_value(
                context, country, wings, patrol_threats[target_id],
                world_state.id_to_province[target_id])
        return protection_scores[key]

    def strength(unit):
        return (unit.get("attack", 0)
                * combat_rules.effective_damage_multiplier(unit, world_state.nation_data))

    # Plan stronger interceptors first. Unit names do not define the preference.
    units_info.sort(key=lambda item: item[0].get("attack", 0)
                    * combat_rules.effective_damage_multiplier(item[0], world_state.nation_data)
                    * (queries.unit_target_damage_multiplier(item[0], item[0], air_to_air=True, context=context) - 1),
                    reverse=True)

    # --- 1. Housekeeping ----------------------------------------------------
    pool = []  # (unit, base, candidates) free for a mission
    for unit, base in units_info:
        if queries.is_tactical_player_unit(context, unit):
            continue
        if queries.is_air_transport(unit, context=context):
            if not queries.is_nation_in_combat_here(country, base, world_state.nation_data):
                original = {"type": unit["original_type"]}
                radius = queries.air_order_radius(original, "AIR_ATTACK", context=context)
                target = max(enemies, key=lambda p: (value(p), -p["id"])) if enemies else None
                path = None
                if target and queries.air_distance_squared(context, base, target["id"]) > radius * radius:
                    destinations = [p for p in world_state.map_data.values()
                        if p.get("owner") == country and not queries.is_water_province(p)
                        and queries.air_distance_squared(context, p, target["id"]) <= radius * radius]
                    for destination in sorted(destinations, key=lambda p: p["id"]):
                        path = queries.find_unit_move_path(unit, base, destination["id"],
                            world_state.id_to_province, world_state.nation_data, context=context)
                        if path:
                            break
                unit_actions.apply_action(context, country, base, unit, {"type": "MOVE", "path": path} if path else
                    {"type": "MOVE", "path": []} if queries.is_water_province(base) else
                    queries.air_conversion_order(unit, context=context), authority="ai")
            continue
        if (not queries.is_air_unit(unit, context=context) or queries.is_water_province(base)
                or queries.is_nation_in_combat_here(country, base, world_state.nation_data)):
            continue
        candidates = legal_air_candidates(context, unit, base, range_cache=range_cache)
        safe_repositions = [order for order in candidates if order["type"] == "AIR_REPOSITION"
                            and order["target_id"] != base["id"] and order["target_id"] not in threatened]
        if base["id"] in threatened and safe_repositions:
            unit_actions.apply_action(context, country, base, unit, min(safe_repositions, key=lambda order: (
                queries.air_distance_squared(context, base, order["target_id"]), order["target_id"])), authority="ai")
            continue
        if queries.air_unit_can_transport(unit, context=context):
            if logistics is None:
                if factories is None:
                    factories = _factory_objectives(context, country, visible, world.provs_by_owner)
                if known_supply is None:
                    known_supply = queries.SupplySnapshot(context, visible_to=country, visible_provinces=visible)
                transport_ranges = [(base, queries.air_order_radius(plane, "AIR_DROP", context=context) ** 2)
                                    for plane, base in units_info if queries.air_unit_can_transport(plane, context=context)]
                reachable_factories = {tile: score for tile, score in factories.items()
                                       if any(queries.air_distance_squared(context, base, tile) <= radius
                                              for base, radius in transport_ranges)}
                logistics = _air_transport_logistics(context, country, reachable_factories, known_supply, actual_supply)
            if _assign_air_transport(context, country, unit, base, safe_repositions, all_units_info, logistics):
                cargo_changed = True
            continue
        repair = _aircraft_repair_order(context, country, unit, base, threatened, candidates)
        if repair:
            unit_actions.apply_action(context, country, base, unit, repair, authority="ai")
            continue
        # A wounded aircraft is not upgraded: an upgrade keeps the health
        # percentage, so it would spend the turn and still be wounded.
        if (base["id"] not in threatened and queries.has_industry(base)
                and _health_fraction(unit) >= ai_tuning.AI_REPAIR_ON_SITE_FRACTION):
            target = world.upgrade_target(country, unit["type"], unit_library, tech_tree)
            if target:
                unit_actions.apply_action(context, country, base, unit, {"type": "UPGRADE", "target_type": target}, authority="ai")
                continue
        pool.append((unit, base, candidates))

    def reach(unit_candidates):
        return {order["target_id"]: order for order in unit_candidates
                if order["type"] == "AIR_ATTACK" and order["target_id"] in enemy_ids}

    reaches = {id(unit): reach(candidates) for unit, _base, candidates in pool}

    # --- 2. Patrols ---------------------------------------------------------
    striking = list(pool)
    if patrol_threats:
        for unit, base, candidates in pool:
            patrol = next((order for order in candidates if order["type"] == "AIR_PATROL"), None)
            if not patrol:
                continue
            coverage = queries.get_air_targets(context, unit, base, "AIR_PATROL", cache=range_cache)
            defense_value = max((protection(patrol_cover.get(target_id, []) + [unit], target_id)
                                 - protection(patrol_cover.get(target_id, []), target_id)
                                 for target_id in coverage.intersection(patrol_threats)), default=0.0)
            if defense_value <= 0:
                continue
            # What this aircraft adds to the full group that could strike each
            # of its targets. A lone plane can be worthless against a target a
            # group would break, so its solo value would undersell the strike.
            attack_value = 0.0
            for target_id in reaches[id(unit)]:
                group = [other for other, _b, _c in striking if target_id in reaches[id(other)]]
                without = [other for other in group if other is not unit]
                attack_value = max(attack_value, strike_value(group, target_id)
                                   - strike_value(without, target_id))
            if defense_value > attack_value:
                unit_actions.apply_action(context, country, base, unit, patrol, authority="ai")
                for target_id in coverage:
                    patrol_cover.setdefault(target_id, []).append(unit)
                striking = [entry for entry in striking if entry[0] is not unit]

    # --- 3. Grouped strikes -------------------------------------------------
    def best_group(target_id, available):
        """The most valuable strongest-first group of `available` for a target."""
        ranked = sorted((entry for entry in available if target_id in reaches[id(entry[0])]),
                        key=lambda entry: strength(entry[0]), reverse=True)
        base_value = strike_value([], target_id)
        best, best_gain = [], 0.0
        for size in range(1, len(ranked) + 1):
            gain = strike_value([entry[0] for entry in ranked[:size]], target_id) - base_value
            if gain > best_gain:
                best, best_gain = ranked[:size], gain
        return best, best_gain

    while striking:
        choices = []
        for target_id in sorted({t for entry in striking for t in reaches[id(entry[0])]}):
            group, gain = best_group(target_id, striking)
            if group:
                choices.append((gain, gain / len(group), -target_id, target_id, group))
        if not choices:
            break
        _gain, _per_plane, _tie, target_id, group = max(choices, key=lambda choice: choice[:3])
        for unit, base, _candidates in group:
            unit_actions.apply_action(context, country, base, unit,
                                      reaches[id(unit)][target_id], authority="ai")
            strike_cover.setdefault(target_id, []).append(unit)
        flown = {id(entry[0]) for entry in group}
        striking = [entry for entry in striking if id(entry[0]) not in flown]

    # --- 4. Leftovers: move nearer the enemy, or patrol ---------------------
    for unit, base, candidates in striking:
        # Rebase on friendly land nearer a known enemy; no hidden target stacks
        # influence the choice. One-use weapons travel at their land speed.
        if enemies:
            target = max(enemies, key=lambda p: (value(p), -p["id"]))
            radius = queries.air_order_radius(unit, "AIR_ATTACK", context=context)
            friendly = [p for p in world_state.map_data.values()
                        if not queries.is_water_province(p) and p.get("owner") == country
                        and p["id"] != base["id"] and p["id"] not in threatened]
            if queries.air_unit_stats(unit, context=context).get("air_consumable"):
                destinations = [p for p in friendly if queries.air_distance_squared(
                    context, p, target["id"]) <= radius * radius]
                relocation = None
                for destination in sorted(destinations, key=lambda p: p["id"]):
                    path = queries.find_unit_move_path(unit, base,
                        destination["id"], world_state.id_to_province, world_state.nation_data, context=context)
                    if path:
                        relocation = {"type": "MOVE", "path": path}
                        break
                if relocation is None and base.get("is_coastal", False):
                    transport = dict(unit)
                    queries.load_transport(transport, "Convoy", context=context)
                    if any(queries.find_unit_move_path(transport, base, destination["id"],
                            world_state.id_to_province, world_state.nation_data, context=context) for destination in destinations):
                        relocation = queries.canonical_unit_order(context, country, base, unit,
                                                                 queries.air_conversion_order(unit, context=context))
                if relocation:
                    unit_actions.apply_action(context, country, base, unit, relocation, authority="ai")
            elif not reaches[id(unit)]:
                # Only an aircraft with nothing in range moves up. One that has
                # targets but no worthwhile strike stays to patrol below.
                reachable = {order["target_id"]: order for order in candidates
                             if order["type"] == "AIR_REPOSITION"}
                choices = [p for p in friendly if p["id"] in reachable]
                if choices:
                    destination = min(choices, key=lambda p: (
                        queries.air_distance_squared(context, p, target["id"]), p["id"]))
                    if queries.air_distance_squared(context, destination, target["id"]) < queries.air_distance_squared(
                            context, base, target["id"]):
                        unit_actions.apply_action(context, country, base, unit, reachable[destination["id"]], authority="ai")
                        continue
        if (unit.get("order") or {}).get("type") == "CONVERT":
            continue
        patrol = next((order for order in candidates if order["type"] == "AIR_PATROL"), None)
        if patrol:
            unit_actions.apply_action(context, country, base, unit, patrol, authority="ai")
            for target_id in queries.get_air_targets(context, unit, base, "AIR_PATROL", cache=range_cache):
                patrol_cover.setdefault(target_id, []).append(unit)
    return cargo_changed


def _safe_raid_targets(context, country, factories, known):
    if not factories:
        return {}
    provinces = known.provinces
    enemies = set(queries.get_enemies(country, known.nations))
    targets = {tile: value for tile, value in factories.items() if not known.occupants.get(tile, set()) & enemies}
    turns = 1 + queries.get_conversion_turns("AIR_DROP_RECOVERY", world_for(context).scenario_settings)
    land = provinces.keys() - known.water

    def threaten(mover, origin, budget, stops=frozenset()):
        reach = _operational_paths(context, mover, origin, provinces, budget, stops)
        for target in tuple(targets):
            if target in reach:
                targets.pop(target)
                continue
            # Another enemy may only be able to enter after ownership changes.
            recipient = targets[target][1]
            captured = dict(provinces[target], owner=recipient, _turn_start_owner=recipient)
            if any(near in reach and near not in stops and len(reach[near]) < budget
                   and queries.can_unit_move_step(mover, provinces[near], captured, known.nations, context=context)
                   for near in captured.get("neighbors", ())):
                targets.pop(target)
        return reach

    for tile, units in known.visible_units.items():
        base = provinces[tile]
        for unit in units:
            if not targets:
                return targets
            if queries.get_unit_combat_owner(unit) not in enemies:
                continue
            if queries.is_air_unit(unit, context=context):
                if (queries.air_unit_can_patrol(unit, context=context)
                        and queries.air_unit_can_launch(context, unit, dict(base, units=units))):
                    for target in tuple(targets):
                        if queries.air_target_in_range(context, unit, base, "AIR_PATROL", target):
                            targets.pop(target)
                continue
            # Use a visible division's full movement allowance. Current enemy
            # orders and supply shortfalls cannot be relied on through recovery.
            ground = dict(unit, order=None)
            if unit.get("type", "").startswith("Convoy"):
                queries.revert_transport(ground, context=context)
                if queries.unit_display_domain(ground, context=context) != "LAND":
                    continue
                sailing = queries.unit_movement_speed(unit, supply={})
                if sailing <= 0:
                    continue
                shores = threaten(dict(unit, order=None), base, sailing * turns, land)
                march = queries.unit_movement_speed(ground, supply={})
                for shore in shores.keys() & land:
                    if not targets:
                        break
                    if shores[shore]:
                        # Landing unpacks the division during movement. Allow
                        # the whole landing turn for its march in the forecast.
                        remaining = turns - (len(shores[shore]) - 1) // sailing
                        threaten(ground, provinces[shore], march * remaining)
            elif queries.unit_display_domain(ground, context=context) == "LAND":
                threaten(ground, base, queries.unit_movement_speed(ground, supply={}) * turns)
    return targets


def _air_transport_logistics(context, country, factories, known, actual_supply):
    """Share a country's raid candidates and friendly land routes across its transports."""
    supply = ai_supply.SupplyPlanner(actual_supply if actual_supply is not None else known, known, country)
    provinces = known.provinces
    allies = queries.get_all_friendly_nations(country, known.nations)
    visible = known.visible_provinces
    walkable = {tile: provinces[tile] for tile in known.for_country(country).province_area.keys() - known.water}
    guards = set(supply.critical)
    front = set()
    for tile, province in walkable.items():
        if province["owner"] not in allies:
            continue
        neighbors = [provinces[near] for near in province.get("neighbors", ()) if near in provinces and near not in known.water]
        if any(neighbor["owner"] in known.nations and neighbor["owner"] not in allies for neighbor in neighbors):
            guards.add(tile)
        if not any((visible is None or neighbor["id"] in visible)
                   and (neighbor["owner"] in supply.enemies or known.occupants.get(neighbor["id"], set()) & supply.enemies)
                   for neighbor in neighbors):
            continue
        garrison = sum(len(known.land_units.get(ally, {}).get(tile, ())) for ally in allies)
        capacity = combat_rules.nation_front_capacity(country, dict(province, units=known.visible_units.get(tile, ())), known.nations)
        if garrison < max(1, capacity):
            front.add(tile)
    return known, _safe_raid_targets(context, country, factories, known), walkable, front, guards, {}


def _air_ferry_order(context, cargo, base, repositions, known, walkable, front):
    if not front or not repositions:
        return None
    speed = min(queries.unit_movement_speed(unit, supply=known) for unit in cargo)
    if speed <= 0:
        return None
    # Eligible ground cargo shares the same land entry rules. Use the whole
    # group's slowest movement allowance when comparing walking times.
    if base["id"] in front:
        return None
    walker = cargo[0]
    paths = (queries.find_unit_move_paths_to_destinations(walker, base, front, walkable, known.nations, context=context)
             if base["id"] in walkable else {})
    on_foot = {target: ceil(len(path) / speed) for target, path in paths.items()}
    current_best = min(on_foot.values(), default=inf)
    if current_best <= 1:
        return None

    # One reverse search gives each landing point its closest reachable front.
    incoming = defaultdict(list)
    for tile, province in walkable.items():
        for neighbor in province.get("neighbors", ()):
            if neighbor in walkable:
                incoming[neighbor].append(tile)
    nearest = {tile: (tile, 0) for tile in front}
    pending = deque(sorted(front))
    landings = {order["target_id"] for order in repositions} & walkable.keys()
    unseen = landings - nearest.keys()
    while pending and unseen:
        tile = pending.popleft()
        front_tile, distance = nearest[tile]
        if 1 + ceil((distance + 1) / speed) >= current_best:
            continue
        for earlier in incoming[tile]:
            if earlier in nearest or not queries.can_unit_move_step(walker, walkable[earlier], walkable[tile], known.nations, context=context):
                continue
            nearest[earlier] = front_tile, distance + 1
            unseen.discard(earlier)
            pending.append(earlier)

    options = []
    for order in repositions:
        landing_id = order["target_id"]
        if landing_id in nearest:
            target, distance = nearest[landing_id]
            total = 1 + ceil(distance / speed)
            options.append((total - on_foot.get(target, inf), total, landing_id, order))
    return min(options)[-1] if options else None


def _assign_air_transport(context, country, plane, base, repositions, units_info, logistics):
    """Commit a safe raid or a useful ferry flight, and release idle cargo."""
    known, raid_targets, walkable, front, guards, raids = logistics
    cargo = plane.get("air_cargo", [])
    selected = cargo
    if not cargo:
        ground = [unit for unit in base.get("units", ()) if queries.air_cargo_is_eligible(plane, unit, context=context)]
        limit = queries.air_transport_capacity(plane, context=context)
        if base["id"] in guards:
            limit = min(limit, max(0, len(ground) - 1))
        selected = sorted((unit for unit in ground if not queries.is_tactical_player_unit(context, unit)
                           and not queries.unit_has_active_order(unit)),
                          key=queries.calculate_unit_strength, reverse=True)[:limit]
    if not selected:
        return False

    loaded = dict(plane, air_cargo=selected)
    order = None
    raid = sorted(raid_targets, key=lambda tile: (-raid_targets[tile][0],
                  queries.air_distance_squared(context, base, tile), tile))
    for tile in raid:
        target = known.provinces[tile]
        if (not queries.air_drop_target_is_legal(loaded, target, known.nations)
                or not queries.air_target_in_range(context, loaded, base, "AIR_DROP", tile)):
            continue
        recipient = raid_targets[tile][1]
        captures = {target_id: owner for target_id, (owner, _) in raids.items()}
        captures[tile] = recipient
        arrivals = [(target_id, unit) for target_id, (_, units) in raids.items() for unit in units]
        arrivals.extend((tile, unit) for unit in selected)
        statuses = known.land_supply_after_capture(country, captures, arrivals)
        if all(status.readiness >= 1 for status in statuses):
            order = queries.canonical_air_order(context, loaded, base, {"type": "AIR_DROP", "target_id": tile})
            break
    if order is None:
        order = _air_ferry_order(context, selected, base, repositions, known, walkable, front)
    if order is None:
        if cargo:
            queries.set_air_cargo(context, country, plane, base, [])
            units_info.extend((unit, base) for unit in cargo)
        return bool(cargo)

    if not cargo:
        queries.ensure_unit_ids(world_for(context).map_data)
        queries.set_air_cargo(context, country, plane, base, [unit["unit_id"] for unit in selected])
    unit_actions.apply_action(context, country, base, plane, order, authority="ai")
    if order["type"] == "AIR_DROP":
        tile = order["target_id"]
        raids[tile] = raid_targets.pop(tile)[1], selected
    return not cargo


def build_neighbor_index(id_to_province):
    """Maps each tile to its neighbours that actually exist on the map.

    Dropping the dangling ids up front is what lets the pathfinder walk an edge
    without looking the destination province up just to confirm it is real.
    """
    return {
        p_id: [n_id for n_id in prov.get("neighbors", ()) if n_id in id_to_province]
        for p_id, prov in id_to_province.items()
    }

def _tile_depth(capacity, tile):
    """How many units `tile` can actually use: a front rank, and its relief.

    Under the lane model a tile's front slots depend on how many ways the fight
    there splits, so this is looked up per tile rather than read off a single
    constant -- `capacity` holds combat_rules.nation_front_capacity's answer for
    the nation doing the planning. A tile nobody measured (a quiet border, an
    empty target) falls back to a typical one-enemy lane, which is the fight
    that would open there if one started.

    The relief rank is counted because a body behind the front is not wasted the
    way it would be if it were surplus: it rotates in as the units ahead of it
    die. Bodies past that are the wasted ones, and under lanes they are wasted
    completely -- they absorb nothing at all while they wait.
    """
    slots = capacity.get(tile) if capacity else None
    if not slots:
        slots = c.LANE_SLOTS_TYPICAL
    return max(1.0, slots * c.AI_RESERVE_DEPTH)


def _tile_pressure(assignments, stacks, tile, capacity=None, factory_bonus=0):
    """How reluctant we are to send one more unit to `tile`.

    A tile holding a full front rank and a full relief rank has nothing to gain
    from the next body, however much the weights want it there, so it sorts
    behind every tile with room and the existing weighted count decides among
    the rest exactly as before.

    This is the only thing in this file that reads combat width. Everything
    else the AI does already scaled with it -- what to buy, what a unit is
    worth, how strong a border is -- while movement spread units evenly across
    targets and never asked how many could fight once they arrived. Lower the
    width and it kept piling five onto a tile where three did nothing; raise it
    and it kept trickling one at a time and never massed anywhere.

    `stacks` is a true unit count, kept apart from `assignments` because that
    one carries preference weights (a battle pulls at -20, a quiet border pushes
    at +50) and so cannot answer "is this tile full?" on its own.
    """
    return (1 if stacks.get(tile, 0) >= _tile_depth(capacity, tile) else 0,
            assignments.get(tile, 0) - factory_bonus)


# Bound retained candidate paths per nation. The cache is discarded before
# another nation plans (and always before units move or diplomacy resolves).
_PATH_SEARCH_CACHE_LIMIT = 128


def _search_target_paths(start_id, target_ids, allowed_prov_ids, id_to_province,
                         is_convoy, is_ship, moving_nation, nation_data,
                         unit_speed, water_ids, neighbor_ids):
    """Discover candidate paths without consulting changing assignments."""
    # Partial paths are cons cells -- (tile_id, cell_it_came_from) -- rather than
    # lists. Extending one is a single tuple instead of copying the whole path,
    # and branches share their common prefix, which matters because this search
    # queues hundreds of thousands of candidates per turn.
    queue = [(0.0, 0, start_id, (start_id, None))]
    visited = {start_id: 0.0}
    valid_paths = []
    found_cost = -1.0
    counter = 1

    # Costs and the depth limit only depend on the unit, so resolve them once.
    speed = max(1.0, float(unit_speed))
    land_step = 1.0 if is_ship else 1.0 / speed
    sea_step = 1.0 * ai_tuning.AI_SEA_PATH_PENALTY_MULTIPLIER
    # DEPTH OF 10 SO AI CAN SEE FAR (Scaled by speed)
    depth_slack = 10.0 / speed

    # If already on a target, staying is evaluated as a valid option
    if start_id in target_ids:
        valid_paths.append((0.0, (start_id, None)))
        found_cost = 0.0

    while queue:
        current_cost, _, curr, path = heapq.heappop(queue)

        # Allow search a few tiles deeper than the first found target
        # so it can accurately discover empty borders further down the line.
        if found_cost != -1.0 and current_cost > found_cost + depth_slack:
            break

        neighbors = neighbor_ids.get(curr)
        if not neighbors: continue

        curr_is_water = curr in water_ids

        for n_id in neighbors:
            # --- NEW CONVOY AND NAVAL BFS RULE ---
            dest_is_water = n_id in water_ids

            if is_convoy or is_ship:
                if not curr_is_water and not dest_is_water:
                    continue # Convoys and Ships on land cannot move to another land tile

                if not dest_is_water:
                    n_prov = id_to_province[n_id]

                    if is_ship:
                        # Ships can only enter friendly coastal tiles
                        if not queries.can_ships_enter(moving_nation, n_prov, nation_data):
                            continue

                    if is_convoy:
                        # Convoys landing must obey land border rules
                        if not queries.can_land_units_enter(moving_nation, n_prov, nation_data):
                            continue

            # --- NEW: Cost Calculation for Dijkstra ---
            # Land unit over water (Convoy) pays the sea penalty; everything else
            # pays its own per-tile rate.
            step_cost = sea_step if (dest_is_water and not is_ship) else land_step

            new_cost = current_cost + step_cost

            # --- BLOCK SUICIDE PATHS ---

            if n_id in target_ids:
                valid_paths.append((new_cost, (n_id, path)))
                if found_cost == -1.0:
                    found_cost = new_cost

            if n_id in allowed_prov_ids and (n_id not in visited or new_cost < visited[n_id]):
                visited[n_id] = new_cost
                heapq.heappush(queue, (new_cost, counter, n_id, (n_id, path)))
                counter += 1

    return tuple(valid_paths)


def _bfs_nearest_target(start_id, target_ids, allowed_prov_ids, id_to_province, target_assignments, is_convoy=False, is_ship=False, moving_nation=None, nation_data=None, unit_speed=1.0, water_ids=None, neighbor_ids=None, target_stacks=None, target_capacity=None, path_cache=None, factory_bonuses=None):
    """Finds shortest path using Dijkstra. Returns the path to the target with the least units assigned."""
    if target_stacks is None:
        target_stacks = {}
    if target_capacity is None:
        target_capacity = {}
    if water_ids is None:
        water_ids = {p_id for p_id, p in id_to_province.items() if queries.is_water_province(p)}
    if neighbor_ids is None:
        neighbor_ids = build_neighbor_index(id_to_province)

    # This cache is scoped to one nation's order pass, where graph, entry
    # permissions and waters are fixed. The complete target set matters: it
    # determines both which paths exist and where the depth cutoff starts.
    key = (start_id, frozenset(target_ids), is_convoy, is_ship,
           moving_nation, max(1.0, float(unit_speed)))
    valid_paths = path_cache.get(key) if path_cache is not None else None
    if valid_paths is None:
        valid_paths = _search_target_paths(
            start_id, target_ids, allowed_prov_ids, id_to_province,
            is_convoy, is_ship, moving_nation, nation_data,
            unit_speed, water_ids, neighbor_ids)
        if path_cache is not None:
            if len(path_cache) >= _PATH_SEARCH_CACHE_LIMIT:
                path_cache.clear()
            path_cache[key] = valid_paths

    # Pick the path pointing to the target with the LEAST assignments, tie-breaking by cost.
    if valid_paths:
        # A cell's head is the tile the path ends on.
        bonuses = factory_bonuses or {}
        best_cell = min(valid_paths,
                        key=lambda p: _tile_pressure(target_assignments, target_stacks, p[1][0],
                                                     target_capacity, bonuses.get(p[1][0], 0)) + (p[0],))[1]

        # If the best path is just staying where we are, return an empty array so we don't move
        if best_cell[0] == start_id:
            return []

        # Unwind the cons chain, which runs destination-first.
        best_path = []
        while best_cell is not None:
            best_path.append(best_cell[0])
            best_cell = best_cell[1]
        best_path.reverse()

        return best_path[1:]

    return []

def process_ai_unit_orders(context, *, countries=None):
    """Generates movement orders for AI-controlled units to balance borders, attack, or escort."""
    # Order generation only reads the diplomatic picture -- it writes unit orders
    # and nothing else -- so faction and alliance membership can be resolved once
    # for the whole pass instead of once per pathfinding edge.
    with queries.diplomacy_snapshot():
        _generate_unit_orders(context, countries=countries)


# ============================================================================ #
#                   _generate_unit_orders PHASE HELPERS                        #
# ============================================================================ #
# One nation's order pass runs a fixed pipeline: figure out who it's fighting
# and where its borders/targets/dangers are, tally how many units are already
# assigned to each one, then walk its units assigning orders against those
# tallies. Each phase reads/writes a shared `ctx` dict rather than a long
# parameter list, since the phases were originally one function's locals and
# the next phase often needs several of the previous one's results at once.

def _build_shared_pathing_caches(context):
    """Water-tile lookup and neighbour index: identical for every nation this
    pass, so built once rather than per-nation."""
    world = ai_world.for_screen(context)
    # AIWorld builds these structural indexes once for the whole AI phase.
    # Keep returning the same three values so the pathing helpers remain
    # usable by isolated tests and older callers.
    allowed_prov_ids_cache = set(world.water_ids)
    water_ids = world.water_ids
    neighbor_ids = world.neighbor_ids
    return allowed_prov_ids_cache, water_ids, neighbor_ids


def _can_replan_unit(context, unit):
    order = unit.get("order")
    return (not queries.is_tactical_player_unit(context, unit)
            and not (isinstance(order, dict) and order.get("type") in c.MULTI_TURN_ORDER_TYPES))


def _reset_orders_and_collect_units(context, ai_nations):
    """Clears every AI unit's movement order (so it rethinks its strategy every
    turn) and buckets units/provinces by owning nation.

    Standing multi-turn commitments survive. This pass runs a few lines after
    ai_construction in prepare_turn, and clearing unconditionally destroyed the
    DISBAND orders construction had just issued -- DISBAND is only executed
    later, in movement_processor, by which point the order was gone. The effect
    was that no AI unit had ever been disbanded: peacetime militia accumulated
    indefinitely and the obsolete-unit cull never ran once.

    A unit already committed is also skipped for order assignment, since it is
    busy; see _assign_unit_orders.
    """
    nation_units = {}
    nation_provs = {}
    world = ai_world.for_screen(context)

    for ai_name in ai_nations:
        # AIWorld already indexed both dimensions during the turn snapshot.
        # This avoids scanning every province once per AI nation, which becomes
        # the dominant cost when late-game unit counts are high.
        provs = world.provs_by_owner.get(ai_name, ())
        units = world.units_by_owner.get(ai_name, ())
        nation_provs[ai_name] = provs
        nation_units[ai_name] = []

        for unit, prov in units:
            if not _can_replan_unit(context, unit):
                continue

            # Clear old path so the AI can rethink its strategy every turn
            unit_actions.apply_action(context, ai_name, prov, unit,
                                      {"type": "MOVE", "path": []}, authority="ai")
            nation_units[ai_name].append((unit, prov))

    return nation_units, nation_provs


def _gather_enemies(context, ai_name):
    """This nation's current enemies, plus (if the scenario enables surprise
    attacks) anyone it has a war declaration queued or drafted against."""
    world_state = world_for(context)
    enemies = list(world_state.nation_data[ai_name].get("at_war_with", []))

    if queries.get_scenario_flag("surprise_attack", c.DEFAULT_SURPRISE_ATTACK,
                                 world_state.scenario_settings):
        queued = world_state.nation_data[ai_name].get("queued_ai_actions", [])
        pending_wars = [q["target"] for q in queued if q.get("action") == "WAR_DECLARATION"]

        pending = world_state.nation_data[ai_name].get("pending_diplomacy", {})
        for target, info in pending.items():
            if isinstance(info, dict) and info.get("action") == "WAR_DECLARATION":
                pending_wars.append(target)

        if pending_wars:
            enemies = list(set(enemies + pending_wars))

    return enemies


def _compute_unsafe_waters(context, ai_name):
    """Pre-calculates areas heavily patrolled by enemies so Convoys and weak
    ships don't suicide into them."""
    world_state = world_for(context)
    unsafe_waters = {}
    world = ai_world.for_screen(context)
    for p in world.water_provinces:
        # Hidden enemy submarines don't make a water tile read as patrolled --
        # an AI that routed convoys around them would be reacting to a fleet
        # it has no way of knowing is there.
        visible_units = queries.filter_visible_units(p.get("units", []), ai_name, p, world_state.nation_data)
        enemy_str = sum(u.get("attack", c.DEFAULT_UNIT_ATK) + u.get("defense", 0) for u in visible_units
                        if queries.are_at_war(ai_name, u.get("owner"), world_state.nation_data)
                        and queries.is_naval_unit(u.get("type", ""), context=context))
        if enemy_str > 0:
            unsafe_waters[p["id"]] = enemy_str
    return unsafe_waters


def _threatened_coasts(context, ai_name, prov_ids, enemies):
    """Map potential landing sites to water tiles reachable from enemy shores or convoys."""
    world_state = world_for(context)
    world = ai_world.for_screen(context)
    if not enemies or not prov_ids:
        return {}
    enemies = set(enemies)
    visible = world.visible_provinces(ai_name)
    approaches = {tile for tile in world.water_ids
                  if any(world_state.id_to_province[near].get("owner") in enemies
                         for near in world.neighbor_ids.get(tile, ()) if near not in world.water_ids)
                  or ((visible is None or tile in visible)
                      and any(unit.get("type", "").startswith("Convoy")
                              for unit in _visible_hostiles(context, ai_name, world_state.id_to_province[tile])))}
    frontier = approaches.copy()
    for _ in range(c.AI_NEARBY_SEA_TILES - 1):
        frontier = {near for tile in frontier for near in world.neighbor_ids.get(tile, ()) if near in world.water_ids} - approaches
        approaches.update(frontier)
    return {beach: entries for beach in prov_ids
            if (entries := approaches.intersection(world.neighbor_ids.get(beach, ())))}


def _operational_paths(context, unit, origin, tiles, limit, stops=frozenset(), intercepted=None):
    """Shortest legal paths within a movement budget, stopping at visible fights."""
    world = world_for(context)
    start = origin["id"]
    paths = {start: ()}
    pending = deque([start])
    while pending:
        here = pending.popleft()
        path = paths[here]
        if len(path) >= limit or (path and here in stops):
            continue
        for tile in sorted(world.id_to_province[here].get("neighbors", ())):
            if tile in paths or tile not in tiles:
                continue
            if intercepted and intercepted(tile, len(path) + 1):
                continue
            if queries.can_unit_move_step(unit, world.id_to_province[here], world.id_to_province[tile], world.nation_data, context=context):
                paths[tile] = (*path, tile)
                pending.append(tile)
    return paths


def _book_reserved_land_order(supply, ctx, unit, origin, path):
    if not path:
        return
    # Optional as in _assign_unit_orders' assign(): a planner without supply
    # rules still books the move against the target counts.
    if supply is not None:
        supply.book(unit, path)
    for tile, delta in ((origin["id"], -1), (path[-1], 1)):
        if tile in ctx["target_assignments"]:
            ctx["target_stacks"][tile] += delta
            ctx["target_assignments"][tile] += delta


def _commit_reserved_orders(context, ai_name, orders, reserved, available, protected, supply, ctx):
    """Issues a group of (unit, origin, path) land orders together, or none.

    Refused when a unit is already reserved or appears twice, or when the group
    would empty a protected tile (`available` counts the free units on each).
    A move the order owner refuses rolls back the ones already issued. On
    success the units join `reserved` and their moves are booked against
    supply and the target counts.
    """
    units = {id(unit) for unit, _, _ in orders}
    if len(units) != len(orders) or units & reserved:
        return False
    leaving = defaultdict(int)
    for _, origin, path in orders:
        if path:
            leaving[origin["id"]] += 1
    if any(available.get(origin, 0) <= count for origin, count in leaving.items() if origin in protected):
        return False
    issued = []
    for unit, origin, path in orders:
        if not _order_move(context, ai_name, origin, unit, path):
            for prior, start in issued:
                _order_move(context, ai_name, start, prior, ())
            return False
        issued.append((unit, origin))
    reserved.update(units)
    for origin, count in leaving.items():
        available[origin] -= count
    for unit, origin, path in orders:
        _book_reserved_land_order(supply, ctx, unit, origin, path)
    return True


def _land_cut_cost(context, supply, tile, orders, defenders, counter):
    """Price a reachable occupation with the shared combat forecast and supply rules."""
    nations = world_for(context).nation_data
    units = [unit for unit, _, _ in orders]
    health = sum(unit["health"] for unit in units)
    cost = health * ai_tuning.AI_SUPPLY_CUT_COMMITMENT_COST
    for unit, _, path in orders:
        if not path:
            continue
        current, _ = supply.current(unit)
        readiness, _ = supply.quality(unit, tile["id"])
        if readiness <= 0:
            return None
        cost += unit["health"] * max(0, current - readiness)
    survivors = units
    if defenders:
        forecast = combat_forecast.simulate_combat(
            [units, defenders], nations, province=tile, max_turns=ai_tuning.AI_SUPPLY_CUT_MAX_VOLLEYS)
        if forecast["winner_side"] != 0:
            return None
        survivors = forecast["sides"][0]
        cost += health - sum(unit["health"] for unit in survivors)
    if counter is not None:
        battle = combat_rules.build_battle([survivors, [counter]], nations,
                                           terrain=tile.get("terrain"), tiles=(tile, tile))
        incoming = combat_rules.projected_incoming_damage(battle, nations, defense_bonus_fn=lambda unit:
                                                           queries.get_fort_defense_bonus(tile, unit, nations, combat_active=True))
        losses = sum(min(unit["health"], incoming.get(id(unit), 0)) for unit in survivors)
        if losses >= sum(unit["health"] for unit in survivors):
            return None
        cost += losses
    return cost


def _reserve_land_supply_orders(context, ai_name, units_info, supply, ctx, reserved):
    """Reserve legal forces for a supply cut before ordinary frontier movement."""
    known = supply.known
    if not supply.enemies.intersection(known.land_units) or not supply.network.unit_area:
        return
    provinces = known.provinces
    ground = supply.network.province_area.keys() - known.water
    hostile_land = {tile for owner in supply.enemies for tile in known.owned_land.get(owner, ())}
    hostile_units = {tile: [u for u in units if queries.get_unit_combat_owner(u) in supply.enemies]
                     for tile, units in known.visible_units.items() if known.occupants[tile] & supply.enemies}
    claims = {enemy: set(known.nations[enemy].get("claims", ())) for enemy in supply.enemies if enemy in known.nations}
    threatened = {}
    targets = set()
    for tile in ground:
        enemy_neighbors = {near for near in provinces[tile].get("neighbors", ()) if near in hostile_land}
        if enemy_neighbors:
            targets.update(enemy_neighbors)
            # Capture gives the former owner a claim. Use claims and cores to
            # recognize territory that could restore a recently cut route.
            retakers = {provinces[near]["owner"] for near in enemy_neighbors}
            retakers = {owner for owner in retakers if tile in claims.get(owner, ()) or owner in provinces[tile].get("cores", ())}
            if retakers:
                threatened[tile] = tuple(sorted(retakers))
    if not targets:
        return

    protected = supply.critical | (ctx["peace_borders"] - ctx["war_borders"])
    available = {}
    for tile, group in known.land_units[ai_name].items():
        orders = (known.unit_data[key].unit.get("order") or {} for key in group)
        available[tile] = sum(not order.get("path") and order.get("type") not in ("CONVERT", "DISBAND") for order in orders)
    stops = hostile_land | hostile_units.keys()
    allowed = ground | targets
    destinations = targets | threatened.keys()
    routes = defaultdict(list)
    for unit, origin in units_info:
        tile = origin["id"]
        if (id(unit) in reserved or queries.supply_unit_key(unit) not in supply.network.unit_area or tile not in ground
                or tile in stops or tile in ctx["lost_battles"] or tile in ctx["active_battles"] or _is_wounded(unit)):
            continue
        speed = queries.unit_movement_speed(unit)
        paths = _operational_paths(context, unit, origin, allowed, speed, stops)
        for target in destinations & paths.keys():
            path = paths[target]
            if path and tile in protected and available.get(tile, 0) <= 1:
                continue
            routes[target].append((unit, origin, path))
    if not routes:
        return

    cuts, holds = supply.land_supply_objectives(
        targets & routes.keys(), {tile: owners for tile, owners in threatened.items() if tile in routes},
        can_coordinate=sum(len(group) for group in known.land_units[ai_name].values()) >= 2)
    if not cuts and not holds:
        return
    land_enemies = {id(known.unit_data[key].unit) for enemy in supply.enemies
                    for group in known.land_units.get(enemy, {}).values() for key in group}
    options = {}
    for tile in sorted(holds.keys() | {tile for cut in cuts for tile in cut}):
        candidates = sorted(routes[tile], key=lambda order: (bool(order[2]), -queries.calculate_unit_strength(order[0]), len(order[2])))
        candidates = candidates[:ai_tuning.AI_SUPPLY_CUT_CANDIDATES_PER_TILE]
        counter = max((unit for near in provinces[tile].get("neighbors", ()) for unit in hostile_units.get(near, ())
                       if id(unit) in land_enemies and queries.unit_movement_speed(unit) > 0
                       and queries.can_unit_move_step(unit, provinces[near], provinces[tile], known.nations, context=context)),
                      key=queries.calculate_unit_strength, default=None)
        options[tile] = []
        for size in range(1, len(candidates) + 1):
            for orders in combinations(candidates, size):
                cost = _land_cut_cost(context, supply, provinces[tile], orders, hostile_units.get(tile, ()), counter)
                if cost is not None:
                    options[tile].append((cost, orders))
        options[tile].sort(key=lambda option: option[0])

    def commit(orders):
        return _commit_reserved_orders(context, ai_name, orders, reserved, available, protected, supply, ctx)

    followup = set()
    for tile, (value, exposed) in sorted(holds.items(), key=lambda row: (-row[1][0], row[0])):
        for cost, orders in options[tile]:
            if cost >= value:
                break
            if commit(orders):
                followup.update(exposed)
                break
    for target in followup & ctx["target_assignments"].keys():
        ctx["target_assignments"][target] -= ai_tuning.AI_SUPPLY_CUT_FOLLOWUP_WEIGHT

    plans = []
    for tiles, losses in cuts.items():
        value = sum(losses.values())
        for choices in product(*(options[tile] for tile in tiles)):
            cost = sum(option[0] for option in choices)
            if value > cost:
                orders = tuple(order for _, group in choices for order in group)
                plans.append((value - cost, cost, tiles, orders))
    disrupted = set()
    taken = set()
    for _, cost, tiles, orders in sorted(plans, key=lambda plan: (-plan[0], plan[2])):
        losses = cuts[tiles]
        if not taken.intersection(tiles) and sum(loss for enemy, loss in losses.items() if enemy not in disrupted) > cost and commit(orders):
            disrupted.update(losses)
            taken.update(tiles)


def _new_fights(context, ai_name, ctx):
    """{tile: visible hostiles} for each enemy tile a fight would start on.

    Enemy or expedition destinations holding visible hostiles that this nation
    is not already fighting on. Only _reserve_strike_orders starts these; a
    battle already under way is reinforced by the ordinary battle pull, which
    tile_is_lost has already judged worth holding.
    """
    world_state = world_for(context)
    fights = {}
    for tile in ctx["target_destinations"]:
        if tile not in ctx["enemy_targets"] and tile not in ctx["expedition_targets"]:
            continue
        if tile in ctx["active_battles"] or tile in ctx["lost_battles"]:
            continue
        prov = world_state.id_to_province.get(tile)
        hostiles = _visible_hostiles(context, ai_name, prov) if prov else []
        if hostiles:
            fights[tile] = hostiles
    return fights


def _may_strike(context, ai_name, unit, origin, ctx, reserved):
    """Whether `unit` would reach _assign_unit_orders' attack branch this turn.

    The checks that run ahead of that branch, in its order, so the strike
    planner takes only units the per-unit pass would have sent to attack:
    nothing busy, fighting, wounded, at sea or riding a convoy; no gun with
    something to shell; nobody with a supply move to make; and nobody about to
    walk into unclaimed land. Lone guards are held back by the caller's
    protected tiles, as in the supply pass.
    """
    world_state = world_for(context)
    nation_data = world_state.nation_data
    u_type = unit.get("type", "")
    if (id(unit) in reserved or not any(current is unit for current in origin.get("units", []))
            or u_type.startswith("Convoy") or _is_combat_ship(u_type, context=context)
            or _is_wounded(unit) or origin["id"] in ctx["lost_battles"]
            or queries.is_nation_in_combat_here(ai_name, origin, nation_data)):
        return False
    bomb_range = queries.get_bombardment_range(u_type, context=context)
    if bomb_range > 0 and _bombardment_target(context, ai_name, origin, bomb_range) is not None:
        return False
    supply = ctx.get("supply")
    if supply is not None:
        relief = ctx.get("relief_targets", set())
        current = supply.current(unit)
        for tile in origin.get("neighbors", ()):
            prov = world_state.id_to_province.get(tile)
            if prov is None or queries.is_water_province(prov):
                continue
            if tile in relief or supply.quality(unit, tile) > current:
                return False
    return not any(tile in ctx["unclaimed_targets"] for tile in origin.get("neighbors", ()))


def _short_of_new_fights(path, new_fights):
    """`path` up to, not into, the first tile where it would start a new fight."""
    for index, tile in enumerate(path):
        if tile in new_fights:
            return list(path[:index])
    return list(path)


def _strike_depth(context, ai_name, tile):
    """How many units a new fight on `tile` can use: a front rank and its relief."""
    world_state = world_for(context)
    prov = world_state.id_to_province[tile]
    capacity = {tile: combat_rules.nation_front_capacity(ai_name, prov, world_state.nation_data)}
    return int(_tile_depth(capacity, tile))


def strike_forecast_turns():
    """How many exchanges ahead a new fight must hold: the retreat horizon, plus one.

    The attack's first exchange is fought in the turn it is ordered, and the
    next turn's tile_is_lost looks AI_RETREAT_FORECAST_TURNS further on from
    there. Holding only that many from the start let a fight lost on the
    exchange after pass here and be abandoned a turn later.
    """
    return ai_tuning.AI_RETREAT_FORECAST_TURNS + 1


def _strike_group(context, ai_name, tile, hostiles, routes, reserved, friendly_nations):
    """The fewest of `routes` that make a new fight on `tile` one we do not lose.

    "Not lost" is the bar tile_is_lost holds a fight by: the shared forecast
    does not have the enemy wipe us out within the horizon it will look at
    next turn (strike_forecast_turns). A fight the planner starts is therefore
    one the retreat check will not order abandoned next turn, unless the enemy
    reinforces it. Strongest units first, and no more than the tile can use
    (_tile_depth). None when even that many would lose.
    """
    world_state = world_for(context)
    prov = world_state.id_to_province[tile]
    candidates = sorted((route for route in routes if id(route[0]) not in reserved),
                        key=lambda route: (-queries.calculate_unit_strength(route[0]), len(route[2]),
                                           str(route[1]["id"])))
    candidates = candidates[:_strike_depth(context, ai_name, tile)]
    allies = [unit for unit in prov.get("units", ())
              if unit.get("health", 0) > 0 and queries.get_unit_combat_owner(unit) in friendly_nations]
    for size in range(1, len(candidates) + 1):
        group = candidates[:size]
        outcome = combat_forecast.estimated_combat_outcome(
            [allies + [unit for unit, _, _ in group], hostiles], world_state.nation_data,
            province=prov, max_turns=strike_forecast_turns())
        if outcome["winner_side"] != 1:
            return tuple(group)
    return None


def _reserve_strike_orders(context, ai_name, units_info, ctx, reserved, ground_ids):
    """Starts new fights as concerted attacks, before the per-unit pass.

    The per-unit pass sent each unit alone at whichever adjacent enemy tile had
    the fewest attackers booked, so an army spread itself evenly along the
    front, and a unit went in whenever it alone survived the first exchange --
    a weaker bar than the one tile_is_lost then held the fight to, so a stack
    could charge a tile one turn and be ordered out of it the next.

    Here every new fight (_new_fights) is planned with every unit that could
    reach it this turn, and started only with a group the retreat check would
    keep there (_strike_group). The fights that need the fewest units go first,
    then productive factories and the land worth most at the peace table.
    The army masses on the fights it can win. Units left over join a
    fight already started, up to what its tile can use.

    `ctx["new_fights"]` tells the per-unit pass which tiles it must not start
    on its own. Patterned on _reserve_land_supply_orders, whose
    _commit_reserved_orders this shares.
    """
    world_state = world_for(context)
    fights = _new_fights(context, ai_name, ctx) if ctx["at_war"] else {}
    ctx["new_fights"] = set(fights)
    if not fights:
        return
    supply = ctx.get("supply")
    friendly_nations = ctx["friendly_nations"]
    stops = set(ctx["enemy_targets"]) | set(ctx["expedition_targets"])
    allowed = set(ground_ids) | set(fights)
    protected = (ctx["peace_borders"] - ctx["war_borders"]) | (supply.critical if supply else set())

    available = defaultdict(int)
    for unit, origin in units_info:
        order = unit.get("order") or {}
        if not order.get("path") and order.get("type") not in ("CONVERT", "DISBAND"):
            available[origin["id"]] += 1

    routes = defaultdict(list)
    for unit, origin in units_info:
        if id(unit) in reserved:
            continue
        # Reach first: a few tiles of search, where _may_strike asks the supply
        # rules about every neighbour. Most of an army is nowhere near a fight.
        paths = _operational_paths(context, unit, origin, allowed, queries.unit_movement_speed(unit), stops)
        reachable = sorted(fights.keys() & paths.keys())
        if not reachable or not _may_strike(context, ai_name, unit, origin, ctx, reserved):
            continue
        for tile in reachable:
            path = paths[tile]
            if not path or (origin["id"] in protected and available.get(origin["id"], 0) <= 1):
                continue
            if supply is not None and not supply.improves_reinforcement(unit, world_state.id_to_province[tile]):
                continue
            routes[tile].append((unit, origin, path))

    plans = {tile: _strike_group(context, ai_name, tile, fights[tile], routes[tile], reserved, friendly_nations)
             for tile in routes}
    factory_bonuses = ctx.get("factory_bonuses", {})
    started = {}
    while True:
        viable = [(len(group), -factory_bonuses.get(tile, 0), -deal_mod.tile_value(world_state.id_to_province[tile]), str(tile), tile)
                  for tile, group in plans.items() if group]
        if not viable:
            break
        tile = min(viable)[-1]
        group = plans.pop(tile)
        if not _commit_reserved_orders(context, ai_name, group, reserved, available, protected, supply, ctx):
            continue
        started[tile] = len(group)
        taken = {id(unit) for unit, _, _ in group}
        for other in list(plans):
            if any(id(unit) in taken for unit, _, _ in routes[other]):
                plans[other] = _strike_group(context, ai_name, other, fights[other], routes[other],
                                             reserved, friendly_nations)

    # Whoever could still reach a fight that is going ahead joins it, strongest
    # first, until its tile has a full front and relief.
    for tile, committed in sorted(started.items()):
        room = _strike_depth(context, ai_name, tile) - committed
        for route in sorted(routes[tile], key=lambda route: (-queries.calculate_unit_strength(route[0]),
                                                             str(route[1]["id"]))):
            if room <= 0:
                break
            if id(route[0]) not in reserved and _commit_reserved_orders(
                    context, ai_name, (route,), reserved, available, protected, supply, ctx):
                room -= 1


def _naval_exchange_favors(context, ship, opponents, tile):
    if not opponents:
        return True
    nations = world_for(context).nation_data
    battle = combat_rules.build_battle([[ship], opponents], nations, terrain=tile.get("terrain"), tiles=(tile, tile))
    incoming = combat_rules.projected_incoming_damage(battle, nations)
    own_loss = incoming.get(id(ship), 0) / ship["health"]
    enemy_loss = sum(min(unit["health"], incoming.get(id(unit), 0)) for unit in opponents)
    return own_loss < 1 and enemy_loss > own_loss * sum(unit["health"] for unit in opponents)


def _reserve_naval_orders(context, ai_name, units_info, supply, beaches):
    """Commit ships to interceptions, then to sea occupations with a supply effect."""
    if not supply.enemies:
        return set(), {}, set()
    world = world_for(context)
    provinces = world.id_to_province
    known = supply.known
    hostile = {tile: [u for u in units if queries.get_unit_combat_owner(u) in supply.enemies]
               for tile, units in known.visible_units.items()}
    hostile = {tile: units for tile, units in hostile.items() if units}
    sea = known.water
    coastal_water = {tile for beach in beaches for tile in provinces[beach].get("neighbors", ()) if tile in sea}
    convoys = [(unit, provinces[tile]) for tile, units in hostile.items() for unit in units
               if unit.get("type", "").startswith("Convoy") and (tile in sea or provinces[tile].get("is_coastal"))]
    fleet = {id(unit): (unit, origin) for unit, origin in units_info
             if _is_combat_ship(unit.get("type", ""), context=context) and unit["health"] > 0 and not _is_wounded(unit)
             and origin["id"] not in hostile}
    if not convoys and not fleet:
        return set(), {}, set()
    fleet_rank = {identity: rank for rank, identity in enumerate(fleet)}

    ship_routes = defaultdict(dict)
    if beaches or known.land_units:
        for identity, (ship, port) in fleet.items():
            for tile, path in _operational_paths(context, ship, port, sea, queries.unit_movement_speed(ship), hostile).items():
                if tile in sea:
                    ship_routes[tile][identity] = path

    enemy_reach = defaultdict(list)
    if ship_routes:
        for tile, units in hostile.items():
            for unit in units:
                if not _is_combat_ship(unit.get("type", ""), context=context):
                    continue
                paths = _operational_paths(context, unit, provinces[tile], sea, queries.unit_movement_speed(unit))
                for target in paths.keys() & ship_routes.keys():
                    enemy_reach[target].append((len(paths[target]), unit))

    reserved = set()
    stations = {}

    def commit(plan):
        ordered = []
        for identity, tile in plan:
            ship, port = fleet[identity]
            if not _order_move(context, ai_name, port, ship, ship_routes[tile][identity]):
                for prior in ordered:
                    _order_move(context, ai_name, fleet[prior][1], fleet[prior][0], ())
                return False
            ordered.append(identity)
        for identity, tile in plan:
            reserved.add(identity)
            stations[tile] = identity
        return True

    def options(tile):
        routes = ship_routes.get(tile, {})
        return sorted(routes.keys() - reserved, key=lambda identity: (len(routes[identity]), -fleet[identity][0]["health"], fleet_rank[identity]))

    def landings(convoy, port, additional=None):
        limit = queries.unit_movement_speed(convoy)

        def intercepted(tile, step):
            identity = additional[1] if additional and tile == additional[0] else stations.get(tile)
            if identity is None or len(ship_routes[tile][identity]) > step:
                return False
            escort = [u for arrival, u in enemy_reach.get(tile, ()) if arrival <= step]
            cargo = [u for u in hostile[port["id"]] if u.get("type", "").startswith("Convoy")]
            return _naval_exchange_favors(context, fleet[identity][0], cargo + escort, provinces[tile])

        paths = _operational_paths(context, convoy, port, sea, limit, intercepted=intercepted)
        routes = {}
        for tile, path in sorted(paths.items(), key=lambda item: len(item[1])):
            if tile not in coastal_water or len(path) >= limit:
                continue
            for beach in provinces[tile].get("neighbors", ()):
                if beach in beaches and beach not in routes and queries.can_unit_move_step(
                        convoy, provinces[tile], provinces[beach], world.nation_data, context=context):
                    routes[beach] = path
        return routes

    # A ship must reach a water tile on the convoy's path by the same step.
    # Recheck possible landings with the ship committed, since an alternate
    # crossing can leave the coast exposed even if the shortest path is covered.
    initial_sites = {beach for convoy, port in convoys for beach in landings(convoy, port)}
    for convoy, port in convoys:
        routes = landings(convoy, port)
        candidates = {(tile, identity) for path in routes.values() for step, tile in enumerate(path, 1)
                      if tile not in stations for identity in options(tile) if len(ship_routes[tile][identity]) <= step}
        ranked = []
        for tile, identity in candidates:
            remaining = landings(convoy, port, (tile, identity))
            if len(remaining) < len(routes):
                ranked.append((len(remaining), len(ship_routes[tile][identity]), tile, identity))
        for _, _, tile, identity in sorted(ranked, key=lambda item: (*item[:3], fleet_rank[item[3]])):
            if commit(((identity, tile),)):
                break

    threats = defaultdict(list)
    for convoy, port in convoys:
        for beach, path in landings(convoy, port).items():
            threats[beach].append(len(path) + 1)

    vacating = defaultdict(set)
    for identity, (_, port) in fleet.items():
        if stations.get(port["id"]) != identity:
            vacating[port["id"]].add(identity)
    reachable = {tile for tile in ship_routes if tile not in stations and ship_routes[tile].keys() - reserved}
    objectives = supply.naval_supply_objectives(reachable, enemy_reach, vacating, set(stations), len(fleet) - len(reserved))
    priorities = {"relief": 0, "guard": 1, "guard_one": 1, "blockade": 2, "scout": 3}
    blockaded = set()
    scouted = False
    restored = False
    for kind, _, tiles, country in sorted(objectives, key=lambda task: (priorities[task[0]], -task[1] / (len(task[2]) if task[0] == "blockade" else 1), task[2], task[3])):
        if set(tiles) & stations.keys() or country in blockaded or (kind == "scout" and (scouted or restored)):
            continue
        choices = []
        for tile in tiles:
            targets = hostile.get(tile, [])
            if kind in ("guard", "guard_one", "blockade"):
                targets = list({id(u): u for u in [*targets, *(u for _, u in enemy_reach[tile])]}.values())
            choices.append([identity for identity in options(tile)
                            if (kind != "scout" or ship_routes[tile][identity])
                            and _naval_exchange_favors(context, fleet[identity][0], targets, provinces[tile])])
        if len(tiles) == 1 or kind == "guard_one":
            best = min(((identity, tile) for tile, ships in zip(tiles, choices) for identity in ships),
                       key=lambda choice: (len(ship_routes[choice[1]][choice[0]]), fleet_rank[choice[0]], choice[1]), default=None)
            plan = (best,) if best is not None else ()
        else:
            plan = next((((first, tiles[0]), (second, tiles[1])) for first in choices[0] for second in choices[1] if first != second), ())
        if plan and commit(plan):
            if kind == "blockade":
                blockaded.add(country)
            restored |= kind == "relief"
            scouted |= kind == "scout"

    return reserved, threats, initial_sites


def _reserve_coastal_guards(context, ai_name, units_info, supply, warnings, threats, ctx):
    """Cover immediate landings first, then keep a guard per exposed coast."""
    provinces = world_for(context).id_to_province
    known = supply.known
    owned_land = {tile for tile, province in provinces.items() if province.get("owner") == ai_name and tile not in known.water}
    stops = {tile for tile in owned_land if known.occupants.get(tile, set()) & supply.enemies}
    warning_risk = {beach: len(entries - known.visible_provinces) if known.visible_provinces is not None else 0
                    for beach, entries in warnings.items()}
    divisions = known.land_units.get(ai_name, {})
    committed = set()
    candidates = []
    for unit, origin in units_info:
        tile = origin["id"]
        if (tile not in owned_land or tile in stops or unit.get("health", 0) <= 0
                or queries.supply_unit_key(unit) not in divisions.get(tile, ())
                or (tile in supply.critical and ctx["target_stacks"].get(tile, 0) <= 1)):
            continue
        speed = queries.unit_movement_speed(unit)
        paths = _operational_paths(context, unit, origin, owned_land, speed * ai_tuning.AI_COAST_GARRISON_TURNS, stops)
        candidates.append((unit, origin, speed, paths))

    def guard(sites, *, imminent=False):
        orders = []
        for unit, origin, speed, paths in candidates:
            if id(unit) in committed:
                continue
            for site in (sites & paths.keys()) - stops:
                path = paths[site]
                if path and speed <= 0:
                    continue
                distance = len(path)
                if imminent:
                    priority = distance > speed, distance, -unit["health"]
                else:
                    # Preserve combat strength for the front when guards can
                    # cover the coast on the same turn.
                    turns_late = (distance - 1) // speed if distance > speed else 0
                    priority = turns_late, queries.calculate_unit_strength(unit), distance
                rank = (-warning_risk.get(site, 0), *priority, site)
                orders.append((rank, unit, origin, path[:speed]))
        for _, unit, origin, path in sorted(orders, key=lambda order: order[0]):
            if _order_move(context, ai_name, origin, unit, path):
                committed.add(id(unit))
                _book_reserved_land_order(supply, ctx, unit, origin, path)
                return True
        return False

    for beach, arrivals in sorted(threats.items(), key=lambda item: (min(item[1]), -len(item[1]), item[0])):
        for _ in arrivals:
            if not guard({beach}, imminent=True):
                break

    pending = warnings.keys() | threats.keys()
    while pending:
        start = min(pending, key=lambda tile: (-warning_risk.get(tile, 0), tile))
        blind = bool(warning_risk.get(start, 0))
        sector = {start}
        frontier = list(sector)
        pending.difference_update(sector)
        while frontier:
            tile = frontier.pop()
            adjacent = {near for near in provinces[tile].get("neighbors", ()) if near in pending
                        and bool(warning_risk.get(near, 0)) == blind}
            sector.update(adjacent)
            pending.difference_update(adjacent)
            frontier.extend(adjacent)
        if not sector & threats.keys():
            guard(sector)
    return committed


def _discover_borders_and_targets(context, ai_name, my_provs, enemies, friendly_nations):
    """Locates coastal/enemy/unclaimed tiles globally (for naval targeting and
    island hopping and distant-ally expeditions) and classifies each of this
    nation's own border provinces as a war, peace, or coastal border."""
    world_state = world_for(context)
    enemies = set(enemies).difference(c.UNPLAYABLE_NATIONS)
    war_borders = set()
    peace_borders = set()
    coastal_borders = set()
    enemy_targets = set()
    all_enemy_coasts = set()
    enemy_coastal_waters = set()
    unclaimed_targets = set()
    all_unclaimed_coasts = set()
    expedition_targets = set()

    world = ai_world.for_screen(context)

    # Locate coastal provinces globally for naval targeting and island hopping.
    # The structural coastal index avoids revisiting inland provinces for each
    # AI nation; the legality and diplomacy decisions remain live queries.
    for prov in world.coastal_provinces:
        owner = prov.get("owner", "Unclaimed")

        if prov.get("is_coastal", False):
            if enemies and owner in enemies:
                all_enemy_coasts.add(prov["id"])

                # Patrol waters off the enemy coast. Supply blockades are scored separately.
                for n_id in prov.get("neighbors", []):
                    n_prov = world_state.id_to_province.get(n_id)
                    if n_prov and queries.is_water_province(n_prov):
                        enemy_coastal_waters.add(n_id)

            # Identify unclaimed islands globally
            elif owner in c.UNOWNED_LAND_OWNERS:
                all_unclaimed_coasts.add(prov["id"])

    if enemies:
        # 1. Reinforce allied battles.  Only combat provinces can satisfy this
        # condition, so avoid checking every map tile.
        for prov in world.combat_provinces:
            units_here = prov.get("units", [])
            if any(u.get("owner") in friendly_nations for u in units_here):
                # Ships join allies at sea only where they share an active enemy.
                if queries.is_water_province(prov) and not any(queries.are_at_war(ai_name, queries.get_unit_combat_owner(u), world_state.nation_data) for u in units_here):
                    continue
                expedition_targets.add(prov["id"])

        # 2. Reinforce allied borders touching mutual enemies.  The owner
        # index narrows this to provinces actually held by an enemy nation.
        for enemy in enemies:
            for prov in world.provs_by_owner.get(enemy, ()):
                for n_id in prov.get("neighbors", []):
                    n_prov = world_state.id_to_province.get(n_id)
                    if (n_prov and n_prov.get("owner") in friendly_nations
                            and n_prov.get("owner") != ai_name):
                        expedition_targets.add(prov["id"])
                        break

    for prov in my_provs:
        is_war_border = False
        is_peace_border = False
        is_coastal = prov.get("is_coastal", False)

        for n_id in prov.get("neighbors", []):
            n_prov = world_state.id_to_province.get(n_id)
            if not n_prov: continue
            if queries.is_water_province(n_prov): continue

            n_owner = n_prov.get("owner", "Unclaimed")
            if n_owner in enemies:
                is_war_border = True
                enemy_targets.add(n_id)
            elif n_owner in c.UNOWNED_LAND_OWNERS:
                unclaimed_targets.add(n_id)
            elif n_owner != ai_name and n_owner not in c.UNPLAYABLE_NATIONS and not queries.are_in_same_faction(ai_name, n_owner, world_state.nation_data):
                is_peace_border = True

        if is_war_border:
            war_borders.add(prov["id"])
        elif is_peace_border:
            peace_borders.add(prov["id"])
        elif is_coastal:
            coastal_borders.add(prov["id"])

    # A coast with no land border needs a guard only if something could land
    # on it. Guarding every one of them kept half of some armies on beaches no
    # enemy could reach (saves/runv3: 47 of the United States' 61 land units,
    # at war with nobody).
    coastal_approaches = _threatened_coasts(context, ai_name, coastal_borders, enemies)

    return {
        "war_borders": war_borders,
        "peace_borders": peace_borders,
        "coastal_approaches": coastal_approaches,
        "enemy_targets": enemy_targets,
        "all_enemy_coasts": all_enemy_coasts,
        "enemy_coastal_waters": enemy_coastal_waters,
        "unclaimed_targets": unclaimed_targets,
        "all_unclaimed_coasts": all_unclaimed_coasts,
        "expedition_targets": expedition_targets,
    }


def tile_is_lost(context, ai_name, prov, friendly_nations, reinforcements=()):
    """Whether staying on this tile means losing the fight on it.

    Asked of the shared battle forecast (combat_forecast), the same simulation
    the map's battle bubbles and Manage Battle's outlook use. It plays the lane
    model forward -- reserves stepping into empty slots, damage after defense --
    for up to AI_RETREAT_FORECAST_TURNS exchanges.

    The check this replaced looked at one exchange only and called the tile lost
    only when that single volley killed every front unit and nobody stood
    behind them. A battle lost over three turns was never "lost", so the stack
    bled out a unit at a time and only the last survivor ever ran.

    `reinforcements` are units that could step onto the tile this turn. When
    they would turn the result, the tile is worth holding: it stays an active
    battle, and the normal reinforcement pull sends them in.

    Only friendly units and visible hostile units are counted.
    """
    world_state = world_for(context)
    nation_data = world_state.nation_data
    ours = [unit for unit in prov.get("units", ())
            if unit.get("health", 0) > 0
            and queries.get_unit_combat_owner(unit) in friendly_nations]
    theirs = _visible_hostiles(context, ai_name, prov)
    if not ours or not theirs:
        return False

    def loses(side):
        outcome = combat_forecast.estimated_combat_outcome(
            [side, theirs], nation_data, province=prov,
            max_turns=ai_tuning.AI_RETREAT_FORECAST_TURNS)
        return outcome["winner_side"] == 1

    if not loses(ours):
        return False
    return not reinforcements or loses(ours + list(reinforcements))


def available_reinforcements(context, ai_name, prov, units_info):
    """Healthy battle reinforcements that can reach `prov` this turn."""
    world_state = world_for(context)
    nation_data = world_state.nation_data
    neighbors = set(prov.get("neighbors", ()))
    naval_battle = queries.is_water_province(prov)
    return [unit for unit, here in units_info
            if here["id"] in neighbors
            and not _is_wounded(unit)
            and _is_combat_ship(unit.get("type", ""), context=context) == naval_battle
            and not queries.is_nation_in_combat_here(ai_name, here, nation_data)
            and queries.can_unit_move_step(unit, here, prov, nation_data, context=context)]


def _retreat_tile(context, ai_name, unit, prov, friendly_nations, unsafe_waters, havens, supply=None):
    """The best neighbouring tile for `unit` to fall back to, or None.

    Chosen per unit, because a ship, a convoy and a division standing on the
    same tile cannot all use the same neighbour. A tile qualifies when the unit
    may legally step there, it is not hostile land, nothing visible is fighting
    there, and no visible enemy fleet patrols it. Prefer better combat supply
    and movement speed, then repair havens, friendly land, and fewer visible
    threats. Ties go to the lowest id so the choice is reproducible.
    """
    world_state = world_for(context)
    nation_data = world_state.nation_data
    combat_owner = queries.get_unit_combat_owner(unit)
    choices = []
    for n_id in sorted(prov.get("neighbors", ())):
        n_prov = world_state.id_to_province.get(n_id)
        if not n_prov or n_id in unsafe_waters:
            continue
        # Sea tiles are not anyone's territory to be hostile; their danger is
        # the visible fleet in them, checked below and through unsafe_waters.
        if (not queries.is_water_province(n_prov) and queries.is_hostile_territory(
                combat_owner, n_prov.get("owner", "Unclaimed"), nation_data)):
            continue
        if not queries.can_unit_move_step(unit, prov, n_prov, nation_data, context=context):
            continue
        if _visible_hostiles(context, ai_name, n_prov):
            continue
        danger = 0
        for far_id in n_prov.get("neighbors", ()):
            far = world_state.id_to_province.get(far_id)
            if far and far_id != prov["id"] and (
                    _visible_hostiles(context, ai_name, far)
                    or queries.are_at_war(ai_name, far.get("owner"), nation_data)):
                danger += 1
        readiness, speed = supply.quality(unit, n_id) if supply else (1.0, 1)
        choices.append((-readiness, -speed, n_id not in havens, n_prov.get("owner") not in friendly_nations,
                        danger, n_id))
    return min(choices)[-1] if choices else None


def _attackers_would_survive(context, ai_name, target_prov, attackers):
    """Whether at least one attacker survives the first exchange at a target.

    A charge that kills every incoming unit is resolved immediately by
    ``combat_processor.process_pinning``. Ask the same battle builder and
    projected damage helper here, so the AI does not deliberately issue a move
    that the resolver will turn into an instant wipeout. A unit that is not in
    a lane is treated as surviving: it is not actually part of this fight.
    """
    world_state = world_for(context)
    attackers = list(attackers)
    if not attackers:
        return False

    target_units = list(target_prov.get("units", ()))
    battle = combat_rules.build_battle(
        [target_units, attackers], world_state.nation_data,
        terrain=target_prov.get("terrain"), tiles=(target_prov, target_prov))
    attackers = [unit for unit in attackers
                 if battle.profiles.get(id(unit), unit).get("health", 1) > 0]
    if not attackers:
        return False
    if not battle.lanes:
        return True

    incoming = combat_rules.projected_incoming_damage(
        battle, world_state.nation_data)
    engaged_ids = {
        id(unit)
        for lane in battle.lanes
        for side in (lane.a, lane.b)
        for unit in side.front
    }

    return any(
        id(unit) not in engaged_ids
        or incoming.get(id(unit), 0.0) < unit.get("health", 1)
        for unit in attackers
    )


def _attack_target_is_immediate_loss(context, ai_name, target_id, unit,
                                   cache=None, attacker_signature=None):
    """True when moving ``unit`` into ``target_id`` would be an instant wipe."""
    world_state = world_for(context)
    if cache is not None:
        target_prov = world_state.id_to_province.get(target_id)
        # A unit already on the target appears twice in the hypothetical sides.
        # That identity-sensitive case must not share another unit's verdict.
        if target_prov and any(defender is unit for defender in target_prov.get("units", ())):
            return _attack_target_is_immediate_loss(context, ai_name, target_id, unit)
        if attacker_signature is None:
            attacker_signature = combat_rules.single_attacker_signature(unit)
        key = (target_id, attacker_signature)
        if key in cache:
            return cache[key]
        # Cache only within one nation's order assignment. No defender stats,
        # politics or diplomatic state change during that pass; the following
        # nation's reserve rotation must not inherit this nation's verdicts.
        result = _attack_target_is_immediate_loss(context, ai_name, target_id, unit)
        cache[key] = result
        return result
    target_prov = world_state.id_to_province.get(target_id)
    if not target_prov:
        return False

    if not any(queries.are_at_war(ai_name, defender.get("owner"),
                                  world_state.nation_data)
               for defender in target_prov.get("units", ())):
        return False

    return not _attackers_would_survive(
        context, ai_name, target_prov, [unit])


def _track_battles_and_convoys(context, ai_name, units_info, friendly_nations, unsafe_waters,
                               all_enemy_coasts, enemy_coastal_waters, havens=frozenset(), supply=None):
    """Finds active battles (and whether this nation is about to lose them, in
    which case its units fall back -- see _retreat_tile), plus which convoys are
    in combat or near danger so the escort-priority weighting can protect them."""
    world_state = world_for(context)
    friendly_convoys = set()
    convoy_in_combat = set()
    convoy_near_ship = set()
    convoy_near_coast = set()

    active_battles = set()
    lost_battles = set()

    for unit, prov in units_info:
        p_id = prov["id"]
        if queries.is_nation_in_combat_here(ai_name, prov, world_state.nation_data):
            if p_id not in active_battles and p_id not in lost_battles:
                reinforcements = available_reinforcements(context, ai_name, prov, units_info)
                # A lost tile is only abandoned when somebody on it can get out;
                # with nowhere to run, the units fight it out as a battle.
                if tile_is_lost(context, ai_name, prov, friendly_nations, reinforcements) and any(
                        _retreat_tile(context, ai_name, mine, prov, friendly_nations,
                                      unsafe_waters, havens, supply) is not None
                        for mine, here in units_info if here is prov):
                    lost_battles.add(p_id)
                else:
                    active_battles.add(p_id)

        if unit.get("type", "").startswith("Convoy"):
            friendly_convoys.add(p_id)
            # Escort AI: Determine how much danger the convoy is in
            if queries.is_nation_in_combat_here(ai_name, prov, world_state.nation_data):
                convoy_in_combat.add(p_id)
            else:
                near_ship = False
                near_coast = False
                for n_id in prov.get("neighbors", []):
                    if n_id in unsafe_waters:
                        near_ship = True
                    elif n_id in all_enemy_coasts or n_id in enemy_coastal_waters:
                        near_coast = True

                if near_ship:
                    convoy_near_ship.add(p_id)
                elif near_coast:
                    convoy_near_coast.add(p_id)

    return {
        "active_battles": active_battles,
        "lost_battles": lost_battles,
        "friendly_convoys": friendly_convoys,
        "convoy_in_combat": convoy_in_combat,
        "convoy_near_ship": convoy_near_ship,
        "convoy_near_coast": convoy_near_coast,
    }


def _build_target_assignments(units_info, borders, battles, at_war, capacity=None, *, water_ids, context):
    """Picks the destination sets (land and naval) this nation's units can be
    routed to, and tallies + weights how many units are already assigned to
    each one so orders spread out rather than piling onto one tile."""
    peace_borders = borders["peace_borders"]
    war_borders = borders["war_borders"]
    unclaimed_targets = borders["unclaimed_targets"]
    all_unclaimed_coasts = borders["all_unclaimed_coasts"]
    enemy_targets = borders["enemy_targets"]
    all_enemy_coasts = borders["all_enemy_coasts"]
    enemy_coastal_waters = borders["enemy_coastal_waters"]
    expedition_targets = borders["expedition_targets"]

    active_battles = battles["active_battles"]
    land_battles = active_battles - water_ids
    naval_expeditions = expedition_targets.intersection(water_ids).difference(active_battles, battles["lost_battles"]) if at_war else set()
    naval_battles = (active_battles & water_ids) | naval_expeditions
    friendly_convoys = battles["friendly_convoys"]
    convoy_in_combat = battles["convoy_in_combat"]
    convoy_near_ship = battles["convoy_near_ship"]
    convoy_near_coast = battles["convoy_near_coast"]

    # Ground units and convoys aim for land. Allied battles can also enter
    # through expedition_targets, so apply the restriction after combining them.
    ground_targets = unclaimed_targets | all_unclaimed_coasts | peace_borders | land_battles
    if at_war:
        ground_targets |= enemy_targets | all_enemy_coasts | expedition_targets
    target_destinations = list(ground_targets - water_ids)

    # Keep track of how many units are assigned to each target so we can spread them evenly
    target_assignments = {t_id: 0 for t_id in target_destinations}

    naval_destinations = list((enemy_coastal_waters | friendly_convoys | naval_battles) - land_battles)
    naval_assignments = {t_id: 0 for t_id in naval_destinations}

    # Convoy Escort Priority
    # Apply massive negative weights so warships heavily prioritize covering active convoys
    for c_id in friendly_convoys:
        if c_id in naval_assignments:
            naval_assignments[c_id] -= ai_tuning.AI_CONVOY_ESCORT_WEIGHT
            if c_id in convoy_in_combat:
                naval_assignments[c_id] -= ai_tuning.AI_CONVOY_COMBAT_WEIGHT
            elif c_id in convoy_near_ship:
                naval_assignments[c_id] -= ai_tuning.AI_CONVOY_DANGER_SHIP_WEIGHT
            elif c_id in convoy_near_coast:
                naval_assignments[c_id] -= ai_tuning.AI_CONVOY_DANGER_COAST_WEIGHT

    # How many units are really on each target, kept clear of the weights
    # below so _tile_pressure can ask whether a tile is full of fighters rather
    # than merely unpopular. Counted before the battle pull, which now needs to
    # know how full a tile already is.
    target_stacks = {t_id: 0 for t_id in target_destinations}
    naval_stacks = {t_id: 0 for t_id in naval_destinations}

    # Pre-count units already AT the targets
    for unit, prov in units_info:
        if prov["id"] in target_assignments:
            target_assignments[prov["id"]] += 1
            target_stacks[prov["id"]] += 1
        if prov["id"] in naval_assignments and _is_combat_ship(unit.get("type", ""), context=context):
            naval_assignments[prov["id"]] += 1
            naval_stacks[prov["id"]] += 1

    # Active Battle Reinforcement Priority, fading as the front and its relief
    # fill up.
    #
    # A flat pull said "this battle is worth 20 units" whatever the combat width
    # was, so a wider front drew no more men than a narrow one -- capping the
    # stack stopped the AI wasting bodies but never made it mass any. Scaling by
    # the share still empty means the pull runs out exactly where the tile stops
    # being able to use another body: at a front rank plus one relief rank. Same
    # strength as before on an empty tile, so a battle still outranks a quiet
    # border by the same margin it always did.
    for b_id in land_battles | naval_battles:
        assignments, stacks = (naval_assignments, naval_stacks) if b_id in naval_battles else (target_assignments, target_stacks)
        depth = _tile_depth(capacity, b_id)
        room = max(0, depth - stacks[b_id]) / depth
        assignments[b_id] -= ai_tuning.AI_REINFORCE_COMBAT_WEIGHT * room

    # Push the main army to the frontlines. Only keep 1 guard per peace
    # border during war or expansion. The guard stays at one whatever the combat
    # width is: a quiet border is a garrison, not a firing line.
    if at_war or unclaimed_targets:
        for p_id in peace_borders:
            if target_assignments.get(p_id, 0) >= 1:
                target_assignments[p_id] += ai_tuning.AI_REAR_GUARD_PENALTY

    # Penalize expedition targets so the AI defends its fronts first.
    for e_id in expedition_targets:
        if e_id in naval_expeditions:
            naval_assignments[e_id] += ai_tuning.AI_EXPEDITION_WEIGHT
        elif e_id in target_assignments and e_id not in enemy_targets and e_id not in war_borders:
            target_assignments[e_id] += ai_tuning.AI_EXPEDITION_WEIGHT

    return {
        "target_destinations": target_destinations,
        "naval_destinations": naval_destinations,
        "target_assignments": target_assignments,
        "naval_assignments": naval_assignments,
        "target_stacks": target_stacks,
        "naval_stacks": naval_stacks,
        "target_capacity": capacity or {},
    }


def _bombardment_target(context, ai_name, prov, bomb_range):
    """The in-range tile whose enemy stack is worth shelling most, or None."""
    world_state = world_for(context)
    best_id, best_value = None, 0.0
    in_range = queries.get_bombardment_targets(prov, world_state.id_to_province, bomb_range)

    for target_id in sorted(in_range):
        target = world_state.id_to_province.get(target_id)
        if not target:
            continue
        visible_units = queries.filter_visible_units(target.get("units", ()), ai_name, target, world_state.nation_data)
        value = sum(queries.calculate_unit_strength(u) for u in visible_units
                    if queries.are_at_war(ai_name, u.get("owner"), world_state.nation_data))
        if value > best_value:
            best_id, best_value = target_id, value

    return best_id


def _try_bombard(context, ai_name, unit, prov):
    """Orders a barrage if this unit has a gun and anything to point it at.

    Bombardment costs nothing, draws no return fire, and sits outside the lane
    system entirely -- it is the only thing in the game that reaches a unit
    waiting in reserve, which under the lane model is most of a deep stack. A
    bombarding unit still fights on its own tile, so the shot is pure profit. The AI had no
    bombardment code at all: it bought artillery, valued it for a barrage, and
    then walked it into melee to swing a melee attack a fraction the size.

    The order is reissued every turn, because process_bombardments clears it
    after firing and the best target moves.
    """
    bomb_range = queries.get_bombardment_range(unit.get("type", ""), context=context)
    if bomb_range <= 0:
        return False

    target_id = _bombardment_target(context, ai_name, prov, bomb_range)
    if target_id is None:
        return False

    unit_actions.apply_action(context, ai_name, prov, unit, {"type": "BOMBARD", "target_id": target_id}, authority="ai")
    return True


def _extend_fast_unit_path(context, unit, first_step, start_id, is_convoy, unsafe_waters, pressure, can_push_into):
    """Further steps for a unit faster than one tile, after its first step.

    Each step must pass queries.can_unit_move_step, the same rule the order
    owner applies, as well as the caller's `can_push_into` owner test. Returns
    the extra steps only; the caller issues the whole path and claims its end.
    """
    world_state = world_for(context)
    speed = queries.unit_movement_speed(unit)
    steps = []
    if speed <= 1:
        return steps
    curr_node = first_step
    for _ in range(speed - 1):
        curr_prov_data = world_state.id_to_province.get(curr_node)
        if not curr_prov_data: break

        next_options = []
        for n_id in curr_prov_data.get("neighbors", []):
            n_prov = world_state.id_to_province.get(n_id)
            if not n_prov: continue

            # Prevent backtracking
            if n_id == first_step or n_id in steps or n_id == start_id:
                continue

            # Obey movement rules using constants
            if is_convoy:
                if not queries.can_convoy_enter(curr_prov_data, n_prov) or n_id in unsafe_waters:
                    continue
            else:
                if queries.is_water_province(n_prov):
                    continue
            if not queries.can_unit_move_step(unit, curr_prov_data, n_prov,
                                              world_state.nation_data, context=context):
                continue

            # Check if it's a valid tile to push into
            if can_push_into(n_prov.get("owner", "Unclaimed")):
                next_options.append(n_id)

        if next_options:
            # Pick the adjacent tile with the least attackers to spread the advance
            next_step = min(next_options, key=pressure)
            steps.append(next_step)
            curr_node = next_step
        else:
            # Reached a dead end (e.g. hit an ocean or a claimed or friendly border)
            break
    return steps


def _assign_unit_orders(context, ai_name, units_info, ctx, allowed_prov_ids, water_ids, neighbor_ids):
    """Walks every one of this nation's units and assigns it a MOVE/CONVERT
    order: retreat from a lost battle, hold a defensive line, push into
    unclaimed or enemy territory next door, or path to the nearest tile that
    still needs reinforcing."""
    world_state = world_for(context)
    unsafe_waters = ctx["unsafe_waters"]
    friendly_nations = ctx["friendly_nations"]
    war_borders = ctx["war_borders"]
    peace_borders = ctx["peace_borders"]
    unclaimed_targets = ctx["unclaimed_targets"]
    active_battles = ctx["active_battles"]
    land_battles = active_battles - water_ids
    lost_battles = ctx["lost_battles"]
    at_war = ctx["at_war"]
    target_destinations = ctx["target_destinations"]
    naval_destinations = ctx["naval_destinations"]
    target_assignments = ctx["target_assignments"]
    naval_assignments = ctx["naval_assignments"]
    target_stacks = ctx["target_stacks"]
    naval_stacks = ctx["naval_stacks"]
    target_capacity = ctx["target_capacity"]
    havens = ctx.get("repair_havens", set())
    supply = ctx.get("supply")
    reserved = ctx.get("reserved_units", set())
    relief = ctx.get("relief_targets", set())
    factory_bonuses = ctx.get("factory_bonuses", {})
    # Enemy tiles where a fight would start. Only _reserve_strike_orders starts
    # one, with a group it has forecast; no unit here walks into one alone.
    new_fights = ctx.get("new_fights", set())
    # Where a wounded unit must not be routed: anywhere the fighting is.
    combat_destinations = (set(active_battles) | set(ctx.get("enemy_targets", ()))
                           | set(ctx.get("expedition_targets", ()))
                           | set(ctx.get("all_enemy_coasts", ())))
    # Amphibious routes can cross open water, but transports avoid visible
    # hostile fleets on the way to a landing.
    ground_route_ids = allowed_prov_ids.difference(unsafe_waters)
    path_cache = {}
    survival_cache = {}

    def claim(tile, from_tile=None):
        """Books one unit onto `tile`, freeing the tile it left.

        The counts have to move as orders are issued, not only reflect where
        everyone started, or the second unit this turn would see the same empty
        battle tile the first one did.
        """
        target_assignments[tile] = target_assignments.get(tile, 0) + 1
        target_stacks[tile] = target_stacks.get(tile, 0) + 1
        if from_tile is not None and from_tile in target_assignments:
            target_assignments[from_tile] -= 1
            target_stacks[from_tile] = max(0, target_stacks.get(from_tile, 0) - 1)

    def pressure(tile):
        return _tile_pressure(target_assignments, target_stacks, tile, target_capacity, factory_bonuses.get(tile, 0))

    def supplied_pressure(unit, tile):
        readiness, speed = supply.quality(unit, tile) if supply else (1.0, 1)
        return -readiness, -speed, pressure(tile)

    def retreat(unit, prov):
        """Falls back one step to the unit's own best tile. True if ordered."""
        tile = _retreat_tile(context, ai_name, unit, prov, friendly_nations,
                             unsafe_waters, havens, supply)
        if tile is None or not assign(unit, prov, [tile]):
            return False
        if tile not in water_ids:
            claim(tile, from_tile=prov["id"])
        return True

    def assign(unit, prov, path):
        if not _order_move(context, ai_name, prov, unit, path):
            return False
        if supply:
            supply.book(unit, path)
        return True

    def restore_supply(unit, prov, signature, wounded):
        current = supply.current(unit)
        candidates = [(tile, supply.quality(unit, tile)) for tile in prov.get("neighbors", ())
                      if tile in world_state.id_to_province and tile not in water_ids]
        candidates = [(tile, quality) for tile, quality in candidates
                      if quality > current or (not wounded and tile in relief)]
        for tile, _ in sorted(candidates, key=lambda choice: (-choice[1][0], -choice[1][1], choice[0] not in havens, pressure(choice[0]), choice[0])):
            visible_enemy = supply.known.occupants.get(tile, set()) & supply.enemies
            if visible_enemy and _attack_target_is_immediate_loss(context, ai_name, tile, unit, survival_cache, signature):
                continue
            if assign(unit, prov, [tile]):
                claim(tile, from_tile=prov["id"])
                return True
        return False

    for unit, prov in units_info:
        if id(unit) in reserved or not any(current is unit for current in prov.get("units", [])):
            continue
        attacker_signature = combat_rules.single_attacker_signature(unit)
        u_type = unit.get("type", "")
        is_convoy = u_type.startswith("Convoy")
        is_naval_combatant = _is_combat_ship(u_type, context=context)
        wounded = _is_wounded(unit)

        curr_id = prov["id"]

        # --- RETREAT FROM LOST BATTLES ---
        # Each unit picks its own tile; a unit with nowhere legal to go stays
        # and fights below.
        if curr_id in lost_battles and retreat(unit, prov):
            continue

        in_combat = queries.is_nation_in_combat_here(ai_name, prov, world_state.nation_data)

        if supply and not in_combat and not (is_convoy or is_naval_combatant):
            if curr_id in supply.critical and target_stacks.get(curr_id, 0) <= 1:
                _try_bombard(context, ai_name, unit, prov)
                continue
            if restore_supply(unit, prov, attacker_signature, wounded):
                continue

        if in_combat:
            # A convoy is a land unit mid-crossing with no business in a sea
            # fight, so it leaves any fight it is caught in. Warships decide
            # with the lane forecast above, like every other unit.
            if is_convoy and _visible_hostiles(context, ai_name, prov) and retreat(unit, prov):
                continue

            # Holding the line does not preclude firing: a bombarding unit still
            # fights on its own tile, so the barrage is pure profit. Tried only
            # after the retreat decisions above, so a unit that should be
            # withdrawing does not stand and shell instead.
            _try_bombard(context, ai_name, unit, prov)
            continue # Otherwise, hold the line and fight!

        # --- BOMBARDMENT ---
        # Free, draws no return fire, and the one thing not capped by combat
        # width, so a gun with anything in range has nothing better to do. An
        # adjacent enemy is inside range 1, which is what stops artillery
        # walking into a melee to swing a melee attack a fraction the size.
        if _try_bombard(context, ai_name, unit, prov):
            continue
        # -------------------

        # If we are the only unit on a peace border, hold the line.
        # Do not apply this to war_borders because we WANT to push forward into enemy_targets.
        is_defensive_hold = curr_id in peace_borders and curr_id not in war_borders

        # Break the hold if there's an active battle literally 1 tile away!
        # A wounded unit is not going to that battle, so it keeps the hold.
        is_near_battle = any(n in land_battles for n in prov.get("neighbors", []))
        if is_near_battle and not wounded:
            is_defensive_hold = False

        # The real number of units here, not the weighted assignment: the
        # rear-guard penalty adds AI_REAR_GUARD_PENALTY to a guarded quiet
        # border, which made every lone guard read as surplus and walk away.
        if not is_naval_combatant and is_defensive_hold:
            if target_stacks.get(curr_id, 0) <= 1:
                continue # Stay put!

        adjacent_unclaimed = [n for n in prov.get("neighbors", []) if n in unclaimed_targets]

        # PREVENT ILLEGAL CONVOY MOVES
        if is_convoy:
            adjacent_unclaimed = [n for n in adjacent_unclaimed if queries.can_convoy_enter(prov, world_state.id_to_province.get(n)) and n not in unsafe_waters]

        if adjacent_unclaimed and not is_naval_combatant:
            best_adj = min(adjacent_unclaimed, key=lambda tile: supplied_pressure(unit, tile))

            # Let fast units pathfind deeper into unclaimed territory!
            path = [best_adj] + _extend_fast_unit_path(
                context, unit, best_adj, curr_id, is_convoy, unsafe_waters, pressure,
                lambda owner: owner in c.UNOWNED_LAND_OWNERS)

            if supply and not is_convoy:
                path = supply.advance(unit, path)
            if assign(unit, prov, path):
                claim(path[-1], from_tile=curr_id)
                continue

        # A wounded unit does not charge: it would be the weakest body in the
        # fight, and this branch is what used to send a routed stack straight
        # back into the tile it had just fled.
        if at_war and not is_naval_combatant and not wounded:
            # Include expedition targets in the adjacent strike check so they can push off allied territory.
            # Empty enemy ground and fights already under way only: a new fight is the strike planner's.
            adjacent_targets = [n for n in prov.get("neighbors", []) if n in target_destinations and (n in ctx["enemy_targets"] or n in ctx["expedition_targets"])
                                and n not in new_fights]

            # PREVENT ILLEGAL CONVOY ATTACKS
            if is_convoy:
                adjacent_targets = [n for n in adjacent_targets if queries.can_convoy_enter(prov, world_state.id_to_province.get(n)) and n not in unsafe_waters]

            if adjacent_targets:
                adjacent_targets = [
                    target_id for target_id in adjacent_targets
                    if not _attack_target_is_immediate_loss(
                        context, ai_name, target_id, unit,
                        survival_cache, attacker_signature)
                    and (supply is None or supply.improves_reinforcement(unit, world_state.id_to_province[target_id]))
                ]
            if adjacent_targets:
                # Pick the adjacent enemy with the least attackers currently assigned
                best_adj = min(adjacent_targets, key=lambda tile: supplied_pressure(unit, tile))

                # Let fast units pathfind deeper from the border!
                path = [best_adj] + _extend_fast_unit_path(
                    context, unit, best_adj, curr_id, is_convoy, unsafe_waters, pressure,
                    lambda owner: (queries.is_hostile_territory(ai_name, owner, world_state.nation_data)
                                   or owner in c.UNOWNED_LAND_OWNERS))
                path = _short_of_new_fights(path, new_fights)

                if supply and not is_convoy:
                    path = supply.advance(unit, path)
                if assign(unit, prov, path):
                    claim(path[-1], from_tile=curr_id)
                    continue

        # Branch routing logic between ground forces and naval forces
        if is_naval_combatant:
            targets = naval_destinations
            assignments = naval_assignments
            stacks = naval_stacks
        else:
            targets = target_destinations
            assignments = target_assignments
            stacks = target_stacks

        # A wounded unit garrisons quiet tiles while it waits for a repair trip;
        # it is not routed toward any fight.
        if wounded:
            targets = [target_id for target_id in targets
                       if target_id not in combat_destinations]

        # Do not route a unit toward an occupied hostile tile if the first
        # exchange is guaranteed to kill that unit. Empty targets and fights
        # where the unit is not at war with anyone remain valid destinations.
        targets = [
            target_id for target_id in targets
            if not _attack_target_is_immediate_loss(
                context, ai_name, target_id, unit,
                survival_cache, attacker_signature)
            and (supply is None or target_id not in land_battles
                 or supply.improves_reinforcement(unit, world_state.id_to_province[target_id]))
        ]

        if not targets:
            continue

        # Bypass the depth limiter for fully garrisoned borders: drop anything
        # carrying the rear-guard penalty, and anything already holding a full
        # front and relief, since neither has anything to gain from one more body.
        priority_targets = [t for t in targets
                            if assignments.get(t, 0) < ai_tuning.AI_REAR_GUARD_PENALTY
                            and stacks.get(t, 0) < _tile_depth(target_capacity, t)]
        search_targets = priority_targets if priority_targets else targets

        # Route to the nearest border/enemy/coast/convoy that needs reinforcements
        path = _bfs_nearest_target(
            curr_id,
            set(search_targets),
            allowed_prov_ids if is_naval_combatant else ground_route_ids,
            world_state.id_to_province,
            assignments,
            is_convoy=is_convoy,
            is_ship=is_naval_combatant,
            moving_nation=ai_name,
            nation_data=world_state.nation_data,
            unit_speed=queries.unit_movement_speed(unit),
            water_ids=water_ids,
            neighbor_ids=neighbor_ids,
            target_stacks=stacks,
            target_capacity=target_capacity,
            path_cache=path_cache,
            factory_bonuses=None if is_naval_combatant else factory_bonuses,
        )

        if path:
            # Convoy Conversion Check
            next_prov = world_state.id_to_province.get(path[0])
            next_is_water = queries.is_water_province(next_prov)

            if next_is_water and not is_convoy and not is_naval_combatant:
                # Cannot step onto water, must explicitly convert first
                unit_actions.apply_action(context, ai_name, prov, unit, {"type": "CONVERT", "turns_left": 1, "to": "Convoy"}, authority="ai")
            else:
                # Truncate the AI's path to match its actual movement speed
                speed = queries.unit_movement_speed(unit)

                # PREVENT LAND UNITS QUEUEING INTO OCEAN MID-MOVE
                final_path = []
                for step_id in _short_of_new_fights(path[:speed], new_fights):
                    step_prov = world_state.id_to_province.get(step_id)
                    if not is_convoy and not is_naval_combatant and step_prov and queries.is_water_province(step_prov):
                        break
                    final_path.append(step_id)

                if not assign(unit, prov, final_path):
                    continue

            # Tell the system this unit is taking this target, reducing its
            # priority -- and filling a slot on it, so the next unit to look
            # sees a tile one body closer to full rather than the same one this
            # unit just claimed.
            if curr_id in assignments:
                assignments[curr_id] -= 1
                stacks[curr_id] = max(0, stacks.get(curr_id, 0) - 1)
            if path[-1] in assignments:
                assignments[path[-1]] += 1
                stacks[path[-1]] = stacks.get(path[-1], 0) + 1


def _repair_havens(context, ai_name, my_provs):
    """Factories where repairs can start, including factories on the front line."""
    return {province["id"] for province in my_provs
            if not unit_actions.repair_site_error(context, ai_name, province)}


def _march_havens(havens, ctx):
    """The subset of `havens` worth walking a wounded unit to.

    Marching is a choice about where to be, so here the war border does matter:
    arriving somewhere that is about to be attacked is the situation the unit
    was sent away from. Deciding this at the destination rather than in
    _repair_havens is what keeps a unit already standing on a front-line factory
    free to repair where it is.
    """
    return havens - ctx["war_borders"]


def _port_havens(context, ai_name, march_targets):
    """The march targets a warship can sail into: friendly coastal factories."""
    world_state = world_for(context)
    return {p_id for p_id in march_targets
            if world_state.id_to_province[p_id].get("is_coastal", False)
            and queries.can_ships_enter(ai_name, world_state.id_to_province[p_id],
                                        world_state.nation_data)}


def _start_repair(context, ai_name, province, unit):
    try:
        unit_actions.apply_action(context, ai_name, province, unit, {"type": "REPAIR"}, authority="ai")
    except ValueError:
        return False
    unit.pop("repair_trip", None)
    return True


def repair_docked_warships(context, ai_name, units_info):
    """Book affordable peacetime naval repairs before recruitment spends the stockpile."""
    candidates = [(unit, province) for unit, province in units_info
                  if province.get("owner") == ai_name and province.get("is_coastal", False)
                  and 0 < _health_fraction(unit) < ai_tuning.AI_REPAIR_ON_SITE_FRACTION
                  and _is_combat_ship(unit.get("type", ""), context=context)
                  and _can_replan_unit(context, unit)]
    havens = _repair_havens(context, ai_name, (province for _, province in candidates))
    for unit, province in candidates:
        if province["id"] in havens:
            _start_repair(context, ai_name, province, unit)


def _may_leave_the_line(context, ai_name, unit, prov, ctx):
    """Whether this wounded unit can be spared for the trip to a factory.

    The repair trip deliberately takes a unit away from the war, so it must
    never open a hole: the last unit on a tile is that tile's defence and
    stays. A unit in a battle is decided by _wounded_who_can_leave, which asks
    whether the front stays covered.

    A war border, or a tile next to a battle, used to keep every unit on it.
    That kept the wounded where they were most needed to be gone: a stack that
    fell back from a lost battle stood next to it, could not leave, and was
    sent straight back in.
    """
    if prov["id"] in ctx["active_battles"]:
        return False
    friendly_nations = ctx["friendly_nations"]
    return any(u.get("owner") in friendly_nations and u is not unit
               for u in prov.get("units", ()))


def _wounded_who_can_leave(context, ai_name, units_info):
    """Wounded units that may walk out of a battle without uncovering its front.

    Per battle tile: the nation must keep enough units on the tile to fill the
    front slots it holds now (combat_rules.slots_held), and at least one of the
    units that stay must not be wounded. The most wounded leave first. Returns
    the leavers' ids.
    """
    world_state = world_for(context)
    nation_data = world_state.nation_data
    tiles = {}
    for unit, prov in units_info:
        if (_is_wounded(unit) and not unit.get("type", "").startswith("Convoy")
                and not queries.unit_is_air_drop_recovering(unit)
                and queries.is_nation_in_combat_here(ai_name, prov, nation_data)):
            tiles.setdefault(prov["id"], (prov, []))[1].append(unit)

    leavers = set()
    for prov, wounded in tiles.values():
        everyone = [u for u in prov.get("units", ())
                    if queries.get_unit_combat_owner(u) == ai_name and u.get("health", 0) > 0]
        battle = combat_rules.build_battle([prov.get("units", ())], nation_data,
                                           terrain=prov.get("terrain"))
        spare = len(everyone) - combat_rules.slots_held(battle, ai_name)
        staying = list(everyone)
        for unit in sorted(wounded, key=_health_fraction):
            if spare <= 0:
                break
            rest = [u for u in staying if u is not unit]
            if not any(not _is_wounded(u) for u in rest):
                break
            leavers.add(id(unit))
            staying = rest
            spare -= 1
    return leavers


def _assign_maintenance_orders(context, ai_name, units_info, ctx,
                               allowed_prov_ids, water_ids, neighbor_ids):
    """Sends wounded or idle units to repair or upgrade instead of a move order.

    Mirrors what a human player would click in the orders panel. Four triggers:

    - Wounded, and already standing somewhere it can be fixed: below
      ai_tuning.AI_REPAIR_ON_SITE_FRACTION health, on a haven (see _repair_havens). A
      unit this hurt deals reduced damage now (see
      combat_rules.health_damage_multiplier), so it is worth less in the next
      fight than the same unit at full health -- fixing it is worth the turn.
    - Wounded, and not: below the harder ai_tuning.AI_REPAIR_HEALTH_FRACTION line it is
      worth the trip as well, so it is sent home. Land units march overland;
      warships sail to their own coastal factories (_port_havens), even when
      they are alone on a water tile. At peace warships use the on-site cutoff
      to start a repair trip.
    - Wounded, in a battle the rest of the stack can hold: it steps out to its
      best retreat tile and starts the trip from there (_wounded_who_can_leave).
    - Idle: on a quiet tile with no battle nearby and nothing else routed
      through it, with research holding a better version of its type. A unit
      that was going to do nothing this turn anyway loses nothing by upgrading.

    Chosen units are dropped from `units_info` in place, so _assign_unit_orders
    never reassigns them a move order this turn. Repairing and upgrading only
    block movement (c.ORDERS_BLOCKING_MOVEMENT) -- the unit is still standing on
    its tile and still fights if it is attacked -- so this never actually leaves
    a front unmanned, only unmoving for a turn.

    **The trip.** Repair requires industry on the tile a unit is standing on,
    so the AI walks wounded units to one. A unit that commits to the trip
    carries `unit["repair_trip"]`, which is a plain key rather than an order
    because _reset_orders_and_collect_units wipes orders every turn and the walk
    home takes several -- the unit would be re-tasked back to the front at the
    first junction. It is handled before anything else here, and dropped the
    moment it stops making sense.
    """
    world_state = world_for(context)
    world = ai_world.for_screen(context)
    unit_library = queries.get_unit_library(context)
    path_cache = {}
    tech_tree = queries.get_tech_tree(context)
    naval_repair_trip_cutoff = (ai_tuning.AI_REPAIR_HEALTH_FRACTION
                                if queries.get_enemies(ai_name, world_state.nation_data)
                                else ai_tuning.AI_REPAIR_ON_SITE_FRACTION)

    war_borders = ctx["war_borders"]
    active_battles = ctx["active_battles"]
    unsafe_waters = ctx["unsafe_waters"]
    target_assignments = ctx["target_assignments"]
    havens = ctx["repair_havens"]
    supply = ctx.get("supply")
    march_targets = _march_havens(havens, ctx)
    port_targets = _port_havens(context, ai_name, march_targets)
    leavers = _wounded_who_can_leave(context, ai_name, units_info)
    trip_tiles = set(allowed_prov_ids) - set(active_battles)
    ship_trip_tiles = trip_tiles.difference(unsafe_waters) if unsafe_waters else trip_tiles

    def route(unit, curr_id, targets, is_ship):
        """A trip to the nearest of `targets`, or None.

        A land unit walks overland only: a land route over water needs the
        CONVERT-to-Convoy dance _assign_unit_orders does for an invasion, and
        none of that is worth it to fix one division. A warship sails around
        visible enemy fleets. A convoy is a land unit mid-crossing that should
        finish the crossing first, so it never starts a trip. No trip passes
        through an active battle.
        """
        if not targets:
            return None
        if supply and not is_ship:
            best_supply = max(supply.quality(unit, tile) for tile in targets)
            best_targets = {tile for tile in targets if supply.quality(unit, tile) == best_supply}
            if best_targets != targets:
                best_path = route(unit, curr_id, best_targets, is_ship)
                if best_path:
                    return best_path
        path = _bfs_nearest_target(
            curr_id, set(targets), ship_trip_tiles if is_ship else trip_tiles, world_state.id_to_province,
            target_assignments, is_ship=is_ship,
            moving_nation=ai_name, nation_data=world_state.nation_data,
            unit_speed=queries.unit_movement_speed(unit),
            water_ids=water_ids, neighbor_ids=neighbor_ids, path_cache=path_cache)
        if not path or (not is_ship and any(step in water_ids for step in path)):
            return None
        return path

    # Units already on a trip count against the cap, so a nation cannot send
    # its whole army back one turn at a time. The cap scales with the army.
    trips = sum(1 for unit, _prov in units_info if unit.get("repair_trip") is not None)
    trip_cap = max(1, int(len(units_info) * ai_tuning.AI_MAX_REPAIR_TRIP_SHARE))

    remaining = []
    reserved = ctx.get("reserved_units", set())
    for unit, prov in units_info:
        if id(unit) in reserved:
            remaining.append((unit, prov))
            continue
        curr_id = prov["id"]
        in_combat = queries.is_nation_in_combat_here(ai_name, prov, world_state.nation_data)
        speed = queries.unit_movement_speed(unit)
        u_type = unit.get("type", "")
        is_convoy = u_type.startswith("Convoy")
        is_naval_combatant = _is_combat_ship(u_type, context=context)
        travels = not is_convoy
        trip_targets = port_targets if is_naval_combatant else march_targets
        trip_cutoff = naval_repair_trip_cutoff if is_naval_combatant else ai_tuning.AI_REPAIR_HEALTH_FRACTION

        # --- a trip already under way ---------------------------------------
        trip = unit.get("repair_trip")
        if trip is not None:
            if _health_fraction(unit) >= ai_tuning.AI_REPAIR_ON_SITE_FRACTION or trip not in havens:
                # Healed on the way, or the destination was taken, overrun, or
                # lost its industry while the unit was still walking to it.
                unit.pop("repair_trip", None)
                trips -= 1
            elif curr_id == trip:
                if _start_repair(context, ai_name, prov, unit):
                    trips -= 1
                    continue
            else:
                path = route(unit, curr_id, {trip}, is_naval_combatant)
                if path and _order_move(context, ai_name, prov, unit, path[:speed]):
                    if supply:
                        supply.book(unit, path[:speed])
                    continue
                # The way home is cut. Fight where it stands.
                unit.pop("repair_trip", None)
                trips -= 1

        if in_combat:
            # Out of the fight first, then home from the retreat tile.
            if id(unit) in leavers and trips < trip_cap:
                tile = _retreat_tile(context, ai_name, unit, prov, ctx["friendly_nations"],
                                     unsafe_waters, havens, supply)
                if tile is not None and _order_move(context, ai_name, prov, unit, [tile]):
                    if supply:
                        supply.book(unit, [tile])
                    home = route(unit, tile, trip_targets, is_naval_combatant)
                    if home or tile in havens:
                        unit["repair_trip"] = tile if tile in havens else home[-1]
                        trips += 1
                    continue
            remaining.append((unit, prov))
            continue

        # --- repair, here or at home -----------------------------------------
        wants_repair = False
        if curr_id in havens:
            if _health_fraction(unit) < ai_tuning.AI_REPAIR_ON_SITE_FRACTION:
                wants_repair = True
                if _start_repair(context, ai_name, prov, unit):
                    continue
        elif (travels
                and trip_targets
                and trips < trip_cap
                and _health_fraction(unit) < trip_cutoff
                and ((is_naval_combatant and curr_id in water_ids)
                     or _may_leave_the_line(context, ai_name, unit, prov, ctx))):
            path = route(unit, curr_id, trip_targets, is_naval_combatant)
            if path and _order_move(context, ai_name, prov, unit, path[:speed]):
                if supply:
                    supply.book(unit, path[:speed])
                unit["repair_trip"] = path[-1]
                trips += 1
                continue

        # --- upgrade, if it has nothing better to do -------------------------
        # Quiet rear tiles as well as quiet borders. Reading this as "on a peace
        # or coastal border" excluded every interior province -- which is
        # exactly where a nation's factories and their garrisons are, so the one
        # unit in the country with nothing to do all game could never upgrade.
        is_quiet = curr_id not in war_borders and curr_id not in active_battles
        is_near_battle = any(n in active_battles for n in prov.get("neighbors", ()))
        # A unit that wanted repairing and could not afford it must not be sent
        # to upgrade instead: a completed UPGRADE order carries health across as a
        # *percentage*, so it would spend the turn and still be wounded, only
        # now wounded as a more expensive type.
        #
        # A haven is a factory tile of ours with no enemy on it, which is
        # exactly the pair of conditions the player's orders panel spells out as
        # "Needs Factory" and "In Combat". The AI used to skip that half of the
        # rule entirely and upgrade wherever a unit happened to be idle -- which
        # is how two American divisions re-equipped themselves to Infantry Type
        # 1943 while adrift in the sea off Spain in saves/HOW DO YOU LAUNCH
        # ARTILLERY FROM THE OCEAN.
        is_idle = (not is_naval_combatant and curr_id in havens
                  and is_quiet and not is_near_battle
                  and not wants_repair
                  and target_assignments.get(curr_id, 0) <= 1)

        if is_idle:
            target = world.upgrade_target(ai_name, u_type, unit_library, tech_tree)
            if target:
                unit_actions.apply_action(context, ai_name, prov, unit, {"type": "UPGRADE", "turns_left": 1,
                                 "target_type": target, "refund": {}}, authority="ai")
                continue

        remaining.append((unit, prov))

    units_info[:] = remaining


def _rotate_damaged_units(context, ai_name, active_battles):
    """Pulls shot-up units out of the front rank when a fresh one can take the slot.

    The only thing the lane model asks of a commander that movement cannot
    express. A reserve takes no damage, so a unit down to a
    fraction of its health is worth more waiting than standing -- but only if
    somebody healthier is behind it, since an empty slot is worse than a hurt one
    and an uncovered lane dissolves entirely.

    Without this the AI would field its casualties until they died while a human
    rotated theirs, which is a real edge and an invisible one.
    """
    world_state = world_for(context)
    for prov_id in active_battles:
        province = world_state.id_to_province.get(prov_id)
        if not province:
            continue

        mine = [u for u in province.get("units", ()) if u.get("owner") == ai_name
                and not queries.is_tactical_player_unit(context, u)
                and not queries.unit_is_air_drop_recovering(u)]
        if len(mine) < 2:
            continue

        # Last turn's stances go before the measurement, not after it. Read the
        # other way round this ratcheted: build_battle saw the units already
        # held back, slots_held answered with the allowance that left, spare was
        # recomputed from that smaller number, and the reserve could only ever
        # grow. A nation pushed down once never climbed back -- three of the
        # four short fronts in saves/province 907 are stuck there.
        for unit in mine:
            unit.pop("combat_stance", None)

        battle = combat_rules.build_battle(
            [province.get("units", ())], world_state.nation_data,
            terrain=province.get("terrain"))
        # Anything past the slots is standing in reserve regardless, so that is
        # exactly how many units can be held back without leaving one empty.
        # The worst-hurt go first.
        for unit in combat_rules.rotation_reserves(battle, ai_name, mine):
            unit["combat_stance"] = "RESERVE"


def _cancel_opposing_transitions(ai_nations, nation_units, contested=None):
    """Anti-swap cleanup: if a unit is ordered A->B and another (identical
    type and health) is ordered B->A, cancel both -- otherwise they'd cross
    paths and swap tiles instead of actually contesting either one.

    A tile with a fight on it is exempt in both directions. Two units passing
    each other between quiet tiles have achieved nothing and may as well stay
    put; a garrison pulling out of a battle while a reserve marches in is the
    relief working exactly as intended, and cancelling it left the wounded unit
    standing in the fight AND the fresh one standing behind it -- the same pair,
    every turn, forever.
    """
    contested = contested or set()
    for ai_name in ai_nations:
        units_info = nation_units[ai_name]

        # Track where every unit is trying to go for this specific nation
        transitions = {}
        for unit, prov in units_info:
            path = unit.get("order", {}).get("path", [])
            if path:
                src_id = prov["id"]
                dest_id = path[0]
                if src_id in contested or dest_id in contested:
                    continue
                transitions.setdefault((src_id, dest_id), []).append(unit)

        # Check for opposing traffic
        processed = set()
        for (src, dest), fwd_units in transitions.items():
            if (src, dest) in processed: continue

            bwd_units = transitions.get((dest, src), [])
            if bwd_units:
                # Match up identical unit types AND health
                fwd_types = {}
                for u in fwd_units:
                    # Using int() on health prevents floating point mismatch errors
                    key = (u.get("type", ""), int(u.get("health", 0)))
                    fwd_types.setdefault(key, []).append(u)

                bwd_types = {}
                for u in bwd_units:
                    key = (u.get("type", ""), int(u.get("health", 0)))
                    bwd_types.setdefault(key, []).append(u)

                # Cancel pairs of identical units
                for u_key, f_list in fwd_types.items():
                    b_list = bwd_types.get(u_key, [])
                    cancel_count = min(len(f_list), len(b_list))

                    for i in range(cancel_count):
                        f_list[i]["order"]["path"] = []
                        b_list[i]["order"]["path"] = []

            processed.add((src, dest))
            processed.add((dest, src))


def _generate_unit_orders(context, *, countries=None):
    world_state = world_for(context)
    session_state = session_for(context)
    ai_nations = queries.get_active_ai_nations(context) if countries is None else countries
    session_state.progress["movement_tasks"].total = len(ai_nations)
    session_state.progress["movement_tasks"].completed = 0
    world = ai_world.for_screen(context)

    # --- NEW: Pre-calculate allowed pathing IDs to include water for convoys ---
    # Doubles as the water lookup the pathfinder uses per tile.
    allowed_prov_ids_cache, water_ids, neighbor_ids = _build_shared_pathing_caches(context)

    nation_units, nation_provs = _reset_orders_and_collect_units(context, ai_nations)
    actual_supply = queries.SupplySnapshot(context)

    # Every tile somebody is fighting over this turn, pooled across nations so
    # the anti-swap pass at the end can leave relief traffic alone.
    contested = set()

    for completed, ai_name in enumerate(ai_nations):
        # The previous country's pass finished, including any no-order early exit.
        session_state.progress["movement_tasks"].completed = completed
        units_info = nation_units[ai_name]
        if not units_info:
            continue

        visible = world.visible_provinces(ai_name)
        factories = _factory_objectives(context, ai_name, visible, world.provs_by_owner)
        best_factory = max((value for value, _ in factories.values()), default=1)
        known_supply = queries.SupplySnapshot(context, visible_to=ai_name, visible_provinces=visible, source=actual_supply)
        with queries.combat_supply(known_supply if visible is None else None):
            cargo_changed = _assign_air_orders(context, ai_name, units_info, factories=factories,
                                              known_supply=known_supply, actual_supply=actual_supply)
        if cargo_changed:
            actual_supply = queries.SupplySnapshot(context, source=actual_supply)
            known_supply = queries.SupplySnapshot(context, visible_to=ai_name, visible_provinces=visible, source=actual_supply)
        units_info = [(unit, base) for unit, base in units_info
                      if not queries.is_air_unit(unit, context=context) and not queries.is_air_transport(unit, context=context)
                      and any(current is unit for current in base.get("units", []))]
        if not units_info:
            continue

        my_provs = nation_provs[ai_name]

        supply = ai_supply.SupplyPlanner(actual_supply, known_supply, ai_name)
        with queries.combat_supply(supply):
            # Combine land and water IDs so BFS can route overseas
            # Include ALL legally passable tiles so the AI isn't blind!
            allowed_prov_ids = set(allowed_prov_ids_cache)
            allowed_prov_ids.update(world.land_entry_ids(ai_name))

            enemies = _gather_enemies(context, ai_name)

            # --- NEW: IDENTIFY UNSAFE WATERS FOR NAVAL SURVIVAL ---
            unsafe_waters = _compute_unsafe_waters(context, ai_name)

            # --- Identify Friendly Nations for Expedition Logic ---
            friendly_nations = queries.get_all_friendly_nations(ai_name, world_state.nation_data)

            borders = _discover_borders_and_targets(context, ai_name, my_provs, enemies, friendly_nations)

            at_war = len(enemies) > 0 and (len(borders["enemy_targets"]) > 0 or len(borders["all_enemy_coasts"]) > 0 or len(borders["expedition_targets"]) > 0)

            # Factory tiles this nation could repair on. Retreats prefer them, so
            # they are known before the battles are read.
            havens = _repair_havens(context, ai_name, my_provs)

            # --- FIND ACTIVE BATTLES, RETREATS & CONVOY STATUS ---
            battles = _track_battles_and_convoys(context, ai_name, units_info, friendly_nations,
                                                 unsafe_waters, borders["all_enemy_coasts"],
                                                 borders["enemy_coastal_waters"], havens, supply)

            # What each destination's fight can actually seat for us, asked of the
            # combat rules rather than restated here. A tile splitting three ways
            # gives us fewer slots than one where we face a single enemy.
            capacity = {
                t_id: combat_rules.nation_front_capacity(
                    ai_name, world_state.id_to_province[t_id], world_state.nation_data)
                for t_id in battles["active_battles"]
                if t_id in world_state.id_to_province
            }

            assignments = _build_target_assignments(units_info, borders, battles, at_war, capacity, water_ids=water_ids, context=context)

            relief = supply.relief_targets(borders["enemy_targets"] | borders["unclaimed_targets"])
            for tile in supply.critical | relief:
                if tile not in assignments["target_destinations"]:
                    assignments["target_destinations"].append(tile)
                counts = assignments["target_assignments"]
                stacks = assignments["target_stacks"]
                stacks.setdefault(tile, sum(1 for unit, province in units_info if province["id"] == tile))
                counts.setdefault(tile, stacks[tile])
                if not stacks[tile]:
                    counts[tile] -= ai_tuning.AI_REINFORCE_COMBAT_WEIGHT

            ctx = {
                "supply": supply,
                "factory_bonuses": {tile: value / best_factory for tile, (value, _) in factories.items()},
                "relief_targets": relief,
                "unsafe_waters": unsafe_waters,
                "friendly_nations": friendly_nations,
                "at_war": at_war,
                **borders,
                **battles,
                **assignments,
            }
            ctx["repair_havens"] = havens
            beaches = {province["id"] for province in my_provs if province.get("is_coastal")}
            reserved, threats, convoy_sites = _reserve_naval_orders(context, ai_name, units_info, supply, beaches)
            for unit, origin in units_info:
                if id(unit) not in reserved or not (path := unit["order"]["path"]):
                    continue
                for tile, delta in ((origin["id"], -1), (path[-1], 1)):
                    if tile in assignments["naval_assignments"]:
                        assignments["naval_assignments"][tile] += delta
                        assignments["naval_stacks"][tile] += delta
            warnings = {beach: approaches for beach, approaches in borders["coastal_approaches"].items() if beach not in convoy_sites}
            if warnings or threats:
                reserved.update(_reserve_coastal_guards(context, ai_name, units_info, supply, warnings, threats, ctx))
            ctx["reserved_units"] = reserved

            _assign_maintenance_orders(context, ai_name, units_info, ctx,
                                       allowed_prov_ids, water_ids, neighbor_ids)
            _reserve_land_supply_orders(context, ai_name, units_info, supply, ctx, reserved)
            _reserve_strike_orders(context, ai_name, units_info, ctx, reserved, allowed_prov_ids - water_ids)

            # Units can need to retreat or restore supply without an offensive target.
            if not (assignments["target_destinations"] or assignments["naval_destinations"] or battles["lost_battles"]
                    or ai_name in known_supply.land_units):
                continue

            _assign_unit_orders(context, ai_name, units_info, ctx, allowed_prov_ids, water_ids, neighbor_ids)
            _rotate_damaged_units(context, ai_name, battles["active_battles"])

            contested |= set(battles["active_battles"])
            contested |= set(battles["lost_battles"])

    # --- Anti-Swap Cleanup ---
    _cancel_opposing_transitions(ai_nations, nation_units, contested)
    # Keep the final country pending until shared order cleanup also finishes.
    session_state.progress["movement_tasks"].completed = session_state.progress["movement_tasks"].total
