"""Older data keeps its meaning after conversion and serialization."""

import copy
import gzip
import json
import os
import re
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


from data import constants as c, migrations, queries
from data.map import history_io, load_map
from map_logic.diplomacy import diplomacy_lifecycle
from scripts.data import write_released_content
from tests import add_test_cases
from data.migrations import released_content
from tests.migration_fixtures import malformed_records

ROOT = Path(__file__).resolve().parents[1]
#: A stamp from an older release. Conversion does not depend on it.
PREVIOUS_VERSION = f"v{migrations.CURRENT_VERSION - 1}"


def round_trip(value):
    return json.loads(json.dumps(value))


def upgraded(save_meta=None, map_data=None, history=None):
    """Convert unstamped fixture data as a load does. Convert each snapshot as a selected turn."""
    save_meta = {} if save_meta is None else save_meta
    map_data = {} if map_data is None else map_data
    history = {} if history is None else history
    migrations.upgrade_save(save_meta, map_data)
    for snapshot in history.values():
        migrations.upgrade_history_turn(snapshot, map_data)
    return save_meta, map_data, history


class GameVersionTests(unittest.TestCase):
    def test_version_numbers_read_stamps_and_treat_missing_stamps_as_oldest(self):
        self.assertEqual(migrations.version_number("v46"), 46)
        self.assertEqual(migrations.version_number(" v7 "), 7)
        for missing in (None, "", "46", "version 46", "v4.6", 46):
            with self.subTest(missing=missing):
                self.assertEqual(migrations.version_number(missing), 0)

    def test_game_version_is_not_older_than_the_released_version(self):
        # version.txt names the last release. GAME_VERSION names the version in development.
        released = (ROOT / "version.txt").read_text(encoding="utf-8").strip()
        self.assertGreaterEqual(migrations.CURRENT_VERSION, migrations.version_number(released))

    def test_newer_saves_are_refused_with_an_update_message(self):
        newer = f"v{migrations.CURRENT_VERSION + 1}"
        with self.assertRaisesRegex(migrations.NewerVersionError, "Update the game"):
            migrations.upgrade_save({"version": newer}, {})
        with tempfile.TemporaryDirectory() as directory:
            with open(os.path.join(directory, "meta.json"), "w") as file:
                json.dump({"version": newer}, file)
            self.assertIn("Update the game", load_map.newer_version_message(directory))
            with open(os.path.join(directory, "meta.json"), "w") as file:
                json.dump({"version": c.GAME_VERSION}, file)
            self.assertIsNone(load_map.newer_version_message(directory))

    def test_every_save_converts_whatever_version_wrote_it(self):
        # Conversion never depends on the stamp. The stamp only refuses newer saves.
        for stamp in (None, "v20", PREVIOUS_VERSION, c.GAME_VERSION):
            with self.subTest(stamp=stamp):
                saved = {"nation_data": {"A": {"allied_with": ["B"]}}}
                if stamp is not None:
                    saved["version"] = stamp
                migrations.upgrade_save(saved, {})
                self.assertNotIn("allied_with", saved["nation_data"]["A"])
                self.assertEqual(saved["version"], c.GAME_VERSION)

    def test_summit_records_are_dropped_and_other_country_data_stays(self):
        saved = {"nation_data": {"A": {
            "ai_commitments": [{"id": "A|B|NON_AGGRESSION|3", "with": "B"}],
            "summit_log": {"B": 3}, "ai_notebook": "Watch B.",
            "temp_modifiers": {"B": {"kept_word": 15}}}}}
        migrations.upgrade_save(saved, {})
        country = saved["nation_data"]["A"]
        self.assertNotIn("ai_commitments", country)
        self.assertNotIn("summit_log", country)
        self.assertEqual(country["ai_notebook"], "Watch B.")
        self.assertEqual(country["temp_modifiers"], {"B": {"kept_word": 15}})

    def test_every_move_converts_whatever_version_wrote_it(self):
        for stamp in (None, PREVIOUS_VERSION, c.GAME_VERSION):
            with self.subTest(stamp=stamp):
                move = {"nation_data": {"allied_with": ["B"]}, "provinces": {},
                        "aircraft_orders": [], "release_subjects": []}
                if stamp is not None:
                    move["game_version"] = stamp
                self.assertEqual(migrations.upgrade_move(move), migrations.version_number(stamp))
                self.assertNotIn("allied_with", move["nation_data"])
                self.assertEqual(move["game_version"], c.GAME_VERSION)
        with self.assertRaisesRegex(migrations.NewerVersionError, "Update the game"):
            migrations.upgrade_move({"game_version": f"v{migrations.CURRENT_VERSION + 1}"})
        # A move without the later sections converts. It is not refused.
        move = {"nation_data": {}, "provinces": {}}
        migrations.upgrade_move(move)
        self.assertEqual(move["aircraft_orders"], [])

    def test_country_only_moves_convert_to_the_snapshot_shape(self):
        """The oldest moves held only the country record."""
        move = {"allied_with": ["B"], "materials": 5, "tournament_turn": 3,
                "release_puppet_queue": [{"core_nation": "B"}]}
        migrations.upgrade_move(move)
        release = {"core_nation": "B", "release_type": c.PUPPET_TYPE_INTEGRATED}
        self.assertEqual(move["nation_data"], {"materials": 5, "release_puppet_queue": [release]})
        self.assertEqual(move["provinces"], {})
        self.assertEqual(move["tournament_turn"], 3)
        self.assertEqual(move["release_subjects"], [release])
        self.assertEqual(move["aircraft_orders"], [])
        self.assertIs(move["unit_snapshot"], False)
        once = copy.deepcopy(move)
        migrations.upgrade_move(move)
        self.assertEqual(move, once)

    def test_older_moves_read_aircraft_orders_from_whole_aircraft_records(self):
        library = queries.get_unit_library()
        aircraft = next(name for name in library if queries.is_air_unit({"type": name}))
        ground = next(name for name in library if not queries.is_air_unit({"type": name}))
        order = {"type": "MOVE", "path": [2]}
        move = {"nation_data": {}, "provinces": {"P": {"units": [
            {"unit_id": "air", "type": aircraft, "order": order, "custom_name": "Ace", "health": 1},
            {"unit_id": "foot", "type": ground, "order": None}]}}}
        migrations.upgrade_move(move)
        self.assertEqual(move["aircraft_orders"], [{"unit_id": "air", "order": order, "custom_name": "Ace"}])
        self.assertIs(move["unit_snapshot"], True)

    def test_current_move_sections_do_not_change(self):
        move = {"nation_data": {"release_puppet_queue": []}, "provinces": {"P": {"units": []}},
                "aircraft_orders": [{"unit_id": "air", "order": None, "custom_name": None}],
                "release_subjects": [], "unit_snapshot": True, "player_intents": [],
                "game_version": c.GAME_VERSION}
        once = copy.deepcopy(move)
        migrations.upgrade_move(move)
        self.assertEqual(move, once)

    def test_saves_leave_history_until_a_player_selects_a_turn(self):
        snapshot = {"nation_data": {"A": {"allied_with": ["B"]}}}
        history = {"1": snapshot}
        migrations.upgrade_save({}, {})
        self.assertEqual(snapshot, {"nation_data": {"A": {"allied_with": ["B"]}}})
        migrations.upgrade_history_turn(history["1"], {})
        self.assertEqual(snapshot, {"nation_data": {"A": {}}})

    def test_conversion_is_safe_to_repeat(self):
        saved = {"nation_data": {"A": {"allied_with": ["B"], "research_queue": [{"tech_name": "a"}]}}}
        upgraded(saved)
        once = copy.deepcopy(saved)
        migrations.upgrade_save(saved, {})
        self.assertEqual(saved, once)


