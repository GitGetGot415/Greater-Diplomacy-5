"""Camera wrapping behavior for looping and bounded maps."""

from types import SimpleNamespace
import unittest

import pygame

from map_logic.camera.camera_handler import MapCamera


def _map(loop_map):
    return SimpleNamespace(
        loop_map=loop_map,
        map_w=1000,
        map_h=800,
        total_ui_h=100,
        top_ui_height=50,
    )


class MapCameraBoundsTests(unittest.TestCase):
    def test_non_looping_pan_uses_direct_distance_instead_of_shortest_wrap(self):
        camera = MapCamera(min_zoom=2)
        camera.zoom = camera.target_zoom = 2
        camera.pos = pygame.Vector2(10, 100)
        camera.target_pos = pygame.Vector2(990, 100)

        camera.update(_map(loop_map=False), 720)

        # A wrapped calculation would move left from 10 to 8. A bounded map
        # must instead advance toward its right-hand target, then clamp there.
        self.assertGreater(camera.pos.x, 10)

    def test_looping_pan_keeps_shortest_wrapped_distance(self):
        camera = MapCamera(min_zoom=2)
        camera.zoom = camera.target_zoom = 2
        camera.pos = pygame.Vector2(10, 100)
        camera.target_pos = pygame.Vector2(990, 100)

        camera.update(_map(loop_map=True), 720)

        self.assertLess(camera.pos.x, 10)


if __name__ == "__main__":
    unittest.main()
