# --- START OF FILE CHANGES ---
from data.state_access import world_for, session_for
import heapq
import data.constants as c
from data import queries
from map_logic.actions import unit_actions
from map_logic.ai import ai_unit_eval, ai_world
from map_logic.system32 import combat_forecast, combat_rules


def _health_fraction(unit):
    return unit.get("health", 0) / max(1.0, unit.get("max_health", 1))


def _is_wounded(unit):
    """Hurt badly enough to be sent to repair rather than into a fight."""
    return _health_fraction(unit) < c.AI_REPAIR_HEALTH_FRACTION


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


def legal_air_candidates(context, unit, base):
    """Only canonical orders are ever offered to heuristic/model consumers."""
    world_state = world_for(context)
    candidates = []
    if not queries.air_unit_can_launch(context, unit, base):
        return candidates
    if queries.air_unit_can_patrol(unit, context=context):
        candidates.append(queries.canonical_air_order(context, unit, base,
            {"type": "AIR_PATROL", "priority": queries.AIR_DEFAULT_PRIORITY}))
    for kind in queries.AIR_TARGET_MISSION_TYPES.values():
        for target_id in sorted(queries.get_air_targets(context, unit, base, kind)):
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
        if queries.get_scenario_flag("fog_of_war", c.DEFAULT_FOG_OF_WAR, context.scenario_settings) and visible is not None and province["id"] not in visible:
            continue
        for unit in queries.filter_visible_units(province.get("units", []), country,
                                                 province, world_state.nation_data):
            if (unit.get("health", 0) <= 0 or queries.is_air_unit(unit, context=context)
                    or not queries.are_at_war(country, queries.get_unit_combat_owner(unit), world_state.nation_data)):
                continue
            reached = {province["id"]}
            frontier = [province]
            for _step in range(unit.get("speed", c.DEFAULT_UNIT_SPD)):
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
        terrain=target.get("terrain") if target else None)
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
                                             world_state.map_data, library)
            value += sum(stats.get(f"cost_{resource}", 0) for resource in ai_unit_eval.RESOURCES)
    return value


def _air_patrol_threats(context, country, visible):
    """Possible strikes on our land or troops, without reading enemy orders."""
    world_state = world_for(context)
    protected = {province["id"] for province in world_state.map_data.values()
                 if province.get("owner") == country or any(
                     queries.get_unit_combat_owner(unit) == country and unit.get("health", 0) > 0
                     for unit in province.get("units", []))}
    threats = {}
    for base in world_state.map_data.values():
        if queries.get_scenario_flag("fog_of_war", c.DEFAULT_FOG_OF_WAR, context.scenario_settings) and visible is not None and base["id"] not in visible:
            continue
        for unit in queries.filter_visible_units(base.get("units", []), country, base, world_state.nation_data):
            if (unit.get("health", 0) <= 0 or not queries.is_air_unit(unit, context=context)
                    or queries.air_unit_stats(unit, context=context).get("air_interception_immune")
                    or not queries.are_at_war(country, queries.get_unit_combat_owner(unit), world_state.nation_data)
                    or not queries.air_unit_can_launch(context, unit, base)):
                continue
            for target_id in protected.intersection(queries.get_air_targets(context, unit, base, "AIR_ATTACK")):
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
    strike (documentation/air_stuff.txt, Interception). So a patrol earns the
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
    if _health_fraction(unit) >= c.AI_REPAIR_ON_SITE_FRACTION:
        return None
    nation = world_state.nation_data[country]
    if (base.get("owner") == country and queries.has_industry(base)
            and base["id"] not in threatened):
        if queries.can_afford(nation, unit_actions.repair_costs(context, unit)):
            return {"type": "REPAIR"}
        return None
    factories = [order for order in candidates
                 if order["type"] == "AIR_REPOSITION" and order["target_id"] not in threatened
                 and world_state.id_to_province[order["target_id"]].get("owner") == country
                 and queries.has_industry(world_state.id_to_province[order["target_id"]])]
    if not factories:
        return None
    return min(factories, key=lambda order: (
        queries.air_distance_squared(context, base, order["target_id"]), order["target_id"]))


