import random
import time
from collections import namedtuple
from map_logic.ai import (ai_candidates, ai_commitments, ai_director, ai_evaluation,
                          ai_handler, ai_llm_runner, ai_negotiation, ai_opinion,
                          ai_personality, ai_prompts, ai_world)
from map_logic.diplomacy import diplomacy_messages, diplomacy_events
from data import queries
import data.constants as c

def _longest_waiting_first(map_screen, jobs):
    """Puts whoever has gone longest without the model at the front of the queue.

    The batch runs in list order, and that order was nation_data's -- the
    scenario file's -- so it never varied. Whenever the turn budget could not
    cover every nation (one thread and a local model is enough to do that with
    a single call), the same nation won every turn and the rest were never
    consulted once: the loading bar promised twelve, but the German Reich, the
    first major power in the file, took the whole budget on turn after turn.

    The stamp lives in nation_data, so it is saved and restored with everything
    else, and a nation that has never been consulted sorts first.
    """
    turn = queries.get_total_turns(map_screen.time_manager)

    def waited(choice):
        stamp = map_screen.nation_data.get(choice["nation"], {}).get("llm_last_turn")
        return (0 if stamp is None else 1, stamp or 0, choice["nation"])

    ordered = sorted(jobs, key=waited)
    for choice in ordered:
        choice["_turn"] = turn
    return ordered


def process_proactive_llm_tasks(map_screen):
    """Lets each nation's leader choose from the options its staff prepared.

    One request per nation, carrying that nation's whole menu, and the same
    reply supplies the wording -- so this replaces both the old per-action text
    batch and the decisions that were made in Python before it ran. Fewer
    requests per turn than before, deciding considerably more.

    Everything on a menu was built by the ordinary rules, so a reply can only
    ever pick something the heuristic layer had already judged legal. A nation
    with nothing to choose between is not asked at all, which on a large map is
    most of them.
    """
    pending_choices = getattr(map_screen, "proactive_choices", None) or []
    map_screen.proactive_llm_tasks = []

    if not pending_choices:
        map_screen.proactive_llm_tasks_total = 0
        map_screen.proactive_llm_tasks_completed = 0
        return

    world = ai_world.for_screen(map_screen)
    mode = ai_handler.get_ai_mode()

    def consulted(choice):
        # The immersion question comes first now: it is what decides whether
        # this nation's words are meant to be written at all, and a forced
        # choice still wants them written.
        if mode == "OFF":
            return False
        wants_prose = not ai_evaluation._use_canned_reply(
            mode, ai_handler.get_ai_immersion_level(), is_ai_to_ai=True,
            has_custom_msg=False, nation=choice["nation"], world=world)
        return wants_prose and ai_director.should_consult(choice["candidates"], wants_prose)

    jobs = [choice for choice in pending_choices if consulted(choice)]
    jobs = _longest_waiting_first(map_screen, jobs)

    map_screen.proactive_llm_tasks_total = len(jobs)
    map_screen.proactive_llm_tasks_completed = 0
    map_screen.loading_status_text = f"Directing AI Nations (0/{len(jobs)})..."

    my_turn_id = ai_handler.CURRENT_TURN_ID
    active_nations = set(queries.get_living_nations(map_screen.map_data))

    def call(choice):
        nation = choice["nation"]
        note = (f"Your temperament: "
                f"{ai_personality.describe(map_screen.nation_data, nation, map_screen.scenario_settings)}.\n")
        system, user = ai_director.build_prompt(
            world, nation, choice["candidates"], c.AI_MAX_ACTIONS_PER_TURN, note)
        context = ai_evaluation.get_world_context(
            map_screen.nation_data, active_nations, nation)
        return ai_handler._run_provider(mode, system, f"{context}\n{user}",
                                        my_turn_id, None, raw=True)

    def record(choice, reply):
        # Stamped whether or not the reply was usable: the nation cost a call
        # and had its turn at the model, so it goes to the back of the queue
        # either way. Stamping only on success would let a nation whose
        # provider keeps erroring monopolise the front of the line.
        map_screen.nation_data.setdefault(choice["nation"], {})["llm_last_turn"] = choice["_turn"]
        if not reply or reply.get("error"):
            return
        chosen, messages = ai_director.parse(reply, choice["candidates"],
                                             c.AI_MAX_ACTIONS_PER_TURN,
                                             choice["nation"], map_screen.nation_data)
        choice["chosen"] = chosen
        choice["messages"] = messages

    def record_fallback(choice):
        pass    # already holds the heuristic's own pick

    count = ai_llm_runner.make_progress_counter(
        map_screen, "Directing AI Nations",
        "proactive_llm_tasks_completed", "proactive_llm_tasks_total")

    if jobs:
        outcome = ai_llm_runner.run_llm_batch(
            jobs, call, record, record_fallback,
            on_progress=count,
            should_abort=lambda: map_screen.force_skip_llm,
            max_workers=queries.get_ai_threads(),
            deadline=ai_llm_runner.turn_deadline(map_screen, c.AI_BUDGET_SHARE_DIRECTOR))
        ai_llm_runner.report_unserved(map_screen, outcome, "Directing AI nations")

    for choice in pending_choices:
        _execute_candidates(map_screen, choice["nation"], choice["pending"],
                            choice["chosen"], choice.get("messages"))

    map_screen.proactive_choices = []

def _complete_exchanges(history):
    """The part of a cut-short summit that reads as a meeting.

    One side speaking and the other never answering is not a summit, it is a
    nation talking to itself, and publishing it would put a half-line in two
    inboxes and start the pair's cooldown for nothing. An odd trailing line is
    dropped; an even transcript is kept whole.
    """
    return history[:len(history) - len(history) % 2]


def process_summits(map_screen):
    """Convenes the AI-to-AI summits worth holding this turn.

    Each pair is one job in the batch and its exchanges run sequentially inside
    it, so the wall clock is rounds x latency rather than pairs x rounds x
    latency. Costs nothing at all unless both sides of a pair are model-driven,
    which in practice means MAJOR or ABSOLUTE.
    """
    if not ai_negotiation.enabled() or ai_handler.get_ai_mode() == "OFF":
        return

    world = ai_world.for_screen(map_screen)
    total_turns = queries.get_total_turns(map_screen.time_manager)
    active_nations = set(queries.get_living_nations(map_screen.map_data))

    def model_driven(nation):
        return ai_evaluation.llm_enabled_for(nation, world) is True

    ai_nations = [n for n in queries.get_active_ai_nations(map_screen) if n in active_nations]
    pairs = ai_negotiation.select_pairs(world, ai_nations, model_driven, total_turns)
    if not pairs:
        return

    # Published before the first request goes out, because the loading screen
    # keys the Force Skip button off these counters and this phase used to set
    # none of them -- leaving the first model work of the turn with nothing on
    # screen to stop it.
    map_screen.summits_total = len(pairs)
    map_screen.summits_completed = 0
    map_screen.loading_status_text = f"Holding Summits (0/{len(pairs)})..."
    my_turn_id = ai_handler.CURRENT_TURN_ID
    mode = ai_handler.get_ai_mode()
    settings = map_screen.scenario_settings

    def say(speaker, listener, system, history):
        context = ai_evaluation.get_world_context(
            map_screen.nation_data, active_nations, speaker, listener)
        transcript = "\n".join(history) if history else "(nothing said yet)"
        reply = ai_handler._run_provider(
            mode, system, f"{context}\nSo far:\n{transcript}\n\nSpeak.",
            my_turn_id, None, raw=True)
        if not reply or reply.get("error"):
            return None, None
        line = str(reply.get("message", "")).strip()[:c.AI_TRANSCRIPT_LINE_LENGTH]
        return (line or None), reply

    deadline = ai_llm_runner.turn_deadline(map_screen, c.AI_BUDGET_SHARE_SUMMITS)

    def out_of_time():
        return deadline is not None and time.monotonic() >= deadline

    def call(pair):
        """One whole meeting, checking the clock between its own lines.

        A summit is five sequential requests, and the batch runner can only
        give up between jobs -- so a summit that could not finish inside the
        budget used to spend all of it and then be thrown away entire, unserved
        and unrecorded. Measured on the 1941 map that was the first 45 seconds
        of every turn, buying nothing at all, before the nations that the player
        actually reads had been asked anything.

        Now it stops where it stands and keeps what was said. Two leaders who
        got one exchange in did meet; they simply did not get as far as terms,
        which is what `terms: []` says.

        Each line lands on `pair["said"]` as it is spoken rather than only in
        the return value, because the return value is exactly what a summit cut
        off mid-request does not get to produce: the clock can only be checked
        between requests, so the one that overruns takes the whole meeting with
        it unless the earlier lines are already somewhere the caller can read.
        """
        a, b = pair["a"], pair["b"]
        history = pair["said"]
        for round_index in range(c.AI_NEGOTIATION_ROUNDS):
            for speaker, listener in ((a, b), (b, a)):
                if out_of_time():
                    return {"transcript": _complete_exchanges(history),
                            "terms": [], "closing": None}
                prompt = (ai_negotiation.opening_prompt if not history
                          else ai_negotiation.reply_prompt)(world, speaker, listener, settings)
                line, _reply = say(speaker, listener, prompt, history)
                if line is None:
                    return {"transcript": _complete_exchanges(history),
                            "terms": [], "closing": None}
                history.append(f"{speaker}: {line}")

        if out_of_time():
            return {"transcript": list(history), "terms": [], "closing": None}

        closing, reply = say(a, b, ai_negotiation.closing_prompt(world, a, b, settings), history)
        terms = []
        if reply and reply.get("agreed"):
            terms = ai_negotiation.validate_terms(world, a, b, reply.get("terms"))
        if closing:
            history.append(f"{a}: {closing}")
        return {"transcript": list(history), "terms": terms, "closing": closing}

    def record(pair, outcome):
        pair["transcript"] = outcome.get("transcript") or []
        pair["terms"] = outcome.get("terms") or []

    def record_fallback(pair):
        # Talks that never started produce nothing, which is correct. Talks cut
        # off in the middle of a request produce what they managed before it --
        # a meeting that reached no terms, rather than nine seconds of the
        # turn's budget spent and nothing to show for it. Terms are left as
        # select_pairs made them: only the closing reply ever sets them, and a
        # summit that was abandoned never got that far.
        pair["transcript"] = _complete_exchanges(pair["said"])

    count = ai_llm_runner.make_progress_counter(
        map_screen, "Holding Summits", "summits_completed", len(pairs))

    outcome = ai_llm_runner.run_llm_batch(
        pairs, call, record, record_fallback,
        on_progress=count,
        should_abort=lambda: map_screen.force_skip_llm,
        max_workers=queries.get_ai_threads(),
        deadline=deadline, min_calls=2)
    ai_llm_runner.report_unserved(map_screen, outcome, "Holding summits")

    for pair in pairs:
        if not pair["transcript"]:
            continue
        ai_negotiation.record_summit(map_screen.nation_data, pair["a"], pair["b"], total_turns)
        agreed = ai_negotiation.apply_terms(
            map_screen, pair["a"], pair["b"], pair["terms"], total_turns)
        _publish_summit(map_screen, pair, agreed)


