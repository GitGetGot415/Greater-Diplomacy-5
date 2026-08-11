"""Covers research priority, which used to have none worth the name.

The old order was `(years overdue, is it new, cost)`. Every already-historical
tech ties at zero on the first term, so in practice the AI researched whichever
brand-new tech was cheapest, with no notion of whether the thing it unlocked was
any use -- an island power researched armour, a nation being overrun researched
recruitment buildings, and neither ever noticed.

The library-dependent cases run against the real tech tree because they are
about tech gating, not balance; the valuation cases use a synthetic library so
they survive a rebalance.
"""

import os
import sys
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import data.constants as c
from data import queries
from map_logic.ai import ai_tech_eval as te, ai_unit_eval as ue


def prices(materials=1.0, manpower=1.0, fuel=1.0):
    return {"materials": materials, "manpower": manpower, "fuel": fuel}


def ctx(budget=100000.0, **kw):
    return ue.context(prices(), volley=2000.0, stack=5.0, enemy_def=0.0,
                      enemy_stack=5.0, frontline=4.0, budget=budget, **kw)


class UnlockTests(unittest.TestCase):
    def setUp(self):
        self.library = queries.get_unit_library()

    def test_a_tech_level_reports_the_unit_it_unlocks(self):
        research = {"medium_tank": 2}
        unlocked = te.units_unlocked_by("medium_tank", research, self.library)
        self.assertIn("Medium Tank III", unlocked)

    def test_a_tech_that_unlocks_nothing_reports_nothing(self):
        """Economic techs earn their keep a different way."""
        self.assertEqual(
            te.units_unlocked_by("resource_refining", {"resource_refining": 3}, self.library),
            ())

    def test_a_maxed_family_unlocks_nothing_further(self):
        research = {"medium_tank": 4}
        self.assertEqual(te.units_unlocked_by("medium_tank", research, self.library), ())

    def test_the_answer_is_remembered_per_research_state(self):
        te._UNLOCK_CACHE.clear()
        for level in range(1, 4):
            te.units_unlocked_by("medium_tank", {"medium_tank": level}, self.library)
        self.assertEqual(len(te._UNLOCK_CACHE), 3)

    def test_building_unlocks_are_found(self):
        blib = queries.get_building_library()
        self.assertIn("Factory Lvl 1", te.buildings_unlocked_by("factory", 1, blib))
        self.assertEqual(te.buildings_unlocked_by("medium_tank", 1, blib), [])


