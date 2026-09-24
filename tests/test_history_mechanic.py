"""Regression coverage for creating and loading turn-history snapshots."""

import copy
import shutil
import tempfile
import unittest
from types import SimpleNamespace

from data import queries
from data.map import history_io, load_map
from map_logic.turn_processing.turn_processor import snapshot_history


class HistoryMechanicTests(unittest.TestCase):
    def setUp(self):
        self.map_screen = SimpleNamespace(
            history={},
            time_manager=SimpleNamespace(
                total_turns=7,
                day=15,
                month_index=4,
                year=1939,
                get_date_string=lambda: "15 May, 1939 AD",
            ),
            nation_data={
                "Avaria": {
                    "materials": 200,
                    "research": {"infantry_type": 3},
                    "pending_deals": [{"clauses": [{"resource": "fuel", "amount": 4}]}],
                }
            },
            map_data={
                (7, 0, 0): {
                    "json_key": "(7, 0, 0)",
                    "owner": "Avaria",
                    "cores": ["Avaria"],
                    "is_coastal": True,
                    "units": [{"type": "Infantry", "owner": "Avaria"}],
                    "building_queue": [],
                    "unit_queue": [],
                    "orders": [],
                    "resources": {"Iron": 30, "Oil": 12},
                    "buildings": ["Factory"],
                }
            },
        )

    def test_snapshot_preserves_resource_mapping_and_nested_state(self):
        snapshot_history(self.map_screen)
        snapshot = self.map_screen.history["7"]

        self.assertEqual(snapshot["provinces"]["(7, 0, 0)"]["resources"],
                         {"Iron": 30, "Oil": 12})
        self.assertEqual(snapshot["nation_data"], self.map_screen.nation_data)

        # A later live-state mutation must not edit the historical turn.
        self.map_screen.map_data[(7, 0, 0)]["resources"]["Iron"] = 0
        self.map_screen.nation_data["Avaria"]["research"]["infantry_type"] = 9
        self.map_screen.nation_data["Avaria"]["pending_deals"][0]["clauses"][0]["amount"] = 99

        self.assertEqual(snapshot["provinces"]["(7, 0, 0)"]["resources"]["Iron"], 30)
        self.assertEqual(snapshot["nation_data"]["Avaria"]["research"]["infantry_type"], 3)
        self.assertEqual(
            snapshot["nation_data"]["Avaria"]["pending_deals"][0]["clauses"][0]["amount"],
            4,
        )

    def test_history_round_trip_and_selected_turn_preserve_resources(self):
        snapshot_history(self.map_screen)
        history_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, history_dir, True)
        history_io.write(history_dir, self.map_screen.history)
        loaded_history = history_io.read(history_dir)

        save_meta = {
            "nation_data": {"Avaria": {"materials": 1}},
            "date": {"day": 1, "month": 0, "year": 1940, "total_turns": 8},
        }
        self.assertTrue(load_map._apply_history_snapshot(save_meta, loaded_history, 7))
        raw_map = {"(7, 0, 0)": {"id": 7, "terrain": "plains", "resources": {"Coal": 5}}}
        queries.overlay_saved_province_data(raw_map, save_meta["provinces"])

        self.assertEqual(raw_map["(7, 0, 0)"]["resources"], {"Iron": 30, "Oil": 12})

    def test_applying_history_does_not_alias_the_loaded_timeline(self):
        snapshot_history(self.map_screen)
        history = copy.deepcopy(self.map_screen.history)
        save_meta = {"date": {}}

        self.assertTrue(load_map._apply_history_snapshot(save_meta, history, 7))
        save_meta["nation_data"]["Avaria"]["research"]["infantry_type"] = 99
        save_meta["provinces"]["(7, 0, 0)"]["resources"]["Oil"] = 0

        self.assertEqual(history["7"]["nation_data"]["Avaria"]["research"]["infantry_type"], 3)
        self.assertEqual(history["7"]["provinces"]["(7, 0, 0)"]["resources"]["Oil"], 12)

    def test_malformed_old_history_resources_do_not_erase_current_mapping(self):
        current = {"(7, 0, 0)": {"resources": {"Iron": 30}}}
        old_history = {"(7, 0, 0)": {"resources": ["Iron"]}}

        queries.overlay_saved_province_data(current, old_history)

        self.assertEqual(current["(7, 0, 0)"]["resources"], {"Iron": 30})


if __name__ == "__main__":
    unittest.main()
