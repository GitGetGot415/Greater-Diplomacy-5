# Standard Library & Third Party

# Load real-time networking inside its callbacks. This map screen also serves local and browser games.

import asyncio
import traceback
import threading
import re
import json
from datetime import datetime
from types import MappingProxyType

import pygame
import os
import sys

# Add the parent directory (project root) to the Python path so it can find the 'data' module
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Data & Constants
import data.constants as c
from data.io import settings_schema
from data import queries
from ui.dialogs import pickers
from ui.dialogs import file_exchange
from data.state_access import StateAccess
from data.map import load_map, save_map
from data.platform import LoadingSteps, run_background

# Core Game State & Global UI Elements
from ui.navigation.screen import Screen
from map_logic.system32 import turn_manager, unit_events
from screens.game import map_buttons, map_input
# Game Logic & Rendering Submodules
from ui.widgets import ui_elements
from ui import sound_effects
from ui.widgets.ui_elements import Button
from ui.panels import diplomatic_popups, army_panel
from screens.editors import menus as editor_menus
from ui.camera.camera_handler import MapCamera
from ui.camera import camera_handler
from map_logic.diplomacy import diplomacy_messages, guarantees, war_actions
from map_logic.random_map import random_map_generator
from ui.rendering import map_renderer, overlay_renderer, refresh_map
from ui.rendering.font_manager import fonts
from ui.rendering.country_names import update_country_centers as calc_country_centers
from screens.setup import player_setup
from map_logic import custom_battle as tactical_battle

from data.io import country_io
from ui import dialogs
from ui.panels import realtime_status_panel, sidebar_info
from map_logic.diplomacy import diplomacy_lifecycle
from map_logic.system32 import economy_processor, turn_processor
from map_logic.ai import ai_handler
from map_logic.actions import unit_actions
from ui.information import feedback_text, tooltip

MAX_Y_TILT_FACTOR = 0.0 # The maximum compression of the Y axis (0.6 = 60% of original height)


def _delete_relay_safely(token, droplet_id, firewall_id=None):
    """Best-effort cleanup must never delay leaving a finished match."""
    try:
        from data.multiplayer.realtime.relay import destroy_temporary_relay
        destroy_temporary_relay(token, droplet_id, firewall_id)
    except Exception:
        # The host can still delete the tagged Droplet in DigitalOcean if the
        # provider API is temporarily unreachable during game shutdown.
        pass


# Map camera and unit-view values. Button layout values are in screens/game/map_buttons.py.
# How far (in screen pixels) to shift the camera left when a province is selected,
# so the orders panel doesn't cover the unit the camera just centered on.
ORDERS_PANEL_CAMERA_X_OFFSET = 0

# Keep the initial country framing just above the strategic compression level:
# ungrouped units remain visible without opening at an overly close zoom.
COUNTRY_FOCUS_UNIT_ZOOM_MARGIN = 0.1

UNIT_VIEW_ANIMATION_MS = 100


