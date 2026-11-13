"""Portable standalone music imports, selection, export queues, and editor permissions."""
import base64
from contextlib import chdir
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from data import constants as c, queries
from data.io import standalone_game, standalone_music
from data.map import load_map
from tests.test_scenario_metadata import editor


class StandaloneMusicTests(unittest.TestCase):
    def setUp(self):
        self.source_defaults = Path("data/json/starting_defaults.json").resolve()
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(chdir(self.root))
        self.enterContext(mock.patch.object(c, "UNDELETABLE_ALBUMS", ("Fixture Base", "Other Base")))
        self.album = Path(c.MUSIC_DIR) / "Fixture Base"
        self.album.mkdir(parents=True)
        (self.album / "base.mp3").write_bytes(b"base audio")
        (self.album / "volumes.json").write_text('{"base.mp3": 0.5}', encoding="utf-8")
        other = Path(c.MUSIC_DIR) / "Other Base"
        other.mkdir()
        (other / "other.ogg").write_bytes(b"other audio")
        self.song = self.root / "Opening.mp3"
        self.song.write_bytes(b"custom audio")
        self.png = base64.b64decode(queries.encode_rgba_to_b64(bytes([10, 20, 30, 255]), (1, 1)))
        self.icon = self.root / "cover.png"
        self.icon.write_bytes(self.png)

    def music(self):
        result = standalone_music.import_song({"album_name": "Custom Album"}, str(self.song), starting=True)
        return standalone_music.import_icon(result, str(self.icon))

    def test_imports_survive_original_file_removal_and_duplicates_do_not_overwrite(self):
        music = self.music()
        music = standalone_music.import_song(music, str(self.song))
        self.assertEqual(len(music["songs"]), 1)
        self.song.write_bytes(b"a different track")
        music = standalone_music.import_song(music, str(self.song))
        self.assertEqual([song["name"] for song in music["songs"]], ["Opening.mp3", "Opening (2).mp3"])
        self.song.unlink()
        self.icon.unlink()
        _copies, files = standalone_music.export_files(music, "Scenario")
        exported = {Path(path): data for path, data in files}
        self.assertEqual(exported[Path(c.MUSIC_DIR) / "Custom Album/Opening.mp3"], b"custom audio")
        self.assertEqual(exported[Path(c.MUSIC_DIR) / "Custom Album/icon.png"], self.png)
        self.assertEqual(music["starting_song"], "Opening.mp3")

    def test_shared_import_validation_rejects_non_music_and_false_pngs(self):
        bad = self.root / "song.txt"
        bad.write_text("not a song", encoding="utf-8")
        with self.assertRaises(ValueError):
            standalone_music.import_song({}, str(bad))
        self.icon.write_bytes(b"GIF89a not a png")
        with self.assertRaises(ValueError):
            standalone_music.import_icon({}, str(self.icon))
        self.song.write_bytes(b"")
        with self.assertRaises(ValueError):
            standalone_music.import_song({}, str(self.song))

    def test_normalization_repairs_old_and_malformed_data_without_reusing_unsafe_names(self):
        default = queries.normalized_standalone_export_settings({})["music"]
        self.assertEqual(default, {"album_name": "", "starting_song": "", "songs": [], "icon": "", "base_albums": []})
        data = base64.b64encode(b"song").decode("ascii")
        value = {"songs": [{"name": "../escape.mp3", "data": data}, {"name": "Track.mp3", "data": data}, {"name": "track.mp3", "data": data}, {"name": "not-music.txt", "data": data}], "starting_song": "missing.mp3", "base_albums": ["Fixture Base", "Not Shipped", "Fixture Base"], "extension": {"preserve": True}}
        music = standalone_music.normalized_music(value)
        self.assertEqual([song["name"] for song in music["songs"]], ["Track.mp3"])
        self.assertEqual(music["starting_song"], "")
        self.assertEqual(music["base_albums"], ["Fixture Base"])
        self.assertEqual(music["extension"], {"preserve": True})
        self.assertEqual(standalone_music.normalized_music(music), music)

    def test_size_counts_decoded_imports_once_and_only_selected_base_album_files(self):
        music = dict(self.music(), base_albums=["Fixture Base"])
        inventory = standalone_music.base_album_inventory()
        expected = len(b"custom audio") + len(self.png) + sum(file.stat().st_size for file in self.album.iterdir())
        self.assertEqual(standalone_music.music_size(music, inventory), expected)
        for length in range(8):
            self.assertEqual(standalone_music.decoded_size(base64.b64encode(b"a" * length).decode("ascii")), length)

    def test_export_writes_selected_files_defaults_starting_song_and_actual_progress(self):
        original_defaults = self.source_defaults.read_bytes()
        music = dict(self.music(), base_albums=["Fixture Base"])
        settings = queries.normalized_standalone_export_settings({"music": music})
        destination = self.root / "export"
        scenario = self.root / "scenario"
        scenario.mkdir()
        copies = [(str(self.source_defaults), str(destination / "data/json/starting_defaults.json"))]
        with mock.patch.object(standalone_game, "export_dir", return_value=str(destination)), mock.patch.object(standalone_game, "_export_copies", return_value=copies):
            steps = standalone_game.export_steps(str(scenario), "Scenario", settings)
            completed = list(steps)
        self.assertEqual(len(completed), steps.total)
        self.assertEqual((destination / c.MUSIC_DIR / "Custom Album/Opening.mp3").read_bytes(), b"custom audio")
        self.assertEqual((destination / c.MUSIC_DIR / "Custom Album/icon.png").read_bytes(), self.png)
        self.assertTrue((destination / c.MUSIC_DIR / "Fixture Base/base.mp3").is_file())
        self.assertFalse((destination / c.MUSIC_DIR / "Other Base").exists())
        active = json.loads((destination / "data/json/active_albums.json").read_text(encoding="utf-8"))
        starting = json.loads((destination / "data/json/starting_song.json").read_text(encoding="utf-8"))
        self.assertEqual(active, ["Custom Album", "Fixture Base"])
        self.assertEqual(starting, {"track": f"{c.MUSIC_DIR}/Custom Album/Opening.mp3"})
        defaults = json.loads((destination / "data/json/starting_defaults.json").read_text(encoding="utf-8"))
        self.assertEqual(defaults["active_albums.json"], active)
        self.assertEqual(defaults["starting_song.json"], starting)
        self.assertEqual(self.source_defaults.read_bytes(), original_defaults)
        manifest = json.loads((destination / "game.json").read_text(encoding="utf-8"))
        with mock.patch.object(standalone_game, "GAME", manifest):
            self.assertEqual(standalone_game.export_settings()["music"], music)

    def test_json_songs_include_the_existing_synth_runtime_files(self):
        song = self.root / "Song.json"
        song.write_text(json.dumps({"format": "BeepBox", "channels": []}), encoding="utf-8")
        for name in ("beepbox", "ultrabox"):
            engine = Path("assets") / name
            engine.mkdir()
            (engine / "synth.js").write_text("fixture", encoding="utf-8")
        music = standalone_music.import_song({"album_name": "Custom"}, str(song), starting=True)
        copies, _files = standalone_music.export_files(music, "Scenario")
        self.assertEqual({Path(target).as_posix() for _source, target in copies}, {"assets/beepbox/synth.js", "assets/ultrabox/synth.js"})

    def test_export_rejects_bad_data_missing_base_albums_and_reserved_album_names(self):
        music = self.music()
        for name in ("../escape", "Fixture Base", "CON"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                standalone_music.export_files(dict(music, album_name=name), "Scenario")
        with self.assertRaises(ValueError):
            standalone_music.export_files(dict(music, base_albums=["Fixture Base"]), "Scenario", inventory={})
        music["songs"][0]["data"] = "not base64!"
        with self.assertRaises(ValueError):
            standalone_music.export_files(music, "Scenario")

    def test_saved_music_round_trips_and_editor_permissions_are_rechecked(self):
        game = editor()
        music = self.music()
        queries.set_standalone_export_setting(game, "music", music)
        saved = {"standalone_export_settings": json.loads(json.dumps(game.standalone_export_settings))}
        restored = editor()
        load_map.restore_scenario_metadata(restored, saved, "Scenario")
        self.assertEqual(restored.standalone_export_settings["music"], music)
        for name in ("multiplayer_mode", "realtime_multiplayer", "is_saving", "ai_is_thinking"):
            with self.subTest(name=name), mock.patch.object(game, name, True), self.assertRaises(ValueError):
                queries.set_standalone_export_setting(game, "music", dict(music, starting_song=""))
        self.assertEqual(game.standalone_export_settings["music"], music)

    def test_invalid_music_does_not_replace_an_existing_export(self):
        from screens.editors import standalone_export
        game = editor()
        game.editor_scenario_name = "Scenario"
        music = self.music()
        music["songs"][0]["data"] = "bad base64!"
        game.standalone_export_settings["music"] = music
        scenarios = self.root / "scenarios"
        (scenarios / "Scenario").mkdir(parents=True)
        destination = self.root / "existing-export"
        destination.mkdir()
        retained = destination / "retained.txt"
        retained.write_text("keep", encoding="utf-8")
        screen = standalone_export.Standalone_Export_Screen()
        screen.map_screen = game
        with mock.patch.object(c, "SCENARIOS_CUSTOM_DIR", str(scenarios)), mock.patch.object(standalone_game, "export_dir", return_value=str(destination)), mock.patch.object(standalone_game, "_export_copies", return_value=[]), mock.patch.object(standalone_game, "clear_export_dir") as clear, mock.patch.object(standalone_export.dialogs, "show_error") as error, mock.patch.object(standalone_export.dialogs, "ask_yes_no") as confirm:
            screen.export()
        error.assert_called_once()
        confirm.assert_not_called()
        clear.assert_not_called()
        self.assertEqual(retained.read_text(encoding="utf-8"), "keep")

    def test_editor_music_callbacks_import_multiple_files_and_reuse_the_inventory(self):
        import pygame
        from screens.editors import standalone_export
        pygame.font.init()
        game = editor()
        game.editor_scenario_name = "Scenario"
        app = SimpleNamespace(states={"MAP": game})
        screen = standalone_export.Standalone_Export_Screen()
        with mock.patch.object(queries, "playable_start_countries", return_value=["A"]):
            screen.on_enter(app, None)
            with mock.patch.object(standalone_export.pickers, "open_file_browser") as pick:
                screen.choose_starting_song()
                pick.call_args.kwargs["on_result"](str(self.song))
                second = self.root / "Second.ogg"
                second.write_bytes(b"second audio")
                screen.choose_other_songs()
                self.assertEqual(pick.call_args.kwargs["mode"], "open_files")
                pick.call_args.kwargs["on_result"]([str(second)])
                screen.choose_album_icon()
                pick.call_args.kwargs["on_result"](str(self.icon))
            with mock.patch.object(standalone_export.dialogs, "ask_string") as name:
                screen.choose_album_name()
                name.call_args.args[2]("My Album")
            screen.toggle_base_album("Fixture Base")
            music = screen.settings()["music"]
            self.assertEqual(music["starting_song"], "Opening.mp3")
            self.assertEqual([song["name"] for song in music["songs"]], ["Opening.mp3", "Second.ogg"])
            self.assertEqual(music["album_name"], "My Album")
            self.assertEqual(music["base_albums"], ["Fixture Base"])
            self.assertTrue(music["icon"])
            with mock.patch.object(standalone_export.pickers, "open_listbox_selector") as starting:
                screen.choose_starting_song()
                starting.call_args.args[4]("Second.ogg")
            self.assertEqual(screen.settings()["music"]["starting_song"], "Second.ogg")
            screen.change_music(starting_song="Opening.mp3")
            with mock.patch.object(standalone_music, "base_album_inventory", side_effect=AssertionError("inventory reread during refresh")):
                screen.refresh_ui()
            with mock.patch.object(standalone_export.pickers, "open_listbox_selector") as remove:
                screen.remove_music_song()
                remove.call_args.args[4]("Second.ogg")
            self.assertEqual([song["name"] for song in screen.settings()["music"]["songs"]], ["Opening.mp3"])
            game.multiplayer_mode = True
            screen.import_music_paths([str(second)])
            self.assertEqual([song["name"] for song in screen.settings()["music"]["songs"]], ["Opening.mp3"])
