"""Separate screen that sets up and exports the edited scenario as a standalone game."""
import os
import tempfile
from copy import deepcopy
from types import SimpleNamespace

import pygame

import data.constants as c
from data import queries
from data.io import keybind_io, settings_schema, standalone_game, standalone_music
from data.map import save_map
from data.platform import IS_WEB, LoadingSteps, downloads_dir
from screens.menus.menu import Menu
from screens.menus.credits import Credits
from screens.menus.keybinds import Keybinds
from screens.menus.load_game import Load_Game
from screens.menus.mouse_settings import Mouse_Settings
from screens.menus.music_player import Music_Player
from screens.menus.settings import Settings
from screens.setup import country_select
from ui import dialogs, music_playback
from ui.bars import ui_bars
from ui.dialogs import pickers
from ui.navigation import screen_runner
from ui.navigation.screen import Screen
from ui.navigation.touch_input import TouchInput
from ui.rendering.font_manager import fonts
from ui.rendering.standalone_background import StandaloneBackground
from ui.widgets import text_utils
from ui.widgets.ui_elements import Button, draw_pixel_panel, make_back_button, toggle_color

# --- Layout. Background and countries share the left column; music occupies the right. ---
PANEL_X = 24
PANEL_WIDTH = 780
PANEL_PADDING = 20
BACKGROUND_TOP = 90
MUSIC_PANEL_X = PANEL_X + PANEL_WIDTH + 16
MUSIC_PANEL_WIDTH = c.SCREEN_WIDTH - MUSIC_PANEL_X - PANEL_X
MUSIC_BUTTON_SIZE = (140, 30)
MUSIC_BASE_BUTTON_SIZE = (190, 28)
MUSIC_STARTING_Y = BACKGROUND_TOP + 52
MUSIC_SONGS_Y = MUSIC_STARTING_Y + 92
MUSIC_ICON_Y = MUSIC_SONGS_Y + 90
MUSIC_NAME_Y = MUSIC_ICON_Y + 70
MUSIC_BASE_Y = MUSIC_NAME_Y + 72
MUSIC_BASE_TOP = MUSIC_BASE_Y + 26
MUSIC_BASE_ROW_GAP = 34
MUSIC_SIZE_Y = MUSIC_BASE_Y + 138
MUSIC_CLEAR_SIZE = (70, 30)
MUSIC_ICON_SIZE = (56, 56)
MUSIC_SIZE_UNITS = ("B", "KiB", "MiB", "GiB")
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
WINDOW_PREVIEW_WIDTH = 160
WINDOW_PREVIEW_BORDER = 2
SWATCH_SIZE = (36, 36)
COUNTRY_ROW_HEIGHT = 42
COUNTRY_LIST_TOP = COUNTRIES_TOP + 100
COUNTRY_LIST_BOTTOM = COUNTRIES_BOTTOM - 16
RANK_WIDTH, NAME_WIDTH, DESCRIPTION_WIDTH, REMOVE_WIDTH = 80, 170, 350, 70
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
    # Album icon decoding is cached across country-list scrolling and other UI rebuilds.
    _music_icon_text = None
    _music_icon = None

    def on_enter(self, app, previous):
        self.controller = app
        self.map_screen = app.states["MAP"]
        self.scroll_y = 0
        self.base_album_inventory = standalone_music.base_album_inventory()
        self.refresh_ui()

    def settings(self):
        return queries.normalized_standalone_export_settings(self.map_screen.standalone_export_settings)

    def refresh_ui(self):
        panel_x = PANEL_X
        self.elements = [make_back_button(self.exit_screen, pos=(panel_x, FOOTER_Y))]
        self.swatches, self.labels, self.row_labels = [], [], []
        self.column_labels = []
        self.music_labels = []
        self.music_icon_surface = None
        if self.map_screen is None:
            return
        settings = self.settings()
        editable = queries.can_bulk_edit_map(self.map_screen)
        width, height = SETTING_BUTTON_SIZE
        left_x = panel_x + PANEL_PADDING
        control_x = left_x + SETTING_LABEL_WIDTH
        self.background_panel = pygame.Rect(panel_x, BACKGROUND_TOP, PANEL_WIDTH, BACKGROUND_HEIGHT)
        self.country_panel = pygame.Rect(panel_x, COUNTRIES_TOP, PANEL_WIDTH, COUNTRIES_BOTTOM - COUNTRIES_TOP)
        self.music_panel = pygame.Rect(MUSIC_PANEL_X, BACKGROUND_TOP, MUSIC_PANEL_WIDTH, COUNTRIES_BOTTOM - BACKGROUND_TOP)

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

        music = settings["music"]
        music_x = self.music_panel.x + PANEL_PADDING
        self.labels.append(("Album & Music", (music_x, BACKGROUND_TOP + 24), "midleft"))
        self.music_labels.extend([("Starting Song", (music_x, MUSIC_STARTING_Y)), (text_utils.fit_text(music["starting_song"] or "None", fonts.get("small"), MUSIC_PANEL_WIDTH - 2 * PANEL_PADDING), (music_x, MUSIC_STARTING_Y + 65)), (f"Other Songs: {len(music['songs']) - bool(music['starting_song'])}", (music_x, MUSIC_SONGS_Y)), ("Album Icon", (music_x, MUSIC_ICON_Y)), ("Album Name", (music_x, MUSIC_NAME_Y)), ("Include Base GD5 Albums", (music_x, MUSIC_BASE_Y))])
        setting_button(music_x, MUSIC_STARTING_Y + 26, "blue", "Choose Song", self.choose_starting_song, size=MUSIC_BUTTON_SIZE)
        setting_button(music_x + MUSIC_BUTTON_SIZE[0] + BUTTON_GAP, MUSIC_STARTING_Y + 26, "red", "Clear", lambda: self.change_music(starting_song=""), enabled=bool(music["starting_song"]), size=MUSIC_CLEAR_SIZE)
        setting_button(music_x, MUSIC_SONGS_Y + 26, "blue", "Add Songs", self.choose_other_songs, size=MUSIC_BUTTON_SIZE)
        setting_button(music_x + MUSIC_BUTTON_SIZE[0] + BUTTON_GAP, MUSIC_SONGS_Y + 26, "red", "Remove Song", self.remove_music_song, enabled=any(song["name"] != music["starting_song"] for song in music["songs"]), size=MUSIC_BUTTON_SIZE)
        setting_button(music_x, MUSIC_ICON_Y + 26, "blue", "Choose icon.png", self.choose_album_icon, size=MUSIC_BUTTON_SIZE)
        setting_button(music_x + MUSIC_BUTTON_SIZE[0] + BUTTON_GAP, MUSIC_ICON_Y + 26, "red", "Clear", lambda: self.change_music(icon=""), enabled=bool(music["icon"]), size=MUSIC_CLEAR_SIZE)
        if music["icon"]:
            if self._music_icon_text != music["icon"]:
                self._music_icon_text = music["icon"]
                try:
                    self._music_icon = pygame.transform.smoothscale(queries.load_png_b64(music["icon"]), MUSIC_ICON_SIZE)
                except (ValueError, pygame.error):
                    self._music_icon = None
            self.music_icon_surface = self._music_icon
        self.music_icon_rect = pygame.Rect(self.music_panel.right - PANEL_PADDING - MUSIC_ICON_SIZE[0], MUSIC_ICON_Y + 2, *MUSIC_ICON_SIZE)
        name = music["album_name"] or self.map_screen.editor_scenario_name or "Set Album Name"
        setting_button(music_x, MUSIC_NAME_Y + 26, "blue", name, self.choose_album_name, size=(MUSIC_PANEL_WIDTH - 2 * PANEL_PADDING, 30))
        for index, album in enumerate(c.UNDELETABLE_ALBUMS):
            column, row = index % 2, index // 2
            included = album in music["base_albums"]
            setting_button(music_x + column * (MUSIC_BASE_BUTTON_SIZE[0] + BUTTON_GAP), MUSIC_BASE_TOP + row * MUSIC_BASE_ROW_GAP, toggle_color(included), album, lambda album=album: self.toggle_base_album(album), enabled=album in self.base_album_inventory, size=MUSIC_BASE_BUTTON_SIZE, selected=included)
        total_bytes = standalone_music.music_size(music, self.base_album_inventory)
        size = total_bytes
        for unit in MUSIC_SIZE_UNITS:
            if size < 1024 or unit == MUSIC_SIZE_UNITS[-1]:
                break
            size /= 1024
        self.music_labels.append((f"Music Files: {size:.2f} {unit}", (music_x, MUSIC_SIZE_Y)))

        export_x = self.music_panel.right - FOOTER_BUTTON_SIZE[0]
        self.elements.append(Button(export_x - FOOTER_BUTTON_SIZE[0] - BUTTON_GAP, FOOTER_Y, FOOTER_BUTTON_SIZE, "light_blue", "Preview Game", self.preview))
        export_button = Button(export_x, FOOTER_Y, FOOTER_BUTTON_SIZE, "blue", "Export Game", self.export)
        # The web build cannot write a game folder for players to run.
        export_button.apply_state(enabled=not IS_WEB, color="blue")
        self.elements.append(export_button)

    def change_music(self, **changes):
        self.change_setting("music", dict(self.settings()["music"], **changes))

    def import_music_paths(self, paths, *, starting=False):
        if not queries.can_bulk_edit_map(self.map_screen):
            return
        music = self.settings()["music"]
        try:
            for path in paths:
                music = standalone_music.import_song(music, path, starting=starting)
            self.change_setting("music", music)
        except (OSError, ValueError) as error:
            dialogs.show_error("Standalone Music", str(error))

    def choose_starting_song(self):
        music = self.settings()["music"]
        if music["songs"]:
            def chosen(name):
                if name == "Import Song...":
                    self.import_starting_song()
                else:
                    self.change_music(starting_song=name)
            pickers.open_listbox_selector(self, "Starting Song", "Choose a song:", [song["name"] for song in music["songs"]] + ["Import Song..."], chosen)
        else:
            self.import_starting_song()

    def import_starting_song(self):
        pickers.open_file_browser(self, "Starting Song", downloads_dir(), extensions=list(standalone_music.SONG_EXTENSIONS), on_result=lambda path: self.import_music_paths([path], starting=True) if path else None)

    def choose_other_songs(self):
        pickers.open_file_browser(self, "Other Songs", downloads_dir(), mode="open_files", extensions=list(standalone_music.SONG_EXTENSIONS), on_result=lambda paths: self.import_music_paths(paths) if paths else None)

    def remove_music_song(self):
        music = self.settings()["music"]
        names = [song["name"] for song in music["songs"] if song["name"] != music["starting_song"]]
        pickers.open_listbox_selector(self, "Remove Song", "Choose a song:", names, lambda name: self.change_music(songs=[song for song in music["songs"] if song["name"] != name]))

    def choose_album_icon(self):
        def picked(path):
            if not path or not queries.can_bulk_edit_map(self.map_screen):
                return
            try:
                self.change_setting("music", standalone_music.import_icon(self.settings()["music"], path))
            except (OSError, ValueError, pygame.error) as error:
                dialogs.show_error("Standalone Music", str(error))
        pickers.open_file_browser(self, "Album icon.png", downloads_dir(), extensions=[".png"], on_result=picked)

    def choose_album_name(self):
        def chosen(name):
            if name is None:
                return
            try:
                name = queries.validated_scenario_name(name, label="Album Name")
                standalone_music.album_name(dict(self.settings()["music"], album_name=name), self.map_screen.editor_scenario_name)
                self.change_music(album_name=name)
            except ValueError as error:
                dialogs.show_error("Standalone Music", str(error))
        dialogs.ask_string("Album Name", "Album Name:", chosen, initial=self.settings()["music"]["album_name"], max_length=120, allow_empty=False)

    def toggle_base_album(self, album):
        included = list(self.settings()["music"]["base_albums"])
        if album in included:
            included.remove(album)
        elif album in self.base_album_inventory:
            included.append(album)
        self.change_music(base_albums=[name for name in c.UNDELETABLE_ALBUMS if name in included])

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
            for rect in (self.background_panel, self.country_panel, self.music_panel):
                draw_pixel_panel(surface, rect, PANEL_COLOR, PANEL_BORDER_COLOR, gradient_strength=0.25)
            draw_pixel_panel(surface, self.list_panel, LIST_COLOR, PANEL_BORDER_COLOR, gradient_strength=0.15)
            surface.blit(self.window_preview_surface, self.window_preview_rect)
            pygame.draw.rect(surface, SWATCH_BORDER_COLOR,
                             self.window_preview_rect.inflate(2 * WINDOW_PREVIEW_BORDER, 2 * WINDOW_PREVIEW_BORDER),
                             WINDOW_PREVIEW_BORDER)
        if self.music_icon_surface is not None:
            surface.blit(self.music_icon_surface, self.music_icon_rect)
        for rect, color in self.swatches:
            surface.fill(color, rect)
            pygame.draw.rect(surface, SWATCH_BORDER_COLOR, rect, 2)
        font = fonts.get("heading2")
        for text, position, *anchor in self.labels:
            rendered = font.render(text, True, TEXT_COLOR)
            surface.blit(rendered, rendered.get_rect(**{anchor[0] if anchor else "midtop": position}))
        if self.map_screen is None:
            return
        for text, position in self.music_labels:
            surface.blit(fonts.get("small").render(text, True, TEXT_COLOR), position)
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
        try:
            steps = standalone_game.export_steps(scenario_dir, name, self.settings())
        except (OSError, ValueError) as error:
            dialogs.show_error("Standalone Export", str(error))
            return
        destination = standalone_game.export_dir(name)
        if not os.path.exists(destination):
            self._run_export(steps)
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
            self._run_export(steps)

        dialogs.ask_yes_no("Standalone Export",
                           f"{os.path.abspath(destination)} already exists. Replace it? Saves inside it are deleted.",
                           on_answer)

    def _run_export(self, steps):
        screen_runner.run_loading(
            steps, "Exporting Standalone Game...",
            on_done=lambda path: self.map_screen.show_feedback(f"Exported standalone game to {path}"),
            on_error=lambda error: dialogs.show_error("Standalone Export", str(error)))


