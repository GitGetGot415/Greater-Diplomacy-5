"""Who runs a faction, and how that can change hands.

A faction's leader was whoever created it, permanently. Everything leadership
carries -- negotiating for the whole bloc at the peace table, kicking members,
disbanding, renaming -- stayed with that nation however the war went, so a
member that outgrew its founder several times over still had to ask permission
to open talks, and still had its territory put on the table by somebody else.

Leadership is now taken rather than granted, and the rule for taking it lives
here alone: the tick that measures it, the screen that offers the button, the AI
that decides to press it and the pass that carries it out all ask this module
rather than each keeping their own copy of "stronger". Two definitions of
stronger would be two different answers to one question, which is how Round 3's
war calls came to disagree with themselves.

The rule: outweigh the leader by FACTION_CHALLENGE_MARGIN for
FACTION_CHALLENGE_TURNS consecutive turns. Both halves matter. Without the
margin, two comparable powers would pass the chair back and forth on the noise
of units being built and lost; without the streak, one good turn would be
enough.

Stdlib, `data` and war_score only.
"""

import data.constants as c
from data import queries
from map_logic.diplomacy import war_score


def power_of(map_screen, nation, world=None):
    """How heavy this nation is, on the same scale the peace table uses."""
    return war_score.nation_power(map_screen, nation, world)


def _leader_of(nation, nation_data):
    faction = nation_data.get(nation, {}).get("faction", "")
    if not faction:
        return None
    leader = queries.get_faction_leader(faction, nation_data)
    return leader if leader and leader != nation else None


def eligible(nation, nation_data):
    """Whether this nation is even in a position to challenge.

    In a faction, not running it, and free to decide its own alignment -- a
    puppet follows its master in and out of factions and does not get to lead
    one out from under it.
    """
    if not _leader_of(nation, nation_data):
        return False
    return queries.can_choose_own_faction(nation, nation_data)


def outweighs(map_screen, nation, world=None):
    """Whether `nation` is far enough ahead of its leader to be gaining ground.

    False for anyone with no leader to be ahead of, so a caller can ask this of
    any nation without checking first.
    """
    leader = _leader_of(nation, map_screen.nation_data)
    if not leader:
        return False

    mine = power_of(map_screen, nation, world)
    theirs = power_of(map_screen, leader, world)
    if mine <= 0:
        return False
    return mine >= theirs * c.FACTION_CHALLENGE_MARGIN


def turns_held(nation, nation_data):
    """How many consecutive turns this nation has outweighed its leader."""
    return int(nation_data.get(nation, {}).get("faction_pressure", 0) or 0)


def can_claim(map_screen, nation):
    """Whether the claim would succeed if it were made this turn."""
    return (eligible(nation, map_screen.nation_data)
            and turns_held(nation, map_screen.nation_data) >= c.FACTION_CHALLENGE_TURNS)


def standing(map_screen, nation, world=None):
    """(turns held, turns needed, ahead right now) for a member, or None.

    What the faction screen prints. None when the question does not apply --
    no faction, already leading it, or a puppet.
    """
    if not eligible(nation, map_screen.nation_data):
        return None
    return (turns_held(nation, map_screen.nation_data), c.FACTION_CHALLENGE_TURNS,
            outweighs(map_screen, nation, world))


def tick(map_screen, world=None):
    """Ages every member's claim on its faction's leadership by one turn.

    Walks factions rather than nations so each leader is weighed once instead of
    once per member. Runs before any action resolves, so the button a player
    sees, the number the AI decides on and the state the claim executes against
    are the same one.
    """
    nation_data = map_screen.nation_data

    leaders = {}
    members = {}
    for nation, data in nation_data.items():
        if not isinstance(data, dict):
            continue
        faction = data.get("faction", "")
        if not faction:
            data.pop("faction_pressure", None)
            continue
        if data.get("is_faction_leader"):
            leaders[faction] = nation
        members.setdefault(faction, []).append(nation)

    for faction, roster in members.items():
        leader = leaders.get(faction)
        if not leader:
            # A faction with nobody at the head of it -- the leader was annexed,
            # or a save predates this. Nothing to measure against; leave the
            # counters where they are rather than crediting everyone a turn.
            continue

        bar = power_of(map_screen, leader, world) * c.FACTION_CHALLENGE_MARGIN
        for nation in roster:
            data = nation_data[nation]
            if nation == leader or not queries.can_choose_own_faction(nation, nation_data):
                data.pop("faction_pressure", None)
                continue

            mine = power_of(map_screen, nation, world)
            if mine > 0 and mine >= bar:
                data["faction_pressure"] = turns_held(nation, nation_data) + 1
            else:
                data.pop("faction_pressure", None)


def transfer(nation_data, old_leader, new_leader):
    """Moves the chair. Everything else about the faction stays where it is.

    Its name, its roster and its pre-war map are all keyed by the faction rather
    than by whoever leads it, so a handover touches two booleans and the grudge
    it leaves behind. Every member's count goes back to zero: the new leader is
    a new bar, and a nation that had been closing on the old one has not yet
    outweighed anybody.
    """
    faction = nation_data.get(new_leader, {}).get("faction", "")

    for member in queries.get_faction_members(faction, nation_data):
        nation_data[member]["is_faction_leader"] = (member == new_leader)
        nation_data[member].pop("faction_pressure", None)

    if old_leader in nation_data:
        nation_data[old_leader]["is_faction_leader"] = False
        queries.add_temporary_modifier(old_leader, new_leader, "deposed",
                                       c.REL_MOD_DEPOSED, nation_data)
    return faction
