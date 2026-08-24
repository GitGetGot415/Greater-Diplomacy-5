import pygame
from map_logic.rendering import map_utils
from map_logic.turn_processing import edit_province_ownership
import data.constants as c
from map_logic.camera import camera_handler
from map_logic.setup import player_setup
from data import queries
from ui_elements import process_text_input
from map_logic.diplomacy import diplomacy_logic
from screens.map_related_screens import battle_screen

# The three panels that sit on the map at fixed screen rects: Buildings/Garrison,
# Diplomatic Info and the production queue overlay. Each publishes a rect and a
# scroll ceiling under these attribute prefixes, and all three want identical
# treatment -- block the map underneath, take the wheel, and be draggable. They
# were previously three copy-pasted blocks per behaviour, nine in total.
MAP_PANELS = ("sidebar", "diplomatic", "queue")


def _panel_rect(map_screen, name):
    return getattr(map_screen, f"{name}_scroll_rect", None)


def _panels_are_live(map_screen):
    """The panels only exist while a province is selected outside selection mode."""
    return bool(map_screen.selected_province) and not map_screen.selection_mode


def handle_map_events(map_screen, event):
    mx, my = pygame.mouse.get_pos()

    # --- POPUP INTERCEPT ---
    from ui import diplomatic_popups
    if diplomatic_popups.handle_events(map_screen, event):
        return

    # --- HOTSEAT MULTIPLAYER HIJACK ---
    if map_screen.show_player_ready_screen:
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if hasattr(map_screen, 'ready_btn_rect') and map_screen.ready_btn_rect.collidepoint(mx, my):
                map_screen.show_player_ready_screen = False
                
                # CRITICAL: Re-bake the relations/cores from the perspective of the new player!
                map_screen.refresh_relations_map() 
                map_screen.refresh_political_map() 
                map_screen.refresh_fog_map()
                
                map_screen.show_feedback(f"Turn started for {map_screen.player_country}")
        return # Block all other map events!
        
    # --- CONFIRMATION LOGIC HIJACK ---
    if map_screen.show_exit_confirmation:
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            # Hit-tests the rects map_renderer published while drawing the
            # dialog, rather than re-deriving them here in a different frame.
            yes_rect = getattr(map_screen, 'exit_yes_rect', None)
            no_rect = getattr(map_screen, 'exit_no_rect', None)
            if yes_rect and yes_rect.collidepoint(mx, my):
                map_screen.confirm_exit()
            elif no_rect and no_rect.collidepoint(mx, my):
                map_screen.cancel_exit()
        return # Block all other map events while confirming
        
    # --- SAVING HIJACK ---
    if map_screen.is_saving:
        return # Block all other map events while saving!

    # --- AI THINKING HIJACK ---
    if map_screen.ai_is_thinking:
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if hasattr(map_screen, 'force_skip_btn_rect') and map_screen.force_skip_btn_rect.collidepoint(mx, my):
                map_screen.force_skip_llm = True

                # --- IMPORTANT: Set the module-level abort flag so running threads instantly die ---
                from map_logic.ai import ai_handler
                ai_handler.FORCE_SKIP = True
                ai_handler.abort_ai_generation()

                map_screen.show_feedback("Forcing AI to skip LLM generation...")
            elif hasattr(map_screen, 'multi_turn_abort_btn_rect') and map_screen.multi_turn_abort_btn_rect.collidepoint(mx, my):
                if not map_screen.multi_turn_abort_requested:
                    map_screen.multi_turn_abort_requested = True
                    map_screen.show_feedback("Multi-turn processing will stop after this turn...")
        return # Block all other map events while AI is processing!
    
    # 1. UI Check (make sure the mouse can't go through the ui bars)
    
    # Always check the top and bottom bars
    on_ui = map_screen.top_bar_rect.collidepoint(mx, my) or map_screen.bot_bar_rect.collidepoint(mx, my)

    # Only check the side bars if they are actually being rendered
    side_ui_hidden = map_screen.selection_mode or map_screen.hide_raised_rect
    
    if not side_ui_hidden:
        if map_screen.raised_rect.collidepoint(mx, my) or map_screen.ui_background_rect.collidepoint(mx, my):
            on_ui = True

    # Buildings/Garrison, Diplomatic Info and the queue overlay sit on top of the
    # map at fixed screen rects, so treat them like any other UI bar: mousedown/
    # hover/camera-pan shouldn't reach through them to the map underneath.
    if _panels_are_live(map_screen):
        if any((r := _panel_rect(map_screen, name)) and r.collidepoint(mx, my) for name in MAP_PANELS):
            on_ui = True

    # --- SCROLLABLE INFO PANEL WHEEL INTERCEPT ---
    # Lets the mouse wheel scroll long Buildings/Garrison, Diplomatic Info, and
    # queue-overlay lists instead of always zooming the map camera. Only
    # relevant while those panels are actually on screen.
    if event.type == pygame.MOUSEWHEEL and _panels_are_live(map_screen):
        for name in MAP_PANELS:
            rect = _panel_rect(map_screen, name)
            if rect and rect.collidepoint(mx, my):
                max_scroll = getattr(map_screen, f"{name}_scroll_max", 0)
                current = getattr(map_screen, f"{name}_scroll_y", 0)
                setattr(map_screen, f"{name}_scroll_y",
                        max(0, min(current - event.y * c.SCROLL_STEP, max_scroll)))
                return

    # --- SCROLLABLE INFO PANEL DRAG INTERCEPT ---
    # Lets the same three panels be grabbed and dragged directly, alongside the
    # wheel scrolling above -- see GameState.handle_content_drag.
    if (event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP, pygame.MOUSEMOTION)
            and _panels_are_live(map_screen)):
        for name in MAP_PANELS:
            if map_screen.handle_content_drag(event, attr=f"{name}_scroll_y",
                                        rect_attr=f"{name}_scroll_rect",
                                        drag_attr=f"{name}_drag_state", lo=0,
                                        hi=getattr(map_screen, f"{name}_scroll_max", 0),
                                        invert=True):
                return

    # 2. Camera Controls (Always allow these so you can move while editing!)
    if event.type == pygame.MOUSEWHEEL:
        map_screen.camera.handle_input(event, map_screen, False)
        if map_screen.selected_province and not map_screen.selection_mode:
            camera_handler.center_camera_on_province(map_screen.camera, map_screen.selected_province["center"], c.SCREEN_WIDTH, c.SCREEN_HEIGHT, map_screen.total_ui_h)
        return

    map_screen.camera.handle_input(event, map_screen, on_ui)

    # 3. HOVER LOGIC (CRITICAL: Must run before painting)
    if not on_ui:
        # FIX: Pass the pre-calculated (mx, my) tuple instead of event.pos!
        map_screen.hovered_province = queries.get_clicked_province((mx, my), map_screen)
        
        # Block interaction with extreme hidden tiles
        if map_screen.hovered_province and hasattr(map_screen, 'extreme_hidden_provinces'):
            if map_screen.hovered_province["id"] in map_screen.extreme_hidden_provinces:
                map_screen.hovered_province = None
        
        if map_screen.hovered_province:
            curr_id = map_screen.hovered_province["id"]
            if curr_id != map_screen.last_hovered_id:
                map_screen.hover_glow_surf, map_screen.hover_glow_rect = map_utils.create_glow_surface(
                    map_screen.id_map, map_screen.hovered_province["map_color"]
                )
                map_screen.last_hovered_id = curr_id
        else:
            map_screen.last_hovered_id = None
            map_screen.hover_glow_surf = None
    else: 
        map_screen.hovered_province = map_screen.hover_glow_surf = None

    # --- UNDO / REDO LOGIC (Ctrl + Z / Ctrl + Y) ---
    if event.type == pygame.KEYDOWN:
        mods = pygame.key.get_mods()
        if mods & pygame.KMOD_CTRL or mods & pygame.KMOD_GUI:
            if event.key == pygame.K_z:
                if map_screen.is_editor:
                    queries.restore_editor_state(map_screen)
                    return
            elif event.key == pygame.K_y:
                if map_screen.is_editor:
                    queries.redo_editor_state(map_screen)
                    return

    # 4. EDITOR PAINTING LOGIC
    # We do this AFTER hover logic so we know what we are hovering over
    if map_screen.is_editor and not on_ui:
        # Capture the map state right before a new paint stroke begins
        if event.type == pygame.MOUSEBUTTONDOWN and event.button in (1, 3):
            queries.save_editor_state(map_screen)

        if pygame.mouse.get_pressed()[0]: # Left Click
            if map_screen.hovered_province:
                # --- NATION MODE ---
                if map_screen.editor_mode == "NATION":
                    if map_screen.hovered_province.get("owner") != map_screen.brush_nation:
                        if map_screen.hovered_province.get("owner") not in c.WATER_NATIONS:
                            edit_province_ownership.conquer_province(map_screen, map_screen.hovered_province, map_screen.brush_nation)
                
                # --- CORE MODE ---
                elif map_screen.editor_mode == "CORE":
                    if map_screen.hovered_province.get("owner") not in c.WATER_NATIONS:
                        # If painting with Unclaimed, wipe the tile
                        if map_screen.brush_nation in c.UNOWNED_LAND_OWNERS:
                            edit_province_ownership.clear_cores(map_screen, map_screen.hovered_province)
                        else:
                            edit_province_ownership.add_core(map_screen, map_screen.hovered_province, map_screen.brush_nation)
                            
                # --- CLAIM MODE ---
                elif map_screen.editor_mode == "CLAIM":
                    if map_screen.hovered_province.get("owner") not in c.WATER_NATIONS:
                        if map_screen.brush_nation in c.UNOWNED_LAND_OWNERS:
                            edit_province_ownership.clear_claims(map_screen, map_screen.hovered_province)
                        else:
                            edit_province_ownership.add_claim(map_screen, map_screen.hovered_province, map_screen.brush_nation)

                # --- BUILDING MODE ---
                elif map_screen.editor_mode == "BUILDING":
                    current_buildings = map_screen.hovered_province.get("buildings", [])
                    
                    if map_screen.brush_building == "None":
                        map_screen.hovered_province["buildings"] = []
                    else:                        
                        # Stop Advanced Buildings on empty tiles
                        is_advanced = "Refinery" in map_screen.brush_building or "Recruitment" in map_screen.brush_building
                        if is_advanced and not queries.has_basic_factory(map_screen.hovered_province):
                            map_screen.show_feedback("Requires a Basic Factory first!")
                        else:
                            # Logic: Workshops/Factories are in the same "industrial" category
                            is_industrial = "Workshop" in map_screen.brush_building or "Factory" in map_screen.brush_building
                            is_recruitment = "Recruitment" in map_screen.brush_building
    
                            new_list = []
                            for b in current_buildings:
                                # Keep existing building IF it's not the same type we are placing
                                # AND (if placing industrial) it's not also industrial
                                keep = True
                                if is_industrial and ("Workshop" in b or "Factory" in b):
                                    keep = False
                                if "Refinery" in map_screen.brush_building and "Refinery" in b:
                                    keep = False
                                if is_recruitment and "Recruitment" in b:
                                    keep = False
    
                                if keep: new_list.append(b)
    
                            if map_screen.brush_building not in new_list:
                                new_list.append(map_screen.brush_building)
    
                            map_screen.hovered_province["buildings"] = new_list

                # --- RESOURCE MODE ---
                elif map_screen.editor_mode == "RESOURCE":
                    if map_screen.brush_resource_type == "None":
                        # Wipe all resources if the "None" brush is used
                        map_screen.hovered_province["resources"] = {}
                    else:
                        # Ensure resources is a dictionary
                        if not isinstance(map_screen.hovered_province.get("resources"), dict):
                            map_screen.hovered_province["resources"] = {}
                        
                        map_screen.hovered_province["resources"][map_screen.brush_resource_type] = map_screen.brush_resource_amount
        
        if pygame.mouse.get_pressed()[2]: # Right Click
            if map_screen.hovered_province:
                if map_screen.hovered_province.get("owner") not in c.WATER_NATIONS:
                    
                    if map_screen.editor_mode == "CORE":
                        edit_province_ownership.remove_core(map_screen, map_screen.hovered_province, map_screen.brush_nation)
                    elif map_screen.editor_mode == "CLAIM":
                        edit_province_ownership.remove_claim(map_screen, map_screen.hovered_province, map_screen.brush_nation)
                    else:
                        map_screen.brush_nation = map_screen.hovered_province.get("owner", "Unclaimed")
                        map_screen.show_feedback(f"Picked: {map_screen.brush_nation}")

        # Unit placement logic
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if map_screen.hovered_province and map_screen.editor_mode == "UNIT":
                if map_screen.brush_unit == "None":
                    map_screen.hovered_province["units"] = []
                    map_screen.show_feedback("Units cleared from province")
                elif map_screen.brush_unit == "Convoy":
                    from ui.editor_menus import open_convoy_converter
                    open_convoy_converter(map_screen, map_screen.hovered_province)
                elif map_screen.brush_unit == "----------":
                    pass
                else:
                    owner = map_screen.hovered_province.get("owner", "Unclaimed")
                    if owner in c.UNPLAYABLE_NATIONS:
                        map_screen.show_feedback("Cannot place units in unowned territory!")
                    else:
                        new_unit = queries.create_unit_dict(map_screen.brush_unit, owner, queries.get_unit_library())
                        map_screen.hovered_province.setdefault("units", []).append(new_unit)
                        map_screen.show_feedback(f"Placed {map_screen.brush_unit} for {owner}")
        
        # RETURN HERE: This stops the code from reaching the "Select Province" logic below
        return

    # 5. COUNTRY SELECTION MODE (Scenarios)
    if map_screen.selection_mode:
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if not map_screen.pending_selection:
                if hasattr(map_screen, 'se_checkbox_rect') and map_screen.se_checkbox_rect.collidepoint(mx, my):
                    if queries.scenario_has_scripted_events(map_screen.nation_data):
                        if queries.toggle_scenario_flag(map_screen.scenario_settings, "use_scripted_events", c.DEFAULT_USE_SCRIPTED_EVENTS):
                            map_screen.show_feedback("Scripted Events: ON")
                        else:
                            map_screen.show_feedback("Scripted Events: OFF")
                    return

            if map_screen.pending_selection:
                if hasattr(map_screen, 'confirm_rect') and map_screen.confirm_rect.collidepoint(mx, my):
                    player_setup.confirm_player_country(map_screen)
                    # Refresh the fog map as soon as the player officially takes control of the country
                    map_screen.refresh_fog_map()
                    map_screen.update_country_centers()
                elif hasattr(map_screen, 'cancel_rect') and map_screen.cancel_rect.collidepoint(mx, my):
                    player_setup.cancel_selection(map_screen)
                return  # <--- CRITICAL FIX: Stops any clicks on the map behind the popup
                
            if map_screen.hovered_province:
                # --- TACTICAL SELECTION ROUTING ---
                if map_screen.tactical_mode:
                    player_setup.select_tactical_unit(map_screen, map_screen.hovered_province)
                else:
                    player_setup.select_player_country(map_screen, map_screen.hovered_province)
        return

    # --- Direct Map Message Editing ---
    # Moved ABOVE the "STANDARD GAME SELECTION" return block!
    if map_screen.selected_province:
        owner = map_screen.selected_province.get("owner")
        is_foreign = queries.is_foreign_playable(owner, map_screen.player_country, map_screen.nation_data)
        if is_foreign:
            # MAIL BOX! MAIL BOX! MAIL BOX!
            
            mail_rect = pygame.Rect(*c.PROVINCE_UI["mail_box"])
            
            # 1. Handle clicking the box to activate/deactivate it
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if mail_rect.collidepoint(event.pos):
                    if map_screen.tactical_mode:
                        map_screen.show_feedback("Tactical Mode: Cannot send messages directly.")
                        map_screen.mail_input_active = False
                    else:
                        map_screen.mail_input_active = True
                else:
                    map_screen.mail_input_active = False
            
            # 2. Handle typing and sending if the box is active
            elif map_screen.mail_input_active:
                if map_screen.tactical_mode:
                    map_screen.mail_input_active = False
                else:
                    map_screen.mail_draft_text, status = process_text_input(
                        event, map_screen.mail_draft_text, max_length=c.MAX_MAIL_DRAFT_LENGTH
                    )
                    
                    if status == "SUBMIT":
                        draft = map_screen.mail_draft_text.strip()
                        if draft:
                            msg = diplomacy_logic.queue_text_message(map_screen.nation_data, map_screen.player_country, owner, draft)
                            map_screen.show_feedback(msg)
                        else:
                            diplomacy_logic.cancel_text_message(map_screen.nation_data, map_screen.player_country, owner)
                            map_screen.show_feedback("Draft cleared.")
                        map_screen.mail_input_active = False

    # 6. STANDARD GAME SELECTION
    # Ignore clicks if a province is already selected, or if we are watching AI moves
    if map_screen.selected_province or map_screen.viewing_ai_moves:
        return

    if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
        if map_screen.hovered_province:
            map_screen.selected_province = map_screen.hovered_province
            camera_handler.center_camera_on_province(map_screen.camera, map_screen.selected_province["center"], c.SCREEN_WIDTH, c.SCREEN_HEIGHT, map_screen.total_ui_h)

            owner = map_screen.selected_province.get("owner")
            map_screen.mail_draft_text = queries.get_message_draft(map_screen.player_country, owner, map_screen.nation_data)

            # Classic: a click only ever opens the plain province menu -- see
            # navigate_view_mode. Jumping straight into Orders/Battle/Production
            # is a Preemptive-only shortcut.
            if c.MAP_NAVIGATION_MODE != "CLASSIC":
                navigate_view_mode(map_screen, map_screen.secondary_mode)


