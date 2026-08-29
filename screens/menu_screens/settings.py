import pygame
import ui_elements
from ui_elements import Button, Slider
from gameState import GameState
import data.constants as c
from data import queries
from map_logic.rendering.font_manager import fonts
from ui.bars import ui_bars
from ui import confirm_dialog

# --- Settings screen button layout ---
SETTINGS_RIGHT_COL_X = c.SCREEN_WIDTH - 250
SETTINGS_BACK_POS = (50, 50)
SETTINGS_FULLSCREEN_Y = 20
SETTINGS_CHECKERBOARD_WATER_Y = 70
SETTINGS_FPS_TOGGLE_Y = 120
SETTINGS_DRAG_KEY_Y = 170
SETTINGS_MAP_NAV_Y = 220
SETTINGS_PLAYER_SLIDER_Y = 400
SETTINGS_FPS_SLIDER_Y = 460
SETTINGS_AI_THREAD_SLIDER_POS = (60, 400)
SETTINGS_SLIDER_WIDTH = 200
SETTINGS_RESET_Y = 650
SETTINGS_UNIT_ART_GAP_X = 20
SETTINGS_KEYBINDS_Y = 520
SETTINGS_AI_TOGGLE_POS = (10, c.SCREEN_HEIGHT - 60)
SETTINGS_AI_PROVIDER_Y = c.SCREEN_HEIGHT - 250
SETTINGS_AI_PROVIDER_START_X = 10
SETTINGS_AI_PROVIDER_STEP_X = 110
SETTINGS_AI_IMMERSION_X = 10
SETTINGS_AI_IMMERSION_ROWS_Y = (c.SCREEN_HEIGHT - 100, c.SCREEN_HEIGHT - 135,
                                c.SCREEN_HEIGHT - 170, c.SCREEN_HEIGHT - 205)
SETTINGS_CLEAR_BTN_GAP_X = 10
SETTINGS_PATH_EDIT_OFFSET_X = -220
SETTINGS_PATH_RESET_OFFSET_X = -110
SETTINGS_PATH_BOX_X = c.SCREEN_WIDTH // 2 - 150

# Info ("?") buttons beside the Fullscreen..Map Navigation column -- same
# small square and left-of-the-setting placement scenario_settings.py uses.
SETTINGS_INFO_GAP_X = 10
SETTINGS_INFO_X = SETTINGS_RIGHT_COL_X - c.SIZES["scenario_setting_info"][0] - SETTINGS_INFO_GAP_X
# Half the leftover height between a "setting_option" button (40px) and the smaller
# "scenario_setting_info" square (32px), so the two line up on center.
SETTINGS_INFO_Y_NUDGE = (c.SIZES["setting_option"][1] - c.SIZES["scenario_setting_info"][1]) // 2

# (row Y, tooltip title, tooltip text) for each info button in that column, in
# the same top-to-bottom order as the buttons themselves.
SETTINGS_INFO_ROWS = (
    (SETTINGS_FULLSCREEN_Y, "Toggle Fullscreen",
     "Switches the game window between fullscreen and windowed mode."),
    (SETTINGS_CHECKERBOARD_WATER_Y, "Checkerboard Water",
     "Whether the map's ocean uses a slowly scrolling checkerboard pattern "
     "instead of a flat fill color. Off by default since it can read as "
     "unusual water for players who don't expect it."),
    (SETTINGS_FPS_TOGGLE_Y, "Show FPS",
     "Displays a live frames-per-second counter on screen."),
    (SETTINGS_DRAG_KEY_Y, "Drag Key",
     "Which mouse button drags/pans the map camera: Right, Left, or Both. "
     "Click to cycle through the three."),
    (SETTINGS_MAP_NAV_Y, "Map Navigation",
     "Classic: clicking a tile always opens the plain province menu, and the "
     "Resources/Blank/Units/Economy ui view buttons only switch "
     "the map's view mode. Orders and Production are reached only through "
     "their own buttons; Battle is opened from Orders. \n"
     "Preemptive: a click jumps "
     "straight into the screen the current view mode implies (Orders for "
     "Units, including a fighting tile). "
     "Click to switch between them."),
)


