"""Each screen that opens MAP builds the map from its own selection."""

import unittest
from types import SimpleNamespace
from unittest import mock

from screens.game import map_launch
from tests import app_harness


class PrepareMapTests(unittest.TestCase):
    def setUp(self):
        self.app = SimpleNamespace(num_players=3, states={"MAP": None})
        patcher = mock.patch.object(map_launch, "_new_map", return_value=mock.Mock(name="built_map"))
        self.new_map = patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_scenario_path_opens_as_a_scenario(self):
        map_launch.open_saved_map(self.app, "scenarios/historical/1939")
        self.new_map.assert_called_once_with(num_players=3, load_path="scenarios/historical/1939",
                                             is_scenario=True, force_editor=False, history_turn=None)
        self.assertIs(self.app.states["MAP"], self.new_map.return_value)

    def test_a_save_keeps_its_history_turn(self):
        map_launch.open_saved_map(self.app, "saves/game", history_turn=4)
        self.new_map.assert_called_once_with(num_players=3, load_path="saves/game", is_scenario=False,
                                             force_editor=False, history_turn=4)

    def test_a_failed_tournament_load_stays_on_the_screen_and_returns_to_the_hub(self):
        app_harness.boot()
        screen = SimpleNamespace(selected_tournament_path="missing", selected_tournament_key="key",
                                 done=True, next_state="MAP")
        failure = (False, None, None, None, None, "File not found")
        with mock.patch("data.multiplayer.tournament.files.load_tournament", return_value=failure), \
                mock.patch("ui.dialogs.show_error") as show_error, mock.patch("builtins.print"):
            self.assertFalse(map_launch.open_tournament_map(self.app, screen))
        show_error.assert_called_once_with("Load Failed", "File not found")
        self.assertFalse(screen.done)
        self.assertEqual(screen.next_state, "MULTIPLAYER_HUB")
        self.new_map.assert_not_called()

    def test_a_tournament_player_receives_only_their_own_view(self):
        app_harness.boot()
        screen = SimpleNamespace(selected_tournament_path="dir/game.gd5tour", selected_tournament_key="key")
        versions = {"h1": {"role": "PLAYER", "country_id": "A", "enc_session": "e1"},
                    "h2": {"role": "HOST"}, "h3": {"role": "PLAYER", "country_id": "Gone", "enc_session": "e3"}}
        result = (True, "PLAYER", "A", "temp", {"A": "player-key"}, "ok", "session", versions)
        with mock.patch("data.multiplayer.tournament.files.load_tournament", return_value=result), \
                mock.patch("data.multiplayer.tournament.files.strip_sensitive_data_for_player") as strip, \
                mock.patch("screens.game.map.render_buttons"), mock.patch("shutil.rmtree") as remove:
            self.assertTrue(map_launch.open_tournament_map(self.app, screen))
        game_map = self.app.states["MAP"]
        strip.assert_called_once_with(game_map, "A")
        remove.assert_called_once_with("temp", ignore_errors=True)
        self.assertEqual(game_map.multiplayer_player_key, "key")
        self.assertEqual(game_map.multiplayer_player_enc_cache, {"A": ("player-key", "h1", "e1")})

    def test_the_host_keeps_a_separate_board_from_the_server_map(self):
        player = SimpleNamespace(player_id="host", country_id="A")
        session = SimpleNamespace(players={"host": player}, host_id="host",
                                  config=SimpleNamespace(scenario_id="scenario", scenario_settings={"rule": 1}))
        lobby = SimpleNamespace(session=session, server="server", server_map="server-map",
                                port_mapping="ports", temporary_relay="relay", relay_token="token")
        with mock.patch.object(map_launch, "enter_realtime_map") as enter:
            map_launch.open_hosted_realtime_map(self.app, lobby)
        board = self.new_map.return_value
        self.new_map.assert_called_once_with(load_path="scenario", is_scenario=True,
                                             map_settings={"rule": 1}, num_players=1)
        self.assertEqual((board.realtime_server, board.realtime_server_map), ("server", "server-map"))
        enter.assert_called_once_with(self.app, board, session, "host", "A")


class ScreenHookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.controller, _ = app_harness.boot()

    def test_a_cancelled_map_keeps_the_active_screen(self):
        controller = self.controller
        original = controller.active_state
        screen = controller.states["MENU"]
        self.addCleanup(setattr, controller, "active_state", original)
        controller.active_state = screen
        with mock.patch.object(screen, "prepare_map", return_value=False), \
                mock.patch.object(screen, "next_state", "MAP", create=True):
            controller.flip_state()
        self.assertIs(controller.active_state, screen)

    def test_each_map_source_uses_its_own_launch_route(self):
        states = self.controller.states
        routes = (("LOAD_GAME", "open_saved_map"), ("NEW_GAME", "open_saved_map"), ("SELECT_BASE_MAP", "open_saved_map"),
                  ("RANDOM_SETUP", "open_new_map"), ("MULTIPLAYER_HOST", "open_tournament_map"),
                  ("MULTIPLAYER_JOIN", "open_tournament_map"), ("REALTIME_LOBBY", "open_hosted_realtime_map"),
                  ("REALTIME_REMOTE_LOBBY", "open_joined_realtime_map"))
        for state, route in routes:
            with self.subTest(state=state), mock.patch.object(map_launch, route) as launch, \
                    mock.patch.object(states[state], "selected_save_path", "path", create=True), \
                    mock.patch.object(states[state], "selected_history_turn", None, create=True), \
                    mock.patch.object(states[state], "random_settings", {}, create=True):
                states[state].prepare_map(self.controller)
                launch.assert_called_once()

    def test_the_map_editor_opens_a_base_map_for_editing(self):
        screen = self.controller.states["SELECT_BASE_MAP"]
        with mock.patch.object(map_launch, "open_saved_map") as launch, \
                mock.patch.object(screen, "selected_save_path", "base_maps/World"):
            screen.prepare_map(self.controller)
        launch.assert_called_once_with(self.controller, "base_maps/World", force_editor=True)


if __name__ == "__main__":
    unittest.main()
