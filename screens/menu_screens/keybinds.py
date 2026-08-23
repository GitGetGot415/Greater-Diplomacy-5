import pygame
from gameState import GameState
from ui_elements import Button, make_back_button
import data.constants as c
from data import queries

# --- Keybinds screen layout ---
KEYBINDS_ROW_X = c.SCREEN_WIDTH // 2 - 100
KEYBINDS_ROW_START_Y = 150
KEYBINDS_ROW_GAP_Y = 70

# (action, label, default key) -- every rebindable global action, in the
# order they're listed on this screen.
KEYBIND_ACTIONS = (
    ("FULLSCREEN", "Fullscreen", pygame.K_F11),
    ("BACK", "Back", pygame.K_ESCAPE),
    ("ORDERS", "Orders", pygame.K_q),
    ("ECONOMY", "Economy", pygame.K_w),
)


class Keybinds(GameState):
    """Settings sub-screen: every rebindable key, moved out of Settings itself
    so that screen doesn't have to grow a row per action."""

    back_state = "SETTINGS"
    title = "Keybinds"

    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.bg_color = (40, 40, 40)
        self.listening_for = None
        self.refresh_ui()

    def start_listening(self, action):
        self.listening_for = action
        self.refresh_ui()

    def refresh_ui(self):
        self.elements = [make_back_button(self.exit_screen)]

        y = KEYBINDS_ROW_START_Y
        for action, label, default_key in KEYBIND_ACTIONS:
            if self.listening_for == action:
                text = "Press any key..."
            else:
                key_name = pygame.key.name(self.controller.keybinds.get(action, default_key)).upper()
                text = f"{label} Key: {key_name}"
            self.elements.append(
                Button(KEYBINDS_ROW_X, y, "medium", "grey", text, lambda a=action: self.start_listening(a))
            )
            y += KEYBINDS_ROW_GAP_Y

    def additional_events(self, event):
        if self.listening_for and event.type == pygame.KEYDOWN:
            self.controller.keybinds[self.listening_for] = event.key
            queries.save_global_settings(self.controller)
            self.listening_for = None
            self.refresh_ui()

    def handle_back_key(self):
        # Ignore Escape while a key is being rebound; it belongs to the capture.
        if not self.listening_for:
            self.exit_screen()