def is_classic_navigation():
    return c.MAP_NAVIGATION_MODE == "CLASSIC"


def navigate_view_mode(map_screen, mode, origin=None):
    """Sets the map's view mode and, in Preemptive navigation, jumps straight
    to whatever screen that mode implies for the selected province: Orders (or
    Battle, if the tile is fighting) for UNITS, Production for ECONOMY.
    RESOURCES/BLANK have no screen of their own, so from anywhere but the map
    itself they just land back on the plain province menu (the Map screen).

    In Classic navigation this only ever sets the view mode -- switching it
    never changes which screen is showing, wherever the row that called this
    is drawn (Map, Orders, Production, Battle). Orders/Battle/Production are
    reached only through their own explicit buttons there -- see
    go_to_orders_screen/go_to_battle_screen/go_to_production_screen below.

    This is for the view-mode row's own buttons (and a plain tile click) only.
    The Orders/Production keybinds jump independently of Classic/Preemptive --
    see handle_view_mode_keybind.
    """
    origin = origin or map_screen
    map_screen.set_view_mode(mode)
    _resync_view_mode_row(origin)
    if is_classic_navigation():
        return
    _jump_to_view_mode_screen(map_screen, mode, origin)


def handle_view_mode_keybind(map_screen, mode, action, origin=None):
    """Q/W. Always sets the view mode; also jumps straight to the screen it
    implies (Orders/Battle for UNITS, Production for ECONOMY) when the
    Keybinds screen's "change screen with this keybind" toggle for `action`
    ("ORDERS" or "ECONOMY") is on -- see queries.get_keybind_changes_screen.

    Deliberately independent of Classic/Preemptive map navigation
    (navigate_view_mode): a Classic player can still want Q/W to jump, and a
    Preemptive one can still want them not to, without changing how a click or
    the view-mode row's own buttons behave.
    """
    origin = origin or map_screen
    map_screen.set_view_mode(mode)
    _resync_view_mode_row(origin)
    if queries.get_keybind_changes_screen(action):
        _jump_to_view_mode_screen(map_screen, mode, origin)


