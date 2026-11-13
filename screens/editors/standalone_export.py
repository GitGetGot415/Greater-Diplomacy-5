"""Separate screen that sets up and exports the edited scenario as a standalone game."""
import os
from copy import deepcopy
from types import SimpleNamespace

import pygame

import data.constants as c
from data import queries
from data.io import keybind_io, settings_schema, standalone_game
from data.map import save_map
from data.platform import IS_WEB, downloads_dir
from screens.menus.menu import Menu
from screens.menus.credits import Credits
from screens.menus.keybinds import Keybinds
from screens.menus.load_game import Load_Game
from screens.menus.mouse_settings import Mouse_Settings
from screens.menus.music_player import Music_Player
from screens.menus.settings import Settings
from screens.setup import country_select
from ui import dialogs
from ui.bars import ui_bars
from ui.dialogs import pickers
from ui.navigation import screen_runner
from ui.navigation.screen import Screen
from ui.navigation.touch_input import TouchInput
from ui.rendering.font_manager import fonts
from ui.rendering.standalone_background import StandaloneBackground
from ui.widgets import text_utils
from ui.widgets.ui_elements import Button, draw_pixel_panel, make_back_button, toggle_color

# --- Layout. Both sections share one left edge and a fixed width. ---
PANEL_WIDTH = 1000
PANEL_PADDING = 24
BACKGROUND_TOP = 90
BACKGROUND_HEIGHT = 246
COUNTRIES_TOP = 350
COUNTRIES_BOTTOM = c.SCREEN_HEIGHT - 90
CONTENT_TOP = BACKGROUND_TOP + 58
ROW_GAP = 46
BUTTON_GAP = 10
SETTING_LABEL_WIDTH = 220
SETTING_BUTTON_SIZE = (140, 36)
CLEAR_BUTTON_SIZE = (70, 36)
IMAGE_FIT_BUTTON_SIZE = (100, 36)
WINDOW_PREVIEW_WIDTH = 200
WINDOW_PREVIEW_BORDER = 2
SWATCH_SIZE = (36, 36)
COUNTRY_ROW_HEIGHT = 42
COUNTRY_LIST_TOP = COUNTRIES_TOP + 100
COUNTRY_LIST_BOTTOM = COUNTRIES_BOTTOM - 16
RANK_WIDTH, NAME_WIDTH, DESCRIPTION_WIDTH, REMOVE_WIDTH = 90, 220, 500, 90
SCROLLBAR_GAP = 12
TEXT_COLOR = (230, 230, 230)
PANEL_COLOR = (34, 40, 52)
PANEL_BORDER_COLOR = (90, 110, 140)
LIST_COLOR = (24, 28, 38)
SWATCH_BORDER_COLOR = (255, 255, 255)
FOOTER_Y = c.SCREEN_HEIGHT - 70
FOOTER_BUTTON_SIZE = (180, 44)
# The large Close Preview button stays in the bottom-left on every preview screen.
PREVIEW_CLOSE_MARGIN = 20
PREVIEW_CLOSE_SIZE = "large"
DESCRIPTION_MAX_LENGTH = 600
DESCRIPTION_LABEL_CHARS = 48
RANK_LABELS = {"major": "Major", "minor": "Minor"}
RANK_COLORS = {"major": "orange", "minor": "light_blue"}
IMAGE_FIT_LABELS = {"fill": "Fill", "stretch": "Stretch", "actual": "Actual Size"}


