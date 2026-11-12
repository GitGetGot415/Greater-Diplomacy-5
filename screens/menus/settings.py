import pygame
from ui.widgets import ui_elements
from ui import sound_effects
from ui.widgets.ui_elements import Button, Slider, TextField, make_info_button, make_toggle_button
from ui.navigation.screen import Screen
import data.constants as c
from data import queries
from data.io import settings_schema
from ui.dialogs import pickers
from ui.rendering.font_manager import fonts
from ui.bars import ui_bars
from ui import dialogs
from map_logic.ai import ai_handler
from screens.menus.keybinds import default_keybinds

MAX_API_KEY_LENGTH = 200
MAX_MODEL_NAME_LENGTH = 150


# All categories share one fixed frame; changing a category only rebuilds its controls.
SETTINGS_CATEGORIES = (("GAME", "Game & Interface"), ("DISPLAY", "Display & Appearance"), ("CONTROLS", "Controls"), ("AI", "LLM AI"), ("FILES", "Default Paths"))
SETTINGS_MARGIN = 32
SETTINGS_PANEL_TOP = 100
SETTINGS_PANEL_HEIGHT = 568
SETTINGS_NAV_WIDTH = 240
SETTINGS_PANEL_GAP = 18
SETTINGS_CONTENT_X = SETTINGS_MARGIN + SETTINGS_NAV_WIDTH + SETTINGS_PANEL_GAP
SETTINGS_CONTENT_WIDTH = c.SCREEN_WIDTH - SETTINGS_CONTENT_X - SETTINGS_MARGIN
SETTINGS_NAV_RECT = (SETTINGS_MARGIN, SETTINGS_PANEL_TOP, SETTINGS_NAV_WIDTH, SETTINGS_PANEL_HEIGHT)
SETTINGS_CONTENT_RECT = (SETTINGS_CONTENT_X, SETTINGS_PANEL_TOP, SETTINGS_CONTENT_WIDTH, SETTINGS_PANEL_HEIGHT)
SETTINGS_PADDING = 28
SETTINGS_X = SETTINGS_CONTENT_X + SETTINGS_PADDING
SETTINGS_SECOND_X = SETTINGS_X + 458
SETTINGS_FIRST_Y = SETTINGS_PANEL_TOP + 80
SETTINGS_ROW_GAP = 52
SETTINGS_NAV_SIZE = (SETTINGS_NAV_WIDTH - 24, 44)
SETTINGS_NAV_GAP = 58
SETTINGS_OPTION_SIZE = (c.SIZES["setting_option"][0], 32)
SETTINGS_LINK_SIZE = (180, 110)
SETTINGS_LINK_GAP = 20
SETTINGS_SLIDER_WIDTH = 300
SETTINGS_BACK_POS = (SETTINGS_MARGIN, 28)
SETTINGS_RESET_Y = SETTINGS_PANEL_TOP + SETTINGS_PANEL_HEIGHT - 64
SETTINGS_RESET_SIZE = (320, 36)
SETTINGS_INFO_GAP_X = 10
SETTINGS_INFO_X = SETTINGS_X + SETTINGS_OPTION_SIZE[0] + SETTINGS_INFO_GAP_X
SETTINGS_INFO_Y_NUDGE = (SETTINGS_OPTION_SIZE[1] - c.SIZES["scenario_setting_info"][1]) // 2
SETTINGS_AI_TOGGLE_Y = SETTINGS_PANEL_TOP + 66
SETTINGS_AI_PROVIDER_Y = SETTINGS_AI_TOGGLE_Y + 82
SETTINGS_AI_PROVIDER_STEP_X = 116
SETTINGS_BOX_X = SETTINGS_X
SETTINGS_BOX_W = 400
SETTINGS_BOX_H = 35
SETTINGS_KEY_BOX_Y = SETTINGS_AI_PROVIDER_Y + 74
SETTINGS_MOD_BOX_Y = SETTINGS_KEY_BOX_Y + 75
SETTINGS_AI_IMMERSION_Y = SETTINGS_MOD_BOX_Y + 112
SETTINGS_AI_THREAD_Y = SETTINGS_AI_IMMERSION_Y + 8
SETTINGS_CLEAR_BTN_GAP_X = 10
SETTINGS_PANEL_COLOR = (34, 40, 52)
SETTINGS_PANEL_BORDER = (90, 110, 140)
SETTINGS_BACKGROUND_COLOR = (32, 34, 40)

