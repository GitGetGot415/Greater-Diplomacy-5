"""Covers the candidate list the proactive pass now produces.

Two things matter here. First, that the arbiter picks the best action rather
than whichever section happened to run first -- the starvation this replaced.
Second, and more importantly for what comes next, that everything on the list is
legal: phase 4 hands this list to a language model to choose from, and the only
reason that is safe is that a candidate which should not exist never gets made.
"""

import os
import sys
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import data.constants as c
from map_logic.ai import ai_candidates as ac, ai_diplomacy, ai_world
from tests.stub_map_screen import StubMapScreen


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.pending = {}
        self.bag = ac.Collector("A", self.pending)

    def test_the_better_of_two_aimed_at_one_nation_wins(self):
        """pending_diplomacy holds one action per target. It used to be whichever
        section ran first; now it is whichever is worth more."""
        self.bag.add(ac.make("REQ_MILITARY_ACCESS", "B", 0.4, "passage"))
        self.bag.add(ac.make("WAR_DECLARATION", "B", 0.9, "they hold our cores"))
        chosen = self.bag.ranked()
        self.assertEqual(len(chosen), 1)
        self.assertEqual(chosen[0].action, "WAR_DECLARATION")

    def test_order_of_offering_does_not_matter(self):
        reverse = ac.Collector("A", {})
        reverse.add(ac.make("WAR_DECLARATION", "B", 0.9, "x"))
        reverse.add(ac.make("REQ_MILITARY_ACCESS", "B", 0.4, "y"))
        self.assertEqual(reverse.ranked()[0].action, "WAR_DECLARATION")

    def test_actions_at_different_nations_all_survive(self):
        self.bag.add(ac.make("TRADE", "B", 0.4, "x"))
        self.bag.add(ac.make("TRADE", "C", 0.4, "y"))
        self.assertEqual(len(self.bag.ranked()), 2)

    def test_a_proposal_already_travelling_is_not_overwritten(self):
        """Replacing it under the recipient would lose a message in transit."""
        self.pending["B"] = {"action": "CEASEFIRE", "turns": 1}
        self.assertFalse(self.bag.add(ac.make("WAR_DECLARATION", "B", 1.0, "x")))
        self.assertEqual(self.bag.ranked(), [])

    def test_a_slot_queued_this_turn_can_still_be_improved(self):
        self.pending["B"] = {"action": "CEASEFIRE", "turns": 0}
        self.assertTrue(self.bag.add(ac.make("WAR_DECLARATION", "B", 1.0, "x")))

    def test_ranking_is_best_first_and_limited(self):
        for i, score in enumerate([0.1, 0.9, 0.5, 0.7]):
            self.bag.add(ac.make("TRADE", f"N{i}", score, "x"))
        chosen = self.bag.ranked(limit=2)
        self.assertEqual([cand.score for cand in chosen], [0.9, 0.7])

    def test_indices_are_assigned_in_rank_order(self):
        self.bag.add(ac.make("TRADE", "B", 0.2, "x"))
        self.bag.add(ac.make("TRADE", "C", 0.8, "y"))
        chosen = self.bag.ranked()
        self.assertEqual([cand.cid for cand in chosen], ["0", "1"])
        self.assertEqual(chosen[0].target, "C")

    def test_ties_break_the_same_way_every_run(self):
        first, second = ac.Collector("A", {}), ac.Collector("A", {})
        for target in ("B", "C", "D"):
            first.add(ac.make("TRADE", target, 0.5, "x"))
        for target in ("D", "C", "B"):
            second.add(ac.make("TRADE", target, 0.5, "x"))
        self.assertEqual([cand.target for cand in first.ranked()],
                         [cand.target for cand in second.ranked()])

    def test_scores_are_clamped(self):
        self.assertEqual(ac.make("TRADE", "B", 5.0, "x").score, 1.0)
        self.assertEqual(ac.make("TRADE", "B", -3.0, "x").score, 0.0)

    def test_adding_nothing_is_harmless(self):
        self.assertFalse(self.bag.add(None))


