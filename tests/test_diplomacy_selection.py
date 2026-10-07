"""Diplomacy callbacks require a current country selection."""

import copy
import unittest
from unittest.mock import patch

from map_logic.diplomacy import player_diplomacy_actions as actions
from tests.stub_map_screen import StubMapScreen


class DiplomacySelectionTests(unittest.TestCase):
    def setUp(self):
        self.game = StubMapScreen(["A", "B"])
        self.game.selected_province = None
        self.game.mail_draft_text = ""
        self.game.mail_input_active = False

    def test_country_callbacks_reject_missing_or_removed_targets(self):
        callbacks = (
            actions.handle_declare_war,
            actions.handle_ceasefire,
            lambda game: actions.handle_specific_action(game, "REQ_MILITARY_ACCESS"),
            actions.handle_guarantee,
            actions.handle_military_attache,
            actions.handle_revoke_foreign_military_attache,
            actions.handle_accept_req,
            actions.handle_reject_req,
            actions.handle_join_wars,
            actions.handle_call_to_arms,
            actions.handle_send_volunteers,
            actions.handle_recall_volunteers,
            actions.handle_send_home_foreign_volunteers,
            actions.handle_withdraw_volunteer_offer,
        )
        for selection in (None, {}, {"owner": "Removed"}, {"owner": "Unclaimed"}):
            for callback in callbacks:
                with self.subTest(selection=selection, callback=callback):
                    self.game.selected_province = selection
                    self.game.feedback.clear()
                    before = copy.deepcopy(self.game.nation_data)
                    callback(self.game)
                    self.assertEqual(self.game.nation_data, before)
                    self.assertTrue(self.game.feedback)

    def test_valid_selection_still_opens_war_menu(self):
        self.game.selected_province = self.game.home_of("B")
        with patch("screens.map_related_screens.war_screen.open_wargoal_selection_menu") as opened:
            actions.handle_declare_war(self.game)
        opened.assert_called_once_with(self.game, "B")

    def test_valid_enemy_selection_still_opens_peace_menu(self):
        self.game.selected_province = self.game.home_of("B")
        self.game.nation_data["A"]["at_war_with"] = ["B"]
        self.game.nation_data["B"]["at_war_with"] = ["A"]
        with patch("screens.map_related_screens.deal_screen.open_peace_menu") as opened:
            actions.handle_declare_war(self.game)
        opened.assert_called_once_with(self.game, "B")

    def test_message_replies_keep_their_explicit_target_without_selection(self):
        self.game.nation_data["B"]["pending_diplomacy"]["A"] = {
            "action": "REQ_MILITARY_ACCESS", "turns": 1,
        }
        for callback in (actions.handle_accept_req, actions.handle_reject_req):
            with self.subTest(callback=callback):
                with patch.object(actions, "_answer_incoming_request") as answered:
                    callback(self.game, "B", "Reply")
                self.assertEqual(answered.call_args.args[1], "B")

    def test_submitted_realtime_turn_remains_locked(self):
        from types import SimpleNamespace

        self.game.selected_province = self.game.home_of("B")
        self.game.realtime_multiplayer = True
        self.game.realtime_player_id = "local"
        self.game.realtime_session = SimpleNamespace(
            phase="TURN", players={"local": SimpleNamespace(submitted=True, eliminated=False)})
        with patch("screens.map_related_screens.war_screen.open_wargoal_selection_menu") as opened:
            actions.handle_declare_war(self.game)
        opened.assert_not_called()
        self.assertTrue(self.game.feedback)


if __name__ == "__main__":
    unittest.main()
