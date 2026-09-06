"""Military attachés share vision only while their host remains eligible."""

import os
import sys
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data import queries
from map_logic.ai import ai_evaluation
from map_logic.diplomacy import (
    diplomacy_logic, military_attaches, treaty_effects, volunteers, war_actions,
)
from tests.stub_map_screen import StubMapScreen


def nation(**extra):
    data = {"at_war_with": [], "allied_with": [], "faction": "", "master": "",
            "puppets": [], "military_access": [], "temp_modifiers": {},
            "pending_diplomacy": {}, "claims": []}
    data.update(extra)
    return data


class MilitaryAttacheTests(unittest.TestCase):
    def test_treaty_acceptance_deploys_an_attache(self):
        screen = StubMapScreen(["A", "B", "C"])
        screen.set_war("B", "C")

        outcome = treaty_effects.apply_treaty_effect(
            screen, military_attaches.ACTION, "A", "B")

        self.assertIsNone(outcome.blocked)
        self.assertEqual(military_attaches.hosts_for("A", screen.nation_data), ["B"])

    def test_ai_accepts_an_attache_without_enemy_support(self):
        data = {"A": nation(), "B": nation(), "C": nation()}
        data["B"]["at_war_with"] = ["C"]
        data["C"]["at_war_with"] = ["B"]

        verdict = ai_evaluation.evaluate_verdict(
            data, {}, "B", "A", military_attaches.ACTION)

        self.assertTrue(verdict.accepted)

    def test_ai_rejects_attache_sender_supporting_its_enemy_with_volunteers(self):
        data = {"A": nation(), "B": nation(at_war_with=["C"]),
                "C": nation(at_war_with=["B"])}
        data["A"]["volunteer_missions"] = {"C": {"state": volunteers.DEPLOYED}}

        verdict = ai_evaluation.evaluate_verdict(
            data, {}, "B", "A", military_attaches.ACTION)

        self.assertFalse(verdict.accepted)

    def test_ai_rejects_attache_sender_observing_its_enemy(self):
        data = {"A": nation(military_attaches=["C"]), "B": nation(at_war_with=["C"]),
                "C": nation(at_war_with=["B"])}

        verdict = ai_evaluation.evaluate_verdict(
            data, {}, "B", "A", military_attaches.ACTION)

        self.assertFalse(verdict.accepted)

    def test_sender_can_withdraw_an_attache_unilaterally(self):
        screen = StubMapScreen(["A", "B", "C"])
        screen.set_war("B", "C")
        screen.nation_data["A"]["military_attaches"] = ["B"]
        diplomacy_logic.toggle_diplomacy_action(
            screen.nation_data, "A", "B", military_attaches.WITHDRAW_ACTION)

        diplomacy_logic.process_diplomacy_turn(screen)

        self.assertEqual(military_attaches.hosts_for("A", screen.nation_data), [])

    def test_ai_hosts_schedule_then_both_revoke_attachés_observing_opposite_sides(self):
        data = {"A": nation(military_attaches=["B", "C"]),
                "B": nation(at_war_with=["C"]), "C": nation(at_war_with=["B"])}

        scheduled = military_attaches.schedule_conflict_revocations_for_ai_hosts(data)

        self.assertEqual(scheduled, [("A", "B"), ("A", "C")])
        self.assertEqual(military_attaches.hosts_for("A", data), ["B", "C"])
        self.assertEqual(military_attaches.process_scheduled_revocations(data),
                         [("A", "B"), ("A", "C")])
        self.assertEqual(military_attaches.hosts_for("A", data), [])

    def test_simultaneous_opposite_side_requests_are_accepted_then_both_revoked(self):
        data = {"A": nation(), "B": nation(at_war_with=["C"]),
                "C": nation(at_war_with=["B"])}

        self.assertTrue(military_attaches.ai_can_accept("A", "B", data)[0])
        self.assertTrue(military_attaches.ai_can_accept("A", "C", data)[0])
        self.assertTrue(military_attaches.send("A", "B", data)[0])
        self.assertTrue(military_attaches.send("A", "C", data)[0])

        self.assertEqual(
            military_attaches.schedule_conflict_revocations_for_ai_hosts(data),
            [("A", "B"), ("A", "C")])
        self.assertEqual(military_attaches.hosts_for("A", data), ["B", "C"])
        self.assertEqual(military_attaches.process_scheduled_revocations(data),
                         [("A", "B"), ("A", "C")])

    def test_simultaneous_requests_revoke_on_the_following_diplomacy_turn(self):
        screen = StubMapScreen(["A", "B", "C"])
        screen.set_war("B", "C")
        diplomacy_logic.toggle_diplomacy_action(
            screen.nation_data, "A", "B", military_attaches.ACTION)
        diplomacy_logic.toggle_diplomacy_action(
            screen.nation_data, "A", "C", military_attaches.ACTION)

        diplomacy_logic.process_diplomacy_turn(screen)  # Requests travel.
        diplomacy_logic.process_diplomacy_turn(screen)  # Both AI hosts accept.

        self.assertEqual(military_attaches.hosts_for("A", screen.nation_data), ["B", "C"])
        self.assertEqual(screen.nation_data["B"].get(military_attaches.PENDING_REVOKE_KEY), ["A"])
        self.assertEqual(screen.nation_data["C"].get(military_attaches.PENDING_REVOKE_KEY), ["A"])

        diplomacy_logic.process_diplomacy_turn(screen)  # Scheduled revocations resolve.

        self.assertEqual(military_attaches.hosts_for("A", screen.nation_data), [])

    def test_ai_host_revokes_existing_attache_during_turn_resolution(self):
        screen = StubMapScreen(["A", "B", "C"])
        screen.set_war("B", "C")
        screen.nation_data["A"]["military_attaches"] = ["B"]
        screen.nation_data["A"]["volunteer_missions"] = {
            "C": {"state": volunteers.AWAITING}}

        diplomacy_logic.process_diplomacy_turn(screen)

        self.assertEqual(military_attaches.hosts_for("A", screen.nation_data), ["B"])
        diplomacy_logic.process_diplomacy_turn(screen)

        self.assertEqual(military_attaches.hosts_for("A", screen.nation_data), [])

    def test_player_host_can_revoke_a_foreign_attache(self):
        screen = StubMapScreen(["A", "B", "C"], human_players=("B",))
        screen.set_war("B", "C")
        screen.nation_data["A"]["military_attaches"] = ["B"]
        diplomacy_logic.toggle_diplomacy_action(
            screen.nation_data, "B", "A", military_attaches.REVOKE_ACTION)

        diplomacy_logic.process_diplomacy_turn(screen)

        self.assertEqual(military_attaches.hosts_for("A", screen.nation_data), [])

    def test_attache_adds_the_host_s_unit_vision(self):
        class VisionMap:
            player_country = "A"
            tactical_mode = False
            player_unit = None

        screen = VisionMap()
        screen.nation_data = {"A": nation(), "B": nation(at_war_with=["C"]),
                              "C": nation(at_war_with=["B"])}
        screen.map_data = {
            "one": {"id": 1, "owner": "A", "neighbors": [], "units": []},
            "two": {"id": 2, "owner": "C", "neighbors": [], "units": []},
            "three": {"id": 3, "owner": "C", "neighbors": [],
                      "units": [{"owner": "B"}]},
        }
        screen.id_to_province = {p["id"]: p for p in screen.map_data.values()}

        before, _partial = queries.get_visible_provinces(screen)
        screen.nation_data["A"]["military_attaches"] = ["B"]
        after, _partial = queries.get_visible_provinces(screen)

        self.assertNotIn(3, before)
        self.assertIn(3, after)

    def test_attache_is_withdrawn_when_the_host_leaves_its_last_war(self):
        data = {"A": nation(military_attaches=["B"]), "B": nation(at_war_with=["C"]),
                "C": nation(at_war_with=["B"])}

        war_actions.finalize_neutral(data, "B", "C")

        self.assertEqual(military_attaches.hosts_for("A", data), [])

    def test_attache_is_withdrawn_when_sender_and_host_go_to_war(self):
        data = {"A": nation(military_attaches=["B"]), "B": nation(at_war_with=["C"]),
                "C": nation(at_war_with=["B"])}

        war_actions.finalize_war({}, data, "A", "B")

        self.assertEqual(military_attaches.hosts_for("A", data), [])


if __name__ == "__main__":
    unittest.main()