class ResourceOfferTests(unittest.TestCase):
    """The offer builder. Its first version returned None for every pair on the
    map because it compared each side's *best* surplus, and nearly every nation
    is longest on materials."""

    class FakeWorld:
        def __init__(self, econ, stock):
            self.economies = econ
            self.nation_data = stock

    def world(self, a_mat, a_fuel, b_mat, b_fuel):
        econ = {
            "A": {"total_inc": {"materials": a_mat, "fuel": a_fuel, "manpower": 0},
                  "upkeep": {"materials": 0, "fuel": 0, "manpower": 0}},
            "B": {"total_inc": {"materials": b_mat, "fuel": b_fuel, "manpower": 0},
                  "upkeep": {"materials": 0, "fuel": 0, "manpower": 0}},
        }
        stock = {"A": {"materials": 0, "fuel": 0}, "B": {"materials": 0, "fuel": 0}}
        return self.FakeWorld(econ, stock)

    def test_materials_for_fuel_when_that_is_the_shortage(self):
        offer = ac.resource_offer(self.world(10000, 10, 500, 4000), "A", "B")
        self.assertIsNotNone(offer)
        self.assertIn("give_materials", offer)
        self.assertIn("take_fuel", offer)

    def test_a_partner_whose_biggest_surplus_is_also_ours_can_still_trade(self):
        """The exact original bug. It picked each side's *best* surplus and bailed
        when they matched -- and nearly every nation on the map is longest on
        materials, so the function returned None for every pair in the game.

        What matters is what *we* are short of, not what they have most of.
        """
        offer = ac.resource_offer(self.world(10000, 10, 8000, 2000), "A", "B")
        self.assertIsNotNone(offer, "both sides longest on materials, but B has fuel to spare")
        self.assertIn("give_materials", offer)
        self.assertIn("take_fuel", offer)

    def test_nothing_to_spare_means_no_offer(self):
        self.assertIsNone(ac.resource_offer(self.world(0, 0, 0, 0), "A", "B"))

    def test_a_partner_with_none_of_what_we_need_is_no_use(self):
        self.assertIsNone(ac.resource_offer(self.world(10000, 10, 10000, 0), "A", "B"))

    def test_a_tiny_surplus_is_not_worth_a_proposal(self):
        self.assertIsNone(ac.resource_offer(self.world(10, 1, 10, 500), "A", "B"))

    def test_the_two_sides_are_not_matched_one_for_one(self):
        """Materials and fuel are nothing like the same value; an even swap by
        volume would be an absurd offer."""
        offer = ac.resource_offer(self.world(20000, 10, 500, 2000), "A", "B")
        self.assertNotEqual(offer["give_materials"], offer["take_fuel"])

    def test_an_unknown_nation_is_handled(self):
        self.assertIsNone(ac.resource_offer(self.world(1, 1, 1, 1), "A", "Nowhere"))


class LegalityTests(unittest.TestCase):
    """Nothing illegal may reach the list. Phase 4 lets a model pick from it."""

    def emitted(self, game):
        ai_diplomacy.process_basic_proactive_ai(game)
        out = []
        for name, data in game.nation_data.items():
            if not isinstance(data, dict):
                continue
            for target, info in (data.get("pending_diplomacy") or {}).items():
                if isinstance(info, dict) and info.get("action"):
                    out.append((name, target, info["action"]))
        return out

    def test_no_war_is_declared_on_a_faction_mate(self):
        game = StubMapScreen(["A", "B", "X"], human_players=[])
        game.set_faction("Pact", "A", "B")
        game.nation_data["A"]["claims"] = [2]
        for name, target, action in self.emitted(game):
            if action == "WAR_DECLARATION":
                self.assertFalse(
                    game.nation_data[name].get("faction")
                    and game.nation_data[name]["faction"] == game.nation_data[target].get("faction"),
                    f"{name} declared war on faction-mate {target}")

    def test_no_war_is_declared_under_a_truce(self):
        game = StubMapScreen(["A", "B"], human_players=[])
        game.nation_data["A"]["truces"] = {"B": 10}
        game.nation_data["A"]["claims"] = [2]
        self.assertNotIn(("A", "B", "WAR_DECLARATION"), self.emitted(game))

    def test_nothing_is_proposed_to_a_nation_that_is_gone(self):
        game = StubMapScreen(["A", "B"], human_players=[])
        game.map_data["2"]["owner"] = "A"      # B no longer owns anything
        living = {name for name, _t, _a in self.emitted(game)}
        for name, target, _action in self.emitted(game):
            self.assertNotEqual(target, "B", "proposed to a dead nation")

    def test_a_nation_never_proposes_to_itself(self):
        game = StubMapScreen(["A", "B", "C"], human_players=[])
        for name, target, _action in self.emitted(game):
            self.assertNotEqual(name, target)

    def test_at_most_the_cap_is_queued_per_nation(self):
        game = StubMapScreen([f"N{i}" for i in range(8)], human_players=[])
        for i in range(1, 8):
            game.set_war("N0", f"N{i}")
        ai_diplomacy.process_basic_proactive_ai(game)
        for name, data in game.nation_data.items():
            if not isinstance(data, dict):
                continue
            fresh = [i for i in (data.get("pending_diplomacy") or {}).values()
                     if isinstance(i, dict) and i.get("turns", 0) == 0]
            self.assertLessEqual(len(fresh), c.AI_MAX_ACTIONS_PER_TURN, name)

    def test_every_queued_action_is_one_the_pass_knows_how_to_send(self):
        game = StubMapScreen(["A", "B", "C"], human_players=[])
        game.set_war("A", "C")
        for _name, _target, action in self.emitted(game):
            self.assertIn(action, ai_diplomacy.PROACTIVE_PROPOSALS, action)


if __name__ == "__main__":
    unittest.main()
