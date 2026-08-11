"""A puppet's alignment is its master's, and a dead nation is nobody's ally.

Two states nothing checked. A subject could join a faction on its own authority
-- saves/Madagascar but not France has French Madagascar in the Axis while Vichy
France, its master, is in nothing -- and a nation that lost its last province
stayed on its faction's roster, because the cleanup that removed one only ever
ran for a puppet the player had created. saves/Tannu Tuva Gone but not forgotten
carries three such ghosts, of which only Tannu Tuva is a puppet at all.

The core rule is the part worth pinning: an integrated puppet the scenario
shipped with keeps its cores when annexed, and one you created and re-annexed
does not. That is the only thing the created/authored distinction now decides.
"""

import os
import sys
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import data.constants as c
from data import queries
from data.map import load_map
from map_logic.diplomacy import faction_actions, puppet_actions, treaty_effects
from map_logic.turn_processing import edit_province_ownership as own


def nation(**over):
    base = {"at_war_with": [], "allied_with": [], "claims": [], "puppets": [],
            "master": "", "puppet_type": "", "faction": "", "is_faction_leader": False,
            "temp_modifiers": {}, "pending_diplomacy": {}, "inbox": [], "relations": {},
            "manpower": 5000, "materials": 8000, "fuel": 500, "war_durations": {}}
    base.update(over)
    return base


class Screen:
    """Enough of a map screen for ownership changes. ai_is_thinking short-circuits
    every repaint, so nothing here needs a display surface."""

    is_editor = False
    viewing_ai_moves = False
    ai_is_thinking = True
    map_mode = "POLITICAL"
    centers_need_update = False

    def __init__(self, nation_data, map_data):
        self.nation_data = nation_data
        self.map_data = map_data
        self.id_to_province = {p["id"]: p for p in map_data.values()}


def province(pid, owner, cores=None):
    return {"id": pid, "json_key": str(pid), "owner": owner,
            "cores": list(cores if cores is not None else [owner]),
            "neighbors": [], "units": [], "unit_queue": [], "building_queue": [],
            "map_color": (pid, pid, pid), "terrain": "plains"}


class CanChooseOwnFactionTests(unittest.TestCase):

    def setUp(self):
        self.nation_data = {"Free": nation(),
                            "Subject": nation(master="Overlord",
                                              puppet_type=c.PUPPET_TYPE_AUTONOMOUS),
                            "Overlord": nation(puppets=["Subject"])}

    def test_an_independent_nation_chooses_for_itself(self):
        self.assertTrue(queries.can_choose_own_faction("Free", self.nation_data))

    def test_a_puppet_does_not(self):
        self.assertFalse(queries.can_choose_own_faction("Subject", self.nation_data))

    def test_an_integrated_puppet_is_bound_the_same_way(self):
        self.nation_data["Subject"]["puppet_type"] = c.PUPPET_TYPE_INTEGRATED
        self.assertFalse(queries.can_choose_own_faction("Subject", self.nation_data))

    def test_a_master_is_not_bound_by_its_subjects(self):
        self.assertTrue(queries.can_choose_own_faction("Overlord", self.nation_data))

    def test_a_nation_nobody_has_heard_of_is_free(self):
        self.assertTrue(queries.can_choose_own_faction("Nowhere", self.nation_data))


class EngineBackstopTests(unittest.TestCase):
    """apply_treaty_effect is where the invitation paths converge."""

    def setUp(self):
        self.nation_data = {
            "Leader": nation(faction="Pact", is_faction_leader=True),
            "Free": nation(),
            "Subject": nation(master="Overlord"),
            "Overlord": nation(puppets=["Subject"]),
        }
        self.map_data = {"1": province(1, "Free")}

    def apply(self, action, proposer, accepter):
        host = Screen(self.nation_data, self.map_data)
        return treaty_effects.apply_treaty_effect(host, action, proposer, accepter)

    def test_a_puppet_cannot_be_invited_in(self):
        self.assertTrue(self.apply("FACTION_INVITE", "Leader", "Subject").blocked)
        self.assertEqual(self.nation_data["Subject"]["faction"], "")

    def test_a_puppet_cannot_ask_to_join(self):
        self.assertTrue(self.apply("JOIN_FACTION_REQ", "Subject", "Leader").blocked)
        self.assertEqual(self.nation_data["Subject"]["faction"], "")

    def test_an_independent_nation_still_joins(self):
        self.assertFalse(self.apply("FACTION_INVITE", "Leader", "Free").blocked)
        self.assertEqual(self.nation_data["Free"]["faction"], "Pact")

    def test_a_puppet_cannot_walk_out_alone(self):
        """The mirror of joining alone: it would strand the subject outside the
        faction its overlord is still in."""
        self.nation_data["Overlord"]["faction"] = "Pact"
        self.nation_data["Subject"]["faction"] = "Pact"
        faction_actions.finalize_faction_leave(self.nation_data, "Subject")
        self.assertEqual(self.nation_data["Subject"]["faction"], "Pact")

    def test_a_master_leaving_takes_its_puppet_with_it(self):
        self.nation_data["Overlord"]["faction"] = "Pact"
        self.nation_data["Subject"]["faction"] = "Pact"
        faction_actions.finalize_faction_leave(self.nation_data, "Overlord")
        self.assertEqual(self.nation_data["Overlord"]["faction"], "")
        self.assertEqual(self.nation_data["Subject"]["faction"], "")

    def test_a_master_joining_takes_its_puppet_with_it(self):
        faction_actions.finalize_faction_join(
            self.map_data, self.nation_data, "Leader", "Overlord")
        self.assertEqual(self.nation_data["Overlord"]["faction"], "Pact")
        self.assertEqual(self.nation_data["Subject"]["faction"], "Pact",
                         "puppets follow their master in, they do not join themselves")


