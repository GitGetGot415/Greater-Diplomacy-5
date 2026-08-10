"""Turns a diplomatic proposal, a plain message, or a proactive action into an
AI reply: canned-table lookup when the LLM isn't consulted, otherwise a
provider call routed through map_logic.ai.ai_handler.

Split out of map_logic/ai/ai_handler.py, which re-exports every name here so
existing `ai_handler.evaluate_diplomatic_proposal(...)`-style call sites keep
working.
"""
import json
from data.platform import IS_WEB

if not IS_WEB:
    from google import genai
    from google.genai import types
else:
    genai = None
    types = None
import data.constants as c
from data import queries
from map_logic.ai import ai_prompts
from map_logic.ai import ai_settings


def _to_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _reply(message, source=None, accepted=None):
    """The answer dict every AI entry point in this file returns.

    It was written out fifteen times, which is how the Ollama branch came to
    trust the model's `opinion_change` raw while the Gemini branch coerced it
    to an int. `source` is a parsed model reply to lift the action fields off;
    without one they all read "NONE", which is what every canned answer said.
    `accepted` is omitted entirely when None -- replies to a plain message
    carry no verdict, and downstream code tells the two apart by that key.
    """
    source = source or {}
    reply = {}
    if accepted is not None:
        reply["accepted"] = accepted
    reply.update({
        "message": message,
        "action": source.get("action", "NONE"),
        "action_target": source.get("action_target", "NONE"),
        "follow_up_action": source.get("follow_up_action", "NONE"),
        "follow_up_target": source.get("follow_up_target", "NONE"),
        "opinion_change": _to_int(source.get("opinion_change", 0)),
    })
    return reply


def _use_canned_reply(mode, immersion, is_ai_to_ai, has_custom_msg=True):
    """Whether this exchange skips the LLM and answers from the canned table.

    One rule for all three entry points. Proactive text passes
    has_custom_msg=False because nobody wrote anything to reply to, which is
    what made its LITE branch look different from the other two.
    """
    if mode == "OFF":
        return True
    if immersion == "ABSOLUTE":
        return False
    if immersion == "FULL":
        return is_ai_to_ai
    # LITE: only a human's own words are worth generating a reply to.
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


def get_world_context(nation_data, active_nations, ai_nation, target_nation=None, current_date="Unknown"):
    ai_stats = nation_data.get(ai_nation, {})
    manpower = ai_stats.get("manpower", 0)
    materials = ai_stats.get("materials", 0)

    # 2. Establish Global Politics (Now includes Factions!)
    politics_str = ""
    for nation in active_nations:
        n_data = nation_data.get(nation, {})
        wars = [w for w in n_data.get("at_war_with", []) if w in active_nations]
        fac = n_data.get("faction", "")
        master = n_data.get("master", "")
        puppets = [p for p in n_data.get("puppets", []) if p in active_nations]

        rels = []
        if wars: rels.append(f"at war with {', '.join(wars)}")
        if fac: rels.append(f"in the faction '{fac}'")
        if master: rels.append(f"a puppet state of {master}")
        if puppets: rels.append(f"puppetmaster of {', '.join(puppets)}")

        # --- Inject Relation Score ---
        if nation != ai_nation:
            rel_score = queries.get_relation_score(ai_nation, nation, nation_data)
            rels.append(f"Relations: {rel_score} (Scale: -200 to 200)")
        if rels:
            politics_str += f"- {nation}: {' | '.join(rels)}.\n"

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
            if sender_field == target_nation:
                thread.append(f"{target_nation}: '{msg.get('content')}'")
            elif sender_field == f"To: {target_nation}":
                thread.append(f"You: '{msg.get('content')}'")

        if thread:
            # Only give the last 10 messages so we don't blow up the context window
            recent_thread = thread[-10:]
            target_context_str = "\n".join(recent_thread) + "\n"

    return ai_prompts.build_world_context(
        current_date, ai_nation, ', '.join(active_nations),
        manpower, materials, politics_str, events_str, target_context_str, target_nation
    )


