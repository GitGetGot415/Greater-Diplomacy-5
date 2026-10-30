import unittest
from unittest.mock import Mock, patch

import pygame

from ui.widgets import ui_elements


class ButtonBackgroundTests(unittest.TestCase):
    def setUp(self):
        pygame.font.init()
        ui_elements._button_background.cache_clear()
        self.surface = pygame.Surface((400, 200))
        self.button = ui_elements.Button(10, 10, (120, 50), "blue", "", Mock())
        self.mouse = patch.object(pygame.mouse, "get_pos", return_value=(300, 150))
        self.mouse.start()
        self.addCleanup(self.mouse.stop)
        self.addCleanup(ui_elements._button_background.cache_clear)

    def test_background_is_shared_and_reused_after_moving(self):
        self.button.draw(self.surface)
        other = ui_elements.Button(150, 80, (120, 50), "blue", "", Mock())
        with patch.object(ui_elements.queries, "lerp_color") as interpolate:
            other.draw(self.surface)
            self.button.rect.move_ip(20, 30)
            self.button.draw(self.surface)
        interpolate.assert_not_called()
        self.assertEqual(ui_elements._button_background.cache_info().misses, 1)
        self.assertEqual(ui_elements._button_background.cache_info().hits, 2)

    def test_background_refreshes_for_state_palette_and_size_changes(self):
        self.button.draw(self.surface)
        self.button.set_colors([101, 121, 141], [111, 131, 151])
        self.button.draw(self.surface)
        with patch.object(pygame.mouse, "get_pos", return_value=self.button.rect.center):
            self.button.draw(self.surface)
            self.button.is_pressed = True
            self.button.draw(self.surface)
            self.button.disabled = True
            self.button.draw(self.surface)
        self.button.is_selected = True
        self.button.draw(self.surface)
        self.button.rect.size = (121, 251)
        self.button.draw(self.surface)
        self.assertEqual(ui_elements._button_background.cache_info().misses, 7)
        with patch.object(ui_elements.queries, "lerp_color") as interpolate:
            self.button.draw(self.surface)
        interpolate.assert_not_called()

    def test_cache_has_a_fixed_capacity(self):
        capacity = ui_elements._button_background.cache_info().maxsize
        for value in range(capacity + 1):
            ui_elements._button_background((10, 10), (value, 0, 0), False, 2)
        self.assertEqual(ui_elements._button_background.cache_info().currsize, capacity)

    def test_flat_and_hidden_buttons_skip_the_background_cache(self):
        self.button.shading = False
        self.button.draw(self.surface)
        self.button.shading = True
        self.button.visible = False
        self.button.draw(self.surface)
        self.assertEqual(ui_elements._button_background.cache_info().misses, 0)

    def test_small_tall_and_empty_buttons_draw_without_errors(self):
        for size in ((0, 50), (50, 0), (1, 1), (3, 7), (9, 9), (51, 31),
                     (120, 150), (121, 251), (390, 300)):
            with self.subTest(size=size):
                self.button.rect.size = size
                self.button.draw(self.surface)

    def test_drawing_preserves_click_and_disabled_behavior(self):
        down = pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1,
                                  pos=self.button.rect.center)
        up = pygame.event.Event(pygame.MOUSEBUTTONUP, button=1,
                                pos=self.button.rect.center)
        with patch.object(ui_elements, "play_ui_sound"):
            self.button.handle_event(down)
            with patch.object(pygame.mouse, "get_pos", return_value=self.button.rect.center):
                self.button.draw(self.surface)
            self.button.handle_event(up)
            self.button.callback.assert_called_once_with()
            self.button.callback.reset_mock()
            self.button.disabled = True
            self.button.handle_event(down)
            self.button.draw(self.surface)
            self.button.handle_event(up)
            self.button.callback.assert_not_called()


if __name__ == "__main__":
    unittest.main()
