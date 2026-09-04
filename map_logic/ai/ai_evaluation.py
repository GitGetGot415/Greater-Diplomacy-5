"""Turns a diplomatic proposal, a plain message, or a proactive action into an
AI reply: canned-table lookup when the LLM isn't consulted, otherwise a
provider call routed through map_logic.ai.ai_handler.

Split out of map_logic/ai/ai_handler.py, which re-exports every name here so
existing `ai_handler.evaluate_diplomatic_proposal(...)`-style call sites keep
working.
"""
import collections

import data.constants as c
from map_logic.ai import ai_commitments, ai_opinion, ai_settings, ai_world
from data import queries
from map_logic.ai import ai_prompts
from map_logic.diplomacy import diplomacy_messages


def _to_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _reply(message, source=None, accepted=None, llm=False):
    """The answer dict every AI entry point in this file returns.

    It was written out fifteen times, which is how the Ollama branch came to
    trust the model's `opinion_change` raw while the Gemini branch coerced it
    to an int. `source` is a parsed model reply to lift the action fields off;
    without one they all read "NONE", which is what every canned answer said.
    `accepted` is omitted entirely when None -- replies to a plain message
    carry no verdict, and downstream code tells the two apart by that key.

    `llm` says a model wrote this line, and is passed explicitly rather than
    inferred from `source`: the abort and no-answer paths return canned text
    too, so "a source was parsed" is not the same question. It rides all the
    way to the message so a reader can see which of the things a country said
    it had actually thought of.
    """
    source = source or {}
    reply = {}
    if accepted is not None:
        reply["accepted"] = accepted
    reply.update({
        "message": message,
        "llm": llm,
        "action": source.get("action", "NONE"),
        "action_target": source.get("action_target", "NONE"),
        "follow_up_action": source.get("follow_up_action", "NONE"),
        "follow_up_target": source.get("follow_up_target", "NONE"),
        "opinion_change": _to_int(source.get("opinion_change", 0)),
    })
    return reply


def llm_enabled_for(nation, world=None):
    """Whether this particular nation is model-driven, or None for "use the
    global rule".

    A per-country setting always wins, so a player can make the rival they care
    about model-driven without paying for the other forty. Otherwise ABSOLUTE
    means everyone and MAJOR means the countries a player actually notices --
    which is the mode worth recommending: great-power diplomacy at a fraction of
    ABSOLUTE's cost.
    """
    if not nation:
        return None

    nation_data = getattr(world, "nation_data", None) or {}
    tier = (nation_data.get(nation) or {}).get("llm_tier", c.AI_TIER_AUTO)
    if tier == c.AI_TIER_ALWAYS:
        return True
    if tier == c.AI_TIER_NEVER:
        return False

    immersion = ai_settings.get_ai_immersion_level()
    if immersion == "ABSOLUTE":
        return True
    if immersion == "MAJOR":
        return world is not None and nation in world.major_powers
    return None


def _use_canned_reply(mode, immersion, is_ai_to_ai, has_custom_msg=True,
                      nation=None, world=None):
    """Whether this exchange skips the LLM and answers from the canned table.

    One rule for all three entry points. Proactive text passes
    has_custom_msg=False because nobody wrote anything to reply to, which is
    what made its LITE branch look different from the other two.
    """
    if mode == "OFF":
        return True

    decided = llm_enabled_for(nation, world)
    if decided is not None:
        return not decided

    if immersion == "ABSOLUTE":
        return False
    if immersion == "FULL":
        return is_ai_to_ai
    # LITE (and any level an older build does not recognise): only a human's own
    # words are worth generating a reply to.
    return not (has_custom_msg and not is_ai_to_ai)


#: What the AI says when the LLM is not consulted for this exchange. Actions
#: not listed fall back to a plain accept/reject line.
LITE_RESPONSE_KEYS = {
    "WAR_DECLARATION": "BETRAYAL",
    "LEAVE_FACTION": "FACTION_ABANDONED",
    "DISBAND_FACTION": "FACTION_DISBANDED",
    "JOIN_WARS": "ACCEPTED_HELP",
    "BREAK_ALLIANCE": "ALLIANCE_BROKEN",
    "KICK_FACTION_MEMBER": "KICKED_FROM_FACTION",
    "CALL_TO_ARMS": "ANSWERED_CALL",
}