class EconomyValueTests(unittest.TestCase):
    def setUp(self):
        self.blib = queries.get_building_library()
        self.income = {"materials": 5000, "manpower": 5000, "fuel": 500}

    def test_a_flat_bonus_tech_is_worth_its_bonus(self):
        value = te.economy_gain("bergius_process", 1, prices(fuel=2.0), self.blib, self.income)
        self.assertAlmostEqual(value, 2.0 * c.BERGIUS_FUEL_BONUS)

    def test_scarcity_makes_the_same_tech_worth_more(self):
        cheap = te.economy_gain("bergius_process", 1, prices(fuel=1.0), self.blib, self.income)
        dear = te.economy_gain("bergius_process", 1, prices(fuel=20.0), self.blib, self.income)
        self.assertGreater(dear, cheap)

    def test_a_percentage_tech_scales_with_income(self):
        small = te.economy_gain("resource_refining", 1, prices(), self.blib,
                                {"materials": 100, "manpower": 100, "fuel": 10})
        large = te.economy_gain("resource_refining", 1, prices(), self.blib,
                                {"materials": 50000, "manpower": 50000, "fuel": 5000})
        self.assertGreater(large, small)

    def test_the_first_building_of_a_chain_is_worth_its_whole_yield(self):
        """Basic Factory replaces nothing, so all 500/turn of it counts.

        Its JSON costs are zeros standing in for a figure computed per nation,
        so the valuation substitutes the real base rather than reading it as a
        free +500/turn, which is what it used to be scored as.
        """
        cheap = prices(materials=1.0, manpower=0.01)
        value = te.economy_gain("basic_factory", 1, cheap, self.blib, self.income)

        # Spelled out from the constants rather than by calling _build_cost,
        # so that zeroing the substituted cost is visible here. queries.py
        # charges 2x the base in materials and 1x in manpower.
        base = float(c.BASIC_FACTORY_BASE_COST_X)
        yield_per_turn = cheap["materials"] * self.blib["Basic Factory"]["prod_materials"]
        real_cost = cheap["materials"] * base * 2 + cheap["manpower"] * base
        self.assertAlmostEqual(value, yield_per_turn - real_cost / c.AI_BUILDING_PAYBACK_TURNS)
        self.assertGreater(value, 0.0)

    def test_the_basic_factory_is_not_scored_as_free(self):
        """Its JSON costs are zeros standing in for a per-nation figure. Read
        literally they made it a free +500/turn, which no other building is."""
        self.assertGreater(
            te._build_cost("Basic Factory", self.blib["Basic Factory"], prices()), 0.0)

    def test_an_upgrade_is_worth_only_what_it_adds(self):
        """Factory Lvl 1 yields 1,000/turn but tears down the Basic Factory's
        500 doing it, for 30,000 materials. That is not a deal."""
        value = te.economy_gain("factory", 1, prices(), self.blib, self.income)
        self.assertEqual(value, 0.0)

    def test_every_factory_upgrade_is_worth_the_same(self):
        """The bug this replaced, and the headline property.

        Every factory level costs a flat 30,000 and adds a flat 1,000/turn over
        the level it destroys, so Lvl 25 is worth exactly what Lvl 2 is. The old
        absolute reading scored the new building's whole output, making Lvl 25
        look twelve times the deal Lvl 2 was and sending the AI chasing tiers
        decades ahead of its date -- the further out of reach, the better it
        looked.
        """
        values = {lvl: te.economy_gain("factory", lvl, prices(), self.blib, self.income)
                  for lvl in (2, 8, 15, 25)}
        self.assertEqual(len(set(values.values())), 1, values)
        self.assertGreater(values[2], 0.0, "still worth having, just not more so")

    def test_the_marginal_yield_is_the_difference_between_the_tiers(self):
        """Priced so the upgrade is worth having, the figure is the gap between
        the two levels and not the higher level's whole output."""
        cheap_build = prices(materials=1.0)
        value = te.economy_gain("factory", 8, cheap_build, self.blib, self.income)
        lvl8 = self.blib["Factory Lvl 8"]
        lvl7 = self.blib["Factory Lvl 7"]
        gain = (te._yield_value(lvl8, cheap_build) - te._yield_value(lvl7, cheap_build))
        cost = te._build_cost("Factory Lvl 8", lvl8, cheap_build) / c.AI_BUILDING_PAYBACK_TURNS
        self.assertAlmostEqual(value, gain - cost)
        self.assertLess(value, te._yield_value(lvl8, cheap_build),
                        "must not be the absolute output")

    def test_fuel_refining_is_worth_something_when_fuel_is_scarce(self):
        """It carries no building, so the building branch scored a fifty-level
        tech at exactly zero for every AI in the game. It raises the ceiling on
        turning materials into fuel, which is worth having only when fuel costs
        more than the ten materials it takes to make."""
        scarce = te.economy_gain("fuel_refining", 1, prices(materials=1.0, fuel=100.0),
                                 self.blib, self.income)
        awash = te.economy_gain("fuel_refining", 1, prices(materials=1.0, fuel=1.0),
                                self.blib, self.income)
        self.assertGreater(scarce, 0.0)
        self.assertEqual(awash, 0.0, "converting at 10:1 into a glut is a loss")

    def test_fuel_refining_stops_paying_past_the_slider_ceiling(self):
        beyond = int(c.MAX_CONVERSION_SLIDER_VAL / c.FUEL_REFINING_CONVERSION_PER_LVL) + 1
        self.assertEqual(
            te.economy_gain("fuel_refining", beyond, prices(materials=1.0, fuel=100.0),
                            self.blib, self.income), 0.0)

    def test_a_military_tech_has_no_economic_value(self):
        self.assertEqual(
            te.economy_gain("medium_tank", 3, prices(), self.blib, self.income), 0.0)


