from ui.navigation.game_state import ButtonMenuScreen
from ui.widgets.ui_elements import Button
import data.constants as c
from data import queries

from ui import dialogs
class Multiplayer_Hub(ButtonMenuScreen):
    back_state = "MULTIPLAYER_MENU"

    title = "Asynchronous Multiplayer"
    bg_color = (10, 10, 40)

    def menu_buttons(self):
        return [
            ("Host Game", "green", self.host_game),
            ("Join Game", "blue", self.join_game),
        ]

    def refresh_ui(self):
        super().refresh_ui()
        self.elements.append(Button(c.SCREEN_WIDTH - 120, 20, "small", "blue", "Help", self.show_help))

    def show_help(self):
        help_text = (
            "Tournaments allow for asynchronous multiplayer gameplay.\n\n"
            "Host: Create a new tournament, distribute the generated .gd5tour file and the player keys to your friends. "
            "When they send back their .gd5move files, load the tournament and load their moves in the Manage Players panel. "
            "Then process the turn and send the updated .gd5tour file back to them.\n\n"
            "Player: Use 'Join Game' to load the .gd5tour file using your player key. "
            "Submit your orders and click 'Export Turn' to generate a .gd5move file, and send it to the host.\n\n"
            "Tournament Spectator: Use 'Join Game' and enter 'Spectator' as the key. "
            "This read-only view has no territory or vision, so it follows the tournament's Lite, Normal, or Extreme fog setting."
        )
        dialogs.show_info("Tournament Help", help_text)

    def host_game(self):
        self.go_to("MULTIPLAYER_HOST")

    def join_game(self):
        self.go_to("MULTIPLAYER_JOIN")
