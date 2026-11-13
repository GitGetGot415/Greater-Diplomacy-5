"""Separate screen that sets up and exports the edited scenario as a standalone game."""
import os

import pygame

import data.constants as c
from data import queries
from data.io import standalone_game
from data.map import save_map
from data.platform import IS_WEB, downloads_dir
from screens.menus.menu import Menu
from screens.setup import country_select
from ui import dialogs
from ui.bars import ui_bars
from ui.dialogs import pickers
from ui.navigation import screen_runner
from ui.navigation.screen import Screen
from ui.rendering.font_manager import fonts
from ui.widgets import text_utils
from ui.widgets.ui_elements import Button, make_back_button

# --- Layout. CONTENT_TOP moves the background rows; COUNTRIES_TOP moves the country list. ---
CONTENT_TOP = 90
ROW_GAP = 46
BUTTON_GAP = 10
SETTING_BUTTON_SIZE = (140, 36)
CLEAR_BUTTON_SIZE = (70, 36)
SWATCH_SIZE = (36, 36)
COUNTRIES_TOP = 220
COUNTRY_ROW_HEIGHT = 42
# The list ends above the two stacked preview buttons.
COUNTRY_LIST_BOTTOM = c.SCREEN_HEIGHT - 160
# Widths of a country row's rank toggle, name, description, and Remove button.
RANK_WIDTH, NAME_WIDTH, DESCRIPTION_WIDTH, REMOVE_WIDTH = 90, 220, 420, 90
SCROLLBAR_GAP = 15
TEXT_COLOR = (230, 230, 230)
SWATCH_BORDER_COLOR = (255, 255, 255)
# Gap between the bottom of the screen and the Export button.
EXPORT_BUTTON_BOTTOM_MARGIN = 40
# Gap between the screen edges and each preview's Close Preview button.
PREVIEW_CLOSE_MARGIN = 20
# Larger sizes would cover the country selector's information panel.
PREVIEW_CLOSE_SIZE = "large"
DESCRIPTION_MAX_LENGTH = 600
DESCRIPTION_LABEL_CHARS = 48
RANK_LABELS = {"major": "Major", "minor": "Minor"}
RANK_COLORS = {"major": "orange", "minor": "light_blue"}


