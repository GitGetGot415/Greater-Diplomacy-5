from gameState import GameState
from ui_elements import Button, Slider, parse_pos
import data.constants as c
from data import queries

# ==========================================
# LAYOUT
# ==========================================

BACK_BTN_POS = (20, 20)

# Everything in the centre column, top to bottom.
FOG_ROW_Y = 160
DAYS_PER_TURN_ROW_Y = 480
RESET_ROW_Y = 600

# The fog intensity slider rides alongside the fog toggle on the first row,
# which is why that toggle is the only one nudged left of centre.
FOG_TOGGLE_X = "centered-120"
FOG_SLIDER_X = "centered+120"
FOG_SLIDER_WIDTH = 180
FOG_SLIDER_Y = FOG_ROW_Y + 15

# Side buttons that open their own sub-screens.
SIDE_BTN_X = 80
SIDE_BTN_AI_Y = 360
SIDE_BTN_TURN_EDITOR_Y = 420

# ==========================================
# TOGGLES
# ==========================================

# (y, settings key, default constant, label). One entry per on/off scenario
# rule: adding a row here gives it a button, a working toggle and a reset entry.
TOGGLE_ROWS = [
    (FOG_ROW_Y, "fog_of_war", c.DEFAULT_FOG_OF_WAR, "Fog of War"),
    (240, "casus_belli_required", c.DEFAULT_CASUS_BELLI, "Casus Belli Required"),
    (300, "surprise_attack", c.DEFAULT_SURPRISE_ATTACK, "Surprise Attack"),
    (360, "disable_factions", c.DEFAULT_DISABLE_FACTIONS, "Disable Factions"),
    (420, "battle_royale", c.DEFAULT_BATTLE_ROYALE, "Battle Royale"),
    (540, "bounce_tiebreaker", c.DEFAULT_BOUNCE_TIEBREAKER, "Bounce Tiebreaker"),
]

# Slider stops for fog_of_war_strength, as (saved value, slider position).
FOG_STRENGTH_STEPS = [("lite", 0.0), ("normal", 1.0), ("extreme", 2.0)]


class Scenario_Settings(GameState):
    back_state = "NEW_GAME" # Track which screen to return to

    def __init__(self):
        super().__init__()
        self.bg_color = (80, 20, 60)
        # Load persistent settings instead of creating defaults
        self.settings = queries.get_scenario_settings()
        if not self.settings:
            self.settings = self.default_settings()
        self.refresh_ui()

    def default_settings(self):
        """Every scenario rule this screen owns, at its constants.py default."""
        defaults = {key: default for _y, key, default, _label in TOGGLE_ROWS}
        defaults["fog_of_war_strength"] = c.DEFAULT_FOG_OF_WAR_STRENGTH
        defaults["use_scripted_events"] = c.DEFAULT_USE_SCRIPTED_EVENTS
        defaults["days_per_turn"] = "Default"
        return defaults

    def refresh_ui(self):
        self.elements = [Button(*BACK_BTN_POS, "small", "red", "Back", self.exit_screen)]

        for y, key, default, label in TOGGLE_ROWS:
            is_on = queries.get_scenario_flag(key, default, self.settings)
            x = FOG_TOGGLE_X if key == "fog_of_war" else "centered"
            self.elements.append(
                Button(x, y, "medium", "green" if is_on else "red",
                       f"{label}: {'ON' if is_on else 'OFF'}",
                       lambda k=key, d=default: self.toggle(k, d))
            )

        self.elements.append(self.build_fog_slider())

        dpt_val = self.settings.get("days_per_turn", "Default")
        self.elements.extend([
            Button("centered", DAYS_PER_TURN_ROW_Y, "medium", "blue",
                   f"Days Per Turn: {dpt_val}", self.cycle_days_per_turn),
            Button("centered", RESET_ROW_Y, "medium", "grey", "Reset to Defaults", self.reset_defaults),
            Button(SIDE_BTN_X, SIDE_BTN_AI_Y, "medium", "blue", "AI Specific Settings", self.open_ai_settings),
            Button(SIDE_BTN_X, SIDE_BTN_TURN_EDITOR_Y, "medium", "purple", "Edit Construction Turns", self.open_turn_editor),
        ])

    def build_fog_slider(self):
        """The Lite/Normal/Extreme intensity slider that sits next to the fog toggle."""
        strength = self.settings.get("fog_of_war_strength", c.DEFAULT_FOG_OF_WAR_STRENGTH)
        value = dict(FOG_STRENGTH_STEPS).get(strength, 1.0)
        max_value = FOG_STRENGTH_STEPS[-1][1]

        def label_for(name):
            return f"Intensity: {name.title()}"

        def on_slide(val):
            # Snap to whichever stop the handle landed nearest
            name = min(FOG_STRENGTH_STEPS, key=lambda step: abs(step[1] - val))[0]
            self.settings["fog_of_war_strength"] = name
            self.fog_slider.text = label_for(name)
            queries.save_scenario_settings(self.settings)

        slider_x = parse_pos(FOG_SLIDER_X, c.SCREEN_WIDTH, FOG_SLIDER_WIDTH)
        self.fog_slider = Slider(slider_x, FOG_SLIDER_Y, FOG_SLIDER_WIDTH, label_for(strength),
                                 value, on_slide, visual_max=max_value, allowed_max=max_value)
        return self.fog_slider

    def toggle(self, key, default):
        queries.toggle_scenario_flag(self.settings, key, default)
        self.refresh_ui()

    def open_turn_editor(self):
        try:
            from ui.turn_editor import open_turn_editor
            open_turn_editor()
        except ImportError as e:
            print(f"Error importing turn editor: {e}")

    def open_ai_settings(self):
        self.go_to("AI_SETTINGS")

    def cycle_days_per_turn(self):
        options = c.DAYS_PER_TURN_OPTIONS
        current = self.settings.get("days_per_turn", "Default")
        next_idx = (options.index(current) + 1) % len(options) if current in options else 0
        self.settings["days_per_turn"] = options[next_idx]
        queries.save_scenario_settings(self.settings)
        self.refresh_ui()

    def reset_defaults(self):
        self.settings.update(self.default_settings())
        queries.save_scenario_settings(self.settings)
        self.refresh_ui()
