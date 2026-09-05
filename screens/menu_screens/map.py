# Standard Library & Third Party
import pygame
import os
import sys

# Add the parent directory (project root) to the Python path so it can find the 'data' module
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Data & Constants
import data.constants as c
from data import queries
from data.map import load_map, save_map
from data.platform import run_background

# Core Game State & Global UI Elements
from gameState import GameState
from map_logic.turn_processing import turn_manager
from ui import event_handler

# Game Logic & Rendering Submodules
import ui_elements
from ui_elements import Button, Slider
from ui import diplomatic_popups, spectator_menus, editor_menus
from map_logic.camera.camera_handler import MapCamera
from map_logic.camera import camera_handler
from map_logic.diplomacy import diplomacy_logic, player_diplomacy_actions, volunteers
from map_logic.random_map import random_map_generator
from map_logic.rendering import map_renderer, refresh_map
from map_logic.rendering.font_manager import fonts
from map_logic.rendering.country_names import update_country_centers as calc_country_centers
from map_logic.setup import player_setup
from screens.editor_screens import scripted_events_editor

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
# Row 14, not 13: the Slider draws its text label at rect.y - 25 (ui_elements),
# which at row 13 lands inside the box of a row-12 button. The rects never
# collide, so test_editor_menu_layout would not have caught it.
CAMERA_TILT_SLIDER_ROW = 14
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
# Ten foreign-diplomacy rows fit above the province-action buttons at this
# spacing (the tenth is Send/Recall Volunteers).
ACTION_BTN_STEP_Y = 30

PROVINCE_BTN_X = 280
BTN_ORDERS_Y = 603
BTN_PRODUCTION_Y = 543

# --- Multiplayer host strip ---
MP_HOST_BTN_Y = 15
MP_HOST_MANAGE_X = 380
MP_HOST_EXPORT_X = 600
MP_HOST_KEYS_X = 820


