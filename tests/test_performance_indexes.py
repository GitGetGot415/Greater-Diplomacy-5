"""Regression coverage for cached AI and dense rendering indexes."""

import unittest
from unittest import mock


from data import queries
from map_logic.ai import ai_world
from ui.rendering.overlay_renderer import _UnitRenderIndex


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

    def test_land_entry_ids_match_the_rule_for_every_province(self):
        # One tile of each kind the entry rule distinguishes: own, enemy,
        # military access, neutral, unclaimed, ownerless, water, and land
        # captured this turn (judged by its turn-start owner).
        provinces = [
            {"id": 1, "owner": "Avaria", "terrain": "plains"},
            {"id": 2, "owner": "Borland", "terrain": "plains"},
            {"id": 3, "owner": "Cordia", "terrain": "plains"},
            {"id": 4, "owner": "Dunmark", "terrain": "plains"},
            {"id": 5, "owner": "Unclaimed", "terrain": "plains"},
            {"id": 6, "terrain": "plains"},
            {"id": 7, "owner": "Unclaimed", "terrain": "ocean"},
            {"id": 8, "owner": "Borland", "_turn_start_owner": "Dunmark", "terrain": "plains"},
            {"id": 9, "owner": "Dunmark", "_turn_start_owner": "Borland", "terrain": "plains"},
            {"id": 10, "owner": "Dunmark", "terrain": "plains"},
        ]
        map_data = {str(prov["id"]): dict(prov, neighbors=[], units=[]) for prov in provinces}
        id_to_province = {prov["id"]: prov for prov in map_data.values()}
        nation_data = {
            "Avaria": {"at_war_with": ["Borland"], "claims": []},
            "Borland": {"at_war_with": ["Avaria"], "claims": []},
            "Cordia": {"at_war_with": [], "claims": [], "military_access": ["Avaria"]},
            "Dunmark": {"at_war_with": [], "claims": []},
        }
        world = ai_world.AIWorld(map_data, nation_data, id_to_province)
        for nation in nation_data:
            expected = {prov["id"] for prov in map_data.values()
                        if queries.can_land_units_enter(nation, prov, nation_data)}
            self.assertEqual(world.land_entry_ids(nation), expected, nation)

    def test_upgrade_target_is_looked_up_once_per_nation_and_type(self):
        world = ai_world.AIWorld(self.map_data, self.nation_data, self.id_to_province)
        self.nation_data["Avaria"]["research"] = {"armor": 2}
        library, tree = {"Tank I": {}, "Tank II": {}}, {}
        with mock.patch.object(queries, "get_upgrade_target", return_value="Tank II") as lookup:
            for _ in range(3):
                self.assertEqual(world.upgrade_target("Avaria", "Tank I", library, tree), "Tank II")
            world.upgrade_target("Borland", "Tank I", library, tree)
        self.assertEqual(lookup.call_args_list, [
            mock.call("Tank I", {"armor": 2}, library, tree),
            mock.call("Tank I", {}, library, tree),
        ])

    def test_render_index_is_dense_over_occupied_provinces(self):
        index = _UnitRenderIndex(self.map_data)

        self.assertEqual(index.total_units, 2)
        self.assertEqual(index.unit_counts.tolist(), [1, 1])
        self.assertEqual(index.occupied_provinces,
                         (self.map_data["1"], self.map_data["2"]))
        self.assertIs(index.live_by_object_id[id(self.unit_b)][0], self.unit_b)
        self.assertIs(index.live_by_object_id[id(self.unit_b)][1], self.map_data["2"])

    def test_training_only_provinces_participate_without_becoming_deployed_units(self):
        training = self.map_data["3"]
        training["unit_queue"] = [{"unit_type": "Infantry"}]
        index = _UnitRenderIndex(self.map_data)
        self.assertIn(training, index.occupied_provinces)
        self.assertIn(id(training), index.training_province_object_ids)
        self.assertEqual(index.unit_counts.tolist(), [1, 1, 0])
        self.assertEqual(index.total_units, 2)
        self.assertEqual(len(index.records), 2)
        self.assertEqual(index.view_units_by_province[id(training)], ())


if __name__ == "__main__":
    unittest.main()
