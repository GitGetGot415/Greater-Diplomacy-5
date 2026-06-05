import json
import requests
import urllib.parse
import http.client
import socket
from google import genai
from google.genai import types
import data.constants as c
from data import queries
from map_logic.ai import ai_prompts

# --- NEW GLOBAL ABORT FLAG ---
FORCE_SKIP = False
CURRENT_TURN_ID = 0
ACTIVE_OLLAMA_CONNECTIONS = []

def abort_ai_generation():
    """Forcefully kills local AI generation by dropping OS sockets and flushing VRAM."""
    # 1. Close all active HTTP TCP sockets to instantly snap threads out of blocking I/O
    for conn in list(ACTIVE_OLLAMA_CONNECTIONS):
        try:
            # --- THE TRUE OS-LEVEL SOCKET KILL ---
            # This forces the blocking recv() in the background threads to instantly throw an exception
            if getattr(conn, 'sock', None):
                conn.sock.shutdown(socket.SHUT_RDWR)
            conn.close()
        except Exception:
            pass
    ACTIVE_OLLAMA_CONNECTIONS.clear()
    
    # 2. Tell Ollama to abort and unload to free up the GPU immediately
    if get_ai_mode() == "OLLAMA":
        try:
            url = get_ollama_url().replace("/api/chat", "/api/generate")
            # A tiny 0.1s timeout so the Pygame UI doesn't hang if Ollama's HTTP queue is saturated
            requests.post(url, json={"model": get_ollama_model(), "prompt": "", "keep_alive": 0}, timeout=(0.1, 0.1))
        except:
            pass

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
    return queries.get_settings().get("ai_immersion_level", "LITE")

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

def call_ollama(system_prompt, user_prompt, turn_id=None):
    """Helper to hit local Ollama instance with direct socket control for instant termination."""
    if FORCE_SKIP or (turn_id is not None and turn_id != CURRENT_TURN_ID): return None
    
    url_str = get_ollama_url()
    parsed_url = urllib.parse.urlparse(url_str)
    
    model_name = get_ollama_model()
    
    # 1. Combine system and user prompts to prevent 400 errors on lightweight models
    # that lack a system prompt block in their instruction template (like many 0.5b models).
    combined_prompt = f"{system_prompt}\n\n{user_prompt}"
    
    payload = {
        "model": model_name,
        "messages": [
            {"role": "user", "content": combined_prompt}
        ],
        "stream": True # Stream token-by-token
    }
    
    # Conditionally apply strict JSON formatting if the model supports it natively
    if hasattr(c, 'OLLAMA_JSON_SUPPORTED_MODELS') and any(supported in model_name.lower() for supported in c.OLLAMA_JSON_SUPPORTED_MODELS):
        payload["format"] = "json"
        
    payload_bytes = json.dumps(payload).encode('utf-8')
    
    # Bypass requests and create a raw HTTP connection directly
    conn = None
    if parsed_url.scheme == "https":
        conn = http.client.HTTPSConnection(parsed_url.hostname, parsed_url.port or 443, timeout=300)
    else:
        conn = http.client.HTTPConnection(parsed_url.hostname, parsed_url.port or 80, timeout=300)
        
    ACTIVE_OLLAMA_CONNECTIONS.append(conn)
    
    try:
        headers = {"Content-Type": "application/json", "Connection": "close"}
        
        # This initiates the blocking request. If conn.sock.shutdown() is called from the UI thread,
        # the OS will instantly throw a ConnectionAbortedError here and wake up this thread.
        conn.request("POST", parsed_url.path, body=payload_bytes, headers=headers)
        response = conn.getresponse()
        
        if response.status >= 400:
            # 2. Extract and decode the actual error message from Ollama
            error_body = response.read().decode('utf-8')
            try:
                # Try to parse it cleanly if it's a JSON error response
                error_json = json.loads(error_body)
                err_msg = error_json.get("error", error_body)
            except:
                err_msg = error_body
                
            return {"message": f"OLLAMA HTTP ERROR {response.status}: {err_msg}"}
        
        full_text = ""
        # Iterate over the stream as it generates
        while True:
            if FORCE_SKIP or (turn_id is not None and turn_id != CURRENT_TURN_ID):
                conn.close()
                return None
                
            line = response.readline()
            if not line:
                break
                
            line_str = line.decode('utf-8').strip()
            if line_str:
                chunk = json.loads(line_str)
                full_text += chunk.get("message", {}).get("content", "")
                
        # Parse the final reconstructed string
        try:
            return json.loads(full_text)
        except json.JSONDecodeError:
            return {"message": f"JSON ERROR: {full_text}"} # Fallback if it fails strict parsing
            
    except Exception as e:
        # If the connection was forcefully closed by the skip button, fail silently
        if FORCE_SKIP or (turn_id is not None and turn_id != CURRENT_TURN_ID):
            return None
        print(f"Ollama Connection Error: {e}")
        return {"message": f"OLLAMA ERROR: {str(e)}"}
    finally:
        if conn in ACTIVE_OLLAMA_CONNECTIONS:
            ACTIVE_OLLAMA_CONNECTIONS.remove(conn)
        try:
            conn.close()
        except:
            pass

