"""A treaty is measured against the map it starts from, not the front line.

Round 2 made peace restore the pre-war border: occupied land the treaty does not
name goes home when the fighting stops. That rule was written in
deal_effects.restore_occupied and known nowhere else, so valuation, the builder
screen and the preview map all went on measuring against the *current* map. The
game priced, drew and explained a different treaty from the one it executed.

The measurable symptom, from a stub with four of B's six provinces overrun:

    white peace                                slack +0.5212  accept
    demand those four, as the screen built it  slack +0.5212  accept   <-- identical
    demand those four, priced honestly         slack -0.0502  refuse

deal_screen named the *current holder* as a term's giver, so demanding land you
already occupy emitted {from: You, to: You}. B was party to neither end of that
clause, so its ledger came back empty and the whole term was invisible to the
nation being asked to sign it. Its mirror was worse: handing back a province
that was reverting anyway scored as a gift, which made the give column a free
source of goodwill.

deal.baseline_owners is that one rule, and everything reads it now.
"""

import os
import sys
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import data.constants as c
from map_logic.ai import ai_opinion, ai_world
from map_logic.diplomacy import deal as deal_mod
from map_logic.diplomacy import deal_effects, war_actions
from tests.stub_map_screen import StubMapScreen


class BaselineTests(unittest.TestCase):
    """A is standing on two of B's provinces and one of neutral C's."""

    def setUp(self):
        self.game = StubMapScreen(["A", "B", "C"])
        self.mine = self.game.add_province("A", cores=["A"])
        self.theirs = self.game.add_province("B", cores=["B"])
        self.also_theirs = self.game.add_province("B", cores=["B"])
        self.neutrals = self.game.add_province("C", cores=["C"])

        for nation in ("A", "B", "C"):
            war_actions.save_own_pre_war_map(self.game.map_data, self.game.nation_data, nation)
        self.game.set_war("A", "B")
        self.theirs["owner"] = "A"
        self.also_theirs["owner"] = "A"
        self.neutrals["owner"] = "A"

    def baseline(self, kind=deal_mod.KIND_PEACE, a=("A",), b=("B",)):
        return deal_mod.baseline_owners(
            deal_mod.new(kind, list(a), list(b), []),
            self.game.map_data, self.game.nation_data)

    def test_land_taken_from_the_other_side_reverts(self):
        baseline = self.baseline()
        self.assertEqual(baseline[self.theirs["id"]], "B")
        self.assertEqual(baseline[self.also_theirs["id"]], "B")

    def test_our_own_land_is_still_ours(self):
        self.assertEqual(self.baseline()[self.mine["id"]], "A")

    def test_a_conquest_from_a_third_party_is_not_this_treatys_business(self):
        """C is not at this table. Its province stays where the armies left it."""
        self.assertEqual(self.baseline()[self.neutrals["id"]], "A")

    def test_a_trade_starts_from_the_map_as_it_is(self):
        """Nothing reverts, because a trade ends no war."""
        baseline = self.baseline(deal_mod.KIND_TRADE)
        self.assertEqual(baseline[self.theirs["id"]], "A")

    def test_it_agrees_with_what_execution_actually_does(self):
        """The picture and the outcome come from one function, so they cannot
        drift apart the way they did when each had its own copy of the rule."""
        expected = self.baseline()
        deal_effects.execute(self.game, deal_mod.ceasefire_deal("A", "B"))
        for prov in self.game.map_data.values():
            with self.subTest(province=prov["id"]):
                self.assertEqual(prov["owner"], expected[prov["id"]])


