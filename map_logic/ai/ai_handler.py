import json
import requests
import random
from google import genai
from google.genai import types
import data.constants as c
from data import queries
from map_logic.ai import ai_prompts

# --- NEW GLOBAL ABORT FLAG ---
FORCE_SKIP = False

def get_gemini_api_key():
    """Helper to dynamically fetch the saved key from cache."""
    settings = queries.get_settings()
    return settings.get("gemini_api_key", settings.get("api_key", ""))

def get_chatgpt_api_key():
    return queries.get_settings().get("chatgpt_api_key", "")

def get_claude_api_key():
    return queries.get_settings().get("claude_api_key", "")

def get_ai_mode():
    """Reads the settings config to see which AI is active."""
    return queries.get_settings().get("ai_mode", c.DEFAULT_AI_MODE)

def get_ai_immersion_level():
    """Reads the settings config to see which immersion level is active."""
    return queries.get_settings().get("ai_immersion_level", "FULL")

# --- MODEL / URL GETTERS ---

def get_gemini_model():
    return queries.get_settings().get("gemini_model", getattr(c, 'DEFAULT_GEMINI_MODEL', "gemini-2.5-flash"))

def get_chatgpt_model():
    return queries.get_settings().get("chatgpt_model", getattr(c, 'DEFAULT_CHATGPT_MODEL', "gpt-4o-mini"))

def get_claude_model():
    return queries.get_settings().get("claude_model", getattr(c, 'DEFAULT_CLAUDE_MODEL', "claude-3-haiku-20240307"))

def get_ollama_model():
    """Reads the settings config to see which Ollama model is requested."""
    return queries.get_settings().get("ollama_model", getattr(c, 'DEFAULT_OLLAMA_MODEL', "llama3"))

def get_ollama_url():
    """Reads the URL from the settings. Defaults to localhost if empty."""
    url = queries.get_settings().get("ollama_api_key", "").strip()
    return url if url else "http://localhost:11434/api/chat"

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
        
        rels = []
        if wars: rels.append(f"at war with {', '.join(wars)}")
        if fac: rels.append(f"in the faction '{fac}'")
        
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

def call_ollama(system_prompt, user_prompt):
    """Helper to hit local Ollama instance with streaming to allow instant termination."""
    if FORCE_SKIP: return None
    
    url = get_ollama_url()
    payload = {
        "model": get_ollama_model(),
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "format": "json",
        "stream": True # <--- THE FIX: Stream token-by-token
    }
    try:
        response = requests.post(url, json=payload, timeout=45, stream=True)
        response.raise_for_status()
        
        full_text = ""
        # Iterate over the stream as it generates
        for line in response.iter_lines():
            # If the user clicked skip midway through generation, sever the TCP connection!
            if FORCE_SKIP:
                response.close()
                return None
                
            if line:
                chunk = json.loads(line)
                full_text += chunk.get("message", {}).get("content", "")
                
        # Parse the final reconstructed string
        try:
            return json.loads(full_text)
        except json.JSONDecodeError:
            return {"message": full_text} # Fallback if it fails strict parsing
            
    except Exception as e:
        print(f"Ollama Python Error: {e}")
        return None