def canned_verdict_reply(nation_data, map_data, ai_nation, sender_nation, action_type,
                         custom_msg="", world=None, scenario_settings=None,
                         verdict=None):
    """The rules' own answer, in canned words. Never touches the model.

    Two callers, and until now they disagreed about something they had no
    business disagreeing about. This one -- the ordinary "the LLM is not
    consulted for this exchange" path -- has always answered with
    evaluate_verdict. The give-up paths did not: an aborted turn and an
    abandoned batch each returned a flat `accepted=True`, so a proposal that
    reached the model queue and did not come back was *agreed to* rather than
    judged.

    That is not a fallback, it is a different game. saves/oh my god germany
    italy wtf is one turn of it: six treaties every one of which the rules had
    refused -- Germany signing away Finnish provinces while holding a quarter of
    the Soviet Union, and five Axis members buying separate peaces that emptied
    the faction -- all executed because the turn ran out of model budget.

    Giving up on the prose was never a reason to give up on the decision. The
    decision is pure arithmetic and costs microseconds; only the sentence needs
    a provider. The proactive passes already knew this -- ai_diplomacy's
    director fallback is a bare `pass  # already holds the heuristic's own pick`
    -- and this is the same principle, for the half of the AI that answers.

    Pass `verdict` when the caller has already worked it out, so the ordinary
    path does not price every clause twice.
    """
    if verdict is None:
        verdict = evaluate_verdict(nation_data, map_data, ai_nation, sender_nation,
                                   action_type, custom_msg, world=world,
                                   scenario_settings=scenario_settings)

    key = LITE_RESPONSE_KEYS.get(action_type,
                                 "AI_OFF_ACCEPT" if verdict.accepted else "AI_OFF_REJECT")
    # Both parties are in hand here, so the line can suit the two of them --
    # a betrayal reads differently from the weaker side than the stronger.
    # This is the reply the player sees most: at anything below ABSOLUTE it
    # answers most of the world's diplomacy.
    return _reply(ai_prompts.resolve(key, sender=ai_nation, target=sender_nation,
                                     nation_data=nation_data, world=world,
                                     map_data=map_data),
                  accepted=verdict.accepted)


def get_world_context(nation_data, active_nations, ai_nation, target_nation=None, current_date="Unknown"):
    ai_stats = nation_data.get(ai_nation, {})
    manpower = ai_stats.get("manpower", 0)
    materials = ai_stats.get("materials", 0)

    # 2. Establish Global Politics (Now includes Factions!)
    #
    # Sorted and free of anything that depends on who is asking, so this block
    # comes out byte-identical for every nation in a turn's batch and a local
    # model can reuse its evaluation of it -- see build_world_context. The
    # relation scores, which are the part that varies, are gathered separately
    # and appended after it.
    politics_str = ""
    relations_str = ""
    for nation in sorted(active_nations):
        n_data = nation_data.get(nation, {})
        wars = [w for w in sorted(n_data.get("at_war_with", [])) if w in active_nations]
        fac = n_data.get("faction", "")
        master = n_data.get("master", "")
        puppets = [p for p in sorted(n_data.get("puppets", [])) if p in active_nations]

        rels = []
        if wars: rels.append(f"at war with {', '.join(wars)}")
        if fac: rels.append(f"in the faction '{fac}'")
        if master: rels.append(f"a puppet state of {master}")
        if puppets: rels.append(f"puppetmaster of {', '.join(puppets)}")
        if rels:
            politics_str += f"- {nation}: {' | '.join(rels)}.\n"

        # Only the opinions that are actually opinions. On the 1941 map 63% of
        # these come out exactly neutral, and eighty lines of "0" cost tokens
        # in the one part of the prompt that cannot be shared between nations,
        # while telling the model nothing it does not assume anyway.
        if nation != ai_nation:
            score = queries.get_relation_score(ai_nation, nation, nation_data)
            if score:
                relations_str += f"- {nation}: {score}\n"

    # 3. Add Recent World Events
    global_event_data = nation_data.get("GLOBAL_EVENTS", {})
    # Safely unpack the new dict format
    events = global_event_data.get("log", []) if isinstance(global_event_data, dict) else global_event_data

    events_str = ""
    if events:
        for ev in events[:8]: # Show the 8 most recent events
            events_str += f"- {ev}\n"

    # 4. Establish Target Context & Message History
    target_context_str = ""
    if target_nation:
        inbox = ai_stats.get("inbox", [])
        thread = []

        # Reverse to read chronologically (oldest to newest)
        for msg in reversed(inbox):
            sender_field = msg.get("sender", "")
            forwarded = diplomacy_messages.forwarded_details(msg)
            if sender_field == target_nation:
                speaker = target_nation
            elif sender_field == f"To: {target_nation}":
                speaker = "You"
            else:
                continue

            if forwarded:
                provenance = (
                    f"[AUTHENTIC FORWARDED MESSAGE: originally sent by "
                    f"{forwarded['original_sender']} to {forwarded['original_receiver']} "
                    f"on {forwarded['original_date']}; "
                    f"forwarded by {forwarded['forwarded_by']} on "
                    f"{forwarded['forwarded_at']}]"
                )
                thread.append(f"{speaker} {provenance}: '{msg.get('content')}'")
            else:
                thread.append(f"{speaker}: '{msg.get('content')}'")

        if thread:
            # Only give the last 10 messages so we don't blow up the context window
            recent_thread = thread[-10:]
            target_context_str = "\n".join(recent_thread) + "\n"

    return ai_prompts.build_world_context(
        current_date, ai_nation, ', '.join(sorted(active_nations)),
        manpower, materials, politics_str, events_str, target_context_str, target_nation,
        relations_str
    )


