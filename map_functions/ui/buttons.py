import pygame
from ui_elements import Button
from data.constants import (
    SCREEN_WIDTH, SCREEN_HEIGHT, TOP_BAR_UI_CENTER_Y, BOTTOM_BAR_UI_CENTER_Y,
    VIEW_BTN_START_X, VIEW_BTN_STEP_X, VIEW_BTN_ROW1_Y, VIEW_BTN_ROW2_Y,
    ACTION_BTN_X, ACTION_BTN_START_Y, ACTION_BTN_STEP_Y,
    LEFT_UI_BAR_X, BTN_RESEARCH_Y, BTN_SAVE_Y, BTN_ECONOMY_Y, BTN_MESSAGES_Y,
    BTN_SPECTATOR_Y, EDITOR_BOT_BTN_START_X, EDITOR_BOT_BTN_STEP_X
)
from map_functions.rendering import symbol_loader
from map_functions.logic import state_queries

def render_buttons(self):
    if not self.selection_mode:
        unit_icon = symbol_loader.get_symbol("Infantry", 2)
        economy_icon = symbol_loader.get_symbol("Factory", 2)
        blank_icon = symbol_loader.get_symbol("Star", 2)
        terrain_icon = symbol_loader.get_symbol("Mountains", 1.5)
        political_icon = symbol_loader.get_symbol("Flag", 1.5)
        relations_icon = symbol_loader.get_symbol("Heart", 2)
        research_icon = symbol_loader.get_symbol("Research", 2)
        mail_icon = symbol_loader.get_symbol("Mail", 2)
        save_icon = symbol_loader.get_symbol("Save", 2)
        core_icon = symbol_loader.get_symbol("Star", 1.5)
        resource_icon = symbol_loader.get_symbol("Iron", 2)

        # Refresh Buttons
        self.elements = [
            Button(SCREEN_WIDTH - 420, TOP_BAR_UI_CENTER_Y, "small", "grey", "Pol Refresh", self.refresh_political_map),
            Button(SCREEN_WIDTH - 320, TOP_BAR_UI_CENTER_Y, "small", "grey", "Rel Refresh", self.refresh_relations_map),
            Button(SCREEN_WIDTH - 220, TOP_BAR_UI_CENTER_Y, "small", "grey", "Core Refresh", self.refresh_cores_map),
        ]

        econ_callback = self.open_editor_economy if getattr(self, 'is_editor', False) else self.open_economy_screen
        
        # View Type Buttons utilizing new constants
        self.elements.extend([
            Button(VIEW_BTN_START_X, VIEW_BTN_ROW1_Y, "small_square", "green", "Terrain", self.set_terrain, image=terrain_icon, show_text=False),
            Button(VIEW_BTN_START_X + VIEW_BTN_STEP_X, VIEW_BTN_ROW1_Y, "small_square", "light_blue", "Political", self.set_political, image=political_icon, show_text=False),
            Button(VIEW_BTN_START_X + VIEW_BTN_STEP_X * 2, VIEW_BTN_ROW1_Y, "small_square", "purple", "Relations", self.set_relations, image=relations_icon, show_text=False),
            Button(VIEW_BTN_START_X + VIEW_BTN_STEP_X * 3, VIEW_BTN_ROW1_Y, "small_square", "pink", "Cores", self.set_cores, image=core_icon, show_text=False),
            
            Button(VIEW_BTN_START_X, VIEW_BTN_ROW2_Y, "small_square", "purple", "Resources", lambda: self.set_view_mode("RESOURCES"), image=resource_icon, show_text=False),
            Button(VIEW_BTN_START_X + VIEW_BTN_STEP_X, VIEW_BTN_ROW2_Y, "small_square", "yellow", "Blank", lambda: self.set_view_mode("BLANK"), image=blank_icon, show_text=False),
            Button(VIEW_BTN_START_X + VIEW_BTN_STEP_X * 2, VIEW_BTN_ROW2_Y, "small_square", "red", "Units", lambda: self.set_view_mode("UNITS"), image=unit_icon, show_text=False),
            Button(VIEW_BTN_START_X + VIEW_BTN_STEP_X * 3, VIEW_BTN_ROW2_Y, "small_square", "orange", "Economy", lambda: self.set_view_mode("ECONOMY"), image=economy_icon, show_text=False),
        ])

        if self.is_editor:
            self.elements.extend([
                Button(EDITOR_BOT_BTN_START_X, BOTTOM_BAR_UI_CENTER_Y, "small", "blue", "Save", self.save_map_data),
                Button(EDITOR_BOT_BTN_START_X - EDITOR_BOT_BTN_STEP_X, BOTTOM_BAR_UI_CENTER_Y, "small", "blue", "Load", self.editor_load_map),
                Button(EDITOR_BOT_BTN_START_X - EDITOR_BOT_BTN_STEP_X*2, BOTTOM_BAR_UI_CENTER_Y, "small", "grey", "Nation", self.select_brush_nation),
                Button(EDITOR_BOT_BTN_START_X - EDITOR_BOT_BTN_STEP_X*3, BOTTOM_BAR_UI_CENTER_Y, "small", "pink", "Core Brush", self.select_core_brush),
                Button(EDITOR_BOT_BTN_START_X - EDITOR_BOT_BTN_STEP_X*3, SCREEN_HEIGHT - 110, "small", "pink", "Auto-Core", self.auto_assign_cores),
                
                Button(EDITOR_BOT_BTN_START_X - EDITOR_BOT_BTN_STEP_X*4, SCREEN_HEIGHT - 110, "small", "purple", "Resource", self.select_resource_brush),
                Button(EDITOR_BOT_BTN_START_X - EDITOR_BOT_BTN_STEP_X*4, BOTTOM_BAR_UI_CENTER_Y, "small", "grey", "Building", self.select_building_brush),
                
                Button(EDITOR_BOT_BTN_START_X - EDITOR_BOT_BTN_STEP_X*5, SCREEN_HEIGHT - 110, "small", "red", "Sync Units", self.sync_units_to_data),
                Button(EDITOR_BOT_BTN_START_X - EDITOR_BOT_BTN_STEP_X*5, BOTTOM_BAR_UI_CENTER_Y, "small", "grey", "Unit", self.select_unit_brush),
                
                Button(EDITOR_BOT_BTN_START_X - EDITOR_BOT_BTN_STEP_X*6, BOTTOM_BAR_UI_CENTER_Y, "small", "purple", "Map Tech", self.open_map_research_editor),
                Button(EDITOR_BOT_BTN_START_X - EDITOR_BOT_BTN_STEP_X*7, BOTTOM_BAR_UI_CENTER_Y, "small", "purple", "Data Refresh", self.refresh_nation_data),
                Button(EDITOR_BOT_BTN_START_X - EDITOR_BOT_BTN_STEP_X*8, BOTTOM_BAR_UI_CENTER_Y, "small", "purple", "Set Date", self.open_editor_date)
            ])
        else:
            # --- Dynamic Next Turn Button ---
            viewing_ai = getattr(self, 'viewing_ai_moves', False)
            next_btn_text = "Resolve Turn" if viewing_ai else "Next Turn"
            next_btn_color = "red" if viewing_ai else "purple"
            
            # We ALWAYS want the next/resolve button to appear
            self.elements.append(
                Button(EDITOR_BOT_BTN_START_X, BOTTOM_BAR_UI_CENTER_Y, "small", next_btn_color, next_btn_text, self.advance_time)
            )
            
            # Hide the management tools while the AI is moving
            if not viewing_ai:
                self.elements.extend([
                    Button(LEFT_UI_BAR_X, BTN_ECONOMY_Y, "left_ui_bar", "orange", "Economy", econ_callback),
                    Button(LEFT_UI_BAR_X, BTN_RESEARCH_Y, "left_ui_bar", "blue", "R&D", self.open_research, image=research_icon),
                    Button(LEFT_UI_BAR_X, BTN_SAVE_Y, "left_ui_bar", "green", "Save", self.save_map_data, image=save_icon),
                    Button(180, 10, "small", "orange", "Edit Nation", self.open_edit_country),
                    Button(LEFT_UI_BAR_X, BTN_MESSAGES_Y, "left_ui_bar", "purple", "Messages", self.open_messages, image=mail_icon)
                ])
        
    # Standard Action Buttons utilizing constants
    self.btn_go_recruit = Button(ACTION_BTN_X, ACTION_BTN_START_Y, "medium", "green", "Recruit Menu", self.open_recruit)
    self.btn_go_orders = Button(ACTION_BTN_X, ACTION_BTN_START_Y + ACTION_BTN_STEP_Y, "medium", "blue", "Give Orders", self.open_orders)
    self.btn_go_build = Button(ACTION_BTN_X, ACTION_BTN_START_Y + ACTION_BTN_STEP_Y * 2, "medium", "grey", "Construction", self.open_construction)

    self.btn_declare_war = Button(ACTION_BTN_X, ACTION_BTN_START_Y, "medium", "red", "Declare War", self.handle_declare_war)
    self.btn_form_alliance = Button(ACTION_BTN_X, ACTION_BTN_START_Y + ACTION_BTN_STEP_Y, "medium", "green", "Form Alliance", self.handle_form_alliance)

    # Spectator God Power Buttons
    self.btn_force_war = Button(ACTION_BTN_X, ACTION_BTN_START_Y, "medium", "red", "Force War", self.force_war_menu)
    self.btn_force_peace = Button(ACTION_BTN_X, ACTION_BTN_START_Y + ACTION_BTN_STEP_Y, "medium", "green", "Force Ceasefire", self.force_peace_menu)
    self.btn_force_alliance = Button(ACTION_BTN_X, ACTION_BTN_START_Y + ACTION_BTN_STEP_Y * 2, "medium", "blue", "Force Alliance", self.force_alliance_menu)
    self.btn_break_alliance = Button(ACTION_BTN_X, ACTION_BTN_START_Y + ACTION_BTN_STEP_Y * 3, "medium", "orange", "Break Alliance", self.force_break_alliance_menu)

    # NEW: Spectator Mode Toggle Button
    self.btn_spectator = Button(LEFT_UI_BAR_X, BTN_SPECTATOR_Y, "medium", "grey", "Spectator Mode", self.start_spectator)

    self.btn_close_info = Button(SCREEN_WIDTH - 120, TOP_BAR_UI_CENTER_Y, "small", "red", "X", self.deselect_province)
    self.btn_exit_to_menu = Button(SCREEN_WIDTH - 120, TOP_BAR_UI_CENTER_Y, "small", "red", "Exit", self.exit_to_menu)

    # Hide context-dependent buttons by default
    for btn in [
        self.btn_go_build, self.btn_close_info, self.btn_exit_to_menu, self.btn_go_recruit, 
        self.btn_go_orders, self.btn_declare_war, self.btn_form_alliance, self.btn_force_war, 
        self.btn_force_peace, self.btn_force_alliance, self.btn_break_alliance, self.btn_spectator
    ]:
        btn.visible = False
        self.elements.append(btn)

