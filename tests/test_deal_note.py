"""A note the player writes to go with an offer, and where it ends up.

There was nowhere to put one. The offer's `message` field was the only text that
travelled, and the deal builder fills it with a generated description of the
terms -- so writing anything of your own meant overwriting what was on the table
with what you thought about it. The prompt made the same conflation from the
other end: a trade's context read "Terms: {custom_msg}", so for trades the
"They included this official message" line was skipped entirely on the grounds
that the message *was* the terms.

Two fields now. `message` is generated and says what is being offered; `note` is
the player's own words, quoted under it in the thread and handed to the model as
their government speaking. With the model switched off nothing reads it and
nothing pretends to -- it still shows up in the recipient's inbox.
"""

import os
import sys
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from map_logic.ai import ai_prompts
from map_logic.diplomacy import diplomacy_messages
from tests.stub_map_screen import StubMapScreen

NOTE = "we need the fuel for the winter, and we will not forget the favour."


class PromptTests(unittest.TestCase):
    """What the model is shown."""

    def context(self, action, terms="you receive 400 Materials.", note=NOTE):
        return ai_prompts.get_bilateral_receive_context(action, "Avaria", terms, note)

    def test_a_trade_shows_both_the_terms_and_the_note(self):
        context = self.context("TRADE")
        self.assertIn("400 Materials", context)
        self.assertIn(NOTE, context)

    def test_a_peace_offer_shows_its_terms_rather_than_the_action_name(self):
        """It fell through to the generic branch -- "Avaria has proposed a Peace
        Treaty." -- so the model was asked to weigh terms it was never shown."""
        context = self.context("PEACE_TREATY", terms="you cede 3 provinces.")
        self.assertIn("cede 3 provinces", context)

    def test_the_terms_are_not_quoted_as_something_they_said(self):
        context = self.context("TRADE", note="")
        self.assertNotIn("official message", context)

    def test_no_note_adds_no_line(self):
        self.assertNotIn("adds:", self.context("TRADE", note=""))


class DeliveryTests(unittest.TestCase):
    """Where the note goes when the offer is actually sent."""

    def setUp(self):
        self.game = StubMapScreen(["A", "B"], human_players=("A",))

    def send(self, note):
        diplomacy_messages.set_pending(
            self.game.nation_data, "A", "B", "TRADE",
            parameters={"give_materials": 400},
            message="you receive 400 Materials.", note=note)
        self.game.run_turn()
        return self.game.inbound("B", "A")

    def test_the_recipient_sees_it_under_the_terms(self):
        received = self.send(NOTE)
        self.assertTrue(received, "nothing arrived at all")
        body = received[-1]
        self.assertIn(NOTE, body)
        self.assertLess(body.index("400"), body.index(NOTE),
                        "the terms come first; the note is a covering letter")

    def test_an_offer_without_one_reads_exactly_as_before(self):
        body = self.send("")[-1]
        self.assertNotIn('"', body)

    def test_the_sender_keeps_a_copy(self):
        self.send(NOTE)
        outgoing = [content for direction, content in self.game.thread("A", "B")
                    if direction == "out"]
        self.assertTrue(any(NOTE in body for body in outgoing))

    def test_reopening_the_offer_recovers_the_note(self):
        diplomacy_messages.set_pending(
            self.game.nation_data, "A", "B", "TRADE",
            parameters={"give_materials": 400}, message="terms", note=NOTE)
        pending = diplomacy_messages.get_pending(self.game.nation_data, "A", "B")
        self.assertEqual(pending.get("note"), NOTE)


if __name__ == "__main__":
    unittest.main()
