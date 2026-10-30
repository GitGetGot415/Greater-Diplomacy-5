"""Scripted-event coverage for the expanded diplomacy actions."""

from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tests.stub_map_screen import StubMapScreen
from map_logic.ai import scripted_events
from map_logic.ai.scripted_events import process_scripted_events
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

    def test_scripted_master_war_makes_the_puppet_leave_the_faction_first(self):
        """The historical Albania event must not leave Axis members at war."""
        self.game.set_faction("Axis", "A", "B")
        self.game.nation_data["A"]["puppets"] = ["B"]
        self.game.nation_data["B"].update(master="A", puppet_type="Autonomous")
        self.game.nation_data["A"]["scripted_events"] = [event("Declare War", "B")]

        process_scripted_events(self.game)
        self.game.run_turn()

        self.assertEqual(self.game.nation_data["A"]["faction"], "Axis")
        self.assertEqual(self.game.nation_data["B"]["faction"], "")
        self.assertIn("B", self.game.nation_data["A"]["at_war_with"])
        self.assertIn("A", self.game.nation_data["B"]["at_war_with"])

    def test_illegal_scripted_diplomacy_actions_are_not_queued(self):
        """Scripted events use the same structural rules as the player UI."""
        self.game.set_faction("Axis", "A", "B")
        self.game.nation_data["A"]["scripted_events"] = [
            event("Declare War", "B"),
            event("Send Ceasefire", "C"),
            event("Guarantee Independence", "B"),
            event("Send Military Attaché", "C"),
            event("Request Military Access", "A"),
        ]

        process_scripted_events(self.game)

        self.assertEqual(self.game.nation_data["A"]["pending_diplomacy"], {})

    def test_scripted_direct_effects_ignore_missing_targets_and_provinces(self):
        home = self.game.home_of("A")
        self.game.nation_data["A"]["scripted_events"] = [{
            "conditions": [{"type": "True", "operator": "==", "value": "", "chain": "AND"}],
            "actions": [
                {"type": "Give Territory", "target": "Missing", "message": str(home["id"])},
                {"type": "Spawn Unit", "target": "Missing", "message": str(home["id"])},
                {"type": "Queue Claims", "target": "None", "message": "999999"},
                {"type": "Send Custom Message", "target": "Missing", "message": "Hello."},
            ],
            "fire_once": True,
            "trigger_type": "Both",
        }]

        process_scripted_events(self.game)

        self.assertEqual(home["owner"], "A")
        self.assertEqual(home["units"], [])
        self.assertEqual(self.game.nation_data["A"].get("claim_queue", []), [])
        self.assertEqual(self.game.nation_data["A"]["pending_diplomacy"], {})


class ScriptedConditionRuleTests(unittest.TestCase):
    def run_state(self, *, turn=5, variables=(), preview=None):
        world = SimpleNamespace(script_variables=list(variables), nation_data={}, map_data={}, id_to_province={})
        return scripted_events.EventRun(None, world, {"A"}, [], turn, preview)

    def met(self, run, *conditions):
        return scripted_events._conditions_met(run, "A", list(conditions))

    def test_editor_choices_all_have_rules(self):
        self.assertEqual(set(scripted_events.COND_TYPES), set(scripted_events.CONDITIONS))
        for action in scripted_events.ACT_TYPES:
            with self.subTest(action=action):
                self.assertTrue(action in scripted_events.ACTIONS
                                or action in scripted_events._SCRIPTED_REQUEST_ACTIONS
                                or action in scripted_events._SCRIPTED_RESPONSE_ACTIONS
                                or action in scripted_events._GENERIC_RESPONSE_VERDICTS
                                or action in ("Offer Volunteer Divisions", "Send Custom Message"))

    def test_turn_number_comparisons_and_ranges(self):
        run = self.run_state(turn=5)
        for op, value, expected in (("==", "5", True), (">", "5", False), (">=", "5", True),
                                    ("BETWEEN (INC)", "5,6", True), ("BETWEEN (EXC)", "5,6", False),
                                    ("BETWEEN (INC)", "5", False), ("==", "text", False),
                                    # The editor does not offer this operator for turns.
                                    ("!=", "4", False)):
            with self.subTest(op=op, value=value):
                self.assertIs(self.met(run, {"type": "Turn Number", "operator": op, "value": value}), expected)

    def test_numeric_variable_truncates_and_rejects_comma_ranges(self):
        run = self.run_state(variables=[{"name": "n", "type": "int", "value": "3.9"}])
        condition = {"type": "Variable", "variable": "n"}
        self.assertTrue(self.met(run, dict(condition, operator="==", value="3")))
        self.assertTrue(self.met(run, dict(condition, operator="!=", value="4")))
        # Existing behavior: a comma-separated value fails its single-number parse.
        self.assertFalse(self.met(run, dict(condition, operator="BETWEEN (INC)", value="1,5")))

    def test_string_and_missing_variables_compare_as_text(self):
        run = self.run_state(variables=[{"name": "s", "type": "string", "value": "yes"}])
        self.assertTrue(self.met(run, {"type": "Variable", "variable": "s", "operator": "==", "value": "yes"}))
        self.assertTrue(self.met(run, {"type": "Variable", "variable": "s", "operator": "!=", "value": "no"}))
        self.assertFalse(self.met(run, {"type": "Variable", "variable": "s", "operator": ">", "value": "a"}))
        self.assertTrue(self.met(run, {"type": "Variable", "variable": "missing", "operator": "==", "value": "0"}))

    def test_every_random_condition_draws_and_a_preview_draws_none(self):
        always_false = {"type": "False"}
        rolled = {"type": "Random (0.00 - 1.00)", "operator": "<", "value": "1", "chain": "AND"}
        with patch.object(scripted_events.random, "random", return_value=0.5) as draw:
            self.assertFalse(self.met(self.run_state(), always_false, rolled, rolled))
            self.assertEqual(draw.call_count, 2)
            draw.reset_mock()
            self.assertIsNone(self.met(self.run_state(preview=("A", "B", "TRADE")), rolled))
            draw.assert_not_called()

    def test_chains_combine_known_and_unknown_results(self):
        chain = scripted_events._chain_condition_result
        for previous, current, name, expected in (
                (True, False, "AND", False), (True, True, "NAND", False), (False, True, "OR", True),
                (False, False, "NOR", True), (True, True, "XOR", False), (True, None, "AND", None),
                (False, None, "AND", False), (True, None, "OR", True), (None, True, "XOR", None),
                (True, False, "unknown", True)):
            with self.subTest(previous=previous, current=current, chain=name):
                self.assertIs(chain(previous, current, name), expected)


if __name__ == "__main__":
    unittest.main()