class Standalone_Export_Screen(Screen):
    """Export settings for a standalone game. Back returns to the map editor."""
    back_state = "MAP"
    title = "STANDALONE EXPORT"
    # The text and label of the last background image measured. See image_size_text.
    _image_size = ("", "No image")
    # The settings and screen size of the last window preview, and the preview. See window_preview.
    _window_preview = (None, None)

    def on_enter(self, app, previous):
        self.controller = app
        self.map_screen = app.states["MAP"]
        self.scroll_y = 0
        self.refresh_ui()

    def settings(self):
        return queries.normalized_standalone_export_settings(self.map_screen.standalone_export_settings)

    def refresh_ui(self):
        panel_x = (c.SCREEN_WIDTH - PANEL_WIDTH) // 2
        self.elements = [make_back_button(self.exit_screen, pos=(panel_x, FOOTER_Y))]
        self.swatches, self.labels, self.row_labels = [], [], []
        self.column_labels = []
        if self.map_screen is None:
            return
        settings = self.settings()
        editable = queries.can_bulk_edit_map(self.map_screen)
        width, height = SETTING_BUTTON_SIZE
        left_x = panel_x + PANEL_PADDING
        control_x = left_x + SETTING_LABEL_WIDTH
        self.background_panel = pygame.Rect(panel_x, BACKGROUND_TOP, PANEL_WIDTH, BACKGROUND_HEIGHT)
        self.country_panel = pygame.Rect(panel_x, COUNTRIES_TOP, PANEL_WIDTH, COUNTRIES_BOTTOM - COUNTRIES_TOP)

        def setting_button(x, y, color, label, callback, enabled=True, size=SETTING_BUTTON_SIZE, row=False, selected=False):
            button = Button(x, y, size, color, label, callback)
            button.fit_text = True
            button.is_selected = selected
            button.apply_state(enabled=editable and enabled, color=color)
            if row:
                self.add_list_row(button)
            else:
                self.elements.append(button)

        self.labels.append(("Menu & Selection Background", (left_x, BACKGROUND_TOP + 24), "midleft"))
        color_y = CONTENT_TOP
        self.labels.append(("Background Color", (left_x, color_y + height // 2), "midleft"))
        setting_button(control_x, color_y, "blue", "Choose Color", self.choose_color)
        self.swatches.append((pygame.Rect((control_x + width + BUTTON_GAP, color_y), SWATCH_SIZE), settings["background_color"]))

        image_y = color_y + ROW_GAP
        self.labels.append(("Image", (left_x, image_y + height // 2), "midleft"))
        setting_button(control_x, image_y, "blue", "Choose Image", self.choose_image)
        setting_button(control_x + width + BUTTON_GAP, image_y, "red", "Clear", lambda: self.change_setting("background_image", ""), enabled=bool(settings["background_image"]), size=CLEAR_BUTTON_SIZE)
        image_text_x = control_x + width + 2 * BUTTON_GAP + CLEAR_BUTTON_SIZE[0]
        self.labels.append((self.image_size_text(settings), (image_text_x, image_y + height // 2), "midleft"))

        # Fit and smoothing apply only to an image, so they are disabled without one.
        fit_y = image_y + ROW_GAP
        has_image = bool(settings["background_image"])
        self.labels.append(("Image Scaling", (left_x, fit_y + height // 2), "midleft"))
        for index, fit in enumerate(queries.STANDALONE_IMAGE_FITS):
            selected = settings["image_fit"] == fit
            setting_button(control_x + index * (IMAGE_FIT_BUTTON_SIZE[0] + BUTTON_GAP), fit_y, toggle_color(selected), IMAGE_FIT_LABELS[fit], lambda fit=fit: self.change_setting("image_fit", fit), enabled=has_image, size=IMAGE_FIT_BUTTON_SIZE, selected=selected)
        smoothing_y = fit_y + ROW_GAP
        smoothing = settings["image_smoothing"]
        self.labels.append(("Smoothing", (left_x, smoothing_y + height // 2), "midleft"))
        setting_button(control_x, smoothing_y, toggle_color(smoothing), "On" if smoothing else "Off", lambda: self.change_setting("image_smoothing", not smoothing), enabled=has_image, selected=smoothing)

        # Cached background preview retains the game window's aspect ratio.
        preview_height = round(WINDOW_PREVIEW_WIDTH * c.SCREEN_HEIGHT / c.SCREEN_WIDTH)
        self.window_preview_rect = pygame.Rect(self.background_panel.right - PANEL_PADDING - WINDOW_PREVIEW_WIDTH, CONTENT_TOP, WINDOW_PREVIEW_WIDTH, preview_height)
        self.window_preview_surface = self.window_preview(settings)

        self.labels.append(("Interesting Countries", (left_x, COUNTRIES_TOP + 32), "midleft"))
        available = self.available_countries(settings)
        add_x = self.country_panel.right - PANEL_PADDING - 2 * width - BUTTON_GAP
        for index, rank in enumerate(queries.INTERESTING_COUNTRY_RANKS):
            setting_button(add_x + index * (width + BUTTON_GAP), COUNTRIES_TOP + 14, RANK_COLORS[rank], f"Add {RANK_LABELS[rank]}", lambda rank=rank: self.add_country(rank), enabled=bool(available))

        entries = self.ordered_countries(settings)
        row_width = RANK_WIDTH + NAME_WIDTH + DESCRIPTION_WIDTH + REMOVE_WIDTH + 3 * BUTTON_GAP
        self.list_panel = pygame.Rect(left_x - 8, COUNTRY_LIST_TOP - 32, row_width + SCROLLBAR_GAP + 30, COUNTRY_LIST_BOTTOM - COUNTRY_LIST_TOP + 40)
        header_x = left_x
        for label, column_width in (("Rank", RANK_WIDTH), ("Country", NAME_WIDTH), ("Description", DESCRIPTION_WIDTH)):
            self.column_labels.append((label, (header_x, COUNTRY_LIST_TOP - 22)))
            header_x += column_width + BUTTON_GAP
        self.scroll_content_rect = pygame.Rect(left_x, COUNTRY_LIST_TOP, row_width, COUNTRY_LIST_BOTTOM - COUNTRY_LIST_TOP)
        self.list_track = (left_x + row_width + SCROLLBAR_GAP, COUNTRY_LIST_TOP, COUNTRY_LIST_BOTTOM - COUNTRY_LIST_TOP)
        name_font = fonts.get("normal")
        for index, y in self.layout_list_rows(len(entries), COUNTRY_ROW_HEIGHT, COUNTRY_LIST_TOP, cull_top=COUNTRY_LIST_TOP, cull_bottom=COUNTRY_LIST_BOTTOM):
            entry = entries[index]
            country = entry["country"]
            other_rank = next(rank for rank in queries.INTERESTING_COUNTRY_RANKS if rank != entry["rank"])
            x = left_x
            setting_button(x, y, RANK_COLORS[entry["rank"]], RANK_LABELS[entry["rank"]], lambda country=country, rank=other_rank: self.update_country(country, rank=rank), size=(RANK_WIDTH, height), row=True)
            x += RANK_WIDTH + BUTTON_GAP
            name = queries.get_country_display_name(country, self.map_screen.nation_data)
            self.row_labels.append((text_utils.fit_text(name, name_font, NAME_WIDTH), (x, y + height // 2)))
            x += NAME_WIDTH + BUTTON_GAP
            description = text_utils.truncate_chars(entry["description"], DESCRIPTION_LABEL_CHARS) or "Set Description"
            setting_button(x, y, "blue", description, lambda country=country: self.edit_description(country), size=(DESCRIPTION_WIDTH, height), row=True)
            x += DESCRIPTION_WIDTH + BUTTON_GAP
            setting_button(x, y, "red", "Remove", lambda country=country: self.remove_country(country), size=(REMOVE_WIDTH, height), row=True)

        export_x = self.country_panel.right - FOOTER_BUTTON_SIZE[0]
        self.elements.append(Button(export_x - FOOTER_BUTTON_SIZE[0] - BUTTON_GAP, FOOTER_Y, FOOTER_BUTTON_SIZE, "light_blue", "Preview Game", self.preview))
        export_button = Button(export_x, FOOTER_Y, FOOTER_BUTTON_SIZE, "blue", "Export Game", self.export)
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

    def window_preview(self, settings):
        """Return the background drawn at the window's size and shrunk to the preview.

        refresh_ui calls this, and frames only draw the result. Scrolling also rebuilds the screen,
        so the background is drawn again only when its settings or the window size change.
        """
        key = (tuple(settings["background_color"]), settings["background_image"], settings["image_fit"],
               settings["image_smoothing"], self.window_preview_rect.size, c.SCREEN_WIDTH, c.SCREEN_HEIGHT)
        if self._window_preview[0] != key:
            window = pygame.Surface((c.SCREEN_WIDTH, c.SCREEN_HEIGHT))
            StandaloneBackground(settings).draw(window)
            self._window_preview = (key, pygame.transform.smoothscale(window, self.window_preview_rect.size))
        return self._window_preview[1]

    def additional_draw(self, surface):
        if self.map_screen is not None:
            for rect in (self.background_panel, self.country_panel):
                draw_pixel_panel(surface, rect, PANEL_COLOR, PANEL_BORDER_COLOR, gradient_strength=0.25)
            draw_pixel_panel(surface, self.list_panel, LIST_COLOR, PANEL_BORDER_COLOR, gradient_strength=0.15)
            surface.blit(self.window_preview_surface, self.window_preview_rect)
            pygame.draw.rect(surface, SWATCH_BORDER_COLOR,
                             self.window_preview_rect.inflate(2 * WINDOW_PREVIEW_BORDER, 2 * WINDOW_PREVIEW_BORDER),
                             WINDOW_PREVIEW_BORDER)
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
        for text, position in self.column_labels:
            surface.blit(name_font.render(text, True, TEXT_COLOR), position)
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
        """Browse the standalone menu screens without starting or loading a game."""
        settings = self.settings()
        entries = country_select.interesting_countries(settings, self.map_screen.map_data, self.map_screen.nation_data)
        screen_runner.run_screen(Standalone_Menu_Preview(self.map_screen.editor_scenario_name, settings, self.controller, self.map_screen.nation_data, entries))

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
    """Browse real standalone menu screens inside one preview navigation boundary."""
    PREVIEW_STATES = {"MENU", "COUNTRY_SELECT", "LOAD_GAME", "SETTINGS", "KEYBINDS", "MOUSE_SETTINGS", "MUSIC_PLAYER", "CREDITS"}

    def __init__(self, title, settings, controller=None, nation_data=None, entries=()):
        super().__init__()
        self.settings = queries.normalized_standalone_export_settings(settings)
        self.controller = controller
        self.nation_data, self.entries = nation_data or {}, entries
        # Exported games start with the shared preference defaults, without editor credentials or paths.
        self.settings_controller = SimpleNamespace(**deepcopy(settings_schema.defaults()))
        self.settings_controller.keybinds = keybind_io.default_keybinds()
        self.settings_controller.touch_input = TouchInput()
        self.menu = Menu(title, self.settings)
        # Preview always shows country selection, even when an export would start directly.
        self.menu.new_game_btn.callback = lambda: self.menu.go_to("COUNTRY_SELECT")
        if self.menu.exit_btn is not None:
            self.menu.exit_btn.visible = False
        self.screens = {"MENU": self.menu}
        self.current_state = "MENU"
        self.current_screen = self.menu
        self.elements = [close_preview_button(self.exit_screen)]

    @property
    def text_input_active(self):
        return self.current_screen.text_input_active

    def open_screen(self, state):
        """Only preview destinations are reachable; MAP never enters this state table."""
        if state not in self.PREVIEW_STATES:
            return
        if state not in self.screens:
            if state == "COUNTRY_SELECT":
                screen = country_select.Country_Select_Screen(preview=True)
                screen.show(self.nation_data, self.entries, self.settings)
            elif state == "SETTINGS":
                screen = Settings(self.settings_controller, standalone=True, preview=True, standalone_settings=self.settings)
            elif state == "KEYBINDS":
                screen = Keybinds(self.settings_controller, preview=True)
            elif state == "MOUSE_SETTINGS":
                screen = Mouse_Settings(self.settings_controller, preview=True)
            elif state == "MUSIC_PLAYER":
                if self.controller is None:
                    return
                screen = Music_Player(self.controller, standalone=True, preview=True)
            elif state == "LOAD_GAME":
                screen = Load_Game(standalone=True, preview=True)
            elif state == "CREDITS":
                screen = Credits(standalone=True)
            self.screens[state] = screen
        self.current_screen.cancel_pointer_input()
        self.current_state = state
        self.current_screen = self.screens[state]
        self.current_screen.done, self.current_screen.next_state = False, None
        if state == "SETTINGS":
            self.current_screen.refresh_ui()

    def follow_navigation(self):
        if not self.current_screen.done:
            return
        destination = self.current_screen.next_state
        self.current_screen.done, self.current_screen.next_state = False, None
        if self.current_state == "MENU" and destination is None:
            self.exit_screen()
        else:
            self.open_screen(destination)

    def handle_back_key(self):
        self.current_screen.handle_back_key()
        self.follow_navigation()

    def handle_events(self, events):
        for event in events:
            close_was_pressed = self.elements[0].is_pressed
            super().handle_events([event])
            if self.done:
                return
            # Keep clicks on Close out of the child, but still release a drag begun elsewhere.
            if hasattr(event, "pos") and self.elements[0].rect.collidepoint(event.pos) and (event.type == pygame.MOUSEBUTTONDOWN or close_was_pressed):
                continue
            self.current_screen.handle_events([event])
            self.follow_navigation()
            if self.done:
                return

    def cancel_active_drags(self):
        super().cancel_active_drags()
        self.current_screen.cancel_active_drags()

    def update(self):
        self.current_screen.update()
        self.follow_navigation()

    def draw(self, surface):
        self.current_screen.draw(surface)
        self.draw_elements(surface)


def close_preview_button(on_click):
    """The same Close Preview control remains available on every preview screen."""
    height = c.SIZES[PREVIEW_CLOSE_SIZE][1]
    return Button(PREVIEW_CLOSE_MARGIN, c.SCREEN_HEIGHT - PREVIEW_CLOSE_MARGIN - height, PREVIEW_CLOSE_SIZE, "red", "Close Preview", on_click, sound_kind="back")
