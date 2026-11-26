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
from map_logic.diplomacy import diplomacy_messages, diplomacy_processor, treaty_effects


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
        self.assertEqual(host.world.nation_data["B"]["master"], "A")
        self.assertIn("B", host.world.nation_data["A"]["puppets"])

    def test_puppet_trade_the_other_way_round(self):
        host = self.world()
        self.apply(host, "TRADE", params={"puppet_state": "RECEIVER"})
        self.assertEqual(host.world.nation_data["A"]["master"], "B")
        self.assertIn("A", host.world.nation_data["B"]["puppets"])

    def test_plain_trade_creates_no_puppet(self):
        host = self.world()
        self.apply(host, "TRADE", params={"give_materials": 10})
        self.assertEqual(host.world.nation_data["B"].get("master", ""), "")

    def test_accepting_peace_says_something(self):
        """Regression: this looked up an ACCEPT_PEACE fallback that was never
        defined, so the reply was delivered with no content."""
        host = self.world()
        host.set_war("A", "B")
        outcome = self.apply(host, "PEACE_TREATY")
        self.assertTrue(outcome.canned, "peace acceptance produced an empty message")
        self.assertIn("ACCEPT_PEACE", ai_prompts.AI_FALLBACK_RESPONSES)

    def test_a_wartime_trade_accepted_by_ai_is_blocked_and_its_escrow_returned(self):
        """Even a scripted AI acceptance cannot execute an enemy's trade."""
        host = self.world()
        host.set_war("A", "B")
        before = (int(host.world.nation_data["A"].get("materials", 0) or 0),
                  int(host.world.nation_data["B"].get("fuel", 0) or 0))
        outcome = treaty_effects.apply_treaty_effect(
            host, "TRADE", "A", "B", {"give_materials": 500, "take_fuel": 100},
            escrow={"materials": 500})
        self.assertEqual(outcome.blocked, ai_prompts.AI_FALLBACK_RESPONSES["TRADE_AT_WAR"])
        self.assertEqual(int(host.world.nation_data["A"].get("materials", 0)), before[0] + 500)
        self.assertEqual(int(host.world.nation_data["B"].get("fuel", 0) or 0), before[1])

    def test_military_access_says_something(self):
        host = StubMapScreen(("A", "B", "C"))
        host.set_war("A", "C")
        host.set_war("B", "C")
        outcome = self.apply(host, "REQ_MILITARY_ACCESS")
        self.assertTrue(outcome.canned)

    def test_founding_a_faction_is_always_logged(self):
        """Regression: only one of the two branches logged the global event, so
        a player-initiated faction left no trace in the event log."""
        host = self.world()
        self.apply(host, "CREATE_FACTION")
        log = host.world.nation_data.get("GLOBAL_EVENTS", {}).get("log", [])
        self.assertTrue(any("faction" in entry.lower() for entry in log),
                        "founding a faction logged no global event")
        self.assertFalse(any("Diplomatic agreement reached" in entry for entry in log))

    def test_trade_announcement_matches_for_queued_and_direct_ai_acceptance(self):
        for message in ("We accepted.", "The terms suit us."):
            with self.subTest(message=message):
                human = StubMapScreen(("A", "B"), human_players=("B",))
                human.propose("A", "B", "TRADE", parameters={"give_materials": 1})
                human.answer("B", "A", diplomacy_messages.RESPONSE_ACCEPT, "TRADE", message)
                diplomacy_processor._process_queued_responses(human)

                ai = self.world("A", "B")
                ai.propose("A", "B", "TRADE", parameters={"give_materials": 1})
                results = {("A", "B", "TRADE"): {"accepted": True, "message": message}}
                diplomacy_processor._resolve_ai_answer(ai, results, ["A", "B"], [], "A", "B", "TRADE", ai.pending("A", "B"))

                for host in (human, ai):
                    self.assertEqual(host.world.nation_data["GLOBAL_EVENTS"]["log"], ["Diplomatic agreement reached between B and A."])
                    self.assertEqual(host.inbound("A", "B"), [message])

    def test_peace_blocked_at_resolution_does_not_announce_an_agreement(self):
        host = self.world()
        host.set_war("A", "B")
        host.propose("A", "B", "PEACE_TREATY")
        host.answer("B", "A", diplomacy_messages.RESPONSE_ACCEPT, "PEACE_TREATY", "We accepted.")
        host.world.nation_data["A"]["at_war_with"].clear()
        host.world.nation_data["B"]["at_war_with"].clear()
        diplomacy_processor._process_queued_responses(host)

        self.assertEqual(host.inbound("A", "B"), [ai_prompts.AI_FALLBACK_RESPONSES["NO_WAR_TO_SETTLE"]])
        self.assertFalse(host.world.nation_data.get("GLOBAL_EVENTS", {}).get("log"))

    # -- role symmetry ---------------------------------------------------

    def test_faction_invite_puts_the_accepter_in_the_proposers_faction(self):
        host = self.world()
        host.world.nation_data["A"]["faction"] = "Pact"
        host.world.nation_data["A"]["is_faction_leader"] = True
        self.apply(host, "FACTION_INVITE", "A", "B")
        self.assertEqual(host.world.nation_data["B"]["faction"], "Pact")

    def test_join_request_puts_the_proposer_in_the_accepters_faction(self):
        """The mirror image of the invite: roles swap, effect is the same."""
        host = self.world()
        host.world.nation_data["B"]["faction"] = "Pact"
        host.world.nation_data["B"]["is_faction_leader"] = True
        self.apply(host, "JOIN_FACTION_REQ", "A", "B")
        self.assertEqual(host.world.nation_data["A"]["faction"], "Pact")

    def test_ceasefire_ends_the_war_both_ways(self):
        host = self.world()
        host.set_war("A", "B")
        self.apply(host, "CEASEFIRE")
        self.assertNotIn("B", host.world.nation_data["A"]["at_war_with"])
        self.assertNotIn("A", host.world.nation_data["B"]["at_war_with"])

    def test_military_access_is_one_way(self):
        host = StubMapScreen(("A", "B"), human_players=("B",))
        self.apply(host, "REQ_MILITARY_ACCESS", "A", "B")
        self.assertIn("A", host.world.nation_data["B"]["military_access"])
        self.assertNotIn("B", host.world.nation_data["A"]["military_access"])

    def test_swapping_the_roles_swaps_who_grants_access(self):
        host = StubMapScreen(("A", "B"), human_players=("A",))
        self.apply(host, "REQ_MILITARY_ACCESS", "B", "A")
        self.assertIn("B", host.world.nation_data["A"]["military_access"])
        self.assertNotIn("A", host.world.nation_data["B"]["military_access"])

    def test_a_shared_war_grant_ends_when_the_grantee_attacks_an_ally(self):
        host = StubMapScreen(("UK", "France", "Germany", "Greece"), human_players=())
        host.set_faction("Allies", "UK", "France")
        host.set_war("UK", "Greece")
        host.set_war("Germany", "Greece")
        self.assertEqual(self.apply(host, "REQ_MILITARY_ACCESS", "Germany", "UK").status, "applied")
        host.set_war("Germany", "France")
        diplomacy_processor.reconcile_ai_wartime_access(host)
        self.assertNotIn("Germany", host.world.nation_data["UK"]["military_access"])
        self.assertEqual(self.apply(host, "REQ_MILITARY_ACCESS", "Germany", "UK").status, "blocked")

    def test_a_scripted_grant_preserves_its_explicit_approval(self):
        host = StubMapScreen(("UK", "France", "Germany"), human_players=())
        host.set_faction("Allies", "UK", "France")
        host.set_war("Germany", "France")
        outcome = treaty_effects.apply_treaty_effect(host, "REQ_MILITARY_ACCESS", "Germany", "UK", scripted=True)
        diplomacy_processor.reconcile_ai_wartime_access(host)
        self.assertEqual(outcome.status, "applied")
        self.assertIn("Germany", host.world.nation_data["UK"]["military_access"])

    def test_ai_leaves_a_settled_war_alone_until_a_fresh_attack(self):
        from map_logic.system32.time_handler import TimeHandler

        host = StubMapScreen(("AI", "Ally", "Enemy"), human_players=("Ally",))
        host.world.time_manager = TimeHandler()
        host.set_faction("Pact", "Ally", "AI")
        host.set_war("Ally", "Enemy")
        data = host.world.nation_data
        data["AI"]["temp_modifiers"] = {"Enemy": {"recent_war": -5}}
        self.assertEqual(self.apply(host, "CALL_TO_ARMS", "Ally", "AI").status, "blocked")

        diplomacy_processor.send_message(host, "Enemy", "Ally", "Declaration of war",
                                          "DIPLOMACY", extra={"action": "WAR_DECLARATION"})
        self.assertEqual(self.apply(host, "CALL_TO_ARMS", "Ally", "AI").status, "applied")
        self.assertIn("Enemy", data["AI"]["at_war_with"])

    def test_a_subject_joins_through_its_overlord(self):
        from map_logic.diplomacy.puppet_actions import assign_puppet

        host = StubMapScreen(("Master", "Subject", "Ally", "Enemy"), human_players=("Master", "Ally"))
        host.set_faction("Pact", "Master", "Ally")
        data = host.world.nation_data
        assign_puppet(host.world.map_data, data, "Master", "Subject")
        host.set_war("Ally", "Enemy")

        self.assertEqual(self.apply(host, "CALL_TO_ARMS", "Ally", "Subject").status, "blocked")
        self.assertEqual(self.apply(host, "CALL_TO_ARMS", "Ally", "Master").status, "applied")
        self.assertIn("Enemy", data["Subject"]["at_war_with"])

    # -- blocked agreements ----------------------------------------------

    def test_invite_is_blocked_when_the_accepter_already_has_a_faction(self):
        host = self.world()
        host.world.nation_data["A"]["faction"] = "Pact"
        host.world.nation_data["B"]["faction"] = "Other"
        outcome = self.apply(host, "FACTION_INVITE", "A", "B")
        self.assertTrue(outcome.blocked)
        self.assertEqual(host.world.nation_data["B"]["faction"], "Other")

    def test_create_faction_is_blocked_when_either_side_is_taken(self):
        for taken in ("A", "B"):
            with self.subTest(taken=taken):
                host = self.world()
                host.world.nation_data[taken]["faction"] = "Other"
                outcome = self.apply(host, "CREATE_FACTION")
                self.assertTrue(outcome.blocked)

    def test_unknown_action_does_nothing(self):
        host = self.world()
        outcome = self.apply(host, "NOT_A_REAL_ACTION")
        self.assertIsNone(outcome.blocked)
        self.assertIsNone(outcome.canned)

    def test_accepting_a_trade_that_eliminates_the_proposer_clears_response_once(self):
        """Regression: landless cleanup removes the response while its own
        processor is still settling it, so the normal final delete must be
        harmless."""
        host = StubMapScreen(("Bulgaria", "Ottoman Empire"), human_players=())
        bulgaria_province = host.home_of("Bulgaria")
        host.border(bulgaria_province["id"], host.home_of("Ottoman Empire")["id"])
        terms = {
            "v": 1,
            "kind": "TRADE",
            "sides": {"a": ["Bulgaria"], "b": ["Ottoman Empire"]},
            "clauses": [{"type": "TILES", "from": "Bulgaria",
                         "to": "Ottoman Empire", "ids": [bulgaria_province["id"]]}],
        }
        host.world.nation_data["Bulgaria"]["pending_diplomacy"]["Ottoman Empire"] = {
            "action": "TRADE", "parameters": terms}
        host.world.nation_data["Ottoman Empire"]["diplo_responses"]["Bulgaria"] = {
            "verdict": "ACCEPT", "action": "TRADE", "parameters": terms}

        diplomacy_processor._process_queued_responses(host)

        self.assertEqual(bulgaria_province["owner"], "Ottoman Empire")
        self.assertEqual(host.world.nation_data["Ottoman Empire"]["diplo_responses"], {})
        self.assertEqual(host.world.nation_data["Bulgaria"]["pending_diplomacy"], {})


if __name__ == "__main__":
    unittest.main()
