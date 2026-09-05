"""Authoring where a nation *starts* on the political axis.

Everyone begins centrist, which is right for a blank map and wrong for a dated
scenario: a 1939 setup where the Reich and the Western democracies open at the
same point on a libertarian/authoritarian axis is saying something it does not
mean. This is the one place that can be changed before the first turn.

Unlike the player's Politics screen this one *is* a drag -- the editor is
setting a position outright rather than choosing a direction to walk in, and the
Slider is the right widget for that. Saving also clears any stored direction, so
an authored country opens the game standing still where it was placed.

See screens/editor_screens/__init__.py: every screen class here is re-exported
at package level, because ui/editor_menus.py looks them up by name.
"""
import pygame
import data.constants as c
from data import queries
from gameState import MapOverlayScreen, NationListOverlayScreen
from ui_elements import Button, Slider, make_back_button
from ui.screen_runner import _run_pygame_sub_screen
from map_logic.rendering.font_manager import fonts
from map_logic import politics


def _to_slider(political_value):
    """Axis value -> the Slider's 0.0-1.0."""
    span = float(c.POLITICS_MAX - c.POLITICS_MIN)
    return (political_value - c.POLITICS_MIN) / span


def _from_slider(fraction):
    """The Slider's 0.0-1.0 -> axis value."""
    span = float(c.POLITICS_MAX - c.POLITICS_MIN)
    return politics.clamp(c.POLITICS_MIN + fraction * span)


class Politics_Edit_Screen(MapOverlayScreen):
    pans_camera = False
    PANEL_BG, PANEL_BORDER, PANEL_BORDER_WIDTH = c.PANEL_THEME_SPECIAL
    TITLE_PRESET = "heading2"
    TITLE_Y_OFFSET = c.MODAL_TITLE_Y_OFFSET

    SLIDER_W = 300

    def __init__(self, map_screen, country_id):
        super().__init__(map_screen, pygame.Rect(0, 0, 520, 400))
        self.back_state = "MAP"
        self.country_id = country_id
        self.value = politics.value(map_screen.nation_data, country_id)
        self.slider = None
        self.refresh_ui()

    def _set(self, fraction):
        self.value = _from_slider(fraction)

    def refresh_ui(self):
        p = self.panel_rect
        self.slider = Slider(p.x + 150, p.y + 150, self.SLIDER_W,
                             "Political Position", _to_slider(self.value), self._set)

        self.elements = [
            make_back_button(self.exit_screen, style="map"),
            Button(p.x + 30, p.bottom - 55, "medium", "grey", "Reset to Centre", self.reset),
            Button(p.right - 190, p.bottom - 55, "medium", "green", "Save", self.save),
            self.slider,
        ]

    def reset(self):
        self.value = c.POLITICS_START
        self.refresh_ui()

    def save(self):
        nation_data = self.map_screen.nation_data
        politics.set_value(nation_data, self.country_id, self.value)
        # A starting position is a place, not a journey: clear any direction so
        # the scenario does not open with the country already on the move.
        politics.set_drift(nation_data, self.country_id, 0)
        self.map_screen.show_feedback(
            "%s starts as %s (%+d)" % (self.country_id, politics.label(self.value), self.value))
        self.done = True

    def get_panel_title(self):
        return "%s Politics" % self.country_id

    def draw_content(self, surface):
        p = self.panel_rect
        self.draw_panel(surface)

        small = fonts.get("small")
        surface.blit(small.render("libertarian", True, c.UI_TEXT_MUTED),
                     (p.x + 30, self.slider.rect.y - 2))
        surface.blit(small.render("authoritarian", True, c.UI_TEXT_MUTED),
                     (self.slider.rect.right + 14, self.slider.rect.y - 2))

        # The brighter of the palette's two shades: these are button fills, and
        # the base one is chosen to sit under white text rather than to be it.
        reading = fonts.get("normal").render(
            "%s  (%+d)" % (politics.label(self.value), self.value),
            True, c.UI_COLORS[politics.palette(self.value)][1])
        surface.blit(reading, (p.centerx - reading.get_width() // 2, self.slider.rect.y + 50))

        effects = small.render(
            "Damage dealt x%.2f      Research speed x%.2f"
            % (1.0 + c.POLITICS_DAMAGE_SPAN * self.value / float(c.POLITICS_MAX),
               1.0 - c.POLITICS_RESEARCH_SPAN * self.value / float(c.POLITICS_MAX)),
            True, c.UI_TEXT_DIM)
        surface.blit(effects, (p.centerx - effects.get_width() // 2, self.slider.rect.y + 90))


class Politics_List_Screen(NationListOverlayScreen):
    pans_camera = False
    scroll_anywhere = True
    PANEL_BG, PANEL_BORDER, PANEL_BORDER_WIDTH = c.PANEL_THEME_SPECIAL
    PANEL_TITLE = "Starting Politics"
    TITLE_PRESET = "heading2"
    TITLE_Y_OFFSET = c.MODAL_TITLE_Y_OFFSET

    def country_button(self, country_id, x, y):
        value = politics.value(self.map_screen.nation_data, country_id)
        label = country_id if value == c.POLITICS_START else "%s  (%+d %s)" % (
            country_id, value, politics.label(value))
        # Color is the ideology, not "has anybody edited this" -- the list
        # then reads as a heat map of who has centralised, and an untouched
        # map opens uniformly yellow because centrist *is* a position.
        return Button(x, y, "list_row", politics.palette(value), label,
                      lambda cid=country_id: self.edit(cid))

    def edit(self, cid):
        _run_pygame_sub_screen(self.map_screen, Politics_Edit_Screen(self.map_screen, cid),
                               on_done=self.refresh_ui)

    def draw_list_header(self, surface):
        p = self.panel_rect
        note = fonts.get("small").render(
            "Blue libertarian, green liberal, yellow centrist, orange statist, red authoritarian.",
            True, c.UI_TEXT_MUTED)
        surface.blit(note, (p.x + 24, p.y + 58))