def evaluate_diplomatic_proposal(nation_data, active_nations, ai_nation, sender_nation, action_type, custom_msg="", human_players=None, turn_id=None):
    if FORCE_SKIP or (turn_id is not None and turn_id != CURRENT_TURN_ID): 
        return {
            "accepted": True, 
            "message": ai_prompts.AI_FALLBACK_RESPONSES["GENERIC_ACCEPT"], 
            "action": "NONE", "action_target": "NONE", 
            "follow_up_action": "NONE", "follow_up_target": "NONE", 
            "opinion_change": 0
        }
    
    if human_players is None:
        human_players = []

    mode = get_ai_mode()
    immersion = get_ai_immersion_level()
    
    ai_stats = nation_data.get(ai_nation, {})
    at_war = len(ai_stats.get("at_war_with", [])) > 0
    in_faction = bool(ai_stats.get("faction", ""))

    accepted = False
    
    # --- IMPROVED FACTION LOGIC ---
    # 1. Check for basic aggressive acceptance
    if at_war and not in_faction:
        if action_type in ["FACTION_INVITE", "CREATE_FACTION", "CEASEFIRE", "PEACE_TREATY"]:
            accepted = True
            
    # 2. Check for Join Faction Requests (If we are the leader)
    if action_type == "JOIN_FACTION_REQ" and ai_stats.get("is_faction_leader", False):
        relation_score = queries.get_relation_score(ai_nation, sender_nation, nation_data)
        
        # Calculate shared enemies
        ai_enemies = set(ai_stats.get("at_war_with", []))
        sender_enemies = set(nation_data.get(sender_nation, {}).get("at_war_with", []))
        share_enemies = bool(ai_enemies.intersection(sender_enemies))
        
        # Accept if relations are good OR they are helping us fight common threats
        # Using a constant for threshold, defaulting to 50 if undefined
        threshold = getattr(c, 'AI_RELATION_FACTION_THRESHOLD', 50)
        if relation_score >= threshold or share_enemies:
            accepted = True

    # 3. Always accept peace deals for now (Per the user request)
    if action_type in ["PEACE_TREATY", "CEASEFIRE"]:
        accepted = True
    # ------------------------------

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
            
        return {
            "accepted": accepted, 
            "message": fallback, 
            "action": "NONE", "action_target": "NONE", 
            "follow_up_action": "NONE", "follow_up_target": "NONE", 
            "opinion_change": 0
        }

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
        result = call_ollama(system_prompt, user_prompt, turn_id)
        if result:
            return {
                "accepted": accepted,
                "message": result.get("message", f"OLLAMA ERROR: Unknown Format"),
                "action": result.get("action", "NONE"),
                "action_target": result.get("action_target", "NONE"),
                "follow_up_action": result.get("follow_up_action", "NONE"),
                "follow_up_target": result.get("follow_up_target", "NONE"),
                "opinion_change": result.get("opinion_change", 0)
            }
        return { "accepted": accepted, "message": "OLLAMA ERROR: No response", "action": "NONE", "action_target": "NONE", "follow_up_action": "NONE", "follow_up_target": "NONE", "opinion_change": 0 }
    elif mode == "CHATGPT":
        print("[LLM] Custom ChatGPT hook to be placed here.")
        return { "accepted": accepted, "message": ai_prompts.AI_FALLBACK_RESPONSES["GENERIC_ACCEPT"], "action": "NONE", "action_target": "NONE", "follow_up_action": "NONE", "follow_up_target": "NONE", "opinion_change": 0 }
    elif mode == "CLAUDE":
        print("[LLM] Custom Claude hook to be placed here.")
        return { "accepted": accepted, "message": ai_prompts.AI_FALLBACK_RESPONSES["GENERIC_ACCEPT"], "action": "NONE", "action_target": "NONE", "follow_up_action": "NONE", "follow_up_target": "NONE", "opinion_change": 0 }

    # Fallback to Gemini
    try:
        client = genai.Client(api_key=get_gemini_api_key())
        response = client.models.generate_content(
            model=get_gemini_model(),
            contents=f"{system_prompt}\n\n{user_prompt}",
            config=types.GenerateContentConfig(response_mime_type="application/json")
        )
        
        if FORCE_SKIP or (turn_id is not None and turn_id != CURRENT_TURN_ID): 
            return { "accepted": accepted, "message": ai_prompts.AI_FALLBACK_RESPONSES["GENERIC_ACCEPT"], "action": "NONE", "action_target": "NONE", "follow_up_action": "NONE", "follow_up_target": "NONE", "opinion_change": 0 }

        reply_json = json.loads(response.text)
        
        try:
            op_val = int(reply_json.get("opinion_change", 0))
        except:
            op_val = 0
            
        return {
            "accepted": accepted,
            "message": reply_json.get("message", f"JSON ERROR: Parsed fine but missing 'message' key."),
            "action": reply_json.get("action", "NONE"),
            "action_target": reply_json.get("action_target", "NONE"),
            "follow_up_action": reply_json.get("follow_up_action", "NONE"),
            "follow_up_target": reply_json.get("follow_up_target", "NONE"),
            "opinion_change": op_val
        }
    except Exception as e:
        print(f"API Error: {e}")
        return {"accepted": accepted, "message": f"API ERROR: {str(e)}", "action": "NONE", "action_target": "NONE", "follow_up_action": "NONE", "follow_up_target": "NONE", "opinion_change": 0}

