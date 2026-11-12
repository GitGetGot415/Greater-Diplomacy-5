"""Map screen buttons: layout values, construction, and state updates.

screens/game/map.py builds these buttons with render_buttons and refreshes them with update_button_states.
Callers reach these helpers through this module so a replaced helper applies to every caller.
"""
from importlib import import_module
import os

import pygame

import data.constants as c
from data import queries
from data.multiplayer.tournament import files as tournament_files
from map_logic.ai.ai_evaluation import evaluate_verdict
from map_logic.ai.scripted_events import scripted_event_response_preview
from map_logic.diplomacy import guarantees, military_attaches, peace_scope, player_diplomacy_actions, volunteers
from map_logic.diplomacy.action_definitions import availability
from map_logic.system32 import turn_manager, unit_events
from screens.editors import menus as editor_menus
from screens.editors import scripted_events_editor
from screens.game import map_input, spectator_controls
from screens.game.politics_screen import Politics_Screen
from screens.setup import player_setup
from ui import dialogs
from ui.bars import resource_hud
from ui.dialogs import file_exchange, pickers
from ui.navigation import screen_runner
from ui.panels import realtime_status_panel
from ui.panels.multiplayer_host_panel import export_next_turn, manage_keys_panel, manage_players_panel, show_move_rejection
from ui.widgets import ui_elements
from ui.widgets.ui_elements import Button, Slider

# ============================================================================ #
#                                   LAYOUT                                     #
# ============================================================================ #
# Every hardcoded position for the map screen's buttons lives here so a nudge
# only ever means editing this block. Sizes come from c.SIZES; the two shared
# bar centre-lines (c.TOP_BAR_UI_CENTER_Y / c.BOTTOM_BAR_UI_CENTER_Y) stay in
# constants.py because other screens line up against them too.

# --- Map view toggles (bottom-left grid) ---


UP_RIGHT_OFFSET = 3
VIEW_BTN_START_X = 10 + UP_RIGHT_OFFSET
VIEW_BTN_STEP_X = 50
VIEW_BTN_ROW1_Y = c.SCREEN_HEIGHT - (50 + UP_RIGHT_OFFSET)
VIEW_BTN_ROW2_Y = c.SCREEN_HEIGHT - (100 + UP_RIGHT_OFFSET)

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
EDITOR_BULK_ICON_SCALE = 2
EDITOR_SELECTION_TOOL_X = EDITOR_BOT_BTN_START_X - EDITOR_BOT_BTN_STEP_X * 0.5
EDITOR_SELECTION_TOOL_GAP = 15
EDITOR_SELECTION_TOOL_STEP_X = c.SIZES["small_square"][0] + EDITOR_SELECTION_TOOL_GAP

# --- Vertical unit filters beside the lower left sidebar ---
UNIT_VIEW_BUTTON_COLORS = {"NAVAL": "blue", "LAND": "green", "AIR": "red", "ALL": "yellow"}
UNIT_VIEW_TOGGLE_HEIGHT = 22
UNIT_VIEW_BUTTON_PADDING_X = 8
UNIT_VIEW_BUTTON_PADDING_Y = 8
UNIT_VIEW_BUTTON_GAP_Y = 10
UNIT_VIEW_ICON_PADDING = 4
UNIT_VIEW_BUTTON_WIDTH, UNIT_VIEW_BUTTON_HEIGHT = c.SIZES["small_square"]
UNIT_VIEW_BUTTON_STEP_Y = UNIT_VIEW_BUTTON_HEIGHT + UNIT_VIEW_BUTTON_GAP_Y
UNIT_VIEW_BAR_WIDTH = UNIT_VIEW_BUTTON_WIDTH + 2 * UNIT_VIEW_BUTTON_PADDING_X
UNIT_VIEW_BAR_HEIGHT = (len(queries.UNIT_VIEW_FILTERS) * UNIT_VIEW_BUTTON_HEIGHT
                        + (len(queries.UNIT_VIEW_FILTERS) - 1) * UNIT_VIEW_BUTTON_GAP_Y
                        + 2 * UNIT_VIEW_BUTTON_PADDING_Y)

# --- Top bar, right-aligned ---
TOP_BAR_BUTTON_GAP = 5
TOP_RIGHT_BTN_X = c.SCREEN_WIDTH - 120
REFRESH_BTN_X = TOP_RIGHT_BTN_X - c.SIZES["small"][0] - TOP_BAR_BUTTON_GAP
HELP_BTN_X = REFRESH_BTN_X - c.SIZES["tiny"][0] - TOP_BAR_BUTTON_GAP
GLOBAL_ECON_BTN_X = HELP_BTN_X - c.SIZES["small"][0] - TOP_BAR_BUTTON_GAP

# --- Mode buttons on the country-selection screen ---
BTN_SPECTATOR_Y = c.SCREEN_HEIGHT - 55
BTN_TACTICAL_OFFSET_X = 240

# --- Province action buttons ---
ACTION_BTN_X = 200          # Spectator god-power column
DIPLO_BTN_X = 180           # Player diplomacy column
ACTION_BTN_START_Y = 300
ACTION_BTN_STEP_Y = 30
# Country actions live in this clipped pane instead of claiming the whole left
# side of the map. It has room for several choices at once and scrolls for the
# rest, leaving the orders and production entry points permanently reachable.
ACTION_SCROLL_HEIGHT = 300
ACTION_SCROLL_WIDTH = 215

# The diplomacy buttons are only 30px high, so their response prediction uses
# a compact image at the right edge and the smaller shared button font.
AI_RESPONSE_INDICATOR_SIZE = 20

PROVINCE_BTN_X = 280
BTN_ORDERS_Y = 603
BTN_PRODUCTION_Y = 543

# --- Multiplayer host strip ---
MP_HOST_BTN_Y = 15
MP_HOST_MANAGE_X = 350
MP_HOST_MANAGE_SIZE = (180, 30)
MP_HOST_EXPORT_X = MP_HOST_MANAGE_X + MP_HOST_MANAGE_SIZE[0] + TOP_BAR_BUTTON_GAP
MP_HOST_EXPORT_SIZE = (150, 30)
MP_HOST_KEYS_X = MP_HOST_EXPORT_X + MP_HOST_EXPORT_SIZE[0] + TOP_BAR_BUTTON_GAP


def _sub_screen_opener(map_screen, module_path, class_name):
    """A click callback that late-imports a screen and runs it over the map.

    The import has to stay inside the callback: these screens import the
    map package, which is the module currently being built.
    """
    def open_it():
        screen_runner._run_pygame_sub_screen(map_screen, getattr(import_module(module_path), class_name)(map_screen))
    return open_it


