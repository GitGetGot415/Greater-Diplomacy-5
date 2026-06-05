import concurrent.futures
from map_logic.ai import ai_prompts
import data.constants as c
from data import queries

# Import from our newly created submodules
from map_logic.diplomacy.diplomacy_events import log_global_event
from map_logic.diplomacy.diplomacy_messages import get_pending_action, send_message
from map_logic.diplomacy.diplomacy_agreements import (
    finalize_war, finalize_neutral, execute_peace_treaty, finalize_create_faction,
    finalize_disband_faction, finalize_faction_join, finalize_faction_leave,
    join_faction_wars, finalize_faction_kick
)

def toggle_diplomacy_action(nation_data, player_name, target_name, action_type, custom_msg="", timer=0):
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
    faction_actions = ["CREATE_FACTION", "JOIN_FACTION_REQ", "ACCEPT_CREATE_FACTION", "ACCEPT_FACTION_INVITE", "ACCEPT_JOIN_FACTION_REQ"]
    if action_type in faction_actions:
        if nation_data[player_name].get("faction", ""):
            return "Cannot do this while already in a faction!"
        
        for other_target, info in pending.items():
            act = info.get("action", "") if isinstance(info, dict) else info
            if act in faction_actions and other_target != target_name:
                return "You already have a pending faction request!"
    # ------------------------------------------------
        
    pending[target_name] = {"action": action_type, "turns": 0, "timer": timer, "message": custom_msg}
    return "Message drafted. Will send at end of turn."

