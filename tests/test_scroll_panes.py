"""Unit tests for ui/widgets/scroll_panes.py.

Exercises the pane bookkeeping directly rather than through a screen: name
generation, row culling, the scroll limit, and wheel routing. Partially visible
rows stay interactive inside the pane; cropped parts cannot receive clicks.
"""

import unittest
from unittest import mock


import pygame

from ui.navigation.screen import Screen
from ui.widgets.scroll_panes import ScrollPanes

_REAL_GET_POS = pygame.mouse.get_pos


class TwoPaneScreen(ScrollPanes, Screen):
    ROW_HEIGHT = 20

    def __init__(self):
        super().__init__()
        self.left = pygame.Rect(0, 100, 200, 200)
        self.right = pygame.Rect(200, 100, 200, 200)

    def pane_rects(self):
        return {"left": self.left, "right": self.right}


def wheel(y):
    return pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=y, flipped=False,
                              precise_x=0.0, precise_y=float(y))


class ScrollAttrTests(unittest.TestCase):
    def setUp(self):
        pygame.init()
        self.screen = TwoPaneScreen()

    def test_a_pane_name_never_shadows_a_screen_method(self):
        handle_events = self.screen.handle_events
        self.screen.pane("events").value = -10
        self.assertEqual(self.screen.handle_events, handle_events)

    def test_panes_are_distinct(self):
        self.assertIsNot(self.screen.pane("left"), self.screen.pane("right"))
        self.assertIs(self.screen.pane("left"), self.screen.pane("left"))

    def test_cancel_releases_every_pane(self):
        for name in ("left", "right"):
            pane = self.screen.pane(name)
            pane.bar_drag, pane.content_drag = True, [0, True]
        self.screen.cancel_active_drags()
        for name in ("left", "right"):
            self.assertFalse(self.screen.pane(name).bar_drag)
            self.assertIsNone(self.screen.pane(name).content_drag)

    def test_dragging_the_handle_keeps_the_grab_point(self):
        pane = self.screen.pane("left")
        pane.limit, pane.value = -300, -100
        surface = pygame.Surface((200, 200))
        track, handle = pane.draw_scrollbar(surface, 0, 0, 100)
        grab = (handle.centerx, handle.bottom - 2)
        self.assertTrue(pane.press_scrollbar(grab))
        pane.snap(grab)
        # Rect coordinates are whole pixels, so the handle centre can round by one.
        self.assertAlmostEqual(pane.value, -100, delta=2)
        # A press on the bare track centres the handle on the pointer.
        self.assertTrue(pane.press_scrollbar((track.centerx, track.bottom - 1)))
        self.assertEqual(pane.value, pane.limit)

    def test_scroll_defaults_to_zero(self):
        self.assertEqual(self.screen.pane_scroll("left"), 0)
        self.assertEqual(self.screen.pane_scroll_limit("left"), 0)


class PaneRowTests(unittest.TestCase):
    def setUp(self):
        pygame.init()
        self.screen = TwoPaneScreen()

    def test_short_list_does_not_scroll(self):
        list(self.screen.pane_rows("left", 3, top=100, view_h=200))
        self.assertEqual(self.screen.pane_scroll_limit("left"), 0)

    def test_long_list_sets_a_negative_limit(self):
        list(self.screen.pane_rows("left", 50, top=100, view_h=200))
        self.assertLess(self.screen.pane_scroll_limit("left"), 0)

    def test_culls_rows_outside_the_pane(self):
        rows = list(self.screen.pane_rows("left", 100, top=100, view_h=200))
        self.assertLess(len(rows), 100)
        self.assertTrue(all(y < 100 + 200 for _i, y in rows))

    def test_scroll_limit_matches_the_clickable_boundary(self):
        """The final row remains reachable at the bottom of the scroll range."""
        top, view_h, row_h, count = 100, 200, 20, 40
        list(self.screen.pane_rows("left", count, top, view_h, row_h))

        self.screen.pane("left").value = self.screen.pane_scroll_limit("left")
        rows = list(self.screen.pane_rows("left", count, top, view_h, row_h))

        last_index, _last_y = rows[-1]
        self.assertEqual(last_index, count - 1, "the final row never becomes reachable")
        with mock.patch.object(pygame.mouse, "get_pos", return_value=(50, top + view_h - 1)):
            self.assertTrue(self.screen.pane("left").guard())

    def test_partially_visible_row_accepts_only_clicks_inside_the_pane(self):
        from ui.widgets.ui_elements import Button

        self.screen.pane("left").value = -5
        rows = dict(self.screen.pane_rows("left", 40, top=100, view_h=200))
        self.assertIn(10, rows)
        clicked = mock.Mock()
        row = self.screen.add_pane_row(
            "left", Button(0, rows[10], "list_row", "blue", "", clicked, sound_kind=None))
        for pos, expected_calls in (((50, 298), 1), ((50, 300), 1), ((50, 305), 1)):
            with mock.patch.object(pygame.mouse, "get_pos", return_value=pos):
                row.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=pos, button=1))
                row.handle_event(pygame.event.Event(pygame.MOUSEBUTTONUP, pos=pos, button=1))
            self.assertEqual(clicked.call_count, expected_calls)