class ValuationTests(unittest.TestCase):
    """What a term is worth is what it changes, not what it calls itself."""

    def setUp(self):
        # "Bee" fights alongside B; "C" is a bystander with land of its own.
        self.game = StubMapScreen(["A", "B", "Bee", "C"])
        self.game.add_province("A", cores=["A"])
        self.theirs = [self.game.add_province("B", cores=["B"]) for _ in range(4)]
        self.untouched = self.game.add_province("B", cores=["B"])
        self.stray = self.game.add_province("C", cores=["C"])

        for nation in ("A", "B", "Bee", "C"):
            war_actions.save_own_pre_war_map(self.game.map_data, self.game.nation_data, nation)
        self.game.set_war("A", "B")
        self.game.set_war("A", "Bee")
        for prov in self.theirs:
            prov["owner"] = "A"

        self.occupied = [prov["id"] for prov in self.theirs]

    def ledger(self, *clauses, nation="B"):
        agreement = deal_mod.new(deal_mod.KIND_PEACE, ["A"], ["B"],
                                 [deal_mod.white_peace()] + list(clauses))
        return deal_mod.ledger(agreement, nation, self.game.map_data, self.game.nation_data)

    def test_demanding_land_you_occupy_costs_the_nation_it_belongs_to(self):
        self.assertGreater(self.ledger(
            deal_mod.tiles_clause("B", "A", self.occupied))["given_land"], 0)

    def test_and_costs_it_the_same_however_the_term_names_its_giver(self):
        """The screen named the occupier; a legacy clause or a mod may still.
        Who loses a province is a fact about the map either way."""
        honest = self.ledger(deal_mod.tiles_clause("B", "A", self.occupied))
        as_the_screen_built_it = self.ledger(deal_mod.tiles_clause("A", "A", self.occupied))
        self.assertEqual(honest, as_the_screen_built_it)
        self.assertGreater(honest["given_land"], 0)

    def test_handing_a_province_back_to_its_own_owner_is_worth_nothing(self):
        """It reverts anyway. Scoring it was an exploit: fill the give column
        with the land you are about to lose regardless and it read as generosity."""
        book = self.ledger(deal_mod.tiles_clause("A", "B", self.occupied))
        self.assertEqual(book["got_land"], 0.0)
        self.assertEqual(book["given_land"], 0.0)

    def test_but_handing_it_to_a_different_nation_on_their_side_is_a_real_transfer(self):
        """Which is the whole point of naming a recipient: giving a conquest to
        a particular enemy nation rather than back to the one it came from."""
        agreement = deal_mod.new(deal_mod.KIND_PEACE, ["A"], ["B", "Bee"],
                                 [deal_mod.white_peace(),
                                  deal_mod.tiles_clause("A", "Bee", self.occupied)])
        book = deal_mod.ledger(agreement, "Bee", self.game.map_data,
                               self.game.nation_data, whole_side=False)
        self.assertGreater(book["got_land"], 0.0)

        loser = deal_mod.ledger(agreement, "B", self.game.map_data,
                                self.game.nation_data, whole_side=False)
        self.assertGreater(loser["given_land"], 0.0,
                           "B is losing land it would otherwise have got back")

    def test_demanding_land_you_have_not_taken_still_costs_them(self):
        self.assertGreater(self.ledger(
            deal_mod.tiles_clause("B", "A", [self.untouched["id"]]))["given_land"], 0)

    def test_a_demand_you_already_occupy_is_a_valid_term_to_send(self):
        """validate required the named giver to still hold the ground, which is
        exactly wrong for the commonest demand there is. deal_effects.prune was
        fixed to the three-way title test and this was left behind, so prune
        honoured terms validate would not let you send."""
        agreement = deal_mod.new(deal_mod.KIND_PEACE, ["A"], ["B"],
                                 [deal_mod.white_peace(),
                                  deal_mod.tiles_clause("B", "A", self.occupied)])
        self.assertEqual(deal_mod.validate(agreement, self.game.map_data,
                                           self.game.nation_data), [])

    def test_demanding_a_province_neither_side_has_title_to_is_still_refused(self):
        agreement = deal_mod.new(deal_mod.KIND_PEACE, ["A"], ["B"],
                                 [deal_mod.white_peace(),
                                  deal_mod.tiles_clause("B", "A", [self.stray["id"]])])
        self.assertTrue(deal_mod.validate(agreement, self.game.map_data,
                                          self.game.nation_data))


