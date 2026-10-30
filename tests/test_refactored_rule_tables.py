"""Check shared tables and helpers that several game paths depend on."""

from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import data.constants as c
from data import queries
from map_logic.ai import ai_movement
from map_logic.diplomacy import action_definitions, diplomacy_messages, diplomacy_processor


class DiplomaticActionTableTests(unittest.TestCase):
    def test_every_unilateral_action_has_a_send_handler(self):
        # A bilateral action can use the shared announcement. A unilateral action would do nothing.
        self.assertTrue(set(c.UNILATERAL_ACTIONS) <= set(diplomacy_processor._SEND_HANDLERS))

    def test_derived_lists_read_the_definition_fields(self):
        fixture = action_definitions.ActionDefinition("bilateral", "reply", None, announcement="Hello.",
                                                      lite_response="KEY", cancelled_by_war=True)
        with patch.dict(action_definitions.ACTION_DEFINITIONS, {"FIXTURE": fixture}):
            self.assertEqual(diplomacy_messages.announcement_for("FIXTURE"), "Hello.")
            self.assertEqual(diplomacy_messages.announcement_for("FIXTURE", "Mine."), "Mine.")

    def test_action_without_an_announcement_names_itself(self):
        self.assertEqual(diplomacy_messages.announcement_for("FIXTURE_ACTION"), "We propose fixture action.")

    def test_an_unhandled_bilateral_action_uses_the_shared_announcement(self):
        send = SimpleNamespace(map_screen=None, country="A", target="B", action="FIXTURE", custom_msg="", wrote_it=False)
        with patch.object(diplomacy_processor, "send_treaty_message") as announce:
            self.assertFalse(diplomacy_processor._send_announcement(send))
        announce.assert_called_once_with(None, "A", "B", "FIXTURE", "", llm=False)


class FastUnitPathTests(unittest.TestCase):
    def setUp(self):
        provinces = {
            1: {"neighbors": [2], "owner": "A"},
            2: {"neighbors": [1, 3, 4], "owner": "Unclaimed"},
            3: {"neighbors": [2, 5], "owner": "Open"},
            4: {"neighbors": [2], "owner": "Closed"},
            5: {"neighbors": [3], "owner": "Open"},
        }
        self.world = SimpleNamespace(id_to_province=provinces)
        self.claim = Mock()

    def extend(self, speed, can_push):
        unit = {"speed": speed, "order": {"path": [2]}}
        with patch.object(queries, "is_water_province", return_value=False):
            ai_movement._extend_fast_unit_path(self.world, unit, 2, 1, False, set(), lambda tile: tile, self.claim, can_push)
        return unit["order"]["path"]

    def test_slow_units_keep_their_first_step(self):
        self.assertEqual(self.extend(1, lambda owner: True), [2])
        self.claim.assert_not_called()

    def test_each_extra_step_follows_the_callers_rule_and_is_claimed(self):
        self.assertEqual(self.extend(3, lambda owner: owner == "Open"), [2, 3, 5])
        self.assertEqual([call.args[0] for call in self.claim.call_args_list], [3, 5])

    def test_path_stops_when_no_tile_passes(self):
        self.assertEqual(self.extend(3, lambda owner: False), [2])


class RealtimeMapEntryTests(unittest.TestCase):
    def setUp(self):
        from tests import app_harness
        app_harness.boot()
        import main
        self.controller_class = main.Controller
        self.session = SimpleNamespace(players={"p1": SimpleNamespace(country_id="A"), "p2": SimpleNamespace(country_id=None),
                                                "p3": SimpleNamespace(country_id="B")})
        self.board = Mock(selection_mode=True, pending_selection="X", show_player_ready_screen=True)
        self.controller = SimpleNamespace(states={})

    def enter(self, after_layers=None):
        with patch("screens.game.map.render_buttons") as render:
            self.controller_class._enter_realtime_map(self.controller, self.board, self.session, "p1", "A", after_layers)
        render.assert_called_once_with(self.board)

    def test_entry_skips_country_selection_and_binds_the_player(self):
        self.enter()
        self.assertFalse(self.board.selection_mode)
        self.assertIsNone(self.board.pending_selection)
        self.assertFalse(self.board.show_player_ready_screen)
        self.assertTrue(self.board.realtime_multiplayer)
        self.assertIs(self.board.realtime_session, self.session)
        self.assertEqual((self.board.realtime_player_id, self.board.player_country), ("p1", "A"))
        self.assertEqual(self.board.active_players, ["A", "B"])
        self.board.set_play_view_defaults.assert_called_once_with()
        self.board.refresh_map_layers.assert_called_once_with("relations", "faction_territories", "fog")
        self.assertIs(self.controller.states["MAP"], self.board)

    def test_snapshot_applies_after_the_layers_and_before_the_board_becomes_active(self):
        order = []
        self.board.refresh_map_layers.side_effect = lambda *_layers: order.append("layers")

        def snapshot():
            order.append("snapshot")
            self.assertNotIn("MAP", self.controller.states)
        self.enter(snapshot)
        self.assertEqual(order, ["layers", "snapshot"])

    def test_initial_snapshot_records_its_turn_and_phase(self):
        view = SimpleNamespace(snapshot={"state": 1}, turn_number=7, phase="TURN")
        with patch("data.multiplayer.realtime.session.apply_authoritative_snapshot") as apply_snapshot:
            self.controller_class._apply_initial_snapshot(self.board, view)
        apply_snapshot.assert_called_once_with(self.board, view.snapshot)
        self.assertEqual((self.board._realtime_snapshot_turn, self.board._realtime_snapshot_phase), (7, "TURN"))


if __name__ == "__main__":
    unittest.main()
