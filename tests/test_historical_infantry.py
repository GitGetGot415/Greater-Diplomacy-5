"""Check historical equipment through research, production, and save boundaries."""

import copy
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import pygame

from data import constants as c, migrations, queries
from data.io.multiplayer_io import _validate_production_projection
from data.io.realtime_multiplayer import MapRealtimeDriver, RealtimeError, apply_authoritative_snapshot
from data.state_access import BackendState
from data.map import history_io, load_map
from map_logic import production_actions
from map_logic.ai import ai_tech_eval, ai_unit_eval
from map_logic.turn_processing.research_processor import process_national_research
from screens.map_related_screens.research import Research_Screen
from tests.test_map_save_format import sample_map_screen


class HistoricalInfantryTests(unittest.TestCase):
    def setUp(self):
        self.tree = queries.get_tech_tree()
        self.library = queries.get_unit_library()
        self.early = {name: stats for name, stats in self.library.items()
                      if stats["metadata"]["research"].get("year", 1910) < 1910}
        self.context = BackendState()
        self.context.session.player_country = "A"
        self.country = {"research": {}, "research_queue": [], "at_war_with": []}
        for resource in c.ECON_RESOURCE_KEYS:
            self.country[resource] = 1 + sum(stats[f"cost_{resource}"] for stats in self.early.values())
        self.context.world.nation_data["A"] = self.country
        self.province = {"id": 1, "json_key": "home", "owner": "A", "cores": ["A"],
                         "is_coastal": True, "buildings": ["Basic Factory"],
                         "unit_queue": [], "building_queue": [], "units": []}
        self.context.world.map_data["home"] = self.province
        self.context.world.id_to_province[1] = self.province

    def test_early_equipment_unlocks_agree_for_players_and_ai(self):
        self.assertTrue(self.early)
        for name in self.early:
            tech, level = queries.get_unit_research_requirement(name, self.library)
            with self.subTest(unit=name):
                before, after = {tech: level - 1}, {tech: level}
                self.assertFalse(queries.is_unit_unlocked(name, before, self.library))
                self.assertTrue(queries.is_unit_unlocked(name, after, self.library))
                self.assertNotIn(name, ai_unit_eval.buildable_units(before, self.library))
                self.assertIn(name, ai_unit_eval.buildable_units(after, self.library))
                self.assertIn(name, ai_tech_eval.units_unlocked_by(tech, before, self.library))
                self.assertIn(name, queries.get_tech_unlocks(tech, level))
                for field in ("health", "attack", "cost_materials", "cost_manpower", "production_time"):
                    self.assertGreater(self.library[name][field], 0)

    def test_starting_equipment_and_factory_are_available_in_1800(self):
        research = queries.get_time_appropriate_research(c.START_YEAR)
        for tech in c.DATED_UNIT_RESEARCH_TRACKS:
            years = self.tree[tech]["years"]
            self.assertEqual(research[tech], sum(year <= c.START_YEAR for year in years))
            self.assertGreater(research[tech], 0)
        self.assertTrue(research["basic_factory"])
        self.assertEqual(queries.get_infantry_family_year("infantry_type", research, self.tree), c.START_YEAR)
        for gate in c.VEHICLE_INFANTRY_GATES:
            self.assertIsNone(queries.get_infantry_family_year(gate, research, self.tree))

    def test_1910_start_and_early_upgrades_reach_original_units(self):
        research = queries.get_time_appropriate_research(1910)
        for name, stats in self.early.items():
            metadata = stats["metadata"]
            tech = metadata["research"]["tech"]
            family = metadata["family"]
            original = next(unit for unit, data in self.library.items()
                            if data["metadata"]["family"] == family
                            and data["metadata"]["research"].get("year") == 1910)
            with self.subTest(unit=name):
                self.assertTrue(queries.is_unit_unlocked(original, research, self.library))
                self.assertEqual(queries.get_upgrade_target(name, research, self.library, self.tree), original)
                self.assertIsNone(queries.get_upgrade_target(name, {tech: 0}, self.library, self.tree))

    def test_trucks_still_require_the_original_final_cavalry_year(self):
        requirement = self.tree["trucks"]["req"]["cavalry"]
        self.assertEqual(self.tree["cavalry"]["years"][requirement - 1],
                         migrations.LEGACY_INFANTRY_RESEARCH_YEARS["cavalry"][-1])
        self.assertFalse(queries.check_tech_requirements({"cavalry": requirement - 1}, self.tree["trucks"]["req"]))
        self.assertTrue(queries.check_tech_requirements({"cavalry": requirement}, self.tree["trucks"]["req"]))

    def test_original_roman_identifiers_keep_their_metadata_free_compatibility(self):
        for family in ("Militia", "Cavalry", "Artillery", "Heavy Artillery"):
            name = f"{family} I"
            with self.subTest(unit=name):
                current = queries.get_unit_metadata(name, self.library)
                older = migrations.legacy_unit_metadata(name, self.library[name])
                self.assertEqual(older["research"], current["research"])
                self.assertEqual(older["tier_order"], current["tier_order"])

    def test_research_completion_uses_each_historical_stage(self):
        self.context.session.player_country = "Spectator"
        self.context.world.time_manager = SimpleNamespace(year=1910, month_index=0, day=1)
        for name in self.early:
            tech, level = queries.get_unit_research_requirement(name, self.library)
            self.country["research"] = {tech: level - 1}
            self.country["research_queue"] = [queries.build_research_project(tech, 0)]
            process_national_research(self.context)
            with self.subTest(unit=name):
                self.assertEqual(self.country["research"][tech], level)
                self.assertTrue(queries.is_unit_unlocked(name, self.country["research"], self.library))

    def test_paid_local_recruitment_reads_historical_unit_data(self):
        for name, stats in self.early.items():
            tech, level = queries.get_unit_research_requirement(name, self.library)
            self.country["research"] = {tech: level}
            before = copy.deepcopy(self.country)
            result = production_actions.submit_production(
                self.context, "A", self.province, "unit_queue", {"unit_type": name})
            with self.subTest(unit=name):
                self.assertEqual(result.order["turns_remaining"], stats["production_time"])
                for resource in c.ECON_RESOURCE_KEYS:
                    self.assertEqual(self.country[resource], before[resource] - stats[f"cost_{resource}"])

    def test_both_multiplayer_production_paths_use_host_research_and_costs(self):
        driver = MapRealtimeDriver(self.context)
        for name in self.early:
            tech, level = queries.get_unit_research_requirement(name, self.library)
            self.country["research"] = {tech: level}
            intent = {"unit_type": name}
            command = {"type": "province_queue", "province_id": 1,
                       "queue": "unit_queue", "items": [intent]}
            expected = driver.validate_draft("A", [command])[0]["items"]
            projection = {"home": {"unit_queue": [intent.copy()]}}
            self.assertEqual(_validate_production_projection(self.context, "A", projection), [])
            self.assertEqual(projection["home"]["unit_queue"], expected)
            for failure in ("unresearched", "foreign", "malformed"):
                with self.subTest(unit=name, failure=failure):
                    if failure == "unresearched":
                        self.country["research"] = {tech: level - 1}
                    elif failure == "foreign":
                        self.province["owner"] = "B"
                    else:
                        intent["unit_type"] = None
                    before = copy.deepcopy((self.country, self.province))
                    with self.assertRaises(RealtimeError):
                        driver.validate_draft("A", [command])
                    with self.assertRaises(ValueError):
                        _validate_production_projection(self.context, "A", {"home": {"unit_queue": [intent.copy()]}})
                    self.assertEqual((self.country, self.province), before)
                    self.country["research"] = {tech: level}
                    self.province["owner"] = "A"

    def test_named_research_stages_use_the_same_editor_prerequisite_path(self):
        screen = Research_Screen.__new__(Research_Screen)
        screen.tech_tree = self.tree
        for tech in c.DATED_UNIT_RESEARCH_TRACKS:
            for level, year in enumerate(self.tree[tech]["years"], 1):
                with self.subTest(tech=tech, year=year):
                    expected = self.tree[tech].get("level_names", {}).get(str(level))
                    if expected:
                        self.assertEqual(screen.get_display_name(tech, level), expected)
                    edited = queries.edited_research_levels({}, tech, level, True, self.tree)
                    self.assertEqual(edited[tech], level)

    def test_current_save_round_trip_preserves_early_research_units_and_progress(self):
        game = sample_map_screen()
        research = queries.get_time_appropriate_research(c.START_YEAR)
        game.nation_data[game.player_country].update(
            research=research, research_queue=[queries.build_research_project("infantry_type", 123)],
            research_progress={"infantry_type": 123})
        province = next(iter(game.map_data.values()))
        province["units"] = [queries.create_unit_dict(name, game.player_country, self.library)
                             for name in ai_unit_eval.buildable_units(research, self.library)
                             if name in self.early]
        saved = json.loads(json.dumps(queries.build_save_dict(game)))
        before = copy.deepcopy(saved)
        migrations.migrate_infantry_research(saved, self.tree)
        self.assertEqual(saved, before)
        self.assertEqual(saved["research_years"], queries.get_research_years())

    def test_realtime_snapshot_preserves_current_early_research(self):
        game = sample_map_screen()
        research = queries.get_time_appropriate_research(c.START_YEAR)
        game.nation_data[game.player_country]["research"] = research
        snapshot = json.loads(json.dumps(queries.build_save_dict(game)))
        game.refresh_all_maps = Mock()
        apply_authoritative_snapshot(game, snapshot)
        self.assertEqual(game.nation_data[game.player_country]["research"], research)

    def test_disk_load_migrates_legacy_history_then_preserves_a_new_save(self):
        game = sample_map_screen()
        province = next(iter(game.map_data.values()))
        province["units"] = []
        province["unit_queue"] = []
        province["buildings"] = ["Basic Factory"]
        province["resources"] = {}
        game.nation_data[game.player_country]["research"] = {"infantry_type": 2, "militia": 0}
        saved = queries.build_save_dict(game)
        saved.pop("research_years")
        saved["default_research"] = {"infantry_type": 1}
        history = {"1": {"nation_data": copy.deepcopy(saved["nation_data"]),
                         "day": 1, "month": 0, "year": 1911, "provinces": saved["provinces"]}}
        history["1"]["nation_data"][game.player_country]["research"]["infantry_type"] = 1
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pygame.image.save(pygame.Surface((1, 1)), root / "id_map.png")
            (root / "map_data.json").write_text(json.dumps(queries.build_map_data_save(game)))
            (root / "meta.json").write_text(json.dumps(saved))
            history_io.write(directory, history)
            loaded = load_map.load_backend_state(directory, history_turn=1, skip_initial_income=True)
            expected = self.tree["infantry_type"]["years"].index(1910) + 1
            self.assertEqual(loaded.nation_data[game.player_country]["research"]["infantry_type"], expected)
            self.assertEqual(loaded.default_research["infantry_type"], expected)
            self.assertEqual(loaded.history["1"]["nation_data"][game.player_country]["research"]["infantry_type"], expected)
            current = queries.build_save_dict(loaded)
            (root / "meta.json").write_text(json.dumps(current))
            history_io.write(directory, loaded.history)
            restored = load_map.load_backend_state(directory, skip_initial_income=True)
            self.assertEqual(restored.nation_data[game.player_country]["research"],
                             loaded.nation_data[game.player_country]["research"])


