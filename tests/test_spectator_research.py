"""A spectator picks a nation and gets that nation's real tech tree.

The R&D button used to hand a spectator the scenario-authoring checkbox list,
which says what a nation has finished and nothing about what it is working on.
The tree itself was unreachable for them because it read player_country, and
the literal "Spectator" is not a key in nation_data.

The screen shows the selected country. View cannot change research.
Edit changes completed levels immediately. Normal players keep their research queue controls.
"""

import unittest
import pygame
from copy import deepcopy
from contextlib import ExitStack
from unittest.mock import patch

import data.constants as c
from data import queries
from tests import app_harness


class SubjectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.controller, cls.surface = app_harness.boot()
        cls.map = app_harness.boot_map()
        cls.screen = cls.controller.states["RESEARCH"]

    def setUp(self):
        self.addCleanup(self.screen.start_research, self.map)
        tree = {"test_research": {"display_name": "Test research", "category": "INDUSTRY",
                                  "years": [1900], "max_lvl": 1, "cost": 100, "req": {}}}
        self.enterContext(patch.object(queries, "get_tech_tree", return_value=tree))
        nation_data = deepcopy(self.map.nation_data)
        for country in nation_data.values():
            country.update(research={}, research_queue=[], research_progress={})
        self.enterContext(patch.object(self.map, "nation_data", nation_data))
        self.enterContext(patch.object(self.map, "is_editor", False))
        self.enterContext(patch.object(self.map, "multiplayer_mode", False, create=True))
        self.enterContext(patch.object(self.map, "realtime_multiplayer", False, create=True))
        self.enterContext(patch.object(self.map, "viewing_research_mode", "VIEW", create=True))
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

    def spectate(self, nation, mode="VIEW"):
        self.map.player_country = "Spectator"
        self.map.viewing_research_country = nation
        self.map.viewing_research_mode = mode
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

    def test_edit_changes_only_selected_country_and_does_not_queue_research(self):
        picks = self.others(2)
        if len(picks) < 2:
            self.skipTest("scenario has only one non-player nation")
        first, second = picks
        self.spectate(first, "EDIT")
        before_second = deepcopy(self.map.nation_data[second])

        tech = next(iter(self.screen.tech_tree))
        self.screen.open_modal({"tech_key": tech, "level": 1})

        self.assertEqual(self.map.nation_data[second],
                         before_second, "editing one nation touched another")
        self.assertEqual(self.map.nation_data[first]["research"], {tech: 1})
        self.assertEqual(self.map.nation_data[first]["research_queue"], [])
        self.screen.open_modal({"tech_key": tech, "level": 1})
        self.assertEqual(self.map.nation_data[first]["research"], {tech: 0})

    # -- the switch -----------------------------------------------------

    def test_a_spectator_may_edit_after_selecting_edit(self):
        self.spectate(self.others()[0], "EDIT")
        self.assertTrue(self.screen.can_edit)
        self.assertTrue(c.SPECTATOR_CAN_EDIT_RESEARCH,
                        "the shipped default is meant to preserve what a spectator could already do")

    def test_with_the_switch_off_nothing_can_be_queued(self):
        target = self.others()[0]
        self.spectate(target, "EDIT")
        self.map.nation_data[target]["research_queue"] = []

        original = c.SPECTATOR_CAN_EDIT_RESEARCH
        c.SPECTATOR_CAN_EDIT_RESEARCH = False
        try:
            self.assertFalse(self.screen.can_edit)
            self.screen.start_or_resume_research(next(iter(self.screen.tech_tree)))
            self.screen.open_modal({"tech_key": next(iter(self.screen.tech_tree)), "level": 1})
            self.assertEqual(self.map.nation_data[target]["research_queue"], [])
            self.assertEqual(self.map.nation_data[target]["research"], {})
        finally:
            c.SPECTATOR_CAN_EDIT_RESEARCH = original

    def test_with_the_switch_off_the_modal_offers_no_action(self):
        target = self.others()[0]
        self.spectate(target)
        original = c.SPECTATOR_CAN_EDIT_RESEARCH
        c.SPECTATOR_CAN_EDIT_RESEARCH = False
        try:
            self.screen.active_modal = {"status": "AVAILABLE",
                                        "tech_key": next(iter(self.screen.tech_tree)),
                                        "level": 1, "display_name": self.screen.get_display_name(
                                            next(iter(self.screen.tech_tree)), 1)}
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
                                    "tech_key": next(iter(self.screen.tech_tree)),
                                    "level": 1, "display_name": self.screen.get_display_name(
                                        next(iter(self.screen.tech_tree)), 1)}
        try:
            self.screen.refresh_ui()
            labels = [getattr(el, "text", "") for el in self.screen.elements]
            self.assertIn("Start Research", labels)
            self.assertNotIn("Spectator: Read Only", labels)
        finally:
            self.screen.active_modal = None

    def test_view_mode_opens_details_but_cannot_change_research(self):
        target = self.others()[0]
        self.spectate(target)
        before = deepcopy(self.map.nation_data[target])
        button = next(button for button in self.screen.elements if getattr(button, "is_tech_node", False))
        button.callback()
        self.assertIsNotNone(self.screen.active_modal)
        self.assertFalse(self.screen.can_edit)
        self.screen.start_or_resume_research("test_research")
        self.screen.pause_research("test_research")
        self.screen.toggle_editor_tech("test_research", 1)
        self.assertEqual(self.map.nation_data[target], before)

    def test_edit_callback_rechecks_local_mode_and_living_country(self):
        target = self.others()[0]
        self.spectate(target, "EDIT")
        button = next(button for button in self.screen.elements if getattr(button, "is_tech_node", False))
        for flags in ({"tactical_mode": True}, {"multiplayer_mode": True},
                      {"realtime_multiplayer": True}, {"player_country": target}):
            with self.subTest(flags=flags), ExitStack() as stack:
                for key, value in flags.items():
                    stack.enter_context(patch.object(self.map, key, value))
                button.callback()
                self.assertEqual(self.map.nation_data[target]["research"], {})
        with patch.object(self.map, "map_data", {}):
            button.callback()
            self.assertEqual(self.map.nation_data[target]["research"], {})

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

    def setUp(self):
        for name, value in (("player_country", "Spectator"), ("is_editor", False),
                            ("tactical_mode", False), ("multiplayer_mode", False),
                            ("realtime_multiplayer", False), ("viewing_research_country", ""),
                            ("viewing_research_mode", "VIEW"), ("next_state", "MAP"), ("done", False)):
            self.enterContext(patch.object(self.map, name, value, create=True))

    def picker(self):
        from screens.map_related_screens.research import ResearchCountrySelectScreen
        return ResearchCountrySelectScreen(self.map)

    def test_the_picker_offers_living_nations_and_routes_view_and_edit_to_the_tree(self):
        from ui import editor_menus
        from ui import screen_runner
        for mode in ("VIEW", "EDIT"):
            with self.subTest(mode=mode), patch.object(screen_runner, "_run_pygame_sub_screen") as launch:
                editor_menus.spec_select_research_country(self.map)
                picker = launch.call_args.args[1]
                self.assertEqual(picker.items, queries.country_picker_items(
                    sorted(queries.get_living_nations(self.map.map_data)), self.map.nation_data))
                picker.set_mode(mode)
                picker.select(picker.items[0])
                self.assertEqual(self.map.viewing_research_country, picker.items[0][1])
                self.assertEqual(self.map.viewing_research_mode, mode)
                self.assertEqual(self.map.next_state, "RESEARCH")
                self.assertTrue(self.map.done)

    def test_mode_buttons_fit_above_search_and_preserve_filter(self):
        for size in ((c.SCREEN_WIDTH, c.SCREEN_HEIGHT), (1280, 720)):
            with self.subTest(size=size), patch.object(c, "SCREEN_WIDTH", size[0]), patch.object(c, "SCREEN_HEIGHT", size[1]):
                picker = self.picker()
                self.assertEqual(picker.mode, "VIEW")
                picker.search_text = picker.items[0][0]
                picker.refresh_ui()
                before = list(picker.visible_items)
                buttons = {button.text: button for button in picker.elements if button.text in ("View", "Edit")}
                self.assertEqual(set(buttons), {"View", "Edit"})
                for button in buttons.values():
                    self.assertTrue(picker.panel_rect.contains(button.rect))
                    self.assertLess(button.rect.bottom, picker.panel_rect.y + picker.SEARCH_BOX_Y)
                    self.assertFalse(button.rect.colliderect(picker.scroll_content_rect))
                self.assertFalse(buttons["View"].rect.colliderect(buttons["Edit"].rect))
                buttons["Edit"].callback()
                self.assertEqual(picker.mode, "EDIT")
                self.assertEqual(picker.visible_items, before)
                picker.draw(pygame.Surface(size))
                picker._handle_search_key(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN, unicode="\r"))
                self.assertEqual(self.map.viewing_research_mode, "EDIT")

    def test_disabled_edit_and_stale_selection_cannot_open_edit_mode(self):
        picker = self.picker()
        picker.set_mode("EDIT")
        with patch.object(c, "SPECTATOR_CAN_EDIT_RESEARCH", False):
            picker.select(picker.items[0])
            self.assertFalse(self.map.done)
            self.assertEqual(picker.mode, "VIEW")
            picker.set_mode("EDIT")
            self.assertEqual(picker.mode, "VIEW")
            picker.select(picker.items[0])
            self.assertEqual(self.map.viewing_research_mode, "VIEW")

    def test_network_and_tactical_spectators_can_only_select_view(self):
        for flag in ("multiplayer_mode", "realtime_multiplayer", "tactical_mode"):
            with self.subTest(flag=flag), patch.object(self.map, flag, True):
                picker = self.picker()
                picker.set_mode("EDIT")
                self.assertEqual(picker.mode, "VIEW")


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
