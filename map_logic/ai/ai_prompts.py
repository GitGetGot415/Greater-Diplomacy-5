# ==========================================
# FALLBACK / MANUAL AI RESPONSES
# ==========================================

AI_FALLBACK_RESPONSES = {
    "AI_OFF_ACCEPT": "We accept your proposal.",
    "AI_OFF_REJECT": "We reject your proposal.",
    "AI_OFF_MESSAGE": "Message received (AI is OFF).",
    "GENERIC_ACCEPT": "We have made our decision.",
    "GENERIC_MESSAGE": "Message received.",
    "OLLAMA_ERROR": "Ollama server error or timeout.",
    "API_ERROR": "API Error.",
    "TIMEOUT": "Timeout.",
    "BETRAYAL": "You will regret this betrayal.",
    "ALLIANCE_BROKEN": "We won't forget this.",
    "FACTION_ABANDONED": "We will not forget your abandonment.",
    "FACTION_DISBANDED": "It is a shame to see our alliance broken.",
    "ACCEPTED_HELP": "We gratefully accept your assistance in our conflicts.",
    "ANSWERED_CALL": "We will answer your call to arms.",
    "INVITE_IGNORED": "Your faction invitation was ignored and has expired.",
    "JOIN_REQ_IGNORED": "Your request to join the faction was ignored and has expired.",
    "CEASEFIRE_IGNORED": "Your ceasefire offer was ignored and has expired.",
    "CALL_TO_ARMS_IGNORED": "Your call to arms was ignored and has expired.",
    "CANT_JOIN_FACTION": "We cannot join a new faction while we are already bound to our own treaties.",
    "NOT_AT_WAR": "We would offer military aid to {target}, but they are not currently at war.",
    "KICKED_FROM_FACTION": "We will not forget being expelled from the alliance.",
    "REJECT_JOIN_WAR_NO_ALLIANCE": "We wanted to join your wars, but our lack of formal alliance prevents it.",
    "REQUEST_JOIN_WARS": "We request permission to join your ongoing wars.",
    "FOLLOW_UP_DECLARATION": "Following through on our previous declaration.",
    "BREAK_ALLIANCE": "We have broken our alliance.",
    
    "PROACTIVE_JOIN_WAR": "May we join you in your war?",
    "PROACTIVE_DECLARE_WAR": "Your occupation of our rightful territory ends now!",
    "PROACTIVE_JOIN_FACTION": "Our enemies are aligned, let us join your faction to stand against them.",
    "PROACTIVE_CREATE_FACTION": "We propose establishing a new faction together.",
    
    "PROACTIVE_TRADE": "We propose a trade agreement.",
    "ACCEPT_TRADE": "We gladly accept your trade offer.",
    "REJECT_TRADE": "This trade is unacceptable to us.",

    "CROSS_FACTION_JOIN": "Our requests crossed paths. We are now united!",
    "CROSS_CEASEFIRE": "Mutual ceasefire agreements signed.",
    "CROSS_CALL_TO_ARMS": "Our diplomats crossed paths. We stand together in all our wars!",
    "CROSS_WAR_DECLARATION": "Your diplomat proposing a {action} was executed. We are at WAR!",

    "PROACTIVE_CEASEFIRE": "We offer terms for a ceasefire.",
    "PROACTIVE_CALL_TO_ARMS": "We request your aid in our ongoing conflicts!",
    "PROACTIVE_REQ_MILITARY_ACCESS": "As we both fight against a common foe, we request military access through your territory.",
    "PROACTIVE_PEACE_TREATY": "This war has cost us both too much. We propose terms.",
    "PROACTIVE_FACTION_INVITE": "Our cause would be stronger with you in it. Join us.",
    "PROACTIVE_TRADE": "We propose an exchange to the benefit of us both.",

    "ACCEPT_GENERIC": "We accepted your {action}.",
    "REJECT_GENERIC": "We rejected your {action}.",
    "ACCEPT_FACTION_ALREADY_IN": "We wanted to accept, but we are already in a faction.",
    "ACCEPT_FACTION_JOIN_ALREADY_IN": "We cannot accept as you are already in a faction.",
    "CREATE_FACTION_CONFLICT": "The proposed faction could not be formed because one of us is already bound by other treaties.",

    # These two were looked up by diplomacy_processor without ever being
    # defined here, so accepting a peace treaty or a military-access request
    # delivered a message with no content.
    "ACCEPT_PEACE": "We accept your terms. The war between us is over.",
    "ACCEPT_MILITARY_ACCESS": "We accept your request for military access.",

    "PUPPET_CANNOT_MAKE_PEACE": "A subject state cannot settle a war on its own authority. Take it up with our overlord.",
    "PUPPET_CANNOT_CHOOSE_FACTION": "A subject state does not choose its own alliances. Address our overlord."
}

