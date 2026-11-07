"""Non-mutating battle forecasts shared by the map, Manage Battle and the AI.

The map's battle bubbles, the battle screen's outlook and the rule-based AI's
retreat decision all ask the same question: who wins this fight, and how soon.
They must get the same answer, so the simulation lives here rather than in a
UI module the AI would otherwise have to import.
"""
from data import queries
from map_logic.system32 import combat_processor, combat_rules


def combat_winner_from_survivors(units, engaged):
    """Rank surviving battle participants. Exclude countries that did not fight.

    This deliberately does not consult province ownership.  Sea tiles do not
    have an owner, and a land battle's likely winner is not necessarily the
    country that currently owns the province.  Volunteers are grouped under
    their temporary combat host, matching the side used by the resolver.
    """
    ranked = queries.rank_combat_nations_by_health([
        unit for unit in units if queries.get_unit_combat_owner(unit) in engaged])
    return ranked[0] if ranked else None


def estimated_combat_outcome(sides, nation_data, province=None, max_turns=100, grounded_sides=None):
    """Estimate the winning side and future volleys for a battle.

    This is deliberately a small, non-mutating simulation of the resolver:
    it rebuilds lanes after every simultaneous exchange, applies the same
    grouped damage function, and includes a province's fort defense when one
    is supplied.

    The returned ``winner_side`` is the index in ``sides`` and is ``None`` when
    the current rules produce a stalemate, both sides survive without a hostile
    lane, or the estimate would exceed the safety limit.  ``turns`` is the
    number of future volleys until that result is reached.
    ``winner_nation`` ranks surviving participants only after the battle ends.
    It is ``None`` when no participant survives or the forecast cannot resolve combat.
    """
    return {key: value for key, value in simulate_combat(
        sides, nation_data, province=province, max_turns=max_turns,
        grounded_sides=grounded_sides).items()
        if key != "sides"}


def simulate_combat(sides, nation_data, province=None, max_turns=100, grounded_sides=None):
    """Run the non-mutating combat estimate and retain its survivors."""
    simulated_sides = [
        [dict(unit) for unit in side if unit.get("health", 0) > 0]
        for side in sides
    ]
    if grounded_sides is None:
        grounded_sides = (set(range(len(sides)))
                          if province is None or not queries.is_water_province(province) else set())
    # Record participants before aircraft can become immediate ground casualties.
    engaged = set(combat_rules.build_battle(
        simulated_sides, nation_data,
        terrain=province.get("terrain") if province is not None else None,
        grounded_sides=grounded_sides, convert_aircraft=False).engaged)
    for index, side in enumerate(simulated_sides):
        enemies = (side if len(simulated_sides) == 1 else
                   [unit for other_index, other_side in enumerate(simulated_sides)
                    if index != other_index for unit in other_side])
        queries.prepare_aircraft_for_ground_combat(side, nation_data, enemies,
            on_land=index in grounded_sides, context=nation_data)
    simulated_sides = [[unit for unit in side if unit.get("health", 0) > 0]
                       for side in simulated_sides]

    def result(winner_side, turns):
        winner_nation = (
            combat_winner_from_survivors(
                [unit for side in simulated_sides for unit in side], engaged)
            if turns is not None else None)
        return {"winner_side": winner_side, "winner_nation": winner_nation,
                "turns": turns, "sides": simulated_sides}

    def defense_bonus(unit):
        if province is None:
            return 0
        return queries.get_fort_defense_bonus(
            province, unit, nation_data, combat_active=True)

    for turns in range(max_turns + 1):
        battle = combat_rules.build_battle(
            simulated_sides, nation_data,
            terrain=province.get("terrain") if province is not None else None,
            grounded_sides=grounded_sides)
        engaged.update(battle.engaged)
        if not battle.lanes:
            live_side_indexes = [index for index, side in enumerate(simulated_sides)
                                 if side]
            winner_side = (live_side_indexes[0]
                           if len(live_side_indexes) == 1 else None)
            return result(winner_side, turns)

        exchanges = list(combat_rules.exchange(battle, nation_data))
        if not exchanges:
            return result(None, None)

        health_before = sum(
            max(0, float(unit.get("health", 0)))
            for side in simulated_sides for unit in side
        )
        for targets, total_attack in exchanges:
            combat_processor.apply_group_damage(
                total_attack, targets, defense_bonus)

        for index, side in enumerate(simulated_sides):
            simulated_sides[index] = [
                unit for unit in side if unit.get("health", 0) > 0
            ]

        health_after = sum(
            max(0, float(unit.get("health", 0)))
            for side in simulated_sides for unit in side
        )
        if health_after >= health_before:
            return result(None, None)

    return result(None, None)