def evaluate_diplomatic_proposal(nation_data, active_nations, ai_nation, sender_nation, action_type, custom_msg="", human_players=None):
    if FORCE_SKIP: return True, ai_prompts.AI_FALLBACK_RESPONSES["GENERIC_ACCEPT"]
    
    if human_players is None:
        human_players = []

    mode = get_ai_mode()
    immersion = get_ai_immersion_level()
    
    # stuff to maybe replace the hardcoded true?
    rel_score = queries.get_relation_score(ai_nation, sender_nation, nation_data)
    
    # Base logic: If they hate us (-100), they won't accept anything but a ceasefire.
    # If they like us (80+), they are very likely to accept.
    chance = 50 + (rel_score / 2) # Scale -100 to 100 into 0% to 100% chance
    
    # War specific logic
    if rel_score <= -100 and action_type != "CEASEFIRE":
        accepted = False
    else:
        accepted = random.randint(0, 100) < chance

    # Ensure 50/50 strict logic regardless of model behavior
    accepted = random.choice([True, False])
    # actually true, always
    accepted = True

    # Check if this is an AI talking to an AI
    is_ai_to_ai = (ai_nation not in human_players) and (sender_nation not in human_players)
    has_custom_msg = bool(custom_msg.strip())

    # Apply LITE / FULL / ABSOLUTE AI rules cleanly
    if immersion == "LITE":
        # AI is off UNLESS a human sent a custom message
        use_lite_logic = not (has_custom_msg and not is_ai_to_ai)
    elif immersion == "FULL":
        use_lite_logic = is_ai_to_ai
    else: # ABSOLUTE
        use_lite_logic = False
        
    if mode == "OFF":
        use_lite_logic = True

    if use_lite_logic:
        # --- OPTIMIZATION: Stripped hardcoded text, defer to dictionary strictly ---
        if action_type == "WAR_DECLARATION":
            fallback = ai_prompts.AI_FALLBACK_RESPONSES["BETRAYAL"]
        elif action_type == "LEAVE_FACTION":
            fallback = ai_prompts.AI_FALLBACK_RESPONSES["FACTION_ABANDONED"]
        elif action_type == "DISBAND_FACTION":
            fallback = ai_prompts.AI_FALLBACK_RESPONSES["FACTION_DISBANDED"]
        elif action_type == "JOIN_WARS":
            fallback = ai_prompts.AI_FALLBACK_RESPONSES["ACCEPTED_HELP"]
        elif action_type == "BREAK_ALLIANCE":
            fallback = ai_prompts.AI_FALLBACK_RESPONSES["ALLIANCE_BROKEN"]
        elif action_type == "KICK_FACTION_MEMBER":
            fallback = ai_prompts.AI_FALLBACK_RESPONSES["KICKED_FROM_FACTION"]
        elif action_type == "CALL_TO_ARMS":
            fallback = ai_prompts.AI_FALLBACK_RESPONSES["ANSWERED_CALL"]
        else:
            fallback = ai_prompts.AI_FALLBACK_RESPONSES["AI_OFF_ACCEPT"] if accepted else ai_prompts.AI_FALLBACK_RESPONSES["AI_OFF_REJECT"]
        return accepted, fallback

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

    if mode == "OLLAMA":
        result = call_ollama(system_prompt, user_prompt)
        if result:
            return accepted, result.get("message", ai_prompts.AI_FALLBACK_RESPONSES["GENERIC_ACCEPT"])
        return accepted, ai_prompts.AI_FALLBACK_RESPONSES["OLLAMA_ERROR"]
    elif mode == "CHATGPT":
        print("[LLM] Custom ChatGPT hook to be placed here.")
        return accepted, ai_prompts.AI_FALLBACK_RESPONSES["GENERIC_ACCEPT"]
    elif mode == "CLAUDE":
        print("[LLM] Custom Claude hook to be placed here.")
        return accepted, ai_prompts.AI_FALLBACK_RESPONSES["GENERIC_ACCEPT"]

    # Fallback to Gemini
    try:
        client = genai.Client(api_key=get_gemini_api_key())
        response = client.models.generate_content(
            model=get_gemini_model(),
            contents=f"{system_prompt}\n\n{user_prompt}",
            config=types.GenerateContentConfig(response_mime_type="application/json")
        )
        reply_json = json.loads(response.text)
        return accepted, reply_json.get("message", ai_prompts.AI_FALLBACK_RESPONSES["GENERIC_ACCEPT"])
    except Exception as e:
        print(f"Gemini Error: {e}")
        return accepted, ai_prompts.AI_FALLBACK_RESPONSES["API_ERROR"]

