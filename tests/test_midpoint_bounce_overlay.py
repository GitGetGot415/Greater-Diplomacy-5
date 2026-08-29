"""Regression tests for the map's hostile head-on movement preview."""

import os
import sys
import unittest
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from map_logic.rendering import overlay_renderer
import pygame
from pygame.math import Vector2


def province(province_id, units):
    return {
        "id": province_id,
        "center": (province_id * 100, 100),
        "units": units,
    }


def moving_unit(owner, destination):
    return {
        "owner": owner,
        "order": {"type": "MOVE", "path": [destination]},
    }


class BouncePreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        pygame.display.set_mode((400, 300))
        from map_logic.rendering import symbol_loader
        symbol_loader.load_symbols()

    def setUp(self):
        self.screen = type("Screen", (), {})()
        self.screen.player_country = "A"
        self.screen.viewing_ai_moves = False
        self.screen.is_editor = False
        self.screen.map_data = {
            1: province(1, [moving_unit("A", 2)]),
            2: province(2, [moving_unit("B", 1)]),
        }
        self.screen.nation_data = {
            "A": {"at_war_with": ["B"]},
            "B": {"at_war_with": ["A"]},
        }

        self.screen.id_to_province = self.screen.map_data
        self.screen.camera = SimpleNamespace(
            zoom=1.0, tilt_factor=1.0, pos=Vector2(0, 0))
        self.screen.visible_provinces = None
        self.screen.partial_visible_provinces = set()
        self.screen.map_w = 400
        self.screen.loop_map = False
        self.screen.top_ui_height = 0

    def test_ai_move_view_shows_the_full_hostile_swap(self):
        self.screen.viewing_ai_moves = True

        self.assertEqual(
            overlay_renderer.midpoint_bounce_pairs(self.screen), [(1, 2)])

    def test_normal_play_does_not_reveal_the_enemy_order(self):
        self.assertEqual(
            overlay_renderer.midpoint_bounce_pairs(self.screen), [])

    def test_spectator_can_preview_the_full_board(self):
        self.screen.player_country = "Spectator"

        self.assertEqual(
            overlay_renderer.midpoint_bounce_pairs(self.screen), [(1, 2)])

    def test_marker_is_drawn_between_the_two_provinces(self):
        self.screen.viewing_ai_moves = True
        surface = pygame.Surface((400, 300), pygame.SRCALPHA)

        overlay_renderer.draw_midpoint_bounces(self.screen, surface)

        marker_pixels = sum(
            1 for x in range(surface.get_width())
            for y in range(surface.get_height())
            if surface.get_at((x, y)).a)
        self.assertGreater(marker_pixels, 0)


if __name__ == "__main__":
    unittest.main()
