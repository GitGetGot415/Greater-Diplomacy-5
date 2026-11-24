"""Set a country's starting positions on the four politics axes."""
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


#: The two compasses, top first, each as (axis across, axis up).
COMPASSES = ((politics.ECONOMIC, politics.POLITICAL), (politics.STRATEGY, politics.QUALITY))


class Politics_Edit_Screen(EditorSliderScreen):
    PANEL_STYLE = EDITOR_PANEL_STYLES["politics"]
    RESET_LABEL = "Reset to Centre"

    PANEL_SIZE = (780, 500)
    # One compass per group, beside that group's two sliders.
    COMPASS_X = 107
    COMPASS_SIZE = 130
    COMPASS_TOPS = (82, 272)
    SLIDER_X = 445
    SLIDER_W = 210
    POLE_LABEL_X = 348
    SLIDER_TOPS = (110, 182, 300, 372)
    READING_GAP = 28

    def __init__(self, map_screen, country_id):
        super().__init__(map_screen, pygame.Rect(0, 0, *self.PANEL_SIZE))
        self.country_id = country_id
        self.values = {axis["id"]: politics.axis_value(map_screen.world.nation_data, country_id, axis["id"])
                       for axis in politics.AXES}
        self.refresh_ui()

    @property
    def value(self):
        return self.values[politics.POLITICAL]

    @property
    def economic_value(self):
        return self.values[politics.ECONOMIC]

    def can_edit(self):
        return (self.country_id in self.map_screen.world.nation_data
                and (queries.can_bulk_edit_map(self.map_screen)
                     or queries.can_use_spectator_country_actions(self.map_screen))
                and self.country_id in queries.get_living_nations(self.map_screen.world.map_data))

    def _reading(self, axis):
        value = self.values[axis["id"]]
        return f"{axis['name']}: {politics.axis_label(axis['id'], value)} ({value:+d})"

    def _set(self, index, fraction):
        axis = politics.AXES[index]
        position = _from_slider(fraction)
        if position == self.values[axis["id"]]:
            return
        self.values[axis["id"]] = position
        self.rows[index][0].text = self._reading(axis)
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
        rows = []
        for index, (axis, top) in enumerate(zip(politics.AXES, self.SLIDER_TOPS)):
            slider = Slider(p.x + self.SLIDER_X, p.y + top, self.SLIDER_W, self._reading(axis),
                            _to_slider(self.values[axis["id"]]),
                            lambda fraction, row=index: self._set(row, fraction))
            rows.append((slider, *axis["ends"]))
        return rows

    def reset(self):
        if not self.can_edit():
            return
        self.values = dict.fromkeys(self.values, c.POLITICS_START)
        self.refresh_ui()

    def save(self):
        if not self.can_edit():
            return
        nation_data = self.map_screen.world.nation_data
        quality_changed = self.values[politics.QUALITY] != politics.axis_value(nation_data, self.country_id, politics.QUALITY)
        stat_policies = politics.unit_stat_policies(nation_data, self.country_id)
        for axis in politics.AXES:
            politics.set_axis_value(nation_data, self.country_id, axis["id"], self.values[axis["id"]])
            # A scenario starts with every direction on Hold.
            politics.set_axis_drift(nation_data, self.country_id, axis["id"], 0)
        politics.reconcile_policy(nation_data, self.country_id)
        if quality_changed:
            queries.refresh_unit_stats(self.map_screen.world.map_data, nation_data, queries.get_unit_library(self.map_screen),
                                       owners={self.country_id})
        else:
            queries.refresh_policy_unit_stats(self.map_screen, self.country_id, stat_policies)
        self.map_screen.refresh_map_layers("relations")
        name = queries.get_country_display_name(self.country_id, nation_data)
        positions = ", ".join(f"{politics.axis_label(axis['id'], self.values[axis['id']])} "
                              f"({self.values[axis['id']]:+d})" for axis in politics.AXES)
        self.map_screen.show_feedback(f"{name} starts at {positions}.")
        self.done = True

    def get_panel_title(self):
        return "%s Politics" % queries.get_country_display_name(
            self.country_id, self.map_screen.world.nation_data)

    def _refresh_preview(self):
        self._preview = pygame.Surface(self.panel_rect.size, pygame.SRCALPHA)
        for (x_axis, y_axis), top in zip(COMPASSES, self.COMPASS_TOPS):
            draw_political_compass(
                self._preview, pygame.Rect(self.COMPASS_X, top, self.COMPASS_SIZE, self.COMPASS_SIZE),
                (self.values[x_axis], self.values[y_axis]),
                labels=(politics.AXES_BY_ID[x_axis]["ends"], politics.AXES_BY_ID[y_axis]["ends"]))
        if not self._editable:
            small = fonts.get("small")
            center_x = self.SLIDER_X + self.SLIDER_W // 2
            readings = [self._reading(axis) for axis in politics.AXES] + ["Read-only"]
            for index, text in enumerate(readings):
                reading = small.render(text, True, c.UI_TEXT_LIGHT)
                self._preview.blit(reading, reading.get_rect(centerx=center_x,
                                                             y=self.SLIDER_TOPS[0] + index * self.READING_GAP))

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
        nation_data = self.map_screen.world.nation_data
        country_name = queries.get_country_display_name(country_id, nation_data)
        positions = "  |  ".join(
            f"{politics.axis_label(axis['id'], value)} {value:+d}"
            for axis in politics.AXES
            for value in (politics.axis_value(nation_data, country_id, axis["id"]),))
        # Color is the ideology, not "has anybody edited this" -- the list
        # then reads as a heat map of who has centralised, and an untouched
        # map opens uniformly yellow because centrist *is* a position.
        button = Button(x, y, "list_row", politics.palette(politics.value(nation_data, country_id)),
                        f"{country_name}  |  {positions}", lambda cid=country_id: self.edit(cid))
        button.fit_text = button.fit_single_line = True
        return button
