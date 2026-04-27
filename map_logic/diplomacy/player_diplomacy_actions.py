from data import queries
from map_logic.diplomacy import diplomacy_logic

def handle_declare_war(map_screen):
    target = map_screen.selected_province.get("owner")
    action, incoming_turns = queries.get_diplomatic_status(target, map_screen.player_country, map_screen.nation_data)

    if action in ["FACTION_INVITE", "CEASEFIRE", "JOIN_FACTION_REQ", "CALL_TO_ARMS"] and incoming_turns > 0:
        del map_screen.nation_data[target]["pending_diplomacy"][map_screen.player_country]
        diplomacy_logic.send_message(map_screen.nation_data, map_screen.player_country, target, f"We rejected your {action.replace('_', ' ').lower()}.", "DIPLOMACY")
        map_screen.show_feedback("Request Rejected!")
        return

    at_war = queries.are_at_war(map_screen.player_country, target, map_screen.nation_data)
    action = "CEASEFIRE" if at_war else "WAR_DECLARATION"
    
    custom_msg = getattr(map_screen, "mail_draft_text", "").strip()
    msg = diplomacy_logic.toggle_diplomacy_action(map_screen.nation_data, map_screen.player_country, target, action, custom_msg)
    map_screen.mail_input_active = False
    map_screen.show_feedback(msg)

def handle_faction_action(map_screen):
    target = map_screen.selected_province.get("owner")
    
    custom_msg = getattr(map_screen, "mail_draft_text", "").strip()
    player_pending = map_screen.nation_data.get(map_screen.player_country, {}).get("pending_diplomacy", {})

    if target == map_screen.player_country:
        action, turns = queries.get_diplomatic_status(target, target, map_screen.nation_data)
        if turns > 0:
            map_screen.show_feedback("Action already in transit, cannot undo!")
            return
            
        in_faction = map_screen.nation_data[target].get("faction", "")
        is_leader = queries.is_faction_leader(target, map_screen.nation_data)
        
        if not in_faction:
            req_action = "CREATE_FACTION"
        elif is_leader:
            req_action = "DISBAND_FACTION"
        else:
            req_action = "LEAVE_FACTION"
            
        # --- NEW: Check for pending invitations & military actions ---
        if req_action in ["DISBAND_FACTION", "LEAVE_FACTION"]:
            has_blocking_action = False
            invites_to_cancel = []
            
            # Scan through the pending diplomacy dict safely
            for other_nation, info in list(player_pending.items()):
                act = info.get("action", "") if isinstance(info, dict) else info
                tns = info.get("turns", 0) if isinstance(info, dict) else 0
                
                if act == "FACTION_INVITE":
                    if tns > 0:
                        has_blocking_action = True
                    else:
                        invites_to_cancel.append(other_nation)
                elif act in ["JOIN_WARS", "CALL_TO_ARMS"]:
                    has_blocking_action = True
            
            # Block the action entirely if an invite is en route or military action is pending
            if has_blocking_action:
                map_screen.show_feedback("Cannot leave with pending invites or military actions!")
                return
            
            # Silently cancel any unsent invites and proceed with the disband
            if invites_to_cancel:
                for n in invites_to_cancel:
                    del player_pending[n]
        # ------------------------------------------

        msg = diplomacy_logic.toggle_diplomacy_action(map_screen.nation_data, map_screen.player_country, target, req_action, custom_msg)
        map_screen.mail_input_active = False
        map_screen.show_feedback(msg)
        return

    if queries.are_at_war(map_screen.player_country, target, map_screen.nation_data):
        map_screen.show_feedback("Cannot interact with nations you are at war with!")
        return

    action, incoming_turns = queries.get_diplomatic_status(target, map_screen.player_country, map_screen.nation_data)

    if incoming_turns > 0:
        my_faction = map_screen.nation_data[map_screen.player_country].get("faction", "")
        i_am_leader = queries.is_faction_leader(map_screen.player_country, map_screen.nation_data)
        
        if action == "FACTION_INVITE":
            if my_faction:
                map_screen.show_feedback("Must leave your current faction first!")
                return
            diplomacy_logic.finalize_faction_join(map_screen.nation_data, target, map_screen.player_country)
            del map_screen.nation_data[target]["pending_diplomacy"][map_screen.player_country]
            
            msg_text = custom_msg if custom_msg else "We accepted your faction invitation."
            diplomacy_logic.send_message(map_screen.nation_data, map_screen.player_country, target, msg_text, "DIPLOMACY")
            map_screen.mail_draft_text = ""
            map_screen.mail_input_active = False
            
            map_screen.show_feedback("Joined Faction!")
            map_screen.refresh_relations_map()
            map_screen.refresh_factions_map()
            return
        elif action == "JOIN_FACTION_REQ":
            if not i_am_leader:
                map_screen.show_feedback("You are no longer the leader, cannot accept!")
                return
            diplomacy_logic.finalize_faction_join(map_screen.nation_data, map_screen.player_country, target)
            del map_screen.nation_data[target]["pending_diplomacy"][map_screen.player_country]
            
            msg_text = custom_msg if custom_msg else "We accepted your request to join."
            diplomacy_logic.send_message(map_screen.nation_data, map_screen.player_country, target, msg_text, "DIPLOMACY")
            map_screen.mail_draft_text = ""
            map_screen.mail_input_active = False
            
            map_screen.show_feedback("Faction Expanded!")
            map_screen.refresh_relations_map()
            map_screen.refresh_factions_map()
            return
        elif action == "CEASEFIRE":
            diplomacy_logic.finalize_neutral(map_screen.nation_data, map_screen.player_country, target)
            del map_screen.nation_data[target]["pending_diplomacy"][map_screen.player_country]
            
            msg_text = custom_msg if custom_msg else "We accepted your ceasefire terms."
            diplomacy_logic.send_message(map_screen.nation_data, map_screen.player_country, target, msg_text, "DIPLOMACY")
            map_screen.mail_draft_text = ""
            map_screen.mail_input_active = False
            
            map_screen.show_feedback("Ceasefire Accepted!")
            return
        elif action == "CALL_TO_ARMS":
            diplomacy_logic.join_faction_wars(map_screen.nation_data, map_screen.player_country, target)
            del map_screen.nation_data[target]["pending_diplomacy"][map_screen.player_country]
            
            msg_text = custom_msg if custom_msg else "We answer your call. Our forces will join your wars."
            diplomacy_logic.send_message(map_screen.nation_data, map_screen.player_country, target, msg_text, "DIPLOMACY")
            map_screen.mail_draft_text = ""
            map_screen.mail_input_active = False
            
            map_screen.show_feedback("Joined Allies in War!")
            map_screen.refresh_relations_map()
            return

    my_faction = map_screen.nation_data[map_screen.player_country].get("faction", "")
    target_faction = map_screen.nation_data[target].get("faction", "")
    i_am_leader = queries.is_faction_leader(map_screen.player_country, map_screen.nation_data)
    target_is_leader = queries.is_faction_leader(target, map_screen.nation_data)

    if my_faction:
        if not i_am_leader:
            map_screen.show_feedback("Only the faction leader can invite nations!")
            return
        if target_faction:
            map_screen.show_feedback(f"{target} must leave their faction first!")
            return
            
        # --- NEW: Check if currently disbanding ---
        self_action, self_turns = queries.get_diplomatic_status(map_screen.player_country, map_screen.player_country, map_screen.nation_data)
        if self_action in ["DISBAND_FACTION", "LEAVE_FACTION"]:
            map_screen.show_feedback("Cannot invite while your faction is being disbanded!")
            return
        # ------------------------------------------

        msg = diplomacy_logic.toggle_diplomacy_action(map_screen.nation_data, map_screen.player_country, target, "FACTION_INVITE", custom_msg)
        map_screen.mail_input_active = False
        map_screen.show_feedback(msg)
    else:
        if not target_faction:
            map_screen.show_feedback("Neither of you are in a faction. Create one first!")
            return
        if not target_is_leader:
            leader = queries.get_faction_leader(target_faction, map_screen.nation_data)
            if leader:
                target = leader
            else:
                map_screen.show_feedback("That faction has no leader!")
                return
        msg = diplomacy_logic.toggle_diplomacy_action(map_screen.nation_data, map_screen.player_country, target, "JOIN_FACTION_REQ", custom_msg)
        map_screen.mail_input_active = False
        map_screen.show_feedback(msg)

