import ui_elements
from gameState import GameState
from ui_elements import Button
import data.constants as c
from map_logic.rendering.font_manager import fonts

class Menu(GameState):
    def __init__(self):
        super().__init__()
        self.bg_color = (10, 10, 40) # Midnight Blue
        self.bg_image_path = c.MENU_BG_FILE 

        self.elements = [
            Button("centered", "centered - 100", "medium", "green", "New Game", self.new_game),
            Button("centered", "centered - 20", "medium", "green", "Load Game", self.load_game),
            Button("centered", "centered + 60", "medium", "green", "Map Editor", self.map_editor),
            Button("centered", "centered + 140", "medium", "blue", "Music Player", self.music_player, image=ui_elements.UI_ICONS.get("music")),
            Button("centered", "centered + 220", "medium", "grey", "Settings", self.settings, image=ui_elements.UI_ICONS.get("settings"))
        ]

    def additional_draw(self, surface):
        font = fonts.get("heading2")
        display_str = f"{c.MENU_BOTTOM_LEFT_TEXT}"
        
        # Shadow
        shadow = font.render(display_str, True, (0, 0, 0))
        surface.blit(shadow, (21, c.SCREEN_HEIGHT - 39))
        
        # Main text
        text_surf = font.render(display_str, True, (255, 255, 255))
        surface.blit(text_surf, (20, c.SCREEN_HEIGHT - 40))

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