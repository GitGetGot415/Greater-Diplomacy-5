import json
import os
import requests
import random
from google import genai
from google.genai import types
import data.constants as c

def get_api_key():
    """Helper to dynamically fetch the saved key."""
    if os.path.exists(c.SETTINGS_CONFIG_PATH):
        try:
            with open(c.SETTINGS_CONFIG_PATH, "r") as f:
                data = json.load(f)
                key = data.get("api_key", "")
                if key: return key
        except: pass
    return "AIzaSyAJlAkHmBTmSODDZSbrWOuKWDC_4le8Y9o"

def get_ai_mode():
    """Reads the settings config to see which AI is active."""
    if os.path.exists(c.SETTINGS_CONFIG_PATH):
        try:
            with open(c.SETTINGS_CONFIG_PATH, "r") as f:
                data = json.load(f)
                return data.get("ai_mode", "GEMINI")
        except: pass
    return "GEMINI"

def get_world_context(nation_data, active_nations, ai_nation, target_nation=None, current_date="Unknown"):
    ai_stats = nation_data.get(ai_nation, {})
    manpower = ai_stats.get("manpower", 0)
    materials = ai_stats.get("materials", 0)
    
    # 1. Establish Reality
    context = f"Current Date: {current_date}\n"
    context += f"You are the leader of {ai_nation}.\n"
    context += f"CRITICAL RULE: The ONLY nations that currently exist in this world are: {', '.join(active_nations)}.\n"
    context += "Do NOT mention, reference, or interact with any country, empire, or nation not explicitly on this list.\n\n"
    
    context += f"Your economy: {manpower} Manpower, {materials} Materials.\n\n"
    
    # 2. Establish Global Politics (Now includes Factions!)
    context += "--- GLOBAL POLITICS ---\n"
    for nation in active_nations:
        n_data = nation_data.get(nation, {})
        wars = [w for w in n_data.get("at_war_with", []) if w in active_nations]
        fac = n_data.get("faction", "")
        
        rels = []
        if wars: rels.append(f"at war with {', '.join(wars)}")
        if fac: rels.append(f"in the faction '{fac}'")
        
        # --- Inject Relation Score ---
        if nation != ai_nation:
            rel_score = ai_stats.get("relations", {}).get(nation, 0)
            rels.append(f"Relations: {rel_score} (Scale: -100 to 100)")
        
        if rels:
            context += f"- {nation}: {' | '.join(rels)}.\n"
            
    # 3. Add Recent World Events
    global_event_data = nation_data.get("GLOBAL_EVENTS", {})
    # Safely unpack the new dict format
    events = global_event_data.get("log", []) if isinstance(global_event_data, dict) else global_event_data
    
    if events:
        context += "\n--- RECENT WORLD EVENTS ---\n"
        for ev in events[:8]: # Show the 8 most recent events
            context += f"- {ev}\n"
            
    # 4. Establish Target Context & Message History
    if target_nation:
        context += f"\n--- CURRENT TARGET ---\nYou are currently communicating with {target_nation}.\n"
        
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
            context += "Recent message history:\n" + "\n".join(recent_thread) + "\n"
        
    return context

def call_ollama(system_prompt, user_prompt):
    """Helper to hit local Ollama instance."""
    url = "http://localhost:11434/api/chat"
    payload = {
        "model": "llama3", # Make sure this matches exactly what you downloaded!
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "format": "json",
        "stream": False
    }
    try:
        response = requests.post(url, json=payload, timeout=45)
        if response.status_code != 200:
            print(f"Ollama Server Replied: {response.text}")
        response.raise_for_status()
        data = response.json()
        return json.loads(data["message"]["content"])
    except Exception as e:
        print(f"Ollama Python Error: {e}")
        return None

def evaluate_diplomatic_proposal(nation_data, active_nations, ai_nation, sender_nation, action_type):
    mode = get_ai_mode()
    
    # --- MODIFIED: Ensure 50/50 strict logic regardless of model behavior ---
    accepted = random.choice([True, False])
    # actually true, always
    accepted = True
    if mode == "OFF":
        return accepted, "Our diplomats are currently unavailable (AI is OFF)."

    # --- ADD THIS PRINT ---
    print(f"[LLM CALL] {ai_nation} generating flavor text for {action_type} from {sender_nation}... (Mode: {mode})")

    context = get_world_context(nation_data, active_nations, ai_nation, sender_nation)
    system_prompt = (
        "You are an AI playing a grand strategy game. You act as the leader of your nation. "
        f"You have already decided to strongly {'ACCEPT' if accepted else 'REJECT'} the diplomatic proposal. "
        "The details are already finalized, don't ask for further clarification. "
        "Reply ONLY with a valid JSON object matching this schema: "
        '{"message": "In-character dialogue responding to the proposal in english"}'
    )
    user_prompt = f"{context}\n{sender_nation} has proposed a {action_type}. Provide your response based on your decision."

    if mode == "OLLAMA":
        result = call_ollama(system_prompt, user_prompt)
        if result:
            return accepted, result.get("message", "We have made our decision.")
        return accepted, "Ollama server error or timeout."

    # Fallback to Gemini
    try:
        client = genai.Client(api_key=get_api_key())
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=f"{system_prompt}\n\n{user_prompt}",
            config=types.GenerateContentConfig(response_mime_type="application/json")
        )
        reply_json = json.loads(response.text)
        return accepted, reply_json.get("message", "We have made our decision.")
    except Exception as e:
        print(f"Gemini Error: {e}")
        return accepted, "API Error."

