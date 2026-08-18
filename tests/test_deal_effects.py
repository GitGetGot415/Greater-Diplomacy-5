"""Covers what actually happens when an itemized deal is signed.

The old execute_peace_treaty had one silent behaviour worth pinning down: a
province promised in a treaty that had changed hands while the treaty was in
transit was skipped without a word. It still is not transferred -- it cannot be
-- but the term is now pruned and reported, so the settlement message can say
so instead of the players quietly getting less than they agreed to.
"""

import os
import sys
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import data.constants as c
from map_logic.diplomacy import deal, deal_effects, restrictions
from tests.stub_map_screen import StubMapScreen


class TerritoryTests(unittest.TestCase):
    def setUp(self):
        self.game = StubMapScreen(["A", "B"])
        self.contested = self.game.add_province("B")
        self.game.border(self.game.home_of("A")["id"], self.contested["id"])

    def test_a_tiles_clause_moves_the_province(self):
        agreement = deal.new(deal.KIND_PEACE, ["A"], ["B"],
                             [deal.tiles_clause("B", "A", [self.contested["id"]])])
        deal_effects.execute(self.game, agreement)
        self.assertEqual(self.game.owner_of(self.contested["id"]), "A")

    def test_a_white_peace_moves_nothing(self):
        agreement = deal.ceasefire_deal("A", "B")
        deal_effects.execute(self.game, agreement)
        self.assertEqual(self.game.owner_of(self.contested["id"]), "B")

    def test_a_province_that_changed_hands_is_pruned_and_reported(self):
        agreement = deal.new(deal.KIND_PEACE, ["A"], ["B"],
                             [deal.tiles_clause("B", "A", [self.contested["id"]])])
        self.contested["owner"] = "A"  # taken by force while the offer travelled

        dropped = deal_effects.execute(self.game, agreement)

        self.assertEqual(len(dropped), 1)
        self.assertIn("already changed hands", dropped[0])

    def test_the_rest_of_a_treaty_survives_one_stale_province(self):
        still_theirs = self.game.add_province("B")
        self.game.border(self.game.home_of("A")["id"], still_theirs["id"])
        agreement = deal.new(deal.KIND_PEACE, ["A"], ["B"],
                             [deal.tiles_clause("B", "A", [self.contested["id"],
                                                           still_theirs["id"]])])
        self.contested["owner"] = "A"

        deal_effects.execute(self.game, agreement)

        self.assertEqual(self.game.owner_of(still_theirs["id"]), "A")

    def test_losing_a_province_grants_a_claim_on_it(self):
        """conquer_province's rule, and peace treaties have always used it: land
        taken at the table is land the loser now wants back."""
        agreement = deal.new(deal.KIND_PEACE, ["A"], ["B"],
                             [deal.tiles_clause("B", "A", [self.contested["id"]])])
        deal_effects.execute(self.game, agreement)
        self.assertIn(self.contested["id"], self.game.nation_data["B"]["claims"])


