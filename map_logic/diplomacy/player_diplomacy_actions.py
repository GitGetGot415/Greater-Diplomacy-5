from data import queries
from map_logic.diplomacy import diplomacy_logic
import data.constants as c

def handle_declare_war(map_screen):
    target = map_screen.selected_province.get("owner")
    at_war = queries.are_at_war(map_screen.player_country, target, map_screen.nation_data)
    
    if at_war:
        handle_ceasefire(map_screen)
        return

    # Prevent declaring war on your own faction
    if queries.are_in_same_faction(map_screen.player_country, target, map_screen.nation_data):
        map_screen.show_feedback("Cannot declare war on a faction member!")
        return

    # Prevent declaring war with active truce
    if queries.has_active_truce(map_screen.player_country, target, map_screen.nation_data):
        map_screen.show_feedback("Cannot declare war while a truce is active!")
        return

    # Direct import to bypass __init__.py namespace issues
    from ui.player_diplomacy_menus import open_wargoal_selection_menu
    open_wargoal_selection_menu(map_screen, target)

def open_claims_menu(map_screen):
    from ui.player_diplomacy_menus import open_claims_menu
    open_claims_menu(map_screen)

def handle_ceasefire(map_screen):
    target = map_screen.selected_province.get("owner")
    
    # Guard check: Prevent modifying or opening a peace offer if it has already been sent (turns > 0)
    pending_action, pending_turns = queries.get_diplomatic_status(map_screen.player_country, target, map_screen.nation_data)
    if pending_action in ["PEACE_TREATY", "CEASEFIRE"] and pending_turns > 0:
        map_screen.show_feedback("You must wait for their response to your peace offer!")
        return
        
    # Direct import to bypass __init__.py namespace issues
    from ui.player_diplomacy_menus import open_peace_menu
    open_peace_menu(map_screen, target)

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

def handle_accept_req(map_screen, target=None, custom_msg=None):
    """Processes the execution of accepting an incoming proposal."""
    if not target:
        target = map_screen.selected_province.get("owner")
        
    action, incoming_turns = queries.get_diplomatic_status(target, map_screen.player_country, map_screen.nation_data)
    
    # If we are UNDOING the acceptance:
    pending_action, pending_turns = queries.get_diplomatic_status(map_screen.player_country, target, map_screen.nation_data)
    if pending_action == f"ACCEPT_{action}" and pending_turns == 0:
        msg = diplomacy_logic.toggle_diplomacy_action(map_screen.nation_data, map_screen.player_country, target, f"ACCEPT_{action}", "")
        map_screen.show_feedback(msg)
        return

    if incoming_turns > 0:
        my_faction = map_screen.nation_data[map_screen.player_country].get("faction", "")
        i_am_leader = queries.is_faction_leader(map_screen.player_country, map_screen.nation_data)
        
        if action == "FACTION_INVITE":
            if my_faction:
                map_screen.show_feedback("Must leave your current faction first!")
                return
        elif action == "JOIN_FACTION_REQ":
            if not i_am_leader:
                map_screen.show_feedback("You are no longer the leader, cannot accept!")
                return
        elif action == "CREATE_FACTION":
                if my_faction:
                    map_screen.show_feedback("Must leave your current faction first!")
                    return
        elif action in ["JOIN_WARS", "CALL_TO_ARMS"]:
            if not queries.are_in_same_faction(map_screen.player_country, target, map_screen.nation_data):
                map_screen.show_feedback("You must be in the same faction to do this!")
                return

        if custom_msg is None:
            custom_msg = getattr(map_screen, "mail_draft_text", "").strip()
            
        msg = diplomacy_logic.toggle_diplomacy_action(map_screen.nation_data, map_screen.player_country, target, f"ACCEPT_{action}", custom_msg)
        
        map_screen.mail_draft_text = ""
        map_screen.mail_input_active = False
        map_screen.refresh_relations_map()
        map_screen.refresh_factions_map()
        map_screen.show_feedback(f"Acceptance queued: {action.replace('_', ' ').title()}")


def handle_reject_req(map_screen, target=None, custom_msg=None):
    """Processes the execution of rejecting an incoming proposal."""
    if not target:
        target = map_screen.selected_province.get("owner")
        
    action, incoming_turns = queries.get_diplomatic_status(target, map_screen.player_country, map_screen.nation_data)

    # If we are UNDOING the rejection:
    pending_action, pending_turns = queries.get_diplomatic_status(map_screen.player_country, target, map_screen.nation_data)
    if pending_action == f"REJECT_{action}" and pending_turns == 0:
        msg = diplomacy_logic.toggle_diplomacy_action(map_screen.nation_data, map_screen.player_country, target, f"REJECT_{action}", "")
        map_screen.show_feedback(msg)
        return

    if incoming_turns > 0:
        if custom_msg is None:
            custom_msg = getattr(map_screen, "mail_draft_text", "").strip()
            
        msg = diplomacy_logic.toggle_diplomacy_action(map_screen.nation_data, map_screen.player_country, target, f"REJECT_{action}", custom_msg)
        
        map_screen.mail_draft_text = ""
        map_screen.mail_input_active = False
        map_screen.show_feedback(f"Rejection queued: {action.replace('_', ' ').title()}")

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