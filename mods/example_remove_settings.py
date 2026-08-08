#screens/menu_screens/settings.py
from gameState import GameState
from ui_elements import Button

class Settings(GameState):
    back_state = "MENU"

    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.bg_color = (64, 64, 64)

        self.elements = [
            Button(20, 20, "small", "grey", "Back", self.exit_screen),
        ]