"""What actually happens when a diplomatic proposal is accepted.

This switch used to exist twice in diplomacy_processor -- once for a proposal a
player (or a queued answer) accepted, once for one an AI accepted -- with the
two roles spelled out under different variable names and, in one branch, in the
opposite order. Predictably they drifted:

- An AI accepting a trade that included a puppet clause transferred the
  resources but never created the puppet. The player-side branch did.
- The player-side branch looked up an ACCEPT_PEACE fallback message that was
  never defined, so accepting a peace treaty delivered a message with no
  content at all.
- Only the AI-side branch logged a global event when a faction was founded.
- The two read the peace-treaty type out of different places.

There is one implementation now, phrased in terms of who proposed and who
accepted rather than which pass is running, so the two can no longer disagree.

data.queries and the agreement helpers stay deferred imports: this module is
reached from diplomacy_processor, which they in turn reach back into.
"""

from collections import namedtuple

from map_logic.ai import ai_prompts
from map_logic.diplomacy import deal as deal_mod
from map_logic.diplomacy import war_calls

#: blocked  -- set when the agreement turned out not to be possible after all,
#:             so the reply has to say so whatever either side wanted to write.
#: canned   -- the stock acceptance line for this action, for callers that have
#:             no prose of their own. An AI that just wrote its own reply
#:             ignores it.
TreatyOutcome = namedtuple("TreatyOutcome", "blocked canned")

_NOTHING = TreatyOutcome(None, None)


def _fallback(key, default=""):
    return ai_prompts.AI_FALLBACK_RESPONSES.get(key, default)


def _blocked(key):
    return TreatyOutcome(_fallback(key), None)


def _canned(key):
    return TreatyOutcome(None, _fallback(key))


_AWAITING_RATIFICATION = ("Terms agreed. They now go to our partners for "
                          "ratification before they take effect.")


def _escrow_pool(proposer, escrow):
    """The {nation: {resource: amount}} shape deal_effects.execute wants.

    Only the proposer ever escrows -- the accepter had not agreed to anything
    when the offer went out, so their half of the bargain is charged live.
    """
    return {proposer: escrow} if escrow else None


def _bloc_ceasefire(proposer, accepter, nation_data):
    """A plain ceasefire, but between the blocs actually fighting.

    "CEASEFIRE" was always a two-nation action and stayed one even when both
    sides were factions, which is how a member could quietly stop fighting while
    its bloc carried on.
    """
    from map_logic.diplomacy import peace_scope

    sides = peace_scope.deal_sides(proposer, accepter, nation_data)
    return deal_mod.new(deal_mod.KIND_PEACE, sides[0], sides[1], [deal_mod.white_peace()])


def _enforce_separate_peace_cost(agreement, proposer, accepter, nation_data):
    """A member that settles behind its bloc's back leaves the bloc.

    The screens add this clause themselves, but it is the price of the whole
    manoeuvre rather than a term either side chose, so it is guaranteed here
    too -- the same reason the puppet check above is repeated at this level.
    """
    from map_logic.diplomacy import peace_scope

    role = peace_scope.negotiation_role(proposer, accepter, nation_data)
    if not peace_scope.costs_membership(role):
        return agreement
    if any(clause.get("type") == deal_mod.FACTION_EXIT and clause.get("nation") == proposer
           for clause in deal_mod.clauses(agreement)):
        return agreement
    return deal_mod.add_clause(agreement, {"type": deal_mod.FACTION_EXIT, "nation": proposer})


