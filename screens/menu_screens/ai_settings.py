from gameState import GameState
from ui_elements import Button, Slider, parse_pos
import data.constants as c
from data import queries

# ==========================================
# LAYOUT
# ==========================================

BACK_BTN_POS = (20, 20)

AI_TOGGLE_Y = 160
RESET_BTN_Y = 480

SLIDER_X = "centered"
SLIDER_WIDTH = 180
TURNS_SLIDER_Y = 240
CHANCE_SLIDER_Y = 320

# Highest number of turns the "wait before war" slider can reach.
MAX_TURNS_BEFORE_WAR = 100.0


class AI_Settings(GameState):
    back_state = "SCENARIO_SETTINGS"

    def __init__(self):
        super().__init__()
        self.bg_color = (80, 20, 60)
        self.settings = queries.get_scenario_settings()
        if not self.settings:
            self.settings = self.default_settings()
        self.refresh_ui()

    def default_settings(self):
        """Every AI rule this screen owns, at its constants.py default."""
        return {
            "ai_disabled": c.DEFAULT_AI_DISABLED,
            "turns_to_wait_before_war": c.TURNS_TO_WAIT_BEFORE_WAR,
            "ai_war_declaration_chance": c.AI_WAR_DECLARATION_CHANCE,
        }

    def refresh_ui(self):
        # The label is inverted on purpose: the setting stores "disabled", the button shows "AI: ON/OFF".
        ai_disabled = queries.get_scenario_flag("ai_disabled", c.DEFAULT_AI_DISABLED, self.settings)

        self.elements = [
            Button(*BACK_BTN_POS, "small", "red", "Back", self.exit_screen),
            Button("centered", AI_TOGGLE_Y, "medium", "red" if ai_disabled else "green",
                   "AI: OFF" if ai_disabled else "AI: ON", self.toggle_ai_disabled),
            self.build_slider("turns_slider", TURNS_SLIDER_Y, "turns_to_wait_before_war",
                              c.TURNS_TO_WAIT_BEFORE_WAR, MAX_TURNS_BEFORE_WAR,
                              lambda v: f"Turns Before War: {int(v)}", int),
            self.build_slider("chance_slider", CHANCE_SLIDER_Y, "ai_war_declaration_chance",
                              c.AI_WAR_DECLARATION_CHANCE, 1.0,
                              lambda v: f"War Chance: {v:.2f}", float),
            Button("centered", RESET_BTN_Y, "medium", "grey", "Reset to Defaults", self.reset_defaults),
        ]

    def build_slider(self, attr, y, key, default, max_value, label_for, cast):
        """One settings slider that writes straight back to the scenario file.

        `cast` is what the value is stored as, which is the only thing that
        actually differs between the turn-count and the probability sliders.
        """
        value = float(self.settings.get(key, default))

        def on_slide(val):
            self.settings[key] = cast(val)
            getattr(self, attr).text = label_for(val)
            queries.save_scenario_settings(self.settings)

        slider = Slider(parse_pos(SLIDER_X, c.SCREEN_WIDTH, SLIDER_WIDTH), y, SLIDER_WIDTH,
                        label_for(value), value, on_slide,
                        visual_max=max_value, allowed_max=max_value)
        setattr(self, attr, slider)
        return slider

    def toggle_ai_disabled(self):
        queries.toggle_scenario_flag(self.settings, "ai_disabled", c.DEFAULT_AI_DISABLED)
        self.refresh_ui()

    def reset_defaults(self):
        self.settings.update(self.default_settings())
        queries.save_scenario_settings(self.settings)
        self.refresh_ui()
