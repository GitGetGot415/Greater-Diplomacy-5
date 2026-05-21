import pygame
from map_logic.system32 import turn_manager
import ui_elements
from ui_elements import Button, Slider
import data.constants as c
from data import queries

# New imports for the refactored logic modules
from map_logic.setup import player_setup
from map_logic.diplomacy import player_diplomacy_actions
from ui import event_handler, spectator_menus, editor_menus

def render_buttons(self):
    """Initializes and registers all map screen buttons uniformly."""
    icons = ui_elements.UI_ICONS
    self.elements = []

    # ==================================================================== #
    #                        MAP VIEW TOGGLES                              #
    # ==================================================================== #
    self.btn_refresh_all = Button(c.SCREEN_WIDTH - 240, c.TOP_BAR_UI_CENTER_Y, "small", "blue", "Refresh Maps", self.refresh_all_maps, font_preset="normal")

    self.btn_view_terrain = Button(c.VIEW_BTN_START_X, c.VIEW_BTN_ROW1_Y, "small_square", "green", "Terrain", lambda: self.set_map_layer("TERRAIN"), image=icons.get("terrain"), show_text=False)
    self.btn_view_political = Button(c.VIEW_BTN_START_X + c.VIEW_BTN_STEP_X, c.VIEW_BTN_ROW1_Y, "small_square", "green", "Political", lambda: self.set_map_layer("POLITICAL"), image=icons.get("political"), show_text=False)
    self.btn_view_relations = Button(c.VIEW_BTN_START_X + c.VIEW_BTN_STEP_X * 2, c.VIEW_BTN_ROW1_Y, "small_square", "green", "Relations", lambda: self.set_map_layer("RELATIONS"), image=icons.get("relations"), show_text=False)
    self.btn_view_cores = Button(c.VIEW_BTN_START_X + c.VIEW_BTN_STEP_X * 3, c.VIEW_BTN_ROW1_Y, "small_square", "green", "Cores", lambda: self.set_map_layer("CORES"), image=icons.get("core"), show_text=False)
    self.btn_view_factions = Button(c.VIEW_BTN_START_X + c.VIEW_BTN_STEP_X * 4, c.VIEW_BTN_ROW1_Y, "small_square", "green", "Factions", lambda: self.set_map_layer("FACTIONS"), image=icons.get("faction"), show_text=False)

    self.btn_view_resources = Button(c.VIEW_BTN_START_X, c.VIEW_BTN_ROW2_Y, "small_square", "red", "Resources", lambda: self.set_view_mode("RESOURCES"), image=icons.get("resource"), show_text=False)
    self.btn_view_blank = Button(c.VIEW_BTN_START_X + c.VIEW_BTN_STEP_X, c.VIEW_BTN_ROW2_Y, "small_square", "red", "Blank", lambda: self.set_view_mode("BLANK"), image=icons.get("star"), show_text=False)
    self.btn_view_units = Button(c.VIEW_BTN_START_X + c.VIEW_BTN_STEP_X * 2, c.VIEW_BTN_ROW2_Y, "small_square", "red", "Units", lambda: self.set_view_mode("UNITS"), image=icons.get("unit"), show_text=False)
    self.btn_view_economy = Button(c.VIEW_BTN_START_X + c.VIEW_BTN_STEP_X * 3, c.VIEW_BTN_ROW2_Y, "small_square", "red", "Economy", lambda: self.set_view_mode("ECONOMY"), image=icons.get("industry"), show_text=False)
    self.btn_toggle_names = Button(c.VIEW_BTN_START_X + c.VIEW_BTN_STEP_X * 4, c.VIEW_BTN_ROW2_Y, "small_square", "blue", "Names", self.toggle_country_names, image=icons.get("names"), show_text=False)

    # ==================================================================== #
    #                        LEFT & BOTTOM UI BARS                         #
    # ==================================================================== #
    is_spec = getattr(self, 'player_country', '') == "Spectator"
    is_ed = getattr(self, 'is_editor', False)

    econ_callback = (lambda: editor_menus.open_editor_economy(self)) if (is_ed or is_spec) else (lambda: self.change_state("ECONOMY"))
    research_callback = (lambda: editor_menus.open_map_research_editor(self)) if (is_ed or is_spec) else (lambda: self.change_state("RESEARCH"))
    msgs_callback = (lambda: editor_menus.open_spectator_messages(self)) if is_spec else (lambda: self.change_state("MESSAGES"))

   # Editor Buttons
    self.btn_ed_econ = Button(c.LEFT_UI_BAR_X, 300, "left_ui_bar", "green", "Country Economy", econ_callback)
    self.btn_ed_rd = Button(c.LEFT_UI_BAR_X, 200, "left_ui_bar", "blue", "R&D", research_callback, image=icons.get("research"))
    self.btn_ed_save = Button(c.EDITOR_BOT_BTN_START_X + c.EDITOR_BOT_BTN_STEP_X*0.5, c.BOTTOM_BAR_UI_CENTER_Y, "small_square", "blue", "Save", self.save_map_data, image=icons.get("save"), show_text=False)
    self.btn_ed_load = Button(c.EDITOR_BOT_BTN_START_X - c.EDITOR_BOT_BTN_STEP_X*0.5, c.BOTTOM_BAR_UI_CENTER_Y, "small", "blue", "Load", lambda: editor_menus.editor_load_map(self))
    self.btn_ed_nation = Button(c.EDITOR_BOT_BTN_START_X - c.EDITOR_BOT_BTN_STEP_X*1.5, c.BOTTOM_BAR_UI_CENTER_Y, "small", "grey", "Nation Brush", lambda: editor_menus.select_brush_nation(self))
    self.btn_ed_core = Button(c.EDITOR_BOT_BTN_START_X - c.EDITOR_BOT_BTN_STEP_X*2.5, c.BOTTOM_BAR_UI_CENTER_Y, "small", "pink", "Core Brush", lambda: editor_menus.select_core_brush(self))
    self.btn_ed_autocore = Button(c.EDITOR_BOT_BTN_START_X - c.EDITOR_BOT_BTN_STEP_X*3.5, c.BOTTOM_BAR_UI_CENTER_Y, "small", "pink", "Auto-Core", self.auto_assign_cores)
    self.btn_ed_resource = Button(c.EDITOR_BOT_BTN_START_X - c.EDITOR_BOT_BTN_STEP_X*4, c.BOTTOM_BAR_UI_CENTER_Y, "small_square", "purple", "Resource", lambda: editor_menus.select_resource_brush(self), image=icons.get("resource"), show_text=False)
    self.btn_ed_building = Button(c.EDITOR_BOT_BTN_START_X - c.EDITOR_BOT_BTN_STEP_X*4.5, c.BOTTOM_BAR_UI_CENTER_Y, "small_square", "grey", "Building", lambda: editor_menus.select_building_brush(self), image=icons.get("industry"), show_text=False)
    self.btn_ed_unit = Button(c.EDITOR_BOT_BTN_START_X - c.EDITOR_BOT_BTN_STEP_X*5, c.BOTTOM_BAR_UI_CENTER_Y, "small_square", "grey", "Unit", lambda: editor_menus.select_unit_brush(self), image=icons.get("unit"), show_text=False)
    self.btn_ed_refresh = Button(c.EDITOR_BOT_BTN_START_X - c.EDITOR_BOT_BTN_STEP_X*6, c.BOTTOM_BAR_UI_CENTER_Y, "small", "purple", "Data Refresh", self.refresh_nation_data)
    self.btn_ed_date = Button(c.EDITOR_BOT_BTN_START_X - c.EDITOR_BOT_BTN_STEP_X*7, c.BOTTOM_BAR_UI_CENTER_Y, "small", "purple", "Set Date", lambda: editor_menus.open_editor_date(self))
    self.btn_ed_diplo = Button(c.EDITOR_BOT_BTN_START_X - c.EDITOR_BOT_BTN_STEP_X*8, c.BOTTOM_BAR_UI_CENTER_Y, "small", "red", "Diplomacy", lambda: editor_menus.open_diplomacy_editor(self))

    # Gameplay Buttons
    self.btn_next_turn = Button(c.EDITOR_BOT_BTN_START_X, c.BOTTOM_BAR_UI_CENTER_Y, "small", "purple", "Next Turn", lambda: turn_manager.advance_time(self))
    self.btn_skip_ai = Button(c.EDITOR_BOT_BTN_START_X - c.EDITOR_BOT_BTN_STEP_X, c.BOTTOM_BAR_UI_CENTER_Y, "small", "grey", "Skip AI", self.toggle_skip_ai, font_preset="normal")
    self.btn_multi_turn = Button(c.EDITOR_BOT_BTN_START_X - c.EDITOR_BOT_BTN_STEP_X * 2, c.BOTTOM_BAR_UI_CENTER_Y, "small", "blue", "Multi-Turn", self.trigger_multi_turn)
    
    start_y_val = 60
    
    def open_edit_country_action():
        if self.player_country == "Spectator":
            editor_menus.spec_select_edit_country(self)
        elif self.player_country and self.player_country != "None":
            self.editing_country = self.player_country
            self.change_state("EDIT_COUNTRY")

    self.btn_gp_edit = Button(c.LEFT_UI_BAR_X, start_y_val + c.LEFT_UI_BAR_STEP_Y * 1, "left_ui_button", "pink", "Identity", open_edit_country_action, image=icons.get("brush"), show_text=True)
    self.btn_gp_econ = Button(c.LEFT_UI_BAR_X, start_y_val + c.LEFT_UI_BAR_STEP_Y * 2, "left_ui_button", "pink", "Economy", econ_callback, image=icons.get("economy(the_economy_of_a_country_to_be_unusually_specific)"), show_text=True)
    self.btn_gp_rd = Button(c.LEFT_UI_BAR_X, start_y_val + c.LEFT_UI_BAR_STEP_Y * 3, "left_ui_button", "pink", "R&D", research_callback, image=icons.get("research"), show_text=True)
    self.btn_gp_msgs = Button(c.LEFT_UI_BAR_X, start_y_val + c.LEFT_UI_BAR_STEP_Y * 4, "left_ui_button", "pink", "Mail", msgs_callback, image=icons.get("mail"), show_text=True)
    self.btn_gp_save = Button(c.LEFT_UI_BAR_X, start_y_val + c.LEFT_UI_BAR_STEP_Y * 5, "left_ui_button", "pink", "Save", self.save_map_data, image=icons.get("save"), show_text=True)
    self.btn_gp_settings = Button(c.LEFT_UI_BAR_X, start_y_val + c.LEFT_UI_BAR_STEP_Y * 6, "left_ui_button", "pink", "Settings", lambda: self.change_state("SETTINGS"), image=icons.get("settings"), show_text=True)
    self.btn_gp_music = Button(c.LEFT_UI_BAR_X, start_y_val + c.LEFT_UI_BAR_STEP_Y * 7, "left_ui_button", "pink", "Music", lambda: self.change_state("MUSIC_PLAYER"), image=icons.get("music"), show_text=True)
    self.btn_gp_faction = Button(c.LEFT_UI_BAR_X, start_y_val + c.LEFT_UI_BAR_STEP_Y * 8, "left_ui_button", "pink", "Faction", lambda: self.change_state("FACTION"), image=icons.get("faction"), show_text=True)

    # NEW: Register the Slider below the Faction button
    slider_y = int(start_y_val + c.LEFT_UI_BAR_STEP_Y * 9.5)
    self.slider_camera_tilt = Slider(c.LEFT_UI_BAR_X, slider_y, 120, "Camera Tilt", getattr(self, 'camera_tilt_slider_val', 0.0), self.set_camera_tilt)

    # ======================================================================== #
    #                        CONTEXTUAL PROVINCE MENUS                         #
    # ======================================================================== #
    domestic_x = c.LEFT_UI_BAR_X
    diplo_x = 180

    # Domestic Set
    self.btn_go_orders = Button(280, 603, "orders", "blue", "Give Orders", lambda: self.change_state("ORDERS"), image=icons.get("paper"), show_text=False)
    self.btn_go_production = Button(280, 543, "orders", "orange", "Production", lambda: self.change_state_if_owned("PRODUCTION", requires_land=True), image=icons.get("industry"), show_text=False)
    #mwsium_square

    # Foreign Set
    self.btn_declare_war = Button(diplo_x, c.ACTION_BTN_START_Y, "diplomatic", "red", "Declare War", lambda: player_diplomacy_actions.handle_declare_war(self))
    self.btn_join_wars = Button(diplo_x, c.ACTION_BTN_START_Y + c.ACTION_BTN_STEP_Y * 1, "diplomatic", "orange", "Join Wars", lambda: player_diplomacy_actions.handle_join_wars(self))
    self.btn_call_to_arms = Button(diplo_x, c.ACTION_BTN_START_Y + c.ACTION_BTN_STEP_Y * 2, "diplomatic", "red", "Call to Arms", lambda: player_diplomacy_actions.handle_call_to_arms(self))
    self.btn_fac_invite = Button(diplo_x, c.ACTION_BTN_START_Y + c.ACTION_BTN_STEP_Y * 3, "diplomatic", "green", "Invite to Faction", lambda: player_diplomacy_actions.handle_specific_action(self, "FACTION_INVITE"))
    self.btn_fac_join_req = Button(diplo_x, c.ACTION_BTN_START_Y + c.ACTION_BTN_STEP_Y * 4, "diplomatic", "green", "Req. Join Faction", lambda: player_diplomacy_actions.handle_specific_action(self, "JOIN_FACTION_REQ"))
    self.btn_fac_kick = Button(diplo_x, c.ACTION_BTN_START_Y + c.ACTION_BTN_STEP_Y * 5, "diplomatic", "red", "Kick from Faction", lambda: player_diplomacy_actions.handle_specific_action(self, "KICK_FACTION_MEMBER"))
    self.btn_fac_create = Button(diplo_x, c.ACTION_BTN_START_Y + c.ACTION_BTN_STEP_Y * 6, "diplomatic", "blue", "Create Faction", lambda: player_diplomacy_actions.handle_specific_action(self, "CREATE_FACTION"))
    self.btn_accept_req = Button(diplo_x, c.ACTION_BTN_START_Y, "diplomatic", "green", "Accept Request", lambda: player_diplomacy_actions.handle_accept_req(self))
    self.btn_reject_req = Button(diplo_x, c.ACTION_BTN_START_Y + c.ACTION_BTN_STEP_Y, "diplomatic", "red", "Reject Request", lambda: player_diplomacy_actions.handle_reject_req(self))

    # Spectator God Power Buttons
    self.btn_force_war = Button(c.ACTION_BTN_X, c.ACTION_BTN_START_Y, "diplomatic", "red", "Force War", lambda: spectator_menus.force_war_menu(self))
    self.btn_force_peace = Button(c.ACTION_BTN_X, c.ACTION_BTN_START_Y + c.ACTION_BTN_STEP_Y, "diplomatic", "green", "Force Ceasefire", lambda: spectator_menus.force_peace_menu(self))
    self.btn_spec_create_fac = Button(c.ACTION_BTN_X, c.ACTION_BTN_START_Y + c.ACTION_BTN_STEP_Y * 2, "diplomatic", "blue", "Create Faction", lambda: spectator_menus.spec_create_faction(self))
    self.btn_spec_join_fac = Button(c.ACTION_BTN_X, c.ACTION_BTN_START_Y + c.ACTION_BTN_STEP_Y * 3, "diplomatic", "yellow", "Join Faction", lambda: spectator_menus.spec_join_faction(self))
    self.btn_spec_invite_fac = Button(c.ACTION_BTN_X, c.ACTION_BTN_START_Y + c.ACTION_BTN_STEP_Y * 2, "diplomatic", "blue", "Invite to Faction", lambda: spectator_menus.spec_invite_faction(self))
    self.btn_spec_leave_fac = Button(c.ACTION_BTN_X, c.ACTION_BTN_START_Y + c.ACTION_BTN_STEP_Y * 3, "diplomatic", "orange", "Leave Faction", lambda: spectator_menus.spec_leave_faction(self))
    self.btn_spec_disband_fac = Button(c.ACTION_BTN_X, c.ACTION_BTN_START_Y + c.ACTION_BTN_STEP_Y * 3, "diplomatic", "red", "Disband Faction", lambda: spectator_menus.spec_disband_faction(self))

    # General Controls
    self.btn_spectator = Button(c.LEFT_UI_BAR_X, c.BTN_SPECTATOR_Y, "medium", "grey", "Spectator Mode", lambda: player_setup.start_spectator(self))
    self.btn_close_info = Button(c.SCREEN_WIDTH - 120, c.TOP_BAR_UI_CENTER_Y, "small", "red", "X", self.deselect_province)
    self.btn_exit_to_menu = Button(c.SCREEN_WIDTH - 120, c.TOP_BAR_UI_CENTER_Y, "small", "red", "Exit", self.exit_to_menu)

    # --- Append all explicitly defined buttons into the elements list ---
    self.elements.extend([
        self.btn_refresh_all,
        self.btn_view_terrain, self.btn_view_political, self.btn_view_relations, self.btn_view_cores, self.btn_view_factions,
        self.btn_view_resources, self.btn_view_blank, self.btn_view_units, self.btn_view_economy, self.btn_toggle_names,
        self.btn_ed_econ, self.btn_ed_rd, self.btn_ed_save, self.btn_ed_load, self.btn_ed_nation,
        self.btn_ed_core, self.btn_ed_autocore, self.btn_ed_resource, self.btn_ed_building,
        self.btn_ed_unit, self.btn_ed_refresh, self.btn_ed_date, self.btn_ed_diplo,
        self.btn_next_turn, self.btn_skip_ai, self.btn_multi_turn, self.btn_gp_edit, self.btn_gp_econ, self.btn_gp_rd, self.btn_gp_msgs,
        self.btn_gp_save, self.btn_gp_settings, self.btn_gp_music, self.btn_gp_faction, self.btn_go_orders, self.btn_go_production,
        self.btn_declare_war, self.btn_join_wars, self.btn_call_to_arms, self.btn_fac_invite,
        self.btn_fac_join_req, self.btn_fac_kick, self.btn_fac_create,
        self.btn_accept_req, self.btn_reject_req, self.btn_force_war, self.btn_force_peace,
        self.btn_spec_create_fac, self.btn_spec_join_fac, self.btn_spec_invite_fac, self.btn_spec_leave_fac,
        self.btn_spec_disband_fac, self.btn_spectator, self.btn_close_info, self.btn_exit_to_menu,
        self.slider_camera_tilt
    ])

    for el in self.elements:
        el.visible = False


