"""Web audio conversion and effect loading must preserve working sounds."""

from collections import OrderedDict
from contextlib import redirect_stdout
import asyncio
import importlib.util
import io
import json
import os
from pathlib import Path
import platform as browser_platform  # pygbag adds .window to the stdlib module
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, call, patch

import pygame

import main as game_main
import data.constants as c
from data import platform as game_platform, queries
from compilation_scripts import html_compilation
from tests.web_fixtures import GarblingWindow
from ui import music_playback
from ui.widgets import ui_elements


class WebAudioTests(unittest.TestCase):
    def test_controller_uses_browser_decoder_only_for_unconverted_web_mp3(self):
        controller = object.__new__(game_main.Controller)
        controller.track_start_times = {}
        controller.track_volumes = {}
        controller.music_pitch = 0.5
        controller.music_volume = 0.7
        controller.music = None
        with patch.object(game_main, 'IS_WEB', True, create=True), \
                patch.object(game_main, 'music_playback', music_playback, create=True), \
                patch.object(game_main, 'c', c, create=True), \
                patch.object(c, 'USE_SOLOUD', False), \
                patch.object(music_playback, 'pygame_audio_path', side_effect=lambda path: path), \
                patch.object(music_playback, 'WebMP3Playback') as browser, \
                patch.object(music_playback, 'PygamePlayback') as mixer:
            controller.play_specific_song('custom.mp3')
            browser.assert_called_once_with('custom.mp3', 0.0, 0.7)
            mixer.assert_not_called()
            controller.play_specific_song('custom.ogg')
            browser.return_value.stop.assert_called_once()
            mixer.assert_called_once_with('custom.ogg', 0.0, 0.7)
            with patch.object(music_playback, 'pygame_audio_path', return_value='bundled.ogg'):
                controller.play_specific_song('bundled.mp3')
            self.assertEqual(browser.call_count, 1)
            self.assertEqual(mixer.call_args.args[0], 'bundled.mp3')
            with patch.object(game_main, 'IS_WEB', False):
                controller.play_specific_song('desktop.mp3')
            self.assertEqual(browser.call_count, 1)
            self.assertEqual(mixer.call_args.args[0], 'desktop.mp3')

    def test_browser_player_controls_and_pending_metadata(self):
        import platform

        window = SimpleNamespace(eval=Mock())
        bridge = {name: Mock() for name in ('load', 'pause', 'seek', 'stop', 'set_volume',
                                          'position', 'length', 'error', 'finished')}
        for name, function in bridge.items():
            setattr(window, '__gd5_mp3_' + name, function)
        bridge['position'].return_value = 2.5
        bridge['length'].return_value = 0
        bridge['error'].return_value = ''
        bridge['finished'].return_value = False
        with patch.object(platform, 'window', window, create=True):
            playback = music_playback.WebMP3Playback('custom.mp3', 2.5, 0.4)
        self.assertEqual(playback.source_length(), 0)
        self.assertEqual(playback.source_position(), 2.5)
        self.assertFalse(playback.finished)
        playback.pause(True)
        playback.seek(4)
        bridge['seek'].assert_called_once_with(4)
        self.assertEqual(bridge['pause'].call_args_list, [call(True), call(False)])
        self.assertFalse(playback.paused)
        playback.set_volume(0.2)
        bridge['set_volume'].assert_called_once_with(0.2)
        bridge['position'].return_value = 4
        bridge['length'].return_value = 20
        self.assertEqual(playback.source_length(), 20)
        self.assertEqual(playback.source_position(), 4)
        bridge['error'].return_value = 'Cannot decode audio'
        self.assertEqual(playback.error, 'Cannot decode audio')
        bridge['finished'].return_value = True
        self.assertTrue(playback.finished)
        playback.stop()
        bridge['stop'].assert_called_once()

    def test_browser_resolves_mp3_effect_without_changing_its_settings_key(self):
        with tempfile.TemporaryDirectory() as temporary:
            original = str(Path(temporary, "Info.mp3"))
            converted = Path(temporary, "Info.ogg")
            converted.write_bytes(b"OggS")
            with patch.object(music_playback, "IS_WEB", True), \
                    patch.object(music_playback.pygame.mixer, "Sound") as factory, \
                    patch.object(ui_elements.c, "SOUND_SLIDER_PATH", original):
                music_playback.load_pygame_sound(original)
                factory.assert_called_once_with(str(converted))
                self.assertEqual(ui_elements._ui_sound_filename("slider"), "Info.mp3")
            with patch.object(music_playback, "IS_WEB", False):
                self.assertEqual(music_playback.pygame_audio_path(original), original)

    def test_wav_and_unconverted_files_keep_their_paths(self):
        with patch.object(music_playback, "IS_WEB", True):
            self.assertEqual(music_playback.pygame_audio_path("effect.wav"), "effect.wav")
            with patch.object(music_playback.os.path, "isfile", return_value=False):
                self.assertEqual(music_playback.pygame_audio_path("custom.mp3"), "custom.mp3")

    def test_one_bad_effect_does_not_block_other_effects(self):
        sound = Mock()

        def load(path):
            if path == "broken.mp3":
                raise pygame.error("unsupported format")
            return sound

        caches = {kind: OrderedDict() for kind in ui_elements._pygame_sfx_pitch_cache}
        with patch.object(ui_elements.c, "SOUND_CLICK_PATH", "click.wav"), \
                patch.object(ui_elements.c, "SOUND_SLIDER_PATH", "broken.mp3"), \
                patch.object(ui_elements, "pygame_click_sound", None), \
                patch.object(ui_elements, "pygame_slider_sound", None), \
                patch.object(ui_elements, "pygame_music_ui_sounds", {}), \
                patch.object(ui_elements, "_pygame_sfx_pitch_cache", caches), \
                patch.dict(ui_elements.MUSIC_UI_SOUND_PATHS,
                           {"back": "broken.mp3", "paper": "paper.wav"}, clear=True), \
                patch.object(music_playback, "load_pygame_sound", side_effect=load), \
                redirect_stdout(io.StringIO()) as output:
            ui_elements.load_pygame_ui_sounds()
            self.assertIs(ui_elements.pygame_click_sound, sound)
            self.assertIsNone(ui_elements.pygame_slider_sound)
            self.assertIs(ui_elements.pygame_music_ui_sounds["paper"], sound)
            self.assertIsNone(ui_elements.pygame_music_ui_sounds["back"])
            self.assertIn("broken.mp3", output.getvalue())

    def test_music_uses_the_same_converted_path(self):
        with patch.object(music_playback, "pygame_audio_path", return_value="track.ogg"), \
                patch.object(music_playback.pygame.mixer, "music") as music:
            playback = music_playback.PygamePlayback("track.mp3", 1.25, 0.5)
        music.load.assert_called_once_with("track.ogg")
        music.play.assert_called_once_with(start=1.25)
        music.set_volume.assert_called_once_with(0.5)
        self.assertEqual(playback.track_path, "track.mp3")


