import os
import sys
import unittest
from unittest import mock

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame

import data.constants as c
from screens.menu_screens.mouse_settings import (
    MOUSE_ACTION_BUTTON_SIZE, MOUSE_EXCLUDE_BUTTON_SIZE, MOUSE_PAN_BUTTON_SIZE,
    Mouse_Settings, mouse_control_warnings,
)
from ui import event_handler


class MouseSettingsTests(unittest.TestCase):
    def setUp(self):
        pygame.init()
        self.original_actions = c.MOUSE_BUTTON_ACTIONS
        self.addCleanup(setattr, c, "MOUSE_BUTTON_ACTIONS", self.original_actions)

    def test_shipped_actions_match_the_navigation_tutorial(self):
        actions = c.default_mouse_button_actions()
        self.assertTrue(actions["left"]["select_units"])
        self.assertTrue(actions["left"]["box_select_units"])
        self.assertTrue(actions["middle"]["pan_map"])
        self.assertTrue(actions["right"]["pan_map"])
        self.assertTrue(actions["right"]["exclude_orders"])
        self.assertTrue(actions["right"]["issue_orders"])
        self.assertEqual(mouse_control_warnings(actions), [])

    def test_same_button_box_selection_and_panning_warns_without_disabling_it(self):
        actions = c.default_mouse_button_actions()
        actions["left"]["pan_map"] = True
        warnings = mouse_control_warnings(actions)
        self.assertEqual(len(warnings), 1)
        self.assertTrue(actions["left"]["box_select_units"])
        self.assertTrue(actions["left"]["pan_map"])

    def test_exclude_orders_square_is_disabled_until_map_panning_is_enabled(self):
        controller = type("Controller", (), {
            "mouse_button_actions": c.default_mouse_button_actions(),
        })()
        screen = Mouse_Settings(controller)
        left_exclude = next(element for element in screen.elements
                            if element.text == "" and element.callback is not None)
        self.assertTrue(left_exclude.disabled)

        with mock.patch("screens.menu_screens.mouse_settings.queries.save_global_settings"):
            screen.toggle_action("left", "pan_map")
        left_exclude = next(element for element in screen.elements
                            if element.text == "" and element.callback is not None)
        self.assertFalse(left_exclude.disabled)

    def test_compact_pan_and_exclude_controls_stay_inside_the_action_button_bounds(self):
        controller = type("Controller", (), {
            "mouse_button_actions": c.default_mouse_button_actions(),
        })()
        screen = Mouse_Settings(controller)
        card = screen._card_rect(0)
        action_left = card.centerx - MOUSE_ACTION_BUTTON_SIZE[0] // 2
        action_right = action_left + MOUSE_ACTION_BUTTON_SIZE[0]
        pan = next(element for element in screen.elements
                   if element.text.startswith("Pan the map"))
        exclude = next(element for element in screen.elements
                       if element.text == "" and element.callback is not None)

        self.assertEqual(pan.rect.size, MOUSE_PAN_BUTTON_SIZE)
        self.assertEqual(exclude.rect.size, MOUSE_EXCLUDE_BUTTON_SIZE)
        self.assertGreaterEqual(pan.rect.left, action_left)
        self.assertLessEqual(exclude.rect.right, action_right)

    def test_toggle_updates_controller_runtime_actions_and_persists(self):
        controller = type("Controller", (), {
            "mouse_button_actions": c.default_mouse_button_actions(),
        })()
        screen = Mouse_Settings(controller)
        with mock.patch("screens.menu_screens.mouse_settings.queries.save_global_settings") as save:
            screen.toggle_action("middle", "issue_orders")

        self.assertTrue(controller.mouse_button_actions["middle"]["issue_orders"])
        self.assertTrue(c.MOUSE_BUTTON_ACTIONS["middle"]["issue_orders"])
        save.assert_called_once_with(controller)
        self.assertEqual(len(screen.elements), 17)  # Back, four rows, an exclude square per mouse button, and reset.

    def test_reset_defaults_restores_and_persists_the_tutorial_layout(self):
        actions = c.default_mouse_button_actions()
        actions["left"]["pan_map"] = True
        actions["middle"]["issue_orders"] = True
        controller = type("Controller", (), {"mouse_button_actions": actions})()
        screen = Mouse_Settings(controller)

        with mock.patch("screens.menu_screens.mouse_settings.queries.save_global_settings") as save:
            screen.reset_defaults()

        self.assertEqual(controller.mouse_button_actions, c.default_mouse_button_actions())
        self.assertEqual(c.MOUSE_BUTTON_ACTIONS, c.default_mouse_button_actions())
        save.assert_called_once_with(controller)

    def test_runtime_lookup_uses_the_custom_assignment(self):
        actions = c.default_mouse_button_actions()
        actions["middle"]["issue_orders"] = True
        c.apply_runtime_settings({"mouse_button_actions": actions})
        self.assertTrue(event_handler.mouse_button_has_action(2, "issue_orders"))
        self.assertIn(2, event_handler.mouse_buttons_with_actions("pan_map"))


if __name__ == "__main__":
    unittest.main()
