"""Check slider input and cached rendering without testing pixel appearance."""

import unittest
from unittest.mock import Mock, patch

import pygame

from screens.menus.music_player import MusicScrubber
from ui import background_styles
from ui.widgets import ui_elements


class SliderInteractionTests(unittest.TestCase):
    def setUp(self):
        pygame.font.init()
        self.surface = pygame.Surface((500, 180))
        self.callback = Mock()
        self.slider = ui_elements.Slider(30, 50, 200, "Value", 0.25,
                                        self.callback, visual_max=2, allowed_max=1)
        ui_elements._button_background.cache_clear()
        self.addCleanup(ui_elements._button_background.cache_clear)
        mouse = patch.object(pygame.mouse, "get_pos", return_value=(490, 170))
        mouse.start()
        self.addCleanup(mouse.stop)

    def event(self, widget, kind, pos):
        widget.handle_event(pygame.event.Event(kind, button=1, pos=pos))

    def test_draw_during_drag_preserves_limits_and_callbacks(self):
        initial = self.slider.value
        self.slider.draw(self.surface)
        self.callback.assert_not_called()
        self.assertEqual(self.slider.value, initial)
        self.event(self.slider, pygame.MOUSEBUTTONDOWN, self.slider.handle_rect.center)
        with patch.object(pygame.mouse, "get_pressed", return_value=(True, False, False)), \
                patch.object(ui_elements, "play_ui_sound"):
            for mouse_x, expected in ((400, 1), (-20, 0)):
                self.event(self.slider, pygame.MOUSEMOTION, (mouse_x, 50))
                self.slider.draw(self.surface)
                self.assertEqual(self.slider.value, expected)
                self.callback.assert_called_with(expected)
        self.assertEqual(self.callback.call_count, 2)
        self.event(self.slider, pygame.MOUSEBUTTONUP, (400, 50))
        self.assertFalse(self.slider.dragging)

    def test_guard_hidden_control_and_missed_release(self):
        self.slider.click_guard = lambda: False
        self.slider.draw(self.surface)
        self.event(self.slider, pygame.MOUSEBUTTONDOWN, self.slider.handle_rect.center)
        self.assertFalse(self.slider.dragging)
        self.slider.click_guard = None
        self.slider.visible = False
        self.slider.draw(self.surface)
        self.event(self.slider, pygame.MOUSEBUTTONDOWN, self.slider.handle_rect.center)
        self.assertFalse(self.slider.dragging)
        self.slider.visible = True
        self.event(self.slider, pygame.MOUSEBUTTONDOWN, self.slider.handle_rect.center)
        self.assertTrue(self.slider.dragging)
        with patch.object(pygame.mouse, "get_pressed", return_value=(False, False, False)):
            self.event(self.slider, pygame.MOUSEMOTION, (150, 50))
        self.slider.draw(self.surface)
        self.assertFalse(self.slider.dragging)
        self.callback.assert_not_called()

    def test_moving_controls_and_music_progress_reuse_cached_shading(self):
        scrubber = MusicScrubber(30, 110, 200, 15, self.callback)
        self.slider.draw(self.surface)
        scrubber.draw(self.surface)
        with patch.object(ui_elements.queries, "lerp_color") as interpolate:
            self.slider.rect.move_ip(20, 0)
            self.slider.handle_rect.move_ip(20, 0)
            self.slider.allowed_max = 0.5
            self.slider.draw(self.surface)
            for progress in (0.25, 0.5, 1):
                scrubber.value = progress
                scrubber.draw(self.surface)
        interpolate.assert_not_called()
        self.callback.assert_not_called()

    def test_music_seeks_on_release_and_retains_drag_preview(self):
        scrubber = MusicScrubber(30, 110, 200, 15, self.callback)
        scrubber.update_progress(20, 100)
        scrubber.draw(self.surface)
        self.event(scrubber, pygame.MOUSEBUTTONDOWN, (130, 110))
        scrubber.update_progress(20, 100)
        scrubber.draw(self.surface)
        self.assertEqual(scrubber.value, 0.5)
        self.assertEqual(scrubber.current_time_str, scrubber._format_time(50))
        self.callback.assert_not_called()
        self.event(scrubber, pygame.MOUSEMOTION, (400, 110))
        scrubber.draw(self.surface)
        self.assertEqual(scrubber.value, 1)
        self.event(scrubber, pygame.MOUSEBUTTONUP, (400, 110))
        self.callback.assert_called_once_with(1)
        self.assertFalse(scrubber.is_dragging)

    def test_style_edits_refresh_cache_and_moving_controls_reuses_it(self):
        rect = self.slider.rect
        handle = self.slider.handle_rect
        styles = {
            name: {"color": (60 + index, 90 + index, 120 + index), "gradient_strength": 0.5}
            for index, name in enumerate(("track", "handle", "locked", "progress"))
        }
        clip = self.surface.get_clip()
        with patch.dict(background_styles.SLIDER_STYLES, styles, clear=True):
            ui_elements.draw_slider(self.surface, rect, handle,
                                    allowed_ratio=0.5, progress_ratio=0.25)
            misses = ui_elements._button_background.cache_info().misses
            self.assertEqual(misses, len(styles))
            for index, (name, style) in enumerate(styles.items()):
                with self.subTest(part=name):
                    for field, value in (("gradient_strength", 0.0),
                                         ("color", (80 + index, 100 + index, 140 + index))):
                        style[field] = value
                        ui_elements.draw_slider(self.surface, rect, handle,
                                                allowed_ratio=0.5, progress_ratio=0.25)
                        misses += 1
                        self.assertEqual(ui_elements._button_background.cache_info().misses, misses)
            rect.move_ip(10, 0)
            handle.move_ip(10, 0)
            with patch.object(ui_elements.queries, "lerp_color") as interpolate:
                ui_elements.draw_slider(self.surface, rect, handle,
                                        allowed_ratio=0.75, progress_ratio=0.5)
            interpolate.assert_not_called()
        self.assertEqual(self.surface.get_clip(), clip)
        self.callback.assert_not_called()


if __name__ == "__main__":
    unittest.main()
