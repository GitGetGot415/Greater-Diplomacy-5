"""A verdict has two audiences and used to have one voice.

`verdict.reason` is a nation's own words about its own position, which is right
where it goes: ai_evaluation feeds it to the model as that leader's private
reasoning, in the first person, about itself.

The builder screen printed the same string verbatim to the player. So under a
leverage bar reading "You 41%   Them 59%" sat the sentence "we are winning this
war; 59% of the leverage is ours", and the player read "we" as themselves and
concluded the screen was contradicting itself. It was not -- 59% was the AI's
share on both lines -- but nothing on screen said so.

Same fault, second report: demanding territory produced "you hold 7% of our land
and are asking for 36% of our country" shown to the side doing the demanding.

So the reason is a template now, said one way to its author and the other way
about them, and the numbers in it are formatted before either voice sees them.
"""

import os
import re
import sys
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from map_logic.ai import ai_opinion, ai_world
from map_logic.diplomacy import deal as deal_mod, war_actions
from tests.stub_map_screen import StubMapScreen


class Fixture(unittest.TestCase):
    def setUp(self):
        self.game = StubMapScreen(["A", "B"])
        self.mine = [self.game.add_province("A", cores=["A"]) for _ in range(6)]
        self.theirs = [self.game.add_province("B", cores=["B"]) for _ in range(6)]
        for nation in ("A", "B"):
            war_actions.save_own_pre_war_map(self.game.map_data, self.game.nation_data, nation)
        self.game.set_war("A", "B")
        self.at_war_for(20)
        self.world = ai_world.for_screen(self.game)

    def at_war_for(self, turns):
        self.game.nation_data["A"]["war_durations"] = {"B": turns}
        self.game.nation_data["B"]["war_durations"] = {"A": turns}

    def _take(self, provinces, taker, count):
        for prov in provinces[:count]:
            prov["owner"] = taker
            prov["units"] = [{"owner": taker, "size": 100}]
        self.world = ai_world.for_screen(self.game)

    def overrun(self, count):
        """A, the side proposing, takes `count` of B's provinces."""
        self._take(self.theirs, "A", count)

    def overrun_by_them(self, count):
        """B, the side answering, takes `count` of A's -- so B is winning."""
        self._take(self.mine, "B", count)

    def verdict(self, *clauses):
        agreement = deal_mod.new(deal_mod.KIND_PEACE, ["A"], ["B"],
                                 [deal_mod.white_peace()] + list(clauses))
        return ai_opinion.peace_verdict(self.world, "B", "A", agreement)

    def demand(self, count):
        return self.verdict(deal_mod.tiles_clause(
            "B", "A", [prov["id"] for prov in self.theirs[:count]]))


class VoiceTests(Fixture):
    def test_the_nations_own_reason_speaks_in_the_first_person(self):
        self.overrun(1)
        self.assertRegex(self.demand(2).reason, r"\b(we|our|us|ours)\b")

    def test_the_same_reason_told_to_somebody_else_speaks_in_the_third(self):
        self.overrun(1)
        told = ai_opinion.reason_about(self.demand(2))
        self.assertNotRegex(told, r"\bour\b")
        self.assertRegex(told, r"\b(they|their|them|theirs)\b")

    def test_a_demand_is_described_to_the_side_making_it(self):
        """"you hold 7% of THEIR land and are asking for 36% of THEIR country"
        -- the sentence the player sees, about the nation refusing."""
        self.overrun(1)
        told = ai_opinion.reason_about(self.demand(5))
        self.assertIn("their", told)
        self.assertNotIn("our", told)

    def test_no_placeholder_survives_into_either_voice(self):
        """A template that reaches the screen unrendered prints as `{our}`."""
        self.overrun(2)
        for verdict in (self.verdict(), self.demand(1), self.demand(6)):
            for text in (verdict.reason, ai_opinion.reason_about(verdict)):
                with self.subTest(text=text):
                    self.assertNotIn("{", text)
                    self.assertNotIn("}", text)

    def test_both_voices_report_the_same_figures(self):
        """Only the pronouns differ. Every number is formatted in before either
        voice is chosen, which is what stops the two drifting."""
        self.overrun(3)
        verdict = self.demand(6)
        numbers = re.compile(r"\d+%")
        self.assertEqual(numbers.findall(verdict.reason),
                         numbers.findall(ai_opinion.reason_about(verdict)))

    def test_a_trade_verdict_is_translated_too(self):
        agreement = deal_mod.new(deal_mod.KIND_TRADE, ["A"], ["B"], [
            deal_mod.resources_clause("B", "A", "materials", 500)])
        verdict = ai_opinion.trade_verdict(self.world, "B", "A", agreement)
        self.assertNotIn("{", ai_opinion.reason_about(verdict))
        self.assertNotIn(" our ", f" {ai_opinion.reason_about(verdict)} ")


class AgreementTests(Fixture):
    """The bar and the sentence must not name different shares for one side."""

    def test_the_share_the_sentence_quotes_is_the_share_the_bar_draws(self):
        """The exact contradiction reported: bar 41/59, sentence 59, and no way
        to tell that both meant the same side."""
        from map_logic.diplomacy import war_score

        self.overrun_by_them(5)          # B is winning, so it says so
        verdict = self.verdict()
        self.assertIn("winning", verdict.reason, "wrong branch for this test")

        # What the builder's bar draws: "You <a>%   Them <b>%", from the player's
        # side. The sentence is about B, whose share is the bar's "Them".
        bar = war_score.leverage(self.game, ["A"], ["B"], self.world)
        theirs = int(round(bar["b"] * 100))
        told = ai_opinion.reason_about(verdict)

        self.assertIn(f"{theirs}%", verdict.reason,
                      "the AI's own words quote a share the bar does not draw")
        self.assertIn(f"{theirs}%", told)
        self.assertIn("theirs", told,
                      "the player must be told whose share that is")


class CompatibilityTests(unittest.TestCase):
    def test_a_verdict_built_the_old_way_still_works(self):
        """`detail` is new and optional, so a mod or an older test that builds a
        three-field Peace gets its plain reason back rather than a crash."""
        verdict = ai_opinion.Peace(True, 0.5, "we are content")
        self.assertEqual(ai_opinion.reason_about(verdict), "we are content")


if __name__ == "__main__":
    unittest.main()