def _publish_summit(map_screen, pair, agreed):
    """Puts the summit where a player can find it.

    The transcript goes into both participants' inboxes, which already keep a
    sent copy, so a spectator sees the whole meeting. The headline goes into the
    global log, which feeds get_world_context -- so nations that were not in the
    room hear about it and react. And anyone bordering either party gets told
    directly, because a summit a player never learns about may as well not have
    happened.
    """
    a, b = pair["a"], pair["b"]
    for line in pair["transcript"]:
        speaker, _, said = line.partition(": ")
        listener = b if speaker == a else a
        # A summit only happens because a model held it, so every line of the
        # transcript is the leader's own words by construction.
        diplomacy_messages.send_message(map_screen, speaker, listener, said, "TEXT", llm=True)

    if agreed:
        summary = ai_negotiation.describe_terms(agreed)
        diplomacy_events.log_global_event(
            map_screen.nation_data, f"SUMMIT: {a} and {b} agreed {summary}.")
        headline = f"Our attaches report that {a} and {b} met in private and agreed {summary}."
    else:
        diplomacy_events.log_global_event(
            map_screen.nation_data, f"SUMMIT: {a} and {b} met, and agreed nothing.")
        headline = f"Our attaches report that {a} and {b} met in private, but parted without agreement."

    world = ai_world.for_screen(map_screen)
    for human in getattr(map_screen, "active_players", ()):
        if human in (a, b):
            continue
        neighbours = world.neighbors.get(human, ())
        shares_bloc = any(queries.are_in_same_faction(human, side, map_screen.nation_data)
                          for side in (a, b))
        if a in neighbours or b in neighbours or shares_bloc:
            diplomacy_messages.send_message(map_screen, "Foreign Ministry", human, headline, "TEXT")


def process_basic_proactive_ai(map_screen):
    """Hardcoded basic logic for AI to declare war for cores and join faction wars."""
    # This pass queues diplomacy and revokes lapsed military access, but never
    # moves a nation between factions, alliances or imperial families -- so the
    # membership half of the diplomatic picture can be resolved once up front.
    # Access itself stays live, since section 0.5 below revokes it as it goes.
    with queries.diplomacy_snapshot(freeze_access=False):
        _run_basic_proactive_ai(map_screen)


#: One row per proposal the AI opens on its own initiative.
#: fallback_key  -- entry in ai_prompts.AI_FALLBACK_RESPONSES
#: fallback      -- the same line again, so a mod that trims that table gets a
#:                  sensible message instead of a KeyError. Two of the seven
#:                  sections used to index the table directly and would crash.
#: queued_message-- overrides what is stored on the queued action itself; only
#:                  a war declaration uses it, to name the wargoal. The words
#:                  the leader says then ride on the entry's `prose` instead,
#:                  since `message` is taken -- see _queue_proactive_proposal
#: cooldown      -- whether queueing also starts a cooldown against the target
ProactiveProposal = namedtuple("ProactiveProposal",
                               "fallback_key fallback queued_message cooldown")

PROACTIVE_PROPOSALS = {
    "CEASEFIRE": ProactiveProposal(
        "PROACTIVE_CEASEFIRE", "We offer terms for a ceasefire.", None, False),
    "JOIN_FACTION_REQ": ProactiveProposal(
        "PROACTIVE_JOIN_FACTION",
        "Our enemies are aligned, let us join your faction to stand against them.",
        None, False),
    "CREATE_FACTION": ProactiveProposal(
        "PROACTIVE_CREATE_FACTION", "We propose establishing a new faction together.",
        None, False),
    "CALL_TO_ARMS": ProactiveProposal(
        "PROACTIVE_CALL_TO_ARMS", "We request your aid in our ongoing conflicts!",
        None, False),
    "REQ_MILITARY_ACCESS": ProactiveProposal(
        "PROACTIVE_REQ_MILITARY_ACCESS",
        "As we both fight against a common foe, we request military access through your territory.",
        None, False),
    "JOIN_WARS": ProactiveProposal(
        "PROACTIVE_JOIN_WAR", "May we join you in your war?", None, False),
    "WAR_DECLARATION": ProactiveProposal(
        "PROACTIVE_DECLARE_WAR", "Your occupation of our rightful territory ends now!",
        c.WARGOAL_TAKE_CLAIMS, True),
    # The three below are actions the AI could receive and answer but never
    # once send. It has never offered peace, never invited anyone into its own
    # faction, and never proposed a trade.
    "PEACE_TREATY": ProactiveProposal(
        "PROACTIVE_PEACE_TREATY", "This war has cost us both too much. We propose terms.",
        None, False),
    "FACTION_INVITE": ProactiveProposal(
        "PROACTIVE_FACTION_INVITE", "Our cause would be stronger with you in it. Join us.",
        None, False),
    # Cooldown on the way out, unlike the other proposals. An accepted trade
    # never records one -- cooldowns are stamped when a proposal is refused --
    # so a pair that gets on well would otherwise trade every single turn
    # forever, which in a 20-turn run came to 84 offers.
    "TRADE": ProactiveProposal(
        "PROACTIVE_TRADE", "We propose an exchange to the benefit of us both.",
        None, True),
}


