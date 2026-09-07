"""Regression coverage for the Greater Diplomacy Hex Edition save importer."""

import json
from pathlib import Path
import tempfile
import unittest

from map_logic import gdhex_translation as gdhex


ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "TEMP_GDHEX" / "GD-HEX_GameSave.txt"


def _nested(rows):
    return json.dumps([json.dumps(row) for row in rows])


def _small_hex_save():
    """A non-40x26 map proves dimensions come from the save, not a constant."""
    width, height = 3, 2
    hexes = [
        [0, 0, "P", 2, 3, 1, 0, 0],
        [1, 0, "WATER", 0, 0, 0, 0, 0],
        [2, 0, "E", 0, 0, 2, 0, 0],
        [0, -1, 50, 0, 0, 3, 0, 0],
        [1, -1, "P", 1, 0, 0, 0, 0],
        [2, -1, "E", 0, 0, 0, 0, 0],
    ]
    armies = [
        [["i", "10", "5", "5", "1", "FALSE", "P", "unarmored"]],
        [["des", "100", "50", "50", "2", "FALSE", "P", "ship"],
         ["cru", "300", "300", "200", "2", "FALSE", "E", "ship"]],
        [], [], [], [],
    ]
    fields = [
        str(width), str(height), "0", "0", "Custom", str(1939 * 12 + 9), "0", "P",
        _nested(armies), _nested(hexes), json.dumps([1, 2, 3]), json.dumps([4, 5, 6]),
    ]
    return "|".join(fields)


class GDHEXTranslationTests(unittest.TestCase):
    def setUp(self):
        self.source = _small_hex_save()

    def test_parses_dynamic_dimensions_and_rejects_wrong_record_counts(self):
        parsed = gdhex.parse_save(self.source)
        self.assertEqual((parsed["width"], parsed["height"]), (3, 2))
        self.assertEqual(len(parsed["hexes"]), 6)

        fields = self.source.split("|")
        fields[8] = _nested([[]] * 5)
        with self.assertRaises(gdhex.GDHEXTranslationError):
            gdhex.parse_save("|".join(fields))

    def test_builds_map_ownership_economy_and_units(self):
        payload, raw_map, assets, notes = gdhex.build_save_payload(gdhex.parse_save(self.source))
        provinces = {province["id"]: province for province in raw_map.values()}
        self.assertEqual(len(raw_map), 6)
        self.assertEqual(payload["date"], {"day": 15, "month": 9, "year": 1939, "total_turns": 0})
        self.assertEqual(payload["player_country"], "Player")
        self.assertEqual(payload["nation_data"]["Player"]["at_war_with"], ["Enemy"])
        self.assertEqual(payload["nation_data"]["Player"]["manpower"], 100)
        self.assertEqual(payload["nation_data"]["Player"]["fuel"], 200)
        self.assertEqual(payload["nation_data"]["Player"]["materials"], 300)
        self.assertIn("Hex Country 50", payload["nation_data"])
        self.assertEqual(provinces[1]["neighbors"], [4, 2])
        self.assertTrue(provinces[1]["is_coastal"])
        self.assertEqual(provinces[1]["resources"], {"Wheat": 100})
        self.assertEqual(provinces[1]["buildings"], ["Factory Lvl 1", "Fort Lvl 3"])
        self.assertEqual(provinces[2]["owner"], "Ocean")
        self.assertEqual(provinces[2]["resources"], {})

        infantry = provinces[1]["units"][0]
        self.assertEqual(infantry["type"], "Infantry Type 1939")
        self.assertEqual(infantry["health"], infantry["max_health"] * 0.5)
        navy = provinces[2]["units"]
        self.assertEqual([unit["type"] for unit in navy], ["Destroyer I", "Dreadnought"])
        self.assertTrue(all(unit["naval_unit"] for unit in navy))
        self.assertEqual(len(assets), 4)
        self.assertTrue(any("3 x 2" in note for note in notes))

    def test_translation_writes_a_complete_loadable_save(self):
        from tests import app_harness
        app_harness.boot()
        import main

        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "small.gdhex"
            source.write_text(self.source, encoding="utf-8")
            destination, _notes = gdhex.translate_file(str(source), saves_dir=temporary)
            destination = Path(destination)
            for name in ("meta.json", "map_data.json", "terrain.png", "id_map.png", "political.png", "cores.png"):
                self.assertTrue((destination / name).is_file())
            loaded = main.Map(load_path=str(destination), is_scenario=False, num_players=1)
            self.assertEqual(len(loaded.id_to_province), 6)
            self.assertEqual(loaded.player_country, "Player")
            loaded.update()

    @unittest.skipUnless(SAMPLE.is_file(), "supplied Hex Edition sample is not present")
    def test_supplied_save_is_a_dynamic_40_by_26_example(self):
        parsed = gdhex.parse_save(SAMPLE.read_text(encoding="utf-8"))
        self.assertEqual((parsed["width"], parsed["height"]), (40, 26))
        payload, raw_map, _assets, _notes = gdhex.build_save_payload(parsed)
        self.assertEqual(len(raw_map), 1040)
        self.assertEqual(payload["date"]["year"], 1941)
        self.assertEqual(payload["date"]["month"], 5)


if __name__ == "__main__":
    unittest.main()
