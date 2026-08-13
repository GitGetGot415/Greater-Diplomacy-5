"""Covers the rule that a trade offer costs the same whoever makes it.

What a proposal promises is taken out of the proposer's hands when the offer is
*sent*, and given back if it is refused or lapses. That used to happen in the
trade screen's evaluate_input, which meant it happened for the player and for
nobody else:

  - an accepted AI trade handed over materials the AI never paid, minting them;
  - a rejected AI trade called cancel_trade_escrow on the AI, *refunding* an
    offer it had never funded -- so every offer the player turned down made the
    AI richer.

These tests drive the real diplomacy pass rather than the screen, so an AI's
offer and a player's offer go down the same path.
"""

import os
import sys
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from map_logic.diplomacy import diplomacy_logic
from tests.stub_map_screen import StubMapScreen


OFFER = {"give_materials": 300, "give_fuel": 0,
         "take_materials": 0, "take_fuel": 200, "puppet_state": "NONE"}


class AiTradeEscrowTests(unittest.TestCase):
    """B is an AI (only A is a human player), so this is the path that minted."""

    def setUp(self):
        self.game = StubMapScreen(["A", "B"], human_players=("A",))
        self.game.propose("B", "A", "TRADE", parameters=dict(OFFER))

    def stock(self, nation):
        data = self.game.nation_data[nation]
        return data["materials"], data["fuel"]

    def test_nothing_leaves_the_treasury_while_the_offer_is_only_drafted(self):
        self.assertEqual(self.stock("B"), (1000, 1000))

    def test_sending_the_offer_escrows_what_it_promises(self):
        self.game.run_turn()
        self.assertEqual(self.stock("B"), (700, 1000))

    def test_a_rejected_offer_leaves_the_proposer_exactly_where_it_started(self):
        """The regression: this used to leave B with 1300 materials."""
        self.game.run_turn()
        self.game.answer("A", "B", diplomacy_logic.RESPONSE_REJECT, "TRADE")
        self.game.run_turn()

        self.assertEqual(self.stock("B"), (1000, 1000))
        self.assertEqual(self.stock("A"), (1000, 1000))

    def test_an_ignored_offer_is_refunded_too(self):
        self.game.run_turn()   # sent
        self.game.run_turn()   # no answer -> auto-declined
        self.game.run_turn()

        self.assertEqual(self.stock("B"), (1000, 1000))

    def test_an_accepted_offer_moves_resources_without_creating_any(self):
        self.game.run_turn()
        self.game.answer("A", "B", diplomacy_logic.RESPONSE_ACCEPT, "TRADE")
        self.game.run_turn()

        self.assertEqual(self.stock("B"), (700, 1200))
        self.assertEqual(self.stock("A"), (1300, 800))

    def test_the_world_total_is_conserved_either_way(self):
        before = sum(self.stock("A") + self.stock("B"))
        self.game.run_turn()
        self.game.answer("A", "B", diplomacy_logic.RESPONSE_ACCEPT, "TRADE")
        self.game.run_turn()

        self.assertEqual(sum(self.stock("A") + self.stock("B")), before)


class PlayerTradeEscrowTests(unittest.TestCase):
    """The same path from the human side. The trade screen no longer deducts as
    you type, so the engine has to be the one doing it."""

    def setUp(self):
        self.game = StubMapScreen(["A", "B"], human_players=("A",))
        self.game.propose("A", "B", "TRADE", parameters=dict(OFFER))

    def stock(self, nation):
        data = self.game.nation_data[nation]
        return data["materials"], data["fuel"]

    def test_sending_escrows_the_players_side(self):
        self.game.run_turn()
        self.assertEqual(self.stock("A"), (700, 1000))

    def test_cancelling_a_draft_costs_nothing(self):
        self.game.propose("A", "B", "TRADE")   # re-queueing the same action undoes it
        self.assertEqual(self.stock("A"), (1000, 1000))

    def test_a_promise_larger_than_the_treasury_escrows_only_what_is_there(self):
        self.game.nation_data["A"]["materials"] = 120
        self.game.propose("A", "B", "TRADE")   # clear the draft from setUp
        self.game.propose("A", "B", "TRADE", parameters=dict(OFFER))

        self.game.run_turn()
        self.assertEqual(self.game.nation_data["A"]["materials"], 0)

        self.game.answer("B", "A", diplomacy_logic.RESPONSE_REJECT, "TRADE")
        self.game.run_turn()
        self.assertEqual(self.game.nation_data["A"]["materials"], 120,
                         "refunding the promise rather than the holding would mint")


if __name__ == "__main__":
    unittest.main()
