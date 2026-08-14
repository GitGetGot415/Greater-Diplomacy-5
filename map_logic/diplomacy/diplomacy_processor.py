from map_logic.ai import ai_commitments, ai_evaluation, ai_llm_runner, ai_prompts
import data.constants as c
from data import queries

# Import from our newly created submodules
from map_logic.diplomacy.diplomacy_events import log_global_event
from map_logic.diplomacy import (
    faction_leadership, peace_scope, ratification, restrictions, treaty_effects, war_calls
)
from map_logic.diplomacy.diplomacy_messages import (
    get_pending_action, send_message, send_treaty_message, get_response, get_response_map,
    set_response, clear_response, RESPONSE_ACCEPT
)
from map_logic.diplomacy.diplomacy_agreements import (
    finalize_war, finalize_neutral, finalize_disband_faction, finalize_faction_join, finalize_faction_leave,
    join_faction_wars, finalize_faction_kick, finalize_annexation, finalize_release, finalize_take_puppets
)

def toggle_diplomacy_action(nation_data, player_name, target_name, action_type, custom_msg="", timer=0, parameters=None):
    """Queues (or cancels) an OUTGOING proposal aimed at target_name.

    Answers to their proposals are a separate channel entirely -- see
    toggle_diplomatic_response -- so the two can never overwrite each other.
    """
    pending = nation_data[player_name].setdefault("pending_diplomacy", {})
    current_action = get_pending_action(nation_data, player_name, target_name)

    if current_action == action_type:
        info = pending.get(target_name, {})
        if isinstance(info, dict) and info.get("turns", 0) > 0:
            return "Cannot undo! The diplomat has already crossed their borders."

        # Nothing is escrowed until an offer is actually sent, so a cancelled
        # draft normally has none -- but a save from before that change can.
        _refund_offer_escrow(nation_data, player_name, info)

        del pending[target_name]
        return f"Undo {action_type.replace('_', ' ').title()}"

    elif current_action is not None:
        # NEW: Allow upgrading a drafted text message into a formal diplomatic action
        info = pending.get(target_name, {})
        is_unilateral = current_action in c.UNILATERAL_ACTIONS

        if isinstance(info, dict) and info.get("action", "").startswith("MSG:") and info.get("turns", 0) == 0:
            if not custom_msg:
                # Inherit the text from the draft if the user didn't provide a new one
                custom_msg = info.get("action")[4:]
        elif is_unilateral and isinstance(info, dict) and info.get("turns", 0) > 0:
            pass # Safe to overwrite an executed unilateral action
        else:
            # Prevents declaring war while an alliance request is pending, etc.
            return "A diplomatic action is already pending with this nation!"

    # --- THE FIX: Prevent multiple faction requests ---
    faction_actions = ["CREATE_FACTION", "JOIN_FACTION_REQ"]
    if action_type in faction_actions:
        if nation_data[player_name].get("faction", ""):
            return "Cannot do this while already in a faction!"

        for other_target, info in pending.items():
            act = info.get("action", "") if isinstance(info, dict) else info
            if act in faction_actions and other_target != target_name:
                return "You already have a pending faction request!"
    # ------------------------------------------------

    pending[target_name] = {
        "action": action_type,
        "turns": 0,
        "timer": timer,
        "message": custom_msg
    }
    if parameters:
        pending[target_name]["parameters"] = parameters
    return "Message drafted. Will send at end of turn."

def toggle_diplomatic_response(nation_data, player_name, sender_name, verdict, action, custom_msg="", parameters=None):
    """Queues (or undoes) an answer to sender_name's incoming proposal.

    Lives in nation_data[player]["diplo_responses"], never in pending_diplomacy,
    so answering someone leaves any offer we have travelling towards them intact.
    Re-queuing the same verdict clears it, which is how the Undo buttons work.
    """
    existing = get_response(nation_data, player_name, sender_name)
    verb = "Accept" if verdict == RESPONSE_ACCEPT else "Reject"
    noun = "Acceptance" if verdict == RESPONSE_ACCEPT else "Rejection"
    action_label = action.replace('_', ' ').title()

    if existing.get("verdict") == verdict and existing.get("action") == action:
        # Undoing a rejection puts their offer back in play. Nothing to refund
        # here -- a trade's escrow belongs to the sender and was never touched.
        clear_response(nation_data, player_name, sender_name)
        return f"Undo {verb} {action_label}"

    extra = {"message": custom_msg}
    if parameters is not None:
        extra["parameters"] = parameters
    set_response(nation_data, player_name, sender_name, verdict, action, **extra)
    return f"{noun} queued: {action_label}"


# ============================================================================ #
#                    process_diplomacy_turn PHASE HELPERS                      #
# ============================================================================ #
# process_diplomacy_turn runs a fixed sequence of phases every turn (decay,
# clash resolution, gathering/running the LLM tasks, three resolution passes,
# then the claim/puppet-release queues). Each phase used to be an unbroken
# block of the one function; they're pulled out here, in the same order they
# run, so each can be read (and the diff for a future change to just one of
# them reviewed) on its own.

def _decay_modifiers_and_truces(map_screen):
    """Ages down temporary relation modifiers, truces, and war-duration counters."""
    for country_name, data in list(map_screen.nation_data.items()):
        if not isinstance(data, dict):
            continue

        temp_mods = data.get("temp_modifiers", {})
        for target, mods in temp_mods.items():
            for mod_name in list(mods.keys()):
                entry = mods[mod_name]
                value = queries.modifier_value(entry)
                decay = queries.modifier_decay(entry)
                turns = queries.modifier_turns(entry)

                # Fade toward zero by `decay` a turn. A decay of 0 is a grudge
                # that does not soften on its own -- it ends when its `turns`
                # run out, or never.
                if value > 0:
                    value = max(0, value - decay)
                elif value < 0:
                    value = min(0, value + decay)

                if turns is not None:
                    turns -= 1

                if value == 0 or (turns is not None and turns <= 0):
                    del mods[mod_name]
                elif isinstance(entry, dict):
                    entry["value"] = value
                    entry["turns"] = turns
                else:
                    mods[mod_name] = value

        # --- AGE TREATY RESTRICTIONS (demilitarization) ---
        restrictions.tick(data)

        # --- DECAY TRUCES ---
        truces = data.get("truces", {})
        for target in list(truces.keys()):
            if truces[target] > 0:
                truces[target] -= 1
            if truces[target] <= 0:
                del truces[target]

        # --- INCREMENT WAR DURATIONS ---
        war_durs = data.setdefault("war_durations", {})

        # 1. Safely increment durations for all currently active wars
        for enemy in data.get("at_war_with", []):
            war_durs[enemy] = war_durs.get(enemy, 0) + 1

        # 2. Clean up stale tracking data for ended wars
        for enemy in list(war_durs.keys()):
            if enemy not in data.get("at_war_with", []):
                del war_durs[enemy]


def _follow_up_is_legal(map_screen, sender, target, action_type):
    """Whether a queued follow-up still makes sense by the time it fires.

    These come from a model's `follow_up_action` and were injected straight into
    pending_diplomacy with no checks of any kind -- no war state, no faction, no
    truce -- while the immediate action beside them went through a whole
    guardrail block. A peace offer is the one that shows: a follow-up CEASEFIRE
    could land on a nation the sender had never fought.
    """
    if action_type in ("CEASEFIRE", "PEACE_TREATY"):
        return (queries.are_at_war(sender, target, map_screen.nation_data)
                and bool(peace_scope.negotiation_role(sender, target, map_screen.nation_data)))
    if action_type == "WAR_DECLARATION":
        return not (queries.are_in_same_faction(sender, target, map_screen.nation_data)
                    or queries.has_active_truce(sender, target, map_screen.nation_data))
    if action_type in ("JOIN_WARS", "CALL_TO_ARMS"):
        return queries.are_in_same_faction(sender, target, map_screen.nation_data)
    return True