def _resync_view_mode_row(origin):
    """Rebuilds `origin`'s own elements right after its view mode changes.

    Orders/Production/Battle each build their copy of the view-mode row once,
    inside their own refresh_ui, and only re-sync the yellow "selected" border
    (view_mode_buttons.sync_highlight) when that runs again -- unlike Map,
    which re-reads secondary_mode fresh every frame in update_button_states.
    Without this, clicking one of those buttons while staying on the same
    screen (always true in Classic navigation; also true in Preemptive for the
    "already on the screen this mode implies" cases in
    _jump_to_view_mode_screen) changed the mode but left the highlight showing
    whatever was selected when the screen last rebuilt. A no-op on Map itself,
    whose refresh_ui does nothing -- it doesn't need this.
    """
    origin.refresh_ui()


def _jump_to_view_mode_screen(map_screen, mode, origin=None):
    """Shared by navigate_view_mode's Preemptive branch and by
    handle_view_mode_keybind: jumps to whatever screen `mode` implies for the
    selected province.

    `origin` is whichever screen the click/keypress came from: the Map itself
    (the default), or one of the screens layered over it (Orders, Production)
    that carry their own copy of this same button row so switching view types
    doesn't require backing out to the map first. Transitions are issued
    against `origin`, not always `map_screen` -- flip_state only reacts to the
    *currently active* screen's next_state/done, and while Orders or
    Production is up, that isn't map_screen.
    """
    origin = origin or map_screen
    province = map_screen.selected_province

    def to_map():
        if origin is not map_screen:
            origin.go_to("MAP")

    def to(state_name):
        if origin is map_screen:
            map_screen.change_state(state_name)
        else:
            origin.go_to(state_name)

    if not province:
        to_map()
        return

    if mode == "UNITS":
        if not queries.is_province_visible(map_screen, province["id"]):
            to_map()
            return
        if queries.is_province_in_active_combat(province, map_screen.nation_data):
            # Battle carries its own copy of this row now too, so clicking
            # Units there while the tile is still fighting must not stack a
            # second modal on top of the one already showing it.
            already_here = (isinstance(origin, battle_screen.Battle_Screen)
                           and origin.province is province)
            if not already_here:
                battle_screen.open_battle_screen(map_screen, origin_screen=origin)
        else:
            # Orders_Screen already renders fine with nothing to show -- an
            # empty unit list just skips the panel -- so an empty tile still
            # opens it rather than bouncing back to the map.
            to("ORDERS")
    elif mode == "ECONOMY":
        owner = province.get("owner")
        owned = owner == map_screen.player_country or map_screen.player_country == "Spectator"
        if not map_screen.tactical_mode and owned and not queries.is_water_province(province):
            to("PRODUCTION")
        else:
            to_map()
    else:
        to_map()


# The province-menu sidebar's three action buttons (Give Orders, Manage/View
# Battle, Production). In Preemptive these route through navigate_view_mode,
# same as the view-mode row, so clicking them also keeps it in sync. In
# Classic they are the *only* way to reach these screens, and jump straight
# there unconditionally -- there is no view mode to keep in sync with.

def go_to_orders_screen(map_screen):
    """Give Orders sidebar button."""
    if is_classic_navigation():
        map_screen.change_state("ORDERS")
    else:
        navigate_view_mode(map_screen, "UNITS")


def go_to_battle_screen(map_screen):
    """Manage/View Battle sidebar button -- shares its slot with Give Orders,
    swapped in whenever the tile is fighting."""
    if is_classic_navigation():
        battle_screen.open_battle_screen(map_screen)
    else:
        navigate_view_mode(map_screen, "UNITS")


def go_to_production_screen(map_screen):
    """Production sidebar button."""
    if is_classic_navigation():
        map_screen.change_state_if_owned("PRODUCTION", requires_land=True)
    else:
        navigate_view_mode(map_screen, "ECONOMY")