def process_custom_message(nation_data, active_nations, ai_nation, sender_nation, message_content, human_players=None, turn_id=None):
    if FORCE_SKIP or (turn_id is not None and turn_id != CURRENT_TURN_ID): 
        return { "message": ai_prompts.AI_FALLBACK_RESPONSES["GENERIC_MESSAGE"], "action": "NONE", "action_target": "NONE", "follow_up_action": "NONE", "follow_up_target": "NONE", "opinion_change": 0 }
    
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
            "follow_up_action": "NONE", "follow_up_target": "NONE",
            "opinion_change": 0
        }

    print(f"[LLM CALL] {ai_nation} is drafting a reply to {sender_nation}... (Mode: {mode})")

    context = get_world_context(nation_data, active_nations, ai_nation, sender_nation)
    system_prompt = ai_prompts.get_custom_message_system_prompt()
    user_prompt = f"{context}\nMessage from {sender_nation}: '{message_content}'"
    
    if mode == "OLLAMA":
        result = call_ollama(system_prompt, user_prompt, turn_id)
        if result:
            return {
                "message": result.get("message", f"OLLAMA ERROR: Unknown Format"), 
                "action": result.get("action", "NONE"),
                "action_target": result.get("action_target", "NONE"),
                "follow_up_action": result.get("follow_up_action", "NONE"),
                "follow_up_target": result.get("follow_up_target", "NONE"),
                "opinion_change": result.get("opinion_change", 0)
            }
        return {
            "message": "OLLAMA ERROR: No response", 
            "action": "NONE", "action_target": "NONE", 
            "follow_up_action": "NONE", "follow_up_target": "NONE", "opinion_change": 0
        }
    elif mode == "CHATGPT":
        print("[LLM] Custom ChatGPT hook to be placed here.")
        return { "message": ai_prompts.AI_FALLBACK_RESPONSES["GENERIC_MESSAGE"], "action": "NONE", "action_target": "NONE", "follow_up_action": "NONE", "follow_up_target": "NONE", "opinion_change": 0 }
    elif mode == "CLAUDE":
        print("[LLM] Custom Claude hook to be placed here.")
        return { "message": ai_prompts.AI_FALLBACK_RESPONSES["GENERIC_MESSAGE"], "action": "NONE", "action_target": "NONE", "follow_up_action": "NONE", "follow_up_target": "NONE", "opinion_change": 0 }

    try:
        client = genai.Client(api_key=get_gemini_api_key())
        response = client.models.generate_content(
            model=get_gemini_model(),
            contents=f"{system_prompt}\n\n{user_prompt}",
            config=types.GenerateContentConfig(response_mime_type="application/json")
        )
        
        if FORCE_SKIP or (turn_id is not None and turn_id != CURRENT_TURN_ID): 
            return { "message": ai_prompts.AI_FALLBACK_RESPONSES["GENERIC_MESSAGE"], "action": "NONE", "action_target": "NONE", "follow_up_action": "NONE", "follow_up_target": "NONE", "opinion_change": 0 }

        reply_json = json.loads(response.text)
        
        try:
            op_val = int(reply_json.get("opinion_change", 0))
        except:
            op_val = 0
                
        return {
            "message": reply_json.get("message", f"JSON ERROR: Parsed fine but missing 'message' key."), 
            "action": reply_json.get("action", "NONE"),
            "action_target": reply_json.get("action_target", "NONE"),
            "follow_up_action": reply_json.get("follow_up_action", "NONE"),
            "follow_up_target": reply_json.get("follow_up_target", "NONE"),
            "opinion_change": op_val
        }
    except Exception as e:
        print(f"API Error: {e}")
        return {
            "message": f"API ERROR: {str(e)}", 
            "action": "NONE", "action_target": "NONE", 
            "follow_up_action": "NONE", "follow_up_target": "NONE",
            "opinion_change": 0
        }

def generate_proactive_text(nation_data, active_nations, ai_nation, target_nation, action_context, human_players=None, turn_id=None):
    """Generates a quick one-liner for proactive hardcoded AI actions."""
    if FORCE_SKIP or (turn_id is not None and turn_id != CURRENT_TURN_ID): return None
    
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
        result = call_ollama(system_prompt, user_prompt, turn_id)
        return result.get("message", "OLLAMA ERROR: Unknown Format") if result else "OLLAMA ERROR: No response"

    try:
        client = genai.Client(api_key=get_gemini_api_key())
        response = client.models.generate_content(
            model=get_gemini_model(),
            contents=f"{system_prompt}\n\n{user_prompt}",
            config=types.GenerateContentConfig(response_mime_type="application/json")
        )
        
        if FORCE_SKIP or (turn_id is not None and turn_id != CURRENT_TURN_ID): return None
            
        return json.loads(response.text).get("message", "JSON ERROR: Parsed fine but missing 'message' key.")
    except Exception as e:
        return f"API ERROR: {str(e)}"