"""Who is winning, as a number both the player and the AI can argue from.

There was no such thing before. `will_ai_accept_peace` flipped on
`ai_thinks_it_can_win`, a boolean about *future* prospects, so a nation sitting
on half its enemy's territory had no more claim at the table than one that had
taken nothing -- and the comment on that function said as much: "This query acts
as a centralized place to expand logic later (e.g. check war score)."

Leverage is advisory, not a budget. Nothing here forbids a demand; it decides
how absurd one looks. That is the difference between this and a Hearts of Iron
war-score bar, and it is deliberate: an outrageous offer should be *refused*,
with the AI saying so, rather than being unclickable.

Two things make up a hand:

  occupation  how much of the other side's pre-war homeland you are standing on
  strength    both blocs' armies and economies, as a share

There was a third, weariness: how long the other side had been at it, on the
theory that a tired enemy concedes sooner. It was a turn counter and nothing
else, so it credited a side with leverage for the passage of time rather than
for anything it had done, and at 0.15 it could tip a stalemate on the calendar
alone. The whole mechanic is gone; its weight went to occupation, which is the
thing it was standing in for.

Deliberately not in data/queries.py: a mod can ship its own copy of that file
and shadow it wholesale, which would take a brand new function down with it.
See the note at the top of map_logic/ai/ai_world.py.
"""

import data.constants as c
from data import queries
from map_logic.diplomacy import deal as deal_mod


def _clamp01(value):
    return max(0.0, min(1.0, value))


# ==========================================
# WHOSE LAND IS IT REALLY
# ==========================================

#: Both of these live in deal.py, because valuation needs them as much as this
#: module does and deal.py is the one of the two that can be imported from the
#: other without a cycle. Re-exported under their original names: the deal screen
#: and the tests reach for war_score.prewar_index, and where a pre-war owner is
#: looked up is a detail of who is winning, not of who calls it.
prewar_index = deal_mod.prewar_index
original_owner = deal_mod.original_owner


def occupation(map_screen, side_a, side_b):
    """How much of each side's homeland the other is sitting on, 0..1 each.

    Measured in the same currency deals are priced in, so taking one industrial
    heartland counts for more than taking five empty tiles -- which is also what
    stops a side that has overrun a wasteland from reading as the winner.
    """
    prewar = prewar_index(map_screen.nation_data)
    a, b = set(side_a), set(side_b)

    homeland = {"a": 0.0, "b": 0.0}
    lost = {"a": 0.0, "b": 0.0}

    for prov in map_screen.map_data.values():
        was = original_owner(prov, prewar)
        side = "a" if was in a else ("b" if was in b else None)
        if side is None:
            continue

        value = deal_mod.tile_value(prov)
        homeland[side] += value

        holder = prov.get("owner")
        if holder != was and holder in (b if side == "a" else a):
            lost[side] += value

    # "a" holds what side b lost, and vice versa.
    return (_clamp01(lost["b"] / homeland["b"]) if homeland["b"] else 0.0,
            _clamp01(lost["a"] / homeland["a"]) if homeland["a"] else 0.0)


# ==========================================
# STRENGTH
# ==========================================

def _bloc_power(map_screen, members, world=None):
    """Armies plus economy for a whole side.

    Summed per member rather than through get_alliance_military_strength, which
    walks each nation's own friend list and would count a faction of four once
    per member.
    """
    total = 0.0
    for nation in members:
        if world is not None:
            total += world.military(nation) + world.econ_power(nation) / 100.0
        else:
            total += (queries.get_military_strength(nation, map_screen.map_data)
                      + queries.get_economic_power(nation, map_screen.nation_data) / 100.0)
    return total


def strength_share(map_screen, side_a, side_b, world=None):
    """Side a's share of the two blocs' combined power, 0..1."""
    power_a = _bloc_power(map_screen, side_a, world)
    power_b = _bloc_power(map_screen, side_b, world)
    combined = power_a + power_b
    if combined <= 0:
        return 0.5
    return _clamp01(power_a / combined)


# ==========================================
# THE HAND
# ==========================================

def leverage(map_screen, side_a, side_b, world=None):
    """Each side's position at the table.

    Returns {"a": 0..1, "b": 0..1, "parts": {...}} where a and b sum to 1, so the
    UI can draw one bar and the AI can read the other side's number directly.
    `parts` carries the components for the breakdown line under the bar.

    Being a *share* is the one thing this number cannot express: two sides that
    have taken nothing from each other both read 0.5, and a side that has taken
    nothing at all still reads about a third once strength is counted. That is
    fine for "who is ahead", which is what the bar says, and useless as a limit
    on what may be demanded -- for which ai_opinion reads `occupation` directly.

    `world` is an AIWorld when one is in scope, purely to reuse its memoised
    strength figures; the answer is the same without it.
    """
    side_a, side_b = list(side_a), list(side_b)
    occ_a, occ_b = occupation(map_screen, side_a, side_b)
    share_a = strength_share(map_screen, side_a, side_b, world)

    parts_a = {"occupation": occ_a, "strength": share_a}
    parts_b = {"occupation": occ_b, "strength": 1.0 - share_a}

    raw_a = _raw(parts_a)
    raw_b = _raw(parts_b)
    combined = raw_a + raw_b

    if combined <= 0:
        score_a = score_b = 0.5
    else:
        score_a = raw_a / combined
        score_b = raw_b / combined

    return {"a": score_a, "b": score_b, "parts": {"a": parts_a, "b": parts_b}}


def _raw(parts):
    """One side's weighted hand, before the two are normalised against each other."""
    return (c.WAR_SCORE_W_OCCUPATION * parts["occupation"]
            + c.WAR_SCORE_W_STRENGTH * parts["strength"])


def between(map_screen, nation, opponent, world=None):
    """Leverage from `nation`'s point of view, sides resolved from the war itself.

    The convenience form: peace_scope decides who is actually bound by a
    settlement between these two, and this reports it as
    {"mine": 0..1, "theirs": 0..1, ...}.
    """
    from map_logic.diplomacy import peace_scope

    side_mine, side_theirs = peace_scope.war_sides(nation, opponent, map_screen.nation_data)
    scores = leverage(map_screen, side_mine, side_theirs, world)
    return {"mine": scores["a"], "theirs": scores["b"],
            "parts": scores["parts"]["a"], "their_parts": scores["parts"]["b"],
            "sides": (side_mine, side_theirs)}


def summary_line(parts):
    """The breakdown printed under the leverage bar."""
    return "  ".join(f"{name} {int(round(value * 100))}%"
                     for name, value in (("occupation", parts["occupation"]),
                                         ("strength", parts["strength"])))
