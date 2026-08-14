"""What a peacetime trade is actually worth to the nation being asked.

Territory was worth nothing at all. trade_verdict priced an offer through
deal.resource_flows, which walks the clause list and skips everything that is
not RESOURCES -- so a TILES clause in a trade cost the seller exactly zero, and
the whole of Bulgaria went for one material in `bought bulgaria for 1 material`.
The AI's own explanation of that deal was "they are asking nothing of us", which
was not a badly worded sentence but an accurate report of what it could see.

Two rules come out of fixing it. Land is priced, in the same currency as goods,
through the exchange rate DEAL_VALUE_RESOURCE_PRICES already sets. And core
ground is not priced at all, because it is not for sale: a nation will trade a
holding it has taken and never started coring, and will not be bought out of its
own country whatever the offer. A peace treaty is a different matter -- losing
core land is what losing a war means -- and none of this applies there.
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
from tests.stub_map_screen import StubMapScreen


class Fixture(unittest.TestCase):
    """B holds four of its own cores and four plain conquests it never cored."""

    def setUp(self):
        self.game = StubMapScreen(["A", "B"])
        self.cores = [self.game.add_province("B", cores=["B"]) for _ in range(4)]
        self.holdings = [self.game.add_province("B", cores=["C"]) for _ in range(4)]
        self.mine = [self.game.add_province("A", cores=["A"]) for _ in range(4)]
        self.refresh()

    def refresh(self):
        self.world = ai_world.build(self.game)

    def trade(self, *clauses):
        return deal_mod.new(deal_mod.KIND_TRADE, ["A"], ["B"], list(clauses))

    def verdict(self, *clauses):
        """B's answer to a trade A is proposing."""
        return ai_opinion.trade_verdict(self.world, "B", "A", self.trade(*clauses))

    def buy(self, provinces, materials):
        return self.verdict(
            deal_mod.tiles_clause("B", "A", [p["id"] for p in provinces]),
            deal_mod.resources_clause("A", "B", "materials", materials))

    def cap(self, nation="A", resource="materials"):
        return deal_mod.resource_cap(nation, resource, self.world.economies)


class LandCountsTests(Fixture):
    def test_a_province_changes_the_answer_at_all(self):
        """The regression. Land was invisible, so these two were the same deal."""
        goods_only = self.verdict(
            deal_mod.resources_clause("A", "B", "materials", 100))
        with_land = self.buy(self.holdings[:1], 100)

        self.assertNotEqual(round(goods_only.slack, 6), round(with_land.slack, 6),
                            "a province cost the seller nothing")

    def test_a_holding_is_dearer_than_the_token_it_used_to_go_for(self):
        self.assertFalse(self.buy(self.holdings[:1], 1).accepted)

    def test_but_can_be_bought_at_a_price(self):
        expensive = self.buy(self.holdings[:1], self.cap())
        self.assertGreater(expensive.slack, self.buy(self.holdings[:1], 1).slack)

    def test_four_holdings_cost_more_than_one(self):
        one = self.buy(self.holdings[:1], 5000)
        four = self.buy(self.holdings, 5000)
        self.assertLess(four.slack, one.slack)

    def test_land_coming_the_other_way_is_a_gain(self):
        gift = self.verdict(deal_mod.tiles_clause("A", "B", [self.mine[0]["id"]]))
        self.assertTrue(gift.accepted)

    def test_the_balance_is_the_arithmetic_the_verdict_uses(self):
        """One computation, two readers. The builder screen prints these two
        figures above the verdict sentence, and a screen that priced a deal
        differently from the engine is how the old peace screen came to predict
        the opposite of what happened."""
        agreement = self.trade(
            deal_mod.tiles_clause("B", "A", [self.holdings[0]["id"]]),
            deal_mod.resources_clause("A", "B", "materials", 4000))
        gained, lost = ai_opinion.trade_balance(self.world, "B", "A", agreement)
        verdict = ai_opinion.trade_verdict(self.world, "B", "A", agreement)

        self.assertEqual(gained > lost, verdict.accepted)

    def test_both_halves_of_the_balance_are_never_negative(self):
        gained, lost = ai_opinion.trade_balance(
            self.world, "B", "A",
            self.trade(deal_mod.tiles_clause("B", "A", [self.holdings[0]["id"]])))
        self.assertGreaterEqual(gained, 0)
        self.assertGreater(lost, 0)


