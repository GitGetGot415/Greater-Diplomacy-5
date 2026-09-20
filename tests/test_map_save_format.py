"""Coverage for map save province state and backwards-compatible overlays."""

import asyncio
import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from data import queries
from data.map import history_io, load_map, save_map
import data.constants as c


def sample_map_screen():
    province = {
        "id": 7,
        "terrain": "plains",
        "center": [12, 34],
        "neighbors": [6, 8],
        "json_key": "(7, 0, 0)",
        "map_color": [7, 0, 0],
        "owner": "Avaria",
        "cores": ["Avaria"],
        "is_coastal": True,
        "units": [{"type": "Infantry", "owner": "Avaria"}],
        "building_queue": [],
        "unit_queue": [{"type": "Infantry", "turns_left": 2}],
        "orders": [],
        "resources": {"Oil": 20},
        "buildings": ["Factory"],
    }
    return SimpleNamespace(
        map_data={(7, 0, 0): province},
        raw_json_data={"(7, 0, 0)": {"id": 7, "terrain": "plains"}},
        time_manager=SimpleNamespace(day=15, month_index=5, year=1939, total_turns=12),
        loop_map=True,
        player_country="Avaria",
        active_players=["Avaria"],
        current_player_index=0,
        scenario_settings={"days_per_turn": 30},
        script_variables=[{"name": "event_flag", "value": True}],
        default_research={"infantry_type": 3},
        nation_data={"Avaria": {"name": "Avaria", "materials": 200}},
    )


class MapSaveFormatTests(unittest.TestCase):
    def test_map_data_holds_current_province_state_and_meta_can_omit_duplicate(self):
        map_screen = sample_map_screen()

        network_snapshot = queries.build_save_dict(map_screen)
        disk_meta = queries.build_save_dict(map_screen, include_provinces=False)
        map_data = queries.build_map_data_save(map_screen)

        key = "(7, 0, 0)"
        self.assertEqual(map_data[key]["owner"], network_snapshot["provinces"][key]["owner"])
        self.assertEqual(map_data[key]["units"], network_snapshot["provinces"][key]["units"])
        self.assertEqual(map_data[key]["resources"], network_snapshot["provinces"][key]["resources"])
        self.assertEqual(map_data[key]["terrain"], "plains")
        self.assertNotIn("provinces", disk_meta)
        self.assertEqual(disk_meta["nation_data"], map_screen.nation_data)
        self.assertEqual(disk_meta["date"], {
            "day": 15, "month": 5, "year": 1939, "total_turns": 12,
        })
        self.assertEqual(disk_meta["scenario_settings"]["days_per_turn"], 30)

        # These are the actual text forms written by map save paths.
        self.assertEqual(json.loads(history_io.dump_compact_text(disk_meta)), disk_meta)
        self.assertEqual(json.loads(history_io.dump_compact_text(map_data)), map_data)
        self.assertEqual(map_screen.raw_json_data, {key: {"id": 7, "terrain": "plains"}})

    def test_full_save_dictionary_still_carries_multiplayer_province_snapshot(self):
        snapshot = queries.build_save_dict(sample_map_screen())
        self.assertEqual(snapshot["provinces"]["(7, 0, 0)"], {
            "owner": "Avaria",
            "cores": ["Avaria"],
            "is_coastal": True,
            "units": [{"type": "Infantry", "owner": "Avaria"}],
            "building_queue": [],
            "unit_queue": [{"type": "Infantry", "turns_left": 2}],
            "orders": [],
            "resources": {"Oil": 20},
            "buildings": ["Factory"],
        })

    def test_disk_save_writes_current_state_compactly_without_meta_overlay(self):
        map_screen = sample_map_screen()
        map_screen.is_editor = False
        map_screen.political_map = object()
        map_screen.terrain_map = object()
        map_screen.id_map = object()
        map_screen.cores_map = object()
        map_screen.show_feedback = lambda _message: None

        with tempfile.TemporaryDirectory() as temporary:
            with mock.patch.object(c, "SAVES_DIR", temporary), \
                 mock.patch.object(save_map.queries, "scrub_default_images"), \
                 mock.patch.object(save_map.pygame.image, "save"), \
                 mock.patch.object(save_map, "sync_persisted_dir"):
                asyncio.run(save_map.save_map_data(map_screen, "compact-save"))

            save_dir = os.path.join(temporary, "compact-save")
            with open(os.path.join(save_dir, "meta.json"), encoding="utf-8") as handle:
                meta_text = handle.read()
            with open(os.path.join(save_dir, "map_data.json"), encoding="utf-8") as handle:
                map_data_text = handle.read()
            meta = json.loads(meta_text)
            map_data = json.loads(map_data_text)

        self.assertNotIn("provinces", meta)
        self.assertEqual(meta["nation_data"], map_screen.nation_data)
        self.assertEqual(meta["date"], {
            "day": 15, "month": 5, "year": 1939, "total_turns": 12,
        })
        self.assertEqual(map_data["(7, 0, 0)"], map_screen.map_data[(7, 0, 0)])
        self.assertEqual(meta_text, json.dumps(meta, separators=(",", ":")))
        self.assertEqual(map_data_text, json.dumps(map_data, separators=(",", ":")))
        self.assertFalse(map_screen.is_saving)

    def test_legacy_meta_and_history_province_overlays_still_apply(self):
        map_data = {
            "(7, 0, 0)": {"id": 7, "terrain": "plains", "owner": "Avaria", "units": []},
        }
        legacy_overlay = {
            "(7, 0, 0)": {"owner": "Borland", "units": [{"type": "Infantry"}]},
            "(99, 0, 0)": {"owner": "Ignored missing province"},
        }

        result = queries.map_data_with_saved_provinces(map_data, legacy_overlay)

        self.assertEqual(result["(7, 0, 0)"], {
            "id": 7, "terrain": "plains", "owner": "Borland",
            "units": [{"type": "Infantry"}],
        })
        self.assertEqual(map_data["(7, 0, 0)"], {
            "id": 7, "terrain": "plains", "owner": "Avaria", "units": [],
        })

    def test_selected_history_turn_supplies_provinces_without_current_meta_overlay(self):
        save_meta = {
            "nation_data": {"Current": {"materials": 5}},
            "date": {"day": 1, "month": 0, "year": 1940, "total_turns": 8},
        }
        history = {
            "3": {
                "nation_data": {"Historical": {"materials": 12}},
                "provinces": {"(7, 0, 0)": {"owner": "Historical"}},
                "day": 15,
                "month": 4,
                "year": 1939,
            },
            "9": {"nation_data": {}, "provinces": {}},
        }

        self.assertTrue(load_map._apply_history_snapshot(save_meta, history, 3))
        raw_map = {"(7, 0, 0)": {"id": 7, "terrain": "plains", "owner": "Current"}}
        queries.overlay_saved_province_data(raw_map, save_meta["provinces"])

        self.assertEqual(raw_map["(7, 0, 0)"], {
            "id": 7, "terrain": "plains", "owner": "Historical",
        })
        self.assertEqual(save_meta["nation_data"], {"Historical": {"materials": 12}})
        self.assertEqual(save_meta["date"], {
            "day": 15, "month": 4, "year": 1939, "total_turns": 3,
        })
        self.assertEqual(set(history), {"3"})


if __name__ == "__main__":
    unittest.main()
