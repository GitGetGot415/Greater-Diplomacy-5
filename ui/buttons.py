import pygame
from map_logic.system32 import turn_manager
import ui_elements
from ui_elements import Button, Slider
import data.constants as c
from data import queries

# New imports for the refactored logic modules
from map_logic import player_setup
from map_logic.diplomacy import player_diplomacy_actions
from ui import event_handler, spectator_menus, editor_menus

def render_buttons(self):
    """Initializes and registers all map screen buttons uniformly."""
    icons = ui_elements.UI_ICONS
    self.elements = []

    # ==================================================================== #
    #                          MAP VIEW TOGGLES                            #
    # ==================================================================== #
    self.btn_refresh_text = Button(c.SCREEN_WIDTH - 420, c.TOP_BAR_UI_CENTER_Y, "small_square", "blue", "Txt Ref", self.update_country_centers)
    self.btn_refresh_pol = Button(c.SCREEN_WIDTH - 370, c.TOP_BAR_UI_CENTER_Y, "small_square", "grey", "Pol Ref", self.refresh_political_map)
    self.btn_refresh_rel = Button(c.SCREEN_WIDTH - 320, c.TOP_BAR_UI_CENTER_Y, "small_square", "grey", "Rel Ref", self.refresh_relations_map)
    self.btn_refresh_core = Button(c.SCREEN_WIDTH - 270, c.TOP_BAR_UI_CENTER_Y, "small_square", "grey", "Core Ref", self.refresh_cores_map)
    self.btn_refresh_fac = Button(c.SCREEN_WIDTH - 220, c.TOP_BAR_UI_CENTER_Y, "small_square", "grey", "Fac Ref", self.refresh_factions_map)

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
    self.btn_ed_econ = Button(c.LEFT_UI_BAR_X, 500, "left_ui_bar", "green", "Country Economy", econ_callback)
    self.btn_ed_rd = Button(c.LEFT_UI_BAR_X, 200, "left_ui_bar", "blue", "R&D", research_callback, image=icons.get("research"))
    self.btn_ed_save = Button(c.EDITOR_BOT_BTN_START_X, c.BOTTOM_BAR_UI_CENTER_Y, "small", "blue", "Save", self.save_map_data)
    self.btn_ed_load = Button(c.EDITOR_BOT_BTN_START_X - c.EDITOR_BOT_BTN_STEP_X, c.BOTTOM_BAR_UI_CENTER_Y, "small", "blue", "Load", lambda: editor_menus.editor_load_map(self))
    self.btn_ed_nation = Button(c.EDITOR_BOT_BTN_START_X - c.EDITOR_BOT_BTN_STEP_X*2, c.BOTTOM_BAR_UI_CENTER_Y, "small", "grey", "Nation", lambda: editor_menus.select_brush_nation(self))
    self.btn_ed_core = Button(c.EDITOR_BOT_BTN_START_X - c.EDITOR_BOT_BTN_STEP_X*3, c.BOTTOM_BAR_UI_CENTER_Y, "small", "pink", "Core Brush", lambda: editor_menus.select_core_brush(self))
    self.btn_ed_autocore = Button(c.EDITOR_BOT_BTN_START_X - c.EDITOR_BOT_BTN_STEP_X*3, c.SCREEN_HEIGHT - 110, "small", "pink", "Auto-Core", self.auto_assign_cores)
    self.btn_ed_resource = Button(c.EDITOR_BOT_BTN_START_X - c.EDITOR_BOT_BTN_STEP_X*4, c.SCREEN_HEIGHT - 110, "small", "purple", "Resource", lambda: editor_menus.select_resource_brush(self))
    self.btn_ed_building = Button(c.EDITOR_BOT_BTN_START_X - c.EDITOR_BOT_BTN_STEP_X*4, c.BOTTOM_BAR_UI_CENTER_Y, "small", "grey", "Building", lambda: editor_menus.select_building_brush(self))
    self.btn_ed_unit = Button(c.EDITOR_BOT_BTN_START_X - c.EDITOR_BOT_BTN_STEP_X*5, c.BOTTOM_BAR_UI_CENTER_Y, "small", "grey", "Unit", lambda: editor_menus.select_unit_brush(self))
    self.btn_ed_refresh = Button(c.EDITOR_BOT_BTN_START_X - c.EDITOR_BOT_BTN_STEP_X*6, c.BOTTOM_BAR_UI_CENTER_Y, "small", "purple", "Data Refresh", self.refresh_nation_data)
    self.btn_ed_date = Button(c.EDITOR_BOT_BTN_START_X - c.EDITOR_BOT_BTN_STEP_X*7, c.BOTTOM_BAR_UI_CENTER_Y, "small", "purple", "Set Date", lambda: editor_menus.open_editor_date(self))
    self.btn_ed_diplo = Button(c.EDITOR_BOT_BTN_START_X - c.EDITOR_BOT_BTN_STEP_X*8, c.BOTTOM_BAR_UI_CENTER_Y, "small", "red", "Diplomacy", lambda: editor_menus.open_diplomacy_editor(self))

    # Gameplay Buttons
    self.btn_next_turn = Button(c.EDITOR_BOT_BTN_START_X, c.BOTTOM_BAR_UI_CENTER_Y, "small", "purple", "Next Turn", lambda: turn_manager.advance_time(self))
    self.btn_skip_ai = Button(c.EDITOR_BOT_BTN_START_X - c.EDITOR_BOT_BTN_STEP_X, c.BOTTOM_BAR_UI_CENTER_Y, "small", "grey", "Skip AI", self.toggle_skip_ai)
    
    start_y_val = 40
    
    def open_edit_country_action():
        if self.player_country == "Spectator":
            editor_menus.spec_select_edit_country(self)
        elif self.player_country and self.player_country != "None":
            self.editing_country = self.player_country
            self.change_state("EDIT_COUNTRY")

    self.btn_gp_edit = Button(c.LEFT_UI_BAR_X, start_y_val + c.LEFT_UI_BAR_STEP_Y * 1, "medium_square", "orange", "Edit Nation", open_edit_country_action, image=icons.get("brush"), show_text=False)
    self.btn_gp_econ = Button(c.LEFT_UI_BAR_X, start_y_val + c.LEFT_UI_BAR_STEP_Y * 2, "medium_square", "green", "Country Economy", econ_callback, image=icons.get("economy(the_economy_of_a_country_to_be_unusually_specific)"), show_text=False)
    self.btn_gp_rd = Button(c.LEFT_UI_BAR_X, start_y_val + c.LEFT_UI_BAR_STEP_Y * 3, "medium_square", "blue", "R&D", research_callback, image=icons.get("research"), show_text=False)
    self.btn_gp_msgs = Button(c.LEFT_UI_BAR_X, start_y_val + c.LEFT_UI_BAR_STEP_Y * 4, "medium_square", "purple", "Messages", msgs_callback, image=icons.get("mail"), show_text=False)
    self.btn_gp_save = Button(c.LEFT_UI_BAR_X, start_y_val + c.LEFT_UI_BAR_STEP_Y * 5, "medium_square", "green", "Save", self.save_map_data, image=icons.get("save"), show_text=False)
    self.btn_gp_settings = Button(c.LEFT_UI_BAR_X, start_y_val + c.LEFT_UI_BAR_STEP_Y * 6, "medium_square", "grey", "Settings", lambda: self.change_state("SETTINGS"), image=icons.get("settings"), show_text=False)

    # ======================================================================== #
    #                        CONTEXTUAL PROVINCE MENUS                         #
    # ======================================================================== #
    domestic_x = c.LEFT_UI_BAR_X
    diplo_x = 180

    # Domestic Set
    self.btn_go_orders = Button(280, 603, "orders", "blue", "Give Orders", lambda: self.change_state("ORDERS"), image=icons.get("paper"), show_text=False)
    self.btn_go_production = Button(600, 603, "medium_square", "orange", "Production", lambda: self.change_state_if_owned("PRODUCTION", requires_land=True), image=icons.get("industry"), show_text=False)

    # Foreign Set
    self.btn_declare_war = Button(diplo_x, c.ACTION_BTN_START_Y, "diplomatic", "red", "Declare War", lambda: player_diplomacy_actions.handle_declare_war(self))
    self.btn_join_wars = Button(diplo_x, c.ACTION_BTN_START_Y + c.ACTION_BTN_STEP_Y * 1, "diplomatic", "orange", "Join Wars", lambda: player_diplomacy_actions.handle_join_wars(self))
    self.btn_call_to_arms = Button(diplo_x, c.ACTION_BTN_START_Y + c.ACTION_BTN_STEP_Y * 2, "diplomatic", "red", "Call to Arms", lambda: player_diplomacy_actions.handle_call_to_arms(self))
    self.btn_fac_invite = Button(diplo_x, c.ACTION_BTN_START_Y + c.ACTION_BTN_STEP_Y * 3, "diplomatic", "green", "Invite to Faction", lambda: player_diplomacy_actions.handle_specific_action(self, "FACTION_INVITE"))
    self.btn_fac_join_req = Button(diplo_x, c.ACTION_BTN_START_Y + c.ACTION_BTN_STEP_Y * 4, "diplomatic", "green", "Req. Join Faction", lambda: player_diplomacy_actions.handle_specific_action(self, "JOIN_FACTION_REQ"))
    self.btn_fac_kick = Button(diplo_x, c.ACTION_BTN_START_Y + c.ACTION_BTN_STEP_Y * 5, "diplomatic", "red", "Kick from Faction", lambda: player_diplomacy_actions.handle_specific_action(self, "KICK_FACTION_MEMBER"))
    self.btn_fac_create = Button(diplo_x, c.ACTION_BTN_START_Y + c.ACTION_BTN_STEP_Y * 6, "diplomatic", "blue", "Create Faction", lambda: player_diplomacy_actions.handle_specific_action(self, "CREATE_FACTION"))
    self.btn_fac_leave = Button(diplo_x, c.ACTION_BTN_START_Y + c.ACTION_BTN_STEP_Y * 7, "diplomatic", "orange", "Leave Faction", lambda: player_diplomacy_actions.handle_specific_action(self, "LEAVE_FACTION"))
    self.btn_fac_disband = Button(diplo_x, c.ACTION_BTN_START_Y + c.ACTION_BTN_STEP_Y * 8, "diplomatic", "red", "Disband Faction", lambda: player_diplomacy_actions.handle_specific_action(self, "DISBAND_FACTION"))
    self.btn_accept_req = Button(diplo_x, c.ACTION_BTN_START_Y, "diplomatic", "green", "Accept Request", lambda: player_diplomacy_actions.handle_accept_req(self))
    self.btn_reject_req = Button(diplo_x, c.ACTION_BTN_START_Y + c.ACTION_BTN_STEP_Y, "diplomatic", "red", "Reject Request", lambda: player_diplomacy_actions.handle_reject_req(self))

    # Spectator God Power Buttons
    self.btn_force_war = Button(c.ACTION_BTN_X, c.ACTION_BTN_START_Y, "medium", "red", "Force War", lambda: spectator_menus.force_war_menu(self))
    self.btn_force_peace = Button(c.ACTION_BTN_X, c.ACTION_BTN_START_Y + c.ACTION_BTN_STEP_Y, "medium", "green", "Force Ceasefire", lambda: spectator_menus.force_peace_menu(self))
    self.btn_spec_create_fac = Button(c.ACTION_BTN_X, c.ACTION_BTN_START_Y + c.ACTION_BTN_STEP_Y * 2, "medium", "blue", "Create Faction", lambda: spectator_menus.spec_create_faction(self))
    self.btn_spec_join_fac = Button(c.ACTION_BTN_X, c.ACTION_BTN_START_Y + c.ACTION_BTN_STEP_Y * 3, "medium", "green", "Join Faction", lambda: spectator_menus.spec_join_faction(self))
    self.btn_spec_invite_fac = Button(c.ACTION_BTN_X, c.ACTION_BTN_START_Y + c.ACTION_BTN_STEP_Y * 2, "medium", "blue", "Invite to Faction", lambda: spectator_menus.spec_invite_faction(self))
    self.btn_spec_leave_fac = Button(c.ACTION_BTN_X, c.ACTION_BTN_START_Y + c.ACTION_BTN_STEP_Y * 3, "medium", "orange", "Leave Faction", lambda: spectator_menus.spec_leave_faction(self))
    self.btn_spec_disband_fac = Button(c.ACTION_BTN_X, c.ACTION_BTN_START_Y + c.ACTION_BTN_STEP_Y * 3, "medium", "red", "Disband Faction", lambda: spectator_menus.spec_disband_faction(self))

    # General Controls
    self.btn_spectator = Button(c.LEFT_UI_BAR_X, c.BTN_SPECTATOR_Y, "medium", "grey", "Spectator Mode", lambda: player_setup.start_spectator(self))
    self.btn_close_info = Button(c.SCREEN_WIDTH - 120, c.TOP_BAR_UI_CENTER_Y, "small", "red", "X", self.deselect_province)
    self.btn_exit_to_menu = Button(c.SCREEN_WIDTH - 120, c.TOP_BAR_UI_CENTER_Y, "small", "red", "Exit", self.exit_to_menu)

    # --- Append all explicitly defined buttons into the elements list ---
    self.elements.extend([
        self.btn_refresh_text, self.btn_refresh_pol, self.btn_refresh_rel, self.btn_refresh_core, self.btn_refresh_fac,
        self.btn_view_terrain, self.btn_view_political, self.btn_view_relations, self.btn_view_cores, self.btn_view_factions,
        self.btn_view_resources, self.btn_view_blank, self.btn_view_units, self.btn_view_economy, self.btn_toggle_names,
        self.btn_ed_econ, self.btn_ed_rd, self.btn_ed_save, self.btn_ed_load, self.btn_ed_nation,
        self.btn_ed_core, self.btn_ed_autocore, self.btn_ed_resource, self.btn_ed_building,
        self.btn_ed_unit, self.btn_ed_refresh, self.btn_ed_date, self.btn_ed_diplo,
        self.btn_next_turn, self.btn_skip_ai, self.btn_gp_edit, self.btn_gp_econ, self.btn_gp_rd, self.btn_gp_msgs,
        self.btn_gp_save, self.btn_gp_settings, self.btn_go_orders, self.btn_go_production,
        self.btn_declare_war, self.btn_join_wars, self.btn_call_to_arms, self.btn_fac_invite,
        self.btn_fac_join_req, self.btn_fac_kick, self.btn_fac_create, self.btn_fac_leave, self.btn_fac_disband,
        self.btn_accept_req, self.btn_reject_req, self.btn_force_war, self.btn_force_peace,
        self.btn_spec_create_fac, self.btn_spec_join_fac, self.btn_spec_invite_fac, self.btn_spec_leave_fac,
        self.btn_spec_disband_fac, self.btn_spectator, self.btn_close_info, self.btn_exit_to_menu
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
    map_screen.btn_refresh_text.visible = True
    map_screen.btn_refresh_pol.visible = True
    map_screen.btn_refresh_rel.visible = True
    map_screen.btn_refresh_core.visible = True
    map_screen.btn_refresh_fac.visible = True

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
            map_screen.btn_ed_date, map_screen.btn_ed_diplo
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
        is_thinking = getattr(map_screen, 'ai_is_thinking', False) # Check our new flag

        # Hide/disable the button if we are thinking
        map_screen.btn_next_turn.visible = not is_sel and not is_thinking
        map_screen.btn_next_turn.text = "Resolve Turn" if viewing_ai else "Next Turn"
        map_screen.btn_next_turn.color, map_screen.btn_next_turn.hover_color = c.UI_COLORS["red" if viewing_ai else "purple"]

        # Visibility and active color swapping for the skip toggle
        map_screen.btn_skip_ai.visible = not is_sel and not is_thinking
        skip_on = getattr(map_screen, 'skip_ai_view', False)
        map_screen.btn_skip_ai.text = "Skip AI: ON" if skip_on else "Skip AI: OFF"
        map_screen.btn_skip_ai.color, map_screen.btn_skip_ai.hover_color = c.UI_COLORS["green" if skip_on else "red"]

        if not viewing_ai:
            gp_btns = [
                map_screen.btn_gp_edit, map_screen.btn_gp_econ, map_screen.btn_gp_rd,
                map_screen.btn_gp_msgs, map_screen.btn_gp_save, map_screen.btn_gp_settings
            ]
            for btn in gp_btns:
                btn.visible = not is_sel

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
                
                is_unilateral_pending = pending_action in ["WAR_DECLARATION", "JOIN_WARS", "BREAK_ALLIANCE", "KICK_FACTION_MEMBER", "LEAVE_FACTION", "DISBAND_FACTION"]
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

                if incoming_turns > 0 and incoming_action in ["FACTION_INVITE", "JOIN_FACTION_REQ", "CEASEFIRE", "CALL_TO_ARMS", "CREATE_FACTION"]:
                    action_name = incoming_action.replace("_", " ")
                    set_btn(map_screen.btn_accept_req, True, True, f"Accept {action_name}", "green")
                    set_btn(map_screen.btn_reject_req, True, True, f"Reject {action_name}", "red")
                else:
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

                    can_invite = bool(my_faction and i_am_leader and not target_faction and not at_war)
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

                    can_leave_fac = bool(my_faction and in_same_faction and not i_am_leader and target_is_leader)
                    leave_text = get_status_text("LEAVE") if pending_action == "LEAVE_FACTION" else "Leave Faction"
                    set_btn(map_screen.btn_fac_leave, True, can_leave_fac or pending_action == "LEAVE_FACTION", leave_text, "orange")

                    can_disband_fac = bool(my_faction and i_am_leader and in_same_faction)
                    disband_text = get_status_text("DISBAND") if pending_action == "DISBAND_FACTION" else "Disband Faction"
                    set_btn(map_screen.btn_fac_disband, True, can_disband_fac or pending_action == "DISBAND_FACTION", disband_text, "red")

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
    
    edit_screen.btn_exp_port = Button(c.EDIT_COUNTRY_UI_X2, 520, "small_square", "blue", "Export Portrait", edit_screen.export_portrait, image=icons.get("export"), show_text=False)
    edit_screen.btn_imp_port = Button(c.EDIT_COUNTRY_UI_X2 + 50, 520, "small_square", "green", "Import Portrait", edit_screen.import_portrait, image=icons.get("import"), show_text=False)
    
    edit_screen.elements.extend([
        edit_screen.btn_cancel, edit_screen.btn_save,
        edit_screen.btn_exp_flag, edit_screen.btn_imp_flag,
        edit_screen.btn_exp_port, edit_screen.btn_imp_port
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
        Button(c.EDIT_COUNTRY_UI_X3 + 125, 80, "small_square", "purple", "Brush Color", edit_screen.pick_custom_brush_color, image=icons.get("star"), show_text=False),
        Button(c.EDIT_COUNTRY_UI_X3 + 175, 80, "small_square", "purple", "Null Color", lambda: edit_screen.set_color((0, 0, 0, 0)), image=icons.get("red_line"), show_text=False)
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
    toggle_text = "AI: ON" if ai_is_on else "AI: OFF"
    settings_screen.elements.append(Button(10, c.SCREEN_HEIGHT - 50, "small", toggle_color, toggle_text, settings_screen.toggle_ai_enabled))

    # --- Only render the sub-options if AI is currently turned ON ---
    if ai_is_on:
        # AI Mode Toggles 
        btn_gem = Button(120, c.SCREEN_HEIGHT - 150, "small", "blue", "GEMINI", lambda: settings_screen.set_ai_mode("GEMINI"))
        btn_gem.is_selected = (settings_screen.ai_mode == "GEMINI")
        settings_screen.elements.append(btn_gem)

        btn_oll = Button(120, c.SCREEN_HEIGHT - 200, "small", "blue", "OLLAMA", lambda: settings_screen.set_ai_mode("OLLAMA"))
        btn_oll.is_selected = (settings_screen.ai_mode == "OLLAMA")
        settings_screen.elements.append(btn_oll)

        btn_gpt = Button(230, c.SCREEN_HEIGHT - 150, "small", "blue", "CHATGPT", lambda: settings_screen.set_ai_mode("CHATGPT"))
        btn_gpt.is_selected = (settings_screen.ai_mode == "CHATGPT")
        settings_screen.elements.append(btn_gpt)

        btn_claude = Button(230, c.SCREEN_HEIGHT - 200, "small", "blue", "CLAUDE", lambda: settings_screen.set_ai_mode("CLAUDE"))
        btn_claude.is_selected = (settings_screen.ai_mode == "CLAUDE")
        settings_screen.elements.append(btn_claude)

        # --- AI IMMERSION BUTTONS ---
        btn_lite = Button(10, c.SCREEN_HEIGHT - 150, "small", "red", "LITE AI", lambda: settings_screen.set_ai_immersion_level("LITE"))
        btn_lite.is_selected = (settings_screen.ai_immersion_level == "LITE")
        settings_screen.elements.append(btn_lite)

        btn_full = Button(10, c.SCREEN_HEIGHT - 200, "small", "red", "FULL AI", lambda: settings_screen.set_ai_immersion_level("FULL"))
        btn_full.is_selected = (settings_screen.ai_immersion_level == "FULL")
        settings_screen.elements.append(btn_full)

        btn_abs = Button(10, c.SCREEN_HEIGHT - 250, "small", "red", "ABSOLUTE AI", lambda: settings_screen.set_ai_immersion_level("ABSOLUTE"))
        btn_abs.is_selected = (settings_screen.ai_immersion_level == "ABSOLUTE")
        settings_screen.elements.append(btn_abs)

    # --- API KEY CLEAR BUTTONS ---
    if settings_screen.ai_mode == "GEMINI":
        settings_screen.elements.append(Button(c.SETTINGS_GEMINI_BOX_X + c.SETTINGS_GEMINI_BOX_W + 20, c.SETTINGS_GEMINI_BOX_Y, "small", "red", "Clear", settings_screen.clear_gemini_api_key))
    elif settings_screen.ai_mode == "OLLAMA":
        settings_screen.elements.append(Button(c.SETTINGS_OLLAMA_BOX_X + c.SETTINGS_OLLAMA_BOX_W + 20, c.SETTINGS_OLLAMA_BOX_Y, "small", "red", "Clear", settings_screen.clear_ollama_model))
    elif settings_screen.ai_mode == "CHATGPT":
        settings_screen.elements.append(Button(c.SETTINGS_CHATGPT_BOX_X + c.SETTINGS_CHATGPT_BOX_W + 20, c.SETTINGS_CHATGPT_BOX_Y, "small", "red", "Clear", settings_screen.clear_chatgpt_api_key))
    elif settings_screen.ai_mode == "CLAUDE":
        settings_screen.elements.append(Button(c.SETTINGS_CLAUDE_BOX_X + c.SETTINGS_CLAUDE_BOX_W + 20, c.SETTINGS_CLAUDE_BOX_Y, "small", "red", "Clear", settings_screen.clear_claude_api_key))

    # Sliders
    settings_screen.volume_slider = Slider(keybind_x, 320, 200, "Volume", settings_screen.volume, settings_screen.set_volume)
    settings_screen.player_slider = Slider(keybind_x, 400, 200, f"Players: {settings_screen.num_players}", (settings_screen.num_players - 1) / 7.0, settings_screen.set_players)

    settings_screen.elements.extend([
        settings_screen.volume_slider,
        settings_screen.player_slider,
        Button(keybind_x, 530, "medium", "grey", back_btn_text, lambda: settings_screen.start_listening("BACK")),
        Button(keybind_x, 590, "medium", "grey", orders_btn_text, lambda: settings_screen.start_listening("ORDERS")),
        Button(keybind_x, 650, "medium", "red", "Reset Keybinds", settings_screen.reset_defaults)
    ])