class RetireLandlessTests(unittest.TestCase):
    """Losing your last province takes you off everyone's books."""

    def build(self, **over):
        self.nation_data = {
            "Empire": nation(faction="Pact", is_faction_leader=True,
                             at_war_with=["Doomed"], puppets=["Doomed"]),
            "Bystander": nation(faction="Pact", at_war_with=["Doomed"],
                                pending_diplomacy={"Doomed": {"action": "TRADE"}}),
            "Doomed": nation(faction="Pact", master="Empire",
                             at_war_with=["Empire", "Bystander"], **over),
        }
        self.map_data = {"1": province(1, "Empire", cores=["Empire", "Doomed"]),
                         "2": province(2, "Empire", cores=["Doomed"])}
        return Screen(self.nation_data, self.map_data)

    def test_a_landless_nation_leaves_its_faction(self):
        screen = self.build()
        own.retire_landless_nation(screen, "Doomed")
        self.assertNotIn("Doomed", queries.get_faction_members("Pact", self.nation_data))

    def test_its_wars_stop_being_anyone_elses_problem(self):
        screen = self.build()
        own.retire_landless_nation(screen, "Doomed")
        self.assertEqual(self.nation_data["Empire"]["at_war_with"], [])
        self.assertEqual(self.nation_data["Bystander"]["at_war_with"], [])

    def test_pending_offers_to_it_are_dropped(self):
        screen = self.build()
        own.retire_landless_nation(screen, "Doomed")
        self.assertEqual(self.nation_data["Bystander"]["pending_diplomacy"], {})

    def test_the_master_stops_listing_it_as_a_puppet(self):
        screen = self.build()
        own.retire_landless_nation(screen, "Doomed")
        self.assertEqual(self.nation_data["Empire"]["puppets"], [])

    def test_a_nation_the_scenario_shipped_with_keeps_its_cores(self):
        """The requested rule: annexing an integrated puppet that existed at the
        start of the game leaves its cores on the map."""
        screen = self.build(puppet_type=c.PUPPET_TYPE_INTEGRATED)
        own.retire_landless_nation(screen, "Doomed")
        self.assertIn("Doomed", self.map_data["1"]["cores"])
        self.assertIn("Doomed", self.map_data["2"]["cores"])
        self.assertIn("Doomed", self.nation_data, "it is retired, not erased")

    def test_a_puppet_you_created_loses_its_cores_when_you_re_annex_it(self):
        screen = self.build(puppet_type=c.PUPPET_TYPE_INTEGRATED,
                            is_created_integrated_puppet=True)
        own.retire_landless_nation(screen, "Doomed")
        self.assertNotIn("Doomed", self.map_data["1"]["cores"])
        self.assertNotIn("Doomed", self.map_data["2"]["cores"])
        self.assertNotIn("Doomed", self.nation_data)

    def test_a_rebellion_put_down_mid_war_is_erased(self):
        screen = self.build(is_rebellion=True)
        own.retire_landless_nation(screen, "Doomed")
        self.assertNotIn("Doomed", self.nation_data)

    def test_a_rebellion_that_settled_by_treaty_is_not(self):
        """No war still running means it ended at a table, not on a field."""
        screen = self.build(is_rebellion=True)
        self.nation_data["Doomed"]["at_war_with"] = []
        own.retire_landless_nation(screen, "Doomed")
        self.assertIn("Doomed", self.nation_data)

    def test_a_nation_that_still_holds_land_is_untouched_by_a_conquest(self):
        nation_data = {"Victim": nation(faction="Pact"), "Taker": nation()}
        map_data = {"1": province(1, "Victim"), "2": province(2, "Victim")}
        screen = Screen(nation_data, map_data)
        own.conquer_province(screen, map_data["1"], "Taker")
        self.assertEqual(nation_data["Victim"]["faction"], "Pact")

    def test_the_last_province_is_what_retires_it(self):
        nation_data = {"Victim": nation(faction="Pact"), "Taker": nation()}
        map_data = {"1": province(1, "Victim")}
        screen = Screen(nation_data, map_data)
        own.conquer_province(screen, map_data["1"], "Taker")
        self.assertEqual(nation_data["Victim"]["faction"], "")

    def test_the_editor_does_not_dissolve_a_nation_you_are_repainting(self):
        """Zero provinces is what half of a repaint looks like. Losing the
        scenario's treaties for it would be destructive, not tidy."""
        screen = self.build()
        screen.is_editor = True
        own.retire_landless_nation(screen, "Doomed")
        self.assertEqual(self.nation_data["Doomed"]["faction"], "Pact")
        self.assertEqual(self.nation_data["Empire"]["at_war_with"], ["Doomed"])

    def test_the_editor_still_erases_a_created_puppet(self):
        """That half always ran there and is how re-annexation cleans up."""
        screen = self.build(is_created_integrated_puppet=True)
        screen.is_editor = True
        own.retire_landless_nation(screen, "Doomed")
        self.assertNotIn("Doomed", self.nation_data)


