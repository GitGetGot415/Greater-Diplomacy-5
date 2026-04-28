import ui_elements
from ui_elements import Button
import data.constants as c
from data import queries
from map_logic.diplomacy import player_diplomacy_actions

def render_buttons(self):
    if not self.selection_mode:
        
        # Helper variable to keep the Button declarations clean
        icons = ui_elements.UI_ICONS

        # ==================================================================== #
        #                          MAP VIEW TOGGLES                            #
        # ==================================================================== #
        
        # Refresh Buttons
        self.elements = [
            Button(c.SCREEN_WIDTH - 520, c.TOP_BAR_UI_CENTER_Y, "small", "grey", "Pol Refresh", self.refresh_political_map),
            Button(c.SCREEN_WIDTH - 420, c.TOP_BAR_UI_CENTER_Y, "small", "grey", "Rel Refresh", self.refresh_relations_map),
            Button(c.SCREEN_WIDTH - 320, c.TOP_BAR_UI_CENTER_Y, "small", "grey", "Core Refresh", self.refresh_cores_map),
            Button(c.SCREEN_WIDTH - 220, c.TOP_BAR_UI_CENTER_Y, "small", "grey", "Fac Refresh", self.refresh_factions_map),
        ]

        # View Type Buttons utilizing new constants
        self.elements.extend([
            Button(c.VIEW_BTN_START_X, c.VIEW_BTN_ROW1_Y, "small_square", "green", "Terrain", self.set_terrain, image=icons.get("terrain"), show_text=False),
            Button(c.VIEW_BTN_START_X + c.VIEW_BTN_STEP_X, c.VIEW_BTN_ROW1_Y, "small_square", "green", "Political", self.set_political, image=icons.get("political"), show_text=False),
            Button(c.VIEW_BTN_START_X + c.VIEW_BTN_STEP_X * 2, c.VIEW_BTN_ROW1_Y, "small_square", "green", "Relations", self.set_relations, image=icons.get("relations"), show_text=False),
            Button(c.VIEW_BTN_START_X + c.VIEW_BTN_STEP_X * 3, c.VIEW_BTN_ROW1_Y, "small_square", "green", "Cores", self.set_cores, image=icons.get("core"), show_text=False),
            Button(c.VIEW_BTN_START_X + c.VIEW_BTN_STEP_X * 4, c.VIEW_BTN_ROW1_Y, "small_square", "green", "Factions", self.set_factions, image=icons.get("faction"), show_text=False),

            Button(c.VIEW_BTN_START_X, c.VIEW_BTN_ROW2_Y, "small_square", "red", "Resources", lambda: self.set_view_mode("RESOURCES"), image=icons.get("resource"), show_text=False),
            Button(c.VIEW_BTN_START_X + c.VIEW_BTN_STEP_X, c.VIEW_BTN_ROW2_Y, "small_square", "red", "Blank", lambda: self.set_view_mode("BLANK"), image=icons.get("star"), show_text=False),
            Button(c.VIEW_BTN_START_X + c.VIEW_BTN_STEP_X * 2, c.VIEW_BTN_ROW2_Y, "small_square", "red", "Units", lambda: self.set_view_mode("UNITS"), image=icons.get("unit"), show_text=False),
            Button(c.VIEW_BTN_START_X + c.VIEW_BTN_STEP_X * 3, c.VIEW_BTN_ROW2_Y, "small_square", "red", "Economy", lambda: self.set_view_mode("ECONOMY"), image=icons.get("industry"), show_text=False),
            
            Button(c.VIEW_BTN_START_X + c.VIEW_BTN_STEP_X * 4, c.VIEW_BTN_ROW2_Y, "small_square", "blue", "Names", self.toggle_country_names, image=icons.get("names"), show_text=False),
        ])


        # ==================================================================== #
        #                        LEFT & BOTTOM UI BARS                         #
        # ==================================================================== #
        
        econ_callback = self.open_editor_economy if getattr(self, 'is_editor', False) else self.open_economy_screen
        research_callback = self.open_map_research_editor if getattr(self, 'is_editor', False) else self.open_research
        
        if self.is_editor:
            # --- EDITOR TOOLS ---
            self.elements.extend([
                # Unified Left Bar Buttons
                Button(c.LEFT_UI_BAR_X, 500, "left_ui_bar", "green", "Country Economy", econ_callback),
                Button(c.LEFT_UI_BAR_X, 200, "left_ui_bar", "blue", "R&D", research_callback, image=icons.get("research")),

                Button(c.EDITOR_BOT_BTN_START_X, c.BOTTOM_BAR_UI_CENTER_Y, "small", "blue", "Save", self.save_map_data),
                Button(c.EDITOR_BOT_BTN_START_X - c.EDITOR_BOT_BTN_STEP_X, c.BOTTOM_BAR_UI_CENTER_Y, "small", "blue", "Load", self.editor_load_map),
                Button(c.EDITOR_BOT_BTN_START_X - c.EDITOR_BOT_BTN_STEP_X*2, c.BOTTOM_BAR_UI_CENTER_Y, "small", "grey", "Nation", self.select_brush_nation),
                Button(c.EDITOR_BOT_BTN_START_X - c.EDITOR_BOT_BTN_STEP_X*3, c.BOTTOM_BAR_UI_CENTER_Y, "small", "pink", "Core Brush", self.select_core_brush),
                Button(c.EDITOR_BOT_BTN_START_X - c.EDITOR_BOT_BTN_STEP_X*3, c.SCREEN_HEIGHT - 110, "small", "pink", "Auto-Core", self.auto_assign_cores),
                
                Button(c.EDITOR_BOT_BTN_START_X - c.EDITOR_BOT_BTN_STEP_X*4, c.SCREEN_HEIGHT - 110, "small", "purple", "Resource", self.select_resource_brush),
                Button(c.EDITOR_BOT_BTN_START_X - c.EDITOR_BOT_BTN_STEP_X*4, c.BOTTOM_BAR_UI_CENTER_Y, "small", "grey", "Building", self.select_building_brush),
                
                Button(c.EDITOR_BOT_BTN_START_X - c.EDITOR_BOT_BTN_STEP_X*5, c.SCREEN_HEIGHT - 110, "small", "red", "Sync Units", self.sync_units_to_data),
                Button(c.EDITOR_BOT_BTN_START_X - c.EDITOR_BOT_BTN_STEP_X*5, c.BOTTOM_BAR_UI_CENTER_Y, "small", "grey", "Unit", self.select_unit_brush),
                
                Button(c.EDITOR_BOT_BTN_START_X - c.EDITOR_BOT_BTN_STEP_X*6, c.BOTTOM_BAR_UI_CENTER_Y, "small", "purple", "Data Refresh", self.refresh_nation_data),
                Button(c.EDITOR_BOT_BTN_START_X - c.EDITOR_BOT_BTN_STEP_X*7, c.BOTTOM_BAR_UI_CENTER_Y, "small", "purple", "Set Date", self.open_editor_date),
                Button(c.EDITOR_BOT_BTN_START_X - c.EDITOR_BOT_BTN_STEP_X*8, c.BOTTOM_BAR_UI_CENTER_Y, "small", "red", "Diplomacy", self.open_diplomacy_editor)
            ])
            
        else:
            # --- GAMEPLAY TOOLS ---
            # --- Dynamic Next Turn Button ---
            viewing_ai = getattr(self, 'viewing_ai_moves', False)
            next_btn_text = "Resolve Turn" if viewing_ai else "Next Turn"
            next_btn_color = "red" if viewing_ai else "purple"
            
            # We ALWAYS want the next/resolve button to appear
            self.elements.append(
                Button(c.EDITOR_BOT_BTN_START_X, c.BOTTOM_BAR_UI_CENTER_Y, "small", next_btn_color, next_btn_text, self.advance_time)
            )
            
            # Hide the management tools while the AI is moving
            if not viewing_ai:

                start_y_val = 40
                self.elements.extend([
                    Button(c.LEFT_UI_BAR_X, start_y_val + c.LEFT_UI_BAR_STEP_Y * 1, "medium_square", "orange", "Edit Nation", self.open_edit_country, image=icons.get("brush"), show_text=False),
                    Button(c.LEFT_UI_BAR_X, start_y_val + c.LEFT_UI_BAR_STEP_Y * 2, "medium_square", "green", "Country Economy", econ_callback, image=icons.get("economy(the_economy_of_a_country_to_be_unusually_specific)"), show_text=False),
                    Button(c.LEFT_UI_BAR_X, start_y_val + c.LEFT_UI_BAR_STEP_Y * 3, "medium_square", "blue", "R&D", research_callback, image=icons.get("research"), show_text=False),
                    Button(c.LEFT_UI_BAR_X, start_y_val + c.LEFT_UI_BAR_STEP_Y * 4, "medium_square", "purple", "Messages", self.open_messages, image=icons.get("mail"), show_text=False),
                    Button(c.LEFT_UI_BAR_X, start_y_val + c.LEFT_UI_BAR_STEP_Y * 5, "medium_square", "green", "Save", self.save_map_data, image=icons.get("save"), show_text=False),
                    Button(c.LEFT_UI_BAR_X, start_y_val + c.LEFT_UI_BAR_STEP_Y * 6, "medium_square", "grey", "Settings", self.open_settings, image=icons.get("settings"), show_text=False)
                ])


    # ======================================================================== #
    #                         CONTEXTUAL PROVINCE MENUS                        #
    # ======================================================================== #
    
    # --- PROVINCE MENU ACTION BUTTONS ---
    domestic_x = 400
    diplo_x = 180

    # Domestic Set
    self.btn_go_orders = Button(domestic_x, c.ACTION_BTN_START_Y, "medium_square", "blue", "Give Orders", self.open_orders)
    self.btn_go_recruit = Button(domestic_x, c.ACTION_BTN_START_Y + c.ACTION_BTN_STEP_Y * 2, "medium_square", "green", "Recruit Menu", self.open_recruit)
    self.btn_go_build = Button(domestic_x, c.ACTION_BTN_START_Y + c.ACTION_BTN_STEP_Y * 4, "medium_square", "orange", "Construction", self.open_construction)

    # Foreign Set
    self.btn_declare_war = Button(diplo_x, c.ACTION_BTN_START_Y, "diplomatic", "red", "Declare War", self.handle_declare_war)
    self.btn_join_wars = Button(diplo_x, c.ACTION_BTN_START_Y + c.ACTION_BTN_STEP_Y * 1, "diplomatic", "orange", "Join Wars", self.handle_join_wars)
    self.btn_call_to_arms = Button(diplo_x, c.ACTION_BTN_START_Y + c.ACTION_BTN_STEP_Y * 2, "diplomatic", "red", "Call to Arms", self.handle_call_to_arms)
    
    self.btn_fac_invite = Button(diplo_x, c.ACTION_BTN_START_Y + c.ACTION_BTN_STEP_Y * 3, "diplomatic", "green", "Invite to Faction", lambda: player_diplomacy_actions.handle_specific_action(self, "FACTION_INVITE"))
    self.btn_fac_join_req = Button(diplo_x, c.ACTION_BTN_START_Y + c.ACTION_BTN_STEP_Y * 4, "diplomatic", "green", "Req. Join Faction", lambda: player_diplomacy_actions.handle_specific_action(self, "JOIN_FACTION_REQ"))
    self.btn_fac_kick = Button(diplo_x, c.ACTION_BTN_START_Y + c.ACTION_BTN_STEP_Y * 5, "diplomatic", "red", "Kick from Faction", lambda: player_diplomacy_actions.handle_specific_action(self, "KICK_FACTION_MEMBER"))

    self.btn_fac_create = Button(diplo_x, c.ACTION_BTN_START_Y + c.ACTION_BTN_STEP_Y * 6, "diplomatic", "blue", "Create Faction", lambda: player_diplomacy_actions.handle_specific_action(self, "CREATE_FACTION"))
    self.btn_fac_leave = Button(diplo_x, c.ACTION_BTN_START_Y + c.ACTION_BTN_STEP_Y * 7, "diplomatic", "orange", "Leave Faction", lambda: player_diplomacy_actions.handle_specific_action(self, "LEAVE_FACTION"))
    self.btn_fac_disband = Button(diplo_x, c.ACTION_BTN_START_Y + c.ACTION_BTN_STEP_Y * 8, "diplomatic", "red", "Disband Faction", lambda: player_diplomacy_actions.handle_specific_action(self, "DISBAND_FACTION"))

    self.btn_accept_req = Button(diplo_x, c.ACTION_BTN_START_Y, "diplomatic", "green", "Accept Request", lambda: player_diplomacy_actions.handle_accept_req(self))
    self.btn_reject_req = Button(diplo_x, c.ACTION_BTN_START_Y + c.ACTION_BTN_STEP_Y, "diplomatic", "red", "Reject Request", lambda: player_diplomacy_actions.handle_reject_req(self))

    # Spectator God Power Buttons
    self.btn_force_war = Button(c.ACTION_BTN_X, c.ACTION_BTN_START_Y, "medium", "red", "Force War", self.force_war_menu)
    self.btn_force_peace = Button(c.ACTION_BTN_X, c.ACTION_BTN_START_Y + c.ACTION_BTN_STEP_Y, "medium", "green", "Force Ceasefire", self.force_peace_menu)
    
    self.btn_spec_create_fac = Button(c.ACTION_BTN_X, c.ACTION_BTN_START_Y + c.ACTION_BTN_STEP_Y * 2, "medium", "blue", "Create Faction", self.spec_create_faction)
    self.btn_spec_join_fac = Button(c.ACTION_BTN_X, c.ACTION_BTN_START_Y + c.ACTION_BTN_STEP_Y * 3, "medium", "green", "Join Faction", self.spec_join_faction)
    self.btn_spec_invite_fac = Button(c.ACTION_BTN_X, c.ACTION_BTN_START_Y + c.ACTION_BTN_STEP_Y * 2, "medium", "blue", "Invite to Faction", self.spec_invite_faction)
    self.btn_spec_leave_fac = Button(c.ACTION_BTN_X, c.ACTION_BTN_START_Y + c.ACTION_BTN_STEP_Y * 3, "medium", "orange", "Leave Faction", self.spec_leave_faction)
    self.btn_spec_disband_fac = Button(c.ACTION_BTN_X, c.ACTION_BTN_START_Y + c.ACTION_BTN_STEP_Y * 3, "medium", "red", "Disband Faction", self.spec_disband_faction)

    # General Controls
    self.btn_spectator = Button(c.LEFT_UI_BAR_X, c.BTN_SPECTATOR_Y, "medium", "grey", "Spectator Mode", self.start_spectator)
    self.btn_close_info = Button(c.SCREEN_WIDTH - 120, c.TOP_BAR_UI_CENTER_Y, "small", "red", "X", self.deselect_province)
    self.btn_exit_to_menu = Button(c.SCREEN_WIDTH - 120, c.TOP_BAR_UI_CENTER_Y, "small", "red", "Exit", self.exit_to_menu)

    # Add them to elements, but hidden
    contextual_buttons = {
        self.btn_go_orders, self.btn_go_recruit, self.btn_go_build, 
        self.btn_fac_create, self.btn_fac_leave, self.btn_fac_disband,
        self.btn_declare_war, self.btn_join_wars, self.btn_call_to_arms, 
        self.btn_fac_invite, self.btn_fac_join_req, self.btn_fac_kick,
        self.btn_accept_req, self.btn_reject_req,
        self.btn_force_war, self.btn_force_peace, self.btn_spec_create_fac, 
        self.btn_spec_join_fac, self.btn_spec_invite_fac, self.btn_spec_leave_fac, 
        self.btn_spec_disband_fac, self.btn_spectator, self.btn_close_info, self.btn_exit_to_menu
    }
    
    for btn in contextual_buttons:
        btn.visible = False
        self.elements.append(btn)