class OlderFormatTests(unittest.TestCase):
    def test_older_unit_names_convert_in_all_saved_references_and_repeat_safely(self):
        for older, current in migrations.LEGACY_UNIT_NAMES.items():
            with self.subTest(unit=older):
                unit = {"unit_id": "keep-id", "owner": "A", "type": older,
                        "health": 11, "max_health": 20,
                        "order": {"type": "UPGRADE", "target_type": older, "turns_left": 2},
                        "future_field": {"keep": True}}
                province = {"terrain": "plains", "units": [unit,
                            {"type": f"Convoy ({older})", "original_type": older},
                            {"type": "Jet Transport I", "air_cargo": [copy.deepcopy(unit)]}],
                            "unit_queue": [{"unit_type": older, "turns_remaining": 3, "paid_materials": 17}]}
                country = {"custom_production_units": [older, current], "research": {"unrelated": 2},
                           "scripted_events": [{"conditions": [], "actions": [
                               {"type": "Spawn Unit", "unit_type": older}]}]}
                saved = {"version": PREVIOUS_VERSION, "nation_data": {"A": country},
                         "provinces": {"P": copy.deepcopy(province)}, "future_field": [7]}
                raw = {"P": copy.deepcopy(province)}
                history = {"1": {"nation_data": {"A": copy.deepcopy(country)},
                                 "provinces": {"P": copy.deepcopy(province)}}}
                upgraded(saved, raw, history)
                for record in (saved, history["1"]):
                    self.assertEqual(record["nation_data"]["A"]["custom_production_units"], [current])
                    self.assertEqual(record["nation_data"]["A"]["scripted_events"][0]
                                     ["actions"][0]["unit_type"], current)
                    self.assertEqual(record["nation_data"]["A"]["research"], {"unrelated": 2})
                for converted in (raw["P"], saved["provinces"]["P"], history["1"]["provinces"]["P"]):
                    self.assertEqual(converted["units"][0], dict(unit, type=current,
                                     order={"type": "UPGRADE", "target_type": current, "turns_left": 2}))
                    self.assertEqual(converted["units"][1],
                                     {"type": f"Convoy ({current})", "original_type": current})
                    self.assertEqual(converted["units"][2]["air_cargo"][0]["type"], current)
                    self.assertEqual(converted["unit_queue"],
                                     [{"unit_type": current, "turns_remaining": 3, "paid_materials": 17}])
                self.assertEqual(saved["future_field"], [7])
                once = copy.deepcopy((saved, raw, history))
                upgraded(saved, raw, history)
                self.assertEqual((saved, raw, history), once)
                self.assertEqual(round_trip(saved), saved)

    def test_older_unit_names_convert_in_tournament_projections_and_intents(self):
        for older, current in migrations.LEGACY_UNIT_NAMES.items():
            with self.subTest(unit=older):
                move = {"game_version": PREVIOUS_VERSION,
                        "nation_data": {"custom_production_units": [older, current]},
                        "provinces": {"P": {"unit_queue": [{"unit_type": older, "turns_remaining": 3}]}},
                        "aircraft_orders": [{"order": {"type": "UPGRADE", "target_type": older}}],
                        "release_subjects": [], "player_intents": [
                            {"type": "province_queue", "queue": "unit_queue", "items": [{"unit_type": older}]},
                            {"type": "unit_order", "order": {"type": "UPGRADE", "target_type": older}},
                            {"type": "country_preferences", "custom_production_units": [older, current]}]}
                migrations.upgrade_move(move)
                self.assertEqual(move["nation_data"]["custom_production_units"], [current])
                self.assertEqual(move["provinces"]["P"]["unit_queue"][0]["unit_type"], current)
                self.assertEqual(move["aircraft_orders"][0]["order"]["target_type"], current)
                self.assertEqual(move["player_intents"][0]["items"][0]["unit_type"], current)
                self.assertEqual(move["player_intents"][1]["order"]["target_type"], current)
                self.assertEqual(move["player_intents"][2]["custom_production_units"], [current])
                once = copy.deepcopy(move)
                migrations.upgrade_move(move)
                self.assertEqual(move, once)

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
        for entry in entries:
            entry["item_name"] = "Fixture Building"
        _meta, map_data, _history = upgraded(map_data={"P": {"building_queue": entries}})
        self.assertEqual(map_data["P"]["building_queue"], [
            {"item_name": "Fixture Building", "turns_remaining": 3, "custom_field": "preserved"},
            {"item_name": "Fixture Building", "turns_remaining": 1},
            {"item_name": "Fixture Building", "turns_remaining": 5}])

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