def _flush_queued_ai_actions(map_screen):
    """Turns each nation's queued_ai_actions (from a follow-up action or a
    multi-turn AI plan) into a fresh pending_diplomacy entry for this turn."""
    for country_name, data in map_screen.nation_data.items():
        if isinstance(data, dict) and "queued_ai_actions" in data and data["queued_ai_actions"]:
            pending = data.setdefault("pending_diplomacy", {})
            for q_action in data["queued_ai_actions"]:
                target = q_action["target"]
                action_type = q_action["action"]

                # Ensure self-targeting actions target the AI itself!
                # FIX: Removed CREATE_FACTION so it properly targets the intended partner
                if action_type in ["LEAVE_FACTION", "DISBAND_FACTION"]:
                    target = country_name

                if not _follow_up_is_legal(map_screen, country_name, target, action_type):
                    print(f"[AI GUARDRAIL] Dropping follow-up {action_type} from {country_name} to {target}.")
                    continue

                # Inject it as a fresh action for this turn, bypassing the LLM
                if target not in pending or (isinstance(pending[target], dict) and pending[target].get("turns", 0) == 0):
                    if action_type == "JOIN_FACTION_REQ":
                        msg = "We formally request to join your faction."
                    elif action_type == "CREATE_FACTION":
                        msg = "We propose establishing a new faction together."
                    else:
                        msg = ai_prompts.AI_FALLBACK_RESPONSES.get("FOLLOW_UP_DECLARATION", "")

                    pending[target] = {"action": action_type, "turns": 0, "timer": 0, "message": msg}
            data["queued_ai_actions"] = []


#: Proposals that a simultaneous declaration of war makes moot.
_WAR_CANCELS = ["FACTION_INVITE", "CEASEFIRE", "JOIN_FACTION_REQ", "PEACE_TREATY", "CREATE_FACTION"]


def _resolve_cross_action(map_screen, nation_a, nation_b, a_data, b_data, msg_key):
    """Helper to cleanly resolve contradictory simultaneous requests and strip them from the queue."""
    msg = ai_prompts.AI_FALLBACK_RESPONSES[msg_key]
    send_message(map_screen, nation_a, nation_b, msg, "DIPLOMACY")
    send_message(map_screen, nation_b, nation_a, msg, "DIPLOMACY")
    if a_data and nation_b in a_data: del a_data[nation_b]
    if b_data and nation_a in b_data: del b_data[nation_a]


def _war_cancels_response(map_screen, declarer, victim):
    """A declaration of war voids any answer the victim had queued for the declarer."""
    resp = get_response(map_screen.nation_data, victim, declarer)
    if not resp or resp.get("action") not in _WAR_CANCELS:
        return
    action_name = resp.get("action", "").split('_')[0].lower()
    msg = ai_prompts.AI_FALLBACK_RESPONSES["CROSS_WAR_DECLARATION"].format(action=action_name)
    send_message(map_screen, declarer, victim, msg, "DIPLOMACY")
    clear_response(map_screen.nation_data, victim, declarer)


def _resolve_simultaneous_clashes(map_screen):
    """Settles every pair of nations that queued contradictory actions against
    each other this turn (e.g. both requesting to join each other's faction,
    or one declaring war while the other proposed something a war voids)."""
    nations = list(map_screen.nation_data.keys())

    for i in range(len(nations)):
        for j in range(i + 1, len(nations)):
            nation_a = nations[i]
            nation_b = nations[j]

            a_data = map_screen.nation_data[nation_a].get("pending_diplomacy", {})
            b_data = map_screen.nation_data[nation_b].get("pending_diplomacy", {})

            a_info = a_data.get(nation_b)
            b_info = b_data.get(nation_a)

            # A declaration of war also voids whatever answer the other side had
            # queued for us. Responses live outside pending_diplomacy now, so they
            # need checking even when only one side has a pending action.
            if isinstance(a_info, dict) and a_info.get("turns", 0) == 0 and a_info.get("action") == "WAR_DECLARATION":
                _war_cancels_response(map_screen, nation_a, nation_b)
            if isinstance(b_info, dict) and b_info.get("turns", 0) == 0 and b_info.get("action") == "WAR_DECLARATION":
                _war_cancels_response(map_screen, nation_b, nation_a)

            if isinstance(a_info, dict) and a_info.get("turns", 0) == 0 and \
               isinstance(b_info, dict) and b_info.get("turns", 0) == 0:

                a_action = a_info.get("action")
                b_action = b_info.get("action")

                if a_action == "JOIN_FACTION_REQ" and b_action == "FACTION_INVITE":
                    if finalize_faction_join(map_screen.map_data, map_screen.nation_data, nation_b, nation_a):
                        log_global_event(map_screen.nation_data, f"{nation_a} and {nation_b} have united their factions!")
                    _resolve_cross_action(map_screen, nation_a, nation_b, a_data, b_data, "CROSS_FACTION_JOIN")

                elif b_action == "JOIN_FACTION_REQ" and a_action == "FACTION_INVITE":
                    if finalize_faction_join(map_screen.map_data, map_screen.nation_data, nation_a, nation_b):
                        log_global_event(map_screen.nation_data, f"{nation_a} and {nation_b} have united their factions!")
                    _resolve_cross_action(map_screen, nation_a, nation_b, a_data, b_data, "CROSS_FACTION_JOIN")

                elif a_action == "WAR_DECLARATION" and b_action in _WAR_CANCELS:
                    action_name = b_action.split('_')[0].lower()
                    msg = ai_prompts.AI_FALLBACK_RESPONSES["CROSS_WAR_DECLARATION"].format(action=action_name)
                    send_message(map_screen, nation_a, nation_b, msg, "DIPLOMACY")
                    del b_data[nation_a]

                elif b_action == "WAR_DECLARATION" and a_action in _WAR_CANCELS:
                    action_name = a_action.split('_')[0].lower()
                    msg = ai_prompts.AI_FALLBACK_RESPONSES["CROSS_WAR_DECLARATION"].format(action=action_name)
                    send_message(map_screen, nation_b, nation_a, msg, "DIPLOMACY")
                    del a_data[nation_b]

                elif a_action == "CEASEFIRE" and b_action == "CEASEFIRE":
                    finalize_neutral(map_screen.nation_data, nation_a, nation_b)
                    log_global_event(map_screen.nation_data, f"{nation_a} and {nation_b} have signed a mutual ceasefire.")
                    _resolve_cross_action(map_screen, nation_a, nation_b, a_data, b_data, "CROSS_CEASEFIRE")

                elif (a_action == "CALL_TO_ARMS" and b_action == "JOIN_WARS") or \
                     (a_action == "JOIN_WARS" and b_action == "CALL_TO_ARMS"):

                    join_faction_wars(map_screen.map_data, map_screen.nation_data, nation_a, nation_b)
                    join_faction_wars(map_screen.map_data, map_screen.nation_data, nation_b, nation_a)
                    log_global_event(map_screen.nation_data, f"ESCALATION: {nation_a} and {nation_b} have formally combined their war efforts!")
                    _resolve_cross_action(map_screen, nation_a, nation_b, a_data, b_data, "CROSS_CALL_TO_ARMS")


