"""Tests for bilateral-action response predictions in the map diplomacy menu."""

import os
import sys
import unittest
from types import SimpleNamespace

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from screens.menu_screens.map import bilateral_response_indicator


def nation(**overrides):
    data = {"at_war_with": [], "allied_with": [], "claims": [], "puppets": [],
            "master": "", "puppet_type": "", "faction": "",
            "is_faction_leader": False, "temp_modifiers": {},
            "pending_diplomacy": {}}
    data.update(overrides)
    return data


class BilateralResponseIndicatorTests(unittest.TestCase):
    def setUp(self):
        self.screen = SimpleNamespace(
            player_country="Sender",
            active_players=["Sender"],
            nation_data={"Sender": nation(), "Target": nation()},
            map_data={},
            scenario_settings={},
        )

    def test_ai_target_uses_the_real_verdict(self):
        self.screen.nation_data["Target"]["at_war_with"] = ["Enemy"]
        self.assertEqual(
            bilateral_response_indicator(self.screen, "Target",
                                         "SEND_MILITARY_ATTACHE"),
            "YES")

    def test_human_target_is_always_unpredictable(self):
        self.screen.active_players.append("Target")
        self.assertEqual(
            bilateral_response_indicator(self.screen, "Target",
                                         "SEND_MILITARY_ATTACHE"),
            "MAYBE")

    def test_invalid_target_has_no_indicator(self):
        self.assertIsNone(
            bilateral_response_indicator(self.screen, "Missing",
                                         "SEND_MILITARY_ATTACHE"))

    def test_member_invitation_shows_no_for_ai_and_human_targets(self):
        self.screen.nation_data["Sender"]["faction"] = "Pact"
        # The target would accept a valid invitation while at war.
        self.screen.nation_data["Target"]["at_war_with"] = ["Enemy"]
        for human_target in (False, True):
            with self.subTest(human_target=human_target):
                self.screen.active_players = ["Sender", "Target"] if human_target else ["Sender"]
                self.assertEqual(bilateral_response_indicator(
                    self.screen, "Target", "FACTION_INVITE"), "NO")

    def test_join_request_to_a_member_shows_no_for_ai_and_human_targets(self):
        self.screen.nation_data["Target"]["faction"] = "Pact"
        for human_target in (False, True):
            with self.subTest(human_target=human_target):
                self.screen.active_players = ["Sender", "Target"] if human_target else ["Sender"]
                self.assertEqual(bilateral_response_indicator(
                    self.screen, "Target", "JOIN_FACTION_REQ"), "NO")

    def test_legal_leader_invitation_keeps_the_ai_acceptance_prediction(self):
        self.screen.nation_data["Sender"].update(faction="Pact", is_faction_leader=True)
        self.screen.nation_data["Target"]["at_war_with"] = ["Enemy"]
        self.assertEqual(bilateral_response_indicator(
            self.screen, "Target", "FACTION_INVITE"), "YES")

    def test_legal_join_request_keeps_the_ai_acceptance_prediction(self):
        import data.constants as c
        self.screen.nation_data["Target"].update(
            faction="Pact", is_faction_leader=True,
            temp_modifiers={"Sender": {"general": c.AI_RELATION_FACTION_THRESHOLD}})
        self.assertEqual(bilateral_response_indicator(
            self.screen, "Target", "JOIN_FACTION_REQ"), "YES")


if __name__ == "__main__":
    unittest.main()
