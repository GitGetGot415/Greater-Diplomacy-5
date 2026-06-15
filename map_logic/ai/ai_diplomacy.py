import random
from map_logic.ai import ai_handler, ai_prompts
from data import queries
import data.constants as c
import concurrent.futures

def process_proactive_llm_tasks(map_screen):
    """Processes all queued proactive diplomacy texts in a background ThreadPoolExecutor."""
    tasks = map_screen.proactive_llm_tasks
    
    if not tasks:
        map_screen.proactive_llm_tasks_total = 0
        map_screen.proactive_llm_tasks_completed = 0
        return
        
    human_players = map_screen.active_players
    current_ai_mode = ai_handler.get_ai_mode()
    immersion = ai_handler.get_ai_immersion_level()
    
    # --- DYNAMIC LOADING BAR CALCULATION ---
    task_count = 0
    if current_ai_mode != "OFF":
        if immersion == "ABSOLUTE":
            # In Absolute mode, every single proactive task calls the LLM
            task_count = len(tasks)
        elif immersion == "FULL":
            # In Full mode, only tasks targeting human players call the LLM
            task_count = sum(1 for t in tasks if t["target"] in human_players)
        # In Lite mode, proactive tasks return None immediately, so count remains 0
        
    map_screen.proactive_llm_tasks_total = task_count
    map_screen.proactive_llm_tasks_completed = 0
    
    max_threads = queries.get_ai_threads()
    
    map_screen.loading_status_text = f"Drafting Proactive Responses (0/{map_screen.proactive_llm_tasks_total})..."
    
    active_nations = set(queries.get_living_nations(map_screen.map_data))
    
    # If skipping, bypass the executor entirely to save time and prevent thread leakage
    if map_screen.force_skip_llm:
        for task in tasks:
            final_msg = task["fallback"]
            sender_data = map_screen.nation_data.get(task["sender"], {})
            pending = sender_data.get("pending_diplomacy", {})
            target_info = pending.get(task["target"])
            if isinstance(target_info, dict) and target_info.get("action") == task["action_type"]:
                target_info["message"] = final_msg
        return

    # REMOVED THE "with" BLOCK SO IT DOESN'T BLOCK ON EXIT
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_threads)
    futures = {}
    my_turn_id = ai_handler.CURRENT_TURN_ID
    for task in tasks:
        future = executor.submit(ai_handler.generate_proactive_text, map_screen.nation_data, active_nations, task["sender"], task["target"], task["context"], human_players, my_turn_id)
        futures[future] = task
        
    while futures:
        # Check if the user pressed the Force Skip button
        if map_screen.force_skip_llm:
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
                    
                # Progress Increment Logic
                is_ai_to_human = task["target"] in human_players
                if current_ai_mode != "OFF":
                    if immersion == "ABSOLUTE" or (immersion == "FULL" and is_ai_to_human):
                        map_screen.proactive_llm_tasks_completed += 1
            
            # Tell the executor to shut down WITHOUT waiting for the API requests to finish
            try:
                executor.shutdown(wait=False, cancel_futures=True)
            except TypeError:
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
                final_msg = f"THREAD ERROR: {str(e)}"
                
            # Update the pending dictionary with the final generated message
            sender_data = map_screen.nation_data.get(task["sender"], {})
            pending = sender_data.get("pending_diplomacy", {})
            target_info = pending.get(task["target"])
            if isinstance(target_info, dict) and target_info.get("action") == task["action_type"]:
                target_info["message"] = final_msg
                
            # Progress Increment Logic
            is_ai_to_human = task["target"] in human_players
            if current_ai_mode != "OFF":
                if immersion == "ABSOLUTE" or (immersion == "FULL" and is_ai_to_human):
                    map_screen.proactive_llm_tasks_completed += 1
                    map_screen.loading_status_text = f"Drafting Proactive Responses ({map_screen.proactive_llm_tasks_completed}/{map_screen.proactive_llm_tasks_total})..."
            
    # Clean up gracefully if it finished normally without skipping
    if not map_screen.force_skip_llm:
        executor.shutdown(wait=True)