def _queue_proactive_proposal(map_screen, pending, ai_name, target, action,
                              context_target=None, parameters=None, message=None):
    """Queues one AI-initiated proposal and books the job that writes its text.

    Every section of the proactive pass builds the same three things -- the
    prompt context, the entry in pending_diplomacy, and the proactive_llm_tasks
    job -- and every difference between them that actually matters is a column
    of PROACTIVE_PROPOSALS.
    """
    spec = PROACTIVE_PROPOSALS[action]
    # Who it is being said to decides how it is said: a nation that knows it is
    # outmatched declares war differently from one that knows it is not.
    fallback = ai_prompts.resolve(spec.fallback_key, sender=ai_name, target=target,
                                  nation_data=map_screen.nation_data,
                                  map_data=map_screen.map_data,
                                  default=spec.fallback)

    # What the leader actually says. For every action but one this is also what
    # gets queued, so it was written straight into `message` and nowhere else.
    #
    # A war declaration is the exception: its queued `message` is the wargoal
    # the rules act on, so it takes that slot and the words had nowhere to go.
    # Both the model's line and the situational fallback computed just above
    # were therefore dropped on the floor for the one action a player is most
    # likely to be reading -- every declaration in the game arrived as the same
    # hardcoded sentence, and the nine PROACTIVE_DECLARE_WAR lines in
    # ai_responses.json had never been used once.
    words = message.strip() if message and message.strip() else fallback
    entry = {
        "action": action,
        "turns": 0,
        "message": spec.queued_message or words,
        "prose": words,
        # The model's line and the canned one used to land in `message`
        # indistinguishably, which is the whole reason nothing downstream could
        # tell a leader's own words from the table's.
        "llm": bool(message and message.strip()),
    }
    if parameters:
        entry["parameters"] = parameters
    pending[target] = entry

    if spec.cooldown:
        queries.set_ai_diplo_cooldown(ai_name, target, action, map_screen.nation_data)


def _execute_candidates(map_screen, ai_name, pending, candidates, messages=None):
    """Turns the chosen candidates into queued proposals.

    `messages` is the leader's own wording per candidate index, when one was
    generated; without it each proposal carries its canned line, which is what
    happens with the model off or after a Force Skip.
    """
    messages = messages or {}
    for candidate in candidates:
        _queue_proactive_proposal(
            map_screen, pending, ai_name, candidate.target, candidate.action,
            context_target=candidate.payload.get("context_target"),
            parameters=candidate.payload.get("parameters"),
            message=messages.get(candidate.cid))


def _decrement_diplo_cooldowns(data):
    """Section 0: ages down (and cleans up) this nation's per-target action cooldowns."""
    if "diplo_cooldowns" in data:
        for target, actions in list(data["diplo_cooldowns"].items()):
            for act, cd in list(actions.items()):
                if cd > 0:
                    actions[act] -= 1
                elif cd == 0:
                    # Clean up finished cooldowns
                    del actions[act]
            if not actions:
                del data["diplo_cooldowns"][target]


def _auto_revoke_war_based_access(map_screen, ai_name, data, my_enemies):
    """Section 0.5: access granted purely because we shared an enemy lapses
    once that shared enemy is no longer common to both of us (peace, ceasefire, etc)."""
    access_reasons = data.get("military_access_reasons", {})
    if not access_reasons:
        return

    my_access = data.get("military_access", [])
    for grantee in list(access_reasons.keys()):
        if access_reasons[grantee] != "war":
            continue
        grantee_enemies = set(queries.get_enemies(grantee, map_screen.nation_data))
        if set(my_enemies) & grantee_enemies:
            continue  # still fighting a common enemy, access stands

        if grantee in my_access:
            my_access.remove(grantee)
        del access_reasons[grantee]

        diplomacy_events.log_global_event(map_screen.nation_data, f"{ai_name} revoked {grantee}'s military access as their shared war has ended.")
        diplomacy_messages.send_message(map_screen, ai_name, grantee, "Our common war has ended; your military access through our territory has been revoked.", "DIPLOMACY")


def _may_settle(nation_data, ai_name, enemy):
    """Both sides must be free to settle their own wars.

    A puppet's wars are its master's business, in both directions -- there is no
    point offering terms to a subject that cannot agree to them either. The same
    now goes for a faction: only its leader can be negotiated with, and only its
    leader can negotiate, so an AI no longer opens talks with a member who has
    no authority to answer. That used to be the only rule here, which is how the
    proactive pass could aim a ceasefire at one nation of a bloc.
    """
    from map_logic.diplomacy import peace_scope

    return (peace_scope.negotiation_role(ai_name, enemy, nation_data) is not None
            and queries.can_negotiate_peace(enemy, ai_name, nation_data))


def _white_peace_terms(map_screen, ai_name, enemy):
    """The status-quo deal, between whichever blocs are actually fighting.

    Every AI peace offer has to carry real terms now. They never did: the
    proactive sections queued a proposal with no `parameters` at all, so the
    recipient's accepts_peace was handed the sentence the leader had said, fell
    through every test to a catch-all `return True`, and agreed -- and
    treaty_effects, finding nothing in the parameters either, executed the
    "peace treaty" as a white peace that transferred nothing.
    """
    from map_logic.diplomacy import deal as deal_mod
    from map_logic.diplomacy import peace_scope

    mine, theirs = peace_scope.deal_sides(ai_name, enemy, map_screen.nation_data)
    return deal_mod.new(deal_mod.KIND_PEACE, mine, theirs, [deal_mod.white_peace()])


def _victors_terms(map_screen, ai_name, enemy, leverage):
    """What a winning nation asks for: the enemy land it is standing on.

    Sized to the hand it is holding rather than to appetite -- an army sitting
    on four provinces asks for those four provinces, which is both the obvious
    demand and the one most likely to be agreed to, since occupied land is
    already discounted at the table.
    """
    from map_logic.diplomacy import deal as deal_mod
    from map_logic.diplomacy import peace_scope, war_score

    mine, theirs = peace_scope.deal_sides(ai_name, enemy, map_screen.nation_data)
    prewar = war_score.prewar_index(map_screen.nation_data)
    ours, foes = set(mine), set(theirs)

    holdings = {}
    for prov in map_screen.map_data.values():
        holder = prov.get("owner")
        if holder not in ours:
            continue
        was = war_score.original_owner(prov, prewar)
        if was in foes:
            holdings.setdefault((was, holder), []).append(prov["id"])

    if not holdings:
        return _white_peace_terms(map_screen, ai_name, enemy)

    clauses = [deal_mod.white_peace()]
    for (loser, winner), ids in sorted(holdings.items()):
        clauses.append(deal_mod.tiles_clause(loser, winner, ids))

    agreement = deal_mod.new(deal_mod.KIND_PEACE, mine, theirs, clauses)

    # Asking for everything we hold when we barely hold the upper hand reads as
    # a demand for surrender and gets refused. Below a commanding position, ask
    # for the status quo instead and take the war off the board.
    if leverage < c.AI_PEACE_DEMAND_LEVERAGE:
        return _white_peace_terms(map_screen, ai_name, enemy)
    return agreement


def _seek_ceasefire_if_unreachable(bag, map_screen, ai_name, my_enemies, active_nations, world):
    """Section 1: offers a ceasefire to any enemy we can no longer physically reach."""
    for enemy in my_enemies:
        if enemy not in active_nations: continue
        if not _may_settle(map_screen.nation_data, ai_name, enemy): continue
        if not world.reachable(ai_name, enemy):
            if ai_candidates.not_on_cooldown(map_screen.nation_data, ai_name, enemy, "CEASEFIRE"):
                bag.add(ai_candidates.make(
                    "CEASEFIRE", enemy, c.AI_SCORE_CEASEFIRE_UNREACHABLE,
                    "we cannot reach them to fight them, and the war costs us anyway",
                    parameters=_white_peace_terms(map_screen, ai_name, enemy)))


def _offer_peace_when_losing(bag, map_screen, ai_name, my_enemies, active_nations, world):
    """Section 1.2: sues for peace in a war going badly.

    Entirely new. The AI has never once offered peace -- the only thing on the
    proactive table was a ceasefire to an enemy it physically could not reach,
    so a nation being slowly destroyed by a neighbour it shared a border with
    had no way to ask for terms and simply fought until it was gone.
    """
    from map_logic.diplomacy import war_score

    for enemy in my_enemies:
        if enemy not in active_nations: continue
        if not _may_settle(map_screen.nation_data, ai_name, enemy): continue
        if not ai_candidates.not_on_cooldown(map_screen.nation_data, ai_name, enemy, "PEACE_TREATY"):
            continue

        # The receiving side has refused to talk for the first couple of turns
        # of a war since MIN_TURNS_FOR_CEASEFIRE was introduced; the offering
        # side never knew, and spent those turns proposing into a wall.
        duration = map_screen.nation_data.get(ai_name, {}).get("war_durations", {}).get(enemy, 0)
        if duration < c.MIN_TURNS_FOR_CEASEFIRE:
            continue

        appetite = ai_opinion.peace_appetite(world, ai_name, enemy, map_screen.scenario_settings)
        if appetite < c.AI_PEACE_OFFER_THRESHOLD:
            continue

        leverage = war_score.between(map_screen, ai_name, enemy, world)["mine"]
        bag.add(ai_candidates.make(
            "PEACE_TREATY", enemy, appetite,
            f"this war with {enemy} is going badly and has run long enough",
            parameters=_victors_terms(map_screen, ai_name, enemy, leverage)))


