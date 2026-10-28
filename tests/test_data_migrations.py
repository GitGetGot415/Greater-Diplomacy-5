"""Older data keeps its meaning after conversion and serialization."""

import copy
import gzip
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from data import constants as c, migrations, queries
from data.map import history_io, load_map
from map_logic.diplomacy import diplomacy_lifecycle

ROOT = Path(__file__).resolve().parents[1]


def round_trip(value):
    return json.loads(json.dumps(value))


def upgraded(save_meta=None, map_data=None, history=None):
    """Run every save step on unstamped fixture data and return the three parts."""
    save_meta = {} if save_meta is None else save_meta
    map_data = {} if map_data is None else map_data
    history = {} if history is None else history
    migrations.upgrade_save(save_meta, map_data, history)
    return save_meta, map_data, history


class GameVersionTests(unittest.TestCase):
    def test_version_numbers_read_stamps_and_treat_missing_stamps_as_oldest(self):
        self.assertEqual(migrations.version_number("v46"), 46)
        self.assertEqual(migrations.version_number(" v7 "), 7)
        for missing in (None, "", "46", "version 46", "v4.6", 46):
            with self.subTest(missing=missing):
                self.assertEqual(migrations.version_number(missing), 0)

    def test_game_version_matches_the_released_version(self):
        released = (ROOT / "version.txt").read_text(encoding="utf-8").strip()
        self.assertEqual(c.GAME_VERSION, released)

    def test_steps_target_released_versions_or_the_next_release(self):
        for steps in (migrations.SAVE_STEPS, migrations.MOVE_STEPS):
            targets = [target for target, _step in steps]
            self.assertEqual(targets, sorted(set(targets)))
            self.assertLessEqual(targets[-1], migrations.CURRENT_VERSION + 1)

    def test_newer_saves_are_refused_with_an_update_message(self):
        newer = f"v{migrations.CURRENT_VERSION + 1}"
        with self.assertRaisesRegex(migrations.NewerVersionError, "Update the game"):
            migrations.upgrade_save({"version": newer}, {}, {})
        with tempfile.TemporaryDirectory() as directory:
            with open(os.path.join(directory, "meta.json"), "w") as file:
                json.dump({"version": newer}, file)
            self.assertIn("Update the game", load_map.newer_version_message(directory))
            with open(os.path.join(directory, "meta.json"), "w") as file:
                json.dump({"version": c.GAME_VERSION}, file)
            self.assertIsNone(load_map.newer_version_message(directory))

    def test_only_steps_newer_than_the_save_run_and_the_save_is_stamped(self):
        calls = []
        steps = ((migrations.CURRENT_VERSION, lambda *parts: calls.append("this release")),
                 (migrations.CURRENT_VERSION + 1, lambda *parts: calls.append("next release")))
        with mock.patch.object(migrations, "SAVE_STEPS", steps):
            old = {"version": f"v{migrations.CURRENT_VERSION - 1}"}
            migrations.upgrade_save(old, {}, {})
            self.assertEqual(calls, ["this release", "next release"])
            self.assertEqual(old["version"], c.GAME_VERSION)
            calls.clear()
            # A save of this release runs only the step for the next release.
            migrations.upgrade_save(old, {}, {})
            self.assertEqual(calls, ["next release"])

    def test_the_next_release_step_is_safe_to_repeat_on_this_release(self):
        saved = {"nation_data": {"A": {"allied_with": ["B"], "research_queue": [{"tech_name": "a"}]}}}
        upgraded(saved)
        once = copy.deepcopy(saved)
        migrations.upgrade_save(saved, {}, {})
        self.assertEqual(saved, once)


