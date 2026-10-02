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
    "biplane": (1910, {}, "Biplane Fighter"),
    "biplane_bomber": (1915, {"biplane": 1}, "Biplane Bomber"),
    "zeppelin": (1915, {"biplane": 1}, "Zeppelin"),
    "piston_fighter": (1930, {"biplane_bomber": 1}, "Monoplane Fighter"),
    "piston_bomber": (1935, {"piston_fighter": 1}, "Monoplane Bomber"),
    "v1_flying_bomb": (1940, {"piston_bomber": 1}, "V1 Flying Bomb"),
    "v2_rocket": (1945, {"v1_flying_bomb": 1}, "V2 Rocket"),
    "jet_engine": (1945, {"piston_bomber": 1}, "Jet Engine"),
    "jet_fighter": (1950, {"jet_engine": 1}, "Jet Fighter"),
}

def aircraft_replacement_cases():
    """Derive replacement cases from the canonical rules and unit library."""
    library = queries.get_unit_library()
    aircraft_by_tech = {queries.get_unit_tech_key(name): name
                        for name, stats in library.items() if stats.get("air_role")}
    return [(obsolete, aircraft_by_tech[tech], tech)
            for obsolete in aircraft_by_tech.values()
            for tech in c.OBSOLESCENCE_RULES.get(obsolete, [])]


