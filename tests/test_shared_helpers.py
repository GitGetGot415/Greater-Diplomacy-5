"""Contracts for the small helpers promoted out of feature modules."""

import os
import tempfile
import unittest

from data.io.json_io import load_json_or_empty, render_compact_mapping, write_compact_mapping
from data.number_utils import clamp, clamp01, clamp_float


class NumberUtilsTests(unittest.TestCase):
    def test_clamp_preserves_the_requested_bounds(self):
        self.assertEqual(clamp(-2, 0, 5), 0)
        self.assertEqual(clamp(7, 0, 5), 5)
        self.assertEqual(clamp(3, 0, 5), 3)

    def test_float_clamping_handles_persisted_values(self):
        self.assertEqual(clamp01(1.2), 1.0)
        self.assertEqual(clamp_float("0.25", 0.0, 1.0, 0.5), 0.25)
        self.assertEqual(clamp_float("not a number", 0.0, 1.0, 0.5), 0.5)


class CompactJsonTests(unittest.TestCase):
    def test_render_and_write_keep_top_level_values_on_one_line(self):
        value = {"Alpha": {"attack": 2, "cost": 5}, "Bravo": {"attack": 3}}
        rendered = render_compact_mapping(value)
        self.assertEqual(rendered.splitlines()[1], '    "Alpha": {"attack": 2, "cost": 5},')

        handle, path = tempfile.mkstemp(suffix=".json")
        os.close(handle)
        try:
            write_compact_mapping(path, value)
            self.assertEqual(load_json_or_empty(path), value)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