SETTINGS_AI_INFO_TITLE = "LLM AI"
SETTINGS_AI_INFO_TEXT = (
    "LLM AI lets a large language model (the LLM) from the provider you choose handle "
    "diplomacy for AI countries. The LLM only handles diplomacy.\n"
    "\n"
    "The rule-based AI still runs every AI country. The rule-based AI moves armies, "
    "builds, researches, and decides which diplomatic actions are legal. The LLM chooses "
    "from those legal actions and writes the messages, so the LLM cannot break the game's "
    "rules.\n"
    "\n"
    "With LLM AI off, the rule-based AI makes every choice, and AI countries answer with "
    "prewritten lines.\n"
    "\n"
    "LITE AI: The LLM only answers messages and notes that you write yourself.\n"
    "\n"
    "FULL AI: The LLM answers all of your proposals and messages. The rule-based AI still "
    "chooses which proposals AI countries make, and AI countries use prewritten lines with "
    "each other.\n"
    "\n"
    "MAJOR AI: Everything in FULL AI. The LLM also handles the diplomacy of the major "
    "countries: leading powers, faction leaders, and countries that border you or fight "
    "you. For these countries, the LLM chooses which proposals to make, writes letters to "
    "other countries and to you, and keeps private notes of their plans.\n"
    "\n"
    "ABSOLUTE AI: The LLM handles the diplomacy of every AI country. This is the most "
    "lifelike level and the slowest, because the LLM receives the most requests each "
    "turn.\n"
    "\n"
    "When the LLM reads a letter for a country, the letter can change that country's "
    "opinion of the letter's writer. The writer can be a player or another AI country.\n"
    "\n"
    "Maximum AI Threads sets how many LLM requests run at once. More threads speed up "
    "hosted providers, but more threads can slow a local Ollama model."
)

# Help follows each setting when its category is rebuilt.
SETTINGS_INFO_ROWS = (
    ("fullscreen", "Toggle Fullscreen",
     "Switches the game window between fullscreen and windowed mode."),
    ("checkerboard_water", "Checkerboard Water",
     "Shows an opaque blue checkerboard on the ocean, aligned with the sky pattern at the horizon. "
     "The water pattern follows "
     "camera movement, zoom, and tilt. Off by default."),
    ("show_fps", "Show FPS",
     "Displays a live frames-per-second counter on screen."),
    ("show_unclaimed", "Show Unassigned",
     "Shows the Unassigned army card for your units outside army groups. "
     "Enabled by default. The card stays hidden when all units are assigned."),
    ("show_strategic_intro_popup", "Show Strategic Tutorial",
     "Shows the Help window when a fresh strategic game begins. Its categories cover the "
     "basics, from map controls to production, research, and diplomacy. "
     "The Help button on the map reopens it."),
    ("show_tactical_intro_popup", "Show Tactical Tutorial",
     "Shows the Help window when a fresh tactical game begins. "
     "The Help button on the map reopens it."),
    ("control_mode", "Controls",
     "Auto chooses Mobile controls on Android and iOS and Desktop controls on other systems at startup. "
     "Mobile supports tap to select, hold and release for a right-click action, drag to pan, and pinch to zoom. "
     "Desktop uses the existing mouse and keyboard controls. Changing controls cancels unfinished touch gestures."),
    ("map_navigation_mode", "Map Navigation",
     "Classic: clicking a tile always opens the plain province menu, and the "
     "Resources/Blank/Units/Economy ui view buttons only switch "
     "the map's view mode. Orders and Production are reached only through "
     "their own buttons; Battle is opened from Orders. \n"
     "Preemptive: a click jumps "
     "straight into the screen the current view mode implies (Orders for "
     "Units, including a fighting tile). "
     "Click to switch between them."),
    ("battle_display_mode", "Battle Display",
     "Compact hides units that are currently fighting beneath an opaque combat "
     "bubble. Full keeps those units visible and makes the bubble translucent. "
     "Click to switch between them."),
    ("army_group_animations", "Army Group Animations",
     "Controls the compression and expansion animation when units become or "
     "leave a strategic army-group marker. Disabling it switches immediately."),
)


def make_option_buttons(options, on_select, current, size="ai_opinion", color="blue", font_preset="small"):
    """Share selection styling and callback binding for provider and immersion choices."""
    return [ui_elements.make_choice_button(x, y, size, label, value == current, lambda v=value: on_select(v), idle_color=color, font_preset=font_preset) for x, y, value, label in options]