def _build_view_buttons(map_screen):
    """The top-bar tools, the bottom-left map view grid, and the unit filter bar."""
    icons = ui_elements.UI_ICONS
    map_screen.btn_help = ui_elements.make_info_button(HELP_BTN_X, c.TOP_BAR_UI_CENTER_Y, map_screen.show_navigation_tutorial)
    map_screen.btn_help.rect.midright = (REFRESH_BTN_X - TOP_BAR_BUTTON_GAP, c.TOP_BAR_UI_CENTER_Y + c.SIZES["small"][1] // 2)
    # The map tutorial has no opening sound, so the button keeps ownership of its click sound.
    map_screen.btn_help.sound_kind = "click"
    map_screen.btn_refresh_all = Button(REFRESH_BTN_X, c.TOP_BAR_UI_CENTER_Y, "small", "blue", "Refresh Maps", map_screen.refresh_all_maps, font_preset="normal")
    map_screen.btn_global_econ_overview = Button(GLOBAL_ECON_BTN_X, c.TOP_BAR_UI_CENTER_Y, "small", "pink", "Global Economy", lambda: editor_menus.open_editor_economy(map_screen), font_preset="normal", sound_kind=None)

    map_layer_buttons = (
        ("btn_view_terrain", "Terrain", "TERRAIN", "terrain"),
        ("btn_view_political", "Political", "POLITICAL", "political"),
        ("btn_view_relations", "Relations", "RELATIONS", "relations"),
        ("btn_view_cores", "Cores", "CORES", "core"),
        ("btn_view_factions", "Factions", "FACTIONS", "faction"),
    )
    for column, (attr, label, layer, icon) in enumerate(map_layer_buttons):
        setattr(map_screen, attr, Button(
            VIEW_BTN_START_X + VIEW_BTN_STEP_X * column, VIEW_BTN_ROW2_Y, "small_square", "green", label,
            lambda layer=layer: map_screen.set_map_layer(layer), image=icons.get(icon), show_text=False,
            sound_kind="select_mode"))

    # In Preemptive navigation, clicking one of these while a tile is already
    # selected jumps straight to that mode's screen for it (Orders for Units,
    # Production for Economy) instead of just flipping the map overlay.
    # In Classic navigation it only ever flips the overlay. See
    # screens.game.map_input.navigate_view_mode / data.constants.MAP_NAVIGATION_MODE.
    view_mode_buttons = (
        ("btn_view_resources", "Resources", "RESOURCES", "resource"),
        ("btn_view_blank", "Blank", "BLANK", "blank"),
        ("btn_view_units", "Units", "UNITS", "unit"),
        ("btn_view_economy", "Economy", "ECONOMY", "industry"),
    )
    for column, (attr, label, mode, icon) in enumerate(view_mode_buttons):
        setattr(map_screen, attr, Button(
            VIEW_BTN_START_X + VIEW_BTN_STEP_X * column, VIEW_BTN_ROW1_Y, "small_square", "red", label,
            lambda mode=mode: map_input.navigate_view_mode(map_screen, mode), image=icons.get(icon), show_text=False,
            sound_kind="select_view"))
    map_screen.btn_toggle_names = Button(VIEW_BTN_START_X + VIEW_BTN_STEP_X * 4, VIEW_BTN_ROW1_Y, "small_square", "blue", "Names", map_screen.toggle_country_names, image=icons.get("names"), show_text=False)

    map_screen.unit_view_bar_rect = pygame.Rect(
        map_screen.raised_rect.right,
        map_screen.ui_background_rect.top - UNIT_VIEW_BAR_HEIGHT,
        UNIT_VIEW_BAR_WIDTH, UNIT_VIEW_BAR_HEIGHT)
    map_screen.btn_unit_view_toggle = Button(
        map_screen.unit_view_bar_rect.x,
        map_screen.unit_view_bar_rect.y - UNIT_VIEW_TOGGLE_HEIGHT,
        (UNIT_VIEW_BAR_WIDTH, UNIT_VIEW_TOGGLE_HEIGHT), "grey", "Hide",
        map_screen.toggle_unit_view_bar, font_preset="small", sound_kind="select_view")
    map_screen.unit_view_buttons = {}
    for index, view_filter in enumerate(queries.UNIT_VIEW_FILTERS):
        icon = icons.get(view_filter.lower())
        if icon is not None:
            # Fit the pixel art once during construction, keeping its aspect
            # ratio and leaving room for the selected button's border.
            scale = min((UNIT_VIEW_BUTTON_WIDTH - 2 * UNIT_VIEW_ICON_PADDING) / icon.get_width(),
                        (UNIT_VIEW_BUTTON_HEIGHT - 2 * UNIT_VIEW_ICON_PADDING) / icon.get_height())
            icon = pygame.transform.scale(icon, (
                max(1, round(icon.get_width() * scale)),
                max(1, round(icon.get_height() * scale))))
        map_screen.unit_view_buttons[view_filter] = Button(
            map_screen.unit_view_bar_rect.x + UNIT_VIEW_BUTTON_PADDING_X,
            map_screen.unit_view_bar_rect.y + UNIT_VIEW_BUTTON_PADDING_Y
            + index * UNIT_VIEW_BUTTON_STEP_Y,
            "small_square", UNIT_VIEW_BUTTON_COLORS[view_filter], view_filter.title(),
            lambda view_filter=view_filter: map_screen.set_unit_view_filter(view_filter),
            image=icon, show_text=False, sound_kind="select_unit_filter")
        # A moving or clipped filter must not receive a click.
        map_screen.unit_view_buttons[view_filter].click_guard = (
            lambda: map_screen.unit_view_animation_start is None)


def _build_editor_buttons(map_screen):
    """The map editor's bottom strip and its three left-bar tools."""
    icons = ui_elements.UI_ICONS
    # (attribute, slots left of the strip's start, size, color, label, callback, icon).
    # An entry without an icon shows its label instead.
    bottom_strip = (
        ("btn_ed_load", -0.5, "small_square", "blue", "Load", lambda: editor_menus.editor_load_map(map_screen), None),
        ("btn_ed_nation", 1.5, "small", "grey", "Nation Brush", lambda: editor_menus.select_brush_nation(map_screen), None),
        ("btn_ed_core", 2.5, "small", "pink", "Core Brush", lambda: editor_menus.select_core_brush(map_screen), None),
        ("btn_ed_autocore", 3, "small_square", "pink", "Autocore", map_screen.auto_assign_cores, None),
        ("btn_ed_bulk", 3.5, "small_square", "blue", "Bulk Edit", lambda: editor_menus.open_bulk_editor(map_screen), "stack"),
        ("btn_ed_claim", 4, "small_square", "orange", "Claim Brush", lambda: editor_menus.select_claim_brush(map_screen), "paper"),
        ("btn_ed_resource", 4.5, "small_square", "purple", "Resource", lambda: editor_menus.select_resource_brush(map_screen), "resource"),
        ("btn_ed_building", 5, "small_square", "grey", "Building", lambda: editor_menus.select_building_brush(map_screen), "industry"),
        ("btn_ed_unit", 5.5, "small_square", "grey", "Unit", lambda: editor_menus.select_unit_brush(map_screen), "unit"),
        ("btn_ed_refresh", 6.5, "small", "purple", "Data Refresh", lambda: editor_menus.confirm_editor_data_refresh(map_screen), None),
        ("btn_ed_date", 7, "small_square", "orange", "Set Date", lambda: editor_menus.open_editor_date(map_screen), "clock"),
        ("btn_ed_edited", 8, "small", "green", "Edited Countries", lambda: editor_menus.open_edited_countries(map_screen), None),
    )
    for attr, slots, size, color, label, callback, icon in bottom_strip:
        appearance = (dict(image=icons.get(icon), show_text=False) if icon else dict(font_preset="normal"))
        setattr(map_screen, attr, Button(EDITOR_BOT_BTN_START_X - EDITOR_BOT_BTN_STEP_X * slots, c.BOTTOM_BAR_UI_CENTER_Y,
                                         size, color, label, callback,
                                         sound_kind=None if attr == "btn_ed_edited" else "click", **appearance))

    map_screen.btn_ed_bulk.image = pygame.transform.scale_by(icons["stack"], EDITOR_BULK_ICON_SCALE)

    map_screen.btn_ed_brush = Button(EDITOR_SELECTION_TOOL_X, c.BOTTOM_BAR_UI_CENTER_Y, "small_square", "blue", "Brush", lambda: map_screen.set_editor_selection_tool("BRUSH"), image=icons.get("brush"), show_text=False)
    map_screen.btn_ed_paint = Button(EDITOR_SELECTION_TOOL_X + EDITOR_SELECTION_TOOL_STEP_X, c.BOTTOM_BAR_UI_CENTER_Y, "small_square", "blue", "Paint", lambda: map_screen.set_editor_selection_tool("PAINT"), image=icons.get("paint"), show_text=False)

    map_screen.btn_ed_diplo = Button(LEFT_UI_BAR_X, LEFT_UI_BAR_START_Y + LEFT_UI_BAR_STEP_Y * 8, "left_ui_button", "red", "Diplomacy", lambda: editor_menus.open_diplomacy_editor(map_screen))
    # Row 11, not 9: btn_gp_claims is row 9 and is also visible in the editor, so
    # this button spent its whole existence hidden underneath it, pixel for pixel,
    # with a click there firing both callbacks. test_editor_menu_layout keeps the
    # rows distinct now rather than trusting the next number picked by hand.
    map_screen.btn_ed_personality = Button(LEFT_UI_BAR_X, LEFT_UI_BAR_START_Y + LEFT_UI_BAR_STEP_Y * 11, "left_ui_button", "purple", "AI Personality", lambda: editor_menus.open_personality_editor(map_screen), font_preset="normal")
    map_screen.btn_ed_scripts = Button(LEFT_UI_BAR_X, LEFT_UI_BAR_START_Y + LEFT_UI_BAR_STEP_Y * 10, "left_ui_button", "red", "Scripted Events", lambda: scripted_events_editor.open_scripted_events_editor(map_screen), font_preset="normal")


def _submit_realtime_turn(map_screen):
    from data.multiplayer.realtime.session import collect_map_commands, RealtimeError

    def confirmed(accepted):
        if not accepted:
            return
        try:
            session = map_screen.realtime_session
            player = map_screen.realtime_player_id
            turn = session.turn_number
            commands = collect_map_commands(map_screen, map_screen.player_country)
            is_remote = bool(map_screen.realtime_client)
            # Set this before the queued socket work begins.  The
            # confirmation modal can therefore close on this frame
            # and the map remains interactive while TLS writes and
            # the host acknowledgement happen in background threads.
            if is_remote:
                map_screen.realtime_submission_pending = True
                map_screen.show_feedback("Submitting turn to the host...")
            if session.sync_draft(player, turn, commands) is False:
                map_screen.realtime_submission_pending = False
                map_screen.show_feedback("Cannot submit: connection to the host was lost.")
                return
            if session.submit(player, turn) is False:
                map_screen.realtime_submission_pending = False
                map_screen.show_feedback("Cannot submit: connection to the host was lost.")
                return
            # A remote client has queued a request, not yet a server
            # acknowledgement.  Make the short in-flight interval
            # explicit instead of leaving an apparently live Submit
            # button on screen.
            if not is_remote:
                map_screen.show_feedback("Turn submitted. Unsubmit to edit again.")
        except RealtimeError as error:
            map_screen.show_feedback(f"Submission rejected: {error}")
    dialogs.ask_yes_no("Submit Turn", "Lock these orders for this turn?", confirmed,
                       yes_label="Submit", no_label="Keep Editing")


def _unsubmit_realtime_turn(map_screen):
    from data.multiplayer.realtime.session import RealtimeError

    def confirmed(accepted):
        if not accepted:
            return
        try:
            if map_screen.realtime_session.unsubmit(
                    map_screen.realtime_player_id,
                    map_screen.realtime_session.turn_number) is False:
                map_screen.show_feedback("Cannot unsubmit: connection to the host was lost.")
                return
            map_screen.show_feedback("Turn unlocked. You may edit orders again.")
        except RealtimeError as error:
            map_screen.show_feedback(f"Cannot unsubmit: {error}")
    dialogs.ask_yes_no("Unsubmit Turn", "Unlock your turn and allow further edits?", confirmed,
                       yes_label="Unsubmit", no_label="Stay Submitted")


def _export_tournament_move(map_screen):
    turn = map_screen.time_manager.total_turns
    cid = map_screen.player_country
    save_name = f"Turn_{turn}_{cid}.gd5move"
    export_path = os.path.join(c.TOURNAMENT_SAVES_DIR, save_name)
    player_key = map_screen.multiplayer_player_key

    def export(path, _overwrite):
        try:
            tournament_files.export_move_file(map_screen, path, player_key)
        except (OSError, ValueError) as error:
            map_screen.show_feedback(f"Move export failed: {error}")
            return
        map_screen.show_feedback(f"Move exported to {path}")

    file_exchange.choose_save_destination(export_path, export, game_state=map_screen,
                                          title="Export Turn")


def _import_tournament_move(map_screen):
    def on_picked(file_path):
        if file_path:
            cid = map_screen.player_country
            player_key = map_screen.multiplayer_player_key
            keys_dict = {cid: player_key}

            summary = tournament_files.load_move_files(map_screen, [file_path], keys_dict)
            if not summary["loaded"]:
                for rejection in summary["rejections"]:
                    show_move_rejection(map_screen, rejection)
                map_screen.show_feedback("Move import rejected. See the notification for details.")
                return
            map_screen.show_feedback(f"Move imported from {os.path.basename(file_path)}")

            map_screen.refresh_map_layers(
                "political", "factions", "relations", "cores", "faction_territories")
            if hasattr(map_screen, 'sync_units_to_data'):
                map_screen.sync_units_to_data()

    pickers.open_file_browser(map_screen, "Select Move File", c.TOURNAMENT_SAVES_DIR,
                              extensions=[".gd5move"], on_result=on_picked)


def _build_turn_buttons(map_screen):
    """The bottom-right turn controls, which depend on the multiplayer mode."""
    icons = ui_elements.UI_ICONS
    # Real-time mode is deliberately checked before the legacy tournament
    # flag: tournaments remain file-based and untouched.
    if map_screen.realtime_multiplayer:
        map_screen._realtime_submit = lambda: _submit_realtime_turn(map_screen)
        map_screen._realtime_unsubmit = lambda: _unsubmit_realtime_turn(map_screen)
        map_screen.btn_next_turn = Button(EDITOR_BOT_BTN_START_X, c.BOTTOM_BAR_UI_CENTER_Y,
                                          "small", "purple", "Submit Turn", map_screen._realtime_submit)
        map_screen.btn_import_turn = Button(-1000, -1000, "small", "grey", "Import Turn", lambda: None)
    elif map_screen.multiplayer_mode:
        map_screen.btn_next_turn = Button(EDITOR_BOT_BTN_START_X, c.BOTTOM_BAR_UI_CENTER_Y, "small", "purple", "Export Turn", lambda: _export_tournament_move(map_screen))
        map_screen.btn_import_turn = Button(EDITOR_BOT_BTN_START_X - EDITOR_BOT_BTN_STEP_X, c.BOTTOM_BAR_UI_CENTER_Y, "small", "purple", "Import Turn", lambda: _import_tournament_move(map_screen))
    else:
        map_screen.btn_next_turn = Button(EDITOR_BOT_BTN_START_X, c.BOTTOM_BAR_UI_CENTER_Y, "small", "purple", "Next Turn", lambda: turn_manager.advance_time(map_screen))
        map_screen.btn_import_turn = Button(-1000, -1000, "small", "grey", "Import Turn", lambda: None)

    map_screen.btn_skip_ai = Button(EDITOR_BOT_BTN_START_X - EDITOR_BOT_BTN_STEP_X, c.BOTTOM_BAR_UI_CENTER_Y, "small", "grey", "Skip AI", map_screen.toggle_skip_ai, font_preset="normal")
    map_screen.btn_multi_turn = Button(EDITOR_BOT_BTN_START_X - EDITOR_BOT_BTN_STEP_X * 2, c.BOTTOM_BAR_UI_CENTER_Y, "small", "blue", "Multi-Turn", map_screen.trigger_multi_turn)

    report_rect = resource_hud.unit_event_button_rect()
    map_screen.btn_unit_events = Button(
        report_rect.x, report_rect.y, "small_square", "yellow", "Unit events",
        _sub_screen_opener(map_screen, "screens.game.unit_events_screen", "UnitEventsScreen"),
        image=icons.get("mail"), show_text=False, sound_kind=None)
    unit_events.refresh_presentation(map_screen)

    open_declare_independence = _sub_screen_opener(
        map_screen, "screens.game.declare_independence", "Declare_Independence_Screen")

    map_screen.btn_declare_indep = Button(EDITOR_BOT_BTN_START_X - EDITOR_BOT_BTN_STEP_X * 2, c.BOTTOM_BAR_UI_CENTER_Y, "small", "pink", "Independence!", open_declare_independence, font_preset="normal")


def _build_left_bar_buttons(map_screen):
    """The left-hand bar shared by players, spectators, and the map editor."""
    icons = ui_elements.UI_ICONS

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

        The map editor sets starting research through country trees or bulk controls.
        A spectator selects View or Edit and a country. A player opens their own tree.
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
            _sub_screen_opener(map_screen, "screens.game.politics_screen",
                               "Politics_Screen")()

    econ_callback = editor_or(editor_menus.open_starting_economy_editor, "ECONOMY")

    def msgs_callback():
        if map_screen.is_editor:
            editor_menus.open_editor_metadata(map_screen)
        elif map_screen.player_country == "Spectator":
            editor_menus.open_spectator_messages(map_screen)
        else:
            map_screen.change_state("MESSAGES")

    # The left-hand bar: one column, one size, one color, one row per entry.
    # Claims and Puppets route everyone to the native Pygame screen so they can
    # see the map highlights.
    left_bar_buttons = (
        ("btn_gp_edit", 1, "Identity", "brush", open_edit_country_action),
        ("btn_gp_econ", 2, "Economy",
         "economy(the_economy_of_a_country_to_be_unusually_specific)", econ_callback),
        ("btn_gp_rd", 3, "R&D", "research", research_callback),
        ("btn_gp_msgs", 4, "Metadata" if map_screen.is_editor else "Mail",
         "core" if map_screen.is_editor else "mail", msgs_callback),
        ("btn_gp_save", 5, "Save", "save", map_screen.save_map_data),
        ("btn_gp_settings", 6, "Settings", "settings", lambda: map_screen.change_state("SETTINGS")),
        ("btn_gp_music", 7, "Music", "music", lambda: map_screen.change_state("MUSIC_PLAYER")),
        ("btn_gp_faction", 8, "Faction", "faction", lambda: map_screen.change_state("FACTION")),
        ("btn_gp_claims", 9, "Claims", "paper",
         lambda: player_diplomacy_actions.open_claims_menu(map_screen)),
        ("btn_gp_puppets", 10, "Puppets", "puppet",
         lambda: player_diplomacy_actions.open_puppets_menu(map_screen)),
        ("btn_gp_automation", 11, "Automation", None,
         _sub_screen_opener(map_screen, "screens.game.automation_screen", "Automation_Screen")),
        # Row 12 is the only row free in both modes -- the editor fills 1-11 too,
        # just with a different set.
        ("btn_gp_politics", 12, "Politics", "tophat", politics_callback),
    )
    for attr, row, label, icon_name, action in left_bar_buttons:
        sound_kind = {"btn_gp_music": "open_music", "btn_gp_settings": "open_settings",
                      "btn_gp_rd": "research", "btn_gp_edit": "paper", "btn_gp_claims": "paper",
                      "btn_gp_puppets": "puppets"}.get(attr, "click")
        if attr == "btn_gp_msgs":
            if map_screen.is_editor:
                sound_kind = "paper"
            elif map_screen.player_country == "Spectator":
                sound_kind = None
            else:
                sound_kind = "paper"
        setattr(map_screen, attr, Button(LEFT_UI_BAR_X, LEFT_UI_BAR_START_Y + LEFT_UI_BAR_STEP_Y * row,
                                   "left_ui_button", "pink", label, action,
                                   image=icons.get(icon_name) if icon_name else None,
                                   show_text=True, sound_kind=sound_kind))

    # Register the Slider below the new Automation button
    slider_y = int(LEFT_UI_BAR_START_Y + LEFT_UI_BAR_STEP_Y * CAMERA_TILT_SLIDER_ROW)
    map_screen.slider_camera_tilt = Slider(LEFT_UI_BAR_X, slider_y, CAMERA_TILT_SLIDER_WIDTH, "Camera Tilt", map_screen.camera_tilt_slider_val, map_screen.set_camera_tilt)


def _load_ai_response_images():
    response_images = {}
    for response in ("YES", "NO", "MAYBE"):
        image_path = os.path.join(c.ASSETS_DIR, f"{response}.png")
        image = pygame.image.load(image_path).convert_alpha()
        scale = min(AI_RESPONSE_INDICATOR_SIZE / image.get_width(),
                    AI_RESPONSE_INDICATOR_SIZE / image.get_height())
        response_images[response] = pygame.transform.smoothscale(
            image, (round(image.get_width() * scale),
                    round(image.get_height() * scale)))
    return response_images


def _add_country_action_button(map_screen, attr, x, row, color, label, action, **appearance):
    base_y = ACTION_BTN_START_Y + ACTION_BTN_STEP_Y * row
    button = Button(x, base_y, "diplomatic", color, label, action, **appearance)
    button.country_action_base_y = base_y
    setattr(map_screen, attr, button)
    map_screen.country_action_buttons.append(button)


def _build_province_buttons(map_screen):
    """The contextual province menus: domestic, foreign, and spectator actions."""
    icons = ui_elements.UI_ICONS
    # Domestic Set. In Preemptive navigation both route through
    # navigate_view_mode rather than jumping straight to their screen, so
    # clicking them also swaps the bottom-left view-mode row over to match
    # (Units for either half of this shared slot, Economy for Production)
    # instead of leaving it on whatever it last was. In Classic navigation they
    # jump straight there unconditionally instead. See
    # screens.game.map_input.go_to_orders_screen/go_to_production_screen.
    map_screen.btn_go_orders = Button(PROVINCE_BTN_X, BTN_ORDERS_Y, "orders", "blue", "Give Orders", lambda: map_input.go_to_orders_screen(map_screen), image=icons.get("paper"), show_text=False)
    # Retained as a compatibility object for old callers/layout code. It is
    # never exposed: a fighting tile enters Orders first, where the lane
    # manager can be opened after the player has access to all order controls.
    map_screen.btn_go_battle = Button(PROVINCE_BTN_X, BTN_ORDERS_Y, "orders", "red", "Manage Battle", lambda: map_input.go_to_battle_screen(map_screen), image=icons.get("battle"), show_text=False)
    map_screen.btn_go_production = Button(PROVINCE_BTN_X, BTN_PRODUCTION_Y, "orders", "orange", "Production", lambda: map_input.go_to_production_screen(map_screen), image=icons.get("industry"), show_text=False)

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
        ("btn_guarantee", 10, "blue", "Guarantee Independence", player_diplomacy_actions.handle_guarantee),
        ("btn_military_attache", 11, "orange", "Send Military Attaché", player_diplomacy_actions.handle_military_attache),
        ("btn_revoke_foreign_military_attache", 12, "red", "Revoke Their Attaché", player_diplomacy_actions.handle_revoke_foreign_military_attache),
        ("btn_send_home_foreign_volunteers", 13, "red", "Send Their Volunteers Home", player_diplomacy_actions.handle_send_home_foreign_volunteers),
    )
    map_screen.ai_response_images = _load_ai_response_images()

    map_screen.country_action_buttons = []
    for attr, row, color, label, handler in diplo_buttons:
        if isinstance(handler, str):
            action = (lambda a=handler:
                      player_diplomacy_actions.handle_specific_action(map_screen, a))
        else:
            action = lambda h=handler: h(map_screen)
        _add_country_action_button(map_screen, attr, DIPLO_BTN_X, row, color, label, action,
                                   font_preset="button_small")

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
        ("btn_spec_annex", 4, "orange", "Annex", "spec_annex_country"),
        ("btn_spec_delete", 5, "red", "Delete", "spec_delete_country"),
    )
    for attr, row, color, label, menu_fn in spectator_buttons:
        _add_country_action_button(map_screen, attr, ACTION_BTN_X, row, color, label,
                                   lambda f=menu_fn: getattr(spectator_controls, f)(map_screen))