def _seek_defensive_faction(bag, map_screen, ai_name, pending, my_enemies, active_nations, world):
    """Section 1.5: an unaligned nation at war looks for a faction to join, or
    else another unaligned co-belligerent to found one with."""
    # Prevent sending multiple faction requests
    has_pending_faction_req = False
    for target_nation, info in pending.items():
        if isinstance(info, dict) and info.get("action") in ["CREATE_FACTION", "JOIN_FACTION_REQ"]:
            has_pending_faction_req = True
            break

    if has_pending_faction_req:
        return

    potential_leaders = []
    for enemy in my_enemies:
        # Find nations also at war with our enemy
        enemy_wars = queries.get_enemies(enemy, map_screen.nation_data)
        for mutual_combatant in enemy_wars:
            if mutual_combatant == ai_name or mutual_combatant not in active_nations:
                continue
            # If they have a faction, we want to talk to the leader
            fac = map_screen.nation_data.get(mutual_combatant, {}).get("faction", "")
            if fac:
                fac_leader = queries.get_faction_leader(fac, map_screen.nation_data)
                if fac_leader and fac_leader not in potential_leaders and fac_leader in active_nations:
                    potential_leaders.append(fac_leader)

    if potential_leaders:
        # Ask whichever leader we would most like to stand with, rather than
        # whichever happened to be found first.
        target_leader = max(potential_leaders,
                            key=lambda n: (ai_opinion.alliance_appetite(
                                world, ai_name, n, map_screen.scenario_settings), n))
        # A puppet has no alignment to seek -- it holds whatever its master
        # holds. Founding one is a different act and stays available:
        # finalize_create_faction redirects to the master and makes it the
        # leader, so the result is a bloc the overlord is actually in, not a
        # subject aligned somewhere its master is not.
        if (queries.can_choose_own_faction(ai_name, map_screen.nation_data)
                and ai_candidates.not_on_cooldown(map_screen.nation_data, ai_name,
                                                  target_leader, "JOIN_FACTION_REQ")):
            bag.add(ai_candidates.make(
                "JOIN_FACTION_REQ", target_leader,
                max(c.AI_SCORE_DEFENSIVE_FACTION,
                    ai_opinion.alliance_appetite(world, ai_name, target_leader,
                                                 map_screen.scenario_settings)),
                "we are at war and alone, and they already fight our enemies"))
        return

    # Find nations also at war with our enemy who aren't in a faction to form a new one with
    potential_partners = []
    for enemy in my_enemies:
        enemy_wars = queries.get_enemies(enemy, map_screen.nation_data)
        for mutual_combatant in enemy_wars:
            if mutual_combatant == ai_name or mutual_combatant not in active_nations:
                continue
            fac = map_screen.nation_data.get(mutual_combatant, {}).get("faction", "")
            if not fac and mutual_combatant not in potential_partners:
                potential_partners.append(mutual_combatant)

    if potential_partners:
        target_partner = max(potential_partners,
                             key=lambda n: (ai_opinion.alliance_appetite(
                                 world, ai_name, n, map_screen.scenario_settings), n))
        if ai_candidates.not_on_cooldown(map_screen.nation_data, ai_name, target_partner, "CREATE_FACTION"):
            bag.add(ai_candidates.make(
                "CREATE_FACTION", target_partner,
                max(c.AI_SCORE_DEFENSIVE_FACTION,
                    ai_opinion.alliance_appetite(world, ai_name, target_partner,
                                                 map_screen.scenario_settings)),
                "neither of us has allies and we fight the same enemy"))


def _call_faction_to_arms(bag, map_screen, ai_name, my_faction, my_enemies, active_nations, world):
    """Section 2: asks a faction-mate to join a war of ours they aren't already in."""
    faction_members = queries.get_faction_members(my_faction, map_screen.nation_data)
    for member in faction_members:
        if member == ai_name or member not in active_nations: continue

        member_enemies = map_screen.nation_data[member].get("at_war_with", [])

        unshared_wars = [e for e in my_enemies if e not in member_enemies and e in active_nations and not queries.has_active_truce(member, e, map_screen.nation_data)]

        if unshared_wars:
            if ai_candidates.not_on_cooldown(map_screen.nation_data, ai_name, member, "CALL_TO_ARMS"):
                # More urgent the worse the war is going.
                urgency = ai_opinion.peace_appetite(world, ai_name, unshared_wars[0],
                                                    map_screen.scenario_settings)
                bag.add(ai_candidates.make(
                    "CALL_TO_ARMS", member,
                    c.AI_SCORE_CALL_TO_ARMS + (1.0 - c.AI_SCORE_CALL_TO_ARMS) * urgency,
                    f"they are sworn to our faction and we are fighting {unshared_wars[0]} alone",
                    context_target=unshared_wars[0]))


def _request_access_from_co_belligerents(bag, map_screen, ai_name, my_enemies, active_nations):
    """Section 2.5: even nations in different factions ask each other for
    passage if they're both fighting the same enemy, so allied fronts can
    actually link up."""
    co_belligerents = []
    for enemy in my_enemies:
        if enemy not in active_nations: continue
        for co in queries.get_enemies(enemy, map_screen.nation_data):
            if co == ai_name or co not in active_nations: continue
            if co in co_belligerents: continue
            if co in my_enemies: continue
            if not queries.needs_military_access_request(ai_name, co, map_screen.nation_data): continue
            co_belligerents.append(co)

    for co in co_belligerents:
        if not ai_candidates.not_on_cooldown(map_screen.nation_data, ai_name, co, "REQ_MILITARY_ACCESS"):
            continue
        bag.add(ai_candidates.make(
            "REQ_MILITARY_ACCESS", co, c.AI_SCORE_MILITARY_ACCESS,
            "we fight the same enemy and our fronts cannot link up without passage"))


def _join_faction_wars_proactively(bag, map_screen, ai_name, my_faction, my_enemies,
                                   active_nations, world):
    """Section 3: offers to join a faction-mate's war we aren't already in."""
    faction_members = queries.get_faction_members(my_faction, map_screen.nation_data)
    loyalty = ai_personality.trait(map_screen.nation_data, ai_name, "loyalty",
                                   map_screen.scenario_settings)
    for member in faction_members:
        if member == ai_name:
            continue

        member_enemies = map_screen.nation_data[member].get("at_war_with", [])

        unshared_wars = [e for e in member_enemies if e not in my_enemies and e in active_nations and not queries.has_active_truce(ai_name, e, map_screen.nation_data)]

        if unshared_wars:
            target_enemy = unshared_wars[0]
            if ai_candidates.not_on_cooldown(map_screen.nation_data, ai_name, member, "JOIN_WARS"):
                # A faithless nation lets its allies fight alone; a loyal one
                # turns up. Nothing used to distinguish them.
                bag.add(ai_candidates.make(
                    "JOIN_WARS", member, c.AI_SCORE_JOIN_WARS * (0.4 + 1.2 * loyalty),
                    f"our faction-mate is fighting {target_enemy} without us",
                    context_target=target_enemy))


