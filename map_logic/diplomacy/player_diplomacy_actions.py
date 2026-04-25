from data import queries
from map_logic.diplomacy import diplomacy_logic

def handle_declare_war(map_screen):
    target = map_screen.selected_province.get("owner")
    action, incoming_turns = queries.get_diplomatic_status(target, map_screen.player_country, map_screen.nation_data)

    if action in ["FACTION_INVITE", "CEASEFIRE", "JOIN_FACTION_REQ"] and incoming_turns > 0:
        del map_screen.nation_data[target]["pending_diplomacy"][map_screen.player_country]
        diplomacy_logic.send_message(map_screen.nation_data, map_screen.player_country, target, f"We rejected your {action.replace('_', ' ').lower()}.", "DIPLOMACY")
        map_screen.show_feedback("Request Rejected!")
        return

    at_war = queries.are_at_war(map_screen.player_country, target, map_screen.nation_data)
    action = "CEASEFIRE" if at_war else "WAR_DECLARATION"
    
    custom_msg = getattr(map_screen, "mail_draft_text", "").strip()
    msg = diplomacy_logic.toggle_diplomacy_action(map_screen.nation_data, map_screen.player_country, target, action, custom_msg)
    map_screen.mail_draft_text = ""
    map_screen.mail_input_active = False
    map_screen.show_feedback(msg)

def handle_faction_action(map_screen):
    target = map_screen.selected_province.get("owner")
    
    custom_msg = getattr(map_screen, "mail_draft_text", "").strip()

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
            
        msg = diplomacy_logic.toggle_diplomacy_action(map_screen.nation_data, map_screen.player_country, target, req_action, custom_msg)
        map_screen.mail_draft_text = ""
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
        msg = diplomacy_logic.toggle_diplomacy_action(map_screen.nation_data, map_screen.player_country, target, "FACTION_INVITE", custom_msg)
        map_screen.mail_draft_text = ""
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
        map_screen.mail_draft_text = ""
        map_screen.mail_input_active = False
        map_screen.show_feedback(msg)

def handle_join_wars(map_screen):
    # Keep this as it is in your original code
    target = map_screen.selected_province.get("owner")
    if queries.are_at_war(map_screen.player_country, target, map_screen.nation_data):
        map_screen.show_feedback("You cannot join the wars of an enemy!")
        return
    if not queries.are_in_same_faction(map_screen.player_country, target, map_screen.nation_data):
        map_screen.show_feedback("You must be in the same faction to assist them!")
        return
        
    custom_msg = getattr(map_screen, "mail_draft_text", "").strip()
    # --- MODIFIED: Queue the action instead of instant execution ---
    msg = diplomacy_logic.toggle_diplomacy_action(map_screen.nation_data, map_screen.player_country, target, "JOIN_WARS", custom_msg)
    map_screen.mail_draft_text = ""
    map_screen.mail_input_active = False
    map_screen.show_feedback(msg)