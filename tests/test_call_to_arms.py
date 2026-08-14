"""A call to arms has to be about a war, and about the right one.

From the save "Hungary left and then asked to join in a faction war what":

    Hungary: faction = ""   at_war_with = []
             pending_diplomacy = {"German Reich": {"action": "CALL_TO_ARMS",
                                  "message": "The pact is being tested. Honour it."}}

A nation in no faction, at war with nobody, calling the player to arms -- and
that message is not even prose, it is the second PROACTIVE_CALL_TO_ARMS line off
the fallback table. The branch that queues a model's chosen action checked
faction membership for JOIN_WARS, war state for CEASEFIRE and existing
membership for JOIN_FACTION_REQ, and checked nothing whatsoever for
CALL_TO_ARMS.

The other half of the same hole is direction. An autonomous puppet's wars are
its master's by construction, so a puppet has no war to call its master into --
what it means is "let us join you", and it sent the mirror image of that,
arriving as "we request your aid" from the nation offering to give it.
"""

import os
import sys
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import data.constants as c
from map_logic.diplomacy import treaty_effects, war_calls


def nation(**over):
    base = {"at_war_with": [], "allied_with": [], "claims": [], "puppets": [],
            "master": "", "puppet_type": "", "faction": "", "is_faction_leader": False,
            "temp_modifiers": {}, "pending_diplomacy": {}, "inbox": [], "truces": {},
            "manpower": 5000, "materials": 8000, "fuel": 500, "war_durations": {}}
    base.update(over)
    return base


class PledgeTests(unittest.TestCase):
    def setUp(self):
        self.nd = {
            "Ally": nation(faction="Axis"),
            "Caller": nation(faction="Axis"),
            "Stranger": nation(),
            "Master": nation(faction="Comintern", puppets=["Subject"]),
            "Subject": nation(master="Master", puppet_type=c.PUPPET_TYPE_AUTONOMOUS),
        }

    def test_faction_mates_owe_each_other_help(self):
        self.assertTrue(war_calls.are_pledged("Caller", "Ally", self.nd))

    def test_two_nations_with_no_pact_owe_each_other_nothing(self):
        """Hungary, with faction = "", asking the German Reich for aid."""
        self.assertFalse(war_calls.are_pledged("Stranger", "Caller", self.nd))

    def test_two_factionless_nations_are_not_pledged_by_sharing_nothing(self):
        self.nd["Other"] = nation()
        self.assertFalse(war_calls.are_pledged("Stranger", "Other", self.nd))

    def test_a_subject_and_its_master_are_pledged_without_a_faction(self):
        """A puppet is not always in its overlord's faction, and is bound
        tighter than any pact regardless -- it gets pulled into the wars."""
        self.assertTrue(war_calls.are_pledged("Subject", "Master", self.nd))
        self.assertTrue(war_calls.are_pledged("Master", "Subject", self.nd))

    def test_nobody_is_pledged_to_themselves(self):
        self.assertFalse(war_calls.are_pledged("Caller", "Caller", self.nd))


class DirectionTests(unittest.TestCase):
    """Which of the mirrored pair the two nations' war lists actually support."""

    def setUp(self):
        self.nd = {
            "Caller": nation(faction="Axis"),
            "Ally": nation(faction="Axis"),
            "Enemy": nation(at_war_with=[]),
        }

    def at_war(self, who):
        self.nd[who]["at_war_with"] = ["Enemy"]
        self.nd["Enemy"]["at_war_with"].append(who)

    def test_a_nation_with_its_own_war_calls_to_arms(self):
        self.at_war("Caller")
        self.assertEqual(war_calls.intended_action("Caller", "Ally", self.nd),
                         war_calls.CALL_TO_ARMS)

    def test_a_nation_whose_ally_is_at_war_asks_to_join(self):
        self.at_war("Ally")
        self.assertEqual(war_calls.intended_action("Caller", "Ally", self.nd),
                         war_calls.JOIN_WARS)

    def test_neither_at_war_supports_neither_message(self):
        self.assertIsNone(war_calls.intended_action("Caller", "Ally", self.nd))

    def test_a_war_they_are_already_in_is_nothing_to_call_them_into(self):
        self.at_war("Caller")
        self.at_war("Ally")
        self.assertIsNone(war_calls.intended_action("Caller", "Ally", self.nd))

    def test_a_truced_enemy_is_not_a_war_to_be_called_into(self):
        """join_faction_wars refuses to tear up a truce, so a call naming only
        truced enemies would be answered by doing nothing at all."""
        self.at_war("Caller")
        self.nd["Ally"]["truces"] = {"Enemy": 8}
        self.assertIsNone(war_calls.intended_action("Caller", "Ally", self.nd))

    def test_the_two_of_them_fighting_each_other_is_not_a_war_to_join(self):
        self.nd["Caller"]["at_war_with"] = ["Ally"]
        self.nd["Ally"]["at_war_with"] = ["Caller"]
        self.assertIsNone(war_calls.intended_action("Caller", "Ally", self.nd))

    def test_a_puppet_with_no_war_of_its_own_offers_to_join_instead(self):
        """The reported case. The subject inherits its master's wars, so it can
        never have one to call the master into; it meant the other message."""
        nd = {"Master": nation(at_war_with=["Enemy"], puppets=["Subject"]),
              "Subject": nation(master="Master", puppet_type=c.PUPPET_TYPE_AUTONOMOUS),
              "Enemy": nation(at_war_with=["Master"])}
        self.assertEqual(war_calls.intended_action("Subject", "Master", nd),
                         war_calls.JOIN_WARS)