class BuildingLeadTests(unittest.TestCase):
    """Research must not run away from what the nation has actually built.

    A province can only ever queue the next item in its chain, so holding
    factory level 8 with nothing above Lvl 1 anywhere buys nothing for seven
    twelve-turn upgrades. That is the state the USA was in when this was found.
    """

    def setUp(self):
        self.blib = queries.get_building_library()
        self.income = {"materials": 5000, "manpower": 5000, "fuel": 500}

    def provinces(self, *buildings):
        return [{"buildings": list(buildings)}]

    def test_built_levels_reports_the_highest_of_each_chain(self):
        provs = self.provinces("Factory Lvl 3") + self.provinces("Factory Lvl 7",
                                                                 "Recruitment Building Lvl 2")
        built = te.built_levels(provs, self.blib)
        self.assertEqual(built["factory"], 7)
        self.assertEqual(built["recruitment_buildings"], 2)

    def test_a_chain_nobody_has_started_is_absent(self):
        self.assertEqual(te.built_levels(self.provinces("Basic Factory"), self.blib),
                         {"basic_factory": 1})

    def test_unknown_buildings_are_ignored(self):
        self.assertEqual(te.built_levels(self.provinces("Pyramid"), self.blib), {})

    def test_the_next_level_up_is_still_worth_researching(self):
        built = {"factory": 7}
        self.assertGreater(
            te.economy_gain("factory", 8, prices(), self.blib, self.income, built), 0.0)

    def test_a_level_far_beyond_what_is_built_is_worth_nothing(self):
        built = {"factory": 1}
        self.assertEqual(
            te.economy_gain("factory", 9, prices(), self.blib, self.income, built), 0.0)

    def test_the_first_level_of_a_chain_is_always_allowed(self):
        """Nothing built means level 0, and one level of lead is granted."""
        self.assertEqual(
            te.economy_gain("factory", 1, prices(materials=0.05), self.blib, self.income, {}),
            te.economy_gain("factory", 1, prices(materials=0.05), self.blib, self.income))

    def test_the_second_level_is_gated_until_the_first_is_standing(self):
        gated = te.economy_gain("factory", 2, prices(), self.blib, self.income, {})
        ungated = te.economy_gain("factory", 2, prices(), self.blib, self.income,
                                  {"factory": 1})
        self.assertEqual(gated, 0.0)
        self.assertGreater(ungated, 0.0)

    def test_omitting_the_argument_applies_no_cap(self):
        """Mods and callers that cannot supply province state keep working."""
        self.assertGreater(
            te.economy_gain("factory", 25, prices(), self.blib, self.income), 0.0)


class UnitGainTests(unittest.TestCase):
    """Uses a synthetic library so a rebalance cannot break these."""

    LIBRARY = {
        "Musket I": {"attack": 100, "defense": 0, "health": 1000, "speed": 1,
                     "cost_materials": 500, "cost_manpower": 500, "cost_fuel": 0,
                     "production_time": 2, "naval_unit": False},
        "Musket II": {"attack": 400, "defense": 50, "health": 1600, "speed": 1,
                      "cost_materials": 520, "cost_manpower": 500, "cost_fuel": 0,
                      "production_time": 2, "naval_unit": False},
    }

    def test_a_tech_unlocking_a_better_unit_scores_above_one_that_unlocks_nothing(self):
        gains = te.UnitGains(["musket", "resource_refining"], {"musket": 1},
                             self.LIBRARY, ctx(), {"Musket I"})
        # Stub the unlock answer so this stays about valuation, not tech gating.
        gains._unlocks = {"musket": ("Musket II",), "resource_refining": ()}
        self.assertGreater(gains.gain("musket"), 0.0)
        self.assertEqual(gains.gain("resource_refining"), 0.0)

    def test_a_strictly_worse_unlock_is_worth_nothing(self):
        library = dict(self.LIBRARY)
        library["Musket II"] = dict(library["Musket II"], attack=1, health=10,
                                    cost_materials=99999)
        gains = te.UnitGains(["musket"], {"musket": 1}, library, ctx(), {"Musket I"})
        gains._unlocks = {"musket": ("Musket II",)}
        self.assertEqual(gains.gain("musket"), 0.0)

    def test_best_score_reports_what_we_can_already_field(self):
        gains = te.UnitGains([], {}, self.LIBRARY, ctx(), {"Musket I"})
        self.assertGreater(gains.best_score(), 0.0)

    def test_best_score_is_zero_with_nothing_buildable(self):
        gains = te.UnitGains([], {}, self.LIBRARY, ctx(), set())
        self.assertEqual(gains.best_score(), 0.0)


