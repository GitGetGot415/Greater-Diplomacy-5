"""Keep country appearance updates separate from gameplay fields."""

import copy
import unittest

from data import queries


class CountryAppearanceActionTests(unittest.TestCase):
    def test_identity_update_preserves_gameplay_and_copies_draft_values(self):
        nations = {"A": {"name": "Before", "materials": 7, "research": {"fixture": 2}}}
        draft = {"name": "After", "color": [10, 20, 30]}
        changed = queries.apply_country_appearance(nations, "A", draft)
        draft["color"][0] = 99
        self.assertEqual(set(changed), {"name", "color"})
        self.assertEqual(nations["A"]["materials"], 7)
        self.assertEqual(nations["A"]["research"], {"fixture": 2})
        self.assertIsNot(nations["A"]["color"], draft["color"])

    def test_gameplay_fields_are_rejected_before_mutation(self):
        nations = {"A": {"name": "Before", "materials": 7}}
        before = copy.deepcopy(nations)
        with self.assertRaises(ValueError):
            queries.apply_country_appearance(nations, "A", {"name": "After", "materials": 99})
        self.assertEqual(nations, before)

    def test_unknown_target_cannot_create_a_country(self):
        nations = {}
        with self.assertRaises(ValueError):
            queries.apply_country_appearance(nations, "missing", {"name": "After"})
        self.assertEqual(nations, {})
