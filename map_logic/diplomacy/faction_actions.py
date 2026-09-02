"""Faction mutations: creating, joining, leaving, kicking, and pulling a
member's wars along with them.

See map_logic/diplomacy/diplomacy_agreements.py for how this fits alongside
war_actions.py and puppet_actions.py.
"""
from data import queries
from map_logic.diplomacy.war_actions import sever_military_access, finalize_neutral, link_war, clear_war_call_cooldowns
import data.constants as c


def rename_faction(nation_data, leader, old_name, new_name):
    """Rename a faction without changing its membership or war bookkeeping.

    A faction has no object of its own: each member stores the same faction
    string, and its pre-war border snapshot is keyed by that string.  Keeping
    this mutation here gives the regular UI and tournament move importer one
    authoritative implementation instead of letting either leave a member or
    a ``FACTION_WAR_MAPS`` entry behind under the old name.

    Only the current leader may rename the faction.  Existing faction names
    are rejected rather than silently merging two unrelated alliances.
    """
    if not isinstance(old_name, str) or not isinstance(new_name, str):
        return False

    new_name = new_name.strip()
    leader_data = nation_data.get(leader, {})
    if (not old_name or not new_name or len(new_name) > 40 or old_name == new_name
            or leader_data.get("faction") != old_name
            or not leader_data.get("is_faction_leader", False)):
        return False

    # A rename must not be allowed to turn into an unannounced merger.  This
    # also protects the separate pre-war snapshots belonging to both blocs.
    if queries.get_faction_members(new_name, nation_data):
        return False

    members = queries.get_faction_members(old_name, nation_data)
    if not members:
        return False

    for member in members:
        nation_data[member]["faction"] = new_name

    faction_war_maps = nation_data.get("FACTION_WAR_MAPS")
    if isinstance(faction_war_maps, dict) and old_name in faction_war_maps:
        faction_war_maps[new_name] = faction_war_maps.pop(old_name)

    return True


def settle_with_faction(nation_data, joiner, fac):
    """Makes peace with everyone already in `fac` and drops passage rights.

    A faction cannot contain two nations at war with each other, so joining one
    ends any such war. Written out twice: once for a nation joining directly,
    once for its puppets being pulled in behind it.

    The truce finalize_neutral writes is then taken back off, which it is not
    anywhere else. A truce is a promise not to fight for twelve turns, and
    between two nations who are now in the same faction that promise is both
    redundant -- they cannot declare war on each other at all -- and misleading:
    it left allies listed as holding non-aggression pacts against each other,
    and outlived the alliance if either of them later walked out.
    """
    for member in queries.get_faction_members(fac, nation_data):
        if member == joiner:
            continue
        if queries.are_at_war(joiner, member, nation_data) or queries.are_at_war(member, joiner, nation_data):
            finalize_neutral(nation_data, joiner, member)
            for side, other in ((joiner, member), (member, joiner)):
                nation_data.get(side, {}).get("truces", {}).pop(other, None)
        sever_military_access(nation_data, joiner, member)


def leave_faction(nation_data, leaver):
    """Strips a nation's faction membership and takes its puppets with it.

    The shared body of leaving voluntarily and being kicked out. What differs
    is only who resents whom afterwards, which stays with the two callers.
    """
    from map_logic.diplomacy.puppet_actions import pull_puppets_out_of_faction

    fac = nation_data[leaver].get("faction", "")
    if fac:
        _keep_own_pre_war_borders(nation_data, leaver, fac)
        queries.remove_member_from_pre_war_map(leaver, fac, nation_data)

    nation_data[leaver]["faction"] = ""
    nation_data[leaver]["is_faction_leader"] = False
    # Whatever claim it had built up on the leadership goes with it. Walking out
    # is not a way to bank six turns of pressure against a bloc you might rejoin.
    nation_data[leaver].pop("faction_pressure", None)
    # Membership starts again from nothing on the way back in, so a nation
    # cannot bank tenure in one bloc and spend it defecting out of the next.
    nation_data[leaver].pop("faction_tenure", None)
    pull_puppets_out_of_faction(leaver, nation_data)
    return fac


def _keep_own_pre_war_borders(nation_data, leaver, fac):
    """Carries a departing member's pre-war borders out of the faction with it.

    A faction's snapshot is the only record of where its members' borders were
    when the war started, and walking out used to delete this nation's share of
    it outright. That was harmless while the snapshot only fed a map mode. It is
    not now: peace hands unnamed occupied land back to its pre-war owner, and
    with no record left the fallback is the first core on the tile -- so a nation
    that bought its way out of a bloc war with a separate peace, which is exactly
    the manoeuvre that ends with somebody leaving a faction, would have its
    borders reconstructed from guesswork at the moment it mattered most.
    """
    snapshot = (nation_data.get("FACTION_WAR_MAPS") or {}).get(fac)
    if not isinstance(snapshot, dict) or not queries.get_enemies(leaver, nation_data):
        return

    mine = {prov_id: owner for prov_id, owner in snapshot.items() if owner == leaver}
    if mine:
        nation_data.setdefault("WAR_PRE_MAPS", {})[leaver] = mine


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
            d.pop("faction_pressure", None)
            d.pop("faction_tenure", None)

    pull_puppets_out_of_faction(leader, nation_data)

