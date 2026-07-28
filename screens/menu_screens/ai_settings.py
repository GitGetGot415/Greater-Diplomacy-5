import os
from gameState import GameState
from ui_elements import Button, Slider
import data.constants as c
from data import queries

class AI_Settings(GameState):
    back_state = "SCENARIO_SETTINGS"

    def __init__(self):
        super().__init__()
        self.bg_color = (80, 20, 60)
        self.settings = queries.get_scenario_settings()
        if not self.settings:
            self.settings = {
                "ai_disabled": c.DEFAULT_AI_DISABLED,
                "turns_to_wait_before_war": c.TURNS_TO_WAIT_BEFORE_WAR,
                "ai_war_declaration_chance": c.AI_WAR_DECLARATION_CHANCE
            }
        self.refresh_ui()

    def refresh_ui(self):
        self.elements = [
            Button(20, 20, "small", "red", "Back", self.exit_screen),
        ]

        # Toggle Button - AI Off
        ai_disabled_val = str(self.settings.get("ai_disabled", c.DEFAULT_AI_DISABLED)).lower() == "true"
        ai_disabled_color = "red" if ai_disabled_val else "green" 
        ai_disabled_text = "AI: OFF" if ai_disabled_val else "AI: ON"

        self.elements.append(
            Button("centered", 160, "medium", ai_disabled_color, ai_disabled_text, self.toggle_ai_disabled)
        )
        
        from ui_elements import parse_pos
        
        # Turns to wait before war slider
        turns_val = float(self.settings.get("turns_to_wait_before_war", c.TURNS_TO_WAIT_BEFORE_WAR))
        turns_text = f"Turns Before War: {int(turns_val)}"
        def turns_slider_cb(val):
            self.settings["turns_to_wait_before_war"] = int(val)
            self.turns_slider.text = f"Turns Before War: {int(val)}"
            queries.save_scenario_settings(self.settings)
            
        slider_x = parse_pos("centered", c.SCREEN_WIDTH, 180)
        self.turns_slider = Slider(slider_x, 240, 180, turns_text, turns_val, turns_slider_cb, visual_max=100.0, allowed_max=100.0)
        self.elements.append(self.turns_slider)

        # AI War Declaration Chance slider
        chance_val = float(self.settings.get("ai_war_declaration_chance", c.AI_WAR_DECLARATION_CHANCE))
        chance_text = f"War Chance: {chance_val:.2f}"
        def chance_slider_cb(val):
            self.settings["ai_war_declaration_chance"] = val
            self.chance_slider.text = f"War Chance: {val:.2f}"
            queries.save_scenario_settings(self.settings)

        self.chance_slider = Slider(slider_x, 320, 180, chance_text, chance_val, chance_slider_cb, visual_max=1.0, allowed_max=1.0)
        self.elements.append(self.chance_slider)

        # Reset Defaults Button
        self.elements.append(
            Button("centered", 480, "medium", "grey", "Reset to Defaults", self.reset_defaults)
        )

    def toggle_ai_disabled(self):
        current = str(self.settings.get("ai_disabled", c.DEFAULT_AI_DISABLED)).lower() == "true"
        self.settings["ai_disabled"] = not current
        queries.save_scenario_settings(self.settings)
        self.refresh_ui()

    def reset_defaults(self):
        self.settings["ai_disabled"] = c.DEFAULT_AI_DISABLED
        self.settings["turns_to_wait_before_war"] = c.TURNS_TO_WAIT_BEFORE_WAR
        self.settings["ai_war_declaration_chance"] = c.AI_WAR_DECLARATION_CHANCE
        queries.save_scenario_settings(self.settings)
        self.refresh_ui()


