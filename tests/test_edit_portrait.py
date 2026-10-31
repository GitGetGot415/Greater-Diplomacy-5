import unittest
from unittest import mock

import pygame

import data.constants as c
from tests import app_harness
from ui.widgets.ui_elements import Slider


class EditPortraitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.controller, _ = app_harness.boot()

    def setUp(self):
        self.menu = self.controller.states["MENU"]
        self.screen = self.controller.states["EDIT_PORTRAIT"]
        self.screen.refresh_ui()
        names = ("hildehrand_gradient", "hildehrand_gradient_strength", "hildehrand_gradient_stepped",
                 "hildehrand_gradient_bands", "hildehrand_gradient_dithering")
        saved = [getattr(self.menu, name) for name in names]
        self.addCleanup(lambda: ([setattr(self.menu, n, v) for n, v in zip(names, saved)],
                                 self.menu._refresh_hildehrand_image()))
        patcher = mock.patch("screens.menus.menu.queries.save_hildehrand_portrait")
        self.save = patcher.start()
        self.addCleanup(patcher.stop)

    def test_menu_has_a_single_button_that_opens_the_editor(self):
        self.menu.edit_portrait_btn.callback()
        self.assertEqual(self.menu.next_state, "EDIT_PORTRAIT")
        self.menu.done, self.menu.next_state = False, None

    def test_menu_and_portrait_forward_independent_dithering_options(self):
        from screens.menus import menu as menu_module
        from ui.widgets import ui_elements

        self.menu.hildehrand_gradient = True
        self.menu.hildehrand_gradient_stepped = True
        self.addCleanup(menu_module._menu_background.cache_clear)
        for sky, portrait in ((True, False), (False, True)):
            with self.subTest(sky=sky, portrait=portrait), \
                    mock.patch.object(menu_module, "MENU_SKY_DITHERING", sky), \
                    mock.patch.object(menu_module, "MENU_WATER_DITHERING", not sky), \
                    mock.patch.object(menu_module, "MENU_WATER_STEPPED", True), \
                    mock.patch.object(menu_module, "MENU_WATER_BANDS", 4), \
                    mock.patch.object(self.menu, "hildehrand_gradient_dithering", portrait), \
                    mock.patch.object(ui_elements, "draw_color_gradient") as draw_sky, \
                    mock.patch.object(ui_elements, "apply_button_gradient",
                                      wraps=ui_elements.apply_button_gradient) as shade_portrait:
                menu_module._menu_background.cache_clear()
                self.menu.draw_background(pygame.Surface((1280, 720)))
                self.menu._refresh_hildehrand_image()
                self.assertEqual(draw_sky.call_count, 2)
                sky_call, water_call = draw_sky.call_args_list
                self.assertEqual(sky_call.kwargs["dithering"], sky)
                self.assertEqual(water_call.kwargs,
                                 {"stepped": True, "bands": 4, "dithering": not sky})
                self.assertEqual(shade_portrait.call_args.kwargs["dithering"], portrait)
                self.menu.draw_background(pygame.Surface((1280, 720)))
                self.assertEqual(draw_sky.call_count, 2)

    def test_dithering_button_toggles_preview_and_saves(self):
        self.menu.hildehrand_gradient = True
        self.menu.hildehrand_gradient_stepped = True
        self.menu.hildehrand_gradient_dithering = True
        self.screen.refresh_ui()
        button = next(e for e in self.screen.elements
                      if getattr(e, "text", "").startswith("Dithering"))
        with mock.patch.object(self.menu, "_refresh_hildehrand_image") as refresh:
            button.callback()
        refresh.assert_called_once_with()
        self.assertFalse(self.menu.hildehrand_gradient_dithering)
        self.assertFalse(self.save.call_args.kwargs["gradient_dithering"])

    def test_dithering_disabled_without_stepped_gradient(self):
        for enabled, stepped in ((False, False), (False, True), (True, False)):
            self.menu.hildehrand_gradient = enabled
            self.menu.hildehrand_gradient_stepped = stepped
            self.menu.hildehrand_gradient_dithering = True
            self.screen.refresh_ui()
            button = next(e for e in self.screen.elements
                          if getattr(e, "text", "").startswith("Dithering"))
            self.assertTrue(button.disabled)
            button.callback()
            self.assertTrue(self.menu.hildehrand_gradient_dithering)
        self.save.assert_not_called()

    def test_dithering_settings_round_trip_and_old_default(self):
        from data.queries import content

        with mock.patch.object(content, "_load_cached_json", return_value={}):
            self.assertTrue(content.get_hildehrand_dithering())
        for dithering in (False, True):
            with mock.patch.object(content, "save_cached_json") as write:
                content.save_hildehrand_portrait("portrait.png", True, 1.0, True, 4,
                                                gradient_dithering=dithering)
            saved = write.call_args.args[1]
            with mock.patch.object(content, "_load_cached_json", return_value=saved):
                self.assertEqual(content.get_hildehrand_dithering(), dithering)

    def test_back_returns_to_the_menu(self):
        self.screen.exit_screen()
        self.assertEqual(self.screen.next_state, "MENU")
        self.screen.done, self.screen.next_state = False, None

    def test_toggle_persists_and_changes_the_menu_portrait(self):
        self.menu.hildehrand_gradient = False
        self.menu._refresh_hildehrand_image()
        plain = self.menu.hildehrand_image
        self.screen.toggle_gradient()
        self.assertTrue(self.menu.hildehrand_gradient)
        self.assertIsNot(self.menu.hildehrand_image, plain)
        self.save.assert_called_with(self.menu.hildehrand_choice, True,
                                     self.menu.hildehrand_gradient_strength,
                                     self.menu.hildehrand_gradient_stepped,
                                     self.menu.hildehrand_gradient_bands,
                                     gradient_dithering=self.menu.hildehrand_gradient_dithering)

    def test_stepped_button_is_disabled_and_ignored_while_the_gradient_is_off(self):
        self.menu.hildehrand_gradient = False
        self.menu.hildehrand_gradient_stepped = True
        self.screen.refresh_ui()
        button = next(e for e in self.screen.elements if getattr(e, "text", "").startswith("Stepped"))
        self.assertTrue(button.disabled)
        self.screen.toggle_stepped()
        self.assertTrue(self.menu.hildehrand_gradient_stepped)
        self.save.assert_not_called()
        self.menu.hildehrand_gradient = True
        self.screen.refresh_ui()
        button = next(e for e in self.screen.elements if getattr(e, "text", "").startswith("Stepped"))
        self.assertFalse(button.disabled)

    def test_each_slider_reads_off_while_its_option_is_off(self):
        cases = ((True, True, False, False), (True, False, False, True), (False, True, True, True),
                 (False, False, True, True))
        for gradient, stepped, strength_off, bands_off in cases:
            with self.subTest(gradient=gradient, stepped=stepped):
                self.menu.hildehrand_gradient = gradient
                self.menu.hildehrand_gradient_stepped = stepped
                self.screen.refresh_ui()
                self.assertEqual(self.screen.strength_slider.disabled, strength_off)
                self.assertEqual(self.screen.bands_slider.disabled, bands_off)
                for slider, off in ((self.screen.strength_slider, strength_off),
                                    (self.screen.bands_slider, bands_off)):
                    self.assertEqual(slider.get_display_string().endswith(": OFF"), off)

    def test_disabled_slider_ignores_input(self):
        self.menu.hildehrand_gradient = False
        self.screen.refresh_ui()
        slider = self.screen.strength_slider
        before = self.menu.hildehrand_gradient_strength
        slider.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1,
                                               pos=slider.handle_rect.center))
        self.assertFalse(slider.dragging)
        self.assertEqual(self.menu.hildehrand_gradient_strength, before)

    def test_style_toggle_persists_and_changes_the_menu_portrait(self):
        self.menu.hildehrand_gradient = True
        self.menu.hildehrand_gradient_stepped = False
        self.menu._refresh_hildehrand_image()
        smooth = pygame.image.tobytes(self.menu.hildehrand_image, "RGBA")
        self.screen.toggle_stepped()
        self.assertTrue(self.menu.hildehrand_gradient_stepped)
        self.assertNotEqual(pygame.image.tobytes(self.menu.hildehrand_image, "RGBA"), smooth)
        self.save.assert_called_with(self.menu.hildehrand_choice, True,
                                     self.menu.hildehrand_gradient_strength, True,
                                     self.menu.hildehrand_gradient_bands,
                                     gradient_dithering=self.menu.hildehrand_gradient_dithering)

    def test_stepped_shading_has_button_bands_and_dithered_edges(self):
        from ui.widgets import ui_elements
        image = pygame.Surface((40, 300), pygame.SRCALPHA)
        image.fill((120, 120, 120, 255))

        def row_shades(stepped):
            shaded = ui_elements.apply_button_gradient(image, 1.0, stepped)
            rows = [{tuple(shaded.get_at((x, y))) for x in range(40)} for y in range(300)]
            bands = []
            for row in rows:
                if not bands or row != bands[-1]:
                    bands.append(row)
            return rows, bands

        stepped_rows, stepped_bands = row_shades(True)
        smooth_rows, smooth_bands = row_shades(False)
        # Dithering mixes two shades on the rows at a band edge; smooth rows are uniform.
        self.assertTrue(any(len(row) > 1 for row in stepped_rows))
        self.assertTrue(all(len(row) == 1 for row in smooth_rows))
        # Stepped adds a band for every button shade height, as a button does; smooth has more.
        self.assertGreater(len(stepped_bands), 5)
        self.assertGreater(len(smooth_bands), len(stepped_bands))

    def test_slider_updates_live_and_saves_once_when_released(self):
        self.menu.hildehrand_gradient = True
        self.screen.refresh_ui()
        slider = self.screen.strength_slider
        slider.callback(c.HILDEHRAND_GRADIENT_MAX_STRENGTH)
        slider.callback(c.HILDEHRAND_GRADIENT_MAX_STRENGTH / 2)
        self.assertEqual(self.menu.hildehrand_gradient_strength, c.HILDEHRAND_GRADIENT_MAX_STRENGTH / 2)
        self.save.assert_not_called()
        self.screen.additional_events(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=(0, 0)))
        self.screen.additional_events(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=(0, 0)))
        self.save.assert_called_once_with(self.menu.hildehrand_choice, True,
                                          c.HILDEHRAND_GRADIENT_MAX_STRENGTH / 2,
                                          self.menu.hildehrand_gradient_stepped,
                                          self.menu.hildehrand_gradient_bands,
                                     gradient_dithering=self.menu.hildehrand_gradient_dithering)

    def test_band_slider_sets_a_whole_number_within_limits_and_saves_on_release(self):
        self.menu.hildehrand_gradient = True
        self.screen.refresh_ui()
        slider = self.screen.bands_slider
        slider.callback(c.HILDEHRAND_GRADIENT_MIN_BANDS + 4.4)
        self.assertEqual(self.menu.hildehrand_gradient_bands, c.HILDEHRAND_GRADIENT_MIN_BANDS + 4)
        slider.callback(0)
        self.assertEqual(self.menu.hildehrand_gradient_bands, c.HILDEHRAND_GRADIENT_MIN_BANDS)
        self.save.assert_not_called()
        self.screen.additional_events(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=(0, 0)))
        self.save.assert_called_once()

    def test_more_bands_make_more_distinct_bands_in_the_portrait(self):
        from ui.widgets import ui_elements
        image = pygame.Surface((40, 300), pygame.SRCALPHA)
        image.fill((120, 120, 120, 255))

        def band_count(bands):
            shaded = ui_elements.apply_button_gradient(image, 1.0, True, bands)
            return len({tuple(shaded.get_at((0, y))) for y in range(300)})
        self.assertLess(band_count(4), band_count(12))

    def test_strength_zero_leaves_the_portrait_unshaded(self):
        self.menu.hildehrand_gradient = True
        self.menu.set_hildehrand_gradient_strength(0.0)
        plain = self.menu._hildehrand_plain_image
        self.assertEqual(pygame.image.tobytes(self.menu.hildehrand_image, "RGBA"),
                         pygame.image.tobytes(plain, "RGBA"))

    def test_gradient_keeps_transparent_pixels_transparent(self):
        image = pygame.Surface((8, 40), pygame.SRCALPHA)
        image.fill((100, 100, 100, 255), (0, 0, 4, 40))
        from ui.widgets import ui_elements
        shaded = ui_elements.apply_button_gradient(image, 1.0)
        self.assertEqual(shaded.get_at((6, 20)).a, 0)
        self.assertEqual(shaded.get_at((1, 20)).a, 255)

    def test_saved_settings_load_with_safe_defaults(self):
        from data import queries
        with mock.patch.dict(queries._JSON_CACHE["hildehrand_choice"], {"data": {"variant": "x"}}):
            self.assertEqual(queries.get_hildehrand_gradient(),
                             (c.HILDEHRAND_GRADIENT_DEFAULT_ENABLED, c.HILDEHRAND_GRADIENT_DEFAULT_STRENGTH,
                              c.HILDEHRAND_GRADIENT_DEFAULT_STEPPED,
                              c.HILDEHRAND_GRADIENT_DEFAULT_BANDS))
        with mock.patch.dict(queries._JSON_CACHE["hildehrand_choice"],
                             {"data": {"gradient": True, "gradient_strength": 99,
                                       "gradient_bands": 999}}):
            self.assertEqual(queries.get_hildehrand_gradient(),
                             (True, c.HILDEHRAND_GRADIENT_MAX_STRENGTH,
                              c.HILDEHRAND_GRADIENT_DEFAULT_STEPPED,
                              c.HILDEHRAND_GRADIENT_MAX_BANDS))

    def test_gradient_enabled_default_and_saved_choice(self):
        from data import queries
        for default in (False, True):
            with self.subTest(default=default), \
                    mock.patch.object(c, "HILDEHRAND_GRADIENT_DEFAULT_ENABLED", default):
                for saved, expected in (({}, default), ({"gradient": False}, False),
                                        ({"gradient": True}, True)):
                    with mock.patch.dict(queries._JSON_CACHE["hildehrand_choice"], {"data": saved}):
                        self.assertEqual(queries.get_hildehrand_gradient()[0], expected)


if __name__ == "__main__":
    unittest.main()
