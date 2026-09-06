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


if __name__ == "__main__":
    unittest.main()
