"""Tournament archive size, compatibility, and recipient state coverage."""

import base64
import copy
import gzip
import json
from pathlib import Path
import random
import tempfile
import unittest
from unittest import mock

import pygame
from cryptography.fernet import Fernet

from data import constants as c, queries
from data.io import multiplayer_io as io
from data.map import history_io
from tests.test_tournament_moves import Host, nation, synchronous_progress


class TournamentArchiveTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        for patcher in (
                mock.patch.object(c, "TOURNAMENT_SAVES_DIR", str(self.root)),
                mock.patch.object(io, "run_with_progress", synchronous_progress),
                mock.patch.object(queries, "datetime")):
            patcher.start()
            self.addCleanup(patcher.stop)
        queries.datetime.now.return_value.isoformat.return_value = "fixture-export-time"
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
        self.host.political_map = self.host.terrain_map.copy()
        self.host.cores_map = self.host.terrain_map.copy()
        self.host.history = {"0": {"nation_data": {"private_old_turn": True}}}
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

    def test_snapshot_stores_current_provinces_once_and_regenerates_overlays(self):
        path, payload = self.export()
        snapshot = io.decrypt_dict(payload["game_data"], self.host.multiplayer_session_key)
        self.assertIsNone(payload["history"])
        self.assertEqual(set(snapshot["_images"]), {"terrain.png", "id_map.png"})
        for key, province in snapshot["provinces"].items():
            self.assertFalse(set(province) & set(snapshot["_raw_map_data"][key]))
        expected = queries.map_data_with_saved_provinces(self.host.raw_json_data, snapshot["provinces"])
        self.assertEqual(queries.map_data_with_saved_provinces(
            snapshot["_raw_map_data"], snapshot["provinces"]), expected)
        self.load_snapshot(path, "host-key")
        for name in ("terrain.png", "id_map.png"):
            self.assertEqual((self.root / "temp_load" / name).read_bytes()[:8], b'\x89PNG\r\n\x1a\n')

    def test_load_ignores_legacy_history_and_removes_stale_history_and_overlays(self):
        path, payload = self.export()
        payload["history"] = io.encrypt_dict(self.host.history, self.host.multiplayer_session_key)
        path.write_text(json.dumps(payload))
        directory = self.root / "temp_load"
        directory.mkdir(exist_ok=True)
        for key in ("host-key", next(iter(self.keys.values())), c.TOURNAMENT_SPECTATOR_KEY):
            for name in (history_io.GZ_NAME, history_io.PLAIN_NAME, "political.png", "cores.png"):
                (directory / name).write_bytes(b"stale data")
            self.load_snapshot(path, key)
            self.assertEqual(history_io.read(directory), {})
            for name in (history_io.GZ_NAME, history_io.PLAIN_NAME, "political.png", "cores.png"):
                self.assertFalse((directory / name).exists())

    def test_compression_is_lossless_and_legacy_ciphertext_remains_supported(self):
        data = {"fixture": [{"text": "repeated message " * 100, "values": [None, True, 1, 1.5]}] * 50}
        compressed = io.encrypt_dict(data, "fixture-key", compress=True)
        plain = io.encrypt_dict(data, "fixture-key")
        self.assertLess(len(compressed) * 5, len(plain))
        self.assertEqual(io.decrypt_dict(compressed, "fixture-key"), data)
        self.assertEqual(io.decrypt_dict(plain, "fixture-key"), data)
        self.assertIsNone(io.decrypt_dict(compressed, "wrong-key"))
        salt_text, token = compressed.split(":", 1)
        salt = base64.urlsafe_b64decode(salt_text)
        cipher = Fernet(io.generate_fernet_key_from_password("fixture-key", salt))
        plaintext = cipher.decrypt(token.encode())
        self.assertEqual(json.loads(gzip.decompress(plaintext)), data)
        corrupt = salt_text + ":" + cipher.encrypt(b'\x1f\x8bcorrupt gzip').decode()
        self.assertIsNone(io.decrypt_dict(corrupt, "fixture-key"))

    def test_compression_does_not_expand_small_tournament_payloads(self):
        data = {"a": 1}
        plain = io.encrypt_dict(data, "fixture-key")
        compressed = io.encrypt_dict(data, "fixture-key", compress=True)
        self.assertEqual(len(compressed), len(plain))
        self.assertEqual(io.decrypt_dict(compressed, "fixture-key"), data)

    def test_legacy_uncompressed_snapshot_loads_for_all_recipients(self):
        path, payload = self.export()
        for field, key in (("game_data", self.host.multiplayer_session_key),
                           ("spectator_game_data", c.TOURNAMENT_SPECTATOR_KEY)):
            payload[field] = io.encrypt_dict(io.decrypt_dict(payload[field], key), key)
        path.write_text(json.dumps(payload))
        for key in ("host-key", next(iter(self.keys.values())), c.TOURNAMENT_SPECTATOR_KEY):
            loaded, snapshot = self.load_snapshot(path, key)
            self.assertTrue(loaded[0])
            self.assertEqual(snapshot["date"]["total_turns"], self.host.time_manager.total_turns)

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
