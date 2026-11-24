"""Regression coverage for real-time lobby-to-map visibility initialization."""

import unittest
from unittest.mock import patch

from data import queries
from tests import app_harness


class RealtimeFogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app_harness.boot()
        cls.map = app_harness.boot_map()

    def test_fog_rebuilds_after_lobby_country_assignment(self):
        """Scenario loading suppresses fog until country selection has ended."""
        game_map = self.map
        original_selection_mode = game_map.session.selection_mode
        try:
            # This is the state while the scenario map constructor builds its
            # initial surfaces for the country picker.
            game_map.session.selection_mode = True
            game_map.refresh_map_layers("fog")
            self.assertIsNone(game_map.fog_map)

            # A real-time player already chose a country in the lobby.  The
            # first playable frame must rebuild fog after clearing that mode.
            game_map.session.selection_mode = False
            game_map.refresh_map_layers("fog")
            self.assertIsNotNone(game_map.fog_map)
            self.assertIsNotNone(game_map.visible_provinces)
        finally:
            game_map.session.selection_mode = original_selection_mode
            game_map.refresh_map_layers("fog")

    def test_snapshot_keeps_my_choice_and_only_the_peace_offer_delivered_to_me(self):
        game = self.map
        owner = game.session.player_country
        enemy = next(country for country in game.world.nation_data if country != owner and queries.is_playable(country, game.world.nation_data))
        country = game.world.nation_data[enemy]
        offer = {"action": "PEACE_TREATY", "turns": 1, "request_id": "visible-offer", "escrow": {"materials": 20}}
        pending = {owner: offer, "Private": {"action": "PEACE_TREATY", "turns": 0}}
        with patch.dict(country, pending_diplomacy=pending, peace_choices={owner: {"selected": enemy}}), \
                patch.dict(game.world.nation_data[owner], peace_choices={enemy: {"selected": owner}}):
            snapshot = queries.player_snapshot_projection(game, queries.build_save_dict(game), owner)
        self.assertEqual(snapshot["nation_data"][owner]["peace_choices"][enemy]["selected"], owner)
        self.assertNotIn("peace_choices", snapshot["nation_data"][enemy])
        self.assertEqual(snapshot["nation_data"][enemy]["pending_diplomacy"], {
            owner: {"action": "PEACE_TREATY", "turns": 1, "request_id": "visible-offer"}})


if __name__ == "__main__":
    unittest.main()
