"""Check historical ships through shared gameplay and multiplayer rules."""

import copy
import json
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from data import constants as c, migrations, queries
from data.multiplayer.tournament.files import _validate_production_projection
from data.multiplayer.realtime.session import MapRealtimeDriver, RealtimeError
from data.state_access import BackendState
from map_logic.actions import production_actions, unit_actions
from map_logic.ai import ai_research, ai_tech_eval, ai_unit_eval
from map_logic.system32.movement_processor import process_upgrades
from map_logic.system32.research_processor import process_national_research
from tests.stub_map_screen import sample_map_screen
from tests import test_tournament_moves as tournament_harness


SHIPS = {"Carrack": "carrack", "Ironclad": "ironclad", "Pre-Dreadnought": "pre-dreadnought",
         "Dreadnought": "dreadnought", "Battleship": "battleship"}


class NavalContentTests(unittest.TestCase):
    def setUp(self):
        self.library = queries.get_unit_library()
        self.tree = queries.get_tech_tree()
        self.ships = {name: stats["metadata"]["research"]["tech"]
                      for name, stats in self.library.items() if stats["metadata"]["family"] in SHIPS}
        self.context = BackendState()
        self.context.session.player_country = "A"
        self.country = {"research": {}, "research_queue": [], "at_war_with": []}
        for resource in c.ECON_RESOURCE_KEYS:
            self.country[resource] = 1 + sum(self.library[name][f"cost_{resource}"] for name in self.ships)
        self.context.world.nation_data["A"] = self.country
        self.province = {"id": 1, "json_key": "home", "owner": "A", "cores": ["A"],
                         "is_coastal": True, "buildings": ["Basic Factory"],
                         "unit_queue": [], "building_queue": [], "units": []}
        self.context.world.map_data["home"] = self.province
        self.context.world.id_to_province[1] = self.province
        self.driver = MapRealtimeDriver(self.context)

    def test_ship_metadata_unlocks_agree_for_players_ai_and_older_libraries(self):
        navy = queries.get_grouped_units(self.library, by_family=False)["Navy"]
        for name, tech in self.ships.items():
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

    def test_each_ship_research_level_unlocks_the_matching_family_upgrade(self):
        for family, tech in SHIPS.items():
            levels = {queries.get_unit_research_requirement(name, self.library)[1]: name
                      for name in self.ships if self.ships[name] == tech}
            self.assertGreater(self.tree[tech]["max_lvl"], 1)
            self.assertEqual(set(levels), set(range(1, self.tree[tech]["max_lvl"] + 1)))
            for level, name in levels.items():
                if level == 1:
                    self.assertEqual(name, family + " I")
                    continue
                research = queries.edited_research_levels({}, tech, level, True, self.tree)
                with self.subTest(ship=name):
                    self.assertEqual(queries.get_upgrade_target(family + " I", research, self.library, self.tree), name)
                    candidates = ai_unit_eval.buildable_units(research, self.library)
                    self.assertIn(name, candidates)
                    self.assertNotIn(levels[level - 1], candidates)
                    self.country["research"] = research
                    unit = queries.create_unit_dict(family + " I", "A", self.library)
                    unit["health"] *= 0.6
                    self.province["units"] = [unit]
                    unit_actions.apply_action(self.context, "A", self.province, unit,
                                              {"type": "UPGRADE", "target_type": name})
                    process_upgrades(self.context)
                    self.assertEqual(unit["type"], name)
                    self.assertAlmostEqual(unit["health"] / unit["max_health"], 0.6)
                    self.assertEqual(unit["max_health"], self.library[name]["health"])
                    for field in ("attack", "defense", "speed"):
                        self.assertEqual(unit[field], self.library[name][field])

    def test_prerequisites_and_costs_agree_for_local_and_server_research(self):
        for tech in (*SHIPS.values(), "destroyer", "submarine"):
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
        unit = queries.create_unit_dict("Carrack I", "A", self.library)
        self.province["units"].append(unit)
        production_actions.submit_production(self.context, "A", self.province, "unit_queue", {"unit_type": "Carrack I"})
        preserved = copy.deepcopy(self.province)
        self.assertFalse(queries.is_unit_obsolete("Carrack", self.country["research"]))
        self.assertIn("Carrack I", ai_unit_eval.buildable_units(self.country["research"], self.library))
        self.country["research"] = queries.edited_research_levels(
            self.country["research"], "ironclad", 1, True, self.tree)
        self.assertTrue(queries.is_unit_obsolete("Carrack", self.country["research"]))
        self.assertNotIn("Carrack I", ai_unit_eval.buildable_units(self.country["research"], self.library))
        self.assertIn("Ironclad I", ai_unit_eval.buildable_units(self.country["research"], self.library))
        self.assertTrue(queries.is_unit_unlocked("Carrack I", self.country["research"], self.library))
        self.assertEqual(self.province, preserved)

    def test_editor_grants_and_removes_the_ship_prerequisite_chain(self):
        granted = queries.edited_research_levels({}, "battleship", 1, True, self.tree)
        for tech in SHIPS.values():
            self.assertTrue(queries.check_tech_requirements(granted, self.tree[tech]["req"]))
            self.assertGreater(granted[tech], 0)
        removed = queries.edited_research_levels(granted, "carrack", 1, False, self.tree)
        for tech in SHIPS.values():
            self.assertEqual(removed[tech], 0)

    def test_destroyer_and_submarine_levels_follow_their_own_research_dependencies(self):
        final_pre_dreadnought = self.tree["pre-dreadnought"]["max_lvl"]
        self.assertEqual(self.tree["destroyer"]["req"], {"pre-dreadnought": final_pre_dreadnought})
        self.assertEqual(self.tree["submarine"]["req"], {"dreadnought": 1})
        for tech, prerequisite, required in (("destroyer", "pre-dreadnought", final_pre_dreadnought),
                                             ("submarine", "dreadnought", 1)):
            entry = self.tree[tech]
            for level in range(1, entry["max_lvl"] + 1):
                self.country["research"] = {tech: level - 1, prerequisite: required - 1}
                with self.subTest(tech=tech, level=level), self.assertRaises(ValueError):
                    queries.canonical_research_selection(self.country, [tech], self.tree)
                with self.subTest(tech=tech, level=level), self.assertRaises(RealtimeError):
                    self.driver.validate_draft("A", [{"type": "research_queue", "tech_names": [tech]}])
                self.country["research"][prerequisite] = required
                local = queries.canonical_research_selection(self.country, [tech], self.tree)
                remote = self.driver.validate_draft("A", [{"type": "research_queue", "tech_names": [tech]}])[0]
                self.assertEqual(local["projects"][0]["tech_name"], tech)
                self.assertEqual(remote["projects"], local["projects"])
            granted = queries.edited_research_levels({}, tech, entry["max_lvl"], True, self.tree)
            self.assertTrue(queries.check_tech_requirements(granted, entry["req"]))
            removed = queries.edited_research_levels(granted, prerequisite, required, False, self.tree)
            self.assertEqual(removed[tech], 0)
            if tech == "destroyer":
                self.assertEqual(granted.get("dreadnought", 0), 0)
                preserved = queries.edited_research_levels(granted, "dreadnought", 1, False, self.tree)
                self.assertEqual(preserved[tech], granted[tech])

    def test_ai_only_offers_destroyer_research_after_the_final_pre_dreadnought_level(self):
        final = self.tree["pre-dreadnought"]["max_lvl"]
        self.context.world.time_manager = SimpleNamespace(year=c.END_YEAR)
        for level in (final - 1, final):
            self.country.update(research={"pre-dreadnought": level}, research_queue=[])
            with patch.object(queries, "get_active_ai_nations", return_value=["A"]), \
                    patch.object(queries, "calculate_all_economies", return_value={}), \
                    patch.object(ai_research.ai_world, "for_screen", return_value=None), \
                    patch.object(ai_research, "_rank_for_nation", return_value=[]) as rank:
                ai_research.process_ai_research(self.context)
            offered = {candidate[0] for candidate in rank.call_args.args[0]}
            self.assertEqual("destroyer" in offered, level == final)

    def test_tournament_destroyer_research_checks_host_prerequisites_identity_and_turn(self):
        final = self.tree["pre-dreadnought"]["max_lvl"]
        harness = tournament_harness.TournamentMoveTests()
        for mode in ("valid", "locked", "malformed", "stale", "wrong_key"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                host = tournament_harness.Host()
                host.nation_data["Leader"]["research"] = {"pre-dreadnought": final - int(mode == "locked")}
                move = {"player_intents": [{"type": "research_queue",
                        "tech_names": "destroyer" if mode == "malformed" else ["destroyer"]}],
                        "game_version": c.GAME_VERSION, "tournament_session": host.multiplayer_session_key,
                        "tournament_turn": host.time_manager.total_turns - int(mode == "stale")}
                before = copy.deepcopy(host.nation_data)
                path = harness.write_move(directory, "destroyer.gd5move", "Leader", move)
                if mode == "wrong_key":
                    with open(path) as file:
                        payload = json.load(file)
                    payload["hash"] = tournament_harness.multiplayer_io.hash_key(harness.keys["Member"])
                    with open(path, "w") as file:
                        json.dump(payload, file)
                result = harness.import_moves(host, [path])
                self.assertEqual(result["loaded"], int(mode == "valid"), result["rejections"])
                if mode == "valid":
                    self.assertEqual(host.nation_data["Leader"]["research_queue"],
                                     [queries.build_research_project("destroyer", self.tree["destroyer"]["cost"])])
                    self.assertEqual(host.nation_data["Member"], before["Member"])
                else:
                    self.assertEqual(host.nation_data, before)

    def test_time_appropriate_research_uses_each_ships_library_year(self):
        for tech in SHIPS.values():
            for level, year in enumerate(self.tree[tech]["years"], start=1):
                with self.subTest(tech=tech, year=year):
                    self.assertLess(queries.get_time_appropriate_research(year - 1)[tech], level)
                    self.assertGreaterEqual(queries.get_time_appropriate_research(year + 1)[tech], level)

    def test_finishing_ship_research_unlocks_paid_coastal_production(self):
        self.context.session.player_country = "Spectator"
        self.context.world.time_manager = SimpleNamespace(year=c.END_YEAR, month_index=0, day=1)
        for name, tech in self.ships.items():
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
        for name, tech in self.ships.items():
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
                        self.country["research"] = {tech: queries.get_unit_research_requirement(name)[1] - 1}
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
        for tech in SHIPS.values():
            research = queries.edited_research_levels(research, tech, self.tree[tech]["max_lvl"], True, self.tree)
        game.nation_data[game.player_country]["research"] = research
        province = next(iter(game.map_data.values()))
        province["units"] = [queries.create_unit_dict(name, game.player_country, self.library) for name in self.ships]
        province["unit_queue"] = [production_actions.canonical_queue_entry(
            "unit_queue", name=name, cost=self.library[name]) for name in self.ships]
        saved = json.loads(json.dumps(queries.build_save_dict(game)))
        loaded = queries.map_data_with_saved_provinces(game.raw_json_data, saved["provinces"])
        self.assertEqual(saved["nation_data"][game.player_country]["research"], research)
        self.assertEqual(next(iter(loaded.values()))["units"], province["units"])
        self.assertEqual(next(iter(loaded.values()))["unit_queue"], province["unit_queue"])
        for base, tech in (("Dreadnought I", "dreadnought"), ("Battleship I", "battleship")):
            existing = {"research": {tech: 1}}
            self.assertEqual(queries.canonical_research_selection(existing, [], self.tree)["projects"], [])
            self.assertEqual(existing["research"], {tech: 1})
            self.assertIsNone(queries.get_upgrade_target(base, existing["research"], self.library, self.tree))
            for name in SHIPS:
                self.assertEqual(queries.is_unit_unlocked(name + " I", existing["research"], self.library), name + " I" == base)

    def test_scenario_disables_use_the_ship_metadata_and_prune_dependencies(self):
        self.context.world.scenario_settings["unit_disabled"] = list(SHIPS)
        library = queries.get_unit_library(self.context)
        tree = queries.get_tech_tree(self.context)
        for name, tech in SHIPS.items():
            self.assertNotIn(name + " I", library)
            self.assertNotIn(tech, tree)
            self.assertFalse(any(stats["metadata"]["family"] == name for stats in library.values()))
        for tech in ("destroyer", "submarine", "aircraft_carrier"):
            self.assertTrue(queries.check_tech_requirements({}, tree[tech]["req"]))


class NavalScreenTests(unittest.TestCase):
    def test_destroyer_research_control_rechecks_the_final_pre_dreadnought_requirement(self):
        from tests import app_harness

        controller, _ = app_harness.boot()
        game = app_harness.boot_map()
        nations = copy.deepcopy(game.nation_data)
        country = nations[game.player_country]
        tree = queries.get_tech_tree(game)
        final = tree["pre-dreadnought"]["max_lvl"]
        research = controller.states["RESEARCH"]
        try:
            with app_harness.patch_map(game, nation_data=nations, tactical_mode=False):
                for complete in (False, True):
                    country["research"] = queries.edited_research_levels(
                        {}, "pre-dreadnought", final - int(not complete), True, tree)
                    country["research_queue"] = []
                    research.start_research(game)
                    research.set_category("NAVY")
                    node = next(button for button in research.elements
                                if getattr(button, "is_tech_node", False)
                                and button.text == research.get_display_name("destroyer", 1))
                    node.callback()
                    self.assertEqual(research.active_modal["status"], "AVAILABLE" if complete else "LOCKED")
                    self.assertEqual(country["research"].get("dreadnought", 0), 0)
                    if complete:
                        button = next(button for button in research.elements
                                      if getattr(button, "text", "") == "Start Research")
                        country["research"]["pre-dreadnought"] = final - 1
                        button.callback()
                        self.assertEqual(country["research_queue"], [])
                        country["research"]["pre-dreadnought"] = final
                    research.start_or_resume_research("destroyer")
                    self.assertEqual([project["tech_name"] for project in country["research_queue"]],
                                     ["destroyer"] if complete else [])
        finally:
            research.start_research(game)

    def test_new_ship_levels_can_be_researched_and_purchased_through_screen_callbacks(self):
        from tests import app_harness

        controller, _ = app_harness.boot()
        game = app_harness.boot_map()
        country_id = game.player_country
        nations = copy.deepcopy(game.nation_data)
        country = nations[country_id]
        library, tree = queries.get_unit_library(game), queries.get_tech_tree(game)
        ships = [name for name, stats in library.items() if stats["metadata"]["family"] in SHIPS]
        for resource in c.ECON_RESOURCE_KEYS:
            country[resource] = 1 + sum(library[name][f"cost_{resource}"] for name in ships)
        province = copy.deepcopy(game.selected_province)
        province.update(owner=country_id, cores=[country_id], is_coastal=True, buildings=["Basic Factory"],
                        unit_queue=[], building_queue=[])
        research, production = controller.states["RESEARCH"], controller.states["PRODUCTION"]
        try:
            with app_harness.patch_map(game, nation_data=nations, tactical_mode=False):
                for family, tech in SHIPS.items():
                    level = tree[tech]["max_lvl"]
                    name = next(name for name in ships
                                if library[name]["metadata"]["family"] == family
                                and queries.get_unit_research_requirement(name, library)[1] == level)
                    country["research"] = queries.edited_research_levels({}, tech, level - 1, True, tree)
                    country["research_queue"] = []
                    research.start_research(game)
                    research.set_category("NAVY")
                    node = next(button for button in research.elements
                                if getattr(button, "is_tech_node", False)
                                and button.text == research.get_display_name(tech, level))
                    node.callback()
                    self.assertEqual((research.active_modal["tech_key"], research.active_modal["level"]), (tech, level))
                    self.assertIn(name, research.modal_entities)
                    next(button for button in research.elements if getattr(button, "text", "") == "Start Research").callback()
                    self.assertEqual(country["research_queue"], [queries.build_research_project(tech, tree[tech]["cost"])])
                    country["research"] = queries.edited_research_levels(country["research"], tech, level, True, tree)
                    country["research_queue"] = []
                    production.start_with_province(province, game)
                    next(button for button in production.elements
                         if getattr(button, "text", "") == queries.get_condensed_unit_name(name)).callback()
                    self.assertEqual(province["unit_queue"][-1]["unit_type"], name)
        finally:
            research.start_research(game)
            production.start_with_province(game.selected_province, game)

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
            country[resource] = 1 + sum(queries.get_unit_library()[name + " I"][f"cost_{resource}"] for name in SHIPS)
        province = copy.deepcopy(game.selected_province)
        province.update(owner=country_id, cores=[country_id], is_coastal=True, buildings=["Basic Factory"],
                        unit_queue=[], building_queue=[])
        research, production = controller.states["RESEARCH"], controller.states["PRODUCTION"]
        try:
            with app_harness.patch_map(game, nation_data=nations, tactical_mode=False):
                research.start_research(game)
                research.set_category("NAVY")
                for family, tech in SHIPS.items():
                    name = family + " I"
                    nodes = [node for node in research.nodes["NAVY"] if node["key"] == tech]
                    self.assertEqual([node["year"] for node in nodes], queries.get_tech_tree(game)[tech]["years"])
                    country["research"] = queries.edited_research_levels({}, tech, 1, True)
                    production.start_with_province(province, game)
                    button = next(button for button in production.elements
                                  if getattr(button, "text", "") == queries.get_condensed_unit_name(name))
                    before = copy.deepcopy(country)
                    button.callback()
                    self.assertEqual(province["unit_queue"][-1]["unit_type"], name)
                    for resource in c.ECON_RESOURCE_KEYS:
                        self.assertEqual(country[resource], before[resource] - queries.get_unit_library()[name][f"cost_{resource}"])
                    if name == "Carrack I":
                        paid_queue = copy.deepcopy(province["unit_queue"])
                        country["research"] = queries.edited_research_levels(country["research"], "ironclad", 1, True)
                        production.start_with_province(province, game)
                        choices = {getattr(button, "text", "") for button in production.elements}
                        self.assertNotIn("Carrack I", choices)
                        self.assertIn("Ironclad I", choices)
                        self.assertEqual(province["unit_queue"], paid_queue)
        finally:
            research.start_research(game)
            production.start_with_province(game.selected_province, game)

