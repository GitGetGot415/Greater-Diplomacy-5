"""Resolve pixel-range aircraft orders once at the turn boundary."""
from data import queries
import data.constants as c
from map_logic.turn_processing import combat_rules, combat_processor


def _cleanup(map_screen):
    for province in map_screen.map_data.values():
        province["units"] = [u for u in province.get("units", []) if u.get("health", 0) > 0]


def process_air_orders(map_screen):
    missions = {}
    patrols = []
    reposition = []
    for base in map_screen.map_data.values():
        # A base already occupied by hostile troops cannot launch aircraft out
        # of an ongoing ground engagement to evade the automatic Truck rule.
        queries.prepare_aircraft_for_ground_combat(base.get("units", []), map_screen.nation_data)
        for unit in base.get("units", []):
            order = unit.get("order")
            if (not isinstance(order, dict) or not isinstance(order.get("type"), str)
                    or order["type"] not in queries.AIR_ORDER_TYPES):
                continue
            try:
                order = queries.canonical_air_order(map_screen, unit, base, order)
            except ValueError:
                unit["order"] = {"type": "MOVE", "path": []}
                continue
            unit["order"] = order
            if order["type"] == "AIR_PATROL":
                patrols.append((unit, base, order))
            elif order["type"] == "AIR_REPOSITION":
                reposition.append((unit, base, order))
            else:
                # All interceptable aircraft aiming at this target form one
                # battle, including multiple hostile powers (the shared lanes
                # decide their wars). V2s form a separate immune mission.
                immune = bool(queries.air_unit_stats(unit).get("air_interception_immune"))
                missions.setdefault((order["target_id"], immune), []).append(unit)

    coverage = {id(unit): queries.get_air_targets(map_screen, unit, base, "AIR_PATROL")
                for unit, base, _order in patrols}
    strengths = {key: sum(queries.calculate_unit_strength(u) for u in force)
                 for key, force in missions.items()}

    def defenders_for(key):
        target_id, immune = key
        if immune:
            return []
        return [unit for unit, _base, _order in patrols
                if unit.get("health", 0) > 0 and target_id in coverage[id(unit)]
                and any(queries.are_at_war(queries.get_unit_combat_owner(unit),
                         queries.get_unit_combat_owner(attacker), map_screen.nation_data)
                        for attacker in missions[key] if attacker.get("health", 0) > 0)]

    # Each patrol contributes precedence constraints between covered missions.
    # Topological scheduling respects all compatible priorities even when
    # coverage overlaps. Contradictory priorities can form a cycle: only then
    # do patrol votes break it, followed by stable target/immune order.
    # Strength is measured on committed forces before interception losses.
    pending = set(missions)
    ordered_patrols = sorted(patrols, key=lambda item: (
        str(item[0].get("owner", "")), item[1]["id"], str(item[0].get("unit_id", ""))))
    predecessors = {key: set() for key in pending}
    rankings = []
    for defender, _base, order in ordered_patrols:
        direction = -1 if order["priority"] == "STRONGEST" else 1
        covered = sorted((key for key in pending if any(
            unit is defender for unit in defenders_for(key))),
            key=lambda key: (direction * strengths[key], key))
        rankings.append(covered)
        for before, after in zip(covered, covered[1:]):
            predecessors[after].add(before)
    while pending:
        ready = [key for key in pending if not predecessors[key].intersection(pending)]
        if ready:
            key = min(ready)
        else:
            votes = {key: 0 for key in pending}
            for ranking in rankings:
                choice = next((key for key in ranking if key in pending), None)
                if choice is not None:
                    votes[choice] += 1
            key = min(pending, key=lambda key: (-votes[key], key))
        pending.remove(key)
        force = [unit for unit in missions[key] if unit.get("health", 0) > 0]
        defenders = defenders_for(key)
        if defenders and force:
            # One side contains every participant: the standard coalition lanes
            # retain three-or-more-side fights. Terrain never changes air width.
            battle = combat_rules.build_battle([force + defenders], map_screen.nation_data,
                                               width=c.COMBAT_WIDTH, air_combat=True)
            for targets, attack in combat_rules.exchange(battle, map_screen.nation_data):
                combat_processor.apply_group_damage(attack, targets)
            for lane in battle.lanes:
                for unit in lane.a.front + lane.b.front:
                    unit["_in_combat_this_turn"] = True
            _cleanup(map_screen)

        survivors = [unit for unit in force if unit.get("health", 0) > 0]
        target = map_screen.id_to_province[key[0]]
        by_owner = {}
        for unit in survivors:
            by_owner.setdefault(queries.get_unit_combat_owner(unit), []).append(unit)
        # A strike is one normal, simultaneous lane exchange against the
        # garrison. Keep aircraft flying so tank immunity still applies, but
        # reserve fighter air-to-air bonuses for the interception above.
        # Separate sides prevent extra fights within the garrison or attacking
        # force; those belong to ground combat and interception respectively.
        garrison = [u for u in target.get("units", []) if any(queries.are_at_war(
            queries.get_unit_combat_owner(wing), queries.get_unit_combat_owner(u),
            map_screen.nation_data) for wing in survivors)]
        if survivors and garrison:
            battle = combat_rules.build_battle(
                [survivors, garrison], map_screen.nation_data,
                terrain=target.get("terrain"), convert_aircraft=False)
            garrison_ids = {id(u) for u in garrison}
            for targets, attack in combat_rules.exchange(battle, map_screen.nation_data):
                combat_processor.apply_group_damage(attack, targets, lambda unit:
                    queries.get_fort_defense_bonus(target, unit, map_screen.nation_data,
                                                  combat_active=True)
                    if id(unit) in garrison_ids else 0)
            for lane in battle.lanes:
                for unit in lane.a.front + lane.b.front:
                    unit["_in_combat_this_turn"] = True

        # Preserve fort damage even on an empty tile: each wing that reaches
        # the target removes one level, after the fort protects this exchange.
        fort_hits = 0
        for owner, wings in by_owner.items():
            if queries.are_at_war(owner, target.get("owner"), map_screen.nation_data):
                fort_hits += len(wings)
        for _ in range(fort_hits):
            queries.damage_fort(target, map_screen.nation_data, map_screen.map_data)
        for unit in survivors:
            unit["order"] = {"type": "MOVE", "path": []}
            if queries.air_unit_stats(unit).get("air_consumable"):
                unit["health"] = 0
        _cleanup(map_screen)

    # Reposition cannot capture or invoke adjacency/access rules. Aircraft on
    # either end can still be attacked there in the subsequent ground phase.
    for unit, base, order in reposition:
        if unit.get("health", 0) <= 0:
            continue
        base["units"] = [u for u in base["units"] if u is not unit]
        map_screen.id_to_province[order["target_id"]].setdefault("units", []).append(unit)
        unit["order"] = {"type": "MOVE", "path": []}
    # Patrols persist; strikes and repositioning are one-shot orders.