class ResearchChangeTests(unittest.TestCase):
    """Technologies gained new prerequisites, and some maximum levels went down."""
    TREE = {"base": {"max_lvl": 3, "req": {}},
            "middle": {"max_lvl": 2, "req": {"base": 2}},
            "top": {"max_lvl": 2, "req": {"middle": 1}},
            "capped": {"max_lvl": 4, "req": {}}}

    def test_owned_technologies_receive_their_prerequisites_once(self):
        country = {"research": {"top": 1, "capped": 2, "unknown_tech": 5, "infantry_type": 30}}
        complete = {"research": {"base": 3, "middle": 2, "top": 2}}
        saved = {"nation_data": {"A": country, "B": complete}, "default_research": {"top": 1}}
        migrations.grant_research_prerequisites(saved, self.TREE)
        self.assertEqual(country["research"], {"top": 1, "middle": 1, "base": 2, "capped": 2,
                                               "unknown_tech": 5, "infantry_type": 30})
        self.assertEqual(saved["default_research"], {"top": 1, "middle": 1, "base": 2})
        self.assertEqual(complete["research"], {"base": 3, "middle": 2, "top": 2})
        once = copy.deepcopy(saved)
        migrations.grant_research_prerequisites(saved, self.TREE)
        self.assertEqual(saved, once)

    def test_levels_above_the_active_maximum_are_lowered_and_finished_projects_removed(self):
        country = {"research": {"capped": 9, "base": 1, "infantry_type": 500},
                   "research_queue": [{"tech_name": "capped", "points_remaining": 5},
                                      {"tech_name": "base", "points_remaining": 5}],
                   "research_progress": {"capped": 3}, "current_research": "capped"}
        saved = {"nation_data": {"A": country}, "default_research": {"capped": 7}}
        migrations.clamp_research_levels(saved, self.TREE)
        # The equipment tracks keep levels beyond a content cap. See migrate_infantry_research.
        self.assertEqual(country["research"], {"capped": 4, "base": 1, "infantry_type": 500})
        self.assertEqual(country["research_queue"], [{"tech_name": "base", "points_remaining": 5}])
        self.assertEqual(country["research_progress"], {})
        self.assertIsNone(country["current_research"])
        self.assertEqual(saved["default_research"], {"capped": 4})

    def test_projects_at_the_active_cap_are_removed_without_changing_other_work(self):
        country = {"research": {"capped": self.TREE["capped"]["max_lvl"], "base": 1},
                   "research_queue": [{"tech_name": "capped", "points_remaining": 13},
                                      {"tech_name": "base", "points_remaining": 17}],
                   "research_progress": {"capped": 13, "base": 17}, "current_research": "capped"}
        saved = {"nation_data": {"A": country}, "default_research": copy.deepcopy(country["research"])}
        queue = country["research_queue"]
        migrations.clamp_research_levels(saved, self.TREE)
        self.assertEqual(country["research"], saved["default_research"])
        self.assertIs(country["research_queue"], queue)
        self.assertEqual(queue, [{"tech_name": "base", "points_remaining": 17}])
        self.assertEqual(country["research_progress"], {"base": 17})
        self.assertIsNone(country["current_research"])
        restored = round_trip(saved)
        migrations.clamp_research_levels(restored, self.TREE)
        self.assertEqual(restored, saved)


class MigrationBoundaryTests(unittest.TestCase):
    """Conversion visits known records and preserves unrelated saved data."""

    OLDER = "Older Fixture Unit"
    CURRENT = "Fixture Unit I"

    def setUp(self):
        aliases = mock.patch("data.migrations.conversions.equipment_stage_aliases",
                             return_value={self.OLDER: self.CURRENT})
        aliases.start()
        self.addCleanup(aliases.stop)

    def test_faction_border_maps_survive_country_conversion_and_research_repairs(self):
        borders = {name: {"(1, 2, 3)": self.OLDER} for name in (
            "allied_with", "research_queue", "research", "research_progress", "inbox",
            "scripted_events", "custom_production_units", "pending_diplomacy", "volunteer_missions")}
        countries = {"FACTION_WAR_MAPS": copy.deepcopy(borders), "A": {"allied_with": ["B"]},
                     "GLOBAL_EVENTS": {"scripted_events": [{"conditions": [], "actions": [
                         {"type": "Spawn Unit", "unit_type": self.OLDER}]}]}}
        saved = {"nation_data": copy.deepcopy(countries)}
        history = {"1": {"nation_data": copy.deepcopy(countries)}}
        upgraded(saved, history=history)
        migrations.migrate_infantry_research(saved, {}, history)
        for record in (saved, history["1"]):
            migrations.clamp_research_levels(record, {})
            migrations.grant_research_prerequisites(record, {})
            self.assertEqual(record["nation_data"]["FACTION_WAR_MAPS"], borders)
            self.assertEqual(record["nation_data"]["A"], {})
            action = record["nation_data"]["GLOBAL_EVENTS"]["scripted_events"][0]["actions"][0]
            self.assertEqual(action["unit_type"], self.CURRENT)
        restored = round_trip(saved)
        migrations.upgrade_save(restored, {})
        self.assertEqual(restored, saved)

    def test_unknown_fields_survive_save_history_and_both_move_formats(self):
        unknown = {key: self.OLDER for key in ("type", "unit_type", "original_type", "target_type")}
        unknown["custom_production_units"] = [self.OLDER, self.OLDER]
        unknown["units"] = [{"type": self.OLDER}]
        order = {"type": "UPGRADE", "target_type": self.OLDER, "future_field": copy.deepcopy(unknown)}
        unit = {"type": self.OLDER, "order": copy.deepcopy(order), "future_field": copy.deepcopy(unknown)}
        carrier = {"type": "Fixture Carrier I", "air_cargo": [copy.deepcopy(unit)],
                   "future_field": copy.deepcopy(unknown)}
        country = {"custom_production_units": [self.OLDER, self.CURRENT],
                   "future_field": copy.deepcopy(unknown), "volunteer_missions": {
                       "B": {"held_units": [{"unit": copy.deepcopy(unit), "future_field": copy.deepcopy(unknown)}],
                             "future_field": copy.deepcopy(unknown)}},
                   "scripted_events": [{"conditions": [], "future_field": copy.deepcopy(unknown), "actions": [
                       {"type": "Spawn Unit", "unit_type": self.OLDER, "future_field": copy.deepcopy(unknown)},
                       {"type": "Fixture Action", "unit_type": self.OLDER}]}]}
        province = {"units": [copy.deepcopy(unit), carrier], "future_field": copy.deepcopy(unknown),
                    "unit_queue": [{"unit_type": self.OLDER, "future_field": copy.deepcopy(unknown)}]}
        saved = {"nation_data": {"A": copy.deepcopy(country)}, "future_field": copy.deepcopy(unknown)}
        raw = {"P": copy.deepcopy(province)}
        snapshot = {"nation_data": {"A": copy.deepcopy(country)}, "provinces": {"P": copy.deepcopy(province)},
                    "future_field": copy.deepcopy(unknown)}
        upgraded(saved, raw, {"1": snapshot})
        records = [saved, raw, snapshot]
        for intents in (False, True):
            move = {"nation_data": copy.deepcopy(country), "provinces": {"P": copy.deepcopy(province)},
                    "aircraft_orders": [{"order": copy.deepcopy(order), "future_field": copy.deepcopy(unknown)}],
                    "future_field": copy.deepcopy(unknown)}
            if intents:
                move["player_intents"] = [
                    {"type": "unit_order", "order": copy.deepcopy(order), "future_field": copy.deepcopy(unknown)},
                    {"type": "province_queue", "queue": "unit_queue", "items": [
                        {"unit_type": self.OLDER, "future_field": copy.deepcopy(unknown)}]},
                    {"type": "country_preferences", "custom_production_units": [self.OLDER, self.CURRENT]}]
            migrations.upgrade_move(move)
            self.assertEqual(move["nation_data"]["volunteer_missions"]["B"]["held_units"][0]["unit"]["type"],
                             self.CURRENT)
            self.assertEqual(move["aircraft_orders"][0]["order"]["target_type"], self.CURRENT)
            if intents:
                self.assertEqual(move["player_intents"][0]["order"]["target_type"], self.CURRENT)
                self.assertEqual(move["player_intents"][1]["items"][0]["unit_type"], self.CURRENT)
                self.assertEqual(move["player_intents"][2]["custom_production_units"], [self.CURRENT])
            once = round_trip(move)
            migrations.upgrade_move(move)
            self.assertEqual(move, once)
            records.append(move)
        self.assertEqual(raw["P"]["units"][1]["air_cargo"][0]["type"], self.CURRENT)
        for record in (saved, snapshot):
            converted = record["nation_data"]["A"]
            self.assertEqual(converted["custom_production_units"], [self.CURRENT])
            self.assertEqual(converted["scripted_events"][0]["actions"][1]["unit_type"], self.OLDER)
            self.assertEqual(converted["volunteer_missions"]["B"]["held_units"][0]["unit"]["order"]["target_type"],
                             self.CURRENT)

        def check_unknown_fields(record):
            if isinstance(record, dict):
                for key, value in record.items():
                    if key == "future_field":
                        self.assertEqual(value, unknown)
                    else:
                        check_unknown_fields(value)
            elif isinstance(record, list):
                for value in record:
                    check_unknown_fields(value)

        check_unknown_fields(round_trip(records))


class MalformedInputTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(mock.patch("builtins.print"))
        self.enterContext(mock.patch("data.migrations.conversions.equipment_stage_aliases", return_value={}))

    def test_malformed_local_records_recover_and_player_moves_still_reject(self):
        for field, country, province in malformed_records():
            for source in ("save", "history", "snapshot", "intents"):
                with self.subTest(field=field, source=source):
                    saved = {"nation_data": {"A": copy.deepcopy(country)},
                             "provinces": {"P": copy.deepcopy(province)}}
                    if source == "save":
                        migrations.upgrade_save(saved, {})
                    elif source == "history":
                        migrations.upgrade_history_turn(saved, {})
                    else:
                        move = {"nation_data": copy.deepcopy(country),
                                "provinces": {"P": copy.deepcopy(province)}}
                        if source == "intents":
                            move["player_intents"] = []
                        with self.assertRaisesRegex(ValueError, re.escape(field)):
                            migrations.upgrade_move(move)

    def test_research_repairs_recover_malformed_containers_without_format_conversion(self):
        for field, country, province in malformed_records():
            if not country or not field.startswith(("research", "current_research")):
                continue
            for repair in (migrations.migrate_infantry_research, migrations.clamp_research_levels,
                           migrations.grant_research_prerequisites):
                with self.subTest(field=field, repair=repair.__name__):
                    repaired = {"nation_data": {"A": copy.deepcopy(country)}}
                    repair(repaired, {})
                    before = round_trip(repaired)
                    repair(repaired, {})
                    self.assertEqual(repaired, before)

    def test_unselected_history_only_repairs_research(self):
        snapshot = {"nation_data": {"A": {"research": {"infantry_type": 1}}},
                    "provinces": {"P": {"deployment_queue": None}}}
        history = {"1": copy.deepcopy(snapshot)}
        migrations.migrate_infantry_research({}, {}, history)
        self.assertEqual(history["1"], snapshot)
        history["1"]["nation_data"]["A"]["research_progress"] = None
        migrations.migrate_infantry_research({}, {}, history)
        self.assertEqual(history["1"]["nation_data"]["A"]["research_progress"], {})
        self.assertIsNone(history["1"]["provinces"]["P"]["deployment_queue"])
        migrations.upgrade_history_turn(history["1"], {})
        self.assertNotIn("deployment_queue", history["1"]["provinces"]["P"])

    def test_invalid_envelopes_and_map_records_raise_value_errors(self):
        for value in (None, [], 7):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "meta"):
                    migrations.upgrade_save(value, {})
                with self.assertRaisesRegex(ValueError, "move"):
                    migrations.upgrade_move(value)
                with self.assertRaisesRegex(ValueError, "map_data"):
                    migrations.upgrade_save({}, value)
                migrations.upgrade_save({}, {"P": value})

    def test_recovered_disk_save_can_process_queues_and_reload(self):
        from map_logic.system32 import economy_processor, research_processor

        source = ROOT / next(BuiltInMapTests.built_in_maps())
        _meta, original, _history = load_map.read_save_files(source)
        key, province = next(iter(original.items()))
        province = copy.deepcopy(province)
        country = "Recovery Fixture"
        library = queries.get_unit_library()
        unit_type = next(name for name, stats in library.items()
                         if not stats.get("naval_unit") and not stats.get("air_role"))
        unit = queries.create_unit_dict(unit_type, country, library)
        unit.update(health="unreadable", order=[])
        paid = {"unit_type": unit_type, "turns_remaining": 2, "refund": {"cost_materials": 17}}
        province.update(owner=country, terrain="plains", units=[None, unit], buildings=[],
                        building_queue=[{"order_type": "BUILDING", "item_name": []}],
                        unit_queue=[copy.deepcopy(paid), None])
        saved = {"version": PREVIOUS_VERSION,
                 "date": {"year": c.START_YEAR, "month": 0, "day": 1, "total_turns": 0},
                 "nation_data": {country: {
            "is_playable": True, "research": {}, "research_progress": None, "research_queue": [None],
            "inbox": None}}, "player_country": country, "active_players": [country]}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copyfile(source / "id_map.png", root / "id_map.png")
            (root / "meta.json").write_text(json.dumps(saved))
            (root / "map_data.json").write_text(json.dumps({key: province}))
            game = load_map.load_backend_state(root, skip_initial_income=True,
                                               scenario_settings=queries.get_default_scenario_settings())
            loaded = next(iter(game.map_data.values()))
            self.assertEqual(len(loaded["units"]), 1)
            self.assertEqual(loaded["units"][0]["health"], library[unit_type]["health"])
            self.assertEqual(loaded["unit_queue"], [paid])
            self.assertEqual(loaded["building_queue"], [])
            self.assertEqual(game.nation_data[country]["research_progress"], {})
            research_processor.process_national_research(game)
            economy_processor.process_queues(game)
            self.assertEqual(loaded["unit_queue"][0]["turns_remaining"], 1)
            current = queries.build_save_dict(game, include_provinces=False)
            (root / "meta.json").write_text(json.dumps(current))
            (root / "map_data.json").write_text(json.dumps(queries.build_map_data_save(game)))
            restored = load_map.load_backend_state(root, skip_initial_income=True,
                                                   scenario_settings=queries.get_default_scenario_settings())
            economy_processor.process_queues(restored)
            self.assertEqual(next(iter(restored.map_data.values()))["unit_queue"], [])

    def test_local_identity_repairs_and_unknown_refund_fields_remain_supported(self):
        unit = {"unit_id": [], "type": "Fixture"}
        raw = {"P": {"units": [unit], "unit_queue": [
            {"unit_type": "Fixture", "turns_remaining": 3,
             "refund": {"cost_materials": 7, "future_receipt": {"text": "kept"}}}]}}
        migrations.upgrade_save({}, raw)
        self.assertEqual(unit["unit_id"], [])
        queries.ensure_unit_ids(raw)
        self.assertIsInstance(unit["unit_id"], str)
        self.assertEqual(raw["P"]["unit_queue"][0]["refund"]["future_receipt"], {"text": "kept"})
        before = round_trip(raw)
        migrations.upgrade_save({}, raw)
        self.assertEqual(raw, before)

    def test_production_intents_use_the_shared_queue_converter(self):
        item = {"unit_type": "Biplane", "days_remaining": 0, "turns_remaining": "obsolete",
                "refund": {"cost_materials": 17}}
        move = {"player_intents": [{"type": "province_queue", "queue": "unit_queue", "items": [item]}]}
        migrations.upgrade_move(move)
        self.assertEqual(item, {"unit_type": "Biplane Fighter I", "turns_remaining": 1,
                                "refund": {"cost_materials": 17}})
        before = round_trip(move)
        migrations.upgrade_move(move)
        self.assertEqual(move, before)
        for bad in ({"item_name": []}, {"refund": None}):
            with self.subTest(item=bad), self.assertRaises(ValueError):
                migrations.upgrade_move({"player_intents": [{"type": "province_queue", "items": [bad]}]})


