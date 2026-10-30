"""Check scrollbar input geometry and reuse of shaded presentation data."""

import unittest
from unittest.mock import patch

import pygame

from ui.bars import ui_bars
from ui.widgets import ui_elements


class ScrollbarRenderingTests(unittest.TestCase):
    def setUp(self):
        self.surface = pygame.Surface((400, 400))
        ui_elements._button_background.cache_clear()
        self.addCleanup(ui_elements._button_background.cache_clear)
        mouse = patch.object(pygame.mouse, "get_pos", return_value=(399, 399))
        mouse.start()
        self.addCleanup(mouse.stop)

    def test_vertical_drawing_uses_input_geometry(self):
        for value in (0, -50, -200):
            with self.subTest(value=value):
                expected = ui_bars.get_standard_scrollbar_rects(value, -200, 20, 20, 200)
                actual = ui_bars.draw_standard_scrollbar(self.surface, value, -200, 20, 20, 200)
                self.assertEqual(actual, expected)
                track, handle = actual
                snapped = ui_bars.calculate_scroll_snap(handle.centery, -200, track.y, track.height)
                self.assertAlmostEqual(snapped, value, delta=2)

    def test_horizontal_endpoints_match_dragging(self):
        for value in (-100, 100):
            track, handle = ui_bars.draw_standard_scrollbar_horizontal(
                self.surface, value, -100, 100, 20, 20, 200)
            snapped = ui_bars.calculate_scroll_snap_horizontal(
                handle.centerx, -100, 100, track.x, track.width)
            self.assertAlmostEqual(snapped, value, delta=2)

    def test_fitting_content_has_no_scrollbar(self):
        self.assertEqual(ui_bars.draw_standard_scrollbar(self.surface, 0, 0, 20, 20, 200),
                         (None, None))
        self.assertEqual(ui_bars.draw_standard_scrollbar_horizontal(
            self.surface, 0, 0, 0, 20, 20, 200), (None, None))
        self.assertEqual(ui_elements._button_background.cache_info().misses, 0)

    def test_scrolling_reuses_shaded_surfaces(self):
        ui_bars.draw_standard_scrollbar(self.surface, 0, -200, 20, 20, 200)
        ui_bars.draw_standard_scrollbar_horizontal(self.surface, 0, 0, 200, 20, 20, 200)
        with patch.object(ui_elements.queries, "lerp_color") as interpolate:
            ui_bars.draw_standard_scrollbar(self.surface, -50, -200, 30, 20, 200)
            ui_bars.draw_standard_scrollbar_horizontal(self.surface, 50, 0, 200, 20, 30, 200)
        interpolate.assert_not_called()

if __name__ == "__main__":
    unittest.main()
