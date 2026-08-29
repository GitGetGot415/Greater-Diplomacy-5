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
pair of hostile **sides**. A side is a coalition -- everyone here who is fighting
this particular enemy together -- not a single nation, which is why two allies
facing two allies is one battle rather than four separate quarrels.
`c.COMBAT_WIDTH` is a budget for the whole tile, divided among the lanes, and
damage never crosses a lane boundary. Units past a side's allowance wait in
reserve, where they neither deal damage nor take it -- bombardment is the only
thing that reaches them.

The invariants the rest of the game is entitled to assume:

1. A nation fires **once** per resolution. A unit holding two fronts -- which
   is how a nation short of men faces more than one hostile side at a time --
   splits its attack between them rather than firing twice. It takes fire from
   both, which is what being outnumbered on two fronts costs.
2. Every lane has exactly two sides, and damage never crosses between lanes.
3. A side's slot allowance is shared between its members by max-min fair split
   (see `share_slots`), so a big ally cannot squeeze a small one out and a
   small one cannot hoard width it has no units for. An allowance is a floor
   on what a member gets, not a cap on what the side fields: if the split
   leaves a slot that nobody's allowance covers and somebody present has a
   unit spare, `_topup` seats it. An empty slot helps nobody.
4. Total front units across every lane equals `c.COMBAT_WIDTH`, unless a floor
   forced it higher -- `c.MIN_LANE_SLOTS_PER_SIDE` per side, or the one unit
   every member nation present is guaranteed -- or there were not enough units
   present to fill the tile.
5. A nation is in *every* lane it is in. It seats one unit in each before any
   lane gets a second, and if it runs out it doubles units up rather than
   abandoning a front. Nobody dodges a fight by looking the other way, and
   nobody is spared one by their enemy being short of men.
6. A member only ever shoots at units it is personally at war with. Standing
   beside an ally does not enlist you in that ally's other wars.
7. Hostility is read both ways round (see below).

