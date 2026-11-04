import pygame
from ui.navigation.screen import Screen
from ui.widgets.ui_elements import Button, make_back_button, make_info_button
import data.constants as c
from data import queries
from data.io import keybind_io, settings_schema
# Preserve the screen import used by startup and older callers.
from data.io.keybind_io import default_keybinds
from ui import dialogs
from ui.widgets import text_utils
from ui.rendering.font_manager import fonts

# --- Keybinds screen layout ---
KEYBINDS_RESET_X = c.SCREEN_WIDTH // 2 - 100
# Keep the Back and Reset controls in their established positions while
# centering the three-column binding group more comfortably on the screen.
KEYBINDS_BINDING_COLUMNS_SHIFT_X = 100
KEYBINDS_ROW_X = KEYBINDS_RESET_X + KEYBINDS_BINDING_COLUMNS_SHIFT_X
KEYBINDS_NAVIGATION_COLUMN_X = KEYBINDS_ROW_X - c.SIZES["medium"][0] - 60
KEYBINDS_MOUSE_COLUMN_X = KEYBINDS_NAVIGATION_COLUMN_X - c.SIZES["medium"][0] - 60
KEYBINDS_ROW_START_Y = 150
KEYBINDS_ROW_GAP_Y = 70
KEYBINDS_RESET_GAP_Y = 30
KEYBINDS_COLUMN_HEADING_Y = KEYBINDS_ROW_START_Y - 35
KEYBINDS_WARNING_TOP_Y = 600
KEYBINDS_WARNING_SIDE_MARGIN = 55
# Each binding gets an adjacent clear button. The compact two-line
# Orders/Production toggle leaves room for it without moving the columns.
KEYBINDS_REMOVE_GAP_X = 5
KEYBINDS_REMOVE_SIZE = (30, 30)
KEYBINDS_REMOVE_Y_NUDGE = (c.SIZES["medium"][1] - KEYBINDS_REMOVE_SIZE[1]) // 2
KEYBINDS_TOGGLE_GAP_X = 10
KEYBINDS_TOGGLE_SIZE = (150, 50)
KEYBINDS_TOGGLE_X = (KEYBINDS_ROW_X + c.SIZES["medium"][0]
                     + KEYBINDS_REMOVE_GAP_X + KEYBINDS_REMOVE_SIZE[0]
                     + KEYBINDS_TOGGLE_GAP_X)
KEYBINDS_TOGGLE_INFO_X = KEYBINDS_TOGGLE_X + KEYBINDS_TOGGLE_SIZE[0] + KEYBINDS_TOGGLE_GAP_X
KEYBINDS_INFO_Y_NUDGE = (KEYBINDS_TOGGLE_SIZE[1] - c.SIZES["scenario_setting_info"][1]) // 2

TOGGLE_INFO_TEXT = (
    "When on, pressing this key also jumps straight to the screen its view "
    "mode implies -- Orders (or Battle, if the tile is fighting) for the "
    "Orders key, Production for the Production key -- instead of only "
    "switching the map's view mode. Works independently of the Map "
    "Navigation setting (Classic/Preemptive) in Settings: it jumps whenever "
    "this is on, in either mode, and never jumps when it's off."
)

# (action, label) in screen order. Bindings belong to starting_defaults.json.
KEYBIND_ACTIONS = (
    ("FULLSCREEN", "Fullscreen"),
    ("BACK", "Back"),
    ("ORDERS", "Orders"),
    ("ECONOMY", "Production"),
    ("CLEAR_ORDERS", "Clear Orders"),
)

# Map-camera bindings get their own left column: they are all related and
# keeping them beside each other makes a remapped directional layout legible.
MAP_PANNING_KEYBIND_ACTIONS = (
    ("PAN_LEFT", "Pan Left"),
    ("PAN_RIGHT", "Pan Right"),
    ("PAN_UP", "Pan Up"),
    ("PAN_DOWN", "Pan Down"),
)

# Keyboard mouse clicks sit to the left of map panning.
MOUSE_CLICK_KEYBIND_ACTIONS = (
    ("MOUSE_LEFT_CLICK", "Left Click"),
    ("MOUSE_MIDDLE_CLICK", "Middle Click"),
    ("MOUSE_RIGHT_CLICK", "Right Click"),
)

ALL_KEYBIND_ACTIONS = (MOUSE_CLICK_KEYBIND_ACTIONS
                       + MAP_PANNING_KEYBIND_ACTIONS + KEYBIND_ACTIONS)


def keybind_conflicts(keybinds):
    """Return every shared key and its user-facing actions, without rejecting it."""
    by_key = {}
    defaults = default_keybinds()
    for action, label in ALL_KEYBIND_ACTIONS:
        key = keybinds.get(action, defaults[action])
        if key is not None:
            by_key.setdefault(key, []).append(label)
    return [(key, labels) for key, labels in by_key.items() if len(labels) > 1]

