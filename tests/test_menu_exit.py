"""Regression tests for the main menu's exit confirmation flow."""

import unittest
from unittest import mock

import pygame
import data.constants as c

from tests import app_harness
from map_logic.rendering.font_manager import fonts
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

    def test_exit_button_slides_in_from_the_right(self):
        current_ticks = self.menu.intro_start_ticks
        button_rects = [(button, button.rect.copy()) for button in self.menu.elements]
        bottom_rects = [
            (item["main_rect"], item["main_rect"].copy(), item["link_rect"].copy())
            for item in self.menu.bottom_texts
        ]
        draw_positions = {
            name: getattr(self.menu, name)
            for name in (
                "_sign_draw_pos",
                "_right_ground_draw_pos",
                "_left_ground_draw_pos",
                "_hildehrand_draw_pos",
                "_version_draw_pos",
            )
        }

        try:
            with mock.patch("screens.menu_screens.menu.pygame.time.get_ticks", return_value=current_ticks):
                self.menu.update()
            self.assertEqual(
                self.menu.exit_btn.rect.left,
                c.SCREEN_WIDTH + self.menu.EXIT_INTRO_START_MARGIN,
            )
        finally:
            for button, rect in button_rects:
                button.rect.update(rect)
            for rect, main_copy, link_copy in bottom_rects:
                rect.update(main_copy)
                link_rect = next(
                    item["link_rect"]
                    for item in self.menu.bottom_texts
                    if item["main_rect"] is rect
                )
                link_rect.update(link_copy)
            for name, position in draw_positions.items():
                setattr(self.menu, name, position)

    def test_ground_images_start_fully_off_screen(self):
        self.assertEqual(
            self.menu._right_ground_draw_pos[0],
            c.SCREEN_WIDTH + self.menu.GROUND_INTRO_START_MARGIN,
        )
        self.assertEqual(
            self.menu._left_ground_draw_pos[0],
            -self.menu.left_ground_rect.width - self.menu.GROUND_INTRO_START_MARGIN,
        )

    def test_sign_is_anchored_by_its_bottom_right_corner(self):
        self.assertEqual(
            self.menu.sign_rect.bottomright,
            self.menu._sign_anchor_bottomright,
        )

    def test_sign_starts_further_off_screen_than_its_width(self):
        self.assertEqual(
            self.menu._sign_draw_pos[0],
            c.SCREEN_WIDTH + self.menu.sign_rect.width + self.menu.SIGN_INTRO_START_MARGIN,
        )

    def test_exit_button_is_omitted_from_web_build(self):
        from screens.menu_screens import menu as menu_module

        with mock.patch.object(menu_module, "IS_WEB", True):
            web_menu = menu_module.Menu()

        self.assertIsNone(web_menu.exit_btn)
        self.assertNotIn("Exit", [element.text for element in web_menu.elements])

    def test_credits_button_is_above_the_bottom_links(self):
        lowest_link_top = min(item["main_rect"].top for item in self.menu.bottom_texts)
        table_buttons = [
            getattr(self.menu, button_data["attribute"])
            for button_data in c.MENU_BUTTON_TABLE
        ]

        self.assertEqual(table_buttons[0].rect.topleft, c.MENU_BUTTON_TABLE_TOP_LEFT)
        self.assertLess(max(button.rect.bottom for button in table_buttons), lowest_link_top)

    def test_main_buttons_follow_their_separate_configured_table(self):
        table_x, table_y = c.MENU_MAIN_BUTTON_TABLE_TOP_LEFT
        button_w, button_h = c.MENU_MAIN_BUTTON_TABLE_BUTTON_SIZE
        columns = c.MENU_MAIN_BUTTON_TABLE_COLUMNS

        for index, button_data in enumerate(c.MENU_MAIN_BUTTON_TABLE):
            row, column = divmod(index, columns)
            button = getattr(self.menu, button_data["attribute"])
            expected_x = table_x + column * (button_w + c.MENU_MAIN_BUTTON_TABLE_X_SPACING)
            expected_y = table_y + row * (button_h + c.MENU_MAIN_BUTTON_TABLE_Y_SPACING)

            self.assertEqual(button.rect.topleft, (expected_x, expected_y))
            self.assertEqual(button.rect.size, c.MENU_MAIN_BUTTON_TABLE_BUTTON_SIZE)
            self.assertEqual(button.text, button_data["text"])
            self.assertEqual(button.font.get_height(), fonts.get_size(button_data["text_size"]).get_height())

    def test_lower_left_buttons_follow_the_configured_table(self):
        table_x, table_y = c.MENU_BUTTON_TABLE_TOP_LEFT
        button_w, button_h = c.MENU_BUTTON_TABLE_BUTTON_SIZE
        columns = c.MENU_BUTTON_TABLE_COLUMNS

        for index, button_data in enumerate(c.MENU_BUTTON_TABLE):
            row, column = divmod(index, columns)
            button = getattr(self.menu, button_data["attribute"])
            expected_x = table_x + column * (button_w + c.MENU_BUTTON_TABLE_X_SPACING)
            expected_y = table_y + row * (button_h + c.MENU_BUTTON_TABLE_Y_SPACING)

            self.assertEqual(button.rect.topleft, (expected_x, expected_y))
            self.assertEqual(button.rect.size, c.MENU_BUTTON_TABLE_BUTTON_SIZE)
            self.assertEqual(button.text, button_data["text"])
            self.assertEqual(button.font.get_height(), fonts.get_size(button_data["text_size"]).get_height())

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
