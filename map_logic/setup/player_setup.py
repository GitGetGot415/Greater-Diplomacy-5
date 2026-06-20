import data.constants as c
from data import queries
from ui import buttons

def select_player_country(map_screen, province):
    owner = province.get("owner", "Unclaimed")
    if owner in map_screen.nation_data and map_screen.nation_data[owner].get("is_playable"):
        map_screen.pending_selection = owner
        map_screen.selected_province = province 
        map_screen.show_feedback(f"Selected {owner.title()}...")
    else:
        map_screen.show_feedback("Cannot select unowned or non-playable territory")

def select_tactical_unit(map_screen, province):
    owner = province.get("owner", "Unclaimed")
    import data.constants as c
    if owner in c.UNPLAYABLE_NATIONS:
        map_screen.show_feedback("Cannot spawn in unplayable territory!")
        return

    units = province.get("units", [])
    
    if not units:
        # SPAWN A BLANK UNIT
        from data import queries
        nation_data = map_screen.nation_data.get(owner, {})
        unit_type = queries.get_highest_infantry(nation_data, queries.get_tech_tree(), queries.get_unit_library(), allow_fuel_units=False)
        
        # Enforce default year if they literally have nothing
        if unit_type == f"Infantry Type {c.START_YEAR}":
            unit_type = f"Infantry Type {c.TACTICAL_DEFAULT_YEAR}"
            
        unit_stats = queries.get_unit_library().get(unit_type, {})
        new_unit = {
            "type": unit_type,
            "owner": owner,
            "health": unit_stats.get("health", 100),
            "max_health": unit_stats.get("health", 100),
            "speed": unit_stats.get("speed", 1),
            "attack": unit_stats.get("attack", 10),
            "defense": unit_stats.get("defense", 10),
            "level": 0,
            "order": {"type": "MOVE", "path": []},
            "_is_tactical_ghost": True # Tag it so we can delete it if they cancel
        }
        province.setdefault("units", []).append(new_unit)
        _stage_tactical_selection(map_screen, new_unit, owner, province)
        
    elif len(units) == 1:
        _stage_tactical_selection(map_screen, units[0], owner, province)
    else:
        # MULTIPLE UNITS: Open Tkinter menu to pick one
        import tkinter as tk
        from data import queries
        root = queries.create_tk_window("Select Tactical Unit", "300x400")
        map_screen.menu_active = True

        def close_menu():
            map_screen.menu_active = False
            root.destroy()

        root.protocol("WM_DELETE_WINDOW", close_menu)
        tk.Label(root, text="Select Unit to Control:", font=("Arial", 12)).pack(pady=10)
        
        lb = tk.Listbox(root, font=("Arial", 11))
        for i, u in enumerate(units):
            lb.insert(tk.END, f"{i+1}. {u.get('type')}")
        lb.pack(fill="both", expand=True, padx=10)
        
        def on_select(event=None):
            selection = lb.curselection()
            if selection:
                selected_unit = units[selection[0]]
                _stage_tactical_selection(map_screen, selected_unit, owner, province)
            close_menu()

        tk.Button(root, text="Take Control", command=on_select, bg="#4CAF50", fg="white", pady=10).pack(fill="x", padx=10, pady=10)
        lb.bind('<Double-1>', on_select)
        queries.run_tk_loop(map_screen, root)

def _stage_tactical_selection(map_screen, unit, owner, province):
    map_screen.pending_selection = owner
    map_screen.pending_unit = unit
    map_screen.selected_province = province
    map_screen.show_feedback(f"Selected {unit.get('type')} in {owner.title()}...")

def confirm_player_country(map_screen):
    if map_screen.pending_selection:
        map_screen.active_players.append(map_screen.pending_selection)
        
        # --- TACTICAL UNIT LOCK-IN ---
        if getattr(map_screen, 'tactical_mode', False) and hasattr(map_screen, 'pending_unit'):
            if map_screen.pending_unit:
                map_screen.pending_unit.pop("_is_tactical_ghost", None) # Remove the tag, it's a real unit now
            map_screen.player_unit = map_screen.pending_unit
            
            # Start the game with half of max fuel
            u_type = map_screen.player_unit.get("original_type", map_screen.player_unit.get("type"))
            from data import queries
            stats = queries.get_unit_library().get(u_type, {})
            map_screen.unit_economy["fuel"] = stats.get("cost_fuel", 0) / 2.0
            map_screen.unit_economy["fuel_inc"] = stats.get("cost_fuel", 0) * c.UPKEEP_MODIFIERS["fuel"]
            
        map_screen.selected_province = None 
        map_screen.hovered_province = None
        map_screen.hover_glow_surf = None
        
        if len(map_screen.active_players) < map_screen.num_players:
            map_screen.show_feedback(f"Player {len(map_screen.active_players) + 1}, pick a country!")
            map_screen.pending_selection = None
            map_screen.pending_unit = None
        else:
            # Everyone picked, start with Player 1
            map_screen.current_player_index = 0
            map_screen.player_country = map_screen.active_players[0]
            map_screen.selection_mode = False
            map_screen.pending_selection = None
            map_screen.pending_unit = None
            
            map_screen.show_feedback(f"Now playing as {map_screen.player_country}")
            buttons.render_buttons(map_screen)
            map_screen.refresh_relations_map()

def cancel_selection(map_screen):
    # Clean up ghost units
    if getattr(map_screen, 'tactical_mode', False) and getattr(map_screen, 'pending_unit', None):
        if map_screen.pending_unit.get("_is_tactical_ghost"):
            if map_screen.selected_province:
                units = map_screen.selected_province.get("units", [])
                if map_screen.pending_unit in units:
                    units.remove(map_screen.pending_unit)
    
    map_screen.pending_selection = None
    map_screen.pending_unit = None
    map_screen.selected_province = None