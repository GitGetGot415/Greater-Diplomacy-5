import pygame
from map_logic.system32 import turn_manager
import ui_elements
from ui_elements import Button, Slider
import data.constants as c
from data import queries
from map_logic.setup import player_setup
from map_logic.diplomacy import player_diplomacy_actions
from ui import spectator_menus, editor_menus, scripted_events_editor

# ============================================================================ #
#                                   LAYOUT                                     #
# ============================================================================ #
# Every hardcoded position for the map screen's buttons lives here so a nudge
# only ever means editing this block. Sizes come from c.SIZES; the two shared
# bar centre-lines (c.TOP_BAR_UI_CENTER_Y / c.BOTTOM_BAR_UI_CENTER_Y) stay in
# constants.py because other screens line up against them too.

# --- Map view toggles (bottom-left grid) ---
VIEW_BTN_START_X = 10
VIEW_BTN_STEP_X = 50
VIEW_BTN_ROW1_Y = c.SCREEN_HEIGHT - 50
VIEW_BTN_ROW2_Y = c.SCREEN_HEIGHT - 100

# --- Left vertical bar (Identity / Economy / R&D / ...) ---
LEFT_UI_BAR_X = 20
LEFT_UI_BAR_STEP_Y = 35
LEFT_UI_BAR_START_Y = 75
CAMERA_TILT_SLIDER_ROW = 13
CAMERA_TILT_SLIDER_WIDTH = 120

# --- Bottom-right button strip (editor tools, turn controls) ---
EDITOR_BOT_BTN_START_X = c.SCREEN_WIDTH - 120
EDITOR_BOT_BTN_STEP_X = 110

# --- Top bar, right-aligned ---
TOP_RIGHT_BTN_X = c.SCREEN_WIDTH - 120
REFRESH_BTN_X = c.SCREEN_WIDTH - 240
GLOBAL_ECON_BTN_X = c.SCREEN_WIDTH - 380

# --- Mode buttons on the country-selection screen ---
BTN_SPECTATOR_Y = c.SCREEN_HEIGHT - 55
BTN_TACTICAL_OFFSET_X = 240

# --- Province action buttons ---
ACTION_BTN_X = 200          # Spectator god-power column
DIPLO_BTN_X = 180           # Player diplomacy column
ACTION_BTN_START_Y = 300
ACTION_BTN_STEP_Y = 33

PROVINCE_BTN_X = 280
BTN_ORDERS_Y = 603
BTN_PRODUCTION_Y = 543

# --- Multiplayer host strip ---
MP_HOST_BTN_Y = 15
MP_HOST_MANAGE_X = 380
MP_HOST_EXPORT_X = 600
MP_HOST_KEYS_X = 820

# --- Edit Country screen ---
EDIT_COUNTRY_SWITCH_BTN_X = 350
EDIT_COUNTRY_SWITCH_BTN_Y = 20
EDIT_COUNTRY_CANCEL_POS = (20, 20)
EDIT_COUNTRY_SAVE_POS = (140, 20)
EDIT_COUNTRY_ICON_STEP_X = 50   # Export/Import/Reset triplets
EDIT_COUNTRY_RESET_OFFSET_X = 100
EDIT_COUNTRY_FLAG_ROW_Y = 400
EDIT_COUNTRY_PORTRAIT_ROW_Y = 520
EDIT_COUNTRY_TOOLS_ROW_Y = 375
EDIT_COUNTRY_UNDO_ROW_Y = 425
EDIT_COUNTRY_MAP_COLOR_Y = 600
EDIT_COUNTRY_RESET_COLOR_POS = (c.SCREEN_WIDTH - 330, 550)
EDIT_COUNTRY_SWATCH_START_Y = 150
EDIT_COUNTRY_SWATCH_STEP = 45
EDIT_COUNTRY_SWATCH_COLUMNS = 8
EDIT_COUNTRY_SIDE_TOOL_OFFSET_X = 225
EDIT_COUNTRY_BRUSH_COLOR_Y = 60
EDIT_COUNTRY_NULL_COLOR_Y = 105

# --- Settings screen ---
SETTINGS_RIGHT_COL_X = c.SCREEN_WIDTH - 250
SETTINGS_BACK_POS = (50, 50)
SETTINGS_FULLSCREEN_Y = 40
SETTINGS_CHECKERBOARD_WATER_Y = 100
SETTINGS_FPS_TOGGLE_Y = 160
SETTINGS_DRAG_KEY_Y = 220
SETTINGS_PLAYER_SLIDER_Y = 340
SETTINGS_FPS_SLIDER_Y = 400
SETTINGS_AI_THREAD_SLIDER_POS = (60, 400)
SETTINGS_SLIDER_WIDTH = 200
SETTINGS_RESET_Y = 650
SETTINGS_KEYBIND_ROWS_Y = (470, 530, 590)
SETTINGS_AI_TOGGLE_POS = (10, c.SCREEN_HEIGHT - 60)
SETTINGS_AI_PROVIDER_Y = c.SCREEN_HEIGHT - 250
SETTINGS_AI_PROVIDER_START_X = 10
SETTINGS_AI_PROVIDER_STEP_X = 110
SETTINGS_AI_IMMERSION_X = 10
SETTINGS_AI_IMMERSION_ROWS_Y = (c.SCREEN_HEIGHT - 110, c.SCREEN_HEIGHT - 155, c.SCREEN_HEIGHT - 200)
SETTINGS_CLEAR_BTN_GAP_X = 10
SETTINGS_PATH_EDIT_OFFSET_X = -220
SETTINGS_PATH_RESET_OFFSET_X = -110
SETTINGS_PATH_BOX_X = c.SCREEN_WIDTH // 2 - 150


