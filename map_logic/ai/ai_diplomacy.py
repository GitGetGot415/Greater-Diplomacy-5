from map_logic.ai import ai_handler
from data import queries
import data.constants as c

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
        
        # --- 1. Faction War Joining Logic ---
        if my_faction:
            faction_members = queries.get_faction_members(my_faction, map_screen.nation_data)
            
            for member in faction_members:
                if member == ai_name:
                    continue
                
                member_enemies = map_screen.nation_data[member].get("at_war_with", [])
                unshared_wars = [e for e in member_enemies if e not in my_enemies and e in active_nations]
                
                if unshared_wars:
                    asked_dict = data.setdefault("asked_to_join_wars", {})
                    asked_enemies = asked_dict.setdefault(member, [])
                    
                    new_targets = [e for e in unshared_wars if e not in asked_enemies]
                    
                    if new_targets:
                        target_enemy = new_targets[0]
                        existing = pending.get(member, {})
                        turns = existing.get("turns", 0) if isinstance(existing, dict) else 0
                        
                        if member not in pending or turns == 0:
                            # Try to generate flavor text first
                            action_context = f"mobilizing our forces to join your war against {target_enemy}"
                            llm_msg = ai_handler.generate_proactive_text(ai_name, member, action_context, human_players)
                            msg = llm_msg if llm_msg else c.AI_FALLBACK_RESPONSES.get("PROACTIVE_JOIN_WAR", "Brothers, let us join your fight.")
                            
                            pending[member] = {
                                "action": "JOIN_WARS",
                                "turns": 0,
                                "message": msg
                            }
                            asked_enemies.append(target_enemy)
                            break # Act once per turn to avoid conflicts

        # --- 2. Declare War for Cores Logic (Border Check Only) ---
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
                
                if my_border_str >= (target_border_str * c.AI_WAR_STRENGTH_THRESHOLD):
                    existing = pending.get(target, {})
                    turns = existing.get("turns", 0) if isinstance(existing, dict) else 0
                    
                    if target not in pending or turns == 0:
                        # Try to generate flavor text first
                        action_context = f"declaring war on {target} to reclaim our rightful core territory"
                        llm_msg = ai_handler.generate_proactive_text(ai_name, target, action_context, human_players)
                        msg = llm_msg if llm_msg else c.AI_FALLBACK_RESPONSES.get("PROACTIVE_DECLARE_WAR", "Your occupation of our rightful territory ends now!")

                        pending[target] = {
                            "action": "WAR_DECLARATION",
                            "turns": 0,
                            "message": msg
                        }
                        break
                        
        # --- Update Progress Bar ---
        map_screen.proactive_tasks_completed += 1
        # map_screen.this_will_cause_an_error += 1
        map_screen.loading_status_text = f"Evaluating AI Grand Strategy ({map_screen.proactive_tasks_completed}/{map_screen.proactive_tasks_total})..."