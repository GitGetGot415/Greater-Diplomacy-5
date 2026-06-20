import data.constants as c
from data import queries

def force_war_menu(map_screen): 
    open_spectator_action_menu(map_screen, "WAR")

def force_peace_menu(map_screen): 
    open_spectator_action_menu(map_screen, "PEACE")

def spec_create_faction(map_screen):
    if not map_screen.selected_province: return
    source_nation = map_screen.selected_province.get("owner")
    from map_logic.diplomacy import diplomacy_logic
    diplomacy_logic.finalize_create_faction(map_screen.map_data, map_screen.nation_data, source_nation)
    map_screen.show_feedback(f"Created Faction: {source_nation}")
    map_screen.refresh_relations_map()
    map_screen.refresh_factions_map()

def spec_leave_faction(map_screen):
    if not map_screen.selected_province: return
    source_nation = map_screen.selected_province.get("owner")
    from map_logic.diplomacy import diplomacy_logic
    diplomacy_logic.finalize_faction_leave(map_screen.nation_data, source_nation)
    map_screen.show_feedback(f"Left Faction: {source_nation}")
    map_screen.refresh_relations_map()
    map_screen.refresh_factions_map()

def spec_disband_faction(map_screen):
    if not map_screen.selected_province: return
    source_nation = map_screen.selected_province.get("owner")
    from map_logic.diplomacy import diplomacy_logic
    diplomacy_logic.finalize_disband_faction(map_screen.nation_data, source_nation)
    map_screen.show_feedback(f"Disbanded Faction: {source_nation}")
    map_screen.refresh_relations_map()
    map_screen.refresh_factions_map()

def spec_join_faction(map_screen):
    open_spectator_action_menu(map_screen, "JOIN_FACTION")

def spec_invite_faction(map_screen):
    open_spectator_action_menu(map_screen, "INVITE_FACTION")

def open_spectator_action_menu(map_screen, action_type):
    if not map_screen.selected_province: return
    source_nation = map_screen.selected_province.get("owner")
    if source_nation in c.UNPLAYABLE_NATIONS: return
    
    living_nations = queries.get_living_nations(map_screen.map_data)
    if action_type == "JOIN_FACTION":
        items = sorted([n for n, d in map_screen.nation_data.items() if d.get("is_faction_leader") and n != source_nation])
    elif action_type == "INVITE_FACTION":
        items = sorted([n for n, d in map_screen.nation_data.items() if d.get("is_playable") and not d.get("faction") and n != source_nation])
    elif action_type == "WAR":
        source_enemies = map_screen.nation_data[source_nation].get("at_war_with", [])
        items = sorted([n for n, d in map_screen.nation_data.items() if d.get("is_playable") and n != source_nation and n in living_nations and n not in source_enemies])
    elif action_type == "PEACE":
        source_enemies = map_screen.nation_data[source_nation].get("at_war_with", [])
        items = sorted([n for n in source_enemies if n in living_nations])
    else:
        items = sorted([n for n, d in map_screen.nation_data.items() if d.get("is_playable") and n != source_nation])

    def cb(target_nation):
        from map_logic.diplomacy import diplomacy_logic
        if action_type == "WAR":
            diplomacy_logic.finalize_war(map_screen.map_data, map_screen.nation_data, source_nation, target_nation)
            map_screen.show_feedback(f"Forced War: {source_nation} vs {target_nation}")
        elif action_type == "PEACE":
            diplomacy_logic.finalize_neutral(map_screen.nation_data, source_nation, target_nation)
            map_screen.show_feedback(f"Forced Peace: {source_nation} & {target_nation}")
        elif action_type == "JOIN_FACTION":
            diplomacy_logic.finalize_faction_join(map_screen.map_data, map_screen.nation_data, target_nation, source_nation)
            map_screen.show_feedback(f"Forced Join: {source_nation} joined {target_nation}")
        elif action_type == "INVITE_FACTION":
            diplomacy_logic.finalize_faction_join(map_screen.map_data, map_screen.nation_data, source_nation, target_nation)
            map_screen.show_feedback(f"Forced Invite: {target_nation} joined {source_nation}")
            
        map_screen.refresh_relations_map()
        map_screen.refresh_factions_map()

    queries.open_listbox_selector(map_screen, f"{action_type} for {source_nation}", f"Select Target for {action_type}:", items, cb)