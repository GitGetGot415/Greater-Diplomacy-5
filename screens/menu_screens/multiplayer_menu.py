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
        self.bg_color = (80, 0, 0)
        self.elements = [
            Button("centered", 220, "large", "green", "Asynchronous (Tournaments)",
                   lambda: self.go_to("MULTIPLAYER_HUB")),
            Button("centered", 330, "large", "blue", "Real Time",
                   lambda: self.go_to("REAL_TIME_MULTIPLAYER")),
            make_back_button(self.exit_screen),
        ]


class Real_Time_Multiplayer(GameState):
    """Desktop authoritative real-time multiplayer entry point."""

    back_state = "MULTIPLAYER_MENU"
    title = "Real Time Multiplayer"
    title_y = 100
    title_shadow = True

    def __init__(self):
        super().__init__()
        self.bg_color = (10, 10, 40)
        self.elements = [
            Button("centered", 260, "large", "green", "Host Match",
                   lambda: self.go_to("REALTIME_HOST_SETUP")),
            Button("centered", 370, "large", "blue", "Join Match",
                   lambda: self.go_to("REALTIME_JOIN")),
            make_back_button(self.exit_screen),
        ]

    def additional_draw(self, surface):
        from data.platform import IS_WEB
        text = ("Desktop-only: host directly over LAN or a forwarded WAN port."
                if not IS_WEB else "Real-time multiplayer is available in desktop builds only.")
        font = fonts.get("normal")
        text_surface = font.render(text, True, (220, 220, 220))
        surface.blit(text_surface, text_surface.get_rect(midtop=(c.SCREEN_WIDTH // 2, 220)))
