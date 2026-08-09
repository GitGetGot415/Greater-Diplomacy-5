"""Unit tests for ui/scroll_panes.py.

Exercises the pane bookkeeping directly rather than through a screen: name
generation, row culling, the scroll limit, and wheel routing. The two settled
divergences (pane_rows not forwarding view_h, and the wheel routing by rect
rather than by an x threshold) each get a test that would fail if reverted.
"""

import os
import sys
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame

from gameState import GameState
from ui.scroll_panes import ScrollPanes

_REAL_GET_POS = pygame.mouse.get_pos


class TwoPaneScreen(ScrollPanes, GameState):
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

    def test_names_are_underscore_prefixed(self):
        """A pane called "events" must not publish self.handle_events and
        clobber GameState.handle_events."""
        attrs = self.screen.scroll_attrs("events")
        self.assertTrue(all(name.startswith("_") for name in attrs.values()))
        self.assertNotIn("handle_events", attrs.values())

    def test_names_are_distinct_per_pane(self):
        left = set(self.screen.scroll_attrs("left").values())
        right = set(self.screen.scroll_attrs("right").values())
        self.assertEqual(left & right, set())

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
        """The whole reason pane_rows withholds view_h from layout_list_rows.

        Scrolled fully to the bottom, the final row must be inside the same
        band that gates clicks -- if the limit were computed against the taller
        view_h, the last row would stop a sliver short of being reachable.
        """
        top, view_h, row_h, count = 100, 200, 20, 40
        list(self.screen.pane_rows("left", count, top, view_h, row_h))

        self.screen._scroll_left = self.screen.pane_scroll_limit("left")
        rows = list(self.screen.pane_rows("left", count, top, view_h, row_h))

        cull_bottom = top + view_h - row_h + 2
        last_index, last_y = rows[-1]
        self.assertEqual(last_index, count - 1, "the final row never becomes reachable")
        self.assertLessEqual(last_y + row_h, cull_bottom + row_h)
        self.assertGreaterEqual(last_y + row_h, cull_bottom - 1,
                                "the final row stops short of the clickable boundary")


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
