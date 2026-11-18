"""Set a country's starting coordinates on the political compass."""
import pygame
import data.constants as c
from ui.background_styles import EDITOR_PANEL_STYLES
from data import queries
from ui.navigation.screen import EditorSliderScreen, NationListOverlayScreen
from ui.widgets.ui_elements import Button, Slider, draw_political_compass, make_back_button
from ui.rendering.font_manager import fonts
from map_logic import politics


def _to_slider(political_value):
    """Axis value -> the Slider's 0.0-1.0."""
    span = float(c.POLITICS_MAX - c.POLITICS_MIN)
    return (political_value - c.POLITICS_MIN) / span


def _from_slider(fraction):
    """The Slider's 0.0-1.0 -> axis value."""
    span = float(c.POLITICS_MAX - c.POLITICS_MIN)
    return politics.clamp(c.POLITICS_MIN + fraction * span)


class Politics_Edit_Screen(EditorSliderScreen):
    PANEL_STYLE = EDITOR_PANEL_STYLES["politics"]
    RESET_LABEL = "Reset to Centre"

    PANEL_SIZE = (780, 340)
    COMPASS_RECT = (107, 82, 146, 146)
    SLIDER_X = 445
    SLIDER_W = 210
    POLE_LABEL_X = 348
    SLIDER_TOP = 113
    SLIDER_GAP = 82
    EFFECTS_Y = 245

    def __init__(self, map_screen, country_id):
        super().__init__(map_screen, pygame.Rect(0, 0, *self.PANEL_SIZE))
        self.country_id = country_id
        self.value = politics.value(map_screen.nation_data, country_id)
        self.economic_value = politics.economic_value(map_screen.nation_data, country_id)
        self.refresh_ui()

    def can_edit(self):
        return (self.country_id in self.map_screen.nation_data
                and (queries.can_bulk_edit_map(self.map_screen)
                     or queries.can_use_spectator_country_actions(self.map_screen))
                and self.country_id in queries.get_living_nations(self.map_screen.map_data))

    def _readings(self):
        return (f"Political: {politics.label(self.value)} ({self.value:+d})",
                f"Economic: {politics.economic_label(self.economic_value)} ({self.economic_value:+d})")

    def _set(self, index, fraction):
        position = _from_slider(fraction)
        if index == 0:
            if position == self.value:
                return
            self.value = position
        else:
            if position == self.economic_value:
                return
            self.economic_value = position
        self.rows[index][0].text = self._readings()[index]
        self._refresh_preview()

    def refresh_ui(self):
        self._editable = self.can_edit()
        if self._editable:
            super().refresh_ui()
        else:
            self.rows = []
            self.elements = [make_back_button(self.exit_screen, style="map")]
        self._refresh_preview()

    def slider_rows(self):
        p = self.panel_rect
        axes = ((self.value, "Libertarian", "Authoritarian"),
                (self.economic_value, "Planned", "Market"))
        rows = []
        for index, (value, low, high) in enumerate(axes):
            slider = Slider(p.x + self.SLIDER_X, p.y + self.SLIDER_TOP + index * self.SLIDER_GAP,
                            self.SLIDER_W, self._readings()[index], _to_slider(value),
                            lambda fraction, row=index: self._set(row, fraction))
            rows.append((slider, low, high))
        return rows

    def reset(self):
        if not self.can_edit():
            return
        self.value = c.POLITICS_START
        self.economic_value = c.POLITICS_START
        self.refresh_ui()

    def save(self):
        if not self.can_edit():
            return
        nation_data = self.map_screen.nation_data
        politics.set_value(nation_data, self.country_id, self.value)
        politics.set_economic_value(nation_data, self.country_id, self.economic_value)
        # A scenario starts with both directions on Hold.
        politics.set_drift(nation_data, self.country_id, 0)
        politics.set_economic_drift(nation_data, self.country_id, 0)
        self.map_screen.invalidate_map_presentation_cache()
        name = queries.get_country_display_name(self.country_id, nation_data)
        self.map_screen.show_feedback(
            f"{name} starts at {politics.label(self.value)} ({self.value:+d}), "
            f"{politics.economic_label(self.economic_value)} ({self.economic_value:+d}).")
        self.done = True

    def get_panel_title(self):
        return "%s Politics" % queries.get_country_display_name(
            self.country_id, self.map_screen.nation_data)

    def _refresh_preview(self):
        self._preview = pygame.Surface(self.panel_rect.size, pygame.SRCALPHA)
        draw_political_compass(self._preview, pygame.Rect(*self.COMPASS_RECT), (self.economic_value, self.value))
        small = fonts.get("small")
        center_x = self.SLIDER_X + self.SLIDER_W // 2
        if not self._editable:
            for index, text in enumerate((*self._readings(), "Read-only")):
                reading = small.render(text, True, c.UI_TEXT_LIGHT)
                self._preview.blit(reading, reading.get_rect(centerx=center_x, y=self.SLIDER_TOP + index * 28))
        damage = politics.axis_damage_multiplier(self.value)
        research = politics.axis_research_multiplier(self.value)
        effects = small.render(f"Damage dealt x{damage:.2f}      Research speed x{research:.2f}", True, c.UI_TEXT_DIM)
        self._preview.blit(effects, effects.get_rect(centerx=center_x, y=self.EFFECTS_Y))

    def draw_content(self, surface):
        super().draw_content(surface)
        surface.blit(self._preview, self.panel_rect)


class Politics_List_Screen(NationListOverlayScreen):
    PANEL_BG, PANEL_BORDER, PANEL_BORDER_WIDTH = c.PANEL_THEME_SPECIAL
    PANEL_STYLE = EDITOR_PANEL_STYLES["politics_list"]
    PANEL_TITLE = "Starting Politics"
    LIST_NOTE = "Blue libertarian, green liberal, yellow centrist, orange statist, red authoritarian."
    EDIT_SCREEN = Politics_Edit_Screen

    def country_button(self, country_id, x, y):
        nation_data = self.map_screen.nation_data
        value = politics.value(nation_data, country_id)
        economic = politics.economic_value(nation_data, country_id)
        country_name = queries.get_country_display_name(country_id, nation_data)
        label = f"{country_name}  |  {politics.label(value)} {value:+d}  |  {politics.economic_label(economic)} {economic:+d}"
        # Color is the ideology, not "has anybody edited this" -- the list
        # then reads as a heat map of who has centralised, and an untouched
        # map opens uniformly yellow because centrist *is* a position.
        return Button(x, y, "list_row", politics.palette(value), label,
                      lambda cid=country_id: self.edit(cid))
