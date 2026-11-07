"""A country never answers its own unilateral action.

A leadership claim, leaving a faction, and disbanding one are aimed at the
sender itself. Each sits at turns=1 for a turn after it executes, and the reply
pass used to treat that like an offer from the sender to the sender: in
saves/same peace deals, Turkey claimed the leadership of its pact and the next
turn wrote "No. Our answer is no." to itself.
"""

import unittest

from map_logic.diplomacy import diplomacy_processor
from tests.stub_map_screen import StubMapScreen


class SelfAimedActionTests(unittest.TestCase):
    def setUp(self):
        self.game = StubMapScreen(["TUR", "ROM", "EST"], human_players=())
        self.game.set_faction("The Pact", "ROM", "TUR", "EST")

    def queue_self_action(self, action):
        info = {"action": action, "turns": 1}
        self.game.nation_data["TUR"]["pending_diplomacy"]["TUR"] = info
        return info

    def tasks(self):
        return [(task["sender"], task["target"], task["action"])
                for task in diplomacy_processor._gather_ai_tasks(self.game)]

    def test_a_leadership_claim_asks_nobody_to_answer_it(self):
        self.queue_self_action("CLAIM_FACTION_LEADERSHIP")
        self.assertNotIn(("TUR", "TUR", "CLAIM_FACTION_LEADERSHIP"), self.tasks())

    def test_leaving_still_lets_the_other_members_react(self):
        self.queue_self_action("LEAVE_FACTION")
        tasks = self.tasks()
        self.assertNotIn(("TUR", "TUR", "LEAVE_FACTION"), tasks)
        for member in ("ROM", "EST"):
            self.assertIn(("TUR", member, "LEAVE_FACTION"), tasks)

    def test_the_claimant_sends_itself_no_reply(self):
        info = self.queue_self_action("CLAIM_FACTION_LEADERSHIP")
        # Even if a reply were somehow on record, it would not be sent to itself.
        results = {("TUR", "TUR", "CLAIM_FACTION_LEADERSHIP"): {"message": "No. Our answer is no."}}
        diplomacy_processor._resolve_unilateral_replies(
            self.game, results, ["EST", "ROM", "TUR"], [], "TUR", "TUR",
            "CLAIM_FACTION_LEADERSHIP", info)
        inbox = self.game.nation_data["TUR"].get("inbox", [])
        self.assertFalse([msg for msg in inbox if msg.get("sender") in ("TUR", "To: TUR")])


if __name__ == "__main__":
    unittest.main()
