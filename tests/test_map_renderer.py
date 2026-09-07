"""Base-map placement at the bounded edges of non-looping maps."""

from types import SimpleNamespace
import unittest
from unittest.mock import patch

import pygame

from map_logic.camera.camera_handler import MapCamera
from map_logic.rendering import map_renderer


class NonLoopingMapRendererTests(unittest.TestCase):
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