def _gather_ai_tasks(map_screen):
    """Collects every pending action (turn 1, not aimed at a human) that needs
    an AI reply this turn, as a flat list the LLM batch runner can chew through."""
    ai_tasks = []
    for country_name, data in list(map_screen.nation_data.items()):
        if not isinstance(data, dict):
            continue

        pending = data.get("pending_diplomacy", {})
        for target, info in pending.items():
            if isinstance(info, str):
                info = {"action": info, "turns": 1, "timer": 0}
                pending[target] = info

            action = info.get("action", "")
            turns = info.get("turns", 0)
            custom_msg = info.get("message", "")

            # EVERY ACTION NOW EVALUATES ON TURN 1
            if turns == 1:
                is_human_target = target in map_screen.active_players
                if not is_human_target:
                    if action in c.UNILATERAL_ACTIONS or action in c.BILATERAL_ACTIONS:
                        # `content` is what the offer *is*; `note` is what its
                        # sender said about it. Kept apart so neither can be
                        # read as the other -- see get_bilateral_receive_context.
                        ai_tasks.append({"sender": country_name, "target": target,
                                         "action": action, "content": custom_msg,
                                         "note": info.get("note", "")})
                    elif action.startswith("MSG:"):
                        ai_tasks.append({"sender": country_name, "target": target, "action": "CUSTOM_MSG", "content": action[4:]})

                # Special self-targeting actions for Factions
                if action in ["LEAVE_FACTION", "DISBAND_FACTION"]:
                    fac = map_screen.nation_data[country_name].get("faction", "")
                    members = queries.get_faction_members(fac, map_screen.nation_data) if fac else []
                    info["cached_members"] = members
                    for m in members:
                        if m != country_name and m not in map_screen.active_players:
                            ai_tasks.append({"sender": country_name, "target": m, "action": action})

    return ai_tasks


def _get_fallback_ai_result(task, nation_data=None, world=None, map_data=None):
    """Unified helper to gracefully fail into standard canned responses if the LLM skips or is offline."""
    action = task["action"]
    if action == "CUSTOM_MSG":
        key, default = "AI_OFF_MESSAGE", "Message received."
    elif action in c.UNILATERAL_ACTIONS:
        fallback_map = {
            "WAR_DECLARATION": "BETRAYAL", "LEAVE_FACTION": "FACTION_ABANDONED",
            "DISBAND_FACTION": "FACTION_DISBANDED", "JOIN_WARS": "ACCEPTED_HELP",
            "BREAK_ALLIANCE": "ALLIANCE_BROKEN", "KICK_FACTION_MEMBER": "KICKED_FROM_FACTION"
        }
        key, default = fallback_map.get(action, "GENERIC_MESSAGE"), "Message received."
    else:
        key, default = "AI_OFF_ACCEPT", "We accept your proposal."

    # The task names both parties, so a declaration of war can read as the
    # weaker or the stronger side declaring it rather than one flat sentence.
    msg = ai_prompts.resolve(key, sender=task.get("sender"), target=task.get("target"),
                             nation_data=nation_data, world=world, map_data=map_data,
                             default=default)

    return {
        "accepted": True, "message": msg, "action": "NONE", "action_target": "NONE",
        "follow_up_action": "NONE", "follow_up_target": "NONE", "opinion_change": 0
    }


def _execute_ai_tasks(map_screen, ai_tasks, active_nations_list):
    """Runs every gathered AI task through the LLM batch runner (or straight to
    its canned fallback) and returns the {(sender, target, action): reply} map
    Passes 1/2 read back from."""
    ai_results = {}

    if not ai_tasks:
        map_screen.responsive_tasks_total = 0
        map_screen.responsive_tasks_completed = 0
        return ai_results

    from map_logic.ai import ai_handler # Import this to safely check the mode

    human_players = map_screen.active_players

    mode = ai_handler.get_ai_mode()
    immersion = ai_handler.get_ai_immersion_level()

    map_screen.responsive_tasks_completed = 0
    my_turn_id = ai_handler.CURRENT_TURN_ID

    # Diplomacy resolves after the AI phases have torn down their snapshot, so
    # this pass builds its own. Verdicts read relations, war odds and prices off
    # it; without one they fall back to the old threshold rules.
    from map_logic.ai import ai_world
    verdict_world = ai_world.for_screen(map_screen)
    scenario_settings = getattr(map_screen, "scenario_settings", None)

    def call(task):
        if task["action"] == "CUSTOM_MSG":
            return ai_handler.process_custom_message(
                map_screen.nation_data, active_nations_list, task["target"], task["sender"],
                task["content"], human_players, my_turn_id)
        return ai_handler.evaluate_diplomatic_proposal(
            map_screen.nation_data, map_screen.map_data, active_nations_list, task["target"],
            task["sender"], task["action"], task.get("content", ""),
            human_players, my_turn_id, world=verdict_world,
            scenario_settings=scenario_settings, note=task.get("note", ""))

    def key_of(task):
        return (task["sender"], task["target"], task["action"])

    def record(task, result):
        ai_results[key_of(task)] = result

    def record_fallback(task):
        ai_results[key_of(task)] = _get_fallback_ai_result(
            task, map_screen.nation_data, verdict_world, map_screen.map_data)

    # One tick per task the model was actually asked about.
    #
    # This used to restate the immersion rules to decide which tasks the bar had
    # been sized for -- a fourth copy of them, and it had drifted: there was no
    # MAJOR branch at all, so the whole phase ran with the bar reading 0/0 at the
    # level the game recommends. The queue below is now the same list the bar is
    # sized from, so there is nothing left to keep in step.
    count = ai_llm_runner.make_progress_counter(
        map_screen, "Processing Global Responses",
        "responsive_tasks_completed", "responsive_tasks_total")

    # Filtered once, up front. The three paths used to disagree about an
    # action that is neither a known proposal nor a custom message: two
    # skipped it, the Force Skip path gave it a canned acceptance.
    answerable = [t for t in ai_tasks
                  if t["action"] in c.UNILATERAL_ACTIONS
                  or t["action"] in c.BILATERAL_ACTIONS
                  or t["action"] == "CUSTOM_MSG"]

    # The player's own correspondence goes to the front. This batch is the whole
    # map's diplomacy -- 192 proposals on the 1941 scenario -- and it runs in the
    # order pending_diplomacy happens to be in, so when the budget ran out it was
    # arbitrary who got a real verdict. A human waiting on an answer to something
    # they sent should never be the one who gets a fallback because forty AI
    # trade offers happened to sort ahead of them.
    def _player_first(task):
        return 0 if (task["sender"] in human_players
                     or task["target"] in human_players) else 1

    answerable.sort(key=_player_first)

    # Only the ones that will actually ask the model are put under the model's
    # budget. At MAJOR immersion 177 of those 192 proposals are answered from
    # the rules in microseconds without a network call anywhere -- and they were
    # being abandoned by a deadline that exists to bound *model* time, so a slow
    # local llama3 answering twelve nations left a hundred and eighty proposals
    # resolved by a fallback verdict instead of the evaluation they were owed.
    #
    # This only decides which queue a task joins. Both queues run the same
    # `call`, which asks _use_canned_reply again for itself, so a task sorted
    # into the wrong one still gets exactly the answer it would have got.
    def _needs_model(task):
        is_ai_to_ai = (task["sender"] not in human_players
                       and task["target"] not in human_players)
        wrote_something = bool(task.get("content", "").strip()
                               or task.get("note", "").strip())
        return not ai_evaluation._use_canned_reply(
            mode, immersion, is_ai_to_ai, wrote_something,
            task["target"], verdict_world)

    asking = [t for t in answerable if _needs_model(t)]

    # Sized from the queue itself, so the bar counts the work the player is
    # actually waiting on rather than a separately-maintained guess at it.
    map_screen.responsive_tasks_total = len(asking)
    map_screen.loading_status_text = f"Processing Global Responses (0/{len(asking)})..."

    for task in [t for t in answerable if not _needs_model(t)]:
        record(task, call(task))

    outcome = ai_llm_runner.run_llm_batch(
        asking, call, record, record_fallback,
        on_progress=count,
        should_abort=lambda: map_screen.force_skip_llm,
        max_workers=queries.get_ai_threads(),
        deadline=ai_llm_runner.turn_deadline(map_screen, c.AI_BUDGET_SHARE_RESPONSES))
    ai_llm_runner.report_unserved(map_screen, outcome, "Answering proposals")

    return ai_results


