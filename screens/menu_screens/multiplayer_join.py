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
        from ui import confirm_dialog

        def after_file(file_path):
            if not file_path:
                return

            def after_key(key):
                if not key:
                    return
                self.selected_tournament_path = file_path
                self.selected_tournament_key = key
                self.go_to("MAP")

            confirm_dialog.ask_string("Player Key", "Enter your Country Key:", after_key)

        queries.open_file_browser(self, "Select Tournament File", c.TOURNAMENT_SAVES_DIR,
                                  extensions=[".gd5tour"], on_result=after_file)
