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

The processor calls this shared implementation for both player and AI acceptance.
"""

from typing import NamedTuple

from map_logic.ai import ai_opinion, ai_prompts, ai_world
from map_logic.diplomacy import deal as deal_mod
from map_logic.diplomacy import war_actions, war_calls

from data import queries
from data.state_access import session_for
from map_logic.diplomacy import peace_scope, deal_effects, global_rules, ratification, military_attaches, volunteers
from map_logic.diplomacy.peace_scope import with_separate_peace_cost  # Public compatibility alias.
from map_logic.diplomacy import diplomacy_lifecycle as lifecycle
from map_logic.diplomacy.action_definitions import handlers_for
from map_logic.diplomacy.faction_actions import finalize_create_faction, finalize_faction_join, join_faction_wars
from map_logic.diplomacy.diplomacy_events import log_global_event


class TreatyOutcome(NamedTuple):
    status: str
    blocked: str | None = None  # Replaces the reply when the agreement fails.
    canned: str | None = None  # Default reply when the responder supplied no text.


_APPLIED = TreatyOutcome("applied")


def _fallback(key, default=""):
    return ai_prompts.AI_FALLBACK_RESPONSES.get(key, default)


def _blocked(key):
    return TreatyOutcome("blocked", blocked=_fallback(key))


def _canned(key):
    return TreatyOutcome("applied", canned=_fallback(key))


_AWAITING_RATIFICATION = ("Terms agreed. They now go to our partners for "
                          "ratification before they take effect.")


def _escrow_pool(proposer, escrow):
    """The {nation: {resource: amount}} shape deal_effects.execute wants.

    Only the proposer ever escrows -- the accepter had not agreed to anything
    when the offer went out, so their half of the bargain is charged live.
    """
    return {proposer: escrow} if escrow else None


def withdraw_peace_offer(nation_data, sender, target, request):
    """Close this offer, including its own reply and any resources held for it."""
    pending = nation_data.get(sender, {}).get("pending_diplomacy", {})
    if not lifecycle.remove_request(pending, target, request_id=request.get("request_id")):
        return
    held = request.pop("escrow", None)
    if held:
        deal_effects.release_escrow(nation_data, held, sender)
    responses = nation_data.get(target, {}).get("diplo_responses", {})
    reply = responses.get(sender)
    if isinstance(reply, dict) and lifecycle.response_matches_request(reply, request):
        lifecycle.remove_response(responses, sender)


def expire_obsolete_peace(nation_data):
    """Keep delivered messages as history but close treaties whose fronts are gone."""
    ratification.expire_obsolete_rounds(nation_data)
    for sender, country in nation_data.items():
        if not isinstance(country, dict):
            continue
        choices = country.get("peace_choices", {})
        if not isinstance(choices, dict):
            country.pop("peace_choices", None)
            choices = {}
        for target, round_ in list(choices.items()):
            offers = round_.get("offers") if isinstance(round_, dict) else None
            if (not isinstance(offers, dict) or set(offers) != {sender, target}
                    or not isinstance(round_.get("round_id"), str)
                    or not all(isinstance(offer, dict) and offer.get("action") in peace_scope.PEACE_ACTIONS
                               and deal_mod.is_deal(offer.get("deal")) for offer in offers.values())
                    or not all(peace_scope.has_current_terms(offer["deal"], proposer,
                               target if proposer == sender else sender, nation_data)
                               for proposer, offer in offers.items())):
                close_peace_choice(nation_data, sender, target)
            elif not isinstance(round_.get("selected"), str) or round_["selected"] not in offers:
                round_.pop("selected", None)
        for target, request in list(country.get("pending_diplomacy", {}).items()):
            if (not isinstance(request, dict) or request.get("action") not in peace_scope.PEACE_ACTIONS
                    or request.get("turns", 0) <= 0):
                continue
            if not peace_scope.offer_wars(sender, target, request, nation_data):
                withdraw_peace_offer(nation_data, sender, target, request)


def close_peace_choice(nation_data, country, opponent):
    data = nation_data.get(country, {})
    rounds = data.get("peace_choices", {})
    round_ = rounds.pop(opponent, {})
    if not rounds:
        data.pop("peace_choices", None)
    if isinstance(round_, dict) and isinstance(round_.get("escrow"), dict):
        deal_effects.release_escrow(nation_data, round_["escrow"], country)


def _accept_faction_invite(host, action, proposer, accepter, params, escrow):
    # The accepter is being invited into the proposer's faction.
    nation_data = host.world.nation_data
    if not queries.can_choose_own_faction(accepter, nation_data):
        return _blocked("PUPPET_CANNOT_CHOOSE_FACTION")
    if queries.get_country_faction(accepter, nation_data):
        return _blocked("ACCEPT_FACTION_ALREADY_IN")
    leadership_error = queries.faction_request_leadership_error(proposer, accepter, action, nation_data)
    if leadership_error:
        return TreatyOutcome("blocked", blocked=leadership_error)
    finalize_faction_join(host.world.map_data, nation_data, proposer, accepter)
    return _APPLIED


def _accept_join_request(host, action, proposer, accepter, params, escrow):
    # The proposer is asking to join the accepter's faction.
    nation_data = host.world.nation_data
    if not queries.can_choose_own_faction(proposer, nation_data):
        return _blocked("PUPPET_CANNOT_CHOOSE_FACTION")
    if queries.get_country_faction(proposer, nation_data):
        return _blocked("ACCEPT_FACTION_JOIN_ALREADY_IN")
    leadership_error = queries.faction_request_leadership_error(proposer, accepter, action, nation_data)
    if leadership_error:
        return TreatyOutcome("blocked", blocked=leadership_error)
    finalize_faction_join(host.world.map_data, nation_data, accepter, proposer)
    return _APPLIED


def _accept_create_faction(host, action, proposer, accepter, params, escrow):
    nation_data = host.world.nation_data
    if queries.get_country_faction(accepter, nation_data) or queries.get_country_faction(proposer, nation_data):
        return _blocked("CREATE_FACTION_CONFLICT")
    finalize_create_faction(host.world.map_data, nation_data, proposer)
    finalize_faction_join(host.world.map_data, nation_data, proposer, accepter)
    log_global_event(nation_data,
                     f"{proposer} and {accepter} have formed a new global faction!")
    return _APPLIED


def _accept_peace(host, action, proposer, accepter, params, escrow, *, chosen_deal=None):
    nation_data = host.world.nation_data
    # A puppet's wars are its master's business. This is the one place all
    # thirteen paths that can settle a war converge, so the backstop lives
    # here even though the friendlier guards upstream catch it first.
    for side, other in ((proposer, accepter), (accepter, proposer)):
        if not queries.can_negotiate_peace(side, other, nation_data):
            return _blocked("PUPPET_CANNOT_MAKE_PEACE")
    if not peace_scope.has_settleable_war(proposer, accepter, nation_data):
        return _blocked("NO_WAR_TO_SETTLE")

    # A bare CEASEFIRE carries no terms by definition; a PEACE_TREATY may
    # carry an itemized deal, an old peace sentence from a save made before
    # the rework, or -- the AI's habit until now -- nothing at all, which
    # coerce reads as the white peace it always silently executed as.
    agreement = chosen_deal if chosen_deal is not None else peace_scope.offered_peace(proposer, accepter, action, params, nation_data)
    blocked = peace_scope.settlement_block(peace_scope.live_war_pairs(agreement, nation_data), nation_data)
    if blocked:
        return _blocked(blocked)
    agreement = peace_scope.with_separate_peace_cost(agreement, proposer, accepter, nation_data)
    if not peace_scope.has_current_terms(agreement, proposer, accepter, nation_data):
        return _blocked("PEACE_TERMS_CHANGED")

    # Whoever the leader bound gets a say before it takes effect. In an
    # ordinary game every bound member is an AI and answers on the spot, so
    # this settles now and the extra turn only appears when a human is asked.
    if ratification.open_round(host, proposer, accepter, agreement,
                               escrow=escrow):
        return _canned("ACCEPT_PEACE") if action == "PEACE_TREATY" else _APPLIED
    return TreatyOutcome("awaiting_ratification", canned=_AWAITING_RATIFICATION)


def _accept_trade(host, action, proposer, accepter, params, escrow):
    # Players may trade with enemies. AI recipients always refuse, including
    # scripted acceptances or offers whose countries went to war while waiting.
    # Return the proposer's payment since the caller has already taken escrow.
    if (accepter not in session_for(host).active_players
            and queries.are_at_war(proposer, accepter, host.world.nation_data)):
        if escrow:
            deal_effects.release_escrow(host.world.nation_data, escrow, proposer)
        return _blocked("TRADE_AT_WAR")
    agreement = deal_mod.coerce(params, proposer, accepter, kind=deal_mod.KIND_TRADE)
    deal_effects.execute(host, agreement, escrowed=_escrow_pool(proposer, escrow))
    return _canned("ACCEPT_TRADE")


def _accept_war_request(host, action, proposer, accepter, params, escrow, *, scripted=False, proposer_scripted=False):
    nation_data = host.world.nation_data
    reason = war_calls.request_block_reason(action, proposer, accepter, nation_data)
    if reason:
        return TreatyOutcome("blocked", blocked=reason)
    fighter, joiner = war_calls.parties(action, proposer, accepter)
    joining_scripted = scripted if action == war_calls.CALL_TO_ARMS else proposer_scripted
    enemies = war_calls.unshared_wars(fighter, joiner, nation_data)
    if (global_rules.is_ai_controlled(host, joiner) and not joining_scripted
            and any(war_calls.recently_settled(joiner, enemy, nation_data) for enemy in enemies)):
        enemies = ai_opinion.wars_to_join(ai_world.for_screen(host), fighter, joiner)
        if not enemies:
            return _blocked("WAR_REQUEST_RECENT_PEACE")
    joined = join_faction_wars(host.world.map_data, nation_data, joiner, fighter, enemies=enemies)
    if joined:
        log_global_event(nation_data, f"ESCALATION: {joiner} joined the wars of {fighter}.")
    return _APPLIED


def _accept_military_access(host, action, proposer, accepter, params, escrow, *, scripted=False):
    nation_data = host.world.nation_data
    # The accepter grants the proposer passage through their territory.
    # Deliberately one-way: the proposer gets no say over the reverse.
    if proposer == accepter or queries.are_at_war(proposer, accepter, nation_data):
        return _blocked("INVALID_MILITARY_ACCESS")
    automatic = global_rules.is_ai_controlled(host, accepter) and not scripted
    if automatic:
        _, reason = war_actions.shared_war_access(proposer, accepter, nation_data)
        if reason:
            return _blocked(reason)

    granted = nation_data[accepter].setdefault("military_access", [])
    if proposer not in granted:
        granted.append(proposer)
        host.world.diplomacy_revision += 1
    reasons = nation_data[accepter].setdefault("military_access_reasons", {})
    if automatic:
        reasons[proposer] = "war"
    else:
        reasons.pop(proposer, None)

    return _canned("ACCEPT_MILITARY_ACCESS")


def _accept_military_attache(host, action, proposer, accepter, params, escrow):
    nation_data = host.world.nation_data
    sent, reason = military_attaches.send(proposer, accepter, nation_data)
    if not sent:
        return TreatyOutcome("blocked", blocked=reason)
    log_global_event(nation_data,
                     f"{proposer} has sent a military attaché to {accepter}.")
    return TreatyOutcome("applied", canned="Military attaché accepted.")


def _accept_volunteers(host, action, proposer, accepter, params, escrow):
    accepted, reason = volunteers.accept_offer(host, proposer, accepter)
    if not accepted:
        return TreatyOutcome("blocked", blocked=reason)
    return _canned("ACCEPT_GENERIC")


_ACCEPTANCE_EFFECTS = handlers_for("acceptance_effect", globals())
_ACCEPTANCES_WITH_OWN_EVENTS = {"CEASEFIRE", "PEACE_TREATY", "CREATE_FACTION", "CALL_TO_ARMS", "JOIN_WARS", "SEND_MILITARY_ATTACHE"}


def apply_treaty_effect(host, action, proposer, accepter, params=None, escrow=None, *, scripted=False, proposer_scripted=False, chosen_deal=None):
    """Applies an accepted proposal and returns a TreatyOutcome.

    `proposer` offered the deal and `accepter` agreed to it, whichever side is
    human. Phrasing it this way rather than "player pass" / "AI pass" is what
    stops the two callers drifting apart again.

    `escrow` is what was taken from the proposer when the offer was sent, so the
    payment half of a trade or a reparations clause is delivered rather than
    charged twice. See deal_effects for why that no longer lives in the UI.

    `scripted` says a scripted event chose the acceptance, which global rules may exempt.
    """
    effect = _ACCEPTANCE_EFFECTS.get(action)
    if effect is None:
        return TreatyOutcome("ignored")
    # The send phase already refused forbidden offers, but factions and wars can
    # change while an offer waits for its answer.
    choice = global_rules.Choice(global_rules.is_ai_controlled(host, accepter), accepting=True, scripted=scripted)
    forbidden = global_rules.forbidden_reason(host, proposer, accepter, action, choices=(choice,))
    if forbidden:
        if escrow:
            deal_effects.release_escrow(host.world.nation_data, escrow, proposer)
        return TreatyOutcome("blocked", blocked=_fallback("GLOBAL_RULE_FORBIDS").format(reason=forbidden))
    if chosen_deal is not None:
        outcome = effect(host, action, proposer, accepter, params, escrow, chosen_deal=chosen_deal)
    elif action in war_calls.WAR_REQUESTS:
        outcome = effect(host, action, proposer, accepter, params, escrow,
                         scripted=scripted, proposer_scripted=proposer_scripted)
    elif action == "REQ_MILITARY_ACCESS":
        outcome = effect(host, action, proposer, accepter, params, escrow, scripted=scripted)
    else:
        outcome = effect(host, action, proposer, accepter, params, escrow)
    if escrow and action in peace_scope.PEACE_ACTIONS and outcome.status == "blocked":
        deal_effects.release_escrow(host.world.nation_data, escrow, proposer)
    if outcome.status == "applied" and action not in _ACCEPTANCES_WITH_OWN_EVENTS:
        log_global_event(host.world.nation_data, f"Diplomatic agreement reached between {accepter} and {proposer}.")
    return outcome
