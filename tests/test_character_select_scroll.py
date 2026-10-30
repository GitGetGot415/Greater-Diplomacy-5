import unittest
from unittest import mock

import data.constants as c
from tests import app_harness
from ui.dialogs.character_select_screen import CharacterSelectScreen


class CharacterSelectScrollTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app_harness.boot()

    def test_selected_portrait_is_centered_within_scroll_limits(self):
        images = [f"portrait_{i}.png" for i in range(80)]
        for index in (0, 35, 79, None):
            with self.subTest(index=index), \
                    mock.patch("ui.dialogs.character_select_screen.discover_character_images", return_value=images), \
                    mock.patch.object(CharacterSelectScreen, "_thumbnail", return_value=None):
                selected = images[index] if index is not None else "missing.png"
                screen = CharacterSelectScreen(None, selected, lambda path: None)
                tile_h = c.SIZES["character_portrait_tile"][1]
                view_h = screen.scroll_content_rect.height
                if index is None:
                    expected = 0
                else:
                    row = (index + 1) // screen.COLUMNS
                    desired = view_h // 2 - (row * (tile_h + screen.TILE_GAP) + tile_h // 2)
                    expected = max(screen.max_scroll, min(0, desired))
                self.assertEqual(screen.scroll_y, expected)
                screen.scroll_y = screen.max_scroll
                screen.refresh_ui()
                self.assertEqual(screen.scroll_y, screen.max_scroll)


if __name__ == "__main__":
    unittest.main()
