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
    "PROACTIVE_JOIN_WAR": "May we join you in your war?",
    "PROACTIVE_DECLARE_WAR": "Your occupation of our rightful territory ends now!",
    "PROACTIVE_JOIN_FACTION": "Our enemies are aligned, let us join your faction to stand against them.",

    "CROSS_FACTION_JOIN": "Our requests crossed paths. We are now united!",
    "CROSS_CEASEFIRE": "Mutual ceasefire agreements signed.",
    "CROSS_CALL_TO_ARMS": "Our diplomats crossed paths. We stand together in all our wars!",
    "CROSS_WAR_DECLARATION": "Your diplomat proposing a {action} was executed. We are at WAR!",

    "PROACTIVE_CEASEFIRE": "We offer terms for a ceasefire.",
    "PROACTIVE_CALL_TO_ARMS": "We request your aid in our ongoing conflicts!"
}

# ==========================================
# SYSTEM PROMPTS & CONTEXT GENERATORS
# ==========================================

def build_world_context(current_date, ai_nation, active_nations_str, manpower, materials, politics_str, events_str, target_context_str, target_nation):
    """Assembles the overarching context about the world, economy, and politics."""
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
    """Returns the descriptive context for when an AI initiates a diplomatic move."""
    if action_type == "CEASEFIRE":
        return "offering a ceasefire because our nations cannot physically reach each other"
    elif action_type == "CALL_TO_ARMS":
        return f"calling you to arms in our war against {target}"
    elif action_type == "JOIN_WARS":
        return f"mobilizing our forces to join your war against {target}"
    elif action_type == "WAR_DECLARATION":
        return f"declaring war on {target} to reclaim our rightful core territory"
    elif action_type == "JOIN_FACTION_REQ":
        return "requesting to join your faction to stand against our mutual enemies"
    return ""

def get_unilateral_receive_context(action_type, sender_nation, custom_msg=""):
    """Returns the context for when an AI receives an un-rejectable action (like War)."""
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
    """Returns the context for when an AI receives a bilateral proposal."""
    if action_type == "JOIN_WARS":
        context = f"{sender_nation} is offering to join YOUR ongoing wars."
    elif action_type == "CALL_TO_ARMS":
        context = f"{sender_nation} is calling YOU to arms to join THEIR ongoing wars."
    elif action_type == "FACTION_INVITE":
        context = f"{sender_nation} is inviting you to join THEIR faction."
    elif action_type == "JOIN_FACTION_REQ":
        context = f"{sender_nation} is requesting to join YOUR faction."
    else:
        context = f"{sender_nation} has proposed a {action_type.replace('_', ' ').title()}."

    if custom_msg:
        context += f" They included this official message: '{custom_msg}'"
        
    return context

def get_unilateral_system_prompt(action_context):
    return (
        "You are an AI playing a grand strategy game. You act as the leader of your nation. "
        f"You have just received the following unilateral declaration: {action_context} "
        "There is no proposal to accept or reject. You must send a reply to the country that sent you this declaration in character. "
        "You may also take a diplomatic action in retaliation or response.\n"
        "Valid actions: 'WAR_DECLARATION', 'JOIN_WARS', 'LEAVE_FACTION', 'JOIN_FACTION_REQ', 'CEASEFIRE', 'CALL_TO_ARMS', 'CREATE_FACTION', 'KICK_FACTION_MEMBER', 'DISBAND_FACTION' or 'NONE'.\n"
        "RULES FOR ACTIONS:\n"
        "- You MUST specify the target country for your action in 'action_target' (e.g., 'Germany', 'Russia', or the sender's name).\n"
        "- Do NOT output 'JOIN_FACTION_REQ' if you are already in a faction. You have to leave your faction before doing that.\n"
        "- Do NOT output 'WAR_DECLARATION' against a member of your own faction. You have to leave your faction before doing that.\n"
        "- Do NOT output 'JOIN_WARS' if you're trying to join the war of someone not in your faction, instead just type 'WAR_DECLARATION' against the target country.\n"
        "- If your plan requires two steps (like leaving your faction this turn to declare war next turn), "
        "put your immediate move in 'action'/'action_target' and your next move in 'follow_up_action'/'follow_up_target'.\n"
        "- You MUST specify an 'opinion_change' integer between -20 and 20 indicating how much this event improved or worsened your general opinion of the sender.\n"
        "Reply ONLY with a valid JSON object matching this schema: "
        '{"message": "In-character dialogue reacting to the event in english", "action": "NONE", "action_target": "NONE", "follow_up_action": "NONE", "follow_up_target": "NONE", "opinion_change": 0}'
    )