class HonestyTests(unittest.TestCase):
    def setUp(self):
        self.nd = {"Caller": nation(faction="Axis", at_war_with=["Enemy"]),
                   "Ally": nation(faction="Axis"),
                   "Enemy": nation(at_war_with=["Caller"])}

    def test_the_supported_message_is_honest(self):
        self.assertTrue(war_calls.is_honest("CALL_TO_ARMS", "Caller", "Ally", self.nd))

    def test_its_mirror_image_is_not(self):
        self.assertFalse(war_calls.is_honest("JOIN_WARS", "Caller", "Ally", self.nd))

    def test_actions_that_are_not_war_calls_are_left_alone(self):
        for action in ("TRADE", "PEACE_TREATY", "FACTION_INVITE"):
            with self.subTest(action=action):
                self.assertTrue(war_calls.is_honest(action, "Caller", "Ally", self.nd))


class BackstopTests(unittest.TestCase):
    """apply_treaty_effect is where every path converges.

    An offer sits in the inbox for turns, and the war it was about can end while
    it waits -- so the check has to be at acceptance, not only at sending.
    """

    class Host:
        pass

    def host(self, nd):
        host = self.Host()
        host.nation_data = nd
        host.map_data = {}
        return host

    def hungary(self):
        """The save's own line-up: Hungary in no faction and fighting nobody,
        the German Reich fighting the United Kingdom."""
        return {"Hungary": nation(), "German Reich": nation(at_war_with=["UK"]),
                "UK": nation(at_war_with=["German Reich"])}

    def test_answering_a_call_with_no_war_behind_it_is_blocked(self):
        nd = self.hungary()
        outcome = treaty_effects.apply_treaty_effect(
            self.host(nd), "CALL_TO_ARMS", "Hungary", "German Reich")
        self.assertTrue(outcome.blocked)

    def test_a_blocked_call_drags_nobody_into_anything(self):
        nd = self.hungary()
        treaty_effects.apply_treaty_effect(
            self.host(nd), "CALL_TO_ARMS", "Hungary", "German Reich")
        self.assertEqual(nd["Hungary"]["at_war_with"], [])
        self.assertEqual(nd["German Reich"]["at_war_with"], ["UK"])
        self.assertEqual(nd["UK"]["at_war_with"], ["German Reich"])

    def test_a_real_call_between_faction_mates_still_goes_through(self):
        nd = {"Caller": nation(faction="Axis", at_war_with=["Enemy"]),
              "Ally": nation(faction="Axis"),
              "Enemy": nation(at_war_with=["Caller"])}
        outcome = treaty_effects.apply_treaty_effect(
            self.host(nd), "CALL_TO_ARMS", "Caller", "Ally")
        self.assertFalse(outcome.blocked)
        self.assertIn("Enemy", nd["Ally"]["at_war_with"])

    def test_a_real_offer_to_join_still_goes_through(self):
        nd = {"Ally": nation(faction="Axis"),
              "Fighter": nation(faction="Axis", at_war_with=["Enemy"]),
              "Enemy": nation(at_war_with=["Fighter"])}
        outcome = treaty_effects.apply_treaty_effect(
            self.host(nd), "JOIN_WARS", "Ally", "Fighter")
        self.assertFalse(outcome.blocked)
        self.assertIn("Enemy", nd["Ally"]["at_war_with"])


class LabelTests(unittest.TestCase):
    def test_the_two_directions_no_longer_share_a_label(self):
        """They did, so a puppet offering to join arrived under the same word as
        an ally demanding help, and only opening it told you which."""
        self.assertNotEqual(c.MESSAGE_CATEGORIES["CALL_TO_ARMS"],
                            c.MESSAGE_CATEGORIES["JOIN_WARS"])

    def test_neither_of_them_reads_as_a_declaration_of_war(self):
        for action in ("CALL_TO_ARMS", "JOIN_WARS"):
            with self.subTest(action=action):
                self.assertNotEqual(c.MESSAGE_CATEGORIES[action],
                                    c.MESSAGE_CATEGORIES["WAR_DECLARATION"])


if __name__ == "__main__":
    unittest.main()
