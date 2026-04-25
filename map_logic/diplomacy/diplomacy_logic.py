import random
import concurrent.futures
import pygame
from map_logic.ai import ai_handler
from map_logic.rendering.font_manager import fonts
from data.constants import UNPLAYABLE_NATIONS
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

def toggle_diplomacy_action(nation_data, player_name, target_name, action_type):
    pending = nation_data[player_name].setdefault("pending_diplomacy", {})
    current_action = get_pending_action(nation_data, player_name, target_name)
    
    if current_action == action_type:
        info = pending.get(target_name, {})
        if isinstance(info, dict) and info.get("turns", 0) > 0:
            return "Cannot undo! The diplomat has already crossed their borders."
            
        del pending[target_name]
        return f"Undo {action_type.replace('_', ' ').title()}"
        
    elif current_action is not None:
        # Prevents declaring war while an alliance request is pending, etc.
        return "A diplomatic action is already pending with this nation!"
    else:
        pending[target_name] = {"action": action_type, "turns": 0}
        return "Message drafted. Will send at end of turn."

def queue_text_message(nation_data, player_name, target_name, content):
    pending = nation_data[player_name].setdefault("pending_diplomacy", {})
    current_action = get_pending_action(nation_data, player_name, target_name)
    
    # Allow overwriting if the pending action is a drafted message, otherwise block it
    if current_action is not None and not current_action.startswith("MSG:"):
        return "A diplomatic action is already pending with this nation!"
        
    pending[target_name] = {"action": f"MSG:{content}", "turns": 0}
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
                    log_global_event(self.nation_data, f"{nation_a} and {nation_b} have united their factions!") # NEW
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
                    log_global_event(self.nation_data, f"{nation_a} and {nation_b} have signed a mutual ceasefire.") # NEW
                    send_message(self.nation_data, nation_a, nation_b, "Mutual ceasefire agreements signed.", "DIPLOMACY")
                    send_message(self.nation_data, nation_b, nation_a, "Mutual ceasefire agreements signed.", "DIPLOMACY")
                    del a_data[nation_b]
                    del b_data[nation_a]

    # --- 2. GATHER AI TASKS ---
    ai_tasks = []
    # FIX: Cast .items() to a list() to prevent size change errors
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
                    if action in ["FACTION_INVITE", "CEASEFIRE", "JOIN_FACTION_REQ"]:
                        ai_tasks.append({"sender": country_name, "target": target, "action": action})
                    elif action.startswith("MSG:"):
                        ai_tasks.append({"sender": country_name, "target": target, "action": "CUSTOM_MSG", "content": action[4:]})

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
                if task["action"] in ["FACTION_INVITE", "CEASEFIRE", "JOIN_FACTION_REQ"]:
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
    # FIX: Cast .items() to a list() to prevent size change errors
    for country_name, data in list(self.nation_data.items()):
        # Safety catch: Skip anything that isn't a dictionary
        if not isinstance(data, dict): 
            continue
            
        pending = data.get("pending_diplomacy", {})
        actions_to_clear = []

        for target, info in pending.items():
            action = info.get("action", "")
            turns = info.get("turns", 0)

            if turns == 0:
                if action == "WAR_DECLARATION":
                    finalize_war(self.nation_data, country_name, target)
                    log_global_event(self.nation_data, f"WAR DECLARED: {country_name} has declared war on {target}!") # NEW
                    send_message(self.nation_data, country_name, target, "We have declared WAR upon you!", "DIPLOMACY")
                elif action == "BREAK_ALLIANCE":
                    finalize_neutral(self.nation_data, country_name, target)
                    log_global_event(self.nation_data, f"{country_name} has broken their alliance with {target}.") # NEW
                    send_message(self.nation_data, country_name, target, "We have broken our alliance.", "DIPLOMACY")
                elif action.startswith("MSG:"):
                    send_message(self.nation_data, country_name, target, action[4:], "TEXT")
                elif action == "FACTION_INVITE":
                    send_message(self.nation_data, country_name, target, "We invite your nation to join our faction.", "DIPLOMACY")
                elif action == "CEASEFIRE":
                    send_message(self.nation_data, country_name, target, "We offer terms for a ceasefire.", "DIPLOMACY")
                elif action == "CREATE_FACTION":
                    send_message(self.nation_data, country_name, target, "We are establishing a new faction.", "DIPLOMACY")
                elif action == "DISBAND_FACTION":
                    send_message(self.nation_data, country_name, target, "We are dissolving our faction.", "DIPLOMACY")
                elif action == "LEAVE_FACTION":
                    send_message(self.nation_data, country_name, target, "We are withdrawing from the faction.", "DIPLOMACY")
                elif action == "JOIN_FACTION_REQ":
                    send_message(self.nation_data, country_name, target, "We formally request to join your faction.", "DIPLOMACY")
                info["turns"] = 1
                
            elif turns == 1:
                if target == country_name:
                    if action == "CREATE_FACTION":
                        finalize_create_faction(self.nation_data, country_name)
                        log_global_event(self.nation_data, f"{country_name} has formed a new global faction!") # NEW
                        send_message(self.nation_data, country_name, country_name, "Our new faction has been established.", "DIPLOMACY")
                    elif action == "DISBAND_FACTION":
                        finalize_disband_faction(self.nation_data, country_name)
                        log_global_event(self.nation_data, f"The faction led by {country_name} has been disbanded.") # NEW
                        send_message(self.nation_data, country_name, country_name, "Our faction has been disbanded.", "DIPLOMACY")
                    elif action == "LEAVE_FACTION":
                        finalize_faction_leave(self.nation_data, country_name)
                        log_global_event(self.nation_data, f"{country_name} has abandoned their faction.") # NEW
                        send_message(self.nation_data, country_name, country_name, "We have left our faction.", "DIPLOMACY")
                    actions_to_clear.append(target)
                    continue

                is_human_target = target in getattr(self, 'active_players', [])

                if action == "WAR_DECLARATION":
                    if not is_human_target: send_message(self.nation_data, target, country_name, "You will regret this betrayal.", "TEXT")
                elif action == "BREAK_ALLIANCE":
                    if not is_human_target: send_message(self.nation_data, target, country_name, "We won't forget this.", "TEXT")
                elif action.startswith("MSG:"):
                    if not is_human_target:
                        reply = ai_results.get((country_name, target, "CUSTOM_MSG"), "Message received.")
                        send_message(self.nation_data, target, country_name, reply, "TEXT")
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
                actions_to_clear.append(target)

        for t in actions_to_clear:
            del pending[t]

# You'll also need to update finalize_war to not remove alliances, since they're factions now
def finalize_war(nation_data, a, b):
    for country, other in [(a, b), (b, a)]:
        if other not in nation_data[country]["at_war_with"]:
            nation_data[country]["at_war_with"].append(other)

def finalize_neutral(nation_data, a, b):
    for country, other in [(a, b), (b, a)]:
        if other in nation_data[country]["at_war_with"]:
            nation_data[country]["at_war_with"].remove(other)
        if other in nation_data[country]["allied_with"]:
            nation_data[country]["allied_with"].remove(other)

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

