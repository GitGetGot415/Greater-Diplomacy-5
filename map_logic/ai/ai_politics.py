"""Which way an AI nation leans on the libertarian/authoritarian axis.

The mechanic itself lives in map_logic/politics.py; this is only the AI's half
of it -- the player steers their own country from the Politics tab.

The shape of the decision matters more than the numbers. A nation picks a
*target position* on the axis and walks one step per turn toward it, rather than
picking a direction and running to the wall. Three things fall out of that for
free:

  - a war it is winning comfortably centralises it a little; a war it is losing
    on three fronts centralises it a lot, and the two end up in visibly
    different places rather than both at +10
  - peace does not mean maximum liberty. A country beside a hostile giant stays
    near the centre; only one with nothing to fear drifts far left
  - because the target is recomputed every turn, a war breaking out halfway
    through a leftward drift turns the nation around gradually instead of
    snapping it

No `random`: this is a pure function of the world snapshot plus the sha256-seeded
personality traits, per the convention documented in ai_personality.procedural
and ai_candidates._haggle. The same save re-run makes the same choices.

Stdlib, `data` and the sibling ai modules only, so it imports under Pyodide.
"""

import data.constants as c
from data import queries
from map_logic import politics
from map_logic.ai import ai_opinion, ai_personality


def _danger(world, nation, enemies):
    """How badly this nation's wars are going, 0..1.

    Two parts: the worst war it is in, and how many of them there are. The
    `losing` term is ai_opinion.peace_appetite's, read off the same cached
    power ratios -- a nation that wants out of a war for being beaten is the
    same nation that wants its factories under state control.
    """
    losing = 0.0
    for enemy in enemies:
        border_ratio, global_ratio = world.power_ratio(nation, enemy)
        losing = max(losing, 1.0 - ai_opinion._sigmoid(
            (border_ratio + global_ratio) / 2.0, 1.0, c.AI_ODDS_STEEPNESS))

    return ai_opinion._clamp01(c.POLITICS_AI_W_LOSING * losing
                               + c.POLITICS_AI_W_LOAD * ai_opinion.war_load(world, nation))


def _menace(world, nation, enemies):
    """How threatening the strongest unfriendly neighbour it is *not* fighting is, 0..1.

    Peacetime's version of danger. Only the global ratio counts: what makes a
    neighbour frightening in peacetime is its total weight, not who currently
    happens to be standing on the border.
    """
    friendly = set(queries.get_all_friendly_nations(nation, world.nation_data))
    worst = 0.0
    for other in world.neighbors.get(nation, ()):
        if other == nation or other in enemies or other in friendly:
            continue
        if other not in world.nation_data or other in c.UNPLAYABLE_NATIONS:
            continue
        _, global_ratio = world.power_ratio(nation, other)
        worst = max(worst, 1.0 - ai_opinion._sigmoid(global_ratio, 1.0, c.AI_ODDS_STEEPNESS))
    return ai_opinion._clamp01(worst)


def desired_value(world, nation, scenario_settings=None):
    """Where this nation would like to sit on the axis, POLITICS_MIN..POLITICS_MAX."""
    enemies = set(e for e in queries.get_enemies(nation, world.nation_data)
                  if e in world.nation_data)

    if enemies:
        base = c.POLITICS_AI_WAR_BASE + c.POLITICS_AI_WAR_DANGER * _danger(world, nation, enemies)
    else:
        safety = 1.0 - _menace(world, nation, enemies)
        base = c.POLITICS_AI_PEACE_BASE - c.POLITICS_AI_PEACE_SAFETY * safety

    # Temperament, centred so an average nation contributes nothing. A cautious
    # country reaches for the emergency powers sooner; so does a belligerent
    # one, for the opposite reason.
    person = ai_personality.get(world.nation_data, nation, scenario_settings)
    base += c.POLITICS_AI_W_CAUTION * (person.get("caution", 0.5) - 0.5)
    base += c.POLITICS_AI_W_AGGRO * (person.get("aggression", 0.5) - 0.5)

    return politics.clamp((2.0 * ai_opinion._clamp01(base) - 1.0) * c.POLITICS_MAX)


def decide(world, nation, nation_data, scenario_settings=None):
    """Points `nation` at its target, or stops it if it has arrived.

    Returns the direction written, so a caller can log it.
    """
    target = desired_value(world, nation, scenario_settings)
    current = politics.value(nation_data, nation)

    if target > current:
        direction = 1
    elif target < current:
        direction = -1
    else:
        direction = 0

    politics.set_drift(nation_data, nation, direction)
    return direction
