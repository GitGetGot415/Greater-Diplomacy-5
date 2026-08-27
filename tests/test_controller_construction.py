"""Guards the frozen application surface: state keys, screen constructors, and
the GameState virtual protocol.

Every screen class name, constructor arity and state-machine string key is
effectively public API -- main.py hardcodes them, and a mod that replaces a
screen module has to keep providing the same class under the same name. Nothing
checked any of that before this file existed.
"""

import unittest
from unittest import mock

import pygame

from tests import app_harness

# The state-machine keys main.py's flip_state() dispatches on. Hardcoded here
# rather than read back from Controller so that deleting one fails the test.
EXPECTED_STATES = {
    "MENU", "NEW_GAME", "RANDOM_SETUP", "LOAD_GAME", "SETTINGS", "UNIT_ART", "CREDITS",
    "MUSIC_PLAYER", "VIEW_ASSETS", "MODS", "SELECT_BASE_MAP", "MAP",
    "PRODUCTION", "ORDERS", "RESEARCH", "ECONOMY", "EDIT_COUNTRY", "MESSAGES",
    "FACTION", "FACTION_TERRITORIES", "SCENARIO_SETTINGS", "MULTIPLAYER_HUB",
    "MULTIPLAYER_HOST", "MULTIPLAYER_JOIN", "MULTIPLAYER_NEW", "TRANSLATE",
    "KEYBINDS",
}

# GameState's virtual methods. Screens override these; mods rely on them.
# draw_content is deliberately absent: it belongs to MapOverlayScreen, not to
# every screen.
PROTOCOL = (
    "handle_events", "additional_events", "update", "draw", "draw_background",
    "draw_title", "draw_elements", "draw_feedback", "additional_draw",
    "go_to", "exit_screen", "handle_back_key", "get_title", "refresh_ui",
)


class ControllerConstructionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.controller, cls.surface = app_harness.boot()

    def test_state_keys_are_exactly_as_expected(self):
        self.assertEqual(set(self.controller.states), EXPECTED_STATES)

    def test_every_state_but_map_is_constructed(self):
        missing = [name for name, screen in self.controller.states.items()
                   if screen is None and name != "MAP"]
        self.assertEqual(missing, [], "states failed to construct")

    def test_map_is_built_lazily(self):
        """MAP is intentionally None until a scenario is chosen; if that ever
        changes, flip_state()'s Map-construction branch needs revisiting.

        Read off what boot() recorded rather than off the live controller: it is
        cached per interpreter, and any earlier test file that called boot_map()
        will have filled MAP in by the time this runs.
        """
        self.assertIn("MAP", app_harness.STATES_UNBUILT_AT_BOOT)

    def test_screens_expose_the_gamestate_protocol(self):
        missing = []
        for name, screen in app_harness.screens(self.controller):
            for method in PROTOCOL:
                if not callable(getattr(screen, method, None)):
                    missing.append(f"{name}.{method}")
        self.assertEqual(missing, [])

    def test_screens_start_not_done(self):
        for name, screen in app_harness.screens(self.controller):
            with self.subTest(state=name):
                self.assertFalse(screen.done, f"{name} was already done on construction")

    def test_active_state_is_the_menu(self):
        self.assertIs(self.controller.active_state, self.controller.states["MENU"])

    def test_clear_orders_keybind_is_available_by_default(self):
        from screens.menu_screens.keybinds import KEYBIND_ACTIONS

        defaults = {action: default for action, _label, default in KEYBIND_ACTIONS}
        self.assertEqual(defaults["CLEAR_ORDERS"], pygame.K_DELETE)
        self.assertIn("CLEAR_ORDERS", self.controller.keybinds)


class GlobalKeyDispatchTests(unittest.TestCase):
    class State:
        listening_for = None

        def __init__(self):
            self.cleared = 0

        def handle_back_key(self):
            pass

        def handle_clear_orders_key(self):
            self.cleared += 1

    def test_clear_orders_key_routes_to_optional_screen_handler(self):
        from gameState import dispatch_global_keys

        state = self.State()
        event = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_DELETE)
        with mock.patch("gameState.queries.get_keybind",
                        side_effect=lambda _action, default: default):
            dispatch_global_keys(state, event)

        self.assertEqual(state.cleared, 1)

    def test_clear_orders_key_honours_rebinding(self):
        from gameState import dispatch_global_keys

        state = self.State()
        event = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_x)

        def binding(action, default):
            return pygame.K_x if action == "CLEAR_ORDERS" else default

        with mock.patch("gameState.queries.get_keybind", side_effect=binding):
            dispatch_global_keys(state, event)

        self.assertEqual(state.cleared, 1)


if __name__ == "__main__":
    unittest.main()
