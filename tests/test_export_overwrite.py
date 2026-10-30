"""Export cancellation preserves destination files and tournament state."""

import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
import zipfile


from data import constants as c, queries
from data.multiplayer.tournament import files as tournament_files
from ui import dialogs
from ui.panels import multiplayer_host_panel


class ExportOverwriteTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.source = self.root / "source.gd5move"
        self.source.write_bytes(b"new move")
        self.downloads = self.root / "Downloads"
        self.downloads.mkdir()
        self.destination = self.downloads / "Turn_4_Player.gd5move"
        for name, patcher in (
                ("ask", mock.patch.object(dialogs, "ask_yes_no")),
                ("success", mock.patch.object(dialogs, "show_success")),
                ("error", mock.patch.object(dialogs, "show_error")),
                ("download", mock.patch.object(queries, "download_file")),
                ("downloads_dir", mock.patch.object(queries, "downloads_dir", return_value=str(self.downloads))),
                ("web", mock.patch.object(queries, "IS_WEB", False))):
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)

    def export_move(self):
        return queries.export_json_file(str(self.source), self.destination.name)

    def test_new_download_exports_immediately(self):
        result = self.export_move()
        self.assertEqual(result, str(self.destination))
        self.assertEqual(self.destination.read_bytes(), self.source.read_bytes())
        self.ask.assert_not_called()
        self.success.assert_called_once()
        self.download.assert_not_called()

    def test_cancel_existing_download_exports_nothing(self):
        self.destination.write_bytes(b"original move")
        original_files = set(self.downloads.iterdir())
        result = self.export_move()
        self.assertIsNone(result)
        self.assertEqual(self.destination.read_bytes(), b"original move")
        self.success.assert_not_called()
        self.ask.call_args.kwargs["on_result"](False)
        self.assertEqual(self.destination.read_bytes(), b"original move")
        self.assertEqual(set(self.downloads.iterdir()), original_files)
        self.success.assert_not_called()
        self.error.assert_not_called()
        self.download.assert_not_called()

    def test_confirm_replaces_existing_download(self):
        self.destination.write_bytes(b"original move")
        self.export_move()
        self.ask.assert_called_once()
        self.assertIn(self.destination.name, self.ask.call_args.args[1])
        self.assertIn(str(self.downloads), self.ask.call_args.args[1])
        self.assertEqual(self.destination.read_bytes(), b"original move")
        self.ask.call_args.kwargs["on_result"](True)
        self.assertEqual(self.destination.read_bytes(), self.source.read_bytes())
        self.success.assert_called_once()

    def test_same_base_name_with_different_extension_is_not_a_conflict(self):
        other_file = self.destination.with_suffix(".gd5tour")
        other_file.write_bytes(b"other file")
        self.export_move()
        self.ask.assert_not_called()
        self.assertEqual(other_file.read_bytes(), b"other file")
        self.assertEqual(self.destination.read_bytes(), self.source.read_bytes())

    def test_zip_export_does_not_build_an_archive_until_confirmed(self):
        destination = self.downloads / "save.zip"
        destination.write_bytes(b"original archive")
        source_dir = self.root / "save"
        source_dir.mkdir()
        (source_dir / "fixture.txt").write_text("new archive content")
        queries.export_dir_as_zip(str(source_dir), destination.name)
        self.assertEqual(destination.read_bytes(), b"original archive")
        self.ask.call_args.kwargs["on_result"](True)
        with zipfile.ZipFile(destination) as archive:
            self.assertEqual(archive.read("fixture.txt"), b"new archive content")
        self.success.assert_called_once()

    def test_error_after_confirmation_does_not_report_success(self):
        self.destination.write_bytes(b"original move")
        self.export_move()
        self.source.unlink()
        self.ask.call_args.kwargs["on_result"](True)
        self.error.assert_called_once()
        self.success.assert_not_called()
        self.assertEqual(self.destination.read_bytes(), b"original move")

    def test_web_confirmation_checks_virtual_file_before_producing_or_downloading(self):
        produce = mock.Mock()
        for answer in (False, True):
            with self.subTest(answer=answer), mock.patch.object(queries, "IS_WEB", True), \
                    mock.patch.object(queries.os.path, "exists", return_value=True) as exists:
                produce.reset_mock()
                self.download.reset_mock()
                self.success.reset_mock()
                queries._export_to_downloads(self.destination.name, produce)
                exists.assert_called_once_with(self.destination.name)
                produce.assert_not_called()
                self.download.assert_not_called()
                self.ask.call_args.kwargs["on_result"](answer)
                self.assertEqual(produce.call_count, int(answer))
                self.assertEqual(self.download.call_count, int(answer))
                self.assertEqual(self.success.call_count, int(answer))

    def test_host_cancel_preserves_pending_keys_and_submissions(self):
        host = SimpleNamespace(
            time_manager=SimpleNamespace(total_turns=4),
            multiplayer_tournament_dir=str(self.downloads),
            multiplayer_master_key="host-key", multiplayer_keys_dict={"Player": "player-key"},
            multiplayer_pending_key_regen={"Player"},
            multiplayer_protected_countries={"Player"}, submitted_moves={"Player"},
            show_feedback=mock.Mock())
        destination = self.downloads / "Turn_4_Host.gd5tour"
        destination.write_bytes(b"original tournament")
        with mock.patch.object(tournament_files, "export_tournament") as exporter:
            multiplayer_host_panel.export_next_turn(host)
            exporter.assert_not_called()
            self.ask.call_args.kwargs["on_result"](False)
            exporter.assert_not_called()
        self.assertEqual(destination.read_bytes(), b"original tournament")
        self.assertEqual(host.multiplayer_pending_key_regen, {"Player"})
        self.assertEqual(host.multiplayer_keys_dict, {"Player": "player-key"})
        self.assertEqual(host.multiplayer_protected_countries, {"Player"})
        self.assertEqual(host.submitted_moves, {"Player"})
        host.show_feedback.assert_not_called()

    def test_host_confirm_runs_export_before_resetting_submissions(self):
        host = SimpleNamespace(
            time_manager=SimpleNamespace(total_turns=4),
            multiplayer_tournament_dir=str(self.downloads),
            multiplayer_master_key="host-key", multiplayer_keys_dict={"Player": "player-key"},
            multiplayer_protected_countries={"Player"}, submitted_moves={"Player"},
            show_feedback=mock.Mock())
        destination = self.downloads / "Turn_4_Host.gd5tour"
        destination.write_bytes(b"original tournament")

        def export(*_args):
            self.assertEqual(host.submitted_moves, {"Player"})
            destination.write_bytes(b"new tournament")

        with mock.patch.object(tournament_files, "export_tournament", side_effect=export) as exporter:
            multiplayer_host_panel.export_next_turn(host)
            self.ask.call_args.kwargs["on_result"](True)
            exporter.assert_called_once_with(host, str(destination), "host-key", host.multiplayer_keys_dict)
        self.assertEqual(destination.read_bytes(), b"new tournament")
        self.assertEqual(host.submitted_moves, set())
        self.assertEqual(host.multiplayer_protected_countries, set())
        host.show_feedback.assert_called_once()

    def test_player_export_button_waits_for_overwrite_confirmation(self):
        from screens.game.map import render_buttons
        from tests import app_harness

        game = app_harness.boot_map()
        self.addCleanup(render_buttons, game)
        player = next(cid for cid, data in game.nation_data.items()
                      if isinstance(data, dict) and data.get("is_playable"))
        turn = game.time_manager.total_turns
        destination = self.downloads / f"Turn_{turn}_{player}.gd5move"
        destination.write_bytes(b"original move")
        with app_harness.patch_map(game, {
                "player_country": player, "multiplayer_mode": True,
                "realtime_multiplayer": False, "multiplayer_player_key": "player-key"}), \
                mock.patch.object(c, "TOURNAMENT_SAVES_DIR", str(self.downloads)), \
                mock.patch.object(tournament_files, "export_move_file") as exporter, \
                mock.patch.object(game, "show_feedback") as feedback:
            render_buttons(game)
            game.btn_next_turn.callback()
            exporter.assert_not_called()
            self.ask.call_args.kwargs["on_result"](False)
            exporter.assert_not_called()
            feedback.assert_not_called()
            self.assertEqual(destination.read_bytes(), b"original move")
            game.btn_next_turn.callback()
            self.ask.call_args.kwargs["on_result"](True)
            exporter.assert_called_once_with(game, str(destination), "player-key")
            feedback.assert_called_once()


if __name__ == "__main__":
    unittest.main()
