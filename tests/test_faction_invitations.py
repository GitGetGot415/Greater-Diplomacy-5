"""Faction invitation permissions at drafting, delivery, and acceptance."""

import copy
import unittest
from unittest import mock

from data import queries
from data.io.realtime_multiplayer import MapRealtimeDriver, RealtimeError
from map_logic.diplomacy import diplomacy_processor, faction_leadership, player_diplomacy_actions
from tests.stub_map_screen import StubMapScreen
from ui import spectator_menus


class FactionInvitationTests(unittest.TestCase):
    def setUp(self):
        self.game = StubMapScreen(["Leader", "Member", "Outsider"],
                                  human_players=["Leader", "Member", "Outsider"])
        self.game.set_faction("Pact", "Leader", "Member")
        self.game.selected_province = self.game.home_of("Outsider")
        self.game.mail_draft_text = "Please join."

    def raw_invitation(self, sender):
        self.game.nation_data[sender]["pending_diplomacy"]["Outsider"] = {
            "action": "FACTION_INVITE", "turns": 0, "timer": 0, "message": "Please join."}

    def test_member_cannot_draft_an_invitation_through_the_player_handler(self):
        self.game.player_country = "Member"
        player_diplomacy_actions.handle_specific_action(self.game, "FACTION_INVITE")
        self.assertEqual(self.game.pending_action("Member", "Outsider"), "")
        self.assertEqual(self.game.feedback[-1], "Only a faction leader may invite members.")

    def test_join_request_to_a_member_directs_the_player_to_the_leader(self):
        self.game.player_country = "Outsider"
        self.game.selected_province = self.game.home_of("Member")
        player_diplomacy_actions.handle_specific_action(self.game, "JOIN_FACTION_REQ")
        self.assertEqual(self.game.pending_action("Outsider", "Member"), "")
        self.assertIn("faction leader", self.game.feedback[-1])
        self.assertEqual(self.game.mail_draft_text, "Please join.")

    def test_join_request_to_the_leader_can_be_sent_and_undone(self):
        self.game.player_country = "Outsider"
        self.game.selected_province = self.game.home_of("Leader")
        player_diplomacy_actions.handle_specific_action(self.game, "JOIN_FACTION_REQ")
        self.assertEqual(self.game.pending_action("Outsider", "Leader"), "JOIN_FACTION_REQ")
        faction_leadership.transfer(self.game.nation_data, "Leader", "Member")
        player_diplomacy_actions.handle_specific_action(self.game, "JOIN_FACTION_REQ")
        self.assertEqual(self.game.pending_action("Outsider", "Leader"), "")

    def test_imported_join_request_to_a_member_is_not_delivered(self):
        self.game.nation_data["Outsider"]["pending_diplomacy"]["Member"] = {
            "action": "JOIN_FACTION_REQ", "turns": 0, "timer": 0, "message": "Let us join."}
        self.game.run_turn()
        self.assertEqual(self.game.inbound("Member", "Outsider"), [])
        self.assertEqual(self.game.pending_action("Outsider", "Member"), "")

    def test_leader_can_invite_and_the_outsider_can_join_at_peace(self):
        player_diplomacy_actions.handle_specific_action(self.game, "FACTION_INVITE")
        self.game.run_turn()
        self.assertTrue(self.game.inbound("Outsider", "Leader"))
        self.game.player_country = "Outsider"
        player_diplomacy_actions.handle_accept_req(self.game, "Leader", "Accepted.")
        self.game.run_turn()
        self.assertEqual(self.game.nation_data["Outsider"]["faction"], "Pact")
        self.assertFalse(self.game.nation_data["Outsider"]["is_faction_leader"])
        self.assertTrue(all(not self.game.nation_data[n]["at_war_with"]
                            for n in ("Leader", "Member", "Outsider")))

    def test_legacy_member_draft_is_removed_before_delivery(self):
        self.raw_invitation("Member")
        self.game.run_turn()
        self.assertEqual(self.game.inbound("Outsider", "Member"), [])
        self.assertEqual(self.game.pending_action("Member", "Outsider"), "")

    def test_losing_leadership_before_sending_prevents_delivery(self):
        self.game.propose("Leader", "Outsider", "FACTION_INVITE")
        faction_leadership.transfer(self.game.nation_data, "Leader", "Member")
        self.game.run_turn()
        self.assertEqual(self.game.inbound("Outsider", "Leader"), [])
        self.assertEqual(self.game.pending_action("Leader", "Outsider"), "")

    def test_former_leader_can_cancel_an_unsent_invitation(self):
        self.game.propose("Leader", "Outsider", "FACTION_INVITE")
        faction_leadership.transfer(self.game.nation_data, "Leader", "Member")
        player_diplomacy_actions.handle_specific_action(self.game, "FACTION_INVITE")
        self.assertEqual(self.game.pending_action("Leader", "Outsider"), "")

    def test_losing_leadership_after_sending_prevents_acceptance(self):
        self.game.propose("Leader", "Outsider", "FACTION_INVITE")
        self.game.run_turn()
        faction_leadership.transfer(self.game.nation_data, "Leader", "Member")
        self.game.player_country = "Outsider"
        player_diplomacy_actions.handle_accept_req(self.game, "Leader", "Accepted.")
        self.game.run_turn()
        self.assertEqual(self.game.nation_data["Outsider"]["faction"], "")

    def test_crossing_request_cannot_bypass_the_invitation_permission(self):
        for joiner_first in (False, True):
            with self.subTest(joiner_first=joiner_first):
                game = StubMapScreen(["Leader", "Member", "Outsider"],
                                     human_players=["Leader", "Member", "Outsider"])
                game.set_faction("Pact", "Leader", "Member")
                game.nation_data["Member"]["pending_diplomacy"]["Outsider"] = {
                    "action": "FACTION_INVITE", "turns": 0, "timer": 0, "message": "Join us."}
                game.nation_data["Outsider"]["pending_diplomacy"]["Member"] = {
                    "action": "JOIN_FACTION_REQ", "turns": 0, "timer": 0, "message": "Let us join."}
                if joiner_first:
                    game.nation_data = dict(reversed(list(game.nation_data.items())))
                game.run_turn()
                self.assertEqual(game.nation_data["Outsider"]["faction"], "")
                self.assertEqual(game.inbound("Outsider", "Member"), [])

    def test_realtime_server_rejects_member_and_stale_leader_drafts(self):
        driver = MapRealtimeDriver(self.game)
        command = {"type": "country_diplomacy", "pending": {
            "Outsider": {"action": "FACTION_INVITE"}}}
        canonical = driver.validate_draft("Leader", [command])
        self.assertEqual(canonical[0]["pending"]["Outsider"]["action"], "FACTION_INVITE")
        with self.assertRaises(RealtimeError):
            driver.validate_draft("Member", [command])
        faction_leadership.transfer(self.game.nation_data, "Leader", "Member")
        with self.assertRaises(RealtimeError):
            driver.validate_draft("Leader", [command])
        self.assertEqual(self.game.pending_action("Leader", "Outsider"), "")
        # Removing an unsent draft remains permitted after leadership changes.
        driver.validate_draft("Leader", [{"type": "country_diplomacy", "pending": {}}])

    def test_realtime_join_requests_must_address_the_current_leader(self):
        driver = MapRealtimeDriver(self.game)
        command = {"type": "country_diplomacy", "pending": {
            "Leader": {"action": "JOIN_FACTION_REQ"}}}
        driver.validate_draft("Outsider", [command])
        with self.assertRaisesRegex(RealtimeError, "faction leader"):
            driver.validate_draft("Outsider", [{"type": "country_diplomacy", "pending": {
                "Member": {"action": "JOIN_FACTION_REQ"}}}])
        faction_leadership.transfer(self.game.nation_data, "Leader", "Member")
        with self.assertRaisesRegex(RealtimeError, "faction leader"):
            driver.validate_draft("Outsider", [command])

    def test_spectator_cannot_invite_from_a_member_or_a_stale_picker(self):
        self.game.selected_province = self.game.home_of("Member")
        with mock.patch.object(queries, "open_listbox_selector") as selector:
            spectator_menus.spec_invite_faction(self.game)
            selector.assert_not_called()
            self.game.selected_province = self.game.home_of("Leader")
            spectator_menus.spec_invite_faction(self.game)
            callback = selector.call_args.args[-1]
            faction_leadership.transfer(self.game.nation_data, "Leader", "Member")
            callback("Outsider")
        self.assertEqual(self.game.nation_data["Outsider"]["faction"], "")


class FactionInvitationButtonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests import app_harness
        cls.game = app_harness.boot_map()

    def setUp(self):
        from screens.menu_screens import map as map_module
        self.map_module = map_module
        game = self.game
        countries = sorted(queries.get_living_nations(game.map_data))[:3]
        self.leader, self.member, self.outsider = countries
        for country in countries:
            original = game.nation_data[country]
            self.addCleanup(game.nation_data.__setitem__, country, original)
            game.nation_data[country] = copy.deepcopy(original)
            game.nation_data[country].update(
                faction="", is_faction_leader=False, master="", at_war_with=[],
                pending_diplomacy={}, diplo_responses={})
        game.nation_data[self.leader].update(faction="Invitation test faction", is_faction_leader=True)
        game.nation_data[self.member]["faction"] = "Invitation test faction"
        fields = dict(player_country=self.member, active_players=countries,
                      selected_province=next(p for p in game.map_data.values()
                                             if p.get("owner") == self.outsider),
                      selection_mode=False, is_editor=False, tactical_mode=False,
                      viewing_ai_moves=False, ai_is_thinking=False)
        for name, value in fields.items():
            patcher = mock.patch.object(game, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_player_invite_is_clickable_and_explains_leadership_and_preserves_undo(self):
        game = self.game
        self.map_module.update_button_states(game)
        self.assertTrue(game.btn_fac_invite.visible)
        self.assertFalse(game.btn_fac_invite.disabled)
        self.assertIs(game.btn_fac_invite.right_image, game.ai_response_images["NO"])
        with mock.patch.object(game, "show_feedback") as feedback:
            game.btn_fac_invite.callback()
        feedback.assert_called_once_with("Only a faction leader may invite members.")
        self.assertNotIn(self.outsider, game.nation_data[self.member]["pending_diplomacy"])
        game.player_country = self.leader
        self.map_module.update_button_states(game)
        self.assertFalse(game.btn_fac_invite.disabled)
        self.assertIs(game.btn_fac_invite.right_image, game.ai_response_images["MAYBE"])
        game.nation_data[self.member]["pending_diplomacy"][self.outsider] = {
            "action": "FACTION_INVITE", "turns": 0}
        game.player_country = self.member
        self.map_module.update_button_states(game)
        self.assertFalse(game.btn_fac_invite.disabled)
        self.assertIsNone(game.btn_fac_invite.right_image)

    def test_spectator_invite_is_clickable_for_leaders_and_members(self):
        game = self.game
        game.player_country = "Spectator"
        for country in (self.member, self.leader):
            game.selected_province = next(p for p in game.map_data.values()
                                          if p.get("owner") == country)
            self.map_module.update_button_states(game)
            self.assertTrue(game.btn_spec_invite_fac.visible)
            self.assertFalse(game.btn_spec_invite_fac.disabled)
            if country == self.member:
                with mock.patch.object(game, "show_feedback") as feedback:
                    game.btn_spec_invite_fac.callback()
                feedback.assert_called_once_with("Only a faction leader may invite members.")

    def test_join_button_to_a_member_is_clickable_and_explains_who_to_ask(self):
        game = self.game
        game.player_country = self.outsider
        game.selected_province = next(p for p in game.map_data.values()
                                      if p.get("owner") == self.member)
        self.map_module.update_button_states(game)
        self.assertTrue(game.btn_fac_join_req.visible)
        self.assertFalse(game.btn_fac_join_req.disabled)
        self.assertIs(game.btn_fac_join_req.right_image, game.ai_response_images["NO"])
        with mock.patch.object(game, "show_feedback") as feedback:
            game.btn_fac_join_req.callback()
        self.assertIn("faction leader", feedback.call_args.args[0])
        self.assertNotIn(self.member, game.nation_data[self.outsider]["pending_diplomacy"])
        game.selected_province = next(p for p in game.map_data.values()
                                      if p.get("owner") == self.leader)
        self.map_module.update_button_states(game)
        self.assertIs(game.btn_fac_join_req.right_image, game.ai_response_images["MAYBE"])

    def test_tactical_player_cannot_invite_even_when_the_country_leads(self):
        self.game.player_country = self.leader
        self.game.tactical_mode = True
        self.map_module.update_button_states(self.game)
        self.assertTrue(self.game.btn_fac_invite.disabled)


if __name__ == "__main__":
    unittest.main()
