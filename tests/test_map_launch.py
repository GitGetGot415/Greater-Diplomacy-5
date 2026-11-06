"""Each screen that opens MAP builds the map from its own selection."""

import os
import unittest
import threading
from contextlib import ExitStack
from types import SimpleNamespace
from unittest import mock

from screens.game import map_launch
from tests import app_harness
from ui.navigation import screen_runner, modal_stack
from data.platform import LoadingSteps


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

    def test_staged_loading_publishes_only_the_completed_map(self):
        old_map = object()
        self.app.states["MAP"] = old_map
        new_map = object()

        def build(**settings):
            yield "stage"
            self.assertIs(self.app.states["MAP"], old_map)
            return new_map

        with mock.patch.object(map_launch, "_new_map_steps", side_effect=build) as create:
            steps = map_launch.open_saved_map_steps(
                self.app, "fixture-save", force_editor=True, history_turn=4)
            next(steps)
            self.assertIs(self.app.states["MAP"], old_map)
            with self.assertRaises(StopIteration) as completed:
                next(steps)
        self.assertTrue(completed.exception.value)
        self.assertIs(self.app.states["MAP"], new_map)
        create.assert_called_once_with(num_players=3, load_path="fixture-save",
                                       is_scenario=False, force_editor=True, history_turn=4)

    def test_staged_tournament_failure_preserves_the_previous_map(self):
        app_harness.boot()
        old_map = object()
        self.app.states["MAP"] = old_map
        screen = SimpleNamespace(selected_tournament_path="missing", selected_tournament_key="key",
                                 done=False, next_state="MAP")
        failure = (False, None, None, None, None, "File not found")
        with mock.patch("data.multiplayer.tournament.files.load_tournament", return_value=failure), \
                mock.patch("ui.dialogs.show_error") as show_error, mock.patch("builtins.print"):
            steps = map_launch.open_tournament_map_steps(self.app, screen)
            next(steps)
            with self.assertRaises(ValueError):
                next(steps)
        show_error.assert_not_called()
        self.assertIs(self.app.states["MAP"], old_map)
        self.assertEqual(screen.next_state, "MULTIPLAYER_HUB")

    def test_staged_tournament_filters_the_player_view_before_publishing(self):
        app_harness.boot()
        screen = SimpleNamespace(selected_tournament_path="dir/game.gd5tour", selected_tournament_key="key")
        game_map = mock.Mock()
        old_map = object()
        self.app.states["MAP"] = old_map
        result = (True, "PLAYER", "A", "temp", {}, "ok", "session", {})

        def build(**settings):
            yield "stage"
            return game_map

        def strip(board, country_id):
            self.assertIs(self.app.states["MAP"], old_map)

        with mock.patch("data.multiplayer.tournament.files.load_tournament", return_value=result), \
                mock.patch("data.multiplayer.tournament.files.strip_sensitive_data_for_player", side_effect=strip) as filtered, \
                mock.patch.object(map_launch, "_new_map_steps", side_effect=build), \
                mock.patch("screens.game.map.render_buttons"), mock.patch("shutil.rmtree"):
            self.assertTrue(map_launch._finish_steps(map_launch.open_tournament_map_steps(self.app, screen)))
        filtered.assert_called_once_with(game_map, "A")
        self.assertIs(self.app.states["MAP"], game_map)


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

    def test_each_map_source_supplies_loading_stages(self):
        routes = (("LOAD_GAME", "open_saved_map_steps"), ("NEW_GAME", "open_saved_map_steps"),
                  ("NEW_MAP", "open_saved_map_steps"), ("SELECT_BASE_MAP", "open_saved_map_steps"),
                  ("RANDOM_SETUP", "open_new_map_steps"),
                  ("MULTIPLAYER_HOST", "open_tournament_map_steps"),
                  ("MULTIPLAYER_JOIN", "open_tournament_map_steps"),
                  ("REALTIME_LOBBY", "open_hosted_realtime_map_steps"),
                  ("REALTIME_REMOTE_LOBBY", "open_joined_realtime_map_steps"))
        for state, route in routes:
            screen = self.controller.states[state]
            with self.subTest(state=state), mock.patch.object(map_launch, route) as launch, \
                    mock.patch.object(screen, "selected_save_path", "fixture", create=True), \
                    mock.patch.object(screen, "selected_history_turn", 4, create=True), \
                    mock.patch.object(screen, "random_settings", {}, create=True):
                self.assertIs(screen.prepare_map_steps(self.controller), launch.return_value)
                launch.assert_called_once()

    def test_controller_enters_the_map_only_after_loading_finishes(self):
        import main

        target = mock.Mock()
        source = SimpleNamespace(next_state="MAP", done=True,
                                 prepare_map_steps=lambda app: iter(["stage"]))
        app = SimpleNamespace(active_state=source, states={"MAP": target})
        with mock.patch.object(main.screen_runner, "run_loading") as loading:
            main.Controller.flip_state(app)
        self.assertIs(app.active_state, source)
        self.assertFalse(source.done)
        target.on_enter.assert_not_called()
        loading.call_args.kwargs["on_done"](True)
        self.assertIs(app.active_state, target)
        target.on_enter.assert_called_once_with(app, source)

    def test_editor_folder_loading_waits_for_the_overlay(self):
        from screens.editors import menus

        game = mock.Mock()
        work = mock.Mock()

        def load_steps(context, path):
            yield "stage"
            work(context, path)

        with mock.patch.object(menus.pickers, "open_file_browser") as picker, \
                mock.patch.object(menus.load_map, "load_map_asset_steps", side_effect=load_steps), \
                mock.patch.object(menus.screen_runner, "run_loading") as loading:
            menus.editor_load_map(game)
            picker.call_args.kwargs["on_result"]("fixture")
            work.assert_not_called()
            game.refresh_map_layers.assert_not_called()
            map_launch._finish_steps(loading.call_args.args[0])
        work.assert_called_once_with(game, "fixture")
        game.refresh_map_layers.assert_called_once_with("political")
        game.show_feedback.assert_not_called()
        loading.call_args.kwargs["on_done"](None)
        game.show_feedback.assert_called_once()

    def test_tournament_creation_waits_for_loading_then_reports_success(self):
        from screens.multiplayer import multiplayer_new

        source = SimpleNamespace(go_to=mock.Mock())
        game = mock.Mock(nation_data={"A": {"is_playable": True}})
        game.time_manager.total_turns = 4

        def build(**settings):
            yield "stage"
            return game

        with mock.patch.object(multiplayer_new.dialogs, "ask_string") as ask, \
                mock.patch.object(multiplayer_new.dialogs, "show_success") as success, \
                mock.patch.object(multiplayer_new.os.path, "exists", return_value=False), \
                mock.patch.object(multiplayer_new.os, "makedirs"), \
                mock.patch.object(multiplayer_new.c, "TOURNAMENT_SAVES_DIR", "fixture-tournaments"), \
                mock.patch.object(multiplayer_new.file_exchange.pickers, "open_file_browser",
                                  side_effect=lambda *_args, **kwargs: kwargs["on_result"]("chosen-tournament")), \
                mock.patch.object(multiplayer_new.queries, "get_scenario_settings", return_value={}), \
                mock.patch.object(multiplayer_new.Map, "loading_steps", side_effect=build), \
                mock.patch.object(multiplayer_new.tournament_files, "export_tournament", return_value=("keys", "all-keys")) as export, \
                mock.patch.object(multiplayer_new.screen_runner, "run_loading") as loading:
            multiplayer_new.Multiplayer_New.start_host_setup(source, "Fixture", "fixture-scenarios")
            ask.call_args.args[2]("Tournament")
            ask.call_args.args[2]("secret-key")
            export.assert_not_called()
            turn = map_launch._finish_steps(loading.call_args.args[0])
            export.assert_called_once()
            self.assertTrue(game.multiplayer_host_mode)
            self.assertEqual(game.multiplayer_master_key, "secret-key")
            self.assertEqual(export.call_args.args[1], os.path.join("chosen-tournament", "Turn_4_Host.gd5tour"))
            success.assert_not_called()
            loading.call_args.kwargs["on_done"](turn)
            success.assert_called_once()
        source.go_to.assert_called_once_with("MULTIPLAYER_HOST")

    def test_canceling_a_new_tournament_destination_does_not_create_or_load_anything(self):
        from screens.multiplayer import multiplayer_new

        source = SimpleNamespace(go_to=mock.Mock())
        with mock.patch.object(multiplayer_new.dialogs, "ask_string") as ask, \
                mock.patch.object(multiplayer_new.file_exchange.pickers, "open_file_browser") as browser, \
                mock.patch.object(multiplayer_new.os, "makedirs") as mkdir, \
                mock.patch.object(multiplayer_new.screen_runner, "run_loading") as loading:
            multiplayer_new.Multiplayer_New.start_host_setup(source, "Fixture", "fixture-scenarios")
            ask.call_args.args[2]("Tournament")
            browser.call_args.kwargs["on_result"](None)
            self.assertEqual(ask.call_count, 1)
            mkdir.assert_not_called()
            loading.assert_not_called()
            source.go_to.assert_not_called()


