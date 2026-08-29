"""Regression tests for the main menu's exit confirmation flow."""

import unittest
from unittest import mock

import pygame
import data.constants as c

from tests import app_harness
from ui import modal_stack


def click(pos, event_type=pygame.MOUSEBUTTONDOWN):
    return pygame.event.Event(event_type, pos=pos, button=1)


class MenuExitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.controller, cls.surface = app_harness.boot()

    def setUp(self):
        while not modal_stack.is_empty():
            modal_stack.pop()
        pygame.event.clear()
        self.menu = self.controller.states["MENU"]

    def open_exit_dialog(self):
        self.menu.exit_btn.handle_event(click(self.menu.exit_btn.rect.center))
        self.menu.exit_btn.handle_event(click(self.menu.exit_btn.rect.center, pygame.MOUSEBUTTONUP))
        modal = modal_stack.active()
        self.assertIsNotNone(modal)
        return modal

    def settle(self, modal):
        modal.update()
        self.assertTrue(modal_stack.is_empty())

    def test_exit_button_is_in_the_top_right_corner(self):
        self.assertEqual(self.menu.exit_btn.rect.top, 20)
        self.assertEqual(self.menu.exit_btn.rect.right, pygame.display.get_surface().get_width() - 20)
        self.assertEqual(self.menu.exit_btn.text, "Exit")

    def test_exit_button_is_omitted_from_web_build(self):
        from screens.menu_screens import menu as menu_module

        with mock.patch.object(menu_module, "IS_WEB", True):
            web_menu = menu_module.Menu()

        self.assertIsNone(web_menu.exit_btn)
        self.assertNotIn("Exit", [element.text for element in web_menu.elements])

    def test_credits_button_is_above_the_bottom_links(self):
        credits = self.menu.credits_btn
        lowest_link_top = min(item["main_rect"].top for item in self.menu.bottom_texts)

        self.assertEqual(credits.rect.left, c.MENU_BOTTOM_TEXT_START_X)
        self.assertLess(credits.rect.bottom, lowest_link_top)

    def test_other_centered_menu_buttons_keep_their_positions(self):
        expected_offsets = {
            "New Game": "- 150", "Load Game": "- 100", "Tournaments": "- 50",
            "Map Editor": "+ 0",
        }
        display_height = pygame.display.get_surface().get_height()
        menu_height = c.SIZES["menu"][1]
        centered_y = int((display_height - menu_height) / 2)

        for button in self.menu.elements:
            offset = expected_offsets.get(getattr(button, "text", ""))
            if offset is None:
                continue
            expected_y = centered_y + int(offset.replace(" ", ""))
            self.assertEqual(button.rect.y, expected_y, button.text)

    def test_assets_and_mods_share_credits_row_without_overlapping(self):
        credits = self.menu.credits_btn
        assets = self.menu.assets_btn
        mods = self.menu.mods_btn
        translate = self.menu.translate_btn
        settings = self.menu.settings_btn
        music = self.menu.music_btn

        self.assertEqual(assets.rect.y, credits.rect.y)
        self.assertEqual(mods.rect.y, credits.rect.y)
        self.assertEqual(translate.rect.y, credits.rect.y)
        self.assertEqual(settings.rect.y, credits.rect.y)
        self.assertEqual(music.rect.y, credits.rect.y)
        self.assertGreater(assets.rect.left, credits.rect.right)
        self.assertGreater(mods.rect.left, assets.rect.right)
        self.assertGreater(translate.rect.left, mods.rect.right)
        self.assertGreater(settings.rect.left, translate.rect.right)
        self.assertGreater(music.rect.left, settings.rect.right)
        self.assertFalse(credits.rect.colliderect(assets.rect))
        self.assertFalse(assets.rect.colliderect(mods.rect))
        self.assertFalse(mods.rect.colliderect(translate.rect))
        self.assertFalse(translate.rect.colliderect(settings.rect))
        self.assertFalse(settings.rect.colliderect(music.rect))

    def test_cancel_keeps_the_game_running(self):
        modal = self.open_exit_dialog()

        with mock.patch("screens.menu_screens.menu.pygame.event.post") as post:
            modal.handle_events([click(modal.no_rect.center)])
            self.settle(modal)

        post.assert_not_called()

    def test_confirm_posts_the_normal_quit_event(self):
        modal = self.open_exit_dialog()

        with mock.patch("screens.menu_screens.menu.pygame.event.post") as post:
            modal.handle_events([click(modal.yes_rect.center)])
            self.settle(modal)

        post.assert_called_once()
        self.assertEqual(post.call_args.args[0].type, pygame.QUIT)


if __name__ == "__main__":
    unittest.main()