class CoreLandTests(Fixture):
    def test_a_core_is_refused_outright(self):
        verdict = self.buy(self.cores[:1], 99999999)
        self.assertFalse(verdict.accepted)
        self.assertEqual(verdict.slack, -1.0)

    def test_and_the_refusal_says_why(self):
        verdict = self.buy(self.cores[:1], 5000)
        self.assertIn("own country", verdict.reason)
        self.assertIn("own country", ai_opinion.reason_about(verdict))

    def test_no_price_moves_it(self):
        cheap = self.buy(self.cores[:1], 1)
        rich = self.buy(self.cores[:1], 99999999)
        self.assertEqual(cheap.slack, rich.slack)

    def test_a_province_being_cored_counts_as_home_ground_too(self):
        """Ground already paid for. Coring is an order sitting in the province's
        building queue, the same shape production.py writes."""
        prov = self.holdings[0]
        prov["building_queue"] = [{"order_type": "CORE", "turns_remaining": 12}]
        self.refresh()

        self.assertTrue(deal_mod.is_home_ground("B", prov))
        self.assertIn("own country", self.buy([prov], 5000).reason)

    def test_a_holding_with_something_else_in_its_queue_is_still_a_holding(self):
        prov = self.holdings[0]
        prov["building_queue"] = [{"order_type": "BUILDING", "item_name": "Workshop"}]
        self.refresh()

        self.assertFalse(deal_mod.is_home_ground("B", prov))

    def test_selling_a_core_is_still_the_sellers_own_business(self):
        """The rule is about what a nation will be talked out of, not about what
        may appear in a treaty. A player handing their own capital to an ally is
        their affair; this is B's answer about B's ground."""
        verdict = self.verdict(deal_mod.tiles_clause("A", "B", [self.mine[0]["id"]]))
        self.assertNotIn("own country", verdict.reason)

    def test_a_peace_may_still_take_core_land(self):
        """Mirror of the rule above, and the reason it lives in trade_verdict
        rather than in the ledger: a war is exactly when core land moves."""
        self.game.set_war("A", "B")
        self.game.nation_data["A"]["war_durations"] = {"B": 30}
        self.game.nation_data["B"]["war_durations"] = {"A": 30}
        self.refresh()

        peace = deal_mod.new(deal_mod.KIND_PEACE, ["A"], ["B"], [
            deal_mod.white_peace(),
            deal_mod.tiles_clause("B", "A", [self.cores[0]["id"]])])
        verdict = ai_opinion.peace_verdict(self.world, "B", "A", peace)

        self.assertNotIn("own country", verdict.reason)


