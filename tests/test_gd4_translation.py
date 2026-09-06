"""Regression coverage for the one-way Greater Diplomacy 4 save importer."""

import base64
import json
from pathlib import Path
import tempfile
import unittest

from map_logic import gd4_translation as gd4


ROOT = Path(__file__).resolve().parent.parent
COMPRESSED_SAMPLE = ROOT / "TEMP" / "(Compressed Base64) German Reich - Oct, 1939.txt"


def _nested(rows):
    return json.dumps([json.dumps(row) for row in rows])


def _standard_gd4_text():
    """A small state wrapped in the exact standard GD4 65-section envelope."""
    countries = [["0"] * 38 for _ in range(gd4.COUNTRY_COUNT)]
    for index, name in ((0, "United States of America"), (1, "Canada"), (2, "Mexico")):
        countries[index][2] = name
        countries[index][23] = "President"
        countries[index][24] = f"{name} Leader"

    provinces = [["0"] * 22 for _ in range(gd4.PROVINCE_COUNT)]
    provinces[0][2] = "USA"
    provinces[0][3] = "5"
    provinces[0][4] = "3"
    provinces[0][5] = "110000"
    provinces[0][18] = "Oil, 0.5"
    # An unsupported naval value must not create a GD5 naval unit.
    provinces[0][11] = "Destroyer"
    provinces[1][2] = "CAN"
    provinces[1][18] = "Gold, 3"

    friends = [[] for _ in range(gd4.COUNTRY_COUNT)]
    wars = [[] for _ in range(gd4.COUNTRY_COUNT)]
    friends[0] = ["CAN"]
    wars[0] = ["MEX"]

    sections = [""] * gd4.SECTION_COUNT
    sections[0] = _nested(countries)
    sections[1] = _nested(provinces)
    sections[2] = _nested(friends)
    sections[3] = _nested(wars)
    sections[12] = str(1939 * 12 + 9)
    sections[16] = "USA"
    return gd4.DIVIDER.join(sections)