def apply_treaty_effect(host, action, proposer, accepter, params=None, escrow=None):
    """Applies an accepted proposal and returns a TreatyOutcome.

    `proposer` offered the deal and `accepter` agreed to it, whichever side is
    human. Phrasing it this way rather than "player pass" / "AI pass" is what
    stops the two callers drifting apart again.

    `escrow` is what was taken from the proposer when the offer was sent, so the
    payment half of a trade or a reparations clause is delivered rather than
    charged twice. See deal_effects for why that no longer lives in the UI.
    """
    from data import queries
    from map_logic.diplomacy import deal_effects, ratification
    from map_logic.diplomacy.diplomacy_agreements import (
        finalize_create_faction, finalize_faction_join, join_faction_wars)
    from map_logic.diplomacy.diplomacy_events import log_global_event

    nation_data = host.nation_data
    map_data = host.map_data

    if action == "FACTION_INVITE":
        # The accepter is being invited into the proposer's faction.
        if not queries.can_choose_own_faction(accepter, nation_data):
            return _blocked("PUPPET_CANNOT_CHOOSE_FACTION")
        if nation_data[accepter].get("faction", ""):
            return _blocked("ACCEPT_FACTION_ALREADY_IN")
        finalize_faction_join(map_data, nation_data, proposer, accepter)

    elif action == "JOIN_FACTION_REQ":
        # The proposer is asking to join the accepter's faction.
        if not queries.can_choose_own_faction(proposer, nation_data):
            return _blocked("PUPPET_CANNOT_CHOOSE_FACTION")
        if nation_data[proposer].get("faction", ""):
            return _blocked("ACCEPT_FACTION_JOIN_ALREADY_IN")
        finalize_faction_join(map_data, nation_data, accepter, proposer)

    elif action == "CREATE_FACTION":
        if nation_data[accepter].get("faction", "") or nation_data[proposer].get("faction", ""):
            return _blocked("CREATE_FACTION_CONFLICT")
        finalize_create_faction(map_data, nation_data, proposer)
        finalize_faction_join(map_data, nation_data, proposer, accepter)
        log_global_event(nation_data,
                         f"{proposer} and {accepter} have formed a new global faction!")

    elif action in ("CEASEFIRE", "PEACE_TREATY"):
        # A puppet's wars are its master's business. This is the one place all
        # thirteen paths that can settle a war converge, so the backstop lives
        # here even though the friendlier guards upstream catch it first.
        for side, other in ((proposer, accepter), (accepter, proposer)):
            if not queries.can_negotiate_peace(side, other, nation_data):
                return _blocked("PUPPET_CANNOT_MAKE_PEACE")

        # A bare CEASEFIRE carries no terms by definition; a PEACE_TREATY may
        # carry an itemized deal, an old peace sentence from a save made before
        # the rework, or -- the AI's habit until now -- nothing at all, which
        # coerce reads as the white peace it always silently executed as.
        agreement = (_bloc_ceasefire(proposer, accepter, nation_data) if action == "CEASEFIRE"
                     else deal_mod.coerce(params, proposer, accepter, kind=deal_mod.KIND_PEACE))
        agreement = _enforce_separate_peace_cost(agreement, proposer, accepter, nation_data)

        # Whoever the leader bound gets a say before it takes effect. In an
        # ordinary game every bound member is an AI and answers on the spot, so
        # this settles now and the extra turn only appears when a human is asked.
        if ratification.open_round(host, proposer, accepter, agreement,
                                   escrow=escrow):
            return _canned("ACCEPT_PEACE") if action == "PEACE_TREATY" else _NOTHING
        return TreatyOutcome(None, _AWAITING_RATIFICATION)

    elif action == "TRADE":
        agreement = deal_mod.coerce(params, proposer, accepter, kind=deal_mod.KIND_TRADE)
        deal_effects.execute(host, agreement, escrowed=_escrow_pool(proposer, escrow))
        return _canned("ACCEPT_TRADE")

    elif action == "CALL_TO_ARMS":
        # The backstop for war_calls, at the point every path converges -- the
        # same place the puppet-peace rule is enforced, and for the same reason:
        # an offer sits in the inbox for turns, and the wars it was about can
        # end while it waits. Answering a call to arms that has nothing left to
        # answer used to run join_faction_wars over an empty list and announce
        # an escalation that had not happened.
        if not war_calls.is_honest(action, proposer, accepter, nation_data):
            return _blocked("NO_WAR_TO_JOIN")
        join_faction_wars(map_data, nation_data, accepter, proposer)
        log_global_event(nation_data,
                         f"ESCALATION: {accepter} answered the call to arms of {proposer}!")

    elif action == "JOIN_WARS":
        if not war_calls.is_honest(action, proposer, accepter, nation_data):
            return _blocked("NO_WAR_TO_JOIN")
        join_faction_wars(map_data, nation_data, proposer, accepter)
        log_global_event(nation_data,
                         f"ESCALATION: {proposer} has joined the wars of {accepter}!")

    elif action == "REQ_MILITARY_ACCESS":
        # The accepter grants the proposer passage through their territory.
        # Deliberately one-way: the proposer gets no say over the reverse.
        granted = nation_data.setdefault(accepter, {}).setdefault("military_access", [])
        if proposer not in granted:
            granted.append(proposer)

        shared_enemy = bool(set(queries.get_enemies(accepter, nation_data)) &
                            set(queries.get_enemies(proposer, nation_data)))
        if shared_enemy:
            nation_data[accepter].setdefault("military_access_reasons", {})[proposer] = "war"

        return _canned("ACCEPT_MILITARY_ACCESS")

    return _NOTHING
