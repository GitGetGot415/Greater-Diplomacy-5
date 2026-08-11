"""Faction mutations: creating, joining, leaving, kicking, and pulling a
member's wars along with them.

See map_logic/diplomacy/diplomacy_agreements.py for how this fits alongside
war_actions.py and puppet_actions.py.
"""
from data import queries
from map_logic.diplomacy.war_actions import sever_military_access, finalize_neutral, link_war, clear_war_call_cooldowns
import data.constants as c


def settle_with_faction(nation_data, joiner, fac):
    """Makes peace with everyone already in `fac` and drops passage rights.

    A faction cannot contain two nations at war with each other, so joining one
    ends any such war. Written out twice: once for a nation joining directly,
    once for its puppets being pulled in behind it.
    """
    for member in queries.get_faction_members(fac, nation_data):
        if member == joiner:
            continue
        if queries.are_at_war(joiner, member, nation_data) or queries.are_at_war(member, joiner, nation_data):
            finalize_neutral(nation_data, joiner, member)
        sever_military_access(nation_data, joiner, member)


def leave_faction(nation_data, leaver):
    """Strips a nation's faction membership and takes its puppets with it.

    The shared body of leaving voluntarily and being kicked out. What differs
    is only who resents whom afterwards, which stays with the two callers.
    """
    from map_logic.diplomacy.puppet_actions import pull_puppets_out_of_faction

    fac = nation_data[leaver].get("faction", "")
    if fac:
        queries.remove_member_from_pre_war_map(leaver, fac, nation_data)

    nation_data[leaver]["faction"] = ""
    nation_data[leaver]["is_faction_leader"] = False
    pull_puppets_out_of_faction(leaver, nation_data)
    return fac


def resent_departure(nation_data, a, b):
    """Applies the mutual "they walked out on us" relations hit."""
    queries.add_temporary_modifier(a, b, "recent_faction", c.REL_MOD_RECENT_FACTION, nation_data)
    queries.add_temporary_modifier(b, a, "recent_faction", c.REL_MOD_RECENT_FACTION, nation_data)


def finalize_create_faction(map_data, nation_data, creator):
    from map_logic.diplomacy.puppet_actions import pull_puppets_into_faction

    if getattr(c, "DISABLE_FACTIONS", False):
        return

    master = nation_data.get(creator, {}).get("master", "")
    leader = master if master else creator

    fac = f"The {nation_data[leader].get('name', leader)} Pact"
    nation_data[leader]["faction"] = fac
    nation_data[leader]["is_faction_leader"] = True

    if master:
        nation_data[creator]["faction"] = fac
        nation_data[creator]["is_faction_leader"] = False

    if queries.is_faction_at_war(fac, nation_data):
        queries.save_faction_pre_war_map(fac, map_data, nation_data)

    pull_puppets_into_faction(leader, fac, map_data, nation_data)

def finalize_disband_faction(nation_data, leader):
    from map_logic.diplomacy.puppet_actions import pull_puppets_out_of_faction

    fac = nation_data[leader].get("faction", "")
    if not fac: return

    if "FACTION_WAR_MAPS" in nation_data and fac in nation_data["FACTION_WAR_MAPS"]:
        del nation_data["FACTION_WAR_MAPS"][fac]

    for n, d in list(nation_data.items()):
        if d.get("faction") == fac:
            d["faction"] = ""
            d["is_faction_leader"] = False

    pull_puppets_out_of_faction(leader, nation_data)

def finalize_faction_join(map_data, nation_data, host, joiner):
    from map_logic.diplomacy.puppet_actions import pull_puppets_into_faction

    # A puppet has no alignment of its own; it follows its master in through
    # pull_puppets_into_faction below, which sets `faction` directly and so does
    # not come back through here. Guarded at this level rather than only at the
    # treaty layer because crossed invitations in diplomacy_processor call
    # straight in, and had no check of any kind.
    if not queries.can_choose_own_faction(joiner, nation_data):
        return

    fac = nation_data[host].get("faction", "")
    if fac:
        nation_data[joiner]["faction"] = fac
        nation_data[joiner]["is_faction_leader"] = False

        settle_with_faction(nation_data, joiner, fac)

        if queries.is_faction_at_war(fac, nation_data):
            queries.add_member_to_pre_war_map(joiner, fac, map_data, nation_data)

        pull_puppets_into_faction(joiner, fac, map_data, nation_data)

def finalize_faction_leave(nation_data, leaver):
    """A nation walks out of its faction. Everyone left behind resents it.

    A puppet cannot: it leaves when its master does, through
    pull_puppets_out_of_faction. Walking out alone would strand it outside the
    faction its overlord is still in, which is the same broken state as joining
    one alone, only mirrored.
    """
    if not queries.can_choose_own_faction(leaver, nation_data):
        return

    # Read the roster before the membership is stripped.
    members = queries.get_faction_members(nation_data[leaver].get("faction", ""), nation_data)

    fac = leave_faction(nation_data, leaver)

    for m in members:
        if m != leaver:
            resent_departure(nation_data, leaver, m)

    if fac:
        queries.clear_faction_pre_war_map_if_peace(fac, nation_data)

def join_faction_wars(map_data, nation_data, joiner, faction_member):
    """Pulls the joining nation into all active wars of the target faction member."""
    from map_logic.diplomacy.puppet_actions import pull_puppets_into_war

    fac = nation_data[faction_member].get("faction", "")
    if fac and not queries.is_faction_at_war(fac, nation_data):
        queries.save_faction_pre_war_map(fac, map_data, nation_data)

    wars = nation_data[faction_member].get("at_war_with", [])
    for enemy in wars:
        link_war(nation_data, joiner, enemy)

        # Recursive puppet pull logic for new wars joined
        pull_puppets_into_war(joiner, enemy, map_data, nation_data)

    # Clear the cooldowns between these two so they can interact in future wars
    clear_war_call_cooldowns(nation_data, joiner, faction_member)
    clear_war_call_cooldowns(nation_data, faction_member, joiner)

def finalize_faction_kick(nation_data, leader, member):
    """The leader throws a member out. Only the two of them fall out over it,
    unlike leaving voluntarily, which the whole faction takes personally."""
    fac = leave_faction(nation_data, member)

    resent_departure(nation_data, leader, member)

    if fac:
        queries.clear_faction_pre_war_map_if_peace(fac, nation_data)
