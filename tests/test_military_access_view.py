"""Military access is stored on the granting side only.

That makes the two directions genuinely different questions -- who may march
through this nation, and whose land it may march through -- and only the first
was answerable without a sweep. Neither was listed anywhere in the UI; access
showed up solely as the enabled/disabled state of a button.
"""

import os
import sys
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data import queries


class MilitaryAccessViewTests(unittest.TestCase):
    def setUp(self):
        # Avaria lets Borland and Cirenia through. Nobody lets Avaria through.
        self.nation_data = {
            "Avaria": {"military_access": ["Borland", "Cirenia"]},
            "Borland": {"military_access": ["Cirenia"]},
            "Cirenia": {},
            "GLOBAL_EVENTS": ["not a nation"],
        }

    def test_granted_by_lists_who_may_walk_through_us(self):
        self.assertEqual(queries.get_military_access_granted_by("Avaria", self.nation_data),
                         ["Borland", "Cirenia"])

    def test_granted_to_lists_whose_land_we_may_walk_through(self):
        self.assertEqual(queries.get_military_access_granted_to("Cirenia", self.nation_data),
                         ["Avaria", "Borland"])

    def test_the_two_directions_are_not_the_same_question(self):
        """Access is one-way: Avaria grants Borland passage, not the reverse."""
        self.assertIn("Borland", queries.get_military_access_granted_by("Avaria", self.nation_data))
        self.assertNotIn("Borland", queries.get_military_access_granted_to("Avaria", self.nation_data))

    def test_a_nation_granting_nothing_reports_nothing(self):
        self.assertEqual(queries.get_military_access_granted_by("Cirenia", self.nation_data), [])

    def test_a_nation_nobody_admits_reports_nothing(self):
        self.assertEqual(queries.get_military_access_granted_to("Avaria", self.nation_data), [])

    def test_non_nation_entries_are_skipped(self):
        """nation_data carries GLOBAL_EVENTS, which is a list, not a nation."""
        self.assertEqual(queries.get_military_access_granted_to("not a nation", self.nation_data), [])

    def test_the_returned_list_is_a_copy(self):
        """Callers must not be able to grant access by editing a panel's list."""
        got = queries.get_military_access_granted_by("Avaria", self.nation_data)
        got.append("Dessia")
        self.assertNotIn("Dessia", self.nation_data["Avaria"]["military_access"])

    def test_an_unknown_nation_is_handled(self):
        self.assertEqual(queries.get_military_access_granted_by("Nowhere", self.nation_data), [])


if __name__ == "__main__":
    unittest.main()
