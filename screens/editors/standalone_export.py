"""Separate screen that sets up and exports the edited scenario as a standalone game."""
import os

import pygame

import data.constants as c
from data import queries
from data.io import standalone_game
from data.map import save_map
from data.platform import IS_WEB, downloads_dir
from screens.menus.menu import Menu
from ui import dialogs
from ui.dialogs import pickers
from ui.navigation import screen_runner
from ui.navigation.screen import Screen
from ui.rendering.font_manager import fonts
from ui.widgets.ui_elements import Button, make_back_button

# --- Layout. CONTENT_TOP moves every setting row together. ---
CONTENT_TOP = 130
ROW_GAP = 50
BUTTON_GAP = 10
SETTING_BUTTON_SIZE = (140, 36)
SWATCH_SIZE = (36, 36)
TEXT_COLOR = (230, 230, 230)
SWATCH_BORDER_COLOR = (255, 255, 255)
# Gap between the bottom of the screen and the Export button.
EXPORT_BUTTON_BOTTOM_MARGIN = 40
# Gap between the screen edges and the preview's Close Preview button.
PREVIEW_CLOSE_MARGIN = 20


class Standalone_Export_Screen(Screen):
    """Export settings for a standalone game. Back returns to the map editor."""
    back_state = "MAP"
    title = "STANDALONE EXPORT"

    def on_enter(self, app, previous):
        self.map_screen = app.states["MAP"]
        self.refresh_ui()

    def settings(self):
        return queries.normalized_standalone_export_settings(self.map_screen.standalone_export_settings)

    def refresh_ui(self):
        self.elements = [make_back_button(self.exit_screen)]
        self.swatches = []
        self.labels = []
        if self.map_screen is None:
            return
        settings = self.settings()
        editable = queries.can_bulk_edit_map(self.map_screen)
        width, height = SETTING_BUTTON_SIZE
        center_x = c.SCREEN_WIDTH // 2
        # Every row starts at the left edge of the two-button image row.
        left_x = center_x - (2 * width + BUTTON_GAP) // 2

        def setting_button(x, y, color, label, callback, enabled=True):
            button = Button(x, y, SETTING_BUTTON_SIZE, color, label, callback)
            button.fit_text = True
            button.apply_state(enabled=editable and enabled, color=color)
            self.elements.append(button)

        self.labels.append(("Menu Background", (center_x, CONTENT_TOP)))
        color_y = CONTENT_TOP + 30
        setting_button(left_x, color_y, "blue", "Background Color", self.choose_color)
        self.swatches.append((pygame.Rect((left_x + width + BUTTON_GAP, color_y), SWATCH_SIZE),
                              settings["background_color"]))

        image_y = color_y + ROW_GAP
        setting_button(left_x, image_y, "blue", "Choose Image", self.choose_image)
        setting_button(left_x + width + BUTTON_GAP, image_y, "red", "Clear Image",
                       lambda: self.change_setting("background_image", ""),
                       enabled=bool(settings["background_image"]))
        image_text_x = left_x + 2 * (width + BUTTON_GAP)
        self.labels.append((self.image_size_text(settings), (image_text_x, image_y + height // 2), "midleft"))

        preview = Button("centered", image_y + ROW_GAP + 20, "medium", "light_blue", "Preview Menu", self.preview)
        self.elements.append(preview)

        export_height = c.SIZES["large"][1]
        export_button = Button("centered", c.SCREEN_HEIGHT - EXPORT_BUTTON_BOTTOM_MARGIN - export_height,
                               "large", "blue", "Export", self.export)
        # The web build cannot write a game folder for players to run.
        export_button.apply_state(enabled=not IS_WEB, color="blue")
        self.elements.append(export_button)

    @staticmethod
    def image_size_text(settings):
        """Name the chosen image's size, or say that none is chosen."""
        if not settings["background_image"]:
            return "No image"
        try:
            image = queries.load_png_b64(settings["background_image"])
        except (ValueError, pygame.error):
            return "Unreadable image"
        return f"{image.get_width()} x {image.get_height()}"

    def additional_draw(self, surface):
        for rect, color in self.swatches:
            surface.fill(color, rect)
            pygame.draw.rect(surface, SWATCH_BORDER_COLOR, rect, 2)
        font = fonts.get("heading2")
        for text, position, *anchor in self.labels:
            rendered = font.render(text, True, TEXT_COLOR)
            surface.blit(rendered, rendered.get_rect(**{anchor[0] if anchor else "midtop": position}))

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

    def preview(self):
        """Show the standalone game's main menu with the current settings."""
        screen_runner.run_screen(Standalone_Menu_Preview(self.map_screen.editor_scenario_name, self.settings()))

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
        close_height = c.SIZES["small"][1]
        close = make_back_button(self.exit_screen, label="Close Preview",
                                 pos=(PREVIEW_CLOSE_MARGIN, c.SCREEN_HEIGHT - PREVIEW_CLOSE_MARGIN - close_height))
        close.fit_text = True
        self.elements = [close]

    def update(self):
        self.menu.update()

    def draw(self, surface):
        self.menu.draw(surface)
        self.draw_elements(surface)
