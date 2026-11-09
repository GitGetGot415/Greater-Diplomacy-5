import os
import subprocess
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

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

    def set_protect_voice(self, _handle, _protected):
        pass

    def set_inaudible_behavior(self, _handle, _must_tick, _kill):
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
    def test_soloud_music_voice_is_protected_before_playback_starts(self):
        engine = Mock()
        engine.play.return_value = 11
        stream = Mock()
        with patch.object(SoLoudPlayback, "_load"):
            playback = SoLoudPlayback(engine, stream, "fixture.ogg", 12, 0.2, 0.8)
        engine.play.assert_called_once_with(stream, aPaused=1)
        engine.set_protect_voice.assert_called_once_with(playback.handle, True)
        engine.set_inaudible_behavior.assert_called_once_with(playback.handle, True, False)
        self.assertLess(engine.mock_calls.index(call.set_protect_voice(11, True)),
                        engine.mock_calls.index(call.set_pause(11, False)))
        self.assertLess(engine.mock_calls.index(call.set_inaudible_behavior(11, True, False)),
                        engine.mock_calls.index(call.set_pause(11, False)))
        engine.seek.assert_called_once_with(11, 12)
        engine.set_volume.assert_called_once_with(11, 0.2)
        engine.set_relative_play_speed.assert_called_once_with(11, 0.8)

    def test_soloud_seek_protects_the_replacement_voice_and_preserves_pause_state(self):
        for paused in (False, True):
            with self.subTest(paused=paused):
                engine = Mock()
                engine.play.side_effect = [11, 22]
                stream = Mock()
                with patch.object(SoLoudPlayback, "_load"):
                    playback = SoLoudPlayback(engine, stream, "fixture.ogg", 0, 0.2, 0.8)
                    playback.pause(paused)
                    engine.reset_mock()
                    playback.seek(24)
                engine.stop.assert_called_once_with(11)
                engine.play.assert_called_once_with(stream, aPaused=1)
                engine.set_protect_voice.assert_called_once_with(22, True)
                engine.set_inaudible_behavior.assert_called_once_with(22, True, False)
                engine.seek.assert_called_once_with(22, 24)
                engine.set_volume.assert_called_once_with(22, 0.2)
                engine.set_relative_play_speed.assert_called_once_with(22, 0.8)
                self.assertEqual(playback.paused, paused)
                if paused:
                    engine.set_pause.assert_not_called()
                else:
                    self.assertLess(engine.mock_calls.index(call.set_protect_voice(22, True)),
                                    engine.mock_calls.index(call.set_pause(22, False)))
                    self.assertLess(engine.mock_calls.index(call.set_inaudible_behavior(22, True, False)),
                                    engine.mock_calls.index(call.set_pause(22, False)))

    @unittest.skipUnless(os.environ.get("GD5_RUN_NATIVE_AUDIO_TESTS") == "1", "native audio integration is opt-in")
    def test_native_music_remains_audible_when_effects_exceed_active_voice_limit(self):
        # Isolate the native engine and use NULLDRIVER: no audio device or real
        # song is needed. Silent effects with high volume still occupy mix slots.
        script = r"""
import ctypes
import os
from pathlib import Path
import tempfile
import wave
if os.name == 'nt':
    ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0002 | 0x8000)
from soloud import Soloud, Wav, WavStream, Soloud_mixSigned16
from ui.music_playback import SoLoudPlayback

engine = Soloud()
assert engine.init(aBackend=Soloud.NULLDRIVER, aSamplerate=44100, aBufferSize=512) == 0
stream, effect = WavStream(), Wav()
try:
    assert engine.set_max_active_voice_count(4) == 0
    silence = (ctypes.c_short * 44100)()
    assert effect.load_raw_wave16(silence, len(silence)) == 0
    output = (ctypes.c_short * 1024)()
    def music_peak():
        for _ in range(4):
            Soloud_mixSigned16(engine.objhandle, output, 512)
        return max(abs(sample) for sample in output)
    with tempfile.TemporaryDirectory() as directory:
        track = Path(directory) / 'fixture.wav'
        with wave.open(str(track), 'wb') as writer:
            writer.setparams((1, 2, 44100, 0, 'NONE', 'not compressed'))
            writer.writeframes(bytes((ctypes.c_short * 44100)(*([10000] * 44100))))
        playback = SoLoudPlayback(engine, stream, str(track), 0, 0.1, 1)
        baseline = music_peak()
        assert baseline > 0
        for _ in range(engine.get_max_active_voice_count() * 2):
            engine.play(effect, aVolume=1)
        assert engine.is_valid_voice_handle(playback.handle)
        assert music_peak() == baseline, 'music stopped mixing under overlapping effects'
        playback.seek(0.25)
        assert music_peak() == baseline, 'seeking lost the reserved music mixing slot'
        playback.stop()
finally:
    engine.deinit()
    stream.destroy()
    effect.destroy()
    engine.destroy()
"""
        result = subprocess.run([sys.executable, "-X", "faulthandler", "-c", script],
                                cwd=os.path.dirname(os.path.dirname(__file__)),
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

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
