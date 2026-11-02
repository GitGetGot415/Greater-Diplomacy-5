"""Faction-screen regression coverage for chairs and long member rosters."""

import unittest
from unittest.mock import patch


import pygame

import data.constants as c
from map_logic.diplomacy import faction_leadership
from screens.game.faction import Faction_Screen
from tests.stub_map_screen import StubMapScreen


class FactionScreenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pygame.init()
        pygame.display.set_mode((c.SCREEN_WIDTH, c.SCREEN_HEIGHT))

    def make_game(self, count=3):
        nations = [f"Nation {i}" for i in range(count)]
        game = StubMapScreen(nations, human_players=(nations[0],))
        game.set_faction("The Pact", nations[0], *nations[1:])
        return game, nations

    def test_leaderless_faction_is_repaired_instead_of_calling_members_puppets(self):
        game, nations = self.make_game()
        for nation in nations:
            game.nation_data[nation]["is_faction_leader"] = False

        self.assertEqual(faction_leadership.repair_leaderless_factions(game), ["The Pact"])
        self.assertTrue(any(game.nation_data[nation]["is_faction_leader"]
                            for nation in nations))

        # The defensive UI fallback remains truthful if an editor creates the
        # transient state between frames.
        screen = Faction_Screen()
        screen.start_faction(game)
        game.nation_data[nations[0]]["is_faction_leader"] = False
        for nation in nations[1:]:
            game.nation_data[nation]["is_faction_leader"] = False
        self.assertEqual(screen._claim_button("").text, "Faction Needs A Leader")

    def open_rename(self, screen):
        with patch("ui.dialogs.ask_string") as ask:
            screen.start_rename()
        return ask

    def rename_button(self, screen):
        return next((el for el in screen.elements if el.text == "Rename Faction"), None)

    def test_rename_button_stays_and_opens_a_popup_with_the_current_name(self):
        game, _nations = self.make_game()
        screen = Faction_Screen()
        screen.start_faction(game)
        ask = self.open_rename(screen)
        self.assertEqual(ask.call_args.kwargs["initial"], "The Pact")
        self.assertEqual(ask.call_args.kwargs["max_length"], c.FACTION_NAME_MAX_LENGTH)
        self.assertIsNotNone(self.rename_button(screen))

    def test_rename_answer_renames_the_faction_and_keeps_the_button(self):
        game, nations = self.make_game()
        screen = Faction_Screen()
        screen.start_faction(game)
        self.open_rename(screen).call_args.args[2]("  New Pact  ")
        self.assertEqual(game.nation_data[nations[1]]["faction"], "New Pact")
        self.assertIsNotNone(self.rename_button(screen))

    def test_cancelled_rename_changes_nothing(self):
        game, nations = self.make_game()
        screen = Faction_Screen()
        screen.start_faction(game)
        self.open_rename(screen).call_args.args[2](None)
        self.assertEqual(game.nation_data[nations[0]]["faction"], "The Pact")

    def test_tournament_rename_records_the_host_command(self):
        game, _nations = self.make_game()
        game.multiplayer_mode = True
        game.multiplayer_pending_faction_renames = []
        screen = Faction_Screen()
        screen.start_faction(game)
        self.open_rename(screen).call_args.args[2]("New Pact")
        self.assertEqual(game.multiplayer_pending_faction_renames,
                         [{"old_name": "The Pact", "new_name": "New Pact"}])

    def test_realtime_rename_is_refused_when_diplomacy_cannot_be_edited(self):
        game, nations = self.make_game()
        game.realtime_multiplayer = True
        screen = Faction_Screen()
        screen.start_faction(game)
        with patch("screens.game.faction.player_diplomacy_actions.can_edit_diplomacy", return_value=False):
            self.open_rename(screen).call_args.args[2]("New Pact")
        self.assertEqual(game.nation_data[nations[0]]["faction"], "The Pact")

    def test_members_do_not_get_a_rename_button(self):
        game, nations = self.make_game()
        game.player_country = nations[1]
        screen = Faction_Screen()
        screen.start_faction(game)
        self.assertIsNone(self.rename_button(screen))

    def test_large_roster_is_scrollable_and_draws_a_flag_for_each_member(self):
        game, nations = self.make_game(30)
        screen = Faction_Screen()
        screen.start_faction(game)
        surface = pygame.Surface((c.SCREEN_WIDTH, c.SCREEN_HEIGHT))

        with patch("screens.game.faction.draw_flag_centered",
                   side_effect=lambda _surface, _nation, _data, x, _y, _h: x + 24) as flags:
            screen.additional_draw(surface)

        self.assertLess(screen.max_scroll, 0)
        self.assertEqual(flags.call_count, len(nations))

        screen.additional_events(pygame.event.Event(pygame.MOUSEWHEEL, y=-1))
        self.assertLess(screen.scroll_y, 0)

    def test_roster_is_sorted_by_visible_country_name(self):
        game, nations = self.make_game()
        game.nation_data[nations[0]]["name"] = "Zulu"
        game.nation_data[nations[1]]["name"] = "alpha"
        game.nation_data[nations[2]]["name"] = "Bravo"
        screen = Faction_Screen()
        screen.start_faction(game)
        surface = pygame.Surface((c.SCREEN_WIDTH, c.SCREEN_HEIGHT))

        with patch("screens.game.faction.draw_flag_centered",
                   side_effect=lambda _surface, _nation, _data, x, _y, _h: x + 24) as flags:
            screen.additional_draw(surface)

        drawn_members = [call.args[1] for call in flags.call_args_list]
        self.assertEqual(drawn_members, [nations[1], nations[2], nations[0]])

    def test_roster_identifies_a_landless_member_as_a_government_in_exile(self):
        game, nations = self.make_game()
        exile = nations[1]
        province = game.home_of(exile)
        del game.map_data[str(province["id"])]
        del game.id_to_province[province["id"]]
        screen = Faction_Screen()
        screen.start_faction(game)

        self.assertEqual(screen._member_label(exile, game.nation_data),
                         f"{exile} (Government in Exile)")


if __name__ == "__main__":
    unittest.main()
