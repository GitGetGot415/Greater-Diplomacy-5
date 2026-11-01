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
        values = {"Slider.wav": 2.5, "Select Music.wav": 0}
        with patch("builtins.open", mock_open(read_data=json.dumps(values))):
            ui_elements.load_sound_volumes()
        ui_elements.global_sfx_volume = 0.4
        with patch.object(ui_elements.c, "SOUND_CLICK_PATH", "assets/sounds/Slider.wav"):
            self.assertEqual(ui_elements._ui_sound_volume("click"), 1.0)
        self.assertEqual(ui_elements._ui_sound_volume("select_music"), 0)
        self.assertEqual(ui_elements._ui_sound_volume("open_music"), 0.4)
        with patch("builtins.open", side_effect=FileNotFoundError):
            ui_elements.load_sound_volumes()
        self.assertEqual(ui_elements._ui_sound_volume("select_music"), 0.4)

    def test_volume_config_rejects_invalid_values_and_json(self):
        for value in [-1, True, "2", None, float("inf"), float("nan")]:
            with self.subTest(value=value):
                contents = json.dumps({"Select Music.wav": value})
                with patch("builtins.open", mock_open(read_data=contents)):
                    with self.assertRaisesRegex(ValueError, "Select Music.wav"):
                        ui_elements.load_sound_volumes()
        for contents in ["[]", "{"]:
            with patch("builtins.open", mock_open(read_data=contents)):
                with self.assertRaisesRegex(ValueError, "volumes.json"):
                    ui_elements.load_sound_volumes()

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
        ui_elements.sound_volume_multipliers["Select Music.wav"] = 4
        ui_elements.global_sfx_volume = 0.5
        engine = Mock()
        sound = Mock()
        with patch.object(ui_elements.c, "USE_SOLOUD", True), \
                patch.object(ui_elements, "soloud_engine", engine), \
                patch.dict(ui_elements.music_ui_sounds, select_music=sound):
            ui_elements.play_ui_sound("select_music")
            engine.set_volume.assert_called_once_with(engine.play.return_value, 2)
        with patch.object(ui_elements.c, "USE_SOLOUD", False), \
                patch.object(ui_elements, "_pygame_sound_at_pitch", return_value=sound) as prepare:
            ui_elements.play_ui_sound("select_music")
            prepare.assert_called_once_with("select_music", 2)
            sound.set_volume.assert_called_once_with(1)
            ui_elements.global_sfx_volume = 0.125
            ui_elements.play_ui_sound("select_music")
            prepare.assert_called_with("select_music", 1)
            sound.set_volume.assert_called_with(0.5)
            sound.play.reset_mock()
            ui_elements.global_sfx_volume = 0
            ui_elements.play_ui_sound("select_music")
            sound.play.assert_not_called()
            ui_elements.global_sfx_volume = 1
            ui_elements.sound_volume_multipliers["Select Music.wav"] = 0
            ui_elements.play_ui_sound("select_music")
            sound.play.assert_not_called()


if __name__ == "__main__":
    unittest.main()
