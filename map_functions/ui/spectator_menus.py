from data.constants import UNPLAYABLE_NATIONS

def force_war_menu(map_screen): 
    open_spectator_action_menu(map_screen, "WAR")

def force_peace_menu(map_screen): 
    open_spectator_action_menu(map_screen, "PEACE")

def force_alliance_menu(map_screen): 
    open_spectator_action_menu(map_screen, "ALLIANCE")

def force_break_alliance_menu(map_screen): 
    open_spectator_action_menu(map_screen, "BREAK")

def open_spectator_action_menu(map_screen, action_type):
    if not map_screen.selected_province: return
    source_nation = map_screen.selected_province.get("owner")
    if source_nation in UNPLAYABLE_NATIONS: return
    
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
            from map_functions.logic import diplomacy_logic
            
            if action_type == "WAR":
                diplomacy_logic.finalize_war(map_screen.nation_data, source_nation, target_nation)
                map_screen.show_feedback(f"Forced War: {source_nation} vs {target_nation}")
            elif action_type == "PEACE":
                diplomacy_logic.finalize_neutral(map_screen.nation_data, source_nation, target_nation)
                map_screen.show_feedback(f"Forced Peace: {source_nation} & {target_nation}")
            elif action_type == "ALLIANCE":
                diplomacy_logic.finalize_alliance(map_screen.nation_data, source_nation, target_nation)
                map_screen.show_feedback(f"Forced Alliance: {source_nation} & {target_nation}")
            elif action_type == "BREAK":
                diplomacy_logic.finalize_neutral(map_screen.nation_data, source_nation, target_nation)
                map_screen.show_feedback(f"Broke Alliance: {source_nation} & {target_nation}")
                
            map_screen.refresh_relations_map()
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
    
    # Only show other living/playable nations
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
        except:
            break