class LoadRepairTests(unittest.TestCase):
    LIBRARY = {"Fixture Ground": {"health": 40, "attack": 6, "defense": 3, "speed": 5},
               "Fixture Ship": {"health": 90, "attack": 9, "defense": 2, "speed": 4, "naval_unit": True}}

    def test_queue_clamp_leaves_malformed_entries_and_unknown_families_alone(self):
        queue = ["not an entry", {}, {"item_name": None}, {"item_name": "Removed Lvl 3"},
                 {"item_name": "Fixture Lvl -4"}]
        migrations.clamp_building_queue(queue, {"Fixture Lvl 1": {}, "Fixture Lvl 2": {}})
        self.assertEqual(queue, ["not an entry", {}, {"item_name": None},
                                 {"item_name": "Removed Lvl 3"}, {"item_name": "Fixture Lvl 1"}])

    def test_queued_building_levels_follow_the_active_library_like_built_ones(self):
        buildings = {"Fixture Lvl 1": {}, "Fixture Lvl 2": {}}
        paid = {"item_name": "Fixture Lvl 9", "order_type": "BUILDING", "turns_remaining": 3,
                "refund": {"cost_materials": 7}}
        province = {"buildings": ["Fixture Lvl 5", "Removed Lvl 1"],
                    "building_queue": [paid, {"item_name": "Fixture Lvl 1"},
                                       {"item_name": "Core Territory", "order_type": "CORE"}]}
        load_map._repair_province(province, buildings)
        self.assertEqual(province["buildings"], ["Fixture Lvl 2"])
        self.assertEqual([entry["item_name"] for entry in province["building_queue"]],
                         ["Fixture Lvl 2", "Fixture Lvl 1", "Core Territory"])
        self.assertEqual((paid["turns_remaining"], paid["refund"]), (3, {"cost_materials": 7}))

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

    def test_province_repair_clamps_building_levels_to_the_library_range(self):
        library = {f"Fixture Lvl {level}": {} for level in (2, 3, 4)}
        library["Other Lvl 1"] = {}
        names = ["Fixture Lvl 50", "Fixture Lvl -4", "Fixture Lvl 3", "Fixture Lvl 0",
                 "Unknown Lvl 9", "Fixture Lvl", "Removed Building"]
        province = {"buildings": names}
        load_map._repair_province(province, library)
        self.assertEqual(province["buildings"],
                         ["Fixture Lvl 4", "Fixture Lvl 2", "Fixture Lvl 3", "Fixture Lvl 2"])

    def test_sparse_building_levels_choose_existing_levels_and_keep_paid_orders(self):
        library = {f"Fixture Lvl {level}": {} for level in (1, 4, 8)}
        for old, current in ((0, 1), (2, 1), (3, 4), (4, 4), (6, 4), (7, 8), (9, 8)):
            with self.subTest(level=old):
                name, expected = f"Fixture Lvl {old}", f"Fixture Lvl {current}"
                paid = {"item_name": name, "order_type": "BUILDING", "turns_remaining": 13,
                        "refund": {"cost_materials": 17}, "future_field": {"keep": True}}
                province = {"buildings": [name], "building_queue": [paid]}
                load_map._repair_province(province, library)
                self.assertEqual(province["buildings"], [expected])
                self.assertIn(expected, library)
                self.assertIs(province["building_queue"][0], paid)
                self.assertEqual(paid, dict(item_name=expected, order_type="BUILDING", turns_remaining=13,
                                           refund={"cost_materials": 17}, future_field={"keep": True}))
                restored = round_trip(province)
                load_map._repair_province(restored, library)
                self.assertEqual(restored, province)

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
    """Every shipped base map and scenario loads through the conversion rules."""

    parallel_cases = True

    @staticmethod
    def built_in_maps():
        for root in (c.BASE_MAPS_DIR, c.SCENARIOS_HISTORICAL_DIR, c.SCENARIOS_ALTERNATE_DIR):
            if not os.path.isdir(ROOT / root):
                continue
            for name in sorted(os.listdir(ROOT / root)):
                path = os.path.join(root, name)
                if os.path.isfile(os.path.join(path, "map_data.json")):
                    yield path

    def test_built_in_maps_exist(self):
        self.assertTrue(list(self.built_in_maps()))

    def map_round_trip(self, path):
        from data.map.load_map import load_backend_state
        # Without explicit settings, the load reads the local, Git-ignored scenario_settings.json.
        context = load_backend_state(path, is_scenario=True,
                                     scenario_settings=queries.get_default_scenario_settings())
        self.assertTrue(context.map_data)
        save = round_trip(queries.build_save_dict(context, include_provinces=False))
        self.assertEqual(save["version"], c.GAME_VERSION)
        map_data = round_trip(queries.build_map_data_save(context))
        before = copy.deepcopy((save, map_data))
        # Every conversion rule leaves a current save unchanged.
        migrations.upgrade_save(save, map_data)
        self.assertEqual((save, map_data), before)


