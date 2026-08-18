"""What a nation holding enemy ground puts on the table, and who gets a vote.

From saves/FRANCE JUST LET SWITZERLAND GO. France had reduced Switzerland to its
last province; the following turn Switzerland had five again. Three things had
to line up for that:

  * _victors_terms, the only function that asks for land, was reachable from one
    caller gated on an appetite a *winning* nation cannot reach. The one peace a
    winner could propose -- a ceasefire to an enemy it cannot physically get at
    -- was hard-wired to a blank white peace.
  * A white peace is not neutral any more. deal_effects.restore_occupied hands
    every unnamed occupied province back to its pre-war owner, so saying nothing
    about the conquests gives them away.
  * A bloc leader signs for the whole bloc, and the member whose conquests those
    were was never asked, because the ratification round only looks at nations
    named in a clause and a white peace names nobody.

France did not agree to any of it. Russia did, on France's behalf, because it
could not reach Switzerland.
"""

import os
import sys
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import data.constants as c
from map_logic.ai import ai_diplomacy
from map_logic.diplomacy import deal, ratification, war_actions
from tests.stub_map_screen import StubMapScreen


class VictorsTermsTests(unittest.TestCase):
    """RUS leads the bloc; FRA is the member standing on FOE's provinces."""

    def setUp(self):
        self.game = StubMapScreen(["RUS", "FRA", "FOE"], human_players=("FRA",))
        self.game.set_faction("Entente", "RUS", "FRA")

        # Four of FOE's provinces, recorded as its own before the war starts.
        self.taken = [self.game.add_province("FOE", cores=["FOE"]) for _ in range(4)]
        for value, prov in enumerate(self.taken):
            # Distinct values so "most valuable first" is observable.
            prov["buildings"] = ["Basic Factory"] * value

        for ours in ("RUS", "FRA"):
            self.game.set_war(ours, "FOE")
        war_actions.save_own_pre_war_map(self.game.map_data, self.game.nation_data, "FOE")

        # FRA overruns them. RUS takes nothing -- it cannot even reach FOE.
        for prov in self.taken:
            prov["owner"] = "FRA"

    def terms(self, leverage, proposer="RUS"):
        return ai_diplomacy._victors_terms(self.game, proposer, "FOE", leverage)

    def demanded(self, agreement):
        """Province ids the deal moves. tile_transfers keys them as the map
        does, which is not always the type the caller wrote them down as."""
        return {str(prov_id) for prov_id
                in deal.tile_transfers(agreement, self.game.map_data,
                                       self.game.nation_data)}

    def test_a_bloc_leader_asks_for_the_ground_its_member_is_standing_on(self):
        """RUS holds nothing itself; the demand is FRA's conquests, to FRA."""
        agreement = self.terms(0.95)
        transfers = deal.tile_transfers(agreement, self.game.map_data,
                                        self.game.nation_data)

        self.assertEqual(self.demanded(agreement),
                         {str(prov["id"]) for prov in self.taken})
        self.assertEqual(set(transfers.values()), {"FRA"})

    def test_a_narrow_winner_asks_for_a_share_rather_than_nothing(self):
        """Below AI_PEACE_DEMAND_LEVERAGE this used to fall through to a bare
        white peace, which now hands the whole occupation back."""
        agreement = self.terms(c.AI_PEACE_DEMAND_LEVERAGE / 2.0)
        wanted = self.demanded(agreement)

        self.assertFalse(deal.is_white_peace(agreement))
        self.assertGreater(len(wanted), 0)
        self.assertLess(len(wanted), len(self.taken))

    def test_a_partial_demand_takes_the_valuable_ground_first(self):
        agreement = self.terms(c.AI_PEACE_DEMAND_LEVERAGE / 2.0)
        wanted = self.demanded(agreement)

        best = max(self.taken, key=deal.tile_value)
        self.assertIn(str(best["id"]), wanted)

    def test_being_ahead_at_all_always_puts_one_province_on_the_table(self):
        agreement = self.terms(0.51)
        self.assertGreaterEqual(len(self.demanded(agreement)), 1)

    def test_a_side_that_is_losing_still_offers_the_status_quo(self):
        """Suing for peace has to stay possible -- an army being destroyed that
        happens to hold one tile must not be made to demand tribute for it."""
        self.assertTrue(deal.is_white_peace(self.terms(0.05)))

    def test_holding_nothing_of_theirs_is_a_white_peace(self):
        for prov in self.taken:
            prov["owner"] = "FOE"
        self.assertTrue(deal.is_white_peace(self.terms(0.95)))


