"""Faction-screen regression coverage for chairs and long member rosters."""

import os
import sys
import unittest
from unittest.mock import patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame

import data.constants as c
from map_logic.diplomacy import faction_leadership
from screens.map_related_screens.faction import Faction_Screen
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

    def test_large_roster_is_scrollable_and_draws_a_flag_for_each_member(self):
        game, nations = self.make_game(30)
        screen = Faction_Screen()
        screen.start_faction(game)
        surface = pygame.Surface((c.SCREEN_WIDTH, c.SCREEN_HEIGHT))

        with patch("screens.map_related_screens.faction.draw_flag_centered",
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

        with patch("screens.map_related_screens.faction.draw_flag_centered",
                   side_effect=lambda _surface, _nation, _data, x, _y, _h: x + 24) as flags:
            screen.additional_draw(surface)

        drawn_members = [call.args[1] for call in flags.call_args_list]
        self.assertEqual(drawn_members, [nations[1], nations[2], nations[0]])


if __name__ == "__main__":
    unittest.main()