def _process_ai_retaliation(map_screen, active_nations_list, delayed_responses, country_name, reply_dict, default_target=None):
    """Processes reactive diplomatic actions appended by the LLM.

    New proposals it decides to send land in `delayed_responses` for
    _apply_delayed_responses to queue onto next turn, since a reply generated
    while resolving this turn can't also inject a fresh pending action into a
    dict Pass 2 is still iterating.
    """
    ai_action = reply_dict.get("action", "NONE")
    follow_up = reply_dict.get("follow_up_action", "NONE")
    raw_act_target = reply_dict.get("action_target", "NONE")
    raw_f_up_target = reply_dict.get("follow_up_target", "NONE")

    def worded(fallback_key, default):
        """The leader's own line for the move it just decided to make.

        Every branch below had the reply in hand as reply_dict["message"] and
        threw it away for a hardcoded constant, so a nation the model had just
        driven into a ceasefire announced it in the same words as one running
        off the canned table. A war declaration is the exception: its message
        field carries the wargoal rather than prose, which is the same exception
        PROACTIVE_PROPOSALS.queued_message already makes.
        """
        own_words = (reply_dict.get("message") or "").strip()
        if own_words and not ai_prompts.reads_as_third_person(
                own_words, country_name, map_screen.nation_data):
            return own_words
        return ai_prompts.AI_FALLBACK_RESPONSES.get(fallback_key, default)

    def get_valid_target(raw_target):
        if not raw_target or raw_target == "NONE": return default_target if default_target else "NONE"
        clean_target = raw_target.strip().lower()
        for n in active_nations_list:
            if n.lower() == clean_target: return n
            if map_screen.nation_data.get(n, {}).get("name", "").lower() == clean_target: return n
        return default_target if default_target else "NONE"

    act_target = get_valid_target(raw_act_target)
    f_up_target = get_valid_target(raw_f_up_target)

    # Modify the original dictionary so calling functions know if the action was aborted
    if ai_action != "NONE" and act_target == "NONE":
        print(f"[AI GUARDRAIL] Aborting {ai_action}: Target '{raw_act_target}' not found.")
        ai_action = "NONE"
        reply_dict["action"] = "NONE"

    if follow_up != "NONE" and f_up_target == "NONE":
        print(f"[AI GUARDRAIL] Aborting follow-up {follow_up}: Target '{raw_f_up_target}' not found.")
        follow_up = "NONE"
        reply_dict["follow_up_action"] = "NONE"

    # Check cooldown and truces
    if ai_action != "NONE":
        if queries.is_ai_diplo_on_cooldown(country_name, act_target, ai_action, map_screen.nation_data):
            print(f"[AI GUARDRAIL] Aborting {ai_action}: Cooldown active.")
            ai_action = "NONE"
        elif ai_action == "WAR_DECLARATION" and queries.has_active_truce(country_name, act_target, map_screen.nation_data):
            print(f"[AI GUARDRAIL] Aborting {ai_action}: Truce active.")
            ai_action = "NONE"
        elif ai_action not in c.BILATERAL_ACTIONS:
            # Unilateral moves have no answer to wait for, so they still rate-limit
            # on the way out. Proposals are rate-limited when they get turned down.
            queries.set_ai_diplo_cooldown(country_name, act_target, ai_action, map_screen.nation_data)

    if ai_action == "WAR_DECLARATION":
        if not c.AI_LLM_DIRECT_RETALIATION:
            # Filed as a request rather than executed. Declaring here skipped
            # every prerequisite the proactive pass enforces -- the waiting
            # period at the start of a game, the requirement to share a border,
            # the need for a wargoal at all -- and went to war with WARGOAL_NO_CB
            # on a nation the AI might not even be able to reach. Next turn's
            # candidate generation drains this and puts it through the same
            # legality and desirability checks as everything else, so a demand
            # that survives is one the nation could legitimately have made.
            requests = map_screen.nation_data[country_name].setdefault("ai_requests", [])
            requests.append({
                "action": "WAR_DECLARATION", "target": act_target,
                "reason": reply_dict.get("message", "")[:c.AI_REQUEST_REASON_LENGTH],
                "turn": queries.get_total_turns(map_screen.time_manager),
            })
            log_global_event(
                map_screen.nation_data,
                f"RUMOR: Hawks in {country_name} are pressing for war with {act_target}.")
        elif queries.are_in_same_faction(country_name, act_target, map_screen.nation_data):
            if queries.is_faction_leader(country_name, map_screen.nation_data):
                delayed_responses.append((country_name, act_target, "KICK_FACTION_MEMBER", 0, "You are expelled from the faction."))
            else:
                delayed_responses.append((country_name, country_name, "LEAVE_FACTION", 0, ""))
            ai_queue = map_screen.nation_data[country_name].setdefault("queued_ai_actions", [])
            ai_queue.append({"target": act_target, "action": "WAR_DECLARATION"})
        else:
            delayed_responses.append((country_name, act_target, "WAR_DECLARATION", 0, c.WARGOAL_NO_CB))
    elif ai_action == "JOIN_WARS":
        if queries.are_in_same_faction(country_name, act_target, map_screen.nation_data):
            delayed_responses.append((country_name, act_target, "JOIN_WARS", 0, worded("PROACTIVE_JOIN_WAR", "We stand with you.")))
        elif war_calls.are_pledged(country_name, act_target, map_screen.nation_data):
            # A puppet is bound to its master without necessarily sharing its
            # faction, and offering to join the wars it is already being dragged
            # into is the one diplomatic move it has. It used to fall through to
            # the branch below and file a war declaration on every enemy of its
            # own overlord.
            delayed_responses.append((country_name, act_target, "JOIN_WARS", 0, worded("PROACTIVE_JOIN_WAR", "We stand with you.")))
        elif not c.AI_LLM_DIRECT_RETALIATION:
            # Asking to join a non-faction-mate's war used to silently expand
            # into a declaration on every one of that nation's enemies at once.
            # Filed as requests, one per enemy, each judged on its own merits.
            requests = map_screen.nation_data[country_name].setdefault("ai_requests", [])
            for enemy in queries.get_enemies(act_target, map_screen.nation_data):
                requests.append({
                    "action": "WAR_DECLARATION", "target": enemy,
                    "reason": f"to stand with {act_target}",
                    "turn": queries.get_total_turns(map_screen.time_manager),
                })
        else:
            target_enemies = queries.get_enemies(act_target, map_screen.nation_data)
            if target_enemies:
                for enemy in target_enemies:
                    if queries.has_active_truce(country_name, enemy, map_screen.nation_data): continue
                    delayed_responses.append((country_name, enemy, "WAR_DECLARATION", 0, ai_prompts.AI_FALLBACK_RESPONSES.get("PROACTIVE_DECLARE_WAR", "We have declared WAR upon you!")))
    elif ai_action == "LEAVE_FACTION":
        delayed_responses.append((country_name, country_name, "LEAVE_FACTION", 0, ""))
    elif ai_action == "JOIN_FACTION_REQ":
        if not map_screen.nation_data[country_name].get("faction", ""):
            delayed_responses.append((country_name, act_target, "JOIN_FACTION_REQ", 0, worded("PROACTIVE_JOIN_FACTION", "We formally request to join your faction.")))
    elif ai_action == "CEASEFIRE":
        # You cannot stop a war you are not fighting. This branch had none of
        # the checks its neighbours above have, and get_valid_target falls back
        # to `default_target` -- the nation whose message is being answered --
        # so a model reply of {"action": "CEASEFIRE", "target": "NONE"} to a
        # faction-mate's call to arms queued a ceasefire offer at that
        # faction-mate, in peacetime. Accepting it ran finalize_neutral, which
        # wrote a 12-turn truce, and join_faction_wars skips a truced pair --
        # so an ally silently opted out of the bloc's wars for twelve turns.
        if not queries.are_at_war(country_name, act_target, map_screen.nation_data):
            print(f"[AI GUARDRAIL] Aborting CEASEFIRE: {country_name} is not at war with {act_target}.")
        elif not peace_scope.negotiation_role(country_name, act_target, map_screen.nation_data):
            print(f"[AI GUARDRAIL] Aborting CEASEFIRE: {country_name} may not settle with {act_target}.")
        else:
            delayed_responses.append((country_name, act_target, "CEASEFIRE", 0, worded("PROACTIVE_CEASEFIRE", "We offer terms for a ceasefire.")))
    elif ai_action == "CALL_TO_ARMS":
        # The one branch in this chain that checked nothing at all. Its
        # neighbours test faction, war state and negotiating rights; this queued
        # whatever the model said, so a nation in no faction and at war with
        # nobody could call the player to arms, and a puppet could call its own
        # master into wars that were the master's to begin with.
        #
        # war_calls decides which of the pair the two nations' war lists
        # actually support. A puppet asking for aid it cannot need is a puppet
        # that meant "let us join you", so that is what it sends -- with the
        # wording that goes with it, rather than "we request your aid" arriving
        # from somebody offering theirs.
        honest = war_calls.intended_action(country_name, act_target, map_screen.nation_data)
        if honest == war_calls.CALL_TO_ARMS:
            delayed_responses.append((country_name, act_target, "CALL_TO_ARMS", 0, worded("PROACTIVE_CALL_TO_ARMS", "We request your aid!")))
        elif honest == war_calls.JOIN_WARS:
            print(f"[AI GUARDRAIL] Rewriting CALL_TO_ARMS from {country_name} as JOIN_WARS: "
                  f"{act_target} is the one at war.")
            delayed_responses.append((country_name, act_target, "JOIN_WARS", 0, worded("PROACTIVE_JOIN_WAR", "We stand with you.")))
        else:
            print(f"[AI GUARDRAIL] Aborting CALL_TO_ARMS: {country_name} has no war "
                  f"{act_target} could be called into.")
    elif ai_action == "CREATE_FACTION":
        delayed_responses.append((country_name, act_target, "CREATE_FACTION", 0, worded("PROACTIVE_CREATE_FACTION", "We propose establishing a new faction.")))
    elif ai_action == "KICK_FACTION_MEMBER":
        delayed_responses.append((country_name, act_target, "KICK_FACTION_MEMBER", 0, worded("KICKED_FROM_FACTION", "You are expelled.")))
    elif ai_action == "DISBAND_FACTION":
        delayed_responses.append((country_name, country_name, "DISBAND_FACTION", 0, ""))

    if follow_up and follow_up != "NONE":
        final_f_up_target = country_name if follow_up in ["LEAVE_FACTION", "DISBAND_FACTION"] else f_up_target
        ai_queue = map_screen.nation_data[country_name].setdefault("queued_ai_actions", [])
        ai_queue.append({"target": final_f_up_target, "action": follow_up})
        log_global_event(map_screen.nation_data, f"RUMOR: Internal shuffling suggests {country_name} is preparing further diplomatic moves regarding {f_up_target}...")