def _declare_war_for_cores_and_claims(bag, map_screen, ai_name, my_enemies, my_master, my_type, is_already_at_war, active_nations, world):
    """Section 4: declares war on a bordering nation holding our cores/claims
    once we think we can win, or fabricates a claim on them first if we lack a wargoal."""
    if my_master and my_type == c.PUPPET_TYPE_INTEGRATED:
        return

    current_turn = queries.get_total_turns(map_screen.time_manager)
    turns_to_wait = int(map_screen.scenario_settings.get("turns_to_wait_before_war", c.TURNS_TO_WAIT_BEFORE_WAR))
    if current_turn < turns_to_wait:
        return

    valid_war_targets = world.core_claim_targets(ai_name)
    if not valid_war_targets:
        return

    # ONLY look at nations we actually share a physical border with. Sorted for
    # a stable order -- iterating the raw set meant which neighbour got invaded
    # came down to string hash order, randomised per process, so the same save
    # could start a different war on different launches. Every one that passes
    # is now offered as a candidate carrying its own desire, and the arbiter
    # picks; this loop no longer breaks on the first.
    my_neighbors = world.neighbors[ai_name]
    valid_border_targets = sorted(t for t in valid_war_targets if t in my_neighbors)

    for target in valid_border_targets:
        if target not in active_nations: continue
        if target in my_enemies: continue
        if queries.are_in_same_faction(ai_name, target, map_screen.nation_data): continue
        if queries.has_active_truce(ai_name, target, map_screen.nation_data): continue

        # --- NEW: Skip Integrated Puppets ---
        t_master = map_screen.nation_data.get(target, {}).get("master", "")
        t_type = map_screen.nation_data.get(target, {}).get("puppet_type", "")
        if t_master and t_type == c.PUPPET_TYPE_INTEGRATED:
            continue

        # Avoid arbitrary attacks on masters
        if my_master and my_type == c.PUPPET_TYPE_AUTONOMOUS and target != my_master:
            continue

        # Border superiority, alliance/economic power and how distracted
        # the target already is all live inside ai_thinks_it_can_win; this
        # block used to recompute every one of them and throw the result
        # away, which cost several full map scans per candidate target.
        # Not "could I win" but "do I want this": the odds still dominate, but a
        # nation we are on good terms with, a promise we made, and the two wars
        # we are already losing all count now -- and an aggressive nation will
        # gamble on odds a cautious one turns down.
        desire = ai_opinion.war_desire(world, ai_name, target, map_screen.scenario_settings)
        if desire >= c.AI_WAR_DESIRE_THRESHOLD:

            # Random chance to actually declare war
            war_chance = float(map_screen.scenario_settings.get("ai_war_declaration_chance", c.AI_WAR_DECLARATION_CHANCE))
            if random.random() <= war_chance:
                has_wargoal = queries.has_wargoal(ai_name, target, map_screen.nation_data, map_screen.map_data)
                if has_wargoal:
                    if ai_candidates.not_on_cooldown(map_screen.nation_data, ai_name, target, "WAR_DECLARATION"):
                        bag.add(ai_candidates.make(
                            "WAR_DECLARATION", target, desire,
                            f"{target} holds territory that is ours by right and we have the strength to take it",
                            context_target=target))
                else:
                    # Make a claim! (assuming no war is happening). Not a
                    # proposal -- it goes straight into our own claim queue --
                    # so it is done here rather than offered as a candidate.
                    if not is_already_at_war and not queries.is_ai_diplo_on_cooldown(ai_name, target, "MAKE_CLAIM", map_screen.nation_data):
                        core_ids = []
                        for prov in map_screen.map_data.values():
                            if prov.get("owner") == target and ai_name in prov.get("cores", []):
                                core_ids.append(prov["id"])

                        if core_ids:
                            queue = map_screen.nation_data[ai_name].setdefault("claim_queue", [])
                            claims = map_screen.nation_data[ai_name].setdefault("claims", [])
                            for cid in core_ids:
                                if cid not in claims and not any(q["prov_id"] == cid for q in queue):
                                    queue.append({"prov_id": cid, "turns_left": c.CLAIM_TURN_CORE})

                            queries.set_ai_diplo_cooldown(ai_name, target, "MAKE_CLAIM", map_screen.nation_data, duration=c.AI_CLAIM_COOLDOWN)
                            break


def _drain_llm_requests(bag, map_screen, ai_name, data, my_enemies, active_nations, world):
    """Section 5.5: reconsiders what the leader asked for last turn.

    The model can push for an action while answering a proposal. That used to be
    executed on the spot, which meant a war declaration skipped the waiting
    period, the border requirement and the need for a wargoal, and went ahead
    with WARGOAL_NO_CB against a nation the AI might not be able to reach.

    Requests are now offered here instead, and only if they clear exactly the
    same checks as anything the staff proposed. A legal one carries a bonus,
    because the leader wanting it is real information -- an illegal one is
    dropped, with a rumour in the log so the pressure is still visible.
    """
    requests = data.get("ai_requests") or []
    if not requests:
        return
    data["ai_requests"] = []

    current_turn = queries.get_total_turns(map_screen.time_manager)
    turns_to_wait = int(map_screen.scenario_settings.get(
        "turns_to_wait_before_war", c.TURNS_TO_WAIT_BEFORE_WAR))

    for request in requests:
        target = request.get("target")
        action = request.get("action")
        if action != "WAR_DECLARATION" or target not in active_nations or target == ai_name:
            continue
        if current_turn - request.get("turn", 0) > c.AI_REQUEST_LIFETIME:
            continue

        legal = (current_turn >= turns_to_wait
                 and target not in my_enemies
                 and target in world.neighbors.get(ai_name, ())
                 and not queries.are_in_same_faction(ai_name, target, map_screen.nation_data)
                 and not queries.has_active_truce(ai_name, target, map_screen.nation_data)
                 and queries.has_wargoal(ai_name, target, map_screen.nation_data, map_screen.map_data)
                 and ai_candidates.not_on_cooldown(map_screen.nation_data, ai_name, target,
                                                   "WAR_DECLARATION"))
        if not legal:
            diplomacy_events.log_global_event(
                map_screen.nation_data,
                f"RUMOR: {ai_name} weighed war with {target} and thought better of it.")
            continue

        desire = ai_opinion.war_desire(world, ai_name, target, map_screen.scenario_settings)
        bag.add(ai_candidates.make(
            "WAR_DECLARATION", target, min(1.0, desire + c.AI_LLM_REQUEST_BONUS),
            f"our own government has pressed for this war since {request.get('reason') or 'last season'}",
            context_target=target))


def _invite_friends_to_faction(bag, map_screen, ai_name, data, active_nations, world):
    """Section 6: a faction leader recruits nations it gets on with.

    New. FACTION_INVITE existed as an action a player could send and an AI could
    accept, but no AI ever sent one -- factions only ever grew by outsiders
    asking to be let in, so a strong bloc never courted anyone.
    """
    if not data.get("is_faction_leader") or getattr(c, "DISABLE_FACTIONS", False):
        return

    for other in sorted(active_nations):
        if other == ai_name:
            continue
        other_data = map_screen.nation_data.get(other, {})
        if other_data.get("faction"):
            continue
        # Courting somebody else's subject is courting their overlord's answer.
        if not queries.can_choose_own_faction(other, map_screen.nation_data):
            continue
        if queries.are_at_war(ai_name, other, map_screen.nation_data):
            continue
        if not ai_candidates.not_on_cooldown(map_screen.nation_data, ai_name, other, "FACTION_INVITE"):
            continue

        appetite = ai_opinion.alliance_appetite(world, ai_name, other,
                                                map_screen.scenario_settings)
        if appetite >= c.AI_ALLIANCE_DESIRE_THRESHOLD:
            bag.add(ai_candidates.make(
                "FACTION_INVITE", other, appetite,
                "they are unaligned, we are on good terms, and they would strengthen the bloc"))


def _offer_trades(bag, map_screen, ai_name, active_nations, world):
    """Section 7: offers a swap to a neighbour whose shortages mirror ours.

    New. The AI could not propose a trade at all, and would accept one only if
    it gave away literally nothing -- so the entire trade system was inert
    between AI nations.
    """
    for other in sorted(world.neighbors.get(ai_name, ())):
        if other not in active_nations:
            continue
        if queries.are_at_war(ai_name, other, map_screen.nation_data):
            continue
        # Neutral is fine. Relations sit at exactly 0 for almost every pair on
        # a fresh map -- requiring better than that meant trade never happened
        # anywhere. Only active dislike rules it out.
        if world.relation(ai_name, other) < 0:
            continue
        if not ai_candidates.not_on_cooldown(map_screen.nation_data, ai_name, other, "TRADE"):
            continue

        offer = ai_candidates.resource_offer(world, ai_name, other,
                                             map_screen.scenario_settings)
        if not offer:
            continue

        bag.add(ai_candidates.make(
            "TRADE", other, c.AI_SCORE_TRADE,
            "we have a surplus of what they lack, and they of what we lack",
            parameters=offer))


