"""Regression coverage for procedural map pixel-to-province setup."""

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import numpy as np

from map_logic.random_map import procedural_map_generator


class ProceduralMapGeneratorTests(unittest.TestCase):
    def test_vectorized_province_summary_preserves_centers_and_terrain(self):
        grid = np.ones((9, 9), dtype=np.int32)
        grid[3:6, 3:6] = 2
        original_grid = grid.copy()

        # Compute the old per-province result as a reference, including the
        # one-pixel border removal that runs before province centers are found.
        expected_grid = original_grid.copy()
        border_mask = ((expected_grid != np.roll(expected_grid, -1, axis=1))
                       | (expected_grid != np.roll(expected_grid, -1, axis=0)))
        expected_grid[border_mask] = 0
        expected = {}
        for province_id in range(1, 4):
            ys, xs = np.where(expected_grid == province_id)
            if len(ys):
                center = (int(np.mean(xs)), int(np.mean(ys)))
                on_edge = (np.any(xs == 0) or np.any(xs == expected_grid.shape[1] - 1)
                           or np.any(ys == 0) or np.any(ys == expected_grid.shape[0] - 1))
                terrain = "ocean" if on_edge else "plains"
            else:
                center = (0, 0)
                terrain = "ocean"
            expected[province_id] = center, terrain

        map_screen = SimpleNamespace()
        with patch.object(procedural_map_generator.random, "choice", return_value="plains"):
            procedural_map_generator._process_grid_to_map(
                map_screen, grid, width=9, height=9, num_provinces=3)

        self.assertTrue(np.array_equal(grid, expected_grid))
        for province_id, (center, terrain) in expected.items():
            province = map_screen.id_to_province[province_id]
            self.assertEqual(province["center"], center)
            self.assertEqual(province["terrain"], terrain)

        self.assertEqual(map_screen.id_map.get_size(), (9, 9))
        self.assertEqual(map_screen.terrain_map.get_size(), (9, 9))


if __name__ == "__main__":
    unittest.main()