def _decline_cooldown(map_screen, sender, target, action):
    """Records that `target` said no, so the AI waits before asking again.

    Stamped when a proposal actually fails rather than when it is sent, so a
    nation keeps offering help every turn until it is genuinely turned down.
    """
    if action in c.BILATERAL_ACTIONS:
        queries.set_ai_diplo_cooldown(sender, target, action, map_screen.nation_data)


def _offer_kind(action):
    from map_logic.diplomacy import deal as deal_mod
    return deal_mod.KIND_PEACE if action in ("PEACE_TREATY", "CEASEFIRE") else deal_mod.KIND_TRADE


def _hold_offer_escrow(map_screen, sender, target, info):
    """Takes what an offer promises out of the sender's hands as it leaves.

    Held on the entry itself as `escrow`, so the refund knows what was actually
    taken rather than re-reading what was promised -- a nation that promised
    more than it had escrowed less, and refunding the promise would have minted
    the difference.

    This used to happen in the trade screen, which meant only the player ever
    paid: an AI's offer cost it nothing, an accepted AI trade created materials
    from thin air, and cancel_trade_escrow then handed the AI a refund for an
    offer it had never funded. Both sides go through here now.
    """
    from map_logic.diplomacy import deal as deal_mod
    from map_logic.diplomacy import deal_effects

    params = info.get("parameters")
    if not params:
        return
    agreement = deal_mod.coerce(params, sender, target, kind=_offer_kind(info.get("action")))
    held = deal_effects.hold_escrow(map_screen.nation_data, agreement, sender,
                                    deal_effects.economies_for(map_screen))
    if any(held.values()):
        info["escrow"] = held


def _refund_offer_escrow(nation_data, sender, info):
    """Gives back an offer's escrow. Safe to call on an offer that never held any."""
    from map_logic.diplomacy import deal_effects

    held = info.pop("escrow", None) if isinstance(info, dict) else None
    if held:
        deal_effects.release_escrow(nation_data, held, sender)


def _process_queued_responses(map_screen):
    """PASS 0.5: settles every queued answer to an incoming proposal (turns == 0).

    Runs ahead of Pass 1 so a deal we accepted is settled before our own fresh
    offers go out this turn. Each side's answer resolves on its own -- two
    nations answering each other never share a slot, so nothing is clobbered
    and one-way agreements (military access) stay one-way.
    """
    for country_name, data in list(map_screen.nation_data.items()):
        if not isinstance(data, dict):
            continue

        responses = get_response_map(map_screen.nation_data, country_name)
        for sender, resp in list(responses.items()):
            if not isinstance(resp, dict):
                del responses[sender]
                continue

            verdict = resp.get("verdict", "")
            orig_action = resp.get("action", "")
            custom_msg = resp.get("message", "")
            # True only while custom_msg is what actually goes out: a blocked
            # or canned outcome below replaces the text, and a replaced line
            # is not the model's however it was answered.
            wrote_it = bool(custom_msg) and bool(resp.get("llm"))
            answered = {"action": orig_action}

            # The terms being agreed to belong to whoever made the offer.
            their_request = map_screen.nation_data.get(sender, {}).get("pending_diplomacy", {}).get(country_name, {})
            if not isinstance(their_request, dict):
                their_request = {}
            params = their_request.get("parameters", resp.get("parameters"))

            if verdict == RESPONSE_ACCEPT:
                fallback_msg = ai_prompts.AI_FALLBACK_RESPONSES.get("ACCEPT_GENERIC").format(action=orig_action.replace('_', ' ').lower())
                msg_text = custom_msg if custom_msg else fallback_msg

                # `sender` proposed and `country_name` accepted. The AI-accepted
                # pass below runs the same rules -- see treaty_effects.
                outcome = treaty_effects.apply_treaty_effect(
                    map_screen, orig_action, sender, country_name, params,
                    escrow=their_request.pop("escrow", None))
                if outcome.blocked:
                    msg_text = outcome.blocked
                    wrote_it = False
                elif not custom_msg and outcome.canned:
                    msg_text = outcome.canned

                send_message(map_screen, country_name, sender, msg_text, "DIPLOMACY",
                             extra=answered, llm=wrote_it)

                if msg_text == custom_msg or "accepted" in msg_text.lower():
                    log_global_event(map_screen.nation_data, f"Diplomatic agreement reached between {country_name} and {sender}.")

            else:
                fallback_msg = ai_prompts.AI_FALLBACK_RESPONSES.get("REJECT_GENERIC").format(action=orig_action.replace('_', ' ').lower())
                msg_text = custom_msg if custom_msg else fallback_msg

                # Whatever the proposer put up for this offer goes home.
                _refund_offer_escrow(map_screen.nation_data, sender, their_request)

                send_message(map_screen, country_name, sender, msg_text, "DIPLOMACY",
                             extra=answered, llm=wrote_it)
                _decline_cooldown(map_screen, sender, country_name, orig_action)

            # Their request has now been answered either way.
            their_pending = map_screen.nation_data.get(sender, {}).get("pending_diplomacy", {})
            their_entry = their_pending.get(country_name)
            if isinstance(their_entry, dict) and their_entry.get("action") == orig_action:
                del their_pending[country_name]

            del responses[sender]