class RankingTests(unittest.TestCase):
    def setUp(self):
        self.library = queries.get_unit_library()
        self.blib = queries.get_building_library()
        self.research = {"infantry_type": 30, "medium_tank": 3, "artillery": 6,
                         "factory": 7, "resource_refining": 29}
        self.current = set(ue.buildable_units(self.research, self.library))
        self.income = {"materials": 25000, "manpower": 11000, "fuel": 1500}

    def rank(self, available, year=1939):
        return te.rank_available(list(available), self.research, self.library,
                                 self.blib, ctx(), self.current, year, self.income)

    def test_ranking_is_stable_for_equal_value(self):
        """Two runs of the same question must not disagree."""
        available = [("medium_tank", 1945, 2400, False), ("artillery", 1940, 900, False),
                     ("factory", 1940, 1200, False)]
        self.assertEqual([e[0] for e in self.rank(available)],
                         [e[0] for e in self.rank(list(reversed(available)))])

    def test_a_tech_far_ahead_of_its_time_is_penalised(self):
        """research_processor halves progress per year early, so an off-schedule
        tech genuinely costs several times its sticker price."""
        on_time = self.rank([("medium_tank", 1939, 2400, False)])
        early = self.rank([("medium_tank", 1980, 2400, False)])
        self.assertEqual(len(on_time), len(early))

        available = [("medium_tank", 1939, 2400, False), ("artillery", 1990, 900, False)]
        self.assertEqual(self.rank(available)[0][0], "medium_tank")

    def test_an_empty_list_is_returned_unchanged(self):
        self.assertEqual(self.rank([]), [])


class QueueFillTests(unittest.TestCase):
    """The slot reservation that stops economy taking the whole tree forever."""

    def setUp(self):
        from map_logic.ai import ai_research
        self.fill = ai_research._fill_queue
        self.library = queries.get_unit_library()
        self.tree = queries.get_tech_tree()
        self.research = {"infantry_type": 30, "medium_tank": 3, "factory": 7}

    def ranked(self):
        # Economic techs first, as raw value genuinely orders them.
        return [("factory", 1940, 1200, False),
                ("recruitment_buildings", 1940, 1200, False),
                ("resource_refining", 1940, 900, False),
                ("medium_tank", 1945, 2400, False)]

    def test_at_least_one_slot_goes_to_something_that_unlocks_a_unit(self):
        queue = []
        self.fill(queue, self.ranked(), self.research, self.library, self.tree)
        self.assertEqual(len(queue), c.RESEARCH_SLOTS)
        self.assertTrue(
            any(te.units_unlocked_by(q["tech_name"], self.research, self.library)
                for q in queue),
            "every slot went to economy, which is how the AI stopped modernising")

    def test_the_best_economy_techs_still_get_the_other_slots(self):
        queue = []
        self.fill(queue, self.ranked(), self.research, self.library, self.tree)
        self.assertIn("factory", [q["tech_name"] for q in queue])

    def test_a_queue_that_already_has_a_military_tech_is_left_to_value(self):
        queue = [{"tech_name": "medium_tank", "points_remaining": 2400}]
        ranked = [e for e in self.ranked() if e[0] != "medium_tank"]
        self.fill(queue, ranked, self.research, self.library, self.tree)
        self.assertEqual([q["tech_name"] for q in queue][1:],
                         ["factory", "recruitment_buildings"])

    def test_it_does_not_hang_when_nothing_unlocks_a_unit(self):
        queue = []
        economy_only = [e for e in self.ranked() if e[0] != "medium_tank"]
        self.fill(queue, economy_only, self.research, self.library, self.tree)
        self.assertEqual(len(queue), 3)

    def test_a_full_queue_is_left_alone(self):
        queue = [{"tech_name": "factory", "points_remaining": 1}] * c.RESEARCH_SLOTS
        self.fill(queue, self.ranked(), self.research, self.library, self.tree)
        self.assertEqual(len(queue), c.RESEARCH_SLOTS)


if __name__ == "__main__":
    unittest.main()
