"""How much a nation wants a thing, rather than whether it is merely allowed.

The AI's grand strategy ran on two booleans. `ai_thinks_it_can_win` returned
true when border strength was 1.2x and global power 0.8x, and that was the whole
of its reasoning about war; `will_ai_accept_peace` flipped on the same function.
Relations were computed, displayed on the map, and consulted by exactly one
branch of one function -- which OR'd them with a shared-enemy check that usually
bypassed them anyway. A nation you had been friendly with for a hundred turns
was exactly as likely to be invaded as a sworn enemy.

Everything here is a degree instead of a threshold, so the same position can
produce different choices from different nations, and relations and temperament
both count. It works with the LLM off; Phase 4 layers a model on top of these
numbers rather than replacing them.

Stdlib and `data` only.
"""

import math

import data.constants as c
from data import queries
from map_logic.ai import ai_personality


def _clamp01(value):
    return max(0.0, min(1.0, value))


def _sigmoid(value, midpoint, steepness):
    """0..1, crossing 0.5 at `midpoint`. The soft version of a threshold."""
    try:
        return 1.0 / (1.0 + math.exp(-steepness * (value - midpoint)))
    except OverflowError:
        return 0.0 if value < midpoint else 1.0


def traits(world, nation, scenario_settings=None):
    return ai_personality.get(world.nation_data, nation, scenario_settings)


def war_load(world, nation):
    """How stretched this nation already is, 0..1.

    A nation at war with three neighbours should be markedly less keen on a
    fourth, which nothing in the old logic expressed -- it evaluated every
    target in isolation.
    """
    enemies = [e for e in queries.get_enemies(nation, world.nation_data)
               if e in world.nation_data]
    if not enemies:
        return 0.0
    return _clamp01(len(enemies) / float(c.AI_WAR_LOAD_SATURATION))


def target_value(world, nation, target):
    """How much this nation stands to gain from taking the target's land, 0..1."""
    contested = world.claim_pressure.get((target, nation), 0)
    owned = max(1, len(world.provs_by_owner.get(target, ())))
    return _clamp01(contested / float(owned))


def war_desire(world, nation, target, scenario_settings=None):
    """How much `nation` wants a war with `target`, 0..1.

    The two power terms are the same quantities ai_thinks_it_can_win compares,
    but read as degrees rather than as a pass/fail -- with the crossover moved
    by how cautious this nation is, so a bold country gambles on odds a careful
    one turns down. The remaining terms are what the old logic had no way to
    say at all: that we like them, that we promised not to, that we are already
    fighting two wars.
    """
    person = traits(world, nation, scenario_settings)
    caution = person.get("caution", 0.5)

    border_ratio, global_ratio = world.power_ratio(nation, target)

    # Each of these is 0..1 in its own right and they are *averaged*, not added.
    # Summing them saturated the clamp at the top of the range -- any nation
    # with decent odds came out at 1.0 whatever it thought of the target -- and
    # in a full run that produced almost twice as many wars as the old boolean
    # it was supposed to be a more considered version of.
    odds = (c.AI_W_BORDER * _sigmoid(border_ratio,
                                     c.AI_WAR_STRENGTH_THRESHOLD * (0.7 + 0.6 * caution),
                                     c.AI_ODDS_STEEPNESS)
            + c.AI_W_GLOBAL * _sigmoid(global_ratio,
                                       c.AI_GLOBAL_STRENGTH_THRESHOLD * (0.7 + 0.6 * caution),
                                       c.AI_ODDS_STEEPNESS))

    appetite = (c.AI_W_CLAIM * target_value(world, nation, target)
                + c.AI_W_AGGRO * person.get("aggression", 0.5)
                + c.AI_W_AMBITION * person.get("ambition", 0.5))

    core = c.AI_W_ODDS * odds + c.AI_W_APPETITE * appetite

    # Relations now suppress war, which they have never done. Measured from
    # neutral upward only: being disliked does not by itself make a nation
    # attack you, that is what aggression is for, but being genuinely friendly
    # holds it back.
    goodwill = _clamp01(max(0.0, world.relation(nation, target)) / 200.0)
    restraint = (c.AI_W_RELATION * goodwill
                 + c.AI_W_OVEREXTENSION * war_load(world, nation))

    return _clamp01(core - restraint)


def wants_war(world, nation, target, scenario_settings=None):
    """Whether desire clears the bar. The single yes/no the pass still needs."""
    return war_desire(world, nation, target, scenario_settings) >= c.AI_WAR_DESIRE_THRESHOLD


