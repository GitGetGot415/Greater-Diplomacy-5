from ui.navigation.game_state import GameState
import data.constants as c
from ui.dialogs import pickers

from ui import dialogs


class TournamentPickerScreen(GameState):
    """Open a tournament file after the player gives its key."""

    back_state = "MULTIPLAYER_HUB"

    title_y = 100
    title_shadow = True

    def __init__(self):
        super().__init__()
        self.bg_color = (10, 10, 40)

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