add_test_cases(BuiltInMapTests, BuiltInMapTests.map_round_trip,
               ((path, path) for path in BuiltInMapTests.built_in_maps()))


class ReleasedContentTests(unittest.TestCase):
    """Every name that a release wrote into saves still has a current meaning.

    data/migrations/released_content.py lists the names. The generator writes that shared inventory.
    See data/migrations/MIGRATIONS.md, Released Names.
    """

    def test_the_last_release_is_listed(self):
        released = (ROOT / "version.txt").read_text(encoding="utf-8").strip()
        self.assertIn(released, released_content.RELEASES,
                      f"version.txt names {released}. Commit the release, then run "
                      "python scripts/data/write_released_content.py.")

    def test_released_units_convert_to_current_units(self):
        library = queries.get_unit_library()
        raw = {name: {"units": [{"type": name}]} for name in released_content.UNITS}
        migrations.upgrade_save({}, raw)
        missing = [name for name, province in raw.items() if province["units"][0]["type"] not in library]
        self.assertEqual(missing, [], "Released saves hold these units. Add an alias in "
                         "data/migrations/units.py that gives each one a current unit.")
        self.assertEqual([name for name in migrations.LEGACY_UNIT_NAMES.values() if name not in library], [],
                         "Each alias must name a unit in the current library.")

    def test_released_buildings_load_as_current_buildings(self):
        library = queries.get_building_library()
        raw = {name: {"buildings": [name]} for name in released_content.BUILDINGS}
        migrations.upgrade_save({}, raw)
        for province in raw.values():
            load_map._repair_province(province, library)
        missing = [name for name, province in raw.items()
                   if len(province["buildings"]) != 1 or province["buildings"][0] not in library]
        self.assertEqual(missing, [], "Released saves hold these buildings, and the load drops them. "
                         "Keep the building family, or add a conversion rule.")

    def test_released_settings_families_still_select_content(self):
        for families, library, keys in (
                (released_content.UNIT_FAMILIES, queries.get_unit_library(),
                 ("unit_disabled", "unit_turn_overrides", "unit_range_overrides")),
                (released_content.BUILDING_FAMILIES, queries.get_building_library(),
                 ("building_disabled", "building_turn_overrides"))):
            current = {queries.get_base_item_name(name) for name in library}
            for family in families:
                with self.subTest(keys=keys, family=family):
                    values = {key: {"bombard_range": 7} if key == "unit_range_overrides" else 7
                              for key in keys[1:]}
                    saved = {"scenario_settings": {keys[0]: [family],
                             **{key: {family: value} for key, value in values.items()}}}
                    migrations.upgrade_save(saved, {})
                    settings = saved["scenario_settings"]
                    self.assertEqual(len(settings[keys[0]]), 1)
                    converted = settings[keys[0]][0]
                    self.assertIn(converted, current,
                                  "Keep the released settings family in unit metadata, "
                                  "or convert it in data/migrations/conversions.py.")
                    for key in keys[1:]:
                        self.assertEqual(settings[key], {converted: values[key]})


