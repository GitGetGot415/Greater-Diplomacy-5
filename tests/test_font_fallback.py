import unittest
from unittest import mock

import pygame

import data.constants as c
from ui.rendering.font_manager import FallbackFont, FontManager

MISSING_WORD = "\u6f22\u5b57"  # Han characters, which neither main font has.


class FontFallbackTests(unittest.TestCase):
    def setUp(self):
        pygame.font.init()
        self.size = 24

    def make_font(self, primary_path):
        primary = pygame.font.Font(primary_path, self.size)
        return FallbackFont(primary, c.FONT_PATH_FALLBACK, self.size), primary

    def test_main_fonts_use_the_fallback_for_a_missing_word(self):
        fallback = pygame.font.Font(c.FONT_PATH_FALLBACK, self.size)
        for path in (c.FONT_PATH_DEFAULT, c.FONT_PATH_MAP):
            with self.subTest(path=path):
                font, _primary = self.make_font(path)
                self.assertEqual(font.size(MISSING_WORD), fallback.size(MISSING_WORD))
                self.assertEqual(font.render(MISSING_WORD, True, (255, 255, 255)).get_width(),
                                 fallback.size(MISSING_WORD)[0])

    def test_text_the_font_can_draw_is_unchanged(self):
        font, primary = self.make_font(c.FONT_PATH_DEFAULT)
        self.assertEqual(font.size("Hello world"), primary.size("Hello world"))

    def test_only_the_word_with_a_missing_glyph_uses_the_fallback(self):
        font, primary = self.make_font(c.FONT_PATH_DEFAULT)
        fallback = pygame.font.Font(c.FONT_PATH_FALLBACK, self.size)
        text = f"Hello {MISSING_WORD} world"
        expected_width = (primary.size("Hello ")[0] + fallback.size(MISSING_WORD)[0]
                          + primary.size(" world")[0])
        self.assertEqual(font.size(text)[0], expected_width)
        self.assertEqual(font.render(text, True, (255, 255, 255)).get_width(), expected_width)

    def test_other_font_methods_pass_through(self):
        font, primary = self.make_font(c.FONT_PATH_DEFAULT)
        self.assertEqual(font.get_height(), primary.get_height())

    def test_missing_fallback_file_keeps_the_primary_font(self):
        font, primary = self.make_font(c.FONT_PATH_DEFAULT)
        font._fallback_path = "assets/fonts/does_not_exist.otf"
        self.assertEqual(font.size(MISSING_WORD), primary.size(MISSING_WORD))

    def test_font_manager_wraps_file_fonts_and_caches_them(self):
        manager = FontManager()
        manager.init_fonts(c.FONT_PATH_DEFAULT)
        self.assertIsInstance(manager.get("normal"), FallbackFont)
        self.assertIsInstance(manager.get_size(20), FallbackFont)
        self.assertIs(manager.get("normal"), manager.get("normal"))

    def test_font_manager_without_a_path_uses_the_system_font(self):
        manager = FontManager()
        manager.init_fonts(None)
        with mock.patch.object(pygame.font, "SysFont", return_value="system") as sysfont:
            self.assertEqual(manager.get_size(20), "system")
        sysfont.assert_called_once()


if __name__ == "__main__":
    unittest.main()