def war_weariness(world, nation, enemy):
    """How tired of this particular war the nation is, 0..1."""
    duration = world.nation_data.get(nation, {}).get("war_durations", {}).get(enemy, 0)
    return _clamp01(duration / float(c.AI_WAR_WEARINESS_TURNS))


def peace_appetite(world, nation, enemy, scenario_settings=None):
    """How much this nation wants out of its war with `enemy`, 0..1.

    Losing, tired, and cautious all push toward the table. The old rule was a
    straight inversion of "can I win", which meant a nation that was narrowly
    ahead would never talk however long the war had run.
    """
    person = traits(world, nation, scenario_settings)
    border_ratio, global_ratio = world.power_ratio(nation, enemy)
    losing = 1.0 - _sigmoid((border_ratio + global_ratio) / 2.0, 1.0, c.AI_ODDS_STEEPNESS)

    return _clamp01(c.AI_W_PEACE_LOSING * losing
                    + c.AI_W_PEACE_WEARINESS * war_weariness(world, nation, enemy)
                    + c.AI_W_PEACE_CAUTION * person.get("caution", 0.5))


def accepts_peace(world, nation, proposer, peace_type, scenario_settings=None):
    """Whether this nation takes the offered terms.

    Replaces queries.will_ai_accept_peace's boolean flip, and in particular the
    rule that a demand for claims was refused unconditionally -- which is why AI
    wars never once ended with territory changing hands. A nation that is
    clearly losing a long war will now give ground, so a war can actually
    resolve into a settlement instead of grinding until somebody is annihilated.
    """
    appetite = peace_appetite(world, nation, proposer, scenario_settings)
    duration = world.nation_data.get(nation, {}).get("war_durations", {}).get(proposer, 0)

    if peace_type.startswith(c.PEACE_DEMAND_CLAIMS):
        if duration < c.MIN_TURNS_FOR_CEASEFIRE:
            return False
        return appetite >= c.AI_PEACE_CEDE_LAND_THRESHOLD

    if peace_type.startswith(c.PEACE_WHITE_PEACE):
        if duration < c.MIN_TURNS_FOR_CEASEFIRE:
            return False
        return appetite >= c.AI_PEACE_CEASEFIRE_THRESHOLD

    if peace_type.startswith(c.PEACE_SURRENDER):
        # They are giving us something. Worth taking unless we are winning
        # comfortably and have barely started.
        if duration < c.MIN_TURNS_FOR_CEASEFIRE:
            return appetite >= c.AI_PEACE_CEASEFIRE_THRESHOLD
        return True

    return True


def trade_appetite(world, nation, sender, receive, give, prices, scenario_settings=None):
    """What this nation makes of a trade, as a net value in its own price terms.

    `receive` and `give` are {resource: amount}. Priced by scarcity, so a
    fuel-starved nation will genuinely overpay for fuel, and shaded by how much
    it likes the other side -- a friend gets a better rate, an enemy does not
    get one at all. The old rule accepted a trade only if the AI gave literally
    nothing, which is why no AI ever agreed to a deal a player would call fair.
    """
    person = traits(world, nation, scenario_settings)
    gained = sum(prices.get(res, 1.0) * float(amount) for res, amount in receive.items())
    lost = sum(prices.get(res, 1.0) * float(amount) for res, amount in give.items())

    goodwill = (world.relation(nation, sender) / 200.0) * person.get("trust", 0.5)
    return gained - lost * (1.0 - c.AI_TRADE_GOODWILL_DISCOUNT * goodwill)


def alliance_appetite(world, nation, other, scenario_settings=None):
    """How much this nation wants a formal bloc with `other`, 0..1."""
    person = traits(world, nation, scenario_settings)
    relation = _clamp01((world.relation(nation, other) + 200.0) / 400.0)

    mine = set(queries.get_enemies(nation, world.nation_data))
    theirs = set(queries.get_enemies(other, world.nation_data))
    shared = 1.0 if (mine & theirs) else 0.0

    return _clamp01(c.AI_W_ALLY_RELATION * relation * (0.5 + person.get("trust", 0.5))
                    + c.AI_W_ALLY_SHARED_ENEMY * shared
                    + c.AI_W_ALLY_WEAKNESS * (1.0 - _clamp01(
                        world.power_ratio(nation, other)[1])))
