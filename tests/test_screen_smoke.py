"""Builds and paints every screen once.

This is the regression net for the chrome/scroll/dialog consolidation: a shared
helper that gets a rect, an attribute name or a draw order wrong shows up here
as an exception rather than as a blank panel someone stumbles into later.

It asserts nothing about what the pixels look like -- that stays a manual check.
What it does assert is that refresh_ui() and a full draw() pass complete, which
is exactly the code path the helpers are being pulled out of.
"""

import unittest

import pygame

from tests import app_harness


class ScreenSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.controller, cls.surface = app_harness.boot()
        # Loads a real scenario and performs every map-layered screen's handoff,
        # so Production/Orders/Economy/Messages are reachable here too.
        cls.map = app_harness.boot_map()

    def setUp(self):
        self.surface.fill((0, 0, 0))

    def all_screens(self):
        return app_harness.screens(self.controller)

    def test_refresh_ui_then_draw(self):
        for name, screen in self.all_screens():
            with self.subTest(state=name):
                screen.refresh_ui()
                screen.draw(self.surface)

    def test_update_is_safe_to_call(self):
        for name, screen in self.all_screens():
            with self.subTest(state=name):
                screen.update()

    def test_survives_an_idle_event_pump(self):
        """A mouse move and a wheel notch over each screen -- the two events the
        scroll helpers key off. Neither should ever raise, whatever the screen's
        scroll state happens to be."""
        events = [
            pygame.event.Event(pygame.MOUSEMOTION, pos=(400, 300), rel=(1, 1), buttons=(0, 0, 0)),
            pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=-1, flipped=False, precise_x=0.0,
                               precise_y=-1.0),
            pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=1, flipped=False, precise_x=0.0,
                               precise_y=1.0),
        ]
        for name, screen in self.all_screens():
            with self.subTest(state=name):
                screen.handle_events(events)
                screen.draw(self.surface)

    def test_titles_render(self):
        for name, screen in self.all_screens():
            with self.subTest(state=name):
                title = screen.get_title()
                self.assertTrue(title is None or isinstance(title, str))


if __name__ == "__main__":
    unittest.main()