class PaymentTests(unittest.TestCase):
    def setUp(self):
        self.game = StubMapScreen(["A", "B"])

    def test_reparations_move_between_stockpiles(self):
        agreement = deal.new(deal.KIND_PEACE, ["A"], ["B"],
                             [deal.resources_clause("B", "A", "materials", 400)])
        deal_effects.execute(self.game, agreement)

        self.assertEqual(self.game.nation_data["A"]["materials"], 1400)
        self.assertEqual(self.game.nation_data["B"]["materials"], 600)

    def test_a_payer_short_of_the_bill_goes_into_debt_for_the_rest(self):
        """The rule this reverses is the one the whole exploit ran on.

        Payment used to be min(promised, stockpile). A term was therefore priced
        at what it said and collected at whatever was in the bank, so any number
        at all could be typed into the box, believed by the other side, and then
        not paid -- which is how a player bought the whole of Bulgaria for one
        material. What a nation cannot cover out of stock it now owes.
        """
        self.game.nation_data["B"]["fuel"] = 50
        agreement = deal.new(deal.KIND_PEACE, ["A"], ["B"],
                             [deal.resources_clause("B", "A", "fuel", 999)])
        deal_effects.execute(self.game, agreement)

        self.assertEqual(self.game.nation_data["B"]["fuel"], -949)
        self.assertEqual(self.game.nation_data["A"]["fuel"], 1999,
                         "and the receiver is paid the whole of it")

    def test_the_debt_is_cleared_by_the_next_turn_of_income(self):
        """Which is why writing one is safe. process_economy adds income before
        it floors a stockpile at zero, and the ceiling on what may be promised is
        that same income -- so a treaty can spend the year's production and can
        never do worse than that."""
        from map_logic.turn_processing import economy_processor

        self.game.nation_data["B"]["fuel"] = 50
        agreement = deal.new(deal.KIND_PEACE, ["A"], ["B"],
                             [deal.resources_clause("B", "A", "fuel", 999)])
        deal_effects.execute(self.game, agreement)
        self.assertLess(self.game.nation_data["B"]["fuel"], 0)

        economy_processor.process_economy(self.game)
        self.assertGreaterEqual(self.game.nation_data["B"]["fuel"], 0)

    def test_a_term_above_the_payers_income_is_charged_at_the_ceiling(self):
        """One turn's output is the most any deal can move, whichever direction
        it moves in -- promising it and demanding it are the same clause."""
        self.game.set_income("B", materials=250)
        agreement = deal.new(deal.KIND_PEACE, ["A"], ["B"],
                             [deal.resources_clause("B", "A", "materials", 99999999)])
        deal_effects.execute(self.game, agreement)

        self.assertEqual(self.game.nation_data["B"]["materials"], 750)
        self.assertEqual(self.game.nation_data["A"]["materials"], 1250)

    def test_and_the_shortfall_is_reported_rather_than_swallowed(self):
        """A promise is capped when it is made, and then travels for a turn --
        long enough to lose the provinces that were producing it. Trimming it is
        right; doing so silently is how a treaty comes to deliver less than it
        says, which is the whole fault this replaced."""
        self.game.set_income("B", materials=250)
        agreement = deal.new(deal.KIND_PEACE, ["A"], ["B"],
                             [deal.resources_clause("B", "A", "materials", 4000)])

        notes = deal_effects.execute(self.game, agreement)
        self.assertTrue(any("could only deliver 250 of the 4000" in n for n in notes),
                        notes)

    def test_a_term_inside_the_ceiling_is_reported_as_nothing(self):
        agreement = deal.new(deal.KIND_PEACE, ["A"], ["B"],
                             [deal.resources_clause("B", "A", "materials", 400)])
        self.assertEqual(deal_effects.execute(self.game, agreement), [])

    def test_an_escrowed_payer_is_not_charged_twice(self):
        agreement = deal.new(deal.KIND_TRADE, ["A"], ["B"],
                             [deal.resources_clause("A", "B", "materials", 300)])
        held = deal_effects.hold_escrow(self.game.nation_data, agreement, "A")
        self.assertEqual(self.game.nation_data["A"]["materials"], 700)

        deal_effects.execute(self.game, agreement, escrowed={"A": held})

        self.assertEqual(self.game.nation_data["A"]["materials"], 700, "charged once")
        self.assertEqual(self.game.nation_data["B"]["materials"], 1300)

    def test_escrow_for_a_pruned_term_goes_home(self):
        prov = self.game.add_province("A")
        agreement = deal.new(deal.KIND_TRADE, ["A"], ["B"], [
            deal.resources_clause("A", "B", "materials", 300),
            deal.tiles_clause("A", "B", [prov["id"]]),
        ])
        held = deal_effects.hold_escrow(self.game.nation_data, agreement, "A")
        # The payment term is what escrowed; strip it and the money is owed to nobody.
        stripped = deal.with_clauses(agreement, [deal.tiles_clause("A", "B", [prov["id"]])])

        deal_effects.execute(self.game, stripped, escrowed={"A": held})

        self.assertEqual(self.game.nation_data["A"]["materials"], 1000)

    def test_escrow_takes_the_whole_promise(self):
        """Promising is spending. Escrow used to hold min(promised, stockpile),
        which is the same forgiveness the payment loop used to grant and the same
        hole: an offer of any size cost only what was lying around."""
        self.game.nation_data["A"]["fuel"] = 20
        agreement = deal.new(deal.KIND_TRADE, ["A"], ["B"],
                             [deal.resources_clause("A", "B", "fuel", 999)])

        held = deal_effects.hold_escrow(self.game.nation_data, agreement, "A")

        self.assertEqual(held, {"fuel": 999})
        self.assertEqual(self.game.nation_data["A"]["fuel"], -979)

    def test_escrow_holds_no_more_than_the_ceiling_either(self):
        agreement = deal.new(deal.KIND_TRADE, ["A"], ["B"],
                             [deal.resources_clause("A", "B", "fuel", 99999999)])

        held = deal_effects.hold_escrow(self.game.nation_data, agreement, "A",
                                        self.game.economies)

        self.assertEqual(held, {"fuel": 5000})

    def test_releasing_escrow_returns_what_was_taken_not_what_was_promised(self):
        """The two are the same figure now that escrow takes the promise whole,
        but release still reads the held dict rather than the deal -- a term
        trimmed to the ceiling would otherwise be refunded at its written size
        and mint the difference."""
        self.game.nation_data["A"]["fuel"] = 20
        agreement = deal.new(deal.KIND_TRADE, ["A"], ["B"],
                             [deal.resources_clause("A", "B", "fuel", 99999999)])

        held = deal_effects.hold_escrow(self.game.nation_data, agreement, "A",
                                        self.game.economies)
        deal_effects.release_escrow(self.game.nation_data, held, "A")

        self.assertEqual(self.game.nation_data["A"]["fuel"], 20)