def render_buttons(map_screen):
    """Initializes and registers all map screen buttons uniformly."""
    icons = ui_elements.UI_ICONS
    map_screen.elements = []

    # ==================================================================== #
    #                        MAP VIEW TOGGLES                              #
    # ==================================================================== #
    map_screen.btn_refresh_all = Button(REFRESH_BTN_X, c.TOP_BAR_UI_CENTER_Y, "small", "blue", "Refresh Maps", map_screen.refresh_all_maps, font_preset="normal")
    map_screen.btn_global_econ_overview = Button(GLOBAL_ECON_BTN_X, c.TOP_BAR_UI_CENTER_Y, "small", "pink", "Global Economy", lambda: editor_menus.open_editor_economy(map_screen), font_preset="normal")

    map_screen.btn_view_terrain = Button(VIEW_BTN_START_X, VIEW_BTN_ROW1_Y, "small_square", "green", "Terrain", lambda: map_screen.set_map_layer("TERRAIN"), image=icons.get("terrain"), show_text=False)
    map_screen.btn_view_political = Button(VIEW_BTN_START_X + VIEW_BTN_STEP_X, VIEW_BTN_ROW1_Y, "small_square", "green", "Political", lambda: map_screen.set_map_layer("POLITICAL"), image=icons.get("political"), show_text=False)
    map_screen.btn_view_relations = Button(VIEW_BTN_START_X + VIEW_BTN_STEP_X * 2, VIEW_BTN_ROW1_Y, "small_square", "green", "Relations", lambda: map_screen.set_map_layer("RELATIONS"), image=icons.get("relations"), show_text=False)
    map_screen.btn_view_cores = Button(VIEW_BTN_START_X + VIEW_BTN_STEP_X * 3, VIEW_BTN_ROW1_Y, "small_square", "green", "Cores", lambda: map_screen.set_map_layer("CORES"), image=icons.get("core"), show_text=False)
    map_screen.btn_view_factions = Button(VIEW_BTN_START_X + VIEW_BTN_STEP_X * 4, VIEW_BTN_ROW1_Y, "small_square", "green", "Factions", lambda: map_screen.set_map_layer("FACTIONS"), image=icons.get("faction"), show_text=False)

    map_screen.btn_view_resources = Button(VIEW_BTN_START_X, VIEW_BTN_ROW2_Y, "small_square", "red", "Resources", lambda: map_screen.set_view_mode("RESOURCES"), image=icons.get("resource"), show_text=False)
    map_screen.btn_view_blank = Button(VIEW_BTN_START_X + VIEW_BTN_STEP_X, VIEW_BTN_ROW2_Y, "small_square", "red", "Blank", lambda: map_screen.set_view_mode("BLANK"), image=icons.get("blank"), show_text=False)
    map_screen.btn_view_units = Button(VIEW_BTN_START_X + VIEW_BTN_STEP_X * 2, VIEW_BTN_ROW2_Y, "small_square", "red", "Units", lambda: map_screen.set_view_mode("UNITS"), image=icons.get("unit"), show_text=False)
    map_screen.btn_view_economy = Button(VIEW_BTN_START_X + VIEW_BTN_STEP_X * 3, VIEW_BTN_ROW2_Y, "small_square", "red", "Economy", lambda: map_screen.set_view_mode("ECONOMY"), image=icons.get("industry"), show_text=False)
    map_screen.btn_toggle_names = Button(VIEW_BTN_START_X + VIEW_BTN_STEP_X * 4, VIEW_BTN_ROW2_Y, "small_square", "blue", "Names", map_screen.toggle_country_names, image=icons.get("names"), show_text=False)

    # ==================================================================== #
    #                        LEFT & BOTTOM UI BARS                         #
    # ==================================================================== #
    start_y_val = LEFT_UI_BAR_START_Y

   # Editor Buttons
    map_screen.btn_ed_load = Button(EDITOR_BOT_BTN_START_X - EDITOR_BOT_BTN_STEP_X *(-0.5), c.BOTTOM_BAR_UI_CENTER_Y, "small_square", "blue", "Load", lambda: editor_menus.editor_load_map(map_screen), font_preset="normal")
    map_screen.btn_ed_nation = Button(EDITOR_BOT_BTN_START_X - EDITOR_BOT_BTN_STEP_X*0.5, c.BOTTOM_BAR_UI_CENTER_Y, "small", "grey", "Nation Brush", lambda: editor_menus.select_brush_nation(map_screen), font_preset="normal")
    map_screen.btn_ed_core = Button(EDITOR_BOT_BTN_START_X - EDITOR_BOT_BTN_STEP_X*1.5, c.BOTTOM_BAR_UI_CENTER_Y, "small", "pink", "Core Brush", lambda: editor_menus.select_core_brush(map_screen), font_preset="normal")
    map_screen.btn_ed_autocore = Button(EDITOR_BOT_BTN_START_X - EDITOR_BOT_BTN_STEP_X*2.5, c.BOTTOM_BAR_UI_CENTER_Y, "small", "pink", "Auto-Core", map_screen.auto_assign_cores, font_preset="normal")
    
    map_screen.btn_ed_clear = Button(EDITOR_BOT_BTN_START_X - EDITOR_BOT_BTN_STEP_X*3.5, c.BOTTOM_BAR_UI_CENTER_Y, "small_square", "pink", "Clear", lambda: editor_menus.open_clear_menu(map_screen), image=icons.get("red_line"), show_text=False)
    
    map_screen.btn_ed_claim = Button(EDITOR_BOT_BTN_START_X - EDITOR_BOT_BTN_STEP_X*4, c.BOTTOM_BAR_UI_CENTER_Y, "small_square", "orange", "Claim Brush", lambda: editor_menus.select_claim_brush(map_screen), image=icons.get("paper"), show_text=False)
    map_screen.btn_ed_resource = Button(EDITOR_BOT_BTN_START_X - EDITOR_BOT_BTN_STEP_X*4.5, c.BOTTOM_BAR_UI_CENTER_Y, "small_square", "purple", "Resource", lambda: editor_menus.select_resource_brush(map_screen), image=icons.get("resource"), show_text=False)
    map_screen.btn_ed_building = Button(EDITOR_BOT_BTN_START_X - EDITOR_BOT_BTN_STEP_X*5, c.BOTTOM_BAR_UI_CENTER_Y, "small_square", "grey", "Building", lambda: editor_menus.select_building_brush(map_screen), image=icons.get("industry"), show_text=False)
    map_screen.btn_ed_unit = Button(EDITOR_BOT_BTN_START_X - EDITOR_BOT_BTN_STEP_X*5.5, c.BOTTOM_BAR_UI_CENTER_Y, "small_square", "grey", "Unit", lambda: editor_menus.select_unit_brush(map_screen), image=icons.get("unit"), show_text=False)
    map_screen.btn_ed_refresh = Button(EDITOR_BOT_BTN_START_X - EDITOR_BOT_BTN_STEP_X*6.5, c.BOTTOM_BAR_UI_CENTER_Y, "small", "purple", "Data Refresh", map_screen.refresh_nation_data, font_preset="normal")
    map_screen.btn_ed_date = Button(EDITOR_BOT_BTN_START_X - EDITOR_BOT_BTN_STEP_X*7, c.BOTTOM_BAR_UI_CENTER_Y, "small_square", "orange", "Set Date", lambda: editor_menus.open_editor_date(map_screen), image=icons.get("clock"), show_text=False)
    map_screen.btn_ed_edited = Button(EDITOR_BOT_BTN_START_X - EDITOR_BOT_BTN_STEP_X*8, c.BOTTOM_BAR_UI_CENTER_Y, "small", "green", "Edited Countries", lambda: editor_menus.open_edited_countries(map_screen), font_preset="normal")
    map_screen.btn_ed_diplo = Button(LEFT_UI_BAR_X, start_y_val + LEFT_UI_BAR_STEP_Y * 8, "left_ui_button", "red", "Diplomacy", lambda: editor_menus.open_diplomacy_editor(map_screen))
    map_screen.btn_ed_scripts = Button(LEFT_UI_BAR_X, start_y_val + LEFT_UI_BAR_STEP_Y * 10, "left_ui_button", "red", "Scripted Events", lambda: scripted_events_editor.open_scripted_events_editor(map_screen), font_preset="normal")

    # Gameplay Buttons
    if getattr(map_screen, 'multiplayer_mode', False):
        def m_export():
            from data.io.multiplayer_io import export_move_file
            import os
            turn = map_screen.time_manager.total_turns if hasattr(map_screen, 'time_manager') else 1
            cid = map_screen.player_country
            save_name = f"Turn_{turn}_{cid}.gd5move"
            export_path = os.path.join(c.TOURNAMENT_SAVES_DIR, save_name)
            player_key = getattr(map_screen, 'multiplayer_player_key', '')
            export_move_file(map_screen, export_path, player_key)
            map_screen.show_feedback(f"Move exported to {export_path}")
            
        map_screen.btn_next_turn = Button(EDITOR_BOT_BTN_START_X, c.BOTTOM_BAR_UI_CENTER_Y, "small", "purple", "Export Turn", m_export)
        
        def m_import():
            from data.io.multiplayer_io import load_move_files
            import os

            def on_picked(file_path):
                if file_path:
                    cid = map_screen.player_country
                    player_key = getattr(map_screen, 'multiplayer_player_key', '')
                    keys_dict = {cid: player_key}

                    load_move_files(map_screen, [file_path], keys_dict)
                    map_screen.show_feedback(f"Move imported from {os.path.basename(file_path)}")

                    map_screen.refresh_political_map()
                    map_screen.refresh_factions_map()
                    map_screen.refresh_relations_map()
                    # If economy map refresh is needed we can do it, but Map doesn't have refresh_economy_map so we skip or call refresh_all_maps()
                    map_screen.refresh_cores_map()
                    map_screen.refresh_faction_territories_map()
                    if hasattr(map_screen, 'sync_units_to_data'):
                        map_screen.sync_units_to_data()

            queries.open_file_browser(map_screen, "Select Move File", c.TOURNAMENT_SAVES_DIR,
                                      extensions=[".gd5move"], on_result=on_picked)

        map_screen.btn_import_turn = Button(EDITOR_BOT_BTN_START_X - EDITOR_BOT_BTN_STEP_X, c.BOTTOM_BAR_UI_CENTER_Y, "small", "purple", "Import Turn", m_import)
    else:
        map_screen.btn_next_turn = Button(EDITOR_BOT_BTN_START_X, c.BOTTOM_BAR_UI_CENTER_Y, "small", "purple", "Next Turn", lambda: turn_manager.advance_time(map_screen))
        map_screen.btn_import_turn = Button(-1000, -1000, "small", "grey", "Import Turn", lambda: None)
        
    map_screen.btn_skip_ai = Button(EDITOR_BOT_BTN_START_X - EDITOR_BOT_BTN_STEP_X, c.BOTTOM_BAR_UI_CENTER_Y, "small", "grey", "Skip AI", map_screen.toggle_skip_ai, font_preset="normal")
    map_screen.btn_multi_turn = Button(EDITOR_BOT_BTN_START_X - EDITOR_BOT_BTN_STEP_X * 2, c.BOTTOM_BAR_UI_CENTER_Y, "small", "blue", "Multi-Turn", map_screen.trigger_multi_turn)
    
    def sub_screen_opener(module_path, class_name):
        """A click callback that late-imports a screen and runs it over the map.

        The import has to stay inside the callback: these screens import the
        map package, which is the module currently being built.
        """
        def open_it():
            from importlib import import_module
            from ui.player_diplomacy_menus import _run_pygame_sub_screen
            _run_pygame_sub_screen(map_screen, getattr(import_module(module_path), class_name)(map_screen))
        return open_it

    open_declare_independence = sub_screen_opener(
        "screens.map_related_screens.declare_independence", "Declare_Independence_Screen")

    map_screen.btn_declare_indep = Button(EDITOR_BOT_BTN_START_X - EDITOR_BOT_BTN_STEP_X * 2, c.BOTTOM_BAR_UI_CENTER_Y, "small", "pink", "Independence!", open_declare_independence, font_preset="normal")

    def open_edit_country_action():
        if map_screen.player_country == "Spectator" or map_screen.is_editor:
            editor_menus.spec_select_edit_country(map_screen)
        elif map_screen.player_country and map_screen.player_country != "None":
            map_screen.editing_country = map_screen.player_country
            map_screen.change_state("EDIT_COUNTRY")

    # Deferred to execution time to prevent initialization sequence bugs: whether
    # the player is an editor/spectator isn't settled when the buttons are built.
    def editor_or(editor_action, player_state):
        return lambda: (editor_action(map_screen) if (map_screen.is_editor or map_screen.player_country == "Spectator")
                        else map_screen.change_state(player_state))

    econ_callback = editor_or(editor_menus.open_starting_economy_editor, "ECONOMY")
    research_callback = editor_or(editor_menus.open_map_research_editor, "RESEARCH")
    msgs_callback = editor_or(editor_menus.open_spectator_messages, "MESSAGES")

    # The left-hand bar: one column, one size, one colour, one row per entry.
    # Claims and Puppets route everyone to the native Pygame screen so they can
    # see the map highlights.
    left_bar_buttons = (
        ("btn_gp_edit", 1, "Identity", "brush", open_edit_country_action),
        ("btn_gp_econ", 2, "Economy",
         "economy(the_economy_of_a_country_to_be_unusually_specific)", econ_callback),
        ("btn_gp_rd", 3, "R&D", "research", research_callback),
        ("btn_gp_msgs", 4, "Mail", "mail", msgs_callback),
        ("btn_gp_save", 5, "Save", "save", map_screen.save_map_data),
        ("btn_gp_settings", 6, "Settings", "settings", lambda: map_screen.change_state("SETTINGS")),
        ("btn_gp_music", 7, "Music", "music", lambda: map_screen.change_state("MUSIC_PLAYER")),
        ("btn_gp_faction", 8, "Faction", "faction", lambda: map_screen.change_state("FACTION")),
        ("btn_gp_claims", 9, "Claims", "paper",
         lambda: player_diplomacy_actions.open_claims_menu(map_screen)),
        ("btn_gp_puppets", 10, "Puppets", "puppet",
         lambda: player_diplomacy_actions.open_puppets_menu(map_screen)),
        ("btn_gp_automation", 11, "Automation", None,
         sub_screen_opener("screens.map_related_screens.automation_screen", "Automation_Screen")),
    )
    for attr, row, label, icon_name, action in left_bar_buttons:
        setattr(map_screen, attr, Button(LEFT_UI_BAR_X, start_y_val + LEFT_UI_BAR_STEP_Y * row,
                                   "left_ui_button", "pink", label, action,
                                   image=icons.get(icon_name) if icon_name else None,
                                   show_text=True))

    # Register the Slider below the new Automation button
    slider_y = int(start_y_val + LEFT_UI_BAR_STEP_Y * CAMERA_TILT_SLIDER_ROW)
    map_screen.slider_camera_tilt = Slider(LEFT_UI_BAR_X, slider_y, CAMERA_TILT_SLIDER_WIDTH, "Camera Tilt", map_screen.camera_tilt_slider_val, map_screen.set_camera_tilt)

    # ======================================================================== #
    #                        CONTEXTUAL PROVINCE MENUS                         #
    # ======================================================================== #
    diplo_x = DIPLO_BTN_X

    # Domestic Set
    map_screen.btn_go_orders = Button(PROVINCE_BTN_X, BTN_ORDERS_Y, "orders", "blue", "Give Orders", lambda: map_screen.change_state("ORDERS"), image=icons.get("paper"), show_text=False)
    map_screen.btn_go_production = Button(PROVINCE_BTN_X, BTN_PRODUCTION_Y, "orders", "orange", "Production", lambda: map_screen.change_state_if_owned("PRODUCTION", requires_land=True), image=icons.get("industry"), show_text=False)

    # Foreign Set. Rows overlap deliberately -- only one of the buttons sharing
    # a row is ever visible at a time (e.g. Request vs Cancel Mil. Access).
    # An entry's last column is either a bare callback or the action string
    # handle_specific_action should queue.
    diplo_buttons = (
        ("btn_declare_war", 0, "red", "Declare War", player_diplomacy_actions.handle_declare_war),
        ("btn_accept_req", 0, "green", "Accept Request", player_diplomacy_actions.handle_accept_req),
        ("btn_reject_req", 1, "red", "Reject Request", player_diplomacy_actions.handle_reject_req),
        ("btn_req_mil_access", 1, "blue", "Request Mil. Access", "REQ_MILITARY_ACCESS"),
        ("btn_cancel_mil_access", 1, "orange", "Cancel Mil. Access", "CANCEL_MILITARY_ACCESS"),
        ("btn_revoke_mil_access", 2, "red", "Revoke Mil. Access", "REVOKE_MILITARY_ACCESS"),
        ("btn_join_wars", 3, "orange", "Join Wars", player_diplomacy_actions.handle_join_wars),
        ("btn_call_to_arms", 4, "red", "Call to Arms", player_diplomacy_actions.handle_call_to_arms),
        ("btn_fac_invite", 5, "green", "Invite to Faction", "FACTION_INVITE"),
        ("btn_fac_join_req", 6, "green", "Req. Join Faction", "JOIN_FACTION_REQ"),
        ("btn_fac_kick", 7, "red", "Kick from Faction", "KICK_FACTION_MEMBER"),
        ("btn_fac_create", 8, "blue", "Create Faction", "CREATE_FACTION"),
    )
    for attr, row, color, label, handler in diplo_buttons:
        if isinstance(handler, str):
            action = (lambda a=handler:
                      player_diplomacy_actions.handle_specific_action(map_screen, a))
        else:
            action = lambda h=handler: h(map_screen)
        setattr(map_screen, attr, Button(diplo_x, ACTION_BTN_START_Y + ACTION_BTN_STEP_Y * row,
                                   "diplomatic", color, label, action))

    # Spectator God Power Buttons. Same overlapping-row rule as the foreign set:
    # only one of the buttons sharing a row is shown for a given selection.
    spectator_buttons = (
        ("btn_force_war", 0, "red", "Force War", "force_war_menu"),
        ("btn_force_peace", 1, "green", "Force Ceasefire", "force_peace_menu"),
        ("btn_spec_create_fac", 2, "blue", "Create Faction", "spec_create_faction"),
        ("btn_spec_invite_fac", 2, "blue", "Invite to Faction", "spec_invite_faction"),
        ("btn_spec_join_fac", 3, "yellow", "Join Faction", "spec_join_faction"),
        ("btn_spec_leave_fac", 3, "orange", "Leave Faction", "spec_leave_faction"),
        ("btn_spec_disband_fac", 3, "red", "Disband Faction", "spec_disband_faction"),
    )
    for attr, row, color, label, menu_fn in spectator_buttons:
        setattr(map_screen, attr, Button(ACTION_BTN_X, ACTION_BTN_START_Y + ACTION_BTN_STEP_Y * row,
                                   "diplomatic", color, label,
                                   lambda f=menu_fn: getattr(spectator_menus, f)(map_screen)))
    
    def host_manage_players():
        from ui.multiplayer_host_panel import manage_players_panel
        manage_players_panel(map_screen)
        
    def host_export_turn():
        from ui.multiplayer_host_panel import export_next_turn
        export_next_turn(map_screen)
        
    def host_manage_keys():
        from ui.multiplayer_host_panel import manage_keys_panel
        manage_keys_panel(map_screen)
        
    map_screen.btn_spec_mp_manage = Button(MP_HOST_MANAGE_X, MP_HOST_BTN_Y, "diplomatic", "blue", "Manage Players", host_manage_players)
    map_screen.btn_spec_mp_export = Button(MP_HOST_EXPORT_X, MP_HOST_BTN_Y, "diplomatic", "green", "Export Turn", host_export_turn)
    map_screen.btn_spec_mp_keys = Button(MP_HOST_KEYS_X, MP_HOST_BTN_Y, "keys", "purple", "Keys", host_manage_keys)

    # General Controls
    def start_spectator_action():
        player_setup.start_spectator(map_screen)
        map_screen.refresh_fog_map()
        
    def toggle_tactical_action():
        map_screen.tactical_mode = not map_screen.tactical_mode
        
        # Auto-swap the view mode so the player can actually see the units
        if map_screen.tactical_mode:
            map_screen.set_view_mode("UNITS")
        else:
            map_screen.set_view_mode("BLANK")
            
        map_screen.show_feedback(f"Mode: {'TACTICAL' if map_screen.tactical_mode else 'STRATEGIC'}")

    map_screen.btn_spectator = Button(LEFT_UI_BAR_X, BTN_SPECTATOR_Y, "medium", "grey", "Spectator Mode", start_spectator_action)
    map_screen.btn_tactical = Button(LEFT_UI_BAR_X + BTN_TACTICAL_OFFSET_X, BTN_SPECTATOR_Y, "medium", "orange", "Tactical Mode", toggle_tactical_action)
    map_screen.btn_close_info = Button(TOP_RIGHT_BTN_X, c.TOP_BAR_UI_CENTER_Y, "small", "red", "X", map_screen.deselect_province)
    map_screen.btn_exit_to_menu = Button(TOP_RIGHT_BTN_X, c.TOP_BAR_UI_CENTER_Y, "small", "red", "Exit", map_screen.exit_to_menu)

    # --- Append all explicitly defined buttons into the elements list ---
    map_screen.elements.extend([
        map_screen.btn_refresh_all, map_screen.btn_global_econ_overview,
        map_screen.btn_view_terrain, map_screen.btn_view_political, map_screen.btn_view_relations, map_screen.btn_view_cores, map_screen.btn_view_factions,
        map_screen.btn_view_resources, map_screen.btn_view_blank, map_screen.btn_view_units, map_screen.btn_view_economy, map_screen.btn_toggle_names,
        map_screen.btn_ed_load, map_screen.btn_ed_nation,
        map_screen.btn_ed_core, map_screen.btn_ed_claim, map_screen.btn_ed_autocore, map_screen.btn_ed_clear, map_screen.btn_ed_resource, map_screen.btn_ed_building,
        map_screen.btn_ed_unit, map_screen.btn_ed_refresh, map_screen.btn_ed_edited, map_screen.btn_ed_date, map_screen.btn_ed_diplo, map_screen.btn_ed_scripts,
        map_screen.btn_next_turn, map_screen.btn_import_turn, map_screen.btn_skip_ai, map_screen.btn_multi_turn, map_screen.btn_declare_indep, map_screen.btn_gp_edit, map_screen.btn_gp_econ, map_screen.btn_gp_rd, map_screen.btn_gp_msgs,
        map_screen.btn_gp_save, map_screen.btn_gp_settings, map_screen.btn_gp_music, map_screen.btn_gp_faction, map_screen.btn_gp_claims, map_screen.btn_gp_puppets, map_screen.btn_gp_automation, map_screen.btn_go_orders, map_screen.btn_go_production,
        map_screen.btn_declare_war, map_screen.btn_join_wars, map_screen.btn_call_to_arms, map_screen.btn_fac_invite,
        map_screen.btn_fac_join_req, map_screen.btn_fac_kick, map_screen.btn_fac_create,
        map_screen.btn_req_mil_access, map_screen.btn_cancel_mil_access, map_screen.btn_revoke_mil_access,
        map_screen.btn_accept_req, map_screen.btn_reject_req, map_screen.btn_force_war, map_screen.btn_force_peace,
        map_screen.btn_spec_create_fac, map_screen.btn_spec_join_fac, map_screen.btn_spec_invite_fac, map_screen.btn_spec_leave_fac,
        map_screen.btn_spec_disband_fac, map_screen.btn_spectator, map_screen.btn_tactical, map_screen.btn_close_info, map_screen.btn_exit_to_menu,
        map_screen.btn_spec_mp_manage, map_screen.btn_spec_mp_export, map_screen.btn_spec_mp_keys,
        map_screen.slider_camera_tilt
    ])

    for el in map_screen.elements:
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
        
        # Hide spectator and tactical buttons if awaiting confirmation
        show_mode_buttons = not bool(map_screen.pending_selection)
        map_screen.btn_spectator.visible = show_mode_buttons
        map_screen.btn_tactical.visible = show_mode_buttons

        is_multiplayer = getattr(map_screen, 'num_players', 1) > 1

        if is_multiplayer:
            map_screen.btn_tactical.apply_state(enabled=False, text="Tactical mode disabled for multiplayer")
        elif map_screen.tactical_mode:
            map_screen.btn_tactical.apply_state(enabled=True, text="TACTICAL", color="orange")
        else:
            map_screen.btn_tactical.apply_state(enabled=True, text="STRATEGIC", color="green")

        # --- BUGFIX: Disable Spectator Mode while in Tactical Mode ---
        if map_screen.tactical_mode:
            map_screen.btn_spectator.apply_state(enabled=False, text="Disabled in Tactical")
        else:
            map_screen.btn_spectator.apply_state(enabled=True, text="Spectator Mode", color="grey")

        return

    # Shorthand for the per-frame visible/enabled/text/colour updates below
    def set_btn(btn, visible, enabled, text, color="green"):
        if btn:
            btn.apply_state(visible=visible, enabled=enabled, text=text, color=color)

    # ==================================================================== #
    #                        VIEW TOGGLES SELECTION                        #
    # ==================================================================== #
    map_screen.btn_refresh_all.visible = True
    map_screen.btn_global_econ_overview.visible = map_screen.is_editor or map_screen.player_country == "Spectator"

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
        (map_screen.btn_toggle_names, map_screen.show_country_names)
    ]
    for btn, is_active in toggles:
        btn.visible = True
        btn.is_selected = is_active

    # ==================================================================== #
    #                        EDITOR & GAMEPLAY TOOLS                       #
    # ==================================================================== #
    if map_screen.is_editor:
        ed_btns = [
            map_screen.btn_gp_edit, map_screen.btn_gp_econ, map_screen.btn_gp_rd,
            map_screen.btn_gp_msgs, map_screen.btn_gp_save, map_screen.btn_gp_claims,
            map_screen.btn_ed_load, map_screen.btn_ed_nation, map_screen.btn_ed_core, map_screen.btn_ed_claim, 
            map_screen.btn_ed_autocore, map_screen.btn_ed_resource, map_screen.btn_ed_building, 
            map_screen.btn_ed_unit, map_screen.btn_ed_refresh, map_screen.btn_ed_clear,
            map_screen.btn_ed_date, map_screen.btn_ed_edited, map_screen.btn_ed_diplo, map_screen.btn_ed_scripts,
            map_screen.btn_gp_settings, map_screen.btn_gp_music, map_screen.slider_camera_tilt
        ]
        for btn in ed_btns:
            btn.visible = True

        # Use the cleaner 'is_selected' gold border instead of overriding raw RGB values
        for mode, btn in (("RESOURCE", map_screen.btn_ed_resource),
                          ("NATION", map_screen.btn_ed_nation),
                          ("BUILDING", map_screen.btn_ed_building),
                          ("CORE", map_screen.btn_ed_core),
                          ("CLAIM", map_screen.btn_ed_claim),
                          ("UNIT", map_screen.btn_ed_unit)):
            btn.is_selected = (map_screen.editor_mode == mode)

    else:
        viewing_ai = map_screen.viewing_ai_moves
        is_thinking = map_screen.ai_is_thinking or map_screen.is_refreshing or map_screen.is_saving

        # Hide/disable the button if we are thinking
        map_screen.btn_next_turn.visible = not is_sel and not is_thinking
        if getattr(map_screen, 'multiplayer_mode', False):
            map_screen.btn_next_turn.text = "Export Turn"
        else:
            map_screen.btn_next_turn.text = "Resolve Turn" if viewing_ai else "Next Turn"
            
        map_screen.btn_next_turn.set_palette("red" if viewing_ai else "purple")

        # Visibility and active color swapping for the skip toggle
        if getattr(map_screen, 'multiplayer_mode', False):
            map_screen.btn_skip_ai.visible = False
            map_screen.btn_import_turn.visible = not is_sel and not is_thinking
        else:
            map_screen.btn_import_turn.visible = False
            map_screen.btn_skip_ai.visible = not is_sel and not is_thinking
            skip_on = map_screen.skip_ai_view
            map_screen.btn_skip_ai.text = "Skip AI: ON" if skip_on else "Skip AI: OFF"
            map_screen.btn_skip_ai.set_palette("green" if skip_on else "red")

        is_spec = map_screen.player_country == "Spectator"
        map_screen.btn_multi_turn.visible = not is_sel and not is_thinking and is_spec
        
        if is_spec:
            map_screen.btn_spec_mp_manage.visible = getattr(map_screen, 'multiplayer_host_mode', False) and not is_sel and not is_thinking
            map_screen.btn_spec_mp_export.visible = getattr(map_screen, 'multiplayer_host_mode', False) and not is_sel and not is_thinking
            map_screen.btn_spec_mp_keys.visible = getattr(map_screen, 'multiplayer_host_mode', False) and not is_sel and not is_thinking
        map_screen.btn_declare_indep.visible = map_screen.tactical_mode and not is_sel and not is_thinking

        gp_btns = [
            map_screen.btn_gp_edit, map_screen.btn_gp_econ, map_screen.btn_gp_rd,
            map_screen.btn_gp_msgs, map_screen.btn_gp_save, map_screen.btn_gp_settings,
            map_screen.btn_gp_music, map_screen.btn_gp_faction, map_screen.btn_gp_claims,
            map_screen.btn_gp_puppets, map_screen.btn_gp_automation, map_screen.slider_camera_tilt
        ]
        
        always_visible_btns = [map_screen.btn_gp_settings, map_screen.btn_gp_music, map_screen.slider_camera_tilt]

        for btn in gp_btns:
            if btn in always_visible_btns:
                btn.visible = not is_sel
            elif viewing_ai or is_thinking:
                btn.visible = False
            else:
                btn.visible = not is_sel

        # GREY OUT THE FACTION BUTTON
        my_faction = map_screen.nation_data.get(map_screen.player_country, {}).get("faction", "")
        map_screen.btn_gp_faction.disabled = not bool(my_faction)

        # DISABLE BUTTONS FOR BATTLE ROYALE
        if c.BATTLE_ROYALE_MODE:
            map_screen.btn_gp_faction.disabled = True
            map_screen.btn_gp_claims.disabled = True
        
        # --- TACTICAL MODE LOCKDOWNS ---
        if map_screen.tactical_mode:
            for btn in (map_screen.btn_gp_faction, map_screen.btn_gp_puppets, map_screen.btn_gp_edit, map_screen.btn_gp_automation):
                btn.apply_state(enabled=False)
        else:
            if bool(my_faction):
                map_screen.btn_gp_faction.set_palette("pink")
            map_screen.btn_gp_puppets.set_palette("pink")


            # --- Update Automation Bubble ---
            if map_screen.player_country in map_screen.nation_data and map_screen.player_country not in ["Spectator", "None", "Editor"]:
                p_data = map_screen.nation_data.get(map_screen.player_country, {})
                auto = p_data.get("automation", {})
                active_count = sum(1 for val in auto.values() if val)
                map_screen.btn_gp_automation.notification_count = active_count
            else:
                map_screen.btn_gp_automation.notification_count = 0
            map_screen.btn_gp_edit.set_palette("pink")

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

            # Allow Spectator to view production lines
            is_land = not queries.is_water_province(map_screen.selected_province)
            set_btn(map_screen.btn_go_production, True, is_land, "View Production", "orange")

        # --- PLAYER ---
        else:
            has_player_units = queries.has_units_in_province(map_screen.player_country, map_screen.selected_province)
            is_land = not queries.is_water_province(map_screen.selected_province)
            is_tactical = map_screen.tactical_mode

            if owner == map_screen.player_country:
                set_btn(map_screen.btn_go_orders, True, has_player_units, "Give Orders", "blue")
                
                if is_tactical:
                    set_btn(map_screen.btn_go_production, True, False, "Tactical: Disabled", "grey")
                else:
                    set_btn(map_screen.btn_go_production, True, is_land, "Production", "orange")

            elif queries.is_playable(owner, map_screen.nation_data):
                set_btn(map_screen.btn_go_orders, True, has_player_units, "Give Orders", "blue")
                
                if is_tactical:
                    # Disable all foreign interactions
                    set_btn(map_screen.btn_declare_war, True, False, "Tactical: Disabled", "grey")
                    set_btn(map_screen.btn_join_wars, True, False, "Tactical: Disabled", "grey")
                    set_btn(map_screen.btn_call_to_arms, True, False, "Tactical: Disabled", "grey")
                    set_btn(map_screen.btn_fac_invite, True, False, "Tactical: Disabled", "grey")
                    set_btn(map_screen.btn_fac_join_req, True, False, "Tactical: Disabled", "grey")
                    set_btn(map_screen.btn_fac_kick, True, False, "Tactical: Disabled", "grey")
                    set_btn(map_screen.btn_fac_create, True, False, "Tactical: Disabled", "grey")
                    set_btn(map_screen.btn_req_mil_access, True, False, "Tactical: Disabled", "grey")
                    set_btn(map_screen.btn_cancel_mil_access, True, False, "Tactical: Disabled", "grey")
                    set_btn(map_screen.btn_revoke_mil_access, True, False, "Tactical: Disabled", "grey")
                    return

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

                my_master = map_screen.nation_data.get(map_screen.player_country, {}).get("master", "")
                t_master = map_screen.nation_data.get(owner, {}).get("master", "")

                is_rebellion = (my_master == owner)
                is_preemptive = (t_master == map_screen.player_country)

                # War / Peace UI routing (Allows internal faction wars strictly for rebellions & preemptive attacks)
                dw_enabled = not (not at_war and in_same_faction and not (is_rebellion or is_preemptive))
                has_truce = queries.has_active_truce(map_screen.player_country, owner, map_screen.nation_data)
                
                # Fetch the exact number of turns remaining ---
                truce_turns = map_screen.nation_data.get(map_screen.player_country, {}).get("truces", {}).get(owner, 0)
                
                if has_truce and not at_war:
                    dw_enabled = False

                if pending_action == "PEACE_TREATY" or pending_action == "CEASEFIRE": 
                    if pending_turns > 0:
                        dw_text = "Peace Offer Pending"
                        dw_enabled = False
                    else:
                        dw_text = "Edit Peace Offer"
                elif pending_action == "WAR_DECLARATION": 
                    dw_text = "Edit War Declaration"
                else: 
                    if has_truce and not at_war:
                        dw_text = f"Truce Active ({truce_turns})"
                    else:
                        if at_war:
                            if c.BATTLE_ROYALE_MODE:
                                dw_text = "Battle Royale (No Peace)"
                                dw_enabled = False
                            else:
                                dw_text = "Ceasefire / Peace"
                        elif my_master == owner:
                            dw_text = "Independence war"
                        elif t_master == map_screen.player_country:
                            dw_text = "Preemptive war"
                        else:
                            dw_text = "Declare War"
                    
                set_btn(map_screen.btn_declare_war, True, dw_enabled, dw_text, "red")
                
                target_wars = queries.get_enemies(owner, map_screen.nation_data)
                player_wars = queries.get_enemies(map_screen.player_country, map_screen.nation_data)
                can_join_wars = bool(in_same_faction and any(w for w in target_wars if w not in player_wars))
                jw_text = get_status_text("JOIN WARS") if pending_action == "JOIN_WARS" else "Join Wars"
                set_btn(map_screen.btn_join_wars, True, can_join_wars or pending_action == "JOIN_WARS", jw_text, "orange")

                can_call_to_arms = bool(in_same_faction and any(w for w in player_wars if w not in target_wars))
                ca_text = get_status_text("CALL TO ARMS") if pending_action == "CALL_TO_ARMS" else "Call to Arms"
                set_btn(map_screen.btn_call_to_arms, True, can_call_to_arms or pending_action == "CALL_TO_ARMS", ca_text, "red")

                factions_disabled = getattr(c, 'DISABLE_FACTIONS', False)

                can_invite = bool(not factions_disabled and my_faction and not target_faction and not at_war)
                inv_text = get_status_text("INVITE") if pending_action == "FACTION_INVITE" else "Invite to Faction"
                set_btn(map_screen.btn_fac_invite, True, can_invite or pending_action == "FACTION_INVITE", inv_text, "green")

                can_req_join = bool(not factions_disabled and not my_faction and target_faction and not at_war)
                req_text = get_status_text("JOIN REQ") if pending_action == "JOIN_FACTION_REQ" else "Req. Join Faction"
                set_btn(map_screen.btn_fac_join_req, True, can_req_join or pending_action == "JOIN_FACTION_REQ", req_text, "green")

                can_kick = bool(not factions_disabled and in_same_faction and i_am_leader)
                kick_text = get_status_text("KICK") if pending_action == "KICK_FACTION_MEMBER" else "Kick from Faction"
                set_btn(map_screen.btn_fac_kick, True, can_kick or pending_action == "KICK_FACTION_MEMBER", kick_text, "red")

                can_create_fac = bool(not factions_disabled and not my_faction and not target_faction and not at_war)
                create_text = get_status_text("CREATE") if pending_action == "CREATE_FACTION" else "Create Faction"
                set_btn(map_screen.btn_fac_create, True, can_create_fac or pending_action == "CREATE_FACTION", create_text, "blue")

                has_access_to_them = queries.has_military_access(map_screen.player_country, owner, map_screen.nation_data)
                they_have_access_to_me = queries.has_military_access(owner, map_screen.player_country, map_screen.nation_data)
                
                can_req_access = not has_access_to_them and not at_war and not in_same_faction
                req_acc_text = get_status_text("REQ ACCESS") if pending_action == "REQ_MILITARY_ACCESS" else "Request Mil. Access"
                
                if has_access_to_them:
                    cancel_acc_text = get_status_text("CANCEL ACCESS") if pending_action == "CANCEL_MILITARY_ACCESS" else "Cancel Mil. Access"
                    set_btn(map_screen.btn_cancel_mil_access, True, True, cancel_acc_text, "orange")
                    set_btn(map_screen.btn_req_mil_access, False, False, "", "blue")
                else:
                    set_btn(map_screen.btn_cancel_mil_access, False, False, "", "orange")
                    set_btn(map_screen.btn_req_mil_access, True, can_req_access or pending_action == "REQ_MILITARY_ACCESS", req_acc_text, "blue")
                    
                if they_have_access_to_me:
                    revoke_acc_text = get_status_text("REVOKE ACCESS") if pending_action == "REVOKE_MILITARY_ACCESS" else "Revoke Mil. Access"
                    set_btn(map_screen.btn_revoke_mil_access, True, True, revoke_acc_text, "red")
                else:
                    set_btn(map_screen.btn_revoke_mil_access, False, False, "", "red")

                # HIDE ALLIANCE/FACTION BUTTONS IN BATTLE ROYALE
                if c.BATTLE_ROYALE_MODE:
                    map_screen.btn_join_wars.visible = False
                    map_screen.btn_call_to_arms.visible = False
                    map_screen.btn_fac_invite.visible = False
                    map_screen.btn_fac_join_req.visible = False
                    map_screen.btn_fac_kick.visible = False
                    map_screen.btn_fac_create.visible = False
                    map_screen.btn_req_mil_access.visible = False
                    map_screen.btn_cancel_mil_access.visible = False
                    map_screen.btn_revoke_mil_access.visible = False

            else:
                set_btn(map_screen.btn_go_orders, True, has_player_units, "Give Orders", "blue")


