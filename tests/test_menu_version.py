import unittest
from unittest import mock

from screens.menus import menu


class MenuVersionTests(unittest.TestCase):
    def test_version_status_compares_version_numbers(self):
        cases = (
            ("v47", "v46", "Version: v47 (Dev version)", (100, 160, 255)),
            ("v9", "v10", "Outdated! Latest: v10 (Current: v9)", (255, 100, 100)),
            ("v47", "v47", "Version: v47 (Up to date)", menu.c.COLOR_SUCCESS_GREEN),
            ("v47", "invalid", "Version: v47 (Error checking)", (255, 100, 100)),
        )
        for current, released, status, color in cases:
            with self.subTest(current=current, released=released), \
                    mock.patch.object(menu.c, "GAME_VERSION", current), \
                    mock.patch.object(menu.urllib.request, "urlopen") as open_url:
                open_url.return_value.read.return_value = released.encode("utf-8")
                instance = menu.Menu.__new__(menu.Menu)
                instance.check_version()
                self.assertEqual(instance.version_status, status)
                self.assertEqual(instance.version_color, color)


if __name__ == "__main__":
    unittest.main()
