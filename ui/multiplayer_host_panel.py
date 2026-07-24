import pygame
import os
import secrets
import tkinter as tk
from tkinter import simpledialog, filedialog
from data.io import multiplayer_io
import data.constants as c



def load_multiplayer_moves(map_ref):
    root = tk.Tk()
    root.withdraw()
    
    files = filedialog.askopenfilenames(
        initialdir=c.TOURNAMENT_SAVES_DIR,
        title="Select Move Files",
        filetypes=[("Move Files", "*.gd5move")]
    )
    if files:
        multiplayer_io.load_move_files(map_ref, files, getattr(map_ref, 'multiplayer_keys_dict', {}))
        map_ref.show_feedback(f"Loaded {len(files)} move files.")

def export_next_turn(map_ref):
    turn = map_ref.time_manager.total_turns
    
    tour_dir = getattr(map_ref, 'multiplayer_tournament_dir', None)
    if not tour_dir and hasattr(map_ref, 'loaded_tournament_path') and map_ref.loaded_tournament_path:
        tour_dir = os.path.dirname(map_ref.loaded_tournament_path)
    if not tour_dir:
        tour_dir = c.TOURNAMENT_SAVES_DIR
        
    os.makedirs(tour_dir, exist_ok=True)
    export_path = os.path.join(tour_dir, f"Turn_{turn}_Host.gd5tour")
    master_key = getattr(map_ref, 'multiplayer_master_key', '')
    keys_dict = getattr(map_ref, 'multiplayer_keys_dict', {})
    
    if not master_key or not keys_dict:
        map_ref.show_feedback("Error: Host keys missing. Did you init multiplayer?")
        return
        
    multiplayer_io.export_tournament(map_ref, export_path, master_key, keys_dict)
    
    # Reset protected countries for next turn
    map_ref.multiplayer_protected_countries = set()
    map_ref.submitted_moves = set()
    map_ref.show_feedback(f"Tournament exported to {export_path}")

def manage_players_panel(map_ref):
    root = tk.Tk()
    root.title("Manage Players & Moves")
    root.geometry("450x600")
    root.attributes("-topmost", True)
    root.focus_force()

    if not hasattr(map_ref, 'multiplayer_protected_countries'):
        map_ref.multiplayer_protected_countries = set()
    if not hasattr(map_ref, 'submitted_moves'):
        map_ref.submitted_moves = set()

    top_frame = tk.Frame(root)
    top_frame.pack(fill=tk.X, padx=10, pady=10)

    lbl = tk.Label(top_frame, text="Load player moves, and select countries to skip (skipped countries will have AI disabled):", wraplength=430)
    lbl.pack(pady=(0, 10))

    def on_load_moves():
        files = filedialog.askopenfilenames(
            parent=root,
            initialdir=c.TOURNAMENT_SAVES_DIR,
            title="Select Move Files",
            filetypes=[("Move Files", "*.gd5move")]
        )
        if files:
            multiplayer_io.load_move_files(map_ref, files, getattr(map_ref, 'multiplayer_keys_dict', {}))
            map_ref.show_feedback(f"Loaded {len(files)} move files.")
            refresh_list()

    load_btn = tk.Button(top_frame, text="Load .gd5move Files", command=on_load_moves, width=20, bg="#add8e6")
    load_btn.pack()

    frame = tk.Frame(root)
    frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
    
    canvas = tk.Canvas(frame)
    scrollbar = tk.Scrollbar(frame, orient="vertical", command=canvas.yview)
    scrollable_frame = tk.Frame(canvas)

    scrollable_frame.bind(
        "<Configure>",
        lambda e: canvas.configure(
            scrollregion=canvas.bbox("all")
        )
    )

    canvas_window = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
    
    def configure_canvas(event):
        canvas.itemconfig(canvas_window, width=event.width)
    canvas.bind("<Configure>", configure_canvas)

    canvas.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)
    
    def _on_mousewheel(event):
        canvas.yview_scroll(int(-1*(event.delta/120)), "units")
    canvas.bind_all("<MouseWheel>", _on_mousewheel)
    
    check_vars = {}
    
    def refresh_list():
        for widget in scrollable_frame.winfo_children():
            widget.destroy()
        check_vars.clear()
        
        active_owners = set(p.get("owner") for p in map_ref.map_data.values())
        countries = [cid for cid, data in map_ref.nation_data.items() if data.get("is_playable") and cid in active_owners]
        countries.sort(key=lambda c: map_ref.nation_data[c].get("name", c))
        
        for cid in countries:
            var = tk.BooleanVar(master=root, value=(cid in map_ref.multiplayer_protected_countries))
            check_vars[cid] = var
            name = map_ref.nation_data[cid].get("name", cid)
            
            has_move = cid in map_ref.submitted_moves
            status = "[SUBMITTED]" if has_move else "[WAITING]"
            color = "green" if has_move else "black"
            
            row_frame = tk.Frame(scrollable_frame)
            row_frame.pack(fill=tk.X, anchor="w", pady=2)
            
            cb = tk.Checkbutton(row_frame, text=f"{name} ({cid})", variable=var)
            cb.pack(side=tk.LEFT, padx=5)
            
            lbl_status = tk.Label(row_frame, text=status, fg=color, font=("Arial", 9, "bold"))
            lbl_status.pack(side=tk.RIGHT, padx=10)
            
    refresh_list()
        
    def on_confirm():
        map_ref.multiplayer_protected_countries.clear()
        skipped_ai_count = 0
        for cid, var in check_vars.items():
            if var.get():
                map_ref.multiplayer_protected_countries.add(cid)
                skipped_ai_count += 1
                
        submitted_count = len(getattr(map_ref, 'submitted_moves', set()))
        if submitted_count > 0 and skipped_ai_count > 0:
            map_ref.show_feedback(f"{submitted_count} player move(s) loaded; {skipped_ai_count} country/countries set to skip AI.")
        elif skipped_ai_count > 0:
            map_ref.show_feedback(f"{skipped_ai_count} country/countries set to skip AI this turn.")
        elif submitted_count > 0:
            map_ref.show_feedback(f"{submitted_count} player move(s) loaded.")
        else:
            map_ref.show_feedback("All unsubmitted countries will be controlled by AI this turn.")
        
        canvas.unbind_all("<MouseWheel>")
        root.quit()
        root.destroy()
        
    def on_closing():
        canvas.unbind_all("<MouseWheel>")
        root.quit()
        root.destroy()

    btn_frame = tk.Frame(root)
    btn_frame.pack(fill=tk.X, pady=10)
    
    confirm_btn = tk.Button(btn_frame, text="Confirm", command=on_confirm, width=15)
    confirm_btn.pack(side=tk.LEFT, padx=30)
    
    cancel_btn = tk.Button(btn_frame, text="Cancel", command=on_closing, width=15)
    cancel_btn.pack(side=tk.RIGHT, padx=30)
    
    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.eval('tk::PlaceWindow . center')
    root.mainloop()