class GD4TranslationTests(unittest.TestCase):
    def setUp(self):
        self.source_text = _standard_gd4_text()

    def test_plain_text_and_base64_fallback_decode(self):
        self.assertEqual(gd4.decode_save_text(self.source_text), self.source_text)
        encoded = base64.b64encode(self.source_text.encode("utf-8")).decode("ascii")
        self.assertEqual(gd4.decode_save_text(encoded), self.source_text)

    @unittest.skipUnless(COMPRESSED_SAMPLE.is_file(), "supplied TurboWarp sample is not present")
    def test_supplied_turbowarp_lz_string_sample_decodes(self):
        parsed = gd4.parse_save(COMPRESSED_SAMPLE.read_text(encoding="utf-8"))
        self.assertEqual(len(parsed["countries"]), gd4.COUNTRY_COUNT)
        self.assertEqual(len(parsed["provinces"]), gd4.PROVINCE_COUNT)
        self.assertEqual(parsed["time"], 23277)
        with tempfile.TemporaryDirectory() as temporary:
            destination, _notes = gd4.translate_file(str(COMPRESSED_SAMPLE), saves_dir=temporary)
            self.assertTrue((Path(destination) / "meta.json").is_file())

    def test_rejects_bad_divider_sections_and_record_counts(self):
        with self.assertRaises(gd4.GD4TranslationError):
            gd4.parse_save("not a GD4 save")
        with self.assertRaises(gd4.GD4TranslationError):
            gd4.parse_save(gd4.DIVIDER.join([""] * 64))

        sections = self.source_text.split(gd4.DIVIDER)
        sections[0] = _nested([["0"] * 38])
        with self.assertRaises(gd4.GD4TranslationError):
            gd4.parse_save(gd4.DIVIDER.join(sections))

    def test_canonical_mappings_are_complete_and_unique(self):
        self.assertEqual(len(gd4.GD4_COUNTRY_CODES), gd4.COUNTRY_COUNT)
        self.assertEqual(len(gd4.GD4_PROVINCE_TO_GD5), gd4.WORLD_PROVINCE_COUNT)
        targets = [target for target in gd4.GD4_PROVINCE_TO_GD5 if target]
        self.assertEqual(len(targets), len(set(targets)))
        self.assertEqual(gd4.GD4_COUNTRY_CODES[:3], ["USA", "CAN", "MEX"])

    def test_factory_levels_follow_the_gd4_industry_progression(self):
        expected = {
            0: [],
            1: ["Basic Factory"],
            2: ["Basic Factory", "Basic Recruitment Center"],
            3: ["Basic Factory", "Recruitment Building Lvl 1"],
            4: ["Factory Lvl 1", "Recruitment Building Lvl 2"],
            5: ["Factory Lvl 2", "Recruitment Building Lvl 3"],
            6: ["Factory Lvl 3", "Recruitment Building Lvl 4"],
            7: ["Factory Lvl 4", "Recruitment Building Lvl 5"],
            8: ["Factory Lvl 5", "Recruitment Building Lvl 6"],
        }
        for level, buildings in expected.items():
            with self.subTest(level=level):
                self.assertEqual(gd4._industry_buildings(level), buildings)

    def test_payload_converts_date_resources_buildings_troops_and_diplomacy(self):
        payload, notes = gd4.build_save_payload(gd4.parse_save(self.source_text))
        self.assertEqual(payload["date"], {"day": 15, "month": 9, "year": 1939, "total_turns": 0})
        self.assertEqual(payload["scenario_settings"]["days_per_turn"], 30)
        self.assertEqual(payload["player_country"], "United States of America")
        self.assertEqual(payload["active_players"], ["United States of America"])
        self.assertEqual(payload["nation_data"]["United States of America"]["research"],
                         gd4.queries.get_time_appropriate_research(1939))
        self.assertEqual(payload["nation_data"]["United States of America"]["leader_title"], "President")
        self.assertEqual(payload["nation_data"]["United States of America"]["leader_name"],
                         "United States of America Leader")
        self.assertEqual(payload["nation_data"]["United States of America"]["allied_with"], [])
        self.assertEqual(payload["nation_data"]["Canada"]["allied_with"], [])
        self.assertEqual(payload["nation_data"]["United States of America"]["faction"], "")
        self.assertEqual(payload["nation_data"]["Canada"]["faction"], "")
        self.assertIn("Mexico", payload["nation_data"]["United States of America"]["at_war_with"])
        self.assertIn("United States of America", payload["nation_data"]["Mexico"]["at_war_with"])

        with open(ROOT / "base_maps" / "GD4" / "map_data.json", encoding="utf-8") as handle:
            base_map = json.load(handle)
        key = next(key for key, province in base_map.items()
                   if province["id"] == gd4.GD4_PROVINCE_TO_GD5[0])
        province = payload["provinces"][key]
        self.assertEqual(province["resources"], {"Oil": 25})
        self.assertEqual(province["buildings"],
                         ["Factory Lvl 2", "Recruitment Building Lvl 3", "Fort Lvl 3"])
        self.assertEqual(len(province["units"]), 2)
        self.assertEqual(province["units"][0]["health"], province["units"][0]["max_health"])
        self.assertEqual(province["units"][1]["health"], province["units"][1]["max_health"] * 0.1)
        self.assertTrue(all("nav" not in unit["type"].lower() for unit in province["units"]))
        self.assertTrue(any("navy" in note for note in notes))
        second_key = next(key for key, item in base_map.items()
                          if item["id"] == gd4.GD4_PROVINCE_TO_GD5[1])
        self.assertEqual(payload["provinces"][second_key]["resources"], {})

    def test_translated_save_loads_through_the_normal_map_loader(self):
        from tests import app_harness
        app_harness.boot()
        import main

        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "fixture.txt"
            source.write_text(self.source_text, encoding="utf-8")
            destination, _notes = gd4.translate_file(str(source), saves_dir=temporary)
            second_destination, _notes = gd4.translate_file(str(source), saves_dir=temporary)
            self.assertNotEqual(destination, second_destination)
            self.assertTrue((Path(destination) / "meta.json").is_file())
            self.assertTrue((Path(destination) / "political.png").is_file())

            loaded = main.Map(load_path=destination, is_scenario=False, num_players=1)
            self.assertEqual(loaded.time_manager.year, 1939)
            self.assertEqual(loaded.time_manager.month_index, 9)
            self.assertEqual(loaded.time_manager.day, 15)
            self.assertEqual(loaded.scenario_settings["days_per_turn"], 30)
            self.assertEqual(loaded.player_country, "United States of America")
            self.assertEqual(loaded.id_to_province[gd4.GD4_PROVINCE_TO_GD5[0]]["owner"],
                             "United States of America")
            # This is where a persisted "None" player country used to crash.
            loaded.update()


if __name__ == "__main__":
    unittest.main()