def render_edit_country_buttons(edit_screen):
    """Renders the buttons for the Edit Country Screen."""
    icons = ui_elements.UI_ICONS
    edit_screen.elements = []

    edit_screen.btn_cancel = Button(*EDIT_COUNTRY_CANCEL_POS, "small", "red", "Cancel", edit_screen.exit_screen)
    edit_screen.btn_save = Button(*EDIT_COUNTRY_SAVE_POS, "medium", "green", "Save Changes", edit_screen.save_and_exit)

    # Switch country graphics configuration handler
    edit_screen.btn_switch_appearance = Button(
        EDIT_COUNTRY_SWITCH_BTN_X,
        EDIT_COUNTRY_SWITCH_BTN_Y,
        "medium", "orange", "Switch Appearance",
        edit_screen.open_switch_appearance_menu
    )

    # Flag and portrait rows are the same Export / Import / Reset triplet, so
    # they come off one spec rather than six near-identical lines.
    for column_x, row_y, kind, attr in ((c.EDIT_COUNTRY_UI_X1, EDIT_COUNTRY_FLAG_ROW_Y, "flag", "flag"),
                                        (c.EDIT_COUNTRY_UI_X2, EDIT_COUNTRY_PORTRAIT_ROW_Y, "portrait", "port")):
        label = kind.capitalize()
        setattr(edit_screen, "btn_exp_" + attr, Button(
            column_x, row_y, "small_square", "blue", "Export " + label,
            getattr(edit_screen, "export_" + kind), image=icons.get("export"), show_text=False))
        setattr(edit_screen, "btn_imp_" + attr, Button(
            column_x + EDIT_COUNTRY_ICON_STEP_X, row_y, "small_square", "green", "Import " + label,
            getattr(edit_screen, "import_" + kind), image=icons.get("import"), show_text=False))
        setattr(edit_screen, "btn_reset_" + attr, Button(
            column_x + EDIT_COUNTRY_RESET_OFFSET_X, row_y, "small", "red", "Reset",
            lambda k=kind: edit_screen.trigger_reset(k.upper())))

    edit_screen.btn_reset_map_color = Button(*EDIT_COUNTRY_RESET_COLOR_POS, "small", "red", "Reset Color", edit_screen.reset_map_color)

    edit_screen.elements.extend([
        edit_screen.btn_cancel, edit_screen.btn_save, edit_screen.btn_switch_appearance,
        edit_screen.btn_exp_flag, edit_screen.btn_imp_flag, edit_screen.btn_reset_flag,
        edit_screen.btn_exp_port, edit_screen.btn_imp_port, edit_screen.btn_reset_port,
        edit_screen.btn_reset_map_color
    ])

    for i, color in enumerate(edit_screen.palette):
        x = c.EDIT_COUNTRY_UI_X3 + (i % EDIT_COUNTRY_SWATCH_COLUMNS) * EDIT_COUNTRY_SWATCH_STEP
        y = EDIT_COUNTRY_SWATCH_START_Y + (i // EDIT_COUNTRY_SWATCH_COLUMNS) * EDIT_COUNTRY_SWATCH_STEP
        btn = Button(x, y, "small_square", "grey", "", lambda c_val=color: edit_screen.set_color(c_val), show_text=False)
        btn.set_colors(color)
        btn.shading = False
        edit_screen.elements.append(btn)

    # Drawing tools are a one-of-three picker; the active tool shows blue
    for slot, (tool, label, icon_name) in enumerate((("PICKER", "Color Picker", "color_picker"),
                                                    ("BRUSH", "Brush", "brush"),
                                                    ("FILL", "Fill", "paint"))):
        edit_screen.elements.append(
            Button(c.EDIT_COUNTRY_UI_X3 + slot * EDIT_COUNTRY_ICON_STEP_X, EDIT_COUNTRY_TOOLS_ROW_Y, "small_square",
                   "blue" if edit_screen.draw_mode == tool else "grey", label,
                   lambda t=tool: edit_screen.set_tool(t), image=icons.get(icon_name), show_text=False)
        )

    side_tool_x = c.EDIT_COUNTRY_UI_X3 + EDIT_COUNTRY_SIDE_TOOL_OFFSET_X
    edit_screen.elements.extend([
        Button(c.EDIT_COUNTRY_UI_X3, EDIT_COUNTRY_UNDO_ROW_Y, "small_square", "grey", "Undo", edit_screen.undo),
        Button(c.EDIT_COUNTRY_UI_X3 + EDIT_COUNTRY_ICON_STEP_X, EDIT_COUNTRY_UNDO_ROW_Y, "small_square", "grey", "Redo", edit_screen.redo),
        Button(c.EDIT_COUNTRY_UI_X3 + EDIT_COUNTRY_RESET_OFFSET_X, EDIT_COUNTRY_MAP_COLOR_Y, "small", "orange", "Map Color", edit_screen.pick_map_color),
        Button(side_tool_x, EDIT_COUNTRY_BRUSH_COLOR_Y, "small_square", "light_grey", "Brush Color", edit_screen.pick_custom_brush_color, image=icons.get("colors"), show_text=False),
        Button(side_tool_x, EDIT_COUNTRY_NULL_COLOR_Y, "small_square", "light_grey", "Null Color", lambda: edit_screen.set_color((0, 0, 0, 0)), image=icons.get("red_line"), show_text=False)
    ])


def make_option_buttons(options, on_select, current, size="small", color="blue", font_preset="button"):
    """Builds a row/column of mutually exclusive buttons with the active one highlighted.

    Options are (x, y, value, label) tuples. Used for every "pick exactly one
    of these" cluster (AI provider, immersion level, wargoal, peace term...) so
    the gold selection border and the callback binding are done identically.
    """
    built = []
    for x, y, value, label in options:
        btn = Button(x, y, size, color, label, lambda v=value: on_select(v), font_preset=font_preset)
        btn.is_selected = (value == current)
        built.append(btn)
    return built

def render_settings_buttons(settings_screen):
    """Renders the buttons and sliders for the Settings screen."""
    keybind_x = SETTINGS_RIGHT_COL_X

    settings_screen.elements = [
        ui_elements.make_back_button(settings_screen.save_and_go_back, pos=SETTINGS_BACK_POS),
        Button(keybind_x, SETTINGS_FULLSCREEN_Y, "medium", "blue", "Toggle Fullscreen", settings_screen.toggle_full),
        Button(keybind_x, SETTINGS_CHECKERBOARD_WATER_Y, "medium", "green" if settings_screen.checkerboard_water else "red",
               f"Checkerboard Water: {'ON' if settings_screen.checkerboard_water else 'OFF'}", settings_screen.toggle_checkerboard_water),
        Button(keybind_x, SETTINGS_FPS_TOGGLE_Y, "medium", "green" if settings_screen.show_fps else "red",
               f"Show FPS: {'ON' if settings_screen.show_fps else 'OFF'}", settings_screen.toggle_fps),
        Button(keybind_x, SETTINGS_DRAG_KEY_Y, "medium", "purple", f"Drag Key: {settings_screen.drag_mouse_toggle}", settings_screen.toggle_drag_button),
    ]

    # --- MASTER AI TOGGLE BUTTON ---
    ai_is_on = settings_screen.ai_mode != "OFF"
    settings_screen.elements.append(
        Button(*SETTINGS_AI_TOGGLE_POS, "small", "green" if ai_is_on else "red",
               "LLM AI: ON" if ai_is_on else "LLM AI: OFF",
               settings_screen.toggle_ai_enabled, font_preset="normal")
    )

    # --- Only render the sub-options if AI is currently turned ON ---
    if ai_is_on:
        # AI provider picker
        settings_screen.elements.extend(make_option_buttons([
            (SETTINGS_AI_PROVIDER_START_X + i * SETTINGS_AI_PROVIDER_STEP_X, SETTINGS_AI_PROVIDER_Y, mode, mode)
            for i, mode in enumerate(("OLLAMA", "GEMINI", "CHATGPT", "CLAUDE"))
        ], settings_screen.set_ai_mode, settings_screen.ai_mode))

        # AI immersion level picker
        settings_screen.elements.extend(make_option_buttons([
            (SETTINGS_AI_IMMERSION_X, y, level, f"{level} AI")
            for y, level in zip(SETTINGS_AI_IMMERSION_ROWS_Y, ("LITE", "FULL", "ABSOLUTE"))
        ], settings_screen.set_ai_immersion_level, settings_screen.ai_immersion_level, color="red"))

        # --- API KEY & MODEL CLEAR BUTTONS ---
        clear_x = c.SETTINGS_BOX_X + c.SETTINGS_BOX_W + SETTINGS_CLEAR_BTN_GAP_X
        for box_type, box_y in (("KEY", c.SETTINGS_KEY_BOX_Y), ("MOD", c.SETTINGS_MOD_BOX_Y)):
            settings_screen.elements.append(
                Button(clear_x, box_y, "small_square", "red", "X",
                       lambda b=box_type: settings_screen.clear_input(b))
            )

    # Sliders
    settings_screen.player_slider = Slider(keybind_x, SETTINGS_PLAYER_SLIDER_Y, SETTINGS_SLIDER_WIDTH,
                                           f"Players: {settings_screen.num_players}",
                                           (settings_screen.num_players - 1) / 7.0, settings_screen.set_players)
    fps_val = (settings_screen.controller.target_fps - 10) / 50.0
    settings_screen.fps_slider = Slider(keybind_x, SETTINGS_FPS_SLIDER_Y, SETTINGS_SLIDER_WIDTH,
                                        f"Max FPS: {settings_screen.controller.target_fps}", fps_val, settings_screen.set_fps)

    # Render above the player count
    thread_val = (settings_screen.ai_threads - 1) / 7.0
    settings_screen.ai_thread_slider = Slider(*SETTINGS_AI_THREAD_SLIDER_POS, SETTINGS_SLIDER_WIDTH,
                                              f"Maximum AI Threads: {settings_screen.ai_threads}",
                                              thread_val, settings_screen.set_ai_threads)

    # Only show the slider if an AI mode is active
    settings_screen.ai_thread_slider.visible = ai_is_on

    settings_screen.elements.extend([
        settings_screen.ai_thread_slider,
        settings_screen.player_slider,
        settings_screen.fps_slider,
        Button(keybind_x, SETTINGS_RESET_Y, "medium", "red", "Reset Defaults", settings_screen.reset_defaults),
    ])

    # Rebindable keys: label shows the bound key, or the capture prompt while listening
    keybind_rows = zip(SETTINGS_KEYBIND_ROWS_Y,
                       (("FULLSCREEN", "Fullscreen", pygame.K_F11),
                        ("BACK", "Back", pygame.K_ESCAPE),
                        ("ORDERS", "Orders", pygame.K_q)))
    for y, (action, label, default_key) in keybind_rows:
        if settings_screen.listening_for == action:
            text = "Press any key..."
        else:
            key_name = pygame.key.name(settings_screen.controller.keybinds.get(action, default_key)).upper()
            text = f"{label} Key: {key_name}"
        settings_screen.elements.append(
            Button(keybind_x, y, "medium", "grey", text,
                   lambda a=action: settings_screen.start_listening(a))
        )

    # Edit/Reset pair for each path and colour row, driven off the screen's own table
    for y, _kind, key, _label in settings_screen.PATH_ROWS:
        settings_screen.elements.extend([
            Button(SETTINGS_PATH_BOX_X + SETTINGS_PATH_EDIT_OFFSET_X, y, "small", "blue", "Edit", lambda k=key: settings_screen.edit_setting(k)),
            Button(SETTINGS_PATH_BOX_X + SETTINGS_PATH_RESET_OFFSET_X, y, "small", "red", "Reset", lambda k=key: settings_screen.reset_setting(k)),
        ])