#: Actions that carry the "change screen with this keybind" toggle -- the two
#: that also switch the map's view mode, and so have a screen the keybind
#: could jump straight into. Back/Fullscreen don't have one.
SCREEN_TOGGLE_ACTIONS = ("ORDERS", "ECONOMY")


class Keybinds(Screen):
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

        self._add_binding_column(MOUSE_CLICK_KEYBIND_ACTIONS,
                                 KEYBINDS_MOUSE_COLUMN_X)
        self._add_binding_column(MAP_PANNING_KEYBIND_ACTIONS,
                                 KEYBINDS_NAVIGATION_COLUMN_X)

        y = KEYBINDS_ROW_START_Y
        for action, label in KEYBIND_ACTIONS:
            self._add_binding_button(action, label, KEYBINDS_ROW_X, y)

            if action in SCREEN_TOGGLE_ACTIONS:
                on = getattr(self.controller, self.screen_toggle_attr(action))
                self.elements.append(
                    Button(KEYBINDS_TOGGLE_X, y, KEYBINDS_TOGGLE_SIZE, "green" if on else "red",
                          "Change Screen\nWith This Keybind",
                          lambda a=action: self.toggle_screen_change(a),
                          font_preset="tiny")
                )
                self.elements.append(
                    make_info_button(
                        KEYBINDS_TOGGLE_INFO_X, y,
                        lambda: dialogs.show_info("Change Screen With This Keybind", TOGGLE_INFO_TEXT),
                        y_offset=KEYBINDS_INFO_Y_NUDGE)
                )

            y += KEYBINDS_ROW_GAP_Y

        self.elements.append(
            Button(KEYBINDS_RESET_X, y + KEYBINDS_RESET_GAP_Y, "medium", "red", "Reset Keybinds", self.reset_defaults)
        )

    def _add_binding_column(self, actions, x):
        """Build one vertical keybind column from the canonical action list."""
        y = KEYBINDS_ROW_START_Y
        for action, label in actions:
            self._add_binding_button(action, label, x, y)
            y += KEYBINDS_ROW_GAP_Y

    def _add_binding_button(self, action, label, x, y):
        """Build a button that either shows or captures one binding."""
        if self.listening_for == action:
            text = "Press any key..."
        else:
            key = self.controller.keybinds.get(action, keybind_io.default_keybind(action))
            key_name = pygame.key.name(key).upper() if key is not None else "UNASSIGNED"
            text = f"{label} Key: {key_name}"
        self.elements.append(
            Button(x, y, "medium", "grey", text,
                   lambda a=action: self.start_listening(a))
        )
        self.elements.append(
            Button(x + c.SIZES["medium"][0] + KEYBINDS_REMOVE_GAP_X,
                   y + KEYBINDS_REMOVE_Y_NUDGE, KEYBINDS_REMOVE_SIZE, "red", "x",
                   lambda a=action: self.remove_binding(a), font_preset="tiny")
        )

    def remove_binding(self, action):
        """Persist an explicitly unassigned key without affecting other bindings."""
        self.controller.keybinds[action] = None
        self.listening_for = None
        queries.save_global_settings(self.controller)
        self.refresh_ui()

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
        self.controller.keybinds = default_keybinds()
        defaults = settings_schema.defaults()
        for action in SCREEN_TOGGLE_ACTIONS:
            attr = self.screen_toggle_attr(action)
            setattr(self.controller, attr, defaults[attr])
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
            self.go_back()

    def additional_draw(self, surface):
        """Label the columns and expose non-blocking duplicate-key warnings."""
        font = fonts.get("small")
        for x, heading in ((KEYBINDS_MOUSE_COLUMN_X, "Mouse Clicks"),
                           (KEYBINDS_NAVIGATION_COLUMN_X, "Map Panning"),
                           (KEYBINDS_ROW_X, "Other Keybinds")):
            label = font.render(heading, True, c.UI_TEXT_DIM)
            surface.blit(label, label.get_rect(
                center=(x + c.SIZES["medium"][0] // 2, KEYBINDS_COLUMN_HEADING_Y)))

        conflicts = keybind_conflicts(self.controller.keybinds)
        if not conflicts:
            return
        warning_font = fonts.get("tiny")
        heading = font.render("Keybind warning", True, (255, 195, 85))
        surface.blit(heading, (KEYBINDS_WARNING_SIDE_MARGIN, KEYBINDS_WARNING_TOP_Y))
        y = KEYBINDS_WARNING_TOP_Y + heading.get_height() + 3
        max_width = c.SCREEN_WIDTH - (2 * KEYBINDS_WARNING_SIDE_MARGIN)
        for key, labels in conflicts:
            message = (f"{pygame.key.name(key).upper()} is assigned to "
                       f"{', '.join(labels)}. Both actions may trigger together.")
            for line in text_utils.wrap_text(message, warning_font, max_width):
                text = warning_font.render(line, True, (255, 220, 155))
                surface.blit(text, (KEYBINDS_WARNING_SIDE_MARGIN, y))
                y += text.get_height() + 2
