"""Web audio conversion and effect loading must preserve working sounds."""

from collections import OrderedDict
from contextlib import redirect_stdout
import io
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import pygame

from compilation_scripts import html_compilation
from ui import music_playback
from ui.widgets import ui_elements


class WebAudioTests(unittest.TestCase):
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
