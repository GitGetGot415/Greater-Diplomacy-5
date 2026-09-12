"""Who a war is actually between, and who is allowed to end it.

Peace was strictly bilateral. Nothing on the peace path had ever heard of a
faction, so a single member could sign its own treaty and walk out of a war its
bloc was still fighting -- which is the state behind "the AI is in a faction but
still at war with one member of another faction, and just ignoring them".

Two questions, and the whole rework of faction peace is the answers:

  war_sides       -- given two belligerents, the two blocs a settlement binds
  negotiation_role -- what this nation is entitled to propose, if anything

The rules, in the order they are decided:

  * Puppets never negotiate for themselves. queries.can_negotiate_peace already
    said so; it stays the first gate.
  * Outside factions, peace is bilateral and anyone may propose it.
  * When a faction is at war, only its leader may negotiate for it, and what the
    leader signs binds every member -- including their territory. Members get a
    ratification round (see diplomacy_processor) and may refuse, which costs
    them their membership.
  * A faction leader and an individual member of the opposing faction may make
    a MEMBER_SEPARATE_PEACE. The leader speaks for their own bloc, but the
    named enemy member alone settles; neither side is ejected from its faction.
    This is the limited peace needed when a single ally wants to leave that
    particular front without deciding its whole faction's war.
  * A non-leader may otherwise sue for a SEPARATE peace with the entire enemy
    bloc. It is the only way out for a member whose leader will not settle, and
    it costs them their faction.
  * A leader may not make a separate peace. Abandoning the bloc you lead is not
    a thing you get to do quietly.
  * Two ordinary non-leaders still cannot make a one-on-one deal with members
    of the opposing faction. Only a leader may authorise the member-level
    settlement above.
"""

from data import queries

#: This nation speaks for its whole bloc; the deal binds every member.
BLOC_LEADER = "BLOC_LEADER"
#: A faction member buying its own way out. Signing costs it its membership.
SEPARATE_PEACE = "SEPARATE_PEACE"
#: A faction leader's bloc settling with one named member of the enemy bloc.
#: The member remains in its faction; only its war against this bloc ends.
MEMBER_SEPARATE_PEACE = "MEMBER_SEPARATE_PEACE"
#: Nobody's bloc is involved; the old two-nation deal.
BILATERAL = "BILATERAL"


def _faction_of(nation, nation_data):
    return nation_data.get(nation, {}).get("faction", "")


def _bloc(nation, nation_data):
    """Everyone a settlement with `nation` has to speak for.

    Their faction if they are in one, otherwise just them. Puppets ride along
    with their master either way -- pull_puppets_into_peace already drags them
    out of a war, so leaving them off the roster would only mean the deal could
    not name their territory.
    """
    faction = _faction_of(nation, nation_data)
    members = queries.get_faction_members(faction, nation_data) if faction else [nation]
    if nation not in members:
        members = list(members) + [nation]

    roster = list(members)
    for member in members:
        for puppet in nation_data.get(member, {}).get("puppets", []):
            if puppet not in roster:
                roster.append(puppet)
    return roster


def war_sides(nation, opponent, nation_data):
    """The two blocs a settlement between these two would bind.

    Restricted to nations actually in the fight: a faction-mate at peace with
    the other side is not dragged to the table, and cannot have its land put on
    it. The two signatories are always on it regardless -- a leader negotiating
    on its bloc's behalf may not itself be at war with anyone left standing, and
    a deal nobody signed is not a deal.
    """
    mine = _bloc(nation, nation_data)
    theirs = _bloc(opponent, nation_data)

    def belligerents(side, other_side, anchor):
        fighting = [n for n in side
                    if n == anchor
                    or any(queries.are_at_war(n, foe, nation_data) for foe in other_side)]
        return fighting or [anchor]

    return (belligerents(mine, theirs, nation), belligerents(theirs, mine, opponent))


def leader_of(nation, nation_data):
    """Who speaks for this nation's side, or the nation itself if unaligned."""
    faction = _faction_of(nation, nation_data)
    if not faction:
        return nation
    return queries.get_faction_leader(faction, nation_data) or nation


