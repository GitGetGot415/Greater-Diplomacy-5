"""Scripted-event coverage for the expanded diplomacy actions."""

import unittest

from tests.stub_map_screen import StubMapScreen
from map_logic.ai.ai_diplomacy import process_scripted_events
from map_logic.diplomacy import diplomacy_messages, guarantees, military_attaches, volunteers


def event(action, target, message="", conditions=None, **action_fields):
    action_data = {"type": action, "target": target, "message": message}
    action_data.update(action_fields)
    return {
        "conditions": conditions or [{"type": "True", "operator": "==", "value": "", "chain": "AND"}],
        "actions": [action_data],
        "fire_once": True,
        "trigger_type": "Both",
    }


def division(owner):
    return {"owner": owner, "type": "Infantry Type 1910", "health": 100,
            "max_health": 100, "attack": 10, "defense": 10, "speed": 1,
            "order": {"type": "MOVE", "path": []}}


class ScriptedDiplomacyActionTests(unittest.TestCase):
    def setUp(self):
        self.game = StubMapScreen(["A", "B", "C", "D"], human_players=("A", "B"))

    def test_guarantee_and_access_requests_are_queued_through_normal_diplomacy(self):
        self.game.nation_data["A"]["scripted_events"] = [
            event("Guarantee Independence", "B"),
            event("Request Military Access", "C"),
        ]

        process_scripted_events(self.game)

        self.assertEqual(self.game.pending_action("A", "B"), guarantees.ACTION)
        self.assertEqual(self.game.pending_action("A", "C"), "REQ_MILITARY_ACCESS")
        self.game.run_turn()
        self.assertIn("B", guarantees.guaranteed_targets("A", self.game.nation_data))

    def test_specific_accept_action_only_answers_its_matching_request(self):
        self.game.set_war("B", "C")
        self.game.propose("A", "B", military_attaches.ACTION)
        self.game.run_turn()  # The request arrives at B.
        self.game.nation_data["B"]["scripted_events"] = [event("Accept Military Attaché", "A")]

        process_scripted_events(self.game)

        verdict, action = diplomacy_messages.get_response_status(self.game.nation_data, "B", "A")
        self.assertEqual((verdict, action), (diplomacy_messages.RESPONSE_ACCEPT,
                                             military_attaches.ACTION))

    def test_scripted_volunteer_offer_reserves_requested_divisions(self):
        self.game.set_war("B", "C")
        home = self.game.home_of("A")
        home["units"] = [division("A") for _ in range(10)]
        self.game.border(home["id"], self.game.home_of("B")["id"])
        self.game.nation_data["A"]["scripted_events"] = [
            event("Offer Volunteer Divisions", "B", "1")]

        process_scripted_events(self.game)

        self.assertEqual(self.game.pending_action("A", "B"), volunteers.ACTION)
        self.assertEqual(len(home["units"]), 9)
        self.assertEqual(volunteers.mission_state(self.game.nation_data, "A", "B"),
                         volunteers.AWAITING)

    def test_volunteer_offer_can_use_the_remaining_capacity_when_enabled(self):
        self.game.set_war("B", "C")
        home = self.game.home_of("A")
        home["units"] = [division("A") for _ in range(10)]  # Cap is one.
        self.game.border(home["id"], self.game.home_of("B")["id"])
        self.game.nation_data["A"]["scripted_events"] = [
            event("Offer Volunteer Divisions", "B", "5", send_up_to=True)]

        process_scripted_events(self.game)

        self.assertEqual(self.game.pending_action("A", "B"), volunteers.ACTION)
        self.assertEqual(len(home["units"]), 9)

    def test_new_diplomacy_conditions_cover_relationships_and_volunteer_counts(self):
        self.game.set_war("B", "C")
        home = self.game.home_of("A")
        home["units"] = [division("A") for _ in range(10)]
        self.game.nation_data["A"]["volunteer_missions"] = {
            "D": {"state": volunteers.AWAITING,
                  "held_units": [{"unit": division("A"), "origin_id": home["id"]}]}}
        self.assertTrue(guarantees.grant("A", "D", self.game.nation_data)[0])
        self.assertTrue(military_attaches.send("A", "B", self.game.nation_data)[0])
        self.game.nation_data["C"]["military_access"] = ["A"]
        self.game.nation_data["A"]["military_access"] = ["B"]
        conditions = [
            {"type": "Guaranteeing", "operator": "==", "value": "D", "chain": "AND"},
            {"type": "Not Guaranteeing", "operator": "==", "value": "C", "chain": "AND"},
            {"type": "Has Military Attaché", "operator": "==", "value": "B", "chain": "AND"},
            {"type": "Doesn't Have Military Attaché", "operator": "==", "value": "C", "chain": "AND"},
            {"type": "Has Military Access Through", "operator": "==", "value": "C", "chain": "AND"},
            {"type": "Doesn't Have Military Access Through", "operator": "==", "value": "B", "chain": "AND"},
            {"type": "Grants Military Access To", "operator": "==", "value": "B", "chain": "AND"},
            {"type": "Doesn't Grant Military Access To", "operator": "==", "value": "C", "chain": "AND"},
            {"type": "Volunteer Divisions Sent", "operator": "==", "value": "1", "chain": "AND"},
            {"type": "Volunteer Capacity Remaining", "operator": "==", "value": "1", "chain": "AND"},
        ]
        self.game.nation_data["A"]["scripted_events"] = [
            event("Send Custom Message", "D", "All checks passed.", conditions)]

        process_scripted_events(self.game)

        self.assertEqual(self.game.pending_action("A", "D"), "MSG:All checks passed.")

    def test_specific_volunteer_acceptance_answers_an_arrived_offer(self):
        self.game.set_war("B", "C")
        home = self.game.home_of("A")
        home["units"] = [division("A") for _ in range(10)]
        self.game.border(home["id"], self.game.home_of("B")["id"])
        self.game.nation_data["A"]["scripted_events"] = [
            event("Offer Volunteer Divisions", "B", "1")]
        process_scripted_events(self.game)
        self.game.run_turn()
        self.game.nation_data["B"]["scripted_events"] = [
            event("Accept Volunteer Divisions", "A")]

        process_scripted_events(self.game)

        verdict, action = diplomacy_messages.get_response_status(self.game.nation_data, "B", "A")
        self.assertEqual((verdict, action), (diplomacy_messages.RESPONSE_ACCEPT,
                                             volunteers.ACTION))


if __name__ == "__main__":
    unittest.main()
