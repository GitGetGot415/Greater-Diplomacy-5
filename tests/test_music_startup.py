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
        with patch("screens.menus.menu.Menu.check_version"):
            app_harness.boot()

    def run_frames(self, frames, *, web=False, now_playing="None"):
        # The harness loads deferred project imports before the real loop runs.
        import main

        trace = []
        state = SimpleNamespace(
            listening_for=None, done=False, handle_events=Mock(), update=Mock(),
            draw=Mock(side_effect=lambda _surface: trace.append("draw")))
        controller = SimpleNamespace(
            clock=Mock(), target_fps=60, music=None,
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
              patch.object(pygame.display, "flip", side_effect=lambda: trace.append("flip"))):
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


class TacticalMusicTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch("screens.menus.menu.Menu.check_version"):
            app_harness.boot()

    def setUp(self):
        import main
        self.controller = object.__new__(main.Controller)
        controller = self.controller
        controller.tactical_battle_song = "battle.ogg"
        controller._tactical_music_active = False
        controller._tactical_music_resume = None
        controller._failed_music_tracks = set()
        controller.shuffle_disabled_tracks = {"battle.ogg"}
        controller.playlist = ["playlist.ogg", "other.ogg"]
        controller.now_playing = "playlist.ogg"
        controller.music_volume = 0.5
        controller.music_pitch = 0.5
        controller.music_pitch_timeline = main.c.MUSIC_PITCH_TIMELINE_STATIC
        controller.track_start_times = {}
        self.original_music = self.playback(position=37.5)
        controller.music = self.original_music
        self.played = []

        def play(track):
            if controller.music is not None:
                controller.music.stop()
            controller.music = self.playback()
            controller.now_playing = track
            self.played.append(track)

        self.play = self.enterContext(patch.object(controller, "play_specific_song", side_effect=play))

    @staticmethod
    def playback(position=0.0):
        return Mock(finished=False, paused=False, error=None,
                    source_position=Mock(return_value=position))

    def test_override_loops_without_changing_playlist_and_restores_position(self):
        controller = self.controller
        controller.set_tactical_battle_music(True)
        self.assertEqual(self.played, ["battle.ogg"])
        controller.set_tactical_battle_music(True)
        self.assertEqual(self.played, ["battle.ogg"])
        controller.play_random_song()
        self.assertEqual(self.played, ["battle.ogg", "battle.ogg"])
        controller.set_tactical_battle_music(False)
        self.assertEqual(controller.now_playing, "playlist.ogg")
        controller.music.seek.assert_called_once_with(37.5)
        controller.music.pause.assert_called_once_with(False)
        self.assertEqual(controller.playlist, ["playlist.ogg", "other.ogg"])
        self.assertEqual(controller.shuffle_disabled_tracks, {"battle.ogg"})
        self.assertFalse(controller._tactical_music_active)
        controller.set_tactical_battle_music(False)
        self.assertEqual(self.played, ["battle.ogg", "battle.ogg", "playlist.ogg"])

    def test_no_selection_does_not_interrupt_normal_music(self):
        self.controller.tactical_battle_song = ""
        self.controller.set_tactical_battle_music(True)
        self.controller.set_tactical_battle_music(False)
        self.play.assert_not_called()
        self.original_music.stop.assert_not_called()

    def test_prior_pause_state_is_restored(self):
        self.original_music.paused = True
        self.controller.set_tactical_battle_music(True)
        self.controller.set_tactical_battle_music(False)
        self.controller.music.pause.assert_called_once_with(True)

    def test_no_prior_track_returns_to_normal_playlist_selection(self):
        self.controller.music = None
        self.controller.now_playing = "None"
        self.controller.set_tactical_battle_music(True)
        self.controller.set_tactical_battle_music(False)
        self.assertIn(self.controller.now_playing, self.controller.playlist)

    def test_missing_position_does_not_seek_the_resumed_song(self):
        self.original_music.source_position.return_value = None
        self.controller.set_tactical_battle_music(True)
        self.controller.set_tactical_battle_music(False)
        self.controller.music.seek.assert_not_called()

    def test_failed_beepbox_song_repeats_its_working_audio_fallback(self):
        self.controller.tactical_battle_song = "battle.json"
        self.controller._failed_music_tracks.add("battle.json")
        with patch.object(self.controller, "_beepbox_audio_fallback", return_value="battle.ogg"):
            self.controller.set_tactical_battle_music(True)
            self.controller.play_random_song()
        self.assertEqual(self.played, ["battle.ogg", "battle.ogg"])

    def test_failed_audio_track_is_skipped_instead_of_retried(self):
        import main
        # Exercise the real backend-selection and failure path without audio files.
        self.play.side_effect = lambda path: main.Controller.play_specific_song(self.controller, path)

        def backend(path, *_args):
            if path == "battle.ogg":
                raise OSError("fixture unavailable track")
            return self.playback()

        with patch.object(main.c, "USE_SOLOUD", False), \
                patch.object(main, "IS_WEB", False), \
                patch.object(main.music_playback, "PygamePlayback", side_effect=backend) as playback:
            self.controller.set_tactical_battle_music(True)
            self.assertIn(self.controller.now_playing, self.controller.playlist)
            self.assertIn("battle.ogg", self.controller._failed_music_tracks)
            self.controller.play_random_song()
            self.assertEqual(sum(call.args[0] == "battle.ogg" for call in playback.call_args_list), 1)
            self.controller.set_tactical_battle_music(False)
            self.assertEqual(self.controller.now_playing, "playlist.ogg")
            self.controller.music.seek.assert_called_once_with(37.5)

    def test_failed_synth_and_audio_counterpart_return_to_playlist_without_recursion(self):
        import main
        import beepbox_audio
        self.controller.tactical_battle_song = "battle.json"
        self.play.side_effect = lambda path: main.Controller.play_specific_song(self.controller, path)

        def backend(path, *_args):
            if path == "battle.ogg":
                raise OSError("fixture bad audio counterpart")
            return self.playback()

        with patch.object(main.c, "USE_SOLOUD", False), patch.object(main, "IS_WEB", False), \
                patch.object(beepbox_audio, "is_beepbox_song", return_value=True), \
                patch.object(beepbox_audio, "BeepBoxStream", side_effect=OSError("fixture bad synth")) as synth, \
                patch.object(main.music_playback, "PygamePlayback", side_effect=backend) as playback, \
                patch.object(self.controller, "_beepbox_audio_fallback", return_value="battle.ogg"):
            self.controller.set_tactical_battle_music(True)
            self.controller.play_random_song()
        self.assertIn(self.controller.now_playing, self.controller.playlist)
        self.assertEqual(self.controller._failed_music_tracks, {"battle.json", "battle.ogg"})
        self.assertEqual(synth.call_count, 1)
        self.assertEqual(sum(call.args[0] == "battle.ogg" for call in playback.call_args_list), 1)


if __name__ == "__main__":
    unittest.main()