def _assign_air_orders(context, country, units_info):
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
    visible = ai_world.visible_to(world_state.map_data, world_state.nation_data,
                                  world_state.id_to_province, country)
    enemies = [province for province in world_state.map_data.values()
               if (not queries.get_scenario_flag("fog_of_war", c.DEFAULT_FOG_OF_WAR, context.scenario_settings) or visible is None or province["id"] in visible)
               and queries.air_target_is_hostile({"owner": country}, province,
                   world_state.nation_data, visible_only=True)]
    threatened = _air_base_threats(context, country, visible)
    unit_library = queries.get_unit_library(context)
    tech_tree = queries.get_tech_tree(context)
    research = world_state.nation_data[country].get("research", {})
    patrol_threats = _air_patrol_threats(context, country, visible)
    patrol_cover = {}
    strike_cover = {}
    protection_scores = {}
    strike_scores = {}
    for unit, base in units_info:
        if not queries.is_tactical_player_unit(context, unit):
            continue
        order = unit.get("order") or {}
        if order.get("type") == "AIR_PATROL":
            for target_id in queries.get_air_targets(context, unit, base, "AIR_PATROL"):
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
        candidates = legal_air_candidates(context, unit, base)
        safe_repositions = [order for order in candidates if order["type"] == "AIR_REPOSITION"
                            and order["target_id"] != base["id"] and order["target_id"] not in threatened]
        if base["id"] in threatened and safe_repositions:
            unit_actions.apply_action(context, country, base, unit, min(safe_repositions, key=lambda order: (
                queries.air_distance_squared(context, base, order["target_id"]), order["target_id"])), authority="ai")
            continue
        if queries.air_unit_can_transport(unit, context=context):
            _assign_air_transport(context, country, unit, base, safe_repositions, enemies, all_units_info)
            continue
        repair = _aircraft_repair_order(context, country, unit, base, threatened, candidates)
        if repair:
            unit_actions.apply_action(context, country, base, unit, repair, authority="ai")
            continue
        # A wounded aircraft is not upgraded: an upgrade keeps the health
        # percentage, so it would spend the turn and still be wounded.
        if (base["id"] not in threatened and queries.has_industry(base)
                and _health_fraction(unit) >= c.AI_REPAIR_ON_SITE_FRACTION):
            target = queries.get_upgrade_target(unit["type"], research, unit_library, tech_tree)
            if target:
                unit_actions.apply_action(context, country, base, unit, queries.canonical_unit_order(context, country, base, unit,
                    {"type": "UPGRADE", "target_type": target}), authority="ai")
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
            coverage = queries.get_air_targets(context, unit, base, "AIR_PATROL")
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
            for target_id in queries.get_air_targets(context, unit, base, "AIR_PATROL"):
                patrol_cover.setdefault(target_id, []).append(unit)


def _assign_air_transport(context, country, plane, base, repositions, enemies, units_info):
    """Drop ground reinforcements on viable enemy land or use accessible bases."""
    world_state = world_for(context)
    cargo = plane.get("air_cargo", [])
    selected = cargo or sorted((unit for unit in base.get("units", [])
        if queries.air_cargo_is_eligible(plane, unit, context=context)
        and not queries.is_tactical_player_unit(context, unit)
        and not queries.unit_has_active_order(unit)),
        key=queries.calculate_unit_strength, reverse=True)[:queries.air_transport_capacity(plane, context=context)]
    # Evaluate a possible load without changing state when no flight is useful.
    loaded = dict(plane, air_cargo=selected)
    dropped = [dict(unit) for unit in selected]
    for unit in dropped:
        queries.begin_air_drop_recovery(unit, world_state.scenario_settings)
    drops = []
    for target in enemies:
        if (not queries.air_drop_target_is_legal(loaded, target, world_state.nation_data)
                or not queries.air_target_in_range(context, loaded, base, "AIR_DROP", target["id"])):
            continue
        visible_target = dict(target, units=queries.filter_visible_units(
            target.get("units", []), country, target, world_state.nation_data))
        if _attackers_would_survive(context, country, visible_target, dropped):
            drops.append(queries.canonical_air_order(context, loaded, base,
                {"type": "AIR_DROP", "target_id": target["id"]}))
    if drops:
        if not cargo:
            queries.ensure_unit_ids(world_state.map_data)
            queries.set_air_cargo(context, country, plane, base, [unit["unit_id"] for unit in selected])
        unit_actions.apply_action(context, country, base, plane, min(drops, key=lambda order: (
            queries.air_distance_squared(context, base, order["target_id"]), order["target_id"])), authority="ai")
        return
    target = min(enemies, key=lambda p: (queries.air_distance_squared(context, base, p["id"]), p["id"])) if enemies else None
    destination = min(repositions, key=lambda order: (
        queries.air_distance_squared(context, world_state.id_to_province[order["target_id"]], target["id"]),
        order["target_id"])) if target and repositions else None
    improves = destination and queries.air_distance_squared(
        context, world_state.id_to_province[destination["target_id"]], target["id"]) < queries.air_distance_squared(
            context, base, target["id"])
    if cargo and not improves:
        released = list(cargo)
        queries.set_air_cargo(context, country, plane, base, [])
        units_info.extend((unit, base) for unit in released)
        return
    if not improves:
        return
    if not cargo:
        if not selected:
            return
        queries.ensure_unit_ids(world_state.map_data)
        queries.set_air_cargo(context, country, plane, base, [unit["unit_id"] for unit in selected])
    unit_actions.apply_action(context, country, base, plane, destination, authority="ai")


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