def _open_selected_country_politics(map_screen):
    """Open the selected foreign country's politics as a read-only view."""
    province = map_screen.selected_province
    owner = province.get("owner") if province else None
    if (not owner or owner == map_screen.player_country
            or owner not in map_screen.nation_data):
        return
    screen_runner._run_pygame_sub_screen(map_screen, Politics_Screen(map_screen, country_id=owner))


def _build_general_buttons(map_screen):
    """The tournament host strip and the remaining fixed controls."""
    map_screen.btn_spec_mp_manage = Button(MP_HOST_MANAGE_X, MP_HOST_BTN_Y, MP_HOST_MANAGE_SIZE, "blue", "Manage Players", lambda: manage_players_panel(map_screen))
    map_screen.btn_spec_mp_export = Button(MP_HOST_EXPORT_X, MP_HOST_BTN_Y, MP_HOST_EXPORT_SIZE, "green", "Export Turn", lambda: export_next_turn(map_screen))
    map_screen.btn_spec_mp_keys = Button(MP_HOST_KEYS_X, MP_HOST_BTN_Y, "keys", "purple", "Keys", lambda: manage_keys_panel(map_screen))

    def start_spectator_action():
        player_setup.start_spectator(map_screen)
        map_screen.refresh_map_layers("fog")

    def toggle_tactical_action():
        map_screen.tactical_mode = not map_screen.tactical_mode

        # Tactical selection needs division boxes, while strategic country
        # selection remains a clean political view for choosing a nation.
        if map_screen.tactical_mode:
            map_screen.set_tactical_view_defaults()
        elif map_screen.selection_mode:
            map_screen.set_country_selection_view_defaults()
        else:
            map_screen.set_play_view_defaults()

        map_screen.show_feedback(f"Mode: {'TACTICAL' if map_screen.tactical_mode else 'STRATEGIC'}")

    map_screen.btn_spectator = Button(LEFT_UI_BAR_X, BTN_SPECTATOR_Y, "medium", "grey", "Spectator Mode", start_spectator_action)
    map_screen.btn_tactical = Button(LEFT_UI_BAR_X + BTN_TACTICAL_OFFSET_X, BTN_SPECTATOR_Y, "medium", "orange", "Tactical Mode", toggle_tactical_action)
    map_screen.btn_close_info = Button(TOP_RIGHT_BTN_X, c.TOP_BAR_UI_CENTER_Y, "small", "red", "X", map_screen.deselect_province, sound_kind="back")
    map_screen.btn_exit_to_menu = Button(TOP_RIGHT_BTN_X, c.TOP_BAR_UI_CENTER_Y, "small", "red", "Exit", map_screen.exit_to_menu, sound_kind="back")
    map_screen.btn_realtime_details = Button(TOP_RIGHT_BTN_X + 30, c.TOP_BAR_UI_CENTER_Y + 120,
                                              "tiny", "blue", "Details",
                                              lambda: realtime_status_panel.show_details(map_screen),
                                              sound_kind=None)
    map_screen.btn_view_foreign_politics = Button(
        *c.PROVINCE_UI["foreign_politics_button"][:2],
        c.PROVINCE_UI["foreign_politics_button"][2:], "purple", "View Their Politics",
        lambda: _open_selected_country_politics(map_screen), font_preset="normal")