class Version47StepTests(unittest.TestCase):
    def test_obsolete_country_alliances_are_removed_from_saves_and_history(self):
        for old_value in ([], ["B"], "B", None, {"invalid": True}):
            with self.subTest(old_value=old_value):
                country = {"allied_with": old_value, "faction": "Pact", "master": "B",
                           "puppets": ["C"], "future_field": {"keep": [17]}}
                expected = {key: value for key, value in country.items() if key != "allied_with"}
                history = {"1": {"nation_data": {"A": copy.deepcopy(country)}}}
                meta, _map, history = upgraded({"nation_data": {"A": country}}, history=history)
                self.assertEqual(meta["nation_data"]["A"], expected)
                self.assertEqual(history["1"]["nation_data"]["A"], expected)

    def test_old_direct_alliances_do_not_affect_current_friendship_queries(self):
        countries = {"A": {"allied_with": ["OLD"], "faction": "Pact", "puppets": ["SUB"]},
                     "B": {"faction": "Pact"}, "SUB": {"master": "A"}, "OLD": {}}
        self.assertEqual(queries.get_all_friendly_nations("A", countries), {"A", "B", "SUB"})
        with queries.diplomacy_snapshot():
            self.assertEqual(queries.get_all_friendly_nations("A", countries), {"A", "B", "SUB"})

    def test_delta_history_round_trip_keeps_converted_snapshots(self):
        history = {"1": {"nation_data": {"A": {"allied_with": ["B"], "faction": "Pact", "future": 3}}},
                   "2": {"nation_data": {"A": {"allied_with": [], "faction": "Pact", "future": 4}}}}
        decoded = history_io.decode_history(history_io.encode_history(history))
        _meta, _map, decoded = upgraded(history=decoded)
        self.assertEqual(decoded, {"1": {"nation_data": {"A": {"faction": "Pact", "future": 3}}},
                                   "2": {"nation_data": {"A": {"faction": "Pact", "future": 4}}}})
        self.assertEqual(history_io.decode_history(history_io.encode_history(decoded)), decoded)

    def test_deployment_queues_split_in_maps_meta_overlays_and_history(self):
        def province():
            return {"unit_queue": [{"unit_type": "Fixture Unit", "turns_remaining": 1}],
                    "deployment_queue": [
                        {"order_type": "BUILDING", "item_name": "Fixture Building", "turns_remaining": 2},
                        {"unit_type": "Second Unit", "turns_remaining": 3}],
                    "custom_field": {"value": 23}}
        meta = {"provinces": {"P": province()}}
        history = {"4": {"provinces": {"P": province()}}}
        _meta, map_data, history = upgraded(meta, {"P": province()}, history)
        for record in (map_data["P"], meta["provinces"]["P"], history["4"]["provinces"]["P"]):
            self.assertNotIn("deployment_queue", record)
            self.assertEqual([entry.get("unit_type") for entry in record["unit_queue"]],
                             ["Fixture Unit", "Second Unit"])
            self.assertEqual(record["building_queue"][0]["item_name"], "Fixture Building")
            self.assertEqual(record["custom_field"], {"value": 23})

    def test_research_projects_gain_points_and_keep_current_points(self):
        projects = [{"tech_name": "a", "days_remaining": 7, "custom_field": "preserved"},
                    {"tech_name": "b"}, {"tech_name": "c", "points_remaining": 0, "days_remaining": 7}]
        meta, _map, _history = upgraded({"nation_data": {"A": {"research_queue": projects}}})
        queue = meta["nation_data"]["A"]["research_queue"]
        self.assertEqual(queue[0]["points_remaining"], 7 * migrations.LEGACY_RESEARCH_POINTS_PER_DAY)
        self.assertEqual(queue[0]["custom_field"], "preserved")
        self.assertEqual(queue[1]["points_remaining"], migrations.LEGACY_RESEARCH_DEFAULT_DAYS
                         * migrations.LEGACY_RESEARCH_POINTS_PER_DAY)
        self.assertEqual(queue[2]["points_remaining"], 0)

    def test_production_day_countdowns_become_turns_with_their_existing_priority(self):
        entries = [{"days_remaining": c.DEFAULT_DAYS_PER_TURN * 3, "turns_remaining": 8,
                    "custom_field": "preserved"}, {"days_remaining": 0}, {"turns_remaining": 5}]
        _meta, map_data, _history = upgraded(map_data={"P": {"building_queue": entries}})
        self.assertEqual(map_data["P"]["building_queue"], [
            {"turns_remaining": 3, "custom_field": "preserved"}, {"turns_remaining": 1},
            {"turns_remaining": 5}])

    def test_old_replies_move_without_overwriting_current_proposals(self):
        proposal = {"action": "FIXTURE_PROPOSAL", "turns": 2, "custom_field": 7}
        pending = {"accepted": {"action": "ACCEPT_FIXTURE", "message": "reply",
                                "parameters": {"value": 9}},
                   "rejected": "REJECT_FIXTURE", "proposal": proposal}
        meta, _map, _history = upgraded({"nation_data": {"country": {"pending_diplomacy": pending}}})
        countries = meta["nation_data"]
        diplomacy_lifecycle.normalize_diplomacy_channels(countries)
        self.assertEqual(set(pending), {"proposal"})
        self.assertIs(pending["proposal"], proposal)
        responses = countries["country"]["diplo_responses"]
        self.assertEqual(responses["accepted"], {"verdict": "ACCEPT", "action": "FIXTURE",
                                               "message": "reply", "parameters": {"value": 9},
                                               "legacy_unmatched": True})
        self.assertEqual(responses["rejected"], {"verdict": "REJECT", "action": "FIXTURE",
                                               "message": "", "parameters": None,
                                               "legacy_unmatched": True})
        restored = round_trip(countries)
        diplomacy_lifecycle.normalize_diplomacy_channels(restored)
        self.assertEqual(restored, countries)

    def test_scripted_events_gain_condition_and_action_lists(self):
        old = {"condition_type": "Turn Number", "condition_val": "17",
               "action_type": "Fixture Action", "action_target": "country", "custom_field": 9}
        spawn = {"conditions": [], "fire_once": False,
                 "actions": [{"type": "Spawn Unit", "unit_type": "Biplane"}]}
        current = {"conditions": [], "actions": [], "fire_once": False}
        meta, _map, _history = upgraded({"nation_data": {"A": {"scripted_events": [
            old, spawn, copy.deepcopy(current)]}}})
        old, spawn, unchanged = meta["nation_data"]["A"]["scripted_events"]
        self.assertEqual(old["conditions"], [{"type": "Turn Number", "operator": "==",
                                             "value": "17", "chain": "AND"}])
        self.assertEqual(old["actions"], [{"type": "Fixture Action", "target": "country"}])
        self.assertTrue(old["fire_once"])
        self.assertEqual(old["custom_field"], 9)
        self.assertEqual(spawn["actions"][0]["unit_type"], "Biplane Fighter I")
        self.assertEqual(unchanged, current)

    def test_messages_and_release_requests_gain_their_required_fields(self):
        message = {"sender": "Fixture Country", "content": "Fixture message"}
        kept = {"message_id": "kept", "content": "Current message"}
        release = {"core_nation": "B", "turns_left": 2}
        meta, _map, _history = upgraded({"nation_data": {"A": {
            "inbox": [message, kept], "release_puppet_queue": [release]}}})
        self.assertTrue(message["message_id"])
        self.assertEqual(kept["message_id"], "kept")
        self.assertEqual(release["release_type"], c.PUPPET_TYPE_INTEGRATED)
        self.assertEqual(round_trip(meta), meta)

    def test_completed_realtime_saves_from_before_offline_view_open_as_spectator(self):
        meta, _map, _history = upgraded({"player_country": "None",
                                         "realtime_match": {"format": "gd5-realtime-v1"}})
        self.assertEqual(load_map._saved_player_view(meta), ("Spectator", []))

    def test_old_aircraft_names_and_truck_cargo_convert_everywhere(self):
        library = {"Biplane Fighter I": {"health": 100, "attack": 7, "defense": 4, "speed": 6,
                                         "naval_unit": False, "air_role": "fighter",
                                         "air_range": 20, "air_consumable": False}}
        land_truck = {"type": "Truck (Biplane)", "max_health": c.TRUCK_MAX_HP,
                      "health": c.TRUCK_MAX_HP / 2, "unit_id": "land", "original_max_health": 100,
                      "order": {"type": "MOVE", "path": [2]}}
        sea_truck = dict(copy.deepcopy(land_truck), unit_id="sea")
        aircraft = {"type": "Biplane", "unit_id": "air", "order": {"type": "UPGRADE", "target_type": "Jet Fighter"}}
        map_data = {"land": {"terrain": "plains", "units": [land_truck, aircraft],
                             "unit_queue": [{"unit_type": "Piston Bomber"}]},
                    "sea": {"terrain": next(iter(c.WATER_TERRAINS)), "units": [sea_truck]}}
        meta = {"nation_data": {"A": {"custom_production_units": ["Biplane", "Fixture"]}}}
        with mock.patch.object(queries, "get_unit_library", return_value=library):
            upgraded(meta, map_data)
        self.assertEqual(land_truck["type"], "Biplane Fighter I")
        self.assertEqual(land_truck["health"], 50)
        self.assertEqual(land_truck["order"], {"type": "MOVE", "path": []})
        self.assertEqual(sea_truck["type"], "Convoy (Biplane Fighter I)")
        self.assertEqual(sea_truck["unit_id"], "sea")
        self.assertEqual(aircraft["type"], "Biplane Fighter I")
        self.assertEqual(aircraft["order"]["target_type"], "Jet Fighter I")
        self.assertEqual(map_data["land"]["unit_queue"][0]["unit_type"], "Monoplane Bomber I")
        self.assertEqual(meta["nation_data"]["A"]["custom_production_units"],
                         ["Biplane Fighter I", "Fixture"])