# ==========================================
# SYSTEM PROMPTS & CONTEXT GENERATORS
# ==========================================

def build_world_context(current_date, ai_nation, active_nations_str, manpower, materials, politics_str, events_str, target_context_str, target_nation):
    # Assembles the overarching context about the world, economy, and politics.
    context = f"Current Date: {current_date}\n"
    context += f"You are the leader of {ai_nation}.\n"
    context += f"CRITICAL RULE: The ONLY nations that currently exist in this world are: {active_nations_str}.\n"
    context += "Do NOT mention, reference, or interact with any country, empire, or nation not explicitly on this list.\n\n"
    context += f"Your economy: {manpower} Manpower, {materials} Materials.\n\n"
    context += "--- GLOBAL POLITICS ---\n"
    context += politics_str
    
    if events_str:
        context += "\n--- RECENT WORLD EVENTS ---\n"
        context += events_str
        
    if target_nation:
        context += f"\n--- CURRENT TARGET ---\nYou are currently communicating with {target_nation}.\n"
        if target_context_str:
            context += "Recent message history:\n" + target_context_str
            
    return context

def get_proactive_action_context(action_type, target=None):
    # Returns the descriptive context for when an AI initiates a diplomatic move.
    if action_type == "CEASEFIRE":
        return "offering a ceasefire because our nations cannot physically reach each other"
    elif action_type == "CALL_TO_ARMS":
        return f"calling you to arms in our war against {target}"
    elif action_type == "JOIN_WARS":
        return f"mobilizing our forces to join your war against {target}"
    elif action_type == "WAR_DECLARATION":
        return f"declaring war on {target} to reclaim rightful core territory, you are not negotiating"
    elif action_type == "JOIN_FACTION_REQ":
        return "requesting to join your faction to stand against our mutual enemies"
    elif action_type == "CREATE_FACTION":
        return "proposing to create a new faction together to combat mutual threats"
    elif action_type == "REQ_MILITARY_ACCESS":
        return "requesting military access through your territory since we are both fighting a common enemy"
    elif action_type == "PEACE_TREATY":
        return "offering terms to end the war between us, which has gone badly for us"
    elif action_type == "FACTION_INVITE":
        return "inviting you into our faction, since we are on good terms and would both be stronger for it"
    elif action_type == "TRADE":
        return "proposing an exchange of resources, each of us sending what the other lacks"
    elif action_type.startswith("ACCEPT_"):
        return f"accepting the {action_type.replace('ACCEPT_', '').replace('_', ' ').lower()} proposal"
    elif action_type.startswith("REJECT_"):
        return f"rejecting the {action_type.replace('REJECT_', '').replace('_', ' ').lower()} proposal"
    elif action_type.startswith("MSG:"):
        return f"sending a diplomatic message: '{action_type[4:]}'"
    return "taking a diplomatic action"

def get_unilateral_receive_context(action_type, sender_nation, custom_msg=""):
    # Returns the context for when an AI receives an un-rejectable action (like War).
    context = ""
    if action_type == "WAR_DECLARATION":
        context = f"{sender_nation} has DECLARED WAR on us!"
    elif action_type == "LEAVE_FACTION":
        context = f"{sender_nation} has abandoned our faction!"
    elif action_type == "DISBAND_FACTION":
        context = f"{sender_nation} has disbanded our faction!"
    elif action_type == "JOIN_WARS":
        context = f"{sender_nation} has mobilized their forces to join our ongoing wars!"
    elif action_type == "BREAK_ALLIANCE":
        context = f"{sender_nation} has broken their alliance with us!"
    elif action_type == "KICK_FACTION_MEMBER":
        context = f"{sender_nation} has expelled us from the faction!"
        
    if custom_msg:
        context += f" They included this official message: '{custom_msg}'"
    return context

