"""History is written compressed and read either way.

The backward-compatibility case is the one that matters: every save made before
compression carries a plain history.json, and those must keep loading forever.
"""

import gzip
import json
import os
import shutil
import tempfile
import unittest

import data.constants as c
from data.map import history_io


def sample_history():
    return {
        "1": {"date_str": "1 January, 1936 AD", "nation_data": {"Avaria": {"materials": 10}},
              "provinces": {"a": {"owner": "Avaria"}}},
        "2": {"date_str": "16 January, 1936 AD", "nation_data": {"Avaria": {"materials": 20}},
              "provinces": {"a": {"owner": "Bruland"}}},
    }


class HistoryIOTests(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)

    def test_round_trip_through_the_compressed_form(self):
        history_io.write(self.dir, sample_history())
        self.assertTrue(os.path.exists(os.path.join(self.dir, history_io.GZ_NAME)))
        self.assertEqual(history_io.read(self.dir), sample_history())

    def test_a_plain_history_from_an_older_save_still_loads(self):
        """The whole point of the fallback -- existing saves predate the .gz."""
        with open(os.path.join(self.dir, history_io.PLAIN_NAME), "w") as f:
            json.dump(sample_history(), f)
        self.assertEqual(history_io.read(self.dir), sample_history())

    def test_the_compressed_form_wins_when_both_are_present(self):
        with open(os.path.join(self.dir, history_io.PLAIN_NAME), "w") as f:
            json.dump({"9": {"date_str": "stale"}}, f)
        history_io.write(self.dir, sample_history())
        self.assertEqual(history_io.read(self.dir), sample_history())

    def test_writing_removes_the_other_form(self):
        """Otherwise a folder keeps a stale plain history beside a fresh one."""
        with open(os.path.join(self.dir, history_io.PLAIN_NAME), "w") as f:
            json.dump({"9": {}}, f)
        history_io.write(self.dir, sample_history())
        self.assertFalse(os.path.exists(os.path.join(self.dir, history_io.PLAIN_NAME)))

    def test_no_history_reads_as_empty(self):
        self.assertEqual(history_io.read(self.dir), {})

    def test_a_corrupt_history_costs_the_timeline_not_the_save(self):
        with gzip.open(os.path.join(self.dir, history_io.GZ_NAME), "wt") as f:
            f.write("{not json")
        self.assertEqual(history_io.read(self.dir), {})

    def test_it_actually_compresses(self):
        """A guard on the gzip level: repetitive snapshots should shrink a lot."""
        repetitive = {str(t): {"date_str": "d", "nation_data": {f"N{i}": {"materials": 5, "fuel": 5}
                                                               for i in range(200)}}
                      for t in range(30)}
        path = history_io.write(self.dir, repetitive)
        plain = len(history_io.dump_text(repetitive))
        self.assertLess(os.path.getsize(path) * 5, plain)

    def test_dump_text_matches_json_dumps(self):
        """It replaces json.dump at every call site, so it must agree with it."""
        obj = sample_history()
        self.assertEqual(json.loads(history_io.dump_text(obj, indent=c.SAVE_INDENT)), obj)
        self.assertEqual(history_io.dump_text(obj), json.dumps(obj))


if __name__ == "__main__":
    unittest.main()
