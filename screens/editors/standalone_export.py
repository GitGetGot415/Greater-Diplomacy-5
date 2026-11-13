"""Separate screen that sets up and exports the edited scenario as a standalone game."""
import os

import data.constants as c
from data import queries
from data.io import standalone_game
from data.map import save_map
from data.platform import IS_WEB
from ui import dialogs
from ui.navigation import screen_runner
from ui.navigation.screen import Screen
from ui.widgets.ui_elements import Button, make_back_button

# Gap between the bottom of the screen and the Export button.
EXPORT_BUTTON_BOTTOM_MARGIN = 40


class Standalone_Export_Screen(Screen):
    """Export options for a standalone game. Back returns to the map editor."""
    back_state = "MAP"
    title = "STANDALONE EXPORT"

    def on_enter(self, app, previous):
        self.map_screen = app.states["MAP"]
        self.refresh_ui()

    def refresh_ui(self):
        export_height = c.SIZES["large"][1]
        export_button = Button("centered", c.SCREEN_HEIGHT - EXPORT_BUTTON_BOTTOM_MARGIN - export_height,
                               "large", "blue", "Export", self.export)
        # The web build cannot write a game folder for players to run.
        export_button.apply_state(enabled=not IS_WEB, color="blue")
        self.elements = [make_back_button(self.exit_screen), export_button]

    def export(self):
        """Export the saved copy of this scenario as a standalone game in exports/<scenario name>/."""
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
            standalone_game.export_steps(scenario_dir, name), "Exporting Standalone Game...",
            on_done=lambda path: self.map_screen.show_feedback(f"Exported standalone game to {path}"),
            on_error=lambda error: dialogs.show_error("Standalone Export", str(error)))
