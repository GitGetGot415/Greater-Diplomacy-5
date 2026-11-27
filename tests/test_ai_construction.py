"""Which buildings the AI puts up, and how many.

Construction used to wait for a flat materials hoard, then build one thing a
turn, choosing factory or recruitment centre by shuffling a list. It now values
each option the way the Production screen describes it to a player -- what the
building adds to that province (queries.group_yields) -- net of its real cost,
with the payback rule research already used (ai_tech_eval.building_net_value),
priced in the nation's own scarcity.

Every building here is a fixture; nothing reads the real library.
"""

import unittest
from unittest.mock import patch

import data.constants as c
from data import queries
from map_logic.ai import ai_construction, ai_tuning, ai_unit_eval
from tests.stub_map_screen import map_double


def building(group, **prod):
    stats = {"group": group, "time": 2, "cost_materials": 100, "cost_manpower": 0, "cost_fuel": 0}
    for res in ("materials", "manpower", "fuel"):
        stats[f"prod_{res}"] = prod.get(res, 0)
    return stats


LIBRARY = {
    "Fixture Works": building("industry", materials=50),
    "Fixture Hall": building("recruitment", manpower=50),
}


def province(pid, *, factory=True, neighbors=()):
    # "Basic Factory" is outside the fixture library: it only satisfies the
    # Production screen's rule that recruitment needs a factory on the tile.
    return {"id": pid, "json_key": str(pid), "owner": "Avaria", "cores": ["Avaria"],
            "buildings": ["Basic Factory"] if factory else [], "building_queue": [],
            "unit_queue": [], "units": [], "neighbors": list(neighbors), "terrain": "plains"}


def economy(income, upkeep):
    """The state the purchase loop hands construction: income and upkeep per resource."""
    return {
        "econ": {"total_inc": dict(income), "upkeep": dict(upkeep)},
        "inc_man": income["manpower"], "inc_mat": income["materials"], "inc_fuel": income["fuel"],
        "upk_man": upkeep["manpower"], "upk_mat": upkeep["materials"], "upk_fuel": upkeep["fuel"],
    }


PLENTY = {"manpower": 10000, "materials": 10000, "fuel": 10000}
NOTHING = {"manpower": 0, "materials": 0, "fuel": 0}