def process_diplomacy_turn(self):
    # --- DECAY TEMPORARY MODIFIERS ---
    for country_name, data in list(self.nation_data.items()):
        if not isinstance(data, dict): 
            continue
            
        temp_mods = data.get("temp_modifiers", {})
        for target, mods in temp_mods.items():
            for mod_name in list(mods.keys()):
                if mods[mod_name] > 0:
                    mods[mod_name] -= 1
                elif mods[mod_name] < 0:
                    mods[mod_name] += 1
                    
                if mods[mod_name] == 0:
                    del mods[mod_name]

    # --- 0. PROCESS QUEUED AI MULTI-TURN ACTIONS ---
    for country_name, data in self.nation_data.items():
        if isinstance(data, dict) and "queued_ai_actions" in data and data["queued_ai_actions"]:
            pending = data.setdefault("pending_diplomacy", {})
            for q_action in data["queued_ai_actions"]:
                target = q_action["target"]
                action_type = q_action["action"]
                
                # Ensure self-targeting actions target the AI itself!
                if action_type in ["CREATE_FACTION", "LEAVE_FACTION", "DISBAND_FACTION"]:
                    target = country_name
                
                # Inject it as a fresh action for this turn, bypassing the LLM
                if target not in pending or (isinstance(pending[target], dict) and pending[target].get("turns", 0) == 0):
                    pending[target] = {"action": action_type, "turns": 0, "timer": 0, "message": "Following through on our previous declaration."}
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
                    finalize_faction_join(self.map_data, self.nation_data, nation_b, nation_a)
                    log_global_event(self.nation_data, f"{nation_a} and {nation_b} have united their factions!")
                    
                    msg = ai_prompts.AI_FALLBACK_RESPONSES["CROSS_FACTION_JOIN"]
                    send_message(self, nation_a, nation_b, msg, "DIPLOMACY")
                    send_message(self, nation_b, nation_a, msg, "DIPLOMACY")
                    
                    del a_data[nation_b]
                    del b_data[nation_a]
                    
                elif b_action == "JOIN_FACTION_REQ" and a_action == "FACTION_INVITE":
                    finalize_faction_join(self.map_data, self.nation_data, nation_a, nation_b)
                    
                    msg = ai_prompts.AI_FALLBACK_RESPONSES["CROSS_FACTION_JOIN"]
                    send_message(self, nation_a, nation_b, msg, "DIPLOMACY")
                    send_message(self, nation_b, nation_a, msg, "DIPLOMACY")
                    
                    del a_data[nation_b]
                    del b_data[nation_a]
                    
                elif a_action == "WAR_DECLARATION" and b_action in ["FACTION_INVITE", "CEASEFIRE", "JOIN_FACTION_REQ", "PEACE_TREATY"]:
                    action_name = b_action.split('_')[0].lower()
                    msg = ai_prompts.AI_FALLBACK_RESPONSES["CROSS_WAR_DECLARATION"].format(action=action_name)
                    
                    send_message(self, nation_a, nation_b, msg, "DIPLOMACY")
                    del b_data[nation_a] 
                    
                elif b_action == "WAR_DECLARATION" and a_action in ["FACTION_INVITE", "CEASEFIRE", "JOIN_FACTION_REQ", "PEACE_TREATY"]:
                    action_name = a_action.split('_')[0].lower()
                    msg = ai_prompts.AI_FALLBACK_RESPONSES["CROSS_WAR_DECLARATION"].format(action=action_name)
                    
                    send_message(self, nation_b, nation_a, msg, "DIPLOMACY")
                    del a_data[nation_b]
                    
                elif a_action == "CEASEFIRE" and b_action == "CEASEFIRE":
                    finalize_neutral(self.nation_data, nation_a, nation_b)
                    log_global_event(self.nation_data, f"{nation_a} and {nation_b} have signed a mutual ceasefire.")
                    
                    msg = ai_prompts.AI_FALLBACK_RESPONSES["CROSS_CEASEFIRE"]
                    send_message(self, nation_a, nation_b, msg, "DIPLOMACY")
                    send_message(self, nation_b, nation_a, msg, "DIPLOMACY")
                    
                    del a_data[nation_b]
                    del b_data[nation_a]
                    
                elif (a_action == "CALL_TO_ARMS" and b_action == "JOIN_WARS") or \
                     (a_action == "JOIN_WARS" and b_action == "CALL_TO_ARMS"):
                    
                    join_faction_wars(self.map_data, self.nation_data, nation_a, nation_b)
                    join_faction_wars(self.map_data, self.nation_data, nation_b, nation_a)
                    log_global_event(self.nation_data, f"ESCALATION: {nation_a} and {nation_b} have formally combined their war efforts!")
                    
                    msg = ai_prompts.AI_FALLBACK_RESPONSES["CROSS_CALL_TO_ARMS"]
                    send_message(self, nation_a, nation_b, msg, "DIPLOMACY")
                    send_message(self, nation_b, nation_a, msg, "DIPLOMACY")
                    
                    del a_data[nation_b]
                    del b_data[nation_a]

    # --- 2. GATHER AI TASKS ---
    ai_tasks = []
    for country_name, data in list(self.nation_data.items()):
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
                is_human_target = target in getattr(self, 'active_players', [])
                if not is_human_target:
                    if action in c.UNILATERAL_ACTIONS or action in c.BILATERAL_ACTIONS:
                        ai_tasks.append({"sender": country_name, "target": target, "action": action, "content": custom_msg})
                    elif action.startswith("MSG:"):
                        ai_tasks.append({"sender": country_name, "target": target, "action": "CUSTOM_MSG", "content": action[4:]})

                # Special self-targeting actions for Factions
                if action in ["LEAVE_FACTION", "DISBAND_FACTION"]:
                    fac = self.nation_data[country_name].get("faction", "")
                    members = queries.get_faction_members(fac, self.nation_data) if fac else []
                    info["cached_members"] = members
                    for m in members:
                        if m != country_name and m not in getattr(self, 'active_players', []):
                            ai_tasks.append({"sender": country_name, "target": m, "action": action})

    # --- 3. EXECUTE AI THREADS ---
    ai_results = {}
    
    if not ai_tasks:
        self.responsive_tasks_total = 0
        self.responsive_tasks_completed = 0
    else:
        from map_logic.ai import ai_handler # Import this to safely check the mode
        
        human_players = getattr(self, 'active_players', [self.player_country])
        
        mode = ai_handler.get_ai_mode()
        immersion = ai_handler.get_ai_immersion_level()
        
        # --- DYNAMIC LOADING BAR CALCULATION ---
        task_count = 0
        if mode != "OFF":
            for t in ai_tasks:
                is_human_related = (t["sender"] in human_players or t["target"] in human_players)
                
                if immersion == "ABSOLUTE":
                    # In Absolute, every task calls the LLM, so count them all
                    task_count += 1
                elif immersion == "FULL":
                    # In Full, only process if a human is involved
                    if is_human_related:
                        task_count += 1
                elif immersion == "LITE":
                    # In Lite, only process if human sent a message or if it's a responding CUSTOM_MSG
                    if is_human_related and (t["action"] == "CUSTOM_MSG" or bool(t.get("content", "").strip())):
                        task_count += 1
                    
        self.responsive_tasks_total = task_count
        self.responsive_tasks_completed = 0
        
        self.loading_status_text = f"Processing Global Responses (0/{self.responsive_tasks_total})..."
    
        # If skipping, bypass the executor entirely
        if getattr(self, 'force_skip_llm', False):
            for task in ai_tasks:
                target_ai, sender = task["target"], task["sender"]
                if task["action"] == "CUSTOM_MSG":
                    ai_results[(sender, target_ai, task["action"])] = {
                        "message": ai_prompts.AI_FALLBACK_RESPONSES["AI_OFF_MESSAGE"], 
                        "action": "NONE", "action_target": "NONE", 
                        "follow_up_action": "NONE", "follow_up_target": "NONE",
                        "opinion_change": 0
                    }
                elif task["action"] in c.UNILATERAL_ACTIONS:
                    fallback_map = {
                        "WAR_DECLARATION": "BETRAYAL",
                        "LEAVE_FACTION": "FACTION_ABANDONED",
                        "DISBAND_FACTION": "FACTION_DISBANDED",
                        "JOIN_WARS": "ACCEPTED_HELP",
                        "BREAK_ALLIANCE": "ALLIANCE_BROKEN",
                        "KICK_FACTION_MEMBER": "KICKED_FROM_FACTION"
                    }
                    fb_key = fallback_map.get(task["action"], "GENERIC_MESSAGE")
                    fallback = ai_prompts.AI_FALLBACK_RESPONSES.get(fb_key, "Message received.")
                    ai_results[(sender, target_ai, task["action"])] = {
                        "accepted": True, "message": fallback, "action": "NONE", "action_target": "NONE", 
                        "follow_up_action": "NONE", "follow_up_target": "NONE", "opinion_change": 0
                    }
                else:
                    fallback = ai_prompts.AI_FALLBACK_RESPONSES.get("AI_OFF_ACCEPT", "We accept your proposal.")
                    ai_results[(sender, target_ai, task["action"])] = {
                        "accepted": True, "message": fallback, "action": "NONE", "action_target": "NONE", 
                        "follow_up_action": "NONE", "follow_up_target": "NONE", "opinion_change": 0
                    }
        else:
            max_threads = queries.get_ai_threads()
            executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_threads)
            futures = {}
            my_turn_id = getattr(ai_handler, 'CURRENT_TURN_ID', 0)
            
            for task in ai_tasks:
                target_ai, sender = task["target"], task["sender"]
                if task["action"] in c.UNILATERAL_ACTIONS or task["action"] in c.BILATERAL_ACTIONS:
                    future = executor.submit(ai_handler.evaluate_diplomatic_proposal, self.nation_data, active_nations_list, target_ai, sender, task["action"], task.get("content", ""), human_players, my_turn_id)
                    futures[future] = task
                elif task["action"] == "CUSTOM_MSG":
                    future = executor.submit(ai_handler.process_custom_message, self.nation_data, active_nations_list, target_ai, sender, task["content"], human_players, my_turn_id)
                    futures[future] = task
                    
            while futures:
                if getattr(self, 'force_skip_llm', False):
                    for f in futures:
                        f.cancel()
                    for f, task in list(futures.items()):
                        if f.done() and not f.cancelled():
                            try:
                                ai_results[(task["sender"], task["target"], task["action"])] = f.result()
                            except:
                                pass
                        else:
                            # Fallback Logic Dictionary
                            if task["action"] == "CUSTOM_MSG":
                                ai_results[(task["sender"], task["target"], task["action"])] = {
                                    "message": ai_prompts.AI_FALLBACK_RESPONSES["AI_OFF_MESSAGE"], 
                                    "action": "NONE", "action_target": "NONE", 
                                    "follow_up_action": "NONE", "follow_up_target": "NONE",
                                    "opinion_change": 0
                                }
                            elif task["action"] in c.UNILATERAL_ACTIONS:
                                fallback_map = {
                                    "WAR_DECLARATION": "BETRAYAL",
                                    "LEAVE_FACTION": "FACTION_ABANDONED",
                                    "DISBAND_FACTION": "FACTION_DISBANDED",
                                    "JOIN_WARS": "ACCEPTED_HELP",
                                    "BREAK_ALLIANCE": "ALLIANCE_BROKEN",
                                    "KICK_FACTION_MEMBER": "KICKED_FROM_FACTION"
                                }
                                fb_key = fallback_map.get(task["action"], "GENERIC_MESSAGE")
                                fallback = ai_prompts.AI_FALLBACK_RESPONSES.get(fb_key, "Message received.")
                                ai_results[(task["sender"], task["target"], task["action"])] = {
                                    "accepted": True, "message": fallback, "action": "NONE", "action_target": "NONE", 
                                    "follow_up_action": "NONE", "follow_up_target": "NONE", "opinion_change": 0
                                }
                            else:
                                fallback = ai_prompts.AI_FALLBACK_RESPONSES.get("AI_OFF_ACCEPT", "We accept your proposal.")
                                ai_results[(task["sender"], task["target"], task["action"])] = {
                                    "accepted": True, "message": fallback, "action": "NONE", "action_target": "NONE", 
                                    "follow_up_action": "NONE", "follow_up_target": "NONE", "opinion_change": 0
                                }
                                
                        # Incremental Progress logic
                        is_human_related = (task["sender"] in human_players or task["target"] in human_players)
                        if mode != "OFF":
                            if immersion == "ABSOLUTE" or (immersion == "FULL" and is_human_related) or (immersion == "LITE" and is_human_related and (task["action"] == "CUSTOM_MSG" or bool(task.get("content", "").strip()))):
                                self.responsive_tasks_completed += 1
                                self.loading_status_text = f"Processing Global Responses ({self.responsive_tasks_completed}/{self.responsive_tasks_total})...."
                    try:
                        executor.shutdown(wait=False, cancel_futures=True)
                    except TypeError:
                        executor.shutdown(wait=False)
                    break
                
                done, _ = concurrent.futures.wait(futures.keys(), timeout=0.1, return_when=concurrent.futures.FIRST_COMPLETED)
                for future in done:
                    task = futures.pop(future)
                    try:
                        ai_results[(task["sender"], task["target"], task["action"])] = future.result()
                    except Exception as e: 
                        print(f"Thread error: {e}")
                        ai_results[(task["sender"], task["target"], task["action"])] = {
                            "accepted": True, "message": f"THREAD ERROR: {str(e)}", "action": "NONE", "action_target": "NONE", 
                            "follow_up_action": "NONE", "follow_up_target": "NONE", "opinion_change": 0
                        }
                        
                    # Incremental Progress logic
                    is_human_related = (task["sender"] in human_players or task["target"] in human_players)
                    if mode != "OFF":
                        if immersion == "ABSOLUTE" or (immersion == "FULL" and is_human_related) or (immersion == "LITE" and is_human_related and (task["action"] == "CUSTOM_MSG" or bool(task.get("content", "").strip()))):
                            self.responsive_tasks_completed += 1
                            self.loading_status_text = f"Processing Global Responses ({self.responsive_tasks_completed}/{self.responsive_tasks_total})..."
        
        if not getattr(self, 'force_skip_llm', False):
            executor.shutdown(wait=True)


    # --- 4. STANDARD RESOLUTION (APPLY AI RESULTS) ---
    delayed_responses = [] # Store AI actions here to queue them for the next turn

    def process_ai_retaliation(country_name, reply_dict):
        """Processes reactive diplomatic actions appended by the LLM."""
        ai_action = reply_dict.get("action", "NONE")
        follow_up = reply_dict.get("follow_up_action", "NONE")
        raw_act_target = reply_dict.get("action_target", "NONE")
        raw_f_up_target = reply_dict.get("follow_up_target", "NONE")
        
        def get_valid_target(raw_target):
            if not raw_target or raw_target == "NONE": return "NONE"
            clean_target = raw_target.strip().lower()
            for n in active_nations_list:
                if n.lower() == clean_target: return n
                if self.nation_data.get(n, {}).get("name", "").lower() == clean_target: return n
            return "NONE"
            
        act_target = get_valid_target(raw_act_target)
        f_up_target = get_valid_target(raw_f_up_target)
        
        if ai_action != "NONE" and act_target == "NONE":
            print(f"[AI GUARDRAIL] Aborting {ai_action}: Target '{raw_act_target}' not found.")
            ai_action = "NONE"
            
        if follow_up != "NONE" and f_up_target == "NONE":
            print(f"[AI GUARDRAIL] Aborting follow-up {follow_up}: Target '{raw_f_up_target}' not found.")
            follow_up = "NONE"

        # Check cooldown
        if ai_action != "NONE":
            if queries.is_ai_diplo_on_cooldown(country_name, act_target, ai_action, self.nation_data):
                print(f"[AI GUARDRAIL] Aborting {ai_action}: Cooldown active.")
                ai_action = "NONE"
            else:
                queries.set_ai_diplo_cooldown(country_name, act_target, ai_action, self.nation_data)

        if ai_action == "WAR_DECLARATION":
            if queries.are_in_same_faction(country_name, act_target, self.nation_data):
                if queries.is_faction_leader(country_name, self.nation_data):
                    delayed_responses.append((country_name, act_target, "KICK_FACTION_MEMBER", 0, "You are expelled from the faction."))
                else:
                    delayed_responses.append((country_name, country_name, "LEAVE_FACTION", 0, ""))
                ai_queue = self.nation_data[country_name].setdefault("queued_ai_actions", [])
                ai_queue.append({"target": act_target, "action": "WAR_DECLARATION"})
            else:
                # --- NEW: Explicitly force LLM reaction wars to use No CB ---
                delayed_responses.append((country_name, act_target, "WAR_DECLARATION", 0, getattr(c, 'WARGOAL_NO_CB', "No Casus Belli")))
        elif ai_action == "JOIN_WARS":
            if queries.are_in_same_faction(country_name, act_target, self.nation_data):
                delayed_responses.append((country_name, act_target, "JOIN_WARS", 0, ai_prompts.AI_FALLBACK_RESPONSES.get("PROACTIVE_JOIN_WAR", "We stand with you.")))
            else:
                target_enemies = queries.get_enemies(act_target, self.nation_data)
                if target_enemies:
                    for enemy in target_enemies:
                        delayed_responses.append((country_name, enemy, "WAR_DECLARATION", 0, ai_prompts.AI_FALLBACK_RESPONSES.get("PROACTIVE_DECLARE_WAR", "We have declared WAR upon you!")))
        elif ai_action == "LEAVE_FACTION":
            delayed_responses.append((country_name, country_name, "LEAVE_FACTION", 0, ""))
        elif ai_action == "JOIN_FACTION_REQ":
            if not self.nation_data[country_name].get("faction", ""):
                delayed_responses.append((country_name, act_target, "JOIN_FACTION_REQ", 0, ai_prompts.AI_FALLBACK_RESPONSES.get("PROACTIVE_JOIN_FACTION", "We formally request to join your faction.")))
        elif ai_action == "CEASEFIRE":
            delayed_responses.append((country_name, act_target, "CEASEFIRE", 0, ai_prompts.AI_FALLBACK_RESPONSES.get("PROACTIVE_CEASEFIRE", "We offer terms for a ceasefire.")))
        elif ai_action == "CALL_TO_ARMS":
            delayed_responses.append((country_name, act_target, "CALL_TO_ARMS", 0, ai_prompts.AI_FALLBACK_RESPONSES.get("PROACTIVE_CALL_TO_ARMS", "We request your aid!")))
        elif ai_action == "CREATE_FACTION":
            delayed_responses.append((country_name, act_target, "CREATE_FACTION", 0, "We propose establishing a new faction."))
        elif ai_action == "KICK_FACTION_MEMBER":
            delayed_responses.append((country_name, act_target, "KICK_FACTION_MEMBER", 0, "You are expelled."))
        elif ai_action == "DISBAND_FACTION":
            delayed_responses.append((country_name, country_name, "DISBAND_FACTION", 0, ""))

        if follow_up and follow_up != "NONE":
            final_f_up_target = country_name if follow_up in ["CREATE_FACTION", "LEAVE_FACTION", "DISBAND_FACTION"] else f_up_target
            ai_queue = self.nation_data[country_name].setdefault("queued_ai_actions", [])
            ai_queue.append({"target": final_f_up_target, "action": follow_up})
            log_global_event(self.nation_data, f"RUMOR: Internal shuffling suggests {country_name} is preparing further diplomatic moves regarding {f_up_target}...")


    for country_name, data in list(self.nation_data.items()):
        if not isinstance(data, dict): 
            continue
            
        pending = data.get("pending_diplomacy", {})
        actions_to_clear = []

        for target, info in pending.items():
            action = info.get("action", "")
            turns = info.get("turns", 0)
            timer = info.get("timer", 0)
            custom_msg = info.get("message", "")

            is_unilateral = action in c.UNILATERAL_ACTIONS

            # --- NEW: COUNTDOWN TIMERS ---
            if timer > 0:
                info["timer"] -= 1
                if info["timer"] > 0:
                    continue
                else:
                    turns = 0 # Force execution this turn

            if turns == 0:
                # EXECUTE unilateral actions instantly on Turn 0
                if action == "JUSTIFY_WARGOAL":
                    prov_ids = [int(x) for x in custom_msg.split(",") if x]
                    
                    # Remove old claims that are currently owned by the target to allow unclaiming
                    current_claims = self.nation_data[country_name].get("claims", [])
                    new_claims = []
                    for cid in current_claims:
                        prov = self.id_to_province.get(cid)
                        if prov and prov.get("owner") == target:
                            continue # Drop it so it can be overwritten
                        new_claims.append(cid)
                        
                    new_claims.extend(prov_ids)
                    self.nation_data[country_name]["claims"] = list(set(new_claims))
                    
                    self.nation_data[country_name].setdefault("wargoals", {})[target] = {"type": getattr(c, 'WARGOAL_TAKE_CLAIMS', "Take Claims")}
                    log_global_event(self.nation_data, f"{country_name} has justified a wargoal against {target}.")
                    if country_name == self.player_country:
                        self.show_feedback(f"Wargoal Justification Complete against {target}!")
                    actions_to_clear.append(target)
                    
                elif action == "WAR_DECLARATION":
                    # Store active wargoal in war data
                    self.nation_data[country_name].setdefault("wargoals", {})[target] = {"type": custom_msg}
                    log_global_event(self.nation_data, f"WAR DECLARED: {country_name} has declared war on {target}!")
                    msg_text = f"We have declared war! Goal: {custom_msg}"
                    send_message(self, country_name, target, msg_text, "DIPLOMACY")
                    finalize_war(self.map_data, self.nation_data, country_name, target) 
                    actions_to_clear.append(target)
                
                elif action == "JOIN_WARS":
                    if not queries.are_in_same_faction(country_name, target, self.nation_data):
                        msg_text = "We wanted to join your wars, but our lack of formal alliance prevents it."
                        send_message(self, country_name, target, msg_text, "DIPLOMACY")
                        actions_to_clear.append(target)
                    else:
                        # DO NOT execute the war join here! Just send the proposal message.
                        msg_text = custom_msg if custom_msg else "We request permission to join your ongoing wars."
                        send_message(self, country_name, target, msg_text, "DIPLOMACY")
                
                elif action == "CALL_TO_ARMS":
                    msg_text = custom_msg if custom_msg else "We request your aid in our ongoing conflicts!"
                    send_message(self, country_name, target, msg_text, "DIPLOMACY")
                
                elif action == "BREAK_ALLIANCE":
                    log_global_event(self.nation_data, f"{country_name} has broken their alliance with {target}.")
                    msg_text = custom_msg if custom_msg else "We have broken our alliance."
                    send_message(self, country_name, target, msg_text, "DIPLOMACY")
                    finalize_neutral(self.nation_data, country_name, target) 
                
                # DELIVER messages to inbox on Turn 0
                elif action.startswith("MSG:"):
                    send_message(self, country_name, target, action[4:], "TEXT")
                
                # --- PROCESS ACCEPT / REJECT INSTANTLY ON TURN 0 ---
                elif action.startswith("ACCEPT_"):
                    orig_action = action.replace("ACCEPT_", "")
                    other_pending = self.nation_data.get(target, {}).get("pending_diplomacy", {}).get(country_name, {})
                    
                    if isinstance(other_pending, dict) and other_pending.get("action") == orig_action:
                        msg_text = custom_msg if custom_msg else f"We accepted your {orig_action.replace('_', ' ').lower()}."
                        
                        if orig_action == "FACTION_INVITE":
                            if not self.nation_data[country_name].get("faction", ""):
                                finalize_faction_join(self.map_data, self.nation_data, target, country_name)
                            else:
                                msg_text = "We wanted to accept, but we are already in a faction."
                        elif orig_action == "JOIN_FACTION_REQ":
                            if not self.nation_data[target].get("faction", ""):
                                finalize_faction_join(self.map_data, self.nation_data, country_name, target)
                            else:
                                msg_text = "We cannot accept as you are already in a faction."
                        elif orig_action == "CREATE_FACTION":
                            if not self.nation_data[country_name].get("faction", "") and not self.nation_data[target].get("faction", ""):
                                finalize_create_faction(self.map_data, self.nation_data, target)
                                finalize_faction_join(self.map_data, self.nation_data, target, country_name)
                            else:
                                msg_text = "The proposed faction could not be formed because one of us is already bound by other treaties."
                        elif orig_action == "CEASEFIRE":
                            finalize_neutral(self.nation_data, country_name, target)
                        elif orig_action == "PEACE_TREATY":
                            treaty_type = other_pending.get("message", getattr(c, 'PEACE_WHITE_PEACE', "Ceasefire (White Peace)"))
                            execute_peace_treaty(self.map_data, self.nation_data, target, country_name, treaty_type, self)
                            msg_text = f"We accepted your peace terms: {treaty_type}."
                        elif orig_action == "CALL_TO_ARMS":
                            join_faction_wars(self.map_data, self.nation_data, country_name, target)
                        elif orig_action == "JOIN_WARS":
                            join_faction_wars(self.map_data, self.nation_data, target, country_name)
                            log_global_event(self.nation_data, f"ESCALATION: {target} has joined the wars of {country_name}!")
                        
                        send_message(self, country_name, target, msg_text, "DIPLOMACY")
                        if msg_text == custom_msg or "accepted" in msg_text:
                            log_global_event(self.nation_data, f"Diplomatic agreement reached between {country_name} and {target}.")
                        
                        # Clear the original request from the sender
                        if target in self.nation_data and "pending_diplomacy" in self.nation_data[target]:
                            if country_name in self.nation_data[target]["pending_diplomacy"]:
                                del self.nation_data[target]["pending_diplomacy"][country_name]
                    
                    actions_to_clear.append(target)
                    
                elif action.startswith("REJECT_"):
                    orig_action = action.replace("REJECT_", "")
                    other_pending = self.nation_data.get(target, {}).get("pending_diplomacy", {}).get(country_name, {})
                    
                    if isinstance(other_pending, dict) and other_pending.get("action") == orig_action:
                        msg_text = custom_msg if custom_msg else f"We rejected your {orig_action.replace('_', ' ').lower()}."
                        send_message(self, country_name, target, msg_text, "DIPLOMACY")
                        
                        # Clear the original request from the sender
                        if target in self.nation_data and "pending_diplomacy" in self.nation_data[target]:
                            if country_name in self.nation_data[target]["pending_diplomacy"]:
                                del self.nation_data[target]["pending_diplomacy"][country_name]
                                
                    actions_to_clear.append(target)
                
                elif action == "FACTION_INVITE":
                    msg_text = custom_msg if custom_msg else "We invite your nation to join our faction."
                    send_message(self, country_name, target, msg_text, "DIPLOMACY")
                
                elif action == "CEASEFIRE":
                    msg_text = custom_msg if custom_msg else "We offer terms for a ceasefire."
                    send_message(self, country_name, target, msg_text, "DIPLOMACY")

                elif action == "PEACE_TREATY":
                    msg_text = f"We propose a peace treaty: {custom_msg}."
                    send_message(self, country_name, target, msg_text, "DIPLOMACY")
                
                elif action == "CREATE_FACTION":
                    msg_text = custom_msg if custom_msg else "We propose establishing a new faction together."
                    send_message(self, country_name, target, msg_text, "DIPLOMACY")
                    
                elif action == "DISBAND_FACTION":
                    fac = self.nation_data[country_name].get("faction", "")
                    info["cached_members"] = info.get("cached_members", queries.get_faction_members(fac, self.nation_data) if fac else [])
                    log_global_event(self.nation_data, f"The faction led by {country_name} has been disbanded.")
                    msg_text = custom_msg if custom_msg else "We are dissolving our faction."
                    
                    for m in info["cached_members"]:
                        if m != country_name:
                            send_message(self, country_name, m, msg_text, "DIPLOMACY")
                            
                    finalize_disband_faction(self.nation_data, country_name)

                elif action == "KICK_FACTION_MEMBER":
                    log_global_event(self.nation_data, f"FACTION EXPULSION: {country_name} has kicked {target} from the faction!")
                    msg_text = custom_msg if custom_msg else "You have been expelled from our faction."
                    send_message(self, country_name, target, msg_text, "DIPLOMACY")
                    finalize_faction_kick(self.nation_data, country_name, target) 

                elif action == "LEAVE_FACTION":
                    fac = self.nation_data[country_name].get("faction", "")
                    info["cached_members"] = info.get("cached_members", queries.get_faction_members(fac, self.nation_data) if fac else [])
                    log_global_event(self.nation_data, f"{country_name} has abandoned their faction.")
                    msg_text = custom_msg if custom_msg else "We are withdrawing from the faction."
                    
                    for m in info["cached_members"]:
                        if m != country_name:
                            send_message(self, country_name, m, msg_text, "DIPLOMACY")
                            
                    finalize_faction_leave(self.nation_data, country_name)
                    
                elif action == "JOIN_FACTION_REQ":
                    msg_text = custom_msg if custom_msg else "We formally request to join your faction."
                    send_message(self, country_name, target, msg_text, "DIPLOMACY")

                # Cleanup or increment
                if target in actions_to_clear:
                    pass # It was executed entirely on turn 0, so we skip the increment
                elif country_name not in getattr(self, 'active_players', []) and action.startswith("MSG:"):
                    # If an AI sent a pure message, it's delivered instantly on turn 0, so clear it.
                    actions_to_clear.append(target)
                else:
                    info["turns"] += 1

            elif turns == 1:
                is_human_target = target in getattr(self, 'active_players', [])

                if is_unilateral:
                    if action == "DISBAND_FACTION" or action == "LEAVE_FACTION":
                        members = info.get("cached_members", [])
                        for m in members:
                            if m != country_name and m not in getattr(self, 'active_players', []):
                                if action == "DISBAND_FACTION":
                                    reply_dict = ai_results.get((country_name, m, action), {})
                                    msg_text = reply_dict.get("message", ai_prompts.AI_FALLBACK_RESPONSES.get("FACTION_DISBANDED", "It is a shame to see our alliance broken."))
                                else:
                                    reply_dict = ai_results.get((country_name, m, action), {})
                                    msg_text = reply_dict.get("message", ai_prompts.AI_FALLBACK_RESPONSES.get("FACTION_ABANDONED", "We will not forget your abandonment."))
                                
                                op_val = reply_dict.get("opinion_change", 0)
                                if op_val != 0:
                                    queries.add_temporary_modifier(m, country_name, "general", op_val, self.nation_data)
                                    
                                send_message(self, m, country_name, msg_text, "DIPLOMACY")
                                process_ai_retaliation(m, reply_dict)
                                
                    elif not is_human_target:
                        reply_dict = ai_results.get((country_name, target, action), {})
                            
                        message = reply_dict.get("message", ai_prompts.AI_FALLBACK_RESPONSES.get("GENERIC_MESSAGE", "Message received."))
                        
                        op_val = reply_dict.get("opinion_change", 0)
                        if op_val != 0:
                            queries.add_temporary_modifier(target, country_name, "general", op_val, self.nation_data)
                            
                        send_message(self, target, country_name, message, "DIPLOMACY")
                        process_ai_retaliation(target, reply_dict)
                        
                    actions_to_clear.append(target)

                elif action.startswith("MSG:"):
                    if not is_human_target:
                        reply_dict = ai_results.get((country_name, target, "CUSTOM_MSG"), {})
                            
                        message = reply_dict.get("message", "Message received.")
                        
                        op_val = reply_dict.get("opinion_change", 0)
                        if op_val != 0:
                            queries.add_temporary_modifier(target, country_name, "general", op_val, self.nation_data)
                            
                        process_ai_retaliation(target, reply_dict)
                        
                        msg_type = "TEXT" if reply_dict.get("action", "NONE") == "NONE" else "DIPLOMACY"
                        send_message(self, target, country_name, message, msg_type)
                        
                    actions_to_clear.append(target)

                elif action in c.BILATERAL_ACTIONS:
                    if is_human_target:
                        # Check if the target has queued an ACCEPT or REJECT for this specific action
                        target_pending = self.nation_data.get(target, {}).get("pending_diplomacy", {}).get(country_name, {})
                        target_action = target_pending.get("action", "") if isinstance(target_pending, dict) else ""
                        
                        if target_action in [f"ACCEPT_{action}", f"REJECT_{action}"]:
                            # Target has responded, allow their Turn 0 processing to handle it
                            info["turns"] += 1
                        else:
                            # Auto-decline since the human player did not respond immediately on their turn
                            send_message(self, target, country_name, "Your proposal was ignored and automatically declined.", "DIPLOMACY")
                            actions_to_clear.append(target)
                    else:
                        reply_dict = ai_results.get((country_name, target, action), {})
                            
                        accepted = reply_dict.get("accepted", False)
                        message = reply_dict.get("message", "Timeout.")
                        
                        op_val = reply_dict.get("opinion_change", 0)
                        if op_val != 0:
                            queries.add_temporary_modifier(target, country_name, "general", op_val, self.nation_data)

                        process_ai_retaliation(target, reply_dict)
                        
                        if accepted:
                            if action == "FACTION_INVITE":
                                if not self.nation_data[target].get("faction", ""):
                                    finalize_faction_join(self.map_data, self.nation_data, country_name, target)
                                else:
                                    message = "We wanted to accept, but we are already in a faction."
                            elif action == "JOIN_FACTION_REQ":
                                if not self.nation_data[country_name].get("faction", ""):
                                    finalize_faction_join(self.map_data, self.nation_data, target, country_name)
                                else:
                                    message = "We cannot accept as you are already in a faction."
                            elif action == "CEASEFIRE":
                                finalize_neutral(self.nation_data, country_name, target)
                            elif action == "PEACE_TREATY":
                                treaty_type = info.get("message", getattr(c, 'PEACE_WHITE_PEACE', "Ceasefire (White Peace)"))
                                execute_peace_treaty(self.map_data, self.nation_data, country_name, target, treaty_type, self)
                            elif action == "CALL_TO_ARMS":
                                join_faction_wars(self.map_data, self.nation_data, target, country_name)
                                log_global_event(self.nation_data, f"ESCALATION: {target} answered the call to arms of {country_name}!")
                            elif action == "CREATE_FACTION":
                                if not self.nation_data[country_name].get("faction", "") and not self.nation_data[target].get("faction", ""):
                                    finalize_create_faction(self.map_data, self.nation_data, country_name)
                                    finalize_faction_join(self.map_data, self.nation_data, country_name, target)
                                    log_global_event(self.nation_data, f"{country_name} and {target} have formed a new global faction!")
                                else:
                                    message = "The proposed faction could not be formed because one of us is already bound by other treaties."
                            elif action == "JOIN_WARS":
                                join_faction_wars(self.map_data, self.nation_data, country_name, target)
                                log_global_event(self.nation_data, f"ESCALATION: {country_name} has joined the wars of {target}!")
                        
                        send_message(self, target, country_name, message, "DIPLOMACY")
                        actions_to_clear.append(target)

            elif turns > 1:
                # It should never reach this point, but just in case it does...
                # Auto-decline if ignored for 0 turns (applies to both AI and Human targets)
                if turns >= 0 and action in c.BILATERAL_ACTIONS:
                    send_message(self, target, country_name, "Your proposal was ignored and automatically declined.", "DIPLOMACY")
                    actions_to_clear.append(target)
                else:
                    info["turns"] += 1

        for t in actions_to_clear:
            if t in pending:
                del pending[t]

    # Process delayed AI responses (like war declarations) converting them to normal queued diplomacy actions
    for sender, receiver, act, tns, msg in delayed_responses:
        pd = self.nation_data.get(sender, {}).setdefault("pending_diplomacy", {})
        if receiver not in pd or (isinstance(pd[receiver], dict) and pd[receiver].get("turns", 0) == 0):
            pd[receiver] = {"action": act, "turns": tns, "timer": 0, "message": msg}

    # --- PROCESS CLAIM QUEUES ---
    for country_name, data in list(self.nation_data.items()):
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
                
                if country_name == self.player_country:
                    self.show_feedback(f"Claim on Province {prov_id} complete!")

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
                    revoke_queue.pop(i)
                    
                    if country_name == self.player_country:
                        self.show_feedback(f"Claim on Province {prov_id} revoked!")