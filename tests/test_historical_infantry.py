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
from data.multiplayer.tournament.v46_moves import _validate_production_projection
from data.multiplayer.realtime.session import MapRealtimeDriver, RealtimeError, apply_authoritative_snapshot
from data.state_access import BackendState
from data.map import history_io, load_map
from map_logic.actions import production_actions
from map_logic.ai import ai_tech_eval, ai_unit_eval
from map_logic.system32.research_processor import process_national_research
from screens.game.research import Research_Screen
from tests.stub_map_screen import sample_map_screen


class HistoricalInfantryTests(unittest.TestCase):
    def setUp(self):
        self.tree = queries.get_tech_tree()
        self.library = queries.get_unit_library()
        self.equipment = {name: stats for name, stats in self.library.items()
                          if stats["metadata"]["research"]["tech"] in c.DATED_UNIT_RESEARCH_TRACKS}
        self.vehicles = {name: stats for name, stats in self.library.items()
                         if stats["metadata"]["research"]["tech"] in c.VEHICLE_INFANTRY_GATES}
        self.production_units = {**self.equipment, **self.vehicles}
        self.final_research = {key: entry["max_lvl"] for key, entry in self.tree.items()}
        self.early = {name: stats for name, stats in self.equipment.items()
                      if stats["metadata"]["research"].get("year", 1910) < 1910}
        self.context = BackendState()
        self.context.session.player_country = "A"
        self.country = {"research": {}, "research_queue": [], "at_war_with": []}
        for resource in c.ECON_RESOURCE_KEYS:
            self.country[resource] = 1 + sum(stats[f"cost_{resource}"] for stats in self.production_units.values())
        self.context.world.nation_data["A"] = self.country
        self.province = {"id": 1, "json_key": "home", "owner": "A", "cores": ["A"],
                         "is_coastal": True, "buildings": ["Basic Factory"],
                         "unit_queue": [], "building_queue": [], "units": []}
        self.context.world.map_data["home"] = self.province
        self.context.world.id_to_province[1] = self.province

    def test_early_equipment_unlocks_agree_for_players_and_ai(self):
        self.assertTrue(self.early)
        for name in self.equipment:
            tech, level = queries.get_unit_research_requirement(name, self.library)
            with self.subTest(unit=name):
                before, after = {tech: level - 1}, {tech: level}
                self.assertFalse(queries.is_unit_unlocked(name, before, self.library))
                self.assertTrue(queries.is_unit_unlocked(name, after, self.library))
                self.assertNotIn(name, ai_unit_eval.buildable_units(before, self.library))
                self.assertIn(name, ai_unit_eval.buildable_units(after, self.library))
                self.assertIn(name, ai_tech_eval.units_unlocked_by(tech, before, self.library))
                self.assertIn(name, queries.get_tech_unlocks(tech, level))

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

    def test_1910_start_and_early_upgrades_reach_the_available_stage(self):
        research = queries.get_time_appropriate_research(1910)
        for name, stats in self.early.items():
            metadata = stats["metadata"]
            tech = metadata["research"]["tech"]
            family = metadata["family"]
            original = queries.get_unit_for_family_year(self.library, family, 1910)
            with self.subTest(unit=name):
                self.assertTrue(queries.is_unit_unlocked(original, research, self.library))
                expected = original if original != name else None
                self.assertEqual(queries.get_upgrade_target(name, research, self.library, self.tree), expected)
                self.assertIsNone(queries.get_upgrade_target(name, {tech: 0}, self.library, self.tree))

    def test_original_roman_identifiers_keep_their_metadata_free_compatibility(self):
        aliases = migrations.equipment_stage_aliases()
        for family in ("Militia", "Cavalry", "Artillery", "Heavy Artillery"):
            name = f"{family} I"
            with self.subTest(unit=name):
                older = migrations.legacy_unit_metadata(name, {})
                target = queries.get_unit_for_family_year(self.library, family, older["tier_order"])
                self.assertEqual(aliases[name], target)

    def test_research_completion_uses_each_historical_stage(self):
        self.context.session.player_country = "Spectator"
        self.context.world.time_manager = SimpleNamespace(year=1910, month_index=0, day=1)
        for name in self.equipment:
            tech, level = queries.get_unit_research_requirement(name, self.library)
            self.country["research"] = {tech: level - 1}
            self.country["research_queue"] = [queries.build_research_project(tech, 0)]
            process_national_research(self.context)
            with self.subTest(unit=name):
                self.assertEqual(self.country["research"][tech], level)
                self.assertTrue(queries.is_unit_unlocked(name, self.country["research"], self.library))

    def test_paid_local_recruitment_reads_historical_unit_data(self):
        for name, stats in self.production_units.items():
            self.country["research"] = self.final_research.copy()
            before = copy.deepcopy(self.country)
            result = production_actions.submit_production(
                self.context, "A", self.province, "unit_queue", {"unit_type": name})
            with self.subTest(unit=name):
                self.assertEqual(result.order["turns_remaining"], stats["production_time"])
                for resource in c.ECON_RESOURCE_KEYS:
                    self.assertEqual(self.country[resource], before[resource] - stats[f"cost_{resource}"])

    def test_both_multiplayer_production_paths_use_host_research_and_costs(self):
        driver = MapRealtimeDriver(self.context)
        for name in self.production_units:
            tech, level = queries.get_unit_research_requirement(name, self.library)
            tech = c.VEHICLE_INFANTRY_GATES.get(tech, tech)
            research = dict(self.final_research, **{tech: level})
            self.country["research"] = research.copy()
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
                    self.country["research"] = research.copy()
                    self.province["owner"] = "A"

    def test_vehicle_recruitment_requires_fuel_and_foot_infantry_does_not(self):
        for name, stats in self.vehicles.items():
            if not stats["cost_fuel"]:
                continue
            base_name = queries.get_unit_for_family_tier(
                self.library, "Infantry Type", stats["metadata"]["tier_order"])
            base = self.library[base_name]
            self.country["research"] = self.final_research.copy()
            for resource in c.ECON_RESOURCE_KEYS:
                self.country[resource] = base[f"cost_{resource}"] + stats[f"cost_{resource}"]
            self.country["fuel"] = 0
            with self.subTest(unit=name):
                paid = production_actions.submit_production(
                    self.context, "A", self.province, "unit_queue", {"unit_type": base_name})
                self.assertEqual(paid.cost["cost_fuel"], 0)
                before = copy.deepcopy((self.country, self.province))
                with self.assertRaisesRegex(ValueError, "Insufficient resources"):
                    production_actions.submit_production(
                        self.context, "A", self.province, "unit_queue", {"unit_type": name})
                self.assertEqual((self.country, self.province), before)
                self.country["fuel"] = stats["cost_fuel"]
                paid = production_actions.submit_production(
                    self.context, "A", self.province, "unit_queue", {"unit_type": name})
                self.assertEqual(paid.cost["cost_fuel"], stats["cost_fuel"])
                self.assertEqual(self.country["fuel"], 0)
                production_actions.cancel_production(
                    self.context, "A", self.province, "unit_queue", len(self.province["unit_queue"]) - 1)
                self.assertEqual(self.country["fuel"], stats["cost_fuel"])

    def test_named_research_stages_use_the_same_editor_prerequisite_path(self):
        screen = Research_Screen.__new__(Research_Screen)
        screen.tech_tree = self.tree
        screen.unit_library = None
        for tech in c.DATED_UNIT_RESEARCH_TRACKS:
            for level, year in enumerate(self.tree[tech]["years"], 1):
                with self.subTest(tech=tech, year=year):
                    expected = self.tree[tech].get("level_names", {}).get(str(level))
                    if expected:
                        self.assertEqual(screen.get_display_name(tech, level), expected)
                    edited = queries.edited_research_levels({}, tech, level, True, self.tree)
                    self.assertEqual(edited[tech], level)

    def test_every_vehicle_stage_uses_its_gate_and_shared_infantry_generation(self):
        final = {key: entry["max_lvl"] for key, entry in self.tree.items()}
        vehicles = {name: stats for name, stats in self.library.items()
                    if stats["metadata"]["research"]["tech"] in c.VEHICLE_INFANTRY_GATES}
        self.assertTrue(vehicles)
        for name, stats in vehicles.items():
            metadata = stats["metadata"]
            gate = c.VEHICLE_INFANTRY_GATES[metadata["research"]["tech"]]
            level = self.tree["infantry_type"]["years"].index(metadata["tier_order"]) + 1
            research = dict(final, infantry_type=level)
            with self.subTest(unit=name):
                self.assertTrue(queries.is_unit_unlocked(name, research, self.library))
                self.assertFalse(queries.is_unit_unlocked(name, dict(research, **{gate: 0}), self.library))
                self.assertFalse(queries.is_unit_unlocked(name, dict(research, infantry_type=level - 1), self.library))
                self.assertIn(name, ai_tech_eval.units_unlocked_by(
                    "infantry_type", dict(research, infantry_type=level - 1), self.library))
                self.assertEqual(queries.get_unit_for_family_tier(
                    self.library, metadata["family"], metadata["tier_order"]), name)

    def test_old_equipment_references_convert_in_all_save_parts_and_repeat_safely(self):
        aliases = migrations.equipment_stage_aliases()
        self.assertTrue(aliases)
        for older, current in aliases.items():
            with self.subTest(older=older):
                unit = {"type": older, "owner": "A", "unit_id": "keep-id", "health": 25, "max_health": 100,
                        "order": {"type": "UPGRADE", "target_type": older}, "unknown": [7]}
                province = {"units": [unit, {"type": f"Convoy ({older})", "original_type": older},
                                       {"type": "Jet Transport I", "air_cargo": [copy.deepcopy(unit)]}],
                            "unit_queue": [{"unit_type": older, "turns_remaining": 3, "paid_materials": 17}]}
                saved = {"version": "v46", "nation_data": {"A": {
                    "custom_production_units": [older, older],
                    "scripted_events": [{"actions": [{"type": "Spawn Unit", "unit_type": older}]}]}},
                    "provinces": {"P": copy.deepcopy(province)}, "unknown": {"keep": "unchanged"}}
                raw = {"P": province}
                history = {"1": {"provinces": {"P": copy.deepcopy(province)}}}
                migrations.upgrade_save(saved, raw, history)
                self.assertEqual(saved["nation_data"]["A"]["custom_production_units"], [current])
                self.assertEqual(saved["nation_data"]["A"]["scripted_events"][0]["actions"][0]["unit_type"], current)
                for converted in (raw["P"], saved["provinces"]["P"], history["1"]["provinces"]["P"]):
                    self.assertEqual(converted["units"][0]["type"], current)
                    self.assertEqual(converted["units"][0]["order"]["target_type"], current)
                    self.assertEqual(converted["units"][1]["type"], f"Convoy ({current})")
                    self.assertEqual(converted["units"][1]["original_type"], current)
                    self.assertEqual(converted["units"][2]["air_cargo"][0]["type"], current)
                    self.assertEqual(converted["unit_queue"], [{"unit_type": current, "turns_remaining": 3, "paid_materials": 17}])
                self.assertTrue(queries.apply_library_stats(unit, self.library))
                self.assertEqual(unit["health"], self.library[current]["health"] / 4)
                self.assertEqual((unit["unit_id"], unit["unknown"]), ("keep-id", [7]))
                once = copy.deepcopy((saved, raw, history))
                migrations.upgrade_save(saved, raw, history)
                self.assertEqual((saved, raw, history), once)

    def test_tournament_conversion_preserves_intents_and_projection_agreement(self):
        older, current = next(iter(migrations.equipment_stage_aliases().items()))
        move = {"nation_data": {"custom_production_units": [older]},
                "provinces": {"P": {"unit_queue": [{"unit_type": older}]}},
                "aircraft_orders": [], "release_subjects": [],
                "player_intents": [{"type": "province_queue", "province_id": 1,
                                    "queue": "unit_queue", "items": [{"unit_type": older}]}]}
        migrations.upgrade_move(move)
        self.assertEqual(move["provinces"]["P"]["unit_queue"][0]["unit_type"], current)
        self.assertEqual(move["player_intents"][0]["items"][0]["unit_type"], current)
        once = copy.deepcopy(move)
        migrations.upgrade_move(move)
        self.assertEqual(move, once)

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

    def test_current_vehicle_save_refreshes_stats_and_keeps_health_and_paid_queue(self):
        game = sample_map_screen()
        province = next(iter(game.map_data.values()))
        names = {}
        for name, stats in self.vehicles.items():
            names.setdefault(stats["metadata"]["family"], name)
        province["units"] = [{"type": name, "owner": game.player_country, "unit_id": family,
                               "health": 25, "max_health": 100, "attack": 3, "defense": 1,
                               "speed": 1, "order": {"type": "MOVE", "path": []}}
                              for family, name in names.items()]
        paid_queue = [{"unit_type": next(iter(names.values())), "turns_remaining": 7,
                       "refund": {"cost_materials": 17.5, "cost_manpower": 13, "cost_fuel": 5}}]
        province["unit_queue"] = copy.deepcopy(paid_queue)
        province["buildings"] = ["Basic Factory"]
        province["resources"] = {}
        game.nation_data[game.player_country]["research"] = self.final_research.copy()
        saved = queries.build_save_dict(game)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pygame.image.save(pygame.Surface((1, 1)), root / "id_map.png")
            (root / "map_data.json").write_text(json.dumps(queries.build_map_data_save(game)))
            (root / "meta.json").write_text(json.dumps(saved))
            loaded = load_map.load_backend_state(directory, skip_initial_income=True)
            loaded_province = next(iter(loaded.map_data.values()))
            self.assertEqual(loaded_province["unit_queue"], paid_queue)
            for unit in loaded_province["units"]:
                stats = self.library[unit["type"]]
                self.assertEqual(unit["health"], stats["health"] / 4)
                self.assertEqual(unit["unit_id"], stats["metadata"]["family"])
                self.assertEqual((unit["max_health"], unit["attack"], unit["defense"], unit["speed"]),
                                 (stats["health"], stats["attack"], stats["defense"], stats["speed"]))
            current = queries.build_save_dict(loaded)
            (root / "meta.json").write_text(json.dumps(current))
            restored = load_map.load_backend_state(directory, skip_initial_income=True)
            self.assertEqual(next(iter(restored.map_data.values()))["units"], loaded_province["units"])
            self.assertEqual(next(iter(restored.map_data.values()))["unit_queue"], paid_queue)

    def test_disk_load_migrates_legacy_history_then_preserves_a_new_save(self):
        game = sample_map_screen()
        province = next(iter(game.map_data.values()))
        province["units"] = [{"type": "Infantry Type 1911", "owner": game.player_country,
                              "unit_id": "legacy-unit", "health": 25, "max_health": 100,
                              "order": {"type": "MOVE", "path": []}}]
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
            expected = sum(year <= 1910 for year in self.tree["infantry_type"]["years"])
            self.assertEqual(loaded.nation_data[game.player_country]["research"]["infantry_type"], expected)
            self.assertEqual(loaded.default_research["infantry_type"], expected)
            self.assertEqual(loaded.history["1"]["nation_data"][game.player_country]["research"]["infantry_type"], expected)
            loaded_unit = next(iter(loaded.map_data.values()))["units"][0]
            unit_type = migrations.equipment_stage_aliases()["Infantry Type 1911"]
            self.assertEqual(loaded_unit["type"], unit_type)
            self.assertEqual(loaded_unit["unit_id"], "legacy-unit")
            self.assertEqual(loaded_unit["health"], self.library[unit_type]["health"] / 4)
            current = queries.build_save_dict(loaded)
            (root / "meta.json").write_text(json.dumps(current))
            history_io.write(directory, loaded.history)
            restored = load_map.load_backend_state(directory, skip_initial_income=True)
            self.assertEqual(restored.nation_data[game.player_country]["research"],
                             loaded.nation_data[game.player_country]["research"])
            self.assertEqual(next(iter(restored.map_data.values()))["units"], [loaded_unit])


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

    def test_condensed_stages_keep_completed_years_and_unfinished_points(self):
        tree = {"infantry_type": {"years": [1800, 1905, 1915, 1925]}}
        saved = {"research_years": {"infantry_type": [1800, 1905, 1910, 1911, 1912, 1913]},
                 "nation_data": {"A": {"research": {"infantry_type": 5},
                    "research_queue": [{"tech_name": "infantry_type", "points_remaining": 73}],
                    "research_progress": {"infantry_type": 73}}}}
        migrations.migrate_infantry_research(saved, tree)
        self.assertEqual(saved["nation_data"]["A"]["research"]["infantry_type"], 2)
        self.assertEqual(saved["nation_data"]["A"]["research_queue"][0]["points_remaining"], 73)
        self.assertEqual(saved["nation_data"]["A"]["research_progress"], {"infantry_type": 73})

    def test_finished_condensed_tracks_drop_pending_projects_at_the_new_cap(self):
        tree = {"infantry_type": {"years": [1800, 1905]}}
        saved = {"research_years": {"infantry_type": [1800, 1905, 1910]},
                 "nation_data": {"A": {"research": {"infantry_type": 2},
                    "research_queue": [{"tech_name": "infantry_type", "points_remaining": 73},
                                       {"tech_name": "unrelated", "points_remaining": 50}],
                    "research_progress": {"infantry_type": 73}, "current_research": "infantry_type"}}}
        migrations.migrate_infantry_research(saved, tree)
        country = saved["nation_data"]["A"]
        self.assertEqual(country["research"], {"infantry_type": 2})
        self.assertEqual(country["research_queue"], [{"tech_name": "unrelated", "points_remaining": 50}])
        self.assertEqual(country["research_progress"], {})
        self.assertIsNone(country["current_research"])
