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
        nation_data = map_screen.nation_data.get(owner, {})
        unit_type = queries.get_highest_infantry(nation_data, queries.get_tech_tree(), queries.get_unit_library(), allow_fuel_units=False)

        if unit_type is None:
            map_screen.show_feedback("No buildable unit available to spawn (Infantry may be disabled for this scenario)")
            return

        # Enforce default year if they literally have nothing
        if unit_type == f"Infantry Type {c.START_YEAR}":
            unit_type = f"Infantry Type {c.TACTICAL_DEFAULT_YEAR}"

        new_unit = queries.create_unit_dict(unit_type, owner, queries.get_unit_library())
        new_unit["_is_tactical_ghost"] = True # Tag it so we can delete it if they cancel
        
        active_counters = queries.build_active_unit_counters(map_screen.map_data)
        new_unit["custom_name"] = queries.generate_unit_custom_name(new_unit, active_counters)
        
        province.setdefault("units", []).append(new_unit)
        _stage_tactical_selection(map_screen, new_unit, owner, province)
        
    elif len(units) == 1:
        _stage_tactical_selection(map_screen, units[0], owner, province)
    else:
        # MULTIPLE UNITS: let the player pick one from an in-game list
        unit_by_label = {f"{i+1}. {u.get('type')}": u for i, u in enumerate(units)}

        def on_select(label):
            _stage_tactical_selection(map_screen, unit_by_label[label], owner, province)

        queries.open_listbox_selector(map_screen, "Select Tactical Unit", "Select Unit to Control:",
                                      list(unit_by_label.keys()), on_select)

def _stage_tactical_selection(map_screen, unit, owner, province):
    map_screen.pending_selection = owner
    map_screen.pending_unit = unit
    map_screen.selected_province = province
    map_screen.show_feedback(f"Selected {unit.get('type')} in {owner.title()}...")

def confirm_player_country(map_screen):
    if map_screen.pending_selection:
        map_screen.active_players.append(map_screen.pending_selection)
        
        # --- TACTICAL UNIT LOCK-IN ---
        if map_screen.tactical_mode and hasattr(map_screen, 'pending_unit'):
            if map_screen.pending_unit:
                map_screen.pending_unit.pop("_is_tactical_ghost", None) # Remove the tag, it's a real unit now
            map_screen.player_unit = map_screen.pending_unit
            
            # Start the game with max fuel
            u_type = map_screen.player_unit.get("original_type", map_screen.player_unit.get("type"))
            stats = queries.get_unit_library().get(u_type, {})
            map_screen.unit_economy["fuel"] = c.TACTICAL_MAX_FUEL
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
    if map_screen.tactical_mode and getattr(map_screen, 'pending_unit', None):
        if map_screen.pending_unit.get("_is_tactical_ghost"):
            if map_screen.selected_province:
                units = map_screen.selected_province.get("units", [])
                if map_screen.pending_unit in units:
                    units.remove(map_screen.pending_unit)
    
    map_screen.pending_selection = None
    map_screen.pending_unit = None
    map_screen.selected_province = None

def start_spectator(map_screen):
    """Initializes spectator mode, giving the player global vision and no direct control."""
    map_screen.active_players = ["Spectator"]
    map_screen.current_player_index = 0
    map_screen.player_country = "Spectator"
    map_screen.selection_mode = False
    map_screen.pending_selection = None
    map_screen.pending_unit = None
    map_screen.selected_province = None
    map_screen.hovered_province = None
    map_screen.hover_glow_surf = None
    map_screen.show_feedback("Entered Spectator Mode")
    
    from ui import buttons
    buttons.render_buttons(map_screen)
    map_screen.refresh_relations_map()