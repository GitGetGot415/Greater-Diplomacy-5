import json
import unittest
from unittest.mock import Mock, mock_open, patch


import numpy as np
import pygame

from ui.widgets import ui_elements


class PygameSfxPitchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if pygame.mixer.get_init() is None:
            pygame.mixer.init(frequency=44100, size=-16, channels=2)

    def setUp(self):
        self.old_click_sound = ui_elements.pygame_click_sound
        self.old_slider_sound = ui_elements.pygame_slider_sound
        self.old_pitch = ui_elements.global_sfx_pitch
        self.old_volume = ui_elements.global_sfx_volume
        self.old_multipliers = ui_elements.sound_volume_multipliers.copy()
        self.old_offsets = ui_elements.sound_start_offsets.copy()
        ui_elements.sound_start_offsets.clear()
        self.old_caches = {
            kind: cache.copy()
            for kind, cache in ui_elements._pygame_sfx_pitch_cache.items()
        }
        channels = pygame.mixer.get_init()[2]
        shape = (120, channels) if channels > 1 else (120,)
        samples = np.full(shape, 1000, dtype=np.int16)
        self.sound = pygame.sndarray.make_sound(samples)

    def tearDown(self):
        ui_elements.pygame_click_sound = self.old_click_sound
        ui_elements.pygame_slider_sound = self.old_slider_sound
        ui_elements.global_sfx_pitch = self.old_pitch
        ui_elements.global_sfx_volume = self.old_volume
        ui_elements.sound_volume_multipliers.clear()
        ui_elements.sound_volume_multipliers.update(self.old_multipliers)
        ui_elements.sound_start_offsets.clear()
        ui_elements.sound_start_offsets.update(self.old_offsets)
        for kind, cache in ui_elements._pygame_sfx_pitch_cache.items():
            cache.clear()
            cache.update(self.old_caches[kind])

    def test_resampling_changes_duration_for_sfx_pitch(self):
        slower = ui_elements._resample_pygame_sound(self.sound, 0.5)
        faster = ui_elements._resample_pygame_sound(self.sound, 1.5)

        self.assertEqual(pygame.sndarray.array(slower).shape[0], 240)
        self.assertEqual(pygame.sndarray.array(faster).shape[0], 80)

    def test_pitched_pygame_sound_is_cached_per_ui_sound_kind(self):
        ui_elements.set_pygame_ui_sounds(self.sound, self.sound)
        ui_elements.set_sfx_pitch(0.0)

        first = ui_elements._pygame_sound_at_pitch("click")
        second = ui_elements._pygame_sound_at_pitch("click")
        slider = ui_elements._pygame_sound_at_pitch("slider")

        self.assertIs(first, second)
        self.assertIsNot(first, slider)
        self.assertEqual(pygame.sndarray.array(first).shape[0], 240)
        self.assertEqual(len(ui_elements._pygame_sfx_pitch_cache["click"]), 1)
        self.assertEqual(len(ui_elements._pygame_sfx_pitch_cache["slider"]), 1)

    def test_volume_config_loads_filename_multipliers_and_defaults(self):
        values = {"Slider.wav": 2.5, "Select Song.wav": 0}
        with patch("builtins.open", mock_open(read_data=json.dumps(values))):
            ui_elements.load_sound_volumes()
        ui_elements.global_sfx_volume = 0.4
        with patch.object(ui_elements.c, "SOUND_CLICK_PATH", "assets/sounds/Slider.wav"):
            self.assertEqual(ui_elements._ui_sound_volume("click"), 1.0)
        self.assertEqual(ui_elements._ui_sound_volume("select_song"), 0)
        self.assertEqual(ui_elements._ui_sound_volume("open_music"), 0.4)
        with patch("builtins.open", side_effect=FileNotFoundError):
            ui_elements.load_sound_volumes()
        self.assertEqual(ui_elements._ui_sound_volume("select_song"), 0.4)

    def test_volume_config_rejects_invalid_values_and_json(self):
        for value in [-1, True, "2", None, float("inf"), float("nan")]:
            with self.subTest(value=value):
                contents = json.dumps({"Select Song.wav": value})
                with patch("builtins.open", mock_open(read_data=contents)):
                    with self.assertRaisesRegex(ValueError, "Select Song.wav"):
                        ui_elements.load_sound_volumes()
        for contents in ["[]", "{"]:
            with patch("builtins.open", mock_open(read_data=contents)):
                with self.assertRaisesRegex(ValueError, "volumes.json"):
                    ui_elements.load_sound_volumes()

    def test_sound_config_accepts_numbers_and_optional_object_fields(self):
        values = {"Slider.wav": 2.5, "Select Song.wav": {"volume": 0.5, "offset": 0.25},
                  "Info.mp3": {"offset": 0.1}, "Table.wav": {"volume": 2}, "Open Music.wav": {}}
        with patch("builtins.open", mock_open(read_data=json.dumps(values))):
            ui_elements.load_sound_volumes()
        self.assertEqual(ui_elements.sound_volume_multipliers,
                         {"Slider.wav": 2.5, "Select Song.wav": 0.5, "Info.mp3": 1.0,
                          "Table.wav": 2, "Open Music.wav": 1.0})
        self.assertEqual(ui_elements.sound_start_offsets,
                         {"Slider.wav": 0.0, "Select Song.wav": 0.25, "Info.mp3": 0.1,
                          "Table.wav": 0.0, "Open Music.wav": 0.0})

    def test_sound_config_rejects_invalid_values_and_preserves_previous_settings(self):
        ui_elements.sound_volume_multipliers["existing.wav"] = 2
        ui_elements.sound_start_offsets["existing.wav"] = 0.5
        for field in ("volume", "offset"):
            for invalid in [-1, True, "2", None, float("inf"), float("nan")]:
                with self.subTest(field=field, invalid=invalid):
                    contents = json.dumps({"test.wav": {field: invalid}})
                    with patch("builtins.open", mock_open(read_data=contents)):
                        with self.assertRaisesRegex(ValueError, f"test.wav {field}"):
                            ui_elements.load_sound_volumes()
                    self.assertEqual(ui_elements.sound_volume_multipliers["existing.wav"], 2)
                    self.assertEqual(ui_elements.sound_start_offsets["existing.wav"], 0.5)
        with patch("builtins.open", mock_open(read_data='{"test.wav": {"offest": 1}}')):
            with self.assertRaisesRegex(ValueError, "offest"):
                ui_elements.load_sound_volumes()

    def test_pygame_offset_trims_source_before_pitch_and_handles_end_of_sound(self):
        sample_rate, _, channels = pygame.mixer.get_init()
        frames = np.arange(1000, dtype=np.int16)
        samples = np.repeat(frames[:, None], channels, axis=1) if channels > 1 else frames
        source = pygame.sndarray.make_sound(samples)
        ui_elements.set_pygame_ui_sounds(source, source)
        with patch.object(ui_elements.c, "SOUND_CLICK_PATH", "assets/sounds/fixture.wav"):
            ui_elements.sound_start_offsets["fixture.wav"] = 100 / sample_rate
            ui_elements.set_sfx_pitch(0.5)
            trimmed = ui_elements._pygame_sound_at_pitch("click")
            np.testing.assert_array_equal(pygame.sndarray.array(trimmed), samples[100:])
            self.assertIs(trimmed, ui_elements._pygame_sound_at_pitch("click"))
            ui_elements.set_sfx_pitch(1.0)
            pitched = pygame.sndarray.array(ui_elements._pygame_sound_at_pitch("click"))
            np.testing.assert_array_equal(pitched[0], samples[100])
            self.assertEqual(len(pitched), 600)
            ui_elements.sound_start_offsets["fixture.wav"] = 1000 / sample_rate
            self.assertIsNone(ui_elements._pygame_sound_at_pitch("click"))
        np.testing.assert_array_equal(pygame.sndarray.array(source), samples)

    def test_soloud_seeks_paused_at_normal_speed_before_playback(self):
        ui_elements.sound_start_offsets["Select Song.wav"] = 0.25
        ui_elements.sound_volume_multipliers["Select Song.wav"] = 1.0
        ui_elements.global_sfx_volume = 0.5
        ui_elements.global_sfx_pitch = 1.0
        sound = Mock()
        sound.get_length.return_value = 1.0
        engine = Mock()
        engine.seek.return_value = 0
        with patch.object(ui_elements.c, "USE_SOLOUD", True), \
                patch.object(ui_elements, "soloud_engine", engine), \
                patch.dict(ui_elements.music_ui_sounds, select_song=sound):
            ui_elements.play_ui_sound("select_song")
            handle = engine.play.return_value
            self.assertEqual(engine.mock_calls, [
                unittest.mock.call.play(sound, aPaused=1),
                unittest.mock.call.seek(handle, 0.25),
                unittest.mock.call.set_volume(handle, 0.5),
                unittest.mock.call.set_relative_play_speed(handle, 1.5),
                unittest.mock.call.set_pause(handle, False),
            ])
            engine.reset_mock()
            ui_elements.sound_start_offsets["Select Song.wav"] = 1.0
            ui_elements.play_ui_sound("select_song")
            engine.play.assert_not_called()
            engine.reset_mock()
            ui_elements.sound_start_offsets["Select Song.wav"] = 0.25
            engine.seek.return_value = 1
            ui_elements.play_ui_sound("select_song")
            engine.stop.assert_called_once_with(handle)
            engine.set_pause.assert_not_called()

    def test_amplification_boosts_samples_and_clips_without_wraparound(self):
        samples = pygame.sndarray.array(self.sound)
        samples[0] = 20000
        samples[1] = -20000
        source = pygame.sndarray.make_sound(samples)
        boosted = ui_elements._amplify_pygame_sound(source, 2)
        actual = pygame.sndarray.array(boosted)
        np.testing.assert_array_equal(actual[0], np.full_like(actual[0], 32767))
        np.testing.assert_array_equal(actual[1], np.full_like(actual[1], -32768))
        np.testing.assert_array_equal(actual[2:], samples[2:] * 2)
        np.testing.assert_array_equal(pygame.sndarray.array(source), samples)

    def test_boosted_pitch_variants_are_cached_separately(self):
        ui_elements.set_pygame_ui_sounds(self.sound, self.sound)
        ui_elements.set_sfx_pitch(0)
        normal = ui_elements._pygame_sound_at_pitch("click")
        boosted = ui_elements._pygame_sound_at_pitch("click", 2)
        self.assertIs(boosted, ui_elements._pygame_sound_at_pitch("click", 2))
        np.testing.assert_array_equal(pygame.sndarray.array(boosted), pygame.sndarray.array(normal) * 2)
        with patch("builtins.open", side_effect=FileNotFoundError):
            ui_elements.load_sound_volumes()
        self.assertIsNot(boosted, ui_elements._pygame_sound_at_pitch("click", 2))

    def test_backend_volume_uses_master_times_multiplier(self):
        ui_elements.sound_volume_multipliers["Select Song.wav"] = 4
        ui_elements.global_sfx_volume = 0.5
        engine = Mock()
        sound = Mock()
        with patch.object(ui_elements.c, "USE_SOLOUD", True), \
                patch.object(ui_elements, "soloud_engine", engine), \
                patch.dict(ui_elements.music_ui_sounds, select_song=sound):
            ui_elements.play_ui_sound("select_song")
            engine.set_volume.assert_called_once_with(engine.play.return_value, 2)
        with patch.object(ui_elements.c, "USE_SOLOUD", False), \
                patch.object(ui_elements, "_pygame_sound_at_pitch", return_value=sound) as prepare:
            ui_elements.play_ui_sound("select_song")
            prepare.assert_called_once_with("select_song", 2)
            sound.set_volume.assert_called_once_with(1)
            ui_elements.global_sfx_volume = 0.125
            ui_elements.play_ui_sound("select_song")
            prepare.assert_called_with("select_song", 1)
            sound.set_volume.assert_called_with(0.5)
            sound.play.reset_mock()
            ui_elements.global_sfx_volume = 0
            ui_elements.play_ui_sound("select_song")
            sound.play.assert_not_called()
            ui_elements.global_sfx_volume = 1
            ui_elements.sound_volume_multipliers["Select Song.wav"] = 0
            ui_elements.play_ui_sound("select_song")
            sound.play.assert_not_called()


if __name__ == "__main__":
    unittest.main()
