"""Taking a faction's leadership off the nation that founded it.

Leadership was permanent. Whoever created a faction spoke for it at the peace
table, chose who was kicked out and whether it existed at all, and no amount of
outgrowing them changed that -- a member with five times the leader's army still
had to ask permission to open talks, and still had its own territory put on the
table by somebody else.

The rule that replaces it is deliberately hard to trip by accident. Outweighing
the leader is not enough; two comparable powers do that to each other every
other turn as units are built and lost, and a bloc whose leadership changed on
that would be unreadable. It takes FACTION_CHALLENGE_MARGIN times their weight,
held for FACTION_CHALLENGE_TURNS consecutive turns, with the count reset by the
first turn it slips.
"""

import os
import sys
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import data.constants as c
from data import queries
from map_logic.diplomacy import faction_leadership, war_score
from tests.stub_map_screen import StubMapScreen


class Bloc(unittest.TestCase):
    """Leader runs The Pact; Rival and Loyal are members.

    Weight is read off stockpiles (get_economic_power) rather than armies, so a
    test can say "twice as strong" in one line instead of placing units.
    """

    def setUp(self):
        self.game = StubMapScreen(["Leader", "Rival", "Loyal", "Outsider"])
        self.game.set_faction("The Pact", "Leader", "Rival", "Loyal")
        self.weigh("Leader", 1000)
        self.weigh("Rival", 1000)
        self.weigh("Loyal", 1000)

    def weigh(self, nation, materials):
        self.game.nation_data[nation]["materials"] = materials
        self.game.nation_data[nation]["fuel"] = 0
        self.game.nation_data[nation]["manpower"] = 0

    def tick(self, times=1):
        for _ in range(times):
            faction_leadership.tick(self.game)

    def held(self, nation):
        return faction_leadership.turns_held(nation, self.game.nation_data)

    def leader(self):
        return queries.get_faction_leader("The Pact", self.game.nation_data)


class PressureTests(Bloc):
    def test_a_member_no_stronger_than_its_leader_never_starts_counting(self):
        self.tick(20)
        self.assertEqual(self.held("Rival"), 0)

    def test_nor_does_merely_pulling_ahead(self):
        """The margin is the whole point. Without it a bloc's leadership would
        follow whichever of two comparable powers last finished a tank."""
        self.weigh("Rival", 1400)   # 1.4x, under the 1.5x bar
        self.tick(20)
        self.assertEqual(self.held("Rival"), 0)

    def test_but_clearing_the_margin_does(self):
        self.weigh("Rival", 2000)
        self.tick(3)
        self.assertEqual(self.held("Rival"), 3)

    def test_and_one_bad_turn_puts_it_back_to_nothing(self):
        self.weigh("Rival", 2000)
        self.tick(5)
        self.weigh("Rival", 1000)
        self.tick(1)
        self.assertEqual(self.held("Rival"), 0)

    def test_the_leader_is_not_measured_against_itself(self):
        self.weigh("Leader", 9999)
        self.tick(10)
        self.assertEqual(self.held("Leader"), 0)

    def test_nor_is_a_nation_outside_the_faction(self):
        self.weigh("Outsider", 99999)
        self.tick(10)
        self.assertEqual(self.held("Outsider"), 0)

    def test_a_puppet_has_no_claim_to_press(self):
        """Its alignment is its master's. Leading a faction out from under the
        overlord that put it in one is the same broken state as joining one
        alone, and can_choose_own_faction is the rule that says so."""
        self.game.nation_data["Rival"]["master"] = "Outsider"
        self.weigh("Rival", 9999)
        self.tick(10)
        self.assertEqual(self.held("Rival"), 0)
        self.assertFalse(faction_leadership.can_claim(self.game, "Rival"))

    def test_the_count_is_dropped_on_the_way_out_of_the_faction(self):
        """Not merely on the next tick. Walking out is not a way to bank six
        turns of pressure against a bloc you might rejoin, and a save taken
        between turns would otherwise carry the stale number."""
        from map_logic.diplomacy import faction_actions

        self.weigh("Rival", 2000)
        self.tick(4)
        faction_actions.leave_faction(self.game.nation_data, "Rival")
        self.assertEqual(self.held("Rival"), 0)

    def test_and_when_the_faction_is_disbanded_under_them(self):
        from map_logic.diplomacy import faction_actions

        self.weigh("Rival", 2000)
        self.tick(4)
        faction_actions.finalize_disband_faction(self.game.nation_data, "Leader")
        self.assertEqual(self.held("Rival"), 0)


class ClaimTests(Bloc):
    def qualify(self, nation="Rival", turns=c.FACTION_CHALLENGE_TURNS):
        self.weigh(nation, 2000)
        self.tick(turns)

    def test_one_turn_short_is_short(self):
        self.qualify(turns=c.FACTION_CHALLENGE_TURNS - 1)
        self.assertFalse(faction_leadership.can_claim(self.game, "Rival"))

    def test_and_the_last_one_unlocks_it(self):
        self.qualify()
        self.assertTrue(faction_leadership.can_claim(self.game, "Rival"))

    def test_the_screen_can_say_how_far_along_it_is(self):
        self.qualify(turns=3)
        self.assertEqual(faction_leadership.standing(self.game, "Rival"),
                         (3, c.FACTION_CHALLENGE_TURNS, True))

    def test_and_says_nothing_at_all_to_the_leader(self):
        self.assertIsNone(faction_leadership.standing(self.game, "Leader"))
        self.assertIsNone(faction_leadership.standing(self.game, "Outsider"))


