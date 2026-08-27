import pygame
from gameState import GameState
from ui_elements import Button, make_back_button
import data.constants as c
from data import queries
from screens.menu_screens.settings import info_button

# --- Keybinds screen layout ---
KEYBINDS_ROW_X = c.SCREEN_WIDTH // 2 - 100
KEYBINDS_ROW_START_Y = 150
KEYBINDS_ROW_GAP_Y = 70
KEYBINDS_RESET_GAP_Y = 30
# The "change screen with this keybind" toggle sits directly right of the
# keybind button, on the same row -- the keybind button itself stays exactly
# where it already was. The info button sits right of that toggle in turn.
KEYBINDS_TOGGLE_GAP_X = 10
KEYBINDS_TOGGLE_X = KEYBINDS_ROW_X + c.SIZES["medium"][0] + KEYBINDS_TOGGLE_GAP_X
KEYBINDS_TOGGLE_INFO_X = KEYBINDS_TOGGLE_X + c.SIZES["keybind_toggle"][0] + KEYBINDS_TOGGLE_GAP_X

TOGGLE_INFO_TEXT = (
    "When on, pressing this key also jumps straight to the screen its view "
    "mode implies -- Orders (or Battle, if the tile is fighting) for the "
    "Orders key, Production for the Production key -- instead of only "
    "switching the map's view mode. Works independently of the Map "
    "Navigation setting (Classic/Preemptive) in Settings: it jumps whenever "
    "this is on, in either mode, and never jumps when it's off."
)

# (action, label, default key) -- every rebindable keyboard action, in the
# order they're listed on this screen.
KEYBIND_ACTIONS = (
    ("FULLSCREEN", "Fullscreen", pygame.K_F11),
    ("BACK", "Back", pygame.K_ESCAPE),
    ("ORDERS", "Orders", pygame.K_q),
    ("ECONOMY", "Production", pygame.K_w),
    ("CLEAR_ORDERS", "Clear Orders", pygame.K_DELETE),
)

#: Actions that carry the "change screen with this keybind" toggle -- the two
#: that also switch the map's view mode, and so have a screen the keybind
#: could jump straight into. Back/Fullscreen don't have one.
SCREEN_TOGGLE_ACTIONS = ("ORDERS", "ECONOMY")


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

            if action in SCREEN_TOGGLE_ACTIONS:
                on = getattr(self.controller, self.screen_toggle_attr(action))
                self.elements.append(
                    Button(KEYBINDS_TOGGLE_X, y, "keybind_toggle", "green" if on else "red",
                          "Change Screen With This Keybind",
                          lambda a=action: self.toggle_screen_change(a),
                          font_preset="tiny")
                )
                self.elements.append(
                    info_button(KEYBINDS_TOGGLE_INFO_X, y, "Change Screen With This Keybind",
                               TOGGLE_INFO_TEXT)
                )

            y += KEYBINDS_ROW_GAP_Y

        self.elements.append(
            Button(KEYBINDS_ROW_X, y + KEYBINDS_RESET_GAP_Y, "medium", "red", "Reset Keybinds", self.reset_defaults)
        )

    def screen_toggle_attr(self, action):
        """Controller attribute backing `action`'s "change screen with this
        keybind" toggle -- see data.io.settings_schema."""
        return f"{action.lower()}_key_changes_screen"

    def toggle_screen_change(self, action):
        attr = self.screen_toggle_attr(action)
        setattr(self.controller, attr, not getattr(self.controller, attr))
        queries.save_global_settings(self.controller)
        self.refresh_ui()

    def reset_defaults(self):
        self.controller.keybinds = {action: default for action, _label, default in KEYBIND_ACTIONS}
        for action in SCREEN_TOGGLE_ACTIONS:
            setattr(self.controller, self.screen_toggle_attr(action), True)
        queries.save_global_settings(self.controller)
        self.refresh_ui()

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