def _tile_pressure(assignments, stacks, tile, capacity=None):
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
            assignments.get(tile, 0))


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
    sea_step = 1.0 * c.AI_SEA_PATH_PENALTY_MULTIPLIER
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


def _bfs_nearest_target(start_id, target_ids, allowed_prov_ids, id_to_province, target_assignments, is_convoy=False, is_ship=False, moving_nation=None, nation_data=None, unsafe_waters=None, unit_speed=1.0, water_ids=None, neighbor_ids=None, target_stacks=None, target_capacity=None, path_cache=None):
    """Finds shortest path using Dijkstra. Returns the path to the target with the least units assigned."""
    if unsafe_waters is None:
        unsafe_waters = {}
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
        best_cell = min(valid_paths,
                        key=lambda p: _tile_pressure(target_assignments, target_stacks, p[1][0],
                                                     target_capacity) + (p[0],))[1]

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

def process_ai_unit_orders(context):
    """Generates movement orders for AI-controlled units to balance borders, attack, or escort."""
    # Order generation only reads the diplomatic picture -- it writes unit orders
    # and nothing else -- so faction and alliance membership can be resolved once
    # for the whole pass instead of once per pathfinding edge.
    with queries.diplomacy_snapshot():
        _generate_unit_orders(context)


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
            if queries.is_tactical_player_unit(context, unit):
                continue
            order = unit.get("order")
            if isinstance(order, dict) and order.get("type") in c.MULTI_TURN_ORDER_TYPES:
                continue  # Already committed; leave it be and do not re-task it.

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


def _threatened_coasts(context, ai_name, prov_ids, enemies, friendly_nations):
    """The coastal tiles in `prov_ids` an enemy could land on soon.

    A tile is threatened when, within AI_NEARBY_SEA_TILES of water from it,
    one of `enemies` owns a shore or has units this nation can see. Lakes
    count: a convoy can cross one. Friendly naval supremacy in that water
    removes the threat -- visible friendly warship strength at least
    AI_COAST_SUPREMACY_RATIO times the visible enemy warship strength, and
    above zero -- because convoys crossing it would be sunk.

    Shores are public map data; enemy ships count only when visible, so a
    hidden submarine is no reason to guard a beach.
    """
    world_state = world_for(context)
    world = ai_world.for_screen(context)
    nation_data = world_state.nation_data
    if not enemies or not prov_ids:
        return set()
    enemies = set(enemies)
    visible = world.visible_provinces(ai_name)

    def reach(prov_id):
        start = [n for n in world.neighbor_ids.get(prov_id, ()) if n in world.water_ids]
        seen, frontier = set(start), list(start)
        for _ in range(c.AI_NEARBY_SEA_TILES - 1):
            frontier = [n for w in frontier for n in world.neighbor_ids.get(w, ())
                        if n in world.water_ids and n not in seen]
            seen.update(frontier)
        return seen

    def warship_strength(units):
        return sum(queries.calculate_unit_strength(u) for u in units
                   if queries.is_naval_unit(u.get("type", ""), context=context)
                   and not u.get("type", "").startswith("Convoy"))

    threatened = set()
    for prov_id in prov_ids:
        waters = reach(prov_id)
        enemy_shore = any(world_state.id_to_province[n].get("owner") in enemies
                          for w in waters for n in world.neighbor_ids.get(w, ())
                          if n not in world.water_ids)
        enemy_units, friendly_units = [], []
        for w in waters:
            if visible is not None and w not in visible:
                continue
            water = world_state.id_to_province[w]
            for unit in queries.filter_visible_units(water.get("units", ()), ai_name, water, nation_data):
                owner = queries.get_unit_combat_owner(unit)
                if owner in enemies or queries.are_at_war(ai_name, owner, nation_data):
                    enemy_units.append(unit)
                elif owner in friendly_nations:
                    friendly_units.append(unit)
        if not (enemy_shore or enemy_units):
            continue
        ours = warship_strength(friendly_units)
        if ours > 0 and ours >= c.AI_COAST_SUPREMACY_RATIO * warship_strength(enemy_units):
            continue
        threatened.add(prov_id)
    return threatened