class TransferTests(Bloc):
    def setUp(self):
        super().setUp()
        self.weigh("Rival", 2000)
        self.tick(c.FACTION_CHALLENGE_TURNS)
        faction_leadership.transfer(self.game.nation_data, "Leader", "Rival")

    def test_exactly_one_nation_leads_afterwards(self):
        flags = [n for n in ("Leader", "Rival", "Loyal")
                 if self.game.nation_data[n]["is_faction_leader"]]
        self.assertEqual(flags, ["Rival"])

    def test_the_faction_itself_is_untouched(self):
        """Its name, its roster and its pre-war map are keyed by the faction and
        not by whoever leads it, so a handover moves two booleans and nothing
        else has to be rewritten."""
        self.assertEqual(sorted(queries.get_faction_members("The Pact",
                                                            self.game.nation_data)),
                         ["Leader", "Loyal", "Rival"])

    def test_every_member_starts_counting_again(self):
        """The new leader is a new bar. A nation that had been closing on the old
        one has not outweighed anybody yet."""
        self.assertEqual(self.held("Rival"), 0)
        self.assertEqual(self.held("Loyal"), 0)

    def test_the_deposed_leader_resents_it_and_nobody_else_does(self):
        mods = self.game.nation_data["Leader"].get("temp_modifiers", {})
        self.assertIn("deposed", mods.get("Rival", {}))
        self.assertNotIn("deposed",
                         self.game.nation_data["Loyal"].get("temp_modifiers", {})
                         .get("Rival", {}))

    def test_the_old_leader_can_now_start_a_claim_of_its_own(self):
        """Nothing is one-way about this. It is still in the faction, and if it
        rebuilds it can take the chair back the same way it lost it."""
        self.weigh("Leader", 4000)
        self.tick(c.FACTION_CHALLENGE_TURNS)
        self.assertTrue(faction_leadership.can_claim(self.game, "Leader"))


class TurnTests(Bloc):
    """The whole path: queue the action the way the button does, run the turn."""

    def qualify(self):
        self.weigh("Rival", 2000)
        self.tick(c.FACTION_CHALLENGE_TURNS)

    def claim(self):
        return self.game.propose("Rival", "Rival", "CLAIM_FACTION_LEADERSHIP")

    def test_a_qualified_claim_changes_the_leader(self):
        self.qualify()
        self.claim()
        self.game.run_turn()
        self.assertEqual(self.leader(), "Rival")

    def test_and_tells_the_rest_of_the_faction(self):
        self.qualify()
        self.claim()
        self.game.run_turn()
        self.assertTrue(self.game.inbound("Loyal", "Rival"),
                        "the other members heard nothing about it")

    def test_a_claim_whose_army_evaporates_in_transit_does_nothing(self):
        """It is queued a turn ahead, and a turn is long enough to lose the war
        that justified it. Re-checked where it executes rather than trusted from
        where it was pressed."""
        self.qualify()
        self.claim()
        self.weigh("Rival", 100)
        self.game.run_turn()
        self.assertEqual(self.leader(), "Leader")

    def test_an_unqualified_claim_does_nothing(self):
        self.claim()
        self.game.run_turn()
        self.assertEqual(self.leader(), "Leader")


class AiClaimTests(Bloc):
    """The AI takes the chair too, or the mechanic is the player's alone."""

    def setUp(self):
        super().setUp()
        self.weigh("Rival", 2000)
        self.tick(c.FACTION_CHALLENGE_TURNS)

    def offered(self, ambition):
        from map_logic.ai import ai_candidates, ai_diplomacy

        settings = {"ai_personality_overrides": {"Rival": {"ambition": ambition}}}
        self.game.nation_data["Rival"].pop("personality", None)
        bag = ai_candidates.Collector("Rival", {})
        ai_diplomacy._claim_faction_leadership(bag, self.game, "Rival", None, settings)
        return [candidate.action for candidate in bag.ranked()]

    def test_an_ambitious_member_takes_it(self):
        self.assertIn("CLAIM_FACTION_LEADERSHIP", self.offered(0.9))

    def test_a_content_one_stays_a_follower(self):
        """However heavy it has grown. Otherwise the strongest army in every
        bloc mechanically ends up at its head, which is a rule rather than a
        decision."""
        self.assertEqual(self.offered(0.1), [])

    def test_and_nobody_claims_what_they_have_not_earned(self):
        self.weigh("Rival", 1000)
        self.tick(1)
        self.assertEqual(self.offered(0.9), [])


class StrengthTests(unittest.TestCase):
    def test_the_scale_is_the_one_the_peace_table_uses(self):
        """A second definition of "stronger" would be a second answer to the
        question the leverage bar already answers."""
        game = StubMapScreen(["A"])
        self.assertEqual(faction_leadership.power_of(game, "A"),
                         war_score.nation_power(game, "A"))

    def test_a_bloc_is_the_sum_of_its_members(self):
        game = StubMapScreen(["A", "B"])
        self.assertAlmostEqual(
            war_score._bloc_power(game, ["A", "B"]),
            war_score.nation_power(game, "A") + war_score.nation_power(game, "B"))


if __name__ == "__main__":
    unittest.main()
