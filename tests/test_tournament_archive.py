"""Tournament archive size, compatibility, and recipient state coverage."""

import base64
import copy
import json
from pathlib import Path
import random
import tempfile
import unittest
from unittest import mock

import pygame

from data import constants as c, queries
from data.io import multiplayer_io as io
from tests.test_tournament_moves import Host, nation, synchronous_progress


class TournamentArchiveTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        for patcher in (
                mock.patch.object(c, "TOURNAMENT_SAVES_DIR", str(self.root)),
                mock.patch.object(io, "run_with_progress", synchronous_progress)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.host = Host()
        self.keys = {f"Country{index}": f"player-key-{index}" for index in range(8)}
        self.host.nation_data = {cid: nation(name=cid) for cid in self.keys}
        self.host.player_country = next(iter(self.keys))
        self.host.active_players = list(self.keys)
        self.host.current_player_index = 0
        self.host.loop_map = False
        self.host.scenario_settings = {"fog_of_war": True}
        self.host.script_variables = []
        self.host.default_research = None
        self.host.map_data = {
            (index, 0, 0): {
                "id": index, "json_key": str(index), "owner": cid,
                "neighbors": [], "center": [index, 0], "units": [],
                "building_queue": [{"fixture": cid}], "unit_queue": [],
                "orders": [], "resources": {"fixture": index}, "buildings": [],
            }
            for index, cid in enumerate(self.keys, start=1)
        }
        self.host.raw_json_data = {
            row["json_key"]: copy.deepcopy(row) for row in self.host.map_data.values()}
        # Random pixels resist compression and expose repeated image payloads.
        rng = random.Random(1923)
        pixels = rng.randbytes(128 * 128 * 3)
        self.host.terrain_map = pygame.image.frombytes(pixels, (128, 128), "RGB")
        self.host.id_map = self.host.terrain_map.copy()
        for index, data in enumerate(self.host.nation_data.values()):
            data["inbox"] = [{"private": index}]
            data["research"] = {"fixture": index}
            data["custom_field"] = {"nested": [None, True, "retained"]}

    def export(self, name="turn.gd5tour", keys=None):
        path = self.root / name
        io.export_tournament(self.host, str(path), "host-key", self.keys if keys is None else keys)
        return path, json.loads(path.read_text())

    def load_snapshot(self, path, key):
        loaded = io.load_tournament(str(path), key)
        self.assertTrue(loaded[0], loaded[-1])
        directory = Path(loaded[3])
        result = json.loads((directory / "meta.json").read_text())
        result["_raw_map_data"] = json.loads((directory / "map_data.json").read_text())
        result["_images"] = {
            name: base64.b64encode((directory / name).read_bytes()).decode()
            for name in ("terrain.png", "id_map.png")}
        return loaded, result

    def test_hosts_and_country_players_load_one_shared_snapshot(self):
        original_raw = copy.deepcopy(self.host.raw_json_data)
        path, payload = self.export()
        self.assertEqual(set(payload), {
            "verification_table", "game_data", "spectator_game_data", "history"})
        canonical = io.decrypt_dict(payload["game_data"], self.host.multiplayer_session_key)
        _, restored = self.load_snapshot(path, "host-key")
        self.assertEqual(restored, canonical)
        _, restored = self.load_snapshot(path, c.TOURNAMENT_SPECTATOR_KEY)
        self.assertEqual(restored, io.build_tournament_spectator_save(canonical))
        for cid, key in self.keys.items():
            with self.subTest(country=cid):
                loaded, restored = self.load_snapshot(path, key)
                self.assertEqual(restored, canonical)
                self.assertEqual(loaded[1:3], ("PLAYER", cid))
                self.assertEqual(loaded[6], self.host.multiplayer_session_key)
                self.assertEqual(loaded[4], {})
                session = io.decrypt_dict(payload["verification_table"][io.hash_key(key)]["enc_session"], key)
                self.assertEqual(session, {"sk": self.host.multiplayer_session_key})
        self.assertEqual(self.host.raw_json_data, original_raw)
        self.assertFalse(io.load_tournament(str(path), "invalid-key")[0])

    def test_more_players_and_repeated_exports_add_only_key_records(self):
        first_country = next(iter(self.keys))
        single_path, single = self.export("single.gd5tour", {first_country: self.keys[first_country]})
        full_path, full = self.export()
        next_path, repeated = self.export("again.gd5tour")
        # These fields contain the whole map. Their size must not depend on
        # the number of country keys or earlier exports.
        for field in ("game_data", "spectator_game_data"):
            self.assertEqual(len(single[field]), len(full[field]))
            self.assertEqual(len(full[field]), len(repeated[field]))
        compact = lambda value: len(json.dumps(value, separators=(",", ":")).encode())
        expected_growth = compact(full["verification_table"]) - compact(single["verification_table"])
        self.assertEqual(full_path.stat().st_size - single_path.stat().st_size, expected_growth)
        self.assertEqual(full_path.stat().st_size, next_path.stat().st_size)
        self.assertEqual(full["verification_table"].keys(), repeated["verification_table"].keys())
        for cid, key in self.keys.items():
            self.assertEqual(full["verification_table"][io.hash_key(key)],
                             repeated["verification_table"][io.hash_key(key)])
            loaded, restored = self.load_snapshot(next_path, key)
            self.assertEqual(loaded[6], self.host.multiplayer_session_key)
            self.assertEqual(restored["nation_data"][cid]["inbox"], self.host.nation_data[cid]["inbox"])

    def test_regenerated_key_still_opens_the_shared_snapshot(self):
        self.export()
        cid = next(iter(self.keys))
        previous_key = self.keys[cid]
        self.host.multiplayer_pending_key_regen = {cid}
        path, payload = self.export("regenerated.gd5tour")
        self.assertNotIn(io.hash_key(previous_key), payload["verification_table"])
        self.assertFalse(io.load_tournament(str(path), previous_key)[0])
        loaded, restored = self.load_snapshot(path, self.keys[cid])
        self.assertEqual(loaded[6], self.host.multiplayer_session_key)
        self.assertEqual(restored, io.decrypt_dict(payload["game_data"], loaded[6]))

    def test_move_session_uses_the_shared_key(self):
        context = {"tournament_session": self.host.multiplayer_session_key,
                   "tournament_turn": self.host.time_manager.total_turns}
        self.assertIsNone(io._move_context_error(self.host, context))
        self.assertIsNone(io._move_context_error(self.host, {}))
        self.assertIsNotNone(io._move_context_error(self.host, dict(context, tournament_session="wrong-session")))
        self.assertIsNotNone(io._move_context_error(self.host, dict(context, tournament_turn=-1)))


if __name__ == "__main__":
    unittest.main()