class AerospaceRulesTests(unittest.TestCase):
    def test_researched_replacements_make_aircraft_obsolete_for_ui_and_ai(self):
        library = queries.get_unit_library()
        cases = aircraft_replacement_cases()
        self.assertTrue(cases)
        for obsolete, replacement, tech in cases:
            with self.subTest(unit=obsolete):
                research = {queries.get_unit_tech_key(obsolete): 1, tech: 0}
                self.assertFalse(queries.is_unit_obsolete(obsolete, research))
                self.assertIn(obsolete, ai_unit_eval.buildable_units(research, library))
                research[tech] = 1
                self.assertTrue(queries.is_unit_obsolete(obsolete, research))
                self.assertNotIn(obsolete, ai_unit_eval.buildable_units(research, library))
                self.assertIn(replacement, ai_unit_eval.buildable_units(research, library))
                # Obsolescence filters the default list, not custom build legality.
                self.assertTrue(queries.is_unit_unlocked(obsolete, research))

    def test_legacy_aircraft_names_preserve_units_transports_and_queue(self):
        province = {"units": [{"type": old} for old in queries.LEGACY_AIRCRAFT_NAMES],
                    "unit_queue": [{"unit_type": old, "turns_remaining": 2}
                                   for old in queries.LEGACY_AIRCRAFT_NAMES]}
        province["units"].append({"type": "Truck (Piston Bomber)",
                                   "original_type": "Piston Bomber", "health": 17})
        queries.migrate_aircraft_names({1: province})
        self.assertEqual([unit["type"] for unit in province["units"][:-1]],
                         list(queries.LEGACY_AIRCRAFT_NAMES.values()))
        self.assertEqual([item["unit_type"] for item in province["unit_queue"]],
                         list(queries.LEGACY_AIRCRAFT_NAMES.values()))
        self.assertEqual(province["units"][-1],
                         {"type": "Truck (Monoplane Bomber)",
                          "original_type": "Monoplane Bomber", "health": 17})
        expected = copy.deepcopy(province)
        queries.migrate_aircraft_names({1: province})
        self.assertEqual(province, expected)

    def test_air_research_notes_follow_the_unit_capabilities(self):
        for key, (_, _, name) in REQUESTED_TREE.items():
            with self.subTest(unit=name):
                if key == "jet_engine":
                    self.assertEqual(queries.get_air_unit_traits(name), [])
                    continue
                with mock.patch.object(queries, "air_order_radius", wraps=queries.air_order_radius) as radius:
                    traits = queries.get_air_unit_traits(name)
                expected = {"AIR_ATTACK"}
                stats = queries.get_unit_library()[name]
                if not stats.get("air_consumable"):
                    expected.add("AIR_REPOSITION")
                if stats["air_role"] == "fighter":
                    expected.add("AIR_PATROL")
                self.assertEqual({call.args[1] for call in radius.call_args_list}, expected)
                self.assertTrue(traits)
                self.assertTrue(set(traits).issubset(queries.get_tech_unlocks(key, 1)))

    def test_air_notes_follow_changed_range_bonus_and_interception_data(self):
        stats = dict(queries.get_unit_library()["Monoplane Fighter"], air_range_px=333,
                     air_attack_multiplier=11)
        with mock.patch.object(queries, "get_unit_library", return_value={"Test Fighter": stats}):
            traits = queries.get_air_unit_traits("Test Fighter")
            self.assertTrue(any(f"{queries.air_order_radius({'type': 'Test Fighter'}, 'AIR_ATTACK'):g}" in line
                                for line in traits))
            self.assertTrue(any(f"{stats['air_attack_multiplier']:g}" in line for line in traits))
            self.assertTrue(any(f"{stats['air_range_px']:g}" in line for line in traits))
        stats = dict(queries.get_unit_library()["V2 Rocket"])
        with mock.patch.object(queries, "get_unit_library", return_value={"Test Rocket": stats}):
            immune = queries.get_air_unit_traits("Test Rocket")
            stats["air_interception_immune"] = False
            interceptable = queries.get_air_unit_traits("Test Rocket")
        self.assertNotEqual(immune, interceptable)
        self.assertEqual(sum(a != b for a, b in zip(immune, interceptable)), 1)

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

    def test_air_roles_and_stats_share_ui_ai_unlocks(self):
        library = queries.get_unit_library()
        for key, (_, _, name) in REQUESTED_TREE.items():
            with self.subTest(tech=key):
                if key == "jet_engine":
                    self.assertNotIn(name, library)
                    self.assertEqual(ai_tech_eval.units_unlocked_by(key, {}, library), ())
                    continue
                self.assertTrue(library[name]["air_role"])
                self.assertGreater(library[name]["air_range_px"], 0)
                self.assertFalse(queries.is_unit_unlocked(name, {}))
                self.assertTrue(queries.is_unit_unlocked(name, {key: 1}))
                self.assertIn(name, ai_tech_eval.units_unlocked_by(key, {}, library))
                self.assertIn(name, ai_unit_eval.buildable_units({key: 1}, library))
                self.assertEqual(queries.classify_unit_group(name, library[name]),
                                 queries.UNIT_GROUP_AEROSPACE)
                created = queries.create_unit_dict(name, "A", library)
                self.assertEqual(created["type"], name)
                self.assertEqual(created["health"], library[name]["health"])
                self.assertTrue(queries.is_air_unit(created))

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
        self.assertTrue(queries.is_unit_unlocked("Biplane Fighter", country["research"]))

    def test_existing_save_shape_preserves_techs_progress_and_unit_queue(self):
        map_ref = sample_map_screen()
        country = map_ref.nation_data["Avaria"]
        country.update(research={key: 1 for key in REQUESTED_TREE},
                       research_queue=[{"tech_name": "jet_fighter", "points_remaining": 50}],
                       research_progress={"jet_engine": 75})
        province = next(iter(map_ref.map_data.values()))
        province["unit_queue"] = [{"unit_type": "Biplane Fighter", "turns_remaining": 1}]
        saved = json.loads(json.dumps(queries.build_save_dict(map_ref)))
        self.assertEqual(saved["nation_data"]["Avaria"], country)
        self.assertEqual(saved["provinces"]["(7, 0, 0)"]["unit_queue"], province["unit_queue"])
        # Old saves use a sparse research dictionary: missing new keys are locked.
        self.assertFalse(queries.is_unit_unlocked("Biplane Fighter", {"infantry_type": 1}))
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

    def test_new_bomber_research_is_authoritative(self):
        for tech_key, unit_name in (("biplane_bomber", "Biplane Bomber"), ("zeppelin", "Zeppelin")):
            self.setUp()
            command = {"type": "research_queue", "tech_names": [tech_key]}
            with self.assertRaises(RealtimeError):
                self.driver.validate_draft("A", [command])
            self.map.nation_data["A"]["research"] = {"biplane": 1}
            projects = self.driver.validate_draft("A", [command])[0]["projects"]
            self.assertEqual(projects[0]["tech_name"], tech_key)
            self.assertEqual(projects[0]["points_remaining"],
                             queries.get_tech_tree()[tech_key]["cost"])

    def test_unit_orders_need_research_and_ownership_and_use_server_stats(self):
        for tech_key, unit_name in (("biplane_bomber", "Biplane Bomber"), ("zeppelin", "Zeppelin")):
            self.setUp()
            command = {"type": "province_queue", "province_id": 1, "queue": "unit_queue",
                       "items": [{"unit_type": unit_name, "turns_remaining": 0, "refund": {}}]}
            with self.assertRaises(RealtimeError):
                self.driver.validate_draft("A", [command])
            self.map.nation_data["A"]["research"] = {tech_key: 1}
            canonical = self.driver.validate_draft("A", [command])[0]["items"][0]
            stats = queries.get_unit_library()[unit_name]
            self.assertEqual(canonical["turns_remaining"], stats["production_time"])
            self.assertEqual(canonical["refund"], {key: stats[key] for key in
                                                  ("cost_materials", "cost_manpower", "cost_fuel")})
            self.map.map_data["home"]["owner"] = "B"
            with self.assertRaises(RealtimeError):
                self.driver.validate_draft("A", [command])

    def test_tournament_import_preserves_aerospace_in_existing_move_fields(self):
        for tech_key, unit_name in (("biplane_bomber", "Biplane Bomber"), ("zeppelin", "Zeppelin")):
            self.setUp()
            harness = tournament_harness.TournamentMoveTests()
            host = tournament_harness.Host()
            host.map_data = {"home": {"id": 1, "json_key": "home", "owner": "Leader", "units": []}}
            move = harness.player_data("Leader", host)
            move["nation_data"]["research_queue"] = [{"tech_name": "jet_engine", "points_remaining": 50}]
            move["provinces"] = {"home": {"unit_queue": [{"unit_type": unit_name, "turns_remaining": 1}]}}
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

    def test_air_details_are_visible_cached_and_fit_above_modal_controls(self):
        from screens.map_related_screens import research
        self.research.start_research(self.map)
        for key, (year, _, name) in REQUESTED_TREE.items():
            if key == "jet_engine":
                continue
            with self.subTest(unit=name):
                self.research.open_modal({"tech_key": key, "level": 1, "status": "COMPLETED",
                    "display_name": name, "target_year": year, "icon": None,
                    "cost": self.research.tech_cost(key)})
                self.assertTrue(set(queries.get_air_unit_traits(name)).issubset(self.research.modal_unlocks))
                width = research.MODAL_WIDTH - research.MODAL_TEXT_X - research.MODAL_TEXT_RIGHT_MARGIN
                for rendered in self.research.modal_unlock_surfaces:
                    self.assertLessEqual(rendered.get_width(), width)
                content_bottom = (research.MODAL_BODY_START_Y + research.MODAL_LINE_STEP_Y
                    + len(self.research.modal_unlock_surfaces) * self.research.modal_unlock_line_step
                    + 2 * research.MODAL_LINE_STEP_Y + research.MODAL_ENTITY_PADDING_Y)
                self.assertLessEqual(content_bottom, research.MODAL_BTN_Y_OFFSET)
                with mock.patch.object(queries, "get_tech_unlocks", side_effect=AssertionError("frame traits")):
                    self.research.draw(self.surface)
        self.research.close_modal()

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
        expected = [name for key, (_, _, name) in REQUESTED_TREE.items()
                    if key != "jet_engine" and not queries.is_unit_obsolete(
                        name, self.map.nation_data[self.country]["research"])]
        self.assertEqual(aerospace_rows, len(expected))
        self.assertEqual(recruitment_rows, 1)
        self.assertNotIn("recruit", [prefix for prefix, *_ in SECTION_PANELS])
        self.assertGreater(self.production.aerospace_end_y, self.production.aerospace_start_y)
        self.production.draw(self.surface)

    def test_production_replacements_hide_default_rows_but_allow_custom_rows(self):
        country = self.map.nation_data[self.country]
        cases = aircraft_replacement_cases()
        self.assertTrue(cases)
        for obsolete, replacement, tech in cases:
            with self.subTest(unit=obsolete):
                country["research"] = {queries.get_unit_tech_key(obsolete): 1,
                                       tech: 0}
                country["custom_production_units"] = [obsolete]
                self.production.start_with_province(self.province, self.map)
                self.assertEqual(sum(stats is self.production.unit_library[obsolete] for _, stats, _, kind
                                     in self.production.active_bars if kind == "UNIT"), 2)
                country["research"][tech] = 1
                self.production.refresh_ui()
                rows = [(stats, y) for _, stats, y, kind in self.production.active_bars
                        if kind == "UNIT"]
                self.assertTrue(any(stats is self.production.unit_library[replacement]
                    and self.production.aerospace_start_y <= y < self.production.aerospace_end_y
                    for stats, y in rows))
                obsolete_rows = [y for stats, y in rows
                                 if stats is self.production.unit_library[obsolete]]
                self.assertEqual(len(obsolete_rows), 1)
                self.assertTrue(self.production.custom_start_y <= obsolete_rows[0] <
                                self.production.custom_end_y)

    def test_visible_production_categories_have_equal_gaps(self):
        from screens.map_related_screens.production import SECTION_PANELS, SECTION_SPACING
        for coastal in (False, True):
            with self.subTest(coastal=coastal):
                self.province["is_coastal"] = coastal
                self.production.start_with_province(self.province, self.map)
                sections = sorted((getattr(self.production, f"{prefix}_start_y"),
                                   getattr(self.production, f"{prefix}_end_y"))
                                  for prefix, *_ in SECTION_PANELS
                                  if getattr(self.production, f"{prefix}_end_y") >
                                     getattr(self.production, f"{prefix}_start_y"))
                for (_, previous_end), (next_start, _) in zip(sections, sections[1:]):
                    self.assertEqual(next_start - previous_end, SECTION_SPACING)

    def test_administration_heading_fits_below_header_at_top_scroll(self):
        from screens.map_related_screens.production import PANEL_LABEL_OFFSET_Y, PANEL_PAD_TOP
        from map_logic.rendering.font_manager import fonts
        self.production.start_with_province(self.province, self.map)
        self.production.target_scroll_y = self.production.scroll_y = 100
        self.production.enforce_scroll_bounds()
        heading_top = self.production.admin_start_y + PANEL_LABEL_OFFSET_Y + self.production.scroll_y
        self.assertGreaterEqual(heading_top, self.production.scroll_content_rect.top)
        self.assertLessEqual(heading_top + fonts.get("heading2").get_height(),
                             self.production.admin_start_y - PANEL_PAD_TOP)
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
                        self.production.buy_unit("Biplane Fighter")
            self.assertEqual(self.province["unit_queue"], [])
        self.production.buy_unit("Biplane Fighter")
        self.assertEqual(self.province["unit_queue"][0]["unit_type"], "Biplane Fighter")