def render_buttons(map_screen):
    """Initializes and registers all map screen buttons uniformly."""
    _build_view_buttons(map_screen)
    _build_editor_buttons(map_screen)
    _build_turn_buttons(map_screen)
    _build_left_bar_buttons(map_screen)
    _build_province_buttons(map_screen)
    _build_general_buttons(map_screen)

    # The order here is the draw and click order.
    map_screen.elements = [
        map_screen.btn_unit_view_toggle,
        *map_screen.unit_view_buttons.values(),
        map_screen.btn_help, map_screen.btn_refresh_all, map_screen.btn_global_econ_overview,
        map_screen.btn_view_terrain, map_screen.btn_view_political, map_screen.btn_view_relations, map_screen.btn_view_cores, map_screen.btn_view_factions,
        map_screen.btn_view_resources, map_screen.btn_view_blank, map_screen.btn_view_units, map_screen.btn_view_economy, map_screen.btn_toggle_names,
        map_screen.btn_unit_events,
        map_screen.btn_ed_load, map_screen.btn_ed_nation, map_screen.btn_ed_brush, map_screen.btn_ed_paint,
        map_screen.btn_ed_core, map_screen.btn_ed_claim, map_screen.btn_ed_autocore, map_screen.btn_ed_resource, map_screen.btn_ed_building,
        map_screen.btn_ed_unit, map_screen.btn_ed_refresh, map_screen.btn_ed_edited, map_screen.btn_ed_date, map_screen.btn_ed_diplo, map_screen.btn_ed_personality, map_screen.btn_ed_scripts, map_screen.btn_ed_bulk,
        map_screen.btn_next_turn, map_screen.btn_import_turn, map_screen.btn_skip_ai, map_screen.btn_multi_turn, map_screen.btn_declare_indep, map_screen.btn_gp_edit, map_screen.btn_gp_econ, map_screen.btn_gp_rd, map_screen.btn_gp_msgs,
        map_screen.btn_gp_save, map_screen.btn_gp_settings, map_screen.btn_gp_music, map_screen.btn_gp_faction, map_screen.btn_gp_claims, map_screen.btn_gp_puppets, map_screen.btn_gp_automation, map_screen.btn_gp_politics, map_screen.btn_go_orders, map_screen.btn_go_battle, map_screen.btn_go_production,
        map_screen.btn_declare_war, map_screen.btn_join_wars, map_screen.btn_call_to_arms, map_screen.btn_fac_invite,
        map_screen.btn_fac_join_req, map_screen.btn_fac_kick, map_screen.btn_fac_create,
        map_screen.btn_volunteers,
        map_screen.btn_guarantee,
        map_screen.btn_military_attache,
        map_screen.btn_revoke_foreign_military_attache,
        map_screen.btn_send_home_foreign_volunteers,
        map_screen.btn_req_mil_access, map_screen.btn_cancel_mil_access, map_screen.btn_revoke_mil_access,
        map_screen.btn_accept_req, map_screen.btn_reject_req, map_screen.btn_force_war, map_screen.btn_force_peace,
        map_screen.btn_spec_create_fac, map_screen.btn_spec_join_fac, map_screen.btn_spec_invite_fac, map_screen.btn_spec_leave_fac,
        map_screen.btn_spec_disband_fac, map_screen.btn_spec_annex, map_screen.btn_spec_delete,
        map_screen.btn_spectator, map_screen.btn_tactical, map_screen.btn_close_info, map_screen.btn_exit_to_menu, map_screen.btn_realtime_details,
        map_screen.btn_view_foreign_politics,
        map_screen.btn_spec_mp_manage, map_screen.btn_spec_mp_export, map_screen.btn_spec_mp_keys,
        map_screen.slider_camera_tilt
    ]

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


