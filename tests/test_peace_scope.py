"""Covers who a war is between and who may end it.

Peace had never heard of a faction. A single member could sign its own treaty
and leave a war its bloc was still fighting, which is the state behind an AI
sitting inside a faction while quietly ignoring one member of the enemy bloc.
"""

import os
import sys
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from map_logic.diplomacy import peace_scope
from tests.stub_map_screen import StubMapScreen


class UnalignedTests(unittest.TestCase):
    def setUp(self):
        self.game = StubMapScreen(["A", "B"])
        self.game.set_war("A", "B")

    def test_two_loners_negotiate_bilaterally(self):
        role = peace_scope.negotiation_role("A", "B", self.game.nation_data)
        self.assertEqual(role, peace_scope.BILATERAL)
        self.assertFalse(peace_scope.binds_whole_bloc(role))
        self.assertFalse(peace_scope.costs_membership(role))

    def test_the_sides_are_just_the_two_of_them(self):
        self.assertEqual(peace_scope.war_sides("A", "B", self.game.nation_data),
                         (["A"], ["B"]))

    def test_a_puppet_cannot_settle_its_own_war(self):
        self.game.nation_data["A"]["master"] = "C"
        self.assertIsNone(peace_scope.negotiation_role("A", "B", self.game.nation_data))
        self.assertIn("Puppets", peace_scope.refusal_reason("A", "B", self.game.nation_data))


class BlocTests(unittest.TestCase):
    """Entente (A leads, with S) against the Alliance (G leads, with T)."""

    def setUp(self):
        self.game = StubMapScreen(["A", "S", "G", "T"], human_players=("A",))
        self.game.set_faction("Entente", "A", "S")
        self.game.set_faction("Alliance", "G", "T")
        for ours in ("A", "S"):
            for theirs in ("G", "T"):
                self.game.set_war(ours, theirs)

    def test_the_sides_are_the_whole_blocs(self):
        mine, theirs = peace_scope.war_sides("A", "G", self.game.nation_data)
        self.assertEqual(sorted(mine), ["A", "S"])
        self.assertEqual(sorted(theirs), ["G", "T"])

    def test_a_leader_speaks_for_its_bloc(self):
        role = peace_scope.negotiation_role("A", "G", self.game.nation_data)
        self.assertEqual(role, peace_scope.BLOC_LEADER)
        self.assertTrue(peace_scope.binds_whole_bloc(role))

    def test_a_leader_deal_binds_every_member(self):
        mine, theirs = peace_scope.deal_sides("A", "G", self.game.nation_data)
        self.assertEqual(sorted(mine), ["A", "S"])
        self.assertEqual(peace_scope.bound_members(mine, "A"), ["S"])

    def test_nobody_may_deal_with_an_individual_member(self):
        """The hole this module exists to close."""
        self.assertIsNone(peace_scope.negotiation_role("A", "T", self.game.nation_data))
        reason = peace_scope.refusal_reason("A", "T", self.game.nation_data)
        self.assertIn("G", reason)
        self.assertIn("Alliance", reason)

    def test_a_member_may_only_buy_its_own_way_out(self):
        role = peace_scope.negotiation_role("S", "G", self.game.nation_data)
        self.assertEqual(role, peace_scope.SEPARATE_PEACE)
        self.assertTrue(peace_scope.costs_membership(role))

    def test_a_separate_peace_is_one_nation_against_the_whole_enemy_bloc(self):
        mine, theirs = peace_scope.deal_sides("S", "G", self.game.nation_data)
        self.assertEqual(mine, ["S"])
        self.assertEqual(sorted(theirs), ["G", "T"])
        self.assertEqual(peace_scope.bound_members(mine, "S"), [])

    def test_a_member_still_cannot_pick_off_another_member(self):
        self.assertIsNone(peace_scope.negotiation_role("S", "T", self.game.nation_data))

    def test_a_faction_mate_at_peace_is_not_dragged_to_the_table(self):
        neutral = "N"
        self.game.nation_data[neutral] = dict(self.game.nation_data["S"], name=neutral,
                                              at_war_with=[], truces={})
        self.game.add_province(neutral)
        self.game.nation_data[neutral]["faction"] = "Entente"

        mine, _ = peace_scope.war_sides("A", "G", self.game.nation_data)
        self.assertNotIn(neutral, mine)

    def test_the_signatory_is_a_party_even_if_it_has_stopped_fighting(self):
        """A leader negotiating for its bloc need not personally still be at
        war with anyone left standing, but it is the one signing."""
        self.game.nation_data["A"]["at_war_with"] = []
        mine, theirs = peace_scope.war_sides("A", "G", self.game.nation_data)
        self.assertIn("A", mine)
        self.assertIn("S", mine)
        self.assertTrue(theirs)


class LeadershipTests(unittest.TestCase):
    def setUp(self):
        self.game = StubMapScreen(["A", "S", "G"], human_players=("A",))
        self.game.set_faction("Entente", "A", "S")
        self.game.set_war("A", "G")
        self.game.set_war("S", "G")

    def test_leader_of_resolves_through_the_faction(self):
        self.assertEqual(peace_scope.leader_of("S", self.game.nation_data), "A")
        self.assertEqual(peace_scope.leader_of("G", self.game.nation_data), "G")

    def test_an_unaligned_enemy_can_still_be_talked_to_directly(self):
        self.assertEqual(peace_scope.negotiation_role("A", "G", self.game.nation_data),
                         peace_scope.BLOC_LEADER)

    def test_a_bloc_deal_with_a_loner_still_binds_the_bloc(self):
        mine, theirs = peace_scope.deal_sides("A", "G", self.game.nation_data)
        self.assertEqual(sorted(mine), ["A", "S"])
        self.assertEqual(theirs, ["G"])

    def test_puppets_ride_along_on_their_masters_side(self):
        self.game.nation_data["P"] = dict(self.game.nation_data["S"], name="P",
                                          faction="", at_war_with=["G"], puppets=[])
        self.game.add_province("P")
        self.game.nation_data["P"]["master"] = "A"
        self.game.nation_data["A"]["puppets"] = ["P"]
        self.game.nation_data["G"]["at_war_with"].append("P")

        mine, _ = peace_scope.war_sides("A", "G", self.game.nation_data)
        self.assertIn("P", mine)


if __name__ == "__main__":
    unittest.main()
