"""An AI must not walk out of a faction it is fighting a war alongside.

From saves/"what happened to the allies": the Allies lost the United Kingdom
(with seven puppets) and, about fourteen turns later, the United States (with
the Philippines), leaving six members under a leader that had inherited the
chair by succession. Both defections were a model answering an ordinary message
with {"action": "LEAVE_FACTION"} -- the one branch of the action chain in
_process_ai_retaliation that checked nothing at all, while its neighbours tested
war state, faction membership and negotiating rights, and while an LLM war
declaration was filed as a request and re-vetted the following turn.

The rest of the split was mechanical: pull_puppets_into_faction takes a
nation's subjects with it, so two decisions moved ten countries.
"""

import os
import sys
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import data.constants as c
from map_logic.diplomacy import diplomacy_processor, faction_actions, faction_leadership

LONG_ENOUGH = c.AI_FACTION_MIN_TENURE + 5


def nation(faction="", leader=False, at_war=(), master="", tenure=LONG_ENOUGH):
    return {"faction": faction, "is_faction_leader": leader,
            "at_war_with": list(at_war), "allied_with": [], "puppets": [],
            "master": master, "faction_tenure": tenure, "research": {}}


def world(**nations):
    return {name.replace("_", " "): data for name, data in nations.items()}


class Screen:
    def __init__(self, nation_data):
        self.nation_data = nation_data
        self.map_data = {}


def blocked(nation_data, who):
    return faction_actions.why_an_ai_may_not_leave(who, nation_data)


class MayNotLeaveTests(unittest.TestCase):

    def test_a_settled_member_at_peace_may_leave(self):
        nd = world(Avaria=nation("Allies"), Borland=nation("Allies", leader=True))
        self.assertIsNone(blocked(nd, "Avaria"))

    def test_a_member_sharing_a_war_with_an_ally_may_not(self):
        """The check that would have stopped both halves of the Allies split."""
        nd = world(Avaria=nation("Allies", at_war=["Cirene"]),
                   Borland=nation("Allies", leader=True, at_war=["Cirene"]),
                   Cirene=nation(at_war=["Avaria", "Borland"]))
        self.assertIn("Borland", blocked(nd, "Avaria"))

    def test_its_own_private_war_is_not_a_shared_one(self):
        """Fighting alone is not fighting alongside anybody."""
        nd = world(Avaria=nation("Allies", at_war=["Cirene"]),
                   Borland=nation("Allies", leader=True),
                   Cirene=nation(at_war=["Avaria"]))
        self.assertIsNone(blocked(nd, "Avaria"))

    def test_a_faction_leader_may_not_walk_out_of_its_own_faction(self):
        """There is a button for this and it is not this one -- disbanding or
        kicking leaves a defined state; walking out leaves the bloc headless."""
        nd = world(Avaria=nation("Allies", leader=True), Borland=nation("Allies"))
        self.assertIn("leader", blocked(nd, "Avaria"))

    def test_a_recent_joiner_may_not(self):
        nd = world(Avaria=nation("Allies", tenure=1), Borland=nation("Allies", leader=True))
        self.assertIn("1 turns", blocked(nd, "Avaria"))

    def test_the_tenure_bar_is_the_constant(self):
        for tenure, allowed in ((c.AI_FACTION_MIN_TENURE - 1, False),
                                (c.AI_FACTION_MIN_TENURE, True)):
            with self.subTest(tenure=tenure):
                nd = world(Avaria=nation("Allies", tenure=tenure),
                           Borland=nation("Allies", leader=True))
                self.assertEqual(blocked(nd, "Avaria") is None, allowed)

    def test_a_nation_in_no_faction_has_nothing_to_leave(self):
        nd = world(Avaria=nation())
        self.assertIsNotNone(blocked(nd, "Avaria"))

    def test_a_puppet_follows_its_master(self):
        nd = world(Avaria=nation("Allies", master="Borland"),
                   Borland=nation("Allies", leader=True))
        nd["Borland"]["puppets"] = ["Avaria"]
        self.assertIn("puppet", blocked(nd, "Avaria"))


