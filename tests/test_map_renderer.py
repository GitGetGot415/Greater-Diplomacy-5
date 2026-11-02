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
    def test_cached_scrolling_buffers_do_not_inherit_native_display_alpha(self):
        surface_type = pygame.Surface

        def native_surface(size, flags=0, depth=0):
            # Model a native window whose default format includes pixel alpha.
            if not flags and not depth:
                return surface_type(size, pygame.SRCALPHA)
            return surface_type(size, flags, depth)

        for cache in (ui_bars.checkerboard_canvas, ui_bars._checkerboard_blend_buffers):
            cache.cache_clear()
            self.addCleanup(cache.cache_clear)
        with patch.object(pygame, "Surface", side_effect=native_surface):
            canvas = ui_bars.checkerboard_canvas((40, 30))
            buffers = ui_bars._checkerboard_blend_buffers((40, 30))
            self.assertIs(ui_bars.checkerboard_canvas((40, 30)), canvas)
            self.assertIs(ui_bars._checkerboard_blend_buffers((40, 30)), buffers)
        for surface in (canvas, *buffers):
            self.assertEqual(surface.get_masks()[3], 0)

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
