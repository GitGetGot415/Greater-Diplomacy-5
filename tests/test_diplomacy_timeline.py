"""Turn-by-turn tests for the diplomacy timelines described in context/diplo_stuff.txt.

The rules being pinned down:
  * a bilateral proposal is written on turn 0 and lands in the other side's
    inbox on turn 1, with an answer coming back on turn 2
  * two proposals travelling in opposite directions never overwrite each other
  * only proposals with the same outcome merge (faction invite x join request,
    call to arms x join wars) -- military access is one-way and must not
  * queued text is delivered exactly once

Run it however you like -- straight from the editor's "Run Python File in
Terminal", via run_tests.py in the repo root, or with
`python -m unittest discover -s tests -t .`.
"""

import os
import sys
import unittest

# Running this file directly puts tests/ on the path rather than the repo root,
# so put the root back before importing anything from the game.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.stub_map_screen import StubMapScreen

from map_logic.diplomacy import diplomacy_messages
import data.constants as c

ACCEPT = diplomacy_messages.RESPONSE_ACCEPT
REJECT = diplomacy_messages.RESPONSE_REJECT


class BilateralDeliveryTests(unittest.TestCase):
    """Every bilateral action must actually reach the other side's inbox."""

    def _setup_for(self, action):
        """Builds whatever world state makes `action` legal between A and B."""
        game = StubMapScreen(["A", "B"], human_players=["A"])
        if action in ("JOIN_WARS", "CALL_TO_ARMS"):
            game.set_faction("Pact", "A", "B")
            game.nation_data["A"]["at_war_with"] = ["C"]
        elif action == "FACTION_INVITE":
            game.set_faction("Pact", "A")
        elif action == "JOIN_FACTION_REQ":
            game.set_faction("Pact", "B")
        elif action in ("CEASEFIRE", "PEACE_TREATY"):
            game.set_war("A", "B")
        return game

    def test_every_bilateral_action_delivers_a_message_on_turn_1(self):
        for action in c.BILATERAL_ACTIONS:
            with self.subTest(action=action):
                game = self._setup_for(action)
                game.propose("A", "B", action, message="Our formal proposal.")

                self.assertEqual(game.inbound("B", "A"), [], "delivered before the turn was processed")

                game.run_turn()

                self.assertTrue(
                    game.inbound("B", "A"),
                    f"{action} never reached B's inbox -- the proposal is invisible",
                )
                # The sender keeps a copy in their own thread
                self.assertTrue(
                    [d for d, _ in game.thread("A", "B") if d == "out"],
                    f"{action} left no sent copy in A's own thread",
                )

    def test_join_faction_req_full_timeline(self):
        """The worked example from diplo_stuff.txt, start to finish."""
        game = StubMapScreen(["A", "B"], human_players=["A", "B"])
        game.set_faction("Pact", "B")

        # turn 0: A writes the request
        game.propose("A", "B", "JOIN_FACTION_REQ", message="Let us join you.")
        self.assertEqual(game.pending_action("A", "B"), "JOIN_FACTION_REQ")

        # turn 1: B receives it and answers
        game.run_turn()
        self.assertEqual(game.inbound("B", "A"), ["Let us join you."])
        self.assertEqual(game.pending("A", "B").get("turns"), 1)
        game.answer("B", "A", ACCEPT, "JOIN_FACTION_REQ", message="Welcome, friend.")

        # turn 2: A receives the acceptance and is in the faction
        game.run_turn()
        self.assertIn("Welcome, friend.", game.inbound("A", "B"))
        self.assertEqual(game.nation_data["A"]["faction"], "Pact")
        self.assertEqual(game.pending_action("A", "B"), "", "the answered request should be cleared")

    def test_faction_leader_can_accept_a_join_request(self):
        """Someone joining OUR faction needs us to have one -- it is not a blocker."""
        game = StubMapScreen(["A", "B"], human_players=["A"])
        game.set_faction("Pact", "A")

        game.propose("B", "A", "JOIN_FACTION_REQ", message="We ask to join.")
        game.run_turn()

        # Go through the real button handler so its eligibility checks are exercised
        from map_logic.diplomacy import player_diplomacy_actions
        player_diplomacy_actions.handle_accept_req(game, "B", "Granted.")

        verdict, action = diplomacy_messages.get_response_status(game.nation_data, "A", "B")
        self.assertEqual((verdict, action), (ACCEPT, "JOIN_FACTION_REQ"),
                         f"acceptance was refused: {game.feedback}")

        game.run_turn()
        self.assertEqual(game.nation_data["B"]["faction"], "Pact")


