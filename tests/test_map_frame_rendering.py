"""Check cached map bars and the retained province-menu image."""

import unittest
from types import SimpleNamespace
from unittest.mock import call, patch

import pygame

import data.constants as c
from ui import background_styles
from ui.bars import ui_bars
from ui.widgets import ui_elements


class MapFrameRenderingTests(unittest.TestCase):
    def setUp(self):
        ui_elements._button_background.cache_clear()
        self.addCleanup(ui_elements._button_background.cache_clear)
        cache = patch.object(ui_bars, "_province_menu_background_cache", {})
        cache.start()
        self.addCleanup(cache.stop)
        self.surface = pygame.Surface((800, 600))
        self.game = SimpleNamespace(
            top_bar_rect=pygame.Rect(0, 0, 800, 40),
            bot_bar_rect=pygame.Rect(0, 560, 800, 40),
            raised_rect=pygame.Rect(0, 0, 120, 600),
            ui_background_rect=pygame.Rect(0, 520, 200, 80),
            unit_view_bar_rect=pygame.Rect(120, 400, 40, 120),
            unit_view_buttons={"ALL": SimpleNamespace(visible=True)},
            secondary_mode="UNITS", selection_mode=False, hide_raised_rect=False,
        )

    def test_province_menu_keeps_its_image_and_caches_resizing(self):
        template = pygame.Surface((80, 60), pygame.SRCALPHA)
        with patch.object(ui_bars, "get_ui_image", return_value=template) as load, \
                patch.object(pygame.transform, "scale", wraps=pygame.transform.scale) as scale:
            frame = ui_bars.get_province_menu_background((800, 600))
            self.assertIs(ui_bars.get_province_menu_background((800, 600)), frame)
            load.assert_called_once_with(c.PROVINCE_BG_FILE, directory=c.BACKGROUNDS_DIR)
            scale.assert_called_once_with(template, (800, 600))

    def test_map_bars_use_cached_shading_without_loading_images(self):
        with patch.object(ui_bars, "get_ui_image", side_effect=AssertionError("Unexpected image load")):
            ui_bars.draw_ui_bars(self.game, self.surface)
            with patch.object(ui_elements.queries, "lerp_color") as interpolate:
                ui_bars.draw_ui_bars(self.game, self.surface)
                self.game.hide_raised_rect = True
                ui_bars.draw_ui_bars(self.game, self.surface)
            interpolate.assert_not_called()

    def test_each_bar_passes_its_own_style_to_the_shared_renderer(self):
        rects = {
            "top": self.game.top_bar_rect,
            "bottom": self.game.bot_bar_rect,
            "left": self.game.raised_rect,
            "unit_filter": self.game.unit_view_bar_rect,
            "bottom_left": self.game.ui_background_rect,
        }
        styles = {name: {"color": (40 + index, 60 + index, 80 + index),
                         "gradient_strength": index / 2}
                  for index, name in enumerate(rects)}
        with patch.dict(background_styles.MAP_BAR_STYLES, styles, clear=True), \
                patch.object(ui_elements, "draw_pixel_panel", wraps=ui_elements.draw_pixel_panel) as draw:
            ui_bars.draw_ui_bars(self.game, self.surface)
        draw.assert_has_calls([
            call(self.surface, rect, styles[name]["color"],
                 gradient_strength=styles[name]["gradient_strength"])
            for name, rect in rects.items()], any_order=True)
        self.assertEqual(draw.call_count, len(styles))

    def test_strength_changes_refresh_the_cache_and_moving_a_panel_reuses_it(self):
        rect = pygame.Rect(0, 0, 120, 80)
        for strength in (0.0, 0.5, 1.0, 2.0):
            ui_elements.draw_pixel_panel(self.surface, rect, (40, 60, 80), gradient_strength=strength)
        self.assertEqual(ui_elements._button_background.cache_info().misses, 4)
        rect.move_ip(10, 10)
        with patch.object(ui_elements.queries, "lerp_color") as interpolate:
            ui_elements.draw_pixel_panel(self.surface, rect, (40, 60, 80), gradient_strength=0.5)
        interpolate.assert_not_called()

    def test_filter_animation_reuses_background_and_restores_clip(self):
        self.game.unit_view_bar_offset = 0
        self.surface.set_clip(pygame.Rect(10, 10, 700, 500))
        clip = self.surface.get_clip()
        ui_bars.draw_ui_bars(self.game, self.surface)
        with patch.object(ui_elements.queries, "lerp_color") as interpolate:
            for offset in (20, 60, 100, 0):
                self.game.unit_view_bar_offset = offset
                ui_bars.draw_ui_bars(self.game, self.surface)
        interpolate.assert_not_called()
        self.assertEqual(self.surface.get_clip(), clip)

    def test_negative_gradient_strength_reports_how_to_correct_it(self):
        with self.assertRaisesRegex(ValueError, "zero or greater"):
            ui_elements.draw_pixel_panel(self.surface, self.game.top_bar_rect, (40, 60, 80),
                                         gradient_strength=-1)


if __name__ == "__main__":
    unittest.main()