#: What the AI decided about an incoming proposal, and how firmly.
#:
#: `confidence` is 1.0 for every path today, which is what makes the extraction
#: of this block a pure refactor. Phase 3 fills it in -- a hard rule (an
#: integrated puppet cannot trade) stays at 1.0 while a marginal peace call
#: drops -- and Phase 4 uses it to decide whether the model is allowed to
#: overrule the recommendation. `reason` is the sentence shown to the model
#: alongside it.
Verdict = collections.namedtuple("Verdict", "accepted confidence reason")


def _confidence(slack):
    """How sure a verdict is, from how far past the line it landed.

    Same figure the player's verdict bar is bucketed from, so the model, the
    engine and the screen are all reading one number. Floored, because even a
    verdict decided by a hair is a verdict.
    """
    return max(0.15, min(1.0, abs(slack) * 2.5))


def _peace_terms(nation_data, sender_nation, ai_nation, custom_msg):
    """The deal being offered, whatever shape it was stored in.

    This used to return a *string* and hand it to will_ai_accept_peace, which
    worked only while the terms and the message were the same text. Anything
    that attached prose to a peace proposal -- a script, or the AI's own
    proactive offers, which never set parameters at all -- made every
    startswith() check silently false, and the offer was then accepted by
    accepts_peace's catch-all. The proposal's own parameters win where they
    exist; the message is the fallback, and coerce reads free prose as the white
    peace such an offer always executed as anyway.
    """
    from map_logic.diplomacy import deal as deal_mod

    pending = nation_data.get(sender_nation, {}).get("pending_diplomacy", {}).get(ai_nation, {})
    params = pending.get("parameters") if isinstance(pending, dict) else None

    if deal_mod.is_deal(params):
        return params
    if isinstance(params, dict):
        declared = params.get("peace_type") or params.get("terms")
        if declared:
            params = str(declared)
        else:
            params = custom_msg or ""
    elif not params:
        params = custom_msg or ""

    return deal_mod.coerce(params, sender_nation, ai_nation, kind=deal_mod.KIND_PEACE)