class SimultaneousRequestTests(unittest.TestCase):
    """Two proposals crossing in the post must both survive."""

    TRADE_TERMS = {"give_materials": 100, "give_fuel": 0,
                   "take_materials": 0, "take_fuel": 0, "puppet_state": "NONE"}

    def test_opposite_requests_both_resolve(self):
        """The worked example from diplo_stuff.txt: a trade crossing an access request."""
        game = StubMapScreen(["A", "B"], human_players=["A", "B"])

        # turn 0: A offers a trade; B asks A for military access
        game.propose("A", "B", "TRADE", message="A trade offer.", parameters=self.TRADE_TERMS)
        game.propose("B", "A", "REQ_MILITARY_ACCESS", message="Grant us passage.")

        game.run_turn()

        # turn 1: both arrived, neither clobbered the other
        self.assertEqual(game.inbound("B", "A"), ["A trade offer."])
        self.assertEqual(game.inbound("A", "B"), ["Grant us passage."])

        # Each side answers the other's proposal
        game.answer("A", "B", ACCEPT, "REQ_MILITARY_ACCESS", message="Passage granted.")
        game.answer("B", "A", ACCEPT, "TRADE", message="Deal.")

        before = game.nation_data["B"]["materials"]
        game.run_turn()

        # turn 2: both agreements executed
        self.assertIn("B", game.nation_data["A"]["military_access"])
        self.assertEqual(game.nation_data["B"]["materials"], before + 100,
                         "the trade terms should have come from the proposer's offer")

    def test_answering_does_not_destroy_our_own_outgoing_proposal(self):
        """The reported bug: accepting their request wiped our pending request."""
        game = StubMapScreen(["A", "B"], human_players=["A"])
        game.set_faction("Pact", "B")

        # A's request is already in transit
        game.propose("A", "B", "JOIN_FACTION_REQ", message="Let us join you.")
        game.run_turn()
        self.assertEqual(game.pending("A", "B").get("turns"), 1)

        # B asks for military access; A answers it
        game.propose("B", "A", "REQ_MILITARY_ACCESS", message="Grant us passage.")
        game.answer("A", "B", ACCEPT, "REQ_MILITARY_ACCESS", message="Passage granted.")

        self.assertEqual(game.pending_action("A", "B"), "JOIN_FACTION_REQ",
                         "answering B overwrote A's own outgoing proposal")

    def test_military_access_is_one_way(self):
        """Mutual requests are NOT the same outcome -- each grant stands alone."""
        game = StubMapScreen(["A", "B"], human_players=["A", "B"])

        game.propose("A", "B", "REQ_MILITARY_ACCESS", message="Let us through.")
        game.propose("B", "A", "REQ_MILITARY_ACCESS", message="And us through you.")
        game.run_turn()

        # Only B grants access; A refuses
        game.answer("B", "A", ACCEPT, "REQ_MILITARY_ACCESS")
        game.answer("A", "B", REJECT, "REQ_MILITARY_ACCESS")
        game.run_turn()

        self.assertIn("A", game.nation_data["B"]["military_access"],
                      "B agreed to let A through and should have")
        self.assertNotIn("B", game.nation_data["A"]["military_access"],
                         "A refused, so B must not have gained access")


class SameOutcomeMergeTests(unittest.TestCase):
    """Requests that would produce an identical result still collapse into one."""

    def test_faction_invite_and_join_request_merge(self):
        game = StubMapScreen(["A", "B"], human_players=["A", "B"])
        game.set_faction("Pact", "B")

        game.propose("A", "B", "JOIN_FACTION_REQ", message="Let us join you.")
        game.propose("B", "A", "FACTION_INVITE", message="Come join us.")
        game.run_turn()

        self.assertEqual(game.nation_data["A"]["faction"], "Pact")
        self.assertEqual(game.pending_action("A", "B"), "")
        self.assertEqual(game.pending_action("B", "A"), "")

    def test_call_to_arms_and_join_wars_merge(self):
        game = StubMapScreen(["A", "B", "C"], human_players=["A", "B"])
        game.set_faction("Pact", "A", "B")
        game.set_war("A", "C")

        game.propose("A", "B", "CALL_TO_ARMS", message="Aid us!")
        game.propose("B", "A", "JOIN_WARS", message="We join your fight!")
        game.run_turn()

        self.assertIn("C", game.nation_data["B"]["at_war_with"],
                      "the merged call to arms should have pulled B into A's war")


