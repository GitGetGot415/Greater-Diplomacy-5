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
    encode_invite, encode_relay_invite, read_message, sanitize_display_name, MapRealtimeDriver,
    collect_map_commands, default_advertised_address,
)
from data.io.realtime_relay import RelayHostTransport, relay_cloud_init, validate_relay_invite, _relay_firewall_payload
from data.io.realtime_relay_service import Relay
from data.io.realtime_networking import (
    PortMappingResult, automatic_tcp_port_mapping, host_network_diagnostics,
    is_public_ipv4, make_lan_announcement, parse_lan_announcement,
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


class FakeAddressProbe:
    def __init__(self, address="192.168.1.42", error=None):
        self.address = address
        self.error = error
        self.closed = False

    def connect(self, _endpoint):
        if self.error:
            raise self.error

    def getsockname(self): return (self.address, 54321)
    def close(self): self.closed = True


class AddressDetectionTests(unittest.TestCase):
    def test_default_address_uses_the_local_outbound_ipv4(self):
        probe = FakeAddressProbe()
        with mock.patch("data.io.realtime_multiplayer.socket.socket", return_value=probe):
            self.assertEqual(default_advertised_address(), "192.168.1.42")
        self.assertTrue(probe.closed)


class ConvenienceNetworkingTests(unittest.TestCase):
    def test_lan_announcement_uses_the_observed_sender_address(self):
        invite = {"v": 1, "host": "public.example", "port": 38475,
                  "session": "session", "fingerprint": "ab" * 32}
        announcement = make_lan_announcement(invite, "Host", "1939")
        match = parse_lan_announcement(announcement, "192.168.1.41", now=10.0)
        self.assertIsNotNone(match)
        self.assertEqual(match.invite["host"], "192.168.1.41")
        self.assertEqual(match.host_name, "Host")
        self.assertEqual(match.scenario_name, "1939")

    def test_lan_discovery_rejects_malformed_and_loopback_announcements(self):
        self.assertIsNone(parse_lan_announcement(b"not json", "192.168.1.41"))
        invite = {"v": 1, "host": "host", "port": 38475,
                  "session": "session", "fingerprint": "ab" * 32}
        self.assertIsNone(parse_lan_announcement(make_lan_announcement(invite, "Host", "Map"),
                                                  "127.0.0.1"))

    def test_mapping_falls_back_from_upnp_to_natpmp_and_reports_diagnostics(self):
        failed = PortMappingResult("UPnP", "No UPnP gateway.")
        mapped = PortMappingResult("NAT-PMP", "Mapped", "203.0.113.20", 38475,
                                   _release=lambda: None)
        with mock.patch("data.io.realtime_networking.try_upnp_port_mapping", return_value=failed), \
             mock.patch("data.io.realtime_networking.try_natpmp_port_mapping", return_value=mapped):
            result = automatic_tcp_port_mapping("192.168.1.41", 38475)
        self.assertIs(result, mapped)
        self.assertFalse(is_public_ipv4("192.168.1.41"))
        # TEST-NET addresses are intentionally non-global, so use a real
        # routable shape only to exercise the public-address classification.
        self.assertTrue(is_public_ipv4("8.8.8.8"))
        text = host_network_diagnostics("192.168.1.41", 38475, True, result)
        self.assertIn("Game server: listening", text)

    def test_default_address_falls_back_to_loopback_without_a_route(self):
        probe = FakeAddressProbe(error=OSError("no route"))
        with mock.patch("data.io.realtime_multiplayer.socket.socket", return_value=probe):
            self.assertEqual(default_advertised_address(), "127.0.0.1")
        self.assertTrue(probe.closed)


class RelayTransportTests(unittest.TestCase):
    def test_relay_invite_validation_and_cloud_init_exclude_provider_credentials(self):
        invite = decode_invite(encode_relay_invite("203.0.113.7", 443, "a" * 32, "b" * 64, "c" * 32))
        self.assertEqual(validate_relay_invite(invite)["relay_host"], "203.0.113.7")
        cloud_init = relay_cloud_init()
        self.assertIn("gd5-relay.service", cloud_init)
        self.assertIn("ssh_pwauth: false", cloud_init)
        self.assertNotIn("DigitalOcean", cloud_init)
        firewall = _relay_firewall_payload(42)
        self.assertEqual(firewall["droplet_ids"], [42])
        self.assertEqual(firewall["inbound_rules"],
                         [{"protocol": "tcp", "ports": "443", "sources": {"addresses": ["0.0.0.0/0"]}}])
        with self.assertRaises(RealtimeError):
            validate_relay_invite({"v": 1, "transport": "relay"})

    def _start_relay(self):
        relay, stopped = Relay(), threading.Event()
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0)); listener.listen(); listener.settimeout(.05)
        def accept_loop():
            while not stopped.is_set():
                try: connection, _ = listener.accept()
                except socket.timeout: continue
                except OSError: break
                threading.Thread(target=relay.serve, args=(connection,), daemon=True).start()
        threading.Thread(target=accept_loop, daemon=True).start()
        return listener, stopped

    def test_relay_invite_connects_to_the_existing_tls_server(self):
        listener, stopped = self._start_relay()
        session = RealtimeSession(RealtimeConfig("test", {}, max_players=2), ["A", "B"], "Host", Driver())
        with tempfile.TemporaryDirectory() as directory:
            certificate, key, fingerprint = create_match_certificate(directory)
            server = RealtimeServer(session, certificate, key)
            transport = RelayHostTransport("127.0.0.1", session.session_id, "h" * 32, "j" * 32,
                                           listener.getsockname()[1])
            try:
                server.start_relay(transport)
                invite = decode_invite(encode_relay_invite("127.0.0.1", listener.getsockname()[1],
                                                           session.session_id, fingerprint, "j" * 32))
                self.assertEqual(invite["transport"], "relay")
                client = RealtimeClient(invite)
                client.connect()
                client.send("join", {"name": "Relay Guest", "password": ""})
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline and not client.player_id:
                    client.poll(); time.sleep(.01)
                self.assertIsNotNone(client.player_id)
                self.assertTrue(server.listening)
                client.close()
            finally:
                server.stop()
                stopped.set(); listener.close()


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
                deadline = time.monotonic() + 5.0
                events = []
                while time.monotonic() < deadline:
                    events.extend(client.poll())
                    if client.player_id:
                        break
                    time.sleep(.01)
                self.assertIsNotNone(client.player_id, (events, client.disconnect_message))
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

    def test_plain_tcp_probe_does_not_stop_tls_listener(self):
        with tempfile.TemporaryDirectory() as directory:
            certificate, key, fingerprint = create_match_certificate(directory)
            server = RealtimeServer(self.session, certificate, key)
            port = server.start(0)
            try:
                # A port check has no TLS handshake.  It must be contained in
                # its own worker rather than ending the authoritative accept
                # loop for future real clients.
                probe = socket.create_connection(("127.0.0.1", port), 1)
                probe.close()
                time.sleep(.03)
                self.assertTrue(server.listening)
                invite = decode_invite(encode_invite("127.0.0.1", port,
                                                     self.session.session_id, fingerprint))
                client = RealtimeClient(invite)
                client.connect()
                client.close()
            finally:
                server.stop()


if __name__ == "__main__":
    unittest.main()