class Standalone_Export_Screen(Screen):
    """Export settings for a standalone game. Back returns to the map editor."""
    back_state = "MAP"
    title = "STANDALONE EXPORT"
    # The text and label of the last background image measured. See image_size_text.
    _image_size = ("", "No image")

    def on_enter(self, app, previous):
        self.map_screen = app.states["MAP"]
        self.scroll_y = 0
        self.refresh_ui()

    def settings(self):
        return queries.normalized_standalone_export_settings(self.map_screen.standalone_export_settings)

    def refresh_ui(self):
        self.elements = [make_back_button(self.exit_screen)]
        self.swatches = []
        self.labels = []
        self.row_labels = []
        if self.map_screen is None:
            return
        settings = self.settings()
        editable = queries.can_bulk_edit_map(self.map_screen)
        width, height = SETTING_BUTTON_SIZE
        center_x = c.SCREEN_WIDTH // 2
        # Every background row starts at the left edge of the two Add buttons.
        left_x = center_x - (2 * width + BUTTON_GAP) // 2

        def setting_button(x, y, color, label, callback, enabled=True, size=SETTING_BUTTON_SIZE, row=False):
            button = Button(x, y, size, color, label, callback)
            button.fit_text = True
            button.apply_state(enabled=editable and enabled, color=color)
            if row:
                self.add_list_row(button)
            else:
                self.elements.append(button)

        self.labels.append(("Menu Background", (center_x, CONTENT_TOP)))
        color_y = CONTENT_TOP + 30
        setting_button(left_x, color_y, "blue", "Background Color", self.choose_color)
        self.swatches.append((pygame.Rect((left_x + width + BUTTON_GAP, color_y), SWATCH_SIZE),
                              settings["background_color"]))

        image_y = color_y + ROW_GAP
        setting_button(left_x, image_y, "blue", "Choose Image", self.choose_image)
        setting_button(left_x + width + BUTTON_GAP, image_y, "red", "Clear",
                       lambda: self.change_setting("background_image", ""),
                       enabled=bool(settings["background_image"]), size=CLEAR_BUTTON_SIZE)
        image_text_x = left_x + width + BUTTON_GAP + CLEAR_BUTTON_SIZE[0] + BUTTON_GAP
        self.labels.append((self.image_size_text(settings), (image_text_x, image_y + height // 2), "midleft"))

        self.labels.append(("Interesting Countries", (center_x, COUNTRIES_TOP)))
        add_y = COUNTRIES_TOP + 30
        available = self.available_countries(settings)
        for index, rank in enumerate(queries.INTERESTING_COUNTRY_RANKS):
            setting_button(left_x + index * (width + BUTTON_GAP), add_y, RANK_COLORS[rank],
                           f"Add {RANK_LABELS[rank]}", lambda rank=rank: self.add_country(rank),
                           enabled=bool(available))

        entries = self.ordered_countries(settings)
        row_width = RANK_WIDTH + NAME_WIDTH + DESCRIPTION_WIDTH + REMOVE_WIDTH + 3 * BUTTON_GAP
        row_x = center_x - row_width // 2
        list_top = add_y + height + BUTTON_GAP
        self.scroll_content_rect = pygame.Rect(0, list_top, c.SCREEN_WIDTH, COUNTRY_LIST_BOTTOM - list_top)
        self.list_track = (row_x + row_width + SCROLLBAR_GAP, list_top, COUNTRY_LIST_BOTTOM - list_top)
        name_font = fonts.get("normal")
        for index, y in self.layout_list_rows(len(entries), COUNTRY_ROW_HEIGHT, list_top,
                                              cull_top=list_top, cull_bottom=COUNTRY_LIST_BOTTOM):
            entry = entries[index]
            country = entry["country"]
            other_rank = next(rank for rank in queries.INTERESTING_COUNTRY_RANKS if rank != entry["rank"])
            x = row_x
            setting_button(x, y, RANK_COLORS[entry["rank"]], RANK_LABELS[entry["rank"]],
                           lambda country=country, rank=other_rank: self.update_country(country, rank=rank),
                           size=(RANK_WIDTH, height), row=True)
            x += RANK_WIDTH + BUTTON_GAP
            name = queries.get_country_display_name(country, self.map_screen.nation_data)
            self.row_labels.append((text_utils.fit_text(name, name_font, NAME_WIDTH), (x, y + height // 2)))
            x += NAME_WIDTH + BUTTON_GAP
            description = (text_utils.truncate_chars(entry["description"], DESCRIPTION_LABEL_CHARS)
                           or "Set Description")
            setting_button(x, y, "blue", description, lambda country=country: self.edit_description(country),
                           size=(DESCRIPTION_WIDTH, height), row=True)
            x += DESCRIPTION_WIDTH + BUTTON_GAP
            setting_button(x, y, "red", "Remove", lambda country=country: self.remove_country(country),
                           size=(REMOVE_WIDTH, height), row=True)

        export_width, export_height = c.SIZES["large"]
        export_y = c.SCREEN_HEIGHT - EXPORT_BUTTON_BOTTOM_MARGIN - export_height
        # Preview Menu sits above Preview Selection, left of Export. Their bottoms line up.
        preview_width, preview_height = c.SIZES["medium"]
        preview_x = center_x - export_width // 2 - BUTTON_GAP - preview_width
        selection_y = export_y + export_height - preview_height
        self.elements.append(Button(preview_x, selection_y - BUTTON_GAP - preview_height, "medium", "light_blue",
                                    "Preview Menu", self.preview))
        self.elements.append(Button(preview_x, selection_y, "medium", "light_blue",
                                    "Preview Selection", self.preview_selection))

        export_button = Button("centered", export_y, "large", "blue", "Export", self.export)
        # The web build cannot write a game folder for players to run.
        export_button.apply_state(enabled=not IS_WEB, color="blue")
        self.elements.append(export_button)

    def image_size_text(self, settings):
        """Name the chosen image's size, or say that none is chosen.

        Scrolling rebuilds the screen, so each image is decoded only once.
        """
        text = settings["background_image"]
        if self._image_size[0] != text:
            try:
                image = queries.load_png_b64(text)
                label = f"{image.get_width()} x {image.get_height()}"
            except (ValueError, pygame.error):
                label = "Unreadable image"
            self._image_size = (text, label)
        return self._image_size[1]

    def additional_events(self, event):
        if self.map_screen is not None:
            self.handle_list_scroll(event, content_rect_attr="scroll_content_rect")

    def additional_draw(self, surface):
        for rect, color in self.swatches:
            surface.fill(color, rect)
            pygame.draw.rect(surface, SWATCH_BORDER_COLOR, rect, 2)
        font = fonts.get("heading2")
        for text, position, *anchor in self.labels:
            rendered = font.render(text, True, TEXT_COLOR)
            surface.blit(rendered, rendered.get_rect(**{anchor[0] if anchor else "midtop": position}))
        if self.map_screen is None:
            return
        name_font = fonts.get("normal")
        with ui_bars.clip_scroll_region(surface, self.scroll_content_rect,
                                        draw_top=self.scroll_y != 0, draw_bottom=self.scroll_y > self.max_scroll):
            for text, position in self.row_labels:
                rendered = name_font.render(text, True, TEXT_COLOR)
                surface.blit(rendered, rendered.get_rect(midleft=position))
        self.draw_list_scrollbar(surface, *self.list_track)

    def change_setting(self, key, value):
        try:
            queries.set_standalone_export_setting(self.map_screen, key, value)
        except ValueError as error:
            dialogs.show_error("Standalone Export", str(error))
        self.refresh_ui()

    def choose_color(self):
        def chosen(color):
            if color is not None:
                self.change_setting("background_color", [int(channel) for channel in color[:3]])
        pickers.ask_color(self, "Background Color", tuple(self.settings()["background_color"]), chosen)

    def choose_image(self):
        def picked(path):
            if not path:
                return
            try:
                with open(path, "rb") as stream:
                    png = stream.read()
                queries.set_standalone_background_image(self.map_screen, png)
            except OSError as error:
                dialogs.show_error("Standalone Export", f"Could not read {path}: {error.strerror}")
            except ValueError as error:
                dialogs.show_error("Standalone Export", str(error))
            self.refresh_ui()

        pickers.open_file_browser(self, "Menu Background Image", downloads_dir(),
                                  extensions=[".png"], on_result=picked)

    # -- Interesting countries ---------------------------------------- #

    @staticmethod
    def ordered_countries(settings):
        """Majors first, then minors, as the standalone country selector shows them."""
        return [entry for rank in queries.INTERESTING_COUNTRY_RANKS
                for entry in settings["interesting_countries"] if entry["rank"] == rank]

    def available_countries(self, settings):
        """Playable starting countries that are not interesting countries yet."""
        listed = {entry["country"] for entry in settings["interesting_countries"]}
        return [country for country in queries.playable_start_countries(self.map_screen.map_data,
                                                                         self.map_screen.nation_data)
                if country not in listed]

    def add_country(self, rank):
        settings = self.settings()
        items = queries.country_picker_items(self.available_countries(settings), self.map_screen.nation_data)

        def chosen(country):
            entry = {"country": country, "rank": rank, "description": ""}
            self.change_setting("interesting_countries", settings["interesting_countries"] + [entry])

        pickers.open_listbox_selector(self, f"Add {RANK_LABELS[rank]} Country", "Choose a country:", items, chosen)

    def update_country(self, country, **changes):
        entries = [dict(entry, **changes) if entry["country"] == country else entry
                   for entry in self.settings()["interesting_countries"]]
        self.change_setting("interesting_countries", entries)

    def remove_country(self, country):
        entries = [entry for entry in self.settings()["interesting_countries"] if entry["country"] != country]
        self.change_setting("interesting_countries", entries)

    def edit_description(self, country):
        entry = next(entry for entry in self.settings()["interesting_countries"] if entry["country"] == country)

        def answered(text):
            if text is not None:
                self.update_country(country, description=text)

        dialogs.ask_string("Country Description", queries.get_country_display_name(country, self.map_screen.nation_data),
                           answered, initial=entry["description"], max_length=DESCRIPTION_MAX_LENGTH)

    def preview(self):
        """Show the standalone game's main menu with the current settings."""
        screen_runner.run_screen(Standalone_Menu_Preview(self.map_screen.editor_scenario_name, self.settings()))

    def preview_selection(self):
        """Show the standalone game's country selector with the current interesting countries.

        An exported game shows the selector only when it has more than one interesting country.
        """
        settings = self.settings()
        entries = country_select.interesting_countries(settings, self.map_screen.map_data, self.map_screen.nation_data)
        screen_runner.run_screen(Standalone_Selection_Preview(self.map_screen.nation_data, entries, settings))

    def export(self):
        """Export the saved copy of this scenario as a standalone game in exports/<scenario name>/.

        game.json receives the settings on this screen.
        """
        if not queries.can_bulk_edit_map(self.map_screen):
            return
        try:
            name = queries.validated_scenario_name(self.map_screen.editor_scenario_name)
            scenario_dir = save_map.editor_save_path(name) if name else None
        except ValueError as error:
            dialogs.show_error("Standalone Export", str(error))
            return
        if scenario_dir is None or not os.path.isdir(scenario_dir):
            dialogs.show_error("Standalone Export", "Save the map before exporting it as a standalone game.")
            return
        destination = standalone_game.export_dir(name)
        if not os.path.exists(destination):
            self._run_export(scenario_dir, name)
            return

        def on_answer(replace):
            if not replace:
                return
            try:
                standalone_game.clear_export_dir(name)
            except OSError as error:
                # A running exported game keeps its files locked on Windows.
                dialogs.show_error("Standalone Export",
                                   f"Could not replace {os.path.abspath(destination)}: {error.strerror}. "
                                   "Close the exported game and anything else using that folder, then try again.")
                return
            self._run_export(scenario_dir, name)

        dialogs.ask_yes_no("Standalone Export",
                           f"{os.path.abspath(destination)} already exists. Replace it? Saves inside it are deleted.",
                           on_answer)

    def _run_export(self, scenario_dir, name):
        screen_runner.run_loading(
            standalone_game.export_steps(scenario_dir, name, self.settings()), "Exporting Standalone Game...",
            on_done=lambda path: self.map_screen.show_feedback(f"Exported standalone game to {path}"),
            on_error=lambda error: dialogs.show_error("Standalone Export", str(error)))


class Standalone_Menu_Preview(Screen):
    """Subscreen that shows a standalone game's main menu. Its buttons do nothing."""

    def __init__(self, title, settings):
        super().__init__()
        self.menu = Menu(title, settings)
        self.elements = [close_preview_button(self.exit_screen)]

    def update(self):
        self.menu.update()

    def draw(self, surface):
        self.menu.draw(surface)
        self.draw_elements(surface)


def close_preview_button(on_click):
    """The Close Preview button in the bottom-left corner of both previews."""
    close_height = c.SIZES[PREVIEW_CLOSE_SIZE][1]
    return Button(PREVIEW_CLOSE_MARGIN, c.SCREEN_HEIGHT - PREVIEW_CLOSE_MARGIN - close_height, PREVIEW_CLOSE_SIZE,
                  "red", "Close Preview", on_click, sound_kind="back")


class Standalone_Selection_Preview(Screen):
    """Subscreen that shows a standalone game's country selector.

    Clicking a country selects it. The selector's Back, Select Country, and Other Countries do nothing.
    """
    MOUSE_EVENTS = (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP, pygame.MOUSEMOTION, pygame.MOUSEWHEEL)

    def __init__(self, nation_data, entries, settings):
        super().__init__()
        self.selector = country_select.Country_Select_Screen()
        self.selector.show(nation_data, entries, settings)
        self.elements = [close_preview_button(self.exit_screen)]

    def handle_events(self, events):
        # Keys stay with the preview, so the back key closes only the preview.
        self.selector.handle_events([event for event in events if event.type in self.MOUSE_EVENTS])
        # The selector's navigation only marks it done. The preview ignores that.
        self.selector.done, self.selector.next_state = False, None
        super().handle_events(events)

    def draw(self, surface):
        self.selector.draw(surface)
        self.draw_elements(surface)