@unittest.skipUnless(importlib.util.find_spec('quickjs'), 'QuickJS is not installed')
class WebMP3BridgeTests(unittest.TestCase):
    def setUp(self):
        import quickjs

        self.context = quickjs.Context()
        self.context.eval(r"""
            globalThis.window = globalThis;
            globalThis.readPath = null;
            globalThis.FS = {readFile(path) { readPath = path; return new Uint8Array([1,2]); }};
            globalThis.Blob = class {constructor(parts, options) { this.type = options.type; }};
            globalThis.revoked = [];
            globalThis.URL = {
                createObjectURL(blob) { return 'blob:' + blob.type; },
                revokeObjectURL(url) { revoked.push(url); }
            };
            globalThis.Audio = class {
                constructor() {
                    this.readyState = 0; this.currentTime = 0; this.ended = false;
                    this.events = {}; this.playCount = 0;
                }
                addEventListener(name, callback) { this.events[name] = callback; }
                play() { this.playCount++; return Promise.resolve(); }
                pause() { this.paused = true; }
                removeAttribute(name) { delete this[name]; }
                load() {}
            };
        """)
        self.context.eval(music_playback._WEB_MP3_BRIDGE)
        self.context.eval(
            "globalThis.player = __gd5_mp3_load(JSON.stringify('/music/My Song.mp3'), 2, 0.4)")

    def test_python_player_reads_a_non_ascii_path_through_pygbag(self):
        track = os.path.join('music', 'Ode à la joie 歌.mp3')
        with patch.object(browser_platform, 'window', GarblingWindow(self.context), create=True):
            music_playback.WebMP3Playback(track, 0, 1)
        self.assertEqual(self.context.eval('readPath'), os.path.abspath(track))

    def test_uses_uploaded_bytes_and_keeps_seek_before_metadata(self):
        self.assertEqual(self.context.eval('readPath'), '/music/My Song.mp3')
        self.assertEqual(self.context.eval('player.audio.src'), 'blob:audio/mpeg')
        self.context.eval("player.seek(7); player.audio.readyState = 1; player.audio.events.loadedmetadata()")
        self.assertEqual(self.context.eval('player.audio.currentTime'), 7)
        self.assertEqual(self.context.eval('player.audio.playCount'), 1)
        self.assertEqual(self.context.eval('__gd5_mp3_position()'), 7)
        self.context.eval('player.audio.duration = 20')
        self.assertEqual(self.context.eval('__gd5_mp3_length()'), 20)
        self.context.eval('player.audio.duration = NaN')
        self.assertEqual(self.context.eval('__gd5_mp3_length()'), 0)

    def test_stop_releases_blob_and_does_not_restart_when_metadata_arrives(self):
        self.context.eval("player.stop(); player.stop(); player.audio.events.loadedmetadata()")
        self.assertEqual(self.context.eval('revoked.length'), 1)
        self.assertTrue(self.context.eval('player.audio.paused'))
        self.assertEqual(self.context.eval('player.audio.currentTime'), 0)
        self.assertEqual(self.context.eval('player.audio.playCount'), 1)

    def test_decode_and_play_errors_are_reported_but_pause_abort_is_ignored(self):
        self.context.eval("player.audio.play = () => Promise.reject({name:'AbortError'}); player.play()")
        while self.context.execute_pending_job():
            pass
        self.assertIsNone(self.context.eval('player.error'))
        self.context.eval("player.audio.play = () => Promise.reject({name:'NotSupportedError', message:'bad MP3'}); player.play()")
        while self.context.execute_pending_job():
            pass
        self.assertEqual(self.context.eval('player.error'), 'bad MP3')
        self.context.eval("player.audio.error = {message:'decode failed'}; player.audio.events.error()")
        self.assertEqual(self.context.eval('player.error'), 'decode failed')


