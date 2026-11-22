"""Choose an AI nation's targets on all four politics axes.

The mechanic itself lives in map_logic/politics.py; this is only the AI's half
of it -- the player steers their own country from the Politics tab.

The shape of the decision matters more than the numbers. A nation picks a
*target position* on each axis and walks one step per turn toward it, rather
than picking a direction and running to the wall. Because the target is
recomputed every turn, a war breaking out halfway through a drift turns the
nation around gradually instead of snapping it, and two nations in the same war
end up in different places.

  - Political: libertarian for research, moving toward authoritarian as more of
    its land is uncored, for fast and cheap coring.
  - Economic: market while its land is cored, moving toward planned as more of
    it is non-core, where a planned economy keeps the land productive.
  - Quality: professional by default, moving toward numerous under the worst of
    a losing war, too few land units to man its land border, or an upkeep bill
    its income cannot carry.
  - Strategy: balanced at peace. At war, offensive while it is winning and
    defensive while it is losing or enemies hold its cores.

No `random`: this is a pure function of the world snapshot, per the convention
documented in ai_personality.procedural and ai_candidates._haggle. The same
save re-run makes the same choices.

Stdlib, `data` and the sibling ai modules only, so it imports under Pyodide.
"""

import data.constants as c
from map_logic.ai import ai_tuning
from data import queries
from data.number_utils import clamp01
from map_logic import politics
from map_logic.ai import ai_opinion


def _enemies(world, nation):
    return set(e for e in queries.get_enemies(nation, world.nation_data) if e in world.nation_data)


def _losing(world, nation, enemies):
    """How badly its worst war is going, 0..1. Even odds read as 0.5."""
    losing = 0.0
    for enemy in enemies:
        border_ratio, global_ratio = world.power_ratio(nation, enemy)
        losing = max(losing, 1.0 - ai_opinion._sigmoid(
            (border_ratio + global_ratio) / 2.0, 1.0, ai_tuning.AI_ODDS_STEEPNESS))
    return losing


def _danger(world, nation, enemies):
    """How badly this nation's wars are going, 0..1.

    Two parts: the worst war it is in, and how many of them there are. The
    `losing` term is ai_opinion.peace_appetite's, read off the same cached
    power ratios -- a nation that wants out of a war for being beaten is the
    same nation that needs more men in the line.
    """
    return clamp01(ai_tuning.POLITICS_AI_LOSING_SHARE * _losing(world, nation, enemies)
                   + (1.0 - ai_tuning.POLITICS_AI_LOSING_SHARE) * ai_opinion.war_load(world, nation))


def _uncored_share(world, nation):
    """The share of its own land it has not cored, 0..1."""
    owned = world.provs_by_owner.get(nation, ())
    if not owned:
        return 0.0
    return sum(not queries.has_core(nation, province) for province in owned) / len(owned)


def _border_shortfall(world, nation):
    """How far its land units fall short of one per land border tile, 0..1."""
    border = len(world.land_border_tiles.get(nation, ()))
    if not border:
        return 0.0
    land_units = sum(not unit.get("naval_unit") and not queries.is_air_unit(unit, context=world.nation_data)
                     for unit, _province in world.units_by_owner.get(nation, ()))
    return clamp01(1.0 - land_units / border)


def _upkeep_pressure(world, nation):
    """How far its worst upkeep-to-income ratio is past the AI's comfort target, 0..1.

    Reaches 1 when that upkeep equals the income it is paid from.
    """
    economy = world.economies.get(nation)
    if not economy:
        return 0.0
    pressure = 0.0
    for resource, target in c.AI_UPKEEP_TARGETS.items():
        ratio = economy["upkeep"][resource] / max(1.0, economy["total_inc"][resource])
        pressure = max(pressure, clamp01((ratio - target) / (1.0 - target)))
    return pressure


def _occupied_core_share(world, nation, enemies):
    """The share of its cores that enemies hold, 0..1."""
    cores = held = 0
    for owner, provinces in world.provs_by_owner.items():
        for province in provinces:
            if nation in province.get("cores", ()):
                cores += 1
                held += owner in enemies
    return held / cores if cores else 0.0


def _position(pull):
    """POLITICS_MIN at no pull, POLITICS_MAX at full pull."""
    return politics.clamp(c.POLITICS_MIN + clamp01(pull) * (c.POLITICS_MAX - c.POLITICS_MIN))


def desired_value(world, nation):
    """Political target: libertarian, moving toward authoritarian with uncored land."""
    return _position(_uncored_share(world, nation) / ai_tuning.POLITICS_AI_UNCORED_SHARE_FOR_AUTHORITY)


def desired_economic_value(world, nation):
    """Economic target: market, moving toward planned with non-core land."""
    return _position(1.0 - _uncored_share(world, nation) / ai_tuning.POLITICS_AI_UNCORED_SHARE_FOR_PLANNING)


def desired_quality_value(world, nation):
    """Quality target: professional, moving toward numerous under the strongest pressure."""
    enemies = _enemies(world, nation)
    danger = _danger(world, nation, enemies) if enemies else 0.0
    return _position(max(danger, _border_shortfall(world, nation), _upkeep_pressure(world, nation)))


def desired_strategy_value(world, nation):
    """Strategy target: balanced at peace; at war, defensive as it loses or loses its cores."""
    enemies = _enemies(world, nation)
    if not enemies:
        return c.POLITICS_START
    occupied = _occupied_core_share(world, nation, enemies) / ai_tuning.POLITICS_AI_OCCUPIED_SHARE_FOR_DEFENSE
    return _position(max(_losing(world, nation, enemies), occupied))


DESIRED_POSITIONS = {
    politics.POLITICAL: desired_value,
    politics.ECONOMIC: desired_economic_value,
    politics.QUALITY: desired_quality_value,
    politics.STRATEGY: desired_strategy_value,
}


def _direction_toward(current, target):
    if target > current:
        return 1
    if target < current:
        return -1
    return 0


def decide(world, nation, nation_data):
    """Point every axis toward its current target. Returns {axis: direction}."""
    directions = {}
    for axis in politics.AXES:
        target = DESIRED_POSITIONS[axis["id"]](world, nation)
        direction = _direction_toward(politics.axis_value(nation_data, nation, axis["id"]), target)
        politics.set_axis_drift(nation_data, nation, axis["id"], direction)
        directions[axis["id"]] = direction
    return directions