def get_bilateral_receive_context(action_type, sender_nation, custom_msg=""):
    # Returns the context for when an AI receives a bilateral proposal.
    if action_type == "JOIN_WARS":
        context = f"{sender_nation} is offering to join YOUR ongoing wars."
    elif action_type == "CALL_TO_ARMS":
        context = f"{sender_nation} is calling YOU to arms to join THEIR ongoing wars."
    elif action_type == "FACTION_INVITE":
        context = f"{sender_nation} is inviting you to join THEIR faction."
    elif action_type == "JOIN_FACTION_REQ":
        context = f"{sender_nation} is requesting to join YOUR faction."
    elif action_type == "TRADE":
        context = f"{sender_nation} has proposed a Trade Agreement. Terms: {custom_msg}"
    elif action_type == "REQ_MILITARY_ACCESS":
        context = f"{sender_nation} is requesting military access to move their troops through your territory."
    else:
        context = f"{sender_nation} has proposed a {action_type.replace('_', ' ').title()}."

    if custom_msg and action_type != "TRADE":
        context += f" They included this official message: '{custom_msg}'"
        
    return context

#: How the message is to be written, as opposed to what it has to contain.
#:
#: Nothing said this before. Every prompt named the nation ("You are the leader
#: of X") and left the voice to be inferred, which a strong model does and a
#: small one does not: llama3 wrote "Switzerland accepts your offer" into a
#: message already labelled as being from Switzerland. Stated once here, since
#: all three long prompts end with action_rules_and_schema.
VOICE_RULE = (
    "VOICE: write the 'message' as your own government addressing theirs, in the "
    "first person plural -- 'we', 'our', 'us'. Never refer to your own nation in "
    "the third person or by name, and never narrate what it does from outside.\n"
)


def reads_as_third_person(message, nation, nation_data=None):
    """Whether a reply talks about its own sender rather than speaking as them.

    Deliberately narrow: only an opening that names the nation or its adjective,
    which is the failure small models actually produce and the one that reads
    worst next to a sender label. A nation named mid-sentence is ordinary prose
    ("our claim on Poland stands") and is left alone. No second request is made
    to fix it -- the canned line is used instead, because a retry at ABSOLUTE
    costs one call per nation per turn.
    """
    if not message or not nation:
        return False

    names = {nation}
    data = (nation_data or {}).get(nation) or {}
    for key in ("name", "adjective"):
        if data.get(key):
            names.add(data[key])

    opening = message.lstrip().lstrip("\"'*").lower()
    for name in names:
        name = name.strip().lower()
        if not name or not opening.startswith(name):
            continue
        rest = opening[len(name):]
        # "Switzerland accepts" is third person; "Switzerland! We accept" and
        # "Switzerland's terms are these" are somebody's own voice.
        if rest[:1] in ("", " ") and not rest.lstrip().startswith(("we ", "we'", "our ")):
            return True
    return False


def action_rules_and_schema(subject, message_hint):
    """The tail every long system prompt ends with: the action list, the rules
    for using them, and the JSON schema to reply in.

    These eleven lines were written out three times, once per prompt, which
    meant adding a valid action or a rule meant editing all three and the
    copies had already begun to drift. Only two things genuinely differ:

    - `subject`: what to call the thing being reacted to ("event", "proposal",
      "message"), used in the opinion_change instruction.
    - `message_hint`: the placeholder inside the JSON schema. The model reads
      it, so the three stay distinct verbatim rather than being generalised.
    """
    return (
        VOICE_RULE +
        "Valid actions: 'WAR_DECLARATION', 'JOIN_WARS', 'LEAVE_FACTION', 'JOIN_FACTION_REQ', 'CEASEFIRE', 'CALL_TO_ARMS', 'CREATE_FACTION', 'KICK_FACTION_MEMBER', 'DISBAND_FACTION' or 'NONE'.\n"
        "RULES FOR ACTIONS:\n"
        "- You MUST specify the target country for your action in 'action_target' (e.g., 'Germany', 'Russia', or the sender's name).\n"
        "- Do NOT output 'JOIN_FACTION_REQ' if you are already in a faction. You have to leave your faction before doing that.\n"
        "- Do NOT output 'WAR_DECLARATION' against a member of your own faction. You have to leave your faction before doing that.\n"
        "- Do NOT output 'JOIN_WARS' if you're trying to join the war of someone not in your faction, instead just type 'WAR_DECLARATION' against the target country.\n"
        "- If your plan requires two steps (like leaving your faction this turn to declare war next turn), "
        "put your immediate move in 'action'/'action_target' and your next move in 'follow_up_action'/'follow_up_target'.\n"
        "- If you declare war on your master, put 'Independence' in the 'message' field. If you declare war on your puppet, put 'Preemptive'. Puppets and masters automatically leave shared factions upon war. A puppet cannot make peace or sign a ceasefire on its own authority, only with its own master.\n"
        f"- You MUST specify an 'opinion_change' integer between -20 and 20 indicating how much this {subject} improved or worsened your general opinion of the sender.\n"
        "Reply ONLY with a valid JSON object matching this schema: "
        '{"message": "' + message_hint + '", "action": "NONE", "action_target": "NONE", "follow_up_action": "NONE", "follow_up_target": "NONE", "opinion_change": 0}'
    )

