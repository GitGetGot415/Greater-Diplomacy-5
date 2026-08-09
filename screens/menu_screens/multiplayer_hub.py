from gameState import GameState
from ui_elements import Button, make_back_button
import data.constants as c
from data import queries

class Multiplayer_Hub(GameState):
    back_state = "MENU"

    title = "Asynchronous Multiplayer"
    title_y = 100
    title_shadow = True

    def __init__(self):
        super().__init__()
        self.bg_color = (10, 10, 40)
        self.elements = [
            Button("centered", 250, "medium", "green", "Host Game", self.host_game),
            Button("centered", 350, "medium", "blue", "Join Game", self.join_game),
            make_back_button(self.exit_screen),
            Button(c.SCREEN_WIDTH - 120, 20, "small", "blue", "Help", self.show_help)
        ]

    def show_help(self):
        from ui import confirm_dialog
        help_text = (
            "Tournaments allow for asynchronous multiplayer gameplay.\n\n"
            "Host: Create a new tournament, distribute the generated .gd5tour file and the player keys to your friends. "
            "When they send back their .gd5move files, load the tournament and load their moves in the Manage Players panel. "
            "Then process the turn and send the updated .gd5tour file back to them.\n\n"
            "Player: Use 'Join Game' to load the .gd5tour file using your player key. "
            "Submit your orders and click 'Export Turn' to generate a .gd5move file, and send it to the host."
        )
        confirm_dialog.show_info("Tournament Help", help_text)

    def host_game(self):
        self.go_to("MULTIPLAYER_HOST")

    def join_game(self):
        self.go_to("MULTIPLAYER_JOIN")