class MusicPersistenceTests(unittest.TestCase):
    def test_all_album_mutations_sync_browser_storage_after_success(self):
        with tempfile.TemporaryDirectory() as temporary, \
                patch.object(c, 'MUSIC_DIR', str(Path(temporary, 'music'))), \
                patch.object(queries, 'sync_persisted_dir') as sync:
            source = Path(temporary, 'song.mp3')
            source.write_bytes(b'mp3 fixture')
            queries.create_album('Mine')
            queries.add_song_to_album(str(source), 'Mine')
            queries.delete_song(str(Path(c.MUSIC_DIR, 'Mine/song.mp3')))
            queries.delete_album('Mine')
            self.assertEqual(sync.call_args_list, [call(c.MUSIC_DIR)] * 4)
            with self.assertRaises(ValueError):
                queries.add_song_to_album(str(source), 'Missing')
            self.assertEqual(sync.call_count, 4)

    def test_music_is_persisted_without_overriding_bundled_albums(self):
        self.assertIn(c.MUSIC_DIR, game_platform._persisted_roots())
        self.assertEqual(json.loads(game_platform._persisted_exclusions(c.MUSIC_DIR)),
                         list(c.UNDELETABLE_ALBUMS))
        self.assertEqual(json.loads(game_platform._persisted_exclusions(c.SAVES_DIR)), [])

    def test_only_music_writes_directory_markers_to_shared_storage(self):
        import platform

        push = Mock()
        window = SimpleNamespace(__gd5_persist_push=push)
        with patch.object(platform, 'window', window, create=True), \
                patch.object(game_platform, 'IS_WEB', True), \
                patch.object(game_platform, '_ensure_persist_js'):
            game_platform.sync_persisted_dir(c.MUSIC_DIR)
            game_platform.sync_persisted_dir(c.MODS_DIR)
        self.assertTrue(push.call_args_list[0].args[2])
        self.assertFalse(push.call_args_list[1].args[2])

    def test_startup_restores_music_before_controller_scans_albums(self):
        trace = []
        game = SimpleNamespace(run=AsyncMock())
        with patch.object(game_main, '_import_project_modules'), \
                patch.object(game_main, 'IS_WEB', True, create=True), \
                patch.object(game_main, 'c', c, create=True), \
                patch.object(game_main, 'restore_persisted_dir',
                             AsyncMock(side_effect=lambda root: trace.append(root)), create=True), \
                patch.object(game_main, 'Controller', side_effect=lambda: trace.append('controller') or game):
            asyncio.run(game_main._run_game())
        self.assertLess(trace.index(c.MUSIC_DIR), trace.index('controller'))


class WebAudioBuildTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.sources = [self.root / "assets/sounds/Info.mp3",
                        self.root / "assets/music/Album/song.mp3"]
        for source in self.sources:
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_bytes(b"mp3 fixture")
        self.ffmpeg = SimpleNamespace(get_ffmpeg_exe=lambda: "ffmpeg")

    def test_conversion_covers_effects_and_music_and_keeps_wav(self):
        wav = self.root / "assets/sounds/Back.wav"
        wav.write_bytes(b"wav fixture")

        def convert(command, **kwargs):
            Path(command[-1]).write_bytes(b"OggS fixture")
            return subprocess.CompletedProcess(command, 0, stderr=b"")

        with patch.dict(sys.modules, {"imageio_ffmpeg": self.ffmpeg}), \
                patch.object(html_compilation.subprocess, "run", side_effect=convert):
            html_compilation.transcode_web_audio(self.root)
        for source in self.sources:
            self.assertFalse(source.exists())
            self.assertEqual(source.with_suffix(".ogg").read_bytes(), b"OggS fixture")
        self.assertEqual(wav.read_bytes(), b"wav fixture")

    def test_conversion_failure_stops_build_and_preserves_source(self):
        with patch.dict(sys.modules, {"imageio_ffmpeg": self.ffmpeg}), \
                patch.object(html_compilation.subprocess, "run", return_value=
                             subprocess.CompletedProcess([], 1, stderr=b"decoder failed")):
            with self.assertRaisesRegex(RuntimeError, "decoder failed"):
                html_compilation.transcode_web_audio(self.root)
        self.assertTrue(all(source.exists() for source in self.sources))

    def test_missing_converter_explains_how_to_install_it(self):
        with patch.dict(sys.modules, {"imageio_ffmpeg": None}):
            with self.assertRaisesRegex(RuntimeError, "pip install imageio-ffmpeg"):
                html_compilation.transcode_web_audio(self.root)


if __name__ == "__main__":
    unittest.main()