def layout_country_action_buttons(map_screen):
    """Place the fixed country-action stack inside its scroll viewport."""
    buttons = map_screen.country_action_buttons
    rect = map_screen.country_actions_scroll_rect
    if not buttons or rect is None:
        return

    content_bottom = max(button.country_action_base_y + button.rect.height
                         for button in buttons)
    map_screen.country_actions_scroll_max = max(
        0, content_bottom - rect.bottom)
    map_screen.country_actions_scroll_y = max(
        0, min(map_screen.country_actions_scroll_y,
                   map_screen.country_actions_scroll_max))

    for button in buttons:
        button.rect.y = (button.country_action_base_y
                         - map_screen.country_actions_scroll_y)
        # Screen dispatches button events before the map event handler can
        # consume a pane drag. Do not let clipped-away rows receive that click.
        button.click_guard = lambda r=rect: r.collidepoint(pygame.mouse.get_pos())


def bilateral_response_indicator(map_screen, target, action):
    """Return the response icon an outgoing bilateral proposal should show.

    This is deliberately a view of ``evaluate_verdict`` rather than a second
    set of AI rules. Leadership restrictions produce NO before prediction.
    Matching scripted responses take precedence for legal proposals, as they do
    when the event runs. Human replies to legal proposals remain unpredictable,
    including in multiplayer and hotseat.
    """
    if target not in map_screen.nation_data:
        return None
    if not availability(map_screen, map_screen.player_country, target, action).allowed:
        return "NO"
    if queries.faction_request_leadership_error(
            map_screen.player_country, target, action, map_screen.nation_data):
        return "NO"
    human_players = set(map_screen.active_players or ())
    if target in human_players:
        return "MAYBE"

    scenario_settings = map_screen.scenario_settings
    scripted_events_enabled = queries.get_scenario_flag(
        "use_scripted_events", c.DEFAULT_USE_SCRIPTED_EVENTS,
        scenario_settings)
    if (map_screen.nation_data[target].get("scripted_events")
            and scripted_events_enabled):
        turns = queries.get_total_turns(map_screen.time_manager)
        events = map_screen.nation_data[target]["scripted_events"]
        fired = tuple(map_screen.nation_data[target].get("fired_scripted_events", []))
        variables = tuple((item["name"], item["type"], item["value"])
                          for item in map_screen.script_variables)
        cache_stamp = (map_screen._presentation_cache_revision, turns,
                       tuple(id(event) for event in events), fired, variables,
                       scripted_events_enabled)
        cache = map_screen._scripted_response_indicator_cache
        if cache is None or cache.get("stamp") != cache_stamp:
            cache = {"stamp": cache_stamp, "responses": {}}
            map_screen._scripted_response_indicator_cache = cache

        cache_key = (target, map_screen.player_country, action)
        if cache_key not in cache["responses"]:

            cache["responses"][cache_key] = scripted_event_response_preview(
                map_screen, target, map_screen.player_country, action)
        scripted_response = cache["responses"][cache_key]
        if scripted_response is not None:
            return scripted_response


    verdict = evaluate_verdict(map_screen.nation_data, map_screen.map_data,
                               target, map_screen.player_country, action,
                               scenario_settings=scenario_settings)
    return "YES" if verdict.accepted else "NO"