class ReleasedContentWriterTests(unittest.TestCase):
    @staticmethod
    def inventory_text(**overrides):
        values = {"RELEASES": {"v1": "fixture"}, "UNITS": ("Fixture Unit I",),
                  "BUILDINGS": ("Fixture Building Lvl 1",), "UNIT_FAMILIES": ("Fixture Settings",),
                  "BUILDING_FAMILIES": ("Fixture Building",), "EQUIPMENT": {}}
        values.update(overrides)
        return "\n".join(f"{name} = {value!r}" for name, value in values.items())

    def test_shallow_history_cannot_replace_the_inventory(self):
        with mock.patch.object(write_released_content, "git", return_value="true\n") as git, \
                mock.patch.object(Path, "write_text") as write:
            with self.assertRaisesRegex(ValueError, "git fetch --unshallow"):
                write_released_content.main()
            git.assert_called_once_with("rev-parse", "--is-shallow-repository")
            write.assert_not_called()

    def test_empty_history_or_missing_latest_release_cannot_replace_the_inventory(self):
        for history in ([], ["older"]):
            with self.subTest(history=history), \
                    mock.patch.object(Path, "read_text", return_value="v3\n"), \
                    mock.patch.object(write_released_content, "git",
                                      side_effect=["false\n", "\n".join(history), *["v1"] * len(history)]), \
                    mock.patch.object(Path, "write_text") as write:
                with self.assertRaisesRegex(ValueError, "Cannot find release v3"):
                    write_released_content.main()
                write.assert_not_called()

    def test_full_history_keeps_release_order_and_ignores_test_stamps(self):
        commits = [letter * 40 for letter in "abcd"]
        with mock.patch.object(Path, "read_text", return_value="v3\n"), \
                mock.patch.object(write_released_content, "git", side_effect=[
                    "false\n", "\n".join(commits), "v3", "v999", "v1", "v15a"]):
            self.assertEqual(write_released_content.release_commits(),
                             {"v1": "c" * 12, "v3": "a" * 12})

    def test_regeneration_cannot_drop_recorded_releases_names_or_families(self):
        unit = {"Fixture Unit I": {"metadata": {"family": "Fixture Unit", "settings_family": "Fixture Settings"}}}
        building = {"Fixture Building Lvl 1": {}}
        cases = {"RELEASES": {"v0": "older", "v1": "fixture"}, "UNITS": ("Removed Fixture I",),
                 "BUILDINGS": ("Removed Fixture Lvl 1",), "UNIT_FAMILIES": ("Removed Fixture",),
                 "BUILDING_FAMILIES": ("Removed Fixture",),
                 "EQUIPMENT": {"Removed Fixture": ("Fixture", "fixture", 1800)}}
        for name, previous in cases.items():
            with self.subTest(field=name), \
                    mock.patch.object(write_released_content, "release_commits", return_value={"v1": "fixture"}), \
                    mock.patch.object(write_released_content, "git", side_effect=[json.dumps(unit), json.dumps(building)]), \
                    mock.patch.object(Path, "exists", return_value=True), \
                    mock.patch.object(Path, "read_text", return_value=self.inventory_text(**{name: previous})), \
                    mock.patch.object(Path, "write_text") as write:
                with self.assertRaisesRegex(ValueError, f"would remove {name}"):
                    write_released_content.main()
                write.assert_not_called()

    def test_empty_discovery_changed_commits_and_broken_inventory_cannot_overwrite_it(self):
        unit = {"Fixture Unit I": {"metadata": {"family": "Fixture Unit", "settings_family": "Fixture Settings"}}}
        building = {"Fixture Building Lvl 1": {}}
        for releases, previous, message in (
                ({}, self.inventory_text(), "No releases found"),
                ({"v1": "changed"}, self.inventory_text(), "change recorded release commits"),
                ({"v1": "fixture"}, "invalid python!", "Cannot read the existing inventory")):
            with self.subTest(message=message), \
                    mock.patch.object(write_released_content, "release_commits", return_value=releases), \
                    mock.patch.object(write_released_content, "git", side_effect=[json.dumps(unit), json.dumps(building)]), \
                    mock.patch.object(Path, "exists", return_value=True), \
                    mock.patch.object(Path, "read_text", return_value=previous), \
                    mock.patch.object(Path, "write_text") as write:
                with self.assertRaisesRegex(ValueError, message):
                    write_released_content.main()
                write.assert_not_called()

    def test_unreadable_release_library_stops_generation_without_replacing_inventory(self):
        for path in (write_released_content.UNIT_DATA, write_released_content.BUILDING_DATA):
            for result in (subprocess.CalledProcessError(128, ["git", "show"]), "invalid json",
                           "{}", "[]", "null"):
                with self.subTest(path=path, result=result):
                    reads = [] if path == write_released_content.UNIT_DATA else ['{"Fixture Unit I": {}}']
                    reads.append(result)
                    with mock.patch.object(write_released_content, "release_commits", return_value={"v1": "fixture"}), \
                            mock.patch.object(write_released_content, "git", side_effect=reads), \
                            mock.patch.object(Path, "write_text") as write:
                        with self.assertRaisesRegex(ValueError, f"fixture:{path}"):
                            write_released_content.main()
                        write.assert_not_called()

    def test_valid_release_libraries_preserve_all_identifiers_and_families(self):
        unit = {"Fixture Unit I": {"metadata": {"family": "Fixture Unit", "settings_family": "Fixture Settings"}}}
        building = {"Fixture Building Lvl 1": {}}
        with mock.patch.object(write_released_content, "release_commits", return_value={"v1": "fixture"}), \
                mock.patch.object(write_released_content, "git", side_effect=[json.dumps(unit), json.dumps(building)]), \
                mock.patch.object(Path, "exists", return_value=True), \
                mock.patch.object(Path, "read_text", return_value=self.inventory_text()), \
                mock.patch.object(Path, "write_text") as write, mock.patch("builtins.print"):
            write_released_content.main()
        generated = {}
        exec(compile(write.call_args.args[0], "released_content.py", "exec"), generated)
        self.assertEqual(generated["RELEASES"], {"v1": "fixture"})
        self.assertEqual(generated["UNITS"], tuple(unit))
        self.assertEqual(generated["BUILDINGS"], tuple(building))
        self.assertEqual(generated["UNIT_FAMILIES"], ("Fixture Settings",))
        self.assertEqual(generated["BUILDING_FAMILIES"], ("Fixture Building",))

    def test_equipment_descriptions_are_written_to_the_shared_inventory(self):
        unit = {"Fixture Unit I": {"metadata": {"family": "Fixture Unit", "settings_family": "Fixture Settings",
                                                "research": {"tech": "fixture", "year": 1800}}}}
        with mock.patch.object(write_released_content, "release_commits", return_value={"v1": "fixture"}), \
                mock.patch.object(write_released_content, "git", side_effect=[json.dumps(unit), '{"Fixture Building Lvl 1": {}}']), \
                mock.patch.object(Path, "exists", return_value=True), \
                mock.patch.object(Path, "read_text", return_value=self.inventory_text()), \
                mock.patch.object(Path, "write_text") as write, mock.patch("builtins.print"):
            write_released_content.main()
        generated = {}
        exec(compile(write.call_args.args[0], "released_content.py", "exec"), generated)
        self.assertEqual(generated["EQUIPMENT"], {"Fixture Unit I": ("Fixture Unit", "fixture", 1800)})

    def test_equipment_history_uses_released_metadata_and_refuses_ambiguity(self):
        older = {"Fixture I": {"metadata": {"family": "Fixture", "research": {"tech": "fixture", "year": 1800}}}}
        newer = copy.deepcopy(older)
        newer["Fixture I"]["metadata"]["research"]["year"] = 1900
        self.assertEqual(write_released_content.equipment_description("Fixture I", older["Fixture I"]),
                         ("Fixture", "fixture", 1800))
        with mock.patch.object(write_released_content, "release_commits", return_value={"v1": "older", "v2": "newer"}), \
                mock.patch.object(write_released_content, "read_json", side_effect=[older, {"Building": {}}, newer]), \
                mock.patch.object(Path, "write_text") as write:
            with self.assertRaisesRegex(ValueError, "conflicting historical equipment meanings"):
                write_released_content.main()
            write.assert_not_called()
        previous = self.inventory_text(EQUIPMENT={"Fixture I": ("Fixture", "fixture", 1800)})
        with mock.patch.object(Path, "exists", return_value=True), \
                mock.patch.object(Path, "read_text", return_value=previous):
            with self.assertRaisesRegex(ValueError, "change historical equipment meanings"):
                write_released_content.validate_inventory({
                    "RELEASES": {"v1": "fixture"}, "UNITS": ("Fixture Unit I",),
                    "BUILDINGS": ("Fixture Building Lvl 1",), "UNIT_FAMILIES": ("Fixture Settings",),
                    "BUILDING_FAMILIES": ("Fixture Building",),
                    "EQUIPMENT": {"Fixture I": ("Fixture", "fixture", 1900)}})

    def test_generator_can_import_before_its_output_exists(self):
        code = ("import sys; sys.modules['data.migrations.released_content'] = None; "
                "import scripts.data.write_released_content")
        result = subprocess.run([sys.executable, "-B", "-c", code], cwd=ROOT,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_generated_equipment_meaning_drives_aliases_without_current_name_parsing(self):
        library = {"Early Stage I": {}, "Later Stage I": {}, "Existing Historical Name": {}}
        descriptions = {"Renamed Historical Unit": ("Fixture", "fixture", 1810),
                        "Existing Historical Name": ("Fixture", "fixture", 1800)}
        index = {"Fixture": [("Later Stage I", 1820, 2), ("Early Stage I", 1800, 1)]}
        with mock.patch.object(queries, "get_unit_library", return_value=library), \
                mock.patch.object(queries, "get_unit_research_index", return_value=index), \
                mock.patch("data.migrations.released_content.EQUIPMENT", descriptions):
            aliases = migrations.equipment_stage_aliases()
        self.assertEqual(aliases["Renamed Historical Unit"], "Early Stage I")
        self.assertNotIn("Existing Historical Name", aliases)

    def test_regeneration_can_add_a_release_and_new_names(self):
        releases = {"v1": "fixture", "v2": "newer"}
        unit = {"Fixture Unit I": {"metadata": {"family": "Fixture Settings"}},
                "New Fixture I": {"metadata": {"family": "New Fixture"}}}
        building = {"Fixture Building Lvl 1": {}, "New Fixture Lvl 1": {}}
        with mock.patch.object(write_released_content, "release_commits", return_value=releases), \
                mock.patch.object(write_released_content, "git",
                                  side_effect=[json.dumps(unit), json.dumps(building)] * 2), \
                mock.patch.object(Path, "exists", return_value=True), \
                mock.patch.object(Path, "read_text", return_value=self.inventory_text()), \
                mock.patch.object(Path, "write_text") as write, mock.patch("builtins.print"):
            write_released_content.main()
        generated = {}
        exec(compile(write.call_args.args[0], "released_content.py", "exec"), generated)
        self.assertEqual(generated["RELEASES"], releases)
        self.assertEqual(set(generated["UNITS"]), set(unit))
        self.assertEqual(set(generated["BUILDINGS"]), set(building))
        self.assertEqual(set(generated["UNIT_FAMILIES"]), {"Fixture Settings", "New Fixture"})
        self.assertEqual(set(generated["BUILDING_FAMILIES"]), {"Fixture Building", "New Fixture"})


class LibraryAndTournamentTests(unittest.TestCase):
    def test_older_unit_library_keys_normalize_without_replacing_current_or_unknown_data(self):
        metadata = {"family": "Battleship", "tier_order": 0, "tier_kind": "single",
                    "tier_label": "", "division_suffix": "", "future_field": [7]}
        old = {"health": 23, "metadata": metadata, "future_field": {"keep": True}}
        library = {"Battleship": old}
        migrations.normalize_cached_json_names("unit_library", library)
        self.assertEqual(set(library), {"Battleship I"})
        self.assertIs(library["Battleship I"], old)
        self.assertEqual(metadata, {"family": "Battleship", "tier_order": 1, "tier_kind": "roman",
                                   "tier_label": "I", "division_suffix": "I", "future_field": [7]})
        self.assertEqual(old["future_field"], {"keep": True})
        current = {"health": 31}
        library = {"Battleship": {"health": 17}, "Battleship I": current}
        migrations.normalize_cached_json_names("unit_library", library)
        self.assertEqual(library, {"Battleship I": current})
        self.assertIs(library["Battleship I"], current)

    def test_encrypted_payload_decoder_supports_both_encodings(self):
        saved = {"country": {"custom_field": 7}}
        payload = json.dumps(saved).encode("utf-8")
        for encoded in (payload, gzip.compress(payload)):
            self.assertEqual(migrations.decode_saved_json(encoded), saved)
        with self.assertRaises(json.JSONDecodeError):
            migrations.decode_saved_json(b"invalid json")

    def test_snapshot_moves_convert_their_country_and_province_records(self):
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