def _fabricate_claims_during_war(map_screen, ai_name, data, my_enemies, active_nations):
    """Section 4.5: while at war and with no claim queued, picks one enemy
    province (preferring one bordering territory we already hold or claim) to fabricate a claim on."""
    claim_queue = data.get("claim_queue", [])
    if claim_queue:
        return

    my_claims = set(data.get("claims", []))
    owned_and_claimed = set(my_claims)
    for prov in map_screen.map_data.values():
        if prov.get("owner") == ai_name:
            owned_and_claimed.add(prov["id"])

    potential_targets_adjacent = []
    potential_targets_any = []

    for enemy in my_enemies:
        if enemy not in active_nations: continue
        if queries.is_ai_diplo_on_cooldown(ai_name, enemy, "FABRICATE_CLAIM", map_screen.nation_data):
            continue

        for prov in map_screen.map_data.values():
            if prov.get("owner") == enemy and prov["id"] not in my_claims:
                potential_targets_any.append((enemy, prov))
                if any(n_id in owned_and_claimed for n_id in prov.get("neighbors", [])):
                    potential_targets_adjacent.append((enemy, prov))

    chosen_target = None
    if potential_targets_adjacent:
        chosen_target = random.choice(potential_targets_adjacent)
    elif potential_targets_any:
        chosen_target = random.choice(potential_targets_any)

    if chosen_target:
        target_enemy, target_prov = chosen_target
        data.setdefault("claim_queue", []).append({"prov_id": target_prov["id"], "turns_left": c.CLAIM_TURN_NON_CORE})
        queries.set_ai_diplo_cooldown(ai_name, target_enemy, "FABRICATE_CLAIM", map_screen.nation_data, duration=c.AI_CLAIM_COOLDOWN)


def _fabricate_claims_on_weaker_neighbors(map_screen, ai_name, data, my_master, my_enemies, active_nations, world):
    """Section 5: while at peace, fabricates a claim on a weaker bordering
    neighbor we don't already have a wargoal or claim against."""
    current_turn = queries.get_total_turns(map_screen.time_manager)
    turns_to_wait = int(map_screen.scenario_settings.get("turns_to_wait_before_war", c.TURNS_TO_WAIT_BEFORE_WAR))
    if current_turn < turns_to_wait:
        return

    # Sorted for the same reason as the war-target loop above: this one also
    # breaks after the first neighbour it successfully queues a claim against.
    my_neighbors = sorted(world.neighbors[ai_name])

    for neighbor in my_neighbors:
        if neighbor not in active_nations: continue
        if neighbor in my_enemies: continue
        if queries.are_in_same_faction(ai_name, neighbor, map_screen.nation_data): continue
        if queries.has_active_truce(ai_name, neighbor, map_screen.nation_data): continue

        # Avoid attacking masters or puppets
        n_master = map_screen.nation_data.get(neighbor, {}).get("master", "")
        if my_master and my_master == neighbor: continue
        if n_master and n_master == ai_name: continue

        # Check if we already have claims on them or an active wargoal
        has_wg = queries.has_wargoal(ai_name, neighbor, map_screen.nation_data, map_screen.map_data)
        claims = data.get("claims", [])
        has_claims_on_them = any(map_screen.id_to_province.get(cid, {}).get("owner") == neighbor for cid in claims)

        if not has_wg and not has_claims_on_them:
            # Fabricating a claim is how a war becomes legal later, so it wants
            # the same appetite the war itself will need -- minus the wargoal
            # requirement it exists to satisfy. An unambitious nation on good
            # terms with a weak neighbour now simply leaves them alone.
            if (world.is_weaker_neighbor(ai_name, neighbor)
                    and ai_opinion.war_desire(world, ai_name, neighbor,
                                              map_screen.scenario_settings)
                    >= c.AI_CLAIM_DESIRE_THRESHOLD):
                if not queries.is_ai_diplo_on_cooldown(ai_name, neighbor, "FABRICATE_CLAIM", map_screen.nation_data):

                    valid_targets = queries.get_valid_claim_targets(ai_name, neighbor, map_screen.map_data)
                    if valid_targets:
                        target_prov = random.choice(valid_targets)
                        queue = data.setdefault("claim_queue", [])

                        # Ensure it's not already in the queue
                        if not any(q["prov_id"] == target_prov["id"] for q in queue):
                            queue.append({"prov_id": target_prov["id"], "turns_left": c.CLAIM_TURN_NON_CORE})
                            queries.set_ai_diplo_cooldown(ai_name, neighbor, "FABRICATE_CLAIM", map_screen.nation_data, duration=c.AI_CLAIM_COOLDOWN)
                            break  # Limit to queueing one claim per cycle


def _run_basic_proactive_ai(map_screen):
    active_nations = set(queries.get_living_nations(map_screen.map_data))
    ai_nations = queries.get_active_ai_nations(map_screen)

    # --- Trigger the UI Progress Bar ---
    map_screen.proactive_tasks_total = len(ai_nations)
    map_screen.proactive_tasks_completed = 0
    map_screen.loading_status_text = "Evaluating AI Grand Strategy..."

    # Nothing below redraws the map, so every border, strength and relation
    # this pass asks about is the same for every nation in it. The snapshot
    # holds the reachability graph that used to be built here, plus the
    # per-pair answers each section below would otherwise sweep the map for.
    world = ai_world.for_screen(map_screen)
    map_screen.proactive_choices = []

    for ai_name in ai_nations:
        if ai_name not in active_nations:
            map_screen.proactive_tasks_completed += 1
            continue

        data = map_screen.nation_data[ai_name]
        pending = data.setdefault("pending_diplomacy", {})
        my_faction = data.get("faction", "")
        my_enemies = data.get("at_war_with", [])
        my_master = data.get("master", "")
        my_type = data.get("puppet_type", "")

        _decrement_diplo_cooldowns(data)
        _auto_revoke_war_based_access(map_screen, ai_name, data, my_enemies)

        # Battle Royale has no diplomacy to run, but the cooldown/access
        # upkeep above still applies to every nation -- this used to `return`
        # from inside the loop, which skipped that upkeep for every nation
        # after the first and left the loading bar stuck below its total.
        if c.BATTLE_ROYALE_MODE:
            map_screen.proactive_tasks_completed += 1
            continue

        is_already_at_war = len(my_enemies) > 0

        # Every section offers what it would like to do and the arbiter picks.
        # They used to write straight into pending_diplomacy, which holds one
        # action per target, so whichever section ran first won the slot and the
        # rest were silently discarded -- a Call to Arms from section 2 starved
        # the war declaration section 4 wanted to send to the same nation, and
        # nothing anywhere compared the two.
        bag = ai_candidates.Collector(ai_name, pending)

        if is_already_at_war:
            _seek_ceasefire_if_unreachable(bag, map_screen, ai_name, my_enemies, active_nations, world)
            _offer_peace_when_losing(bag, map_screen, ai_name, my_enemies, active_nations, world)

        if is_already_at_war and not my_faction and not getattr(c, "DISABLE_FACTIONS", False):
            _seek_defensive_faction(bag, map_screen, ai_name, pending, my_enemies, active_nations, world)

        if is_already_at_war and my_faction:
            _call_faction_to_arms(bag, map_screen, ai_name, my_faction, my_enemies, active_nations, world)

        if is_already_at_war:
            _request_access_from_co_belligerents(bag, map_screen, ai_name, my_enemies, active_nations)

        if my_faction:
            _join_faction_wars_proactively(bag, map_screen, ai_name, my_faction, my_enemies, active_nations, world)

        _declare_war_for_cores_and_claims(bag, map_screen, ai_name, my_enemies, my_master, my_type, is_already_at_war, active_nations, world)

        _drain_llm_requests(bag, map_screen, ai_name, data, my_enemies, active_nations, world)

        if not getattr(c, "DISABLE_FACTIONS", False):
            _invite_friends_to_faction(bag, map_screen, ai_name, data, active_nations, world)

        _offer_trades(bag, map_screen, ai_name, active_nations, world)

        # Held rather than executed. The director pass runs next and gives each
        # nation's leader the chance to pick differently from its staff; without
        # a model, or after a Force Skip, `chosen` is what actually happens.
        ranked = bag.ranked()
        if ranked:
            map_screen.proactive_choices.append({
                "nation": ai_name,
                "pending": pending,
                "candidates": ranked,
                "chosen": ranked[:c.AI_MAX_ACTIONS_PER_TURN],
                "messages": {},
            })

        if is_already_at_war and not (my_master and my_type == c.PUPPET_TYPE_INTEGRATED):
            _fabricate_claims_during_war(map_screen, ai_name, data, my_enemies, active_nations)

        if not is_already_at_war and not (my_master and my_type == c.PUPPET_TYPE_INTEGRATED):
            _fabricate_claims_on_weaker_neighbors(map_screen, ai_name, data, my_master, my_enemies, active_nations, world)

        # --- Update Progress Bar ---
        map_screen.proactive_tasks_completed += 1
        map_screen.loading_status_text = f"Evaluating AI Grand Strategy ({map_screen.proactive_tasks_completed}/{map_screen.proactive_tasks_total})..."