class ConstructionTests(unittest.TestCase):
    def build(self, provinces, stock, state, library=LIBRARY, extra=None):
        screen = map_double()
        for prov in provinces + list(extra or ()):
            screen.world.map_data[str(prov["id"])] = prov
            screen.world.id_to_province[prov["id"]] = prov
        data = {"research": {}, "at_war_with": [], **stock}
        screen.world.nation_data["Avaria"] = data
        screen.world.nation_data["Borland"] = {"research": {}, "at_war_with": list(
            ["Avaria"] if "Borland" in data["at_war_with"] else [])}
        with patch("data.queries.get_building_required_tech", return_value=(None, 0)):
            ai_construction._apply_construction_logic(screen, "Avaria", data, provinces, library, state)
        return [[entry["item_name"] for entry in prov["building_queue"]] for prov in provinces]

    def test_a_nation_short_of_manpower_builds_recruitment(self):
        state = economy(PLENTY, {**NOTHING, "manpower": PLENTY["manpower"]})
        queued = self.build([province(1)], {"materials": 100000, "manpower": 0, "fuel": 0}, state)
        self.assertEqual(queued, [["Fixture Hall"]])

    def test_a_nation_short_of_materials_builds_industry(self):
        state = economy(PLENTY, {**NOTHING, "materials": PLENTY["materials"]})
        queued = self.build([province(1)], {"materials": 1000, "manpower": 100000, "fuel": 0}, state)
        self.assertEqual(queued, [["Fixture Works"]])

    def test_no_more_than_the_cap_a_turn_and_one_per_province(self):
        count = ai_tuning.AI_MAX_BUILDINGS_PER_TURN + 1
        provinces = [province(pid, factory=False) for pid in range(1, count + 1)]
        queued = self.build(provinces, {"materials": 100000, "manpower": 0, "fuel": 0},
                            economy(PLENTY, NOTHING))
        expected = [["Fixture Works"]] * ai_tuning.AI_MAX_BUILDINGS_PER_TURN + [[]]
        self.assertEqual(queued, expected, "equal options go to the lowest province ids")

    def test_a_building_never_eats_into_the_runway(self):
        drain = 10
        income = {**PLENTY, "materials": drain}
        upkeep = {**NOTHING, "materials": 2 * drain}
        # The price the AI pays, after the politics multiplier, not the library figure.
        cost = queries.get_building_cost("Fixture Works", "Avaria", {}, LIBRARY,
                                         {"Avaria": {"research": {}}})["cost_materials"]
        enough = cost + drain * ai_tuning.AI_CONSTRUCTION_RESERVE_TURNS
        state = economy(income, upkeep)
        self.assertEqual(self.build([province(1, factory=False)],
                                    {"materials": enough - 1, "manpower": 0, "fuel": 0}, state), [[]])
        self.assertEqual(self.build([province(1, factory=False)],
                                    {"materials": enough, "manpower": 0, "fuel": 0}, state),
                         [["Fixture Works"]])

    def test_a_province_at_the_front_is_not_built_on(self):
        front = province(1, factory=False, neighbors=[2])
        enemy_tile = {"id": 2, "json_key": "2", "owner": "Borland", "cores": ["Borland"],
                      "buildings": [], "building_queue": [], "units": [
                          {"type": "Fixture Rifles", "owner": "Borland", "health": 100}],
                      "neighbors": [1], "terrain": "plains"}
        stock = {"materials": 100000, "manpower": 0, "fuel": 0, "at_war_with": ["Borland"]}
        queued = self.build([front], stock, economy(PLENTY, NOTHING), extra=[enemy_tile])
        self.assertEqual(queued, [[]])

        enemy_tile["units"] = []
        front["building_queue"] = []
        queued = self.build([front], stock, economy(PLENTY, NOTHING), extra=[enemy_tile])
        self.assertEqual(queued, [["Fixture Works"]], "with nobody next door it builds")

    def test_a_building_that_adds_nothing_is_not_worth_its_cost(self):
        library = {"Fixture Folly": building("industry")}
        queued = self.build([province(1, factory=False)], {"materials": 100000, "manpower": 0, "fuel": 0},
                            economy(PLENTY, NOTHING), library=library)
        self.assertEqual(queued, [[]])

    def test_a_country_prepares_modifiers_and_quotes_once_for_its_building_candidates(self):
        provinces = [province(pid, factory=False) for pid in (1, 2)]
        research = {"fixture_bonus": 1}
        data = {"research": research, "at_war_with": []}
        tree = {"fixture_bonus": {"max_lvl": 1, "building_output_bonuses": [
            {"building_groups": ["industry"], "outputs": {"materials": 0.5}}]}}
        screen = map_double(map_data={prov["id"]: prov for prov in provinces}, nation_data={"Avaria": data})
        with patch.object(queries, "get_tech_tree", return_value=tree), \
                patch.object(queries, "get_building_required_tech", return_value=(None, 0)), \
                patch.object(queries, "get_building_output_modifiers", wraps=queries.get_building_output_modifiers) as prepare, \
                patch.object(queries, "get_building_cost", wraps=queries.get_building_cost) as quote, \
                patch.object(queries, "group_yields", wraps=queries.group_yields) as yields:
            ai_construction._construction_options(
                screen, "Avaria", data, provinces, LIBRARY, {}, {"materials": 1, "manpower": 1, "fuel": 1})
        prepare.assert_called_once_with(research, LIBRARY, context=screen)
        quote.assert_called_once_with("Fixture Works", "Avaria", screen.world.map_data, LIBRARY,
                                      screen.world.nation_data, context=screen)
        self.assertEqual(yields.call_count, 2)
        self.assertIs(yields.call_args_list[0].kwargs["modifiers"], yields.call_args_list[1].kwargs["modifiers"])

    def test_construction_checks_the_live_quote_after_an_earlier_purchase(self):
        def quote(name, nation, map_data, library, nation_data, *, context):
            stats = library[name].copy()
            if any(prov["building_queue"] for prov in map_data.values()):
                stats["cost_materials"] += 1
            return stats

        provinces = [province(pid, factory=False) for pid in (1, 2)]
        stock = {"materials": 2 * LIBRARY["Fixture Works"]["cost_materials"], "manpower": 0, "fuel": 0}
        with patch.object(queries, "get_building_cost", side_effect=quote), \
                patch.object(ai_tuning, "AI_MAX_BUILDINGS_PER_TURN", 2):
            queued = self.build(provinces, stock, economy(PLENTY, NOTHING))
        self.assertEqual(queued, [["Fixture Works"], []])