class VerdictTests(unittest.TestCase):
    """The reading the player is shown, which is the one that went wrong."""

    def setUp(self):
        self.game = StubMapScreen(["A", "B"])
        self.game.add_province("A", cores=["A"])
        self.theirs = [self.game.add_province("B", cores=["B"]) for _ in range(6)]
        for nation in ("A", "B"):
            war_actions.save_own_pre_war_map(self.game.map_data, self.game.nation_data, nation)
        self.game.set_war("A", "B")
        self.game.nation_data["A"]["war_durations"] = {"B": 20}
        self.game.nation_data["B"]["war_durations"] = {"A": 20}
        for prov in self.theirs[:4]:
            prov["owner"] = "A"
            prov["units"] = [{"owner": "A", "size": 100}]

        self.world = ai_world.for_screen(self.game)
        self.occupied = [prov["id"] for prov in self.theirs[:4]]

    def verdict(self, *clauses):
        agreement = deal_mod.new(deal_mod.KIND_PEACE, ["A"], ["B"],
                                 [deal_mod.white_peace()] + list(clauses))
        return ai_opinion.peace_verdict(self.world, "B", "A", agreement)

    def test_demanding_what_you_hold_is_no_longer_the_same_as_asking_nothing(self):
        """The whole of `demanding provinces you already control doesn't seem to
        change the outcome at all`, in one assertion."""
        nothing = self.verdict()
        demanded = self.verdict(deal_mod.tiles_clause("A", "A", self.occupied))
        self.assertLess(demanded.slack, nothing.slack)

    def test_and_the_bigger_the_demand_the_worse_it_reads(self):
        one = self.verdict(deal_mod.tiles_clause("A", "A", self.occupied[:1]))
        all_four = self.verdict(deal_mod.tiles_clause("A", "A", self.occupied))
        self.assertLess(all_four.slack, one.slack)

    def test_giving_back_what_reverts_anyway_buys_nothing(self):
        nothing = self.verdict()
        generous = self.verdict(deal_mod.tiles_clause("A", "B", self.occupied))
        self.assertEqual(generous.slack, nothing.slack)


