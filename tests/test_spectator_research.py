"""A spectator picks a nation and gets that nation's real tech tree.

The R&D button used to hand a spectator the scenario-authoring checkbox list,
which says what a nation has finished and nothing about what it is working on.
The tree itself was unreachable for them because it read player_country, and
the literal "Spectator" is not a key in nation_data.

The property under test is that the screen serves whoever it is pointed at and
nobody else -- in particular that a player's path is unchanged, since they use
this screen every turn and a spectator uses it never.
"""

import unittest

import data.constants as c
from tests import app_harness


class SubjectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.controller, cls.surface = app_harness.boot()
        cls.map = app_harness.boot_map()
        cls.screen = cls.controller.states["RESEARCH"]

    def setUp(self):
        self.saved = {a: getattr(self.map, a, None)
                      for a in ("player_country", "viewing_research_country", "tactical_mode")}
        self.addCleanup(self.restore)
        self.map.viewing_research_country = ""

    def restore(self):
        for attr, value in self.saved.items():
            setattr(self.map, attr, value)

    def others(self, count=1):
        """Living nations that are not the player, for pointing the screen at."""
        from data import queries
        living = sorted(queries.get_living_nations(self.map.map_data))
        return [n for n in living if n != self.map.player_country][:count]

    def spectate(self, nation):
        self.map.player_country = "Spectator"
        self.map.viewing_research_country = nation
        self.screen.start_research(self.map)

    # -- who the screen is looking at -----------------------------------

    def test_a_player_sees_their_own_research(self):
        self.screen.start_research(self.map)
        self.assertEqual(self.screen.subject, self.map.player_country)

    def test_a_player_is_unaffected_by_a_stale_choice(self):
        """The picker's leftovers must not follow a player into their own tree."""
        self.map.viewing_research_country = ""
        self.screen.start_research(self.map)
        self.assertEqual(self.screen.subject, self.map.player_country)

    def test_a_spectator_sees_the_nation_they_picked(self):
        target = self.others()[0]
        self.spectate(target)
        self.assertEqual(self.screen.subject, target)
        self.assertIs(self.screen.subject_data, self.map.nation_data[target])

    def test_the_screen_builds_and_paints_for_someone_else(self):
        """It used to KeyError on "Spectator" before reaching any of this."""
        self.spectate(self.others()[0])
        self.screen.refresh_ui()
        self.screen.draw(self.surface)
        self.assertTrue(self.screen.elements)

    def test_two_nations_do_not_share_a_queue(self):
        picks = self.others(2)
        if len(picks) < 2:
            self.skipTest("scenario has only one non-player nation")
        first, second = picks
        self.spectate(first)
        before_second = list(self.map.nation_data[second].get("research_queue", []))

        tech = next(iter(self.screen.tech_tree))
        self.screen.start_or_resume_research(tech)

        self.assertEqual(list(self.map.nation_data[second].get("research_queue", [])),
                         before_second, "queuing for one nation touched another")
        self.assertIn(tech, [p["tech_name"] for p in
                             self.map.nation_data[first].get("research_queue", [])])

    # -- the switch -----------------------------------------------------

    def test_a_spectator_may_edit_by_default(self):
        self.spectate(self.others()[0])
        self.assertTrue(self.screen.can_edit)
        self.assertTrue(c.SPECTATOR_CAN_EDIT_RESEARCH,
                        "the shipped default is meant to preserve what a spectator could already do")

    def test_with_the_switch_off_nothing_can_be_queued(self):
        target = self.others()[0]
        self.spectate(target)
        self.map.nation_data[target]["research_queue"] = []

        original = c.SPECTATOR_CAN_EDIT_RESEARCH
        c.SPECTATOR_CAN_EDIT_RESEARCH = False
        try:
            self.assertFalse(self.screen.can_edit)
            self.screen.start_or_resume_research(next(iter(self.screen.tech_tree)))
            self.assertEqual(self.map.nation_data[target]["research_queue"], [])
        finally:
            c.SPECTATOR_CAN_EDIT_RESEARCH = original

    def test_with_the_switch_off_the_modal_offers_no_action(self):
        target = self.others()[0]
        self.spectate(target)
        original = c.SPECTATOR_CAN_EDIT_RESEARCH
        c.SPECTATOR_CAN_EDIT_RESEARCH = False
        try:
            self.screen.active_modal = {"status": "AVAILABLE",
                                        "tech_key": next(iter(self.screen.tech_tree))}
            self.screen.refresh_ui()
            labels = [getattr(el, "text", "") for el in self.screen.elements]
            self.assertIn("Spectator: Read Only", labels)
            self.assertNotIn("Start Research", labels)
        finally:
            c.SPECTATOR_CAN_EDIT_RESEARCH = original
            self.screen.active_modal = None

    def test_a_player_still_gets_the_action_button(self):
        self.screen.start_research(self.map)
        self.map.tactical_mode = False
        self.map.nation_data[self.map.player_country]["research_queue"] = []
        self.screen.active_modal = {"status": "AVAILABLE",
                                    "tech_key": next(iter(self.screen.tech_tree))}
        try:
            self.screen.refresh_ui()
            labels = [getattr(el, "text", "") for el in self.screen.elements]
            self.assertIn("Start Research", labels)
            self.assertNotIn("Spectator: Read Only", labels)
        finally:
            self.screen.active_modal = None

    def test_tactical_mode_is_still_read_only(self):
        """The switch was added beside this rule, not on top of it."""
        self.screen.start_research(self.map)
        self.map.tactical_mode = True
        self.assertFalse(self.screen.can_edit)


class PickerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app_harness.boot()
        cls.map = app_harness.boot_map()

    def test_the_picker_offers_living_nations_and_routes_to_the_tree(self):
        from data import queries
        from ui import editor_menus

        captured = {}

        def fake_selector(game_state, title, prompt, items, on_confirm):
            captured["items"] = items
            captured["confirm"] = on_confirm

        original = queries.open_listbox_selector
        queries.open_listbox_selector = fake_selector
        saved = (getattr(self.map, "viewing_research_country", None),
                 self.map.next_state, self.map.done)
        try:
            editor_menus.spec_select_research_country(self.map)
            self.assertEqual(captured["items"],
                             sorted(queries.get_living_nations(self.map.map_data)))

            captured["confirm"](captured["items"][0])
            self.assertEqual(self.map.viewing_research_country, captured["items"][0])
            self.assertEqual(self.map.next_state, "RESEARCH")
            self.assertTrue(self.map.done)
        finally:
            queries.open_listbox_selector = original
            self.map.viewing_research_country, self.map.next_state, self.map.done = saved


class AppearanceSwitchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.controller, cls.surface = app_harness.boot()
        cls.map = app_harness.boot_map()
        cls.screen = cls.controller.states["EDIT_COUNTRY"]

    def setUp(self):
        self.saved_player = self.map.player_country
        self.addCleanup(lambda: setattr(self.map, "player_country", self.saved_player))

    def test_a_spectator_may_edit_appearance_by_default(self):
        self.map.player_country = "Spectator"
        self.screen.map_screen = self.map
        self.assertTrue(self.screen.can_edit)

    def test_with_the_switch_off_saving_writes_nothing(self):
        target = getattr(self.map, "editing_country", None)
        self.addCleanup(lambda: setattr(self.map, "editing_country", target)
                        if target is not None else None)
        self.map.player_country = "Spectator"
        self.screen.start_editor(self.map)

        before = dict(self.map.nation_data[self.screen.editing_country])
        original = c.SPECTATOR_CAN_EDIT_APPEARANCE
        c.SPECTATOR_CAN_EDIT_APPEARANCE = False
        try:
            self.screen.country_name = "Renamed By A Spectator"
            self.screen.save_and_exit()
            after = self.map.nation_data[self.screen.editing_country]
            self.assertEqual(after.get("name"), before.get("name"))
        finally:
            c.SPECTATOR_CAN_EDIT_APPEARANCE = original

    def test_with_the_switch_off_the_save_button_is_inert(self):
        self.map.player_country = "Spectator"
        self.screen.start_editor(self.map)
        original = c.SPECTATOR_CAN_EDIT_APPEARANCE
        c.SPECTATOR_CAN_EDIT_APPEARANCE = False
        try:
            self.screen.refresh_ui()
            self.assertEqual(self.screen.btn_save.text, "Spectator: Read Only")
        finally:
            c.SPECTATOR_CAN_EDIT_APPEARANCE = original

    def test_a_player_keeps_a_working_save_button(self):
        self.screen.start_editor(self.map)
        self.screen.refresh_ui()
        self.assertEqual(self.screen.btn_save.text, "Save Changes")


if __name__ == "__main__":
    unittest.main()