def process_basic_proactive_ai(map_screen):
    """Hardcoded basic logic for AI to declare war for cores and join faction wars."""
    active_nations = set(queries.get_living_nations(map_screen.map_data))
    ai_nations = queries.get_active_ai_nations(map_screen)
    
    # Grab the active players to pass down for our FULL/ABSOLUTE optimization check
    human_players = map_screen.active_players

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
        my_master = data.get("master", "")
        my_type = data.get("puppet_type", "")
        
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
            # Prevent sending multiple faction requests
            has_pending_faction_req = False
            for target_nation, info in pending.items():
                if isinstance(info, dict) and info.get("action") in ["CREATE_FACTION", "JOIN_FACTION_REQ"]:
                    has_pending_faction_req = True
                    break
                    
            if not has_pending_faction_req:
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
                            fallback = ai_prompts.AI_FALLBACK_RESPONSES["PROACTIVE_JOIN_FACTION"]
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
                            break # Act once per turn to avoid conflicts (lol imagine trying to create 2 seperate factions simultaneously)
                else:
                    # Find nations also at war with our enemy who aren't in a faction to form a new one with
                    potential_partners = []
                    for enemy in my_enemies:
                        enemy_wars = map_screen.nation_data.get(enemy, {}).get("at_war_with", [])
                        for mutual_combatant in enemy_wars:
                            if mutual_combatant == ai_name or mutual_combatant not in active_nations:
                                continue
                            fac = map_screen.nation_data.get(mutual_combatant, {}).get("faction", "")
                            if not fac and mutual_combatant not in potential_partners:
                                potential_partners.append(mutual_combatant)

                    if potential_partners:
                        target_partner = potential_partners[0]
                        if not queries.is_ai_diplo_on_cooldown(ai_name, target_partner, "CREATE_FACTION", map_screen.nation_data):
                            existing = pending.get(target_partner, {})
                            turns = existing.get("turns", 0) if isinstance(existing, dict) else 0

                            if target_partner not in pending or turns == 0:
                                # Updated to reference ai_prompts dynamically
                                action_context = ai_prompts.get_proactive_action_context("CREATE_FACTION")
                                fallback = ai_prompts.AI_FALLBACK_RESPONSES["PROACTIVE_CREATE_FACTION"]
                                pending[target_partner] = {
                                    "action": "CREATE_FACTION",
                                    "turns": 0,
                                    "message": fallback
                                }
                                queries.set_ai_diplo_cooldown(ai_name, target_partner, "CREATE_FACTION", map_screen.nation_data)
                                
                                map_screen.proactive_llm_tasks.append({
                                    "sender": ai_name,
                                    "target": target_partner,
                                    "context": action_context,
                                    "fallback": fallback,
                                    "action_type": "CREATE_FACTION"
                                })

        # --- 2. Call to Arms Logic ---
        if is_already_at_war and my_faction:
            faction_members = queries.get_faction_members(my_faction, map_screen.nation_data)
            for member in faction_members:
                if member == ai_name or member not in active_nations: continue
                
                member_enemies = map_screen.nation_data[member].get("at_war_with", [])
                
                # INDENTED THIS BLOCK
                unshared_wars = [e for e in my_enemies if e not in member_enemies and e in active_nations and not queries.has_active_truce(member, e, map_screen.nation_data)]
                
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
                            

        # --- 3. Faction War Joining Logic ---
        if my_faction:
            faction_members = queries.get_faction_members(my_faction, map_screen.nation_data)
            for member in faction_members:
                if member == ai_name:
                    continue
                
                member_enemies = map_screen.nation_data[member].get("at_war_with", [])
                
                # INDENTED THIS BLOCK
                unshared_wars = [e for e in member_enemies if e not in my_enemies and e in active_nations and not queries.has_active_truce(ai_name, e, map_screen.nation_data)]
                
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
                            
        # --- 4. Declare War for Cores & Claims Logic ---
        if not (my_master and my_type == c.PUPPET_TYPE_INTEGRATED):
            current_turn = queries.get_total_turns(map_screen.time_manager)
            if current_turn >= c.TURNS_TO_WAIT_BEFORE_WAR:
                valid_war_targets = queries.get_nations_holding_our_cores_or_claims(ai_name, map_screen.map_data, map_screen.nation_data)
                
                if valid_war_targets:
                    # ONLY look at nations we actually share a physical border with
                    my_neighbors = queries.get_neighboring_nations(ai_name, map_screen.map_data, map_screen.id_to_province)
                    valid_border_targets = [t for t in valid_war_targets if t in my_neighbors]
                    
                    for target in valid_border_targets:
                        if target not in active_nations: continue
                        if target in my_enemies: continue
                        if queries.are_in_same_faction(ai_name, target, map_screen.nation_data): continue
                        if queries.has_active_truce(ai_name, target, map_screen.nation_data): continue
                        
                        # --- NEW: Skip Integrated Puppets ---
                        t_master = map_screen.nation_data.get(target, {}).get("master", "")
                        t_type = map_screen.nation_data.get(target, {}).get("puppet_type", "")
                        if t_master and t_type == c.PUPPET_TYPE_INTEGRATED:
                            continue
                            
                        # Avoid arbitrary attacks on masters
                        if my_master and my_type == c.PUPPET_TYPE_AUTONOMOUS and target != my_master:
                            continue
                        
                        # Check localized border strength instead of global strength
                        my_border_str, target_border_str = queries.get_border_strength(ai_name, target, map_screen.map_data, map_screen.id_to_province)
                        
                        # Prevent division by zero if they have literally no troops on the border
                        target_border_str = max(1, target_border_str)
                        
                        # Consider total alliance strength, economy, and distractions
                        my_alliance_str = queries.get_alliance_military_strength(ai_name, map_screen.map_data, map_screen.nation_data)
                        target_alliance_str = queries.get_alliance_military_strength(target, map_screen.map_data, map_screen.nation_data)
                        
                        my_econ_power = queries.get_economic_power(ai_name, map_screen.nation_data) / 100.0
                        target_econ_power = queries.get_economic_power(target, map_screen.nation_data) / 100.0

                        # Factor in how distracted the target is by their existing wars
                        target_distraction_str = queries.get_combined_enemy_strength(target, map_screen.map_data, map_screen.nation_data) * c.AI_ENEMY_DISTRACTION_WEIGHT

                        # Add the target's distraction to our perceived power
                        my_total_power = my_alliance_str + my_econ_power + target_distraction_str
                        target_total_power = max(1.0, target_alliance_str + target_econ_power)
                        
                        # AI needs local border superiority AND overall global viability to declare war
                        if queries.ai_thinks_it_can_win(ai_name, target, map_screen.map_data, map_screen.nation_data, map_screen.id_to_province):
                            
                            # Random chance to actually declare war
                            if random.random() <= c.AI_WAR_DECLARATION_CHANCE:
                                has_wargoal = queries.has_wargoal(ai_name, target, map_screen.nation_data, map_screen.map_data)
                                if has_wargoal:
                                    if not queries.is_ai_diplo_on_cooldown(ai_name, target, "WAR_DECLARATION", map_screen.nation_data):
                                        existing = pending.get(target, {})
                                        turns = existing.get("turns", 0) if isinstance(existing, dict) else 0
                                        
                                        if target not in pending or turns == 0:
                                            action_context = ai_prompts.get_proactive_action_context("WAR_DECLARATION", target)
                                            fallback = ai_prompts.AI_FALLBACK_RESPONSES.get("PROACTIVE_DECLARE_WAR", "Your occupation of our rightful territory ends now!")

                                            pending[target] = {
                                                "action": "WAR_DECLARATION",
                                                "turns": 0,
                                                "message": c.WARGOAL_TAKE_CLAIMS
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
                                else:
                                    # Make a claim! (assuming no war is happening)
                                    if not is_already_at_war and not queries.is_ai_diplo_on_cooldown(ai_name, target, "MAKE_CLAIM", map_screen.nation_data):
                                        core_ids = []
                                        for prov in map_screen.map_data.values():
                                            if prov.get("owner") == target and ai_name in prov.get("cores", []):
                                                core_ids.append(prov["id"])

                                        if core_ids:
                                            queue = map_screen.nation_data[ai_name].setdefault("claim_queue", [])
                                            claims = map_screen.nation_data[ai_name].setdefault("claims", [])
                                            for cid in core_ids:
                                                if cid not in claims and not any(q["prov_id"] == cid for q in queue):
                                                    queue.append({"prov_id": cid, "turns_left": c.CLAIM_TURN_CORE})
                                            
                                            queries.set_ai_diplo_cooldown(ai_name, target, "MAKE_CLAIM", map_screen.nation_data, duration=c.AI_CLAIM_COOLDOWN)
                                            break

        # --- 5. Fabricate Claims on Weaker Neighbors ---
        if not is_already_at_war and not (my_master and my_type == c.PUPPET_TYPE_INTEGRATED):
            current_turn = queries.get_total_turns(map_screen.time_manager)
            if current_turn >= c.TURNS_TO_WAIT_BEFORE_WAR:
                my_neighbors = queries.get_neighboring_nations(ai_name, map_screen.map_data, map_screen.id_to_province)
                
                for neighbor in my_neighbors:
                    if neighbor not in active_nations: continue
                    if neighbor in my_enemies: continue
                    if queries.are_in_same_faction(ai_name, neighbor, map_screen.nation_data): continue
                    if queries.has_active_truce(ai_name, neighbor, map_screen.nation_data): continue
                    
                    # Avoid attacking masters or puppets
                    n_master = map_screen.nation_data.get(neighbor, {}).get("master", "")
                    if my_master and my_master == neighbor: continue
                    if n_master and n_master == ai_name: continue
                    
                    # Check if we already have claims on them or an active wargoal
                    has_wg = queries.has_wargoal(ai_name, neighbor, map_screen.nation_data, map_screen.map_data)
                    claims = data.get("claims", [])
                    has_claims_on_them = any(map_screen.id_to_province.get(cid, {}).get("owner") == neighbor for cid in claims)
                    
                    if not has_wg and not has_claims_on_them:
                        if queries.is_weaker_neighbor(ai_name, neighbor, map_screen.map_data, map_screen.nation_data):
                            if not queries.is_ai_diplo_on_cooldown(ai_name, neighbor, "FABRICATE_CLAIM", map_screen.nation_data):
                                
                                valid_targets = queries.get_valid_claim_targets(ai_name, neighbor, map_screen.map_data)
                                if valid_targets:
                                    target_prov = random.choice(valid_targets)
                                    queue = data.setdefault("claim_queue", [])
                                    
                                    # Ensure it's not already in the queue
                                    if not any(q["prov_id"] == target_prov["id"] for q in queue):
                                        queue.append({"prov_id": target_prov["id"], "turns_left": c.CLAIM_TURN_NON_CORE})
                                        queries.set_ai_diplo_cooldown(ai_name, neighbor, "FABRICATE_CLAIM", map_screen.nation_data, duration=c.AI_CLAIM_COOLDOWN)
                                        break  # Limit to queueing one claim per cycle
                        
        # --- Update Progress Bar ---
        map_screen.proactive_tasks_completed += 1
        map_screen.loading_status_text = f"Evaluating AI Grand Strategy ({map_screen.proactive_tasks_completed}/{map_screen.proactive_tasks_total})..."

def process_scripted_events(map_screen):
    """Processes scenario-specific scripted events for AI nations."""
    if not map_screen.scenario_settings.get("use_scripted_events", False):
        return
        
    active_nations = set(queries.get_living_nations(map_screen.map_data))
    human_players = getattr(map_screen, 'active_players', [map_screen.player_country])
    
    for nation_name in active_nations:
        if nation_name in human_players:
            continue # Skip human players
            
        data = map_screen.nation_data.get(nation_name, {})
        events = data.get("scripted_events", [])
        if not events:
            continue
            
        # Keep track of events that have already fired so they don't fire every turn
        fired_events = data.setdefault("fired_scripted_events", [])
        
        for i, evt in enumerate(events):
            if i in fired_events:
                continue
                
            cond_type = evt.get("condition_type")
            cond_val = evt.get("condition_val")
            
            condition_met = False
            if cond_type == "Turn Number":
                try:
                    if queries.get_total_turns(map_screen.time_manager) >= int(cond_val):
                        condition_met = True
                except ValueError:
                    pass
            elif cond_type == "At War With":
                if cond_val in active_nations and queries.are_at_war(nation_name, cond_val, map_screen.nation_data):
                    condition_met = True
            elif cond_type == "In Faction With":
                if cond_val in active_nations and queries.are_in_same_faction(nation_name, cond_val, map_screen.nation_data):
                    condition_met = True
            elif cond_type == "At Peace With":
                if cond_val in active_nations and not queries.are_at_war(nation_name, cond_val, map_screen.nation_data):
                    condition_met = True
                    
            if condition_met:
                action_type = evt.get("action_type")
                action_target = evt.get("action_target")
                
                # Queue the action using existing AI queued actions mechanism
                ai_queue = data.setdefault("queued_ai_actions", [])
                
                eng_action = ""
                if action_type == "Declare War":
                    eng_action = "WAR_DECLARATION"
                elif action_type == "Join Faction":
                    eng_action = "JOIN_FACTION_REQ"
                elif action_type == "Create Faction":
                    eng_action = "CREATE_FACTION"
                    
                if eng_action:
                    ai_queue.append({"target": action_target, "action": eng_action})
                
                fired_events.append(i)