class LoadingRunnerTests(unittest.TestCase):
    def setUp(self):
        self.done = mock.Mock()
        self.error = mock.Mock()
        patcher = mock.patch.object(screen_runner.pygame.display, "get_surface", return_value=mock.Mock())
        patcher.start()
        self.addCleanup(patcher.stop)
        self.original_stack = list(modal_stack._stack)
        modal_stack._stack.clear()
        self.addCleanup(lambda: modal_stack._stack.__setitem__(slice(None), self.original_stack))

    def loader(self, steps, total=1):
        screen_runner.run_loading(LoadingSteps(steps, total), on_done=self.done, on_error=self.error)
        return modal_stack.active()

    def draw(self, loader):
        with mock.patch.object(screen_runner.turn_progress, "draw_simple_refresh_bar"):
            loader.draw(mock.Mock())

    def test_web_waits_for_a_draw_and_advances_one_stage_per_update(self):
        calls = []

        def work():
            yield "First Stage"
            calls.append("first")
            yield "Second Stage"
            calls.append("second")
            return "map"

        loader = self.loader(work(), total=2)
        with mock.patch.object(screen_runner, "IS_WEB", True), \
                mock.patch.object(screen_runner, "run_background") as background:
            loader.update()
            self.assertEqual(calls, [])
            self.assertEqual((loader.completed, loader.total), (0, 2))
            self.draw(loader)
            loader.update()
            self.assertEqual(calls, [])
            self.assertEqual(loader.completed, 0)
            loader.update()
            self.assertEqual(calls, ["first"])
            self.assertEqual((loader.completed, loader.total), (1, 2))
            loader.handle_events([mock.Mock()])
            loader.update()
            self.assertEqual(calls, ["first", "second"])
            self.assertEqual((loader.completed, loader.total), (2, 2))
            self.done.assert_not_called()
            loader.update()
        background.assert_not_called()
        self.done.assert_called_once_with("map")
        self.error.assert_not_called()
        self.assertTrue(modal_stack.is_empty())

    def test_desktop_completion_returns_to_the_ui_thread(self):
        worker_ids = []

        def work():
            worker_ids.append(threading.get_ident())
            yield "stage"
            return "map"

        loader = self.loader(work())
        self.draw(loader)
        self.assertEqual((loader.completed, loader.total), (0, 1))
        with mock.patch.object(screen_runner, "IS_WEB", False), \
                mock.patch.object(screen_runner, "run_background") as start:
            loader.update()
            loader.update()
            start.assert_called_once()
            worker = threading.Thread(target=start.call_args.args[0])
            worker.start()
            worker.join(timeout=5)
            self.assertFalse(worker.is_alive())
            self.assertEqual((loader.completed, loader.total), (1, 1))
            self.done.assert_not_called()
            self.done.side_effect = lambda result: self.assertEqual(threading.get_ident(), ui_thread)
            ui_thread = threading.get_ident()
            loader.update()
        self.assertNotEqual(worker_ids, [ui_thread])
        self.done.assert_called_once_with("map")

    def test_failed_load_closes_the_overlay_before_reporting_the_error(self):
        failure = ValueError("Invalid map")

        def work():
            yield "stage"
            raise failure

        loader = self.loader(work())
        self.draw(loader)
        self.error.side_effect = lambda error: self.assertTrue(modal_stack.is_empty())
        with mock.patch.object(screen_runner, "IS_WEB", True):
            loader.update()
            loader.update()
            loader.update()
        self.error.assert_called_once_with(failure)
        self.done.assert_not_called()
        self.assertEqual((loader.completed, loader.total), (0, 1))

    def test_progress_stays_still_until_the_running_stage_finishes(self):
        entered = threading.Event()
        release = threading.Event()

        def work():
            yield "stage"
            entered.set()
            if not release.wait(timeout=5):
                raise TimeoutError("Test did not release loading stage")

        loader = self.loader(work())
        worker = threading.Thread(target=loader._run)
        worker.start()
        try:
            self.assertTrue(entered.wait(timeout=5))
            for _ in range(3):
                self.draw(loader)
                self.assertEqual((loader.completed, loader.total), (0, 1))
        finally:
            release.set()
            worker.join(timeout=5)
        self.assertFalse(worker.is_alive())
        self.assertEqual((loader.completed, loader.total), (1, 1))
        self.assertIsNone(loader.error)