def _process_pass1_immediate_actions(map_screen):
    """PASS 1: executes every action that fires the instant it's queued (turns == 0),
    and advances everything else to turns == 1 for Pass 2 to pick up."""
    for country_name, data in list(map_screen.nation_data.items()):
        if not isinstance(data, dict):
            continue

        pending = data.get("pending_diplomacy", {})
        actions_to_clear = []
        # Targets whose drafted text already went out via the MSG: branch below.
        # The draft_lists flush at the end of this loop would otherwise deliver
        # the very same text a second time.
        msg_delivered = set()

        for target, info in list(pending.items()):
            action = info.get("action", "")
            turns = info.get("turns", 0)
            timer = info.get("timer", 0)
            custom_msg = info.get("message", "")
            # Set beside `message` by whoever queued it, so the flag travels
            # with the text it belongs to rather than being guessed at here.
            wrote_it = bool(info.get("llm"))

            is_unilateral = action in c.UNILATERAL_ACTIONS

            # --- NEW: COUNTDOWN TIMERS ---
            if timer > 0:
                info["timer"] -= 1
                if info["timer"] > 0:
                    continue
                else:
                    turns = 0 # Force execution this turn

            if turns == 0:
                info["_processed_this_turn"] = True
                # EXECUTE unilateral actions instantly on Turn 0
                if action == "JUSTIFY_WARGOAL":
                    prov_ids = [int(x) for x in custom_msg.split(",") if x]

                    # Remove old claims that are currently owned by the target to allow unclaiming
                    current_claims = map_screen.nation_data[country_name].get("claims", [])
                    new_claims = []
                    for cid in current_claims:
                        prov = map_screen.id_to_province.get(cid)
                        if prov and prov.get("owner") == target:
                            continue # Drop it so it can be overwritten
                        new_claims.append(cid)

                    new_claims.extend(prov_ids)
                    map_screen.nation_data[country_name]["claims"] = list(set(new_claims))

                    map_screen.nation_data[country_name].setdefault("wargoals", {})[target] = {"type": c.WARGOAL_TAKE_CLAIMS}
                    log_global_event(map_screen.nation_data, f"{country_name} has justified a wargoal against {target}.")
                    if country_name == map_screen.player_country:
                        map_screen.show_feedback(f"Wargoal Justification Complete against {target}!")
                    actions_to_clear.append(target)

                elif action == "WAR_DECLARATION":
                    # Store active wargoal in war data
                    map_screen.nation_data[country_name].setdefault("wargoals", {})[target] = {"type": custom_msg}
                    log_global_event(map_screen.nation_data, f"WAR DECLARED: {country_name} has declared war on {target}!")
                    # `custom_msg` is the wargoal here, not anything anyone said,
                    # so the words come off `prose` -- which is where they had to
                    # go once the wargoal took the message field. This line used
                    # to be a hardcoded sentence that ignored the model and the
                    # canned table alike, so at ABSOLUTE every war in the game
                    # was declared in exactly the same words.
                    words = info.get("prose") or "We have declared war!"
                    goal = f" Goal: {custom_msg}" if custom_msg else ""
                    send_message(map_screen, country_name, target, f"{words}{goal}",
                                 "DIPLOMACY", extra={"action": action}, llm=wrote_it)
                    finalize_war(map_screen.map_data, map_screen.nation_data, country_name, target)
                    actions_to_clear.append(target)

                elif action == "JOIN_WARS":
                    if not queries.are_in_same_faction(country_name, target, map_screen.nation_data):
                        send_message(map_screen, country_name, target,
                                     ai_prompts.AI_FALLBACK_RESPONSES["REJECT_JOIN_WAR_NO_ALLIANCE"],
                                     "DIPLOMACY", extra={"action": action})
                        actions_to_clear.append(target)
                    else:
                        # DO NOT execute the war join here! Just send the proposal message.
                        send_treaty_message(map_screen, country_name, target, action, custom_msg, llm=wrote_it)

                elif action == "CALL_TO_ARMS":
                    send_treaty_message(map_screen, country_name, target, action, custom_msg, llm=wrote_it)

                elif action == "BREAK_ALLIANCE":
                    log_global_event(map_screen.nation_data, f"{country_name} has broken their alliance with {target}.")
                    send_treaty_message(map_screen, country_name, target, action, custom_msg, llm=wrote_it)
                    finalize_neutral(map_screen.nation_data, country_name, target)

                elif action == "ANNEX_PUPPET":
                    finalize_annexation(map_screen.map_data, map_screen.nation_data, country_name, target, map_screen)
                    actions_to_clear.append(target)

                elif action == "RELEASE_PUPPET":
                    finalize_release(map_screen.map_data, map_screen.nation_data, country_name, target, map_screen)
                    actions_to_clear.append(target)

                elif action == "TAKE_PUPPETS":
                    finalize_take_puppets(map_screen.map_data, map_screen.nation_data, country_name, target)
                    map_screen.show_feedback(f"Assumed control of {target}'s puppets.")
                    actions_to_clear.append(target)

                elif action == "CANCEL_MILITARY_ACCESS":
                    # We are cancelling our access to their country (target's list)
                    target_list = map_screen.nation_data.get(target, {}).setdefault("military_access", [])
                    if country_name in target_list:
                        target_list.remove(country_name)
                    log_global_event(map_screen.nation_data, f"{country_name} cancelled their military access to {target}.")
                    send_treaty_message(map_screen, country_name, target, action, custom_msg, llm=wrote_it)
                    actions_to_clear.append(target)

                elif action == "REVOKE_MILITARY_ACCESS":
                    # We are revoking their access to our country (our list)
                    our_list = map_screen.nation_data.get(country_name, {}).setdefault("military_access", [])
                    if target in our_list:
                        our_list.remove(target)
                    log_global_event(map_screen.nation_data, f"{country_name} revoked {target}'s military access.")
                    send_treaty_message(map_screen, country_name, target, action, custom_msg, llm=wrote_it)
                    actions_to_clear.append(target)


                # DELIVER messages to inbox on Turn 0
                elif action.startswith("MSG:"):
                    send_message(map_screen, country_name, target, action[4:], "TEXT")
                    msg_delivered.add(target)

                elif action in ("FACTION_INVITE", "JOIN_FACTION_REQ", "REQ_MILITARY_ACCESS",
                                "CEASEFIRE", "CREATE_FACTION", "TRADE"):
                    # Nothing happens on the sender's side; the offer just travels.
                    # A trade's terms travel with it, so both sides can still
                    # read what was agreed after the offer itself is cleared.
                    _hold_offer_escrow(map_screen, country_name, target, info)
                    send_treaty_message(map_screen, country_name, target, action, custom_msg,
                                        parameters=info.get("parameters"), llm=wrote_it,
                                        note=info.get("note", ""))

                elif action == "PEACE_TREATY":
                    # Reparations are promised the moment the offer leaves, the
                    # same as a trade's goods.
                    _hold_offer_escrow(map_screen, country_name, target, info)
                    send_treaty_message(map_screen, country_name, target, action, custom_msg,
                                        parameters=info.get("parameters"), llm=wrote_it,
                                        note=info.get("note", ""))

                elif action == "DISBAND_FACTION":
                    fac = map_screen.nation_data[country_name].get("faction", "")
                    info["cached_members"] = info.get("cached_members", queries.get_faction_members(fac, map_screen.nation_data) if fac else [])
                    log_global_event(map_screen.nation_data, f"The faction led by {country_name} has been disbanded.")
                    for m in info["cached_members"]:
                        if m != country_name:
                            send_treaty_message(map_screen, country_name, m, action, custom_msg, llm=wrote_it)

                    finalize_disband_faction(map_screen.nation_data, country_name)

                elif action == "KICK_FACTION_MEMBER":
                    log_global_event(map_screen.nation_data, f"FACTION EXPULSION: {country_name} has kicked {target} from the faction!")
                    send_treaty_message(map_screen, country_name, target, action, custom_msg, llm=wrote_it)
                    finalize_faction_kick(map_screen.nation_data, country_name, target)

                elif action == "LEAVE_FACTION":
                    fac = map_screen.nation_data[country_name].get("faction", "")
                    info["cached_members"] = info.get("cached_members", queries.get_faction_members(fac, map_screen.nation_data) if fac else [])
                    log_global_event(map_screen.nation_data, f"{country_name} has abandoned their faction.")
                    for m in info["cached_members"]:
                        if m != country_name:
                            send_treaty_message(map_screen, country_name, m, action, custom_msg, llm=wrote_it)

                    finalize_faction_leave(map_screen.nation_data, country_name)

                elif action == "CLAIM_FACTION_LEADERSHIP":
                    # Re-checked here rather than trusted from when the button
                    # was pressed. A claim is queued a turn ahead, and a turn is
                    # long enough to lose the army that justified it -- or the
                    # faction, if the leader disbanded it in the meantime.
                    fac = map_screen.nation_data[country_name].get("faction", "")
                    old = queries.get_faction_leader(fac, map_screen.nation_data) if fac else ""
                    if not faction_leadership.can_claim(map_screen, country_name):
                        print(f"[GUARDRAIL] {country_name} no longer has a claim on "
                              f"{fac or 'any faction'}'s leadership.")
                        actions_to_clear.append(target)
                    else:
                        members = queries.get_faction_members(fac, map_screen.nation_data)
                        log_global_event(map_screen.nation_data,
                                         f"FACTION LEADERSHIP: {country_name} has taken "
                                         f"command of {fac} from {old}.")
                        faction_leadership.transfer(map_screen.nation_data, old, country_name)
                        for m in members:
                            if m != country_name:
                                send_treaty_message(map_screen, country_name, m, action,
                                                    custom_msg, llm=wrote_it)

                elif action in c.BILATERAL_ACTIONS:
                    # Catch-all so a bilateral action added to constants.py without
                    # its own branch above still reaches the other side's inbox
                    # instead of silently advancing to turns=1 with no message.
                    send_treaty_message(map_screen, country_name, target, action, custom_msg, llm=wrote_it)

                # Cleanup or increment
                if target in actions_to_clear:
                    pass # It was executed entirely on turn 0, so we skip the increment
                elif country_name not in map_screen.active_players and action.startswith("MSG:"):
                    # If an AI sent a pure message, it's delivered instantly on turn 0, so clear it.
                    actions_to_clear.append(target)
                else:
                    info["turns"] += 1

        for t in actions_to_clear:
            if t in pending:
                del pending[t]

        # DELIVER and clear text drafts stored in draft_lists for Turn 0.
        # Only drafts riding alongside a FORMAL action land here -- when the text
        # is all there is, the MSG: branch above already sent it.
        draft_lists = data.get("draft_lists", {})
        if draft_lists:
            for d_target, d_messages in list(draft_lists.items()):
                if d_messages and d_target not in msg_delivered:
                    combined_msg = "\n".join(d_messages)
                    send_message(map_screen, country_name, d_target, combined_msg, "TEXT")
            data["draft_lists"] = {}


