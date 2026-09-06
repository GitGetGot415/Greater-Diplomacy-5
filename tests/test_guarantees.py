"""Guarantees are unilateral, defensive, and short-lived when war begins."""

import os
import sys
import unittest
from collections import defaultdict
from unittest.mock import patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from map_logic.diplomacy import guarantees
from map_logic.diplomacy import diplomacy_logic
from map_logic.diplomacy import faction_actions
from map_logic.diplomacy import war_actions
from map_logic.ai import ai_opinion
from tests.stub_map_screen import StubMapScreen


def nation(**extra):
    data = {"at_war_with": [], "allied_with": [], "faction": "",
            "master": "", "puppets": [], "military_access": []}
    data.update(extra)
    return data


class GuaranteeTests(unittest.TestCase):
    def test_ai_war_desire_falls_when_the_target_is_guaranteed(self):
        class World:
            def __init__(self):
                self.nation_data = {"A": nation(), "B": nation(), "G": nation()}
                self.claim_pressure = defaultdict(int)
                self.provs_by_owner = {"B": [1]}

            def power_ratio(self, attacker, target):
                return (2.0, 2.0) if target == "B" else (0.5, 0.5)

            def relation(self, _a, _b):
                return 0

        world = World()
        personality = {"caution": 0.5, "aggression": 0.5, "ambition": 0.5}
        with patch("map_logic.ai.ai_opinion.traits", return_value=personality):
            unguarded = ai_opinion.war_desire(world, "A", "B")
            world.nation_data["G"]["guarantees"] = ["B"]
            guarded = ai_opinion.war_desire(world, "A", "B")

        self.assertLess(guarded, unguarded)

    def test_guarantee_resolves_without_an_acceptance(self):
        screen = StubMapScreen(["A", "B"])
        diplomacy_logic.toggle_diplomacy_action(
            screen.nation_data, "A", "B", guarantees.ACTION)

        diplomacy_logic.process_diplomacy_turn(screen)

        self.assertEqual(guarantees.guaranteed_targets("A", screen.nation_data), ["B"])
        self.assertNotIn("B", screen.nation_data["A"]["pending_diplomacy"])

    def test_revoke_resolves_without_an_acceptance(self):
        screen = StubMapScreen(["A", "B"])
        screen.nation_data["A"]["guarantees"] = ["B"]
        diplomacy_logic.toggle_diplomacy_action(
            screen.nation_data, "A", "B", guarantees.REVOKE_ACTION)

        diplomacy_logic.process_diplomacy_turn(screen)

        self.assertEqual(guarantees.guaranteed_targets("A", screen.nation_data), [])
        self.assertNotIn("B", screen.nation_data["A"]["pending_diplomacy"])

    def test_only_a_peaceful_non_faction_target_can_be_guaranteed(self):
        data = {"A": nation(), "B": nation()}
        self.assertTrue(guarantees.grant("A", "B", data)[0])

        data["B"]["faction"] = "Bloc"
        self.assertFalse(guarantees.is_eligible("A", "B", data)[0])
        guarantees.reconcile(data)
        self.assertEqual(guarantees.guaranteed_targets("A", data), [])

    def test_defensive_declaration_calls_guarantor_before_removal(self):
        data = {"ATTACKER": nation(), "DEFENDER": nation(),
                "GUARANTOR": nation(guarantees=["DEFENDER"])}

        war_actions.finalize_war({}, data, "ATTACKER", "DEFENDER")

        self.assertIn("ATTACKER", data["DEFENDER"]["at_war_with"])
        self.assertIn("ATTACKER", data["GUARANTOR"]["at_war_with"])
        self.assertNotIn("DEFENDER", data["GUARANTOR"].get("guarantees", []))

    def test_guarantee_does_not_help_a_country_that_started_the_war(self):
        data = {"ATTACKER": nation(), "DEFENDER": nation(),
                "GUARANTOR": nation(guarantees=["ATTACKER"])}

        war_actions.finalize_war({}, data, "ATTACKER", "DEFENDER")

        self.assertNotIn("ATTACKER", data["GUARANTOR"]["at_war_with"])
        self.assertNotIn("DEFENDER", data["GUARANTOR"]["at_war_with"])

    def test_guarantee_honours_defence_even_when_a_truce_exists(self):
        data = {"ATTACKER": nation(truces={"GUARANTOR": 8}),
                "DEFENDER": nation(),
                "GUARANTOR": nation(guarantees=["DEFENDER"],
                                    truces={"ATTACKER": 8})}

        war_actions.finalize_war({}, data, "ATTACKER", "DEFENDER")

        self.assertIn("ATTACKER", data["GUARANTOR"]["at_war_with"])
        self.assertNotIn("ATTACKER", data["GUARANTOR"]["truces"])

    def test_joining_a_faction_immediately_ends_guarantees_over_joiner(self):
        data = {"HOST": nation(faction="Bloc", is_faction_leader=True),
                "JOINER": nation(), "GUARANTOR": nation(guarantees=["JOINER"])}

        self.assertTrue(faction_actions.finalize_faction_join({}, data, "HOST", "JOINER"))

        self.assertEqual(guarantees.guaranteed_targets("GUARANTOR", data), [])


if __name__ == "__main__":
    unittest.main()
