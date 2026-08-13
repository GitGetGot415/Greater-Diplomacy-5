"""Covers peace between whole factions, driven through the real turn pass.

Three things this pins down:

  * A leader's settlement ends the war for every member of both blocs. It used
    to end it for exactly two nations, so a faction could be left half at war.
  * A member bound by terms it did not agree to may refuse, at the price of its
    faction -- and the rest of the treaty still stands.
  * The reported bug: an AI inside a faction offering a ceasefire to a
    faction-mate in peacetime. The LLM retaliation branch had no war check and
    fell back to targeting whoever had just messaged it, and accepting the
    result wrote a 12-turn truce that quietly opted the pair out of the bloc's
    wars.
"""

import os
import sys
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import data.constants as c
from data import queries
from map_logic.diplomacy import (deal, diplomacy_logic, diplomacy_processor,
                                 peace_scope, ratification)
from tests.stub_map_screen import StubMapScreen


def two_blocs(human_players=("A",)):
    """Entente (A leads, with S) at war with the Alliance (G leads, with T)."""
    game = StubMapScreen(["A", "S", "G", "T"], human_players=human_players)
    game.set_faction("Entente", "A", "S")
    game.set_faction("Alliance", "G", "T")
    for ours in ("A", "S"):
        for theirs in ("G", "T"):
            game.set_war(ours, theirs)
    return game


def at_war(game, a, b):
    return queries.are_at_war(a, b, game.nation_data)


class BlocPeaceTests(unittest.TestCase):
    """A is human and leads the Entente; G leads the Alliance and is an AI."""

    def setUp(self):
        self.game = two_blocs()

    def sides(self):
        return peace_scope.deal_sides("A", "G", self.game.nation_data)

    def test_a_leaders_white_peace_ends_the_war_for_everyone(self):
        mine, theirs = self.sides()
        agreement = deal.new(deal.KIND_PEACE, mine, theirs, [deal.white_peace()])

        self.game.propose("A", "G", "PEACE_TREATY", parameters=agreement)
        self.game.run_turn()
        self.game.answer("G", "A", diplomacy_logic.RESPONSE_ACCEPT, "PEACE_TREATY")
        self.game.run_turn()

        for ours in ("A", "S"):
            for theirs_n in ("G", "T"):
                self.assertFalse(at_war(self.game, ours, theirs_n),
                                 f"{ours} is still at war with {theirs_n}")

    def test_the_truce_covers_every_pair(self):
        mine, theirs = self.sides()
        agreement = deal.new(deal.KIND_PEACE, mine, theirs, [deal.white_peace()])

        self.game.propose("A", "G", "PEACE_TREATY", parameters=agreement)
        self.game.run_turn()
        self.game.answer("G", "A", diplomacy_logic.RESPONSE_ACCEPT, "PEACE_TREATY")
        self.game.run_turn()

        self.assertEqual(self.game.nation_data["S"]["truces"]["T"], c.TRUCE_TURNS)

    def test_a_leader_can_cede_a_members_territory(self):
        theirs_prov = self.game.add_province("T", cores=["T"])
        mine, theirs = self.sides()
        agreement = deal.new(deal.KIND_PEACE, mine, theirs, [
            deal.white_peace(),
            deal.tiles_clause("T", "S", [theirs_prov["id"]]),
        ])

        self.game.propose("A", "G", "PEACE_TREATY", parameters=agreement)
        self.game.run_turn()
        self.game.answer("G", "A", diplomacy_logic.RESPONSE_ACCEPT, "PEACE_TREATY")
        self.game.run_turn()

        self.assertEqual(self.game.owner_of(theirs_prov["id"]), "S")