def evaluate_verdict(nation_data, map_data, ai_nation, sender_nation, action_type,
                     custom_msg="", world=None, scenario_settings=None):
    """Whether the AI accepts a proposal, decided without consulting the model.

    Lifted out of evaluate_diplomatic_proposal unchanged. It was worth its own
    function regardless -- it is the actual diplomatic brain and had no test
    coverage at all -- but the specific reason to move it now is that Phase 4
    lets the LLM overrule it. Doing both at once would mean changing behaviour
    and restructuring untested code in the same step, so this lands first with
    tests/test_ai_verdict.py pinning every branch, and the override arrives on
    top of a known-good baseline.

    Two quirks preserved deliberately, both addressed in Phase 3 rather than
    here: the relation lookup omits id_to_province and so skips the claim
    penalty, and `custom_msg` doubles as the peace terms string.
    """
    ai_stats = nation_data.get(ai_nation, {})
    at_war = len(ai_stats.get("at_war_with", [])) > 0
    in_faction = bool(ai_stats.get("faction", ""))

    accepted = False

    # Volunteers are an unconditional gift of troops from a peaceful country.
    # The offer has already passed the legality checks, so AI recipients always
    # accept it rather than spending a model response on a no-downside choice.
    if action_type == "SEND_VOLUNTEERS":
        return Verdict(True, 1.0, "volunteer divisions are always welcome")

    # --- IMPROVED FACTION LOGIC ---
    # 1. Check for basic aggressive acceptance
    if at_war and not in_faction:
        if action_type in ["FACTION_INVITE", "CREATE_FACTION"]:
            if not queries.are_at_war(ai_nation, sender_nation, nation_data):
                accepted = True

    # Accept calls to arms and requests to join wars if in the same faction
    if action_type in ["JOIN_WARS", "CALL_TO_ARMS"]:
        if queries.are_in_same_faction(ai_nation, sender_nation, nation_data):
            accepted = True
        elif ai_commitments.joint_war_target(nation_data, ai_nation, sender_nation):
            # We promised to fight this war with them. Honouring it is the whole
            # point of having agreed; refusing is a betrayal and priced as one.
            return Verdict(True, 1.0, "we gave our word to fight this war alongside them")

    # Accept Military Access requests from nations fighting the same enemies as us,
    # even across faction lines, so co-belligerents can cross each other's territory.
    if action_type == "REQ_MILITARY_ACCESS":
        ai_enemies = set(ai_stats.get("at_war_with", []))
        sender_enemies = set(queries.get_enemies(sender_nation, nation_data))
        accepted = bool(ai_enemies & sender_enemies) or bool(
            ai_commitments.active_with(nation_data, ai_nation, sender_nation,
                                       ai_commitments.MILITARY_ACCESS))

    # NEW: AI Master-Puppet Faction Acceptance
    my_master = ai_stats.get("master", "")
    if my_master == sender_nation and action_type in ["FACTION_INVITE", "CREATE_FACTION", "JOIN_FACTION_REQ"]:
        accepted = True

    # A puppet does not choose its own alignment, either way round: it cannot
    # accept an invitation, and there is no point letting one in, since it holds
    # whatever its master holds. Structural, so nothing may overrule it.
    # CREATE_FACTION is exempt -- finalize_create_faction redirects to the
    # master, so founding one is the overlord's act, not the subject's.
    if action_type in ["FACTION_INVITE", "JOIN_FACTION_REQ"] and my_master != sender_nation:
        if not (queries.can_choose_own_faction(ai_nation, nation_data)
                and queries.can_choose_own_faction(sender_nation, nation_data)):
            return Verdict(False, 1.0,
                           "a subject state does not choose its own alliances")

    # 2. Check for Join Faction Requests (If we are the leader)
    if action_type == "JOIN_FACTION_REQ" and ai_stats.get("is_faction_leader", False):
        relation_score = queries.get_relation_score(ai_nation, sender_nation, nation_data)

        # Calculate shared enemies
        ai_enemies = set(ai_stats.get("at_war_with", []))
        sender_enemies = set(queries.get_enemies(sender_nation, nation_data))
        share_enemies = bool(ai_enemies.intersection(sender_enemies))

        # Accept if relations are good OR they are helping us fight common
        # threats -- but never from somebody we are fighting ourselves. Two
        # nations at war can easily share a third enemy, and share_enemies alone
        # let that auto-accept an applicant whose war with us settle_with_faction
        # would then white-peace on the way in. The FACTION_INVITE branch above
        # has asked this since it was written.
        if queries.are_at_war(ai_nation, sender_nation, nation_data):
            accepted = False
        elif relation_score >= c.AI_RELATION_FACTION_THRESHOLD or share_enemies:
            accepted = True

    # 3. Evaluate peace deals dynamically using the centralized query
    if action_type in ["PEACE_TREATY", "CEASEFIRE"]:
        # A puppet cannot settle its own wars, and there is no point agreeing
        # terms with one that cannot honour them. Structural, so no judgement
        # call and nothing to overrule.
        if not (queries.can_negotiate_peace(ai_nation, sender_nation, nation_data)
                and queries.can_negotiate_peace(sender_nation, ai_nation, nation_data)):
            return Verdict(False, 1.0, "a subject state cannot settle a war on its own authority")

        # One brain, always. The no-world path used to fall through to
        # queries.will_ai_accept_peace, which refused any demand for claims
        # outright -- so what the peace screen predicted and what the engine
        # actually decided could and did disagree in front of the player.
        if world is None:
            world = ai_world.AIWorld(map_data, nation_data,
                                     {prov["id"]: prov for prov in map_data.values()})

        terms = _peace_terms(nation_data, sender_nation, ai_nation, custom_msg)
        # One number decides and explains, so the sentence under the player's
        # verdict bar and the answer the engine gives cannot drift apart. The
        # confidence used to be derived from peace_appetite alone -- a quantity
        # that is only one of four the decision rests on -- so a treaty refused
        # on its terms could still be reported as a close call.
        peace = ai_opinion.peace_verdict(world, ai_nation, sender_nation, terms,
                                         scenario_settings)
        return Verdict(peace.accepted, _confidence(peace.slack), peace.reason)

    # --- NEW AI TRADE LOGIC ---
    elif action_type == "TRADE":
        from map_logic.diplomacy import deal as deal_mod

        pending = nation_data.get(sender_nation, {}).get("pending_diplomacy", {}).get(ai_nation, {})
        params = pending.get("parameters", {})

        # Read the terms as a deal, whatever shape they arrived in.
        #
        # This branch used to reach straight for params["give_materials"] and
        # friends. A trade the player builds has been a deal -- {"clauses": [...]}
        # -- since the deal screen replaced the four number boxes, so all four
        # of those lookups returned 0, every player-built trade netted out to
        # exactly nothing, and the AI refused it with "we give up more than we
        # gain" whatever was in it. The AI's own offers still use the flat keys,
        # which is why nobody noticed: half the traffic worked.
        agreement = deal_mod.coerce(params, sender_nation, ai_nation,
                                    kind=deal_mod.KIND_TRADE)
        # We are the AI: we take what they give, and give what they take.
        receive, give = deal_mod.resource_flows(agreement, ai_nation)

        # An integrated puppet used to be barred from trading with anyone but
        # its master; that restriction is gone and subjects trade like anyone
        # else. A clause that would hand a nation over is still not something
        # the receiving side can be talked into -- a structural impossibility,
        # not a judgement call, so nothing may overrule it.
        if deal_mod.vassalizes(agreement, ai_nation):
            return Verdict(False, 1.0, "the terms are not ours to agree to")

        if world is not None:
            # Priced against our own scarcity and shaded by how much we like
            # them, replacing "accept only if we give literally nothing" -- which
            # is why no AI ever agreed to a deal a player would call fair.
            trade = ai_opinion.trade_verdict(world, ai_nation, sender_nation,
                                             agreement, scenario_settings)
            return Verdict(trade.accepted, _confidence(trade.slack), trade.reason)

        accepted = not any(give.values()) and any(receive.values())
    # ------------------------------

    return Verdict(accepted, 1.0, "")


