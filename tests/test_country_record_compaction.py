"""Country template compaction must preserve authored state and editor access."""

import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from data import queries
from data.io import country_io
from data.map import load_map
from map_tools import compact_country_records
from tests.test_map_save_format import sample_map_screen
from ui import editor_menus


def templates():
    return {name: {"name": name, "color": [index, 20, 30],
                   "research": {"infantry_type": 1}, "manpower": 0,
                   "materials": 0, "fuel": 0, "is_playable": True,
                   "flag_data": "", "portrait_data": "",
                   "at_war_with": [], "allied_with": []}
            for index, name in enumerate(("A", "B", "C", "D", "E"))}


class CountryRecordCompactionTests(unittest.TestCase):
    def setUp(self):
        self.catalog = templates()
        self.patch = mock.patch.object(queries, "get_country_data", return_value=self.catalog)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.nations = copy.deepcopy(self.catalog)

    def test_only_unused_defaults_become_empty_and_order_is_preserved(self):
        self.nations["Custom"] = {"name": "Custom", "color": [10, 10, 10]}
        before = copy.deepcopy(self.nations)
        compact = queries.compact_nation_data(self.nations, {"owner": "B"})
        self.assertEqual(compact["A"], {})
        self.assertEqual(compact["B"], before["B"])
        self.assertEqual(compact["Custom"], before["Custom"])
        self.assertEqual(list(compact), list(before))
        self.assertEqual(self.nations, before)
        self.assertEqual(self.catalog, templates())
        restored = queries.merge_country_templates(copy.deepcopy(compact))
        self.assertEqual(restored, before)
        self.assertEqual(list(restored), list(before))

    def test_cores_units_and_queues_preserve_landless_countries(self):
        provinces = {"p": {"owner": "A", "cores": ["B"],
                           "units": [{"owner": "C", "volunteer_host": "D"}],
                           "unit_queue": [{"owner": "E"}]}}
        self.assertEqual(queries.compact_nation_data(self.nations, provinces), self.nations)

    def test_metadata_keeps_humans_and_unknown_country_references(self):
        result = queries.compact_nation_data(self.nations, {
            "player_country": "A", "active_players": ["B"],
            "script_variables": [{"value": "C"}],
            "realtime_match": {"country_assignments": {"D": "player"}},
        })
        for name in "ABCD":
            self.assertEqual(result[name], self.nations[name])
        self.assertEqual(result["E"], {})

    def test_retained_records_protect_transitive_diplomacy_and_event_targets(self):
        self.nations["A"]["pending_diplomacy"] = {"B": {"action": "WAR_DECLARATION"}}
        self.nations["B"]["guarantees"] = ["C"]
        self.nations["C"]["scripted_events"] = [{"actions": [{"target": "D"}]}]
        result = queries.compact_nation_data(self.nations)
        for name in "ABCD":
            self.assertEqual(result[name], self.nations[name])
        self.assertEqual(result["E"], {})

    def test_customizations_are_preserved_even_without_territory(self):
        changes = {"name": "Renamed", "color": [1, 2, 3], "manpower": 10,
                   "materials": 10, "fuel": 10, "leader_name": "Custom",
                   "leader_title": "Custom", "research": {"infantry_type": 0},
                   "flag_data": "custom-b64", "portrait_data": "custom-b64",
                   "is_playable": False, "faction": "Government in exile",
                   "custom_empty_field": {}, "future_field": ["payload"]}
        for field, value in changes.items():
            with self.subTest(field=field):
                nations = copy.deepcopy(self.catalog)
                nations["A"][field] = value
                self.assertEqual(queries.compact_nation_data(nations)["A"], nations["A"])

    def test_empty_bookkeeping_and_default_images_are_recoverable(self):
        self.nations["A"].update({"pending_diplomacy": {}, "relations": {},
                                 "diplo_responses": {}, "military_attaches": [],
                                 "armies": [], "war_durations": {},
                                 "flag_data": "DEFAULT", "portrait_data": "DEFAULT"})
        compact = queries.compact_nation_data(self.nations)
        self.assertEqual(compact["A"], {})
        restored = queries.merge_country_templates(copy.deepcopy(compact))
        with mock.patch.object(queries, "scrub_default_images"):
            load_map._load_default_images(SimpleNamespace(nation_data=restored))
        self.assertEqual(restored["A"]["flag_data"], self.nations["A"]["flag_data"])
        self.assertEqual(restored["A"]["portrait_data"], self.nations["A"]["portrait_data"])
        for field in ("pending_diplomacy", "relations", "diplo_responses", "war_durations"):
            self.assertEqual(restored["A"].get(field, {}), self.nations["A"][field])
        for field in ("military_attaches", "armies"):
            self.assertEqual(restored["A"].get(field, []), self.nations["A"][field])

    def test_nonempty_optional_bookkeeping_is_preserved(self):
        changes = {"pending_diplomacy": {"B": {}}, "relations": {"B": 0},
                   "diplo_responses": {"B": {}}, "military_attaches": ["B"],
                   "armies": [{"unit_ids": ["unit"]}], "war_durations": {"B": 0}}
        for field, value in changes.items():
            with self.subTest(field=field):
                nations = copy.deepcopy(self.catalog)
                nations["A"][field] = value
                self.assertEqual(queries.compact_nation_data(nations)["A"], nations["A"])

    def test_prewar_maps_and_global_events_keep_referenced_country_state(self):
        self.nations["FACTION_WAR_MAPS"] = {"bloc": {"province": "B"}}
        self.nations["GLOBAL_EVENTS"] = {"scripted_events": [{"target": "C"}]}
        result = queries.compact_nation_data(self.nations)
        for name in ("B", "C", "FACTION_WAR_MAPS", "GLOBAL_EVENTS"):
            self.assertEqual(result[name], self.nations[name])
        self.assertEqual(result["D"], {})

    def test_legacy_research_migration_and_cache_isolation(self):
        self.nations["A"]["research"] = {}
        compact = queries.compact_nation_data(self.nations)
        self.assertEqual(compact["A"], {})
        compact.pop("E")  # Old saves may omit entire catalog entries.
        restored = queries.merge_country_templates(copy.deepcopy(compact))
        self.assertEqual(restored, self.catalog)
        restored["A"]["color"][0] = 255
        restored["B"]["research"]["infantry_type"] = 5
        self.assertEqual(self.catalog, templates())

    def test_unknown_research_and_catalog_image_overrides_survive(self):
        self.nations["A"]["research"]["unknown"] = 0
        self.catalog["B"]["flag_data"] = "catalog-image"
        self.nations["B"]["flag_data"] = "DEFAULT"
        result = queries.compact_nation_data(self.nations)
        self.assertEqual(result["A"], self.nations["A"])
        self.assertEqual(result["B"], self.nations["B"])

    def test_editor_can_still_pick_and_paint_a_restored_country(self):
        compact = queries.compact_nation_data(self.nations, {"owner": "A"})
        self.assertEqual(compact["B"], {})
        restored = queries.merge_country_templates(json.loads(json.dumps(compact)))
        screen = SimpleNamespace(nation_data=restored)
        self.assertIn(("B", "B"), editor_menus._paintable_nations(screen))
        self.assertEqual(country_io.nation_colors_from(restored)["B"], tuple(self.catalog["B"]["color"]))
        self.assertTrue(queries.is_playable("B", restored))

    def test_network_snapshots_remain_full_and_disk_compaction_is_explicit(self):
        screen = sample_map_screen()
        screen.nation_data.update(copy.deepcopy(self.nations))
        network = queries.build_save_dict(screen)
        disk = queries.build_save_dict(screen, include_provinces=False, compact_nations=True)
        self.assertEqual(network["nation_data"], screen.nation_data)
        self.assertEqual(disk["nation_data"]["B"], {})
        self.assertEqual(disk["nation_data"]["Avaria"], screen.nation_data["Avaria"])
        self.assertNotIn("provinces", disk)
        self.assertTrue(screen.nation_data["B"])

    def test_cleanup_tool_is_previewable_idempotent_and_only_writes_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            meta = {"nation_data": self.nations, "unknown": {"field": "preserved"}}
            meta_path = directory / "meta.json"
            meta_path.write_text(json.dumps(meta, indent=4), encoding="utf-8")
            map_path = directory / "map_data.json"
            map_path.write_text('{"p":{"owner":"A"}}', encoding="utf-8")
            history_path = directory / "history.json"
            history_path.write_text('{"old":"history"}', encoding="utf-8")
            originals = {path.name: path.read_bytes() for path in directory.iterdir()}
            count, saved = compact_country_records.compact_map_metadata(directory)
            self.assertEqual(count, len(self.catalog) - 1)
            self.assertGreater(saved, 0)
            self.assertEqual(meta_path.read_bytes(), originals["meta.json"])
            self.assertEqual(compact_country_records.compact_map_metadata(directory, write=True), (count, saved))
            after = json.loads(meta_path.read_bytes())
            self.assertEqual(after["unknown"], meta["unknown"])
            self.assertEqual(after["nation_data"]["A"], self.nations["A"])
            self.assertEqual(after["nation_data"]["B"], {})
            self.assertEqual(compact_country_records.compact_map_metadata(directory, write=True), (0, 0))
            self.assertEqual(map_path.read_bytes(), originals["map_data.json"])
            self.assertEqual(history_path.read_bytes(), originals["history.json"])


class BundledCountryRecordTests(unittest.TestCase):
    def test_bundled_metadata_does_not_repeat_unused_country_templates(self):
        root = Path(__file__).resolve().parents[1]
        for map_root in (root / "base_maps", root / "scenarios"):
            for meta_path in map_root.rglob("meta.json"):
                if "map_editor" in meta_path.parts:
                    continue
                with self.subTest(path=str(meta_path.relative_to(root))):
                    count, _ = compact_country_records.compact_map_metadata(meta_path.parent)
                    self.assertEqual(count, 0, "unused templates should be compacted before shipping")


if __name__ == "__main__":
    unittest.main()