class RecruitmentSavingsTests(unittest.TestCase):
    def plan(self, materials, *, at_war):
        home = province(1)
        uncored = province(2)
        uncored.update(cores=[], is_coastal=True)
        data = {"research": {}, "at_war_with": ["Borland"] if at_war else [],
                "materials": materials, "manpower": 1000, "fuel": 100}
        screen = map_double(map_data={1: home, 2: uncored}, id_to_province={1: home, 2: uncored},
                            nation_data={"Avaria": data, "Borland": {"at_war_with": ["Avaria"] if at_war else []}})
        units = {}
        values = {}
        for name, score, man, mat in (("Fixture Tank", 10, 100, 300), ("Fixture Rifles", 3, 5, 40)):
            stats = {
                "production_time": 2, "cost_manpower": man, "cost_materials": mat, "cost_fuel": 0,
                "metadata": {"family": name, "tier_order": 0, "research": {"tech": "fixture", "level": 0},
                             "requirements": [], "recruitment": {"industry": "none", "coastal": False}},
            }
            units[name] = stats
            values[name] = ai_unit_eval.UnitValue(name, ai_unit_eval.ROLE_LINE, score, 1, 1, 1, 1, 1, stats, False)
        buildings = {
            "Fixture Works": building("industry", materials=50),
            "Fixture Hall": {**building("recruitment", manpower=50), "cost_materials": 0, "cost_manpower": 40},
        }
        options = [(2, home, "Fixture Works"), (1, home, "Fixture Hall")]
        income = {"manpower": 100, "materials": 110, "fuel": 100}
        upkeep = {**NOTHING, "materials": 70}
        core_cost = {"cost_manpower": 950, "time": 1}
        with (
            patch.multiple(queries, get_unit_library=lambda *_: units, get_building_library=lambda *_: buildings,
                           get_tech_tree=lambda *_: {}, calculate_all_economies=lambda *_, **__: {"Avaria": economy(income, upkeep)["econ"]},
                           get_unit_upkeep=lambda *_, **__: NOTHING, get_building_required_tech=lambda _: (None, 0),
                           get_building_cost=lambda target, *_, **__: buildings[target], get_core_cost=lambda *_: core_cost),
            patch.object(ai_unit_eval, "evaluate", return_value=values),
            patch.object(ai_construction, "_construction_options", return_value=options),
            patch.object(c, "AI_UPKEEP_TARGETS", dict.fromkeys(ai_unit_eval.RESOURCES, 0.8)),
            patch.multiple(ai_tuning, AI_MARGINAL_FLOOR=0.15, AI_SAVE_UP_THRESHOLD=0.6,
                           AI_MAX_BUILDINGS_PER_TURN=2, AI_SURPLUS_MANPOWER_FOR_CORING=500),
        ):
            ai_construction.process_ai_economy_decisions(screen, countries=["Avaria"])
        return home, uncored, data

    def test_wartime_savings_protect_the_tank_budget_from_construction(self):
        home, uncored, data = self.plan(260, at_war=True)
        self.assertEqual(home["unit_queue"], [])
        self.assertEqual([entry["item_name"] for entry in home["building_queue"]], ["Fixture Hall"])
        self.assertEqual(uncored["building_queue"], [])
        self.assertEqual((data["materials"], data["manpower"]), (260, 960))

    def test_wartime_recruitment_buys_now_if_net_income_needs_two_turns(self):
        home, _, _ = self.plan(220, at_war=True)
        self.assertTrue(home["unit_queue"])
        self.assertEqual(home["unit_queue"][0]["unit_type"], "Fixture Rifles")

    def test_peacetime_recruitment_can_wait_two_turns(self):
        home, _, data = self.plan(220, at_war=False)
        self.assertEqual(home["unit_queue"], [])
        self.assertEqual(data["materials"], 220)


if __name__ == "__main__":
    unittest.main()