class ReasonTests(Fixture):
    def reason(self, *clauses):
        return self.verdict(*clauses).reason

    def test_nothing_on_the_table_says_so(self):
        self.assertEqual(self.reason(), "there is nothing here to agree to")

    def test_a_pure_gift_costs_nothing(self):
        self.assertEqual(
            self.reason(deal_mod.resources_clause("A", "B", "materials", 500)),
            "this costs us nothing")

    def test_asking_for_land_and_offering_nothing_says_that(self):
        reason = self.reason(
            deal_mod.tiles_clause("B", "A", [self.holdings[0]["id"]]))
        self.assertEqual(reason, "we would be giving this away for nothing")

    def test_a_priced_exchange_names_the_ratio(self):
        reason = self.reason(
            deal_mod.tiles_clause("B", "A", [self.holdings[0]["id"]]),
            deal_mod.resources_clause("A", "B", "materials", 4000))
        self.assertRegex(reason, r"(\d+(\.\d+)?x|many times|a fraction of)")

    def test_a_lopsided_offer_is_described_rather_than_printed(self):
        """A province against a token comes out around 0.006, and "about 0.0x
        what it would give up" reads as a broken screen rather than as a
        terrible offer."""
        self.assertEqual(ai_opinion.times_phrase(0.006), "a fraction of")
        self.assertEqual(ai_opinion.times_phrase(400.0), "many times")
        self.assertEqual(ai_opinion.times_phrase(1.0), "about 1x")
        self.assertEqual(ai_opinion.times_phrase(2.4), "about 2.4x")

    def test_the_two_sides_of_the_balance_stay_gross(self):
        """Netting the goods before splitting them lost the offer entirely: a
        nation handed 400 fuel for 20,000 materials came out negative overall
        and was reported as being offered nothing at all."""
        gained, lost = ai_opinion.trade_balance(
            self.world, "B", "A",
            self.trade(deal_mod.resources_clause("A", "B", "fuel", 400),
                       deal_mod.resources_clause("B", "A", "materials", 20000)))
        self.assertGreater(gained, 0, "the fuel on the table vanished")
        self.assertGreater(lost, gained)

    def test_no_reason_still_claims_nothing_is_being_asked(self):
        """The exact sentence the report was about. It fired whenever the other
        side's *resource* column was empty, which for a land-for-cash offer is
        always -- so a player buying a country read "they are asking nothing of
        them" under the accept button."""
        for clauses in ([], [deal_mod.resources_clause("A", "B", "materials", 500)],
                        [deal_mod.tiles_clause("B", "A", [self.holdings[0]["id"]])],
                        [deal_mod.tiles_clause("B", "A", [self.cores[0]["id"]])]):
            verdict = self.verdict(*clauses)
            for voice in (verdict.reason, ai_opinion.reason_about(verdict)):
                self.assertNotIn("asking nothing", voice)

    def test_every_trade_reason_renders_in_both_voices(self):
        """A template that forgets a placeholder throws KeyError at draw time."""
        for clauses in ([], [deal_mod.resources_clause("A", "B", "materials", 500)],
                        [deal_mod.tiles_clause("B", "A", [self.holdings[0]["id"]])],
                        [deal_mod.tiles_clause("B", "A", [self.cores[0]["id"]])],
                        [deal_mod.tiles_clause("B", "A", [self.holdings[0]["id"]]),
                         deal_mod.resources_clause("A", "B", "materials", 4000)]):
            verdict = self.verdict(*clauses)
            for voice in (verdict.reason, ai_opinion.reason_about(verdict)):
                self.assertNotIn("{", voice)
                self.assertTrue(voice)


class CapTests(unittest.TestCase):
    """The ceiling on any one term: what the payer produces in a turn.

    A promise used to be worth what it said and collected at whatever was in the
    bank, both halves of paying having clamped to the stockpile. So the number in
    the box meant nothing, and 99,999,999 materials was a legal term.
    """

    ECON = {"A": {"total_inc": {"materials": 500, "fuel": 40}}}

    def test_the_ceiling_is_one_turn_of_output(self):
        self.assertEqual(deal_mod.resource_cap("A", "materials", self.ECON),
                         500 * c.DEAL_MAX_RESOURCE_TURNS)

    def test_an_amount_over_it_comes_back_at_it(self):
        self.assertEqual(deal_mod.capped(99999999, "A", "materials", self.ECON), 500)

    def test_and_one_under_it_is_left_alone(self):
        self.assertEqual(deal_mod.capped(400, "A", "materials", self.ECON), 400)

    def test_each_resource_has_its_own(self):
        self.assertEqual(deal_mod.capped(1000, "A", "fuel", self.ECON), 40)

    def test_a_nation_not_on_the_books_produces_nothing(self):
        self.assertEqual(deal_mod.resource_cap("Nobody", "materials", self.ECON), 0)

    def test_but_no_books_at_all_means_no_ceiling(self):
        """A caller that cannot know what a nation produces must not be told the
        answer is zero -- that would cancel every payment in the treaty rather
        than leave it alone."""
        self.assertIsNone(deal_mod.resource_cap("A", "materials", None))
        self.assertEqual(deal_mod.capped(9999, "A", "materials", None), 9999)


if __name__ == "__main__":
    unittest.main()
