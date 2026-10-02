import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import main as game_main


class HeadlessAudioTests(unittest.TestCase):
    def test_test_setup_overrides_an_audible_sdl_driver(self):
        from tests import configure_test_audio

        with patch.dict(os.environ, {"SDL_AUDIODRIVER": "wasapi"}):
            configure_test_audio()
            self.assertEqual(os.environ["SDL_AUDIODRIVER"], "dummy")

    def test_application_harness_boots_without_native_output_or_startup_music(self):
        from tests import app_harness
        import data.constants as c
        import ui_elements

        controller, _surface = app_harness.boot()
        self.assertEqual(os.environ["SDL_AUDIODRIVER"], "dummy")
        self.assertFalse(c.USE_SOLOUD)
        self.assertIsNone(ui_elements.soloud_engine)
        self.assertIsNone(controller.beepbox_stream)
        self.assertEqual(controller.now_playing, "None")


class AudioShutdownTests(unittest.TestCase):
    def test_desktop_quit_exits_before_native_audio_teardown(self):
        stream = SimpleNamespace(stop=Mock())
        soloud = SimpleNamespace(deinit=Mock())
        controller = object.__new__(game_main.Controller)
        controller.beepbox_stream = stream
        controller.soloud = soloud

        with patch.object(game_main, "IS_WEB", False, create=True), \
                patch.object(game_main.os, "_exit", side_effect=SystemExit(0)) as exit_process:
            with self.assertRaises(SystemExit):
                controller._shutdown_audio()

        exit_process.assert_called_once_with(0)
        stream.stop.assert_not_called()
        soloud.deinit.assert_not_called()

    def test_web_quit_stops_the_stream_and_mixer(self):
        stream = SimpleNamespace(stop=Mock())
        mixer = SimpleNamespace(quit=Mock())
        controller = object.__new__(game_main.Controller)
        controller.beepbox_stream = stream

        with patch.object(game_main, "IS_WEB", True, create=True), \
                patch.object(game_main, "c", SimpleNamespace(USE_SOLOUD=False), create=True), \
                patch.object(game_main, "pygame", SimpleNamespace(mixer=mixer), create=True):
            controller._shutdown_audio()

        stream.stop.assert_called_once_with()
        mixer.quit.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
