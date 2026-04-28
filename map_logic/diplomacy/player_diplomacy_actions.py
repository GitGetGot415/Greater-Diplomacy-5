from data import queries
from map_logic.diplomacy import diplomacy_logic

def handle_declare_war(map_screen):
    target = map_screen.selected_province.get("owner")
    at_war = queries.are_at_war(map_screen.player_country, target, map_screen.nation_data)
    
    # --- FIX: Prevent declaring war on your own faction ---
    if not at_war and queries.are_in_same_faction(map_screen.player_country, target, map_screen.nation_data):
        map_screen.show_feedback("Cannot declare war on a faction member!")
        return

    action = "CEASEFIRE" if at_war else "WAR_DECLARATION"
    
    custom_msg = getattr(map_screen, "mail_draft_text", "").strip()
    msg = diplomacy_logic.toggle_diplomacy_action(map_screen.nation_data, map_screen.player_country, target, action, custom_msg)
    map_screen.mail_input_active = False
    map_screen.show_feedback(msg)

def handle_specific_action(map_screen, action_type):
    """A clean, generic handler replacing the overloaded faction button logic."""
    target = map_screen.selected_province.get("owner")
        
    custom_msg = getattr(map_screen, "mail_draft_text", "").strip()

    # Pre-flight Check: Ensure we don't accidentally leave/disband while an invite is pending
    if action_type in ["LEAVE_FACTION", "DISBAND_FACTION"]:
        player_pending = map_screen.nation_data.get(map_screen.player_country, {}).get("pending_diplomacy", {})
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
        
        # Silently cancel any unsent invites and proceed
        if invites_to_cancel:
            for n in invites_to_cancel:
                del player_pending[n]

    # Pass the validated action down to the engine
    msg = diplomacy_logic.toggle_diplomacy_action(map_screen.nation_data, map_screen.player_country, target, action_type, custom_msg)
    map_screen.mail_input_active = False
    map_screen.show_feedback(msg)

def handle_accept_req(map_screen):
    """Processes the execution of accepting an incoming proposal."""
    target = map_screen.selected_province.get("owner")
    action, incoming_turns = queries.get_diplomatic_status(target, map_screen.player_country, map_screen.nation_data)
    custom_msg = getattr(map_screen, "mail_draft_text", "").strip()
    
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
            map_screen.show_feedback("Joined Faction!")

        elif action == "JOIN_FACTION_REQ":
            if not i_am_leader:
                map_screen.show_feedback("You are no longer the leader, cannot accept!")
                return
            diplomacy_logic.finalize_faction_join(map_screen.nation_data, map_screen.player_country, target)
            del map_screen.nation_data[target]["pending_diplomacy"][map_screen.player_country]
            
            msg_text = custom_msg if custom_msg else "We accepted your request to join."
            diplomacy_logic.send_message(map_screen.nation_data, map_screen.player_country, target, msg_text, "DIPLOMACY")
            map_screen.show_feedback("Faction Expanded!")

        elif action == "CREATE_FACTION":
            if my_faction:
                map_screen.show_feedback("Must leave your current faction first!")
                return
            diplomacy_logic.finalize_create_faction(map_screen.nation_data, target)
            diplomacy_logic.finalize_faction_join(map_screen.nation_data, target, map_screen.player_country)
            del map_screen.nation_data[target]["pending_diplomacy"][map_screen.player_country]
            
            msg_text = custom_msg if custom_msg else "We agreed to form a faction with you."
            diplomacy_logic.send_message(map_screen.nation_data, map_screen.player_country, target, msg_text, "DIPLOMACY")
            map_screen.show_feedback("Faction Formed!")

        elif action == "CEASEFIRE":
            diplomacy_logic.finalize_neutral(map_screen.nation_data, map_screen.player_country, target)
            del map_screen.nation_data[target]["pending_diplomacy"][map_screen.player_country]
            msg_text = custom_msg if custom_msg else "We accepted your ceasefire terms."
            diplomacy_logic.send_message(map_screen.nation_data, map_screen.player_country, target, msg_text, "DIPLOMACY")
            map_screen.show_feedback("Ceasefire Accepted!")

        elif action == "CALL_TO_ARMS":
            diplomacy_logic.join_faction_wars(map_screen.nation_data, map_screen.player_country, target)
            del map_screen.nation_data[target]["pending_diplomacy"][map_screen.player_country]
            msg_text = custom_msg if custom_msg else "We answer your call. Our forces will join your wars."
            diplomacy_logic.send_message(map_screen.nation_data, map_screen.player_country, target, msg_text, "DIPLOMACY")
            map_screen.show_feedback("Joined Allies in War!")

        map_screen.mail_draft_text = ""
        map_screen.mail_input_active = False
        map_screen.refresh_relations_map()
        map_screen.refresh_factions_map()

def handle_reject_req(map_screen):
    """Processes the execution of rejecting an incoming proposal."""
    target = map_screen.selected_province.get("owner")
    action, incoming_turns = queries.get_diplomatic_status(target, map_screen.player_country, map_screen.nation_data)

    if incoming_turns > 0:
        del map_screen.nation_data[target]["pending_diplomacy"][map_screen.player_country]
        diplomacy_logic.send_message(map_screen.nation_data, map_screen.player_country, target, f"We rejected your {action.replace('_', ' ').lower()}.", "DIPLOMACY")
        map_screen.show_feedback("Request Rejected!")
        map_screen.mail_input_active = False

def handle_join_wars(map_screen):
    target = map_screen.selected_province.get("owner")
    if queries.are_at_war(map_screen.player_country, target, map_screen.nation_data):
        map_screen.show_feedback("You cannot join the wars of an enemy!")
        return
    if not queries.are_in_same_faction(map_screen.player_country, target, map_screen.nation_data):
        map_screen.show_feedback("You must be in the same faction to assist them!")
        return
        
    # --- Check if currently disbanding ---
    self_action, self_turns = queries.get_diplomatic_status(map_screen.player_country, map_screen.player_country, map_screen.nation_data)
    if self_action in ["DISBAND_FACTION", "LEAVE_FACTION"]:
        map_screen.show_feedback("Cannot join wars while leaving the faction!")
        return
        
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
        
    # --- Check if currently disbanding ---
    self_action, self_turns = queries.get_diplomatic_status(map_screen.player_country, map_screen.player_country, map_screen.nation_data)
    if self_action in ["DISBAND_FACTION", "LEAVE_FACTION"]:
        map_screen.show_feedback("Cannot call to arms while leaving the faction!")
        return
        
    custom_msg = getattr(map_screen, "mail_draft_text", "").strip()
    msg = diplomacy_logic.toggle_diplomacy_action(map_screen.nation_data, map_screen.player_country, target, "CALL_TO_ARMS", custom_msg)
    map_screen.mail_input_active = False
    map_screen.show_feedback(msg)