class Standalone_Menu_Preview(Screen):
    """Browse real standalone menu screens inside one preview navigation boundary."""
    PREVIEW_STATES = {"MENU", "COUNTRY_SELECT", "LOAD_GAME", "SETTINGS", "KEYBINDS", "MOUSE_SETTINGS", "MUSIC_PLAYER", "CREDITS"}

    def __init__(self, title, settings, controller=None, nation_data=None, entries=()):
        super().__init__()
        self.settings = queries.normalized_standalone_export_settings(settings)
        self.controller = controller
        self.scenario_name = title
        self.preview_music_directory = None
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
                self.open_music_preview()
                return
            elif state == "LOAD_GAME":
                screen = Load_Game(standalone=True, preview=True, standalone_settings=self.settings)
            elif state == "CREDITS":
                screen = Credits(standalone=True, standalone_settings=self.settings)
            self.screens[state] = screen
        self.current_screen.cancel_pointer_input()
        self.current_state = state
        self.current_screen = self.screens[state]
        self.current_screen.done, self.current_screen.next_state = False, None
        if state == "SETTINGS":
            self.current_screen.refresh_ui()

    def open_music_preview(self):
        music = self.settings["music"]
        albums = {name: list(self.controller.all_albums.get(name, ())) for name in music["base_albums"]}
        try:
            _copies, files = standalone_music.export_files(dict(music, base_albums=[]), self.scenario_name)
        except ValueError as error:
            dialogs.show_error("Standalone Music", str(error))
            return
        if not files:
            self.screens["MUSIC_PLAYER"] = Music_Player(self.controller, standalone=True, preview=True, preview_albums=albums)
            self.open_screen("MUSIC_PLAYER")
            return
        self.preview_music_directory = tempfile.TemporaryDirectory(prefix="gd5-music-preview-")
        root = self.preview_music_directory.name
        name = standalone_music.album_name(music, self.scenario_name)
        directory = os.path.join(root, c.MUSIC_DIR, name)

        def steps():
            for relative, data in files:
                yield f"Preparing {os.path.basename(relative)}..."
                path = os.path.join(root, relative)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "wb") as target:
                    target.write(data)
            albums[name] = [os.path.join(directory, song["name"]).replace("\\", "/") for song in music["songs"]]

        def prepared(_result):
            starting_song = os.path.join(directory, music["starting_song"]) if music["starting_song"] else None
            self.screens["MUSIC_PLAYER"] = Music_Player(self.controller, standalone=True, preview=True, preview_albums=albums, album_directories={name: directory}, preview_starting_song=starting_song)
            self.open_screen("MUSIC_PLAYER")

        def failed(error):
            self.preview_music_directory.cleanup()
            self.preview_music_directory = None
            dialogs.show_error("Standalone Music", str(error))

        screen_runner.run_loading(LoadingSteps(steps(), len(files)), "Preparing Music Preview...", on_done=prepared, on_error=failed)

    def exit_screen(self):
        if self.preview_music_directory is not None:
            root = self.preview_music_directory.name.replace("\\", "/") + "/"
            if self.controller.now_playing.replace("\\", "/").startswith(root):
                # Release the temporary playing file and continue the normal playlist before cleanup.
                if isinstance(self.controller.music, music_playback.PygamePlayback):
                    self.controller.music.stop()
                    pygame.mixer.music.unload()
                self.controller.play_random_song()
            self.preview_music_directory.cleanup()
            self.preview_music_directory = None
        super().exit_screen()

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
