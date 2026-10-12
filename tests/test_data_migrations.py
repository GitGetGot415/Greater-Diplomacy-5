"""Older data keeps its meaning after conversion and serialization."""

import contextlib
import copy
import gzip
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from data import constants as c, migrations, queries


def round_trip(value):
    return json.loads(json.dumps(value))


class SavedDataMigrationTests(unittest.TestCase):
    def test_province_queues_keep_existing_entries_and_unknown_fields(self):
        units = [{"unit_type": "Fixture Unit"}]
        buildings = [{"building_type": "Fixture Building"}]
        resources = {"fixture_resource": 17}
        province = {
            "unit_queue": units, "building_queue": buildings,
            "deployment_queue": [
                {"order_type": "BUILDING", "building_type": "Fixture Building"},
                {"unit_type": "Second Unit"},
            ],
            "buildings": ["Fixture Building", "Removed Building"],
            "resources": resources, "custom_field": {"value": 23},
        }
        migrations.migrate_province_record(province, {"Fixture Building": {}})
        self.assertIs(province["unit_queue"], units)
        self.assertIs(province["building_queue"], buildings)
        self.assertIs(province["resources"], resources)
        self.assertEqual([entry["unit_type"] for entry in units], ["Fixture Unit", "Second Unit"])
        self.assertEqual(len(buildings), 2)
        self.assertNotIn("deployment_queue", province)
        self.assertEqual(province["buildings"], ["Fixture Building"])
        self.assertEqual(province["custom_field"], {"value": 23})
        restored = round_trip(province)
        migrations.migrate_province_record(restored, {"Fixture Building": {}})
        self.assertEqual(restored, province)

    def test_research_conversion_preserves_current_points(self):
        old = {"days_remaining": 7, "custom_field": "preserved"}
        migrations.migrate_research_project(old)
        self.assertEqual(old["points_remaining"], 7 * migrations.LEGACY_RESEARCH_POINTS_PER_DAY)
        restored = round_trip(old)
        migrations.migrate_research_project(restored)
        self.assertEqual(restored, old)
        current = {"points_remaining": 0, "days_remaining": 7}
        migrations.migrate_research_project(current)
        self.assertEqual(current["points_remaining"], 0)
        missing = migrations.migrate_research_project({})
        self.assertEqual(missing["points_remaining"], migrations.LEGACY_RESEARCH_DEFAULT_DAYS
                         * migrations.LEGACY_RESEARCH_POINTS_PER_DAY)

    def test_production_preserves_display_and_execution_precedence(self):
        old = {"days_remaining": c.DEFAULT_DAYS_PER_TURN * 3,
               "turns_remaining": 8, "custom_field": "preserved"}
        before = copy.deepcopy(old)
        self.assertEqual(migrations.production_queue_turns(old), 8)
        self.assertEqual(old, before)
        migrations.migrate_production_queue_item(old)
        self.assertEqual(old, {"turns_remaining": 3, "custom_field": "preserved"})
        restored = round_trip(old)
        migrations.migrate_production_queue_item(restored)
        self.assertEqual(restored, old)
        self.assertEqual(migrations.migrate_production_queue_item(
            {"days_remaining": 0})["turns_remaining"], 1)

    def test_unit_load_pipeline_preserves_version_gate_and_health_fraction(self):
        library = {
            "Fixture Ground": {"health": 40, "attack": 6, "defense": 3,
                               "speed": 5, "naval_unit": False},
            "Biplane Fighter I": {"health": 100, "attack": 7, "defense": 4,
                                  "speed": 6, "naval_unit": False, "air_role": "fighter",
                                  "air_range": 20, "air_consumable": False},
        }
        for old_version in (False, True):
            with self.subTest(old_version=old_version):
                ground = {"type": "Fixture Ground", "max_health": 200, "health": 100,
                          "attack": 1, "unit_id": "ground-id", "custom_field": 9}
                aircraft = {"type": "Biplane", "max_health": 200, "health": 100,
                            "unit_id": "air-id", "order": {"type": "MOVE", "path": [2]}}
                map_data = {"province": {"id": 1, "units": [ground, aircraft]}}
                countries = {"country": {"custom_production_units": ["Biplane"]}}
                with mock.patch.object(queries, "get_unit_library", return_value=library), \
                        contextlib.redirect_stdout(io.StringIO()):
                    version = "fixture-older-version" if old_version else c.GAME_VERSION
                    migrations.migrate_loaded_units(map_data, countries, library, version)
                    expected = copy.deepcopy(map_data)
                    migrations.migrate_loaded_units(map_data, countries, library, version)
                self.assertEqual(map_data, expected)
                self.assertIs(map_data["province"]["units"][0], ground)
                self.assertEqual(ground["health"], 20 if old_version else 100)
                self.assertEqual(ground["max_health"], 40 if old_version else 200)
                self.assertEqual(ground["attack"], 6 if old_version else 1)
                self.assertEqual(ground["custom_field"], 9)
                self.assertEqual(aircraft["type"], "Biplane Fighter I")
                self.assertEqual(aircraft["health"], 50)
                self.assertEqual(aircraft["order"], {"type": "MOVE", "path": []})
                self.assertEqual(countries["country"]["custom_production_units"], ["Biplane Fighter I"])
                self.assertEqual(round_trip(map_data), map_data)

    def test_missing_and_duplicate_unit_ids_stay_stable_after_round_trip(self):
        units = [{"unit_id": "existing"}, {"unit_id": "existing"},
                 {"air_cargo": [{"unit_id": ""}, {}]}]
        map_data = {"province": {"units": units}}
        added = migrations.ensure_unit_ids(map_data)
        all_ids = [unit["unit_id"] for unit in queries.units_with_air_cargo(units)]
        self.assertEqual(units[0]["unit_id"], "existing")
        self.assertEqual(len(added), 4)
        self.assertEqual(len(all_ids), len(set(all_ids)))
        restored = round_trip(map_data)
        self.assertEqual(migrations.ensure_unit_ids(restored), [])
        self.assertEqual(restored, map_data)

    def test_old_replies_move_without_overwriting_current_proposals(self):
        proposal = {"action": "FIXTURE_PROPOSAL", "turns": 2, "custom_field": 7}
        pending = {"accepted": {"action": "ACCEPT_FIXTURE", "message": "reply",
                                "parameters": {"value": 9}},
                   "rejected": "REJECT_FIXTURE", "proposal": proposal}
        responses = {}
        countries = {"country": {"pending_diplomacy": pending, "diplo_responses": responses}}
        migrations.migrate_pending_responses(countries)
        self.assertIs(countries["country"]["pending_diplomacy"], pending)
        self.assertIs(countries["country"]["diplo_responses"], responses)
        self.assertEqual(pending, {"proposal": proposal})
        self.assertIs(pending["proposal"], proposal)
        self.assertEqual(responses["accepted"], {"verdict": "ACCEPT", "action": "FIXTURE",
                                               "message": "reply", "parameters": {"value": 9}})
        self.assertEqual(responses["rejected"], {"verdict": "REJECT", "action": "FIXTURE",
                                               "message": "", "parameters": None})
        restored = round_trip(countries)
        migrations.migrate_pending_responses(restored)
        self.assertEqual(restored, countries)

    def test_scripted_forecast_reads_old_fields_without_mutation(self):
        old = {"condition_type": "Turn Number", "condition_val": "17",
               "action_type": "Fixture Action", "action_target": "country",
               "custom_field": 9}
        before = copy.deepcopy(old)
        conditions = migrations.scripted_event_conditions(old)
        actions = migrations.scripted_event_actions(old)
        self.assertEqual(conditions, [{"type": "Turn Number", "operator": "==",
                                      "value": "17", "chain": "AND"}])
        self.assertEqual(actions, [{"type": "Fixture Action", "target": "country"}])
        self.assertEqual(old, before)
        migrations.migrate_scripted_event(old)
        self.assertEqual(old["conditions"], conditions)
        self.assertTrue(old["fire_once"])
        restored = round_trip(old)
        migrations.migrate_scripted_event(restored)
        self.assertEqual(restored, old)
        current = {"conditions": [], "actions": [], "fire_once": False}
        migrations.migrate_scripted_event(current)
        self.assertEqual(current, {"conditions": [], "actions": [], "fire_once": False})

    def test_message_reference_is_added_once_and_saved(self):
        message = {"sender": "Fixture Country", "content": "Fixture message"}
        reference = migrations.ensure_message_id(message)
        restored = round_trip(message)
        self.assertTrue(reference)
        self.assertEqual(migrations.ensure_message_id(restored), reference)
        self.assertEqual(restored, message)

    def test_encrypted_payload_decoder_supports_both_encodings(self):
        saved = {"country": {"custom_field": 7}}
        payload = json.dumps(saved).encode("utf-8")
        for encoded in (payload, gzip.compress(payload)):
            self.assertEqual(migrations.decode_saved_json(encoded), saved)
        with self.assertRaises(json.JSONDecodeError):
            migrations.decode_saved_json(b"invalid json")

    def test_tournament_formats_preserve_explicit_request_priority(self):
        country = {"release_puppet_queue": [{"core_nation": "old"}]}
        existing = [{"core_nation": "host"}]
        self.assertEqual(migrations.tournament_move_sections(country), (country, {}))
        payload = {"nation_data": country, "provinces": {"province": {}}, "release_subjects": []}
        self.assertEqual(migrations.tournament_move_sections(payload), (country, payload["provinces"]))
        self.assertEqual(migrations.tournament_release_requests(payload, country, existing), [])
        self.assertEqual(migrations.tournament_release_requests({}, country, existing), country["release_puppet_queue"])
        self.assertIs(migrations.tournament_release_requests({}, {}, existing), existing)

    def test_cold_imports_work_from_each_entry_point(self):
        root = Path(__file__).resolve().parents[1]
        for first in ("data.migrations", "data.constants", "data.io.settings_schema",
                      "data.queries", "map_logic.diplomacy.deal"):
            with self.subTest(first=first):
                code = (f"import {first}; from data import migrations; "
                        "from data.io import settings_schema; "
                        "from map_logic.diplomacy import deal; "
                        "assert migrations.normalize_ai_mode('LING') == 'OPENROUTER'; "
                        "assert deal.coerce('old text', 'a', 'b', deal.KIND_PEACE)['kind'] == deal.KIND_PEACE")
                result = subprocess.run([sys.executable, "-c", code], cwd=root,
                                        capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_old_aircraft_snapshots_supply_drafts_without_submitted_stats(self):
        snapshot = {"unit_id": "fixture-aircraft", "type": "Fixture Aircraft",
                    "order": {"type": "MOVE", "path": []}, "custom_name": "Fixture Name",
                    "attack": 999, "health": 999, "position": 999}
        provinces = {"province": {"units": [snapshot]}}
        before = copy.deepcopy(provinces)
        with mock.patch.object(queries, "get_unit_library", return_value={
                "Fixture Aircraft": {"air_role": "fighter"}}):
            commands = migrations.tournament_aircraft_commands({}, provinces, {"fixture-aircraft"})
            self.assertEqual(commands, [{"unit_id": "fixture-aircraft", "order": snapshot["order"],
                                         "custom_name": "Fixture Name"}])
            self.assertEqual(migrations.tournament_aircraft_commands(
                {"aircraft_orders": []}, provinces, {"fixture-aircraft"}), [])
        self.assertEqual(provinces, before)