def evaluate_diplomatic_proposal(nation_data, map_data, active_nations, ai_nation, sender_nation, action_type, custom_msg="", human_players=None, turn_id=None):
    from map_logic.ai import ai_handler

    if ai_handler._aborted(turn_id):
        return _reply(ai_prompts.AI_FALLBACK_RESPONSES["GENERIC_ACCEPT"], accepted=True)

    if human_players is None:
        human_players = []

    mode = ai_settings.get_ai_mode()
    immersion = ai_settings.get_ai_immersion_level()

    ai_stats = nation_data.get(ai_nation, {})
    at_war = len(ai_stats.get("at_war_with", [])) > 0
    in_faction = bool(ai_stats.get("faction", ""))

    accepted = False

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

    # Accept Military Access requests from nations fighting the same enemies as us,
    # even across faction lines, so co-belligerents can cross each other's territory.
    if action_type == "REQ_MILITARY_ACCESS":
        ai_enemies = set(ai_stats.get("at_war_with", []))
        sender_enemies = set(queries.get_enemies(sender_nation, nation_data))
        accepted = bool(ai_enemies & sender_enemies)

    # NEW: AI Master-Puppet Faction Acceptance
    my_master = ai_stats.get("master", "")
    if my_master == sender_nation and action_type in ["FACTION_INVITE", "CREATE_FACTION", "JOIN_FACTION_REQ"]:
        accepted = True

    # 2. Check for Join Faction Requests (If we are the leader)
    if action_type == "JOIN_FACTION_REQ" and ai_stats.get("is_faction_leader", False):
        relation_score = queries.get_relation_score(ai_nation, sender_nation, nation_data)

        # Calculate shared enemies
        ai_enemies = set(ai_stats.get("at_war_with", []))
        sender_enemies = set(queries.get_enemies(sender_nation, nation_data))
        share_enemies = bool(ai_enemies.intersection(sender_enemies))

        # Accept if relations are good OR they are helping us fight common threats
        if relation_score >= c.AI_RELATION_FACTION_THRESHOLD or share_enemies:
            accepted = True

    # 3. Evaluate peace deals dynamically using the centralized query
    if action_type in ["PEACE_TREATY", "CEASEFIRE"]:
        accepted = queries.will_ai_accept_peace(ai_nation, sender_nation, custom_msg, map_data, nation_data)

    # --- NEW AI TRADE LOGIC ---
    elif action_type == "TRADE":
        pending = nation_data.get(sender_nation, {}).get("pending_diplomacy", {}).get(ai_nation, {})
        params = pending.get("parameters", {})

        puppet_state = params.get("puppet_state", "NONE")
        sender_master = nation_data.get(sender_nation, {}).get("master", "")
        sender_type = nation_data.get(sender_nation, {}).get("puppet_type", "")
        my_type = ai_stats.get("puppet_type", "")

        is_sender_integrated = bool(sender_master and sender_type == c.PUPPET_TYPE_INTEGRATED and sender_master != ai_nation)
        is_my_integrated = bool(my_master and my_type == c.PUPPET_TYPE_INTEGRATED and my_master != sender_nation)

        # We are the AI (Receiving). Therefore we "Take" what they "Give", and we "Give" what they "Take".
        ai_takes_mats = params.get("give_materials", 0)
        ai_takes_fuel = params.get("give_fuel", 0)
        ai_gives_mats = params.get("take_materials", 0)
        ai_gives_fuel = params.get("take_fuel", 0)

        if puppet_state != "NONE" or is_sender_integrated or is_my_integrated:
            accepted = False
        elif ai_gives_mats == 0 and ai_gives_fuel == 0 and (ai_takes_mats > 0 or ai_takes_fuel > 0):
            accepted = True
        else:
            accepted = False
    # ------------------------------

    # Check if this is an AI talking to an AI
    is_ai_to_ai = (ai_nation not in human_players) and (sender_nation not in human_players)

    if _use_canned_reply(mode, immersion, is_ai_to_ai, bool(custom_msg.strip())):
        key = LITE_RESPONSE_KEYS.get(action_type,
                                     "AI_OFF_ACCEPT" if accepted else "AI_OFF_REJECT")
        return _reply(ai_prompts.AI_FALLBACK_RESPONSES[key], accepted=accepted)

    print(f"[LLM CALL] {ai_nation} generating flavor text for {action_type} from {sender_nation}... (Mode: {mode})")

    context = get_world_context(nation_data, active_nations, ai_nation, sender_nation)

    # --- Split logic between Proposals and Unilateral Declarations ---
    if action_type in c.UNILATERAL_ACTIONS:
        action_context = ai_prompts.get_unilateral_receive_context(action_type, sender_nation, custom_msg)
        system_prompt = ai_prompts.get_unilateral_system_prompt(action_context)
        user_prompt = f"{context}\n{action_context} Provide your reaction."
    else:
        action_context = ai_prompts.get_bilateral_receive_context(action_type, sender_nation, custom_msg)
        system_prompt = ai_prompts.get_bilateral_system_prompt(accepted)
        user_prompt = f"{context}\n{action_context} Provide your response based on your decision."

    return ai_handler._run_provider(mode, system_prompt, user_prompt, turn_id,
                         ai_prompts.AI_FALLBACK_RESPONSES["GENERIC_ACCEPT"], accepted)

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

    if mode == "OLLAMA":
        result = ai_handler.call_ollama(system_prompt, user_prompt, turn_id)
        return result.get("message", "OLLAMA ERROR: Unknown Format") if result else "OLLAMA ERROR: No response"

    if mode in ai_handler.OPENAI_COMPATIBLE_PROVIDERS:
        get_url, get_key, get_model = ai_handler.OPENAI_COMPATIBLE_PROVIDERS[mode]
        result = ai_handler.call_openai_compatible(get_url(), get_key(), get_model(), system_prompt, user_prompt, turn_id)
        return result.get("message", f"{mode} ERROR: Unknown Format") if result else f"{mode} ERROR: No response"

    if mode == "CLAUDE":
        result = ai_handler.call_claude(ai_settings.get_claude_api_key(), ai_settings.get_claude_model(),
                                         system_prompt, user_prompt, turn_id)
        return result.get("message", "CLAUDE ERROR: Unknown Format") if result else "CLAUDE ERROR: No response"

    try:
        client = genai.Client(api_key=ai_settings.get_gemini_api_key())
        response = client.models.generate_content(
            model=ai_settings.get_gemini_model(),
            contents=f"{system_prompt}\n\n{user_prompt}",
            config=types.GenerateContentConfig(response_mime_type="application/json")
        )

        if ai_handler._aborted(turn_id): return None

        return json.loads(response.text).get("message", "JSON ERROR: Parsed fine but missing 'message' key.")
    except Exception as e:
        return f"API ERROR: {str(e)}"