def info_button(x, y, tooltip_title, tooltip_text):
    """A small "?" button that pops up a tooltip -- same shape scenario_settings
    uses for its rows, reused here for the Settings/Keybinds screens' toggles."""
    return Button(x, y + SETTINGS_INFO_Y_NUDGE, "scenario_setting_info", "light_blue", "?",
                 lambda: confirm_dialog.show_info(tooltip_title, tooltip_text))


def make_option_buttons(options, on_select, current, size="ai_opinion", color="blue", font_preset="small"):
    """Builds a row/column of mutually exclusive buttons with the active one highlighted.

    Options are (x, y, value, label) tuples. Used for every "pick exactly one
    of these" cluster (AI provider, immersion level) so the gold selection
    border and the callback binding are done identically.
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
        Button(keybind_x, SETTINGS_FULLSCREEN_Y, "setting_option", "blue", "Toggle Fullscreen", settings_screen.toggle_full),
        Button(keybind_x, SETTINGS_CHECKERBOARD_WATER_Y, "setting_option", "green" if settings_screen.checkerboard_water else "red",
               f"Checkerboard Water: {'ON' if settings_screen.checkerboard_water else 'OFF'}", settings_screen.toggle_checkerboard_water),
        Button(keybind_x, SETTINGS_FPS_TOGGLE_Y, "setting_option", "green" if settings_screen.show_fps else "red",
               f"Show FPS: {'ON' if settings_screen.show_fps else 'OFF'}", settings_screen.toggle_fps),
        Button(keybind_x, SETTINGS_DRAG_KEY_Y, "setting_option", "purple", f"Drag Key: {settings_screen.drag_mouse_toggle}", settings_screen.toggle_drag_button),
        Button(keybind_x, SETTINGS_MAP_NAV_Y, "setting_option", "purple",
               f"Map Navigation: {settings_screen.map_navigation_mode.title()}",
               settings_screen.toggle_map_navigation_mode),
    ]
    settings_screen.elements.extend(
        info_button(SETTINGS_INFO_X, y, title, text) for y, title, text in SETTINGS_INFO_ROWS
    )

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
            for i, mode in enumerate(("OLLAMA", "GEMINI", "CHATGPT", "CLAUDE", "DEEPSEEK", "KIMI"))
        ], settings_screen.set_ai_mode, settings_screen.ai_mode))

        # AI immersion level picker
        # MAJOR sits between FULL and ABSOLUTE: the model drives the countries a
        # player actually notices, which is great-power diplomacy at a fraction
        # of what ABSOLUTE costs.
        settings_screen.elements.extend(make_option_buttons([
            (SETTINGS_AI_IMMERSION_X, y, level, f"{level} AI")
            for y, level in zip(SETTINGS_AI_IMMERSION_ROWS_Y, c.AI_IMMERSION_LEVELS)
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
        Button(keybind_x - c.SIZES["medium"][0] - SETTINGS_UNIT_ART_GAP_X, SETTINGS_RESET_Y, "medium", "blue",
               "Unit Art", settings_screen.open_unit_art),
    ])

    # Rebinding itself now lives on its own screen; this just links to it.
    settings_screen.elements.append(
        Button(keybind_x, SETTINGS_KEYBINDS_Y, "medium", "purple", "Keybinds",
               settings_screen.open_keybinds, image=ui_bars.get_ui_image("Keybind.png"))
    )

    # Edit/Reset pair for each path and color row, driven off the screen's own table
    for y, _kind, key, _label in settings_screen.PATH_ROWS:
        settings_screen.elements.extend([
            Button(SETTINGS_PATH_BOX_X + SETTINGS_PATH_EDIT_OFFSET_X, y, "small", "blue", "Edit", lambda k=key: settings_screen.edit_setting(k)),
            Button(SETTINGS_PATH_BOX_X + SETTINGS_PATH_RESET_OFFSET_X, y, "small", "red", "Reset", lambda k=key: settings_screen.reset_setting(k)),
        ])


class Settings(GameState):
    # Every LLM provider stores its credentials under the same attribute pair,
    # so one naming rule replaces the four-branch if/elif chains this screen
    # used to carry in five separate places.
    AI_MODES = ["OFF", "GEMINI", "OLLAMA", "CHATGPT", "CLAUDE", "DEEPSEEK", "KIMI"]
    AI_FIELD_SUFFIX = {"KEY": "api_key", "MOD": "model"}

    # key -> (constants attribute to keep in sync, default value, picker title)
    DIR_FIELDS = {
        "saves_dir":            ("SAVES_DIR",            "saves",                "Select Saves Directory"),
        "custom_scenarios_dir": ("SCENARIOS_CUSTOM_DIR", "scenarios/map_editor", "Select Custom Scenarios Directory"),
        "tournament_saves_dir": ("TOURNAMENT_SAVES_DIR", "tournament_saves",     "Select Tournament Saves Directory"),
    }
    # key -> (constants attribute, constants attribute holding the default, picker title)
    COLOR_FIELDS = {
        "ocean_light_color": ("OCEAN_LIGHT_BLUE", "DEFAULT_OCEAN_LIGHT_BLUE", "Select Zoom-In Water Color"),
        "ocean_dark_color":  ("OCEAN_DARK_BLUE",  "DEFAULT_OCEAN_DARK_BLUE",  "Select Zoom-Out Water Color"),
    }

    # (y, kind, key, label) for the path/color block in the middle of the screen.
    # Shared by additional_draw here and by the Edit/Reset button rows in
    # render_settings_buttons above so the two cannot drift out of alignment.
    PATH_ROWS = [
        (60,  "dir",   "saves_dir",            "Saves Path:"),
        (120, "dir",   "custom_scenarios_dir", "Custom Maps Path:"),
        (175, "color", "ocean_light_color",    "Zoom-In Water Color:"),
        (230, "color", "ocean_dark_color",     "Zoom-Out Water Color:"),
        (285, "dir",   "tournament_saves_dir", "Tournament Saves Path:"),
    ]

    DIR_BOX_W = 400
    DIR_BOX_H = 35
    COLOR_BOX_W = 40

    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.bg_color = (40, 40, 40)
        self.bg_image_path = c.SETTINGS_BG_FILE
        self.back_state = "MENU"

        self.sfx_volume = self.controller.sfx_volume
        self.num_players = self.controller.num_players
        self.ai_mode = self.controller.ai_mode
        self.ai_immersion_level = self.controller.ai_immersion_level
        self.ai_modes = self.AI_MODES

        self.last_ai_mode = self.ai_mode if self.ai_mode != "OFF" else c.AI_MODE_REENABLE_FALLBACK

        self.fullscreen = False

        # Mirror the controller's editable string state onto "<attr>_text" locals:
        # the API key / model name pair per provider, plus the path settings.
        for attr in self.editable_attrs():
            setattr(self, f"{attr}_text", getattr(self.controller, attr))

        # Load dynamic mouse button config from controller, fallback to constants configuration setting
        self.drag_mouse_toggle = self.controller.drag_mouse_toggle

        self.active_input = None # Dynamically track which box is selected: "{MODE}_KEY" or "{MODE}_MOD"

        self.ai_threads = self.controller.ai_threads
        self.show_fps = self.controller.show_fps
        self.checkerboard_water = self.controller.checkerboard_water
        self.map_navigation_mode = self.controller.map_navigation_mode

        for key in list(self.DIR_FIELDS) + list(self.COLOR_FIELDS):
            setattr(self, key, getattr(self.controller, key))

        self.refresh_ui()

    # ------------------------------------------------------------------ #
    #                       AI PROVIDER TEXT FIELDS                      #
    # ------------------------------------------------------------------ #

    @classmethod
    def editable_attrs(cls):
        """Controller attribute names for every provider's key and model name."""
        return [f"{mode.lower()}_{suffix}"
                for mode in cls.AI_MODES if mode != "OFF"
                for suffix in cls.AI_FIELD_SUFFIX.values()]

    def field_attr(self, box_type):
        """Controller attribute backing the KEY or MOD box for the active mode."""
        return f"{self.ai_mode.lower()}_{self.AI_FIELD_SUFFIX[box_type]}"

    def get_field(self, box_type):
        return getattr(self, f"{self.field_attr(box_type)}_text", "")

    def set_field(self, box_type, text):
        """Writes a box's text to the screen state and its trimmed form to the controller."""
        attr = self.field_attr(box_type)
        setattr(self, f"{attr}_text", text)
        setattr(self.controller, attr, text.strip())

    def toggle_fps(self):
        self.show_fps = not self.show_fps
        self.controller.show_fps = self.show_fps
        queries.save_global_settings(self.controller)
        self.refresh_ui()

    def toggle_checkerboard_water(self):
        self.checkerboard_water = not self.checkerboard_water
        self.controller.checkerboard_water = self.checkerboard_water
        c.apply_runtime_settings({"checkerboard_water": self.checkerboard_water})
        queries.save_global_settings(self.controller)
        self.refresh_ui()

    def toggle_map_navigation_mode(self):
        """Cycles between CLASSIC (click always opens the plain province menu;
        the view-mode row only swaps the map overlay) and PREEMPTIVE (both of
        those also jump straight into whatever screen the view mode implies).
        See data.constants.MAP_NAVIGATION_MODE."""
        self.map_navigation_mode = "PREEMPTIVE" if self.map_navigation_mode == "CLASSIC" else "CLASSIC"
        self.controller.map_navigation_mode = self.map_navigation_mode
        c.apply_runtime_settings({"map_navigation_mode": self.map_navigation_mode})
        queries.save_global_settings(self.controller)
        self.refresh_ui()

    def open_unit_art(self):
        self.go_to("UNIT_ART")

    def open_keybinds(self):
        self.go_to("KEYBINDS")

    def toggle_drag_button(self):
        """Cycles the dynamic mouse button configuration toggle value string."""
        options = ["RIGHT", "LEFT", "BOTH"]
        current_idx = options.index(self.drag_mouse_toggle)
        next_idx = (current_idx + 1) % len(options)
        
        self.drag_mouse_toggle = options[next_idx]
        
        # Inject the modification to the global fallback configuration value AND controller
        c.apply_runtime_settings({"drag_mouse_toggle": self.drag_mouse_toggle})
        self.controller.drag_mouse_toggle = self.drag_mouse_toggle
        
        queries.save_global_settings(self.controller)
        self.refresh_ui()

    def set_ai_threads(self, val):
        # Scale 0.0-1.0 to 1-8
        threads = 1 + int(val * 7)
        self.ai_threads = threads
        self.controller.ai_threads = threads
        if hasattr(self, 'ai_thread_slider'):
            self.ai_thread_slider.text = f"Maximum AI Threads: {threads}"
        # Silently save whenever the slider moves
        queries.save_global_settings(self.controller)

    def update(self):
        super().update()
        if hasattr(self, 'player_slider'):
            self.player_slider.visible = (self.back_state != "MAP")

    def set_ai_mode(self, mode):
        self.ai_mode = mode
        self.controller.ai_mode = mode
        self.active_input = None # Deselect input box when switching modes
        # Provider clients and the shared HTTP session are cached between turns;
        # drop them so the next call is built against the provider just picked.
        from map_logic.ai import ai_handler
        ai_handler.reset_clients()
        self.refresh_ui()

    def set_ai_immersion_level(self, level):
        self.ai_immersion_level = level
        self.controller.ai_immersion_level = level
        self.refresh_ui()

    def clear_input(self, box_type):
        """Generic method to clear the currently visible input box."""
        self.set_field(box_type, "")
        self.active_input = None
        self.refresh_ui()

    def refresh_ui(self):
        render_settings_buttons(self)

    def toggle_ai_enabled(self):
        if self.ai_mode == "OFF":
            self.set_ai_mode(self.last_ai_mode)
        else:
            self.last_ai_mode = self.ai_mode
            self.set_ai_mode("OFF")

    def reset_defaults(self):
        default_keys = {"BACK": pygame.K_ESCAPE, "ORDERS": pygame.K_q, "FULLSCREEN": pygame.K_F11,
                        "ECONOMY": pygame.K_w, "CLEAR_ORDERS": pygame.K_DELETE}
        self.controller.keybinds = default_keys
        self.controller.target_fps = c.TARGET_FPS

        self.controller.ai_threads = c.DEFAULT_AI_THREADS
        self.ai_threads = self.controller.ai_threads

        self.controller.num_players = 1
        self.num_players = self.controller.num_players

        self.drag_mouse_toggle = c.DEFAULT_MOUSE_BUTTON_TOGGLE
        c.apply_runtime_settings({"drag_mouse_toggle": c.DEFAULT_MOUSE_BUTTON_TOGGLE})
        self.controller.drag_mouse_toggle = c.DEFAULT_MOUSE_BUTTON_TOGGLE

        self.map_navigation_mode = c.DEFAULT_MAP_NAVIGATION_MODE
        c.apply_runtime_settings({"map_navigation_mode": c.DEFAULT_MAP_NAVIGATION_MODE})
        self.controller.map_navigation_mode = c.DEFAULT_MAP_NAVIGATION_MODE

        for key in self.COLOR_FIELDS:
            self.reset_setting(key, refresh=False)

        queries.save_global_settings(self.controller)
        self.refresh_ui()

    # ------------------------------------------------------------------ #
    #                     PATH & COLOR PREFERENCES                       #
    # ------------------------------------------------------------------ #

    def apply_setting(self, key, value, refresh=True):
        """Stores a path/color on the screen, the controller and constants at once.

        All three had to be written together for the change to take effect, and
        forgetting one was the failure mode of the per-setting methods this
        replaces.
        """
        const_attr = (self.DIR_FIELDS.get(key) or self.COLOR_FIELDS[key])[0]
        setattr(self, key, value)
        setattr(self.controller, key, value)
        setattr(c, const_attr, value)
        queries.save_global_settings(self.controller)
        if refresh:
            self.refresh_ui()

    def edit_setting(self, key):
        """Opens the native picker for a path or color setting."""
        current = getattr(self, key)

        def on_chosen(chosen):
            if chosen:
                self.apply_setting(key, chosen)

        if key in self.DIR_FIELDS:
            _const, _default, title = self.DIR_FIELDS[key]
            queries.ask_directory(self, title, current, on_chosen)
        else:
            _const, _default_attr, title = self.COLOR_FIELDS[key]
            queries.ask_color(self, title, current, on_chosen)

    def reset_setting(self, key, refresh=True):
        """Restores a path or color setting to its shipped default."""
        if key in self.DIR_FIELDS:
            default = self.DIR_FIELDS[key][1]
        else:
            default = getattr(c, self.COLOR_FIELDS[key][1])
        self.apply_setting(key, default, refresh=refresh)

    def set_fps(self, val):
        fps = int(20 + (val * 40)) # Scale 0.0-1.0 to 20-60
        self.controller.target_fps = fps
        if hasattr(self, 'fps_slider'):
            self.fps_slider.text = f"Max FPS: {fps}"

    def handle_events(self, events):
        for event in events:
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                mx, my = event.pos
                
                # Check for Input Box Selection Dynamically
                if self.ai_mode != "OFF":
                    key_rect = pygame.Rect(c.SETTINGS_BOX_X, c.SETTINGS_KEY_BOX_Y, c.SETTINGS_BOX_W, c.SETTINGS_BOX_H)
                    mod_rect = pygame.Rect(c.SETTINGS_BOX_X, c.SETTINGS_MOD_BOX_Y, c.SETTINGS_BOX_W, c.SETTINGS_BOX_H)
                    
                    if key_rect.collidepoint(mx, my):
                        self.active_input = f"{self.ai_mode}_KEY"
                    elif mod_rect.collidepoint(mx, my):
                        self.active_input = f"{self.ai_mode}_MOD"
                    else:
                        self.active_input = None

            for el in self.elements:
                el.handle_event(event)
            self.additional_events(event)

    def additional_events(self, event):
        if self.active_input and self.ai_mode != "OFF":
            box_type = self.active_input.rsplit("_", 1)[-1]
            if box_type in self.AI_FIELD_SUFFIX:
                limit = c.MAX_API_KEY_LENGTH if box_type == "KEY" else c.MAX_MODEL_NAME_LENGTH
                new_text, _status = ui_elements.process_text_input(event, self.get_field(box_type),
                                                                  max_length=limit)
                self.set_field(box_type, new_text)

    # ------------------------------------------------------------------ #
    #                             RENDERING                              #
    # ------------------------------------------------------------------ #

    @property
    def dir_box_x(self):
        return c.SCREEN_WIDTH // 2 - self.DIR_BOX_W // 2 + 50

    def draw_text_field(self, surface, rect, text, active=False):
        """Draws one of the screen's read-only/editable text boxes.

        Used for the path boxes and the API key/model boxes alike; `active`
        lights the fill and appends the caret.
        """
        ui_elements.draw_text_box(surface, rect, text, active=active, pad_x=5)

    def additional_draw(self, surface):
        font = fonts.get("normal")
        x = self.dir_box_x

        # --- PATH BOXES & WATER COLOR SWATCHES (Middle Top) ---
        for y, kind, key, label in self.PATH_ROWS:
            value = getattr(self, key)

            if kind == "dir":
                surface.blit(font.render(label, True, (100, 100, 100)), (x, y - 20))
                self.draw_text_field(surface, pygame.Rect(x, y, self.DIR_BOX_W, self.DIR_BOX_H), value)
            else:
                # Color rows label to the right of the row and show a swatch
                surface.blit(font.render(label, True, (100, 100, 100)), (x, y + 10))
                swatch = pygame.Rect(x + self.DIR_BOX_W - self.COLOR_BOX_W, y,
                                     self.COLOR_BOX_W, self.DIR_BOX_H)
                pygame.draw.rect(surface, value, swatch)
                pygame.draw.rect(surface, (150, 150, 150), swatch, 1)

        if self.ai_mode == "OFF":
            return

        # --- API KEY / URL box, then MODEL box ---
        boxes = [
            ("KEY", c.SETTINGS_KEY_BOX_Y,
             "Ollama Base URL (blank = localhost):" if self.ai_mode == "OLLAMA"
             else f"Paste {self.ai_mode.capitalize()} API Key:"),
            ("MOD", c.SETTINGS_MOD_BOX_Y, f"{self.ai_mode.capitalize()} Model Name:"),
        ]
        for box_type, box_y, label in boxes:
            surface.blit(font.render(label, True, c.UI_TEXT_LIGHT), (c.SETTINGS_BOX_X, box_y - 25))
            rect = pygame.Rect(c.SETTINGS_BOX_X, box_y, c.SETTINGS_BOX_W, c.SETTINGS_BOX_H)
            self.draw_text_field(surface, rect, self.get_field(box_type),
                                 active=self.active_input == f"{self.ai_mode}_{box_type}")

    def set_players(self, val):
        self.num_players = 1 + int(val * 7)
        self.controller.num_players = self.num_players
        if hasattr(self, 'player_slider'):
            self.player_slider.text = f"Players: {self.num_players}"

    def save_and_go_back(self, execute_exit=True):
        queries.save_global_settings(self.controller)
        
        if execute_exit:
            self.exit_screen()

    def handle_back_key(self):
        self.save_and_go_back()

    def toggle_full(self):
        self.controller.toggle_fullscreen()
        self.fullscreen = getattr(self.controller, 'is_fullscreen', False)

    def set_volume(self, val):
        self.sfx_volume = val
        self.controller.sfx_volume = val
        ui_elements.set_sfx_volume(val)