class TenureTests(unittest.TestCase):
    """Counted up by the same tick that ages a leadership claim.

    Stamping it at the join would mean remembering to stamp it in all nine
    places a nation can end up in a faction, including puppets dragged in behind
    a master and the crossed invitation that bypasses the treaty layer.
    """

    def screen(self, nation_data):
        s = Screen(nation_data)
        s.map_data = {}
        return s

    def tick(self, nd):
        faction_leadership.tick(self.screen(nd), None)

    def test_membership_ages_by_a_turn(self):
        nd = world(Avaria=nation("Allies", tenure=3), Borland=nation("Allies", leader=True))
        self.tick(nd)
        self.assertEqual(nd["Avaria"]["faction_tenure"], 4)

    def test_the_leader_is_counted_too(self):
        """Unlike faction_pressure, which is a claim against the leader."""
        nd = world(Avaria=nation("Allies", tenure=3), Borland=nation("Allies", leader=True, tenure=9))
        self.tick(nd)
        self.assertEqual(nd["Borland"]["faction_tenure"], 10)

    def test_a_nation_with_no_faction_carries_no_tenure(self):
        nd = world(Avaria=nation(tenure=40))
        self.tick(nd)
        self.assertNotIn("faction_tenure", nd["Avaria"])

    def test_leaving_forfeits_it(self):
        """Otherwise a nation banks tenure in one bloc and spends it defecting
        out of the next one the turn after it joins."""
        nd = world(Avaria=nation("Allies", tenure=40), Borland=nation("Allies", leader=True))
        faction_actions.leave_faction(nd, "Avaria")
        self.assertNotIn("faction_tenure", nd["Avaria"])

    def test_disbanding_forfeits_it_for_everybody(self):
        nd = world(Avaria=nation("Allies", tenure=40),
                   Borland=nation("Allies", leader=True, tenure=40))
        faction_actions.finalize_disband_faction(nd, "Borland")
        self.assertNotIn("faction_tenure", nd["Avaria"])
        self.assertNotIn("faction_tenure", nd["Borland"])


class FollowUpTests(unittest.TestCase):
    """The prompt taught the two-step defection, and the follow-up channel was
    the unchecked half of it: _follow_up_is_legal had cases for four actions and
    `return True` for everything else."""

    def legal(self, nd, sender, target, action):
        return diplomacy_processor._follow_up_is_legal(Screen(nd), sender, target, action)

    def test_a_leave_follow_up_obeys_the_same_rule(self):
        nd = world(Avaria=nation("Allies", at_war=["Cirene"]),
                   Borland=nation("Allies", leader=True, at_war=["Cirene"]),
                   Cirene=nation(at_war=["Avaria", "Borland"]))
        self.assertFalse(self.legal(nd, "Avaria", "Avaria", "LEAVE_FACTION"))

    def test_a_legitimate_leave_follow_up_still_fires(self):
        nd = world(Avaria=nation("Allies"), Borland=nation("Allies", leader=True))
        self.assertTrue(self.legal(nd, "Avaria", "Avaria", "LEAVE_FACTION"))

    def test_a_nation_already_in_a_faction_cannot_ask_to_join_another(self):
        nd = world(Avaria=nation("Allies"), Borland=nation("Axis", leader=True))
        self.assertFalse(self.legal(nd, "Avaria", "Borland", "JOIN_FACTION_REQ"))

    def test_it_cannot_ask_to_join_a_faction_it_is_fighting(self):
        nd = world(Avaria=nation(at_war=["Borland"]),
                   Borland=nation("Axis", leader=True, at_war=["Avaria"]))
        self.assertFalse(self.legal(nd, "Avaria", "Borland", "JOIN_FACTION_REQ"))

    def test_an_unaligned_nation_at_peace_may_ask(self):
        nd = world(Avaria=nation(), Borland=nation("Axis", leader=True))
        self.assertTrue(self.legal(nd, "Avaria", "Borland", "JOIN_FACTION_REQ"))


class SelfTargetedCooldownTests(unittest.TestCase):
    """A move a nation makes about itself is rate-limited against itself.

    get_valid_target falls back to whoever the AI was answering, so keying the
    cooldown on the target made LEAVE_FACTION's limit per-interlocutor: blocked
    after talking to one neighbour, free again by answering a different one.
    """

    def test_leaving_and_disbanding_are_self_targeted(self):
        self.assertIn("LEAVE_FACTION", c.SELF_TARGETED_ACTIONS)
        self.assertIn("DISBAND_FACTION", c.SELF_TARGETED_ACTIONS)

    def test_a_move_aimed_at_somebody_is_not(self):
        for action in ("WAR_DECLARATION", "JOIN_FACTION_REQ", "CEASEFIRE"):
            self.assertNotIn(action, c.SELF_TARGETED_ACTIONS)


if __name__ == "__main__":
    unittest.main()
