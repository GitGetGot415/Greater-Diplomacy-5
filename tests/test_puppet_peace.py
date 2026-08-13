"""A puppet's wars are its master's business.

Nothing enforced this before: thirteen separate paths could initiate or accept
a peace and none of them looked at `master`, so a subject could sign its own
treaty with a third party while its overlord fought on. The mirror of the rule
that already existed for war -- "puppets can only declare war on their master"
-- so peace with the master itself is still allowed, since that is how an
independence war ends.
"""

import os
import sys
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import data.constants as c
from data import queries
from map_logic.ai import ai_evaluation
from map_logic.diplomacy import treaty_effects


def nation(**over):
    base = {"at_war_with": [], "allied_with": [], "claims": [], "puppets": [],
            "master": "", "puppet_type": "", "faction": "", "is_faction_leader": False,
            "temp_modifiers": {}, "pending_diplomacy": {}, "inbox": [],
            "manpower": 5000, "materials": 8000, "fuel": 500, "war_durations": {}}
    base.update(over)
    return base


class CanNegotiateTests(unittest.TestCase):
    def setUp(self):
        self.nation_data = {"Free": nation(),
                            "Subject": nation(master="Overlord",
                                              puppet_type=c.PUPPET_TYPE_AUTONOMOUS),
                            "Overlord": nation(puppets=["Subject"])}

    def test_an_independent_nation_may_settle_with_anyone(self):
        self.assertTrue(queries.can_negotiate_peace("Free", "Overlord", self.nation_data))

    def test_a_puppet_may_not_settle_with_a_third_party(self):
        self.assertFalse(queries.can_negotiate_peace("Subject", "Free", self.nation_data))

    def test_a_puppet_may_settle_with_its_own_master(self):
        """That is how an independence war ends."""
        self.assertTrue(queries.can_negotiate_peace("Subject", "Overlord", self.nation_data))

    def test_an_integrated_puppet_is_bound_the_same_way(self):
        self.nation_data["Subject"]["puppet_type"] = c.PUPPET_TYPE_INTEGRATED
        self.assertFalse(queries.can_negotiate_peace("Subject", "Free", self.nation_data))

    def test_a_master_is_not_bound_by_its_subjects(self):
        self.assertTrue(queries.can_negotiate_peace("Overlord", "Free", self.nation_data))


class EngineBackstopTests(unittest.TestCase):
    """apply_treaty_effect is where all thirteen paths converge."""

    def setUp(self):
        self.nation_data = {"Free": nation(at_war_with=["Subject"]),
                            "Subject": nation(master="Overlord", at_war_with=["Free"]),
                            "Overlord": nation(puppets=["Subject"])}
        self.map_data = {"1": {"id": 1, "owner": "Free", "cores": ["Free"],
                               "neighbors": [], "units": []}}

    class Host:
        pass

    def apply(self, action, proposer, accepter):
        host = self.Host()
        host.nation_data = self.nation_data
        host.map_data = self.map_data
        return treaty_effects.apply_treaty_effect(host, action, proposer, accepter)

    def test_a_puppet_proposing_peace_is_blocked(self):
        for action in ("PEACE_TREATY", "CEASEFIRE"):
            with self.subTest(action=action):
                self.assertTrue(self.apply(action, "Subject", "Free").blocked)

    def test_a_puppet_accepting_peace_is_blocked(self):
        for action in ("PEACE_TREATY", "CEASEFIRE"):
            with self.subTest(action=action):
                self.assertTrue(self.apply(action, "Free", "Subject").blocked)

    def test_the_war_is_left_running_when_blocked(self):
        self.apply("CEASEFIRE", "Subject", "Free")
        self.assertIn("Free", self.nation_data["Subject"]["at_war_with"])

    def test_two_independent_nations_are_unaffected(self):
        self.nation_data["Free"]["at_war_with"] = ["Overlord"]
        self.nation_data["Overlord"]["at_war_with"] = ["Free"]
        self.assertFalse(self.apply("CEASEFIRE", "Free", "Overlord").blocked)
        self.assertNotIn("Overlord", self.nation_data["Free"]["at_war_with"])

    def test_a_puppet_may_still_settle_with_its_own_master(self):
        self.nation_data["Subject"]["at_war_with"] = ["Overlord"]
        self.nation_data["Overlord"]["at_war_with"] = ["Subject"]
        self.assertFalse(self.apply("CEASEFIRE", "Subject", "Overlord").blocked)


