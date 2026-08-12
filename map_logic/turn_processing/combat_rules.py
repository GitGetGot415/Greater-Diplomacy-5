"""The rules of a fight, in the one place both the resolver and the map read.

Two questions live here.

**Which units meet head-on between two tiles.** A meeting engagement is two
garrisons swapping places: the units in province P ordered into Q, against the
units in Q ordered into P. Two places need to know about them -- the prediction
bubble the player sees before ending their turn (data/queries.py) and the combat
that actually resolves (map_logic/turn_processing/combat_processor.py) -- and
each carried its own implementation of the same rule, so a change to one
silently made the bubble lie about the other.

Only the resolution side has ever been the truth, so this is that version,
with one addition the prediction side needs: `visible_to`. In a hotseat game
the player must not be shown movements they did not order, so the prediction
call passes the set of nations whose orders it may reveal and the resolution
call passes None, meaning everything.

The pairs are found up front but the units on each side are gathered per pair,
as the resolver walks them. That ordering is load-bearing: a unit killed in one
engagement is removed from its province, so it must not still be counted in the
next engagement that province takes part in.

**Who then shoots at whom, once they are in the same place.** `firing_lines`,
below. Four callers need that answer -- the tile fight, the head-on fight, the
prediction bubble and the sidebar's combat roster -- which is three more than
have ever agreed on it.

Imports data.queries in-function only -- queries is a cycle participant, and
this module is meant to be safe to import from anywhere.
"""

from collections import namedtuple

#: One nation's contribution to one fight: `units` fire a single pooled volley
#: at `targets`, and at nothing else.
FiringLine = namedtuple("FiringLine", "owner units targets")


def firing_lines(sides, nation_data):
    """Which units each nation's volley lands on, for one fight.

    `sides` is a list of unit lists. One side is a tile: everyone standing here
    can fight everyone else standing here. Two sides is a head-on clash between
    tiles, where a unit fights only across the divide -- two nations at war with
    each other while marching the same way settle it where they land, not while
    they cross.

    Returns a FiringLine for every nation that has somebody to shoot at, in
    first-appearance order. A nation with no enemy among the units it can reach
    is absent from the result entirely: it is here by military access, or at war
    with somebody who is not, and takes no part in the fight at all -- no damage
    dealt, none taken, and none of the things a battle does to the units caught
    in it.

    A volley belongs to a column, not to a flag: a nation with units marching
    both ways down the same edge fields one firing line per direction, since
    those are two bodies of troops meeting two different enemies.

    Hostility is read both ways round. A scenario or an editor can leave one
    nation's war list out of step with the other's, and the pairwise loop this
    replaced resolved that case differently depending on the order the units
    happened to sit in the province -- which is not a rule, it is an accident.
    """
    from data import queries

    def hostile(a, b):
        return (queries.are_at_war(a, b, nation_data)
                or queries.are_at_war(b, a, nation_data))

    # Group into columns -- (which side, whose) -- keeping first-appearance
    # order so the same fight always resolves the same way.
    columns = []
    seen = {}
    for side_index, side in enumerate(sides):
        for unit in side:
            owner = unit.get("owner")
            if not owner:
                continue
            key = (side_index, owner)
            if key not in seen:
                seen[key] = len(columns)
                columns.append((side_index, owner, []))
            columns[seen[key]][2].append(unit)

    across_only = len(sides) > 1

    lines = []
    for side_index, owner, units in columns:
        targets = [unit
                   for other_side, other_owner, other_units in columns
                   if (other_side != side_index or not across_only)
                   and hostile(owner, other_owner)
                   for unit in other_units]
        if targets:
            lines.append(FiringLine(owner, units, targets))
    return lines


def movers_into(province, dest_id, visible_to=None):
    """The units in `province` whose next step is into `dest_id`.

    Only MOVE orders carry a path, so testing for one is the same as testing
    the order type; both call sites did it one way or the other.
    """
    movers = []
    for unit in province.get("units", []):
        order = unit.get("order") or {}
        path = order.get("path")
        if not path or path[0] != dest_id:
            continue
        if visible_to is not None and unit.get("owner") not in visible_to:
            continue
        movers.append(unit)
    return movers


def find_meeting_pairs(map_data, nation_data, visible_to=None):
    """Every pair of provinces whose garrisons crossed paths this turn.

    Returned as sorted (id_a, id_b) tuples, each appearing once, in the order
    they were found -- the resolver depends on processing them one at a time.
    """
    from data import queries

    # Who is stepping into where, and from where.
    incoming = {}
    for province in map_data.values():
        for unit in province.get("units", []):
            order = unit.get("order") or {}
            if order.get("type") != "MOVE" or not order.get("path"):
                continue
            if visible_to is not None and unit.get("owner") not in visible_to:
                continue
            incoming.setdefault(order["path"][0], []).append((unit, province["id"]))

    pairs = []
    seen = set()
    for dest_id, arrivals in incoming.items():
        for unit, origin_id in arrivals:
            # Anyone heading the other way down the same edge, who we are at war with.
            crossing = any(
                other_origin == dest_id
                and queries.are_at_war(unit["owner"], other["owner"], nation_data)
                for other, other_origin in incoming.get(origin_id, [])
            )
            if not crossing:
                continue
            pair = tuple(sorted([origin_id, dest_id]))
            if pair not in seen:
                seen.add(pair)
                pairs.append(pair)
    return pairs


def meeting_sides(id_to_province, pair, visible_to=None):
    """The two sides of one meeting engagement, read fresh from the map."""
    prov_a = id_to_province[pair[0]]
    prov_b = id_to_province[pair[1]]
    return (prov_a, prov_b,
            movers_into(prov_a, pair[1], visible_to),
            movers_into(prov_b, pair[0], visible_to))
