import pygame
from gameState import GameState
from ui_elements import Button, Slider, parse_pos
import data.constants as c
from data import queries
from ui import confirm_dialog

# ==========================================
# LAYOUT
# ==========================================
# Everything lives on one screen now: the general scenario rules on the left,
# the AI-specific rules boxed off on the right so they still read as their own
# section, and the two screen-opening actions (reset / turn editor) footered
# below both columns. Only "Edit Construction Turns" still opens a sub-screen.

BACK_BTN_POS = (20, 20)

ROW_H = 46
INFO_GAP = 10  # gap between an info button's right edge and its setting button's left edge
# Half the leftover height between a "scenario_setting_button" (36px) and the
# smaller "scenario_setting_info" square (32px), so the two line up on center.
INFO_Y_NUDGE = (c.SIZES["scenario_setting_button"][1] - c.SIZES["scenario_setting_info"][1]) // 2

# --- Left column: general scenario rules ---
LEFT_TOP_Y = 110
LEFT_BTN_X = 330
LEFT_INFO_X = LEFT_BTN_X - c.SIZES["scenario_setting_info"][0] - INFO_GAP

# The fog intensity slider rides alongside the fog toggle on its row.
FOG_SLIDER_X = 545
FOG_SLIDER_WIDTH = 170
FOG_SLIDER_Y_OFFSET = 8

# --- Right column: AI settings, boxed off to keep it visually distinct ---
AI_PANEL_TOP = 85
AI_PANEL_BOTTOM = 310
AI_HEADER_Y = 95
AI_TOP_Y = 140
AI_BTN_X = 800
AI_INFO_X = AI_BTN_X - c.SIZES["scenario_setting_info"][0] - INFO_GAP
AI_PANEL_RECT = pygame.Rect(AI_INFO_X - 20, AI_PANEL_TOP,
                            (AI_BTN_X + c.SIZES["scenario_setting_button"][0] + 20) - (AI_INFO_X - 20),
                            AI_PANEL_BOTTOM - AI_PANEL_TOP)

SLIDER_WIDTH = 180
AI_SLIDER_Y_OFFSET = 8

# --- Footer actions, centred under both columns ---
DAYS_PER_TURN_ROW_Y = LEFT_TOP_Y + 6 * ROW_H
RESET_ROW_Y = 470
TURN_EDITOR_ROW_Y = 530

# ==========================================
# TOGGLES
# ==========================================

# (settings key, default constant, label, tooltip). One entry per on/off
# scenario rule: adding a row here gives it a button, a toggle, an info
# button and a reset entry, in that order down the left column.
TOGGLE_ROWS = [
    ("fog_of_war", c.DEFAULT_FOG_OF_WAR, "Fog of War",
     "Hides territory and units you can't currently see. Use the slider "
     "beside it to set how strong the effect is: Lite, Normal, or Extreme."),
    ("casus_belli_required", c.DEFAULT_CASUS_BELLI, "Casus Belli Required",
     "Requires a valid justification (casus belli) before a country can declare war on another."),
    ("surprise_attack", c.DEFAULT_SURPRISE_ATTACK, "Surprise Attack",
     "Lets armies attack on the same turn as a war declaration instead of making them wait until the other size receives it, catching the enemy by surprise."),
    ("disable_factions", c.DEFAULT_DISABLE_FACTIONS, "Disable Factions",
     "Disables the internal political faction system for every country."),
    ("battle_royale", c.DEFAULT_BATTLE_ROYALE, "Battle Royale",
     "Starts every country at war with every other country from turn one."),
    ("bounce_tiebreaker", c.DEFAULT_BOUNCE_TIEBREAKER, "Bounce Tiebreaker",
     "When equally-matched attackers contest a province, this makes the move bounce "
     "instead of letting chance decide who takes it."),
]

DAYS_PER_TURN_TOOLTIP = "Sets how many in-game days pass with each turn you take."

# Slider stops for fog_of_war_strength, as (saved value, slider position).
FOG_STRENGTH_STEPS = [("lite", 0.0), ("normal", 1.0), ("extreme", 2.0)]

# Highest number of turns the "wait before war" AI slider can reach.
MAX_TURNS_BEFORE_WAR = 100.0

