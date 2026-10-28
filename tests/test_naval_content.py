"""Check historical ships through shared gameplay and multiplayer rules."""

import copy
import json
import unittest
from types import SimpleNamespace

from data import constants as c, migrations, queries
from data.multiplayer.tournament.files import _validate_production_projection
from data.multiplayer.realtime.session import MapRealtimeDriver, RealtimeError
from data.state_access import BackendState
from map_logic.actions import production_actions
from map_logic.ai import ai_tech_eval, ai_unit_eval
from map_logic.turn_processing.research_processor import process_national_research
from tests.test_map_save_format import sample_map_screen


SHIPS = {"Carrack": "carrack", "Ironclad": "ironclad", "Pre-Dreadnought": "pre-dreadnought"}


class NavalContentTests(unittest.TestCase):
    def setUp(self):
        self.library = queries.get_unit_library()
        self.tree = queries.get_tech_tree()
        self.context = BackendState()
        self.context.session.player_country = "A"
        self.country = {"research": {}, "research_queue": [], "at_war_with": []}
        for resource in c.ECON_RESOURCE_KEYS:
            self.country[resource] = 1 + sum(self.library[name][f"cost_{resource}"] for name in SHIPS)
        self.context.world.nation_data["A"] = self.country
        self.province = {"id": 1, "json_key": "home", "owner": "A", "cores": ["A"],
                         "is_coastal": True, "buildings": ["Basic Factory"],
                         "unit_queue": [], "building_queue": [], "units": []}
        self.context.world.map_data["home"] = self.province
        self.context.world.id_to_province[1] = self.province
        self.driver = MapRealtimeDriver(self.context)

    def test_ship_metadata_unlocks_agree_for_players_ai_and_older_libraries(self):
        navy = queries.get_grouped_units(self.library)["Navy"]
        for name, tech in SHIPS.items():
            with self.subTest(ship=name):
                self.assertIn(name, navy)
                metadata = queries.get_unit_metadata(name, self.library)
                self.assertEqual(metadata["research"]["tech"], tech)
                self.assertEqual(migrations.legacy_unit_metadata(name, self.library[name])["research"],
                                 metadata["research"])
                level = metadata["research"]["level"]
                before, after = {tech: level - 1}, {tech: level}
                self.assertFalse(queries.is_unit_unlocked(name, before, self.library))
                self.assertNotIn(name, ai_unit_eval.buildable_units(before, self.library))
                self.assertTrue(queries.is_unit_unlocked(name, after, self.library))
                self.assertIn(name, ai_unit_eval.buildable_units(after, self.library))
                self.assertIn(name, ai_tech_eval.units_unlocked_by(tech, before, self.library))
                unit = queries.create_unit_dict(name, "A", self.library)
                self.assertTrue(queries.is_naval_unit(name))
                for field in ("health", "attack", "defense", "speed"):
                    self.assertEqual(unit[field], self.library[name][field])

    def test_prerequisites_and_costs_agree_for_local_and_server_research(self):
        for tech in (*SHIPS.values(), "dreadnought", "destroyer", "submarine"):
            requirements = self.tree[tech]["req"]
            for prerequisite, level in requirements.items():
                self.country["research"] = dict(requirements, **{prerequisite: level - 1})
                with self.subTest(tech=tech), self.assertRaises(ValueError):
                    queries.canonical_research_selection(self.country, [tech], self.tree)
                with self.subTest(tech=tech), self.assertRaises(RealtimeError):
                    self.driver.validate_draft("A", [{"type": "research_queue", "tech_names": [tech]}])
            self.country["research"] = dict(requirements)
            local = queries.canonical_research_selection(self.country, [tech], self.tree)
            server = self.driver.validate_draft("A", [{"type": "research_queue", "tech_names": [tech]}])[0]
            self.assertEqual(local["projects"], server["projects"])
            self.assertEqual(local["projects"][0]["points_remaining"], self.tree[tech]["cost"])

    def test_completed_ironclad_research_obsoletes_carracks_without_removing_paid_units_or_queues(self):
        self.country["research"] = queries.edited_research_levels({}, "carrack", 1, True, self.tree)
        self.country["research_queue"] = [queries.build_research_project("ironclad", self.tree["ironclad"]["cost"])]
        unit = queries.create_unit_dict("Carrack", "A", self.library)
        self.province["units"].append(unit)
        production_actions.submit_production(self.context, "A", self.province, "unit_queue", {"unit_type": "Carrack"})
        preserved = copy.deepcopy(self.province)
        self.assertFalse(queries.is_unit_obsolete("Carrack", self.country["research"]))
        self.assertIn("Carrack", ai_unit_eval.buildable_units(self.country["research"], self.library))
        self.country["research"] = queries.edited_research_levels(
            self.country["research"], "ironclad", 1, True, self.tree)
        self.assertTrue(queries.is_unit_obsolete("Carrack", self.country["research"]))
        self.assertNotIn("Carrack", ai_unit_eval.buildable_units(self.country["research"], self.library))
        self.assertIn("Ironclad", ai_unit_eval.buildable_units(self.country["research"], self.library))
        self.assertTrue(queries.is_unit_unlocked("Carrack", self.country["research"], self.library))
        self.assertEqual(self.province, preserved)

    def test_editor_grants_and_removes_the_ship_prerequisite_chain(self):
        granted = queries.edited_research_levels({}, "dreadnought", 1, True, self.tree)
        for tech in SHIPS.values():
            self.assertTrue(queries.check_tech_requirements(granted, self.tree[tech]["req"]))
            self.assertGreater(granted[tech], 0)
        removed = queries.edited_research_levels(granted, "carrack", 1, False, self.tree)
        for tech in (*SHIPS.values(), "dreadnought"):
            self.assertEqual(removed[tech], 0)

    def test_destroyer_and_submarine_levels_require_dreadnought_and_follow_editor_dependencies(self):
        for tech in ("destroyer", "submarine"):
            entry = self.tree[tech]
            self.assertIn("dreadnought", entry["req"])
            for level in range(1, entry["max_lvl"] + 1):
                country = {"research": {tech: level - 1}}
                with self.subTest(tech=tech, level=level), self.assertRaises(ValueError):
                    queries.canonical_research_selection(country, [tech], self.tree)
                country["research"].update(entry["req"])
                self.assertEqual(queries.canonical_research_selection(country, [tech], self.tree)
                                 ["projects"][0]["tech_name"], tech)
            granted = queries.edited_research_levels({}, tech, entry["max_lvl"], True, self.tree)
            self.assertTrue(queries.check_tech_requirements(granted, entry["req"]))
            removed = queries.edited_research_levels(granted, "dreadnought", 1, False, self.tree)
            self.assertEqual(removed[tech], 0)

    def test_time_appropriate_research_uses_each_ships_library_year(self):
        for tech in SHIPS.values():
            for level, year in enumerate(self.tree[tech]["years"], start=1):
                with self.subTest(tech=tech, year=year):
                    self.assertLess(queries.get_time_appropriate_research(year - 1)[tech], level)
                    self.assertGreaterEqual(queries.get_time_appropriate_research(year + 1)[tech], level)

    def test_finishing_ship_research_unlocks_paid_coastal_production(self):
        self.context.session.player_country = "Spectator"
        self.context.world.time_manager = SimpleNamespace(year=c.END_YEAR, month_index=0, day=1)
        for name, tech in SHIPS.items():
            self.country["research_queue"] = [queries.build_research_project(tech, 0)]
            process_national_research(self.context)
            stats = self.library[name]
            before = copy.deepcopy(self.country)
            result = production_actions.submit_production(
                self.context, "A", self.province, "unit_queue", {"unit_type": name}, authority="ai")
            self.assertEqual(result.order["turns_remaining"], stats["production_time"])
            for resource in c.ECON_RESOURCE_KEYS:
                self.assertEqual(self.country[resource], before[resource] - stats[f"cost_{resource}"])

    def test_both_multiplayer_adapters_use_host_ship_costs_and_reject_invalid_production(self):
        for name, tech in SHIPS.items():
            self.country["research"] = {tech: queries.get_unit_research_requirement(name)[1]}
            intent = {"unit_type": name}
            command = {"type": "province_queue", "province_id": 1, "queue": "unit_queue", "items": [intent]}
            expected = self.driver.validate_draft("A", [command])[0]["items"]
            projection = {"home": {"unit_queue": [intent.copy()]}}
            self.assertEqual(_validate_production_projection(self.context, "A", projection), [])
            self.assertEqual(projection["home"]["unit_queue"], expected)
            for invalid in ("missing research", "inland", "foreign", "malformed"):
                with self.subTest(ship=name, invalid=invalid):
                    country_before, province_before = copy.deepcopy(self.country), copy.deepcopy(self.province)
                    if invalid == "missing research":
                        self.country["research"] = {}
                    elif invalid == "inland":
                        self.province["is_coastal"] = False
                    elif invalid == "foreign":
                        self.province["owner"] = "B"
                    else:
                        intent["unit_type"] = None
                    unchanged = copy.deepcopy((self.country, self.province))
                    with self.assertRaises(RealtimeError):
                        self.driver.validate_draft("A", [command])
                    with self.assertRaises(ValueError):
                        _validate_production_projection(self.context, "A", {"home": {"unit_queue": [intent.copy()]}})
                    self.assertEqual((self.country, self.province), unchanged)
                    self.country.clear()
                    self.country.update(country_before)
                    self.province.clear()
                    self.province.update(province_before)
                    intent["unit_type"] = name

    def test_restored_ships_research_and_paid_queues_survive_save_data_round_trip(self):
        game = sample_map_screen()
        research = queries.edited_research_levels({}, "dreadnought", 1, True, self.tree)
        game.nation_data[game.player_country]["research"] = research
        province = next(iter(game.map_data.values()))
        province["units"] = [queries.create_unit_dict(name, game.player_country, self.library) for name in SHIPS]
        province["unit_queue"] = [production_actions.canonical_queue_entry(
            "unit_queue", name=name, cost=self.library[name]) for name in SHIPS]
        saved = json.loads(json.dumps(queries.build_save_dict(game)))
        loaded = queries.map_data_with_saved_provinces(game.raw_json_data, saved["provinces"])
        self.assertEqual(saved["nation_data"][game.player_country]["research"], research)
        self.assertEqual(next(iter(loaded.values()))["units"], province["units"])
        self.assertEqual(next(iter(loaded.values()))["unit_queue"], province["unit_queue"])
        existing = {"research": {"dreadnought": self.tree["dreadnought"]["max_lvl"]}}
        self.assertEqual(queries.canonical_research_selection(existing, [], self.tree)["projects"], [])
        self.assertEqual(set(existing["research"]), {"dreadnought"})
        for name in SHIPS:
            self.assertFalse(queries.is_unit_unlocked(name, existing["research"], self.library))

    def test_scenario_disables_use_the_ship_metadata_and_prune_dependencies(self):
        self.context.world.scenario_settings["unit_disabled"] = list(SHIPS)
        library = queries.get_unit_library(self.context)
        tree = queries.get_tech_tree(self.context)
        for name, tech in SHIPS.items():
            self.assertNotIn(name, library)
            self.assertNotIn(tech, tree)
        self.assertTrue(queries.check_tech_requirements({}, tree["dreadnought"]["req"]))