def negotiation_role(nation, opponent, nation_data):
    """What `nation` may propose to `opponent`, or None if nothing.

    Paired with `refusal_reason`, which says the same thing in words for a
    player who just clicked the button.
    """
    if not queries.can_negotiate_peace(nation, opponent, nation_data):
        return None

    my_faction = _faction_of(nation, nation_data)
    their_faction = _faction_of(opponent, nation_data)
    i_am_leader = queries.is_faction_leader(nation, nation_data)
    they_are_leader = queries.is_faction_leader(opponent, nation_data)

    # A leader may settle their bloc's war with one named member of the other
    # bloc. The mirror is equally important: that member may offer terms to
    # the leader, who can accept without treating it as a decision for every
    # member of the offerer's faction. A leaderless faction still falls through
    # to the normal whole-bloc rule below, because it has nobody authorised to
    # distinguish a member-level settlement from a bloc one.
    their_leader = queries.get_faction_leader(their_faction, nation_data) if their_faction else None
    my_leader = queries.get_faction_leader(my_faction, nation_data) if my_faction else None
    if ((i_am_leader and their_faction and not they_are_leader and their_leader)
            or (they_are_leader and my_faction and not i_am_leader and my_leader)):
        return MEMBER_SEPARATE_PEACE

    # Talking to a bloc means talking to whoever runs it -- unless it has nobody
    # running it, in which case there is nobody to be sent to and refusing would
    # make the war unendable. faction_leadership.promote fills that seat the
    # moment a leader is conquered, so this only catches the gap before the next
    # tick and saves written before the succession rule existed.
    if their_faction and not they_are_leader and their_leader:
        return None

    if not my_faction:
        return BILATERAL

    if i_am_leader:
        return BLOC_LEADER

    # A member may still walk out on its own -- but only by settling with the
    # whole other side, and only at the price of its membership.
    return SEPARATE_PEACE


def refusal_reason(nation, opponent, nation_data):
    """Why `nation` cannot open talks with `opponent`, or "" if it can.

    The wording a player sees, so every gate that refuses has a sentence rather
    than a button that quietly does nothing.
    """
    if not queries.can_negotiate_peace(nation, opponent, nation_data):
        return "Puppets can only make peace with their master!"
    if not queries.can_negotiate_peace(opponent, nation, nation_data):
        return f"{opponent} is a puppet -- negotiate with its master instead!"

    their_faction = _faction_of(opponent, nation_data)
    if their_faction and not queries.is_faction_leader(opponent, nation_data):
        leader = queries.get_faction_leader(their_faction, nation_data)
        if leader:
            if queries.is_faction_leader(nation, nation_data):
                return ""
            return f"{opponent} cannot settle alone -- negotiate with {leader}, who leads {their_faction}."
        # A leaderless bloc has nobody to redirect to, so there is no reason to
        # refuse; negotiation_role lets this through as an ordinary bilateral.
        return ""
    return ""


def binds_whole_bloc(role):
    return role in (BLOC_LEADER, MEMBER_SEPARATE_PEACE)


def costs_membership(role):
    """Whether signing this deal takes the proposer out of its own faction."""
    return role == SEPARATE_PEACE


def is_member_separate_peace(role):
    """Whether this settles one enemy faction member against a leader's bloc."""
    return role == MEMBER_SEPARATE_PEACE


def _leader_side_against(leader, opponent, nation_data):
    """The leader's faction members actually bound against one opponent."""
    return [nation for nation in _bloc(leader, nation_data)
            if nation == leader or queries.are_at_war(nation, opponent, nation_data)]


def deal_sides(nation, opponent, nation_data, role=None):
    """The two side rosters to build a deal with, given the proposer's role.

    A separate peace is one nation against the whole enemy bloc; a leader's deal
    is bloc against bloc. Getting this wrong is how a treaty ends up binding
    somebody it never mentioned.
    """
    if role is None:
        role = negotiation_role(nation, opponent, nation_data)

    mine, theirs = war_sides(nation, opponent, nation_data)
    if role == MEMBER_SEPARATE_PEACE:
        if queries.is_faction_leader(nation, nation_data):
            return _leader_side_against(nation, opponent, nation_data), [opponent]
        return [nation], _leader_side_against(opponent, nation, nation_data)
    if role == SEPARATE_PEACE:
        return [nation], theirs
    if role == BLOC_LEADER:
        return mine, theirs
    return [nation], theirs


def has_settleable_war(nation, opponent, nation_data):
    """Whether the peace scope contains at least one live enemy pair.

    A faction leader can represent a member who is still fighting even after
    the leader themselves has made peace with that particular opponent. Looking
    only at the two clicked country ids would label that situation as a new war
    declaration rather than the faction-level peace it actually is.
    """
    role = negotiation_role(nation, opponent, nation_data)
    if role is None:
        return False
    mine, theirs = deal_sides(nation, opponent, nation_data, role)
    return any(queries.are_at_war(ours, theirs_nation, nation_data)
               for ours in mine for theirs_nation in theirs)


def bound_members(deal_sides_for_proposer, proposer):
    """The proposer's faction-mates a deal would commit besides the proposer."""
    return [n for n in deal_sides_for_proposer if n != proposer]
