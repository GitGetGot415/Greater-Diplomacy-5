"""A standalone game's country selector: its interesting countries, chosen before the map opens."""
import pygame

import data.constants as c
from data import migrations, queries
from data.io import standalone_game
from data.map import load_map
from data.platform import LoadingSteps
from screens.game import map_launch
from screens.setup import player_setup
from ui.navigation.screen import Screen
from ui.rendering.font_manager import fonts
from ui.rendering.standalone_background import StandaloneBackground
from ui.widgets import text_utils
from ui.widgets.ui_elements import Button, draw_pixel_panel, make_back_button, toggle_color

# --- Layout. Each group moves with its own top value. ---
SIDE_MARGIN = 20
CARD_GAP = 10
MAJOR_TOP = 90
MAJOR_CARD_SIZE = (140, 220)
MAJOR_PORTRAIT_SCALE = 2
MAJOR_FLAG_SIZE = (75, 50)
MINOR_TOP = MAJOR_TOP + MAJOR_CARD_SIZE[1] + 15
MINOR_BUTTON_SIZE = (70, 50)
INFO_TOP = 460
INFO_HEIGHT = 170
INFO_PANEL_WIDTH = 420
INFO_PADDING = 12
SELECT_BUTTON_BOTTOM_MARGIN = 20
PANEL_COLOR = (45, 45, 50)
PANEL_BORDER_COLOR = (15, 15, 15)
TEXT_COLOR = (230, 230, 230)
MUTED_TEXT_COLOR = (170, 170, 170)


def interesting_countries(settings, map_data, nation_data):
    """Return the interesting countries that a new game can start as.

    Majors come first, then minors, each in the order the map editor saved them.
    """
    playable = set(queries.playable_start_countries(map_data, nation_data))
    return [entry for rank in queries.INTERESTING_COUNTRY_RANKS
            for entry in settings["interesting_countries"] if entry["rank"] == rank and entry["country"] in playable]


def load_interesting_countries(scenario_path, settings):
    """Return (nation_data, entries) for a saved scenario's interesting countries."""
    save_meta, map_data, _history = load_map.read_save_files(scenario_path)
    migrations.upgrade_save(save_meta, map_data)
    nation_data = save_meta.get("nation_data", {})
    queries.merge_country_templates(nation_data)
    return nation_data, interesting_countries(settings, map_data, nation_data)


