import random
import concurrent.futures
import pygame
from map_logic.ai import ai_handler
from map_logic.rendering.font_manager import fonts
import data.constants as c
from data import queries

def log_global_event(nation_data, event_message):
    """Stores world events so the AI can react to them on the next turn."""
    if "GLOBAL_EVENTS" not in nation_data:
        nation_data["GLOBAL_EVENTS"] = {"is_playable": False, "log": [], "news_flash": []}
        
    log = nation_data["GLOBAL_EVENTS"].setdefault("log", [])
    log.insert(0, event_message)
    
    # NEW: Add to news flash for instant AI reactions
    news = nation_data["GLOBAL_EVENTS"].setdefault("news_flash", [])
    news.append(event_message)
    
    # Keep only the last 15 events to prevent the context window from exploding
    if len(log) > 15:
        log.pop()

def get_pending_action(nation_data, player_name, target_name):
    pending = nation_data.get(player_name, {}).get("pending_diplomacy", {})
    info = pending.get(target_name)
    if isinstance(info, dict):
        return info.get("action")
    return info

def toggle_diplomacy_action(nation_data, player_name, target_name, action_type, custom_msg=""):
    pending = nation_data[player_name].setdefault("pending_diplomacy", {})
    current_action = get_pending_action(nation_data, player_name, target_name)
    
    if current_action == action_type:
        info = pending.get(target_name, {})
        if isinstance(info, dict) and info.get("turns", 0) > 0:
            return "Cannot undo! The diplomat has already crossed their borders."
            
        del pending[target_name]
        return f"Undo {action_type.replace('_', ' ').title()}"
        
    elif current_action is not None:
        # NEW: Allow upgrading a drafted text message into a formal diplomatic action
        info = pending.get(target_name, {})
        if isinstance(info, dict) and info.get("action", "").startswith("MSG:") and info.get("turns", 0) == 0:
            if not custom_msg:
                # Inherit the text from the draft if the user didn't provide a new one
                custom_msg = info.get("action")[4:]
        else:
            # Prevents declaring war while an alliance request is pending, etc.
            return "A diplomatic action is already pending with this nation!"
            
    pending[target_name] = {"action": action_type, "turns": 0, "message": custom_msg}
    return "Message drafted. Will send at end of turn."

def queue_text_message(nation_data, player_name, target_name, content):
    pending = nation_data[player_name].setdefault("pending_diplomacy", {})
    current_action = get_pending_action(nation_data, player_name, target_name)
    
    if current_action is not None and not current_action.startswith("MSG:"):
        # NEW: If a formal action is already pending, attach the typed message to it!
        if isinstance(pending.get(target_name), dict):
            pending[target_name]["message"] = content
        return "Message attached to pending action."
        
    pending[target_name] = {"action": f"MSG:{content}", "turns": 0, "message": content}
    return "Message draft saved. Will send at end of turn."

def cancel_text_message(nation_data, player_name, target_name):
    """Safely clears a drafted text message if it hasn't been sent yet."""
    pending = nation_data[player_name].setdefault("pending_diplomacy", {})
    current_action = get_pending_action(nation_data, player_name, target_name)
    
    if current_action and current_action.startswith("MSG:"):
        info = pending.get(target_name, {})
        if isinstance(info, dict) and info.get("turns", 0) > 0:
            return "Cannot undo! Message is already in transit."
            
        del pending[target_name]
        return "Draft cleared."
    return "No drafted message to clear."

def send_message(nation_data, sender, receiver, content, msg_type="TEXT"):
    # 1. Deliver the message to the receiver
    receiver_data = nation_data.get(receiver)
    if receiver_data:
        if "inbox" not in receiver_data:
            receiver_data["inbox"] = []
        
        receiver_data["inbox"].insert(0, {
            "sender": sender, "content": content, "type": msg_type, "read": False
        })

    # 2. Save a "Sent" copy to the sender's inbox
    sender_data = nation_data.get(sender)
    if sender_data:
        if "inbox" not in sender_data:
            sender_data["inbox"] = []
            
        sender_data["inbox"].insert(0, {
            "sender": f"To: {receiver}", "content": content, "type": msg_type, "read": True 
        })