AI_TOGGLE_TOOLTIP = ("Turns AI-controlled countries on or off. With AI off, "
                     "other countries take no actions on their turns.")
AI_TURNS_TOOLTIP = ("Minimum number of turns from the start of the game the AI "
                    "will wait before it's allowed to declare war.")
AI_CHANCE_TOOLTIP = "Chance each turn that an AI meeting the conditions for war actually declares it."


class Scenario_Settings(GameState):
    back_state = "NEW_GAME" # Track which screen to return to
    title = "Scenario Settings"
    title_y = 30

    def __init__(self):
        super().__init__()
        self.bg_color = (80, 20, 60)
        # Load persistent settings instead of creating defaults
        self.settings = queries.get_scenario_settings()
        if not self.settings:
            self.settings = self.default_settings()
        self.refresh_ui()

    def default_settings(self):
        """Every scenario and AI rule this screen owns, at its constants.py default."""
        defaults = {key: default for key, default, _label, _tip in TOGGLE_ROWS}
        defaults["fog_of_war_strength"] = c.DEFAULT_FOG_OF_WAR_STRENGTH
        defaults["use_scripted_events"] = c.DEFAULT_USE_SCRIPTED_EVENTS
        defaults["days_per_turn"] = "Default"
        defaults["ai_disabled"] = c.DEFAULT_AI_DISABLED
        defaults["turns_to_wait_before_war"] = c.TURNS_TO_WAIT_BEFORE_WAR
        defaults["ai_war_declaration_chance"] = c.AI_WAR_DECLARATION_CHANCE
        return defaults

    def info_button(self, x, y, tooltip_title, tooltip_text):
        return Button(x, y + INFO_Y_NUDGE, "scenario_setting_info", "light_blue", "?",
                     lambda: confirm_dialog.show_info(tooltip_title, tooltip_text))

    def refresh_ui(self):
        self.elements = [Button(*BACK_BTN_POS, "small", "red", "Back", self.exit_screen)]

        for i, (key, default, label, tooltip) in enumerate(TOGGLE_ROWS):
            y = LEFT_TOP_Y + i * ROW_H
            is_on = queries.get_scenario_flag(key, default, self.settings)
            self.elements.append(self.info_button(LEFT_INFO_X, y, label, tooltip))
            self.elements.append(
                Button(LEFT_BTN_X, y, "scenario_setting_button", "green" if is_on else "red",
                       f"{label}: {'ON' if is_on else 'OFF'}",
                       lambda k=key, d=default: self.toggle(k, d), font_preset="button_small")
            )

        self.elements.append(self.build_fog_slider())

        dpt_val = self.settings.get("days_per_turn", "Default")
        self.elements.append(self.info_button(LEFT_INFO_X, DAYS_PER_TURN_ROW_Y, "Days Per Turn", DAYS_PER_TURN_TOOLTIP))
        self.elements.append(
            Button(LEFT_BTN_X, DAYS_PER_TURN_ROW_Y, "scenario_setting_button", "blue",
                   f"Days Per Turn: {dpt_val}", self.cycle_days_per_turn, font_preset="button_small")
        )

        self.elements.extend(self.build_ai_section())

        turn_editor_btn = Button("centered", TURN_EDITOR_ROW_Y, "scenario_setting_button", "purple",
                                 "Edit Construction Turns", self.open_turn_editor, font_preset="button_small")
        if queries.scenario_has_construction_customizations(self.settings):
            turn_editor_btn.notification_text = "!"

        self.elements.extend([
            Button("centered", RESET_ROW_Y, "scenario_setting_button", "grey", "Reset to Defaults",
                   self.reset_defaults, font_preset="button_small"),
            turn_editor_btn,
        ])

    def build_fog_slider(self):
        """The Lite/Normal/Extreme intensity slider that sits next to the fog toggle."""
        strength = self.settings.get("fog_of_war_strength", c.DEFAULT_FOG_OF_WAR_STRENGTH)
        value = dict(FOG_STRENGTH_STEPS).get(strength, 1.0)
        max_value = FOG_STRENGTH_STEPS[-1][1]

        def label_for(name):
            return f"Fog Intensity: {name.title()}"

        def on_slide(val):
            # Snap to whichever stop the handle landed nearest
            name = min(FOG_STRENGTH_STEPS, key=lambda step: abs(step[1] - val))[0]
            self.settings["fog_of_war_strength"] = name
            self.fog_slider.text = label_for(name)
            queries.save_scenario_settings(self.settings)

        fog_y = LEFT_TOP_Y # fog is always the first toggle row
        self.fog_slider = Slider(FOG_SLIDER_X, fog_y + FOG_SLIDER_Y_OFFSET, FOG_SLIDER_WIDTH,
                                 label_for(strength), value, on_slide,
                                 visual_max=max_value, allowed_max=max_value)
        return self.fog_slider

    def build_ai_section(self):
        ai_disabled = queries.get_scenario_flag("ai_disabled", c.DEFAULT_AI_DISABLED, self.settings)

        elements = [
            self.info_button(AI_INFO_X, AI_TOP_Y, "AI", AI_TOGGLE_TOOLTIP),
            Button(AI_BTN_X, AI_TOP_Y, "scenario_setting_button", "red" if ai_disabled else "green",
                   "AI: OFF" if ai_disabled else "AI: ON", self.toggle_ai_disabled, font_preset="button_small"),
            self.info_button(AI_INFO_X, AI_TOP_Y + ROW_H, "Turns Before War", AI_TURNS_TOOLTIP),
            self.build_ai_slider("turns_slider", AI_TOP_Y + ROW_H, "turns_to_wait_before_war",
                                 c.TURNS_TO_WAIT_BEFORE_WAR, MAX_TURNS_BEFORE_WAR,
                                 lambda v: f"Turns Before War: {int(v)}", int),
            self.info_button(AI_INFO_X, AI_TOP_Y + 2 * ROW_H, "War Chance", AI_CHANCE_TOOLTIP),
            self.build_ai_slider("chance_slider", AI_TOP_Y + 2 * ROW_H, "ai_war_declaration_chance",
                                 c.AI_WAR_DECLARATION_CHANCE, 1.0,
                                 lambda v: f"War Chance: {v:.2f}", float),
        ]
        return elements

    def build_ai_slider(self, attr, y, key, default, max_value, label_for, cast):
        value = float(self.settings.get(key, default))

        def on_slide(val):
            self.settings[key] = cast(val)
            getattr(self, attr).text = label_for(val)
            queries.save_scenario_settings(self.settings)

        slider = Slider(AI_BTN_X, y + AI_SLIDER_Y_OFFSET, SLIDER_WIDTH,
                        label_for(value), value, on_slide,
                        visual_max=max_value, allowed_max=max_value)
        setattr(self, attr, slider)
        return slider

    def toggle(self, key, default):
        queries.toggle_scenario_flag(self.settings, key, default)
        self.refresh_ui()

    def toggle_ai_disabled(self):
        queries.toggle_scenario_flag(self.settings, "ai_disabled", c.DEFAULT_AI_DISABLED)
        self.refresh_ui()

    def open_turn_editor(self):
        try:
            from ui.turn_editor import open_turn_editor
            # Re-reads settings once the editor closes so the "!" badge reflects
            # whatever was actually saved (or cleared, on cancel/back).
            open_turn_editor(on_done=lambda screen: self.refresh_ui())
        except ImportError as e:
            print(f"Error importing turn editor: {e}")

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

    def additional_draw(self, surface):
        from map_logic.rendering.font_manager import fonts

        left_center_x = LEFT_INFO_X + (LEFT_BTN_X + c.SIZES["scenario_setting_button"][0] - LEFT_INFO_X) // 2
        header_font = fonts.get("heading2")
        left_header = header_font.render("Scenario Rules", True, (230, 230, 230))
        surface.blit(left_header, left_header.get_rect(midtop=(left_center_x, 70)))

        # Boxed panel keeps the AI settings reading as their own distinct section.
        panel = pygame.Surface(AI_PANEL_RECT.size, pygame.SRCALPHA)
        panel.fill((255, 255, 255, 18))
        surface.blit(panel, AI_PANEL_RECT.topleft)
        pygame.draw.rect(surface, (150, 150, 220), AI_PANEL_RECT, 2, border_radius=6)

        ai_header = header_font.render("AI Settings", True, (230, 230, 255))
        surface.blit(ai_header, ai_header.get_rect(midtop=(AI_PANEL_RECT.centerx, AI_HEADER_Y)))