class ReleasedPuppetTests(unittest.TestCase):
    """A released puppet is an ordinary country from then on."""

    def test_releasing_forgets_that_it_was_ever_created(self):
        nation_data = {"Master": nation(puppets=["Made"]),
                       "Made": nation(master="Master", puppet_type=c.PUPPET_TYPE_INTEGRATED,
                                      is_created_integrated_puppet=True)}
        puppet_actions.break_puppet_link(nation_data, "Master", "Made")
        self.assertNotIn("is_created_integrated_puppet", nation_data["Made"])
        self.assertEqual(nation_data["Made"]["master"], "")

    def test_and_so_keeps_its_cores_if_conquered_later(self):
        nation_data = {"Master": nation(puppets=["Made"]), "Taker": nation(),
                       "Made": nation(master="Master", puppet_type=c.PUPPET_TYPE_INTEGRATED,
                                      is_created_integrated_puppet=True)}
        map_data = {"1": province(1, "Made", cores=["Made"])}
        puppet_actions.break_puppet_link(nation_data, "Master", "Made")
        screen = Screen(nation_data, map_data)
        own.conquer_province(screen, map_data["1"], "Taker")
        self.assertIn("Made", map_data["1"]["cores"])


class RosterRepairTests(unittest.TestCase):
    """The load-time pass, for saves already in the broken states."""

    def setUp(self):
        self.nation_data = {
            "Reich": nation(faction="Axis", is_faction_leader=True),
            "Vichy": nation(puppets=["Madagascar"]),
            "Madagascar": nation(faction="Axis", master="Vichy",
                                 puppet_type=c.PUPPET_TYPE_INTEGRATED),
            "Ghost": nation(faction="Axis"),
            "Italy": nation(faction="Axis"),
            "Loyal": nation(faction="Axis", master="Reich"),
        }
        # Madagascar holds land, so only the master-mismatch rule can drop it --
        # otherwise this passes whether that rule works or not.
        self.map_data = {"1": province(1, "Reich"), "2": province(2, "Italy"),
                         "3": province(3, "Vichy"), "4": province(4, "Loyal"),
                         "5": province(5, "Madagascar")}

    def repair(self):
        load_map.repair_faction_rosters(self.nation_data, self.map_data)
        return set(queries.get_faction_members("Axis", self.nation_data))

    def test_a_puppet_whose_master_is_not_in_the_faction_is_dropped(self):
        self.assertNotIn("Madagascar", self.repair())

    def test_a_landless_nation_is_dropped(self):
        self.assertNotIn("Ghost", self.repair())

    def test_a_puppet_in_its_masters_faction_is_kept(self):
        self.assertIn("Loyal", self.repair())

    def test_ordinary_members_are_kept(self):
        self.assertEqual(self.repair(), {"Reich", "Italy", "Loyal"})

    def test_it_clears_leadership_too(self):
        self.nation_data["Ghost"]["is_faction_leader"] = True
        self.repair()
        self.assertFalse(self.nation_data["Ghost"]["is_faction_leader"])

    def test_nothing_but_membership_changes(self):
        self.repair()
        self.assertIn("Madagascar", self.nation_data)
        self.assertEqual(self.nation_data["Madagascar"]["master"], "Vichy")

    def test_it_says_so_in_the_global_log(self):
        self.repair()
        log = " ".join(self.nation_data.get("GLOBAL_EVENTS", {}).get("log", []))
        self.assertIn("Madagascar", log)
        self.assertIn("Ghost", log)

    def test_a_clean_save_is_left_exactly_as_it_was(self):
        del self.nation_data["Madagascar"]
        del self.nation_data["Ghost"]
        self.nation_data["Vichy"]["puppets"] = []
        before = {n: d.get("faction") for n, d in self.nation_data.items()}
        self.repair()
        self.assertEqual({n: d.get("faction") for n, d in self.nation_data.items()}, before)

    def test_the_bookkeeping_key_is_not_mistaken_for_a_nation(self):
        self.nation_data["FACTION_WAR_MAPS"] = {}
        self.repair()
        self.assertIn("FACTION_WAR_MAPS", self.nation_data)


if __name__ == "__main__":
    unittest.main()