class OtherClauseTests(unittest.TestCase):
    def setUp(self):
        self.game = StubMapScreen(["A", "B"])

    def test_vassalage_creates_the_puppet_link(self):
        agreement = deal.new(deal.KIND_PEACE, ["A"], ["B"],
                             [{"type": deal.VASSALIZE, "master": "A", "subject": "B",
                               "puppet_type": c.PUPPET_TYPE_AUTONOMOUS}])
        deal_effects.execute(self.game, agreement)

        self.assertEqual(self.game.nation_data["B"]["master"], "A")
        self.assertIn("B", self.game.nation_data["A"]["puppets"])

    def test_demilitarization_is_recorded_in_turns(self):
        agreement = deal.new(deal.KIND_PEACE, ["A"], ["B"],
                             [{"type": deal.DEMILITARIZE, "nation": "B", "turns": 10}])
        deal_effects.execute(self.game, agreement)
        self.assertEqual(self.game.nation_data["B"]["restrictions"]["demilitarized"], 10)

    def test_a_longer_demilitarization_wins_over_a_standing_one(self):
        self.game.nation_data["B"]["restrictions"] = {"demilitarized": 15}
        agreement = deal.new(deal.KIND_PEACE, ["A"], ["B"],
                             [{"type": deal.DEMILITARIZE, "nation": "B", "turns": 4}])
        deal_effects.execute(self.game, agreement)
        self.assertEqual(self.game.nation_data["B"]["restrictions"]["demilitarized"], 15)

    def test_military_access_is_one_way(self):
        agreement = deal.new(deal.KIND_PEACE, ["A"], ["B"],
                             [{"type": deal.MILITARY_ACCESS, "grantor": "B", "grantee": "A"}])
        deal_effects.execute(self.game, agreement)

        self.assertIn("A", self.game.nation_data["B"]["military_access"])
        self.assertNotIn("B", self.game.nation_data["A"]["military_access"])

    def test_faction_exit_removes_the_membership(self):
        self.game.set_faction("The Pact", "B")
        self.game.nation_data["C"] = dict(self.game.nation_data["A"], name="C")
        agreement = deal.new(deal.KIND_PEACE, ["A"], ["B"],
                             [{"type": deal.FACTION_EXIT, "nation": "B"}])
        deal_effects.execute(self.game, agreement)
        self.assertEqual(self.game.nation_data["B"]["faction"], "")

    def test_war_exit_unlinks_only_that_pair(self):
        self.game.set_war("B", "A")
        agreement = deal.new(deal.KIND_TRADE, ["A"], ["B"],
                             [{"type": deal.WAR_EXIT, "nation": "B", "against": "A"}])
        deal_effects.execute(self.game, agreement)

        self.assertNotIn("A", self.game.nation_data["B"]["at_war_with"])
        self.assertNotIn("B", self.game.nation_data["A"]["at_war_with"])