def handle_join_wars(map_screen):
    target = map_screen.selected_province.get("owner")
    if queries.are_at_war(map_screen.player_country, target, map_screen.nation_data):
        map_screen.show_feedback("You cannot join the wars of an enemy!")
        return
    if not queries.are_in_same_faction(map_screen.player_country, target, map_screen.nation_data):
        map_screen.show_feedback("You must be in the same faction to assist them!")
        return
        
    # --- NEW: Check if currently disbanding ---
    self_action, self_turns = queries.get_diplomatic_status(map_screen.player_country, map_screen.player_country, map_screen.nation_data)
    if self_action in ["DISBAND_FACTION", "LEAVE_FACTION"]:
        map_screen.show_feedback("Cannot join wars while leaving the faction!")
        return
    # ------------------------------------------
        
    custom_msg = getattr(map_screen, "mail_draft_text", "").strip()
    msg = diplomacy_logic.toggle_diplomacy_action(map_screen.nation_data, map_screen.player_country, target, "JOIN_WARS", custom_msg)
    map_screen.mail_input_active = False
    map_screen.show_feedback(msg)

def handle_call_to_arms(map_screen):
    target = map_screen.selected_province.get("owner")
    if queries.are_at_war(map_screen.player_country, target, map_screen.nation_data):
        map_screen.show_feedback("Cannot call enemies to arms!")
        return
    if not queries.are_in_same_faction(map_screen.player_country, target, map_screen.nation_data):
        map_screen.show_feedback("You must be in the same faction to call them to arms!")
        return
        
    # --- NEW: Check if currently disbanding ---
    self_action, self_turns = queries.get_diplomatic_status(map_screen.player_country, map_screen.player_country, map_screen.nation_data)
    if self_action in ["DISBAND_FACTION", "LEAVE_FACTION"]:
        map_screen.show_feedback("Cannot call to arms while leaving the faction!")
        return
    # ------------------------------------------
        
    custom_msg = getattr(map_screen, "mail_draft_text", "").strip()
    msg = diplomacy_logic.toggle_diplomacy_action(map_screen.nation_data, map_screen.player_country, target, "CALL_TO_ARMS", custom_msg)
    map_screen.mail_input_active = False
    map_screen.show_feedback(msg)