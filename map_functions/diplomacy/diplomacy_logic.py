import random
import concurrent.futures
import pygame
from map_functions.ai import ai_handler
from map_functions.rendering.font_manager import fonts
from data.constants import UNPLAYABLE_NATIONS
from data import queries

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
            
            # If both queued an action on the same turn (turns == 0)
            if isinstance(a_info, dict) and a_info.get("turns", 0) == 0 and \
               isinstance(b_info, dict) and b_info.get("turns", 0) == 0:
               
                a_action = a_info.get("action")
                b_action = b_info.get("action")
                
                if a_action == "ALLIANCE_REQUEST" and b_action == "ALLIANCE_REQUEST":
                    finalize_alliance(self.nation_data, nation_a, nation_b)
                    send_message(self.nation_data, nation_a, nation_b, "Our mutual alliance proposals crossed paths. We are now allied!", "DIPLOMACY")
                    send_message(self.nation_data, nation_b, nation_a, "Our mutual alliance proposals crossed paths. We are now allied!", "DIPLOMACY")
                    del a_data[nation_b]
                    del b_data[nation_a]
                    
                elif a_action == "WAR_DECLARATION" and b_action in ["ALLIANCE_REQUEST", "CEASEFIRE"]:
                    send_message(self.nation_data, nation_a, nation_b, f"Your diplomat proposing a {b_action.split('_')[0].lower()} was executed. We are at WAR!", "DIPLOMACY")
                    del b_data[nation_a] 
                    
                elif b_action == "WAR_DECLARATION" and a_action in ["ALLIANCE_REQUEST", "CEASEFIRE"]:
                    send_message(self.nation_data, nation_b, nation_a, f"Your diplomat proposing a {a_action.split('_')[0].lower()} was executed. We are at WAR!", "DIPLOMACY")
                    del a_data[nation_b] 
                    
                elif a_action == "CEASEFIRE" and b_action == "CEASEFIRE":
                    finalize_neutral(self.nation_data, nation_a, nation_b)
                    send_message(self.nation_data, nation_a, nation_b, "Mutual ceasefire agreements signed.", "DIPLOMACY")
                    send_message(self.nation_data, nation_b, nation_a, "Mutual ceasefire agreements signed.", "DIPLOMACY")
                    del a_data[nation_b]
                    del b_data[nation_a]

    # --- 2. GATHER AI TASKS ---
    ai_tasks = []
    for country_name, data in self.nation_data.items():
        pending = data.get("pending_diplomacy", {})

        for target, info in pending.items():
            # Handle old string format if loading a legacy save
            if isinstance(info, str):
                info = {"action": info, "turns": 1}
                pending[target] = info

            action = info.get("action", "")
            turns = info.get("turns", 0)

            if turns == 1:
                is_human_target = target in getattr(self, 'active_players', [])
                if not is_human_target:
                    if action in ["ALLIANCE_REQUEST", "CEASEFIRE"]:
                        ai_tasks.append({"sender": country_name, "target": target, "action": action})
                    elif action.startswith("MSG:"):
                        ai_tasks.append({"sender": country_name, "target": target, "action": "CUSTOM_MSG", "content": action[4:]})

    # --- 3. LOADING SCREEN & EXECUTE AI THREADS ---
    ai_results = {}
    if ai_tasks:
        # DRAW LOADING SCREEN BEFORE BLOCKING THE THREAD
        surf = pygame.display.get_surface()
        if surf:
            # We removed the overlay.fill() here so it doesn't double-darken the screen!
            
            font = fonts.get("title")
            # Changed color to a gold/yellow to pop against the main white text
            txt = font.render(f"Waiting for {len(ai_tasks)} AI nations to respond...", True, (255, 200, 50))
            # Shifted DOWN by 20 pixels
            surf.blit(txt, txt.get_rect(center=(surf.get_width()//2, surf.get_height()//2 + 20)))
            
            sub_font = fonts.get("normal")
            sub_txt = sub_font.render("Generating responses... Please do not close the game.", True, (150, 150, 150))
            # Shifted DOWN by 60 pixels
            surf.blit(sub_txt, sub_txt.get_rect(center=(surf.get_width()//2, surf.get_height()//2 + 60)))
            
            pygame.display.flip()

        print(f"Firing {len(ai_tasks)} AI Diplomacy API calls...")
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = {}
            for task in ai_tasks:
                target_ai = task["target"]
                sender = task["sender"]
                
                if task["action"] in ["ALLIANCE_REQUEST", "CEASEFIRE"]:
                    future = executor.submit(ai_handler.evaluate_diplomatic_proposal, self.nation_data, active_nations_list, target_ai, sender, task["action"])
                    futures[future] = task
                elif task["action"] == "CUSTOM_MSG":
                    future = executor.submit(ai_handler.process_custom_message, self.nation_data, active_nations_list, target_ai, sender, task["content"])
                    futures[future] = task

            for future in concurrent.futures.as_completed(futures):
                task = futures[future]
                try:
                    result = future.result()
                    key = (task["sender"], task["target"], task["action"])
                    ai_results[key] = result
                except Exception as e:
                    print(f"Thread error: {e}")

    # --- 4. STANDARD RESOLUTION (APPLY AI RESULTS) ---
    for country_name, data in self.nation_data.items():
        pending = data.get("pending_diplomacy", {})
        actions_to_clear = []

        for target, info in pending.items():
            action = info.get("action", "")
            turns = info.get("turns", 0)

            if turns == 0:
                # Phase 1 (End of Turn 0): Apply unilateral effects & log messages to your outbox
                if action == "WAR_DECLARATION":
                    finalize_war(self.nation_data, country_name, target)
                    send_message(self.nation_data, country_name, target, "We have declared WAR upon you!", "DIPLOMACY")
                elif action == "BREAK_ALLIANCE":
                    finalize_neutral(self.nation_data, country_name, target)
                    send_message(self.nation_data, country_name, target, "We have broken our alliance.", "DIPLOMACY")
                elif action.startswith("MSG:"):
                    content = action[4:]
                    send_message(self.nation_data, country_name, target, content, "TEXT")
                elif action == "ALLIANCE_REQUEST":
                    send_message(self.nation_data, country_name, target, "We propose an alliance between our nations.", "DIPLOMACY")
                elif action == "CEASEFIRE":
                    send_message(self.nation_data, country_name, target, "We offer terms for a ceasefire.", "DIPLOMACY")

                # Advance all actions to Phase 2
                info["turns"] = 1
                
            elif turns == 1:
                # Phase 2 (End of Round 1 for AI, End of Round 2 for Humans): Bilateral effects apply
                is_human_target = target in getattr(self, 'active_players', [])

                if action == "WAR_DECLARATION":
                    if not is_human_target:
                        send_message(self.nation_data, target, country_name, "You will regret this betrayal.", "TEXT")
                elif action == "BREAK_ALLIANCE":
                    if not is_human_target:
                        send_message(self.nation_data, target, country_name, "We won't forget this.", "TEXT")
                
                elif action.startswith("MSG:"):
                    if not is_human_target:
                        reply = ai_results.get((country_name, target, "CUSTOM_MSG"), "Message received.")
                        send_message(self.nation_data, target, country_name, reply, "TEXT")
                    
                elif action == "ALLIANCE_REQUEST":
                    if is_human_target:
                        # If it survived to this phase, the human player ignored it during their turn!
                        send_message(self.nation_data, target, country_name, "Your alliance proposal was ignored and has expired.", "DIPLOMACY")
                    else:
                        accepted, message = ai_results.get((country_name, target, action), (False, "Timeout."))
                        if accepted:
                            finalize_alliance(self.nation_data, country_name, target)
                            send_message(self.nation_data, target, country_name, message, "DIPLOMACY")
                        else:
                            send_message(self.nation_data, target, country_name, message, "DIPLOMACY")
                        
                elif action == "CEASEFIRE":
                    if is_human_target:
                        # If it survived to this phase, the human player ignored it during their turn!
                        send_message(self.nation_data, target, country_name, "Your ceasefire offer was ignored and has expired.", "DIPLOMACY")
                    else:
                        accepted, message = ai_results.get((country_name, target, action), (False, "Timeout."))
                        if accepted:
                            finalize_neutral(self.nation_data, country_name, target)
                            send_message(self.nation_data, target, country_name, message, "DIPLOMACY")
                        else:
                            send_message(self.nation_data, target, country_name, message, "DIPLOMACY")
                
                # Action is fully resolved (or expired), queue it for cleanup
                actions_to_clear.append(target)

        # Cleanup resolved actions
        for t in actions_to_clear:
            del pending[t]

def finalize_war(nation_data, a, b):
    for country, other in [(a, b), (b, a)]:
        if other not in nation_data[country]["at_war_with"]:
            nation_data[country]["at_war_with"].append(other)
        if other in nation_data[country]["allied_with"]:
            nation_data[country]["allied_with"].remove(other)

def finalize_alliance(nation_data, a, b):
    for country, other in [(a, b), (b, a)]:
        if other not in nation_data[country]["allied_with"]:
            nation_data[country]["allied_with"].append(other)
        if other in nation_data[country]["at_war_with"]:
            nation_data[country]["at_war_with"].remove(other)

def finalize_neutral(nation_data, a, b):
    for country, other in [(a, b), (b, a)]:
        if other in nation_data[country]["at_war_with"]:
            nation_data[country]["at_war_with"].remove(other)
        if other in nation_data[country]["allied_with"]:
            nation_data[country]["allied_with"].remove(other)