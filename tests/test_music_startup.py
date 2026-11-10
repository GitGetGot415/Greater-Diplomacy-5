"""Check startup music timing against frame presentation and browser input."""

import asyncio
import json
import os
import tempfile
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
            touch_input=main.TouchInput(), control_mode=main.c.DEFAULT_CONTROL_MODE,
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

    def test_finger_down_unlocks_browser_audio_before_a_tap_is_completed(self):
        gesture = pygame.event.Event(pygame.FINGERDOWN, touch_id=1, finger_id=1,
                                      x=0.5, y=0.5)
        controller, _trace = self.run_frames([[gesture]], web=True)
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
        controller.tactical_infantry_songs = ["battle.ogg"]
        controller.tactical_tank_songs = ["tank-one.ogg", "tank-two.ogg"]
        controller._tactical_song_setting = None
        controller._failed_music_tracks = set()
        controller.shuffle_disabled_tracks = {"battle.ogg"}
        controller.playlist = ["playlist.ogg", "other.ogg"]
        controller.now_playing = "playlist.ogg"
        controller.music_volume = 0.5
        controller.music_pitch = 0.5
        controller.music_pitch_timeline = main.c.MUSIC_PITCH_TIMELINE_STATIC
        controller.track_start_times = {}
        controller.track_volumes = {}
        controller.music_volume_scale = 1.0
        self.original_music = self.playback()
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
    def playback():
        return Mock(finished=False, paused=False, error=None)

    def test_override_loops_then_stops_and_uses_normal_playlist_selection(self):
        controller = self.controller
        controller.set_tactical_battle_music(True)
        self.assertEqual(self.played, ["battle.ogg"])
        controller.set_tactical_battle_music(True)
        self.assertEqual(self.played, ["battle.ogg"])
        controller.play_random_song()
        self.assertEqual(self.played, ["battle.ogg", "battle.ogg"])
        battle_music = controller.music
        with patch("main.random.choice", return_value="other.ogg"):
            controller.set_tactical_battle_music(False)
        battle_music.stop.assert_called_once_with()
        battle_music.pause.assert_not_called()
        self.assertEqual(controller.now_playing, "other.ogg")
        controller.music.seek.assert_not_called()
        controller.music.pause.assert_not_called()
        self.original_music.source_position.assert_not_called()
        self.assertEqual(controller.playlist, ["playlist.ogg", "other.ogg"])
        self.assertEqual(controller.shuffle_disabled_tracks, {"battle.ogg"})
        self.assertIsNone(controller._tactical_song_setting)
        controller.set_tactical_battle_music(False)
        self.assertEqual(self.played, ["battle.ogg", "battle.ogg", "other.ogg"])

    def test_volume_scale_applies_to_the_playing_song_and_later_songs(self):
        controller = self.controller
        controller.track_volumes = {"other.ogg": 0.5}
        controller.set_music_volume_scale(0.25)
        self.original_music.set_volume.assert_called_once_with(0.5 * 0.25)
        self.assertAlmostEqual(controller.track_volume("other.ogg"), 0.5 * 0.5 * 0.25)
        controller.set_music_volume_scale(0.25)
        self.original_music.set_volume.assert_called_once()
        controller.set_music_volume_scale(1.0)
        self.assertEqual(self.original_music.set_volume.call_args.args, (0.5,))

    def test_tank_battles_pick_random_tank_songs_without_repeating(self):
        controller = self.controller
        with patch("main.random.choice", side_effect=lambda tracks: tracks[0]) as choice:
            controller.set_tactical_battle_music(True, tanks=True)
            controller.play_random_song()
        self.assertEqual(self.played, ["tank-one.ogg", "tank-two.ogg"])
        # The second pick excludes the song that just played.
        self.assertEqual(choice.call_args.args[0], ["tank-two.ogg"])
        # A battle without tanks switches to the infantry songs.
        controller.set_tactical_battle_music(True)
        self.assertEqual(self.played, ["tank-one.ogg", "tank-two.ogg", "battle.ogg"])

    def test_empty_tank_list_keeps_normal_music(self):
        self.controller.tactical_tank_songs = []
        self.controller.set_tactical_battle_music(True, tanks=True)
        self.play.assert_not_called()
        self.assertIsNone(self.controller._tactical_song_setting)

    def test_no_selection_does_not_interrupt_normal_music(self):
        self.controller.tactical_infantry_songs = []
        self.controller.set_tactical_battle_music(True)
        self.controller.set_tactical_battle_music(False)
        self.play.assert_not_called()
        self.original_music.stop.assert_not_called()

    def test_prior_pause_state_is_not_restored(self):
        self.original_music.paused = True
        self.controller.set_tactical_battle_music(True)
        self.controller.set_tactical_battle_music(False)
        self.assertFalse(self.controller.music.paused)
        self.controller.music.pause.assert_not_called()
        self.original_music.source_position.assert_not_called()

    def test_no_prior_track_returns_to_normal_playlist_selection(self):
        self.controller.music = None
        self.controller.now_playing = "None"
        self.controller.set_tactical_battle_music(True)
        self.controller.set_tactical_battle_music(False)
        self.assertIn(self.controller.now_playing, self.controller.playlist)

    def test_empty_playlist_stops_battle_music(self):
        self.controller.playlist = []
        self.controller.set_tactical_battle_music(True)
        battle_music = self.controller.music
        self.controller.set_tactical_battle_music(False)
        battle_music.stop.assert_called_once_with()
        battle_music.pause.assert_not_called()
        self.assertIsNone(self.controller.music)
        self.assertEqual(self.controller.now_playing, "None")

    def test_failed_beepbox_song_repeats_its_working_audio_fallback(self):
        self.controller.tactical_infantry_songs = ["battle.json"]
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
            self.assertIn(self.controller.now_playing, self.controller.playlist)
            self.controller.music.seek.assert_not_called()
            self.controller.music.pause.assert_not_called()

    def test_failed_synth_and_audio_counterpart_return_to_playlist_without_recursion(self):
        import main
        import beepbox_audio
        self.controller.tactical_infantry_songs = ["battle.json"]
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


