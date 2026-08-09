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

import data.constants as c
from map_logic.ai import ai_prompts

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


def apply_treaty_effect(host, action, proposer, accepter, params=None):
    """Applies an accepted proposal and returns a TreatyOutcome.

    `proposer` offered the deal and `accepter` agreed to it, whichever side is
    human. Phrasing it this way rather than "player pass" / "AI pass" is what
    stops the two callers drifting apart again.
    """
    from data import queries
    from map_logic.diplomacy.diplomacy_agreements import (
        assign_puppet, execute_peace_treaty, finalize_create_faction,
        finalize_faction_join, finalize_neutral, join_faction_wars)
    from map_logic.diplomacy.diplomacy_events import log_global_event

    nation_data = host.nation_data
    map_data = host.map_data

    if action == "FACTION_INVITE":
        # The accepter is being invited into the proposer's faction.
        if nation_data[accepter].get("faction", ""):
            return _blocked("ACCEPT_FACTION_ALREADY_IN")
        finalize_faction_join(map_data, nation_data, proposer, accepter)

    elif action == "JOIN_FACTION_REQ":
        # The proposer is asking to join the accepter's faction.
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

    elif action == "CEASEFIRE":
        finalize_neutral(nation_data, proposer, accepter)

    elif action == "PEACE_TREATY":
        execute_peace_treaty(map_data, nation_data, proposer, accepter,
                             params if params else c.PEACE_WHITE_PEACE, host)
        return _canned("ACCEPT_PEACE")

    elif action == "TRADE":
        trade_params = params if isinstance(params, dict) else {}
        queries.execute_trade_transfer(nation_data[proposer], nation_data[accepter], trade_params)

        puppet_state = trade_params.get("puppet_state", "NONE")
        if puppet_state == "SENDER":
            assign_puppet(map_data, nation_data, proposer, accepter)
        elif puppet_state == "RECEIVER":
            assign_puppet(map_data, nation_data, accepter, proposer)

        return _canned("ACCEPT_TRADE")

    elif action == "CALL_TO_ARMS":
        join_faction_wars(map_data, nation_data, accepter, proposer)
        log_global_event(nation_data,
                         f"ESCALATION: {accepter} answered the call to arms of {proposer}!")

    elif action == "JOIN_WARS":
        join_faction_wars(map_data, nation_data, proposer, accepter)
        log_global_event(nation_data,
                         f"ESCALATION: {proposer} has joined the wars of {accepter}!")

    elif action == "REQ_MILITARY_ACCESS":
        # The accepter grants the proposer passage through their territory.
        # Deliberately one-way: the proposer gets no say over the reverse.
        granted = nation_data.setdefault(accepter, {}).setdefault("military_access", [])
        if proposer not in granted:
            granted.append(proposer)

        shared_enemy = bool(set(nation_data.get(accepter, {}).get("at_war_with", [])) &
                            set(nation_data.get(proposer, {}).get("at_war_with", [])))
        if shared_enemy:
            nation_data[accepter].setdefault("military_access_reasons", {})[proposer] = "war"

        return _canned("ACCEPT_MILITARY_ACCESS")

    return _NOTHING