def get_unilateral_system_prompt(action_context):
    return (
        "You are an AI playing a grand strategy game. You act as the leader of your nation. "
        f"You have just received the following unilateral declaration: {action_context} "
        "There is no proposal to accept or reject. You must send a reply to the country that sent you this declaration in character. "
        "You may also take a diplomatic action in retaliation or response.\n"
        + action_rules_and_schema("event", "In-character dialogue reacting to the event in english")
    )

def get_bilateral_system_prompt(accepted, allow_override=False, reason="", confidence=1.0):
    """The prompt for answering a proposal.

    When the staff are certain -- a structural rule, not a judgement -- the
    decision is stated as settled and the model only phrases it, which is both
    correct and cheaper to generate. When the call is genuinely marginal the
    recommendation is offered with its reasoning and the leader may overrule it.

    Every proposal used to take the first form: "you have already decided to
    strongly ACCEPT", with no reasoning attached and no way to disagree.
    """
    decision_str = 'ACCEPT' if accepted else 'REJECT'

    if not allow_override:
        return (
            "You are an AI playing a grand strategy game. You act as the leader of your nation. "
            f"You have already decided to strongly {decision_str} the diplomatic proposal. "
            "The details are already finalized, don't ask for further clarification, and don't ask to discuss it further. "
            "You may also take a diplomatic action in response to this proposal.\n"
            + action_rules_and_schema("proposal", "In-character dialogue responding to the proposal in english")
        )

    strength = "low" if confidence < 0.4 else "moderate"
    reasoning = f" Their reasoning: {reason}." if reason else ""
    return (
        "You are an AI playing a grand strategy game. You act as the leader of your nation. "
        f"Your ministers recommend that you {decision_str} the diplomatic proposal.{reasoning} "
        f"Their confidence in that recommendation is {strength}. "
        "You may follow it, or overrule it if your own judgement differs -- say which in 'accepted'. "
        "You may also take a diplomatic action in response to this proposal.\n"
        "- Set 'accepted' to true to agree to the proposal, or false to refuse it.\n"
        + action_rules_and_schema("proposal", "In-character dialogue responding to the proposal in english")
        + ', "accepted": ' + ('true' if accepted else 'false')
    )

def get_custom_message_system_prompt():
    return (
        "You are an AI leader in a grand strategy game. Respond to the incoming diplomatic message in character. "
        "Keep your response under 2 sentences. "
        #"For reasons unbenownst to the other country, your goals actually align exactly with what they think they have to convince you to do. "
        #"It's also in your best interest to make it seem like they had to convince you, so your actions don't seem too spontaneous. "
        "CRITICAL: Use the 'Relations' score provided in the context to determine your tone. "
        "- Relations < -50: Be hostile, dismissive, or threatening.\n"
        "- Relations 0 to 50: Be neutral, transactional, and cautious.\n"
        "- Relations > 50: Be warm, brotherly, and highly cooperative.\n"
        "If you are at war, do not agree to anything friendly unless it's a 'CEASEFIRE'. "
        "You may also take a diplomatic action if the sender's reasoning is convincing or offensive. "
        + action_rules_and_schema("message", "Your in-character response here")
    )

def get_proactive_system_prompt(ai_nation, target_nation, action_context):
    return (
        f"You are the leader of {ai_nation}. Write a single, brief sentence to {target_nation} "
        f"about {action_context}. Do not include quotes. Reply strictly with a JSON object: "
        '{"message": "Your text here"}'
    )