# ============================================================================ #
#                            DYNAMIC BUTTON UPDATES                            #
# ============================================================================ #

def update_button_states(map_screen):
    """Dynamically updates button visibility, colors, and text every frame."""
    
    # Reset all to invisible first
    for el in map_screen.elements:
        el.visible = False

        # ==================================================================== #
        #                       VIEW TOGGLES SELECTION                         #
        # ==================================================================== #
        if hasattr(el, 'text'):
            if el.text == "Terrain": el.is_selected = (map_screen.base_layer == "TERRAIN")
            elif el.text == "Political": el.is_selected = (map_screen.base_layer == "POLITICAL")
            elif el.text == "Relations": el.is_selected = (map_screen.base_layer == "RELATIONS")
            elif el.text == "Cores": el.is_selected = (map_screen.base_layer == "CORES")
            elif el.text == "Factions": el.is_selected = (map_screen.base_layer == "FACTIONS")
            elif el.text == "Units": el.is_selected = (map_screen.secondary_mode == "UNITS")
            elif el.text == "Blank": el.is_selected = (map_screen.secondary_mode == "BLANK")
            elif el.text == "Economy":
                if not getattr(el, 'show_text', True): el.is_selected = (map_screen.secondary_mode == "ECONOMY")
                else: el.is_selected = False
            elif el.text == "Resources": el.is_selected = (map_screen.secondary_mode == "RESOURCES")
            elif el.text == "Names": el.is_selected = getattr(map_screen, 'show_country_names', True)
            else: el.is_selected = False


    # ======================================================================== #
    #                        EDITOR BRUSH HIGHLIGHTS                           #
    # ======================================================================== #
    if map_screen.is_editor:
        for el in map_screen.elements:
            if el.text in ["Terrain", "Political", "Relations", "Factions", "Pol Refresh",
                           "Rel Refresh", "Core Refresh", "Data Refresh", "Fac Refresh",
                           "Set Date", "Core Brush", "Cores", "Auto-Core", "Unit",
                           "R&D", "Reset", "Save", "Load", "Nation", "Building", "Economy",
                           "Refresh", "Exit", "View Mode", "Units", "Country Economy", "Blank",
                           "Resource", "Resources", "Sync Units", "Diplomacy", "Names"]:
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


    # ======================================================================== #
    #                          SELECTION MODE LOGIC                            #
    # ======================================================================== #
    is_sel = bool(map_screen.selected_province)
    if map_screen.selection_mode:
        map_screen.btn_exit_to_menu.visible = True
        if hasattr(map_screen, 'btn_spectator'):
            map_screen.btn_spectator.visible = True
        return
    

    # ======================================================================== #
    #                    CONTEXTUAL / NON-CONTEXTUAL SORT                      #
    # ======================================================================== #
    # Group our tracked elements to prevent logic collisions
    contextual_buttons = {
        getattr(map_screen, 'btn_go_orders', None), getattr(map_screen, 'btn_go_recruit', None), 
        getattr(map_screen, 'btn_go_build', None), getattr(map_screen, 'btn_fac_create', None), 
        getattr(map_screen, 'btn_fac_leave', None), getattr(map_screen, 'btn_fac_disband', None),
        getattr(map_screen, 'btn_declare_war', None), getattr(map_screen, 'btn_join_wars', None), 
        getattr(map_screen, 'btn_call_to_arms', None), getattr(map_screen, 'btn_fac_invite', None), 
        getattr(map_screen, 'btn_fac_join_req', None), getattr(map_screen, 'btn_fac_kick', None), 
        getattr(map_screen, 'btn_accept_req', None), getattr(map_screen, 'btn_reject_req', None),
        getattr(map_screen, 'btn_force_war', None), getattr(map_screen, 'btn_force_peace', None), 
        getattr(map_screen, 'btn_spec_create_fac', None), getattr(map_screen, 'btn_spec_join_fac', None), 
        getattr(map_screen, 'btn_spec_invite_fac', None), getattr(map_screen, 'btn_spec_leave_fac', None), 
        getattr(map_screen, 'btn_spec_disband_fac', None), getattr(map_screen, 'btn_spectator', None),
        getattr(map_screen, 'btn_close_info', None), getattr(map_screen, 'btn_exit_to_menu', None)
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
        if el.text == "Next Turn" or el.text == "Resolve Turn":
            el.visible = not is_sel
            break

    # Helper function to assign valid/invalid styling and set interactivity
    def set_btn(btn, visible, enabled, text, color="green"):
        btn.visible = visible
        btn.disabled = not enabled
        btn.text = text
        if enabled:
            btn.color, btn.hover_color = c.UI_COLORS[color]
            btn.pressed_color = (max(0, btn.color[0]-40), max(0, btn.color[1]-40), max(0, btn.color[2]-40))
        else:
            btn.color, btn.hover_color = c.UI_COLORS["grey"]
            btn.pressed_color = (max(0, btn.color[0]-40), max(0, btn.color[1]-40), max(0, btn.color[2]-40))


    # ======================================================================== #
    #                      PROVINCE INTERACTION LOGIC                          #
    # ======================================================================== #
    if is_sel:
        owner = map_screen.selected_province.get("owner", "Unclaimed")
        player_data = map_screen.nation_data.get(map_screen.player_country, {})
        
        # --------------------------------------------------------------------
        # SPECTATOR PROVINCE LOGIC
        # --------------------------------------------------------------------
        if map_screen.player_country == "Spectator":
            if queries.is_playable(owner, map_screen.nation_data):
                set_btn(map_screen.btn_force_war, True, True, "Force War", "red")
                set_btn(map_screen.btn_force_peace, True, True, "Force Ceasefire", "green")

                in_faction = map_screen.nation_data[owner].get("faction", "")
                is_leader = queries.is_faction_leader(owner, map_screen.nation_data)

                if not in_faction:
                    set_btn(map_screen.btn_spec_create_fac, True, True, "Create Faction", "blue")
                    set_btn(map_screen.btn_spec_join_fac, True, True, "Join Faction", "green")
                    map_screen.btn_spec_invite_fac.visible = False
                    map_screen.btn_spec_leave_fac.visible = False
                    map_screen.btn_spec_disband_fac.visible = False
                else:
                    map_screen.btn_spec_create_fac.visible = False
                    map_screen.btn_spec_join_fac.visible = False
                    set_btn(map_screen.btn_spec_invite_fac, True, True, "Invite to Faction", "blue")
                    if is_leader:
                        set_btn(map_screen.btn_spec_disband_fac, True, True, "Disband Faction", "red")
                        map_screen.btn_spec_leave_fac.visible = False
                    else:
                        set_btn(map_screen.btn_spec_leave_fac, True, True, "Leave Faction", "orange")
                        map_screen.btn_spec_disband_fac.visible = False

        # --------------------------------------------------------------------
        # PLAYER PROVINCE LOGIC
        # --------------------------------------------------------------------
        else:
            has_player_units = queries.has_units_in_province(map_screen.player_country, map_screen.selected_province)
            terrain = map_screen.selected_province.get("terrain", "")
            is_land = terrain not in c.WATER_TERRAINS

            if owner == map_screen.player_country:
                # --- DOMESTIC PROVINCE ---
                # Use their original distinct colors
                set_btn(map_screen.btn_go_orders, True, has_player_units, "Give Orders", "blue")
                set_btn(map_screen.btn_go_recruit, True, is_land, "Recruit Menu", "green")
                set_btn(map_screen.btn_go_build, True, is_land, "Construction", "orange")

                # Hide foreign buttons
                for btn in [
                    map_screen.btn_declare_war, map_screen.btn_join_wars, map_screen.btn_call_to_arms, 
                    map_screen.btn_fac_invite, map_screen.btn_fac_join_req, map_screen.btn_fac_kick,
                    map_screen.btn_accept_req, map_screen.btn_reject_req,
                    map_screen.btn_fac_create, map_screen.btn_fac_leave, map_screen.btn_fac_disband
                ]:
                    btn.visible = False

            elif queries.is_playable(owner, map_screen.nation_data):
                # --- FOREIGN PROVINCE ---
                
                # Only "Give Orders" applies here dynamically from the domestic side
                set_btn(map_screen.btn_go_orders, True, has_player_units, "Give Orders", "blue")
                
                for btn in [map_screen.btn_go_recruit, map_screen.btn_go_build]:
                    btn.visible = False

                incoming_action, incoming_turns = queries.get_diplomatic_status(owner, map_screen.player_country, map_screen.nation_data)
                at_war = queries.are_at_war(map_screen.player_country, owner, map_screen.nation_data)
                in_same_faction = queries.are_in_same_faction(map_screen.player_country, owner, map_screen.nation_data)
                pending_action, pending_turns = queries.get_diplomatic_status(map_screen.player_country, owner, map_screen.nation_data)
                is_sending = (pending_turns == 0 and pending_action)

                def get_status_text(base):
                    return f"UNDO {base}" if is_sending else "WAITING..."

                # Define these variables up high so everything can use them
                my_faction = map_screen.nation_data[map_screen.player_country].get("faction", "")
                target_faction = map_screen.nation_data[owner].get("faction", "")
                i_am_leader = queries.is_faction_leader(map_screen.player_country, map_screen.nation_data)
                target_is_leader = queries.is_faction_leader(owner, map_screen.nation_data)

                # Handle Incoming Action Override
                if incoming_turns > 0 and incoming_action in ["FACTION_INVITE", "JOIN_FACTION_REQ", "CEASEFIRE", "CALL_TO_ARMS", "CREATE_FACTION"]:
                    # Hide the standard action array
                    for btn in [map_screen.btn_declare_war, map_screen.btn_join_wars, map_screen.btn_call_to_arms, map_screen.btn_fac_invite, map_screen.btn_fac_join_req, map_screen.btn_fac_kick, map_screen.btn_fac_create, map_screen.btn_fac_leave, map_screen.btn_fac_disband]:
                        btn.visible = False
                        
                    action_name = incoming_action.replace("_", " ")
                    set_btn(map_screen.btn_accept_req, True, True, f"Accept {action_name}", "green")
                    set_btn(map_screen.btn_reject_req, True, True, f"Reject {action_name}", "red")
                
                else:
                    map_screen.btn_accept_req.visible = False
                    map_screen.btn_reject_req.visible = False

                    # Declare War / Ceasefire
                    dw_enabled = True
                    if pending_action == "CEASEFIRE": dw_text = get_status_text("CEASEFIRE")
                    elif pending_action == "WAR_DECLARATION": dw_text = get_status_text("WAR")
                    else: dw_text = "Ceasefire" if at_war else "Declare War"

                    # --- FIX: Disable war declarations against faction members ---
                    if not at_war and in_same_faction:
                        dw_enabled = False

                    set_btn(map_screen.btn_declare_war, True, dw_enabled, dw_text, "red")
                    
                    # Join Wars
                    target_wars = queries.get_enemies(owner, map_screen.nation_data)
                    player_wars = queries.get_enemies(map_screen.player_country, map_screen.nation_data)
                    can_join_wars = bool(in_same_faction and any(w for w in target_wars if w not in player_wars))
                    jw_text = get_status_text("JOIN WARS") if pending_action == "JOIN_WARS" else "Join Wars"
                    set_btn(map_screen.btn_join_wars, True, can_join_wars or pending_action == "JOIN_WARS", jw_text, "orange")

                    # Call to Arms
                    can_call_to_arms = bool(in_same_faction and any(w for w in player_wars if w not in target_wars))
                    ca_text = get_status_text("CALL TO ARMS") if pending_action == "CALL_TO_ARMS" else "Call to Arms"
                    set_btn(map_screen.btn_call_to_arms, True, can_call_to_arms or pending_action == "CALL_TO_ARMS", ca_text, "red")

                    # Invite to Faction
                    can_invite = bool(my_faction and i_am_leader and not target_faction and not at_war)
                    inv_text = get_status_text("INVITE") if pending_action == "FACTION_INVITE" else "Invite to Faction"
                    set_btn(map_screen.btn_fac_invite, True, can_invite or pending_action == "FACTION_INVITE", inv_text, "green")

                    # Request to Join
                    can_req_join = bool(not my_faction and target_faction and not at_war)
                    req_text = get_status_text("JOIN REQ") if pending_action == "JOIN_FACTION_REQ" else "Req. Join Faction"
                    set_btn(map_screen.btn_fac_join_req, True, can_req_join or pending_action == "JOIN_FACTION_REQ", req_text, "green")

                    # Kick from Faction
                    can_kick = bool(in_same_faction and i_am_leader)
                    kick_text = get_status_text("KICK") if pending_action == "KICK_FACTION_MEMBER" else "Kick from Faction"
                    set_btn(map_screen.btn_fac_kick, True, can_kick or pending_action == "KICK_FACTION_MEMBER", kick_text, "red")

                    # Create Faction
                    can_create_fac = bool(not my_faction and not target_faction and not at_war)
                    create_text = get_status_text("CREATE") if pending_action == "CREATE_FACTION" else "Create Faction"
                    set_btn(map_screen.btn_fac_create, True, can_create_fac or pending_action == "CREATE_FACTION", create_text, "blue")

                    # Leave Faction
                    can_leave_fac = bool(my_faction and in_same_faction and not i_am_leader and target_is_leader)
                    leave_text = get_status_text("LEAVE") if pending_action == "LEAVE_FACTION" else "Leave Faction"
                    set_btn(map_screen.btn_fac_leave, True, can_leave_fac or pending_action == "LEAVE_FACTION", leave_text, "orange")

                    # Disband Faction
                    can_disband_fac = bool(my_faction and i_am_leader and in_same_faction)
                    disband_text = get_status_text("DISBAND") if pending_action == "DISBAND_FACTION" else "Disband Faction"
                    set_btn(map_screen.btn_fac_disband, True, can_disband_fac or pending_action == "DISBAND_FACTION", disband_text, "red")

            else:
                # --- UNCLAIMED / WATER ---
                # Unclaimed / Water tiles don't support these interactions
                set_btn(map_screen.btn_go_orders, True, has_player_units, "Give Orders", "blue")
                
                for btn in [
                    map_screen.btn_go_recruit, map_screen.btn_go_build, map_screen.btn_declare_war, 
                    map_screen.btn_join_wars, map_screen.btn_call_to_arms, map_screen.btn_fac_create, 
                    map_screen.btn_fac_leave, map_screen.btn_fac_disband, map_screen.btn_fac_invite, 
                    map_screen.btn_fac_join_req, map_screen.btn_fac_kick, map_screen.btn_accept_req, 
                    map_screen.btn_reject_req
                ]:
                    btn.visible = False

def render_edit_country_buttons(edit_screen):
    """Renders the buttons for the Edit Country Screen."""
    icons = ui_elements.UI_ICONS

    edit_screen.elements = [
        Button(20, 20, "small", "red", "Cancel", edit_screen.exit_to_map),
        Button(140, 20, "medium", "green", "Save Changes", edit_screen.save_and_exit)
    ]
    
    # Export / Import Buttons
    edit_screen.elements.append(Button(c.EDIT_COUNTRY_UI_X1, 420, "small_square", "blue", "Export Flag", edit_screen.export_flag, image=icons.get("export"), show_text=False))
    edit_screen.elements.append(Button(c.EDIT_COUNTRY_UI_X1 + 50, 420, "small_square", "green", "Import Flag", edit_screen.import_flag, image=icons.get("import"), show_text=False))
    
    edit_screen.elements.append(Button(c.EDIT_COUNTRY_UI_X2, 520, "small_square", "blue", "Export Portrait", edit_screen.export_portrait, image=icons.get("export"), show_text=False))
    edit_screen.elements.append(Button(c.EDIT_COUNTRY_UI_X2 + 50, 520, "small_square", "green", "Import Portrait", edit_screen.import_portrait, image=icons.get("import"), show_text=False))
    
    # Build Palette Buttons
    for i, color in enumerate(edit_screen.palette):
        colors_per_row = 8
        space_between_colors = 45
        x = c.EDIT_COUNTRY_UI_X3 + (i % colors_per_row) * space_between_colors
        y = 150 + (i // colors_per_row) * space_between_colors
        btn = Button(x, y, "small_square", "grey", "", lambda c_val=color: edit_screen.set_color(c_val), show_text=False)
        btn.color = btn.hover_color = color
        btn.shading = False
        edit_screen.elements.append(btn)

    # Tool Selection Buttons
    brush_color = "blue" if edit_screen.draw_mode == "BRUSH" else "grey"
    fill_color = "blue" if edit_screen.draw_mode == "FILL" else "grey"
    picker_color = "blue" if edit_screen.draw_mode == "PICKER" else "grey"
    
    edit_screen.elements.append(Button(c.EDIT_COUNTRY_UI_X3, 425, "small_square", "grey", "Undo", edit_screen.undo))
    edit_screen.elements.append(Button(c.EDIT_COUNTRY_UI_X3 + 50, 425, "small_square", "grey", "Redo", edit_screen.redo))
    edit_screen.elements.append(Button(c.EDIT_COUNTRY_UI_X3, 375, "small_square", picker_color, "Color Picker", lambda: edit_screen.set_tool("PICKER"), image=icons.get("color_picker"), show_text=False))
    edit_screen.elements.append(Button(c.EDIT_COUNTRY_UI_X3 + 50, 375, "small_square", brush_color, "Brush", lambda: edit_screen.set_tool("BRUSH"), image=icons.get("brush"), show_text=False))
    edit_screen.elements.append(Button(c.EDIT_COUNTRY_UI_X3 + 100, 375, "small_square", fill_color, "Fill", lambda: edit_screen.set_tool("FILL"), image=icons.get("paint"), show_text=False))

    
    # Updated Buttons to have both Map Color and Custom Brush Color pickers side-by-side
    edit_screen.elements.append(Button(c.EDIT_COUNTRY_UI_X3 + 100, 600, "small", "orange", "Map Color", edit_screen.pick_map_color))
    edit_screen.elements.append(Button(c.EDIT_COUNTRY_UI_X3 + 125, 80, "small_square", "purple", "Brush Color", edit_screen.pick_custom_brush_color, image=icons.get("star"), show_text=False))
    edit_screen.elements.append(Button(c.EDIT_COUNTRY_UI_X3 + 175, 80, "small_square", "purple", "Null Color", lambda: edit_screen.set_color((0, 0, 0, 0)), image=icons.get("red_line"), show_text=False))
