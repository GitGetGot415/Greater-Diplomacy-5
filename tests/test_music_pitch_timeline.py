import unittest
from types import SimpleNamespace
from unittest.mock import patch

import data.constants as c
from screens.menus.music_player import Music_Player
from ui.music_playback import BeepBoxPlayback, SoLoudPlayback


class FakeBeepBoxStream:
    def __init__(self, position, speed, length=480):
        self.position = position
        self.speed = speed
        self.length = length
        self.seeks = []

    def seek(self, position, speed=None):
        self.seeks.append((position, speed))
        self.position = position
        if speed is not None:
            self.speed = speed


class FakeSoloud:
    def __init__(self, source_position):
        self.source_position = source_position
        self.speed_changes = []
        self.seeks = []
        self.pauses = []

    def get_stream_position(self, _handle):
        return self.source_position

    def set_relative_play_speed(self, _handle, speed):
        self.speed_changes.append(speed)

    def stop(self, _handle):
        pass

    def play(self, _stream, aPaused=0):
        return 2

    def set_volume(self, _handle, _volume):
        pass

    def seek(self, _handle, position):
        self.seeks.append(position)
        self.source_position = position

    def set_pause(self, _handle, paused):
        self.pauses.append(paused)


def make_player(controller):
    player = object.__new__(Music_Player)
    player.controller = controller
    player.save_audio_settings = lambda: None
    return player


def soloud_playback(soloud, speed, length=480):
    """A SoLoud playback of a fake 'song.mp3', with the start-up speed call cleared."""
    with patch.object(SoLoudPlayback, "_load"):
        playback = SoLoudPlayback(soloud, SimpleNamespace(get_length=lambda: length),
                                  "song.mp3", 0.0, 1.0, speed)
    soloud.speed_changes.clear()
    return playback


class MusicPitchTimelineTests(unittest.TestCase):
    def test_beepbox_speed_change_preserves_musical_progress(self):
        stream = FakeBeepBoxStream(position=240, speed=1.0)
        controller = SimpleNamespace(
            music=BeepBoxPlayback(stream),
            music_pitch=0.5,
            music_pitch_timeline=c.MUSIC_PITCH_TIMELINE_DYNAMIC,
            _frozen_time=240,
        )
        player = make_player(controller)

        player.set_music_pitch(0.3)

        self.assertEqual(stream.seeks, [(300, 0.8)])
        self.assertEqual(controller.music_pitch, 0.3)
        self.assertEqual(controller._frozen_time, 300)
        self.assertAlmostEqual(stream.position / (480 / stream.speed), 0.5)

    def test_soloud_duration_and_position_use_scaled_playback_time(self):
        soloud = FakeSoloud(source_position=240)
        controller = SimpleNamespace(
            music=soloud_playback(soloud, speed=0.8),
            music_pitch=0.3,
            music_pitch_timeline=c.MUSIC_PITCH_TIMELINE_DYNAMIC,
            now_playing="song.mp3",
            _frozen_time=0,
        )
        player = make_player(controller)

        self.assertEqual(player.get_current_track_length(), 600)
        self.assertAlmostEqual(player.get_current_track_pos(), 300)

        player.set_music_pitch(0.5)

        self.assertEqual(soloud.speed_changes, [1.0])
        self.assertEqual(controller._frozen_time, 240)
        self.assertEqual(player.get_current_track_length(), 480)
        self.assertAlmostEqual(player.get_current_track_pos(), 240)

    def test_soloud_scrubbing_converts_playback_time_to_source_time(self):
        soloud = FakeSoloud(source_position=0)
        controller = SimpleNamespace(
            music=soloud_playback(soloud, speed=0.8),
            music_pitch=0.3,
            music_pitch_timeline=c.MUSIC_PITCH_TIMELINE_DYNAMIC,
            now_playing="song.mp3",
            _frozen_time=0,
        )
        player = make_player(controller)

        with patch.object(SoLoudPlayback, "_load"):
            player.scrub_music(0.5)

        self.assertAlmostEqual(soloud.seeks[0], 239.8)
        self.assertAlmostEqual(controller._frozen_time, 299.75)
        self.assertEqual(soloud.speed_changes, [0.8])

    def test_static_beepbox_timeline_keeps_the_source_position_and_length(self):
        stream = FakeBeepBoxStream(position=300, speed=0.8, length=600)
        controller = SimpleNamespace(
            music=BeepBoxPlayback(stream),
            music_pitch=0.3,
            music_pitch_timeline=c.MUSIC_PITCH_TIMELINE_STATIC,
            now_playing="song.json",
            _frozen_time=240,
        )
        player = make_player(controller)

        self.assertEqual(player.get_current_track_length(), 480)
        self.assertEqual(player.get_current_track_pos(), 240)
        player.set_music_pitch(0.5)

        self.assertEqual(stream.seeks, [(240, 1.0)])
        self.assertEqual(controller._frozen_time, 240)

    def test_static_soloud_scrubbing_uses_source_track_seconds(self):
        soloud = FakeSoloud(source_position=0)
        controller = SimpleNamespace(
            music=soloud_playback(soloud, speed=0.8),
            music_pitch=0.3,
            music_pitch_timeline=c.MUSIC_PITCH_TIMELINE_STATIC,
            now_playing="song.mp3",
            _frozen_time=0,
        )
        player = make_player(controller)

        with patch.object(SoLoudPlayback, "_load"):
            player.scrub_music(0.5)

        self.assertAlmostEqual(soloud.seeks[0], 239.75)
        self.assertAlmostEqual(controller._frozen_time, 239.75)

    def test_timeline_buttons_switch_and_persist_the_preference_without_a_song(self):
        controller = SimpleNamespace(
            now_playing="None",
            music_pitch_timeline=c.MUSIC_PITCH_TIMELINE_STATIC,
        )
        player = make_player(controller)
        player.refresh_ui = lambda: None

        player.set_dynamic_pitch_timeline()

        self.assertEqual(controller.music_pitch_timeline,
                         c.MUSIC_PITCH_TIMELINE_DYNAMIC)


if __name__ == "__main__":
    unittest.main()