def cached_bilateral_response_indicator(map_screen, target, action):
    """Reuse proposal availability and forecasts until input or world state changes."""
    revision = map_screen._presentation_cache_revision
    if revision is None or not hasattr(map_screen, "world"):
        return bilateral_response_indicator(map_screen, target, action)
    world = map_screen.world
    stamp = (revision, world.diplomacy_revision, world.runtime_rules.revision,
             world.time_manager.total_turns, map_screen.player_country, tuple(map_screen.active_players))
    cache = map_screen._bilateral_response_indicator_cache
    if cache is None or cache[0] != stamp:
        cache = (stamp, {})
        map_screen._bilateral_response_indicator_cache = cache
    key = (target, action)
    if key not in cache[1]:
        cache[1][key] = bilateral_response_indicator(map_screen, target, action)
    return cache[1][key]


def set_bilateral_response_indicator(map_screen, button, target, action,
                                    applicable=True):
    """Attach or remove one outgoing-proposal response image from a button."""
    button.right_image = None
    if not applicable:
        return
    response = cached_bilateral_response_indicator(map_screen, target, action)
    if response:
        button.right_image = map_screen.ai_response_images.get(
            response)


def set_btn(btn, visible, enabled, text, color="green"):
    """Shorthand for the per-frame visible/enabled/text/color updates below."""
    if btn:
        btn.apply_state(visible=visible, enabled=enabled, text=text, color=color)


def _update_selection_mode_buttons(map_screen):
    map_screen.btn_exit_to_menu.visible = True

    # Hide spectator and tactical buttons if awaiting confirmation
    show_mode_buttons = not bool(map_screen.pending_selection)
    map_screen.btn_spectator.visible = show_mode_buttons
    map_screen.btn_tactical.visible = show_mode_buttons

    is_multiplayer = map_screen.num_players > 1

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


def _update_view_toggles(map_screen):
    map_screen.btn_help.visible = True
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


def _update_unassigned_viewer_buttons(map_screen, is_sel, is_thinking):
    """Leave map controls and an exit, but expose no country-owned actions."""
    for button in (map_screen.btn_gp_settings, map_screen.btn_gp_music,
                   map_screen.slider_camera_tilt):
        button.visible = not is_sel
    # Hotseat clears the viewer after the last player's orders. Keep
    # resolution available without granting that viewer country actions.
    local_turn_preview = (
        map_screen.player_country == "n/a" and map_screen.viewing_ai_moves
        and len(map_screen.active_players) > 1
        and not map_screen.multiplayer_mode
        and not map_screen.realtime_multiplayer)
    set_btn(map_screen.btn_next_turn,
            local_turn_preview and not is_sel and not is_thinking,
            not is_thinking, "Resolve Turn", "red")
    map_screen.btn_exit_to_menu.visible = not is_sel
    map_screen.btn_close_info.visible = is_sel
    map_screen.btn_realtime_details.visible = bool(
        map_screen.realtime_multiplayer) and not is_sel