def _process_pass2_delayed_actions(map_screen, ai_results, active_nations_list, delayed_responses):
    """PASS 2: resolves everything that had to wait a turn for an answer
    (turns >= 1) -- LLM-evaluated proposals/messages, and human replies picked
    up via Pass 0.5. Anything that outlives its response window auto-declines."""
    for country_name, data in list(map_screen.nation_data.items()):
        if not isinstance(data, dict):
            continue

        pending = data.get("pending_diplomacy", {})
        actions_to_clear = []

        for target, info in list(pending.items()):
            action = info.get("action", "")
            turns = info.get("turns", 0)
            custom_msg = info.get("message", "")

            is_unilateral = action in c.UNILATERAL_ACTIONS

            # Skip actions that were already handled in Pass 1
            if info.pop("_processed_this_turn", False):
                continue

            if turns == 1:
                is_human_target = target in map_screen.active_players

                if is_unilateral:
                    if action == "DISBAND_FACTION" or action == "LEAVE_FACTION":
                        members = info.get("cached_members", [])
                        for m in members:
                            if m != country_name and m not in map_screen.active_players:
                                if action == "DISBAND_FACTION":
                                    reply_dict = ai_results.get((country_name, m, action), {})
                                    msg_text = reply_dict.get("message", ai_prompts.AI_FALLBACK_RESPONSES.get("FACTION_DISBANDED", "It is a shame to see our alliance broken."))
                                else:
                                    reply_dict = ai_results.get((country_name, m, action), {})
                                    msg_text = reply_dict.get("message", ai_prompts.AI_FALLBACK_RESPONSES.get("FACTION_ABANDONED", "We will not forget your abandonment."))

                                op_val = reply_dict.get("opinion_change", 0)
                                if op_val != 0:
                                    queries.add_temporary_modifier(m, country_name, "general", op_val, map_screen.nation_data)

                                _process_ai_retaliation(map_screen, active_nations_list, delayed_responses, m, reply_dict, default_target=country_name)
                                send_message(map_screen, m, country_name, msg_text, "DIPLOMACY",
                                             extra={"action": action},
                                             llm=bool(reply_dict.get("llm")))

                    elif not is_human_target:
                        reply_dict = ai_results.get((country_name, target, action), {})

                        message = reply_dict.get("message", ai_prompts.AI_FALLBACK_RESPONSES.get("GENERIC_MESSAGE", "Message received."))

                        op_val = reply_dict.get("opinion_change", 0)
                        if op_val != 0:
                            queries.add_temporary_modifier(target, country_name, "general", op_val, map_screen.nation_data)

                        _process_ai_retaliation(map_screen, active_nations_list, delayed_responses, target, reply_dict, default_target=country_name)
                        send_message(map_screen, target, country_name, message, "DIPLOMACY",
                                     extra={"action": action},
                                     llm=bool(reply_dict.get("llm")))

                    actions_to_clear.append(target)

                elif action.startswith("MSG:"):
                    if not is_human_target:
                        reply_dict = ai_results.get((country_name, target, "CUSTOM_MSG"), {})

                        message = reply_dict.get("message", "Message received.")

                        op_val = reply_dict.get("opinion_change", 0)
                        if op_val != 0:
                            queries.add_temporary_modifier(target, country_name, "general", op_val, map_screen.nation_data)

                        _process_ai_retaliation(map_screen, active_nations_list, delayed_responses, target, reply_dict, default_target=country_name)

                        msg_type = "TEXT" if reply_dict.get("action", "NONE") == "NONE" else "DIPLOMACY"
                        send_message(map_screen, target, country_name, message, msg_type,
                                     llm=bool(reply_dict.get("llm")))

                    actions_to_clear.append(target)

                elif action in c.BILATERAL_ACTIONS:
                    if is_human_target:
                        # A queued answer is resolved by Pass 0.5, which also deletes
                        # this entry -- so if we still see it here, they answered
                        # something else or nothing at all.
                        target_resp = get_response(map_screen.nation_data, target, country_name)

                        if target_resp.get("action") == action:
                            # Answer is in hand, let Pass 0.5 settle it next tick
                            info["turns"] += 1
                        else:
                            # Auto-decline since the human player did not respond immediately on their turn
                            _refund_offer_escrow(map_screen.nation_data, country_name, info)
                            send_message(map_screen, target, country_name, "Your proposal was ignored and automatically declined.", "DIPLOMACY",
                                     extra={"action": action})
                            _decline_cooldown(map_screen, country_name, target, action)
                            actions_to_clear.append(target)
                    else:
                        reply_dict = ai_results.get((country_name, target, action), {})

                        accepted = reply_dict.get("accepted", False)
                        message = reply_dict.get("message", "Timeout.")
                        wrote_it = bool(reply_dict.get("llm"))

                        op_val = reply_dict.get("opinion_change", 0)
                        if op_val != 0:
                            queries.add_temporary_modifier(target, country_name, "general", op_val, map_screen.nation_data)

                        _process_ai_retaliation(map_screen, active_nations_list, delayed_responses, target, reply_dict, default_target=country_name)

                        if accepted:
                            # `country_name` proposed and `target` accepted,
                            # mirroring the player-accepted pass above. The AI
                            # wrote its own reply, so only a blocked agreement
                            # replaces it.
                            outcome = treaty_effects.apply_treaty_effect(
                                map_screen, action, country_name, target, info.get("parameters"),
                                escrow=info.pop("escrow", None))
                            if outcome.blocked:
                                message = outcome.blocked
                                wrote_it = False
                        else:
                            _refund_offer_escrow(map_screen.nation_data, country_name, info)
                            _decline_cooldown(map_screen, country_name, target, action)

                        send_message(map_screen, target, country_name, message, "DIPLOMACY",
                                     extra={"action": action}, llm=wrote_it)
                        actions_to_clear.append(target)

            elif turns > 1:
                # Auto-decline anything that outlived its response window
                if action in c.BILATERAL_ACTIONS:
                    _refund_offer_escrow(map_screen.nation_data, country_name, info)

                    send_message(map_screen, target, country_name, "Your proposal was ignored and automatically declined.", "DIPLOMACY",
                                     extra={"action": action})
                    _decline_cooldown(map_screen, country_name, target, action)
                    actions_to_clear.append(target)
                else:
                    info["turns"] += 1

        for t in actions_to_clear:
            if t in pending:
                del pending[t]


