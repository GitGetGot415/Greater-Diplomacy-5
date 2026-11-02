from ui.navigation.screen import ButtonMenuScreen
from ui.widgets import ui_elements

from data.platform import IS_WEB


class Multiplayer_Menu(ButtonMenuScreen):
    """Choose between the available multiplayer modes."""

    back_state = "MENU"
    title = "Multiplayer"
    bg_color = (80, 0, 0)

    def menu_buttons(self):
        return [
            ("Asynchronous (Tournaments)", "green", lambda: self.go_to("MULTIPLAYER_HUB"), ui_elements.UI_ICONS.get("mail")),
            ("Real Time", "blue", lambda: self.go_to("REAL_TIME_MULTIPLAYER"), ui_elements.UI_ICONS.get("clock")),
        ]


class Real_Time_Multiplayer(ButtonMenuScreen):
    """Desktop authoritative real-time multiplayer entry point."""

    back_state = "MULTIPLAYER_MENU"
    title = "Real Time Multiplayer"
    bg_color = (10, 10, 40)
    caption = ("Desktop-only: host directly over LAN or a forwarded WAN port."
               if not IS_WEB else "Real-time multiplayer is available in desktop builds only.")

    def menu_buttons(self):
        return [
            ("Host Match", "green", lambda: self.go_to("REALTIME_HOST_SETUP")),
            ("Join Match", "blue", lambda: self.go_to("REALTIME_JOIN")),
        ]
