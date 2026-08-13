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

Three things make up a hand:

  occupation  how much of the other side's pre-war homeland you are standing on
  strength    both blocs' armies and economies, as a share
  weariness   how long *they* have been at it -- a tired enemy concedes sooner

Deliberately not in data/queries.py: a mod can ship its own copy of that file
and shadow it wholesale, which would take a brand new function down with it.
See the note at the top of map_logic/ai/ai_world.py.
"""

import data.constants as c
from data import queries
from map_logic.ai import ai_opinion
from map_logic.diplomacy import deal as deal_mod


def _clamp01(value):
    return max(0.0, min(1.0, value))


# ==========================================
# WHOSE LAND IS IT REALLY
# ==========================================

def prewar_index(nation_data):
    """{province id (as str): owner when the war began}, across every faction.

    save_faction_pre_war_map only records provinces held by that faction's own
    members, so the per-faction snapshots never overlap and can be merged.
    """
    merged = {}
    for snapshot in (nation_data.get("FACTION_WAR_MAPS") or {}).values():
        if isinstance(snapshot, dict):
            merged.update(snapshot)
    return merged


def original_owner(prov, prewar):
    """Who this province belonged to before the shooting started.

    The inverse of queries.was_original_owner, which answers the same question
    one nation at a time; asking it per nation per province would be a sweep
    per belligerent. Same two rules in the same order: the faction's pre-war
    snapshot if there is one, otherwise cores. A province with several cores
    resolves to the first, which load_map treats as the primary one.
    """
    owner = prewar.get(str(prov["id"]))
    if owner:
        return owner
    cores = prov.get("cores") or []
    return cores[0] if cores else prov.get("owner")


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
# WEARINESS
# ==========================================

def _bloc_weariness(map_screen, members, enemies, world=None):
    """How tired this side is of the war, averaged over its members, 0..1."""
    if not members:
        return 0.0
    shim = world if world is not None else _QueryWorld(map_screen)

    scores = []
    for nation in members:
        worst = max((ai_opinion.war_weariness(shim, nation, enemy) for enemy in enemies),
                    default=0.0)
        scores.append(worst)
    return sum(scores) / float(len(scores))


class _QueryWorld:
    """The two attributes ai_opinion.war_weariness reads off an AIWorld.

    AIWorld only exists while the AI passes are running -- map_screen.ai_world is
    None everywhere else -- and the peace screen very much wants a leverage bar.
    """

    def __init__(self, map_screen):
        self.nation_data = map_screen.nation_data


# ==========================================
# THE HAND
# ==========================================

def leverage(map_screen, side_a, side_b, world=None):
    """Each side's position at the table.

    Returns {"a": 0..1, "b": 0..1, "parts": {...}} where a and b sum to 1, so the
    UI can draw one bar and the AI can read the other side's number directly.
    `parts` carries the three components for the breakdown line under the bar.

    `world` is an AIWorld when one is in scope, purely to reuse its memoised
    strength figures; the answer is the same without it.
    """
    side_a, side_b = list(side_a), list(side_b)
    occ_a, occ_b = occupation(map_screen, side_a, side_b)
    share_a = strength_share(map_screen, side_a, side_b, world)

    wear_a = _bloc_weariness(map_screen, side_a, side_b, world)
    wear_b = _bloc_weariness(map_screen, side_b, side_a, world)

    parts_a = {"occupation": occ_a, "strength": share_a, "exhaustion": wear_b}
    parts_b = {"occupation": occ_b, "strength": 1.0 - share_a, "exhaustion": wear_a}

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
    """One side's weighted hand, before the two are normalised against each other.

    `exhaustion` here is the *opponent's* weariness: their exhaustion is your
    leverage, which is why parts_a carries wear_b.
    """
    return (c.WAR_SCORE_W_OCCUPATION * parts["occupation"]
            + c.WAR_SCORE_W_STRENGTH * parts["strength"]
            + c.WAR_SCORE_W_WEARINESS * parts["exhaustion"])


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
                                         ("strength", parts["strength"]),
                                         ("their exhaustion", parts["exhaustion"])))