class NavalScreenTests(unittest.TestCase):
    def test_research_nodes_and_production_callbacks_use_the_restored_ships(self):
        from tests import app_harness

        controller, _ = app_harness.boot()
        game = app_harness.boot_map()
        country_id = game.player_country
        nations = copy.deepcopy(game.nation_data)
        country = nations[country_id]
        country["research"] = queries.edited_research_levels({}, "pre-dreadnought", 1, True)
        country["research_queue"] = []
        for resource in c.ECON_RESOURCE_KEYS:
            country[resource] = 1 + sum(queries.get_unit_library()[name][f"cost_{resource}"] for name in SHIPS)
        province = copy.deepcopy(game.selected_province)
        province.update(owner=country_id, cores=[country_id], is_coastal=True, buildings=["Basic Factory"],
                        unit_queue=[], building_queue=[])
        research, production = controller.states["RESEARCH"], controller.states["PRODUCTION"]
        try:
            with app_harness.patch_map(game, nation_data=nations, tactical_mode=False):
                research.start_research(game)
                research.set_category("NAVY")
                for name, tech in SHIPS.items():
                    node = next(node for node in research.nodes["NAVY"] if node["key"] == tech)
                    self.assertEqual(node["year"], queries.get_tech_tree(game)[tech]["years"][node["lvl"] - 1])
                    self.assertEqual(research.get_display_name(tech, node["lvl"]), name)
                    country["research"] = queries.edited_research_levels({}, tech, 1, True)
                    production.start_with_province(province, game)
                    button = next(button for button in production.elements if getattr(button, "text", "") == name)
                    before = copy.deepcopy(country)
                    button.callback()
                    self.assertEqual(province["unit_queue"][-1]["unit_type"], name)
                    for resource in c.ECON_RESOURCE_KEYS:
                        self.assertEqual(country[resource], before[resource] - queries.get_unit_library()[name][f"cost_{resource}"])
                    if name == "Carrack":
                        paid_queue = copy.deepcopy(province["unit_queue"])
                        country["research"] = queries.edited_research_levels(country["research"], "ironclad", 1, True)
                        production.start_with_province(province, game)
                        choices = {getattr(button, "text", "") for button in production.elements}
                        self.assertNotIn("Carrack", choices)
                        self.assertIn("Ironclad", choices)
                        self.assertEqual(province["unit_queue"], paid_queue)
        finally:
            research.start_research(game)
            production.start_with_province(game.selected_province, game)