class RatificationTests(unittest.TestCase):
    """S is a human member of A's bloc, so it gets a real say."""

    def setUp(self):
        self.game = two_blocs(human_players=("A", "S"))
        self.at_stake = self.game.add_province("S", cores=["S"])
        mine, theirs = peace_scope.deal_sides("A", "G", self.game.nation_data)
        self.deal = deal.new(deal.KIND_PEACE, mine, theirs, [
            deal.white_peace(),
            deal.tiles_clause("S", "G", [self.at_stake["id"]]),
        ])

    def reach_acceptance(self):
        self.game.propose("A", "G", "PEACE_TREATY", parameters=self.deal)
        self.game.run_turn()
        self.game.answer("G", "A", diplomacy_logic.RESPONSE_ACCEPT, "PEACE_TREATY")
        self.game.run_turn()

    def test_a_bound_member_is_asked_before_it_takes_effect(self):
        self.reach_acceptance()

        asked = ratification.pending_for(self.game.nation_data, "S")
        self.assertTrue(asked)
        self.assertEqual(asked["signatory"], "A")
        self.assertEqual(self.game.owner_of(self.at_stake["id"]), "S",
                         "nothing moves until the member answers")
        self.assertTrue(at_war(self.game, "S", "G"))

    def test_ratifying_lets_the_treaty_through(self):
        self.reach_acceptance()
        ratification.answer(self.game.nation_data, "S", ratification.RATIFY)
        self.game.run_turn()

        self.assertEqual(self.game.owner_of(self.at_stake["id"]), "G")
        self.assertFalse(at_war(self.game, "S", "G"))
        self.assertEqual(self.game.nation_data["S"]["faction"], "Entente")

    def test_refusing_costs_the_faction_and_keeps_the_war(self):
        self.reach_acceptance()
        ratification.answer(self.game.nation_data, "S", ratification.REFUSE)
        self.game.run_turn()

        self.assertEqual(self.game.owner_of(self.at_stake["id"]), "S", "kept its land")
        self.assertEqual(self.game.nation_data["S"]["faction"], "", "lost its faction")
        self.assertTrue(at_war(self.game, "S", "G"), "fights on alone")

    def test_the_rest_of_the_treaty_survives_a_refusal(self):
        self.reach_acceptance()
        ratification.answer(self.game.nation_data, "S", ratification.REFUSE)
        self.game.run_turn()

        self.assertFalse(at_war(self.game, "A", "G"),
                         "the leader's own peace still holds")

    def test_silence_is_taken_as_consent_eventually(self):
        """A member cannot hold a bloc's settlement open forever by ignoring it."""
        self.reach_acceptance()
        for _ in range(c.RATIFICATION_TURNS + 1):
            self.game.run_turn()

        self.assertEqual(self.game.owner_of(self.at_stake["id"]), "G")
        self.assertFalse(ratification.pending_for(self.game.nation_data, "S"))

    def test_a_member_with_nothing_at_stake_is_not_asked(self):
        mine, theirs = peace_scope.deal_sides("A", "G", self.game.nation_data)
        plain = deal.new(deal.KIND_PEACE, mine, theirs, [deal.white_peace()])

        self.game.propose("A", "G", "PEACE_TREATY", parameters=plain)
        self.game.run_turn()
        self.game.answer("G", "A", diplomacy_logic.RESPONSE_ACCEPT, "PEACE_TREATY")
        self.game.run_turn()

        self.assertFalse(ratification.pending_for(self.game.nation_data, "S"))
        self.assertFalse(at_war(self.game, "S", "G"))


class SeparatePeaceTests(unittest.TestCase):
    """S is a human member who wants out of a war its leader will not end."""

    def setUp(self):
        self.game = two_blocs(human_players=("S",))

    def test_a_member_settling_alone_leaves_its_faction(self):
        mine, theirs = peace_scope.deal_sides("S", "G", self.game.nation_data)
        agreement = deal.new(deal.KIND_PEACE, mine, theirs, [deal.white_peace()])

        self.game.propose("S", "G", "PEACE_TREATY", parameters=agreement)
        self.game.run_turn()
        self.game.run_turn()

        self.assertEqual(self.game.nation_data["S"]["faction"], "")
        self.assertFalse(at_war(self.game, "S", "G"))
        self.assertFalse(at_war(self.game, "S", "T"))

    def test_the_bloc_it_left_fights_on(self):
        mine, theirs = peace_scope.deal_sides("S", "G", self.game.nation_data)
        agreement = deal.new(deal.KIND_PEACE, mine, theirs, [deal.white_peace()])

        self.game.propose("S", "G", "PEACE_TREATY", parameters=agreement)
        self.game.run_turn()
        self.game.run_turn()

        self.assertTrue(at_war(self.game, "A", "G"))

    def test_leaving_is_enforced_even_if_the_clause_is_missing(self):
        """The price of the manoeuvre, not a term either side chose -- so
        treaty_effects adds it whether or not the screen did."""
        agreement = deal.new(deal.KIND_PEACE, ["S"], ["G", "T"], [deal.white_peace()])

        self.game.propose("S", "G", "PEACE_TREATY", parameters=agreement)
        self.game.run_turn()
        self.game.run_turn()

        self.assertEqual(self.game.nation_data["S"]["faction"], "")


