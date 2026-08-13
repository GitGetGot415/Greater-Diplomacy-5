"""Covers claim-making as a step of declaring war.

Claims used to live on a tab of their own, reached from the left bar, with
nothing on either screen saying it had anything to do with the war it existed to
start: you claimed land in one place and declared war in another. There is no
Claims tab in a game now -- the picker opens from the declare-war window, aimed
at the nation you are building a case against, and it is the same screen the
editor still uses to browse every claim on the map.
"""

import unittest

import pygame

import data.constants as c
from data import queries
from tests import app_harness


class WarScreenTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app_harness.boot()
        cls.map = app_harness.boot_map()

    def setUp(self):
        self.surface = pygame.Surface((c.SCREEN_WIDTH, c.SCREEN_HEIGHT))

        # The harness map is shared across the run and earlier modules move
        # provinces around on it, so ownership is read live rather than cached.
        landed = [n for n in sorted(queries.get_living_nations(self.map.map_data))
                  if n not in c.UNPLAYABLE_NATIONS and n in self.map.nation_data]
        self.player, self.target = landed[0], landed[1]

        self.map.player_country = self.player
        self.map.active_players = [self.player]
        for nation in (self.player, self.target):
            data = self.map.nation_data[nation]
            data["at_war_with"] = []
            data["pending_diplomacy"] = {}
            data["claims"] = []
            data["claim_queue"] = []
            data["revoke_queue"] = []
            data["wargoals"] = {}
            data["faction"] = ""
            data["master"] = ""

        self.their_prov = next(p for p in self.map.map_data.values()
                               if p.get("owner") == self.target)
        # A tile they hold that we have no historic claim on, so "Take Claims"
        # genuinely starts unavailable.
        self.their_prov["cores"] = [self.target]
        self.map.selected_province = self.their_prov

    def war_screen(self):
        from screens.map_related_screens.war_screen import Declare_War_Screen
        return Declare_War_Screen(self.map, self.target)

    def picker(self):
        from screens.map_related_screens.claims_screen import Claims_Screen
        return Claims_Screen(self.map, self.target)


class DeclareWarScreenTests(WarScreenTestCase):
    def test_it_builds_and_paints(self):
        screen = self.war_screen()
        screen.refresh_ui()
        screen.draw(self.surface)

    def test_take_claims_starts_unavailable_without_one(self):
        self.assertFalse(self.war_screen().wargoal_options[0]["enabled"])

    def test_there_is_a_way_to_go_and_make_one(self):
        labels = [getattr(el, "text", "") for el in self.war_screen().elements]
        self.assertTrue(any("Justify" in str(label) for label in labels),
                        "no route from declaring war to fabricating a claim")

    def test_a_matured_claim_unlocks_take_claims(self):
        self.map.nation_data[self.player]["claims"] = [self.their_prov["id"]]
        self.assertTrue(self.war_screen().wargoal_options[0]["enabled"])

    def test_it_reports_how_long_a_justification_still_has_to_run(self):
        self.map.nation_data[self.player]["claim_queue"] = [
            {"prov_id": self.their_prov["id"], "turns_left": c.CLAIM_TURN_NON_CORE}]

        screen = self.war_screen()
        screen._reread_wargoals()
        screen.refresh_ui()
        screen.draw(self.surface)

        self.assertEqual(len(screen.justifying), 1)

    def test_a_claim_being_justified_elsewhere_is_not_this_wars_business(self):
        mine = next(p for p in self.map.map_data.values() if p.get("owner") == self.player)
        self.map.nation_data[self.player]["claim_queue"] = [
            {"prov_id": mine["id"], "turns_left": 2}]

        screen = self.war_screen()
        screen._reread_wargoals()
        self.assertEqual(screen.justifying, [])


class ClaimPickerTests(WarScreenTestCase):
    def test_it_builds_and_paints(self):
        screen = self.picker()
        screen.refresh_ui()
        screen.draw(self.surface)

    def test_pointed_at_one_nation_there_are_no_view_tabs(self):
        """The overview's three modes are an editor concern; building a case
        against somebody has exactly one question in it."""
        self.assertTrue(self.picker().is_picker)
        self.assertFalse(self.picker().is_global_viewer)

    def test_clicking_their_land_queues_a_justification(self):
        screen = self.picker()
        screen.toggle_claim(self.their_prov)

        queued = [q["prov_id"] for q in self.map.nation_data[self.player]["claim_queue"]]
        self.assertIn(self.their_prov["id"], queued)

    def test_clicking_it_again_takes_it_back_off(self):
        screen = self.picker()
        screen.toggle_claim(self.their_prov)
        screen.toggle_claim(self.their_prov)
        self.assertEqual(self.map.nation_data[self.player]["claim_queue"], [])

    def test_a_justification_takes_turns_to_mature(self):
        screen = self.picker()
        screen.toggle_claim(self.their_prov)
        entry = self.map.nation_data[self.player]["claim_queue"][0]
        self.assertEqual(entry["turns_left"], c.CLAIM_TURN_NON_CORE)

    def test_the_editor_overview_still_browses_every_claim(self):
        from screens.map_related_screens.claims_screen import Claims_Screen

        self.map.is_editor = True
        try:
            overview = Claims_Screen(self.map)
            self.assertFalse(overview.is_picker)
            self.assertTrue(overview.is_global_viewer)
            self.assertEqual(overview.view_mode, "GLOBAL")
            overview.draw(self.surface)
        finally:
            self.map.is_editor = False


if __name__ == "__main__":
    unittest.main()