class Map(StateAccess, Screen):
    _popup_presentation_revision = None

    # Network connection state. main.py and the multiplayer screens attach it
    # when a networked game starts. Every other game keeps these defaults.
    realtime_session = None
    realtime_player_id = None
    realtime_client = None
    realtime_server = None
    realtime_port_mapping = None
    realtime_temporary_relay = None
    realtime_relay_token = ""
    realtime_connection_error = ""
    realtime_submission_pending = False
    _realtime_snapshot_turn = None
    _realtime_snapshot_phase = None
    _realtime_draft_dirty = True
    _realtime_draft_fingerprint = None
    multiplayer_host_mode = False
    multiplayer_player_key = ""

    # Screens and panels set these on first use. Reads before that get these values.
    unit_view_filter = queries.DEFAULT_UNIT_VIEW_FILTER
    unit_view_bar_collapsed = False
    unit_view_bar_progress = 1.0
    unit_view_bar_offset = 0
    unit_view_animation_start = None
    unit_view_animation_from = 1.0
    btn_unit_view_toggle = None
    _ignore_left_until_release = False
    _ignore_right_until_release = False
    _unit_roster_cache = None
    partial_visible_provinces = None
    extreme_hidden_provinces = frozenset()
    compact_army_unit_object_ids = frozenset()
    country_action_buttons = ()
    ai_response_images = MappingProxyType({})
    unit_view_buttons = MappingProxyType({})
    deal_drafts = None
    hovered_combat_bubble = None
    strategic_unit_fade_states = None
    army_custom_symbol_state = None
    army_panel_scroll_y = 0
    army_panel_visible_in_orders = False
    # The turn loading screen's model threads panel (ui/panels/llm_threads_panel.py).
    llm_threads_open = False
    llm_threads_selected = None
    llm_threads_scroll = 0
    _army_tray_right_click_active = False
    sidebar_scroll_y = 0
    sidebar_scroll_max = 0
    diplomatic_scroll_y = 0
    diplomatic_scroll_max = 0
    viewing_research_country = ""
    viewing_research_mode = "VIEW"
    btn_realtime_details = None
    exit_yes_rect = None
    exit_no_rect = None
    _viewport_scale_cache = None
    _minimap_image_cache = None
    _hover_glow_scale_cache = None
    _badge_state_cache = None

    def refresh_ui(self):
        # Screen can refresh during construction before Map has a selection.
        province = getattr(self, "selected_province", None)
        if province is not None:
            sidebar_info.prepare_unit_roster(self, province)

    def __init__(self, load_path=None, is_scenario=False, is_random=False, force_editor=False, random_settings=None, map_settings=None, num_players=1, history_turn=None, skip_initial_income=False):
        for _ in self._initialize_steps(
                load_path, is_scenario, is_random, force_editor, random_settings,
                map_settings, num_players, history_turn, skip_initial_income):
            pass

    @classmethod
    def loading_steps(cls, **settings):
        """Return the completed map after yielding its loading stages."""
        game_map = cls.__new__(cls)
        return LoadingSteps(game_map._load_steps(**settings), cls.loading_step_count(**settings))

    @classmethod
    def loading_step_count(cls, *, load_path=None, is_random=False, random_settings=None, **settings):
        # Initialization, map controls, game controls, country labels, and economy.
        setup_stages = 5
        randomizing = bool(is_random and random_settings)
        asset_path = random_settings["map_path"] if randomizing else load_path
        return (setup_stages + len(cls.ALL_MAP_LAYERS) + int(randomizing)
                + load_map.map_asset_loading_step_count(asset_path))

    def _load_steps(self, **settings):
        yield from self._initialize_steps(**settings)
        return self

    def _initialize_steps(self, load_path=None, is_scenario=False, is_random=False,
                          force_editor=False, random_settings=None, map_settings=None,
                          num_players=1, history_turn=None, skip_initial_income=False):
        yield "Preparing Map..."
        super().__init__()
        self.presentation_enabled = True

        self.history_turn = history_turn
        self.num_players = num_players
        self._init_session_state()
        self._init_view_mode(load_path, is_scenario, force_editor)

        # --- 2. Data Loading ---
        if is_random and random_settings:
            self.random_settings = random_settings
            yield from load_map.load_map_asset_steps(self, random_settings["map_path"], scenario_settings=map_settings)
            self.time_manager.year = random_settings["year"]
        else:
            yield from load_map.load_map_asset_steps(self, load_path, scenario_settings=map_settings)

        yield "Preparing Map Controls..."
        self._init_ui_layout()
        self._init_selection_state()

        self.relations_map = self.id_map.copy()
        self.factions_map = self.id_map.copy()
        self.faction_territories_map = self.id_map.copy()

        # --- 3. RUN THE RANDOMIZER ---
        if is_random and random_settings:
            yield "Randomizing Countries..."
            random_map_generator.randomize_all_provinces(self, random_settings)

        # --- 4. REFRESH MAPS ---
        for layer in self.ALL_MAP_LAYERS:
            yield f"Rendering {layer.replace('_', ' ').title()} Map..."
            self.refresh_map_layers(layer)

        yield "Preparing Game Controls..."
        map_buttons.render_buttons(self)

        diplomacy_lifecycle.normalize_diplomacy_channels(self.nation_data)

        # A loaded save may have been written immediately before a faction join
        # or war was resolved. Reconcile once on load so its UI never advertises
        # a guarantee or military-access grant that is no longer valid.
        guarantees.reconcile(self.nation_data)
        war_actions.reconcile_military_access(self.nation_data)

        yield "Preparing Country Labels..."
        self.update_country_centers()

        # --- 5. INITIALIZE INCOME ---
        # Provide 1 turn of simulated income so nations don't spawn with 0 resources
        yield "Preparing Economy..."
        economy_processor.initialize_income(self, skip=skip_initial_income)
        # Build unit membership after loading, before any planning-frame draw.
        overlay_renderer._unit_render_index(self)

    def _init_session_state(self):
        self.country_actions_scroll_rect = pygame.Rect(
            map_buttons.DIPLO_BTN_X, map_buttons.ACTION_BTN_START_Y, map_buttons.ACTION_SCROLL_WIDTH, map_buttons.ACTION_SCROLL_HEIGHT)
        self.country_actions_scroll_y = 0
        self.country_actions_scroll_max = 0

        self.active_players = [] # Usually empty on boot unless loaded from save
        self.current_player_index = 0
        self.show_player_ready_screen = False
        self.unit_event_log = {"turn": 0, "events": []}
        self.unit_event_read_turns = {}
        # Local display preferences reset after each completed turn.
        self.unit_event_filter = None
        self.unit_event_filter_turn = None
        self._unit_event_view = []
        self._unit_event_unread = 0
        # Every playable map session, including saves and multiplayer sessions,
        # gets a chance to show the tutorial after it has finished loading.
        # The persisted setting is checked when that moment arrives; editor
        # maps deliberately never arm the player-facing tutorial.
        self.show_navigation_intro_when_ready = False
        self.navigation_intro_popup = None

       # --- UI DISPLAY OVERRIDES ---
        self.hide_raised_rect = False
        self.hide_top_info = False
        # Separate from hide_top_info so map-layered panels can suppress only
        # the large top-left flag without also removing the country/date text.
        self.hide_flag = False
        self.hide_tooltip = False
        self.hide_resource_hud = False
        self.hide_minimap = False
        # Presentation only: saves and multiplayer snapshots never persist it.
        self.unit_view_filter = queries.DEFAULT_UNIT_VIEW_FILTER
        self.unit_view_bar_collapsed = False
        self.unit_view_bar_progress = 1.0
        self.unit_view_bar_offset = 0
        self.unit_view_animation_start = None
        self.unit_view_animation_from = 1.0
        self.centers_need_update = False
        # Editor brushes may touch many provinces in one drag.  Queue the
        # expensive derived map surfaces and rebuild each affected layer once
        # when the stroke ends, while invalidating the displayed cache at the
        # first changed tile so it can never keep showing old pixels.
        self._editor_visual_refresh_layers = set()
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
        # (province, friendly roster, enemy roster) handed to the tactical preview, and the
        # last turn whose battle was offered, so one turn opens at most one preview.
        self.tactical_battle_request = None
        self._tactical_battle_turn = None

        # --- MULTI-TURN FLAGS ---
        self.multi_turn_processing_complete = False
        self.multi_turns_total = 0
        self.multi_turns_completed = 0
        self.multi_turn_abort_requested = False

        # --- NEW PROGRESS BAR TRACKERS ---
        self.loading_status_text = "Waiting..."
        self.proactive_tasks_total = 0
        self.proactive_tasks_completed = 0
        self.movement_tasks_total = 0
        self.movement_tasks_completed = 0
        self.proactive_llm_tasks_total = 0
        self.proactive_llm_tasks_completed = 0
        self.proactive_llm_tasks = []
        # Each AI nation's menu of legal moves, held between the proactive
        # pass that builds it and the director pass that picks from it.
        self.proactive_choices = []
        self.responsive_tasks_total = 0
        self.responsive_tasks_completed = 0
        self.letters_total = 0
        self.letters_completed = 0
        self.diplomatic_popups = []

        # Per-turn AI map snapshot (map_logic/ai/ai_world.py). Only ever set
        # while the AI passes of prepare_turn are running; None the rest of the
        # time, which is what stops anything reading last turn's answers.
        self.ai_world = None

        # Initialize variables previously hidden by getattr
        self.fog_map = None
        # Transient surfaces keyed by their resolved pixel inputs. Refreshes
        # reuse unchanged layers; saves and multiplayer state omit these.
        self._map_surface_cache = {}
        self._fog_surface_cache = None
        # The right-clicked country's view of the relations map, if any.
        self._relations_view = None
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

        # Country selection keeps country names visible, but still shows units
        # so the player can assess the nation they are about to command.
        self.show_country_names = True

    def _init_view_mode(self, load_path, is_scenario, force_editor):
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
        else:
            self.show_navigation_intro_when_ready = True

        if self.selection_mode:
            self.set_country_selection_view_defaults()
        elif self.load_path and not self.is_editor:
            # A resumed game is already operational; it should not reopen in
            # the country-selection presentation.
            self.set_play_view_defaults()

        self.painting_active = False
        self.editor_selection_tool = "BRUSH"
        self.brush_nation = "Unclaimed"
        self.viewing_ai_moves = False
        self.skip_ai_view = False

    def _init_ui_layout(self):
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
        if self.load_path and not self.selection_mode and not self.is_editor:
            self.focus_camera_on_country(self.player_country)

        self.active_map = self.political_map if self.base_layer == "POLITICAL" else self.terrain_map
        self.map_mode = self.base_layer

    def _init_selection_state(self):
        self.selected_province = self.hovered_province = self.last_hovered_id = None
        self._tooltip_building_stamp = None
        self._tooltip_building_yields = []
        self.hover_glow_surf = self.hover_glow_rect = None
        self.hovered_unit_stack = None
        # Map-unit selection is presentation state only. Unit dictionaries
        # remain the persisted source of truth; object identities are stable
        # for this map instance and are deliberately discarded on snapshots.
        self.selected_unit_ids = set()
        self.unit_stack_hitboxes = []
        self.unit_hover_hitboxes = []
        # Presentation-derived data is valid only until an explicit state or
        # order boundary.  Render helpers use this revision instead of
        # re-running simulations on every planning frame.
        self._presentation_cache_revision = 0
        self._combat_bubble_records_cache = None
        self._combat_unit_view_cache = None
        self._unit_render_index_cache = None
        self._unit_roster_cache = {}
        unit_events.refresh_presentation(self)
        self.unit_selection_drag = None
        self.army_group_transition_states = {}
        # Army-card editing is local UI state like selection.  The edited
        # record itself still lives in nation_data and is saved/synchronized.
        self.army_editor_state = None
        self.unassigned_army_card = None
        self.unassigned_army_country = None
        self._ignore_left_until_release = False
        self._ignore_right_until_release = False
        # Where a right-press began, to tell a Relations click from a pan.
        self._relations_click_start = None
        self._unit_selection_turn = self.time_manager.total_turns
        self._unit_selection_player = self.player_country
        self.feedback_text = ""
        self.feedback_timer = 0

        self.show_exit_confirmation = False
        self.confirm_box_rect = pygame.Rect(0, 0, 400, 200)

    def open_tactical_battle(self):
        """Once per turn, put a tactical player whose unit is fighting into battle preview.

        Hostile artillery alone cannot fight back: the player wins at once without a battle.
        """
        if (not self.tactical_mode or self.player_unit is None or self.multiplayer_mode
                or self.realtime_multiplayer
                or self._tactical_battle_turn == self.time_manager.total_turns):
            return
        self._tactical_battle_turn = self.time_manager.total_turns
        province = next((tile for tile in self.map_data.values()
                         if any(unit is self.player_unit for unit in tile.get("units", []))), None)
        if province is None:
            return
        library = queries.get_unit_library(self)
        forces = tactical_battle.campaign_forces(self.player_unit, province, self.nation_data, library)
        if forces is None:
            return
        if not forces[1]:
            tactical_battle.win_against_artillery(self.player_unit, province, self.nation_data, library)
            player_setup.settle_tactical_tile(self, province)
            return
        self.tactical_battle_request = (province, *forces)
        self.go_to("CUSTOM_BATTLE")

    def draw_clean_map_background(self, surface):
        """Temporarily hides UI elements and province selection to draw a clean map background."""
        temp_prov = self.selected_province
        self.selected_province = None

        # Save previous states to be completely safe
        prev_raised = self.hide_raised_rect
        prev_tooltip = self.hide_tooltip
        prev_hud = self.hide_resource_hud
        prev_mini = self.hide_minimap
        prev_flag = self.hide_flag

        self.hide_raised_rect = True
        self.hide_tooltip = True
        self.hide_resource_hud = True
        self.hide_minimap = True
        # Screens drawn over the map are not about the player's own country.
        self.hide_flag = True

        self.additional_draw(surface)

        # Restore original states
        self.hide_flag = prev_flag
        self.hide_raised_rect = prev_raised
        self.hide_tooltip = prev_tooltip
        self.hide_resource_hud = prev_hud
        self.hide_minimap = prev_mini
        self.selected_province = temp_prov

    # --- Properties ---
    @property
    def text_input_active(self):
        return bool(self.mail_input_active or self.army_editor_state) or super().text_input_active

    @property
    def player_manpower(self):
        return self.nation_data.get(self.player_country, {}).get("manpower", 0)
    @player_manpower.setter
    def player_manpower(self, value):
        if self.player_country in self.nation_data: self.nation_data[self.player_country]["manpower"] = value

    @property
    def player_materials(self):
        return self.nation_data.get(self.player_country, {}).get("materials", 0)

    @property
    def player_fuel(self):
        return self.nation_data.get(self.player_country, {}).get("fuel", 0)

    def set_camera_tilt(self, val):
        """Callback for the manual camera tilt slider."""
        self.camera_tilt_slider_val = val

        # Grab the old tilt before we update it to calculate the difference
        old_tilt = self.camera.manual_tilt_factor
        new_tilt = 1.0 - (val * (1.0 - MAX_Y_TILT_FACTOR))

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
        map_buttons.update_button_states(self)

    def set_view_mode(self, mode):
        now = pygame.time.get_ticks()
        self._advance_unit_view_animation(now)
        previous_target = self._unit_view_bar_target()
        self.secondary_mode = mode
        if self._unit_view_bar_target() != previous_target:
            self._start_unit_view_animation(now)
        tooltip.prepare_building_yields(self)
        self.show_feedback(f"View: {mode}")

    def _unit_view_bar_target(self):
        """Keep manual collapse separate from automatic hiding outside Units view."""
        return float(self.secondary_mode == "UNITS" and not self.unit_view_bar_collapsed)

    def toggle_unit_view_bar(self):
        """Hide or show the filter strip without changing the selected filter."""
        now = pygame.time.get_ticks()
        self._advance_unit_view_animation(now)
        self.unit_view_bar_collapsed = not self.unit_view_bar_collapsed
        self._start_unit_view_animation(now)
        map_buttons.update_button_states(self)

    def _start_unit_view_animation(self, now):
        """Start or reverse the strip from its current position."""
        self.unit_view_animation_from = self.unit_view_bar_progress
        target = self._unit_view_bar_target()
        self.unit_view_animation_start = now if self.unit_view_bar_progress != target else None
        # A moving control must not retain a pending mouse press.
        for button in self.unit_view_buttons.values():
            button.is_pressed = False

    def _advance_unit_view_animation(self, now=None):
        """Advance the local strip animation without changing game state."""
        if self.unit_view_animation_start is None:
            return
        if now is None:
            now = pygame.time.get_ticks()
        elapsed = max(0, now - self.unit_view_animation_start)
        fraction = min(1.0, elapsed / UNIT_VIEW_ANIMATION_MS)
        target = self._unit_view_bar_target()
        self.unit_view_bar_progress = (self.unit_view_animation_from
                                       + (target - self.unit_view_animation_from) * fraction)
        if fraction >= 1.0:
            self.unit_view_animation_start = None

    def set_unit_view_filter(self, view_filter):
        """Switch the local unit overlay without changing any world state."""
        if view_filter not in queries.UNIT_VIEW_FILTERS:
            raise ValueError(f"Unknown unit view filter: {view_filter}")
        if view_filter != self.unit_view_filter:
            self.unit_view_filter = view_filter
            self._unit_render_index_cache = None
            self._combat_unit_view_cache = None
            # Hidden selections and an old compression animation must not
            # keep issuing orders or drawing units from the previous filter.
            self.clear_map_unit_selection()
            self.army_group_transition_states.clear()
            self.unit_stack_hitboxes = []
            self.unit_hover_hitboxes = []
            self.hovered_unit_stack = None
            overlay_renderer._unit_render_index(self)
        map_buttons.update_button_states(self)

    def set_play_view_defaults(self):
        """Apply the player-facing map view after country selection finishes."""
        self.sec_idx = self.secondary_modes.index("UNITS")
        self.secondary_mode = "UNITS"
        self.show_country_names = False

    def set_country_selection_view_defaults(self):
        """Apply the strategic country-picker's uncluttered political view."""
        self.sec_idx = self.secondary_modes.index("BLANK")
        self.secondary_mode = "BLANK"
        self.show_country_names = True

    def set_tactical_view_defaults(self):
        """Apply the unit-focused view used while choosing or playing tactically."""
        self.sec_idx = self.secondary_modes.index("UNITS")
        self.secondary_mode = "UNITS"
        self.show_country_names = False

    def focus_camera_on_country(self, country_id, animate=False):
        """Frame a country's core-territory center at the unit-visible zoom."""
        center = queries.get_country_map_center(
            country_id, self.map_data, self.loop_map, self.map_w)
        if center is None:
            return False

        self.focus_camera_on_position(center, animate)
        return True

    def focus_camera_on_position(self, center, animate=False):
        """Frame a world position at the unit-visible zoom."""
        target_zoom = max(
            self.min_zoom,
            min(c.MAX_CAMERA_ZOOM,
                overlay_renderer.ARMY_GROUP_ICON_MAX_ZOOM + COUNTRY_FOCUS_UNIT_ZOOM_MARGIN),
        )
        camera_handler.focus_camera_on_position(
            self.camera, center, c.SCREEN_WIDTH, c.SCREEN_HEIGHT,
            self.total_ui_h, target_zoom, animate)

    def focus_camera_on_army(self, records):
        """Frame an explicitly selected army at the centre of its live units."""
        center = queries.get_average_province_center(
            [province for _unit, province in records], self.loop_map, self.map_w)
        if center is None:
            return False
        camera_handler.center_camera_on_province(
            self.camera, center, c.SCREEN_WIDTH, c.SCREEN_HEIGHT,
            self.total_ui_h, x_offset=ORDERS_PANEL_CAMERA_X_OFFSET)
        return True

    def trigger_multi_turn(self):

        def on_turns(turns):
            if turns:
                self.multi_turns_total = turns
                self.multi_turns_completed = 0
                self.multi_turn_abort_requested = False
                self.ai_is_thinking = True
                self.loading_status_text = f"Skipping {turns} Turns..."
                run_background(self._run_multi_turn_thread, turns)

        dialogs.ask_integer("Process Multiple Turns", "How many turns to process at once?",
                                   on_turns, minvalue=1, maxvalue=5000)

    async def _run_multi_turn_thread(self, turns):

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
                self.movement_tasks_total = 0
                self.movement_tasks_completed = 0
                self.proactive_llm_tasks_total = 0
                self.proactive_llm_tasks_completed = 0
                self.proactive_llm_tasks = []
                self.responsive_tasks_total = 0
                self.responsive_tasks_completed = 0
                self.letters_total = 0
                self.letters_completed = 0

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
        # Each visit to the Relations view starts from the player's own view.
        self._relations_view = None
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
        if (self.realtime_multiplayer
                and next_state in {"PRODUCTION", "ORDERS", "TACTICAL_ORDERS", "RESEARCH", "ECONOMY", "EDIT_COUNTRY",
                                  "MESSAGES", "FACTION", "FACTION_TERRITORIES", "POLITICS",
                                  "AUTOMATION", "PUPPETS", "CLAIMS", "DECLARE_INDEPENDENCE"}):
            player = self.realtime_session.players.get(self.realtime_player_id)
            if (self.realtime_session.phase != "TURN" or not player
                    or player.submitted or player.eliminated):
                self.show_feedback("Orders are locked until you explicitly unsubmit.")
                return
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
                    diplomacy_messages.queue_text_message(self.nation_data, self.player_country, owner, draft)
                else:
                    diplomacy_messages.cancel_text_message(self.nation_data, self.player_country, owner)
                self.mail_input_active = False

        self.selected_province = self.hovered_province = self.hover_glow_surf = self.last_hovered_id = None
        self.hovered_unit_stack = None
        # Back keys run before queued mouse events. Cancel presses and hide
        # province controls before a later release can use the cleared selection.
        for element in self.elements:
            if isinstance(element, Button):
                element.is_pressed = False
        map_buttons.update_button_states(self)
        self.show_feedback("Map Unlocked")

    def save_map_data(self, save_name=None, *, overwrite=False, save_path=None):
        if self.is_saving:
            return # Already saving, ignore duplicate clicks
        if self.realtime_multiplayer:
            session = self.realtime_session
            if session.phase != "GAME_OVER":
                self.show_feedback("Real-time matches can be saved after they end.")
                return
            if save_path is None:
                default_name = save_name or datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                file_exchange.choose_save_destination(
                    os.path.join(c.SAVES_DIR, default_name),
                    lambda path, replace: self.save_map_data(overwrite=replace, save_path=path),
                    game_state=self, title="Save Game", directory=True)
                return
            authoritative_map = self.realtime_server_map or self
            authoritative_map.realtime_match_metadata = session.completed_metadata()
            # The authoritative map is intentionally a countryless server
            # instance while the match runs. Persisting that internal ``None``
            # country made an opened result feel broken. Completed matches are
            # offline spectator replays instead, never resumable sessions.
            authoritative_map.player_country = "Spectator"
            authoritative_map.active_players = []
            authoritative_map.current_player_index = 0
            authoritative_map.show_feedback = self.show_feedback
            if authoritative_map is not self:
                authoritative_map.save_map_data(save_name, overwrite=overwrite, save_path=save_path)
                return
        if self.is_editor:
            if not queries.can_bulk_edit_map(self):
                return
            if save_name is None and save_path is None:
                editor_menus.prepare_editor_save(
                    self, lambda path, replace: self.save_map_data(overwrite=replace, save_path=path))
                return
        elif save_name is None and save_path is None:
            file_exchange.choose_save_destination(
                os.path.join(c.SAVES_DIR, datetime.now().strftime("%Y-%m-%d_%H-%M-%S")),
                lambda path, replace: self.save_map_data(overwrite=replace, save_path=path),
                game_state=self, title="Save Game", directory=True)
            return
        self.is_saving = True
        self.loading_status_text = "Saving Game..."
        self.save_progress_completed = 0
        self.save_progress_total = 5

        # Force the loading screen to actually appear before run_background either
        # spawns a thread (desktop) or, on web, blocks the frame running synchronously.
        self.draw(pygame.display.get_surface())
        pygame.display.flip()

        run_background(save_map.save_map_data, self, save_name, overwrite=overwrite, save_path=save_path)

    MAP_LAYER_REFRESHERS = {
        "political": refresh_map.refresh_political_map,
        "relations": refresh_map.refresh_relations_map,
        "factions": refresh_map.refresh_factions_map,
        "cores": refresh_map.refresh_cores_map,
        "faction_territories": refresh_map.refresh_faction_territories_map,
        "fog": refresh_map.refresh_fog_map,
    }
    ALL_MAP_LAYERS = tuple(MAP_LAYER_REFRESHERS)

    def invalidate_map_presentation_cache(self):
        """Discard state-derived map presentation after a player/world change.

        Rendering remains free to position cached pixels as the camera moves,
        but it must not derive combat forecasts or rescale an unchanged map
        layer during a planning turn.  State-changing UI actions and visual
        layer refreshes converge here so their caches cannot drift apart.
        """
        self._presentation_cache_revision = (
            self._presentation_cache_revision + 1)
        # Lightweight map doubles may not initialize hover presentation state.
        if hasattr(self, "_tooltip_building_stamp"):
            tooltip.prepare_building_yields(self)
        self._combat_bubble_records_cache = None
        self._combat_unit_view_cache = None
        self._unit_render_index_cache = None
        self._unit_roster_cache = {}
        army_panel.prepare(self)
        unit_events.refresh_presentation(self)
        # The inspector projects aircraft caught in ground combat as casualties.
        # Build its roster at this boundary, never during the frame draw.
        if self.selected_province is not None:
            sidebar_info.prepare_unit_roster(self, self.selected_province)
        map_renderer.clear_viewport_scale_cache(self)
        # A real-time draft is a state snapshot, not per-frame presentation.
        # The next update serializes it once after the action that changed it.
        self._realtime_draft_dirty = True
        # Classification belongs to this state boundary, not the frame loop.
        overlay_renderer._unit_render_index(self)

    def queue_editor_visual_refresh(self, *layers):
        """Record editor changes for one post-stroke visual-layer rebuild."""
        self.invalidate_map_presentation_cache()
        self._editor_visual_refresh_layers.update(layers)

    def flush_editor_visual_refresh(self):
        """Rebuild the visual layers changed by an editor stroke, once."""
        if not self._editor_visual_refresh_layers:
            return
        layers = tuple(self._editor_visual_refresh_layers)
        self._editor_visual_refresh_layers.clear()
        # THIS IS INTENTIONALLY COMMENTED OUT FOR A REASON
        # refreshing the map takes about a second
        # by removing this we can prioritize speed over making the country appear perfect
        # if the player really wants to they can hit the refresh maps button in the top right corner
        # self.refresh_map_layers(*layers)

    def refresh_map_layers(self, *layers):
        """Rebuilds named visual layers in the caller-supplied order.

        Layer names live beside the Map UI that owns their cached surfaces.
        The renderer remains responsible for the actual image construction;
        callers no longer need six nearly identical forwarding methods.
        """
        self.invalidate_map_presentation_cache()
        for layer in layers:
            try:
                self.MAP_LAYER_REFRESHERS[layer](self)
            except KeyError as error:
                raise ValueError(f"Unknown map layer: {layer!r}") from error
        if "fog" in layers and hasattr(self, "_tooltip_building_stamp"):
            tooltip.prepare_building_yields(self)

    def refresh_diplomacy_maps(self):
        """Unified helper to quickly refresh only diplomacy-related overlays."""
        self.refresh_map_layers("relations", "factions", "faction_territories")

    def refresh_all_maps(self):
        """Unified method to refresh all visual map layers and text at once."""
        queries.build_air_geometry(self)
        # do note that for larger maps this might take over 1000 ms to complete, this is NOT instant by any means
        # TODO: maybe add the ability to ignore certain refresh actions (example: refresh all except for faction territories)
        refresh_map.invalidate_map_surface_cache(self)
        self.refresh_map_layers(*self.ALL_MAP_LAYERS)
        self.update_country_centers()
        self.show_feedback("Maps refreshed!")

    def show_navigation_tutorial(self):
        """Reopen Help from the persistent Help button, at the topic viewed last."""
        dialogs.show_navigation_intro(self, resume=True)

    def auto_assign_cores(self):

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
        dialogs.ask_yes_no(
            "Confirm Auto-Core",
            "Are you sure you want to auto-assign all cores?\nThis will overwrite existing core data for every province on the map based on current ownership.",
            on_confirm
        )

    def exit_to_menu(self):
        if self.realtime_multiplayer:
            session = self.realtime_session
            is_host = (self.realtime_player_id == getattr(session, "host_id", None))
            if not is_host:

                def leave_match(confirmed):
                    if not confirmed:
                        return
                    client = self.realtime_client
                    if client:
                        client.close()
                    self.show_feedback("You left the match. The host and other players continue normally.")
                    self.change_state("MULTIPLAYER_MENU")

                dialogs.ask_yes_no(
                    "Leave Real-Time Match",
                    "Leave this match? This disconnects only you; the host and other players keep playing. "
                    "You can rejoin with your reconnect code while the match is active.",
                    leave_match, yes_label="Leave Match", no_label="Stay")
                return

            if session.phase == "GAME_OVER":
                if self.realtime_port_mapping:
                    self.realtime_port_mapping.stop()
                if self.realtime_server:
                    self.realtime_server.stop("The host closed this completed real-time match.")
                self._destroy_temporary_relay()
                self.change_state("MULTIPLAYER_MENU")
                return

            def close_match(confirmed):
                if not confirmed:
                    return
                session.end_match(self.realtime_player_id)
                if self.realtime_port_mapping:
                    self.realtime_port_mapping.stop()
                if self.realtime_server:
                    self.realtime_server.stop(
                        "The host ended the real-time match. You have been disconnected.")
                self._destroy_temporary_relay()
                self.show_feedback(
                    "Current turn is finishing safely; all guests have been disconnected."
                    if session.phase == "PROCESSING" else
                    "Real-time match ended by host. Save the final result before leaving.")
            dialogs.ask_yes_no("End Real-Time Match",
                                      "Leaving stops the server for every player. End this match?",
                                      close_match, yes_label="End Match", no_label="Cancel")
            return
        self.show_exit_confirmation = True
        for el in self.elements: el.visible = False

    def _destroy_temporary_relay(self):
        """Delete the host-owned, memory-only temporary relay after shutdown."""
        relay = self.realtime_temporary_relay
        token = self.realtime_relay_token
        if not relay or not token:
            return
        self.realtime_temporary_relay = None
        try:
            from data.multiplayer.realtime.relay import destroy_temporary_relay
            threading.Thread(target=lambda: _delete_relay_safely(token, relay.droplet_id, relay.firewall_id), daemon=True).start()
        except (ImportError, AttributeError):
            pass

    def cancel_exit(self):
        self.show_exit_confirmation = False
        self.show_feedback("Exit cancelled")

    def confirm_exit(self):
        sound_effects.play_ui_sound("back")
        diplomatic_popups.clear_popups(self)
        self.change_state("MENU")

    def show_feedback(self, text):
        self._bilateral_response_indicator_cache = None
        self.feedback_text, self.feedback_timer = text, pygame.time.get_ticks()
        print(f"[UI EVENT] {text}")

    def additional_events(self, event):
        # Intercept inputs if the game has crashed
        if self.thread_error:
            if (event.type == pygame.MOUSEBUTTONDOWN and event.button == 1
                    and not getattr(event, "mobile_drag", False)):
                btn_rect = pygame.Rect(c.SCREEN_WIDTH - 240, c.SCREEN_HEIGHT - 80, 220, 60)
                if btn_rect.collidepoint(event.pos):
                    if pickers.copy_to_clipboard(self.thread_error):
                        self.error_copied = True
            return # Block all other map events!

        # Buttons are dispatched before this method, but map tile selection
        # starts on mouse-down whereas Button callbacks fire on mouse-up. Do
        # not let a click on a visible map HUD control (notably the movable
        # Details button) fall through and select the province underneath it.
        if event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP):
            unit_view_buttons = self.unit_view_buttons
            if any(isinstance(element, Button) and element.visible
                   and element.rect.collidepoint(event.pos)
                   and (element not in unit_view_buttons.values()
                        or self.unit_view_bar_rect.collidepoint(event.pos))
                   for element in self.elements):
                return
        map_input.handle_map_events(self, event)

    def touch_map_at(self, position):
        if (self.thread_error or self.show_player_ready_screen or self.show_exit_confirmation
                or self.is_saving or self.ai_is_thinking
                or map_input._map_position_is_on_ui(self, position)
                or army_panel.blocks_map_touch(self, position)):
            return None
        if diplomatic_popups.map_message_popups_visible(self):
            popups = self.diplomatic_popups + ([self.navigation_intro_popup]
                      if self.navigation_intro_popup is not None else [])
            if any(popup.rect.collidepoint(position) for popup in popups):
                return None
        if any(element.visible and element.rect.collidepoint(position)
               for element in self.elements if isinstance(element, Button)):
            return None
        return self

    def cancel_pointer_input(self):
        super().cancel_pointer_input()
        for popup in self.diplomatic_popups:
            popup.is_dragging = False
        if self.navigation_intro_popup is not None:
            self.navigation_intro_popup.is_dragging = False
            self.navigation_intro_popup._scroll_drag_offset = None

    def has_secondary_action_at(self, position):
        return (self.touch_map_at(position) is self
                and map_input.has_secondary_map_action(self, position))

    def handle_events(self, events):
        """Route the live navigation guide before HUD buttons and map input."""
        for event in events:
            map_input.resolve_map_mouse_gesture_conflict(self, event)
            popup = self.navigation_intro_popup
            if (popup is not None and diplomatic_popups.map_message_popups_visible(self)
                    and popup.handle_event(event)):
                continue
            if army_panel.handle_event(self, event):
                continue
            toggle = self.btn_unit_view_toggle
            if toggle is not None and event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP):
                release = event.type == pygame.MOUSEBUTTONUP and event.button == 1 and toggle.is_pressed
                if release or (toggle.visible and toggle.rect.collidepoint(event.pos)):
                    # A moving button must consume its release, even if the pointer leaves it.
                    if toggle.visible:
                        toggle.handle_event(event)
                    else:
                        toggle.is_pressed = False
                    continue
            super().handle_events([event])

    # --- Map-level unit selection and movement ---------------------------------

    def can_select_map_units(self):
        if (self.selection_mode or self.is_editor or self.viewing_ai_moves
                or self.ai_is_thinking or self.player_country in (
                    "None", "Spectator", c.TOURNAMENT_SPECTATOR)):
            return False
        if self.realtime_multiplayer:
            player = self.realtime_session.players.get(self.realtime_player_id)
            if (self.realtime_session.phase != "TURN" or not player
                    or player.submitted or player.eliminated):
                return False
        return True

    def is_unit_selected(self, unit):
        selected = self.selected_unit_ids
        # ``id(unit)`` remains accepted for lightweight legacy test doubles,
        # while live maps use the persistent identity introduced for armies.
        return unit.get("unit_id") in selected or id(unit) in selected

    def clear_map_unit_selection(self):
        self.selected_unit_ids.clear()
        self.unit_selection_drag = None

    def deselect_map_units(self, units):
        """Remove specific stacks without disturbing selections elsewhere."""
        for unit in units:
            self.selected_unit_ids.discard(unit.get("unit_id"))
            self.selected_unit_ids.discard(id(unit))

    def select_map_units(self, units, additive=False, *, sound_kind="select_unit"):
        """Select commandable units represented by one or more visible stacks."""
        if not self.can_select_map_units():
            return
        previous_selection = self.selected_unit_ids.copy()
        eligible = [unit for unit in units if unit.get("owner") == self.player_country]
        if self.tactical_mode:
            eligible = [unit for unit in eligible if unit is self.player_unit]
        if not additive:
            self.selected_unit_ids.clear()
        queries.ensure_unit_ids(self.map_data)
        self.selected_unit_ids.update(unit["unit_id"] for unit in eligible)
        if eligible and self.selected_unit_ids != previous_selection and sound_kind is not None:
            sound_effects.play_ui_sound(sound_kind)
        self.show_feedback(f"{len(self.selected_unit_ids)} unit{'s' if len(self.selected_unit_ids) != 1 else ''} selected")

    def click_select_map_units(self, units, additive=False):
        """Apply the shared plain-click/Shift-click unit-selection convention.

        A plain click on a member of a larger selection focuses that member,
        while a plain click on the only selected unit deselects it. Shift-click
        adds units without disturbing the current selection, matching HOI4's
        individual division-selection behavior.
        """
        if not self.can_select_map_units():
            return False
        eligible = [unit for unit in units if unit.get("owner") == self.player_country]
        if self.tactical_mode:
            eligible = [unit for unit in eligible if unit is self.player_unit]
        if not eligible:
            return False

        target_is_selected = all(self.is_unit_selected(unit) for unit in eligible)
        target_objects = {id(unit) for unit in eligible}
        has_other_selected = any(
            id(unit) not in target_objects
            for unit, _province in self.selected_unit_records())
        if additive:
            self.select_map_units(eligible, additive=True)
        elif target_is_selected and has_other_selected:
            self.select_map_units(eligible)
        elif target_is_selected:
            self.deselect_map_units(eligible)
        else:
            self.select_map_units(eligible)
        return all(self.is_unit_selected(unit) for unit in eligible)

    def selected_unit_records(self):
        """Return selected units with their current provinces, pruning stale IDs."""
        records, live_ids = [], set()
        for province in self.map_data.values():
            for unit in province.get("units", []):
                unit_id = unit.get("unit_id")
                legacy_id = id(unit)
                if unit_id in self.selected_unit_ids or legacy_id in self.selected_unit_ids:
                    live_ids.update((unit_id, legacy_id))
                    if unit.get("owner") == self.player_country:
                        records.append((unit, province))
        self.selected_unit_ids.intersection_update(live_ids)
        return records

    def issue_selected_move_orders(self, destination, append=False):
        """Atomically give every selected unit its own route to a destination."""
        if not self.can_select_map_units() or not destination:
            return False
        records = self.selected_unit_records()
        if not records:
            return False
        try:
            choices = queries.plan_unit_move_orders(self, records, destination, append)
        except ValueError as exc:
            self.show_feedback(str(exc))
            return False
        unit_actions.apply_batch(self, self.player_country, choices)
        self.invalidate_map_presentation_cache()
        self.show_feedback(f"{len(choices)} unit{'s' if len(choices) != 1 else ''} routed to province {destination['id']}")
        return True

    def can_issue_selected_move_orders(self, destination, append=False):
        """Preview meaningful movement without changing orders, resources, or feedback."""
        if not self.can_select_map_units() or not destination:
            return False
        try:
            choices = queries.plan_unit_move_orders(self, self.selected_unit_records(), destination, append)
            prepared = []
            for unit, origin, order in choices:
                if not unit_actions.unit_permission(self, self.player_country, unit):
                    return False
                prepared.append(unit_actions.prepare_action(self, self.player_country, origin, unit, order))
        except ValueError:
            return False
        return any(result.changed for result in prepared)

    def selected_map_unit_ids(self):
        """Persistent IDs for the currently commandable selection."""
        return [unit["unit_id"] for unit, _province in self.selected_unit_records()
                if isinstance(unit.get("unit_id"), str) and not queries.unit_is_air_drop_recovering(unit)]

    def create_army_from_selection(self):
        if not self.can_select_map_units():
            return None
        army = queries.create_army(self.player_country, self.selected_map_unit_ids(),
                                   self.nation_data, self.map_data)
        if army:
            sound_effects.play_ui_sound("create_army")
            self.invalidate_map_presentation_cache()
            self.show_feedback(f"Created {army['name']}")
        return army

    def assign_selection_to_army(self, army_id):
        if not self.can_select_map_units():
            return False
        changed = queries.assign_units_to_army(
            self.player_country, army_id, self.selected_map_unit_ids(),
            self.nation_data, self.map_data)
        if changed:
            self.invalidate_map_presentation_cache()
            self.show_feedback("Selected units assigned to army")
        return changed

    def ungroup_selection(self):
        if not self.can_select_map_units():
            return False
        changed = queries.ungroup_units(self.player_country,
                                        self.selected_map_unit_ids(),
                                        self.nation_data, self.map_data)
        if changed:
            self.invalidate_map_presentation_cache()
            self.show_feedback("Selected units removed from their armies")
        return changed

    def select_army(self, army_id, open_orders=True):
        """Select all live members of one army, optionally opening Orders."""
        if not self.can_select_map_units():
            return False
        if army_id == c.UNASSIGNED_ARMY_ID:
            army = queries.get_unassigned_army(self.player_country, self.nation_data, self.map_data)
        else:
            armies = queries.get_armies(self.player_country, self.nation_data, self.map_data)
            army = next((item for item in armies if item.get("id") == army_id), None)
        if army is None:
            return False
        records_by_id = {
            unit.get("unit_id"): (unit, province)
            for province in self.map_data.values()
            for unit in province.get("units", [])
            if unit.get("owner") == self.player_country
        }
        records = [records_by_id[unit_id] for unit_id in army.get("unit_ids", [])
                   if unit_id in records_by_id]
        if not records:
            queries.normalize_armies(self.nation_data, self.map_data)
            return False
        self.select_map_units([unit for unit, _province in records])
        self.selected_province = records[0][1]
        sidebar_info.prepare_unit_roster(self, self.selected_province)
        self.focus_camera_on_army(records)
        if open_orders:
            self._orders_return_to_province_menu = False
            self.change_state(map_input.orders_state(self))
        return True

    def open_orders_for_unit_stack(self, province, units, return_to_province_menu=False):
        """Open Orders around a clicked stack without losing map selection."""
        self.select_map_units(units)
        self.selected_province = province
        self._orders_return_to_province_menu = return_to_province_menu
        self.change_state(map_input.orders_state(self))

    def sync_units_to_data(self):
        unit_library = queries.get_unit_library(self)
        building_library = queries.get_building_library(self)
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
                    match = re.search(r'\((.*?)\)', base_type)
                    if match:
                        base_type = match.group(1).strip()

                # Check if the unit is still valid
                if base_type in unit_library or base_type in ["Convoy", "Truck"]:
                    if queries.apply_library_stats(unit, unit_library):
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

        army_panel.prepare(self)
        print(f"[MAP SCRUBBER] {updated_count} entities updated, {removed_count} obsolete entities vaporized.")

    def handle_back_key(self):
        if army_panel.handle_back_key(self):
            return
        if self.selected_province:
            sound_effects.play_ui_sound("back")
            self.deselect_province()

    def handle_orders_key(self):
        """Q. Sets the view mode to Units, same as clicking that button; also
        jumps straight into Orders or Battle for the selected tile when the
        Keybinds screen's "change screen with this keybind" toggle is on for
        this key -- independent of Classic/Preemptive map navigation, see
        screens.game.map_input.handle_view_mode_keybind.

        Not gated on owning anything here: both screens read a province you have
        no units in, and refuse to edit units you do not command.
        """
        if self.selection_mode or self.player_country == c.TOURNAMENT_SPECTATOR:
            return
        map_input.handle_view_mode_keybind(self, "UNITS", "ORDERS")

    def handle_economy_key(self):
        """W. Sets the view mode to Economy, same as clicking that button;
        also jumps straight into Production for the selected tile when the
        Keybinds screen's "change screen with this keybind" toggle is on for
        this key -- see handle_orders_key.
        """
        if self.selection_mode or self.player_country == c.TOURNAMENT_SPECTATOR:
            return
        map_input.handle_view_mode_keybind(self, "ECONOMY", "ECONOMY")

    def draw_background(self, surface):
        # Recomputed here (not just in update()) so callers that draw this
        # background without running Map_Screen.update() first -- Orders_Screen,
        # MapOverlayScreen (claims/peace/trade/nation creation) -- still get a live,
        # zoom-responsive color instead of a stale one. The shared renderer
        # anchors the sky and optional water reflection to the map camera.
        self.bg_color = camera_handler.get_dynamic_ocean_color(self.camera, self.min_zoom)
        map_renderer.draw_map_background(self, surface, self.bg_color)

    def additional_draw(self, surface):
        map_renderer.draw_map_screen(self, surface)
        if self.unit_selection_drag:
            start = self.unit_selection_drag["start"]
            current = self.unit_selection_drag["current"]
            rect = pygame.Rect(start, (current[0] - start[0], current[1] - start[1]))
            rect.normalize()
            pygame.draw.rect(surface, (220, 210, 80), rect, 2)
            shade = pygame.Surface(rect.size, pygame.SRCALPHA)
            shade.fill((220, 210, 80, 35))
            surface.blit(shade, rect.topleft)

    def draw_elements(self, surface):
        """Draw country actions in their own clipped, scrollable HUD pane."""
        country_actions = set(self.country_action_buttons)
        unit_view_buttons = set(self.unit_view_buttons.values())
        for element in self.elements:
            if element not in country_actions:
                if element in unit_view_buttons:
                    old_clip = surface.get_clip()
                    surface.set_clip(old_clip.clip(self.unit_view_bar_rect))
                    element.draw(surface)
                    surface.set_clip(old_clip)
                else:
                    element.draw(surface)

        visible_actions = [button for button in country_actions if button.visible]
        if not visible_actions:
            return

        map_buttons.layout_country_action_buttons(self)
        old_clip = surface.get_clip()
        surface.set_clip(self.country_actions_scroll_rect)
        for button in country_actions:
            button.draw(surface)
        surface.set_clip(old_clip)

        if self.country_actions_scroll_max > 0:
            rect = self.country_actions_scroll_rect
            track = pygame.Rect(rect.right - 10, rect.y, 8, rect.height)
            handle_h = max(30, int(rect.height * rect.height /
                                   (rect.height + self.country_actions_scroll_max)))
            travel = rect.height - handle_h
            ratio = self.country_actions_scroll_y / self.country_actions_scroll_max
            handle = pygame.Rect(rect.right - 10, rect.y + int(travel * ratio), 8, handle_h)
            ui_elements.draw_slider(surface, track, handle)

    def draw(self, surface):
        super().draw(surface)
        map_renderer.draw_badges(self, surface)

        realtime_status_panel.draw(self, surface)
        army_panel.draw(self, surface)

        diplomatic_popups.draw(self, surface)

        popup = self.navigation_intro_popup
        if popup is not None and diplomatic_popups.map_message_popups_visible(self):
            popup.draw(surface)

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
        tech_tree = queries.get_tech_tree(self)
        for country, data in self.nation_data.items():
            if "research" in data:
                obsolete_keys = [k for k in data["research"].keys() if k not in tech_tree]
                for k in obsolete_keys:
                    del data["research"][k]
                    updated_count += 1

        # --- NEW: Scrub the map's default template too! ---
        if self.default_research is not None:
            obsolete_defaults = [k for k in self.default_research.keys() if k not in tech_tree]
            for k in obsolete_defaults:
                del self.default_research[k]
                updated_count += 1

        self.nation_colors = country_io.nation_colors_from(self.nation_data)
        self.refresh_map_layers("political", "relations")

        # Merge the unit sync into this function
        self.sync_units_to_data()

        self.show_feedback(f"Data Resynced! Added {added_count}, Updated {updated_count}. Objects Synced.")

    def set_editor_selection_tool(self, tool):
        """Select the local territory and core painting tool."""
        if not self.is_editor or self.editor_mode not in ("NATION", "CORE"):
            return
        if tool not in ("BRUSH", "PAINT"):
            raise ValueError("Unknown editor selection tool.")
        self.editor_selection_tool = tool
        map_buttons.update_button_states(self)

    def _apply_host_realtime_snapshot(self):
        """Refresh the host's visible map when the authoritative turn changes.

        The host intentionally plays on a separate map from MapRealtimeDriver,
        so its UI cannot mutate the server state directly.  Unlike guests it
        has no network client to poll, however, and therefore needs to take a
        turn-boundary snapshot from its local session before it serializes its
        next draft.  Applying only at a new turn (or game over) preserves the
        host's unsubmitted local orders throughout the active turn.
        """
        if (not self.realtime_server_map
                or self.realtime_client):
            return
        session = self.realtime_session
        if not session or session.phase not in ("TURN", "GAME_OVER"):
            return

        current_turn = session.turn_number
        current_phase = session.phase
        applied_turn = self._realtime_snapshot_turn
        applied_phase = self._realtime_snapshot_phase
        should_apply = (applied_turn is None or current_turn != applied_turn or
                        (current_phase == "GAME_OVER" and applied_phase != "GAME_OVER"))
        if not should_apply:
            return

        # public_state holds the session lock while it snapshots the server
        # map, so the UI cannot copy a halfway-resolved turn.
        state = session.public_state()
        snapshot = state.get("game_state") if isinstance(state, dict) else None
        if not snapshot:
            return
        from data.multiplayer.realtime.session import apply_authoritative_snapshot
        apply_authoritative_snapshot(self, snapshot)
        self._realtime_snapshot_turn = current_turn
        self._realtime_snapshot_phase = current_phase

    def update(self):
        self._advance_unit_view_animation()
        if (self._unit_selection_turn != self.time_manager.total_turns
                or self._unit_selection_player != self.player_country):
            self.clear_map_unit_selection()
            self._unit_selection_turn = self.time_manager.total_turns
            self._unit_selection_player = self.player_country
        if self.realtime_multiplayer:
            self._apply_host_realtime_snapshot()
        if self.realtime_multiplayer:
            session = self.realtime_session
            player = session.players.get(self.realtime_player_id)
            if (session.phase == "TURN" and player and not player.submitted and not player.eliminated
                    and not self.realtime_submission_pending
                    and self._realtime_draft_dirty):
                # Keep the server's last accepted draft current after a real
                # player/state boundary.  Serializing every province and army
                # every frame made an idle planning turn do map-wide work just
                # to rediscover an unchanged draft.
                from data.multiplayer.realtime.session import collect_map_commands, RealtimeError
                commands = collect_map_commands(self, self.player_country)
                fingerprint = f"{session.turn_number}:" + json.dumps(commands, sort_keys=True, separators=(",", ":"))
                if fingerprint != self._realtime_draft_fingerprint:
                    try:
                        if session.sync_draft(self.realtime_player_id, session.turn_number, commands) is not False:
                            self._realtime_draft_fingerprint = fingerprint
                    except RealtimeError as error:
                        self.show_feedback(f"Order update rejected: {error}")
                self._realtime_draft_dirty = False
        if self.realtime_multiplayer and self.realtime_client:
            from data.multiplayer.realtime.session import apply_authoritative_snapshot
            events = self.realtime_client.poll()
            # A socket close can be queued next to the host's explicit
            # shutdown frame.  The latter is the useful reason, so never let
            # its companion disconnect event replace it.
            if any(event.get("type") == "shutdown" for event in events):
                events = [event for event in events if event.get("type") != "disconnected"]
            for event in events:
                payload = event.get("payload", {})
                state = payload if event.get("type") == "state" else payload.get("state")
                if state:
                    self.realtime_session.update(state)
                    player = self.realtime_session.players.get(self.realtime_player_id)
                    if player and player.submitted:
                        self.realtime_submission_pending = False
                    # Status heartbeats and draft acknowledgements describe
                    # the same in-progress turn. Re-applying their base-game
                    # snapshot would erase a player's unsubmitted local
                    # research/orders/queues. Apply only the initial board,
                    # a newly opened turn, or the final processed result.
                    current_turn = self.realtime_session.turn_number
                    current_phase = self.realtime_session.phase
                    applied_turn = self._realtime_snapshot_turn
                    applied_phase = self._realtime_snapshot_phase
                    should_apply = (applied_turn is None or current_turn != applied_turn or
                                    (current_phase == "GAME_OVER" and applied_phase != "GAME_OVER"))
                    if self.realtime_session.snapshot and should_apply:
                        apply_authoritative_snapshot(self, self.realtime_session.snapshot)
                        self._realtime_snapshot_turn = current_turn
                        self._realtime_snapshot_phase = current_phase
                elif event.get("type") in ("error", "disconnected", "shutdown"):
                    message = payload.get("message", "Disconnected from real-time server.")
                    self.realtime_submission_pending = False
                    if event.get("type") in ("disconnected", "shutdown"):
                        # Do not keep retrying a draft send after the relay or
                        # host has gone away. The final authoritative state
                        # remains visible, but this client is read-only.
                        self.realtime_connection_error = message
                        if event.get("type") == "shutdown":
                            self.realtime_client.close()
                        self.realtime_client = None
                        self.show_feedback(
                            f"Match ended by host: {message} Multiplayer actions are disabled."
                            if event.get("type") == "shutdown" else
                            "Connection lost. Multiplayer actions are disabled; rejoin from the menu.")
                    else:
                        self.show_feedback(message)
        elif self.realtime_multiplayer and self.realtime_server_map:
            # The host uses a separate visual map. Pull only processed server
            # turns across, never an in-progress draft, so hosting confers no
            # direct gameplay authority.
            server_map = self.realtime_server_map
            if server_map.time_manager.total_turns != self.time_manager.total_turns:
                from data.multiplayer.realtime.session import MapRealtimeDriver, apply_authoritative_snapshot
                apply_authoritative_snapshot(self, MapRealtimeDriver(server_map).snapshot())
        super().update()
        self.camera.update(self, c.SCREEN_HEIGHT)

        # Defer editor map label/layer updates until either brush button is up.
        editor_mouse_buttons = pygame.mouse.get_pressed()
        editor_stroke_active = (editor_mouse_buttons[0] or editor_mouse_buttons[2])
        if self.centers_need_update and not editor_stroke_active:
            self.update_country_centers()
            self.centers_need_update = False
        if self.is_editor and not editor_stroke_active:
            self.flush_editor_visual_refresh()

        # Only spawn popups when the player is fully in control of the current turn
        is_playing = not self.viewing_ai_moves and \
                     not self.ai_is_thinking and \
                     not self.show_player_ready_screen and \
                     not self.selection_mode

        if (is_playing and self._popup_presentation_revision
                != self._presentation_cache_revision):
            diplomatic_popups.spawn_popups_for_player(self)
            self._popup_presentation_revision = self._presentation_cache_revision

        if self.show_navigation_intro_when_ready and is_playing:
            self.show_navigation_intro_when_ready = False
            if settings_schema.read_setting(queries.get_settings(), settings_schema.intro_popup_setting(self.tactical_mode)):
                dialogs.show_navigation_intro(self)

        if self.show_player_ready_screen:
            for el in self.elements: el.visible = False
            return

        if is_playing and not self.is_refreshing:
            self.open_tactical_battle()

        if self.multi_turn_processing_complete:
            self.multi_turn_processing_complete = False
            self.multi_turns_total = 0
            self.ai_is_thinking = False

            if self.thread_error: return

            self.refresh_map_layers(*self.ALL_MAP_LAYERS)
            self.update_country_centers()

            self.viewing_ai_moves = False # Safely unlock PyGame UI rendering

            map_buttons.update_button_states(self)
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
                map_buttons.render_buttons(self)
                elapsed_seconds = (pygame.time.get_ticks() - self.turn_start_time) / 1000.0
                self.show_feedback(f"AI Strategy generated in {elapsed_seconds:.2f}s")
                print(f"[PERFORMANCE] Phase 1 completed in {elapsed_seconds:.2f} seconds.")

        self.bg_color = camera_handler.get_dynamic_ocean_color(self.camera, self.min_zoom)
        map_buttons.update_button_states(self)