def render_buttons(map_screen):
    """Initializes and registers all map screen buttons uniformly."""
    icons = ui_elements.UI_ICONS
    map_screen.elements = []

    # ==================================================================== #
    #                        MAP VIEW TOGGLES                              #
    # ==================================================================== #
    map_screen.btn_refresh_all = Button(REFRESH_BTN_X, c.TOP_BAR_UI_CENTER_Y, "small", "blue", "Refresh Maps", map_screen.refresh_all_maps, font_preset="normal")
    map_screen.btn_global_econ_overview = Button(GLOBAL_ECON_BTN_X, c.TOP_BAR_UI_CENTER_Y, "small", "pink", "Global Economy", lambda: editor_menus.open_editor_economy(map_screen), font_preset="normal")

    map_screen.btn_view_terrain = Button(VIEW_BTN_START_X, VIEW_BTN_ROW2_Y, "small_square", "green", "Terrain", lambda: map_screen.set_map_layer("TERRAIN"), image=icons.get("terrain"), show_text=False)
    map_screen.btn_view_political = Button(VIEW_BTN_START_X + VIEW_BTN_STEP_X, VIEW_BTN_ROW2_Y, "small_square", "green", "Political", lambda: map_screen.set_map_layer("POLITICAL"), image=icons.get("political"), show_text=False)
    map_screen.btn_view_relations = Button(VIEW_BTN_START_X + VIEW_BTN_STEP_X * 2, VIEW_BTN_ROW2_Y, "small_square", "green", "Relations", lambda: map_screen.set_map_layer("RELATIONS"), image=icons.get("relations"), show_text=False)
    map_screen.btn_view_cores = Button(VIEW_BTN_START_X + VIEW_BTN_STEP_X * 3, VIEW_BTN_ROW2_Y, "small_square", "green", "Cores", lambda: map_screen.set_map_layer("CORES"), image=icons.get("core"), show_text=False)
    map_screen.btn_view_factions = Button(VIEW_BTN_START_X + VIEW_BTN_STEP_X * 4, VIEW_BTN_ROW2_Y, "small_square", "green", "Factions", lambda: map_screen.set_map_layer("FACTIONS"), image=icons.get("faction"), show_text=False)

    # In Preemptive navigation, clicking one of these while a tile is already
    # selected jumps straight to that mode's screen for it (Orders for Units,
    # Production for Economy) instead of just flipping the map overlay.
    # In Classic navigation it only ever flips the overlay. See
    # ui.event_handler.navigate_view_mode / data.constants.MAP_NAVIGATION_MODE.
    map_screen.btn_view_resources = Button(VIEW_BTN_START_X, VIEW_BTN_ROW1_Y, "small_square", "red", "Resources", lambda: event_handler.navigate_view_mode(map_screen, "RESOURCES"), image=icons.get("resource"), show_text=False)
    map_screen.btn_view_blank = Button(VIEW_BTN_START_X + VIEW_BTN_STEP_X, VIEW_BTN_ROW1_Y, "small_square", "red", "Blank", lambda: event_handler.navigate_view_mode(map_screen, "BLANK"), image=icons.get("blank"), show_text=False)
    map_screen.btn_view_units = Button(VIEW_BTN_START_X + VIEW_BTN_STEP_X * 2, VIEW_BTN_ROW1_Y, "small_square", "red", "Units", lambda: event_handler.navigate_view_mode(map_screen, "UNITS"), image=icons.get("unit"), show_text=False)
    map_screen.btn_view_economy = Button(VIEW_BTN_START_X + VIEW_BTN_STEP_X * 3, VIEW_BTN_ROW1_Y, "small_square", "red", "Economy", lambda: event_handler.navigate_view_mode(map_screen, "ECONOMY"), image=icons.get("industry"), show_text=False)
    map_screen.btn_toggle_names = Button(VIEW_BTN_START_X + VIEW_BTN_STEP_X * 4, VIEW_BTN_ROW1_Y, "small_square", "blue", "Names", map_screen.toggle_country_names, image=icons.get("names"), show_text=False)

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
    # Row 11, not 9: btn_gp_claims is row 9 and is also visible in the editor, so
    # this button spent its whole existence hidden underneath it, pixel for pixel,
    # with a click there firing both callbacks. test_editor_menu_layout keeps the
    # rows distinct now rather than trusting the next number picked by hand.
    map_screen.btn_ed_personality = Button(LEFT_UI_BAR_X, start_y_val + LEFT_UI_BAR_STEP_Y * 11, "left_ui_button", "purple", "AI Personality", lambda: editor_menus.open_personality_editor(map_screen), font_preset="normal")
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

                    summary = load_move_files(map_screen, [file_path], keys_dict)
                    if not summary["loaded"]:
                        map_screen.show_feedback("Move import rejected: wrong key, tournament, or turn.")
                        return
                    map_screen.show_feedback(f"Move imported from {os.path.basename(file_path)}")

                    map_screen.refresh_map_layers(
                        "political", "factions", "relations", "cores", "faction_territories")
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
            from ui.screen_runner import _run_pygame_sub_screen
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

    def research_callback():
        """Three different things, because R&D means three different things.

        The map editor authors what a nation *starts* with, so it keeps the bulk
        checkbox list. A spectator wants to watch and steer a live programme, so
        they pick a nation and get the real tech tree. A player gets their own.
        """
        if map_screen.is_editor:
            editor_menus.open_map_research_editor(map_screen)
        elif map_screen.player_country == "Spectator":
            editor_menus.spec_select_research_country(map_screen)
        else:
            map_screen.viewing_research_country = ""
            map_screen.change_state("RESEARCH")

    def politics_callback():
        """Steering your own axis, or authoring everyone's starting position.

        Same split as research_callback: the map editor sets what a nation
        *starts* at, a player picks which way their own country is heading.
        """
        if map_screen.is_editor or map_screen.player_country == "Spectator":
            editor_menus.open_politics_editor(map_screen)
        else:
            sub_screen_opener("screens.map_related_screens.politics_screen",
                              "Politics_Screen")()

    econ_callback = editor_or(editor_menus.open_starting_economy_editor, "ECONOMY")
    msgs_callback = editor_or(editor_menus.open_spectator_messages, "MESSAGES")

    # The left-hand bar: one column, one size, one color, one row per entry.
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
        # Row 12 is the only row free in both modes -- the editor fills 1-11 too,
        # just with a different set.
        ("btn_gp_politics", 12, "Politics", "tophat", politics_callback),
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

    # Domestic Set. In Preemptive navigation both route through
    # navigate_view_mode rather than jumping straight to their screen, so
    # clicking them also swaps the bottom-left view-mode row over to match
    # (Units for either half of this shared slot, Economy for Production)
    # instead of leaving it on whatever it last was. In Classic navigation they
    # jump straight there unconditionally instead. See
    # ui.event_handler.go_to_orders_screen/go_to_production_screen.
    map_screen.btn_go_orders = Button(PROVINCE_BTN_X, BTN_ORDERS_Y, "orders", "blue", "Give Orders", lambda: event_handler.go_to_orders_screen(map_screen), image=icons.get("paper"), show_text=False)
    # Retained as a compatibility object for old callers/layout code. It is
    # never exposed: a fighting tile enters Orders first, where the lane
    # manager can be opened after the player has access to all order controls.
    map_screen.btn_go_battle = Button(PROVINCE_BTN_X, BTN_ORDERS_Y, "orders", "red", "Manage Battle", lambda: event_handler.go_to_battle_screen(map_screen), image=icons.get("battle"), show_text=False)
    map_screen.btn_go_production = Button(PROVINCE_BTN_X, BTN_PRODUCTION_Y, "orders", "orange", "Production", lambda: event_handler.go_to_production_screen(map_screen), image=icons.get("industry"), show_text=False)

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
        ("btn_volunteers", 9, "purple", "Send Volunteers", player_diplomacy_actions.handle_send_volunteers),
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
        map_screen.refresh_map_layers("fog")

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
        map_screen.btn_ed_unit, map_screen.btn_ed_refresh, map_screen.btn_ed_edited, map_screen.btn_ed_date, map_screen.btn_ed_diplo, map_screen.btn_ed_personality, map_screen.btn_ed_scripts,
        map_screen.btn_next_turn, map_screen.btn_import_turn, map_screen.btn_skip_ai, map_screen.btn_multi_turn, map_screen.btn_declare_indep, map_screen.btn_gp_edit, map_screen.btn_gp_econ, map_screen.btn_gp_rd, map_screen.btn_gp_msgs,
        map_screen.btn_gp_save, map_screen.btn_gp_settings, map_screen.btn_gp_music, map_screen.btn_gp_faction, map_screen.btn_gp_claims, map_screen.btn_gp_puppets, map_screen.btn_gp_automation, map_screen.btn_gp_politics, map_screen.btn_go_orders, map_screen.btn_go_battle, map_screen.btn_go_production,
        map_screen.btn_declare_war, map_screen.btn_join_wars, map_screen.btn_call_to_arms, map_screen.btn_fac_invite,
        map_screen.btn_fac_join_req, map_screen.btn_fac_kick, map_screen.btn_fac_create,
        map_screen.btn_volunteers,
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

