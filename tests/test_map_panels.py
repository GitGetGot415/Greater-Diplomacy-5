"""Covers the three panels layered over the map: Buildings/Garrison, Diplomatic
Info and the production queue overlay.

Each publishes a rect and a scroll ceiling under its own attribute prefix, and
ui/event_handler.py gives all three identical treatment -- block map clicks
underneath, take the wheel, and be draggable. That used to be nine copy-pasted
blocks; these tests pin the behaviour the table-driven version has to keep.
"""

import unittest

import pygame

from tests import app_harness
from ui import event_handler


def wheel(y, pos):
    pygame.mouse.get_pos = lambda: pos
    return pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=y, flipped=False,
                              precise_x=0.0, precise_y=float(y))


class MapPanelScrollTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.controller, cls.surface = app_harness.boot()
        cls.map = app_harness.boot_map()
        cls.real_get_pos = pygame.mouse.get_pos

    def setUp(self):
        # The panels only exist with a province selected outside selection mode,
        # which is the state the map starts a scenario in.
        self.map.selection_mode = False
        self.map.refresh_ui()
        self.map.draw(self.surface)

    def tearDown(self):
        pygame.mouse.get_pos = self.real_get_pos

    def test_all_three_panels_publish_a_rect(self):
        for name in event_handler.MAP_PANELS:
            with self.subTest(panel=name):
                self.assertIsNotNone(event_handler._panel_rect(self.map, name),
                                     f"{name} panel published no rect")

    def test_panels_are_only_live_with_a_selection(self):
        self.assertTrue(event_handler._panels_are_live(self.map))
        self.map.selection_mode = True
        self.assertFalse(event_handler._panels_are_live(self.map))
        self.map.selection_mode = False

    def test_wheel_over_a_panel_scrolls_it_and_not_the_others(self):
        for name in event_handler.MAP_PANELS:
            with self.subTest(panel=name):
                rect = event_handler._panel_rect(self.map, name)
                # Give the panel something to scroll; the ceiling is normally
                # set from the content height while drawing.
                for other in event_handler.MAP_PANELS:
                    setattr(self.map, f"{other}_scroll_y", 0)
                    setattr(self.map, f"{other}_scroll_max", 500)

                event_handler.handle_map_events(self.map, wheel(-1, rect.center))

                self.assertGreater(getattr(self.map, f"{name}_scroll_y"), 0,
                                   f"{name} did not scroll")
                for other in event_handler.MAP_PANELS:
                    if other != name:
                        self.assertEqual(getattr(self.map, f"{other}_scroll_y"), 0,
                                         f"{other} scrolled when {name} was under the cursor")

    def test_scroll_is_clamped_to_the_ceiling(self):
        name = event_handler.MAP_PANELS[0]
        rect = event_handler._panel_rect(self.map, name)
        setattr(self.map, f"{name}_scroll_y", 0)
        setattr(self.map, f"{name}_scroll_max", 40)

        for _ in range(20):
            event_handler.handle_map_events(self.map, wheel(-1, rect.center))
        self.assertEqual(getattr(self.map, f"{name}_scroll_y"), 40)

        for _ in range(20):
            event_handler.handle_map_events(self.map, wheel(1, rect.center))
        self.assertEqual(getattr(self.map, f"{name}_scroll_y"), 0)

    def test_wheel_off_every_panel_does_not_scroll_them(self):
        for name in event_handler.MAP_PANELS:
            setattr(self.map, f"{name}_scroll_y", 0)
            setattr(self.map, f"{name}_scroll_max", 500)

        # Bottom-left corner, clear of all three published rects.
        away = (2, 2)
        self.assertFalse(any(r.collidepoint(away)
                             for r in (event_handler._panel_rect(self.map, n)
                                       for n in event_handler.MAP_PANELS)))
        event_handler.handle_map_events(self.map, wheel(-1, away))

        for name in event_handler.MAP_PANELS:
            self.assertEqual(getattr(self.map, f"{name}_scroll_y"), 0)

    def test_a_panel_blocks_clicks_reaching_the_map(self):
        """Hovering a panel must set on_ui, or a click passes through to the
        province underneath it."""
        rect = event_handler._panel_rect(self.map, event_handler.MAP_PANELS[0])
        pygame.mouse.get_pos = lambda: rect.center
        before = self.map.hovered_province
        event_handler.handle_map_events(
            self.map, pygame.event.Event(pygame.MOUSEMOTION, pos=rect.center,
                                         rel=(1, 1), buttons=(0, 0, 0)))
        self.assertIsNone(self.map.hovered_province,
                          f"hover reached the map through a panel (was {before})")



class ExitConfirmationTests(unittest.TestCase):
    """The quit-to-menu dialog is drawn by map_logic/rendering/map_renderer.py
    and clicked in ui/event_handler.py. Its button geometry used to be written
    out in both, in two different coordinate frames, agreeing only by accident
    of the box's height."""

    @classmethod
    def setUpClass(cls):
        cls.controller, cls.surface = app_harness.boot()
        cls.map = app_harness.boot_map()
        cls.real_get_pos = pygame.mouse.get_pos

    def setUp(self):
        self.map.show_exit_confirmation = True
        self.map.draw(self.surface)

    def tearDown(self):
        pygame.mouse.get_pos = self.real_get_pos
        self.map.show_exit_confirmation = False

    def press(self, pos):
        pygame.mouse.get_pos = lambda: pos
        event_handler.handle_map_events(
            self.map, pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=pos, button=1))

    def test_drawing_publishes_both_button_rects(self):
        self.assertIsNotNone(getattr(self.map, "exit_yes_rect", None))
        self.assertIsNotNone(getattr(self.map, "exit_no_rect", None))

    def test_clicking_anywhere_in_the_drawn_stay_button_cancels(self):
        """Every corner of the painted button has to answer, which is exactly
        what the two-coordinate-frame version could not guarantee."""
        rect = self.map.exit_no_rect
        for pos in (rect.center, (rect.left + 1, rect.top + 1), (rect.right - 1, rect.top + 1),
                    (rect.left + 1, rect.bottom - 1), (rect.right - 1, rect.bottom - 1)):
            with self.subTest(pos=pos):
                self.map.show_exit_confirmation = True
                self.press(pos)
                self.assertFalse(self.map.show_exit_confirmation,
                                 f"click at {pos} missed the drawn STAY button")

    def test_clicking_outside_both_buttons_does_nothing(self):
        self.press((self.map.exit_no_rect.right + 40, self.map.exit_no_rect.centery))
        self.assertTrue(self.map.show_exit_confirmation)

if __name__ == "__main__":
    unittest.main()