def evaluate_diplomatic_proposal(nation_data, map_data, active_nations, ai_nation, sender_nation, action_type, custom_msg="", human_players=None, turn_id=None, world=None, scenario_settings=None, note=""):
    from map_logic.ai import ai_handler

    if ai_handler._aborted(turn_id):
        # Force Skip, or the turn moved on while this was queued. Either way the
        # model is out of reach and the rules are not -- see canned_verdict_reply.
        return canned_verdict_reply(nation_data, map_data, ai_nation, sender_nation,
                                    action_type, custom_msg, world=world,
                                    scenario_settings=scenario_settings)

    if human_players is None:
        human_players = []

    mode = ai_settings.get_ai_mode()
    immersion = ai_settings.get_ai_immersion_level()

    verdict = evaluate_verdict(nation_data, map_data, ai_nation, sender_nation,
                               action_type, custom_msg, world=world,
                               scenario_settings=scenario_settings)
    accepted = verdict.accepted

    # Check if this is an AI talking to an AI
    is_ai_to_ai = (ai_nation not in human_players) and (sender_nation not in human_players)

    # A note the other side actually wrote is a reason to answer in kind rather
    # than reach for a canned line -- more so than the generated terms are.
    if _use_canned_reply(mode, immersion, is_ai_to_ai,
                         bool(custom_msg.strip()) or bool(note.strip()),
                         nation=ai_nation, world=world):
        return canned_verdict_reply(nation_data, map_data, ai_nation, sender_nation,
                                    action_type, custom_msg, world=world,
                                    scenario_settings=scenario_settings,
                                    verdict=verdict)

    print(f"[LLM CALL] {ai_nation} answering {action_type} from {sender_nation}... (Mode: {mode})")

    context = get_world_context(nation_data, active_nations, ai_nation, sender_nation)

    # A marginal judgement is exactly where a leader's own view should be allowed
    # to differ from the staff's. A hard rule -- an integrated puppet cannot
    # trade, we are already in a faction -- is not a judgement, and stays settled.
    allow_override = verdict.confidence < c.AI_VERDICT_OVERRIDE_MAX_CONFIDENCE

    # --- Split logic between Proposals and Unilateral Declarations ---
    if action_type in c.UNILATERAL_ACTIONS:
        action_context = ai_prompts.get_unilateral_receive_context(action_type, sender_nation, custom_msg)
        system_prompt = ai_prompts.get_unilateral_system_prompt(action_context)
        user_prompt = f"{context}\n{action_context} Provide your reaction."
        allow_override = False
    else:
        action_context = ai_prompts.get_bilateral_receive_context(
            action_type, sender_nation, custom_msg, note)
        system_prompt = ai_prompts.get_bilateral_system_prompt(
            accepted, allow_override, verdict.reason, verdict.confidence)
        user_prompt = f"{context}\n{action_context} Provide your response."

    reply = ai_handler._run_provider(mode, system_prompt, user_prompt, turn_id,
                                     ai_prompts.AI_FALLBACK_RESPONSES["GENERIC_ACCEPT"], accepted,
                                     raw=True)
    if reply is None:
        return _reply(ai_prompts.AI_FALLBACK_RESPONSES["GENERIC_ACCEPT"], accepted=accepted)

    if allow_override and isinstance(reply.get("accepted"), bool):
        accepted = reply["accepted"]

    return _reply(reply.get("message", f"{mode} ERROR: reply had no 'message' field"),
                  reply, accepted, llm=bool(reply.get("message")))