def set_orders_or_battle(map_screen, set_btn, has_player_units):
    """Shows the Orders entry point for both quiet and contested tiles.

    Battle management lives inside Orders now, alongside Disband/Repair/
    Bombard and retreat orders, so selecting a contested tile never skips the
    order controls.

    Neither needs units of your own to open, and Orders needs no units at all
    -- an empty tile just opens it blank. Somebody else's battle is worth
    reading -- it is how you find out whether the front you are about to walk
    into is already collapsing -- and both screens refuse to edit units you do
    not command, so viewing costs nothing. What gates them is fog of war.
    """
    province = map_screen.selected_province
    visible = queries.is_province_visible(map_screen, province["id"])

    orders_label = "Give Orders" if has_player_units else "View Units"
    set_btn(map_screen.btn_go_orders, visible, visible,
            orders_label, "blue" if has_player_units else "grey")
    # Kept as a compatibility object for saved layouts and callers, but no
    # longer exposed: the Orders screen owns the Battle handoff.
    set_btn(map_screen.btn_go_battle, False, False, "Battle", "red")


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

    # Shorthand for the per-frame visible/enabled/text/color updates below
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
            map_screen.btn_ed_date, map_screen.btn_ed_edited, map_screen.btn_ed_diplo, map_screen.btn_ed_personality, map_screen.btn_ed_scripts,
            map_screen.btn_gp_settings, map_screen.btn_gp_music, map_screen.btn_gp_politics,
            map_screen.slider_camera_tilt
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
            map_screen.btn_gp_puppets, map_screen.btn_gp_automation, map_screen.btn_gp_politics,
            map_screen.slider_camera_tilt
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
            set_orders_or_battle(map_screen, set_btn, False)

        # --- PLAYER ---
        else:
            has_player_units = queries.has_units_in_province(map_screen.player_country, map_screen.selected_province)
            is_land = not queries.is_water_province(map_screen.selected_province)
            is_tactical = map_screen.tactical_mode

            if owner == map_screen.player_country:
                set_orders_or_battle(map_screen, set_btn, has_player_units)

                if is_tactical:
                    set_btn(map_screen.btn_go_production, True, False, "Tactical: Disabled", "grey")
                else:
                    set_btn(map_screen.btn_go_production, True, is_land, "Production", "orange")

            elif queries.is_playable(owner, map_screen.nation_data):
                set_orders_or_battle(map_screen, set_btn, has_player_units)

                if is_tactical:
                    # Disable all foreign interactions
                    set_btn(map_screen.btn_declare_war, True, False, "Tactical: Disabled", "grey")
                    set_btn(map_screen.btn_join_wars, True, False, "Tactical: Disabled", "grey")
                    set_btn(map_screen.btn_call_to_arms, True, False, "Tactical: Disabled", "grey")
                    set_btn(map_screen.btn_volunteers, True, False, "Tactical: Disabled", "grey")
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

                # A destroyed volunteer has no off-map record to clean up, so
                # reconcile before deciding whether this is Send or Recall.
                volunteers.reconcile_deployed_missions(
                    map_screen, map_screen.player_country)
                volunteer_state = volunteers.mission_state(map_screen.nation_data, map_screen.player_country, owner)
                if volunteer_state == volunteers.AWAITING:
                    if pending_action == volunteers.ACTION and pending_turns == 0:
                        set_btn(map_screen.btn_volunteers, True, True, "Undo Send Volunteers", "purple")
                        map_screen.btn_volunteers.callback = lambda: player_diplomacy_actions.handle_withdraw_volunteer_offer(map_screen)
                    else:
                        set_btn(map_screen.btn_volunteers, True, False, "Waiting for Answer", "grey")
                elif volunteer_state in (volunteers.OUTBOUND, volunteers.DEPLOYED):
                    turns_left = map_screen.nation_data[map_screen.player_country]["volunteer_missions"][owner].get("turns_left")
                    if pending_action == volunteers.RECALL_ACTION and pending_turns == 0:
                        text = "Undo Recall Volunteers"
                    else:
                        text = "Recall Volunteers" if turns_left is None else f"Recall Volunteers ({turns_left}t)"
                    set_btn(map_screen.btn_volunteers, True, True, text, "purple")
                    map_screen.btn_volunteers.callback = lambda: player_diplomacy_actions.handle_recall_volunteers(map_screen)
                elif volunteer_state == volunteers.RETURNING:
                    turns_left = map_screen.nation_data[map_screen.player_country]["volunteer_missions"][owner].get("turns_left", 0)
                    set_btn(map_screen.btn_volunteers, True, False, f"Volunteers Returning ({turns_left}t)", "grey")
                else:
                    legal, _reason = volunteers.is_eligible(map_screen.player_country, owner, map_screen.nation_data)
                    enabled = legal and volunteers.remaining_capacity(map_screen, map_screen.player_country) > 0
                    set_btn(map_screen.btn_volunteers, True, enabled, "Send Volunteers", "purple")
                    map_screen.btn_volunteers.callback = lambda: player_diplomacy_actions.handle_send_volunteers(map_screen)

                factions_disabled = getattr(c, 'DISABLE_FACTIONS', False)

                # A puppet's alignment is its master's, both ways round: it may
                # not be invited in, and may not ask to join. Greyed out here so
                # the option never appears, rather than being refused later.
                they_are_free = queries.can_choose_own_faction(owner, map_screen.nation_data)
                i_am_free = queries.can_choose_own_faction(map_screen.player_country, map_screen.nation_data)

                can_invite = bool(not factions_disabled and my_faction and not target_faction
                                  and not at_war and they_are_free)
                inv_text = get_status_text("INVITE") if pending_action == "FACTION_INVITE" else "Invite to Faction"
                set_btn(map_screen.btn_fac_invite, True, can_invite or pending_action == "FACTION_INVITE", inv_text, "green")

                can_req_join = bool(not factions_disabled and not my_faction and target_faction
                                    and not at_war and i_am_free)
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
                    map_screen.btn_volunteers.visible = False

            else:
                set_orders_or_battle(map_screen, set_btn, has_player_units)