class FactionMateCeasefireTests(unittest.TestCase):
    """The reported bug, at the branch that caused it."""

    def setUp(self):
        self.game = two_blocs(human_players=("A",))
        self.delayed = []

    def retaliate(self, sender, target, default_target="A"):
        """One model reply, as _process_pass2_delayed_actions delivers it.

        `default_target` is the nation whose proposal the sender is answering --
        which is what an unresolvable target silently became.
        """
        diplomacy_processor._process_ai_retaliation(
            self.game, sorted(self.game.nation_data), self.delayed, sender,
            {"action": "CEASEFIRE", "action_target": target, "message": ""},
            default_target=default_target)

    def queued(self):
        return [(entry[0], entry[1], entry[2]) for entry in self.delayed]

    def test_an_unnamed_target_no_longer_becomes_whoever_just_wrote_to_us(self):
        """The bug exactly: S answers its faction-mate A's call to arms, the
        model returns CEASEFIRE with no usable target, and get_valid_target
        hands back `default_target` -- A. That queued a ceasefire offer to an
        ally, in peacetime."""
        self.retaliate("S", "NONE", default_target="A")
        self.assertEqual(self.queued(), [])

    def test_a_garbled_target_is_dropped_rather_than_redirected(self):
        self.retaliate("S", "Freedonia", default_target="A")
        self.assertEqual(self.queued(), [])

    def test_a_ceasefire_naming_a_faction_mate_outright_is_dropped_too(self):
        self.retaliate("S", "A")
        self.assertEqual(self.queued(), [])

    def test_a_ceasefire_with_an_actual_enemy_still_goes_out(self):
        self.retaliate("A", "G")
        self.assertEqual(self.queued(), [("A", "G", "CEASEFIRE")])

    def test_a_ceasefire_aimed_at_a_mere_member_of_the_enemy_bloc_is_dropped(self):
        """T is at war with A, but T does not lead the Alliance -- so there is
        nobody there with the authority to answer."""
        self.retaliate("A", "T")
        self.assertEqual(self.queued(), [])

    def test_a_follow_up_ceasefire_is_validated_too(self):
        """_flush_queued_ai_actions injected these with no checks at all."""
        self.game.nation_data["S"]["queued_ai_actions"] = [
            {"target": "A", "action": "CEASEFIRE"}]

        diplomacy_processor._flush_queued_ai_actions(self.game)

        self.assertEqual(self.game.pending_action("S", "A"), "")

    def test_a_legitimate_follow_up_still_lands(self):
        self.game.nation_data["A"]["queued_ai_actions"] = [
            {"target": "G", "action": "CEASEFIRE"}]

        diplomacy_processor._flush_queued_ai_actions(self.game)

        self.assertEqual(self.game.pending_action("A", "G"), "CEASEFIRE")

    def test_no_faction_mate_ever_ends_up_truced_with_another(self):
        """The consequence that made the bug bite: a truce between allies makes
        join_faction_wars skip them for twelve turns."""
        for _ in range(4):
            self.game.run_turn()

        for a, b in (("A", "S"), ("G", "T")):
            self.assertNotIn(b, self.game.nation_data[a].get("truces", {}))
            self.assertNotIn(a, self.game.nation_data[b].get("truces", {}))


if __name__ == "__main__":
    unittest.main()
