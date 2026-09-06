from gameState import GameState
from ui_elements import Button, make_back_button
from map_logic.rendering.font_manager import fonts
import data.constants as c


class Translation_Menu(GameState):
    """Choose which game's map format should be used for translation."""

    back_state = "MENU"
    title = "TRANSLATE MAPS"

    def __init__(self):
        super().__init__()
        self.bg_color = (20, 45, 55)
        self.elements = [
            make_back_button(self.exit_screen),
            Button(260, 180, "large", "green", "Open Doctrines",
                   lambda: self.go_to("TRANSLATE")),
            Button(260, 300, "large", "light_blue", "Greater Diplomacy 4",
                   lambda: self.go_to("TRANSLATE_GD4")),
        ]

    def additional_draw(self, surface):
        text = "Choose the map format you want to translate."
        font = fonts.get("normal")
        text_surface = font.render(text, True, (220, 220, 220))
        surface.blit(text_surface, text_surface.get_rect(midtop=(c.SCREEN_WIDTH // 2, 130)))


class Greater_Diplomacy_4_Translation(GameState):
    """Placeholder for the future Greater Diplomacy 4 translator."""

    back_state = "TRANSLATION_MENU"
    title = "GREATER DIPLOMACY 4 TRANSLATION"

    def __init__(self):
        super().__init__()
        self.bg_color = (35, 35, 55)
        self.elements = [make_back_button(self.exit_screen)]

    def additional_draw(self, surface):
        message = fonts.get("heading2").render("Soon", True, (220, 220, 220))
        surface.blit(message, message.get_rect(center=(c.SCREEN_WIDTH // 2, 250)))

        detail = fonts.get("normal").render(
            "Greater Diplomacy 4 translation soon",
            True,
            (180, 180, 190),
        )
        surface.blit(detail, detail.get_rect(center=(c.SCREEN_WIDTH // 2, 300)))