def update_button_states(map_screen):
    """Dynamically updates button visibility, colors, and text every frame."""
    
    # reset all to invisible first
    for el in map_screen.elements:
        el.visible = False

        if hasattr(el, 'text'):
            if el.text == "Terrain": el.is_selected = (map_screen.base_layer == "TERRAIN")
            elif el.text == "Political": el.is_selected = (map_screen.base_layer == "POLITICAL")
            elif el.text == "Relations": el.is_selected = (map_screen.base_layer == "RELATIONS")
            elif el.text == "Cores": el.is_selected = (map_screen.base_layer == "CORES")
            elif el.text == "Units": el.is_selected = (map_screen.secondary_mode == "UNITS")
            elif el.text == "Blank": el.is_selected = (map_screen.secondary_mode == "BLANK")
            elif el.text == "Economy":
                if not getattr(el, 'show_text', True): el.is_selected = (map_screen.secondary_mode == "ECONOMY")
                else: el.is_selected = False
            elif el.text == "Resources": el.is_selected = (map_screen.secondary_mode == "RESOURCES")
            else: el.is_selected = False

    if map_screen.is_editor:
        for el in map_screen.elements:
            if el.text in ["Terrain", "Political", "Relations", "Pol Refresh", "Rel Refresh", "Core Refresh", "Data Refresh", "Set Date", "Core Brush", "Cores", "Auto-Core", "Unit", "Map Tech", "Reset", "Save", "Load", "Nation", "Building", "Refresh", "Exit", "View Mode", "Units", "Economy", "Blank", "Resource", "Resources", "Sync Units"]:
                el.visible = True
            
            if el.text == "Resource":
                el.visible = True
                if getattr(map_screen, "editor_mode", "") == "RESOURCE":
                    el.color, el.hover_color = (150, 0, 150), (200, 50, 200)
                else:
                    el.color, el.hover_color = (100, 100, 100), (150, 150, 150)

            if el.text == "Nation":
                el.visible = True
                if map_screen.editor_mode == "NATION":
                    el.color, el.hover_color = (0, 150, 0), (0, 200, 0)
                else:
                    el.color, el.hover_color = (100, 100, 100), (150, 150, 150)

            if el.text == "Building":
                el.visible = True
                if map_screen.editor_mode == "BUILDING":
                    el.color, el.hover_color = (0, 100, 200), (50, 150, 255)
                else:
                    el.color, el.hover_color = (100, 100, 100), (150, 150, 150)
            
            if el.text == "Core Brush":
                el.visible = True
                if map_screen.editor_mode == "CORE":
                    el.color, el.hover_color = (200, 100, 100), (255, 150, 150)
                else:
                    el.color, el.hover_color = (100, 100, 100), (150, 150, 150)

            if el.text == "Unit":
                el.visible = True
                if map_screen.editor_mode == "UNIT":
                    el.color, el.hover_color = (200, 0, 0), (255, 50, 50)
                else:
                    el.color, el.hover_color = (100, 100, 100), (150, 150, 150)
        return

    is_sel = bool(map_screen.selected_province)
    if map_screen.selection_mode:
        map_screen.btn_exit_to_menu.visible = True
        if hasattr(map_screen, 'btn_spectator'):
            map_screen.btn_spectator.visible = True
        return
    
    contextual_buttons = {
        getattr(map_screen, 'btn_go_build', None), getattr(map_screen, 'btn_close_info', None), 
        getattr(map_screen, 'btn_exit_to_menu', None), getattr(map_screen, 'btn_go_recruit', None), 
        getattr(map_screen, 'btn_go_orders', None), getattr(map_screen, 'btn_declare_war', None), 
        getattr(map_screen, 'btn_form_alliance', None), getattr(map_screen, 'btn_force_war', None), 
        getattr(map_screen, 'btn_force_peace', None), getattr(map_screen, 'btn_force_alliance', None), 
        getattr(map_screen, 'btn_break_alliance', None), getattr(map_screen, 'btn_spectator', None)
    }
    
    for el in map_screen.elements:
        if el not in contextual_buttons:
            el.visible = True
            
    map_screen.btn_exit_to_menu.visible = not is_sel
    for i in range(min(10, len(map_screen.elements))): 
        map_screen.elements[i].visible = True
        
    map_screen.btn_exit_to_menu.visible = not is_sel
    map_screen.btn_close_info.visible = is_sel

    for el in map_screen.elements:
        if el.text == "Next Turn":
            el.visible = not is_sel
            break

    if is_sel:
        owner = map_screen.selected_province.get("owner", "Unclaimed")
        player_data = map_screen.nation_data.get(map_screen.player_country, {})
        
        if map_screen.player_country == "Spectator":
            if state_queries.is_playable(owner, map_screen.nation_data):
                map_screen.btn_force_war.visible = True
                map_screen.btn_force_peace.visible = True
                map_screen.btn_force_alliance.visible = True
                map_screen.btn_break_alliance.visible = True
        else:
            has_player_units = state_queries.has_units_in_province(map_screen.player_country, map_screen.selected_province)
            
            if owner == map_screen.player_country or has_player_units:
                map_screen.btn_go_orders.visible = True
                if owner == map_screen.player_country:
                    from data.constants import WATER_TERRAINS
                    terrain = map_screen.selected_province.get("terrain", "")
                    is_land = terrain not in WATER_TERRAINS
                    map_screen.btn_go_build.visible = True
                    map_screen.btn_go_recruit.visible = is_land

            if owner != map_screen.player_country and state_queries.is_playable(owner, map_screen.nation_data):
                incoming_action, incoming_turns = state_queries.get_diplomatic_status(owner, map_screen.player_country, map_screen.nation_data)

                if incoming_action == "ALLIANCE_REQUEST" and incoming_turns > 0:
                    map_screen.btn_declare_war.visible = True
                    map_screen.btn_declare_war.text = "REJECT ALLIANCE"
                    map_screen.btn_form_alliance.visible = True
                    map_screen.btn_form_alliance.text = "ACCEPT ALLIANCE"

                elif incoming_action == "CEASEFIRE" and incoming_turns > 0:
                    map_screen.btn_declare_war.visible = True
                    map_screen.btn_declare_war.text = "REJECT CEASEFIRE"
                    map_screen.btn_form_alliance.visible = True
                    map_screen.btn_form_alliance.text = "ACCEPT CEASEFIRE"

                else:
                    at_war = state_queries.are_at_war(map_screen.player_country, owner, map_screen.nation_data)
                    allied = state_queries.are_allied(map_screen.player_country, owner, map_screen.nation_data)

                    pending_action, pending_turns = state_queries.get_diplomatic_status(map_screen.player_country, owner, map_screen.nation_data)
                    is_sending = (pending_turns == 0)

                    def get_status_text():
                        return "SENDING (UNDO)" if is_sending else "WAITING..."

                    if at_war:
                        map_screen.btn_form_alliance.visible = False
                        map_screen.btn_declare_war.visible = True
                        if pending_action == "CEASEFIRE": map_screen.btn_declare_war.text = get_status_text()
                        else: map_screen.btn_declare_war.text = "CEASEFIRE"
                            
                    elif allied:
                        map_screen.btn_declare_war.visible = False
                        map_screen.btn_form_alliance.visible = True
                        if pending_action == "BREAK_ALLIANCE": map_screen.btn_form_alliance.text = get_status_text()
                        else: map_screen.btn_form_alliance.text = "BREAK ALLIANCE"
                            
                    else:
                        if pending_action == "WAR_DECLARATION":
                            map_screen.btn_declare_war.visible = True
                            map_screen.btn_declare_war.text = get_status_text()
                            map_screen.btn_form_alliance.visible = False
                            
                        elif pending_action == "ALLIANCE_REQUEST":
                            map_screen.btn_form_alliance.visible = True
                            map_screen.btn_form_alliance.text = get_status_text()
                            map_screen.btn_declare_war.visible = False
                            
                        else:
                            map_screen.btn_declare_war.visible = True
                            map_screen.btn_declare_war.text = "DECLARE WAR"
                            map_screen.btn_form_alliance.visible = True
                            map_screen.btn_form_alliance.text = "FORM ALLIANCE"