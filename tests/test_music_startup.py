"""Check startup music timing against frame presentation and browser input."""

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pygame

from tests import app_harness


class StartupMusicTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app_harness.boot()

    def run_frames(self, frames, *, web=False, now_playing="None"):
        # The harness loads deferred project imports before the real loop runs.
        import main

        trace = []
        state = SimpleNamespace(
            listening_for=None, done=False, handle_events=Mock(), update=Mock(),
            draw=Mock(side_effect=lambda _surface: trace.append("draw")))
        controller = SimpleNamespace(
            clock=Mock(), target_fps=60, beepbox_stream=None, music_handle=None,
            now_playing=now_playing, _web_audio_unlocked=False, keybinds={},
            init_web_audio=Mock(), _shutdown_audio=Mock(), active_state=state,
            screen=object(), show_fps=False,
            play_startup_song=Mock(side_effect=lambda: trace.append("music")))
        events = [*frames, [pygame.event.Event(pygame.QUIT)]]
        with (patch.object(main, "IS_WEB", web),
              patch.object(main.c, "USE_SOLOUD", False),
              patch.object(main.modal_stack, "active", return_value=None),
              patch.object(main, "keyboard_input_is_captured", return_value=False),
              patch.object(main, "synthesize_keybind_mouse_events",
                           side_effect=lambda events, *_args, **_kwargs: events),
              patch.object(pygame.event, "get", side_effect=events),
              patch.object(pygame.display, "flip", side_effect=lambda: trace.append("flip")),
              patch.object(pygame.mixer.music, "get_busy", return_value=True)):
            asyncio.run(main.Controller.run(controller))
        return controller, trace

    def test_desktop_starts_music_once_after_first_presented_frame(self):
        controller, trace = self.run_frames([[], []])
        self.assertEqual(trace, ["draw", "flip", "music", "draw", "flip"])
        controller.play_startup_song.assert_called_once_with()

    def test_closing_before_first_frame_does_not_start_music(self):
        controller, trace = self.run_frames([])
        self.assertEqual(trace, [])
        controller.play_startup_song.assert_not_called()

    def test_existing_track_is_not_replaced_by_startup_music(self):
        controller, _trace = self.run_frames([[]], now_playing="chosen-track.mp3")
        controller.play_startup_song.assert_not_called()

    def test_browser_waits_for_input_and_starts_music_only_once(self):
        controller, _trace = self.run_frames([[], []], web=True)
        controller.init_web_audio.assert_not_called()
        controller.play_startup_song.assert_not_called()
        gesture = pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(10, 10))
        controller, _trace = self.run_frames([[], [gesture], [gesture]], web=True)
        controller.init_web_audio.assert_called_once_with()
        controller.play_startup_song.assert_called_once_with()

    def test_constructor_does_not_start_music(self):
        import main

        with (patch.object(main.Controller, "play_startup_song") as play,
              patch.object(main.Menu, "check_version")):
            main.Controller()
        play.assert_not_called()


if __name__ == "__main__":
    unittest.main()