class LandCapTests(unittest.TestCase):
    """You may demand what you hold, and no more -- measured in one currency.

    The ceiling compared two figures that only looked comparable. The demand was
    the hardest-hit member's loss as a share of *itself*, priced with the core
    multiplier; the occupation came from war_score, which resolves the whole
    coalition on each side and prices tiles bare. On `what the hell happened
    here` those read 36% and 7% for the same twenty-two provinces, so Germany
    asking for two of the twenty-two it was standing on was refused outright.
    """

    def setUp(self):
        # A three-nation bloc, so the coalition denominator differs sharply from
        # the member one -- which is what the old comparison got wrong.
        self.game = StubMapScreen(["Attacker", "Victim", "BigAlly"])
        self.victim_land = [self.game.add_province("Victim", cores=["Victim"])
                            for _ in range(10)]
        for _ in range(60):
            self.game.add_province("BigAlly", cores=["BigAlly"])

        for nation in ("Attacker", "Victim", "BigAlly"):
            war_actions.save_own_pre_war_map(self.game.map_data, self.game.nation_data, nation)
        self.game.set_faction("Allies", "Victim", "BigAlly")
        self.game.set_war("Attacker", "Victim")
        self.game.set_war("Attacker", "BigAlly")
        self.game.nation_data["Attacker"]["war_durations"] = {"Victim": 20, "BigAlly": 20}
        self.game.nation_data["Victim"]["war_durations"] = {"Attacker": 20}
        self.game.nation_data["BigAlly"]["war_durations"] = {"Attacker": 20}

        # Attacker overruns half the Victim -- and none of its enormous ally.
        for prov in self.victim_land[:5]:
            prov["owner"] = "Attacker"
        self.world = ai_world.for_screen(self.game)
        self.held = [prov["id"] for prov in self.victim_land[:5]]

    def verdict(self, ids):
        agreement = deal_mod.new(deal_mod.KIND_PEACE, ["Attacker"], ["Victim", "BigAlly"], [
            deal_mod.white_peace(), deal_mod.tiles_clause("Victim", "Attacker", ids)])
        return ai_opinion.peace_verdict(self.world, "Victim", "Attacker", agreement)

    def test_the_two_halves_of_the_cap_are_the_same_measurement(self):
        agreement = deal_mod.new(deal_mod.KIND_PEACE, ["Attacker"], ["Victim", "BigAlly"],
                                 [deal_mod.white_peace()])
        occupied = deal_mod.occupied_fraction(agreement, "Victim", self.game.map_data,
                                              self.game.nation_data, whole_side=False)
        demanded = deal_mod.demand_fraction(
            deal_mod.add_clause(agreement,
                                deal_mod.tiles_clause("Victim", "Attacker", self.held)),
            "Victim", self.game.map_data, self.game.nation_data, whole_side=False)
        self.assertAlmostEqual(occupied, demanded, places=6,
                               msg="asking for exactly what you hold must read as "
                                   "exactly what you hold")

    def test_demanding_a_fraction_of_what_you_hold_is_weighed_not_refused_flat(self):
        one = self.verdict(self.held[:1])
        self.assertGreater(one.slack, -1.0,
                           "a modest demand inside the occupation is not a flat refusal")

    def test_and_a_bigger_slice_of_it_reads_worse(self):
        self.assertLess(self.verdict(self.held).slack, self.verdict(self.held[:1]).slack)

    def test_demanding_land_you_do_not_hold_is_still_refused_outright(self):
        everything = [prov["id"] for prov in self.victim_land]
        self.assertEqual(self.verdict(everything).slack, -1.0)

    def test_a_members_share_is_measured_against_the_member(self):
        """Not against the coalition. The Victim's ten provinces are a rounding
        error beside BigAlly's sixty, which is how a whole country was once
        signed away as a modest fraction of the alliance."""
        agreement = deal_mod.new(deal_mod.KIND_PEACE, ["Attacker"], ["Victim", "BigAlly"], [
            deal_mod.white_peace(),
            deal_mod.tiles_clause("Victim", "Attacker",
                                  [p["id"] for p in self.victim_land])])
        alone = deal_mod.demand_fraction(agreement, "Victim", self.game.map_data,
                                         self.game.nation_data, whole_side=False)
        bloc = deal_mod.demand_fraction(agreement, "Victim", self.game.map_data,
                                        self.game.nation_data, whole_side=True)
        self.assertGreater(alone, bloc * 3, "the fixture does not exercise the gap")
        self.assertFalse(ai_opinion.peace_verdict(
            self.world, "Victim", "Attacker", agreement).accepted)


class RebalanceTests(unittest.TestCase):
    """Materials are a short-term gain and a province is a permanent one.

    They were summed into one demand figure at prices that made a treasury
    comparable to a country: on the save these were measured from, the German
    stockpile of 33,000 materials read as 34% of the Netherlands.
    """

    def test_a_bare_province_costs_more_materials_than_a_great_power_holds(self):
        per_province = c.DEAL_VALUE_TILE_BASE / c.DEAL_VALUE_RESOURCE_PRICES["materials"]
        self.assertGreater(per_province, 10000)

    def test_cash_cannot_buy_off_most_of_a_territorial_demand(self):
        self.assertLessEqual(c.AI_PEACE_CASH_OFFSET_CAP, 0.15)

    def test_fuel_is_still_worth_more_than_materials(self):
        prices = c.DEAL_VALUE_RESOURCE_PRICES
        self.assertGreater(prices["fuel"], prices["materials"])


if __name__ == "__main__":
    unittest.main()