class RejectionAndCooldownTests(unittest.TestCase):
    def test_rejection_starts_the_cooldown(self):
        """The AI should keep asking until it is actually told no."""
        game = StubMapScreen(["A", "B"], human_players=["A"])
        game.set_faction("Pact", "A")

        game.propose("B", "A", "JOIN_FACTION_REQ", message="We ask to join.")
        game.run_turn()

        cooldowns = game.nation_data["B"].get("diplo_cooldowns", {}).get("A", {})
        self.assertEqual(cooldowns.get("JOIN_FACTION_REQ", 0), 0,
                         "a request in transit must not be on cooldown yet")

        game.answer("A", "B", REJECT, "JOIN_FACTION_REQ", message="No.")
        game.run_turn()

        cooldowns = game.nation_data["B"].get("diplo_cooldowns", {}).get("A", {})
        self.assertGreater(cooldowns.get("JOIN_FACTION_REQ", 0), 0,
                           "being turned down should start the cooldown")

    def test_ignoring_a_proposal_auto_declines_it(self):
        game = StubMapScreen(["A", "B"], human_players=["A"])
        game.set_faction("Pact", "A")

        game.propose("B", "A", "JOIN_FACTION_REQ", message="We ask to join.")
        game.run_turn()   # delivered
        game.run_turn()   # A never answered

        self.assertIn("Your proposal was ignored and automatically declined.",
                      game.inbound("B", "A"))
        self.assertEqual(game.pending_action("B", "A"), "")

    def test_undo_clears_a_queued_answer(self):
        game = StubMapScreen(["A", "B"], human_players=["A"])
        game.set_faction("Pact", "A")

        game.propose("B", "A", "JOIN_FACTION_REQ", message="We ask to join.")
        game.run_turn()

        game.answer("A", "B", ACCEPT, "JOIN_FACTION_REQ")
        self.assertEqual(diplomacy_messages.get_response_status(game.nation_data, "A", "B")[0], ACCEPT)

        game.answer("A", "B", ACCEPT, "JOIN_FACTION_REQ")  # click again = undo
        self.assertEqual(diplomacy_messages.get_response_status(game.nation_data, "A", "B"), ("", ""))


class TextMessageTests(unittest.TestCase):
    def test_queued_text_is_delivered_exactly_once(self):
        """save_current_draft writes both a MSG: action and a draft_lists entry."""
        game = StubMapScreen(["A", "B"], human_players=["A"])

        game.nation_data["A"]["pending_diplomacy"]["B"] = {
            "action": "MSG:Hello there.", "turns": 0, "message": "Hello there."}
        game.nation_data["A"]["draft_lists"]["B"] = ["Hello there."]

        game.run_turn()

        self.assertEqual(game.inbound("B", "A"), ["Hello there."])

    def test_text_alongside_a_formal_action_still_arrives(self):
        game = StubMapScreen(["A", "B"], human_players=["A"])
        game.set_faction("Pact", "B")

        game.nation_data["A"]["pending_diplomacy"]["B"] = {
            "action": "JOIN_FACTION_REQ", "turns": 0, "message": "Let us join you."}
        game.nation_data["A"]["draft_lists"]["B"] = ["Also, greetings."]

        game.run_turn()

        self.assertEqual(sorted(game.inbound("B", "A")),
                         sorted(["Let us join you.", "Also, greetings."]))