def _discover_borders_and_targets(context, ai_name, my_provs, enemies, friendly_nations):
    """Locates coastal/enemy/unclaimed tiles globally (for naval targeting and
    island hopping and distant-ally expeditions) and classifies each of this
    nation's own border provinces as a war, peace, or coastal border."""
    world_state = world_for(context)
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

                # Find adjacent water tiles for ships to blockade from
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
            elif n_owner != ai_name and n_owner not in c.WATER_NATIONS and not queries.are_in_same_faction(ai_name, n_owner, world_state.nation_data):
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
    coastal_borders = _threatened_coasts(context, ai_name, coastal_borders, enemies,
                                         friendly_nations)

    return {
        "war_borders": war_borders,
        "peace_borders": peace_borders,
        "coastal_borders": coastal_borders,
        "enemy_targets": enemy_targets,
        "all_enemy_coasts": all_enemy_coasts,
        "enemy_coastal_waters": enemy_coastal_waters,
        "unclaimed_targets": unclaimed_targets,
        "all_unclaimed_coasts": all_unclaimed_coasts,
        "expedition_targets": expedition_targets,
    }


def _tile_is_lost(context, ai_name, prov, friendly_nations, reinforcements=()):
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
            max_turns=c.AI_RETREAT_FORECAST_TURNS)
        return outcome["winner_side"] == 1

    if not loses(ours):
        return False
    return not reinforcements or loses(ours + list(reinforcements))


def _available_reinforcements(context, ai_name, prov, units_info):
    """This nation's healthy units next door that could legally step onto `prov`."""
    world_state = world_for(context)
    nation_data = world_state.nation_data
    neighbors = set(prov.get("neighbors", ()))
    return [unit for unit, here in units_info
            if here["id"] in neighbors
            and not _is_wounded(unit)
            and not queries.is_nation_in_combat_here(ai_name, here, nation_data)
            and queries.can_unit_move_step(unit, here, prov, nation_data, context=context)]