# ============================================================================ #
#                            DYNAMIC BUTTON UPDATES                            #
# ============================================================================ #

def update_button_states(map_screen):
    """Dynamically updates button visibility, colors, and text every frame using explicit attributes."""
    
    for el in map_screen.elements:
        el.visible = False

    is_sel = bool(map_screen.selected_province)

    if map_screen.selection_mode:
        map_screen.btn_exit_to_menu.visible = True
        map_screen.btn_spectator.visible = True
        return

    # Helper function to override dynamically updated button values
    def set_btn(btn, visible, enabled, text, color="green"):
        if not btn: return
        btn.visible = visible
        btn.disabled = not enabled
        btn.text = text
        if enabled:
            btn.color, btn.hover_color = c.UI_COLORS[color]
        else:
            btn.color, btn.hover_color = c.UI_COLORS["grey"]
        btn.pressed_color = (max(0, btn.color[0]-40), max(0, btn.color[1]-40), max(0, btn.color[2]-40))

    # ==================================================================== #
    #                        VIEW TOGGLES SELECTION                        #
    # ==================================================================== #
    map_screen.btn_refresh_all.visible = True

    toggles = [
        (map_screen.btn_view_terrain, map_screen.base_layer == "TERRAIN"),
        (map_screen.btn_view_political, map_screen.base_layer == "POLITICAL"),
        (map_screen.btn_view_relations, map_screen.base_layer == "RELATIONS"),
        (map_screen.btn_view_cores, map_screen.base_layer == "CORES"),
        (map_screen.btn_view_factions, map_screen.base_layer == "FACTIONS"),
        (map_screen.btn_view_resources, map_screen.secondary_mode == "RESOURCES"),
        (map_screen.btn_view_blank, map_screen.secondary_mode == "BLANK"),
        (map_screen.btn_view_units, map_screen.secondary_mode == "UNITS"),
        (map_screen.btn_view_economy, map_screen.secondary_mode == "ECONOMY"),
        (map_screen.btn_toggle_names, getattr(map_screen, 'show_country_names', True))
    ]
    for btn, is_active in toggles:
        btn.visible = True
        btn.is_selected = is_active

    # ==================================================================== #
    #                        EDITOR & GAMEPLAY TOOLS                       #
    # ==================================================================== #
    if map_screen.is_editor:
        ed_btns = [
            map_screen.btn_ed_econ, map_screen.btn_ed_rd, map_screen.btn_ed_save, 
            map_screen.btn_ed_load, map_screen.btn_ed_nation, map_screen.btn_ed_core, 
            map_screen.btn_ed_autocore, map_screen.btn_ed_resource, map_screen.btn_ed_building, 
            map_screen.btn_ed_unit, map_screen.btn_ed_refresh, 
            map_screen.btn_ed_date, map_screen.btn_ed_diplo,
            map_screen.btn_gp_settings, map_screen.btn_gp_music, map_screen.slider_camera_tilt
        ]
        for btn in ed_btns:
            btn.visible = True

        # Use the cleaner 'is_selected' gold border instead of overriding raw RGB values
        current_mode = getattr(map_screen, "editor_mode", "")
        map_screen.btn_ed_resource.is_selected = (current_mode == "RESOURCE")
        map_screen.btn_ed_nation.is_selected = (current_mode == "NATION")
        map_screen.btn_ed_building.is_selected = (current_mode == "BUILDING")
        map_screen.btn_ed_core.is_selected = (current_mode == "CORE")
        map_screen.btn_ed_unit.is_selected = (current_mode == "UNIT")

    else:
        viewing_ai = getattr(map_screen, 'viewing_ai_moves', False)
        is_thinking = getattr(map_screen, 'ai_is_thinking', False) or getattr(map_screen, 'is_refreshing', False) # Check our flags

        # Hide/disable the button if we are thinking
        map_screen.btn_next_turn.visible = not is_sel and not is_thinking
        map_screen.btn_next_turn.text = "Resolve Turn" if viewing_ai else "Next Turn"
        map_screen.btn_next_turn.color, map_screen.btn_next_turn.hover_color = c.UI_COLORS["red" if viewing_ai else "purple"]

        # Visibility and active color swapping for the skip toggle
        map_screen.btn_skip_ai.visible = not is_sel and not is_thinking
        skip_on = getattr(map_screen, 'skip_ai_view', False)
        map_screen.btn_skip_ai.text = "Skip AI: ON" if skip_on else "Skip AI: OFF"
        map_screen.btn_skip_ai.color, map_screen.btn_skip_ai.hover_color = c.UI_COLORS["green" if skip_on else "red"]

        is_spec = getattr(map_screen, 'player_country', '') == "Spectator"
        map_screen.btn_multi_turn.visible = not is_sel and not is_thinking and is_spec

        gp_btns = [
            map_screen.btn_gp_edit, map_screen.btn_gp_econ, map_screen.btn_gp_rd,
            map_screen.btn_gp_msgs, map_screen.btn_gp_save, map_screen.btn_gp_settings,
            map_screen.btn_gp_music, map_screen.btn_gp_faction, map_screen.slider_camera_tilt
        ]
        
        always_visible_btns = [map_screen.btn_gp_settings, map_screen.btn_gp_music, map_screen.slider_camera_tilt]

        for btn in gp_btns:
            if btn in always_visible_btns:
                btn.visible = not is_sel
            elif viewing_ai or is_thinking:
                btn.visible = False
            else:
                btn.visible = not is_sel

        # --- ADD THIS LOGIC TO GREY OUT THE FACTION BUTTON ---
        my_faction = map_screen.nation_data.get(map_screen.player_country, {}).get("faction", "")
        map_screen.btn_gp_faction.disabled = not bool(my_faction)

    map_screen.btn_exit_to_menu.visible = not is_sel
    map_screen.btn_close_info.visible = is_sel

    # ======================================================================== #
    #                        PROVINCE INTERACTION LOGIC                        #
    # ======================================================================== #

    if is_sel:
        owner = map_screen.selected_province.get("owner", "Unclaimed")
        
        # --- SPECTATOR ---
        if map_screen.player_country == "Spectator":
            if queries.is_playable(owner, map_screen.nation_data):
                set_btn(map_screen.btn_force_war, True, True, "Force War", "red")
                set_btn(map_screen.btn_force_peace, True, True, "Force Ceasefire", "green")

                in_faction = map_screen.nation_data[owner].get("faction", "")
                is_leader = queries.is_faction_leader(owner, map_screen.nation_data)

                if not in_faction:
                    set_btn(map_screen.btn_spec_create_fac, True, True, "Create Faction", "blue")
                    set_btn(map_screen.btn_spec_join_fac, True, True, "Join Faction", "green")
                else:
                    set_btn(map_screen.btn_spec_invite_fac, True, True, "Invite to Faction", "blue")
                    if is_leader:
                        set_btn(map_screen.btn_spec_disband_fac, True, True, "Disband Faction", "red")
                    else:
                        set_btn(map_screen.btn_spec_leave_fac, True, True, "Leave Faction", "orange")

            # --- NEW: Allow Spectator to view production lines ---
            terrain = map_screen.selected_province.get("terrain", "")
            is_land = terrain not in c.WATER_TERRAINS
            set_btn(map_screen.btn_go_production, True, is_land, "View Production", "orange")

        # --- PLAYER ---
        else:
            has_player_units = queries.has_units_in_province(map_screen.player_country, map_screen.selected_province)
            terrain = map_screen.selected_province.get("terrain", "")
            is_land = terrain not in c.WATER_TERRAINS

            if owner == map_screen.player_country:
                set_btn(map_screen.btn_go_orders, True, has_player_units, "Give Orders", "blue")
                set_btn(map_screen.btn_go_production, True, is_land, "Production", "orange")

            elif queries.is_playable(owner, map_screen.nation_data):
                set_btn(map_screen.btn_go_orders, True, has_player_units, "Give Orders", "blue")

                incoming_action, incoming_turns = queries.get_diplomatic_status(owner, map_screen.player_country, map_screen.nation_data)
                at_war = queries.are_at_war(map_screen.player_country, owner, map_screen.nation_data)
                in_same_faction = queries.are_in_same_faction(map_screen.player_country, owner, map_screen.nation_data)
                pending_action, pending_turns = queries.get_diplomatic_status(map_screen.player_country, owner, map_screen.nation_data)
                
                is_unilateral_pending = pending_action in c.UNILATERAL_ACTIONS
                if is_unilateral_pending and pending_turns > 0:
                    pending_action = ""
                    pending_turns = 0
                
                is_sending = (pending_turns == 0 and pending_action)
                def get_status_text(base):
                    return f"UNDO {base}" if is_sending else "WAITING..."

                my_faction = map_screen.nation_data[map_screen.player_country].get("faction", "")
                target_faction = map_screen.nation_data[owner].get("faction", "")
                i_am_leader = queries.is_faction_leader(map_screen.player_country, map_screen.nation_data)
                target_is_leader = queries.is_faction_leader(owner, map_screen.nation_data)

                # Freed up the UI! The Accept/Reject override block has been removed from here.
                
                dw_enabled = not (not at_war and in_same_faction)
                if pending_action == "CEASEFIRE": dw_text = get_status_text("CEASEFIRE")
                elif pending_action == "WAR_DECLARATION": dw_text = get_status_text("WAR")
                else: dw_text = "Ceasefire" if at_war else "Declare War"
                set_btn(map_screen.btn_declare_war, True, dw_enabled, dw_text, "red")
                
                target_wars = queries.get_enemies(owner, map_screen.nation_data)
                player_wars = queries.get_enemies(map_screen.player_country, map_screen.nation_data)
                can_join_wars = bool(in_same_faction and any(w for w in target_wars if w not in player_wars))
                jw_text = get_status_text("JOIN WARS") if pending_action == "JOIN_WARS" else "Join Wars"
                set_btn(map_screen.btn_join_wars, True, can_join_wars or pending_action == "JOIN_WARS", jw_text, "orange")

                can_call_to_arms = bool(in_same_faction and any(w for w in player_wars if w not in target_wars))
                ca_text = get_status_text("CALL TO ARMS") if pending_action == "CALL_TO_ARMS" else "Call to Arms"
                set_btn(map_screen.btn_call_to_arms, True, can_call_to_arms or pending_action == "CALL_TO_ARMS", ca_text, "red")

                can_invite = bool(my_faction and not target_faction and not at_war)
                inv_text = get_status_text("INVITE") if pending_action == "FACTION_INVITE" else "Invite to Faction"
                set_btn(map_screen.btn_fac_invite, True, can_invite or pending_action == "FACTION_INVITE", inv_text, "green")

                can_req_join = bool(not my_faction and target_faction and not at_war)
                req_text = get_status_text("JOIN REQ") if pending_action == "JOIN_FACTION_REQ" else "Req. Join Faction"
                set_btn(map_screen.btn_fac_join_req, True, can_req_join or pending_action == "JOIN_FACTION_REQ", req_text, "green")

                can_kick = bool(in_same_faction and i_am_leader)
                kick_text = get_status_text("KICK") if pending_action == "KICK_FACTION_MEMBER" else "Kick from Faction"
                set_btn(map_screen.btn_fac_kick, True, can_kick or pending_action == "KICK_FACTION_MEMBER", kick_text, "red")

                can_create_fac = bool(not my_faction and not target_faction and not at_war)
                create_text = get_status_text("CREATE") if pending_action == "CREATE_FACTION" else "Create Faction"
                set_btn(map_screen.btn_fac_create, True, can_create_fac or pending_action == "CREATE_FACTION", create_text, "blue")

            else:
                set_btn(map_screen.btn_go_orders, True, has_player_units, "Give Orders", "blue")


