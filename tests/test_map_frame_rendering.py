"""Check cached map bars and the retained province-menu image."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import pygame

import data.constants as c
from ui.bars import ui_bars
from ui.widgets import ui_elements


class MapFrameRenderingTests(unittest.TestCase):
    def setUp(self):
        ui_elements._button_background.cache_clear()
        self.addCleanup(ui_elements._button_background.cache_clear)
        cache = patch.object(ui_bars, "_province_menu_background_cache", {})
        cache.start()
        self.addCleanup(cache.stop)

    def test_province_menu_keeps_its_image_and_caches_resizing(self):
        template = pygame.Surface((80, 60), pygame.SRCALPHA)
        with patch.object(ui_bars, "get_ui_image", return_value=template) as load, \
                patch.object(pygame.transform, "scale", wraps=pygame.transform.scale) as scale:
            frame = ui_bars.get_province_menu_background((800, 600))
            self.assertIs(ui_bars.get_province_menu_background((800, 600)), frame)
            load.assert_called_once_with(c.PROVINCE_BG_FILE, directory=c.BACKGROUNDS_DIR)
            scale.assert_called_once_with(template, (800, 600))

    def test_map_bars_use_cached_shading_without_loading_images(self):
        surface = pygame.Surface((800, 600))
        game = SimpleNamespace(
            top_bar_rect=pygame.Rect(0, 0, 800, 40),
            bot_bar_rect=pygame.Rect(0, 560, 800, 40),
            raised_rect=pygame.Rect(0, 0, 120, 600),
            ui_background_rect=pygame.Rect(0, 520, 200, 80),
            unit_view_bar_rect=pygame.Rect(120, 400, 40, 120),
            unit_view_buttons={"ALL": SimpleNamespace(visible=True)},
            secondary_mode="UNITS", selection_mode=False, hide_raised_rect=False,
        )
        with patch.object(ui_bars, "get_ui_image", side_effect=AssertionError("Unexpected image load")):
            ui_bars.draw_ui_bars(game, surface)
            with patch.object(ui_elements.queries, "lerp_color") as interpolate:
                ui_bars.draw_ui_bars(game, surface)
                game.hide_raised_rect = True
                ui_bars.draw_ui_bars(game, surface)
            interpolate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
