"""Base-map placement at the bounded edges of non-looping maps."""

from types import SimpleNamespace
import unittest
from unittest.mock import patch

import pygame

from map_logic.camera.camera_handler import MapCamera
from map_logic.rendering import hover_renderer, map_renderer
from screens.menu_screens.map import Map


class NonLoopingMapRendererTests(unittest.TestCase):
    def test_editor_refresh_queue_coalesces_a_brush_stroke(self):
        map_screen = SimpleNamespace(
            _editor_visual_refresh_layers=set())
        # A lightweight stand-in keeps this focused on the map screen's
        # editor boundary rather than requiring a loaded scenario.
        invalidations = []
        refreshes = []
        map_screen.invalidate_map_presentation_cache = lambda: invalidations.append(True)
        map_screen.refresh_map_layers = lambda *layers: refreshes.append(layers)

        Map.queue_editor_visual_refresh(map_screen, "political", "relations")
        Map.queue_editor_visual_refresh(map_screen, "political")
        Map.flush_editor_visual_refresh(map_screen)

        self.assertEqual(len(invalidations), 2)
        self.assertEqual(len(refreshes), 1)
        self.assertEqual(set(refreshes[0]), {"political", "relations"})
        self.assertFalse(map_screen._editor_visual_refresh_layers)

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

    def test_negative_left_camera_offset_shifts_clipped_map_right(self):
        surface = pygame.Surface((100, 100))
        background_color = (1, 2, 3)
        map_color = (200, 100, 50)
        surface.fill(background_color)
        active_map = pygame.Surface((200, 100))
        active_map.fill(map_color)

        camera = MapCamera(min_zoom=1)
        camera.pos = pygame.Vector2(-10, 0)
        map_screen = SimpleNamespace(
            active_map=active_map,
            camera=camera,
            total_ui_h=0,
            top_ui_height=0,
            map_w=200,
            map_h=100,
            loop_map=False,
            fog_map=None,
            show_player_ready_screen=False,
            multi_turns_total=0,
            multi_turns_completed=0,
            ai_is_thinking=True,
            is_refreshing=False,
            is_saving=False,
            selection_mode=True,
        )

        with patch.object(map_renderer.loading_screen, "draw_turn_loading_screen"), \
             patch.object(map_renderer.ui_bars, "draw_ui_bars"):
            map_renderer.draw_map_screen(map_screen, surface)

        # The 10-pixel out-of-map region remains the background, while map
        # x=0 appears 10 pixels to the right instead of being glued to x=0.
        self.assertEqual(surface.get_at((0, 50))[:3], background_color)
        self.assertEqual(surface.get_at((10, 50))[:3], map_color)
        self.assertEqual(surface.get_at((99, 50))[:3], map_color)


if __name__ == "__main__":
    unittest.main()