def get_bilateral_system_prompt(accepted):
    decision_str = 'ACCEPT' if accepted else 'REJECT'
    return (
        "You are an AI playing a grand strategy game. You act as the leader of your nation. "
        f"You have already decided to strongly {decision_str} the diplomatic proposal. "
        "The details are already finalized, don't ask for further clarification, and don't ask to discuss it further. "
        "You may also take a diplomatic action in response to this proposal.\n"
        "Valid actions: 'WAR_DECLARATION', 'JOIN_WARS', 'LEAVE_FACTION', 'JOIN_FACTION_REQ', 'CEASEFIRE', 'CALL_TO_ARMS', 'CREATE_FACTION', 'KICK_FACTION_MEMBER', 'DISBAND_FACTION' or 'NONE'.\n"
        "RULES FOR ACTIONS:\n"
        "- You MUST specify the target country for your action in 'action_target' (e.g., 'Germany', 'Russia', or the sender's name).\n"
        "- Do NOT output 'JOIN_FACTION_REQ' if you are already in a faction. You have to leave your faction before doing that.\n"
        "- Do NOT output 'WAR_DECLARATION' against a member of your own faction. You have to leave your faction before doing that.\n"
        "- Do NOT output 'JOIN_WARS' if you're trying to join the war of someone not in your faction, instead just type 'WAR_DECLARATION' against the target country.\n"
        "- If your plan requires two steps (like leaving your faction this turn to declare war next turn), "
        "put your immediate move in 'action'/'action_target' and your next move in 'follow_up_action'/'follow_up_target'.\n"
        "- You MUST specify an 'opinion_change' integer between -20 and 20 indicating how much this proposal improved or worsened your general opinion of the sender.\n"
        "Reply ONLY with a valid JSON object matching this schema: "
        '{"message": "In-character dialogue responding to the proposal in english", "action": "NONE", "action_target": "NONE", "follow_up_action": "NONE", "follow_up_target": "NONE", "opinion_change": 0}'
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
        #"If you are at war (Relations -100 or lower), do not agree to anything friendly unless it's a 'CEASEFIRE'. "
        "You may also take a diplomatic action if the sender's reasoning is convincing or offensive. " 
        "Valid actions: 'WAR_DECLARATION', 'JOIN_WARS', 'LEAVE_FACTION', 'JOIN_FACTION_REQ', 'CEASEFIRE', 'CALL_TO_ARMS', 'CREATE_FACTION', 'KICK_FACTION_MEMBER', 'DISBAND_FACTION' or 'NONE'.\n"
        "RULES FOR ACTIONS:\n"
        "- You MUST specify the target country for your action in 'action_target' (e.g., 'Germany', 'Russia', or the sender's name).\n"
        "- Do NOT output 'JOIN_FACTION_REQ' if you are already in a faction. You have to leave your faction before doing that.\n"
        "- Do NOT output 'WAR_DECLARATION' against a member of your own faction. You have to leave your faction before doing that.\n"
        "- Do NOT output 'JOIN_WARS' if you're trying to join the war of someone not in your faction, instead just type 'WAR_DECLARATION' against the target country.\n"
        "- If your plan requires two steps (like leaving your faction this turn to declare war next turn), "
        "put your immediate move in 'action'/'action_target' and your next move in 'follow_up_action'/'follow_up_target'.\n"
        "- You MUST specify an 'opinion_change' integer between -20 and 20 indicating how much this message improved or worsened your general opinion of the sender.\n"
        "Reply ONLY with a valid JSON object matching this schema: "
        '{"message": "Your in-character response here", "action": "NONE", "action_target": "NONE", "follow_up_action": "NONE", "follow_up_target": "NONE", "opinion_change": 0}'
    )

def get_proactive_system_prompt(ai_nation, target_nation, action_context):
    return (
        f"You are the leader of {ai_nation}. Write a single, brief sentence to {target_nation} "
        f"about {action_context}. Do not include quotes. Reply strictly with a JSON object: "
        '{"message": "Your text here"}'
    )