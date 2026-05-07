import ui_elements
from gameState import GameState
from ui_elements import Button
import data.constants as c

class Menu(GameState):
    def __init__(self):
        super().__init__()
        self.bg_color = (10, 10, 40) # Midnight Blue
        self.bg_image_path = c.MENU_BG_FILE 

        self.elements = [
            Button("centered", "centered - 100", "medium", "green", "New Game", self.new_game),
            Button("centered", "centered - 20", "medium", "green", "Load Game", self.load_game),
            Button("centered", "centered + 60", "medium", "green", "Map Editor", self.map_editor),
            Button("centered", "centered + 140", "medium", "blue", "Music Player", self.music_player), # <--- NEW
            Button("centered", "centered + 220", "medium", "grey", "Settings", self.settings, image=ui_elements.UI_ICONS.get("settings"))
        ]

    def new_game(self):
        self.next_state = "NEW_GAME"
        self.done = True

    def load_game(self):
        self.next_state = "LOAD_GAME"
        self.done = True

    def music_player(self):
        self.next_state = "MUSIC_PLAYER"
        self.done = True

    def settings(self):
        self.next_state = "SETTINGS"
        self.done = True

    def map_editor(self):
        self.next_state = "SELECT_BASE_MAP"
        self.done = True