def process_diplomacy_turn(self):
    # --- 0. PROCESS QUEUED AI MULTI-TURN ACTIONS ---
    # We do this first so queued actions slide right into the normal resolution pipeline
    for country_name, data in self.nation_data.items():
        if isinstance(data, dict) and "queued_ai_actions" in data and data["queued_ai_actions"]:
            pending = data.setdefault("pending_diplomacy", {})
            for q_action in data["queued_ai_actions"]:
                target = q_action["target"]
                action_type = q_action["action"]
                
                # --- FIX: Ensure self-targeting actions target the AI itself! ---
                if action_type in ["CREATE_FACTION", "LEAVE_FACTION", "DISBAND_FACTION"]:
                    target = country_name
                
                # Inject it as a fresh action for this turn, bypassing the LLM
                if target not in pending or (isinstance(pending[target], dict) and pending[target].get("turns", 0) == 0):
                    pending[target] = {"action": action_type, "turns": 0, "message": "Following through on our previous declaration."}
            data["queued_ai_actions"] = []

    # --- 0. FIND ALIVE NATIONS ---
    active_nations = queries.get_living_nations(self.map_data)
    active_nations_list = sorted(list(active_nations))

    # --- 1. SIMULTANEOUS ACTION CLASH RESOLUTION ---
    nations = list(self.nation_data.keys())
    for i in range(len(nations)):
        for j in range(i + 1, len(nations)):
            nation_a = nations[i]
            nation_b = nations[j]
            
            a_data = self.nation_data[nation_a].get("pending_diplomacy", {})
            b_data = self.nation_data[nation_b].get("pending_diplomacy", {})
            
            a_info = a_data.get(nation_b)
            b_info = b_data.get(nation_a)
            
            if isinstance(a_info, dict) and a_info.get("turns", 0) == 0 and \
               isinstance(b_info, dict) and b_info.get("turns", 0) == 0:
                
                a_action = a_info.get("action")
                b_action = b_info.get("action")
                
                if a_action == "JOIN_FACTION_REQ" and b_action == "FACTION_INVITE":
                    finalize_faction_join(self.nation_data, nation_b, nation_a)
                    log_global_event(self.nation_data, f"{nation_a} and {nation_b} have united their factions!")
                    send_message(self.nation_data, nation_a, nation_b, "Our requests crossed paths. We are now united!", "DIPLOMACY")
                    send_message(self.nation_data, nation_b, nation_a, "Our requests crossed paths. We are now united!", "DIPLOMACY")
                    del a_data[nation_b]
                    del b_data[nation_a]
                elif b_action == "JOIN_FACTION_REQ" and a_action == "FACTION_INVITE":
                    finalize_faction_join(self.nation_data, nation_a, nation_b)
                    send_message(self.nation_data, nation_a, nation_b, "Our requests crossed paths. We are now united!", "DIPLOMACY")
                    send_message(self.nation_data, nation_b, nation_a, "Our requests crossed paths. We are now united!", "DIPLOMACY")
                    del a_data[nation_b]
                    del b_data[nation_a]
                elif a_action == "WAR_DECLARATION" and b_action in ["FACTION_INVITE", "CEASEFIRE", "JOIN_FACTION_REQ"]:
                    send_message(self.nation_data, nation_a, nation_b, f"Your diplomat proposing a {b_action.split('_')[0].lower()} was executed. We are at WAR!", "DIPLOMACY")
                    del b_data[nation_a] 
                elif b_action == "WAR_DECLARATION" and a_action in ["FACTION_INVITE", "CEASEFIRE", "JOIN_FACTION_REQ"]:
                    send_message(self.nation_data, nation_b, nation_a, f"Your diplomat proposing a {a_action.split('_')[0].lower()} was executed. We are at WAR!", "DIPLOMACY")
                    del a_data[nation_b]
                elif a_action == "CEASEFIRE" and b_action == "CEASEFIRE":
                    finalize_neutral(self.nation_data, nation_a, nation_b)
                    log_global_event(self.nation_data, f"{nation_a} and {nation_b} have signed a mutual ceasefire.")
                    send_message(self.nation_data, nation_a, nation_b, "Mutual ceasefire agreements signed.", "DIPLOMACY")
                    send_message(self.nation_data, nation_b, nation_a, "Mutual ceasefire agreements signed.", "DIPLOMACY")
                    del a_data[nation_b]
                    del b_data[nation_a]

    # --- 2. GATHER AI TASKS ---
    ai_tasks = []
    for country_name, data in list(self.nation_data.items()):
        # Safety catch: Skip anything that isn't a dictionary
        if not isinstance(data, dict): 
            continue
            
        pending = data.get("pending_diplomacy", {})
        for target, info in pending.items():
            if isinstance(info, str):
                info = {"action": info, "turns": 1}
                pending[target] = info

            action = info.get("action", "")
            turns = info.get("turns", 0)

            if turns == 1:
                is_human_target = target in getattr(self, 'active_players', [])
                if not is_human_target:
                    # Added JOIN_WARS and BREAK_ALLIANCE to the list of tasks the AI should process
                    if action in ["FACTION_INVITE", "CEASEFIRE", "JOIN_FACTION_REQ", "CALL_TO_ARMS", "WAR_DECLARATION", "JOIN_WARS", "BREAK_ALLIANCE"]:
                        ai_tasks.append({"sender": country_name, "target": target, "action": action})
                    elif action.startswith("MSG:"):
                        ai_tasks.append({"sender": country_name, "target": target, "action": "CUSTOM_MSG", "content": action[4:]})

                # --- FIX: Queue AI responses using the members cached from Turn 0 ---
                if target == country_name and action in ["LEAVE_FACTION", "DISBAND_FACTION"]:
                    members = info.get("cached_members", [])
                    for m in members:
                        if m != country_name and m not in getattr(self, 'active_players', []):
                            ai_tasks.append({"sender": country_name, "target": m, "action": action})

    # --- 3. LOADING SCREEN & EXECUTE AI THREADS ---
    ai_results = {}
    if ai_tasks:
        surf = pygame.display.get_surface()
        if surf:
            font = fonts.get("title")
            txt = font.render(f"Waiting for {len(ai_tasks)} AI nations to respond...", True, (255, 200, 50))
            surf.blit(txt, txt.get_rect(center=(surf.get_width()//2, surf.get_height()//2 + 20)))
            sub_font = fonts.get("normal")
            sub_txt = sub_font.render("Generating responses... Please do not close the game.", True, (150, 150, 150))
            surf.blit(sub_txt, sub_txt.get_rect(center=(surf.get_width()//2, surf.get_height()//2 + 60)))
            pygame.display.flip()

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = {}
            for task in ai_tasks:
                target_ai, sender = task["target"], task["sender"]
                # Added JOIN_WARS and BREAK_ALLIANCE to the thread spawn list
                if task["action"] in ["FACTION_INVITE", "CEASEFIRE", "JOIN_FACTION_REQ", "CALL_TO_ARMS", "WAR_DECLARATION", "LEAVE_FACTION", "DISBAND_FACTION", "JOIN_WARS", "BREAK_ALLIANCE"]:
                    future = executor.submit(ai_handler.evaluate_diplomatic_proposal, self.nation_data, active_nations_list, target_ai, sender, task["action"])
                    futures[future] = task
                elif task["action"] == "CUSTOM_MSG":
                    future = executor.submit(ai_handler.process_custom_message, self.nation_data, active_nations_list, target_ai, sender, task["content"])
                    futures[future] = task
            for future in concurrent.futures.as_completed(futures):
                task = futures[future]
                try:
                    ai_results[(task["sender"], task["target"], task["action"])] = future.result()
                except Exception as e: print(f"Thread error: {e}")

    # --- 4. STANDARD RESOLUTION (APPLY AI RESULTS) ---
    for country_name, data in list(self.nation_data.items()):
        if not isinstance(data, dict): 
            continue
            
        pending = data.get("pending_diplomacy", {})
        actions_to_clear = []

        for target, info in pending.items():
            action = info.get("action", "")
            turns = info.get("turns", 0)
            custom_msg = info.get("message", "")

            if turns == 0:
                if action == "WAR_DECLARATION":
                    finalize_war(self.nation_data, country_name, target)
                    log_global_event(self.nation_data, f"WAR DECLARED: {country_name} has declared war on {target}!")
                    msg_text = custom_msg if custom_msg else "We have declared WAR upon you!"
                    send_message(self.nation_data, country_name, target, msg_text, "DIPLOMACY")
                
                elif action == "JOIN_WARS":
                    join_faction_wars(self.nation_data, country_name, target)
                    log_global_event(self.nation_data, f"ESCALATION: {country_name} has joined the wars of {target}!")
                    msg_text = custom_msg if custom_msg else "We stand with you. Our forces are joining your wars."
                    send_message(self.nation_data, country_name, target, msg_text, "DIPLOMACY")
                
                elif action == "CALL_TO_ARMS":
                    msg_text = custom_msg if custom_msg else "We request your aid in our ongoing conflicts!"
                    send_message(self.nation_data, country_name, target, msg_text, "DIPLOMACY")
                
                elif action == "BREAK_ALLIANCE":
                    finalize_neutral(self.nation_data, country_name, target)
                    log_global_event(self.nation_data, f"{country_name} has broken their alliance with {target}.")
                    msg_text = custom_msg if custom_msg else "We have broken our alliance."
                    send_message(self.nation_data, country_name, target, msg_text, "DIPLOMACY")
                
                elif action.startswith("MSG:"):
                    send_message(self.nation_data, country_name, target, action[4:], "TEXT")
                
                elif action == "FACTION_INVITE":
                    msg_text = custom_msg if custom_msg else "We invite your nation to join our faction."
                    send_message(self.nation_data, country_name, target, msg_text, "DIPLOMACY")
                
                elif action == "CEASEFIRE":
                    msg_text = custom_msg if custom_msg else "We offer terms for a ceasefire."
                    send_message(self.nation_data, country_name, target, msg_text, "DIPLOMACY")
                
                elif action == "CREATE_FACTION":
                    finalize_create_faction(self.nation_data, country_name)
                    log_global_event(self.nation_data, f"{country_name} has formed a new global faction!")
                    msg_text = custom_msg if custom_msg else "We are establishing a new faction."
                    send_message(self.nation_data, country_name, target, msg_text, "DIPLOMACY")
                    
                elif action == "DISBAND_FACTION":
                    fac = self.nation_data[country_name].get("faction", "")
                    info["cached_members"] = queries.get_faction_members(fac, self.nation_data) if fac else []
                    
                    finalize_disband_faction(self.nation_data, country_name)
                    log_global_event(self.nation_data, f"The faction led by {country_name} has been disbanded.")
                    msg_text = custom_msg if custom_msg else "We are dissolving our faction."
                    send_message(self.nation_data, country_name, target, msg_text, "DIPLOMACY")
                    
                elif action == "LEAVE_FACTION":
                    fac = self.nation_data[country_name].get("faction", "")
                    info["cached_members"] = queries.get_faction_members(fac, self.nation_data) if fac else []
                    
                    finalize_faction_leave(self.nation_data, country_name)
                    log_global_event(self.nation_data, f"{country_name} has abandoned their faction.")
                    msg_text = custom_msg if custom_msg else "We are withdrawing from the faction."
                    send_message(self.nation_data, country_name, target, msg_text, "DIPLOMACY")
                    
                elif action == "JOIN_FACTION_REQ":
                    msg_text = custom_msg if custom_msg else "We formally request to join your faction."
                    send_message(self.nation_data, country_name, target, msg_text, "DIPLOMACY")
                
                info["turns"] = 1

            elif turns == 1:
                if target == country_name:
                    if action == "CREATE_FACTION":
                        pass # Handled instantly on Turn 0
                    elif action == "DISBAND_FACTION":
                        # Fetch cached members to deliver the AI responses
                        members = info.get("cached_members", [])
                        for m in members:
                            if m != country_name and m not in getattr(self, 'active_players', []):
                                accepted, msg_text = ai_results.get((country_name, m, action), (False, c.AI_FALLBACK_RESPONSES.get("FACTION_DISBANDED", "It is a shame to see our alliance broken.")))
                                send_message(self.nation_data, m, country_name, msg_text, "TEXT")
                                
                    elif action == "LEAVE_FACTION":
                        # Fetch cached members to deliver the AI responses
                        members = info.get("cached_members", [])
                        for m in members:
                            if m != country_name and m not in getattr(self, 'active_players', []):
                                accepted, msg_text = ai_results.get((country_name, m, action), (False, c.AI_FALLBACK_RESPONSES.get("FACTION_ABANDONED", "We will not forget your abandonment.")))
                                send_message(self.nation_data, m, country_name, msg_text, "TEXT")
                                
                    actions_to_clear.append(target)
                    continue

                is_human_target = target in getattr(self, 'active_players', [])

                if action == "WAR_DECLARATION":
                    if not is_human_target:
                        accepted, message = ai_results.get((country_name, target, action), (False, "You will regret this betrayal."))
                        send_message(self.nation_data, target, country_name, message, "TEXT")
                
                elif action == "BREAK_ALLIANCE":
                    if not is_human_target: 
                        accepted, message = ai_results.get((country_name, target, action), (False, "We won't forget this."))
                        send_message(self.nation_data, target, country_name, message, "TEXT")
                
                elif action.startswith("MSG:"):
                    # ... (Leave CUSTOM_MSG block unchanged) ...
                    if not is_human_target:
                        reply = ai_results.get((country_name, target, "CUSTOM_MSG"), {})
                        
                        # Fallback format correction
                        if isinstance(reply, str):
                            reply = {"message": reply, "action": "NONE"}
                            
                        msg_text = reply.get("message", "Message received.")
                        ai_action = reply.get("action", "NONE")
                        follow_up = reply.get("follow_up_action", "NONE")
                        
                        raw_act_target = reply.get("action_target", "NONE")
                        raw_f_up_target = reply.get("follow_up_target", "NONE")
                        
                        def get_valid_target(raw_target):
                            if not raw_target or raw_target == "NONE": return "NONE"
                            clean_target = raw_target.strip().lower()
                            for n in active_nations_list:
                                if n.lower() == clean_target: return n
                                if self.nation_data.get(n, {}).get("name", "").lower() == clean_target: return n
                            return "NONE"
                            
                        act_target = get_valid_target(raw_act_target)
                        f_up_target = get_valid_target(raw_f_up_target)
                        
                        # GUARDRAIL: If they chose an action but target is invalid, abort so they don't shoot the messenger!
                        if ai_action != "NONE" and act_target == "NONE":
                            print(f"[AI GUARDRAIL] Aborting {ai_action}: Target '{raw_act_target}' not found.")
                            ai_action = "NONE"
                            
                        if follow_up != "NONE" and f_up_target == "NONE":
                            print(f"[AI GUARDRAIL] Aborting follow-up {follow_up}: Target '{raw_f_up_target}' not found.")
                            follow_up = "NONE"
                        
                        send_message(self.nation_data, target, country_name, msg_text, "TEXT")
                        
                        # --- Execute dynamic AI action ---
                        if ai_action == "WAR_DECLARATION":
                            if queries.are_in_same_faction(target, act_target, self.nation_data):
                                finalize_faction_leave(self.nation_data, target)
                                log_global_event(self.nation_data, f"BETRAYAL: {target} has abandoned their faction to attack {act_target}!")
                                
                            finalize_war(self.nation_data, target, act_target)
                            log_global_event(self.nation_data, f"WAR DECLARED: {target} has declared war on {act_target}!")
                            
                        elif ai_action == "JOIN_WARS":
                            if queries.are_in_same_faction(target, act_target, self.nation_data):
                                join_faction_wars(self.nation_data, target, act_target)
                                log_global_event(self.nation_data, f"ESCALATION: {target} has joined the wars of their ally, {act_target}!")
                            else:
                                target_enemies = queries.get_enemies(act_target, self.nation_data)
                                if target_enemies:
                                    for enemy in target_enemies:
                                        finalize_war(self.nation_data, target, enemy)
                                        log_global_event(self.nation_data, f"INTERVENTION: {target} has independently declared war on {enemy} to aid {act_target}!")
                                else:
                                    send_message(self.nation_data, target, country_name, f"We would offer military aid to {act_target}, but they are not currently at war.", "TEXT")
                            
                        elif ai_action == "LEAVE_FACTION":
                            finalize_faction_leave(self.nation_data, target)
                            log_global_event(self.nation_data, f"{target} has abandoned their faction.")
                            
                        elif ai_action == "JOIN_FACTION_REQ":
                            if self.nation_data[target].get("faction", ""):
                                send_message(self.nation_data, target, country_name, "We cannot join a new faction while we are already bound to our own treaties.", "TEXT")
                            else:
                                finalize_faction_join(self.nation_data, act_target, target)
                                log_global_event(self.nation_data, f"{target} has joined the faction of {act_target}.")
                        
                        # --- Queue Follow-Up Action for Next Turn ---
                        if follow_up and follow_up != "NONE":
                            final_f_up_target = target if follow_up in ["CREATE_FACTION", "LEAVE_FACTION", "DISBAND_FACTION"] else f_up_target
                            ai_queue = self.nation_data[target].setdefault("queued_ai_actions", [])
                            ai_queue.append({"target": final_f_up_target, "action": follow_up})
                            log_global_event(self.nation_data, f"RUMOR: Internal shuffling suggests {target} is preparing further diplomatic moves regarding {f_up_target}...")
                
                elif action == "FACTION_INVITE":
                    if is_human_target:
                        send_message(self.nation_data, target, country_name, "Your faction invitation was ignored and has expired.", "DIPLOMACY")
                    else:
                        accepted, message = ai_results.get((country_name, target, action), (False, "Timeout."))
                        if accepted:
                            finalize_faction_join(self.nation_data, country_name, target)
                        send_message(self.nation_data, target, country_name, message, "DIPLOMACY")
                
                elif action == "JOIN_FACTION_REQ":
                    if is_human_target:
                        send_message(self.nation_data, target, country_name, "Your request to join the faction was ignored and has expired.", "DIPLOMACY")
                    else:
                        accepted, message = ai_results.get((country_name, target, action), (False, "Timeout."))
                        if accepted:
                            finalize_faction_join(self.nation_data, target, country_name)
                        send_message(self.nation_data, target, country_name, message, "DIPLOMACY")
                
                elif action == "CEASEFIRE":
                    if is_human_target:
                        send_message(self.nation_data, target, country_name, "Your ceasefire offer was ignored and has expired.", "DIPLOMACY")
                    else:
                        accepted, message = ai_results.get((country_name, target, action), (False, "Timeout."))
                        if accepted:
                            finalize_neutral(self.nation_data, country_name, target)
                        send_message(self.nation_data, target, country_name, message, "DIPLOMACY")
                
                elif action == "CALL_TO_ARMS":
                    if is_human_target:
                        send_message(self.nation_data, target, country_name, "Your call to arms was ignored and has expired.", "DIPLOMACY")
                    else:
                        accepted, message = ai_results.get((country_name, target, action), (False, "Timeout."))
                        if accepted:
                            join_faction_wars(self.nation_data, target, country_name)
                            log_global_event(self.nation_data, f"ESCALATION: {target} answered the call to arms of {country_name}!")
                        send_message(self.nation_data, target, country_name, message, "DIPLOMACY")
                
                elif action == "JOIN_WARS":
                    if not is_human_target:
                        accepted, message = ai_results.get((country_name, target, action), (True, "We gratefully accept your assistance in our conflicts."))
                        send_message(self.nation_data, target, country_name, message, "TEXT")
                
                actions_to_clear.append(target)

        for t in actions_to_clear:
            del pending[t]

# You'll also need to update finalize_war to not remove alliances, since they're factions now
def finalize_war(nation_data, a, b):
    # GUARDRAIL: If they are in the same faction, the aggressor (a) leaves automatically
    if queries.are_in_same_faction(a, b, nation_data):
        finalize_faction_leave(nation_data, a)

    for country, other in [(a, b), (b, a)]:
        if other not in nation_data[country]["at_war_with"]:
            nation_data[country]["at_war_with"].append(other)
            
        # Snap relations to rock bottom
        nation_data[country].setdefault("relations", {})[other] = -100

def finalize_neutral(nation_data, a, b):
    for country, other in [(a, b), (b, a)]:
        if other in nation_data[country]["at_war_with"]:
            nation_data[country]["at_war_with"].remove(other)
        if other in nation_data[country]["allied_with"]:
            nation_data[country]["allied_with"].remove(other)
            
        # Reset relations to 0 upon ceasefire
        nation_data[country].setdefault("relations", {})[other] = 0

def finalize_create_faction(nation_data, creator):
    fac = f"The {nation_data[creator].get('name', creator)} Pact"
    nation_data[creator]["faction"] = fac
    nation_data[creator]["is_faction_leader"] = True

def finalize_disband_faction(nation_data, leader):
    fac = nation_data[leader].get("faction", "")
    if not fac: return
    for n, d in nation_data.items():
        if d.get("faction") == fac:
            d["faction"] = ""
            d["is_faction_leader"] = False

def finalize_faction_join(nation_data, host, joiner):
    fac = nation_data[host].get("faction", "")
    if fac:
        nation_data[joiner]["faction"] = fac
        nation_data[joiner]["is_faction_leader"] = False
        
        # --- FIX: Set relations to 100 with all faction members ---
        from data import queries
        members = queries.get_faction_members(fac, nation_data)
        for member in members:
            if member != joiner:
                nation_data[joiner].setdefault("relations", {})[member] = 100
                nation_data[member].setdefault("relations", {})[joiner] = 100
        # ----------------------------------------------------------

def finalize_faction_leave(nation_data, leaver):
    nation_data[leaver]["faction"] = ""
    nation_data[leaver]["is_faction_leader"] = False

def join_faction_wars(nation_data, joiner, faction_member):
    """Pulls the joining nation into all active wars of the target faction member."""
    wars = nation_data[faction_member].get("at_war_with", [])
    for enemy in wars:
        if enemy not in nation_data[joiner]["at_war_with"]:
            nation_data[joiner]["at_war_with"].append(enemy)
        if joiner not in nation_data[enemy]["at_war_with"]:
            nation_data[enemy]["at_war_with"].append(joiner)
            
        # --- FIX: Instantly drop relations to -100 upon joining a war ---
        nation_data[joiner].setdefault("relations", {})[enemy] = -100
        nation_data[enemy].setdefault("relations", {})[joiner] = -100
        # ----------------------------------------------------------------