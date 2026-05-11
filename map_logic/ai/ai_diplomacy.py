import random
from map_logic.ai import ai_handler, ai_prompts
from data import queries
import data.constants as c
import concurrent.futures

def process_proactive_llm_tasks(map_screen):
    """Processes all queued proactive diplomacy texts in a background ThreadPoolExecutor."""
    tasks = getattr(map_screen, 'proactive_llm_tasks', [])
    map_screen.proactive_llm_tasks_total = len(tasks)
    map_screen.proactive_llm_tasks_completed = 0
    
    if map_screen.proactive_llm_tasks_total == 0:
        return
        
    human_players = getattr(map_screen, 'active_players', [map_screen.player_country])
    current_ai_mode = ai_handler.get_ai_mode()
    
    max_threads = queries.get_ollama_threads() if current_ai_mode == "OLLAMA" else 25
    
    map_screen.loading_status_text = "Drafting Proactive Responses..."
    
    active_nations = list(queries.get_living_nations(map_screen.map_data))
    
    # REMOVED THE "with" BLOCK SO IT DOESN'T BLOCK ON EXIT
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_threads)
    futures = {}
    for task in tasks:
        future = executor.submit(ai_handler.generate_proactive_text, map_screen.nation_data, active_nations, task["sender"], task["target"], task["context"], human_players)
        futures[future] = task
        
    while futures:
        # Check if the user pressed the Force Skip button
        if getattr(map_screen, 'force_skip_llm', False):
            # Cancel pending futures to prevent API spam
            for f in futures:
                f.cancel()
                
            # Apply fallback to everything remaining
            for f, task in futures.items():
                final_msg = task["fallback"]
                
                # If it somehow just finished perfectly before we canceled it
                if f.done() and not f.cancelled():
                    try:
                        llm_msg = f.result()
                        if llm_msg: final_msg = llm_msg
                    except:
                        pass
                        
                sender_data = map_screen.nation_data.get(task["sender"], {})
                pending = sender_data.get("pending_diplomacy", {})
                target_info = pending.get(task["target"])
                if isinstance(target_info, dict) and target_info.get("action") == task["action_type"]:
                    target_info["message"] = final_msg
                    
                map_screen.proactive_llm_tasks_completed += 1
            
            # Tell the executor to shut down WITHOUT waiting for the API requests to finish
            executor.shutdown(wait=False)
            break # Exit the while loop entirely
            
        # Process successfully completed threads in chunks of 0.1 seconds
        done, _ = concurrent.futures.wait(futures.keys(), timeout=0.1, return_when=concurrent.futures.FIRST_COMPLETED)
        for future in done:
            task = futures.pop(future)
            try:
                llm_msg = future.result()
                final_msg = llm_msg if llm_msg else task["fallback"]
            except Exception as e:
                print(f"Thread error in proactive response: {e}")
                final_msg = task["fallback"]
                
            # Update the pending dictionary with the final generated message
            sender_data = map_screen.nation_data.get(task["sender"], {})
            pending = sender_data.get("pending_diplomacy", {})
            target_info = pending.get(task["target"])
            if isinstance(target_info, dict) and target_info.get("action") == task["action_type"]:
                target_info["message"] = final_msg
                
            map_screen.proactive_llm_tasks_completed += 1
            map_screen.loading_status_text = f"Drafting Proactive Responses ({map_screen.proactive_llm_tasks_completed}/{map_screen.proactive_llm_tasks_total})..."
            
    # Clean up gracefully if it finished normally without skipping
    if not getattr(map_screen, 'force_skip_llm', False):
        executor.shutdown(wait=True)

