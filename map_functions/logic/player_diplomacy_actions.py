from map_functions.logic import diplomacy_logic, state_queries

def handle_declare_war(map_screen):
    target = map_screen.selected_province.get("owner")
    
    # --- NEW: Use clean queries ---
    action, incoming_turns = state_queries.get_diplomatic_status(target, map_screen.player_country, map_screen.nation_data)

    # ONLY intercept if the request has actually been delivered (turns > 0)
    if action in ["ALLIANCE_REQUEST", "CEASEFIRE"] and incoming_turns > 0:
        del map_screen.nation_data[target]["pending_diplomacy"][map_screen.player_country]
        diplomacy_logic.send_message(map_screen.nation_data, map_screen.player_country, target, f"We rejected your {action.replace('_', ' ').lower()}.", "DIPLOMACY")
        map_screen.show_feedback("Request Rejected!")
        return

    at_war = state_queries.are_at_war(map_screen.player_country, target, map_screen.nation_data)
    
    action = "CEASEFIRE" if at_war else "WAR_DECLARATION"
    msg = diplomacy_logic.toggle_diplomacy_action(map_screen.nation_data, map_screen.player_country, target, action)
    map_screen.show_feedback(msg)

def handle_form_alliance(map_screen):
    target = map_screen.selected_province.get("owner")
    
    # --- NEW: Use clean queries ---
    action, incoming_turns = state_queries.get_diplomatic_status(target, map_screen.player_country, map_screen.nation_data)

    # ONLY intercept if the request has actually been delivered (turns > 0)
    if incoming_turns > 0:
        if action == "ALLIANCE_REQUEST":
            diplomacy_logic.finalize_alliance(map_screen.nation_data, map_screen.player_country, target)
            del map_screen.nation_data[target]["pending_diplomacy"][map_screen.player_country]
            diplomacy_logic.send_message(map_screen.nation_data, map_screen.player_country, target, "We accepted your alliance proposal.", "DIPLOMACY")
            map_screen.show_feedback("Alliance Accepted!")
            return
        elif action == "CEASEFIRE":
            diplomacy_logic.finalize_neutral(map_screen.nation_data, map_screen.player_country, target)
            del map_screen.nation_data[target]["pending_diplomacy"][map_screen.player_country]
            diplomacy_logic.send_message(map_screen.nation_data, map_screen.player_country, target, "We accepted your ceasefire terms.", "DIPLOMACY")
            map_screen.show_feedback("Ceasefire Accepted!")
            return

    allied = state_queries.are_allied(map_screen.player_country, target, map_screen.nation_data)
    
    action = "BREAK_ALLIANCE" if allied else "ALLIANCE_REQUEST"
    msg = diplomacy_logic.toggle_diplomacy_action(map_screen.nation_data, map_screen.player_country, target, action)
    map_screen.show_feedback(msg)