def manage_keys_panel(map_ref):
    root = tk.Tk()
    root.title("Regenerate Player Keys")
    root.geometry("450x600")
    root.attributes("-topmost", True)
    root.focus_force()

    if not hasattr(map_ref, 'multiplayer_pending_key_regen'):
        map_ref.multiplayer_pending_key_regen = set()

    top_frame = tk.Frame(root)
    top_frame.pack(fill=tk.X, padx=10, pady=10)

    lbl = tk.Label(top_frame, text="Select countries whose keys should be regenerated upon exporting the turn/map:", wraplength=430)
    lbl.pack(pady=(0, 10))

    frame = tk.Frame(root)
    frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
    
    canvas = tk.Canvas(frame)
    scrollbar = tk.Scrollbar(frame, orient="vertical", command=canvas.yview)
    scrollable_frame = tk.Frame(canvas)

    scrollable_frame.bind(
        "<Configure>",
        lambda e: canvas.configure(
            scrollregion=canvas.bbox("all")
        )
    )

    canvas_window = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
    
    def configure_canvas(event):
        canvas.itemconfig(canvas_window, width=event.width)
    canvas.bind("<Configure>", configure_canvas)

    canvas.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)
    
    def _on_mousewheel(event):
        canvas.yview_scroll(int(-1*(event.delta/120)), "units")
    canvas.bind_all("<MouseWheel>", _on_mousewheel)
    
    check_vars = {}
    
    def refresh_list():
        for widget in scrollable_frame.winfo_children():
            widget.destroy()
        check_vars.clear()
        
        active_owners = set(p.get("owner") for p in map_ref.map_data.values()) if hasattr(map_ref, 'map_data') and map_ref.map_data else set()
        countries = [cid for cid, data in map_ref.nation_data.items() if data.get("is_playable") and cid in active_owners]
        countries.sort(key=lambda c: map_ref.nation_data[c].get("name", c))
        
        for cid in countries:
            var = tk.BooleanVar(master=root, value=(cid in map_ref.multiplayer_pending_key_regen))
            check_vars[cid] = var
            name = map_ref.nation_data[cid].get("name", cid)
            
            row_frame = tk.Frame(scrollable_frame)
            row_frame.pack(fill=tk.X, anchor="w", pady=2)
            
            cb = tk.Checkbutton(row_frame, text=f"{name} ({cid})", variable=var)
            cb.pack(side=tk.LEFT, padx=5)
            
    refresh_list()
        
    def on_confirm():
        map_ref.multiplayer_pending_key_regen.clear()
        count = 0
        for cid, var in check_vars.items():
            if var.get():
                map_ref.multiplayer_pending_key_regen.add(cid)
                count += 1
        map_ref.show_feedback(f"{count} country key(s) queued for regeneration upon export.")
        
        canvas.unbind_all("<MouseWheel>")
        root.quit()
        root.destroy()
        
    def on_closing():
        canvas.unbind_all("<MouseWheel>")
        root.quit()
        root.destroy()

    btn_frame = tk.Frame(root)
    btn_frame.pack(fill=tk.X, pady=10)
    
    confirm_btn = tk.Button(btn_frame, text="Confirm", command=on_confirm, width=15)
    confirm_btn.pack(side=tk.LEFT, padx=30)
    
    cancel_btn = tk.Button(btn_frame, text="Cancel", command=on_closing, width=15)
    cancel_btn.pack(side=tk.RIGHT, padx=30)
    
    root.protocol("WM_DELETE_WINDOW", on_closing)
    root.eval('tk::PlaceWindow . center')
    root.mainloop()
