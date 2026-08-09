from gameState import GameState
from ui_elements import Button, make_back_button
import data.constants as c
from data import queries

class Multiplayer_Host(GameState):
    back_state = "MULTIPLAYER_HUB"

    title = "Host Dashboard"
    title_y = 100
    title_shadow = True

    def __init__(self):
        super().__init__()
        self.bg_color = (10, 10, 40)
        self.elements = [
            Button("centered", "centered - 50", "medium", "green", "Start New Multiplayer Game", self.start_new),
            Button("centered", "centered + 50", "medium", "green", "Load Existing Tournament", self.load_existing),
            make_back_button(self.exit_screen)
        ]



    def start_new(self):
        self.go_to("MULTIPLAYER_NEW")

    def load_existing(self):
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

            confirm_dialog.ask_string("Master Key", "Enter your Master Key:", after_key)

        queries.open_file_browser(self, "Select Tournament File", c.TOURNAMENT_SAVES_DIR,
                                  extensions=[".gd5tour"], on_result=after_file)
