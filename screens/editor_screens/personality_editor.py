"""Editing what an AI nation is like -- see screens/editor_screens/__init__.py.

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
from data import queries
from gameState import MapOverlayScreen
from ui_elements import Button, Slider, make_back_button
from ui.screen_runner import _run_pygame_sub_screen
from map_logic.rendering.font_manager import fonts
from map_logic.ai import ai_personality

#: What each end of a trait means, so the screen explains itself.
TRAIT_POLES = {
    "aggression": ("peaceable", "belligerent"),
    "ambition": ("content", "expansionist"),
    "caution": ("reckless", "cautious"),
    "loyalty": ("faithless", "loyal"),
    "trust": ("suspicious", "trusting"),
}


class Personality_Edit_Screen(MapOverlayScreen):
    pans_camera = False
    PANEL_BG, PANEL_BORDER, PANEL_BORDER_WIDTH = c.PANEL_THEME_SPECIAL
    TITLE_PRESET = "heading2"
    TITLE_Y_OFFSET = c.MODAL_TITLE_Y_OFFSET

    SLIDER_W = 300
    ROW_STEP = 62

    def __init__(self, map_screen, country_id):
        super().__init__(map_screen, pygame.Rect(0, 0, 520, 520))
        self.back_state = "MAP"
        self.country_id = country_id

        # Reading through ai_personality rather than nation_data means a nation
        # that has never been asked gets its procedural traits seeded here, so
        # the sliders open where the AI would actually have played it.
        traits = ai_personality.get(map_screen.nation_data, country_id,
                                    getattr(map_screen, "scenario_settings", None))
        self.values = {t: float(traits.get(t, 0.5)) for t in ai_personality.TRAITS}
        self.sliders = {}
        self.refresh_ui()

    def _set(self, trait, value):
        self.values[trait] = value

    def refresh_ui(self):
        p = self.panel_rect
        x = p.x + 150
        y = p.y + 90

        self.sliders = {}
        for name in ai_personality.TRAITS:
            slider = Slider(x, y, self.SLIDER_W, name.capitalize(), self.values[name],
                            lambda v, n=name: self._set(n, v))
            self.sliders[name] = slider
            y += self.ROW_STEP

        self.elements = [
            make_back_button(self.exit_screen, style="map"),
            Button(p.x + 30, p.bottom - 55, "medium", "grey", "Reset to Procedural", self.reset),
            Button(p.right - 190, p.bottom - 55, "medium", "green", "Save", self.save),
        ] + list(self.sliders.values())

    def reset(self):
        """Back to the seeded values, and back to being regenerated on load."""
        nation_data = self.map_screen.nation_data
        block = nation_data.setdefault(self.country_id, {})
        block.pop("personality", None)
        traits = ai_personality.get(nation_data, self.country_id,
                                    getattr(self.map_screen, "scenario_settings", None))
        self.values = {t: float(traits.get(t, 0.5)) for t in ai_personality.TRAITS}
        self.map_screen.show_feedback(f"{self.country_id} reset to procedural traits")
        self.refresh_ui()

    def save(self):
        ai_personality.set_authored(self.map_screen.nation_data, self.country_id, self.values)
        self.map_screen.show_feedback(f"Saved personality for {self.country_id}")
        self.done = True

    def get_panel_title(self):
        return f"{self.country_id} Personality"

    def draw_content(self, surface):
        p = self.panel_rect
        self.draw_panel(surface)

        small = fonts.get("small")
        for name, slider in self.sliders.items():
            low, high = TRAIT_POLES.get(name, ("low", "high"))
            surface.blit(small.render(low, True, c.UI_TEXT_MUTED),
                         (p.x + 30, slider.rect.y - 2))
            hi_surf = small.render(high, True, c.UI_TEXT_MUTED)
            surface.blit(hi_surf, (slider.rect.right + 14, slider.rect.y - 2))

        note = ai_personality.describe(self.map_screen.nation_data, self.country_id,
                                       getattr(self.map_screen, "scenario_settings", None))
        summary = small.render(f"Currently saved as: {note}", True, c.UI_TEXT_DIM)
        surface.blit(summary, (p.x + 30, p.bottom - 90))


class Personality_List_Screen(MapOverlayScreen):
    pans_camera = False
    scroll_anywhere = True
    PANEL_BG, PANEL_BORDER, PANEL_BORDER_WIDTH = c.PANEL_THEME_SPECIAL
    PANEL_TITLE = "AI Personalities"
    TITLE_PRESET = "heading2"
    TITLE_Y_OFFSET = c.MODAL_TITLE_Y_OFFSET

    def __init__(self, map_screen):
        super().__init__(map_screen, pygame.Rect(0, 0, 620, 560))
        self.back_state = "MAP"
        self.active_countries = sorted(queries.get_living_nations(map_screen.map_data))
        self.refresh_ui()

    def refresh_ui(self):
        p = self.panel_rect
        self.elements = [make_back_button(self.exit_screen, style="map")]

        row_top = p.y + 90
        view_h = p.height - 110
        row_x = p.centerx - (c.SIZES["list_row"][0] // 2)
        cull_top, cull_bottom = p.y + 80, p.bottom - 20
        self.scroll_content_rect = pygame.Rect(p.x, cull_top, p.width, cull_bottom - cull_top)

        for i, y in self.layout_list_rows(len(self.active_countries), 40, row_top, view_h=view_h,
                                          cull_top=cull_top, cull_bottom=cull_bottom):
            cid = self.active_countries[i]
            stored = self.map_screen.nation_data.get(cid, {}).get("personality") or {}
            authored = stored.get("_source") in ai_personality.AUTHORED_SOURCES
            label = f"[AUTHORED] {cid}" if authored else cid
            btn = Button(row_x, y, "list_row", "green" if authored else "blue", label,
                         lambda cc=cid: self.edit(cc))
            btn.is_scrollable = True
            btn.click_guard = self.scroll_click_guard
            self.elements.append(btn)

        self.list_view_h = view_h

    def edit(self, cid):
        _run_pygame_sub_screen(self.map_screen, Personality_Edit_Screen(self.map_screen, cid),
                               on_done=self.refresh_ui)

    def draw_content(self, surface):
        p = self.panel_rect
        self.draw_panel(surface)
        note = fonts.get("small").render(
            "Unmarked nations use procedural traits, seeded from the scenario.",
            True, c.UI_TEXT_MUTED)
        surface.blit(note, (p.x + 24, p.y + 58))
