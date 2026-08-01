from gameState import GameState
from ui_elements import Button
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
            Button(20, 20, "small", "red", "Back", self.exit_screen)
        ]



    def start_new(self):
        self.go_to("MULTIPLAYER_NEW")

    def load_existing(self):
        from tkinter import filedialog
        from ui import confirm_dialog

        root = queries.get_transient_tk_root()

        file_path = filedialog.askopenfilename(
            initialdir=c.TOURNAMENT_SAVES_DIR,
            title="Select Tournament File",
            filetypes=[("Tournament Files", "*.gd5tour")],
            parent=root
        )
        queries.destroy_tk_root(root)

        key = confirm_dialog.ask_string("Master Key", "Enter your Master Key:") if file_path else None

        if not file_path or not key:
            return

        self.selected_tournament_path = file_path
        self.selected_tournament_key = key
        self.go_to("MAP")
