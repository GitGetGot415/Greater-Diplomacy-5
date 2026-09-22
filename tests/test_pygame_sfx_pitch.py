import os
import unittest

os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import numpy as np
import pygame

import ui_elements


class PygameSfxPitchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if pygame.mixer.get_init() is None:
            pygame.mixer.init(frequency=44100, size=-16, channels=2)

    def setUp(self):
        self.old_click_sound = ui_elements.pygame_click_sound
        self.old_slider_sound = ui_elements.pygame_slider_sound
        self.old_pitch = ui_elements.global_sfx_pitch
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


if __name__ == "__main__":
    unittest.main()
