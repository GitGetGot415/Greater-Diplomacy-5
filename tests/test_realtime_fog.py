"""Regression coverage for real-time lobby-to-map visibility initialization."""

import unittest

from tests import app_harness


class RealtimeFogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app_harness.boot()
        cls.map = app_harness.boot_map()

    def test_fog_rebuilds_after_lobby_country_assignment(self):
        """Scenario loading suppresses fog until country selection has ended."""
        game_map = self.map
        original_selection_mode = game_map.selection_mode
        try:
            # This is the state while the scenario map constructor builds its
            # initial surfaces for the country picker.
            game_map.selection_mode = True
            game_map.refresh_map_layers("fog")
            self.assertIsNone(game_map.fog_map)

            # A real-time player already chose a country in the lobby.  The
            # first playable frame must rebuild fog after clearing that mode.
            game_map.selection_mode = False
            game_map.refresh_map_layers("fog")
            self.assertIsNotNone(game_map.fog_map)
            self.assertIsNotNone(game_map.visible_provinces)
        finally:
            game_map.selection_mode = original_selection_mode
            game_map.refresh_map_layers("fog")


if __name__ == "__main__":
    unittest.main()
