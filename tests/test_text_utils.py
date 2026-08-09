"""Unit tests for ui/text_utils.py.

Uses a stand-in font whose width is a fixed multiple of the character count, so
the expected wrap points can be reasoned about exactly and the tests need no
display, no font file, and no pygame init.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ui import text_utils


class FixedWidthFont:
    """Minimal stand-in for a pygame Font: every glyph is `char_w` wide."""

    def __init__(self, char_w=10):
        self.char_w = char_w

    def size(self, text):
        return (len(text) * self.char_w, 20)


def _legacy_fit_text(text, font, max_width):
    """The character-at-a-time implementation fit_text replaced. Kept here so
    the binary search can be proven to produce identical output."""
    if font.size(text)[0] <= max_width:
        return text
    while text and font.size(text + "...")[0] > max_width:
        text = text[:-1]
    return text + "..."


def _legacy_fit_path(text, font, max_width):
    if font.size(text)[0] <= max_width:
        return text
    while text and font.size("..." + text)[0] > max_width:
        text = text[1:]
    return "..." + text


class WrapTextTests(unittest.TestCase):
    def setUp(self):
        self.font = FixedWidthFont(10)

    def test_wraps_on_word_boundaries(self):
        # 10px/char, 100px box -> 10 chars per line.
        self.assertEqual(
            text_utils.wrap_text("alpha beta gamma", self.font, 100),
            ["alpha beta", "gamma"],
        )

    def test_boundary_is_inclusive(self):
        """A line exactly as wide as the box fits -- the old implementations
        disagreed here, some using `<` and breaking one word early."""
        self.assertEqual(text_utils.wrap_text("abcde fghi", self.font, 100), ["abcde fghi"])

    def test_preserves_blank_lines(self):
        self.assertEqual(text_utils.wrap_text("a\n\nb", self.font, 100), ["a", "", "b"])

    def test_can_collapse_blank_lines(self):
        self.assertEqual(
            text_utils.wrap_text("a\n\nb", self.font, 100, keep_blank_lines=False),
            ["a", "b"],
        )

    def test_hard_breaks_oversized_word(self):
        self.assertEqual(
            text_utils.wrap_text("aaaaaaaaaaaaa", self.font, 50),
            ["aaaaa", "aaaaa", "aaa"],
        )

    def test_oversized_word_can_overflow_instead(self):
        self.assertEqual(
            text_utils.wrap_text("aaaaaaaaaaaaa", self.font, 50, break_long_words=False),
            ["aaaaaaaaaaaaa"],
        )

    def test_oversized_word_after_normal_word(self):
        self.assertEqual(
            text_utils.wrap_text("hi aaaaaaa", self.font, 50),
            ["hi", "aaaaa", "aa"],
        )

    def test_empty_string(self):
        self.assertEqual(text_utils.wrap_text("", self.font, 100), [""])

    def test_normalizes_crlf(self):
        self.assertEqual(text_utils.wrap_text("a\r\nb\rc", self.font, 100), ["a", "b", "c"])

    def test_max_lines_cuts_silently_by_default(self):
        lines = text_utils.wrap_text("a b c d e f g h", self.font, 30, max_lines=2)
        self.assertEqual(len(lines), 2)
        self.assertFalse(lines[-1].endswith("..."))

    def test_max_lines_with_ellipsis_marks_the_cut(self):
        lines = text_utils.wrap_text("a b c d e f g h", self.font, 50, max_lines=2,
                                     ellipsis="...")
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[-1].endswith("..."))
        self.assertLessEqual(self.font.size(lines[-1])[0], 50)

    def test_max_lines_leaves_short_text_alone(self):
        self.assertEqual(
            text_utils.wrap_text("a b", self.font, 100, max_lines=4, ellipsis="..."),
            ["a b"],
        )


class TruncateCharsTests(unittest.TestCase):
    def test_leaves_short_text_alone(self):
        self.assertEqual(text_utils.truncate_chars("abc", 10), "abc")

    def test_exact_length_is_not_truncated(self):
        self.assertEqual(text_utils.truncate_chars("abcde", 5), "abcde")

    def test_truncates_to_the_budget(self):
        self.assertEqual(text_utils.truncate_chars("abcdefghij", 6), "abc...")

    def test_honours_a_shorter_ellipsis(self):
        self.assertEqual(text_utils.truncate_chars("abcdefghij", 6, ellipsis=".."), "abcd..")

    def test_coerces_non_strings(self):
        self.assertEqual(text_utils.truncate_chars(1234567, 5), "12...")


class FitTextTests(unittest.TestCase):
    def setUp(self):
        self.font = FixedWidthFont(10)

    def test_leaves_fitting_text_alone(self):
        self.assertEqual(text_utils.fit_text("abc", self.font, 100), "abc")

    def test_appends_ellipsis(self):
        self.assertEqual(text_utils.fit_text("abcdefghij", self.font, 60), "abc...")

    def test_degenerate_width_yields_bare_ellipsis(self):
        self.assertEqual(text_utils.fit_text("abcdefghij", self.font, 5), "...")

    def test_fit_path_keeps_the_tail(self):
        self.assertEqual(text_utils.fit_path("abcdefghij", self.font, 60), "...hij")

    def test_matches_the_legacy_linear_implementations(self):
        """The binary search must be a drop-in for the character-at-a-time walk
        it replaced, across every width a caller could plausibly pass."""
        samples = ["", "a", "abc", "a much longer file name.png",
                   "scenarios/custom/deeply/nested/path/to/a/file.json",
                   "x" * 80]
        for text in samples:
            for width in range(0, 220, 7):
                with self.subTest(text=text, width=width):
                    self.assertEqual(
                        text_utils.fit_text(text, self.font, width),
                        _legacy_fit_text(text, self.font, width),
                    )
                    self.assertEqual(
                        text_utils.fit_path(text, self.font, width),
                        _legacy_fit_path(text, self.font, width),
                    )


if __name__ == "__main__":
    unittest.main()