class WheelRoutingTests(unittest.TestCase):
    def setUp(self):
        pygame.init()
        self.screen = TwoPaneScreen()
        for name in ("left", "right"):
            list(self.screen.pane_rows(name, 50, top=100, view_h=200))

    def _at(self, pos):
        """Pins the cursor. set_pos is a no-op under the dummy video driver, so
        the position has to be faked at the source the router reads."""
        pygame.mouse.get_pos = lambda: pos

    def tearDown(self):
        pygame.mouse.get_pos = _REAL_GET_POS

    def _scroll_at(self, pos):
        self._at(pos)
        self.screen.route_pane_scroll(wheel(-1))
        return self.screen.pane_scroll("left"), self.screen.pane_scroll("right")

    def test_wheel_scrolls_the_pane_under_the_cursor(self):
        left, right = self._scroll_at((50, 150))
        self.assertLess(left, 0)
        self.assertEqual(right, 0)

    def test_wheel_over_the_other_pane_scrolls_that_one(self):
        left, right = self._scroll_at((300, 150))
        self.assertEqual(left, 0)
        self.assertLess(right, 0)

    def test_wheel_outside_every_pane_scrolls_nothing(self):
        """Routing by rect, not by an x threshold: above the panes entirely,
        no pane should move. An x-based router would still pick one."""
        left, right = self._scroll_at((50, 10))
        self.assertEqual((left, right), (0, 0))

    def test_returns_whether_it_consumed_the_event(self):
        self._at((50, 150))
        self.assertTrue(self.screen.route_pane_scroll(wheel(-1)))
        self._at((50, 10))
        self.assertFalse(self.screen.route_pane_scroll(wheel(-1)))


class HorizontalPaneTests(unittest.TestCase):
    def setUp(self):
        pygame.init()
        self.screen = TwoPaneScreen()
        self.screen.pane_scroll_axis = lambda name: "x" if name == "left" else "y"
        self.screen.pane("left").limit = -300
        self.screen.pane("right").limit = -300
        self.screen.pane("left").content_rect = self.screen.left

    def test_horizontal_and_vertical_wheels_pan_only_the_horizontal_pane(self):
        with mock.patch.object(pygame.mouse, "get_pos", return_value=self.screen.left.center):
            for event in (wheel(-1), pygame.event.Event(pygame.MOUSEWHEEL, x=1, y=0)):
                previous = self.screen.pane_scroll("left")
                self.assertTrue(self.screen.route_pane_scroll(event))
                self.assertLess(self.screen.pane_scroll("left"), previous)
                self.assertEqual(self.screen.pane_scroll("right"), 0)

    def test_horizontal_scrollbar_reaches_both_ends(self):
        surface = pygame.Surface((400, 400))
        track, _handle = self.screen.draw_pane_scrollbar(surface, "left", 0, 285, 200)
        pos = (track.right - 1, track.centery)
        self.screen.route_pane_scroll(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=pos, button=1))
        self.screen.route_pane_scroll(pygame.event.Event(pygame.MOUSEBUTTONUP, pos=pos, button=1))
        self.assertEqual(self.screen.pane_scroll("left"), -300)
        track, handle = self.screen.draw_pane_scrollbar(surface, "left", 0, 285, 200)
        self.screen.route_pane_scroll(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=handle.center, button=1))
        self.screen.route_pane_scroll(pygame.event.Event(
            pygame.MOUSEMOTION, pos=(track.left, track.centery), rel=(-200, 0), buttons=(1, 0, 0)))
        self.screen.route_pane_scroll(pygame.event.Event(
            pygame.MOUSEBUTTONUP, pos=(track.left, track.centery), button=1))
        self.assertEqual(self.screen.pane_scroll("left"), 0)
        self.assertFalse(self.screen.pane("left").bar_drag)
        self.assertEqual(self.screen.pane_scroll("right"), 0)

    def test_horizontal_content_drag_follows_the_pointer(self):
        self.screen.pane("left").value = -150
        self.screen.route_pane_scroll(pygame.event.Event(
            pygame.MOUSEBUTTONDOWN, pos=(50, 150), button=1))
        self.screen.route_pane_scroll(pygame.event.Event(
            pygame.MOUSEMOTION, pos=(80, 150), rel=(30, 0), buttons=(1, 0, 0)))
        self.assertEqual(self.screen.pane_scroll("left"), -120)
        self.screen.route_pane_scroll(pygame.event.Event(
            pygame.MOUSEMOTION, pos=(60, 150), rel=(-20, 0), buttons=(1, 0, 0)))
        self.assertEqual(self.screen.pane_scroll("left"), -140)
        self.screen.route_pane_scroll(pygame.event.Event(
            pygame.MOUSEBUTTONUP, pos=(60, 150), button=1))


class AddPaneRowTests(unittest.TestCase):
    def setUp(self):
        pygame.init()
        self.screen = TwoPaneScreen()

    def test_tags_and_registers(self):
        class FakeButton:
            pass

        rows = list(self.screen.pane_rows("left", 5, top=100, view_h=200))
        self.assertTrue(rows)
        btn = self.screen.add_pane_row("left", FakeButton())
        self.assertEqual(btn.pane, "left")
        self.assertTrue(btn.is_scrollable)
        self.assertIn(btn, self.screen.elements)
        self.assertTrue(callable(btn.click_guard))


if __name__ == "__main__":
    unittest.main()
