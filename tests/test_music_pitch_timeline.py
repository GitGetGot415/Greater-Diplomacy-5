import unittest
from types import SimpleNamespace
from unittest.mock import patch

from screens.menu_screens.music_player import Music_Player


class FakeBeepBoxStream:
    def __init__(self, position, speed):
        self.position = position
        self.speed = speed
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
    player._track_lengths = {}
    player._last_ticks = 0
    player.save_audio_settings = lambda: None
    return player


class MusicPitchTimelineTests(unittest.TestCase):
    def test_beepbox_speed_change_preserves_musical_progress(self):
        stream = FakeBeepBoxStream(position=240, speed=1.0)
        controller = SimpleNamespace(
            beepbox_stream=stream,
            music_handle=None,
            music_pitch=0.5,
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
            beepbox_stream=None,
            music_handle=1,
            music_pitch=0.3,
            music_stream=SimpleNamespace(get_length=lambda: 480),
            soloud=soloud,
            now_playing="song.mp3",
            is_paused=False,
            _frozen_time=0,
        )
        player = make_player(controller)
        player._track_lengths["song.mp3"] = 480

        with patch("screens.menu_screens.music_player.c.USE_SOLOUD", True):
            self.assertEqual(player.get_current_track_length(), 600)
            self.assertAlmostEqual(player.get_current_track_pos(), 300)

            player.set_music_pitch(0.5)

        self.assertEqual(soloud.speed_changes, [1.0])
        self.assertEqual(controller._frozen_time, 240)
        with patch("screens.menu_screens.music_player.c.USE_SOLOUD", True):
            self.assertEqual(player.get_current_track_length(), 480)
            self.assertAlmostEqual(player.get_current_track_pos(), 240)

    def test_soloud_scrubbing_converts_playback_time_to_source_time(self):
        soloud = FakeSoloud(source_position=0)
        controller = SimpleNamespace(
            beepbox_stream=None,
            music_handle=1,
            music_pitch=0.3,
            music_volume=1.0,
            music_stream=object(),
            soloud=soloud,
            now_playing="song.mp3",
            is_paused=False,
            _frozen_time=0,
            _load_soloud_stream_unicode_safe=lambda _track: None,
        )
        player = make_player(controller)
        player._track_lengths["song.mp3"] = 480

        with patch("screens.menu_screens.music_player.c.USE_SOLOUD", True):
            player.scrub_music(0.5)

        self.assertAlmostEqual(soloud.seeks[0], 239.8)
        self.assertAlmostEqual(controller._frozen_time, 299.75)
        self.assertEqual(soloud.speed_changes, [0.8])


if __name__ == "__main__":
    unittest.main()