class LoadRepairTests(unittest.TestCase):
    LIBRARY = {"Fixture Ground": {"health": 40, "attack": 6, "defense": 3, "speed": 5},
               "Fixture Ship": {"health": 90, "attack": 9, "defense": 2, "speed": 4, "naval_unit": True}}

    def test_units_take_library_stats_and_keep_their_health_fraction(self):
        ground = {"type": "Fixture Ground", "max_health": 200, "health": 100,
                  "attack": 1, "unit_id": "ground", "custom_field": 9}
        carried = {"type": "Convoy (Fixture Ground)", "original_type": "Fixture Ground",
                   "max_health": c.CONVOY_MAX_HP, "health": c.CONVOY_MAX_HP / 4,
                   "original_attack": 1, "unit_id": "carried"}
        volunteer = {"type": "Fixture Ship", "max_health": 90, "health": 30, "attack": 1}
        unknown = {"type": "Removed Fixture", "max_health": 10, "health": 5, "attack": 1}
        map_data = {"P": {"units": [ground, carried, unknown]}}
        nation_data = {"A": {"volunteer_missions": {"m": {"held_units": [{"unit": volunteer}]}}}}
        queries.refresh_unit_stats(map_data, nation_data, self.LIBRARY)
        self.assertEqual((ground["max_health"], ground["health"], ground["attack"]), (40, 20, 6))
        self.assertFalse(ground["naval_unit"])
        self.assertEqual(ground["custom_field"], 9)
        self.assertEqual((carried["original_max_health"], carried["original_attack"]), (40, 6))
        self.assertEqual((carried["max_health"], carried["health"]), (c.CONVOY_MAX_HP, c.CONVOY_MAX_HP / 4))
        self.assertEqual((volunteer["health"], volunteer["attack"]), (30, 9))
        self.assertTrue(volunteer["naval_unit"])
        self.assertEqual(unknown["attack"], 1)
        # A repeated refresh keeps exact values.
        before = copy.deepcopy(map_data)
        queries.refresh_unit_stats(map_data, nation_data, self.LIBRARY)
        self.assertEqual(map_data, before)
        self.assertEqual(round_trip(map_data), map_data)

    def test_province_repair_drops_buildings_missing_from_the_active_library(self):
        units = [{"unit_type": "Fixture Unit"}]
        resources = {"fixture_resource": 17}
        province = {"unit_queue": units, "buildings": ["Fixture Building", "Removed Building"],
                    "resources": resources, "custom_field": {"value": 23}}
        load_map._repair_province(province, {"Fixture Building": {}})
        self.assertIs(province["unit_queue"], units)
        self.assertEqual(province["building_queue"], [])
        self.assertIs(province["resources"], resources)
        self.assertEqual(province["buildings"], ["Fixture Building"])
        self.assertEqual(province["custom_field"], {"value": 23})
        malformed = {"resources": ["Oil"]}
        load_map._repair_province(malformed, {})
        self.assertEqual(malformed["resources"], {})

    def test_missing_and_duplicate_unit_ids_stay_stable_after_round_trip(self):
        units = [{"unit_id": "existing"}, {"unit_id": "existing"},
                 {"air_cargo": [{"unit_id": ""}, {}]}]
        map_data = {"province": {"units": units}}
        added = queries.ensure_unit_ids(map_data)
        all_ids = [unit["unit_id"] for unit in queries.units_with_air_cargo(units)]
        self.assertEqual(units[0]["unit_id"], "existing")
        self.assertEqual(len(added), 4)
        self.assertEqual(len(all_ids), len(set(all_ids)))
        restored = round_trip(map_data)
        self.assertEqual(queries.ensure_unit_ids(restored), [])
        self.assertEqual(restored, map_data)