def process_basic_proactive_ai(map_screen):
    """Hardcoded basic logic for AI to declare war for cores and join faction wars."""
    active_nations = list(queries.get_living_nations(map_screen.map_data))
    ai_nations = queries.get_active_ai_nations(map_screen)
    
    # Grab the active players to pass down for our FULL/ABSOLUTE optimization check
    human_players = getattr(map_screen, 'active_players', [map_screen.player_country])

    # --- Trigger the UI Progress Bar ---
    map_screen.proactive_tasks_total = len(ai_nations)
    map_screen.proactive_tasks_completed = 0
    map_screen.loading_status_text = "Evaluating AI Grand Strategy..."

    for ai_name in ai_nations:
        if ai_name not in active_nations:
            map_screen.proactive_tasks_completed += 1
            continue

        data = map_screen.nation_data[ai_name]
        pending = data.setdefault("pending_diplomacy", {})
        my_faction = data.get("faction", "")
        my_enemies = data.get("at_war_with", [])
        
        # --- 0. Decrement Diplomatic Cooldowns ---
        if "diplo_cooldowns" in data:
            for target, actions in list(data["diplo_cooldowns"].items()):
                for act, cd in list(actions.items()):
                    if cd > 0:
                        actions[act] -= 1
                    elif cd == 0:
                        # Clean up finished cooldowns
                        del actions[act]
                if not actions:
                    del data["diplo_cooldowns"][target]

        is_already_at_war = len(my_enemies) > 0
        
        # --- 1. Unreachable Ceasefire Logic ---
        if is_already_at_war:
            for enemy in my_enemies:
                if enemy not in active_nations: continue
                if not queries.is_nation_reachable(ai_name, enemy, map_screen.map_data, map_screen.id_to_province, map_screen.nation_data):
                    if not queries.is_ai_diplo_on_cooldown(ai_name, enemy, "CEASEFIRE", map_screen.nation_data):
                        existing = pending.get(enemy, {})
                        turns = existing.get("turns", 0) if isinstance(existing, dict) else 0
                        
                        if enemy not in pending or turns == 0:
                            action_context = ai_prompts.get_proactive_action_context("CEASEFIRE")
                            fallback = ai_prompts.AI_FALLBACK_RESPONSES.get("PROACTIVE_CEASEFIRE", "We offer terms for a ceasefire.")
                            
                            pending[enemy] = {
                                "action": "CEASEFIRE",
                                "turns": 0,
                                "message": fallback
                            }
                            queries.set_ai_diplo_cooldown(ai_name, enemy, "CEASEFIRE", map_screen.nation_data)
                            
                            map_screen.proactive_llm_tasks.append({
                                "sender": ai_name,
                                "target": enemy,
                                "context": action_context,
                                "fallback": fallback,
                                "action_type": "CEASEFIRE"
                            })
                            break # Act once per turn to avoid conflicts

        # --- 1.5. Defensive Faction Seeking Logic ---
        if is_already_at_war and not my_faction:
            potential_leaders = []
            for enemy in my_enemies:
                # Find nations also at war with our enemy
                enemy_wars = map_screen.nation_data.get(enemy, {}).get("at_war_with", [])
                for mutual_combatant in enemy_wars:
                    if mutual_combatant == ai_name or mutual_combatant not in active_nations:
                        continue
                    # If they have a faction, we want to talk to the leader
                    fac = map_screen.nation_data.get(mutual_combatant, {}).get("faction", "")
                    if fac:
                        fac_leader = queries.get_faction_leader(fac, map_screen.nation_data)
                        if fac_leader and fac_leader not in potential_leaders and fac_leader in active_nations:
                            potential_leaders.append(fac_leader)

            if potential_leaders:
                # Just ask the first valid leader we found
                target_leader = potential_leaders[0]
                if not queries.is_ai_diplo_on_cooldown(ai_name, target_leader, "JOIN_FACTION_REQ", map_screen.nation_data):
                    existing = pending.get(target_leader, {})
                    turns = existing.get("turns", 0) if isinstance(existing, dict) else 0

                    if target_leader not in pending or turns == 0:
                        # --- REFACTORED TO PULL FROM AI_PROMPTS ---
                        action_context = ai_prompts.get_proactive_action_context("JOIN_FACTION_REQ")
                        fallback = ai_prompts.AI_FALLBACK_RESPONSES["PROACTIVE_JOIN_WAR"]
                        pending[target_leader] = {
                            "action": "JOIN_FACTION_REQ",
                            "turns": 0,
                            "message": fallback
                        }
                        queries.set_ai_diplo_cooldown(ai_name, target_leader, "JOIN_FACTION_REQ", map_screen.nation_data)
                        
                        map_screen.proactive_llm_tasks.append({
                            "sender": ai_name,
                            "target": target_leader,
                            "context": action_context,
                            "fallback": fallback,
                            "action_type": "JOIN_FACTION_REQ"
                        })

        # --- 2. Call to Arms Logic ---
        if is_already_at_war and my_faction:
            faction_members = queries.get_faction_members(my_faction, map_screen.nation_data)
            for member in faction_members:
                if member == ai_name or member not in active_nations: continue
                
                member_enemies = map_screen.nation_data[member].get("at_war_with", [])
                unshared_wars = [e for e in my_enemies if e not in member_enemies and e in active_nations]
                
                if unshared_wars:
                    if not queries.is_ai_diplo_on_cooldown(ai_name, member, "CALL_TO_ARMS", map_screen.nation_data):
                        existing = pending.get(member, {})
                        turns = existing.get("turns", 0) if isinstance(existing, dict) else 0
                        
                        if member not in pending or turns == 0:
                            target_enemy = unshared_wars[0]
                            action_context = ai_prompts.get_proactive_action_context("CALL_TO_ARMS", target_enemy)
                            fallback = ai_prompts.AI_FALLBACK_RESPONSES.get("PROACTIVE_CALL_TO_ARMS", "We request your aid in our ongoing conflicts!")
                            
                            pending[member] = {
                                "action": "CALL_TO_ARMS",
                                "turns": 0,
                                "message": fallback
                            }
                            queries.set_ai_diplo_cooldown(ai_name, member, "CALL_TO_ARMS", map_screen.nation_data)
                            
                            map_screen.proactive_llm_tasks.append({
                                "sender": ai_name,
                                "target": member,
                                "context": action_context,
                                "fallback": fallback,
                                "action_type": "CALL_TO_ARMS"
                            })
                            break # Act once per turn to avoid conflicts

        # --- 3. Faction War Joining Logic ---
        if my_faction:
            faction_members = queries.get_faction_members(my_faction, map_screen.nation_data)
            for member in faction_members:
                if member == ai_name:
                    continue
                
                member_enemies = map_screen.nation_data[member].get("at_war_with", [])
                unshared_wars = [e for e in member_enemies if e not in my_enemies and e in active_nations]
                
                if unshared_wars:
                    target_enemy = unshared_wars[0]
                    if not queries.is_ai_diplo_on_cooldown(ai_name, member, "JOIN_WARS", map_screen.nation_data):
                        existing = pending.get(member, {})
                        turns = existing.get("turns", 0) if isinstance(existing, dict) else 0
                        
                        if member not in pending or turns == 0:
                            action_context = ai_prompts.get_proactive_action_context("JOIN_WARS", target_enemy)
                            fallback = ai_prompts.AI_FALLBACK_RESPONSES.get("PROACTIVE_JOIN_WAR", "Brothers, let us join your fight.")
                            
                            pending[member] = {
                                "action": "JOIN_WARS",
                                "turns": 0,
                                "message": fallback
                            }
                            queries.set_ai_diplo_cooldown(ai_name, member, "JOIN_WARS", map_screen.nation_data)
                            
                            map_screen.proactive_llm_tasks.append({
                                "sender": ai_name,
                                "target": member,
                                "context": action_context,
                                "fallback": fallback,
                                "action_type": "JOIN_WARS"
                            })
                            break # Act once per turn to avoid conflicts

        # --- 4. Declare War for Cores Logic (Border Check Only) ---
        if not is_already_at_war:
            current_turn = queries.get_total_turns(map_screen.time_manager)
            if current_turn >= c.TURNS_TO_WAIT_BEFORE_WAR:
                targets_holding_cores = queries.get_nations_holding_our_cores(ai_name, map_screen.map_data)
                
                if targets_holding_cores:
                    # ONLY look at nations we actually share a physical border with
                    my_neighbors = queries.get_neighboring_nations(ai_name, map_screen.map_data, map_screen.id_to_province)
                    valid_border_targets = [t for t in targets_holding_cores if t in my_neighbors]
                    
                    for target in valid_border_targets:
                        if target not in active_nations: continue
                        if target in my_enemies: continue
                        if queries.are_in_same_faction(ai_name, target, map_screen.nation_data): continue
                        
                        # Check localized border strength instead of global strength
                        my_border_str, target_border_str = queries.get_border_strength(ai_name, target, map_screen.map_data, map_screen.id_to_province)
                        
                        # Prevent division by zero if they have literally no troops on the border
                        target_border_str = max(1, target_border_str)
                        
                        # --- MODIFIED: Consider total alliance strength, economy, and distractions ---
                        my_alliance_str = queries.get_alliance_military_strength(ai_name, map_screen.map_data, map_screen.nation_data)
                        target_alliance_str = queries.get_alliance_military_strength(target, map_screen.map_data, map_screen.nation_data)
                        
                        my_econ_power = queries.get_economic_power(ai_name, map_screen.nation_data) / 100.0
                        target_econ_power = queries.get_economic_power(target, map_screen.nation_data) / 100.0

                        # Factor in how distracted the target is by their existing wars
                        target_distraction_str = queries.get_combined_enemy_strength(target, map_screen.map_data, map_screen.nation_data) * getattr(c, 'AI_ENEMY_DISTRACTION_WEIGHT', 0.8)

                        # Add the target's distraction to our perceived power
                        my_total_power = my_alliance_str + my_econ_power + target_distraction_str
                        target_total_power = max(1.0, target_alliance_str + target_econ_power)
                        # ---------------------------------------------------------
                        
                        # AI needs local border superiority AND overall global viability to declare war
                        if my_border_str >= (target_border_str * c.AI_WAR_STRENGTH_THRESHOLD) and my_total_power >= (target_total_power * c.AI_GLOBAL_STRENGTH_THRESHOLD):
                            
                            # Random chance to actually declare war
                            if random.random() <= getattr(c, 'AI_WAR_DECLARATION_CHANCE', 0.50):
                                if not queries.is_ai_diplo_on_cooldown(ai_name, target, "WAR_DECLARATION", map_screen.nation_data):
                                    existing = pending.get(target, {})
                                    turns = existing.get("turns", 0) if isinstance(existing, dict) else 0
                                    
                                    if target not in pending or turns == 0:
                                        action_context = ai_prompts.get_proactive_action_context("WAR_DECLARATION", target)
                                        fallback = ai_prompts.AI_FALLBACK_RESPONSES.get("PROACTIVE_DECLARE_WAR", "Your occupation of our rightful territory ends now!")

                                        pending[target] = {
                                            "action": "WAR_DECLARATION",
                                            "turns": 0,
                                            "message": fallback
                                        }
                                        queries.set_ai_diplo_cooldown(ai_name, target, "WAR_DECLARATION", map_screen.nation_data)
                                        
                                        map_screen.proactive_llm_tasks.append({
                                            "sender": ai_name,
                                            "target": target,
                                            "context": action_context,
                                            "fallback": fallback,
                                            "action_type": "WAR_DECLARATION"
                                        })
                                        break
                        
        # --- Update Progress Bar ---
        map_screen.proactive_tasks_completed += 1
        map_screen.loading_status_text = f"Evaluating AI Grand Strategy ({map_screen.proactive_tasks_completed}/{map_screen.proactive_tasks_total})..."