def process_custom_message(nation_data, active_nations, ai_nation, sender_nation, message_content, human_players=None, turn_id=None):
    from map_logic.ai import ai_handler

    if ai_handler._aborted(turn_id):
        return _reply(ai_prompts.AI_FALLBACK_RESPONSES["GENERIC_MESSAGE"])

    if human_players is None:
        human_players = []

    mode = ai_settings.get_ai_mode()
    immersion = ai_settings.get_ai_immersion_level()

    is_ai_to_ai = (ai_nation not in human_players) and (sender_nation not in human_players)
    if _use_canned_reply(mode, immersion, is_ai_to_ai):
        return _reply(ai_prompts.AI_FALLBACK_RESPONSES["AI_OFF_MESSAGE"])

    print(f"[LLM CALL] {ai_nation} is drafting a reply to {sender_nation}... (Mode: {mode})")

    context = get_world_context(nation_data, active_nations, ai_nation, sender_nation)
    system_prompt = ai_prompts.get_custom_message_system_prompt()
    user_prompt = f"{context}\nMessage from {sender_nation}: '{message_content}'"

    return ai_handler._run_provider(mode, system_prompt, user_prompt, turn_id,
                         ai_prompts.AI_FALLBACK_RESPONSES["GENERIC_MESSAGE"])

def generate_proactive_text(nation_data, active_nations, ai_nation, target_nation, action_context, human_players=None, turn_id=None):
    """Generates a quick one-liner for proactive hardcoded AI actions.

    Unlike the two above, this returns a bare string (or None to mean "use the
    caller's fallback"), because a proactive line has no verdict or follow-up
    action attached to it.
    """
    from map_logic.ai import ai_handler

    if ai_handler._aborted(turn_id): return None

    if human_players is None:
        human_players = []

    mode = ai_settings.get_ai_mode()
    immersion = ai_settings.get_ai_immersion_level()

    is_ai_to_ai = (ai_nation not in human_players) and (target_nation not in human_players)
    # No incoming message to react to, so LITE never generates here.
    if _use_canned_reply(mode, immersion, is_ai_to_ai, has_custom_msg=False):
        return None

    context = get_world_context(nation_data, active_nations, ai_nation, target_nation)
    system_prompt = ai_prompts.get_proactive_system_prompt(ai_nation, target_nation, action_context)
    user_prompt = f"{context}\nWrite the message."

    # This used to be its own copy of ai_handler's provider ladder, built its
    # own genai client, and reported provider failures as the message itself --
    # so a bad API key was delivered to the player as the text of a war
    # declaration. None means "no answer", and the caller uses its fallback line.
    result = ai_handler._run_provider(mode, system_prompt, user_prompt, turn_id, None, raw=True)
    if not result or result.get("error"):
        return None
    return result.get("message")