class ProactiveAITests(unittest.TestCase):
    """The AI should reliably get its requests out every turn."""

    @staticmethod
    def run_proactive(game):
        """The full proactive sequence.

        It is two passes now: the first works out each nation's legal options
        and scores them, the second lets the leader choose from that menu and
        queues the result. With the model off the second is pure bookkeeping,
        but nothing is queued until it runs, so a caller that only invokes the
        first sees no diplomacy at all.
        """
        from map_logic.ai import ai_diplomacy
        ai_diplomacy.process_basic_proactive_ai(game)
        ai_diplomacy.process_proactive_llm_tasks(game)

    def test_call_to_arms_survives_the_rest_of_the_pass(self):
        """Section 3's Join Wars used to overwrite section 2's Call to Arms."""
        # A and B are allies with different wars, so both sections want the same slot
        game = StubMapScreen(["A", "B", "X", "Y"], human_players=["B"])
        game.set_faction("Pact", "A", "B")
        game.set_war("A", "X")
        game.set_war("B", "Y")

        self.run_proactive(game)

        self.assertEqual(game.pending_action("A", "B"), "CALL_TO_ARMS",
                         "A's call to arms was overwritten before it could be sent")

    def test_a_faction_request_does_not_abort_the_rest_of_the_ai(self):
        """A stray break used to skip every AI processed after the requester."""
        # A leads a faction and fights X. C and Z are unfactioned and fight X too,
        # so C asks to join A -- and Z, processed after C, must still get its turn.
        game = StubMapScreen(["A", "C", "X", "Z"], human_players=["A"])
        game.set_faction("Pact", "A")
        game.set_war("A", "X")
        game.set_war("C", "X")
        game.set_war("Z", "X")

        self.run_proactive(game)

        self.assertEqual(game.pending_action("C", "A"), "JOIN_FACTION_REQ")
        self.assertTrue(game.nation_data["Z"]["pending_diplomacy"],
                        "Z was skipped entirely because C queued a faction request")

    def test_a_request_in_flight_is_not_put_on_cooldown(self):
        """Cooldowns mean 'recently told no', not 'recently asked'."""
        from map_logic.ai import ai_diplomacy

        game = StubMapScreen(["A", "B", "X", "Y"], human_players=["B"])
        game.set_faction("Pact", "A", "B")
        game.set_war("A", "X")
        game.set_war("B", "Y")

        ai_diplomacy.process_basic_proactive_ai(game)
        ai_diplomacy.process_proactive_llm_tasks(game)

        cooldowns = game.nation_data["A"].get("diplo_cooldowns", {}).get("B", {})
        self.assertEqual(cooldowns.get("CALL_TO_ARMS", 0), 0)


class UnreadBadgeTests(unittest.TestCase):
    """The map badge and the contact list must never disagree."""

    def test_incoming_request_is_both_counted_and_reachable(self):
        from data import queries

        game = StubMapScreen(["A", "B"], human_players=["A"])
        game.set_faction("Pact", "A")

        game.propose("B", "A", "JOIN_FACTION_REQ", message="We ask to join.")
        game.run_turn()

        self.assertTrue(queries.has_unanswered_request("A", "B", game.nation_data))
        self.assertIn("B", queries.get_pending_request_senders("A", game.nation_data))
        # A message the player can actually open backs the notification
        self.assertTrue(game.inbound("A", "B"))

    def test_badge_survives_nation_data_growing_mid_scan(self):
        """Badges are drawn mid-turn, while nation_data is still being added to.

        Multi-turn processing yields to the event loop between phases, so a draw
        can land while the engine is inserting keys (faction war maps, nations
        released by a peace deal). Reading a live iterator crashed there.
        """
        from data import queries

        game = StubMapScreen(["A", "B"], human_players=["A"])
        game.set_faction("Pact", "A")
        game.propose("B", "A", "JOIN_FACTION_REQ", message="We ask to join.")
        game.run_turn()

        class GrowingNationData(dict):
            """Inserts a key the first time it is read, as a live turn would."""
            def __init__(self, *args):
                super().__init__(*args)
                self.grown = False

            def get(self, key, default=None):
                if not self.grown:
                    self.grown = True
                    self["FACTION_WAR_MAPS"] = {}
                return super().get(key, default)

        live = GrowingNationData(game.nation_data)

        self.assertIn("B", queries.get_pending_request_senders("A", live))
        self.assertGreaterEqual(queries.get_unread_message_count("A", live), 1)
        self.assertGreaterEqual(queries.get_unread_message_count("Spectator", live), 1)

    def test_answering_clears_the_notification(self):
        from data import queries

        game = StubMapScreen(["A", "B"], human_players=["A"])
        game.set_faction("Pact", "A")

        game.propose("B", "A", "JOIN_FACTION_REQ", message="We ask to join.")
        game.run_turn()
        game.answer("A", "B", ACCEPT, "JOIN_FACTION_REQ")

        self.assertFalse(queries.has_unanswered_request("A", "B", game.nation_data))


if __name__ == "__main__":
    unittest.main()
