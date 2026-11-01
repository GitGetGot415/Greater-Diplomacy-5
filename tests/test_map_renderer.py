"""Map and hover surfaces reuse their caches until invalidation."""

from types import SimpleNamespace
import unittest
from unittest.mock import patch

import pygame

from ui.rendering import hover_renderer, map_renderer
from ui.bars import ui_bars
import data.constants as c
from tests.stub_map_screen import map_double


class CheckerboardAnimationTests(unittest.TestCase):
    def test_speed_changes_and_pause_keep_the_current_phase(self):
        with patch.object(ui_bars, "_checkerboard_scroll_clock", None), \
                patch.object(c, "CHECKERBOARD_SCROLL_SPEED", 10), \
                patch.object(pygame.time, "get_ticks", return_value=1000) as ticks:
            self.assertEqual(ui_bars.checkerboard_scroll_offset(), 10)
            ticks.return_value = 2000
            self.assertEqual(ui_bars.checkerboard_scroll_offset(), 20)
            c.CHECKERBOARD_SCROLL_SPEED = 20
            self.assertEqual(ui_bars.checkerboard_scroll_offset(), 20)
            ticks.return_value = 2500
            self.assertEqual(ui_bars.checkerboard_scroll_offset(), 30)
            c.CHECKERBOARD_SCROLL_SPEED = 0
            self.assertEqual(ui_bars.checkerboard_scroll_offset(), 30)
            ticks.return_value = 3000
            self.assertEqual(ui_bars.checkerboard_scroll_offset(), 30)


class NonLoopingMapRendererTests(unittest.TestCase):
    def test_hover_glow_scale_reuses_unchanged_sticker(self):
        map_screen = map_double(
            hover_glow_surf=pygame.Surface((10, 10), pygame.SRCALPHA))

        with patch.object(hover_renderer.pygame.transform, "scale",
                          wraps=pygame.transform.scale) as scale:
            first = hover_renderer._scaled_hover_glow(map_screen, (20, 20))
            second = hover_renderer._scaled_hover_glow(map_screen, (20, 20))

        self.assertIs(first, second)
        self.assertEqual(scale.call_count, 1)

    def test_viewport_scale_reuses_unchanged_source_region(self):
        source = pygame.Surface((20, 20))
        map_screen = map_double()
        rect = pygame.Rect(2, 3, 10, 8)

        with patch.object(map_renderer.pygame.transform, "scale",
                          wraps=pygame.transform.scale) as scale:
            first = map_renderer._scaled_map_region(map_screen, source, rect, (30, 24))
            second = map_renderer._scaled_map_region(map_screen, source, rect, (30, 24))

        self.assertIs(first, second)
        self.assertEqual(scale.call_count, 1)

        map_renderer.clear_viewport_scale_cache(map_screen)
        third = map_renderer._scaled_map_region(map_screen, source, rect, (30, 24))
        self.assertIsNot(first, third)

if __name__ == "__main__":
    unittest.main()