class Country_Select_Screen(Screen):
    """Choose an interesting country, or Other Countries to choose on the map."""
    back_state = "MENU"
    title = "SELECT COUNTRY"

    def __init__(self):
        super().__init__()
        self.nation_data = {}
        self.entries = []
        self.selected = None
        self.chosen_country = None
        self.images = {}
        # The main menu's background. None before the selector first opens.
        self.background = None

    def on_enter(self, app, previous):
        settings = standalone_game.export_settings()
        self.show(*load_interesting_countries(standalone_game.scenario_path(), settings), settings)

    def show(self, nation_data, entries, settings):
        """Show these entries with the first selected, over the main menu's background.

        The export screen's preview calls this with the map editor's current settings.
        """
        self.background = StandaloneBackground(settings)
        self.nation_data, self.entries = nation_data, entries
        self.images = {entry["country"]: self._images(entry["country"]) for entry in self.entries}
        self.selected = self.entries[0]["country"] if self.entries else None
        self.chosen_country = None
        self.refresh_ui()

    def _images(self, country):
        record = self.nation_data.get(country, {})
        portrait = queries.decode_b64_to_surf(record.get("portrait_data", "DEFAULT"), c.PORTRAIT_SIZE,
                                              is_portrait=True, country_name=country)
        flag = queries.decode_b64_to_surf(record.get("flag_data", "DEFAULT"), c.FLAG_SIZE, country_name=country)
        large_portrait = pygame.transform.scale(
            portrait, (c.PORTRAIT_SIZE[0] * MAJOR_PORTRAIT_SCALE, c.PORTRAIT_SIZE[1] * MAJOR_PORTRAIT_SCALE))
        return {"portrait": large_portrait, "card_flag": pygame.transform.scale(flag, MAJOR_FLAG_SIZE), "flag": flag}

    def name(self, country):
        return queries.get_country_display_name(country, self.nation_data)

    def _card_image(self, country):
        """Portrait, flag, and name stacked into one major country card."""
        images = self.images[country]
        width = MAJOR_CARD_SIZE[0] - 10
        name = fonts.get("small").render(text_utils.fit_text(self.name(country), fonts.get("small"), width),
                                         True, TEXT_COLOR)
        parts = (images["portrait"], images["card_flag"], name)
        card = pygame.Surface((width, sum(part.get_height() for part in parts) + 2 * CARD_GAP), pygame.SRCALPHA)
        y = 0
        for part in parts:
            card.blit(part, part.get_rect(midtop=(width // 2, y)))
            y += part.get_height() + CARD_GAP
        return card

    def refresh_ui(self):
        self.elements = [make_back_button(self.exit_screen)]
        majors = [entry for entry in self.entries if entry["rank"] == "major"]
        minors = [entry for entry in self.entries if entry["rank"] == "minor"]

        # Other Countries sits after the major cards, so the row holds one more card than there are majors.
        available = c.SCREEN_WIDTH - 2 * SIDE_MARGIN
        card_width = min(MAJOR_CARD_SIZE[0], (available - len(majors) * CARD_GAP) // (len(majors) + 1))
        row_width = (len(majors) + 1) * card_width + len(majors) * CARD_GAP
        x = (c.SCREEN_WIDTH - row_width) // 2
        for entry in majors:
            country = entry["country"]
            self.elements.append(Button(x, MAJOR_TOP, (card_width, MAJOR_CARD_SIZE[1]),
                                        toggle_color(country == self.selected), self.name(country),
                                        lambda country=country: self.select(country),
                                        image=self._card_image(country), show_text=False))
            x += card_width + CARD_GAP
        other = Button(x, MAJOR_TOP, (card_width, MAJOR_CARD_SIZE[1]), "blue", "Other Countries",
                       self.choose_on_map)
        other.fit_text = True
        self.elements.append(other)

        per_row = max(1, (available + CARD_GAP) // (MINOR_BUTTON_SIZE[0] + CARD_GAP))
        for index, entry in enumerate(minors):
            row, column = divmod(index, per_row)
            count = min(per_row, len(minors) - row * per_row)
            left = (c.SCREEN_WIDTH - (count * MINOR_BUTTON_SIZE[0] + (count - 1) * CARD_GAP)) // 2
            country = entry["country"]
            self.elements.append(Button(left + column * (MINOR_BUTTON_SIZE[0] + CARD_GAP),
                                        MINOR_TOP + row * (MINOR_BUTTON_SIZE[1] + CARD_GAP),
                                        MINOR_BUTTON_SIZE, toggle_color(country == self.selected),
                                        self.name(country), lambda country=country: self.select(country),
                                        image=self.images[country]["flag"], show_text=False))

        select_height = c.SIZES["medium"][1]
        select = Button("centered", c.SCREEN_HEIGHT - SELECT_BUTTON_BOTTOM_MARGIN - select_height, "medium",
                        "green", "Select Country", self.start)
        select.apply_state(enabled=self.selected is not None, color="green")
        self.elements.append(select)

    def select(self, country):
        self.selected = country
        self.refresh_ui()

    def start(self):
        """Open the map as the selected country."""
        self.chosen_country = self.selected
        self.go_to("MAP")

    def choose_on_map(self):
        """Open the map in country selection, as a game without interesting countries does."""
        self.chosen_country = None
        self.go_to("MAP")

    def prepare_map(self, app):
        map_launch.open_saved_map(app, standalone_game.scenario_path())
        if self.chosen_country:
            player_setup.start_as_country(app.states["MAP"], self.chosen_country)
        return True

    def prepare_map_steps(self, app):
        steps = map_launch.open_saved_map_steps(app, standalone_game.scenario_path())
        country = self.chosen_country

        def load_then_start():
            loaded = yield from steps
            if loaded and country:
                player_setup.start_as_country(app.states["MAP"], country)
            return loaded

        return LoadingSteps(load_then_start(), steps.total)

    def draw_background(self, surface):
        if self.background is None:
            super().draw_background(surface)
        else:
            self.background.draw(surface)

    def additional_draw(self, surface):
        entry = next((entry for entry in self.entries if entry["country"] == self.selected), None)
        if entry is None:
            return
        country = entry["country"]
        info = pygame.Rect(SIDE_MARGIN, INFO_TOP, INFO_PANEL_WIDTH, INFO_HEIGHT)
        history = pygame.Rect(info.right + CARD_GAP, INFO_TOP,
                              c.SCREEN_WIDTH - SIDE_MARGIN - info.right - CARD_GAP, INFO_HEIGHT)
        for rect in (info, history):
            draw_pixel_panel(surface, rect, PANEL_COLOR, PANEL_BORDER_COLOR)

        portrait = self.images[country]["portrait"]
        surface.blit(portrait, (info.x + INFO_PADDING, info.y + INFO_PADDING))
        text_x = info.x + 2 * INFO_PADDING + portrait.get_width()
        text_width = info.right - INFO_PADDING - text_x
        record = self.nation_data.get(country, {})
        leader = " ".join(part for part in (record.get("leader_title", ""), record.get("leader_name", "")) if part)
        y = info.y + INFO_PADDING
        for text, preset, color in ((self.name(country), "heading2", TEXT_COLOR), (leader, "normal", MUTED_TEXT_COLOR)):
            if text:
                font = fonts.get(preset)
                surface.blit(font.render(text_utils.fit_text(text, font, text_width), True, color), (text_x, y))
                y += font.get_height() + 6

        font = fonts.get("normal")
        lines = text_utils.wrap_text(entry["description"], font, history.width - 2 * INFO_PADDING,
                                     max_lines=(history.height - 2 * INFO_PADDING) // font.get_linesize(),
                                     ellipsis=c.ELLIPSIS)
        for index, line in enumerate(lines):
            surface.blit(font.render(line, True, TEXT_COLOR),
                         (history.x + INFO_PADDING, history.y + INFO_PADDING + index * font.get_linesize()))
