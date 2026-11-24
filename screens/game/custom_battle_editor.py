"""Group Settings for the units selected on the tactical battle screen."""

from data import queries
from screens.game import custom_battle_layout as layout
from ui.dialogs import pickers
from ui.navigation.modal_screen import ModalScreen
from ui.widgets.ui_elements import Button, Slider


class CustomBattleUnitEditor(ModalScreen):
    """Edit one custom roster entry, or a selected group, with the country picker and an HP slider."""

    PANEL_SIZE = (460, 250)
    ROW_TOP = 70
    ROW_HEIGHT = 42
    ROW_GAP = 12
    DONE_SIZE = (100, 34)
    SLIDER_OFFSET = ROW_HEIGHT + ROW_GAP + 28
    DONE_GAP = 40

    def __init__(self, battle_screen, side, units):
        super().__init__(battle_screen, "Unit Settings" if len(units) == 1 else "Group Settings")
        self.battle_screen = battle_screen
        self.side = side
        self.units = units
        self.refresh_ui()

    def _health_percent(self, unit):
        return unit["health"] / unit["max_health"] * 100

    def refresh_ui(self):
        x = self.panel_rect.x + self.PAD
        y = self.panel_rect.y + self.ROW_TOP
        width = self.panel_rect.width - self.PAD * 2
        owners = {unit["owner"] for unit in self.units}
        percents = {round(self._health_percent(unit)) for unit in self.units}
        country = (queries.get_country_display_name(next(iter(owners)), self.battle_screen.country_data)
                   if len(owners) == 1 else layout.MIXED_LABEL)
        health = f"{next(iter(percents))}%" if len(percents) == 1 else layout.MIXED_LABEL
        buttons = [
            Button(x, y, (width, self.ROW_HEIGHT), "grey", f"Nationality: {country}",
                   self.choose_country, font_size=18),
            Button(self.panel_rect.centerx - self.DONE_SIZE[0] // 2,
                   y + self.SLIDER_OFFSET + self.DONE_GAP, self.DONE_SIZE, "blue", "Done",
                   self.exit_screen, font_size=18, sound_kind="back"),
        ]
        for button in buttons:
            button.fit_text = True
            button.fit_single_line = True
        # The label is drawn above the track, so the slider sits below that label's room.
        self.hp_slider = Slider(x, y + self.SLIDER_OFFSET, width, f"Starting HP: {health}",
                                self._health_percent(self.units[0]), self.set_percent,
                                visual_max=100, allowed_max=100)
        self.elements = [buttons[0], self.hp_slider, buttons[1]]

    def set_percent(self, value):
        percent = max(1, round(value))
        if self.battle_screen.set_unit_options(self.side, self.units, health_percent=percent):
            # Keep the dragged slider alive instead of rebuilding the controls.
            self.hp_slider.text = f"Starting HP: {percent}%"

    def _set_options(self, **options):
        if self.battle_screen.set_unit_options(self.side, self.units, **options):
            self.refresh_ui()

    def choose_country(self):
        pickers.open_listbox_selector(
            self, "Nationality", "",
            queries.country_picker_items(self.battle_screen.nationalities, self.battle_screen.country_data),
            lambda country: self._set_options(owner=country))