def process_custom_message(nation_data, active_nations, ai_nation, sender_nation, message_content, human_players=None):
    if FORCE_SKIP: 
        return { "message": ai_prompts.AI_FALLBACK_RESPONSES["GENERIC_MESSAGE"], "action": "NONE", "action_target": "NONE", "follow_up_action": "NONE", "follow_up_target": "NONE" }
    
    if human_players is None:
        human_players = []

    mode = get_ai_mode()
    immersion = get_ai_immersion_level()
    
    is_ai_to_ai = (ai_nation not in human_players) and (sender_nation not in human_players)
    
    # Apply LITE / FULL / ABSOLUTE AI rules cleanly
    if immersion == "LITE":
        use_lite_logic = is_ai_to_ai # Allow if sender is human
    elif immersion == "FULL":
        use_lite_logic = is_ai_to_ai
    else: # ABSOLUTE
        use_lite_logic = False
        
    if mode == "OFF":
        use_lite_logic = True

    if use_lite_logic:
        return {
            "message": ai_prompts.AI_FALLBACK_RESPONSES["AI_OFF_MESSAGE"], 
            "action": "NONE", "action_target": "NONE", 
            "follow_up_action": "NONE", "follow_up_target": "NONE"
        }

    print(f"[LLM CALL] {ai_nation} is drafting a reply to {sender_nation}... (Mode: {mode})")

    context = get_world_context(nation_data, active_nations, ai_nation, sender_nation)
    system_prompt = ai_prompts.get_custom_message_system_prompt()
    user_prompt = f"{context}\nMessage from {sender_nation}: '{message_content}'"
    
    if mode == "OLLAMA":
        result = call_ollama(system_prompt, user_prompt)
        if result:
            return {
                "message": result.get("message", ai_prompts.AI_FALLBACK_RESPONSES["GENERIC_MESSAGE"]), 
                "action": result.get("action", "NONE"),
                "action_target": result.get("action_target", "NONE"),
                "follow_up_action": result.get("follow_up_action", "NONE"),
                "follow_up_target": result.get("follow_up_target", "NONE")
            }
        return {
            "message": ai_prompts.AI_FALLBACK_RESPONSES["OLLAMA_ERROR"], 
            "action": "NONE", "action_target": "NONE", 
            "follow_up_action": "NONE", "follow_up_target": "NONE"
        }
    elif mode == "CHATGPT":
        print("[LLM] Custom ChatGPT hook to be placed here.")
        return { "message": ai_prompts.AI_FALLBACK_RESPONSES["GENERIC_MESSAGE"], "action": "NONE", "action_target": "NONE", "follow_up_action": "NONE", "follow_up_target": "NONE" }
    elif mode == "CLAUDE":
        print("[LLM] Custom Claude hook to be placed here.")
        return { "message": ai_prompts.AI_FALLBACK_RESPONSES["GENERIC_MESSAGE"], "action": "NONE", "action_target": "NONE", "follow_up_action": "NONE", "follow_up_target": "NONE" }

    try:
        client = genai.Client(api_key=get_gemini_api_key())
        response = client.models.generate_content(
            model=get_gemini_model(),
            contents=f"{system_prompt}\n\n{user_prompt}",
            config=types.GenerateContentConfig(response_mime_type="application/json")
        )
        reply_json = json.loads(response.text)
        
        ai_action = reply_json.get("action", "NONE")
        act_target = reply_json.get("action_target", "NONE")
        if ai_action == "WAR_DECLARATION":
            from data import queries
            if queries.are_at_war(ai_nation, act_target, nation_data):
                print(f"[AI GUARDRAIL] Prevented {ai_nation} from declaring war on existing enemy {act_target}.")
                ai_action = "NONE"

        # --- Extract Opinion Mod ---
        try:
            op_val = int(reply_json.get("opinion_change", 0))
            if op_val != 0:
                queries.add_temporary_modifier(ai_nation, sender_nation, "general", op_val, nation_data)
        except Exception as e:
            pass
                
        return {
            "message": reply_json.get("message", ai_prompts.AI_FALLBACK_RESPONSES["GENERIC_MESSAGE"]), 
            "action": ai_action,
            "action_target": act_target,
            "follow_up_action": reply_json.get("follow_up_action", "NONE"),
            "follow_up_target": reply_json.get("follow_up_target", "NONE")
        }
    except Exception as e:
        print(f"Gemini Error: {e}")
        return {
            "message": ai_prompts.AI_FALLBACK_RESPONSES["GENERIC_MESSAGE"], 
            "action": "NONE", "action_target": "NONE", 
            "follow_up_action": "NONE", "follow_up_target": "NONE"
        }

def generate_proactive_text(nation_data, active_nations, ai_nation, target_nation, action_context, human_players=None):
    """Generates a quick one-liner for proactive hardcoded AI actions."""
    if FORCE_SKIP: return None
    
    if human_players is None:
        human_players = []
        
    mode = get_ai_mode()
    immersion = get_ai_immersion_level()
    
    is_ai_to_ai = (ai_nation not in human_players) and (target_nation not in human_players)
    use_lite_logic = (mode == "OFF") or (immersion == "LITE") or (immersion == "FULL" and is_ai_to_ai)
    
    if use_lite_logic:
        return None 
        
    context = get_world_context(nation_data, active_nations, ai_nation, target_nation)
    system_prompt = ai_prompts.get_proactive_system_prompt(ai_nation, target_nation, action_context)
    user_prompt = f"{context}\nWrite the message."
    
    if mode == "OLLAMA":
        result = call_ollama(system_prompt, user_prompt)
        return result.get("message") if result else None

    try:
        client = genai.Client(api_key=get_gemini_api_key())
        response = client.models.generate_content(
            model=get_gemini_model(),
            contents=f"{system_prompt}\n\n{user_prompt}",
            config=types.GenerateContentConfig(response_mime_type="application/json")
        )
        return json.loads(response.text).get("message")
    except Exception:
        return None