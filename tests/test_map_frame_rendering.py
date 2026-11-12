"""Check cached map bars and the retained province-menu image."""

import unittest
from types import SimpleNamespace
from unittest.mock import call, patch

import pygame

import data.constants as c
from ui import background_styles
from ui.bars import ui_bars
from ui.widgets import ui_elements


class DisplayModeTests(unittest.TestCase):
    def test_recreated_windows_disable_native_destination_alpha(self):
        for flags in (0, pygame.FULLSCREEN, pygame.NOFRAME):
            with self.subTest(flags=flags):
                native = pygame.Surface((40, 30), pygame.SRCALPHA)
                with patch.object(pygame.display, "set_mode", return_value=native) as create:
                    surface = ui_bars.set_display_mode((40, 30), flags)
                create.assert_called_once_with((40, 30), flags)
                self.assertIs(surface, native)
                self.assertIsNone(surface.get_alpha())

    def test_standalone_window_uses_the_same_display_setup(self):
        native = pygame.Surface((40, 30), pygame.SRCALPHA)
        with patch.object(pygame.display, "get_surface", return_value=None), \
                patch.object(pygame, "get_init", return_value=True), \
                patch.object(pygame.display, "set_mode", return_value=native), \
                patch.object(pygame.display, "set_caption") as caption:
            surface, owns_display = ui_bars.acquire_surface((40, 30), "Tool")
        self.assertIs(surface, native)
        self.assertTrue(owns_display)
        self.assertIsNone(surface.get_alpha())
        caption.assert_called_once_with("Tool")

    def test_fullscreen_and_windowed_transitions_reapply_display_setup(self):
        import main

        controller = main.Controller.__new__(main.Controller)
        controller.is_fullscreen = False
        controller.last_toggle_time = None
        native = pygame.Surface((40, 30), pygame.SRCALPHA)
        with patch.object(main, "pygame", pygame, create=True), \
                patch.object(main, "c", c, create=True), \
                patch.object(main, "ui_bars", ui_bars, create=True), \
                patch.object(pygame.display, "set_mode", return_value=native) as create, \
                patch.object(pygame.time, "get_ticks", side_effect=(1000, 1000, 2000, 2000)), \
                patch.object(pygame.event, "clear"):
            controller.toggle_fullscreen()
            self.assertTrue(controller.is_fullscreen)
            self.assertIsNone(controller.screen.get_alpha())
            # A new native window can enable alpha again on each mode change.
            native.set_alpha(255)
            controller.toggle_fullscreen()
        self.assertFalse(controller.is_fullscreen)
        self.assertIsNone(controller.screen.get_alpha())
        create.assert_has_calls([
            call((c.SCREEN_WIDTH, c.SCREEN_HEIGHT), pygame.FULLSCREEN),
            call((c.SCREEN_WIDTH, c.SCREEN_HEIGHT), 0),
        ])

    def test_fullscreen_failure_keeps_borderless_fallback_opaque(self):
        import main

        controller = main.Controller.__new__(main.Controller)
        controller.is_fullscreen = False
        controller.last_toggle_time = None
        native = pygame.Surface((40, 30), pygame.SRCALPHA)
        with patch.object(main, "pygame", pygame, create=True), \
                patch.object(main, "c", c, create=True), \
                patch.object(main, "ui_bars", ui_bars, create=True), \
                patch.object(pygame.display, "set_mode",
                             side_effect=(pygame.error("Fullscreen unavailable"), native)) as create, \
                patch.object(pygame.display, "Info",
                             return_value=SimpleNamespace(current_w=1280, current_h=720)), \
                patch.object(pygame.event, "clear"):
            controller.toggle_fullscreen()
        self.assertIs(controller.screen, native)
        self.assertIsNone(native.get_alpha())
        create.assert_has_calls([
            call((c.SCREEN_WIDTH, c.SCREEN_HEIGHT), pygame.FULLSCREEN),
            call((1280, 720), pygame.NOFRAME),
        ])


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
            load.assert_called_once_with(ui_bars.PROVINCE_BG_FILE, directory=c.BACKGROUNDS_DIR)
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