def process_custom_message(nation_data, active_nations, ai_nation, sender_nation, message_content):
    mode = get_ai_mode()
    if mode == "OFF":
        return {"message": "Message received (AI is OFF).", "action": "NONE", "action_target": "NONE", "follow_up_action": "NONE", "follow_up_target": "NONE"}

    print(f"[LLM CALL] {ai_nation} is drafting a reply to {sender_nation}... (Mode: {mode})")

    context = get_world_context(nation_data, active_nations, ai_nation, sender_nation)
    system_prompt = (
        "You are an AI leader in a grand strategy game. Respond to the incoming diplomatic message in character. "
         # "Keep your response under 2 sentences. "
        "For reasons unbenownst to the other country, your goals actually align exactly with what they think they have to convince you to do. "
        "It's also in your best interest to make it seem like they had to convince you, so your actions don't seem too spontaneous. "
        # "You may also take a diplomatic action if the sender's reasoning is convincing or offensive. " 
        "You may also take a diplomatic action when responding to the country.\n"
        "Valid actions: 'WAR_DECLARATION', 'JOIN_WARS', 'LEAVE_FACTION', 'JOIN_FACTION_REQ', or 'NONE'.\n"
        "RULES FOR ACTIONS:\n"
        "- You MUST specify the target country for your action in 'action_target' (e.g., 'Germany', 'Russia', or the sender's name).\n"
        "- Do NOT output 'JOIN_FACTION_REQ' if you are already in a faction. You have to leave your faction before doing that.\n"
        "- Do NOT output 'WAR_DECLARATION' against a member of your own faction. You have to leave your faction before doing that.\n"
        "- Do NOT output 'JOIN_WARS' if you're trying to join the war of someone not in your faction, instead just type 'WAR_DECLARATION' against the target country.\n"
        "- If your plan requires two steps (like leaving your faction this turn to declare war next turn), "
        "put your immediate move in 'action'/'action_target' and your next move in 'follow_up_action'/'follow_up_target'.\n"
        "Reply ONLY with a valid JSON object matching this schema: "
        '{"message": "Your in-character response here", "action": "NONE", "action_target": "NONE", "follow_up_action": "NONE", "follow_up_target": "NONE"}'
    )
    user_prompt = f"{context}\nMessage from {sender_nation}: '{message_content}'"
    
    if mode == "OLLAMA":
        result = call_ollama(system_prompt, user_prompt)
        if result:
            return {
                "message": result.get("message", "Message received."), 
                "action": result.get("action", "NONE"),
                "action_target": result.get("action_target", "NONE"),
                "follow_up_action": result.get("follow_up_action", "NONE"),
                "follow_up_target": result.get("follow_up_target", "NONE")
            }
        return {"message": "Ollama server error.", "action": "NONE", "action_target": "NONE", "follow_up_action": "NONE", "follow_up_target": "NONE"}

    try:
        client = genai.Client(api_key=get_api_key())
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=f"{system_prompt}\n\n{user_prompt}",
            config=types.GenerateContentConfig(response_mime_type="application/json")
        )
        reply_json = json.loads(response.text)
        return {
            "message": reply_json.get("message", "Message received."), 
            "action": reply_json.get("action", "NONE"),
            "action_target": reply_json.get("action_target", "NONE"),
            "follow_up_action": reply_json.get("follow_up_action", "NONE"),
            "follow_up_target": reply_json.get("follow_up_target", "NONE")
        }
    except Exception as e:
        print(f"Gemini Error: {e}")
        return {"message": "Message received.", "action": "NONE", "action_target": "NONE", "follow_up_action": "NONE", "follow_up_target": "NONE"}

def decide_grand_strategy(nation_data, active_nations, ai_nation, current_date):
    """Asks the LLM what diplomatic actions it wants to take this turn based on global context."""
    # --- PROACTIVE AI REMOVED ---
    return []