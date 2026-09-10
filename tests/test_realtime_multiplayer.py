"""Focused deterministic coverage for the real-time session state machine."""

import threading
import time
import unittest
import tempfile
import socket
import struct
from types import SimpleNamespace
from unittest import mock

from data.io.realtime_multiplayer import (
    DEFAULT_MAX_TURNS, RealtimeConfig, RealtimeError, RealtimeSession,
    RealtimeClient, RealtimeServer, create_match_certificate, decode_invite,
    encode_invite, read_message, sanitize_display_name, MapRealtimeDriver,
    collect_map_commands,
)


class Clock:
    def __init__(self): self.value = 100.0
    def __call__(self): return self.value


class Driver:
    def __init__(self):
        self.processed = []
        self.eliminated = set()
        self.release = None

    def validate_draft(self, country, commands):
        if any(command.get("country") not in (None, country) for command in commands):
            raise RealtimeError("Foreign order.")
        return commands

    def process_turn(self, drafts):
        if self.release:
            self.release.wait(1)
        self.processed.append(drafts)

    def is_eliminated(self, country): return country in self.eliminated


class RealtimeSessionTests(unittest.TestCase):
    def setUp(self):
        self.clock, self.driver = Clock(), Driver()
        self.session = RealtimeSession(RealtimeConfig("test", {}, max_players=3,
                                                       max_turns=2, turn_minutes=1),
                                       ["A", "B", "C"], "Host", self.driver, clock=self.clock)
        self.host = self.session.host_id
        self.other = self.session.join("Guest")

    def start(self):
        self.session.select_country(self.host, "A")
        self.session.select_country(self.other.player_id, "B")
        self.session.set_ready(self.host, True)
        self.session.set_ready(self.other.player_id, True)
        self.session.start(self.host)

    def wait_for_turn(self):
        for _ in range(100):
            if self.session.phase in ("TURN", "GAME_OVER"):
                return
            time.sleep(.01)
        self.fail("turn did not finish")

    def test_name_validation_and_duplicate_rejection(self):
        self.assertEqual(sanitize_display_name("  Alice  "), "Alice")
        with self.assertRaises(RealtimeError): sanitize_display_name("\nAlice")
        with self.assertRaises(RealtimeError): self.session.join("guest")

    def test_country_selection_is_exclusive_under_race(self):
        outcomes = []
        barrier = threading.Barrier(2)
        def choose(player):
            barrier.wait()
            try:
                self.session.select_country(player, "A")
                outcomes.append("accepted")
            except RealtimeError:
                outcomes.append("rejected")
        a = threading.Thread(target=choose, args=(self.host,))
        b = threading.Thread(target=choose, args=(self.other.player_id,))
        a.start(); b.start(); a.join(); b.join()
        self.assertEqual(sorted(outcomes), ["accepted", "rejected"])

    def test_lobby_readiness_and_host_normal_player(self):
        self.session.select_country(self.host, "A")
        self.session.select_country(self.other.player_id, "B")
        self.session.set_ready(self.host, True)
        self.assertFalse(self.session.can_start()[0])
        self.session.set_ready(self.other.player_id, True)
        self.session.start(self.host)
        self.assertEqual(self.session.players[self.host].country_id, "A")
        self.assertFalse(hasattr(self.session.players[self.host], "admin_gameplay"))

    def test_timer_uses_server_clock_and_latest_draft(self):
        self.start()
        self.session.sync_draft(self.host, 1, [{"type": "hold", "country": "A"}])
        self.clock.value += 61
        self.session.tick()
        self.wait_for_turn()
        self.assertEqual(self.driver.processed[0]["A"][0]["type"], "hold")

    def test_submit_lock_unsubmit_and_processing_race(self):
        self.start()
        self.session.submit(self.host, 1)
        with self.assertRaises(RealtimeError): self.session.sync_draft(self.host, 1, [])
        self.session.unsubmit(self.host, 1)
        self.assertFalse(self.session.players[self.host].submitted)
        self.driver.release = threading.Event()
        self.session.submit(self.host, 1)
        self.session.submit(self.other.player_id, 1)
        self.assertEqual(self.session.phase, "PROCESSING")
        with self.assertRaises(RealtimeError): self.session.unsubmit(self.host, 1)
        self.driver.release.set()
        self.wait_for_turn()

    def test_end_match_waits_for_inflight_processing(self):
        self.start()
        self.driver.release = threading.Event()
        self.session.submit(self.host, 1)
        self.session.submit(self.other.player_id, 1)
        self.session.end_match(self.host)
        self.assertEqual(self.session.phase, "PROCESSING")
        self.driver.release.set()
        self.wait_for_turn()
        self.assertEqual(self.session.phase, "GAME_OVER")
        self.assertEqual(self.session.game_over_reason, "host_aborted")

    def test_stale_orders_duplicate_processing_and_turn_limit(self):
        self.start()
        with self.assertRaises(RealtimeError): self.session.sync_draft(self.host, 2, [])
        self.session.submit(self.host, 1); self.session.submit(self.other.player_id, 1)
        self.wait_for_turn()
        self.session.submit(self.host, 2); self.session.submit(self.other.player_id, 2)
        self.wait_for_turn()
        self.assertEqual(self.session.phase, "GAME_OVER")
        self.assertEqual(self.session.game_over_reason, "turn_limit")
        self.assertEqual(len(self.driver.processed), 2)
        with self.assertRaises(RealtimeError): self.session.submit(self.host, 2)

    def test_reconnect_and_invite_round_trip(self):
        token = self.other.reconnect_token
        self.session.disconnect(self.other.player_id)
        restored = self.session.reconnect(token)
        self.assertEqual(restored.player_id, self.other.player_id)
        invite = encode_invite("example.test", 38475, self.session.session_id, "ab" * 32)
        self.assertEqual(decode_invite(invite)["session"], self.session.session_id)

    def test_research_draft_uses_server_progress_not_client_progress(self):
        map_ref = SimpleNamespace(
            nation_data={"A": {"research": {"test_tech": 0}, "research_queue": [],
                               "research_progress": {}}},
            map_data={}, id_to_province={})
        driver = MapRealtimeDriver(map_ref)
        tech_tree = {"test_tech": {"max_lvl": 1, "cost": 250, "req": {}}}
        with mock.patch("data.queries.get_tech_tree", return_value=tech_tree):
            canonical = driver.validate_draft("A", [{"type": "research_queue",
                                                       "tech_names": ["test_tech"],
                                                       "points_remaining": 0}])
            self.assertEqual(canonical[0]["projects"],
                             [{"tech_name": "test_tech", "points_remaining": 250}])

            map_ref.nation_data["A"]["research_queue"] = canonical[0]["projects"]
            map_ref.nation_data["A"]["research_queue"][0]["points_remaining"] = 125
            paused = driver.validate_draft("A", [{"type": "research_queue", "tech_names": []}])
        self.assertEqual(paused[0]["research_progress"], {"test_tech": 125})

    def test_collects_empty_and_nonempty_research_selection(self):
        map_ref = SimpleNamespace(
            map_data={},
            nation_data={"A": {"name": "A", "color": [1, 2, 3],
                               "research_queue": [{"tech_name": "test_tech", "points_remaining": 10}]}})
        commands = collect_map_commands(map_ref, "A")
        self.assertIn({"type": "research_queue", "tech_names": ["test_tech"]}, commands)
        map_ref.nation_data["A"]["research_queue"] = []
        self.assertIn({"type": "research_queue", "tech_names": []},
                      collect_map_commands(map_ref, "A"))

    def test_tls_server_client_join_and_malformed_frame_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            certificate, key, fingerprint = create_match_certificate(directory)
            server = RealtimeServer(self.session, certificate, key)
            port = server.start(0)
            try:
                invite = decode_invite(encode_invite("127.0.0.1", port,
                                                     self.session.session_id, fingerprint))
                client = RealtimeClient(invite)
                client.connect()
                client.send("join", {"name": "Network Guest", "password": ""})
                for _ in range(50):
                    if any(event.get("type") == "ok" for event in client.poll()):
                        break
                    time.sleep(.01)
                self.assertIsNotNone(client.player_id)
                client.close()
            finally:
                server.stop()
        left, right = socket.socketpair()
        try:
            right.sendall(struct.pack("!I", 1) + b"{")
            with self.assertRaises(RealtimeError):
                read_message(left)
        finally:
            left.close(); right.close()


if __name__ == "__main__":
    unittest.main()
