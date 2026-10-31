import unittest
from unittest.mock import Mock, patch

import pygame

from ui.widgets import ui_elements


class ButtonBackgroundTests(unittest.TestCase):
    def setUp(self):
        pygame.font.init()
        ui_elements._button_background.cache_clear()
        ui_elements._translucent_background.cache_clear()
        self.surface = pygame.Surface((400, 200))
        self.button = ui_elements.Button(10, 10, (120, 50), "blue", "", Mock())
        self.mouse = patch.object(pygame.mouse, "get_pos", return_value=(300, 150))
        self.mouse.start()
        self.addCleanup(self.mouse.stop)
        self.addCleanup(ui_elements._button_background.cache_clear)
        self.addCleanup(ui_elements._translucent_background.cache_clear)

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

    def test_translucent_panels_reuse_copies_without_changing_opaque_cache(self):
        rect = pygame.Rect(10, 10, 120, 50)
        color = (30, 50, 70)
        opaque = ui_elements._button_background(rect.size, color, False, 2)
        original_alpha = opaque.get_alpha()
        ui_elements.draw_pixel_panel(self.surface, rect, (*color, 180))
        rect.move_ip(30, 20)
        with patch.object(ui_elements.queries, "lerp_color") as interpolate:
            ui_elements.draw_pixel_panel(self.surface, rect, (*color, 180))
            ui_elements.draw_pixel_panel(self.surface, rect, (*color, 220))
        interpolate.assert_not_called()
        self.assertEqual(opaque.get_alpha(), original_alpha)
        self.assertEqual(ui_elements._translucent_background.cache_info().misses, 2)
        self.assertEqual(ui_elements._translucent_background.cache_info().hits, 1)

    def test_progress_changes_reuse_shading_and_preserve_clip_and_geometry(self):
        rect = pygame.Rect(10, 10, 200, 25)
        original = rect.copy()
        self.surface.set_clip(pygame.Rect(20, 15, 120, 60))
        clip = self.surface.get_clip()
        ui_elements.draw_progress_bar(self.surface, rect, 0.25)
        with patch.object(ui_elements.queries, "lerp_color") as interpolate:
            for progress in (-1, 0, 0.5, 1, 2):
                ui_elements.draw_progress_bar(self.surface, rect, progress)
        interpolate.assert_not_called()
        self.assertEqual(rect, original)
        self.assertEqual(self.surface.get_clip(), clip)

    def test_custom_button_gradient_changes_refresh_and_reuse_cached_backgrounds(self):
        rect = pygame.Rect(10, 10, 120, 50)
        for disabled in (False, True):
            for strength in (0.0, 0.5, 1.0, 2.0):
                ui_elements.draw_pixel_button(self.surface, rect, (40, 80, 120),
                                              disabled=disabled, pressed=False,
                                              gradient_strength=strength)
        self.assertEqual(ui_elements._button_background.cache_info().misses, 8)
        rect.move_ip(10, 10)
        with patch.object(ui_elements.queries, "lerp_color") as interpolate:
            ui_elements.draw_pixel_button(self.surface, rect, (40, 80, 120), pressed=False,
                                          gradient_strength=0.5)
        interpolate.assert_not_called()

    def test_text_input_styles_refresh_the_cache_and_drawing_preserves_clipping(self):
        rect = pygame.Rect(10, 10, 120, 40)
        self.surface.set_clip(pygame.Rect(15, 15, 80, 35))
        clip = self.surface.get_clip()
        font = pygame.font.Font(None, 18)
        styles = {"inactive": {"color": (70, 80, 90), "gradient_strength": 1.0},
                  "active": {"color": (80, 90, 100), "gradient_strength": 0.5}}
        with patch.dict(ui_elements.TEXT_INPUT_STYLES, styles, clear=True):
            ui_elements.draw_text_box(self.surface, rect, "name", font=font)
            styles["inactive"]["gradient_strength"] = 0.5
            ui_elements.draw_text_box(self.surface, rect, "name", font=font)
            styles["inactive"]["color"] = (90, 100, 110)
            ui_elements.draw_text_box(self.surface, rect, "name", font=font)
            ui_elements.draw_text_box(self.surface, rect, "name", active=True, font=font)
            self.assertEqual(ui_elements._button_background.cache_info().misses, 4)
            with patch.object(ui_elements.queries, "lerp_color") as interpolate:
                ui_elements.draw_text_box(self.surface, rect, "long name" * 8, active=True, font=font)
            interpolate.assert_not_called()
        self.assertEqual(self.surface.get_clip(), clip)


if __name__ == "__main__":
    unittest.main()