def _update_editor_buttons(map_screen, is_sel):
    map_screen.btn_gp_msgs.text = "Metadata"
    map_screen.btn_gp_msgs.image = ui_elements.UI_ICONS.get("core")
    ed_btns = [
        map_screen.btn_gp_edit, map_screen.btn_gp_econ, map_screen.btn_gp_rd,
        map_screen.btn_gp_msgs, map_screen.btn_gp_save, map_screen.btn_gp_claims,
        map_screen.btn_ed_load, map_screen.btn_ed_nation, map_screen.btn_ed_brush, map_screen.btn_ed_paint, map_screen.btn_ed_core, map_screen.btn_ed_claim,
        map_screen.btn_ed_autocore, map_screen.btn_ed_resource, map_screen.btn_ed_building,
        map_screen.btn_ed_unit, map_screen.btn_ed_refresh, map_screen.btn_ed_bulk,
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

    for tool, btn in (("BRUSH", map_screen.btn_ed_brush),
                      ("PAINT", map_screen.btn_ed_paint)):
        btn.disabled = map_screen.editor_mode not in ("NATION", "CORE")
        btn.is_selected = (not btn.disabled and map_screen.editor_selection_tool == tool)

    # A painted province may be selected, but the editor is not a player
    # nation.  Do not let that selection fall through into the gameplay
    # diplomacy controls, which require a nation_data player record.
    map_screen.btn_exit_to_menu.visible = True
    map_screen.btn_close_info.visible = is_sel
    map_screen.btn_realtime_details.visible = False


def _update_unit_view_buttons(map_screen, is_sel, is_thinking):
    """Share unit filter controls between the game and map editor."""
    unit_view_visible = not is_sel and not is_thinking and not map_screen.hide_raised_rect
    if map_screen.unit_view_buttons:
        if map_screen.unit_view_animation_start is None:
            map_screen.unit_view_bar_progress = map_screen._unit_view_bar_target()
        offset = round(UNIT_VIEW_BAR_HEIGHT * (1 - map_screen.unit_view_bar_progress))
        map_screen.unit_view_bar_offset = offset
        toggle = map_screen.btn_unit_view_toggle
        toggle.visible = unit_view_visible
        toggle.disabled = map_screen.secondary_mode != "UNITS"
        toggle.text = "" if toggle.disabled else "Show" if map_screen.unit_view_bar_collapsed else "Hide"
        if toggle.disabled:
            toggle.is_pressed = False
        toggle.rect.bottom = map_screen.unit_view_bar_rect.top + offset
    for index, (view_filter, button) in enumerate(map_screen.unit_view_buttons.items()):
        button.rect.y = (map_screen.unit_view_bar_rect.y + UNIT_VIEW_BUTTON_PADDING_Y
                         + index * UNIT_VIEW_BUTTON_STEP_Y + map_screen.unit_view_bar_offset)
        button.visible = unit_view_visible and map_screen.unit_view_bar_progress > 0
        button.is_selected = view_filter == map_screen.unit_view_filter


def _update_turn_buttons(map_screen, is_sel, is_thinking):
    viewing_ai = map_screen.viewing_ai_moves

    # Hide/disable the button if we are thinking
    map_screen.btn_next_turn.visible = not is_sel and not is_thinking
    if map_screen.realtime_multiplayer:
        session = map_screen.realtime_session
        player = session.players.get(map_screen.realtime_player_id)
        submission_pending = bool(map_screen.realtime_submission_pending)
        locked = (session.phase != "TURN" or not player or player.submitted or player.eliminated)
        connection_lost = bool(map_screen.realtime_connection_error)
        map_screen.btn_next_turn.text = ("Submitting..." if submission_pending else
                                         "Unsubmit Turn" if player and player.submitted else "Submit Turn")
        map_screen.btn_next_turn.callback = (map_screen._realtime_unsubmit if player and player.submitted
                                             else map_screen._realtime_submit)
        map_screen.btn_next_turn.set_palette("blue" if submission_pending else
                                             "orange" if player and player.submitted else "purple")
        map_screen.btn_next_turn.apply_state(enabled=not (connection_lost or session.phase == "PROCESSING"
                                                           or submission_pending or player and player.eliminated))
    elif map_screen.multiplayer_mode:
        map_screen.btn_next_turn.text = "Export Turn"
    else:
        map_screen.btn_next_turn.text = "Resolve Turn" if viewing_ai else "Next Turn"

    map_screen.btn_next_turn.set_palette("red" if viewing_ai else "purple")

    # Visibility and active color swapping for the skip toggle
    if map_screen.realtime_multiplayer:
        map_screen.btn_skip_ai.visible = False
        map_screen.btn_import_turn.visible = False
    elif map_screen.multiplayer_mode:
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
        map_screen.btn_spec_mp_manage.visible = map_screen.multiplayer_host_mode and not is_sel and not is_thinking
        map_screen.btn_spec_mp_export.visible = map_screen.multiplayer_host_mode and not is_sel and not is_thinking
        map_screen.btn_spec_mp_keys.visible = map_screen.multiplayer_host_mode and not is_sel and not is_thinking
    map_screen.btn_declare_indep.visible = map_screen.tactical_mode and not is_sel and not is_thinking


def _update_gameplay_buttons(map_screen, is_sel, is_thinking):
    map_screen.btn_gp_msgs.text = "Mail"
    map_screen.btn_gp_msgs.image = ui_elements.UI_ICONS.get("mail")
    viewing_ai = map_screen.viewing_ai_moves
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
    if queries.get_scenario_flag("battle_royale", c.DEFAULT_BATTLE_ROYALE, map_screen.scenario_settings):
        map_screen.btn_gp_faction.disabled = True
        map_screen.btn_gp_claims.disabled = True

    # --- TACTICAL MODE LOCKDOWNS ---
    if map_screen.tactical_mode:
        for btn in (map_screen.btn_gp_faction, map_screen.btn_gp_puppets, map_screen.btn_gp_edit,
                    map_screen.btn_gp_econ, map_screen.btn_gp_automation):
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


def _update_spectator_province_buttons(map_screen, owner):
    if queries.is_playable(owner, map_screen.nation_data):
        set_btn(map_screen.btn_force_war, True, True, "Force War", "red")
        set_btn(map_screen.btn_force_peace, True, True, "Force Ceasefire", "green")
        can_remove_country = queries.can_use_spectator_country_actions(map_screen)
        set_btn(map_screen.btn_spec_annex, can_remove_country, can_remove_country, "Annex", "orange")
        set_btn(map_screen.btn_spec_delete, can_remove_country, can_remove_country, "Delete", "red")

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


def _foreign_action_buttons(map_screen):
    """Return every country-to-country button. Each one is disabled together in tactical mode."""
    return (map_screen.btn_declare_war, map_screen.btn_join_wars, map_screen.btn_call_to_arms,
            map_screen.btn_volunteers, map_screen.btn_guarantee, map_screen.btn_military_attache,
            map_screen.btn_revoke_foreign_military_attache, map_screen.btn_send_home_foreign_volunteers,
            map_screen.btn_fac_invite, map_screen.btn_fac_join_req, map_screen.btn_fac_kick,
            map_screen.btn_fac_create, map_screen.btn_req_mil_access, map_screen.btn_cancel_mil_access,
            map_screen.btn_revoke_mil_access)


def _update_war_button(map_screen, owner, pending_action, pending_turns, at_war):
    my_master = map_screen.nation_data.get(map_screen.player_country, {}).get("master", "")
    t_master = map_screen.nation_data.get(owner, {}).get("master", "")

    faction_peace_active = peace_scope.has_settleable_war(
        map_screen.player_country, owner, map_screen.nation_data)
    has_truce = queries.has_active_truce(map_screen.player_country, owner, map_screen.nation_data)

    # Fetch the exact number of turns remaining ---
    truce_turns = map_screen.nation_data.get(map_screen.player_country, {}).get("truces", {}).get(owner, 0)

    # This button is also the peace button, and handle_ceasefire explains a refused peace.
    # Otherwise it declares war, so it is enabled only when the shared war rule allows that.
    if at_war or faction_peace_active:
        dw_enabled = True
    else:
        dw_enabled = availability(map_screen, map_screen.player_country, owner, "WAR_DECLARATION").allowed

    if pending_action == "PEACE_TREATY" or pending_action == "CEASEFIRE":
        if pending_turns > 0:
            dw_text = "Peace Offer Pending"
            dw_enabled = False
        else:
            dw_text = "Edit Peace Offer"
    elif pending_action == "WAR_DECLARATION":
        dw_text = "Edit War Declaration"
    else:
        if has_truce and not at_war and not faction_peace_active:
            dw_text = f"Truce Active ({truce_turns})"
        else:
            if at_war or faction_peace_active:
                if queries.get_scenario_flag("battle_royale", c.DEFAULT_BATTLE_ROYALE, map_screen.scenario_settings):
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


def _update_volunteer_buttons(map_screen, owner, pending_action, pending_turns):
    """Update both volunteer buttons and return this country's mission state."""
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

    foreign_volunteer_state = volunteers.mission_state(
        map_screen.nation_data, owner, map_screen.player_country)
    pending_send_home = (pending_action == volunteers.SEND_HOME_ACTION
                         and pending_turns == 0)
    hosting_foreign_volunteers = foreign_volunteer_state in (
        volunteers.OUTBOUND, volunteers.DEPLOYED)
    set_btn(map_screen.btn_send_home_foreign_volunteers,
            hosting_foreign_volunteers or pending_send_home,
            hosting_foreign_volunteers or pending_send_home,
            "Undo Send Home" if pending_send_home else "Send Their Volunteers Home",
            "red")
    return volunteer_state


def _set_commitment_button(button, legal, active, pending_start, pending_end, texts, color):
    """Show a commitment button. `texts` is (undo start, undo end, end, start)."""
    undo_start, undo_end, end, start = texts
    if pending_start:
        text = undo_start
    elif pending_end:
        text = undo_end
    elif active:
        text = end
    else:
        text = start
    set_btn(button, True, pending_start or pending_end or active or (legal and not active), text, color)


def _update_guarantee_button(map_screen, owner, pending_action, pending_turns):
    guarantee_legal, _guarantee_reason = guarantees.is_eligible(
        map_screen.player_country, owner, map_screen.nation_data)
    already_guaranteed = owner in guarantees.guaranteed_targets(
        map_screen.player_country, map_screen.nation_data)
    _set_commitment_button(
        map_screen.btn_guarantee, guarantee_legal, already_guaranteed,
        pending_action == guarantees.ACTION and pending_turns == 0,
        pending_action == guarantees.REVOKE_ACTION and pending_turns == 0,
        ("Undo Guarantee", "Undo Revoke Guarantee", "Revoke Guarantee", "Guarantee Independence"), "blue")


def _update_attache_buttons(map_screen, owner, pending_action, pending_turns):
    """Update both attaché buttons and return whether an attaché request can be forecast."""
    attache_legal, _attache_reason = military_attaches.is_eligible(
        map_screen.player_country, owner, map_screen.nation_data)
    attached = owner in military_attaches.hosts_for(
        map_screen.player_country, map_screen.nation_data)
    pending_attache = (pending_action == military_attaches.ACTION
                       and pending_turns == 0)
    pending_withdraw_attache = (pending_action == military_attaches.WITHDRAW_ACTION
                                 and pending_turns == 0)
    _set_commitment_button(
        map_screen.btn_military_attache, attache_legal, attached, pending_attache, pending_withdraw_attache,
        ("Undo Attaché Request", "Undo Attaché Withdrawal", "Withdraw Military Attaché", "Send Military Attaché"),
        "orange")

    hosting_their_attache = map_screen.player_country in military_attaches.hosts_for(
        owner, map_screen.nation_data)
    pending_revoke_their_attache = (
        pending_action == military_attaches.REVOKE_ACTION and pending_turns == 0)
    set_btn(map_screen.btn_revoke_foreign_military_attache,
            hosting_their_attache or pending_revoke_their_attache,
            hosting_their_attache or pending_revoke_their_attache,
            "Undo Revoke Their Attaché" if pending_revoke_their_attache
            else "Revoke Their Attaché", "red")
    return not attached and not pending_attache and not pending_withdraw_attache


def _update_faction_offer_buttons(map_screen, owner, set_offer, at_war, in_same_faction):
    """Update the faction buttons and return what each proposal can forecast."""
    my_faction = map_screen.nation_data[map_screen.player_country].get("faction", "")
    target_faction = map_screen.nation_data[owner].get("faction", "")
    i_am_leader = queries.is_faction_leader(map_screen.player_country, map_screen.nation_data)
    factions_disabled = queries.get_scenario_flag("disable_factions", c.DEFAULT_DISABLE_FACTIONS, map_screen.scenario_settings)

    # A puppet's alignment is its master's, both ways round: it may
    # not be invited in, and may not ask to join. Greyed out here so
    # the option never appears, rather than being refused later.
    they_are_free = queries.can_choose_own_faction(owner, map_screen.nation_data)
    i_am_free = queries.can_choose_own_faction(map_screen.player_country, map_screen.nation_data)

    # Keep membership controls clickable so refusal feedback is reachable.
    can_try_invite = bool(not factions_disabled and my_faction and not target_faction
                          and not at_war and they_are_free)
    can_try_req_join = bool(not factions_disabled and not my_faction and target_faction
                            and not at_war and i_am_free)
    can_kick = bool(not factions_disabled and in_same_faction and i_am_leader)
    can_create_fac = bool(not factions_disabled and not my_faction and not target_faction and not at_war)

    forecasts = [
        (map_screen.btn_fac_invite, "FACTION_INVITE",
         set_offer(map_screen.btn_fac_invite, "FACTION_INVITE", "INVITE", "Invite to Faction", "green", can_try_invite)),
        (map_screen.btn_fac_join_req, "JOIN_FACTION_REQ",
         set_offer(map_screen.btn_fac_join_req, "JOIN_FACTION_REQ", "JOIN REQ", "Req. Join Faction", "green", can_try_req_join)),
    ]
    set_offer(map_screen.btn_fac_kick, "KICK_FACTION_MEMBER", "KICK", "Kick from Faction", "red", can_kick)
    forecasts.append((map_screen.btn_fac_create, "CREATE_FACTION",
                      set_offer(map_screen.btn_fac_create, "CREATE_FACTION", "CREATE", "Create Faction", "blue", can_create_fac)))
    return forecasts


def _update_access_buttons(map_screen, owner, set_offer, at_war, in_same_faction):
    """Update the military access buttons and return whether a request can be forecast."""
    has_access_to_them = queries.has_military_access(map_screen.player_country, owner, map_screen.nation_data)
    they_have_access_to_me = queries.has_military_access(owner, map_screen.player_country, map_screen.nation_data)

    forecast_request = False
    if has_access_to_them:
        set_offer(map_screen.btn_cancel_mil_access, "CANCEL_MILITARY_ACCESS", "CANCEL ACCESS", "Cancel Mil. Access", "orange", True)
        set_btn(map_screen.btn_req_mil_access, False, False, "", "blue")
    else:
        set_btn(map_screen.btn_cancel_mil_access, False, False, "", "orange")
        can_req_access = not at_war and not in_same_faction
        forecast_request = set_offer(map_screen.btn_req_mil_access, "REQ_MILITARY_ACCESS", "REQ ACCESS", "Request Mil. Access", "blue", can_req_access)

    if they_have_access_to_me:
        set_offer(map_screen.btn_revoke_mil_access, "REVOKE_MILITARY_ACCESS", "REVOKE ACCESS", "Revoke Mil. Access", "red", True)
    else:
        set_btn(map_screen.btn_revoke_mil_access, False, False, "", "red")
    return forecast_request


def _update_foreign_country_buttons(map_screen, owner):
    at_war = queries.are_at_war(map_screen.player_country, owner, map_screen.nation_data)
    in_same_faction = queries.are_in_same_faction(map_screen.player_country, owner, map_screen.nation_data)
    pending_action, pending_turns = queries.get_diplomatic_status(map_screen.player_country, owner, map_screen.nation_data)

    is_unilateral_pending = pending_action in c.UNILATERAL_ACTIONS
    if is_unilateral_pending and pending_turns > 0:
        pending_action = ""
        pending_turns = 0

    def set_offer(button, action, status, label, color, allowed):
        """Show one offer button and return whether its reply can be forecast."""
        pending = pending_action == action
        if pending:
            label = f"UNDO {status}" if pending_turns == 0 else "WAITING..."
        set_btn(button, True, allowed or pending, label, color)
        return allowed and not pending

    _update_war_button(map_screen, owner, pending_action, pending_turns, at_war)

    target_wars = queries.get_enemies(owner, map_screen.nation_data)
    player_wars = queries.get_enemies(map_screen.player_country, map_screen.nation_data)
    can_join_wars = bool(in_same_faction and any(w for w in target_wars if w not in player_wars))
    forecast_join_wars = set_offer(map_screen.btn_join_wars, "JOIN_WARS", "JOIN WARS", "Join Wars", "orange", can_join_wars)

    can_call_to_arms = bool(in_same_faction and any(w for w in player_wars if w not in target_wars))
    forecast_call_to_arms = set_offer(map_screen.btn_call_to_arms, "CALL_TO_ARMS", "CALL TO ARMS", "Call to Arms", "red", can_call_to_arms)

    volunteer_state = _update_volunteer_buttons(map_screen, owner, pending_action, pending_turns)
    _update_guarantee_button(map_screen, owner, pending_action, pending_turns)
    can_forecast_attache = _update_attache_buttons(map_screen, owner, pending_action, pending_turns)

    faction_forecasts = _update_faction_offer_buttons(map_screen, owner, set_offer, at_war, in_same_faction)
    forecast_access = _update_access_buttons(map_screen, owner, set_offer, at_war, in_same_faction)

    # Forecast every offer this menu can send to the selected
    # country. Indicators are hidden while a button is performing
    # a different follow-up action (undo, recall, withdrawal,
    # etc.), because those actions do not ask for a fresh reply.
    predictions = (
        (map_screen.btn_join_wars, "JOIN_WARS", forecast_join_wars),
        (map_screen.btn_call_to_arms, "CALL_TO_ARMS", forecast_call_to_arms),
        *faction_forecasts,
        (map_screen.btn_req_mil_access, "REQ_MILITARY_ACCESS", forecast_access),
        (map_screen.btn_volunteers, volunteers.ACTION,
         volunteer_state not in (volunteers.AWAITING,
                                 volunteers.OUTBOUND,
                                 volunteers.DEPLOYED,
                                 volunteers.RETURNING)),
        (map_screen.btn_military_attache, military_attaches.ACTION, can_forecast_attache),
    )
    for button, action, applicable in predictions:
        set_bilateral_response_indicator(map_screen, button, owner,
                                         action, applicable)

    # HIDE ALLIANCE/FACTION BUTTONS IN BATTLE ROYALE
    if queries.get_scenario_flag("battle_royale", c.DEFAULT_BATTLE_ROYALE, map_screen.scenario_settings):
        for button in _foreign_action_buttons(map_screen):
            if button is not map_screen.btn_declare_war:
                button.visible = False


def _update_player_province_buttons(map_screen, owner):
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
            for button in _foreign_action_buttons(map_screen):
                set_btn(button, True, False, "Tactical: Disabled", "grey")
            return
        _update_foreign_country_buttons(map_screen, owner)

    else:
        set_orders_or_battle(map_screen, set_btn, has_player_units)


def update_button_states(map_screen):
    """Dynamically updates button visibility, colors, and text every frame using explicit attributes."""

    for el in map_screen.elements:
        el.visible = False

    layout_country_action_buttons(map_screen)

    is_sel = bool(map_screen.selected_province)

    if map_screen.selection_mode:
        _update_selection_mode_buttons(map_screen)
        return

    _update_view_toggles(map_screen)

    # A map can briefly be displayed after country selection has ended but
    # before a playable country has been assigned (for example, while a saved
    # or networked session is being handed off).  "None" is a sentinel, not a
    # nation_data key, so it must not enter the player diplomacy UI below.
    # Leave the map controls and a way to close the selection/exit available,
    # but expose no country-owned actions until the state has a real owner.
    has_player_country = map_screen.player_country in map_screen.nation_data
    is_thinking = map_screen.ai_is_thinking or map_screen.is_refreshing or map_screen.is_saving
    map_screen.btn_unit_events.visible = (
        not map_screen.is_editor and not map_screen.hide_resource_hud
        and (has_player_country or map_screen.player_country == "Spectator")
        and not is_thinking and not map_screen.viewing_ai_moves
        and not map_screen.show_player_ready_screen)
    map_screen.btn_unit_events.notification_count = map_screen._unit_event_unread
    if (not map_screen.is_editor
            and map_screen.player_country != "Spectator"
            and not has_player_country):
        _update_unassigned_viewer_buttons(map_screen, is_sel, is_thinking)
        return

    _update_unit_view_buttons(map_screen, is_sel, is_thinking)

    if map_screen.is_editor:
        _update_editor_buttons(map_screen, is_sel)
        return

    _update_turn_buttons(map_screen, is_sel, is_thinking)
    _update_gameplay_buttons(map_screen, is_sel, is_thinking)

    map_screen.btn_exit_to_menu.visible = not is_sel
    map_screen.btn_close_info.visible = is_sel
    map_screen.btn_realtime_details.visible = bool(map_screen.realtime_multiplayer) and not is_sel
    selected_owner = (map_screen.selected_province or {}).get("owner")
    map_screen.btn_view_foreign_politics.visible = bool(
        is_sel and not map_screen.is_editor
        and selected_owner != map_screen.player_country
        and selected_owner in map_screen.nation_data
        and selected_owner not in c.UNPLAYABLE_NATIONS)

    if is_sel:
        owner = map_screen.selected_province.get("owner", "Unclaimed")
        if map_screen.player_country == "Spectator":
            _update_spectator_province_buttons(map_screen, owner)
        else:
            _update_player_province_buttons(map_screen, owner)
