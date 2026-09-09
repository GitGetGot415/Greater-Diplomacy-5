from gameState import GameState
from ui_elements import Button, make_back_button
from map_logic.rendering.font_manager import fonts
import data.constants as c


class Multiplayer_Menu(GameState):
    """Choose between the available multiplayer modes."""

    back_state = "MENU"
    title = "Multiplayer"
    title_y = 100
    title_shadow = True

    def __init__(self):
        super().__init__()
        self.bg_color = (10, 10, 40)
        self.elements = [
            Button("centered", 220, "large", "green", "Asynchronous (Tournaments)",
                   lambda: self.go_to("MULTIPLAYER_HUB")),
            Button("centered", 330, "large", "blue", "Real Time",
                   lambda: self.go_to("REAL_TIME_MULTIPLAYER")),
            make_back_button(self.exit_screen),
        ]


class Real_Time_Multiplayer(GameState):
    """Placeholder for the future real-time multiplayer mode."""

    back_state = "MULTIPLAYER_MENU"
    title = "Real Time Multiplayer"
    title_y = 100
    title_shadow = True

    def __init__(self):
        super().__init__()
        self.bg_color = (10, 10, 40)
        self.elements = [make_back_button(self.exit_screen)]

    def additional_draw(self, surface):
        text = "Real-time multiplayer soon!"
        font = fonts.get("normal")
        text_surface = font.render(text, True, (220, 220, 220))
        surface.blit(text_surface, text_surface.get_rect(midtop=(c.SCREEN_WIDTH // 2, 220)))
