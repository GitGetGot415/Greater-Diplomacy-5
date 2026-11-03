import unittest
from unittest import mock

from screens.menus import menu


class MenuVersionTests(unittest.TestCase):
    def version_status(self, current, released):
        with mock.patch.object(menu.c, "GAME_VERSION", current), \
                mock.patch.object(menu.urllib.request, "urlopen") as open_url:
            open_url.return_value.read.return_value = released.encode("utf-8")
            instance = menu.Menu.__new__(menu.Menu)
            instance.check_version()
        self.assertIn(current, instance.version_status)
        return instance.version_status.replace(current, "{current}").replace(released, "{released}")

    def test_version_status_compares_version_numbers(self):
        # Equal comparisons must report the same state after display text changes.
        states = {"newer": self.version_status("v2", "v1"),
                  "older": self.version_status("v1", "v2"),
                  "same": self.version_status("v1", "v1"),
                  "error": self.version_status("v1", "invalid")}
        self.assertEqual(len(set(states.values())), len(states))
        cases = (
            ("v47", "v46", "newer"),
            ("v9", "v10", "older"),
            ("v10", "v9", "newer"),
            ("v47", "v47", "same"),
            ("v47", "invalid", "error"),
            ("invalid", "v47", "error"),
        )
        for current, released, state in cases:
            with self.subTest(current=current, released=released):
                self.assertEqual(self.version_status(current, released), states[state])


if __name__ == "__main__":
    unittest.main()
