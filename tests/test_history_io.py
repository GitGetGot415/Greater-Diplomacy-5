"""History is written compressed and read either way.

The backward-compatibility case is the one that matters: every save made before
compression carries a plain history.json, and those must keep loading forever.
"""

import gzip
import copy
import json
import os
import random
import shutil
import tempfile
import unittest
from unittest import mock

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
        self.assertEqual(history_io.read_turn_dates(self.dir), {})

    def test_turn_dates_support_full_and_delta_files_in_both_storage_forms(self):
        history = {
            "7": {"date_str": "First date", "nation_data": {"A": {"materials": 10}}},
            "9": {"date_str": "First date", "nation_data": {"B": {"materials": 20}}},
            "10": {"nation_data": {}},
            "11": {"date_str": "Last date", "nation_data": {}},
        }
        expected = {"7": "First date", "9": "First date", "10": "Turn 10", "11": "Last date"}
        for filename, opener in ((history_io.PLAIN_NAME, open), (history_io.GZ_NAME, gzip.open)):
            for payload in (history, history_io.encode_history(history)):
                with self.subTest(filename=filename, delta="_history_format" in payload):
                    with opener(os.path.join(self.dir, filename), "wt", encoding="utf-8") as handle:
                        json.dump(payload, handle)
                    with mock.patch.object(history_io.copy, "deepcopy", side_effect=AssertionError(
                            "The history menu must not copy full snapshots")):
                        self.assertEqual(history_io.read_turn_dates(self.dir), expected)
                    self.assertEqual(history_io.read(self.dir), history)
                    os.remove(os.path.join(self.dir, filename))

    def test_turn_dates_prefer_compressed_history_and_keep_the_payload_unchanged(self):
        history = sample_history()
        payload = history_io.encode_history(history)
        before = copy.deepcopy(payload)
        expected = {turn: snapshot["date_str"] for turn, snapshot in history.items()}
        self.assertEqual(history_io.decode_history(payload, dates_only=True), expected)
        self.assertEqual(payload, before)
        with open(os.path.join(self.dir, history_io.PLAIN_NAME), "w", encoding="utf-8") as handle:
            json.dump({"99": {"date_str": "Stale date"}}, handle)
        with gzip.open(os.path.join(self.dir, history_io.GZ_NAME), "wt", encoding="utf-8") as handle:
            json.dump(payload, handle)
        self.assertEqual(history_io.read_turn_dates(self.dir), expected)

    def test_writing_empty_history_removes_old_files_and_writes_nothing(self):
        for filename in (history_io.GZ_NAME, history_io.PLAIN_NAME):
            with open(os.path.join(self.dir, filename), "w", encoding="utf-8") as f:
                f.write("{}")

        self.assertIsNone(history_io.write(self.dir, {}))
        self.assertFalse(os.path.exists(os.path.join(self.dir, history_io.GZ_NAME)))
        self.assertFalse(os.path.exists(os.path.join(self.dir, history_io.PLAIN_NAME)))
        self.assertEqual(history_io.read(self.dir), {})

    def test_a_corrupt_history_costs_the_timeline_not_the_save(self):
        with gzip.open(os.path.join(self.dir, history_io.GZ_NAME), "wt") as f:
            f.write("{not json")
        self.assertEqual(history_io.read(self.dir), {})

    def test_a_corrupt_compressed_history_falls_back_to_a_valid_legacy_file(self):
        with gzip.open(os.path.join(self.dir, history_io.GZ_NAME), "wt") as f:
            f.write("{not json")
        with open(os.path.join(self.dir, history_io.PLAIN_NAME), "w", encoding="utf-8") as f:
            json.dump(sample_history(), f)

        self.assertEqual(history_io.read(self.dir), sample_history())
        self.assertEqual(history_io.read_turn_dates(self.dir),
                         {turn: snapshot["date_str"] for turn, snapshot in sample_history().items()})

    def test_a_non_object_history_payload_is_treated_as_unavailable(self):
        with open(os.path.join(self.dir, history_io.PLAIN_NAME), "w", encoding="utf-8") as f:
            json.dump(["not", "a", "timeline"], f)

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

    def test_compact_dump_preserves_json_values_without_optional_whitespace(self):
        obj = sample_history()
        text = history_io.dump_compact_text(obj)
        self.assertEqual(json.loads(text), obj)
        self.assertEqual(text, json.dumps(obj, separators=(",", ":")))

    def test_save_text_keeps_short_values_on_one_line_and_splits_long_ones(self):
        obj = {"province": {"center": [84, 47], "order": {"type": "MOVE", "path": []},
                            "long": list(range(c.SAVE_LINE_WIDTH)), "empty": {}}}
        text = history_io.dump_save_text(obj)
        self.assertEqual(json.loads(text), obj)
        lines = text.split("\n")
        nested = " " * (2 * c.SAVE_INDENT)
        self.assertIn(nested + '"center": [84, 47],', lines)
        self.assertIn(nested + '"order": {"type": "MOVE", "path": []},', lines)
        self.assertIn(nested + '"empty": {}', lines)
        self.assertIn(nested + '"long": [', lines)
        self.assertTrue(all(len(line.rstrip(",")) <= c.SAVE_LINE_WIDTH for line in lines))

    def test_save_text_reads_back_as_json_dumps_does(self):
        obj = {1: [1.5, float("inf"), None, True, "é\n\"quoted\""], None: {}, False: [],
               2.5: (1, 2), "nested": [{"values": list(range(c.SAVE_LINE_WIDTH))}]}
        self.assertEqual(json.loads(history_io.dump_save_text(obj)), json.loads(json.dumps(obj)))
        with self.assertRaises(TypeError):
            history_io.dump_save_text({(1, 2): "tuple keys are not JSON"})
        with self.assertRaises(TypeError):
            history_io.dump_save_text({"value": {"sets are not JSON"}})

    def test_saved_history_is_readably_indented_before_compression(self):
        obj = sample_history()
        path = history_io.write(self.dir, obj, compress=False)
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        self.assertEqual(history_io.decode_history(json.loads(text)), obj)
        self.assertEqual(text, json.dumps(history_io.encode_history(obj), indent=c.HISTORY_INDENT))
        self.assertGreater(text.count("\n"), 1)

    def test_legacy_compressed_full_snapshots_still_load(self):
        with gzip.open(os.path.join(self.dir, history_io.GZ_NAME), "wt", encoding="utf-8") as handle:
            json.dump(sample_history(), handle)
        self.assertEqual(history_io.read(self.dir), sample_history())

    def test_deltas_preserve_edits_deletions_order_and_json_types(self):
        original = {
            "nation_data": {"A": {"inbox": [{"read": False}], "unknown": {"keep": 1, "remove": 2}},
                            "B": {"materials": 5}},
            "provinces": {"p": {"units": [{"id": "u", "health": 7}, {"id": "v"}]}}
        }
        modified = copy.deepcopy(original)
        modified["nation_data"]["A"]["inbox"][0]["read"] = True
        modified["nation_data"]["A"]["inbox"].append({"read": False, "text": "new"})
        modified["nation_data"]["A"]["unknown"] = {"new": None, "keep": True}
        modified["nation_data"] = {"B": modified["nation_data"]["B"], "A": modified["nation_data"]["A"]}
        modified["provinces"]["p"]["units"] = [{"id": "u", "health": 7.0}]
        removed = copy.deepcopy(modified)
        removed["nation_data"].pop("B")
        removed["provinces"]["p"]["units"] = []
        history = {"7": original, "9": modified, "10": removed, "11": copy.deepcopy(removed)}
        before = copy.deepcopy(history)
        history_io.write(self.dir, history)
        restored = history_io.read(self.dir)
        self.assertEqual(history, before)
        self.assertEqual(restored, history)
        self.assertEqual(list(restored), list(history))
        self.assertEqual(list(restored["9"]["nation_data"]), ["B", "A"])
        self.assertEqual(list(restored["9"]["nation_data"]["A"]["unknown"]), ["new", "keep"])
        self.assertIs(type(restored["7"]["nation_data"]["A"]["unknown"]["keep"]), int)
        self.assertIs(type(restored["9"]["nation_data"]["A"]["unknown"]["keep"]), bool)
        self.assertIs(type(restored["9"]["provinces"]["p"]["units"][0]["health"]), float)
        restored["9"]["nation_data"]["A"]["inbox"][0]["read"] = "changed"
        self.assertEqual(restored["10"], history["10"])
        self.assertEqual(restored["11"], history["11"])
        self.assertEqual(restored["7"], history["7"])

    def test_messages_inserted_at_the_front_store_older_messages_once(self):
        """Inboxes insert new messages first; older entries must not be rewritten."""
        limit = 40
        inbox = [{"text": f"message-{index}", "read": False} for index in range(limit)]
        history = {"1": {"nation_data": {"A": {"inbox": copy.deepcopy(inbox)}}}}
        inbox[0]["read"] = True
        inbox = [{"text": "new-1", "read": False}, {"text": "new-2", "read": False}] + inbox
        history["2"] = {"nation_data": {"A": {"inbox": inbox[:limit]}}}
        encoded = history_io.encode_history(history)
        inbox_delta = encoded["turns"][1][1][2]["nation_data"][2]["A"][2]["inbox"]
        self.assertEqual(inbox_delta[0], "list")
        self.assertEqual(inbox_delta[3], 2)
        text = history_io.dump_compact_text(encoded)
        for index in range(limit):
            self.assertEqual(text.count(f'"message-{index}"'), 1)
        self.assertEqual(history_io.decode_history(json.loads(text)), history)

    def test_list_changes_without_an_offset_still_load(self):
        payload = {"_history_format": history_io.DELTA_FORMAT, "turns": [
            ["1", ["set", {"values": [1, 2]}]],
            ["2", ["dict", [], {"values": ["list", 3, {"0": ["set", 9], "2": ["set", 3]}]}, None]],
        ]}
        self.assertEqual(history_io.decode_history(payload),
                         {"1": {"values": [1, 2]}, "2": {"values": [9, 2, 3]}})

    def test_invalid_list_offsets_are_rejected(self):
        for change in (["list", 1, {"0": ["set", 1]}, 2], ["list", 1, {"0": ["set", 1]}, -1],
                       ["list", 2, {}, 1], ["list", 2, {"0": ["set", 1]}, "1"]):
            payload = {"_history_format": history_io.DELTA_FORMAT, "turns": [
                ["1", ["set", {"values": [1]}]], ["2", ["dict", [], {"values": change}, None]]]}
            with self.subTest(change=change), self.assertRaises(ValueError):
                history_io.decode_history(payload)

    def test_appended_messages_and_unchanged_units_are_stored_once(self):
        history = {}
        snapshot = {"nation_data": {"A": {"inbox": []}}, "provinces": {
            str(index): {"units": [{"id": f"unit-{index}", "fixture": list(range(20))}]}
            for index in range(200)}}
        for turn in range(30):
            snapshot["nation_data"]["A"]["inbox"].append({"text": f"message-{turn}", "read": False})
            history[str(turn)] = copy.deepcopy(snapshot)
        encoded = history_io.encode_history(history)
        text = history_io.dump_compact_text(encoded)
        for turn in range(30):
            self.assertEqual(text.count(f'"message-{turn}"'), 1)
        self.assertEqual(text.count('"unit-199"'), 1)
        self.assertLess(len(text) * 10, len(history_io.dump_compact_text(history)))
        self.assertEqual(history_io.decode_history(json.loads(text)), history)

    def test_compressed_history_uses_compact_json_for_repetitive_snapshots(self):
        snapshot = {"provinces": {str(i): {"unit": {"fixture": list(range(30))}} for i in range(100)}}
        history = {str(turn): copy.deepcopy(snapshot) for turn in range(15)}
        path = history_io.write(self.dir, history)
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            text = handle.read()
        self.assertEqual(json.loads(text)["_history_format"], history_io.DELTA_FORMAT)
        self.assertNotIn("\n", text)
        self.assertEqual(history_io.read(self.dir), history)
        baseline = gzip.compress(history_io.dump_compact_text(history).encode(),
                                 compresslevel=c.HISTORY_GZIP_LEVEL, mtime=0)
        self.assertLess(os.path.getsize(path), len(baseline))

    def test_dense_changes_use_full_snapshots_when_patches_compress_worse(self):
        rng = random.Random(613)
        history = {str(turn): {"rows": [[rng.randrange(1000000) for _ in range(10)]
                                       for _ in range(100)]} for turn in range(10)}
        full = gzip.compress(history_io.dump_compact_text(history).encode(),
                             compresslevel=c.HISTORY_GZIP_LEVEL, mtime=0)
        deltas = gzip.compress(history_io.dump_compact_text(history_io.encode_history(history)).encode(),
                               compresslevel=c.HISTORY_GZIP_LEVEL, mtime=0)
        self.assertLess(len(full), len(deltas))
        path = history_io.write(self.dir, history)
        self.assertLessEqual(os.path.getsize(path), len(full))
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            self.assertEqual(json.load(handle), history)
        self.assertEqual(history_io.read(self.dir), history)

    def test_failed_compression_preserves_existing_history_and_removes_temporary_files(self):
        path = history_io.write(self.dir, sample_history())
        with open(path, "rb") as handle:
            original = handle.read()
        with mock.patch.object(history_io, "_snapshot_delta", side_effect=ValueError("fixture failure")):
            with self.assertRaisesRegex(ValueError, "fixture failure"):
                history_io.write(self.dir, {"99": {"fixture": "replacement"}})
        with open(path, "rb") as handle:
            self.assertEqual(handle.read(), original)
        self.assertEqual(os.listdir(self.dir), [history_io.GZ_NAME])
        self.assertEqual(history_io.read(self.dir), sample_history())

    def test_rewriting_a_compressed_legacy_history_keeps_all_snapshots_and_does_not_expand_it(self):
        history = {str(turn): {"country": {"inbox": [{"message": i} for i in range(turn)]},
                              "rows": [{"fixture": i, "value": turn + i} for i in range(200)]}
                   for turn in range(20)}
        path = os.path.join(self.dir, history_io.GZ_NAME)
        with gzip.open(path, "wt", encoding="utf-8", compresslevel=c.HISTORY_GZIP_LEVEL) as handle:
            handle.write(history_io.dump_text(history))
        original_size = os.path.getsize(path)
        loaded = history_io.read(self.dir)
        history_io.write(self.dir, loaded)
        self.assertLess(os.path.getsize(path), original_size)
        self.assertEqual(history_io.read(self.dir), history)

    def test_corrupt_delta_falls_back_to_legacy_history(self):
        with open(os.path.join(self.dir, history_io.PLAIN_NAME), "w", encoding="utf-8") as handle:
            json.dump(sample_history(), handle)
        malformed = [
            {"_history_format": "unknown", "turns": []},
            {"_history_format": history_io.DELTA_FORMAT, "turns": [["1", ["unknown"]]]},
            {"_history_format": history_io.DELTA_FORMAT, "turns": [["1", ["set", []]]]},
            {"_history_format": history_io.DELTA_FORMAT, "turns": [["1", ["set", {}]], ["1", None]]},
        ]
        for payload in malformed:
            with self.subTest(payload=payload):
                with gzip.open(os.path.join(self.dir, history_io.GZ_NAME), "wt", encoding="utf-8") as handle:
                    json.dump(payload, handle)
                self.assertEqual(history_io.read(self.dir), sample_history())
                self.assertEqual(history_io.read_turn_dates(self.dir),
                                 {turn: snapshot["date_str"] for turn, snapshot in sample_history().items()})


if __name__ == "__main__":
    unittest.main()