def _apply_delayed_responses(map_screen, delayed_responses):
    """Converts the proposals _process_ai_retaliation queued up (like war
    declarations) into normal pending_diplomacy actions for next turn."""
    for sender, receiver, act, tns, msg in delayed_responses:
        pd = map_screen.nation_data.get(sender, {}).setdefault("pending_diplomacy", {})
        if receiver not in pd or (isinstance(pd[receiver], dict) and pd[receiver].get("turns", 0) == 0):
            pd[receiver] = {"action": act, "turns": tns, "timer": 0, "message": msg}


def _process_claim_queues(map_screen):
    """Ticks down every nation's claim/revoke/return/puppet-release queues by
    one turn, applying whichever entries finish this turn."""
    for country_name, data in list(map_screen.nation_data.items()):
        if not isinstance(data, dict):
            continue

        claim_queue = data.get("claim_queue", [])
        if claim_queue:
            current_claim = claim_queue[0]
            current_claim["turns_left"] -= 1

            if current_claim["turns_left"] <= 0:
                prov_id = current_claim["prov_id"]
                data.setdefault("claims", []).append(prov_id)
                claim_queue.pop(0)

                if country_name == map_screen.player_country:
                    map_screen.show_feedback(f"Claim on Province {prov_id} complete!")

        # --- PROCESS REVOKE QUEUE (Simultaneous) ---
        revoke_queue = data.get("revoke_queue", [])
        if revoke_queue:
            # Iterate backwards so we can safely pop elements as they complete
            for i in range(len(revoke_queue) - 1, -1, -1):
                rq = revoke_queue[i]
                rq["turns_left"] -= 1

                if rq["turns_left"] <= 0:
                    prov_id = rq["prov_id"]
                    claims = data.get("claims", [])
                    if prov_id in claims:
                        claims.remove(prov_id)

                    # --- NEW: Strip the core from the province map data! ---
                    prov = map_screen.id_to_province.get(prov_id)
                    if prov and country_name in prov.get("cores", []):
                        prov["cores"].remove(country_name)

                    revoke_queue.pop(i)

                    if country_name == map_screen.player_country:
                        map_screen.show_feedback(f"Claim on Province {prov_id} revoked!")
        # --- PROCESS RETURN QUEUE (Simultaneous) ---
        return_queue = data.get("return_queue", [])
        if return_queue:
            for i in range(len(return_queue) - 1, -1, -1):
                rq = return_queue[i]
                rq["turns_left"] -= 1

                if rq["turns_left"] <= 0:
                    prov_id = rq["prov_id"]
                    recipient = rq["recipient"]

                    prov = map_screen.id_to_province.get(prov_id)
                    if prov and prov.get("owner") == country_name:
                        from map_logic.turn_processing import edit_province_ownership
                        # Return the province to the intended recipient!
                        edit_province_ownership.conquer_province(map_screen, prov, recipient)

                        if country_name == map_screen.player_country:
                            map_screen.show_feedback(f"Returned Province {prov_id} to {recipient}!")

                    return_queue.pop(i)

        # --- PROCESS PUPPET RELEASE QUEUE ---
        release_queue = data.get("release_puppet_queue", [])
        if release_queue:
            ready_to_release = []
            for i in range(len(release_queue) - 1, -1, -1):
                release_queue[i]["turns_left"] -= 1
                if release_queue[i]["turns_left"] <= 0:
                    ready_to_release.insert(0, release_queue.pop(i))

            for rq in ready_to_release:
                core_nation = rq["core_nation"]
                keep_cores = rq.get("keep_cores", False)
                from map_logic.diplomacy.diplomacy_agreements import finalize_create_integrated_puppet
                finalize_create_integrated_puppet(map_screen.map_data, map_screen.nation_data, country_name, core_nation, map_screen, keep_cores)
                if country_name == map_screen.player_country:
                    map_screen.show_feedback(f"Created integrated puppet from {core_nation} cores!")


def process_diplomacy_turn(map_screen):
    _decay_modifiers_and_truces(map_screen)
    # Ages every faction member's claim on the leadership. Before anything acts,
    # so the button a player sees, the number an AI decides on and the state a
    # claim executes against are one measurement rather than three.
    faction_leadership.tick(map_screen, getattr(map_screen, "ai_world", None))
    # Settles promises that ran their course or were broken this turn. After the
    # modifier decay so a fresh betrayal grudge is not aged on the turn it lands.
    ai_commitments.tick(map_screen)
    _flush_queued_ai_actions(map_screen)

    # --- 0. FIND ALIVE NATIONS ---
    active_nations = queries.get_living_nations(map_screen.map_data)
    active_nations_list = sorted(list(active_nations))

    # --- 1. SIMULTANEOUS ACTION CLASH RESOLUTION ---
    _resolve_simultaneous_clashes(map_screen)

    # --- 2. GATHER AI TASKS ---
    ai_tasks = _gather_ai_tasks(map_screen)

    # --- 3. EXECUTE AI THREADS ---
    ai_results = _execute_ai_tasks(map_screen, ai_tasks, active_nations_list)

    # --- 4. STANDARD RESOLUTION (APPLY AI RESULTS) ---
    delayed_responses = [] # Store AI actions here to queue them for the next turn

    # A bloc treaty accepted last turn may still be waiting on a human member's
    # answer. Settled before this turn's offers go out, for the same reason
    # Pass 0.5 runs before Pass 1.
    ratification.process_ratifications(map_screen)

    _process_queued_responses(map_screen)
    _process_pass1_immediate_actions(map_screen)
    _process_pass2_delayed_actions(map_screen, ai_results, active_nations_list, delayed_responses)
    _apply_delayed_responses(map_screen, delayed_responses)

    # --- PROCESS CLAIM QUEUES ---
    _process_claim_queues(map_screen)
