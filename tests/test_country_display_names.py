"""Regression coverage for player-facing country names versus internal IDs."""

import unittest

from data import queries


class CountryDisplayNameTests(unittest.TestCase):
    def setUp(self):
        self.nation_data = {
            "GER": {"name": "German Reich"},
            "FRA": {"name": "French Republic"},
            "ALT_GER": {"name": "German Reich"},
            "EMPTY": {"name": "   "},
        }

    def test_display_name_uses_authored_name_with_id_fallback(self):
        self.assertEqual("German Reich", queries.get_country_display_name("GER", self.nation_data))
        self.assertEqual("UNKNOWN", queries.get_country_display_name("UNKNOWN", self.nation_data))
        self.assertEqual("EMPTY", queries.get_country_display_name("EMPTY", self.nation_data))

    def test_picker_hides_ids_except_for_duplicate_names(self):
        self.assertEqual(
            [("German Reich (GER)", "GER"), ("French Republic", "FRA"),
             ("German Reich (ALT_GER)", "ALT_GER")],
            queries.country_picker_items(["GER", "FRA", "ALT_GER"], self.nation_data))

    def test_picker_returns_the_internal_id_from_a_name_label(self):
        from ui.list_select_screen import ListSelectScreen

        picked = []
        screen = ListSelectScreen.__new__(ListSelectScreen)
        screen.on_confirm = picked.append
        screen.exit_screen = lambda: None
        screen.select(("German Reich", "GER"))
        self.assertEqual(["GER"], picked)


if __name__ == "__main__":
    unittest.main()
