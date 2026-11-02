"""Editing what an AI nation is like -- see screens/editors/__init__.py.

Personality drives war appetite, peace terms, who a nation will ally with and
whether it keeps a promise, but until this screen there was no way to set it
short of hand-editing a scenario JSON: ai_personality_overrides had a reader,
two tests and no writer at all. Without an override the traits are procedural,
which means reproducible but historically arbitrary -- this seed gives the 1939
German Reich an aggression of 0.51 and the USSR 0.04.

Saving goes through ai_personality.set_authored, which stamps the traits
`_source: "editor"` so nothing regenerates them, and they persist for free
inside nation_data.
"""
import pygame
import data.constants as c
from ui.background_styles import EDITOR_PANEL_STYLES
from data import queries
from ui.navigation.screen import EditorSliderScreen, NationListOverlayScreen
from ui.widgets.ui_elements import Button, Slider
from ui.rendering.font_manager import fonts
from map_logic.ai import ai_personality

#: What each end of a trait means, so the screen explains itself.
TRAIT_POLES = {
    "aggression": ("peaceable", "belligerent"),
    "ambition": ("content", "expansionist"),
    "caution": ("reckless", "cautious"),
    "loyalty": ("faithless", "loyal"),
    "trust": ("suspicious", "trusting"),
}


class Personality_Edit_Screen(EditorSliderScreen):
    PANEL_STYLE = EDITOR_PANEL_STYLES["personality"]
    RESET_LABEL = "Reset to Procedural"

    SLIDER_TOP = 90
    ROW_STEP = 62

    def __init__(self, map_screen, country_id):
        super().__init__(map_screen, pygame.Rect(0, 0, 520, 520))
        self.country_id = country_id

        # Reading through ai_personality rather than nation_data means a nation
        # that has never been asked gets its procedural traits seeded here, so
        # the sliders open where the AI would actually have played it.
        traits = ai_personality.get(map_screen.nation_data, country_id,
                                    map_screen.scenario_settings)
        self.values = {t: float(traits.get(t, 0.5)) for t in ai_personality.TRAITS}
        self.refresh_ui()

    def _set(self, trait, value):
        self.values[trait] = value

    def slider_rows(self):
        p = self.panel_rect
        rows = []
        for row, name in enumerate(ai_personality.TRAITS):
            slider = Slider(p.x + self.SLIDER_X, p.y + self.SLIDER_TOP + row * self.ROW_STEP, self.SLIDER_W,
                            name.capitalize(), self.values[name], lambda v, n=name: self._set(n, v))
            rows.append((slider, *TRAIT_POLES.get(name, ("low", "high"))))
        return rows

    def reset(self):
        """Back to the seeded values, and back to being regenerated on load."""
        nation_data = self.map_screen.nation_data
        block = nation_data.setdefault(self.country_id, {})
        block.pop("personality", None)
        traits = ai_personality.get(nation_data, self.country_id,
                                    self.map_screen.scenario_settings)
        self.values = {t: float(traits.get(t, 0.5)) for t in ai_personality.TRAITS}
        self.map_screen.show_feedback(queries.get_country_display_name(
            self.country_id, self.map_screen.nation_data) + " reset to procedural traits")
        self.refresh_ui()

    def save(self):
        ai_personality.set_authored(self.map_screen.nation_data, self.country_id, self.values)
        self.map_screen.show_feedback("Saved personality for " + queries.get_country_display_name(
            self.country_id, self.map_screen.nation_data))
        self.done = True

    def get_panel_title(self):
        return queries.get_country_display_name(self.country_id, self.map_screen.nation_data) + " Personality"

    def draw_content(self, surface):
        super().draw_content(surface)
        p = self.panel_rect
        small = fonts.get("small")
        note = ai_personality.describe(self.map_screen.nation_data, self.country_id,
                                       self.map_screen.scenario_settings)
        summary = small.render(f"Currently saved as: {note}", True, c.UI_TEXT_DIM)
        surface.blit(summary, (p.x + 30, p.bottom - 90))


class Personality_List_Screen(NationListOverlayScreen):
    PANEL_BG, PANEL_BORDER, PANEL_BORDER_WIDTH = c.PANEL_THEME_SPECIAL
    PANEL_STYLE = EDITOR_PANEL_STYLES["personality_list"]
    PANEL_TITLE = "AI Personalities"
    LIST_NOTE = "Unmarked nations use procedural traits, seeded from the scenario."
    EDIT_SCREEN = Personality_Edit_Screen

    def country_button(self, country_id, x, y):
        stored = self.map_screen.nation_data.get(country_id, {}).get("personality") or {}
        authored = stored.get("_source") in ai_personality.AUTHORED_SOURCES
        country_name = queries.get_country_display_name(country_id, self.map_screen.nation_data)
        label = f"[AUTHORED] {country_name}" if authored else country_name
        return Button(x, y, "list_row", "green" if authored else "blue", label,
                      lambda cid=country_id: self.edit(cid))