class DemilitarizationTests(unittest.TestCase):
    """A clause is only real if something enforces it."""

    def setUp(self):
        self.game = StubMapScreen(["A", "B"])
        agreement = deal.new(deal.KIND_PEACE, ["A"], ["B"],
                             [{"type": deal.DEMILITARIZE, "nation": "B", "turns": 3}])
        deal_effects.execute(self.game, agreement)

    def test_the_signatory_may_not_raise_units(self):
        self.assertFalse(restrictions.can_raise_units("B", self.game.nation_data))
        self.assertTrue(restrictions.can_raise_units("A", self.game.nation_data))

    def test_it_counts_down_a_turn_at_a_time(self):
        restrictions.tick(self.game.nation_data["B"])
        self.assertEqual(
            restrictions.turns_left("B", self.game.nation_data, "demilitarized"), 2)

    def test_it_expires_and_cleans_up_after_itself(self):
        for _ in range(3):
            restrictions.tick(self.game.nation_data["B"])

        self.assertTrue(restrictions.can_raise_units("B", self.game.nation_data))
        self.assertNotIn("restrictions", self.game.nation_data["B"])

    def test_ticking_a_nation_with_no_restrictions_is_harmless(self):
        restrictions.tick(self.game.nation_data["A"])
        self.assertTrue(restrictions.can_raise_units("A", self.game.nation_data))

    def test_the_diplomacy_turn_ages_it(self):
        self.game.run_turn()
        self.assertEqual(
            restrictions.turns_left("B", self.game.nation_data, "demilitarized"), 2)


class WarEndingTests(unittest.TestCase):
    def setUp(self):
        self.game = StubMapScreen(["A", "B"])
        self.game.set_war("A", "B")

    def test_a_peace_deal_ends_the_war_and_writes_a_truce(self):
        deal_effects.execute(self.game, deal.ceasefire_deal("A", "B"))

        self.assertNotIn("B", self.game.nation_data["A"]["at_war_with"])
        self.assertNotIn("A", self.game.nation_data["B"]["at_war_with"])
        self.assertEqual(self.game.nation_data["A"]["truces"]["B"], c.TRUCE_TURNS)

    def test_a_trade_leaves_the_war_running(self):
        agreement = deal.new(deal.KIND_TRADE, ["A"], ["B"],
                             [deal.resources_clause("A", "B", "fuel", 10)])
        deal_effects.execute(self.game, agreement)
        self.assertIn("B", self.game.nation_data["A"]["at_war_with"])

    def test_a_bloc_peace_ends_every_cross_pair(self):
        self.game.nation_data["C"] = dict(self.game.nation_data["B"], name="C",
                                          at_war_with=[], allied_with=[], truces={})
        self.game.add_province("C")
        self.game.set_war("A", "C")

        agreement = deal.new(deal.KIND_PEACE, ["A"], ["B", "C"], [deal.white_peace()])
        deal_effects.execute(self.game, agreement)

        self.assertEqual(self.game.nation_data["A"]["at_war_with"], [])
        self.assertNotIn("A", self.game.nation_data["C"]["at_war_with"])

    def test_wargoals_between_the_signatories_are_cleared(self):
        self.game.nation_data["A"]["wargoals"] = {"B": {"type": c.WARGOAL_TAKE_CLAIMS}}
        self.game.nation_data["B"]["wargoals"] = {"A": {"type": c.WARGOAL_NO_CB}}

        deal_effects.execute(self.game, deal.ceasefire_deal("A", "B"))

        self.assertEqual(self.game.nation_data["A"]["wargoals"], {})
        self.assertEqual(self.game.nation_data["B"]["wargoals"], {})

    def test_executing_something_that_is_not_a_deal_does_nothing(self):
        self.assertEqual(deal_effects.execute(self.game, "Ceasefire"), [])
        self.assertIn("B", self.game.nation_data["A"]["at_war_with"])


if __name__ == "__main__":
    unittest.main()