class BuiltInMapTests(unittest.TestCase):
    """Every shipped base map and scenario loads through the version steps."""

    def built_in_maps(self):
        for root in (c.BASE_MAPS_DIR, c.SCENARIOS_HISTORICAL_DIR, c.SCENARIOS_ALTERNATE_DIR):
            if not os.path.isdir(ROOT / root):
                continue
            for name in sorted(os.listdir(ROOT / root)):
                path = os.path.join(root, name)
                if os.path.isfile(os.path.join(path, "map_data.json")):
                    yield path

    def test_built_in_maps_load_and_round_trip(self):
        from data.map.load_map import load_backend_state
        maps = list(self.built_in_maps())
        self.assertTrue(maps)
        for path in maps:
            with self.subTest(map=path):
                context = load_backend_state(path, is_scenario=True)
                self.assertTrue(context.map_data)
                save = round_trip(queries.build_save_dict(context, include_provinces=False))
                self.assertEqual(save["version"], c.GAME_VERSION)
                map_data = round_trip(queries.build_map_data_save(context))
                before = copy.deepcopy((save, map_data))
                # A current save passes through every step unchanged.
                migrations.upgrade_save(save, map_data, {})
                self.assertEqual((save, map_data), before)


class LibraryAndTournamentTests(unittest.TestCase):
    def test_encrypted_payload_decoder_supports_both_encodings(self):
        saved = {"country": {"custom_field": 7}}
        payload = json.dumps(saved).encode("utf-8")
        for encoded in (payload, gzip.compress(payload)):
            self.assertEqual(migrations.decode_saved_json(encoded), saved)
        with self.assertRaises(json.JSONDecodeError):
            migrations.decode_saved_json(b"invalid json")

    def test_v46_moves_convert_their_country_and_province_records(self):
        move = {"nation_data": {"allied_with": ["B"], "research_queue": [{"tech_name": "a"}]},
                "provinces": {"P": {"unit_queue": [{"unit_type": "Biplane", "days_remaining": 0}]}},
                "aircraft_orders": [], "release_subjects": [{"core_nation": "B"}]}
        migrations.upgrade_move(move)
        self.assertEqual(move["game_version"], c.GAME_VERSION)
        self.assertNotIn("allied_with", move["nation_data"])
        self.assertIn("points_remaining", move["nation_data"]["research_queue"][0])
        self.assertEqual(move["provinces"]["P"]["unit_queue"],
                         [{"unit_type": "Biplane Fighter I", "turns_remaining": 1}])
        self.assertEqual(move["release_subjects"][0]["release_type"], c.PUPPET_TYPE_INTEGRATED)

    def test_cold_imports_work_from_each_entry_point(self):
        for first in ("data.migrations", "data.constants", "data.io.settings_schema",
                      "data.queries", "map_logic.diplomacy.deal"):
            with self.subTest(first=first):
                code = (f"import {first}; from data import migrations; "
                        "from data.io import settings_schema; "
                        "from map_logic.diplomacy import deal; "
                        "assert migrations.normalize_ai_mode('LING') == 'OPENROUTER'; "
                        "assert deal.coerce('old text', 'a', 'b', deal.KIND_PEACE)['kind'] == deal.KIND_PEACE")
                result = subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                                        capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
