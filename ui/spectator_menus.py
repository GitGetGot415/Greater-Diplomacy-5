# ui/spectator_menus.py
import data.constants as c

def force_war_menu(map_screen): 
    open_spectator_action_menu(map_screen, "WAR")

def force_peace_menu(map_screen): 
    open_spectator_action_menu(map_screen, "PEACE")

def spec_create_faction(map_screen):
    if not map_screen.selected_province: return
    source_nation = map_screen.selected_province.get("owner")
    from map_logic.diplomacy import diplomacy_logic
    diplomacy_logic.finalize_create_faction(map_screen.nation_data, source_nation)
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
    
    import tkinter as tk
    root = tk.Tk()
    root.title(f"{action_type} for {source_nation}")
    root.geometry("300x450")
    root.attributes("-topmost", True)
    map_screen.menu_active = True

    def on_select(event=None):
        selection = lb.curselection()
        if selection:
            target_nation = lb.get(selection[0])
            from map_logic.diplomacy import diplomacy_logic
            from data import queries
            
            if action_type == "WAR":
                diplomacy_logic.finalize_war(map_screen.nation_data, source_nation, target_nation)
                map_screen.show_feedback(f"Forced War: {source_nation} vs {target_nation}")
            elif action_type == "PEACE":
                diplomacy_logic.finalize_neutral(map_screen.nation_data, source_nation, target_nation)
                map_screen.show_feedback(f"Forced Peace: {source_nation} & {target_nation}")
            elif action_type == "JOIN_FACTION":
                diplomacy_logic.finalize_faction_join(map_screen.nation_data, target_nation, source_nation)
                map_screen.show_feedback(f"Forced Join: {source_nation} joined {target_nation}")
            elif action_type == "INVITE_FACTION":
                diplomacy_logic.finalize_faction_join(map_screen.nation_data, source_nation, target_nation)
                map_screen.show_feedback(f"Forced Invite: {target_nation} joined {source_nation}")
                
            map_screen.refresh_relations_map()
            map_screen.refresh_factions_map()
        close_menu()

    def close_menu():
        map_screen.menu_active = False
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", close_menu)
    tk.Label(root, text=f"Select Target for {action_type}:", font=("Arial", 12)).pack(pady=10)
    
    frame = tk.Frame(root)
    frame.pack(fill="both", expand=True, padx=10)
    scrollbar = tk.Scrollbar(frame)
    scrollbar.pack(side="right", fill="y")
    
    # --- NEW: Dynamic filtering based on action type ---
    from data import queries
    living_nations = queries.get_living_nations(map_screen.map_data)
    
    if action_type == "JOIN_FACTION":
        nations = sorted([n for n, d in map_screen.nation_data.items() if d.get("is_faction_leader") and n != source_nation])
    elif action_type == "INVITE_FACTION":
        nations = sorted([n for n, d in map_screen.nation_data.items() if d.get("is_playable") and not d.get("faction") and n != source_nation])
    elif action_type == "WAR":
        # Only show alive nations not currently at war with the source
        source_enemies = map_screen.nation_data[source_nation].get("at_war_with", [])
        nations = sorted([n for n, d in map_screen.nation_data.items() if d.get("is_playable") and n != source_nation and n in living_nations and n not in source_enemies])
    elif action_type == "PEACE":
        # Only show alive nations that are currently at war with the source
        source_enemies = map_screen.nation_data[source_nation].get("at_war_with", [])
        nations = sorted([n for n in source_enemies if n in living_nations])
    else:
        nations = sorted([n for n, d in map_screen.nation_data.items() if d.get("is_playable") and n != source_nation])

    lb = tk.Listbox(frame, yscrollcommand=scrollbar.set, font=("Arial", 11))
    for n in nations:
        lb.insert(tk.END, n)
    lb.pack(side="left", fill="both", expand=True)
    scrollbar.config(command=lb.yview)
    
    tk.Button(root, text="Confirm", command=on_select, bg="#4CAF50", fg="white", pady=10).pack(fill="x", padx=10, pady=10)
    lb.bind('<Double-1>', on_select)

    import pygame
    while map_screen.menu_active:
        try:
            root.update()
            pygame.event.pump()
            pygame.time.wait(c.CPU_LIMITER) # --- CPU LIMITER FIX ---
        except:
            break