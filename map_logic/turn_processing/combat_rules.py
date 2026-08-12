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

**Who then duels whom, once they are in the same place.** `build_battle`, below.
Four callers need that answer -- the tile fight, the head-on fight, the
prediction bubble and the sidebar's combat roster -- which is three more than
have ever agreed on it.

A tile is not one pot. It is a container that splits into *lanes*: one duel per
pair of hostile powers standing on it. `c.COMBAT_WIDTH` is a budget for the
whole tile, divided among those lanes, and damage never crosses a lane
boundary. Units past a lane's allowance wait in reserve, where they neither
deal damage nor take it -- bombardment is the only thing that reaches them.

The invariants the rest of the game is entitled to assume:

1. A nation fires **once** per resolution. A unit holding two fronts -- which
   is how a nation short of men covers more duels than it has units -- splits
   its attack between them rather than firing twice. It takes fire from both,
   which is what being outnumbered on two fronts costs.
2. Every lane has exactly two nations, and damage never crosses between lanes.
3. `len(side.front) <= lane.slots`, always.
4. Total front units across every lane equals `c.COMBAT_WIDTH`, unless
   `c.MIN_LANE_SLOTS_PER_SIDE` forced it higher or there were not enough units
   present to fill the tile.
5. A nation is in *every* lane it is in. It seats one unit in each before any
   lane gets a second, and if it runs out it doubles units up rather than
   abandoning a front. Nobody dodges a fight by looking the other way, and
   nobody is spared one by their enemy being short of men.
6. Hostility is read both ways round (see below).

