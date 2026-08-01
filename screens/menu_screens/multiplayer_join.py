from gameState import GameState
from ui_elements import Button
import data.constants as c
from data import queries

class Multiplayer_Join(GameState):
    back_state = "MULTIPLAYER_HUB"

    title = "Join Game"
    title_y = 100
    title_shadow = True

    def __init__(self):
        super().__init__()
        self.bg_color = (10, 10, 40)
        self.elements = [
            Button("centered", "centered", "medium", "blue", "Load Tournament File", self.load_tour_file),
            Button(20, 20, "small", "red", "Back", self.exit_screen)
        ]

    def load_tour_file(self):
        queries.open_file_browser(self, "Select Tournament File", c.TOURNAMENT_SAVES_DIR,
                                  self._on_tournament_file_picked, mode="open_file", extensions=[".gd5tour"])

    def _on_tournament_file_picked(self, file_path):
        from ui import confirm_dialog
        key = confirm_dialog.ask_string("Player Key", "Enter your Country Key:")
        if not key:
            return

        self.selected_tournament_path = file_path
        self.selected_tournament_key = key
        self.go_to("MAP")
