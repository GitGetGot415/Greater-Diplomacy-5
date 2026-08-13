"""Covers leverage -- who is winning, as a number.

There was no such thing before: will_ai_accept_peace flipped on
ai_thinks_it_can_win, a judgement about future prospects, so a nation sitting on
half its enemy's territory had exactly as much claim at the table as one that
had taken nothing.

The two properties that matter are that the two sides' scores always sum to one
(the UI draws a single bar from them) and that occupying more of the enemy's
homeland can only ever help.
"""

import os
import sys
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from map_logic.diplomacy import war_score
from tests.stub_map_screen import StubMapScreen


class OriginalOwnerTests(unittest.TestCase):
    def test_the_prewar_snapshot_wins_over_cores(self):
        prewar = {"7": "B"}
        prov = {"id": 7, "owner": "A", "cores": ["A"]}
        self.assertEqual(war_score.original_owner(prov, prewar), "B")

    def test_cores_answer_when_there_is_no_snapshot(self):
        prov = {"id": 7, "owner": "A", "cores": ["B"]}
        self.assertEqual(war_score.original_owner(prov, {}), "B")

    def test_a_province_with_neither_is_owned_by_whoever_holds_it(self):
        prov = {"id": 7, "owner": "A", "cores": []}
        self.assertEqual(war_score.original_owner(prov, {}), "A")

    def test_the_index_merges_every_factions_snapshot(self):
        nation_data = {"FACTION_WAR_MAPS": {"Entente": {"1": "A"}, "Alliance": {"2": "G"}}}
        self.assertEqual(war_score.prewar_index(nation_data), {"1": "A", "2": "G"})

    def test_a_map_with_no_faction_wars_has_an_empty_index(self):
        self.assertEqual(war_score.prewar_index({}), {})


class OccupationTests(unittest.TestCase):
    def setUp(self):
        self.game = StubMapScreen(["A", "B"])
        self.game.set_war("A", "B")
        # Four provinces of B's homeland beyond the one it starts with
        self.theirs = [self.game.add_province("B", cores=["B"]) for _ in range(4)]

    def test_nobody_holds_anything_at_the_start(self):
        self.assertEqual(war_score.occupation(self.game, ["A"], ["B"]), (0.0, 0.0))

    def test_taking_their_land_registers_as_occupation(self):
        self.theirs[0]["owner"] = "A"
        occ_a, occ_b = war_score.occupation(self.game, ["A"], ["B"])
        self.assertGreater(occ_a, 0.0)
        self.assertEqual(occ_b, 0.0)

    def test_occupation_rises_with_every_province_taken(self):
        readings = []
        for prov in self.theirs:
            prov["owner"] = "A"
            readings.append(war_score.occupation(self.game, ["A"], ["B"])[0])

        self.assertEqual(readings, sorted(readings))
        self.assertLess(readings[0], readings[-1])

    def test_holding_all_of_it_is_total(self):
        for prov in self.game.map_data.values():
            prov["owner"] = "A"
        self.assertAlmostEqual(war_score.occupation(self.game, ["A"], ["B"])[0], 1.0)

    def test_an_industrial_province_counts_for_more_than_an_empty_one(self):
        empty = self.theirs[0]
        rich = self.theirs[1]
        rich["buildings"] = ["Basic Factory", "Basic Factory"]

        empty["owner"] = "A"
        taking_the_empty_one = war_score.occupation(self.game, ["A"], ["B"])[0]
        empty["owner"] = "B"
        rich["owner"] = "A"
        taking_the_rich_one = war_score.occupation(self.game, ["A"], ["B"])[0]

        self.assertGreater(taking_the_rich_one, taking_the_empty_one)

    def test_the_prewar_snapshot_decides_whose_land_it_was(self):
        """Land B took from A before this reading is still A's homeland, so
        A recovering it is not counted as A occupying B."""
        contested = self.theirs[0]
        contested["owner"] = "A"
        self.game.nation_data["FACTION_WAR_MAPS"] = {"X": {str(contested["id"]): "A"}}

        occ_a, _ = war_score.occupation(self.game, ["A"], ["B"])
        self.assertEqual(occ_a, 0.0)


class LeverageTests(unittest.TestCase):
    def setUp(self):
        self.game = StubMapScreen(["A", "B"])
        self.game.set_war("A", "B")
        self.theirs = [self.game.add_province("B", cores=["B"]) for _ in range(4)]

    def test_the_two_scores_always_sum_to_one(self):
        scores = war_score.leverage(self.game, ["A"], ["B"])
        self.assertAlmostEqual(scores["a"] + scores["b"], 1.0)

    def test_an_even_war_is_even(self):
        scores = war_score.leverage(self.game, ["A"], ["B"])
        self.assertAlmostEqual(scores["a"], 0.5)

    def test_occupying_their_land_moves_the_bar(self):
        before = war_score.leverage(self.game, ["A"], ["B"])["a"]
        for prov in self.theirs:
            prov["owner"] = "A"
        after = war_score.leverage(self.game, ["A"], ["B"])["a"]

        self.assertGreater(after, before)
        self.assertGreater(after, 0.5)

    def test_leverage_is_symmetric(self):
        self.theirs[0]["owner"] = "A"
        forward = war_score.leverage(self.game, ["A"], ["B"])
        backward = war_score.leverage(self.game, ["B"], ["A"])

        self.assertAlmostEqual(forward["a"], backward["b"])
        self.assertAlmostEqual(forward["b"], backward["a"])

    def test_a_long_war_alone_gives_nobody_the_upper_hand(self):
        """The calendar is not a war aim.

        Weariness used to be a third of the hand: forty turns of stalemate handed
        A the advantage over B without a shot being fired, purely because B's
        counter had run up. The mechanic is gone, so a long war and a short one
        with the same front line read the same.
        """
        before = war_score.leverage(self.game, ["A"], ["B"])["a"]
        self.game.nation_data["B"]["war_durations"] = {"A": 40}
        self.game.nation_data["A"]["war_durations"] = {"B": 40}
        self.assertEqual(war_score.leverage(self.game, ["A"], ["B"])["a"], before)

    def test_the_breakdown_names_both_components(self):
        parts = war_score.leverage(self.game, ["A"], ["B"])["parts"]["a"]
        self.assertEqual(set(parts), {"occupation", "strength"})

    def test_the_summary_line_is_printable(self):
        parts = war_score.leverage(self.game, ["A"], ["B"])["parts"]["a"]
        line = war_score.summary_line(parts)
        self.assertIn("occupation", line)
        self.assertIn("%", line)


class BlocLeverageTests(unittest.TestCase):
    def setUp(self):
        self.game = StubMapScreen(["A", "S", "G"], human_players=("A",))
        self.game.set_faction("Entente", "A", "S")
        self.game.set_war("A", "G")
        self.game.set_war("S", "G")

    def test_between_resolves_the_blocs_itself(self):
        reading = war_score.between(self.game, "A", "G")
        mine, theirs = reading["sides"]

        self.assertEqual(sorted(mine), ["A", "S"])
        self.assertEqual(theirs, ["G"])
        self.assertAlmostEqual(reading["mine"] + reading["theirs"], 1.0)

    def test_two_against_one_favours_the_two(self):
        self.assertGreater(war_score.between(self.game, "A", "G")["mine"], 0.5)

    def test_the_lone_side_sees_the_mirror_image(self):
        ours = war_score.between(self.game, "A", "G")
        theirs = war_score.between(self.game, "G", "A")
        self.assertAlmostEqual(ours["mine"], theirs["theirs"])


if __name__ == "__main__":
    unittest.main()