Imports data.queries in-function only -- queries is a cycle participant, and
this module is meant to be safe to import from anywhere.
"""

from collections import namedtuple

import data.constants as c

#: One nation's half of one duel. `front` fire and are fired at; `reserve` are
#: present and pinned but untouched until a front slot opens. `side_index` is
#: which of `sides` they came from, which is what stops a head-on clash pairing
#: a column with itself.
#:
#: `reserve` is a nation's units left out of every front rank, attributed to its
#: highest-priority lane so the UI lists them exactly once -- it is not "the
#: reserve of this duel specifically".
LaneSide = namedtuple("LaneSide", "nation side_index front reserve")

#: One duel: two nations, and the per-side slot allowance they were given.
#: `index` is stable and is what the UI numbers lanes by.
Lane = namedtuple("Lane", "index slots a b")

#: The whole fight in one place -- one tile, or one edge between two.
#:
#: engaged    -- nations holding a front slot in at least one lane, in
#:               first-appearance order
#: bystanders -- nations present and in no lane, same order: here on military
#:               access, at war with somebody who is not standing here, or short
#:               enough of units that the lane they would have held dissolved
#: width      -- distinct units holding a front slot anywhere in this fight
#: shares     -- {id(unit): fronts it is holding}, so a unit spread over two
#:               duels fires one volley split between them rather than two
Battle = namedtuple("Battle", "lanes engaged bystanders width shares")


def _hostile(nation_data):
    """Two-way war test.

    A scenario or an editor can leave one nation's war list out of step with the
    other's, and the pairwise loop this module replaced resolved that case
    differently depending on the order the units happened to sit in the
    province -- which is not a rule, it is an accident.
    """
    from data import queries

    def hostile(a, b):
        return (queries.are_at_war(a, b, nation_data)
                or queries.are_at_war(b, a, nation_data))
    return hostile


def _columns(sides):
    """Group units into (side_index, owner) columns, in first-appearance order.

    Keeping first-appearance order is what makes the same fight always resolve
    the same way. A volley belongs to a column, not to a flag: a nation with
    units marching both ways down the same edge fields one column per direction,
    since those are two bodies of troops meeting two different enemies.
    """
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
    return columns


def _coalition_groups(columns, nation_data):
    """Column indices merged into coalitions, each group in column order.

    Pairing every hostile pair of nations would break the case the lane model
    exists for: in a real alliance war A is at war with both X and Y, so A+B
    against X+Y would spawn four duels rather than the two the front actually
    has. Two columns merge when they are on the same side, not at war, and
    friendly both ways round -- allies, faction partners, or an imperial family.
    A neutral standing here on access merges with nobody.

    Where nobody is allied this degrades exactly to one coalition per nation, so
    it is a strict generalisation of the pairwise answer rather than a different
    rule for a special case.
    """
    from data import queries

    hostile = _hostile(nation_data)
    parent = list(range(len(columns)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(columns)):
        for j in range(i + 1, len(columns)):
            side_i, owner_i, _ = columns[i]
            side_j, owner_j, _ = columns[j]
            if side_i != side_j or owner_i == owner_j or hostile(owner_i, owner_j):
                continue
            if (owner_j in queries.friendly_nations_view(owner_i, nation_data)
                    and owner_i in queries.friendly_nations_view(owner_j, nation_data)):
                root_i, root_j = find(i), find(j)
                # The lower index always wins, so a group's root is its earliest
                # member and walking columns in order yields the groups in order.
                if root_i != root_j:
                    parent[max(root_i, root_j)] = min(root_i, root_j)

    groups = {}
    for i in range(len(columns)):
        groups.setdefault(find(i), []).append(i)
    # Never iterate the union-find map itself -- dict insertion order here is
    # ascending root index, which is column order.
    return list(groups.values())


def coalitions(owners, nation_data):
    """The coalitions a list of nation names falls into, for tests and the UI."""
    columns = _columns([[{"owner": owner} for owner in owners]])
    return [[columns[i][1] for i in group]
            for group in _coalition_groups(columns, nation_data)]


def lane_slots(num_lanes, width=None):
    """How many units each side of a lane may seat, given how many lanes there are."""
    if num_lanes <= 0:
        return 0
    if width is None:
        width = c.COMBAT_WIDTH
    return max(c.MIN_LANE_SLOTS_PER_SIDE, width // (2 * num_lanes))


def _duels(columns, coalition_groups, hostile, across_only):
    """Column-index pairs to fight as lanes, in a stable order.

    Hostile coalitions are matched member to member round-robin, so two allies
    facing two allies produce two duels rather than four. The coverage pass
    afterwards catches anyone the round-robin skipped, which only happens when
    war lists are asymmetric enough that some members are hostile and others
    are not.
    """
    def can_fight(i, j):
        return ((not across_only or columns[i][0] != columns[j][0])
                and hostile(columns[i][1], columns[j][1]))

    duels = []
    seen = set()

    def add(i, j):
        if (i, j) in seen:
            return
        seen.add((i, j))
        duels.append((i, j))

    for gi in range(len(coalition_groups)):
        for gj in range(gi + 1, len(coalition_groups)):
            left, right = coalition_groups[gi], coalition_groups[gj]
            pairs = [(i, j) for i in left for j in right if can_fight(i, j)]
            if not pairs:
                continue

            for k in range(max(len(left), len(right))):
                i, j = left[k % len(left)], right[k % len(right)]
                if can_fight(i, j):
                    add(i, j)

            covered = {i for i, _ in duels} | {j for _, j in duels}
            for i, j in pairs:
                if i not in covered or j not in covered:
                    add(i, j)
                    covered.add(i)
                    covered.add(j)

    return duels


def _seat(columns, duels, slots):
    """Which units hold which front slots. Returns {(column, duel): [units]}.

    Per nation, in priority order: honour a valid `lane_target` pin, then seat
    one unit in every lane it is in, then fill lanes to `slots` in priority
    order. Priority is the heaviest enemy first, so the depth goes where the
    fighting is.

    Mandatory coverage before depth is what stops a nation concentrating
    everything into one duel and letting the others dissolve, which would let a
    defender take zero damage from an enemy that had committed to fighting it.
    """
    lanes_of = {}
    for duel_index, (left, right) in enumerate(duels):
        lanes_of.setdefault(left, []).append(duel_index)
        lanes_of.setdefault(right, []).append(duel_index)

    def opponent(column_index, duel_index):
        left, right = duels[duel_index]
        return right if left == column_index else left

    def enemy_weight(column_index, duel_index):
        other = columns[opponent(column_index, duel_index)][2]
        return sum(u.get("attack", c.DEFAULT_UNIT_ATK) for u in other)

    seats = {}
    for column_index, (_side, _owner, units) in enumerate(columns):
        my_lanes = lanes_of.get(column_index)
        if not my_lanes:
            continue
        my_lanes = sorted(my_lanes,
                          key=lambda d: (-enemy_weight(column_index, d), d))
        for duel_index in my_lanes:
            seats[(column_index, duel_index)] = []

        # sorted() is stable, so equal-attack units keep their province order.
        pool = sorted(units, key=lambda u: u.get("attack", c.DEFAULT_UNIT_ATK),
                      reverse=True)
        available = [u for u in pool if u.get("combat_stance") != "RESERVE"]
        # Holding a unit back is a preference, not a veto. A nation that held
        # everything back would otherwise vanish from a fight it is standing in
        # the middle of -- which is what a stale flag on a wounded unit did:
        # Nationalist China's only unit on a tile refused to fight Japan and the
        # battle silently did not happen.
        if not available:
            available = pool
        pinned = set()

        for unit in available:
            target = unit.get("lane_target")
            if not target:
                continue
            for duel_index in my_lanes:
                if columns[opponent(column_index, duel_index)][1] != target:
                    continue
                if len(seats[(column_index, duel_index)]) < slots:
                    seats[(column_index, duel_index)].append(unit)
                    pinned.add(id(unit))
                break

        rest = [u for u in available if id(u) not in pinned]

        for duel_index in my_lanes:
            if not rest:
                break
            if not seats[(column_index, duel_index)]:
                seats[(column_index, duel_index)].append(rest.pop(0))

        for duel_index in my_lanes:
            while rest and len(seats[(column_index, duel_index)]) < slots:
                seats[(column_index, duel_index)].append(rest.pop(0))

        # A nation with fewer units than fronts holds every one of them anyway,
        # by fighting on more than one. Leaving a front empty used to dissolve
        # the duel, so a lone defender facing two attackers was fought by
        # whichever of them happened to be heavier and simply ignored the other.
        # Firing once a turn is a rule about a nation's output; it was never a
        # reason for an enemy standing in front of it to be unable to attack.
        for duel_index in my_lanes:
            if seats[(column_index, duel_index)]:
                continue
            for unit in available:
                seats[(column_index, duel_index)].append(unit)
                break

    return seats


def _lane_shares(seats):
    """How many fronts each unit is holding, by id.

    A unit spread over two duels still fires one volley, so its attack is
    divided between them. Without that this is the pair loop the multiparty
    work removed, where a nation at war with three others dealt triple its own
    attack. It takes fire from both, though, which is what being outnumbered on
    two fronts is supposed to cost.
    """
    shares = {}
    for units in seats.values():
        for unit in units:
            shares[id(unit)] = shares.get(id(unit), 0) + 1
    return shares


def build_battle(sides, nation_data, width=None):
    """Who duels whom, and who is in the front rank, for one fight.

    `sides` is a list of unit lists. One side is a tile: everyone standing here
    can fight everyone else standing here. Two sides is a head-on clash between
    tiles, where a lane's two halves must come from different sides -- two
    nations at war with each other while marching the same way settle it where
    they land, not while they cross.

    Every duel between two nations that both have units here becomes a lane. A
    nation short of units holds its extra fronts by fighting on more than one at
    once, splitting its volley between them rather than abandoning any -- see
    _lane_shares. The dissolve below is therefore a guard rather than a rule:
    it can only fire if a column turned up with no units at all.
    """
    hostile = _hostile(nation_data)
    columns = _columns(sides)
    across_only = len(sides) > 1

    duels = _duels(columns, _coalition_groups(columns, nation_data),
                   hostile, across_only)
    slots = lane_slots(len(duels), width)
    seats = _seat(columns, duels, slots)

    # A lane needs both halves. With the coverage pass in _seat this can only
    # happen if a column is empty, which _columns makes impossible -- kept as a
    # guard so a future change cannot silently delete a fight instead of failing.
    live = [duel_index
            for duel_index, (left, right) in enumerate(duels)
            if seats.get((left, duel_index)) and seats.get((right, duel_index))]

    # Everything a nation did not seat in a *surviving* lane, attributed once,
    # to the lane it would reinforce first.
    live_set = set(live)
    seated_ids = {id(u)
                  for (_column, duel_index), units in seats.items()
                  if duel_index in live_set
                  for u in units}
    # seats was filled in each column's own priority order, so the first
    # surviving lane found here is the one that column would reinforce first.
    reserve_lane = {}
    for column_index, duel_index in seats:
        if duel_index in live_set:
            reserve_lane.setdefault(column_index, duel_index)

    lanes = []
    engaged = {}
    for duel_index in live:
        left, right = duels[duel_index]

        def side_for(column_index, duel_index=duel_index):
            reserve = ([u for u in columns[column_index][2] if id(u) not in seated_ids]
                       if reserve_lane.get(column_index) == duel_index else [])
            return LaneSide(columns[column_index][1], columns[column_index][0],
                            seats[(column_index, duel_index)], reserve)

        lanes.append(Lane(len(lanes), slots, side_for(left), side_for(right)))
        engaged[columns[left][1]] = None
        engaged[columns[right][1]] = None

    present = {}
    for _side, owner, _units in columns:
        present[owner] = None

    shares = _lane_shares({key: units for key, units in seats.items()
                           if key[1] in live_set})

    return Battle(lanes,
                  list(engaged),
                  [owner for owner in present if owner not in engaged],
                  # Distinct units, since one holding two fronts is one unit
                  # fighting, not two.
                  len({id(u) for lane in lanes for side in (lane.a, lane.b)
                       for u in side.front}),
                  shares)


def volley(units, shares=None):
    """Attack of a front rank, with any unit fighting on two fronts counted once.

    `shares` is Battle.shares. Omitting it reads every unit as holding this
    front alone, which is what a caller measuring a hypothetical rank wants.
    """
    return sum(u.get("attack", c.DEFAULT_UNIT_ATK) / (shares or {}).get(id(u), 1)
               for u in units)


def exchange(battle):
    """[(targets, total_attack)] for every side of every lane.

    Measured but not applied, so a caller can land them all at once. That is
    what keeps a fight simultaneous: a nation wiped out this turn still fires
    this turn, and nobody's share depends on who happened to resolve first.
    """
    shots = []
    for lane in battle.lanes:
        shots.append((lane.b.front, volley(lane.a.front, battle.shares)))
        shots.append((lane.a.front, volley(lane.b.front, battle.shares)))
    return shots


def nation_front_capacity(nation, province, nation_data, width=None):
    """How many front slots `nation` could fill on this tile.

    What the AI needs to answer "is this tile full for me?". A tile with no
    fight on it answers with a typical lane, since that is what would open if
    one started.
    """
    battle = build_battle([list(province.get("units", ()))], nation_data, width)
    total = sum(lane.slots
                for lane in battle.lanes
                for side in (lane.a, lane.b)
                if side.nation == nation)
    return total or c.LANE_SLOTS_TYPICAL


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
