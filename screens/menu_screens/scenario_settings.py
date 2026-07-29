import os
from gameState import GameState
from ui_elements import Button, Slider
import data.constants as c
from data import queries

class Scenario_Settings(GameState):
    back_state = "NEW_GAME" # Track which screen to return to

    def __init__(self):
        super().__init__()
        self.bg_color = (80, 20, 60)
        # Load persistent settings instead of creating defaults
        self.settings = queries.get_scenario_settings()
        if not self.settings:
            self.settings = {
                "fog_of_war": c.DEFAULT_FOG_OF_WAR,
                "fog_of_war_strength": c.DEFAULT_FOG_OF_WAR_STRENGTH,
                "casus_belli_required": c.DEFAULT_CASUS_BELLI,
                "surprise_attack": c.DEFAULT_SURPRISE_ATTACK,
                "use_scripted_events": c.DEFAULT_USE_SCRIPTED_EVENTS,
                "ai_disabled": c.DEFAULT_AI_DISABLED,
                "battle_royale": c.DEFAULT_BATTLE_ROYALE,
                "bounce_tiebreaker": c.DEFAULT_BOUNCE_TIEBREAKER
            }
        self.refresh_ui()

    def refresh_ui(self):
        self.elements = [
            Button(20, 20, "small", "red", "Back", self.exit_screen),
        ]
        
        # Toggle Button - Fog of War
        fog_val = str(self.settings.get("fog_of_war", c.DEFAULT_FOG_OF_WAR)).lower() == "true"
        fog_color = "green" if fog_val else "red"
        fog_text = "Fog of War: ON" if fog_val else "Fog of War: OFF"
        
        self.elements.append(
            Button("centered-120", 160, "medium", fog_color, fog_text, self.toggle_fog)
        )

        fog_strength = self.settings.get("fog_of_war_strength", "normal")
        if fog_strength == "lite":
            s_val = 0.0
            s_text = "Intensity: Lite"
        elif fog_strength == "extreme":
            s_val = 2.0
            s_text = "Intensity: Extreme"
        else:
            s_val = 1.0
            s_text = "Intensity: Normal"

        def fog_slider_cb(val):
            if val < 0.66:
                self.settings["fog_of_war_strength"] = "lite"
                self.fog_slider.text = "Intensity: Lite"
            elif val > 1.33:
                self.settings["fog_of_war_strength"] = "extreme"
                self.fog_slider.text = "Intensity: Extreme"
            else:
                self.settings["fog_of_war_strength"] = "normal"
                self.fog_slider.text = "Intensity: Normal"
            queries.save_scenario_settings(self.settings)

        from ui_elements import parse_pos
        slider_x = parse_pos("centered+120", c.SCREEN_WIDTH, 180)
        self.fog_slider = Slider(slider_x, 175, 180, s_text, s_val, fog_slider_cb, visual_max=2.0, allowed_max=2.0)
        self.elements.append(self.fog_slider)

        # Toggle Button - Casus Belli Required
        cb_val = str(self.settings.get("casus_belli_required", c.DEFAULT_CASUS_BELLI)).lower() == "true"
        cb_color = "green" if cb_val else "red"
        cb_text = "Casus Belli Required: ON" if cb_val else "Casus Belli Required: OFF"

        self.elements.append(
            Button("centered", 240, "medium", cb_color, cb_text, self.toggle_casus_belli)
        )

        # Toggle Button - Surprise Attack
        ib_val = str(self.settings.get("surprise_attack", c.DEFAULT_SURPRISE_ATTACK)).lower() == "true"
        ib_color = "green" if ib_val else "red"
        ib_text = "Surprise Attack: ON" if ib_val else "Surprise Attack: OFF"

        self.elements.append(
            Button("centered", 300, "medium", ib_color, ib_text, self.toggle_surprise_attack)
        )

        # Button to open AI Settings
        self.elements.append(
            Button(80, 360, "medium", "blue", "AI Specific Settings", self.open_ai_settings)
        )

        # Toggle Button - Disable Factions
        df_val = str(self.settings.get("disable_factions", c.DEFAULT_DISABLE_FACTIONS)).lower() == "true"
        df_color = "green" if df_val else "red"
        df_text = "Disable Factions: ON" if df_val else "Disable Factions: OFF"

        self.elements.append(
            Button("centered", 360, "medium", df_color, df_text, self.toggle_disable_factions)
        )

        # Toggle Button - Battle Royale
        br_val = str(self.settings.get("battle_royale", c.DEFAULT_BATTLE_ROYALE)).lower() == "true"
        br_color = "green" if br_val else "red"
        br_text = "Battle Royale: ON" if br_val else "Battle Royale: OFF"

        self.elements.append(
            Button("centered", 420, "medium", br_color, br_text, self.toggle_battle_royale)
        )

        dpt_val = self.settings.get("days_per_turn", "Default")
        self.elements.append(
            Button("centered", 480, "medium", "blue", f"Days Per Turn: {dpt_val}", self.cycle_days_per_turn)
        )

        # Toggle Button - Bounce Tiebreaker
        bt_val = str(self.settings.get("bounce_tiebreaker", c.DEFAULT_BOUNCE_TIEBREAKER)).lower() == "true"
        bt_color = "green" if bt_val else "red"
        bt_text = "Bounce Tiebreaker: ON" if bt_val else "Bounce Tiebreaker: OFF"

        self.elements.append(
            Button("centered", 540, "medium", bt_color, bt_text, self.toggle_bounce_tiebreaker)
        )

        # Reset Defaults Button
        self.elements.append(
            Button("centered", 600, "medium", "grey", "Reset to Defaults", self.reset_defaults)
        )

        # Edit Construction Turns
        self.elements.append(
            Button(80, 420, "medium", "purple", "Edit Construction Turns", self.open_turn_editor)
        )

    def open_turn_editor(self):
        try:
            from ui.turn_editor import open_turn_editor
            open_turn_editor()
        except ImportError as e:
            print(f"Error importing turn editor: {e}")

    def toggle_bounce_tiebreaker(self):
        current = str(self.settings.get("bounce_tiebreaker", c.DEFAULT_BOUNCE_TIEBREAKER)).lower() == "true"
        self.settings["bounce_tiebreaker"] = not current
        queries.save_scenario_settings(self.settings)
        self.refresh_ui()

    def toggle_fog(self):
        current = str(self.settings.get("fog_of_war", c.DEFAULT_FOG_OF_WAR)).lower() == "true"
        self.settings["fog_of_war"] = not current
        queries.save_scenario_settings(self.settings)
        self.refresh_ui()

    def toggle_casus_belli(self):
        current = str(self.settings.get("casus_belli_required", c.DEFAULT_CASUS_BELLI)).lower() == "true"
        self.settings["casus_belli_required"] = not current
        queries.save_scenario_settings(self.settings)
        self.refresh_ui()

    def toggle_surprise_attack(self):
        current = str(self.settings.get("surprise_attack", c.DEFAULT_SURPRISE_ATTACK)).lower() == "true"
        self.settings["surprise_attack"] = not current
        queries.save_scenario_settings(self.settings)
        self.refresh_ui()

    def open_ai_settings(self):
        self.go_to("AI_SETTINGS")

    def toggle_battle_royale(self):
        current = str(self.settings.get("battle_royale", c.DEFAULT_BATTLE_ROYALE)).lower() == "true"
        self.settings["battle_royale"] = not current
        queries.save_scenario_settings(self.settings)
        self.refresh_ui()

    def cycle_days_per_turn(self):
        options = c.DAYS_PER_TURN_OPTIONS
        current = self.settings.get("days_per_turn", "Default")
        if current in options:
            idx = options.index(current)
            next_idx = (idx + 1) % len(options)
        else:
            next_idx = 0
        self.settings["days_per_turn"] = options[next_idx]
        queries.save_scenario_settings(self.settings)
        self.refresh_ui()

    def toggle_disable_factions(self):
        current = str(self.settings.get("disable_factions", c.DEFAULT_DISABLE_FACTIONS)).lower() == "true"
        self.settings["disable_factions"] = not current
        queries.save_scenario_settings(self.settings)
        self.refresh_ui()

    def reset_defaults(self):
        self.settings["fog_of_war"] = c.DEFAULT_FOG_OF_WAR
        self.settings["fog_of_war_strength"] = c.DEFAULT_FOG_OF_WAR_STRENGTH
        self.settings["casus_belli_required"] = c.DEFAULT_CASUS_BELLI
        self.settings["surprise_attack"] = c.DEFAULT_SURPRISE_ATTACK
        self.settings["days_per_turn"] = "Default"
        self.settings["use_scripted_events"] = c.DEFAULT_USE_SCRIPTED_EVENTS
        self.settings["battle_royale"] = c.DEFAULT_BATTLE_ROYALE
        self.settings["bounce_tiebreaker"] = c.DEFAULT_BOUNCE_TIEBREAKER
        self.settings["disable_factions"] = c.DEFAULT_DISABLE_FACTIONS
        queries.save_scenario_settings(self.settings)
        self.refresh_ui()

