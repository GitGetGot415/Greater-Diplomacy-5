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
        saved = (self.menu.hildehrand_gradient, self.menu.hildehrand_gradient_strength)
        self.addCleanup(lambda: (setattr(self.menu, "hildehrand_gradient", saved[0]),
                                 setattr(self.menu, "hildehrand_gradient_strength", saved[1]),
                                 self.menu._refresh_hildehrand_image()))
        patcher = mock.patch("screens.menus.menu.queries.save_hildehrand_portrait")
        self.save = patcher.start()
        self.addCleanup(patcher.stop)

    def test_menu_has_a_single_button_that_opens_the_editor(self):
        self.menu.edit_portrait_btn.callback()
        self.assertEqual(self.menu.next_state, "EDIT_PORTRAIT")
        self.menu.done, self.menu.next_state = False, None

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
                                     self.menu.hildehrand_gradient_strength)

    def test_slider_updates_live_and_saves_once_when_released(self):
        self.menu.hildehrand_gradient = True
        self.screen.refresh_ui()
        slider = next(e for e in self.screen.elements if isinstance(e, Slider))
        slider.callback(c.HILDEHRAND_GRADIENT_MAX_STRENGTH)
        slider.callback(c.HILDEHRAND_GRADIENT_MAX_STRENGTH / 2)
        self.assertEqual(self.menu.hildehrand_gradient_strength, c.HILDEHRAND_GRADIENT_MAX_STRENGTH / 2)
        self.save.assert_not_called()
        self.screen.additional_events(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=(0, 0)))
        self.screen.additional_events(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=(0, 0)))
        self.save.assert_called_once_with(self.menu.hildehrand_choice, True,
                                          c.HILDEHRAND_GRADIENT_MAX_STRENGTH / 2)

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
                             (False, c.HILDEHRAND_GRADIENT_DEFAULT_STRENGTH))
        with mock.patch.dict(queries._JSON_CACHE["hildehrand_choice"],
                             {"data": {"gradient": True, "gradient_strength": 99}}):
            self.assertEqual(queries.get_hildehrand_gradient(),
                             (True, c.HILDEHRAND_GRADIENT_MAX_STRENGTH))


if __name__ == "__main__":
    unittest.main()