Imports data.queries in-function only -- queries is a cycle participant, and
this module is meant to be safe to import from anywhere.
"""

from collections import namedtuple

import data.constants as c
from map_logic import politics

#: One nation's contribution to one side of one duel. `slots` is its share of
#: the side's allowance; `front` fire and are fired at; `reserve` are present and
#: pinned but untouched until a front slot opens; `targets` are the opposing
#: front units this nation is actually at war with, which is everything it may
#: shoot at.
#:
#: `reserve` is a nation's units left out of every front rank, attributed to its
#: highest-priority lane so the UI lists them exactly once -- it is not "the
#: reserve of this duel specifically".
LaneMember = namedtuple("LaneMember", "nation slots front reserve targets")

#: One side of one duel: the coalition fighting it, and their units pooled.
#:
#: `front` and `reserve` are the members' own lists flattened in member order,
#: so anything that only cares about "who is trading fire here" can read the
#: side and ignore the breakdown. `side_index` is which of `sides` the coalition
#: came from, which is what stops a head-on clash pairing a column with itself.
LaneSide = namedtuple("LaneSide", "nations side_index slots members front reserve")

#: One duel: two sides, and the per-side slot allowance they were given.
#: `index` is stable and is what the UI numbers lanes by.
Lane = namedtuple("Lane", "index slots a b")

#: The whole fight in one place -- one tile, or one edge between two.
#:
#: engaged    -- nations holding a front slot in at least one lane, in
#:               first-appearance order
#: bystanders -- nations present and in no lane, same order: here on military
#:               access, or at war with somebody who is not standing here
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
    """Pairs of coalition-group indices to fight as lanes, in a stable order.

    One lane per pair of hostile coalitions, and that is the whole rule. An
    earlier version matched the two groups member to member round-robin, which
    put A against X and B against Y and left A and Y unable to touch each other
    while standing on the same tile at war -- the "strange how that works" save,
    where Germany and the United Kingdom shared a province and fought different
    people. A front is not a set of private quarrels.

    A pair becomes a lane as soon as *any* member of one is at war with any
    member of the other. Which of them may then shoot which is settled per
    member, in _targets_for -- an ally standing here does not inherit the war.
    """
    def can_fight(i, j):
        return ((not across_only or columns[i][0] != columns[j][0])
                and hostile(columns[i][1], columns[j][1]))

    duels = []
    for gi in range(len(coalition_groups)):
        for gj in range(gi + 1, len(coalition_groups)):
            left, right = coalition_groups[gi], coalition_groups[gj]
            if any(can_fight(i, j) for i in left for j in right):
                duels.append((gi, gj))
    return duels


def share_slots(demands, slots):
    """Max-min fair split of `slots` among members wanting `demands`.

    Allies on one side share the side's width rather than cutting it into equal
    pieces, because equal pieces waste it: nine units and one unit given three
    slots each fields four when it could field six. Each pass hands the
    remaining width out evenly among whoever still wants more and drops anyone
    satisfied, so the width flows to where there are bodies for it.

    The guarantee that comes with it is the important half. A member can never
    be pushed below what an even split would have given it -- it only ever
    receives *less* than its even share by not wanting the rest. Nine against
    one over six slots is 5/1; five against five is 3/3, and no amount of extra
    units on one side moves that.

    `demands` is a list, and ties are broken by its order, so the caller's
    ordering (column order, i.e. first appearance) is what makes this
    deterministic.
    """
    alloc = [0] * len(demands)
    remaining = slots
    wanting = [i for i, want in enumerate(demands) if want > 0]

    while remaining > 0 and wanting:
        # max(1, ...) so the last few slots are handed out one at a time in
        # member order rather than the loop stalling on a share of zero.
        share = max(1, remaining // len(wanting))
        for i in list(wanting):
            if remaining <= 0:
                break
            take = min(share, demands[i] - alloc[i], remaining)
            alloc[i] += take
            remaining -= take
            if alloc[i] >= demands[i]:
                wanting.remove(i)

    # Nobody present is left with nothing to fight with, even when there are
    # more allies here than there is width to go round. The same call the
    # MIN_LANE_SLOTS_PER_SIDE floor makes one level up: a small ally that turned
    # up is in the battle, and the width gives way rather than the ally.
    for i, want in enumerate(demands):
        if want > 0 and alloc[i] == 0:
            alloc[i] = 1
    return alloc


def _lane_membership(columns, coalition_groups, duels, can_fight):
    """Which lanes each column fights in, and who it may shoot at there.

    Returns ({column: [duel_index, ...]}, {(column, duel): [opposing columns]}).

    A column joins its coalition's lane only if it is at war with somebody on
    the other side of it. An ally that turned up to fight a different enemy is
    standing here, not fighting here: it would otherwise eat width in a battle
    where it can neither deal nor take a shot.
    """
    lanes_of = {}
    foes = {}
    for duel_index, (left_group, right_group) in enumerate(duels):
        for mine, theirs in ((coalition_groups[left_group], coalition_groups[right_group]),
                             (coalition_groups[right_group], coalition_groups[left_group])):
            for i in mine:
                enemies = [j for j in theirs if can_fight(i, j)]
                if not enemies:
                    continue
                lanes_of.setdefault(i, []).append(duel_index)
                foes[(i, duel_index)] = enemies
    return lanes_of, foes


def _availability(columns):
    """{column: units, in the order that column would rather field them}.

    Worked out once per column rather than once per lane it fights in: this is
    a sort, and build_battle runs every frame for the sidebar and the map's
    combat bubbles.

    Holding a unit back is a preference, not a veto: RESERVE reorders this list,
    it does not shorten it. A held unit goes to the back and is seated only once
    every unheld one already has a slot -- which is the rotation the flag is for
    -- but it is still seated rather than leaving the width short.

    Filtering held units out instead is what left front slots empty with bodies
    standing on the tile. _caps reads its demand off this list, so a nation that
    held four of ten units back was not merely fielding its healthy six: it was
    *granted* six slots out of the six it was entitled to, and the four it gave
    up went to nobody. Province 1724 of the "province 907" save is the extreme
    of it -- Japan seating one unit of six slots with five more standing there.

    The `or pool` fallback this replaced was the same idea applied only to the
    all-held case, after a stale flag on a wounded unit made Nationalist China's
    only unit on a tile refuse to fight Japan and the battle silently not happen.
    """
    available = {}
    for i, (_side, _owner, units) in enumerate(columns):
        # sorted() is stable, so equal-attack units keep their province order.
        pool = sorted(units, key=lambda u: u.get("attack", c.DEFAULT_UNIT_ATK),
                      reverse=True)
        held = [u for u in pool if u.get("combat_stance") == "RESERVE"]
        available[i] = [u for u in pool if u.get("combat_stance") != "RESERVE"] + held
    return available


def _caps(coalition_groups, duels, lanes_of, available, slots, eager=()):
    """{(column, duel): slots} -- each side's allowance split among its members.

    The split is max-min fair (see share_slots), so allies pool their width
    instead of quartering it. A member's demand is simply how many units it
    brought: asking for more than that would take width off an ally that has
    bodies for it.

    `eager` names columns to weigh as if they had brought a full rank instead.
    Nothing in a real fight passes it -- a nation cannot seat men who are not
    there -- but the AI's "how much room is there for me here?" is a question
    about the fight it would be in after marching, not the one it is standing in
    now, and answering that with today's headcount is what made a battle tile
    look full to the very reserves it needed. See nation_front_capacity.
    """
    caps = {}
    for duel_index, groups in enumerate(duels):
        for group_index in groups:
            members = [i for i in coalition_groups[group_index]
                       if duel_index in lanes_of.get(i, ())]
            demands = [slots if i in eager else len(available[i]) for i in members]
            for i, allowance in zip(members, share_slots(demands, slots)):
                caps[(i, duel_index)] = allowance
    return caps


def _seat(columns, duels, lanes_of, foes, caps, available):
    """Which units hold which front slots. Returns {(column, duel): [units]}.

    Per nation, in priority order: honour a valid `lane_target` pin, then seat
    one unit in every lane it is in, then fill lanes to the nation's allowance
    in priority order. Priority is the heaviest enemy first, so the depth goes
    where the fighting is.

    Mandatory coverage before depth is what stops a nation concentrating
    everything into one duel and letting the others dissolve, which would let a
    defender take zero damage from an enemy that had committed to fighting it.
    """
    def enemy_weight(column_index, duel_index):
        return sum(u.get("attack", c.DEFAULT_UNIT_ATK)
                   for j in foes[(column_index, duel_index)]
                   for u in columns[j][2])

    seats = {}
    for column_index in range(len(columns)):
        my_lanes = lanes_of.get(column_index)
        if not my_lanes:
            continue
        my_lanes = sorted(my_lanes, key=lambda d: (-enemy_weight(column_index, d), d))
        for duel_index in my_lanes:
            seats[(column_index, duel_index)] = []

        fieldable = available[column_index]
        pinned = set()

        # A pin names an enemy nation, not a lane -- "fight these people" is the
        # gesture, and it survives the lanes being redrawn around it.
        for unit in fieldable:
            target = unit.get("lane_target")
            if not target:
                continue
            for duel_index in my_lanes:
                if all(columns[j][1] != target for j in foes[(column_index, duel_index)]):
                    continue
                if len(seats[(column_index, duel_index)]) < caps[(column_index, duel_index)]:
                    seats[(column_index, duel_index)].append(unit)
                    pinned.add(id(unit))
                break

        rest = [u for u in fieldable if id(u) not in pinned]

        for duel_index in my_lanes:
            if not rest:
                break
            if not seats[(column_index, duel_index)]:
                seats[(column_index, duel_index)].append(rest.pop(0))

        for duel_index in my_lanes:
            while rest and len(seats[(column_index, duel_index)]) < caps[(column_index, duel_index)]:
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
            for unit in fieldable:
                seats[(column_index, duel_index)].append(unit)
                break

    return seats


def _topup(coalition_groups, duels, lanes_of, available, slots, seats):
    """Seats spare men into slots a side left empty. Modifies `seats` in place.

    _caps hands each member an allowance and _seat fills it, which is the whole
    story when a side is one nation. It is not when a side is a coalition and
    its members are in different numbers of lanes: a nation fighting two duels
    is credited the same demand in each, spends its men on the heavier one
    first, and arrives at the lighter one empty-handed -- while the ally beside
    it, whose allowance was already met, still has units standing there. The
    allowance says that ally may not take more; the width says the slot exists;
    nobody fills it.

    So this is the invariant, enforced after the allowances have had their say:
    **no side leaves a front slot empty while one of its members has a unit
    standing here that is not already fighting.** Fewest seats first, so the
    spare width lands the way share_slots would have handed it out.

    Only units seated in *no* lane are eligible. Doubling a unit up buys
    nothing -- a nation fires once and _lane_shares divides that one volley, so
    a unit added to a second lane weakens the first by exactly what it adds
    here, and takes fire in both. The empty-lane guard in _seat already doubles
    up in the one case where it is worth it: a front that would otherwise
    dissolve entirely.
    """
    seated_anywhere = {id(u) for units in seats.values() for u in units}

    for duel_index, pair in enumerate(duels):
        for group_index in pair:
            members = [i for i in coalition_groups[group_index]
                       if duel_index in lanes_of.get(i, ())]
            if not members:
                continue

            seated = sum(len(seats.get((i, duel_index), ())) for i in members)
            spare = {i: [u for u in available[i] if id(u) not in seated_anywhere]
                     for i in members}

            while seated < slots and any(spare[i] for i in members):
                i = min((m for m in members if spare[m]),
                        key=lambda m: (len(seats.get((m, duel_index), ())), m))
                unit = spare[i].pop(0)
                seats.setdefault((i, duel_index), []).append(unit)
                seated_anywhere.add(id(unit))
                seated += 1

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


def build_battle(sides, nation_data, width=None, full_rank_for=None):
    """Who duels whom, and who is in the front rank, for one fight.

    `sides` is a list of unit lists. One side is a tile: everyone standing here
    can fight everyone else standing here. Two sides is a head-on clash between
    tiles, where a lane's two halves must come from different sides -- two
    nations at war with each other while marching the same way settle it where
    they land, not while they cross.

    Every pair of hostile coalitions with units here becomes a lane, and allies
    on one side of it share the width between them. A nation facing two separate
    hostile coalitions holds both fronts at once, splitting its volley between
    them rather than abandoning either -- see _lane_shares. The dissolve below is
    therefore a guard rather than a rule: it can only fire if a column turned up
    with no units at all.

    `full_rank_for` is a nation whose *allowance* is worked out as though it had
    brought a full rank -- see _caps. It changes no unit's seat, only the width
    that nation is credited with, and exists for nation_front_capacity.
    """
    hostile = _hostile(nation_data)
    columns = _columns(sides)
    across_only = len(sides) > 1

    def can_fight(i, j):
        return ((not across_only or columns[i][0] != columns[j][0])
                and hostile(columns[i][1], columns[j][1]))

    groups = _coalition_groups(columns, nation_data)
    duels = _duels(columns, groups, hostile, across_only)
    slots = lane_slots(len(duels), width)
    lanes_of, foes = _lane_membership(columns, groups, duels, can_fight)
    available = _availability(columns)
    eager = ({i for i, col in enumerate(columns) if col[1] == full_rank_for}
             if full_rank_for else ())
    caps = _caps(groups, duels, lanes_of, available, slots, eager)
    seats = _seat(columns, duels, lanes_of, foes, caps, available)
    _topup(groups, duels, lanes_of, available, slots, seats)

    def front(group_index, duel_index):
        return [u for i in groups[group_index]
                for u in seats.get((i, duel_index), ())]

    # A lane needs both halves. With the coverage pass in _seat this can only
    # happen if a column is empty, which _columns makes impossible -- kept as a
    # guard so a future change cannot silently delete a fight instead of failing.
    live = [duel_index
            for duel_index, (left, right) in enumerate(duels)
            if front(left, duel_index) and front(right, duel_index)]

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

        def members_of(group_index, duel_index=duel_index):
            out = []
            for i in groups[group_index]:
                if duel_index not in lanes_of.get(i, ()):
                    continue
                reserve = ([u for u in columns[i][2] if id(u) not in seated_ids]
                           if reserve_lane.get(i) == duel_index else [])
                out.append((i, reserve))
            return out

        def side_for(group_index, duel_index=duel_index):
            members = []
            for i, reserve in members_of(group_index):
                # Only what this member is personally at war with. An ally is
                # not enlisted in wars it never joined by standing next to you.
                targets = [u for j in foes[(i, duel_index)]
                           for u in seats.get((j, duel_index), ())]
                # _topup can seat a member past the allowance _caps granted it,
                # when the side would otherwise have left width standing empty.
                # What it holds is then what it seated: slots_held reads this,
                # and a member reading 3/2 in the battle screen is nonsense.
                # (not named `front` -- that is the helper defined above)
                seated = seats[(i, duel_index)]
                members.append(LaneMember(columns[i][1],
                                          max(caps[(i, duel_index)], len(seated)),
                                          seated, reserve, targets))
                engaged[columns[i][1]] = None
            # Every column in a coalition came from the same side of the fight;
            # _coalition_groups never merges across one.
            return LaneSide(tuple(m.nation for m in members),
                            columns[groups[group_index][0]][0],
                            slots, members,
                            [u for m in members for u in m.front],
                            [u for m in members for u in m.reserve])

        lanes.append(Lane(len(lanes), slots, side_for(left), side_for(right)))

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


def health_damage_multiplier(unit):
    """How much of a unit's attack lands, scaled by how hurt it is.

    1.0 at full health, c.DAMAGE_AT_ZERO_HEALTH at 0 health, linear between --
    a wounded unit still fights, just weaker. c.DAMAGE_AT_ZERO_HEALTH = 1
    disables this entirely (every unit always deals full damage). The constant
    is a live mirror of the scenario's "damage_at_zero_health" setting -- see
    queries.apply_global_scenario_flags -- so a slider change takes effect
    without threading a settings dict through every combat call.
    """
    max_hp = unit.get("max_health") or c.DEFAULT_UNIT_HP
    frac = max(0.0, min(1.0, unit.get("health", 0) / max_hp))
    floor = c.DAMAGE_AT_ZERO_HEALTH
    return floor + (1.0 - floor) * frac


def health_defense_multiplier(unit):
    """How much of a unit's defense still blocks incoming damage, scaled by how hurt it is.

    Mirrors health_damage_multiplier: 1.0 at full health, c.DEFENSE_AT_ZERO_HEALTH
    at 0 health, linear between. c.DEFENSE_AT_ZERO_HEALTH = 1 disables this
    entirely (defense always holds at full value). The constant is a live
    mirror of the scenario's "defense_at_zero_health" setting -- see
    queries.apply_global_scenario_flags.
    """
    max_hp = unit.get("max_health") or c.DEFAULT_UNIT_HP
    frac = max(0.0, min(1.0, unit.get("health", 0) / max_hp))
    floor = c.DEFENSE_AT_ZERO_HEALTH
    return floor + (1.0 - floor) * frac


def effective_damage_multiplier(unit, nation_data=None):
    """Everything that scales one unit's damage: its wounds, then its politics.

    The one figure a screen must print its attack through. Both callers below
    -- the volley and the bombardment pass -- apply exactly this product, so a
    unit panel scaling by health_damage_multiplier alone advertises a number
    the fight will not produce. That drift is the whole reason this exists
    rather than the two multipliers being multiplied at each of the five sites
    that need them.

    `nation_data` is optional because the callers that compare raw unit stats
    -- what a factory would build, what a tech unlocks -- want the stat, not
    this particular country's version of it. Omitting it reads as centrist.
    """
    political = (politics.damage_multiplier(nation_data, unit.get("owner"))
                 if nation_data else 1.0)
    return health_damage_multiplier(unit) * political


def volley(units, shares=None, nation_data=None):
    """Attack of a front rank, with any unit fighting on two fronts counted once.

    `shares` is Battle.shares. Omitting it reads every unit as holding this
    front alone, which is what a caller measuring a hypothetical rank wants.

    `nation_data` turns on the political damage multiplier, which is applied per
    unit rather than to the total: a LaneMember's front is one nation's, but a
    LaneSide's front is a whole coalition's, and the map's prediction bubbles
    read the latter.
    """
    return sum(u.get("attack", c.DEFAULT_UNIT_ATK) / (shares or {}).get(id(u), 1)
               * effective_damage_multiplier(u, nation_data)
               for u in units)


def exchange(battle, nation_data=None):
    """[(targets, total_attack)] for every nation in every lane.

    One shot per member rather than one per side, because a side is a coalition
    and its members do not all share the same war. Where everyone on one side is
    at war with everyone on the other -- the ordinary case -- this is exactly
    the pooled answer, since every member's targets are the whole enemy front.

    Measured but not applied, so a caller can land them all at once. That is
    what keeps a fight simultaneous: a nation wiped out this turn still fires
    this turn, and nobody's share depends on who happened to resolve first.
    """
    shots = []
    for lane in battle.lanes:
        for side in (lane.a, lane.b):
            for member in side.members:
                if member.targets:
                    shots.append((member.targets,
                                  volley(member.front, battle.shares, nation_data)))
    return shots


def projected_incoming_damage(battle, nation_data=None, defense_bonus_fn=None):
    """Returns the damage each unit would take in ``battle``.

    This is the non-mutating counterpart to the damage arithmetic in
    ``combat_processor.apply_group_damage``. AI planning needs to ask whether
    a hypothetical charge leaves anyone alive, and using the same lane volley,
    health-scaled defense, and political damage rules keeps that prediction in
    step with the resolver.

    ``defense_bonus_fn`` is optional so callers that model a fortified tile can
    include its bonus without making fortification part of the general combat
    rules.
    """
    incoming = {}
    for targets, total_attack in exchange(battle, nation_data):
        if not targets:
            continue
        damage_per_unit = total_attack / len(targets)
        for unit in targets:
            defense_bonus = defense_bonus_fn(unit) if defense_bonus_fn else 0
            defense = (unit.get("defense", 0)
                       * health_defense_multiplier(unit)
                       + defense_bonus)
            incoming[id(unit)] = incoming.get(id(unit), 0.0) + max(
                0.0, damage_per_unit - defense)
    return incoming


def slots_held(battle, nation):
    """How many front slots `nation` was given across this whole fight.

    One answer, because two callers used to work it out from the lane list
    themselves and both would have had to learn that a side's allowance is now
    split between its members.
    """
    return sum(member.slots
               for lane in battle.lanes
               for side in (lane.a, lane.b)
               for member in side.members
               if member.nation == nation)


def nation_front_capacity(nation, province, nation_data, width=None):
    """How many front slots `nation` could fill on this tile.

    What the AI needs to answer "is this tile full for me?". A tile with no
    fight on it answers with a typical lane, since that is what would open if
    one started.

    Could fill, not does fill. This used to hand back slots_held, which _caps
    bounds by the units already standing here -- so a lone defender was told its
    tile seats one, ai_movement doubled that for the relief rank, and a province
    with five empty slots in front of it sorted as full against a quiet border
    worth twelve. One man held the line while seven reserves next door marched
    somewhere else, every turn: saves/THEYRE NOT PUTTING IN THEIR RESERVES.
    Asking instead for the allowance a full rank would be given still splits the
    width fairly against allies who are actually here; it only stops our own
    absence from being the thing that makes the tile look full.
    """
    battle = build_battle([list(province.get("units", ()))], nation_data, width,
                          full_rank_for=nation)
    return slots_held(battle, nation) or c.LANE_SLOTS_TYPICAL


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