def render_settings_buttons(settings_screen):
    """Build navigation and only the active category's controls."""
    screen = settings_screen
    screen.elements = [ui_elements.make_back_button(screen.save_and_go_back, pos=SETTINGS_BACK_POS)]
    screen.elements.extend(ui_elements.make_choice_button(SETTINGS_MARGIN + 12, SETTINGS_PANEL_TOP + 24 + index * SETTINGS_NAV_GAP, SETTINGS_NAV_SIZE, label, screen.sub_state == category, lambda value=category: screen.set_sub_state(value), idle_color="grey", font_preset="small", sound_kind="select_category") for index, (category, label) in enumerate(SETTINGS_CATEGORIES))
    screen.ai_fields = {}
    screen.player_slider = screen.fps_slider = screen.ai_thread_slider = None
    screen.checkerboard_gradient_slider = screen.checkerboard_speed_slider = None

    if screen.sub_state == "GAME":
        rows = (
            ("show_strategic_intro_popup", "Show Strategic Tutorial", screen.show_strategic_intro_popup, lambda: screen.toggle_intro_popup(False)),
            ("show_tactical_intro_popup", "Show Tactical Tutorial", screen.show_tactical_intro_popup, lambda: screen.toggle_intro_popup(True)),
            ("show_unclaimed", "Show Unassigned", screen.show_unclaimed, screen.toggle_show_unclaimed),
            ("army_group_animations", "Army Group Animations", screen.army_group_animations, screen.toggle_army_group_animations),
        )
        for index, (key, label, enabled, callback) in enumerate(rows):
            y = SETTINGS_FIRST_Y + index * SETTINGS_ROW_GAP
            screen.elements.append(make_toggle_button(SETTINGS_X, y, SETTINGS_OPTION_SIZE, label, enabled, callback, font_preset="small"))
            screen.add_setting_info(key, y)
        y = SETTINGS_FIRST_Y + len(rows) * SETTINGS_ROW_GAP
        screen.elements.append(Button(SETTINGS_X, y, SETTINGS_OPTION_SIZE, "purple", f"Battle Display: {screen.battle_display_mode.title()}", screen.toggle_battle_display_mode))
        screen.add_setting_info("battle_display_mode", y)
        screen.player_slider = Slider(SETTINGS_X, y + 92, SETTINGS_SLIDER_WIDTH, f"Players: {screen.num_players}", (screen.num_players - 1) / 7.0, screen.set_players)
        # A live game's participant count cannot be changed from Settings.
        screen.player_slider.visible = screen.back_state != "MAP"
        screen.elements.append(screen.player_slider)

    elif screen.sub_state == "DISPLAY":
        for index, (key, label, callback) in enumerate((("fullscreen", "Toggle Fullscreen", screen.toggle_full), ("show_fps", "Show FPS", screen.toggle_fps), ("checkerboard_water", "Checkerboard Water", screen.toggle_checkerboard_water))):
            y = SETTINGS_FIRST_Y + index * SETTINGS_ROW_GAP
            control = Button(SETTINGS_X, y, SETTINGS_OPTION_SIZE, "blue", label, callback) if key == "fullscreen" else make_toggle_button(SETTINGS_X, y, SETTINGS_OPTION_SIZE, label, getattr(screen, key), callback)
            screen.elements.append(control)
            screen.add_setting_info(key, y)
        # Use the same 20..60 scale as set_fps so rebuilding never moves the handle.
        screen.fps_slider = Slider(SETTINGS_X, SETTINGS_FIRST_Y + 3 * SETTINGS_ROW_GAP + 32, SETTINGS_SLIDER_WIDTH, f"Max FPS: {screen.controller.target_fps}", (screen.controller.target_fps - 20) / 40.0, screen.set_fps)
        screen.checkerboard_gradient_slider = Slider(SETTINGS_X, screen.fps_slider.rect.y + 78, SETTINGS_SLIDER_WIDTH, f"Checkerboard Gradient: {screen.controller.checkerboard_gradient_strength:.2f}", screen.controller.checkerboard_gradient_strength, screen.set_checkerboard_gradient, visual_max=c.MAX_CHECKERBOARD_GRADIENT_STRENGTH, allowed_max=c.MAX_CHECKERBOARD_GRADIENT_STRENGTH)
        screen.checkerboard_speed_slider = Slider(SETTINGS_X, screen.checkerboard_gradient_slider.rect.y + 78, SETTINGS_SLIDER_WIDTH, f"Checkerboard Speed: {screen.controller.checkerboard_scroll_speed:g}", screen.controller.checkerboard_scroll_speed, screen.set_checkerboard_speed, visual_max=c.MAX_CHECKERBOARD_SCROLL_SPEED, allowed_max=c.MAX_CHECKERBOARD_SCROLL_SPEED)
        screen.elements.extend([screen.fps_slider, screen.checkerboard_gradient_slider, screen.checkerboard_speed_slider])
        screen.elements.append(Button(SETTINGS_SECOND_X, SETTINGS_FIRST_Y + 4 * SETTINGS_ROW_GAP, SETTINGS_LINK_SIZE, "blue", "Unit Art", screen.open_unit_art, image=ui_bars.get_ui_image("Brush.png")))

    elif screen.sub_state == "CONTROLS":
        screen.elements.append(Button(SETTINGS_X, SETTINGS_FIRST_Y, SETTINGS_OPTION_SIZE, "purple", f"Controls: {screen.control_mode.title()}", screen.cycle_control_mode))
        screen.add_setting_info("control_mode", SETTINGS_FIRST_Y)
        y = SETTINGS_FIRST_Y + SETTINGS_ROW_GAP
        screen.elements.append(Button(SETTINGS_X, y, SETTINGS_OPTION_SIZE, "purple", f"Map Navigation: {screen.map_navigation_mode.title()}", screen.toggle_map_navigation_mode))
        screen.add_setting_info("map_navigation_mode", y)
        screen.elements.extend([
            Button(SETTINGS_X, y + SETTINGS_ROW_GAP, SETTINGS_LINK_SIZE, "purple", "Keybinds", screen.open_keybinds, image=ui_bars.get_ui_image("Keybind.png"), layout="vertical"),
            Button(SETTINGS_X + SETTINGS_LINK_SIZE[0] + SETTINGS_LINK_GAP, y + SETTINGS_ROW_GAP, SETTINGS_LINK_SIZE, "purple", "Mouse Settings", screen.open_mouse_settings, image=ui_bars.get_ui_image("Blank.png", scale=0.6, directory=f"{c.ASSETS_ROOT_DIR}/mouse"), layout="vertical"),
        ])

    elif screen.sub_state == "AI":
        ai_is_on = screen.ai_mode != "OFF"
        screen.elements.extend([
            make_toggle_button(SETTINGS_X, SETTINGS_AI_TOGGLE_Y, SETTINGS_OPTION_SIZE, "LLM AI", ai_is_on, screen.toggle_ai_enabled),
            # Inline parts keep the existing long explanation left-aligned and scrollable.
            make_info_button(SETTINGS_INFO_X, SETTINGS_AI_TOGGLE_Y, lambda: dialogs.show_info(SETTINGS_AI_INFO_TITLE, SETTINGS_AI_INFO_TEXT, inline_parts=[(SETTINGS_AI_INFO_TEXT, None)]), y_offset=SETTINGS_INFO_Y_NUDGE),
        ])
        if ai_is_on:
            screen.elements.extend(make_option_buttons([(SETTINGS_X + index * SETTINGS_AI_PROVIDER_STEP_X, SETTINGS_AI_PROVIDER_Y, mode, screen.AI_PROVIDER_LABELS.get(mode, mode)) for index, mode in enumerate(screen.ai_modes[1:])], screen.set_ai_mode, screen.ai_mode))
            clear_x = SETTINGS_BOX_X + SETTINGS_BOX_W + SETTINGS_CLEAR_BTN_GAP_X
            default_x = clear_x + c.SIZES["small_square"][0] + SETTINGS_CLEAR_BTN_GAP_X
            for box_type, box_y, _label in screen.ai_field_rows():
                field = TextField(SETTINGS_BOX_X, box_y, SETTINGS_BOX_W, SETTINGS_BOX_H, screen.get_field(box_type), max_length=MAX_MODEL_NAME_LENGTH if box_type == "MOD" else MAX_API_KEY_LENGTH, on_change=lambda text, box=box_type: screen.set_field(box, text), pad_x=5)
                screen.ai_fields[box_type] = field
                screen.elements.extend([field, Button(clear_x, box_y, "small_square", "red", "X", lambda box=box_type: screen.clear_input(box))])
                if box_type == "MOD":
                    screen.elements.append(Button(default_x, box_y, "small", "blue", "Default", screen.reset_model_default))
            # MAJOR lets the LLM drive diplomacy for the countries a player notices,
            # between FULL's human-facing diplomacy and ABSOLUTE's every country.
            screen.elements.extend(make_option_buttons([(SETTINGS_X + index * SETTINGS_AI_PROVIDER_STEP_X, SETTINGS_AI_IMMERSION_Y, level, f"{level} AI") for index, level in enumerate(c.AI_IMMERSION_LEVELS)], screen.set_ai_immersion_level, screen.ai_immersion_level, size=(108, 32), color="red"))
            screen.ai_thread_slider = Slider(SETTINGS_SECOND_X + 38, SETTINGS_AI_THREAD_Y, SETTINGS_SLIDER_WIDTH, f"Maximum AI Threads: {screen.ai_threads}", (screen.ai_threads - 1) / 7.0, screen.set_ai_threads)
            screen.elements.append(screen.ai_thread_slider)

    # Field rows are shared with drawing so labels, controls and swatches agree.
    for y, kind, key, _label in screen.preference_rows():
        edit_x = SETTINGS_X + screen.DIR_BOX_W + SETTINGS_CLEAR_BTN_GAP_X if kind == "dir" else SETTINGS_SECOND_X + screen.COLOR_BOX_W + SETTINGS_CLEAR_BTN_GAP_X
        screen.elements.extend([
            Button(edit_x, y, "small", "blue", "Edit", lambda name=key: screen.edit_setting(name)),
            Button(edit_x + c.SIZES["small"][0] + SETTINGS_CLEAR_BTN_GAP_X, y, "small", "red", "Reset", lambda name=key: screen.reset_setting(name)),
        ])
    reset_label = dict(SETTINGS_CATEGORIES)[screen.sub_state]
    screen.elements.append(Button(SETTINGS_X, SETTINGS_RESET_Y, SETTINGS_RESET_SIZE, "red", f"Reset {reset_label} Defaults", screen.reset_category_defaults, font_preset="small"))
    for element in screen.elements:
        if isinstance(element, Button):
            element.fit_text = True
            element.fit_single_line = True


