from data import queries
from map_logic.diplomacy import diplomacy_logic

def handle_declare_war(map_screen):
    target = map_screen.selected_province.get("owner")
    
    # --- NEW: Use clean queries ---
    action, incoming_turns = queries.get_diplomatic_status(target, map_screen.player_country, map_screen.nation_data)

    # ONLY intercept if the request has actually been delivered (turns > 0)
    if action in ["FACTION_INVITE", "CEASEFIRE"] and incoming_turns > 0:
        del map_screen.nation_data[target]["pending_diplomacy"][map_screen.player_country]
        diplomacy_logic.send_message(map_screen.nation_data, map_screen.player_country, target, f"We rejected your {action.replace('_', ' ').lower()}.", "DIPLOMACY")
        map_screen.show_feedback("Request Rejected!")
        return

    at_war = queries.are_at_war(map_screen.player_country, target, map_screen.nation_data)
    
    action = "CEASEFIRE" if at_war else "WAR_DECLARATION"
    msg = diplomacy_logic.toggle_diplomacy_action(map_screen.nation_data, map_screen.player_country, target, action)
    map_screen.show_feedback(msg)

def handle_faction_action(map_screen):
    target = map_screen.selected_province.get("owner")
    
    # Safety Check: Can't invite someone you're shooting at
    if queries.are_at_war(map_screen.player_country, target, map_screen.nation_data):
        map_screen.show_feedback("Cannot invite nations you are at war with!")
        return
    
    # Check if they are already in our faction (to leave/kick)
    if queries.are_in_same_faction(map_screen.player_country, target, map_screen.nation_data):
        diplomacy_logic.finalize_faction_leave(map_screen.nation_data, map_screen.player_country)
        map_screen.show_feedback("Left Faction.")
        map_screen.refresh_relations_map()
        return

    # --- NEW: Use clean queries ---
    action, incoming_turns = queries.get_diplomatic_status(target, map_screen.player_country, map_screen.nation_data)

    # ONLY intercept if the request has actually been delivered (turns > 0)
    if incoming_turns > 0:
        if action == "FACTION_INVITE":
            diplomacy_logic.finalize_faction_join(map_screen.nation_data, target, map_screen.player_country)
            del map_screen.nation_data[target]["pending_diplomacy"][map_screen.player_country]
            diplomacy_logic.send_message(map_screen.nation_data, map_screen.player_country, target, "We accepted your faction invitation.", "DIPLOMACY")
            map_screen.show_feedback("Joined Faction!")
            map_screen.refresh_relations_map()
            return
        elif action == "CEASEFIRE":
            diplomacy_logic.finalize_neutral(map_screen.nation_data, map_screen.player_country, target)
            del map_screen.nation_data[target]["pending_diplomacy"][map_screen.player_country]
            diplomacy_logic.send_message(map_screen.nation_data, map_screen.player_country, target, "We accepted your ceasefire terms.", "DIPLOMACY")
            map_screen.show_feedback("Ceasefire Accepted!")
            return

    msg = diplomacy_logic.toggle_diplomacy_action(map_screen.nation_data, map_screen.player_country, target, "FACTION_INVITE")
    map_screen.show_feedback(msg)

def handle_join_wars(map_screen):
    target = map_screen.selected_province.get("owner")
    
    # Hard Logic Locks
    if queries.are_at_war(map_screen.player_country, target, map_screen.nation_data):
        map_screen.show_feedback("You cannot join the wars of an enemy!")
        return
        
    if not queries.are_in_same_faction(map_screen.player_country, target, map_screen.nation_data):
        map_screen.show_feedback("You must be in the same faction to assist them!")
        return
    
    diplomacy_logic.join_faction_wars(map_screen.nation_data, map_screen.player_country, target)
    map_screen.show_feedback(f"Joined {target}'s wars!")
    map_screen.refresh_relations_map()