def render_edit_country_buttons(edit_screen):
    """Renders the buttons for the Edit Country Screen."""
    icons = ui_elements.UI_ICONS
    edit_screen.elements = []
    
    edit_screen.btn_cancel = Button(20, 20, "small", "red", "Cancel", edit_screen.exit_to_map)
    edit_screen.btn_save = Button(140, 20, "medium", "green", "Save Changes", edit_screen.save_and_exit)
    
    edit_screen.btn_exp_flag = Button(c.EDIT_COUNTRY_UI_X1, 420, "small_square", "blue", "Export Flag", edit_screen.export_flag, image=icons.get("export"), show_text=False)
    edit_screen.btn_imp_flag = Button(c.EDIT_COUNTRY_UI_X1 + 50, 420, "small_square", "green", "Import Flag", edit_screen.import_flag, image=icons.get("import"), show_text=False)
    edit_screen.btn_reset_flag = Button(c.EDIT_COUNTRY_UI_X1 + 100, 420, "small", "red", "Reset", lambda: edit_screen.trigger_reset("FLAG"))
    
    edit_screen.btn_exp_port = Button(c.EDIT_COUNTRY_UI_X2, 520, "small_square", "blue", "Export Portrait", edit_screen.export_portrait, image=icons.get("export"), show_text=False)
    edit_screen.btn_imp_port = Button(c.EDIT_COUNTRY_UI_X2 + 50, 520, "small_square", "green", "Import Portrait", edit_screen.import_portrait, image=icons.get("import"), show_text=False)
    edit_screen.btn_reset_port = Button(c.EDIT_COUNTRY_UI_X2 + 100, 520, "small", "red", "Reset", lambda: edit_screen.trigger_reset("PORTRAIT"))
    
    edit_screen.elements.extend([
        edit_screen.btn_cancel, edit_screen.btn_save,
        edit_screen.btn_exp_flag, edit_screen.btn_imp_flag, edit_screen.btn_reset_flag,
        edit_screen.btn_exp_port, edit_screen.btn_imp_port, edit_screen.btn_reset_port
    ])
    
    for i, color in enumerate(edit_screen.palette):
        x = c.EDIT_COUNTRY_UI_X3 + (i % 8) * 45
        y = 150 + (i // 8) * 45
        btn = Button(x, y, "small_square", "grey", "", lambda c_val=color: edit_screen.set_color(c_val), show_text=False)
        btn.color = btn.hover_color = color
        btn.shading = False
        edit_screen.elements.append(btn)

    brush_color = "blue" if edit_screen.draw_mode == "BRUSH" else "grey"
    fill_color = "blue" if edit_screen.draw_mode == "FILL" else "grey"
    picker_color = "blue" if edit_screen.draw_mode == "PICKER" else "grey"
    
    edit_screen.elements.extend([
        Button(c.EDIT_COUNTRY_UI_X3, 425, "small_square", "grey", "Undo", edit_screen.undo),
        Button(c.EDIT_COUNTRY_UI_X3 + 50, 425, "small_square", "grey", "Redo", edit_screen.redo),
        Button(c.EDIT_COUNTRY_UI_X3, 375, "small_square", picker_color, "Color Picker", lambda: edit_screen.set_tool("PICKER"), image=icons.get("color_picker"), show_text=False),
        Button(c.EDIT_COUNTRY_UI_X3 + 50, 375, "small_square", brush_color, "Brush", lambda: edit_screen.set_tool("BRUSH"), image=icons.get("brush"), show_text=False),
        Button(c.EDIT_COUNTRY_UI_X3 + 100, 375, "small_square", fill_color, "Fill", lambda: edit_screen.set_tool("FILL"), image=icons.get("paint"), show_text=False),
        Button(c.EDIT_COUNTRY_UI_X3 + 100, 600, "small", "orange", "Map Color", edit_screen.pick_map_color),
        Button(c.EDIT_COUNTRY_UI_X3 + 225, 60, "small_square", "light_grey", "Brush Color", edit_screen.pick_custom_brush_color, image=icons.get("colors"), show_text=False),
        Button(c.EDIT_COUNTRY_UI_X3 + 225, 105, "small_square", "light_grey", "Null Color", lambda: edit_screen.set_color((0, 0, 0, 0)), image=icons.get("red_line"), show_text=False)
    ])

def render_settings_buttons(settings_screen):

    keybind_x = c.SCREEN_WIDTH - 250

    """Renders the buttons and sliders for the Settings screen."""
    back_key_name = pygame.key.name(settings_screen.controller.keybinds.get("BACK", pygame.K_ESCAPE)).upper()
    back_btn_text = f"Back Key: {back_key_name}"
    if settings_screen.listening_for == "BACK":
        back_btn_text = "Press any key..."

    orders_key_name = pygame.key.name(settings_screen.controller.keybinds.get("ORDERS", pygame.K_q)).upper()
    orders_btn_text = f"Orders Key: {orders_key_name}"
    if settings_screen.listening_for == "ORDERS":
        orders_btn_text = "Press any key..."

    settings_screen.elements = [
        Button(50, 50, "small", "red", "Back", settings_screen.go_back),
        Button(keybind_x, 100, "medium", "blue", "Toggle Fullscreen", settings_screen.toggle_full),
    ]

    # --- MASTER AI TOGGLE BUTTON ---
    ai_is_on = settings_screen.ai_mode != "OFF"
    toggle_color = "green" if ai_is_on else "red"
    toggle_text = "LLM AI: ON" if ai_is_on else "LLM AI: OFF"
    settings_screen.elements.append(Button(10, c.SCREEN_HEIGHT - 60, "small", toggle_color, toggle_text, settings_screen.toggle_ai_enabled, font_preset="normal"))

    # --- Only render the sub-options if AI is currently turned ON ---
    if ai_is_on:
        # AI Mode Toggles 
        btn_gem = Button(120, c.SCREEN_HEIGHT - 250, "small", "blue", "GEMINI", lambda: settings_screen.set_ai_mode("GEMINI"))
        btn_gem.is_selected = (settings_screen.ai_mode == "GEMINI")
        settings_screen.elements.append(btn_gem)

        btn_oll = Button(10, c.SCREEN_HEIGHT - 250, "small", "blue", "OLLAMA", lambda: settings_screen.set_ai_mode("OLLAMA"))
        btn_oll.is_selected = (settings_screen.ai_mode == "OLLAMA")
        settings_screen.elements.append(btn_oll)

        btn_gpt = Button(230, c.SCREEN_HEIGHT - 250, "small", "blue", "CHATGPT", lambda: settings_screen.set_ai_mode("CHATGPT"))
        btn_gpt.is_selected = (settings_screen.ai_mode == "CHATGPT")
        settings_screen.elements.append(btn_gpt)

        btn_claude = Button(340, c.SCREEN_HEIGHT - 250, "small", "blue", "CLAUDE", lambda: settings_screen.set_ai_mode("CLAUDE"))
        btn_claude.is_selected = (settings_screen.ai_mode == "CLAUDE")
        settings_screen.elements.append(btn_claude)

        # --- AI IMMERSION BUTTONS ---
        btn_lite = Button(10, c.SCREEN_HEIGHT - 110, "small", "red", "LITE AI", lambda: settings_screen.set_ai_immersion_level("LITE"))
        btn_lite.is_selected = (settings_screen.ai_immersion_level == "LITE")
        settings_screen.elements.append(btn_lite)

        btn_full = Button(10, c.SCREEN_HEIGHT - 155, "small", "red", "FULL AI", lambda: settings_screen.set_ai_immersion_level("FULL"))
        btn_full.is_selected = (settings_screen.ai_immersion_level == "FULL")
        settings_screen.elements.append(btn_full)

        btn_abs = Button(10, c.SCREEN_HEIGHT - 200, "small", "red", "ABSOLUTE AI", lambda: settings_screen.set_ai_immersion_level("ABSOLUTE"))
        btn_abs.is_selected = (settings_screen.ai_immersion_level == "ABSOLUTE")
        settings_screen.elements.append(btn_abs)

        # --- API KEY & MODEL CLEAR BUTTONS ---
        settings_screen.elements.append(Button(c.SETTINGS_BOX_X + c.SETTINGS_BOX_W + 10, c.SETTINGS_KEY_BOX_Y, "small_square", "red", "X", lambda: settings_screen.clear_input("KEY")))
        settings_screen.elements.append(Button(c.SETTINGS_BOX_X + c.SETTINGS_BOX_W + 10, c.SETTINGS_MOD_BOX_Y, "small_square", "red", "X", lambda: settings_screen.clear_input("MOD")))

    # Sliders
    settings_screen.player_slider = Slider(keybind_x, 400, 200, f"Players: {settings_screen.num_players}", (settings_screen.num_players - 1) / 7.0, settings_screen.set_players)
    fps_val = (settings_screen.controller.target_fps - 10) / 50.0
    settings_screen.fps_slider = Slider(keybind_x, 460, 200, f"Max FPS: {settings_screen.controller.target_fps}", fps_val, settings_screen.set_fps)

    # Render above the player count
    thread_val = (settings_screen.ai_threads - 1) / 7.0
    settings_screen.ai_thread_slider = Slider(60, 400, 200, f"Maximum AI Threads: {settings_screen.ai_threads}", thread_val, settings_screen.set_ai_threads)
    
    # Only show the slider if an AI mode is active
    settings_screen.ai_thread_slider.visible = (settings_screen.ai_mode != "OFF")
    
    settings_screen.elements.append(settings_screen.ai_thread_slider)

    settings_screen.elements.extend([
        settings_screen.player_slider,
        settings_screen.fps_slider,
        Button(keybind_x, 530, "medium", "grey", back_btn_text, lambda: settings_screen.start_listening("BACK")),
        Button(keybind_x, 590, "medium", "grey", orders_btn_text, lambda: settings_screen.start_listening("ORDERS")),
        Button(keybind_x, 650, "medium", "red", "Reset Defaults", settings_screen.reset_defaults)
    ])