class Settings(Screen):
    title = "Settings"
    player_slider = None
    fps_slider = None
    ai_thread_slider = None
    #: The active provider's TextField per box type, rebuilt with the buttons.
    ai_fields = {}

    # Hosted providers use API keys and model names. Ollama uses a base URL.
    AI_MODES = ["OFF", "OLLAMA", "GEMINI", "CHATGPT", "CLAUDE", "DEEPSEEK", "KIMI", "OPENROUTER"]
    # Preserve service-name capitalization in the UI.
    AI_PROVIDER_LABELS = {"OPENROUTER": "OpenRouter"}
    AI_FIELD_SUFFIX = {"KEY": "api_key", "MOD": "model"}

    # key -> (constants attribute to keep in sync, default value, picker title)
    DIR_FIELDS = {
        "saves_dir":            ("SAVES_DIR",            c.DEFAULT_SAVES_DIR,     "Select Saves Directory"),
        "custom_scenarios_dir": ("SCENARIOS_CUSTOM_DIR", c.DEFAULT_SCENARIOS_CUSTOM_DIR, "Select Custom Scenarios Directory"),
        "tournament_saves_dir": ("TOURNAMENT_SAVES_DIR", c.DEFAULT_TOURNAMENT_SAVES_DIR, "Select Tournament Saves Directory"),
    }
    # key -> (constants attribute, constants attribute holding the default, picker title)
    COLOR_FIELDS = {
        "ocean_light_color": ("OCEAN_LIGHT_BLUE", "DEFAULT_OCEAN_LIGHT_BLUE", "Select Zoom-In Water Color"),
        "ocean_dark_color":  ("OCEAN_DARK_BLUE",  "DEFAULT_OCEAN_DARK_BLUE",  "Select Zoom-Out Water Color"),
    }

    # Category resets retain credentials, models, URLs, audio, and Unit Art.
    CATEGORY_RESET_FIELDS = {
        "GAME": ("num_players", "show_strategic_intro_popup", "show_tactical_intro_popup", "show_unclaimed", "battle_display_mode", "army_group_animations"),
        "DISPLAY": ("target_fps", "show_fps", "checkerboard_water", "checkerboard_gradient_strength", "checkerboard_scroll_speed", "ocean_light_color", "ocean_dark_color"),
        "CONTROLS": ("map_navigation_mode", "control_mode", "mouse_button_actions", "orders_key_changes_screen", "economy_key_changes_screen"),
        "AI": ("ai_mode", "ai_immersion_level", "ai_threads"),
        "FILES": tuple(DIR_FIELDS),
    }

    DIR_BOX_W = 400
    DIR_BOX_H = 35
    COLOR_BOX_W = 40

    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.bg_color = SETTINGS_BACKGROUND_COLOR
        self.sub_state = "GAME"
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

        self.show_strategic_intro_popup = self.controller.show_strategic_intro_popup
        self.show_tactical_intro_popup = self.controller.show_tactical_intro_popup
        self.show_unclaimed = self.controller.show_unclaimed

        self.ai_threads = self.controller.ai_threads
        self.show_fps = self.controller.show_fps
        self.checkerboard_water = self.controller.checkerboard_water
        self.map_navigation_mode = self.controller.map_navigation_mode
        self.control_mode = self.controller.control_mode
        self.battle_display_mode = self.controller.battle_display_mode
        self.army_group_animations = self.controller.army_group_animations

        for key in list(self.DIR_FIELDS) + list(self.COLOR_FIELDS):
            setattr(self, key, getattr(self.controller, key))

        self.refresh_ui()

    def on_enter(self, app, previous):
        self.return_to_previous_context(app, previous)
        # The navigation tutorial may persist its opt-out while Settings
        # is closed; rebuild so its toggle always reflects that value.
        self.refresh_ui()

    def draw_background(self, surface):
        super().draw_background(surface)
        ui_elements.draw_pixel_panel(surface, pygame.Rect(SETTINGS_NAV_RECT), SETTINGS_PANEL_COLOR, SETTINGS_PANEL_BORDER, gradient_strength=0.25)
        ui_elements.draw_pixel_panel(surface, pygame.Rect(SETTINGS_CONTENT_RECT), SETTINGS_PANEL_COLOR, SETTINGS_PANEL_BORDER, gradient_strength=0.25)

    def set_sub_state(self, state):
        self.cancel_pointer_input()
        super().set_sub_state(state)

    def add_setting_info(self, key, y):
        _key, title, text = next(row for row in SETTINGS_INFO_ROWS if row[0] == key)
        self.elements.append(make_info_button(SETTINGS_INFO_X, y, lambda: dialogs.show_info(title, text), y_offset=SETTINGS_INFO_Y_NUDGE))

    # ------------------------------------------------------------------ #
    #                       AI PROVIDER TEXT FIELDS                      #
    # ------------------------------------------------------------------ #

    @classmethod
    def editable_attrs(cls):
        """Controller attributes for provider credentials and models."""
        return [cls.provider_field_attr(mode, box_type)
                for mode in cls.AI_MODES if mode != "OFF"
                for box_type in cls.AI_FIELD_SUFFIX]

    @classmethod
    def provider_field_attr(cls, mode, box_type):
        """Use a URL field for Ollama and API-key fields for hosted providers."""
        if mode == "OLLAMA" and box_type == "KEY":
            return "ollama_base_url"
        return f"{mode.lower()}_{cls.AI_FIELD_SUFFIX[box_type]}"

    def ai_field_rows(self):
        """Share field positions and labels across rendering and input handling."""
        provider_name = self.AI_PROVIDER_LABELS.get(self.ai_mode, self.ai_mode.capitalize())
        return [
            ("KEY", SETTINGS_KEY_BOX_Y,
             "Ollama Base URL (blank = localhost):" if self.ai_mode == "OLLAMA"
             else f"Paste {provider_name} API Key:"),
            ("MOD", SETTINGS_MOD_BOX_Y, f"{provider_name} Model Name:"),
        ]

    def field_attr(self, box_type):
        """Controller attribute for an editable field in the active mode."""
        return self.provider_field_attr(self.ai_mode, box_type)

    @property
    def active_input(self):
        """The focused box as "{MODE}_KEY" or "{MODE}_MOD", or None."""
        for box_type, field in self.ai_fields.items():
            if field.active:
                return f"{self.ai_mode}_{box_type}"
        return None

    @property
    def text_input_active(self):
        return self.active_input is not None or super().text_input_active

    def get_field(self, box_type):
        return getattr(self, f"{self.field_attr(box_type)}_text", "")

    def set_field(self, box_type, text):
        """Writes a box's text to the screen state and its trimmed form to the controller."""
        attr = self.field_attr(box_type)
        setattr(self, f"{attr}_text", text)
        setattr(self.controller, attr, text.strip())
        if box_type in self.ai_fields:
            self.ai_fields[box_type].text = text

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

    def cycle_control_mode(self):
        self.control_mode = c.CONTROL_MODES[(c.CONTROL_MODES.index(self.control_mode) + 1)
                                            % len(c.CONTROL_MODES)]
        self.controller.control_mode = self.control_mode
        c.apply_runtime_settings({"control_mode": self.control_mode})
        self.controller.touch_input.cancel()
        queries.save_global_settings(self.controller)
        self.refresh_ui()

    def toggle_battle_display_mode(self):
        """Cycles between the compact and full map battle presentations."""
        self.battle_display_mode = (
            "COMPACT" if self.battle_display_mode == "FULL" else "FULL")
        self.controller.battle_display_mode = self.battle_display_mode
        c.apply_runtime_settings({"battle_display_mode": self.battle_display_mode})
        queries.save_global_settings(self.controller)
        self.refresh_ui()

    def open_unit_art(self):
        self.go_to("UNIT_ART")

    def open_keybinds(self):
        self.go_to("KEYBINDS")

    def open_mouse_settings(self):
        self.go_to("MOUSE_SETTINGS")

    def toggle_intro_popup(self, tactical_mode):
        """Persist the startup tutorial preference for one play mode."""
        name = settings_schema.intro_popup_setting(tactical_mode)
        enabled = not getattr(self, name)
        setattr(self, name, enabled)
        setattr(self.controller, name, enabled)
        queries.save_global_settings(self.controller)
        self.refresh_ui()

    def toggle_show_unclaimed(self):
        """Save whether the army tray displays units outside army groups."""
        self.show_unclaimed = not self.show_unclaimed
        self.controller.show_unclaimed = self.show_unclaimed
        c.apply_runtime_settings({"show_unclaimed": self.show_unclaimed})
        queries.save_global_settings(self.controller)
        self.refresh_ui()

    def toggle_army_group_animations(self):
        """Persist whether strategic army markers animate between presentations."""
        self.army_group_animations = not self.army_group_animations
        self.controller.army_group_animations = self.army_group_animations
        c.apply_runtime_settings({"army_group_animations": self.army_group_animations})
        queries.save_global_settings(self.controller)
        self.refresh_ui()

    def set_ai_threads(self, val):
        # Scale 0.0-1.0 to 1-8
        threads = 1 + int(val * 7)
        self.ai_threads = threads
        self.controller.ai_threads = threads
        if self.ai_thread_slider is not None:
            self.ai_thread_slider.text = f"Maximum AI Threads: {threads}"
        # Silently save whenever the slider moves
        queries.save_global_settings(self.controller)

    def update(self):
        super().update()
        if self.player_slider is not None:
            self.player_slider.visible = (self.back_state != "MAP")

    def set_ai_mode(self, mode):
        self.ai_mode = mode
        self.controller.ai_mode = mode
        # Provider clients and the shared HTTP session are cached between turns;
        # drop them so the next call is built against the provider just picked.
        ai_handler.reset_clients()
        self.refresh_ui()

    def set_ai_immersion_level(self, level):
        self.ai_immersion_level = level
        self.controller.ai_immersion_level = level
        self.refresh_ui()

    def clear_input(self, box_type):
        """Generic method to clear the currently visible input box."""
        self.set_field(box_type, "")
        self.refresh_ui()

    def reset_model_default(self):
        """Sets the active provider's model to the default a new settings file gets."""
        self.set_field("MOD", settings_schema.defaults()[self.field_attr("MOD")])
        self.refresh_ui()

    def refresh_ui(self):
        # Either tutorial can change its preference while Settings is
        # closed, so re-read the cached persisted values whenever this screen
        # rebuilds rather than showing a stale controller value.
        saved = queries.get_settings()
        for tactical_mode in (False, True):
            name = settings_schema.intro_popup_setting(tactical_mode)
            enabled = settings_schema.read_setting(saved, name, getattr(self.controller, name))
            setattr(self, name, enabled)
            setattr(self.controller, name, enabled)
        render_settings_buttons(self)

    def toggle_ai_enabled(self):
        if self.ai_mode == "OFF":
            self.set_ai_mode(self.last_ai_mode)
        else:
            self.last_ai_mode = self.ai_mode
            self.set_ai_mode("OFF")

    def reset_defaults(self):
        self.controller.keybinds = default_keybinds()
        # Preserve this control's scope: provider credentials, audio and the
        # other preferences outside this list are not part of this reset.
        names = (
            "target_fps", "ai_threads", "num_players", "show_fps",
            "checkerboard_water", "checkerboard_gradient_strength", "checkerboard_scroll_speed",
            "show_strategic_intro_popup", "show_tactical_intro_popup", "show_unclaimed", "map_navigation_mode", "control_mode",
            "battle_display_mode", "army_group_animations", "mouse_button_actions",
        )
        self._reset_fields(names + tuple(self.COLOR_FIELDS))

    def reset_category_defaults(self):
        """Reset only this category, preserving API keys, models, URLs and audio."""
        names = self.CATEGORY_RESET_FIELDS[self.sub_state]
        if self.sub_state == "GAME" and self.back_state == "MAP":
            names = tuple(name for name in names if name != "num_players")
        if self.sub_state == "CONTROLS":
            self.controller.keybinds = default_keybinds()
            self.controller.touch_input.cancel()
        if self.sub_state == "AI":
            ai_handler.reset_clients()
        self._reset_fields(names)

    def _reset_fields(self, names):
        defaults = settings_schema.defaults()
        for name in names:
            if name in self.DIR_FIELDS or name in self.COLOR_FIELDS:
                self.reset_setting(name, refresh=False)
            else:
                setattr(self.controller, name, defaults[name])
                if hasattr(self, name):
                    setattr(self, name, defaults[name])
        c.apply_runtime_settings({name: defaults[name] for name in names})
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
            pickers.ask_directory(self, title, current, on_chosen)
        else:
            _const, _default_attr, title = self.COLOR_FIELDS[key]
            pickers.ask_color(self, title, current, on_chosen)

    def reset_setting(self, key, refresh=True):
        """Restores a path or color setting to its shipped default."""
        self.apply_setting(key, settings_schema.defaults()[key], refresh=refresh)

    def set_checkerboard_gradient(self, val):
        strength = round(val, 2)
        self.controller.checkerboard_gradient_strength = strength
        c.apply_runtime_settings({"checkerboard_gradient_strength": strength})
        self.checkerboard_gradient_slider.text = f"Checkerboard Gradient: {strength:.2f}"
        queries.save_global_settings(self.controller)

    def set_checkerboard_speed(self, val):
        speed = round(val)
        self.controller.checkerboard_scroll_speed = speed
        c.apply_runtime_settings({"checkerboard_scroll_speed": speed})
        self.checkerboard_speed_slider.text = f"Checkerboard Speed: {speed}"
        queries.save_global_settings(self.controller)

    def set_fps(self, val):
        fps = int(20 + (val * 40)) # Scale 0.0-1.0 to 20-60
        self.controller.target_fps = fps
        if self.fps_slider is not None:
            self.fps_slider.text = f"Max FPS: {fps}"

    # ------------------------------------------------------------------ #
    #                             RENDERING                              #
    # ------------------------------------------------------------------ #

    def preference_rows(self):
        """Return the active category's path or color rows for controls and drawing."""
        if self.sub_state == "FILES":
            return [(SETTINGS_FIRST_Y + 35 + index * 108, "dir", key, label) for index, (key, label) in enumerate((("saves_dir", "Saves Path:"), ("custom_scenarios_dir", "Custom Maps Path:"), ("tournament_saves_dir", "Tournament Saves Path:")))]
        if self.sub_state == "DISPLAY":
            return [(SETTINGS_FIRST_Y + index * 100, "color", key, label) for index, (key, label) in enumerate((("ocean_light_color", "Zoom-In Water Color:"), ("ocean_dark_color", "Zoom-Out Water Color:")))]
        return []

    def draw_path_box(self, surface, rect, text):
        """Draws one of the screen's read-only path boxes."""
        ui_elements.draw_text_box(surface, rect, text, pad_x=5)

    def additional_draw(self, surface):
        font = fonts.get("normal")
        heading = fonts.get("heading2").render(dict(SETTINGS_CATEGORIES)[self.sub_state], True, c.UI_TEXT_LIGHT)
        surface.blit(heading, (SETTINGS_X, SETTINGS_PANEL_TOP + 22))
        for y, kind, key, label in self.preference_rows():
            x = SETTINGS_X if kind == "dir" else SETTINGS_SECOND_X
            surface.blit(font.render(label, True, c.UI_TEXT_LIGHT), (x, y - 30))
            if kind == "dir":
                self.draw_path_box(surface, pygame.Rect(x, y, self.DIR_BOX_W, self.DIR_BOX_H), getattr(self, key))
            else:
                # Swatches stay flat so the selected color is shown accurately.
                swatch = pygame.Rect(x, y, self.COLOR_BOX_W, self.DIR_BOX_H)
                pygame.draw.rect(surface, getattr(self, key), swatch)
                pygame.draw.rect(surface, SETTINGS_PANEL_BORDER, swatch, 1)
        if self.sub_state == "AI" and self.ai_mode != "OFF":
            for _box_type, box_y, label in self.ai_field_rows():
                surface.blit(font.render(label, True, c.UI_TEXT_LIGHT), (SETTINGS_BOX_X, box_y - 30))
            for label, y in (("Provider", SETTINGS_AI_PROVIDER_Y), ("Immersion", SETTINGS_AI_IMMERSION_Y)):
                surface.blit(font.render(label, True, c.UI_TEXT_LIGHT), (SETTINGS_X, y - 30))

    def set_players(self, val):
        self.num_players = 1 + int(val * 7)
        self.controller.num_players = self.num_players
        if self.player_slider is not None:
            self.player_slider.text = f"Players: {self.num_players}"

    def save_and_go_back(self, execute_exit=True):
        queries.save_global_settings(self.controller)
        
        if execute_exit:
            self.exit_screen()

    def handle_back_key(self):
        sound_effects.play_ui_sound("back")
        self.save_and_go_back()

    def toggle_full(self):
        self.controller.toggle_fullscreen()
        self.fullscreen = getattr(self.controller, 'is_fullscreen', False)

    def set_volume(self, val):
        self.sfx_volume = val
        self.controller.sfx_volume = val
        sound_effects.set_sfx_volume(val)
