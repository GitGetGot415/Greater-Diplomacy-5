#screens/menu_screens/view_assets.py
from gameState import GameState
from ui_elements import Button

class View_Assets(GameState):
    back_state = "MENU"

    def __init__(self):
        super().__init__()
        self.bg_color = (64, 64, 64)

        self.elements = [
            Button(20, 20, "small", "grey", "Back", self.exit_screen),
        ]