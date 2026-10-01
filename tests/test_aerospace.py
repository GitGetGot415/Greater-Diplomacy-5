"""Aerospace content uses the shared research, production and network rules."""
import copy
import json
import os
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame
import data.constants as c
from data import queries
from data.io.realtime_multiplayer import MapRealtimeDriver, RealtimeError
from map_logic.ai import ai_tech_eval, ai_unit_eval
from map_logic.turn_processing.research_processor import process_national_research
from tests import app_harness
from tests.test_map_save_format import sample_map_screen
from tests import test_tournament_moves as tournament_harness

# These dates and links are the requested content, rather than balance values.
REQUESTED_TREE = {
    "biplane": (1910, {}, "Biplane"),
    "piston_fighter": (1930, {"biplane": 1}, "Piston Fighter"),
    "piston_bomber": (1935, {"piston_fighter": 1}, "Piston Bomber"),
    "v1_flying_bomb": (1940, {"piston_bomber": 1}, "V1 Flying Bomb"),
    "v2_rocket": (1945, {"v1_flying_bomb": 1}, "V2 Rocket"),
    "jet_engine": (1945, {"piston_bomber": 1}, "Jet Engine"),
    "jet_fighter": (1950, {"jet_engine": 1}, "Jet Fighter"),
}


class AerospaceRulesTests(unittest.TestCase):
    def test_requested_dates_and_prerequisites(self):
        tree = queries.get_tech_tree()
        for key, (year, requirements, name) in REQUESTED_TREE.items():
            with self.subTest(tech=key):
                self.assertEqual(tree[key]["category"], "AEROSPACE")
                self.assertEqual(tree[key]["years"], [year])
                self.assertEqual(tree[key]["req"], requirements)
                self.assertEqual(tree[key]["display_name"], name)
                self.assertTrue(queries.check_tech_requirements(requirements, tree[key]["req"]))
                if requirements:
                    self.assertFalse(queries.check_tech_requirements({}, tree[key]["req"]))

    def test_units_copy_infantry_stats_and_share_ui_ai_unlocks(self):
        library = queries.get_unit_library()
        baseline = library["Infantry Type 1910"]
        for key, (_, _, name) in REQUESTED_TREE.items():
            with self.subTest(tech=key):
                if key == "jet_engine":
                    self.assertNotIn(name, library)
                    self.assertEqual(ai_tech_eval.units_unlocked_by(key, {}, library), ())
                    continue
                self.assertEqual({k: v for k, v in library[name].items()
                                  if k != "production_group"}, baseline)
                self.assertFalse(queries.is_unit_unlocked(name, {}))
                self.assertTrue(queries.is_unit_unlocked(name, {key: 1}))
                self.assertIn(name, ai_tech_eval.units_unlocked_by(key, {}, library))
                self.assertIn(name, ai_unit_eval.buildable_units({key: 1}, library))
                self.assertEqual(queries.classify_unit_group(name, library[name]),
                                 queries.UNIT_GROUP_AEROSPACE)
                created = queries.create_unit_dict(name, "A", library)
                self.assertEqual(created["type"], name)
                self.assertEqual(created["health"], baseline["health"])

    def test_exact_units_and_families_have_the_same_category(self):
        library = queries.get_unit_library()
        expected = [name for key, (_, _, name) in REQUESTED_TREE.items() if key != "jet_engine"]
        for by_family in (True, False):
            groups = queries.get_grouped_units(library, by_family=by_family)
            self.assertCountEqual(groups[queries.UNIT_GROUP_AEROSPACE], expected)
            self.assertFalse(set(expected).intersection(groups[queries.UNIT_GROUP_INFANTRY]))

    def test_research_completion_unlocks_production(self):
        country = {"research": {}, "research_queue": [
            {"tech_name": "biplane", "points_remaining": 1}]}
        map_ref = SimpleNamespace(nation_data={"A": country}, player_country="A",
                                 time_manager=SimpleNamespace(year=1910, day=1, month_index=0),
                                 scenario_settings={}, show_feedback=mock.Mock())
        with mock.patch("map_logic.politics.research_multiplier", return_value=1):
            process_national_research(map_ref)
        self.assertEqual(country["research_queue"], [])
        self.assertTrue(queries.is_unit_unlocked("Biplane", country["research"]))

    def test_existing_save_shape_preserves_techs_progress_and_unit_queue(self):
        map_ref = sample_map_screen()
        country = map_ref.nation_data["Avaria"]
        country.update(research={key: 1 for key in REQUESTED_TREE},
                       research_queue=[{"tech_name": "jet_fighter", "points_remaining": 50}],
                       research_progress={"jet_engine": 75})
        province = next(iter(map_ref.map_data.values()))
        province["unit_queue"] = [{"unit_type": "Biplane", "turns_remaining": 1}]
        saved = json.loads(json.dumps(queries.build_save_dict(map_ref)))
        self.assertEqual(saved["nation_data"]["Avaria"], country)
        self.assertEqual(saved["provinces"]["(7, 0, 0)"]["unit_queue"], province["unit_queue"])
        # Old saves use a sparse research dictionary: missing new keys are locked.
        self.assertFalse(queries.is_unit_unlocked("Biplane", {"infantry_type": 1}))
        self.assertTrue(set(REQUESTED_TREE).issubset(queries.get_time_appropriate_research(c.START_YEAR)))

    def test_icons_are_real_png_files(self):
        for key, (_, _, name) in REQUESTED_TREE.items():
            folder = "images" if key == "jet_engine" else "classic"
            path = Path(c.ASSETS_ROOT_DIR) / folder / f"{name}.png"
            with self.subTest(icon=path):
                self.assertEqual(path.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")


class AerospaceRealtimeTests(unittest.TestCase):
    def setUp(self):
        province = {"id": 1, "owner": "A", "cores": ["A"], "is_coastal": False,
                    "buildings": ["Basic Factory"], "unit_queue": [], "units": []}
        country = {"research": {}, "research_queue": [], "materials": 100000,
                   "manpower": 100000, "fuel": 100000}
        self.map = SimpleNamespace(map_data={"home": province}, id_to_province={1: province},
                                   nation_data={"A": country}, scenario_settings={})
        self.driver = MapRealtimeDriver(self.map)

    def test_research_requires_prerequisites_and_keeps_server_costs(self):
        command = {"type": "research_queue", "tech_names": ["jet_fighter"]}
        with self.assertRaises(RealtimeError):
            self.driver.validate_draft("A", [command])
        self.map.nation_data["A"]["research"] = {"jet_engine": 1}
        canonical = self.driver.validate_draft("A", [command])[0]
        self.assertEqual(canonical["projects"][0]["points_remaining"],
                         queries.get_tech_tree()["jet_fighter"]["cost"])
        for names in (["biplane", "biplane"], [123], ["missing_tech"]):
            with self.subTest(names=names), self.assertRaises(RealtimeError):
                self.driver.validate_draft("A", [{"type": "research_queue", "tech_names": names}])

    def test_unit_orders_need_research_and_ownership_and_use_server_stats(self):
        command = {"type": "province_queue", "province_id": 1, "queue": "unit_queue",
                   "items": [{"unit_type": "Biplane", "turns_remaining": 0, "refund": {}}]}
        with self.assertRaises(RealtimeError):
            self.driver.validate_draft("A", [command])
        self.map.nation_data["A"]["research"] = {"biplane": 1}
        canonical = self.driver.validate_draft("A", [command])[0]["items"][0]
        stats = queries.get_unit_library()["Biplane"]
        self.assertEqual(canonical["turns_remaining"], stats["production_time"])
        self.assertEqual(canonical["refund"], {key: stats[key] for key in
                                              ("cost_materials", "cost_manpower", "cost_fuel")})
        self.map.map_data["home"]["owner"] = "B"
        with self.assertRaises(RealtimeError):
            self.driver.validate_draft("A", [command])

    def test_tournament_import_preserves_aerospace_in_existing_move_fields(self):
        harness = tournament_harness.TournamentMoveTests()
        host = tournament_harness.Host()
        host.map_data = {"home": {"id": 1, "json_key": "home", "owner": "Leader", "units": []}}
        move = harness.player_data("Leader", host)
        move["nation_data"]["research_queue"] = [{"tech_name": "jet_engine", "points_remaining": 50}]
        move["provinces"] = {"home": {"unit_queue": [{"unit_type": "Biplane", "turns_remaining": 1}]}}
        with tempfile.TemporaryDirectory() as directory:
            path = harness.write_move(directory, "aerospace.gd5move", "Leader", move)
            result = harness.import_moves(host, [path])
        self.assertEqual(result["loaded"], 1)
        self.assertEqual(host.nation_data["Leader"]["research_queue"], move["nation_data"]["research_queue"])
        self.assertEqual(host.map_data["home"]["unit_queue"], move["provinces"]["home"]["unit_queue"])


class AerospaceScreenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.controller, cls.surface = app_harness.boot()
        cls.map = app_harness.boot_map()

    def setUp(self):
        self.research = self.controller.states["RESEARCH"]
        self.production = self.controller.states["PRODUCTION"]
        self.addCleanup(self.restore_screens)
        self.country = self.map.player_country
        nation_data = copy.deepcopy(self.map.nation_data)
        country = nation_data[self.country]
        country["research"] = {key: data["max_lvl"] for key, data in queries.get_tech_tree().items()}
        country["research_queue"] = []
        for resource in c.ECON_RESOURCE_KEYS:
            country[resource] = 1000000
        self.enterContext(mock.patch.object(self.map, "nation_data", nation_data))
        self.enterContext(mock.patch.object(self.map, "tactical_mode", False))
        self.enterContext(mock.patch.object(self.map, "viewing_research_country", "", create=True))
        self.province = copy.deepcopy(next(p for p in self.map.map_data.values() if p["owner"] == self.country))
        self.province.update(buildings=["Basic Factory"], cores=[self.country], is_coastal=False,
                             unit_queue=[], building_queue=[])

    def restore_screens(self):
        self.research.start_research(self.map)
        self.production.start_with_province(self.map.selected_province, self.map)

    def test_research_category_order_and_header_containment(self):
        self.research.start_research(self.map)
        categories = self.research.categories
        self.assertLess(categories.index("NAVY"), categories.index("AEROSPACE"))
        self.assertLess(categories.index("AEROSPACE"), categories.index("INDUSTRY"))
        buttons = [el for el in self.research.elements if getattr(el, "text", None) in categories]
        bounds = pygame.Rect(0, 0, c.SCREEN_WIDTH, c.SCREEN_HEIGHT)
        for button in buttons:
            self.assertTrue(bounds.contains(button.rect))
        for first, second in zip(buttons, buttons[1:]):
            self.assertLessEqual(first.rect.right, second.rect.left)
        self.research.set_category("AEROSPACE")
        self.assertEqual({node["key"] for node in self.research.nodes["AEROSPACE"]}, set(REQUESTED_TREE))
        for key, (_, _, name) in REQUESTED_TREE.items():
            self.assertEqual(self.research.get_display_name(key, 1), name)
        self.research.draw(self.surface)
        self.research.set_category("COMPLETED")
        self.research.draw(self.surface)
        for rendered, position in self.research.completed_text_surfaces:
            self.assertLessEqual(position[0] + rendered.get_width(), c.SCREEN_WIDTH)

    def test_aerospace_rows_are_red_and_recruitment_is_in_general_buildings(self):
        from screens.map_related_screens.production import SECTION_PANELS
        self.production.start_with_province(self.province, self.map)
        aerospace_rows = recruitment_rows = 0
        for rect, stats, y, kind in self.production.active_bars:
            if kind == "UNIT" and stats.get("production_group") == queries.UNIT_GROUP_AEROSPACE:
                aerospace_rows += 1
                self.assertTrue(self.production.aerospace_start_y <= y < self.production.aerospace_end_y)
                button = next(el for el in self.production.elements
                              if getattr(el, "base_y", None) == y)
                self.assertEqual(button.color, c.UI_COLORS["red"][0])
            if kind == "BUILDING" and stats.get("group") == "recruitment":
                recruitment_rows += 1
                self.assertTrue(self.production.other_start_y <= y < self.production.other_end_y)
        self.assertEqual(aerospace_rows, sum(key != "jet_engine" for key in REQUESTED_TREE))
        self.assertEqual(recruitment_rows, 1)
        self.assertNotIn("recruit", [prefix for prefix, *_ in SECTION_PANELS])
        self.assertGreater(self.production.aerospace_end_y, self.production.aerospace_start_y)
        self.production.draw(self.surface)

    def test_buy_boundary_rejects_unresearched_foreign_and_read_only_orders(self):
        self.production.start_with_province(self.province, self.map)
        scenarios = ({"research": {}}, {"tactical_mode": True}, {"player_country": "Other"},
                     {"player_country": "Spectator"})
        for changes in scenarios:
            with self.subTest(changes=changes), mock.patch.object(c, "SPECTATOR_CAN_EDIT_PRODUCTION", False):
                with mock.patch.dict(self.map.nation_data[self.country],
                                     {"research": changes["research"]} if "research" in changes else {}):
                    with ExitStack() as stack:
                        for key, value in changes.items():
                            if key != "research":
                                stack.enter_context(mock.patch.object(self.map, key, value))
                        self.production.buy_unit("Biplane")
            self.assertEqual(self.province["unit_queue"], [])
        self.production.buy_unit("Biplane")
        self.assertEqual(self.province["unit_queue"][0]["unit_type"], "Biplane")