class AlbumVolumesTests(unittest.TestCase):
    """An album's volumes.json uses the format of assets/sounds/volumes.json."""

    @classmethod
    def setUpClass(cls):
        with patch("screens.menus.menu.Menu.check_version"):
            app_harness.boot()

    def test_album_volumes_set_each_tracks_volume_and_offset(self):
        import main
        music_dir = self.enterContext(tempfile.TemporaryDirectory())
        album = os.path.join(music_dir, "Fixture")
        os.mkdir(album)
        for name in ("one.mp3", "two.ogg", "three.wav"):
            open(os.path.join(album, name), "wb").close()
        with open(os.path.join(album, "volumes.json"), "w", encoding="utf-8") as stream:
            # "two.mp3" names two.ogg by its other extension.
            json.dump({"one.mp3": {"volume": 0.5, "offset": 2}, "two.mp3": 3}, stream)
        controller = object.__new__(main.Controller)
        controller.music_volume = 0.8
        controller.music_volume_scale = 1.0
        with patch.object(main.c, "MUSIC_DIR", music_dir),                 patch.object(main.queries, "get_active_albums", return_value=[]),                 patch.object(main.queries, "get_shuffle_disabled_tracks", return_value=[]),                 patch.object(main.queries, "get_starting_song", return_value=None):
            controller.load_music_data()
        track = lambda name: os.path.join(album, name).replace("\\", "/")
        self.assertEqual(controller.track_start_times, {track("one.mp3"): 2, track("two.ogg"): 0.0})
        self.assertAlmostEqual(controller.track_volume(track("one.mp3")), 0.4)
        self.assertAlmostEqual(controller.track_volume(track("two.ogg")), 2.4)
        self.assertAlmostEqual(controller.track_volume(track("three.wav")), 0.8)

    def test_invalid_album_volumes_leave_the_album_playable_without_settings(self):
        import main
        music_dir = self.enterContext(tempfile.TemporaryDirectory())
        album = os.path.join(music_dir, "Fixture")
        os.mkdir(album)
        open(os.path.join(album, "one.mp3"), "wb").close()
        with open(os.path.join(album, "volumes.json"), "w", encoding="utf-8") as stream:
            json.dump({"one.mp3": -1}, stream)
        controller = object.__new__(main.Controller)
        with patch.object(main.c, "MUSIC_DIR", music_dir),                 patch.object(main.queries, "get_active_albums", return_value=[]),                 patch.object(main.queries, "get_shuffle_disabled_tracks", return_value=[]),                 patch.object(main.queries, "get_starting_song", return_value=None),                 patch("builtins.print"):
            controller.load_music_data()
        self.assertEqual(controller.all_albums["Fixture"], [os.path.join(album, "one.mp3").replace("\\", "/")])
        self.assertEqual((controller.track_volumes, controller.track_start_times), ({}, {}))

if __name__ == "__main__":
    unittest.main()