class LoadingCountTests(unittest.TestCase):
    def test_asset_totals_match_the_regular_and_procedural_pipelines(self):
        from data.map import load_map
        from data.state_access import BackendState

        runtime = SimpleNamespace(libraries={"unit_library": {}, "tech_tree": {}}, disabled_tech_keys=set())
        with ExitStack() as patches:
            for name in ("_load_map_images", "_load_nation_records", "_load_default_images",
                         "_load_provinces", "_repair_factions", "_load_procedural_world"):
                patches.enter_context(mock.patch.object(load_map, name))
            patches.enter_context(mock.patch.object(load_map, "_resolve_load_path", return_value="fixture-map"))
            patches.enter_context(mock.patch.object(load_map, "read_save_files", return_value=(None, {}, {})))
            patches.enter_context(mock.patch.object(load_map, "rebuild", return_value=runtime))
            patches.enter_context(mock.patch.object(load_map.queries, "build_air_geometry"))
            for path in ("fixture-map", "PROCEDURAL"):
                with self.subTest(path=path):
                    context = BackendState()
                    context.history_turn = None
                    steps = load_map.load_map_asset_steps(context, path, {})
                    self.assertEqual(len(list(steps)), steps.total)

    def test_launch_totals_include_nested_map_stages(self):
        app = SimpleNamespace(num_players=1, states={"MAP": None})
        lobby = SimpleNamespace(session=SimpleNamespace(config=SimpleNamespace(scenario_id="fixture-map")))
        with mock.patch.object(map_launch, "_map_loading_total", return_value=7):
            self.assertEqual(map_launch.open_saved_map_steps(app, "fixture-map").total, 7)
            self.assertEqual(map_launch.open_tournament_map_steps(app, mock.Mock()).total, 9)
            self.assertEqual(map_launch.open_hosted_realtime_map_steps(app, lobby).total, 8)
            self.assertEqual(map_launch.open_joined_realtime_map_steps(app, mock.Mock()).total, 9)


if __name__ == "__main__":
    unittest.main()