class HistoricalResearchMigrationTests(unittest.TestCase):
    def setUp(self):
        self.tree = {"infantry_type": {"years": [1800, 1850, 1910, 1911, 1912]},
                     "militia": {"years": [1800, 1900, 1910, 1915]}}

    def test_legacy_levels_preserve_years_defaults_history_and_pending_work(self):
        saved = {"nation_data": {"A": {
            "research": {"infantry_type": 2, "militia": 0, "custom": 9},
            "research_queue": [{"tech_name": "militia", "points_remaining": 73}],
            "research_progress": {"militia": 73}}},
            "default_research": {"infantry_type": 1, "militia": 0}}
        history = {"1": {"nation_data": {"A": {"research": {"infantry_type": 1}}}}}
        migrations.migrate_infantry_research(saved, self.tree, history)
        self.assertEqual(saved["default_research"], {"infantry_type": 3, "militia": 0})
        country = saved["nation_data"]["A"]
        self.assertEqual(country["research"], {"infantry_type": 4, "militia": 2, "custom": 9})
        self.assertEqual(country["research_queue"], [{"tech_name": "militia", "points_remaining": 73}])
        self.assertEqual(country["research_progress"], {"militia": 73})
        self.assertEqual(history["1"]["nation_data"]["A"]["research"]["infantry_type"], 3)
        before = copy.deepcopy((saved, history))
        migrations.migrate_infantry_research(saved, self.tree, history)
        self.assertEqual((saved, history), before)

    def test_explicit_year_lists_preserve_early_research_and_unknown_fields(self):
        saved = {"research_years": {"infantry_type": [1800, 1910, 1911]},
                 "nation_data": {"A": {"research": {"infantry_type": 1}, "unknown": [7]}}}
        migrations.migrate_infantry_research(saved, self.tree)
        self.assertEqual(saved["nation_data"]["A"], {"research": {"infantry_type": 1}, "unknown": [7]})
        restored = json.loads(json.dumps(saved))
        migrations.migrate_infantry_research(restored, self.tree)
        self.assertEqual(restored, saved)

    def test_malformed_year_lists_are_rejected(self):
        for source in (None, [], [1910, 1800], [1910, 1910], ["1910"]):
            with self.subTest(source=source), self.assertRaises(ValueError):
                migrations.migrate_infantry_research({"research_years": {"infantry_type": source},
                    "nation_data": {"A": {"research": {"infantry_type": 1}}}}, self.tree)