class Map(GameState):
    def __init__(self, load_path=None, is_scenario=False, is_random=False, force_editor=False, random_settings=None, map_settings=None, num_players=1, history_turn=None, skip_initial_income=False):
        super().__init__()

        self.history_turn = history_turn
        self.num_players = num_players
        self.active_players = [] # Usually empty on boot unless loaded from save
        self.current_player_index = 0
        self.show_player_ready_screen = False

       # --- UI DISPLAY OVERRIDES ---
        self.hide_raised_rect = False
        self.hide_top_info = False
        # Separate from hide_top_info so map-layered panels can suppress only
        # the large top-left flag without also removing the country/date text.
        self.hide_flag = False
        self.hide_tooltip = False
        self.hide_resource_hud = False
        self.hide_minimap = False
        self.centers_need_update = False
        self.error_copied = False
        self.random_settings = None

        # --- BACKGROUND PROCESSING FLAGS ---
        self.ai_is_thinking = False
        self.ai_processing_complete = False
        self.is_refreshing = False
        self.is_saving = False
        self.save_progress_completed = 0
        self.save_progress_total = 5
        self.thread_error = None
        self.force_skip_llm = False

        # --- TACTICAL MODE STATE ---
        self.tactical_mode = False
        self.player_unit = None
        self.unit_economy = {**{res: 0 for res in c.ECON_RESOURCE_KEYS}, "fuel_inc": 0}

        # --- MULTI-TURN FLAGS ---
        self.multi_turn_processing_complete = False
        self.multi_turns_total = 0
        self.multi_turns_completed = 0
        self.multi_turn_abort_requested = False

        # --- NEW PROGRESS BAR TRACKERS ---
        self.loading_status_text = "Waiting..."
        self.proactive_tasks_total = 0
        self.proactive_tasks_completed = 0
        self.proactive_llm_tasks_total = 0
        self.proactive_llm_tasks_completed = 0
        self.proactive_llm_tasks = []
        # Each AI nation's menu of legal moves, held between the proactive
        # pass that builds it and the director pass that picks from it.
        self.proactive_choices = []
        self.responsive_tasks_total = 0
        self.responsive_tasks_completed = 0
        self.summits_total = 0
        self.summits_completed = 0
        self.diplomatic_popups = []

        # Per-turn AI map snapshot (map_logic/ai/ai_world.py). Only ever set
        # while the AI passes of prepare_turn are running; None the rest of the
        # time, which is what stops anything reading last turn's answers.
        self.ai_world = None

        # Initialize variables previously hidden by getattr
        self.fog_map = None
        self.visible_provinces = None
        self.mail_draft_text = ""
        self.mail_input_active = False

        # --- NEW REFRESH TRACKERS ---
        self.refresh_tasks_total = 0
        self.refresh_tasks_completed = 0
        self.loading_spinner_angle = 0

        self.brush_building = "None"
        self.brush_unit = "None"
        self.editor_mode = "NATION"

        self.show_country_names = True

        # --- 1. Basic State Variables ---
        self.camera_tilt_slider_val = 0.0 # Starts fully top-down
        self.selection_mode = is_scenario
        self.pending_selection = None
        self.player_country = "None"

        self.secondary_modes = ["UNITS", "ECONOMY", "BLANK"]
        self.sec_idx = 0
        self.secondary_mode = self.secondary_modes[2]

        self.base_layer = "POLITICAL"
        self.load_path = load_path

        self.is_editor = force_editor or (self.load_path is None and not is_scenario)
        if self.is_editor:
            self.player_country = "Editor"
            self.selection_mode = False

        self.painting_active = False
        self.brush_nation = "Unclaimed"
        self.viewing_ai_moves = False
        self.skip_ai_view = False

        # --- 2. Data Loading ---
        if is_random and random_settings:
            self.random_settings = random_settings
            load_map.load_map_assets(self, random_settings["map_path"])
            self.time_manager.year = random_settings["year"]
        else:
            load_map.load_map_assets(self, load_path)

        # Re-mirror the camera's drag button onto data.constants, where the
        # camera reads it. Deliberately only this one: a controller that is
        # missing an attribute would otherwise hand apply_runtime_settings a
        # schema default and quietly reset the player's save folder.
        if hasattr(self, 'controller') and hasattr(self.controller, 'drag_mouse_toggle'):
            c.apply_runtime_settings({"drag_mouse_toggle": self.controller.drag_mouse_toggle})

        # Capture settings passed from New_Game
        if map_settings:
            self.scenario_settings = map_settings
        elif not hasattr(self, 'scenario_settings'):
            self.scenario_settings = {
                "fog_of_war": c.DEFAULT_FOG_OF_WAR,
                "fog_of_war_strength": c.DEFAULT_FOG_OF_WAR_STRENGTH,
                "casus_belli_required": c.DEFAULT_CASUS_BELLI
            }

        # --- 3. Visuals & UI Setup ---
        self.bg_color = (20, 20, 20)
        self.font = fonts.get("normal")
        self.small_font = fonts.get("tiny")

        self.top_ui_height = c.TOP_UI_HEIGHT
        self.bot_ui_height = c.BOT_UI_HEIGHT
        self.total_ui_h = c.TOTAL_UI_HEIGHT

        self.top_bar_rect = pygame.Rect(0, 0, c.SCREEN_WIDTH, self.top_ui_height)
        self.bot_bar_rect = pygame.Rect(0, c.SCREEN_HEIGHT - self.bot_ui_height, c.SCREEN_WIDTH, self.bot_ui_height)
        self.raised_rect = pygame.Rect(0, 0, c.UI_LEFT_OFFSET, c.SCREEN_HEIGHT)
        self.ui_background_rect = pygame.Rect(0, c.SCREEN_HEIGHT - self.total_ui_h, 270, self.total_ui_h)

        self.map_w, self.map_h = self.id_map.get_size()
        self.min_zoom = (c.SCREEN_HEIGHT - self.total_ui_h) / self.map_h
        self.camera = MapCamera(self.min_zoom)

        self.active_map = self.political_map if self.base_layer == "POLITICAL" else self.terrain_map
        self.map_mode = self.base_layer

        self.selected_province = self.hovered_province = self.last_hovered_id = None
        self.hover_glow_surf = self.hover_glow_rect = None
        self.feedback_text = ""
        self.feedback_timer = 0

        self.show_exit_confirmation = False
        self.confirm_box_rect = pygame.Rect(0, 0, 400, 200)

        self.relations_map = self.id_map.copy()
        self.factions_map = self.id_map.copy()
        self.faction_territories_map = self.id_map.copy()

        # --- 3. RUN THE RANDOMIZER ---
        if is_random and random_settings:
            random_map_generator.randomize_all_provinces(self, random_settings)

        # --- 4. REFRESH MAPS ---
        self.refresh_map_layers(*self.ALL_MAP_LAYERS)

        render_buttons(self)

        for country_name, data in self.nation_data.items():
            data.setdefault("at_war_with", [])
            data.setdefault("allied_with", [])
            data.setdefault("pending_diplomacy", {})
            responses = data.setdefault("diplo_responses", {})

            # Older saves parked answers in the outgoing-proposal slot, where they
            # overwrote whatever offer was already travelling to that nation. Move
            # them across so they resolve on the response channel instead.
            for other, info in list(data["pending_diplomacy"].items()):
                act = info.get("action", "") if isinstance(info, dict) else info
                if not isinstance(act, str):
                    continue
                for prefix, verdict in (("ACCEPT_", "ACCEPT"), ("REJECT_", "REJECT")):
                    if act.startswith(prefix):
                        responses[other] = {
                            "verdict": verdict,
                            "action": act[len(prefix):],
                            "message": info.get("message", "") if isinstance(info, dict) else "",
                            "parameters": info.get("parameters") if isinstance(info, dict) else None,
                        }
                        del data["pending_diplomacy"][other]
                        break

        self.update_country_centers()

        # --- 5. INITIALIZE INCOME ---
        # Provide 1 turn of simulated income so nations don't spawn with 0 resources
        if self.time_manager.total_turns == 0 and not self.is_editor and not skip_initial_income:
            from map_logic.turn_processing import economy_processor
            economy_processor.process_economy(self)

    def draw_clean_map_background(self, surface):
        """Temporarily hides UI elements and province selection to draw a clean map background."""
        temp_prov = self.selected_province
        self.selected_province = None

        # Save previous states to be completely safe
        prev_raised = self.hide_raised_rect
        prev_tooltip = self.hide_tooltip
        prev_hud = self.hide_resource_hud
        prev_mini = self.hide_minimap

        self.hide_raised_rect = True
        self.hide_tooltip = True
        self.hide_resource_hud = True
        self.hide_minimap = True

        self.additional_draw(surface)

        # Restore original states
        self.hide_raised_rect = prev_raised
        self.hide_tooltip = prev_tooltip
        self.hide_resource_hud = prev_hud
        self.hide_minimap = prev_mini
        self.selected_province = temp_prov

    # --- Properties ---
    @property
    def player_manpower(self):
        if self.tactical_mode: return self.unit_economy.get("manpower", 0)
        return self.nation_data.get(self.player_country, {}).get("manpower", 0)
    @player_manpower.setter
    def player_manpower(self, value):
        if self.tactical_mode: self.unit_economy["manpower"] = value
        elif self.player_country in self.nation_data: self.nation_data[self.player_country]["manpower"] = value

    @property
    def player_materials(self):
        if self.tactical_mode: return self.unit_economy.get("materials", 0)
        return self.nation_data.get(self.player_country, {}).get("materials", 0)

    @property
    def player_fuel(self):
        if self.tactical_mode and self.player_unit:
            base_fuel = self.unit_economy.get("fuel", 0)
            u = self.player_unit
            order = u.get("order")
            path = order.get("path", []) if isinstance(order, dict) else []
            if path:
                fuel_inc = self.unit_economy.get("fuel_inc", 0)
                cost_per_tile = queries.get_tactical_fuel_cost_per_tile(u, fuel_inc)
                calc_speed = queries.get_tactical_speed(u)
                immediate_steps = min(len(path), calc_speed)
                return max(0, base_fuel - (cost_per_tile * immediate_steps))
            return base_fuel
        return self.nation_data.get(self.player_country, {}).get("fuel", 0)

    def set_camera_tilt(self, val):
        """Callback for the manual camera tilt slider."""
        self.camera_tilt_slider_val = val

        # Grab the old tilt before we update it to calculate the difference
        old_tilt = self.camera.manual_tilt_factor
        new_tilt = 1.0 - (val * (1.0 - c.MAX_Y_TILT_FACTOR))

        # Failsafe to prevent division by zero
        if old_tilt == 0: old_tilt = 0.001
        if new_tilt == 0: new_tilt = 0.001

        # --- NEW: Anchor the compression to the center of the camera ---
        # Find the pixel center of the playable view area (excluding UI bars)
        view_h = c.SCREEN_HEIGHT - self.total_ui_h
        screen_center_y = view_h / 2.0

        # Shift the camera Y position to perfectly compensate for the scale change,
        # keeping the exact same world coordinate centered on your screen.
        self.camera.pos.y += (screen_center_y / self.camera.zoom) * ((1.0 / old_tilt) - (1.0 / new_tilt))

        # Sync the target position so the smooth-pan lerp doesn't aggressively snap it back
        self.camera.target_pos.y = self.camera.pos.y

        # Apply the new tilt
        self.camera.manual_tilt_factor = new_tilt

        # Flag the label centers for an update because tilting the world compresses
        # the visual space, shifting where country names need to physically render.
        self.centers_need_update = True

    # --- Toggles & View Modes ---
    def toggle_country_names(self):
        self.show_country_names = not self.show_country_names
        self.show_feedback(f"Country Names: {'ON' if self.show_country_names else 'OFF'}")

    def toggle_skip_ai(self):
        self.skip_ai_view = not self.skip_ai_view
        self.show_feedback(f"Skip AI View: {'ON' if self.skip_ai_view else 'OFF'}")
        update_button_states(self)

    def set_view_mode(self, mode):
        self.secondary_mode = mode
        self.show_feedback(f"View: {mode}")

    def cycle_secondary_mode(self):
        self.sec_idx = (self.sec_idx + 1) % len(self.secondary_modes)
        self.secondary_mode = self.secondary_modes[self.sec_idx]
        self.show_feedback(f"View Mode: {self.secondary_mode}")

    def trigger_multi_turn(self):
        from ui import confirm_dialog

        def on_turns(turns):
            if turns:
                self.multi_turns_total = turns
                self.multi_turns_completed = 0
                self.multi_turn_abort_requested = False
                self.ai_is_thinking = True
                self.loading_status_text = f"Skipping {turns} Turns..."
                run_background(self._run_multi_turn_thread, turns)

        confirm_dialog.ask_integer("Process Multiple Turns", "How many turns to process at once?",
                                   on_turns, minvalue=1, maxvalue=5000)

    async def _run_multi_turn_thread(self, turns):
        from map_logic.turn_processing import turn_processor
        from map_logic.ai import ai_handler
        import asyncio
        import traceback

        try:
            ai_handler.FORCE_SKIP = True
            self.force_skip_llm = True
            self.viewing_ai_moves = True # Prevents PyGame surface edits from background thread

            for i in range(turns):
                self.multi_turns_completed = i + 1
                self.loading_status_text = f"Processing Turn {i+1}/{turns}..."

                # Mock the UI prep variables to prevent crashes
                self.proactive_tasks_total = 1
                self.proactive_tasks_completed = 1
                self.proactive_llm_tasks_total = 0
                self.proactive_llm_tasks_completed = 0
                self.proactive_llm_tasks = []
                self.responsive_tasks_total = 0
                self.responsive_tasks_completed = 0
                self.summits_total = 0
                self.summits_completed = 0

                await turn_processor.prepare_turn(self)
                await turn_processor.resolve_turn_logic(self)
                # Extra yield so the multi-turn progress bar (map_renderer.py)
                # gets at least one render between turns even if a turn's own
                # internal phases all happened to resolve without yielding.
                await asyncio.sleep(0)

                # --- ABORT CHECK ---
                # Can't interrupt a turn mid-computation, so the turn that was
                # running when the user clicked Abort finishes normally, and
                # simply becomes the last one processed.
                if self.multi_turn_abort_requested:
                    self.multi_turns_total = self.multi_turns_completed
                    break

        except Exception as e:
            self.thread_error = traceback.format_exc()
            print(f"MULTI-TURN CRASH CAUGHT:\n{self.thread_error}")
        finally:
            ai_handler.FORCE_SKIP = False
            self.force_skip_llm = False
            self.multi_turn_abort_requested = False
            self.multi_turn_processing_complete = True

    def update_country_centers(self):
        """Calculates new label centers and text blobs for the map."""
        calc_country_centers(self)

    def set_map_layer(self, layer_name):
        """Unified map layer setter."""
        self.base_layer = layer_name
        self.map_mode = layer_name
        layer_map = {
            "TERRAIN": self.terrain_map,
            "POLITICAL": self.political_map,
            "RELATIONS": self.relations_map,
            "FACTIONS": self.factions_map,
            "CORES": self.cores_map,
            "FACTION_TERRITORIES": self.faction_territories_map
        }
        self.active_map = layer_map.get(layer_name, self.political_map)

        # --- ADDED: Auto-refresh the text blobs when changing map views ---
        self.update_country_centers()

        self.show_feedback(f"Mode: {layer_name.title()}")

    # --- Screen Transitions ---
    def change_state(self, next_state):
        self.next_state, self.done = next_state, True

    def change_state_if_owned(self, next_state, requires_land=False):
        """Only transitions if the player owns the selected province (and optionally if it's land)."""
        if self.selected_province:
            owner = self.selected_province.get("owner")
            # Allow the spectator to bypass ownership checks
            if owner == self.player_country or self.player_country == "Spectator":
                if requires_land and queries.is_water_province(self.selected_province):
                    return
                self.change_state(next_state)

    def deselect_province(self):
        if self.selected_province:
            owner = self.selected_province.get("owner")
            is_foreign = queries.is_foreign_playable(owner, self.player_country, self.nation_data)
            if is_foreign:
                draft = self.mail_draft_text.strip()
                if draft:
                    diplomacy_logic.queue_text_message(self.nation_data, self.player_country, owner, draft)
                else:
                    diplomacy_logic.cancel_text_message(self.nation_data, self.player_country, owner)
                self.mail_input_active = False

        self.selected_province = self.hovered_province = self.hover_glow_surf = self.last_hovered_id = None
        self.show_feedback("Map Unlocked")

    def save_map_data(self):
        if self.is_saving:
            return # Already saving, ignore duplicate clicks
        self.is_saving = True
        self.loading_status_text = "Saving Game..."
        self.save_progress_completed = 0
        self.save_progress_total = 5

        # Force the loading screen to actually appear before run_background either
        # spawns a thread (desktop) or, on web, blocks the frame running synchronously.
        self.draw(pygame.display.get_surface())
        pygame.display.flip()

        run_background(save_map.save_map_data, self)

    MAP_LAYER_REFRESHERS = {
        "political": refresh_map.refresh_political_map,
        "relations": refresh_map.refresh_relations_map,
        "factions": refresh_map.refresh_factions_map,
        "cores": refresh_map.refresh_cores_map,
        "faction_territories": refresh_map.refresh_faction_territories_map,
        "fog": refresh_map.refresh_fog_map,
    }
    ALL_MAP_LAYERS = tuple(MAP_LAYER_REFRESHERS)

    def refresh_map_layers(self, *layers):
        """Rebuilds named visual layers in the caller-supplied order.

        Layer names live beside the Map UI that owns their cached surfaces.
        The renderer remains responsible for the actual image construction;
        callers no longer need six nearly identical forwarding methods.
        """
        for layer in layers:
            try:
                self.MAP_LAYER_REFRESHERS[layer](self)
            except KeyError as error:
                raise ValueError(f"Unknown map layer: {layer!r}") from error

    def refresh_diplomacy_maps(self):
        """Unified helper to quickly refresh only diplomacy-related overlays."""
        self.refresh_map_layers("relations", "factions", "faction_territories")

    def refresh_all_maps(self):
        """Unified method to refresh all visual map layers and text at once."""
        # do note that for larger maps this might take over 1000 ms to complete, this is NOT instant by any means
        # TODO: maybe add the ability to ignore certain refresh actions (example: refresh all except for faction territories)
        self.refresh_map_layers(*self.ALL_MAP_LAYERS)
        self.update_country_centers()
        self.show_feedback("Maps refreshed!")

    def auto_assign_cores(self):
        from ui import confirm_dialog

        def on_confirm(confirm):
            if confirm:
                for province in self.map_data.values():
                    owner = province.get("owner", "Unclaimed")
                    province["cores"] = [owner] if owner not in c.OWNERLESS_OWNERS else []
                self.show_feedback("Auto-assigned all cores!")
                if self.map_mode == "CORES":
                    self.refresh_map_layers("cores")
            else:
                self.show_feedback("Auto-core cancelled.")

        # Ask for confirmation first before doing anything destructive
        confirm_dialog.ask_yes_no(
            "Confirm Auto-Core",
            "Are you sure you want to auto-assign all cores?\nThis will overwrite existing core data for every province on the map based on current ownership.",
            on_confirm
        )

    def exit_to_menu(self):
        self.show_exit_confirmation = True
        for el in self.elements: el.visible = False

    def cancel_exit(self):
        self.show_exit_confirmation = False
        self.show_feedback("Exit cancelled")

    def confirm_exit(self):
        diplomatic_popups.clear_popups(self)
        self.change_state("MENU")

    def show_feedback(self, text):
        self.feedback_text, self.feedback_timer = text, pygame.time.get_ticks()
        print(f"[UI EVENT] {text}")

    def additional_events(self, event):
        # Intercept inputs if the game has crashed
        if self.thread_error:
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                btn_rect = pygame.Rect(c.SCREEN_WIDTH - 240, c.SCREEN_HEIGHT - 80, 220, 60)
                if btn_rect.collidepoint(event.pos):
                    if queries.copy_to_clipboard(self.thread_error):
                        self.error_copied = True
            return # Block all other map events!

        event_handler.handle_map_events(self, event)

    def sync_units_to_data(self):
        unit_library = queries.get_unit_library()
        building_library = queries.get_building_library()
        if not unit_library:
            self.show_feedback("Error: unit library not found!")
            return

        updated_count = 0
        removed_count = 0

        for province in self.map_data.values():
            # 1. Clean Units
            units_to_keep = []
            for unit in province.get("units", []):
                u_type = unit.get("type", "")
                base_type = unit.get("original_type", u_type)

                # Handle dynamic transport names
                if base_type.startswith("Convoy (") or base_type.startswith("Truck ("):
                    import re
                    match = re.search(r'\((.*?)\)', base_type)
                    if match:
                        base_type = match.group(1).strip()

                # Check if the unit is still valid
                if base_type in unit_library or base_type in ["Convoy", "Truck"]:
                    if u_type in unit_library:
                        stats = unit_library[u_type]
                        unit.update({
                            "max_health": stats.get("health", c.DEFAULT_UNIT_HP),
                            "attack": stats.get("attack", c.DEFAULT_UNIT_ATK),
                            "defense": stats.get("defense", c.DEFAULT_UNIT_DEF),
                            "speed": stats.get("speed", c.DEFAULT_UNIT_SPD)
                        })
                        # Cap health to new max
                        unit["health"] = min(unit.get("health", stats.get("health", c.DEFAULT_UNIT_HP)), unit["max_health"])
                        updated_count += 1
                    units_to_keep.append(unit)
                else:
                    removed_count += 1 # It's obsolete, drop it!

            province["units"] = units_to_keep

            # 2. Clean Buildings
            if "buildings" in province:
                original_b_count = len(province["buildings"])
                province["buildings"] = [b for b in province["buildings"] if b in building_library]
                removed_count += (original_b_count - len(province["buildings"]))

            # 3. Clean Queues
            for queue_key in ["building_queue", "unit_queue"]:
                if queue_key in province:
                    valid_queue = []
                    for q in province[queue_key]:
                        is_valid = True
                        if q.get("order_type") == "BUILDING" and q.get("item_name") not in building_library:
                            is_valid = False
                        elif "unit_type" in q and q.get("unit_type") not in unit_library:
                            is_valid = False

                        if is_valid:
                            valid_queue.append(q)
                        else:
                            removed_count += 1
                    province[queue_key] = valid_queue

            # Wipe legacy data if it exists
            if "deployment_queue" in province:
                del province["deployment_queue"]

        print(f"[MAP SCRUBBER] {updated_count} entities updated, {removed_count} obsolete entities vaporized.")

    def handle_back_key(self):
        if self.selected_province:
            self.deselect_province()

    def handle_orders_key(self):
        """Q. Sets the view mode to Units, same as clicking that button; also
        jumps straight into Orders or Battle for the selected tile when the
        Keybinds screen's "change screen with this keybind" toggle is on for
        this key -- independent of Classic/Preemptive map navigation, see
        ui.event_handler.handle_view_mode_keybind.

        Not gated on owning anything here: both screens read a province you have
        no units in, and refuse to edit units you do not command.
        """
        if self.selection_mode:
            return
        event_handler.handle_view_mode_keybind(self, "UNITS", "ORDERS")

    def handle_economy_key(self):
        """W. Sets the view mode to Economy, same as clicking that button;
        also jumps straight into Production for the selected tile when the
        Keybinds screen's "change screen with this keybind" toggle is on for
        this key -- see handle_orders_key.
        """
        if self.selection_mode:
            return
        event_handler.handle_view_mode_keybind(self, "ECONOMY", "ECONOMY")

    def draw_background(self, surface):
        # Recomputed here (not just in update()) so callers that draw this
        # background without running Map_Screen.update() first -- Orders_Screen,
        # MapOverlayScreen (claims/peace/trade/puppets) -- still get a live,
        # zoom-responsive color instead of a stale one. The generic checkerboard
        # fallback would checkerboard the ocean itself, so gate that behind the
        # opt-in Settings toggle; default is a flat fill so gameplay water looks
        # like water unless the player asks otherwise.
        self.bg_color = camera_handler.get_dynamic_ocean_color(self.camera, self.min_zoom)
        if c.CHECKERBOARD_WATER:
            super().draw_background(surface)
        else:
            surface.fill(self.bg_color)

    def additional_draw(self, surface):
        map_renderer.draw_map_screen(self, surface)

    def draw(self, surface):
        super().draw(surface)
        map_renderer.draw_badges(self, surface)

        diplomatic_popups.draw(self, surface)

        if self.thread_error:
            surface.fill((150, 0, 0))
            title = fonts.get("heading1").render("FATAL THREAD ERROR", True, (255, 255, 255))
            surface.blit(title, (20, 20))
            y_offset = 80
            for line in self.thread_error.split('\n'):
                surface.blit(fonts.get("small").render(line, True, (255, 200, 200)), (20, y_offset))
                y_offset += 25

            # Draw Copy Button
            btn_rect = pygame.Rect(c.SCREEN_WIDTH - 240, c.SCREEN_HEIGHT - 80, 220, 60)
            mx, my = pygame.mouse.get_pos()

            # Hover effect
            color = (200, 50, 50) if btn_rect.collidepoint(mx, my) else (150, 30, 30)

            pygame.draw.rect(surface, color, btn_rect, border_radius=5)
            pygame.draw.rect(surface, (255, 255, 255), btn_rect, 2, border_radius=5)

            btn_txt = fonts.get("button").render("Copy to Clipboard", True, (255, 255, 255))
            surface.blit(btn_txt, btn_txt.get_rect(center=btn_rect.center))

            # Show "Copied!" feedback text above the button
            if self.error_copied:
                copied_txt = fonts.get("small").render("Copied!", True, c.COLOR_SUCCESS_GREEN)
                surface.blit(copied_txt, (btn_rect.centerx - copied_txt.get_width()//2, btn_rect.y - 25))

            return

        from ui.information import feedback_text
        feedback_text.draw_feedback(self, surface)

    def refresh_nation_data(self, options=None):
        if options is None:
            options = {
                "reset_names": True,
                "reset_adjectives": True,
                "reset_leaders": True,
                "reset_flags": True,
                "reset_colors": True,
            }

        from data.io import country_io
        new_data = country_io.load_all_country_data()
        added_count = 0
        updated_count = 0

        for country, data in new_data.items():
            if country not in self.nation_data:
                self.nation_data[country] = data
                added_count += 1
            else:
                # SYNC FIX: Merge any missing top-level keys from the base template
                for base_key, base_val in data.items():
                    if base_key not in self.nation_data[country]:
                        self.nation_data[country][base_key] = base_val

                if "color" in data and options.get("reset_colors", True) and self.nation_data[country].get("color") != data["color"]:
                    self.nation_data[country]["color"] = data["color"]
                    updated_count += 1
                if "name" in data and options.get("reset_names", True):
                    self.nation_data[country]["name"] = data["name"]
                if "adjective" in data and options.get("reset_adjectives", True):
                    self.nation_data[country]["adjective"] = data["adjective"]
                if "leader" in data and options.get("reset_leaders", True):
                    self.nation_data[country]["leader"] = data["leader"]
                if "leader_title" in data and options.get("reset_leaders", True):
                    self.nation_data[country]["leader_title"] = data["leader_title"]

                if "research" in data:
                    current_res = self.nation_data[country].setdefault("research", {})
                    for tech_key, start_val in data["research"].items():
                        if tech_key not in current_res:
                            current_res[tech_key] = start_val
                            updated_count += 1

        # --- NEW: AUTO-RESET ASSETS TO DISK DEFAULTS ---
        if options.get("reset_flags", True):
            # By setting to DEFAULT, we force the rendering engine to search the disk again.
            queries.clear_image_cache()
            for c_name, n_data in self.nation_data.items():
                n_data["flag_data"] = "DEFAULT"
                n_data["portrait_data"] = "DEFAULT"

            # Clean up obsolete research for EVERY nation currently on the map
        tech_tree = queries.get_tech_tree()
        for country, data in self.nation_data.items():
            if "research" in data:
                obsolete_keys = [k for k in data["research"].keys() if k not in tech_tree]
                for k in obsolete_keys:
                    del data["research"][k]
                    updated_count += 1

        # --- NEW: Scrub the map's default template too! ---
        if getattr(self, "default_research", None) is not None:
            obsolete_defaults = [k for k in self.default_research.keys() if k not in tech_tree]
            for k in obsolete_defaults:
                del self.default_research[k]
                updated_count += 1

        self.nation_colors = country_io.nation_colors_from(self.nation_data)
        self.refresh_map_layers("political", "relations")

        # Merge the unit sync into this function
        self.sync_units_to_data()

        self.show_feedback(f"Data Resynced! Added {added_count}, Updated {updated_count}. Objects Synced.")

    def toggle_editor_brush_type(self):
        if self.editor_mode == "NATION":
            self.editor_mode = "BUILDING"
            self.show_feedback("Editor: Building Placement")
        else:
            self.editor_mode = "NATION"
            self.show_feedback("Editor: Nation Painting")

    def update(self):
        super().update()
        self.camera.update(self, c.SCREEN_HEIGHT)

        # Defer editor map label updates until the user finishes their brush stroke
        if self.centers_need_update and not pygame.mouse.get_pressed()[0]:
            self.update_country_centers()
            self.centers_need_update = False

        # Only spawn popups when the player is fully in control of the current turn
        is_playing = not self.viewing_ai_moves and \
                     not self.ai_is_thinking and \
                     not self.show_player_ready_screen and \
                     not self.selection_mode

        if is_playing:
            from ui import diplomatic_popups
            diplomatic_popups.spawn_popups_for_player(self)

        if self.show_player_ready_screen:
            for el in self.elements: el.visible = False
            return

        if self.multi_turn_processing_complete:
            self.multi_turn_processing_complete = False
            self.multi_turns_total = 0
            self.ai_is_thinking = False

            if self.thread_error: return

            self.refresh_map_layers(*self.ALL_MAP_LAYERS)
            self.update_country_centers()

            self.viewing_ai_moves = False # Safely unlock PyGame UI rendering

            update_button_states(self)
            self.show_feedback(f"Multi-Turn Processing Complete!")
            return

        if self.ai_processing_complete:
            self.ai_processing_complete = False
            self.ai_is_thinking = False

            if self.thread_error: return

            if self.skip_ai_view:
                self.viewing_ai_moves = True
                turn_manager.advance_time(self)
            else:
                self.viewing_ai_moves = True
                self.refresh_map_layers("political", "relations", "fog")
                render_buttons(self)
                elapsed_seconds = (pygame.time.get_ticks() - self.turn_start_time) / 1000.0
                self.show_feedback(f"AI Strategy generated in {elapsed_seconds:.2f}s")
                print(f"[PERFORMANCE] Phase 1 completed in {elapsed_seconds:.2f} seconds.")

        self.bg_color = camera_handler.get_dynamic_ocean_color(self.camera, self.min_zoom)
        update_button_states(self)
