from gameState import GameState
from ui_elements import Button

class Menu(GameState):
    def __init__(self):
        super().__init__()
        self.bg_color = (10, 10, 40) # Midnight Blue
        
        # Just fill the list; the Parent handles the rest
        self.elements = [
            Button("centered", "centered - 80", "medium", "green", "New Game", self.new_game),
            Button("centered", "centered", "medium", "green", "Load Game", self.load_game),
            Button("centered", "centered + 80", "medium", "green", "Map Editor", self.map_editor),
            Button("centered", "centered + 160", "medium", "grey", "Settings", self.settings)
        ]

    def new_game(self):
        self.next_state = "NEW_GAME"
        self.done = True

    def load_game(self):
        self.next_state = "LOAD_GAME"
        self.done = True

    def settings(self):
        self.next_state = "SETTINGS"
        self.done = True

    def map_editor(self):
        self.next_state = "MAP"
        self.done = True