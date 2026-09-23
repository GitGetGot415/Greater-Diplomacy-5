"""Regression coverage for cached AI and dense rendering indexes."""

import os
import sys
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from map_logic.ai import ai_world
from map_logic.rendering.overlay_renderer import _UnitRenderIndex


class PerformanceIndexTests(unittest.TestCase):
    def setUp(self):
        self.unit_a = {
            "owner": "Avaria", "attack": 10, "defense": 5,
            "health": 100, "unit_id": "a-1",
        }
        self.unit_b = {
            "owner": "Borland", "attack": 20, "defense": 7,
            "health": 80, "unit_id": "b-1",
        }
        self.map_data = {
            "1": {"id": 1, "owner": "Avaria", "center": (10, 10),
                   "terrain": "plains", "neighbors": [2], "units": [self.unit_a]},
            "2": {"id": 2, "owner": "Borland", "center": (30, 10),
                   "terrain": "plains", "neighbors": [1], "units": [self.unit_b]},
            "3": {"id": 3, "owner": "Avaria", "center": (50, 10),
                   "terrain": "plains", "neighbors": [2], "units": []},
        }
        self.id_to_province = {province["id"]: province
                               for province in self.map_data.values()}
        self.nation_data = {
            "Avaria": {"at_war_with": ["Borland"], "claims": []},
            "Borland": {"at_war_with": ["Avaria"], "claims": []},
        }

    def test_ai_world_indexes_units_without_copying_them(self):
        world = ai_world.AIWorld(self.map_data, self.nation_data,
                                  self.id_to_province)

        self.assertEqual(world.provs_by_owner["Avaria"], [self.map_data["1"], self.map_data["3"]])
        self.assertEqual(world.units_by_owner["Avaria"], [(self.unit_a, self.map_data["1"])])
        self.assertIs(world.units_by_owner["Avaria"][0][0], self.unit_a)
        self.assertEqual(world.land_entry_ids("Avaria"), {1, 2, 3})

    def test_render_index_is_dense_over_occupied_provinces(self):
        index = _UnitRenderIndex(self.map_data)

        self.assertEqual(index.total_units, 2)
        self.assertEqual(index.unit_counts.tolist(), [1, 1])
        self.assertEqual(index.occupied_provinces,
                         (self.map_data["1"], self.map_data["2"]))
        self.assertIs(index.live_by_object_id[id(self.unit_b)][0], self.unit_b)
        self.assertIs(index.live_by_object_id[id(self.unit_b)][1], self.map_data["2"])


if __name__ == "__main__":
    unittest.main()
