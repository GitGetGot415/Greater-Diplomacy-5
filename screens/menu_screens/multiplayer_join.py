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
        from tkinter import filedialog, simpledialog

        root = queries.get_transient_tk_root()

        file_path = filedialog.askopenfilename(
            initialdir=c.TOURNAMENT_SAVES_DIR,
            title="Select Tournament File",
            filetypes=[("Tournament Files", "*.gd5tour")],
            parent=root
        )
        key = simpledialog.askstring("Player Key", "Enter your Country Key:", parent=root) if file_path else None
        queries.destroy_tk_root(root)

        if not file_path or not key:
            return

        self.selected_tournament_path = file_path
        self.selected_tournament_key = key
        self.go_to("MAP")
