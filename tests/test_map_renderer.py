"""Map and hover surfaces reuse their caches until invalidation."""

from types import SimpleNamespace
import unittest
from unittest.mock import patch

import pygame

from map_logic.rendering import hover_renderer, map_renderer


class NonLoopingMapRendererTests(unittest.TestCase):
    def test_hover_glow_scale_reuses_unchanged_sticker(self):
        map_screen = SimpleNamespace(
            hover_glow_surf=pygame.Surface((10, 10), pygame.SRCALPHA))

        with patch.object(hover_renderer.pygame.transform, "scale",
                          wraps=pygame.transform.scale) as scale:
            first = hover_renderer._scaled_hover_glow(map_screen, (20, 20))
            second = hover_renderer._scaled_hover_glow(map_screen, (20, 20))

        self.assertIs(first, second)
        self.assertEqual(scale.call_count, 1)

    def test_viewport_scale_reuses_unchanged_source_region(self):
        source = pygame.Surface((20, 20))
        map_screen = SimpleNamespace()
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
