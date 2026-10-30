"""Research output bonuses share targeting, economy, preview, and AI rules."""

import copy
import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import data.constants as c
from data import queries
from data.runtime_rules import ActiveLibrary, RuntimeRules
from map_logic.ai import ai_tech_eval
from map_logic.system32 import economy_processor, research_processor
from tests.stub_map_screen import map_double, sample_map_screen
from tests.research_fixtures import research_lock_cases


def building(materials, manpower, fuel, group):
    return dict(prod_materials=materials, prod_manpower=manpower, prod_fuel=fuel,
                cost_materials=0, cost_manpower=0, cost_fuel=0, time=1, group=group)


class OutputBonusTests(unittest.TestCase):
    def setUp(self):
        self.library = {
            "Basic Factory": building(31, 7, 5, "industry"),
            "Factory Lvl 1": building(47, 11, 13, "industry"),
            "Workshop": building(19, 3, 2, "industry"),
            "Recruitment Building Lvl 1": building(0, 29, 17, "recruitment"),
        }
        self.tree = {
            "first": {"max_lvl": 2, "building_output_bonuses": [
                {"building_families": ["Basic Factory", "Factory"], "outputs": {"materials": 0.5}}]},
            "second": {"max_lvl": 1, "building_output_bonuses": [
                {"building_families": ["Factory"], "outputs": {"materials": 0.25}}]},
            "recruit": {"max_lvl": 1, "building_output_bonuses": [
                {"building_groups": ["recruitment"], "outputs": {"fuel": 0.5, "manpower": 1.0}}]},
        }
        self.enterContext(patch.object(queries, "get_tech_tree", return_value=self.tree))
        self.enterContext(patch.object(queries, "get_building_library", return_value=self.library))
        self.enterContext(patch.object(queries, "get_unit_library", return_value={}))

    def output(self, name, research):
        return queries.get_building_output(name, research, self.library)

    def province(self, core=True):
        return {"owner": "A", "cores": ["A"] if core else [],
                "buildings": list(self.library), "units": [], "resources": {"Iron": 23, "Oil": 29}}

    def test_family_bonus_compounds_per_level_and_leaves_other_outputs_and_workshops_unchanged(self):
        research = {"first": 2, "second": 1}
        self.assertEqual(self.output("Factory Lvl 1", research),
                         {"materials": 47 * 1.5 ** 2 * 1.25, "manpower": 11, "fuel": 13})
        self.assertEqual(self.output("Basic Factory", research)["materials"], 31 * 1.5 ** 2)
        self.assertEqual(self.output("Workshop", research), {"materials": 19, "manpower": 3, "fuel": 2})
        self.assertEqual(self.output("Factory Lvl 1", {}), {"materials": 47, "manpower": 11, "fuel": 13})

    def test_group_bonus_can_change_manpower_and_fuel_without_creating_other_resources(self):
        self.assertEqual(self.output("Recruitment Building Lvl 1", {"recruit": 1}),
                         {"materials": 0, "manpower": 58, "fuel": 25.5})
        self.assertEqual(self.output("Factory Lvl 1", {"recruit": 1}), self.output("Factory Lvl 1", {}))

    def test_flat_bonuses_add_per_level_before_percentages_and_cap_at_maximum_level(self):
        self.tree["flat"] = {"max_lvl": 2, "building_output_bonuses": [
            {"building_families": ["Basic Factory"], "flat_outputs": {"materials": 13, "fuel": 17}}]}
        research = {"flat": 9, "first": 1}
        self.assertEqual(self.output("Basic Factory", research),
                         {"materials": (31 + 26) * 1.5, "manpower": 7, "fuel": 5 + 34})
        self.assertEqual(self.output("Factory Lvl 1", research), self.output("Factory Lvl 1", {"first": 1}))
        self.library["Basic Factory"]["prod_fuel"] = 0
        self.assertEqual(self.output("Basic Factory", {"flat": 1})["fuel"], 17)
        self.tree["flat"]["building_output_bonuses"][0]["flat_outputs"]["materials"] = 19
        self.assertEqual(self.output("Basic Factory", {"flat": 1})["materials"], 31 + 19)
        self.assertTrue(queries.get_tech_unlocks("flat", 1))

    def test_flat_bonus_reaches_income_construction_and_ai_without_affecting_other_factories(self):
        self.tree["flat"] = {"max_lvl": 1, "building_output_bonuses": [
            {"building_families": ["Basic Factory"], "flat_outputs": {"materials": 13}}]}
        province = self.province()
        province["buildings"] = ["Basic Factory", "Factory Lvl 1"]
        research = {"flat": 1}
        expected = 31 + 13 + 47
        self.assertEqual(queries.get_province_building_output(province, research, self.library)["materials"], expected)
        country = {"research": research, **dict.fromkeys(c.ECON_RESOURCE_KEYS, 0)}
        game = map_double(map_data={1: province}, nation_data={"A": country}, tactical_mode=False, player_country="A")
        report = queries.calculate_all_economies(game.map_data, game.nation_data)["A"]
        self.assertEqual(report["breakdown"]["materials"]["buildings"], expected)
        economy_processor.process_economy(game)
        self.assertEqual(country["materials"], report["total_inc"]["materials"])
        prices = dict.fromkeys(c.ECON_RESOURCE_KEYS, 1)
        self.assertEqual(ai_tech_eval.economy_gain("flat", 1, prices, self.library, {}, provinces=[province]), 13)
        province["buildings"] = ["Factory Lvl 1"]
        self.assertEqual(ai_tech_eval.economy_gain("flat", 1, prices, self.library, {}, provinces=[province]), 0)
        province["buildings"] = []
        province["building_queue"] = [{"item_name": "Basic Factory", "turns_remaining": 3}]
        fraction = c.BASIC_FACTORY_CONSTRUCTION_OUTPUT_FRACTIONS[-1]
        self.assertEqual(queries.get_province_building_output(province, research, self.library)["materials"],
                         int((31 + 13) * fraction))
        self.assertEqual(ai_tech_eval.economy_gain("flat", 1, prices, self.library, {}, provinces=[province]),
                         int((31 + 13) * fraction) - int(31 * fraction))

    def test_output_changes_refresh_after_research_and_library_edits(self):
        research = {"first": 1}
        self.assertEqual(self.output("Basic Factory", research)["materials"], 31 * 1.5)
        self.tree["first"]["building_output_bonuses"][0]["outputs"]["materials"] = 0.25
        self.library["Basic Factory"]["prod_materials"] = 40
        self.assertEqual(self.output("Basic Factory", research)["materials"], 50)

    def test_matching_both_selectors_applies_a_bonus_once(self):
        bonus = self.tree["recruit"]["building_output_bonuses"][0]
        bonus["building_families"] = ["Recruitment Building"]
        self.assertEqual(self.output("Recruitment Building Lvl 1", {"recruit": 1})["manpower"], 58)

    def test_unknown_technology_and_buildings_have_no_bonus_and_inputs_stay_unchanged(self):
        before = copy.deepcopy((self.library, self.tree))
        self.assertEqual(self.output("Unknown", {"first": 1}), dict.fromkeys(c.ECON_RESOURCE_KEYS, 0))
        self.assertEqual(self.output("Basic Factory", {"legacy": 9}), self.output("Basic Factory", {}))
        self.assertEqual((self.library, self.tree), before)

    def test_territory_penalty_and_rounding_match_economy_reports(self):
        research = {"first": 1, "recruit": 1}
        for core in (True, False):
            province = self.province(core)
            mult = 1 if core else c.NON_CORE_BUILDING_MULTIPLIER
            expected = {res: sum(int(self.output(name, research)[res] * mult) for name in self.library)
                        for res in c.ECON_RESOURCE_KEYS}
            actual = queries.get_province_building_output(province, research, self.library)
            self.assertEqual(actual, expected)
            before = queries.calculate_all_economies({1: province}, {"A": {"research": {}}})["A"]
            after = queries.calculate_all_economies({1: province}, {"A": {"research": research}})["A"]
            for res in c.ECON_RESOURCE_KEYS:
                self.assertEqual(after["breakdown"][res]["buildings"], expected[res])
                for category in ("base", "core", "non_core", "resources"):
                    self.assertEqual(before["breakdown"][res][category], after["breakdown"][res][category])

    def test_factory_construction_yields_use_the_same_bonus_and_territory_penalty(self):
        province = self.province(False)
        province["buildings"] = []
        fractions = c.BASIC_FACTORY_CONSTRUCTION_OUTPUT_FRACTIONS
        for stage, fraction in enumerate(fractions):
            remaining = c.BASIC_FACTORY_TURNS - stage * (c.BASIC_FACTORY_TURNS // len(fractions)) - 1
            province["building_queue"] = [{"item_name": "Basic Factory", "turns_remaining": remaining}]
            after = queries.get_province_building_output(province, {"first": 2}, self.library)["materials"]
            self.assertEqual(after, int(self.library["Basic Factory"]["prod_materials"] * fraction
                                        * 1.5 ** 2 * c.NON_CORE_BUILDING_MULTIPLIER))

    def test_turn_processor_applies_the_reported_income(self):
        country = {"research": {"first": 1}, **dict.fromkeys(c.ECON_RESOURCE_KEYS, 0)}
        game = map_double(map_data={1: self.province()}, nation_data={"A": country},
                               tactical_mode=False, player_country="A")
        expected = queries.calculate_all_economies(game.map_data, game.nation_data)["A"]
        economy_processor.process_economy(game)
        for res in c.ECON_RESOURCE_KEYS:
            self.assertEqual(country[res], expected["total_inc"][res])

    def test_shared_sweep_tables_give_each_nation_its_own_research_output(self):
        # One economy sweep shares building tables between nations with the same
        # output research. Each nation must still get its uncached building output.
        research_by_nation = {"A": {"first": 1, "recruit": 1}, "B": {"first": 1, "recruit": 1},
                              "C": {"first": 2}, "D": {"first": 9}, "E": {"recruit": 1, "first": 1},
                              "F": {}, "G": {"first": 1, "recruit": 1}}
        map_data = {}
        for index, name in enumerate(research_by_nation):
            province = self.province()
            province["owner"], province["cores"] = name, [name]
            map_data[index] = province
        nation_data = {name: {"research": research} for name, research in research_by_nation.items()}
        report = queries.calculate_all_economies(map_data, nation_data)
        for index, (name, research) in enumerate(research_by_nation.items()):
            expected = queries.get_province_building_output(map_data[index], research, self.library)
            with self.subTest(nation=name):
                for res in c.ECON_RESOURCE_KEYS:
                    self.assertEqual(report[name]["breakdown"][res]["buildings"], expected[res])

        cache = {}
        shared = queries.get_building_output_modifiers(research_by_nation["A"], self.library, cache=cache)
        self.assertIs(queries.get_building_output_modifiers(research_by_nation["B"], self.library, cache=cache),
                      shared)
        self.assertIsNot(queries.get_building_output_modifiers(research_by_nation["C"], self.library, cache=cache),
                         shared)
        self.assertEqual(queries.get_building_output_modifiers(research_by_nation["D"], self.library, cache=cache),
                         queries.get_building_output_modifiers(research_by_nation["C"], self.library))

    def test_ai_values_the_actual_increment_on_owned_buildings(self):
        province = self.province(False)
        prices = {"materials": 3, "manpower": 2, "fuel": 7}
        research = {"first": 1}
        before = queries.get_province_building_output(province, research, self.library)
        after = queries.get_province_building_output(province, {"first": 2}, self.library)
        value = ai_tech_eval.economy_gain("first", 2, prices, self.library, {},
                                        research=research, provinces=[province])
        self.assertEqual(value, sum(prices[res] * (after[res] - before[res]) for res in prices))
        self.assertEqual(ai_tech_eval.economy_gain("first", 2, prices, self.library, {}), 0)

    def test_ai_building_upgrades_include_completed_output_bonuses(self):
        self.library["Factory Lvl 1"]["req"] = "Basic Factory"
        prices = dict.fromkeys(c.ECON_RESOURCE_KEYS, 1)
        research = {"first": 2}
        old = self.output("Basic Factory", research)
        new = self.output("Factory Lvl 1", research)
        self.assertEqual(ai_tech_eval.economy_gain("factory", 1, prices, self.library, {}, research=research),
                         sum(new[res] - old[res] for res in prices))

    def test_ai_values_a_gate_from_the_next_reachable_upgrade_and_both_research_costs(self):
        self.tree.update(gate={"max_lvl": 1, "cost": 20}, factory={
            "max_lvl": 2, "cost": 40, "level_reqs": {"2": {"gate": 1}}})
        self.library["Factory Lvl 2"] = dict(building(100, 11, 13, "industry"), req="Factory Lvl 1")
        prices = dict.fromkeys(c.ECON_RESOURCE_KEYS, 1)
        research = {"factory": 1}
        gain = (self.library["Factory Lvl 2"]["prod_materials"]
                - self.library["Factory Lvl 1"]["prod_materials"])
        value = ai_tech_eval.economy_gain("gate", 1, prices, self.library, {}, research=research)
        self.assertAlmostEqual(value, gain * 20 / (20 + 40))
        self.assertEqual(queries.get_tech_level_gate_unlocks("gate", 1), [("factory", 2)])
        self.assertTrue(queries.get_tech_unlocks("gate", 1))
        self.assertEqual(ai_tech_eval.economy_gain("gate", 1, prices, self.library, {}, research={}), 0)
        with patch.object(c, "AI_MAX_BUILDING_RESEARCH_LEAD", 1):
            self.assertEqual(ai_tech_eval.economy_gain("gate", 1, prices, self.library, {},
                                                     built={"factory": 0}, research=research), 0)
        self.tree["factory"]["req"] = {"other": 1}
        self.assertEqual(ai_tech_eval.economy_gain("gate", 1, prices, self.library, {}, research=research), 0)

    def test_ai_values_consecutive_prerequisite_only_steps_through_their_eventual_output(self):
        self.tree.update({
            "first_gate": {"max_lvl": 1, "cost": 20, "req": {}},
            "second_gate": {"max_lvl": 1, "cost": 40, "req": {"first_gate": 1}},
            "output": {"max_lvl": 1, "cost": 60, "req": {"second_gate": 1},
                       "building_output_bonuses": [
                           {"building_families": ["Basic Factory"], "flat_outputs": {"materials": 13}}]},
        })
        prices = dict.fromkeys(c.ECON_RESOURCE_KEYS, 1)
        self.assertEqual(queries.get_tech_level_gate_unlocks("first_gate", 1), [("second_gate", 1)])
        self.assertTrue(queries.get_tech_unlocks("first_gate", 1))
        value = ai_tech_eval.economy_gain("first_gate", 1, prices, self.library, {},
                                         research={}, provinces=[self.province()])
        self.assertGreater(value, 0)
        self.assertLessEqual(value, 13)


class ResearchGraphRuleTests(unittest.TestCase):
    """Use an artificial tree so research rules stay independent of current content."""

    TREE = {
        "root": {"category": "INDUSTRY", "cost": 7, "max_lvl": 1, "req": {}, "years": [1800]},
        "middle": {"category": "INDUSTRY", "cost": 11, "max_lvl": 1, "req": {"root": 1}, "years": [1810]},
        "gated": {"category": "INDUSTRY", "cost": 13, "max_lvl": 3, "req": {"middle": 1},
                  "level_reqs": {"2": {"gate_a": 1}, "3": {"gate_b": 1}}, "years": [1820, 1830, 1840]},
        "gate_a": {"category": "INDUSTRY", "cost": 17, "max_lvl": 1, "req": {"gated": 1}, "years": [1825]},
        "gate_b": {"category": "INDUSTRY", "cost": 19, "max_lvl": 1, "req": {"gated": 2}, "years": [1835]},
        "unrelated": {"category": "INDUSTRY", "cost": 23, "max_lvl": 1, "req": {"root": 1}, "years": [1815]},
    }

    def test_selection_requires_each_link_and_charges_the_tech_cost(self):
        for tech, predecessor, required in (("middle", "root", 1), ("gated", "middle", 1),
                                            ("gate_a", "gated", 1), ("gate_b", "gated", 2)):
            with self.subTest(tech=tech):
                with self.assertRaises(ValueError):
                    queries.canonical_research_selection({"research": {}}, [tech], self.TREE)
                result = queries.canonical_research_selection(
                    {"research": {predecessor: required}}, [tech], self.TREE)
                self.assertEqual(result["projects"], [{"tech_name": tech, "points_remaining": self.TREE[tech]["cost"]}])

    def test_level_gates_block_only_the_level_they_guard(self):
        country = {"research": queries.edited_research_levels({}, "gated", 1, True, self.TREE)}
        with self.assertRaises(ValueError):
            queries.canonical_research_selection(country, ["gated"], self.TREE)
        country["research"]["gate_a"] = 1
        self.assertEqual(queries.canonical_research_selection(country, ["gated"], self.TREE)["projects"],
                         [{"tech_name": "gated", "points_remaining": self.TREE["gated"]["cost"]}])
        with self.assertRaises(ValueError):
            queries.canonical_research_selection(dict(country, research=dict(country["research"], gated=2)),
                                                 ["gated"], self.TREE)

    def test_editor_grants_only_the_prerequisites_of_the_requested_level(self):
        levels = queries.edited_research_levels({}, "gated", 1, True, self.TREE)
        self.assertEqual(levels, {"root": 1, "middle": 1, "gated": 1})
        levels = queries.edited_research_levels(levels, "gated", 3, True, self.TREE)
        self.assertEqual(levels, {"root": 1, "middle": 1, "gated": 3, "gate_a": 1, "gate_b": 1})

    def test_editor_removal_removes_only_dependent_levels(self):
        full = queries.edited_research_levels({}, "gated", 3, True, self.TREE)
        full["unrelated"] = 1
        removed = queries.edited_research_levels(full, "gate_b", 1, False, self.TREE)
        self.assertEqual((removed["gated"], removed["gate_a"], removed["gate_b"]), (2, 1, 0))
        removed = queries.edited_research_levels(full, "gate_a", 1, False, self.TREE)
        self.assertEqual((removed["gated"], removed["gate_a"], removed["gate_b"]), (1, 0, 0))
        removed = queries.edited_research_levels(full, "middle", 1, False, self.TREE)
        self.assertEqual((removed["root"], removed["unrelated"]), (1, 1))
        for tech in ("middle", "gated", "gate_a", "gate_b"):
            self.assertEqual(removed[tech], 0)

    def test_date_based_starts_use_each_year_as_an_exclusive_boundary(self):
        with patch.object(queries, "get_tech_tree", return_value=self.TREE):
            for tech, entry in self.TREE.items():
                for level, year in enumerate(entry["years"], 1):
                    with self.subTest(tech=tech, level=level):
                        self.assertLess(queries.get_time_appropriate_research(year)[tech], level)
                        self.assertGreaterEqual(queries.get_time_appropriate_research(year + 1)[tech], level)


class FactoryResearchContentTests(unittest.TestCase):
    def test_every_technology_has_one_ordered_year_for_each_level(self):
        for tech, entry in queries.get_tech_tree().items():
            with self.subTest(tech=tech):
                self.assertEqual(len(entry["years"]), entry["max_lvl"])
                self.assertEqual(entry["years"], sorted(entry["years"]))

    def test_every_gated_step_in_the_active_tree_is_enforced(self):
        tree = queries.get_tech_tree()
        for category in dict.fromkeys(entry["category"] for entry in tree.values()):
            for tech, locked, unlocked in research_lock_cases(tree, category):
                with self.subTest(tech=tech, level=unlocked[tech] + 1):
                    with self.assertRaises(ValueError):
                        queries.canonical_research_selection({"research": locked}, [tech], tree)
                    selection = queries.canonical_research_selection({"research": unlocked}, [tech], tree)
                    self.assertEqual(selection["projects"], [{"tech_name": tech, "points_remaining": tree[tech]["cost"]}])

    def test_output_bonus_records_name_real_targets_and_resources(self):
        library = queries.get_building_library()
        groups = {stats.get("group") for stats in library.values()}
        families = {queries.get_base_item_name(name) for name in library}
        for tech, entry in queries.get_tech_tree().items():
            for bonus in entry.get("building_output_bonuses", []):
                with self.subTest(tech=tech):
                    self.assertTrue(set(bonus.get("building_families", [])) <= families)
                    self.assertTrue(set(bonus.get("building_groups", [])) <= groups)
                    outputs = {*bonus.get("outputs", {}), *bonus.get("flat_outputs", {})}
                    self.assertTrue(outputs)
                    self.assertTrue(outputs <= set(c.ECON_RESOURCE_KEYS))

    def test_older_factory_projects_keep_progress_without_granting_the_new_technologies(self):
        project = {"tech_name": "factory", "points_remaining": 41}
        country = {"research": {"basic_factory": 1}, "research_queue": [project]}
        before = copy.deepcopy(country)
        result = queries.canonical_research_selection(country, ["factory"])
        self.assertEqual(result["projects"], [project])
        self.assertEqual(country, before)

    def test_existing_save_and_missing_keys_preserve_research_without_bonus_grants(self):
        completed = queries.edited_research_levels({}, "factory", 9, True)
        for research in ({"factory": 2}, {"factory": 8, "bessemer_process": 1}, completed):
            game = sample_map_screen()
            game.nation_data["Avaria"]["research"] = dict(research)
            game.map_data[(7, 0, 0)]["buildings"] = ["Factory Lvl 1"]
            saved = json.loads(json.dumps(queries.build_save_dict(game)))
            loaded = queries.merge_country_templates(saved["nation_data"])
            self.assertEqual(loaded["Avaria"]["research"], research)
            for building_name in ("Basic Factory", "Factory Lvl 1"):
                self.assertEqual(queries.get_building_output(building_name, loaded["Avaria"]["research"]),
                                 queries.get_building_output(building_name, research))

    def test_completion_changes_yields_without_mutating_building_data(self):
        library = {"Basic Factory": building(31, 7, 5, "industry"), "Factory Lvl 1": building(47, 11, 13, "industry")}
        original = copy.deepcopy(library)
        tree = {"upgrade": {"max_lvl": 1, "cost": 1, "years": [1800], "building_output_bonuses": [
            {"building_families": ["Basic Factory"], "flat_outputs": {"materials": 19}}]}}
        game = map_double(nation_data={"A": {"research": {},
            "research_queue": [{"tech_name": "upgrade", "points_remaining": 1}]}},
            time_manager=SimpleNamespace(year=2000, month_index=0, day=1), scenario_settings={},
            player_country="A", show_feedback=Mock())
        with patch.object(queries, "get_tech_tree", return_value=tree), \
                patch.object(queries, "get_building_library", return_value=library):
            research_processor.process_national_research(game)
            country = game.nation_data["A"]
            self.assertEqual(country["research"]["upgrade"], 1)
            self.assertEqual(queries.get_building_output("Basic Factory", country["research"], library)["materials"], 31 + 19)
            self.assertEqual(queries.get_building_output("Factory Lvl 1", country["research"], library)["materials"], 47)
        self.assertEqual(library, original)

    def test_active_world_bonuses_do_not_leak_between_worlds(self):
        def library_with_bonus(amount):
            runtime = RuntimeRules()
            for name, contents in {
                "unit_library": {}, "building_library": {"Fixture": building(12, 0, 0, "custom")},
                "tech_tree": {"upgrade": {"max_lvl": 1, "building_output_bonuses": [
                    {"building_groups": ["custom"], "outputs": {"materials": amount}}]}}}.items():
                runtime.libraries[name] = ActiveLibrary(runtime)
                runtime.libraries[name].update(contents)
            return runtime.libraries["building_library"]
        for amount in (0.25, 2.0, 0.25):
            library = library_with_bonus(amount)
            self.assertEqual(queries.get_building_output("Fixture", {"upgrade": 1}, library)["materials"],
                             12 * (1 + amount))


class OutputResearchScreenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests import app_harness
        cls.controller, cls.surface = app_harness.boot()
        cls.game = app_harness.boot_map()

    def setUp(self):
        self.enterContext(patch.object(self.game, "nation_data", copy.deepcopy(self.game.nation_data)))
        self.country = next(iter(queries.get_living_nations(self.game.map_data)))
        self.enterContext(patch.object(self.game, "player_country", self.country))
        for flag in ("is_editor", "tactical_mode", "realtime_multiplayer", "multiplayer_mode"):
            self.enterContext(patch.object(self.game, flag, False))
        self.enterContext(patch.object(self.game, "viewing_research_country", "", create=True))
        self.game.nation_data[self.country].update(research={"basic_factory": 1}, research_queue=[], research_progress={})

    def test_research_nodes_open_details_and_start_the_authoritative_project(self):
        from screens.game.research import Research_Screen
        tree = queries.get_tech_tree(self.game)
        techs = [key for key, entry in tree.items() if entry["category"] == "INDUSTRY" and entry["max_lvl"] == 1]
        self.assertTrue(techs)
        for tech in techs:
            with self.subTest(tech=tech):
                country = self.game.nation_data[self.country]
                levels = queries.edited_research_levels({}, tech, 1, True, context=self.game)
                levels.pop(tech)
                country.update(research=levels, research_queue=[], research_progress={})
                screen = Research_Screen()
                screen.start_research(self.game)
                screen.set_category("INDUSTRY")
                button = next(button for button in screen.elements
                              if getattr(button, "is_tech_node", False)
                              and button.text == screen.get_display_name(tech, 1))
                button.callback()
                self.assertEqual(screen.active_modal["tech_key"], tech)
                self.assertEqual(screen.active_modal["status"], "AVAILABLE")
                with patch.object(queries, "get_building_output", side_effect=AssertionError("frame output rules")):
                    screen.draw(self.surface)
                screen.modal_start_research()
                self.assertEqual(country["research_queue"], [{"tech_name": tech, "points_remaining": tree[tech]["cost"]}])
                self.assertNotIn(tech, country["research"])

    def test_production_prepares_effective_yields_once_and_keeps_library_data_unchanged(self):
        from screens.game.production import Production_Screen
        library = {"Basic Factory": building(31, 7, 5, "industry"),
                   "Factory Lvl 1": dict(building(47, 11, 13, "industry"), req="Basic Factory")}
        original = copy.deepcopy(library)
        self.game.nation_data[self.country]["research"].update(factory=1, bessemer_process=1)
        province = copy.deepcopy(next(province for province in self.game.map_data.values()
                                      if province.get("owner") == self.country))
        province.update(buildings=["Basic Factory"], cores=[], building_queue=[], unit_queue=[])
        with patch.object(queries, "get_building_library", return_value=library):
            screen = Production_Screen()
            screen.start_with_province(province, self.game)
            stats = next(stats for _, stats, _, kind in screen.active_bars
                         if kind == "BUILDING" and stats.get("group") == "industry")
            for res in c.ECON_RESOURCE_KEYS:
                self.assertEqual(stats[f"prod_{res}"],
                                 int(library["Factory Lvl 1"][f"prod_{res}"] * c.NON_CORE_BUILDING_MULTIPLIER))
            with patch.object(queries, "get_province_building_output", side_effect=AssertionError("frame output rules")):
                screen.update()
                screen.draw(self.surface)
        self.assertEqual(library, original)


if __name__ == "__main__":
    unittest.main()