def finalize_faction_join(map_data, nation_data, host, joiner):
    """Returns True if the join happened, False if it was skipped."""
    from map_logic.diplomacy.puppet_actions import pull_puppets_into_faction

    # A puppet has no alignment of its own; it follows its master in through
    # pull_puppets_into_faction below, which sets `faction` directly and so does
    # not come back through here. Guarded at this level rather than only at the
    # treaty layer because crossed invitations in diplomacy_processor call
    # straight in, and had no check of any kind.
    if not queries.can_choose_own_faction(joiner, nation_data):
        return False

    # Already in a faction (possibly a different one than `host`'s): joining
    # here would silently overwrite that membership without ever leaving the
    # old faction, so skip rather than corrupt the old faction's bookkeeping.
    if nation_data[joiner].get("faction", ""):
        return False

    fac = nation_data[host].get("faction", "")
    if not fac:
        return False

    nation_data[joiner]["faction"] = fac
    nation_data[joiner]["is_faction_leader"] = False

    settle_with_faction(nation_data, joiner, fac)

    if queries.is_faction_at_war(fac, nation_data):
        queries.add_member_to_pre_war_map(joiner, fac, map_data, nation_data)

    pull_puppets_into_faction(joiner, fac, map_data, nation_data)

    return True

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

def why_an_ai_may_not_leave(nation, nation_data):
    """Why this nation's AI must not walk out of its faction, or None if it may.

    The one branch of _process_ai_retaliation's action chain that checked
    nothing at all. Its neighbours test war state, faction and negotiating
    rights; LEAVE_FACTION was a single unguarded append, and an LLM answering
    any message with it defected on the spot -- taking its puppets, which follow
    it automatically, and leaving its former allies fighting the war it had been
    fighting beside them. Both halves of the Allies split in saves/"what
    happened to the allies" are that line.

    Deliberately a rule about the AI and not about the game: a player may leave
    a faction whenever they like, and finalize_faction_leave is unchanged.

    The shared-war test is the one that matters. Everything else here is
    bookkeeping; walking out of a bloc in the middle of a war you are fighting
    *together* is the move that made the save unreadable.
    """
    data = nation_data.get(nation, {})
    fac = data.get("faction", "")
    if not fac:
        return "it is in no faction"

    if not queries.can_choose_own_faction(nation, nation_data):
        return "a puppet follows its master in and out"

    if data.get("is_faction_leader"):
        # There is a button for this and it is not this one: a leader that wants
        # out disbands the faction or kicks the members it is done with, both of
        # which leave a defined state behind. Walking out leaves the bloc
        # headless until faction_leadership.promote notices.
        return "a faction leader cannot walk out of its own faction"

    tenure = int(data.get("faction_tenure", 0) or 0)
    if tenure < c.AI_FACTION_MIN_TENURE:
        return f"it has only been a member {tenure} turns"

    my_enemies = set(queries.get_enemies(nation, nation_data))
    if my_enemies:
        for member in queries.get_faction_members(fac, nation_data):
            if member == nation:
                continue
            if my_enemies & set(queries.get_enemies(member, nation_data)):
                return f"it is fighting {member}'s war alongside it"

    return None


def join_faction_wars(map_data, nation_data, joiner, faction_member):
    """Pulls the joining nation into all active wars of the target faction member.

    Except the ones it has already settled. A truce is a signed peace with a
    number of turns left on it, and a call to arms is not a reason to tear one
    up -- it used to be, silently: Japan made peace with the Guangxi Clique, and
    the following turn five Chinese Unified Front members called Guangxi to arms
    and put the war straight back on both lists with twelve turns still on the
    truce. The player saw a peace they had signed simply not take.

    The pact is still honoured for every other war of the caller. Only the
    settled one is left alone, and only for as long as the truce lasts.
    """
    from map_logic.diplomacy.puppet_actions import pull_puppets_into_war

    fac = nation_data[faction_member].get("faction", "")
    if fac and not queries.is_faction_at_war(fac, nation_data):
        queries.save_faction_pre_war_map(fac, map_data, nation_data)

    wars = nation_data[faction_member].get("at_war_with", [])
    for enemy in wars:
        # Read both ways round. A truce is bilateral, but a save written before
        # pull_puppets_into_peace recorded it on both sides can hold it on one,
        # and a peace that only one party remembers is still a peace.
        if (queries.has_active_truce(joiner, enemy, nation_data)
                or queries.has_active_truce(enemy, joiner, nation_data)):
            continue
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