class AIVerdictTests(unittest.TestCase):
    """The AI must not agree terms it has no authority to agree."""

    def setUp(self):
        self.nation_data = {"Avaria": nation(at_war_with=["Borland"]),
                            "Borland": nation(at_war_with=["Avaria"]),
                            "Overlord": nation()}
        self.map_data = {
            "1": {"id": 1, "owner": "Avaria", "cores": ["Avaria"], "neighbors": [2], "units": []},
            "2": {"id": 2, "owner": "Borland", "cores": ["Borland"], "neighbors": [1], "units": []},
        }

    def verdict(self, action="CEASEFIRE"):
        return ai_evaluation.evaluate_verdict(
            self.nation_data, self.map_data, "Avaria", "Borland", action, "")

    def test_a_puppet_ai_refuses_terms_from_a_third_party(self):
        self.nation_data["Avaria"]["master"] = "Overlord"
        v = self.verdict()
        self.assertFalse(v.accepted)
        self.assertEqual(v.confidence, 1.0, "structural, so nothing may overrule it")

    def test_terms_from_a_puppet_are_refused(self):
        self.nation_data["Borland"]["master"] = "Overlord"
        self.assertFalse(self.verdict().accepted)

    def test_a_puppet_ai_will_still_treat_with_its_own_master(self):
        """Not asserted as accepted -- only that the ordinary reasoning gets to
        run, rather than being cut short by the structural refusal."""
        self.nation_data["Avaria"]["master"] = "Borland"
        self.assertNotIn("subject state", self.verdict().reason)


class RefusalWordingTests(unittest.TestCase):
    """Being refused for the right reason.

    Declare War and Ceasefire are the same button -- map.py relabels it once you
    are at war and leaves the callback alone -- and handle_declare_war ran its
    "puppets may only declare war on their master" gate before it noticed the
    click was about peace. So a puppet asking for a ceasefire was told, quite
    truthfully and entirely unhelpfully, that it could not declare war.
    """

    class Screen:
        def __init__(self, nation_data, player, target):
            self.nation_data = nation_data
            self.player_country = player
            self.selected_province = {"owner": target}
            self.said = []

        def show_feedback(self, text):
            self.said.append(text)

    def screen(self, at_war):
        nd = {"Subject": nation(master="Overlord", puppet_type=c.PUPPET_TYPE_AUTONOMOUS),
              "Overlord": nation(puppets=["Subject"]),
              "Free": nation()}
        if at_war:
            nd["Subject"]["at_war_with"] = ["Free"]
            nd["Free"]["at_war_with"] = ["Subject"]
        return self.Screen(nd, "Subject", "Free")

    def test_a_puppet_asking_for_peace_is_told_about_peace(self):
        from map_logic.diplomacy import player_diplomacy_actions

        screen = self.screen(at_war=True)
        player_diplomacy_actions.handle_declare_war(screen)
        self.assertEqual(screen.said, ["Puppets can only make peace with their master!"])

    def test_a_puppet_declaring_war_is_still_told_about_war(self):
        from map_logic.diplomacy import player_diplomacy_actions

        screen = self.screen(at_war=False)
        player_diplomacy_actions.handle_declare_war(screen)
        self.assertEqual(screen.said, ["Puppets can only declare war on their master!"])


if __name__ == "__main__":
    unittest.main()