def process_scripted_events(map_screen):
    """Processes scenario-specific scripted events for AI nations."""
    if not queries.get_scenario_flag("use_scripted_events", c.DEFAULT_USE_SCRIPTED_EVENTS, map_screen.scenario_settings):
        return
        
    active_nations = set(queries.get_living_nations(map_screen.map_data))
    human_players = map_screen.active_players
    current_turn = queries.get_total_turns(map_screen.time_manager)
    
    for nation_name in active_nations:
        data = map_screen.nation_data.get(nation_name, {})
        events = data.get("scripted_events", [])
        if not events:
            continue
            
        fired_events = data.setdefault("fired_scripted_events", [])
        
        for i, evt in enumerate(events):
            if i in fired_events and evt.get("fire_once", True):
                continue
                
            # --- NEW: TRIGGER TYPE CHECK ---
            trigger_type = evt.get("trigger_type", "AI Only")
            if trigger_type == "AI Only" and nation_name in human_players:
                continue
            if trigger_type == "Player Only" and nation_name not in human_players:
                continue
            
            # Backwards compatibility parser
            if "conditions" not in evt:
                evt["conditions"] = [{
                    "type": evt.get("condition_type", "Turn Number"),
                    "operator": "==",
                    "value": evt.get("condition_val", ""),
                    "chain": "AND"
                }]
                evt["fire_once"] = True

            conditions = evt.get("conditions", [])
            if not conditions:
                continue

            overall_met = False

            for c_idx, cond in enumerate(conditions):
                c_type = cond.get("type")
                c_op = cond.get("operator", "==")
                c_val = cond.get("value", "")
                chain = cond.get("chain", "AND")
                
                res = False
                
                if c_type == "Turn Number":
                    try:
                        if "BETWEEN" in c_op:
                            parts = c_val.split(",")
                            if len(parts) >= 2:
                                v1, v2 = int(parts[0].strip()), int(parts[1].strip())
                                if c_op == "BETWEEN (INC)":
                                    res = (v1 <= current_turn <= v2)
                                else:
                                    res = (v1 < current_turn < v2)
                        else:
                            v = int(c_val.strip())
                            if c_op == "==": res = (current_turn == v)
                            elif c_op == ">": res = (current_turn > v)
                            elif c_op == "<": res = (current_turn < v)
                            elif c_op == ">=": res = (current_turn >= v)
                            elif c_op == "<=": res = (current_turn <= v)
                    except ValueError:
                        pass
                
                # Random Generation
                elif c_type == "Random (0.00 - 1.00)":
                    rand_val = random.random()
                    try:
                        if "BETWEEN" in c_op:
                            parts = c_val.split(",")
                            if len(parts) >= 2:
                                v1, v2 = float(parts[0].strip()), float(parts[1].strip())
                                if c_op == "BETWEEN (INC)":
                                    res = (v1 <= rand_val <= v2)
                                else:
                                    res = (v1 < rand_val < v2)
                        else:
                            v = float(c_val.strip())
                            if c_op == "==": res = (rand_val == v)
                            elif c_op == ">": res = (rand_val > v)
                            elif c_op == "<": res = (rand_val < v)
                            elif c_op == ">=": res = (rand_val >= v)
                            elif c_op == "<=": res = (rand_val <= v)
                    except ValueError:
                        pass
                        
                elif c_type == "Variable":
                    var_name = cond.get("variable", "")
                    var_type = "string"
                    var_val = "0"
                    for v in getattr(map_screen, "script_variables", []):
                        if v["name"] == var_name:
                            var_type = v["type"]
                            var_val = v["value"]
                            break
                            
                    if var_type in ["int", "double"]:
                        try:
                            # Int truncates internally for execution
                            current_v = int(float(var_val)) if var_type == "int" else float(var_val)
                            check_v = int(float(c_val.strip())) if var_type == "int" else float(c_val.strip())
                            
                            if "BETWEEN" in c_op:
                                parts = c_val.split(",")
                                if len(parts) >= 2:
                                    v1 = int(float(parts[0].strip())) if var_type == "int" else float(parts[0].strip())
                                    v2 = int(float(parts[1].strip())) if var_type == "int" else float(parts[1].strip())
                                    if c_op == "BETWEEN (INC)":
                                        res = (v1 <= current_v <= v2)
                                    else:
                                        res = (v1 < current_v < v2)
                            else:
                                if c_op == "==": res = (current_v == check_v)
                                elif c_op == "!=": res = (current_v != check_v)
                                elif c_op == ">": res = (current_v > check_v)
                                elif c_op == "<": res = (current_v < check_v)
                                elif c_op == ">=": res = (current_v >= check_v)
                                elif c_op == "<=": res = (current_v <= check_v)
                        except ValueError:
                            res = False
                    else:
                        if c_op == "==": res = (str(var_val) == str(c_val))
                        elif c_op == "!=": res = (str(var_val) != str(c_val))
                        
                elif c_type in ["At War With", "In Faction With", "Not In Faction With", "Has Truce With", "At Peace With", "Country Exists", "Country Doesn't Exist", "Occupying Claims Of", "Occupying All Claims"]:
                    targets = [t.strip() for t in str(c_val).split(",") if t.strip()]
                    if not targets:
                        res = False
                    elif c_type == "At War With":
                        res = all(t in active_nations and queries.are_at_war(nation_name, t, map_screen.nation_data) for t in targets)
                    elif c_type == "In Faction With":
                        res = all(t in active_nations and queries.are_in_same_faction(nation_name, t, map_screen.nation_data) for t in targets)
                    elif c_type == "Not In Faction With":
                        res = all(t in active_nations and not queries.are_in_same_faction(nation_name, t, map_screen.nation_data) for t in targets)
                    elif c_type == "Has Truce With":
                        res = all(t in active_nations and queries.has_active_truce(nation_name, t, map_screen.nation_data) for t in targets)
                    elif c_type == "At Peace With":
                        res = all(t in active_nations and not queries.are_at_war(nation_name, t, map_screen.nation_data) for t in targets)
                    elif c_type == "Country Exists":
                        res = all(t in active_nations for t in targets)
                    elif c_type == "Country Doesn't Exist":
                        res = all(t not in active_nations for t in targets)
                    elif c_type == "Occupying Claims Of":
                        res = all(any(map_screen.id_to_province.get(pid, {}).get("owner") == nation_name for pid in map_screen.nation_data.get(t, {}).get("claims", [])) for t in targets)
                    elif c_type == "Occupying All Claims":
                        res = all(map_screen.nation_data.get(t, {}).get("claims") and all(map_screen.id_to_province.get(pid, {}).get("owner") == nation_name for pid in map_screen.nation_data.get(t, {}).get("claims", [])) for t in targets)
                elif c_type == "True":
                    res = True
                elif c_type == "False":
                    res = False
                elif c_type == "Received Action":
                    pend_act, pend_turns = queries.get_diplomatic_status(c_val, nation_name, map_screen.nation_data)
                    res = (pend_act == c_op and pend_turns > 0)
                elif c_type == "Occupying All Cores Of":
                    res = queries.is_occupying_all_cores(nation_name, c_val, map_screen.map_data)
                elif c_type == "Occupying Tile":
                    res = queries.is_occupying_tiles(nation_name, c_val, map_screen.id_to_province)
                elif c_type == "Is AI Controlled":
                    target_check = c_val if c_val else nation_name
                    res = (target_check not in human_players and target_check in active_nations)
                elif c_type == "Is Player Controlled":
                    target_check = c_val if c_val else nation_name
                    res = (target_check in human_players and target_check in active_nations)
                elif c_type == "Occupying Core Of":
                    res = any(p.get("owner") == nation_name and c_val in p.get("cores", []) for p in map_screen.map_data.values())
                elif c_type == "Bordering":
                    res = c_val in queries.get_neighboring_nations(nation_name, map_screen.map_data, map_screen.id_to_province)
                elif c_type == "Not Bordering":
                    res = c_val not in queries.get_neighboring_nations(nation_name, map_screen.map_data, map_screen.id_to_province)
                elif c_type == "Is At War":
                    target_check = c_val if c_val else nation_name
                    res = len(queries.get_enemies(target_check, map_screen.nation_data)) > 0
                elif c_type == "Is At Peace":
                    target_check = c_val if c_val else nation_name
                    res = len(queries.get_enemies(target_check, map_screen.nation_data)) == 0
                elif c_type == "Is In Faction":
                    target_check = c_val if c_val else nation_name
                    res = map_screen.nation_data.get(target_check, {}).get("faction", "") != ""
                elif c_type == "Is Faction Leader":
                    target_check = c_val if c_val else nation_name
                    res = queries.is_faction_leader(target_check, map_screen.nation_data)
                    
                if c_idx == 0:
                    overall_met = res
                else:
                    if chain == "AND": overall_met = overall_met and res
                    elif chain == "OR": overall_met = overall_met or res
                    elif chain == "XOR": overall_met = overall_met ^ res
                    elif chain == "NOR": overall_met = not (overall_met or res)
                    elif chain == "NAND": overall_met = not (overall_met and res)
                    
            if overall_met:
                actions = evt.get("actions", [])
                if not actions and "action_type" in evt:
                    actions = [{"type": evt["action_type"], "target": evt.get("action_target", "None")}]
                
                pending = data.setdefault("pending_diplomacy", {})
                
                for act in actions:
                    a_type = act.get("type")
                    raw_targets = act.get("target", "None")
                    
                    if a_type in ["Edit Name", "Edit Leader Name", "Edit Leader Title", "Edit Color", "Edit Flag", "Edit Portrait"]:
                        val = act.get("message", "")
                        if not val: continue
                        
                        if a_type == "Edit Name":
                            data["name"] = val
                        elif a_type == "Edit Leader Name":
                            data["leader_name"] = val
                        elif a_type == "Edit Leader Title":
                            data["leader_title"] = val
                        elif a_type == "Edit Flag":
                            data["flag_data"] = val
                        elif a_type == "Edit Portrait":
                            data["portrait_data"] = val
                        elif a_type == "Edit Color":
                            try:
                                new_col = tuple(map(int, val.replace(" ", "").split(',')))
                                if len(new_col) == 3:
                                    data["color"] = list(new_col)
                                    if hasattr(map_screen, 'nation_colors'):
                                        map_screen.nation_colors[nation_name] = new_col
                                    map_screen.centers_need_update = True
                            except Exception:
                                pass
                        continue

                    if a_type == "Queue Claims":
                        prov_ids = [int(p.strip()) for p in str(act.get("message", "")).split(",") if p.strip().isdigit()]
                        for pid in prov_ids:
                            queue = data.setdefault("claim_queue", [])
                            if not any(q["prov_id"] == pid for q in queue) and pid not in data.get("claims", []):
                                queue.append({"prov_id": pid, "turns_left": c.CLAIM_TURN_NON_CORE})
                        continue

                    if a_type == "Revoke Claims":
                        prov_ids = [int(p.strip()) for p in str(act.get("message", "")).split(",") if p.strip().isdigit()]
                        revoke_queue = data.setdefault("revoke_queue", [])
                        for pid in prov_ids:
                            if not any(rq["prov_id"] == pid for rq in revoke_queue) and pid in data.get("claims", []):
                                revoke_queue.append({"prov_id": pid, "turns_left": 1})
                        continue

                    if a_type == "Revoke All Claims":
                        target_list = [t.strip() for t in str(raw_targets).split(",") if t.strip()]
                        for a_target in target_list:
                            if a_target == "None": continue
                            t_data = map_screen.nation_data.get(a_target, {})
                            revoke_queue = t_data.setdefault("revoke_queue", [])
                            for pid in t_data.get("claims", []):
                                if not any(rq["prov_id"] == pid for rq in revoke_queue):
                                    revoke_queue.append({"prov_id": pid, "turns_left": 1})
                        continue

                    if a_type == "Give Territory":
                        target_list = [t.strip() for t in str(raw_targets).split(",") if t.strip()]
                        tiles = [t.strip() for t in str(act.get("message", "")).split(",") if t.strip()]
                        must_control = act.get("ai_generate", False)
                        from map_logic.turn_processing import edit_province_ownership
                        for a_target in target_list:
                            if a_target == "None": continue
                            for tile_id in tiles:
                                if not tile_id.isdigit(): continue
                                prov = map_screen.id_to_province.get(int(tile_id))
                                if prov:
                                    if must_control and prov.get("owner") != nation_name:
                                        continue
                                    edit_province_ownership.conquer_province(map_screen, prov, a_target)
                        continue

                    if a_type == "Spawn Unit":
                        target_list = [t.strip() for t in str(raw_targets).split(",") if t.strip()]
                        unit_type = act.get("unit_type", "Infantry Type 1910")
                        tiles = [t.strip() for t in str(act.get("message", "")).split(",") if t.strip()]
                        must_control = act.get("ai_generate", False)
                        for a_target in target_list:
                            if a_target == "None": continue
                            for tile_id in tiles:
                                if not tile_id.isdigit(): continue
                                prov = map_screen.id_to_province.get(int(tile_id))
                                if prov:
                                    if must_control and prov.get("owner") != nation_name:
                                        continue
                                    new_unit = queries.create_unit_dict(unit_type, a_target, queries.get_unit_library())
                                    prov.setdefault("units", []).append(new_unit)
                        continue
                    
                    if a_type == "Set Variable":
                        var_name = act.get("target")
                        op = act.get("unit_type", "Set")
                        msg_val = act.get("message", "0")
                        
                        for v in getattr(map_screen, "script_variables", []):
                            if v["name"] == var_name:
                                var_type = v["type"]
                                if var_type in ["int", "double"]:
                                    try:
                                        current_v = float(v["value"])
                                        change_v = float(msg_val)
                                        
                                        if op == "Set":
                                            current_v = change_v
                                        elif op == "Add":
                                            current_v += change_v
                                        elif op == "Subtract":
                                            current_v -= change_v
                                        elif op == "Multiply":
                                            current_v *= change_v
                                        elif op == "Divide" and change_v != 0:
                                            current_v /= change_v
                                            
                                        if var_type == "int":
                                            v["value"] = str(int(current_v))
                                        else:
                                            v["value"] = str(current_v)
                                    except ValueError:
                                        pass
                                else:
                                    if op == "Set":
                                        v["value"] = str(msg_val)
                                break
                        continue
                    
                    # Supports comma-separated targets for simultaneous multi-country actions
                    target_list = [t.strip() for t in str(raw_targets).split(",") if t.strip()]
                    
                    for a_target in target_list:
                        if a_target == "None": continue

                        # Answering a proposal is its own channel, not a pending action
                        if a_type in ("Accept Proposal", "Reject Proposal"):
                            pend_act, pend_turns = queries.get_diplomatic_status(a_target, nation_name, map_screen.nation_data)
                            if pend_turns > 0 and pend_act in c.BILATERAL_ACTIONS:
                                verdict = diplomacy_messages.RESPONSE_ACCEPT if a_type == "Accept Proposal" else diplomacy_messages.RESPONSE_REJECT
                                their_req = diplomacy_messages.get_pending(map_screen.nation_data, a_target, nation_name)
                                diplomacy_messages.set_response(
                                    map_screen.nation_data, nation_name, a_target, verdict, pend_act,
                                    message=act.get("message", ""), parameters=their_req.get("parameters"))
                            continue

                        eng_action = ""
                        if a_type == "Declare War": eng_action = "WAR_DECLARATION"
                        elif a_type == "Join Faction": eng_action = "JOIN_FACTION_REQ"
                        elif a_type == "Create Faction": eng_action = "CREATE_FACTION"
                        elif a_type == "Invite to Faction": eng_action = "FACTION_INVITE"
                        elif a_type == "Send Ceasefire": eng_action = "CEASEFIRE"
                        elif a_type == "Send Custom Message": eng_action = f"MSG:{act.get('message', '')}"

                        if eng_action:
                            already_queued = (a_target in pending and isinstance(pending[a_target], dict) and pending[a_target].get("action") == eng_action)
                            if not already_queued:
                                custom_msg = act.get("message", "")
                                ai_generate = act.get("ai_generate", False)

                                pending[a_target] = {
                                    "action": eng_action,
                                    "turns": 0,
                                    "timer": 0,
                                    "message": custom_msg
                                }

                                if ai_generate:
                                    # Generated here rather than queued. Scripted
                                    # events run *after* the LLM pass, so anything
                                    # appended to its task list was never picked
                                    # up -- the ai_generate checkbox has quietly
                                    # done nothing. There are only ever a handful
                                    # of these in a turn, so an inline call costs
                                    # little and makes the option real.
                                    fallback = custom_msg if custom_msg else "We have sent a diplomatic missive."
                                    generated = ai_handler.generate_proactive_text(
                                        map_screen.nation_data, active_nations, nation_name,
                                        a_target,
                                        ai_prompts.get_proactive_action_context(eng_action, a_target),
                                        human_players, ai_handler.CURRENT_TURN_ID)
                                    pending[a_target]["message"] = generated or fallback
                            
                if evt.get("fire_once", True) and i not in fired_events:
                    fired_events.append(i)