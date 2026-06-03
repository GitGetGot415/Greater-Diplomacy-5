import tkinter as tk
from tkinter import messagebox
import data.constants as c
from data import queries
from map_logic.diplomacy import diplomacy_logic

def _create_diplo_window(title, geometry):
    """Standardizes creation of diplomacy overlay popups to prevent PyGame hanging."""
    root = tk.Tk()
    root.title(title)
    root.geometry(geometry)
    root.attributes("-topmost", True)
    return root

def _run_diplo_loop(map_screen, root):
    """Runs a non-blocking Tkinter loop perfectly embedded within the PyGame tick sequence."""
    import pygame
    map_screen.menu_active = True
    while map_screen.menu_active:
        try:
            root.update()
            pygame.event.pump()
            pygame.time.wait(getattr(c, 'CPU_LIMITER', 10))
        except (tk.TclError, Exception):
            break

def open_wargoal_selection_menu(map_screen, target_nation):
    root = _create_diplo_window(f"Declare War: {target_nation}", "300x250")
    
    def close_menu():
        map_screen.menu_active = False
        root.destroy()
        
    root.protocol("WM_DELETE_WINDOW", close_menu)
    
    tk.Label(root, text=f"Select Wargoal against {target_nation}:", font=("Arial", 12)).pack(pady=10)
    
    wargoals = map_screen.nation_data.get(map_screen.player_country, {}).get("wargoals", {}).get(target_nation, {})
    
    # Check if a wargoal was successfully generated against this specific target
    available_wargoals = []
    if wargoals:
        available_wargoals.append(wargoals.get("type", getattr(c, 'WARGOAL_TAKE_CLAIMS', "Take Claims")))
    else:
        # Fallback for manual/override forcing
        available_wargoals.append(getattr(c, 'WARGOAL_TAKE_CLAIMS', "Take Claims"))
        available_wargoals.append(getattr(c, 'WARGOAL_ANNEX', "Total Annexation"))
        
    selected_wargoal = tk.StringVar(value=available_wargoals[0])
    
    for wg in available_wargoals:
        tk.Radiobutton(root, text=wg, variable=selected_wargoal, value=wg, font=("Arial", 11)).pack(anchor="w", padx=20)
        
    def on_confirm():
        wg = selected_wargoal.get()
        # Custom message acts as the data packet for the dynamic treaty
        msg = diplomacy_logic.toggle_diplomacy_action(map_screen.nation_data, map_screen.player_country, target_nation, "WAR_DECLARATION", wg)
        map_screen.show_feedback(msg)
        close_menu()
        
    tk.Button(root, text="Declare War", command=on_confirm, bg="#f44336", fg="white", font=("Arial", 11, "bold")).pack(fill="x", padx=20, pady=20)
    
    _run_diplo_loop(map_screen, root)

def open_justify_menu(map_screen, target_nation):
    root = _create_diplo_window(f"Justify Wargoal: {target_nation}", "350x450")
    
    def close_menu():
        map_screen.menu_active = False
        root.destroy()
        
    root.protocol("WM_DELETE_WINDOW", close_menu)
    
    tk.Label(root, text="Select Provinces to Claim:", font=("Arial", 12)).pack(pady=5)
    
    frame = tk.Frame(root)
    frame.pack(fill="both", expand=True, padx=10)
    scrollbar = tk.Scrollbar(frame)
    scrollbar.pack(side="right", fill="y")
    
    lb = tk.Listbox(frame, selectmode=tk.MULTIPLE, yscrollcommand=scrollbar.set, font=("Arial", 11))
    
    valid_targets = queries.get_valid_claim_targets(map_screen.player_country, target_nation, map_screen.map_data)
    
    prov_ids = []
    for prov in valid_targets:
        is_core = map_screen.player_country in prov.get("cores", [])
        core_str = " (CORE)" if is_core else ""
        lb.insert(tk.END, f"Province {prov['id']}{core_str}")
        prov_ids.append(prov['id'])
        
    lb.pack(side="left", fill="both", expand=True)
    scrollbar.config(command=lb.yview)
    
    time_lbl = tk.Label(root, text="Estimated Time: 1 turns", font=("Arial", 10, "italic"))
    time_lbl.pack(pady=5)
    
    def update_time(event=None):
        selection = lb.curselection()
        selected_ids = [prov_ids[i] for i in selection]
        turns = queries.calculate_justification_time(map_screen.player_country, selected_ids, map_screen.id_to_province)
        time_lbl.config(text=f"Estimated Time: {turns} turns")
        
    lb.bind("<<ListboxSelect>>", update_time)
    
    def on_confirm():
        selection = lb.curselection()
        if not selection:
            messagebox.showerror("Error", "You must select at least one province to claim.")
            return
            
        selected_ids = [prov_ids[i] for i in selection]
        turns = queries.calculate_justification_time(map_screen.player_country, selected_ids, map_screen.id_to_province)
        
        # Pass the formatted strings dynamically downstream to the backend
        msg = diplomacy_logic.toggle_diplomacy_action(
            map_screen.nation_data, 
            map_screen.player_country, 
            target_nation, 
            "JUSTIFY_WARGOAL", 
            ",".join(map(str, selected_ids)),
            timer=turns
        )
        map_screen.show_feedback(msg)
        close_menu()
        
    tk.Button(root, text="Start Justification", command=on_confirm, bg="#FF9800", fg="white", font=("Arial", 11, "bold")).pack(fill="x", padx=20, pady=10)
    
    _run_diplo_loop(map_screen, root)

def open_peace_menu(map_screen, target_nation):
    root = _create_diplo_window(f"Peace Treaty: {target_nation}", "300x250")
    
    def close_menu():
        map_screen.menu_active = False
        root.destroy()
        
    root.protocol("WM_DELETE_WINDOW", close_menu)
    
    tk.Label(root, text=f"Propose Terms to {target_nation}:", font=("Arial", 12)).pack(pady=10)
    
    terms = [
        getattr(c, 'PEACE_WHITE_PEACE', "Ceasefire (White Peace)"),
        getattr(c, 'PEACE_DEMAND_CLAIMS', "Demand Claims"),
        getattr(c, 'PEACE_SURRENDER', "Surrender")
    ]
    
    selected_term = tk.StringVar(value=terms[0])
    
    for term in terms:
        tk.Radiobutton(root, text=term, variable=selected_term, value=term, font=("Arial", 11)).pack(anchor="w", padx=20)
        
    def on_confirm():
        term = selected_term.get()
        # Pushes custom term into the packet for the other player (or AI) to read
        msg = diplomacy_logic.toggle_diplomacy_action(map_screen.nation_data, map_screen.player_country, target_nation, "PEACE_TREATY", term)
        map_screen.show_feedback(msg)
        close_menu()
        
    tk.Button(root, text="Send Proposal", command=on_confirm, bg="#4CAF50", fg="white", font=("Arial", 11, "bold")).pack(fill="x", padx=20, pady=20)
    
    _run_diplo_loop(map_screen, root)