"""Pins the rules for an accepted diplomatic proposal.

diplomacy_processor used to implement this switch twice -- once for a proposal
a player accepted, once for one an AI accepted -- and the copies had drifted.
These tests assert the surviving implementation behaves identically whichever
side accepted, and cover the three divergences that were fixed rather than
preserved.
"""

import unittest

from tests.stub_map_screen import StubMapScreen

from map_logic.ai import ai_prompts
from map_logic.diplomacy import treaty_effects


class TreatyEffectTests(unittest.TestCase):
    def world(self, *nations):
        return StubMapScreen(nations or ("A", "B"))

    def apply(self, host, action, proposer="A", accepter="B", params=None):
        return treaty_effects.apply_treaty_effect(host, action, proposer, accepter, params)

    # -- the fixed divergences -------------------------------------------

    def test_puppet_trade_creates_the_puppet(self):
        """Regression: the AI-accepted branch transferred the resources but
        never called assign_puppet, so an accepted puppet-trade produced no
        puppet at all."""
        host = self.world()
        self.apply(host, "TRADE", params={"puppet_state": "SENDER"})
        self.assertEqual(host.nation_data["B"]["master"], "A")
        self.assertIn("B", host.nation_data["A"]["puppets"])

    def test_puppet_trade_the_other_way_round(self):
        host = self.world()
        self.apply(host, "TRADE", params={"puppet_state": "RECEIVER"})
        self.assertEqual(host.nation_data["A"]["master"], "B")
        self.assertIn("A", host.nation_data["B"]["puppets"])

    def test_plain_trade_creates_no_puppet(self):
        host = self.world()
        self.apply(host, "TRADE", params={"give_materials": 10})
        self.assertEqual(host.nation_data["B"].get("master", ""), "")

    def test_accepting_peace_says_something(self):
        """Regression: this looked up an ACCEPT_PEACE fallback that was never
        defined, so the reply was delivered with no content."""
        host = self.world()
        host.set_war("A", "B")
        outcome = self.apply(host, "PEACE_TREATY")
        self.assertTrue(outcome.canned, "peace acceptance produced an empty message")
        self.assertIn("ACCEPT_PEACE", ai_prompts.AI_FALLBACK_RESPONSES)

    def test_military_access_says_something(self):
        host = self.world()
        outcome = self.apply(host, "REQ_MILITARY_ACCESS")
        self.assertTrue(outcome.canned)

    def test_founding_a_faction_is_always_logged(self):
        """Regression: only one of the two branches logged the global event, so
        a player-initiated faction left no trace in the event log."""
        host = self.world()
        self.apply(host, "CREATE_FACTION")
        log = host.nation_data.get("GLOBAL_EVENTS", {}).get("log", [])
        self.assertTrue(any("faction" in entry.lower() for entry in log),
                        "founding a faction logged no global event")

    # -- role symmetry ---------------------------------------------------

    def test_faction_invite_puts_the_accepter_in_the_proposers_faction(self):
        host = self.world()
        host.nation_data["A"]["faction"] = "Pact"
        host.nation_data["A"]["is_faction_leader"] = True
        self.apply(host, "FACTION_INVITE", "A", "B")
        self.assertEqual(host.nation_data["B"]["faction"], "Pact")

    def test_join_request_puts_the_proposer_in_the_accepters_faction(self):
        """The mirror image of the invite: roles swap, effect is the same."""
        host = self.world()
        host.nation_data["B"]["faction"] = "Pact"
        host.nation_data["B"]["is_faction_leader"] = True
        self.apply(host, "JOIN_FACTION_REQ", "A", "B")
        self.assertEqual(host.nation_data["A"]["faction"], "Pact")

    def test_ceasefire_ends_the_war_both_ways(self):
        host = self.world()
        host.set_war("A", "B")
        self.apply(host, "CEASEFIRE")
        self.assertNotIn("B", host.nation_data["A"]["at_war_with"])
        self.assertNotIn("A", host.nation_data["B"]["at_war_with"])

    def test_military_access_is_one_way(self):
        host = self.world()
        self.apply(host, "REQ_MILITARY_ACCESS", "A", "B")
        self.assertIn("A", host.nation_data["B"]["military_access"])
        self.assertNotIn("B", host.nation_data["A"]["military_access"])

    def test_swapping_the_roles_swaps_who_grants_access(self):
        host = self.world()
        self.apply(host, "REQ_MILITARY_ACCESS", "B", "A")
        self.assertIn("B", host.nation_data["A"]["military_access"])
        self.assertNotIn("A", host.nation_data["B"]["military_access"])

    # -- blocked agreements ----------------------------------------------

    def test_invite_is_blocked_when_the_accepter_already_has_a_faction(self):
        host = self.world()
        host.nation_data["A"]["faction"] = "Pact"
        host.nation_data["B"]["faction"] = "Other"
        outcome = self.apply(host, "FACTION_INVITE", "A", "B")
        self.assertTrue(outcome.blocked)
        self.assertEqual(host.nation_data["B"]["faction"], "Other")

    def test_create_faction_is_blocked_when_either_side_is_taken(self):
        for taken in ("A", "B"):
            with self.subTest(taken=taken):
                host = self.world()
                host.nation_data[taken]["faction"] = "Other"
                outcome = self.apply(host, "CREATE_FACTION")
                self.assertTrue(outcome.blocked)

    def test_unknown_action_does_nothing(self):
        host = self.world()
        outcome = self.apply(host, "NOT_A_REAL_ACTION")
        self.assertIsNone(outcome.blocked)
        self.assertIsNone(outcome.canned)


if __name__ == "__main__":
    unittest.main()
