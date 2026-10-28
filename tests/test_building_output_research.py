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
from map_logic.turn_processing import economy_processor, research_processor
from tests.test_map_save_format import sample_map_screen


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
        for remaining in (19, 15, 11, 7, 3):
            province["building_queue"] = [{"item_name": "Basic Factory", "turns_remaining": remaining}]
            with patch.object(c, "NON_CORE_BUILDING_MULTIPLIER", 1):
                before = queries.get_province_building_output(province, {}, self.library)["materials"]
            after = queries.get_province_building_output(province, {"first": 2}, self.library)["materials"]
            self.assertEqual(after, int(before * 1.5 ** 2 * c.NON_CORE_BUILDING_MULTIPLIER))

    def test_turn_processor_applies_the_reported_income(self):
        country = {"research": {"first": 1}, **dict.fromkeys(c.ECON_RESOURCE_KEYS, 0)}
        game = SimpleNamespace(map_data={1: self.province()}, nation_data={"A": country},
                               tactical_mode=False, player_country="A")
        expected = queries.calculate_all_economies(game.map_data, game.nation_data)["A"]
        economy_processor.process_economy(game)
        for res in c.ECON_RESOURCE_KEYS:
            self.assertEqual(country[res], expected["total_inc"][res])

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


class FactoryResearchContentTests(unittest.TestCase):
    def test_requested_chain_dates_and_factory_only_material_bonus(self):
        tree = queries.get_tech_tree()
        self.assertEqual(tree["bessemer_process"]["years"], [1850])
        self.assertEqual(tree["assembly_line"]["years"], [1903])
        for tech, year in (("waltham_system", 1815), ("conveyor_belt", 1915),
                           ("just_in_time_manufacturing", 1945)):
            self.assertEqual(tree[tech]["years"], [year])
        self.assertEqual(tree["waltham_system"]["req"], {"basic_factory": 1})
        self.assertEqual(tree["waltham_system"]["building_output_bonuses"], [
            {"building_families": ["Basic Factory", "Factory"], "outputs": {"materials": 0.5}}])
        self.assertEqual(tree["bessemer_process"]["req"], {"waltham_system": 1})
        self.assertEqual(tree["assembly_line"]["req"], {"factory": 1})
        self.assertEqual(tree["conveyor_belt"]["req"], {"factory": 3})
        self.assertEqual(tree["just_in_time_manufacturing"]["req"], {"factory": 8})
        self.assertEqual(tree["factory"]["req"], {"bessemer_process": 1})
        self.assertEqual(tree["factory"]["level_reqs"], {
            "2": {"assembly_line": 1}, "4": {"conveyor_belt": 1}, "9": {"just_in_time_manufacturing": 1}})
        for tech in ("bessemer_process", "assembly_line"):
            self.assertEqual(tree[tech]["max_lvl"], 1)
            self.assertEqual(tree[tech]["building_output_bonuses"], [
                {"building_families": ["Basic Factory", "Factory"], "outputs": {"materials": 1.0}}])

    def test_research_selections_require_completed_links_and_editor_grants_them(self):
        tree = queries.get_tech_tree()
        for tech, predecessor, required in (("waltham_system", "basic_factory", 1),
                                           ("bessemer_process", "waltham_system", 1),
                                           ("assembly_line", "factory", 1), ("conveyor_belt", "factory", 3),
                                           ("just_in_time_manufacturing", "factory", 8),
                                           ("factory", "bessemer_process", 1)):
            with self.subTest(tech=tech):
                with self.assertRaises(ValueError):
                    queries.canonical_research_selection({"research": {}}, [tech], tree)
                result = queries.canonical_research_selection({"research": {predecessor: required}}, [tech], tree)
                self.assertEqual(result["projects"][0]["points_remaining"], tree[tech]["cost"])
        levels = queries.edited_research_levels({}, "factory", 1, True, tree)
        self.assertNotIn("assembly_line", levels)
        levels = queries.edited_research_levels(levels, "factory", 2, True, tree)
        for tech in ("basic_factory", "bessemer_process", "assembly_line"):
            self.assertEqual(levels[tech], 1)
        self.assertEqual(levels["factory"], 2)
        for level in (1, 2):
            country = {"research": {"factory": level, "bessemer_process": 1}}
            with self.assertRaises(ValueError):
                queries.canonical_research_selection(country, ["factory"], tree)
            country["research"]["assembly_line"] = 1
            self.assertEqual(queries.canonical_research_selection(country, ["factory"], tree)["projects"],
                             [{"tech_name": "factory", "points_remaining": tree["factory"]["cost"]}])
        without_assembly = queries.edited_research_levels(levels, "assembly_line", 1, False, tree)
        self.assertEqual(without_assembly["factory"], 1)
        removed = queries.edited_research_levels(levels, "bessemer_process", 1, False, tree)
        self.assertEqual(removed["basic_factory"], 1)
        for tech in ("bessemer_process", "assembly_line", "factory"):
            self.assertEqual(removed[tech], 0)

    def test_later_gates_grant_and_remove_only_the_dependent_factory_levels(self):
        tree = queries.get_tech_tree()
        for gate, lower, upper in (("conveyor_belt", 3, 4), ("just_in_time_manufacturing", 8, 9)):
            with self.subTest(gate=gate):
                before = queries.edited_research_levels({}, "factory", lower, True, tree)
                self.assertNotIn(gate, before)
                with self.assertRaises(ValueError):
                    queries.canonical_research_selection({"research": before}, ["factory"], tree)
                after = queries.edited_research_levels({}, "factory", upper, True, tree)
                self.assertEqual(after[gate], 1)
                removed = queries.edited_research_levels(after, gate, 1, False, tree)
                self.assertEqual(removed["factory"], lower)
        all_levels = queries.edited_research_levels({}, "factory", tree["factory"]["max_lvl"], True, tree)
        removed = queries.edited_research_levels(all_levels, "waltham_system", 1, False, tree)
        self.assertEqual(removed["basic_factory"], 1)
        for tech in ("bessemer_process", "assembly_line", "conveyor_belt", "just_in_time_manufacturing", "factory"):
            self.assertEqual(removed[tech], 0)

    def test_output_upgrades_affect_every_factory_tier_and_only_its_materials(self):
        library = queries.get_building_library()
        research = {"waltham_system": 1, "bessemer_process": 1, "assembly_line": 1}
        material_factor = 1.0
        for tech in research:
            material_factor *= 1 + queries.get_tech_tree()[tech]["building_output_bonuses"][0]["outputs"]["materials"]
        multipliers = queries.get_building_output_multipliers(research, library)
        for name, stats in library.items():
            is_factory = name == "Basic Factory" or name.startswith("Factory Lvl ")
            with self.subTest(building=name):
                output = queries.get_building_output(name, research, library, multipliers=multipliers)
                for res in c.ECON_RESOURCE_KEYS:
                    factor = material_factor if is_factory and res == "materials" else 1
                    self.assertEqual(output[res], stats.get(f"prod_{res}", 0) * factor)

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
            self.assertEqual(queries.get_building_output("Factory Lvl 1", loaded["Avaria"]["research"]),
                             queries.get_building_output("Factory Lvl 1", research))

    def test_completion_changes_yields_without_mutating_building_data(self):
        library = queries.get_building_library()
        original = copy.deepcopy(library)
        game = SimpleNamespace(nation_data={"A": {"research": {"basic_factory": 1},
            "research_queue": [{"tech_name": "bessemer_process", "points_remaining": 1}]}},
            time_manager=SimpleNamespace(year=2000, month_index=0, day=1), scenario_settings={},
            player_country="A", show_feedback=Mock())
        research_processor.process_national_research(game)
        country = game.nation_data["A"]
        self.assertEqual(country["research"]["bessemer_process"], 1)
        for name in ("Basic Factory", "Factory Lvl 1"):
            self.assertEqual(queries.get_building_output(name, country["research"])["materials"],
                             library[name]["prod_materials"] * 2)
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

    def test_new_research_node_opens_details_and_starts_the_authoritative_project(self):
        from screens.map_related_screens.research import Research_Screen
        self.game.nation_data[self.country]["research"]["waltham_system"] = 1
        screen = Research_Screen()
        screen.start_research(self.game)
        screen.set_category("INDUSTRY")
        button = next(button for button in screen.elements if getattr(button, "text", "") == "Bessemer Process")
        button.callback()
        self.assertEqual(screen.active_modal["tech_key"], "bessemer_process")
        self.assertEqual(screen.active_modal["status"], "AVAILABLE")
        self.assertTrue(screen.modal_unlocks)
        with patch.object(queries, "get_building_output", side_effect=AssertionError("frame output rules")):
            screen.draw(self.surface)
        screen.modal_start_research()
        country = self.game.nation_data[self.country]
        self.assertEqual(country["research_queue"], [{"tech_name": "bessemer_process",
            "points_remaining": queries.get_tech_tree(self.game)["bessemer_process"]["cost"]}])
        self.assertNotIn("bessemer_process", country["research"])

    def test_added_industry_nodes_open_details_and_queue_through_player_controls(self):
        from screens.map_related_screens.research import Research_Screen
        for tech in ("waltham_system", "conveyor_belt", "just_in_time_manufacturing"):
            with self.subTest(tech=tech):
                country = self.game.nation_data[self.country]
                levels = queries.edited_research_levels({}, tech, 1, True, context=self.game)
                levels.pop(tech)
                country.update(research=levels, research_queue=[], research_progress={})
                screen = Research_Screen()
                screen.start_research(self.game)
                screen.set_category("INDUSTRY")
                button = next(button for button in screen.elements
                              if getattr(button, "text", "") == queries.get_tech_display_name(tech, context=self.game))
                button.callback()
                self.assertEqual(screen.active_modal["tech_key"], tech)
                self.assertEqual(screen.active_modal["status"], "AVAILABLE")
                self.assertTrue(screen.modal_unlocks)
                screen.modal_start_research()
                self.assertEqual(country["research_queue"], [{"tech_name": tech,
                    "points_remaining": queries.get_tech_tree(self.game)[tech]["cost"]}])

    def test_production_prepares_effective_yields_once_and_keeps_library_data_unchanged(self):
        from screens.map_related_screens.production import Production_Screen
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
                bonus = 2 if res == "materials" else 1
                self.assertEqual(stats[f"prod_{res}"],
                                 int(library["Factory Lvl 1"][f"prod_{res}"] * bonus * c.NON_CORE_BUILDING_MULTIPLIER))
            with patch.object(queries, "get_province_building_output", side_effect=AssertionError("frame output rules")):
                screen.update()
                screen.draw(self.surface)
        self.assertEqual(library, original)


if __name__ == "__main__":
    unittest.main()