class SeparatePeacePriceTests(unittest.TestCase):
    """What walking out of a bloc costs, written down while it is still a choice.

    A member can only settle by leaving its faction (peace_scope.SEPARATE_PEACE)
    and treaty_effects wrote that clause into the treaty at execution -- after
    both sides had already made their minds up. So the most expensive clause in
    the game (DEAL_VALUE_FACTION_EXIT) was in nobody's ledger while anybody was
    still deciding: the nation resigning from its alliance never weighed the
    alliance, and the side accepting never saw what it was being handed.

    Five Axis members did exactly that in one turn of
    saves/oh my god germany italy wtf.
    """

    def setUp(self):
        self.game = StubMapScreen(["LEADER", "MEMBER", "FOE"], human_players=())
        self.game.set_faction("Pact", "LEADER", "MEMBER")
        for ours in ("LEADER", "MEMBER"):
            self.game.set_war(ours, "FOE")

    def terms(self, proposer):
        return ai_diplomacy._white_peace_terms(self.game, proposer, "FOE")

    def exits(self, agreement):
        return [clause["nation"] for clause in deal.clauses(agreement)
                if clause.get("type") == deal.FACTION_EXIT]

    def test_a_members_offer_says_it_is_leaving_the_bloc(self):
        self.assertEqual(self.exits(self.terms("MEMBER")), ["MEMBER"])

    def test_a_leaders_offer_does_not(self):
        """A leader negotiates for the bloc; it is not resigning from it."""
        self.assertEqual(self.exits(self.terms("LEADER")), [])

    def test_the_price_lands_on_the_member_and_nobody_else(self):
        agreement = self.terms("MEMBER")
        cost = deal.demand_fraction(agreement, "MEMBER", self.game.map_data,
                                    self.game.nation_data, whole_side=False)
        self.assertGreater(cost, 0.0, "leaving the bloc has to cost something")
        self.assertEqual(
            deal.demand_fraction(agreement, "FOE", self.game.map_data,
                                 self.game.nation_data, whole_side=False),
            0.0)

    def offers_of(self, proposer):
        """What section 1 puts forward for a nation that cannot reach FOE."""
        from map_logic.ai import ai_candidates, ai_world

        world = ai_world.for_screen(self.game)
        world.reachable = lambda *_: False

        bag = ai_candidates.Collector(proposer, {})
        ai_diplomacy._seek_ceasefire_if_unreachable(
            bag, self.game, proposer, ["FOE"], ["FOE"], world)
        return [candidate.action for candidate in bag.ranked()]

    def test_a_member_will_not_resign_merely_because_it_cannot_reach_them(self):
        """Section 1 offers a ceasefire to an enemy it physically cannot get at.
        For a member that means leaving the bloc -- and being unable to reach
        one enemy is not a reason to walk out on every ally you have.
        """
        self.assertEqual(self.offers_of("MEMBER"), [])

    def test_but_a_leader_still_will(self):
        """It settles for the whole bloc and resigns from nothing."""
        self.assertEqual(self.offers_of("LEADER"), ["CEASEFIRE"])


class SilentLossRatificationTests(unittest.TestCase):
    """The member whose conquests a treaty says nothing about gets a vote."""

    def setUp(self):
        self.game = StubMapScreen(["RUS", "FRA", "FOE"], human_players=("FRA",))
        self.game.set_faction("Entente", "RUS", "FRA")

        self.taken = self.game.add_province("FOE", cores=["FOE"])
        for ours in ("RUS", "FRA"):
            self.game.set_war(ours, "FOE")
        war_actions.save_own_pre_war_map(self.game.map_data, self.game.nation_data, "FOE")
        self.taken["owner"] = "FRA"

    def bound_by(self, agreement):
        return ratification._members_with_something_to_lose(self.game, agreement, "RUS")

    def test_a_white_peace_that_costs_a_member_its_conquests_is_put_to_it(self):
        """It names nobody, so nobody used to be asked -- and restore_occupied
        then took the province off FRA without FRA ever seeing the terms."""
        agreement = deal.new(deal.KIND_PEACE, ["RUS", "FRA"], ["FOE"],
                             [deal.white_peace()])
        self.assertIn("FRA", self.bound_by(agreement))

    def test_a_member_that_keeps_what_it_took_is_not_asked(self):
        agreement = deal.new(deal.KIND_PEACE, ["RUS", "FRA"], ["FOE"],
                             [deal.white_peace(),
                              deal.tiles_clause("FOE", "FRA", [self.taken["id"]])])
        self.assertNotIn("FRA", self.bound_by(agreement))

    def test_a_trade_is_not_a_treaty_and_restores_nothing(self):
        agreement = deal.new(deal.KIND_TRADE, ["RUS", "FRA"], ["FOE"], [])
        self.assertNotIn("FRA", self.bound_by(agreement))


if __name__ == "__main__":
    unittest.main()
