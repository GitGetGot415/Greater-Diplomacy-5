from ui.navigation.screen import ButtonMenuScreen
from screens.game import map_launch
import data.constants as c
from ui.dialogs import pickers

from ui import dialogs


class TournamentPickerScreen(ButtonMenuScreen):
    """Open a tournament file after the player gives its key."""

    back_state = "MULTIPLAYER_HUB"
    bg_color = (10, 10, 40)

    def pick_tournament(self, key_title, key_prompt):

        def after_file(file_path):
            if not file_path:
                return

            def after_key(key):
                if not key:
                    return
                self.selected_tournament_path = file_path
                self.selected_tournament_key = key
                self.go_to("MAP")

            dialogs.ask_string(key_title, key_prompt, after_key)

        pickers.open_file_browser(self, "Select Tournament File", c.TOURNAMENT_SAVES_DIR,
                                  extensions=[".gd5tour"], on_result=after_file)

    def prepare_map(self, app):
        return map_launch.open_tournament_map(app, self)

    def prepare_map_steps(self, app):
        return map_launch.open_tournament_map_steps(app, self)