def _retreat_tile(context, ai_name, unit, prov, friendly_nations, unsafe_waters, havens):
    """The best neighbouring tile for `unit` to fall back to, or None.

    Chosen per unit, because a ship, a convoy and a division standing on the
    same tile cannot all use the same neighbour. A tile qualifies when the unit
    may legally step there, it is not hostile land, nothing visible is fighting
    there, and no visible enemy fleet patrols it. Among those: a repair haven
    first, then friendly land, then the tile with the fewest visible threats
    next to it. Ties go to the lowest id so the choice is reproducible.
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
        choices.append((n_id not in havens, n_prov.get("owner") not in friendly_nations,
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
        terrain=target_prov.get("terrain"))
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
                               all_enemy_coasts, enemy_coastal_waters, havens=frozenset()):
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
                reinforcements = _available_reinforcements(context, ai_name, prov, units_info)
                # A lost tile is only abandoned when somebody on it can get out;
                # with nowhere to run, the units fight it out as a battle.
                if _tile_is_lost(context, ai_name, prov, friendly_nations, reinforcements) and any(
                        _retreat_tile(context, ai_name, mine, prov, friendly_nations,
                                      unsafe_waters, havens) is not None
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


def _build_target_assignments(units_info, borders, battles, at_war, capacity=None):
    """Picks the destination sets (land and naval) this nation's units can be
    routed to, and tallies + weights how many units are already assigned to
    each one so orders spread out rather than piling onto one tile."""
    peace_borders = borders["peace_borders"]
    coastal_borders = borders["coastal_borders"]
    war_borders = borders["war_borders"]
    unclaimed_targets = borders["unclaimed_targets"]
    all_unclaimed_coasts = borders["all_unclaimed_coasts"]
    enemy_targets = borders["enemy_targets"]
    all_enemy_coasts = borders["all_enemy_coasts"]
    enemy_coastal_waters = borders["enemy_coastal_waters"]
    expedition_targets = borders["expedition_targets"]

    active_battles = battles["active_battles"]
    friendly_convoys = battles["friendly_convoys"]
    convoy_in_combat = battles["convoy_in_combat"]
    convoy_near_ship = battles["convoy_near_ship"]
    convoy_near_coast = battles["convoy_near_coast"]

    # --- FIX: UNIVERSAL TARGETS ---
    # ALWAYS include peace and coastal borders to prevent abandonment
    target_destinations = list(set(list(unclaimed_targets) + list(all_unclaimed_coasts) + list(peace_borders) + list(coastal_borders) + list(active_battles)))

    if at_war:
        # Inject expedition_targets so distant armies mobilize!
        target_destinations = list(set(target_destinations + list(enemy_targets) + list(all_enemy_coasts) + list(expedition_targets)))

    # If no targets (e.g. island with no neighbors), fall back to coastal borders.
    if not target_destinations:
        target_destinations = list(coastal_borders)

    # Keep track of how many units are assigned to each target so we can spread them evenly
    target_assignments = {t_id: 0 for t_id in target_destinations}

    naval_destinations = list(set(list(enemy_coastal_waters) + list(friendly_convoys)))
    naval_assignments = {t_id: 0 for t_id in naval_destinations}

    # Convoy Escort Priority
    # Apply massive negative weights so warships heavily prioritize covering active convoys
    for c_id in friendly_convoys:
        if c_id in naval_assignments:
            naval_assignments[c_id] -= c.AI_CONVOY_ESCORT_WEIGHT
            if c_id in convoy_in_combat:
                naval_assignments[c_id] -= c.AI_CONVOY_COMBAT_WEIGHT
            elif c_id in convoy_near_ship:
                naval_assignments[c_id] -= c.AI_CONVOY_DANGER_SHIP_WEIGHT
            elif c_id in convoy_near_coast:
                naval_assignments[c_id] -= c.AI_CONVOY_DANGER_COAST_WEIGHT

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
        if prov["id"] in naval_assignments:
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
    for b_id in active_battles:
        if b_id in target_assignments:
            depth = _tile_depth(capacity, b_id)
            room = max(0, depth - target_stacks.get(b_id, 0)) / depth
            target_assignments[b_id] -= c.AI_REINFORCE_COMBAT_WEIGHT * room

    # --- STRATEGIC WEIGHTING FIX ---
    # 1. Coasts are low priority. Inflate their count so units prefer land borders.
    for c_id in coastal_borders:
        if c_id in target_assignments and c_id not in peace_borders and c_id not in war_borders:
            target_assignments[c_id] += 1

    # 2. Push the main army to the frontlines! Only keep 1 guard per peace/coastal
    # border during war or expansion. The guard stays at one whatever the combat
    # width is: a quiet border is a garrison, not a firing line.
    if at_war or unclaimed_targets:
        for p_id in peace_borders:
            if target_assignments.get(p_id, 0) >= 1:
                target_assignments[p_id] += c.AI_REAR_GUARD_PENALTY
        for c_id in coastal_borders:
            if target_assignments.get(c_id, 0) >= 1:
                target_assignments[c_id] += c.AI_REAR_GUARD_PENALTY

    # 3. Penalize expedition targets so the AI defends its homeland fronts FIRST.
    for e_id in expedition_targets:
        if e_id in target_assignments and e_id not in enemy_targets and e_id not in war_borders:
            target_assignments[e_id] += c.AI_EXPEDITION_WEIGHT

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
    speed = unit.get("speed", 1)
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
    coastal_borders = ctx["coastal_borders"]
    unclaimed_targets = ctx["unclaimed_targets"]
    active_battles = ctx["active_battles"]
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
    # Where a wounded unit must not be routed: anywhere the fighting is.
    combat_destinations = (set(active_battles) | set(ctx.get("enemy_targets", ()))
                           | set(ctx.get("expedition_targets", ()))
                           | set(ctx.get("all_enemy_coasts", ())))
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
        return _tile_pressure(target_assignments, target_stacks, tile, target_capacity)

    def retreat(unit, prov):
        """Falls back one step to the unit's own best tile. True if ordered."""
        tile = _retreat_tile(context, ai_name, unit, prov, friendly_nations,
                             unsafe_waters, havens)
        return tile is not None and _order_move(context, ai_name, prov, unit, [tile])

    for unit, prov in units_info:
        if not any(current is unit for current in prov.get("units", [])):
            continue
        attacker_signature = combat_rules.single_attacker_signature(unit)
        u_type = unit.get("type", "")
        is_convoy = u_type.startswith("Convoy")
        is_naval_combatant = queries.is_naval_unit(u_type, context=context) and not is_convoy
        wounded = _is_wounded(unit)

        curr_id = prov["id"]

        # --- RETREAT FROM LOST BATTLES ---
        # Each unit picks its own tile; a unit with nowhere legal to go stays
        # and fights below.
        if curr_id in lost_battles and retreat(unit, prov):
            continue

        in_combat = queries.is_nation_in_combat_here(ai_name, prov, world_state.nation_data)

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

        # If we are holding a defensive border (peace or coastal) and we are the ONLY unit here, HOLD THE LINE.
        # Do not apply this to war_borders because we WANT to push forward into enemy_targets.
        is_defensive_hold = (curr_id in peace_borders or curr_id in coastal_borders) and curr_id not in war_borders

        # Break the hold if there's an active battle literally 1 tile away!
        # A wounded unit is not going to that battle, so it keeps the hold.
        is_near_battle = any(n in active_battles for n in prov.get("neighbors", []))
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
            best_adj = min(adjacent_unclaimed, key=pressure)

            # Let fast units pathfind deeper into unclaimed territory!
            path = [best_adj] + _extend_fast_unit_path(
                context, unit, best_adj, curr_id, is_convoy, unsafe_waters, pressure,
                lambda owner: owner in c.UNOWNED_LAND_OWNERS)

            if _order_move(context, ai_name, prov, unit, path):
                claim(path[-1], from_tile=curr_id)
                continue

        # A wounded unit does not charge: it would be the weakest body in the
        # fight, and this branch is what used to send a routed stack straight
        # back into the tile it had just fled.
        if at_war and not is_naval_combatant and not wounded:
            # Include expedition targets in the adjacent strike check so they can push off allied territory
            adjacent_targets = [n for n in prov.get("neighbors", []) if n in target_destinations and (n in ctx["enemy_targets"] or n in ctx["expedition_targets"])]

            # PREVENT ILLEGAL CONVOY ATTACKS
            if is_convoy:
                adjacent_targets = [n for n in adjacent_targets if queries.can_convoy_enter(prov, world_state.id_to_province.get(n)) and n not in unsafe_waters]

            if adjacent_targets:
                adjacent_targets = [
                    target_id for target_id in adjacent_targets
                    if not _attack_target_is_immediate_loss(
                        context, ai_name, target_id, unit,
                        survival_cache, attacker_signature)
                ]
            if adjacent_targets:
                # Pick the adjacent enemy with the least attackers currently assigned
                best_adj = min(adjacent_targets, key=pressure)

                # Let fast units pathfind deeper from the border!
                path = [best_adj] + _extend_fast_unit_path(
                    context, unit, best_adj, curr_id, is_convoy, unsafe_waters, pressure,
                    lambda owner: (queries.is_hostile_territory(ai_name, owner, world_state.nation_data)
                                   or owner in c.UNOWNED_LAND_OWNERS))

                if _order_move(context, ai_name, prov, unit, path):
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
        ]

        if not targets:
            continue

        # Bypass the depth limiter for fully garrisoned borders: drop anything
        # carrying the rear-guard penalty, and anything already holding a full
        # front and relief, since neither has anything to gain from one more body.
        priority_targets = [t for t in targets
                            if assignments.get(t, 0) < c.AI_REAR_GUARD_PENALTY
                            and stacks.get(t, 0) < _tile_depth(target_capacity, t)]
        search_targets = priority_targets if priority_targets else targets

        # Route to the nearest border/enemy/coast/convoy that needs reinforcements
        path = _bfs_nearest_target(
            curr_id,
            set(search_targets),
            allowed_prov_ids,
            world_state.id_to_province,
            assignments,
            is_convoy=is_convoy,
            is_ship=is_naval_combatant,
            moving_nation=ai_name,
            nation_data=world_state.nation_data,
            unsafe_waters=unsafe_waters,
            unit_speed=unit.get("speed", 1),
            water_ids=water_ids,
            neighbor_ids=neighbor_ids,
            target_stacks=stacks,
            target_capacity=target_capacity,
            path_cache=path_cache
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
                speed = unit.get("speed", 1)

                # PREVENT LAND UNITS QUEUEING INTO OCEAN MID-MOVE
                final_path = []
                for step_id in path[:speed]:
                    step_prov = world_state.id_to_province.get(step_id)
                    if not is_convoy and not is_naval_combatant and step_prov and queries.is_water_province(step_prov):
                        break
                    final_path.append(step_id)

                if not _order_move(context, ai_name, prov, unit, final_path):
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
    """Tiles where this nation could repair a unit: industry, and no enemy on it.

    Exactly the two conditions the player's own orders panel applies -- "Needs
    Factory" (queries.has_industry) and "In Combat" -- and deliberately nothing
    else. Whether a tile is somewhere you would *march* a wounded unit to is a
    different question, asked separately in _march_havens; conflating the two is
    what stopped a Soviet Heavy Tank III sitting at 4% health on top of its own
    factory in province 295 from repairing (saves/NOT REPAIRING). That tile
    borders four German provinces, so it is a war border, so it was not a haven,
    so the tank marched off to take empty ground instead.

    A unit already standing on a factory is not choosing where to be. It is not
    in combat, it is holding the tile either way -- REPAIR blocks movement, not
    fighting -- and at 4% health it is contributing almost nothing to holding
    it. Repairing is simply the best thing it can do with the turn, and where
    the tile sits on the map has no bearing on that.
    """
    world_state = world_for(context)
    havens = set()
    for prov in my_provs:
        if not queries.has_industry(prov):
            continue
        if queries.is_nation_in_combat_here(ai_name, prov, world_state.nation_data):
            continue
        havens.add(prov["id"])
    return havens


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
      c.AI_REPAIR_ON_SITE_FRACTION health, on a haven (see _repair_havens). A
      unit this hurt deals reduced damage now (see
      combat_rules.health_damage_multiplier), so it is worth less in the next
      fight than the same unit at full health -- fixing it is worth the turn.
    - Wounded, and not: below the harder c.AI_REPAIR_HEALTH_FRACTION line it is
      worth the trip as well, so it is sent home. Land units march overland;
      warships sail to a friendly port with a factory (_port_havens).
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
    unit_library = queries.get_unit_library(context)
    path_cache = {}
    tech_tree = queries.get_tech_tree(context)
    nation = world_state.nation_data.get(ai_name, {})
    research = nation.get("research", {})

    war_borders = ctx["war_borders"]
    active_battles = ctx["active_battles"]
    target_assignments = ctx["target_assignments"]
    havens = ctx["repair_havens"]
    march_targets = _march_havens(havens, ctx)
    port_targets = _port_havens(context, ai_name, march_targets)
    leavers = _wounded_who_can_leave(context, ai_name, units_info)
    trip_tiles = set(allowed_prov_ids) - set(active_battles)

    def start_repair(unit):
        costs = unit_actions.repair_costs(context, unit, unit_library)
        if not queries.can_afford(nation, costs):
            return False
        unit_actions.apply_action(context, ai_name, prov, unit,
                                  {"type": "REPAIR"}, authority="ai")
        unit.pop("repair_trip", None)
        return True

    def route(unit, curr_id, targets, is_ship):
        """A trip to the nearest of `targets`, or None.

        A land unit walks overland only: a land route over water needs the
        CONVERT-to-Convoy dance _assign_unit_orders does for an invasion, and
        none of that is worth it to fix one division. A warship sails. A convoy
        is a land unit mid-crossing that should finish the crossing first, so
        it never starts a trip. No trip passes through a battle.
        """
        if not targets:
            return None
        path = _bfs_nearest_target(
            curr_id, set(targets), trip_tiles, world_state.id_to_province,
            target_assignments, is_ship=is_ship,
            moving_nation=ai_name, nation_data=world_state.nation_data,
            unit_speed=unit.get("speed", 1),
            water_ids=water_ids, neighbor_ids=neighbor_ids, path_cache=path_cache)
        if not path or (not is_ship and any(step in water_ids for step in path)):
            return None
        return path

    # Units already on a trip count against the cap, so a nation cannot send
    # its whole army back one turn at a time. The cap scales with the army.
    trips = sum(1 for unit, _prov in units_info if unit.get("repair_trip") is not None)
    trip_cap = max(1, int(len(units_info) * c.AI_MAX_REPAIR_TRIP_SHARE))

    remaining = []
    for unit, prov in units_info:
        curr_id = prov["id"]
        in_combat = queries.is_nation_in_combat_here(ai_name, prov, world_state.nation_data)
        speed = unit.get("speed", 1)
        u_type = unit.get("type", "")
        is_convoy = u_type.startswith("Convoy")
        is_naval_combatant = queries.is_naval_unit(u_type, context=context) and not is_convoy
        travels = not is_convoy
        trip_targets = port_targets if is_naval_combatant else march_targets

        # --- a trip already under way ---------------------------------------
        trip = unit.get("repair_trip")
        if trip is not None:
            if _health_fraction(unit) >= c.AI_REPAIR_ON_SITE_FRACTION or trip not in havens:
                # Healed on the way, or the destination was taken, overrun, or
                # lost its industry while the unit was still walking to it.
                unit.pop("repair_trip", None)
                trips -= 1
            elif curr_id == trip:
                if not in_combat and start_repair(unit):
                    trips -= 1
                    continue
            else:
                path = route(unit, curr_id, {trip}, is_naval_combatant)
                if path and _order_move(context, ai_name, prov, unit, path[:speed]):
                    continue
                # The way home is cut. Fight where it stands.
                unit.pop("repair_trip", None)
                trips -= 1

        if in_combat:
            # Out of the fight first, then home from the retreat tile.
            if id(unit) in leavers and trips < trip_cap:
                tile = _retreat_tile(context, ai_name, unit, prov, ctx["friendly_nations"],
                                     ctx["unsafe_waters"], havens)
                if tile is not None and _order_move(context, ai_name, prov, unit, [tile]):
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
            if _health_fraction(unit) < c.AI_REPAIR_ON_SITE_FRACTION:
                wants_repair = True
                if start_repair(unit):
                    continue
        elif (travels
                and trip_targets
                and trips < trip_cap
                and _is_wounded(unit)
                and _may_leave_the_line(context, ai_name, unit, prov, ctx)):
            path = route(unit, curr_id, trip_targets, is_naval_combatant)
            if path and _order_move(context, ai_name, prov, unit, path[:speed]):
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
        # to upgrade instead: process_upgrades carries health across as a
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
            target = queries.get_upgrade_target(u_type, research, unit_library, tech_tree)
            if target:
                unit_actions.apply_action(context, ai_name, prov, unit, {"type": "UPGRADE", "turns_left": 1,
                                 "target_type": target, "refund": {}}, authority="ai")
                continue

        remaining.append((unit, prov))

    units_info[:] = remaining


def _rotate_damaged_units(context, ai_name, active_battles):
    """Pulls shot-up units out of the front rank when a fresh one can take the slot.

    The only thing the lane model asks of a commander that movement cannot
    express. A reserve takes no damage and recovers morale, so a unit down to a
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


def _generate_unit_orders(context):
    world_state = world_for(context)
    session_state = session_for(context)
    ai_nations = queries.get_active_ai_nations(context)
    session_state.movement_tasks_total = len(ai_nations)
    session_state.movement_tasks_completed = 0
    world = ai_world.for_screen(context)

    # --- NEW: Pre-calculate allowed pathing IDs to include water for convoys ---
    # Doubles as the water lookup the pathfinder uses per tile.
    allowed_prov_ids_cache, water_ids, neighbor_ids = _build_shared_pathing_caches(context)

    nation_units, nation_provs = _reset_orders_and_collect_units(context, ai_nations)

    # Every tile somebody is fighting over this turn, pooled across nations so
    # the anti-swap pass at the end can leave relief traffic alone.
    contested = set()

    for completed, ai_name in enumerate(ai_nations):
        # The previous country's pass finished, including any no-order early exit.
        session_state.movement_tasks_completed = completed
        units_info = nation_units[ai_name]
        if not units_info:
            continue

        _assign_air_orders(context, ai_name, units_info)
        units_info = [(unit, base) for unit, base in units_info
                      if not queries.is_air_unit(unit, context=context) and not queries.is_air_transport(unit, context=context)
                      and any(current is unit for current in base.get("units", []))]
        if not units_info:
            continue

        my_provs = nation_provs[ai_name]

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
                                             borders["enemy_coastal_waters"], havens)

        # What each destination's fight can actually seat for us, asked of the
        # combat rules rather than restated here. A tile splitting three ways
        # gives us fewer slots than one where we face a single enemy.
        capacity = {
            t_id: combat_rules.nation_front_capacity(
                ai_name, world_state.id_to_province[t_id], world_state.nation_data)
            for t_id in battles["active_battles"]
            if t_id in world_state.id_to_province
        }

        assignments = _build_target_assignments(units_info, borders, battles, at_war, capacity)

        ctx = {
            "unsafe_waters": unsafe_waters,
            "friendly_nations": friendly_nations,
            "at_war": at_war,
            **borders,
            **battles,
            **assignments,
        }
        ctx["repair_havens"] = havens

        _assign_maintenance_orders(context, ai_name, units_info, ctx,
                                   allowed_prov_ids, water_ids, neighbor_ids)

        # If no targets at all (e.g. an island with no neighbours), there is
        # nothing to march toward. Maintenance runs before this rather than
        # after it: a garrison sitting on its own factory with no front to walk
        # to is the unit with the most to gain from a repair or an upgrade, and
        # skipping the nation here is what stopped it ever getting one.
        if not assignments["target_destinations"]:
            continue

        _assign_unit_orders(context, ai_name, units_info, ctx, allowed_prov_ids, water_ids, neighbor_ids)
        _rotate_damaged_units(context, ai_name, battles["active_battles"])

        contested |= set(battles["active_battles"])
        contested |= set(battles["lost_battles"])

    # --- Anti-Swap Cleanup ---
    _cancel_opposing_transitions(ai_nations, nation_units, contested)
    # Keep the final country pending until shared order cleanup also finishes.
    session_state.movement_tasks_completed = session_state.movement_tasks_total
