"""Focused deterministic coverage for the real-time session state machine."""

import threading
import time
import unittest
import tempfile
import socket
import struct
import pygame
from types import SimpleNamespace
from unittest import mock

from data.io.realtime_multiplayer import (
    DEFAULT_MAX_TURNS, RealtimeConfig, RealtimeError, RealtimeSession,
    RealtimeClient, RealtimeServer, create_match_certificate, decode_invite,
    encode_invite, encode_relay_invite, read_message, sanitize_display_name, MapRealtimeDriver,
    apply_authoritative_snapshot, collect_map_commands, default_advertised_address,
    load_reconnect_token, persist_reconnect_token,
)
import data.constants as c
from data.io.realtime_relay import (RelayHostTransport, relay_cloud_init, validate_relay_invite,
                                    _relay_firewall_payload, DigitalOceanRelayTask)
from data.io.realtime_relay_service import Relay
from data.map.load_map import _saved_player_view
from data.io.realtime_networking import (
    PortMappingResult, automatic_tcp_port_mapping, host_network_diagnostics,
    is_public_ipv4, make_lan_announcement, parse_lan_announcement,
)
from screens.menu_screens.realtime_multiplayer import (
    Realtime_Join, Realtime_Relay_Provision, Realtime_Remote_Lobby,
)
from screens.menu_screens.map import Map
from ui_elements import Button


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


class HostSnapshotTests(unittest.TestCase):
    def test_host_view_refreshes_from_server_before_the_next_turn_draft(self):
        """The host UI is a separate map and must not retain turn-one units."""
        province = {"id": 1, "json_key": "home", "owner": "A", "units": [],
                    "cores": [], "building_queue": [], "unit_queue": []}
        host_view = object.__new__(Map)
        host_view.realtime_server_map = object()
        host_view.map_data = {"home": province}
        host_view.nation_data = {"A": {}}
        host_view.time_manager = SimpleNamespace(day=1, month_index=0, year=1939,
                                                  total_turns=0)
        host_view.refresh_all_maps = mock.Mock()
        snapshot = {
            "nation_data": {"A": {"name": "A"}},
            "provinces": {"home": {"units": [{"owner": "A", "type": "Infantry"}]}},
            "date": {"day": 1, "month": 0, "year": 1939, "total_turns": 1},
        }
        session = SimpleNamespace(phase="TURN", turn_number=2,
                                  public_state=mock.Mock(return_value={"game_state": snapshot}))
        host_view.realtime_session = session

        Map._apply_host_realtime_snapshot(host_view)

        self.assertEqual(host_view.map_data["home"]["units"], snapshot["provinces"]["home"]["units"])
        self.assertEqual(host_view._realtime_snapshot_turn, 2)
        session.public_state.assert_called_once_with()

        Map._apply_host_realtime_snapshot(host_view)
        session.public_state.assert_called_once_with()

    def test_snapshot_retains_local_read_and_popup_state_for_the_same_message(self):
        client_map = object.__new__(Map)
        client_map.player_country = "A"
        client_map.nation_data = {"A": {"inbox": [
            {"message_id": "handled", "read": True, "popup_shown": True},
        ]}}
        client_map.map_data = {}
        client_map.refresh_all_maps = mock.Mock()
        snapshot = {"nation_data": {"A": {"inbox": [
            {"message_id": "handled", "read": False, "popup_shown": False},
            {"message_id": "new", "read": False, "popup_shown": False},
        ]}}}

        apply_authoritative_snapshot(client_map, snapshot)

        handled, new = client_map.nation_data["A"]["inbox"]
        self.assertTrue(handled["read"])
        self.assertTrue(handled["popup_shown"])
        self.assertFalse(new["read"])
        self.assertFalse(new["popup_shown"])


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
    def test_macos_clipboard_fallback_uses_pbcopy_when_sdl_clipboard_is_unavailable(self):
        from data import queries
        with mock.patch("data.queries.pygame.scrap.get_init", side_effect=RuntimeError("no SDL clipboard")), \
             mock.patch("data.queries.sys.platform", "darwin"), \
             mock.patch("data.queries.subprocess.run") as run:
            self.assertTrue(queries.copy_to_clipboard("reconnect-code"))
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0], ["/usr/bin/pbcopy"])
        self.assertEqual(run.call_args.kwargs["input"], b"reconnect-code")

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

    def test_relay_task_exposes_a_nonempty_progress_status(self):
        task = DigitalOceanRelayTask("x" * 24, "a" * 32)
        self.assertIn("Ready", task.status)

    def test_client_send_reports_a_broken_pipe_without_blocking_the_ui(self):
        class BrokenSocket:
            def __init__(self): self.closed = False
            def sendall(self, _data): raise BrokenPipeError("connection closed")
            def close(self): self.closed = True

        client = RealtimeClient({"session": "test"})
        connection = BrokenSocket()
        client.socket = connection

        # Queuing succeeds immediately; the sender thread reports the actual
        # broken pipe asynchronously instead of freezing a confirmation modal.
        self.assertTrue(client.send("select_country", {"country_id": "A"}))
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline and client.socket is not None:
            time.sleep(.01)
        self.assertTrue(connection.closed)
        self.assertIsNone(client.socket)
        self.assertEqual(client.poll(), [{"type": "disconnected", "payload": {
            "message": "connection closed"}}])

    def test_reconnect_token_is_recovered_only_for_the_same_pinned_invite(self):
        invite = decode_invite(encode_invite("example.test", 38475, "s" * 32, "a" * 64))
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(c, "SAVES_DIR", directory):
            persist_reconnect_token(invite, "reconnect-secret", "Guest")
            self.assertEqual(load_reconnect_token(invite), "reconnect-secret")
            other_invite = dict(invite, fingerprint="b" * 64)
            self.assertEqual(load_reconnect_token(other_invite), "")

    def test_join_uses_entered_name_even_when_an_old_reconnect_code_exists(self):
        """A reconnect token restores a prior identity only when the player
        explicitly chooses Reconnect; it must not silently discard a new name.
        """
        invite = encode_invite("example.test", 38475, "s" * 32, "a" * 64)
        screen = object.__new__(Realtime_Join)
        screen.invite_text, screen.name = invite, "New Guest"
        screen.password, screen.reconnect_token = "", "old-reconnect-code"
        client = mock.Mock()
        with mock.patch("screens.menu_screens.realtime_multiplayer.RealtimeClient", return_value=client):
            Realtime_Join.connect(screen)

        client.connect.assert_called_once_with()
        client.send.assert_called_once_with("join", {"name": "New Guest", "password": ""})

    def test_reconnect_is_an_explicit_separate_request(self):
        invite = encode_invite("example.test", 38475, "s" * 32, "a" * 64)
        screen = object.__new__(Realtime_Join)
        screen.invite_text, screen.name = invite, "New Guest"
        screen.password, screen.reconnect_token = "", "old-reconnect-code"
        client = mock.Mock()
        with mock.patch("screens.menu_screens.realtime_multiplayer.RealtimeClient", return_value=client):
            Realtime_Join.reconnect(screen)

        client.send.assert_called_once_with("reconnect", {"reconnect_token": "old-reconnect-code"})

    def test_remote_lobby_rename_sends_a_server_validated_request(self):
        screen = object.__new__(Realtime_Remote_Lobby)
        screen.client = mock.Mock()
        screen.view = SimpleNamespace(player_id="guest", players={
            "guest": SimpleNamespace(name="Player"),
        })

        def answer(_title, _message, callback, **_kwargs):
            callback("New Guest")

        with mock.patch("ui.confirm_dialog.ask_string", side_effect=answer):
            Realtime_Remote_Lobby.edit_name(screen)

        screen.client.send.assert_called_once_with("rename", {"name": "New Guest"})

    def test_idle_read_timeout_is_ignored_until_the_connection_actually_closes(self):
        class Socket:
            def close(self): pass

        client = RealtimeClient({"session": "test"})
        client.socket = Socket()
        with mock.patch("data.io.realtime_multiplayer.read_message",
                        side_effect=[TimeoutError("idle"), ConnectionError("closed")]) as read:
            client._receive_loop()

        self.assertEqual(read.call_count, 2)
        self.assertEqual(client.poll(), [{"type": "disconnected", "payload": {"message": "closed"}}])

    def test_explicit_host_shutdown_is_not_replaced_by_a_disconnect_alert(self):
        class Socket:
            def __init__(self): self.closed = False
            def close(self): self.closed = True

        client = RealtimeClient({"session": "test"})
        connection = Socket()
        client.socket = connection
        shutdown = {"session_id": "test", "type": "shutdown",
                    "payload": {"message": "The host ended the match."}}
        with mock.patch("data.io.realtime_multiplayer.read_message", return_value=shutdown):
            client._receive_loop()

        self.assertTrue(connection.closed)
        self.assertIsNone(client.socket)
        self.assertEqual(client.poll(), [shutdown])
        client._mark_disconnected("connection closed")
        self.assertEqual(client.poll(), [])

    def test_explicit_lobby_kick_is_not_replaced_by_a_disconnect_alert(self):
        class Socket:
            def __init__(self): self.closed = False
            def close(self): self.closed = True

        client = RealtimeClient({"session": "test"})
        connection = Socket()
        client.socket = connection
        kicked = {"session_id": "test", "type": "kicked",
                  "payload": {"message": "The host removed you from the real-time lobby."}}
        with mock.patch("data.io.realtime_multiplayer.read_message", return_value=kicked):
            client._receive_loop()

        self.assertTrue(connection.closed)
        self.assertIsNone(client.socket)
        self.assertEqual(client.poll(), [kicked])

    def test_finished_relay_task_is_attached_and_transitioned_once(self):
        """A completed worker stays completed, so the screen must consume it once."""
        relay = object()
        finish = mock.Mock()
        task = SimpleNamespace(done=lambda: True, result=relay)
        screen = Realtime_Relay_Provision.__new__(Realtime_Relay_Provision)
        screen.host_setup = SimpleNamespace(relay_task=task, finish_relay_provisioning=finish)
        screen._relay_transitioned = False
        screen.go_to = mock.Mock()

        screen.update()
        screen.update()

        finish.assert_called_once_with(relay)
        screen.go_to.assert_called_once_with("REALTIME_LOBBY")

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
                self.assertIsNone(client.socket.gettimeout())
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


class RealtimeExitTests(unittest.TestCase):
    def test_guest_leaving_does_not_call_host_end_match(self):
        """A remote player may disconnect, but cannot shut down the host match."""
        client = SimpleNamespace(close=mock.Mock())
        session = SimpleNamespace(phase="TURN", host_id="host", end_match=mock.Mock())
        map_ref = SimpleNamespace(
            realtime_multiplayer=True,
            realtime_session=session,
            realtime_player_id="guest",
            realtime_client=client,
            show_feedback=mock.Mock(),
            change_state=mock.Mock(),
        )

        def confirm(_title, _message, callback, **_labels):
            callback(True)

        with mock.patch("ui.confirm_dialog.ask_yes_no", side_effect=confirm) as ask:
            Map.exit_to_menu(map_ref)

        self.assertEqual(ask.call_args.args[0], "Leave Real-Time Match")
        client.close.assert_called_once()
        session.end_match.assert_not_called()
        map_ref.change_state.assert_called_once_with("MULTIPLAYER_MENU")

    def test_host_exit_notifies_guests_before_stopping_server(self):
        server = SimpleNamespace(stop=mock.Mock())
        session = SimpleNamespace(phase="TURN", host_id="host")

        def end_match(_player):
            session.phase = "GAME_OVER"

        session.end_match = end_match
        map_ref = SimpleNamespace(
            realtime_multiplayer=True,
            realtime_session=session,
            realtime_player_id="host",
            realtime_server=server,
            realtime_port_mapping=None,
            _destroy_temporary_relay=mock.Mock(),
            show_feedback=mock.Mock(),
        )

        def confirm(_title, _message, callback, **_labels):
            callback(True)

        with mock.patch("ui.confirm_dialog.ask_yes_no", side_effect=confirm):
            Map.exit_to_menu(map_ref)

        server.stop.assert_called_once_with(
            "The host ended the real-time match. You have been disconnected.")

    def test_map_hud_button_click_does_not_fall_through_to_a_tile(self):
        pygame.font.init()
        button = Button(100, 100, "small", "blue", "Details", lambda: None)
        map_ref = SimpleNamespace(thread_error=None, elements=[button])
        event = pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(110, 110))
        with mock.patch("screens.menu_screens.map.event_handler.handle_map_events") as handle:
            Map.additional_events(map_ref, event)
        handle.assert_not_called()


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

    def test_server_acknowledges_the_authoritative_join_name(self):
        server = RealtimeServer(self.session, "unused-cert", "unused-key")
        result, player_id = server._handle_message(None, {
            "type": "join", "payload": {"name": "  Network Guest  ", "password": ""},
        })

        self.assertEqual(result["display_name"], "Network Guest")
        self.assertEqual(self.session.players[player_id].name, "Network Guest")

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
        self.assertEqual(self.session.public_state()["host_id"], self.host)

    def test_public_state_reports_server_measured_player_ping(self):
        self.session.set_ping(self.other.player_id, 47)
        players = {player["player_id"]: player for player in self.session.public_state()["players"]}
        self.assertEqual(players[self.host]["ping_ms"], 0)
        self.assertEqual(players[self.other.player_id]["ping_ms"], 47)
        self.session.disconnect(self.other.player_id)
        players = {player["player_id"]: player for player in self.session.public_state()["players"]}
        self.assertNotIn(self.other.player_id, players)

    def test_lobby_disconnect_removes_the_player_and_releases_their_country(self):
        self.session.select_country(self.other.player_id, "B")
        self.session.set_ready(self.other.player_id, True)

        self.session.disconnect(self.other.player_id)

        self.assertNotIn(self.other.player_id, self.session.players)
        self.assertNotIn("B", [p.country_id for p in self.session.players.values()])

    def test_server_kick_removes_guest_and_sends_a_specific_notice(self):
        server = RealtimeServer(self.session, "unused-cert", "unused-key")
        guest_connection = mock.Mock()
        server._clients[self.other.player_id] = guest_connection

        with mock.patch.object(server, "_send_message") as send:
            server.kick_player(self.host, self.other.player_id)

        self.assertNotIn(self.other.player_id, self.session.players)
        self.assertNotIn(self.other.player_id, server._clients)
        send.assert_called_once_with(guest_connection, "kicked", {
            "message": "The host removed you from the real-time lobby.",
        })
        guest_connection.close.assert_called_once_with()

    def test_server_stop_sends_an_explicit_shutdown_to_each_guest(self):
        server = RealtimeServer(self.session, "unused-cert", "unused-key")
        guest_connection = mock.Mock()
        server._clients[self.other.player_id] = guest_connection
        with mock.patch.object(server, "_send_message") as send:
            server.stop("The host ended the match.")
        send.assert_called_once_with(
            guest_connection, "shutdown", {"message": "The host ended the match."})

    def test_completed_realtime_save_loads_as_an_offline_spectator(self):
        metadata = self.session.completed_metadata()
        self.assertEqual(metadata["offline_view"], "spectator")
        player, active_players = _saved_player_view({
            "player_country": "None", "active_players": ["A", "B"],
            "realtime_match": metadata,
        })
        self.assertEqual((player, active_players), ("Spectator", []))

        # The first real-time format already existed before offline_view was
        # stored. Keep those completed saves usable too.
        legacy_player, legacy_active = _saved_player_view({
            "player_country": "None", "realtime_match": {"format": "gd5-realtime-v1"},
        })
        self.assertEqual((legacy_player, legacy_active), ("Spectator", []))

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

    def test_economy_conversions_and_claim_drafts_are_server_validated(self):
        province = {"id": 7, "owner": "B", "units": []}
        map_ref = SimpleNamespace(
            map_data={"target": province}, id_to_province={7: province},
            nation_data={
                "A": {"claims": [], "claim_queue": [], "research": {}},
                "B": {},
            })
        driver = MapRealtimeDriver(map_ref)
        preferences = {
            "type": "country_preferences", "political_drift": 0,
            "automation": {}, "conscription_slider": .4,
            "mat_to_fuel_slider": .25,
        }
        with mock.patch("data.queries.get_max_fuel_conversion", return_value=.5):
            canonical = driver.validate_draft("A", [
                preferences, {"type": "claim_draft", "province_ids": [7]},
            ])
            self.assertEqual(canonical[0]["conscription_slider"], .4)
            self.assertEqual(canonical[0]["mat_to_fuel_slider"], .25)
            self.assertEqual(canonical[1]["queue"], [
                {"prov_id": 7, "turns_left": c.CLAIM_TURN_NON_CORE}])
            with self.assertRaises(RealtimeError):
                driver.validate_draft("A", [{**preferences, "mat_to_fuel_slider": .6}])

        # A follow-up draft can retain an accepted claim but cannot forge a
        # shorter countdown to make it complete early.
        map_ref.nation_data["A"]["claim_queue"] = [{"prov_id": 7, "turns_left": 3}]
        retained = driver.validate_draft("A", [{"type": "claim_draft", "province_ids": [7]}])
        self.assertEqual(retained[0]["queue"], [{"prov_id": 7, "turns_left": 3}])

    def test_collects_economy_conversion_and_claim_choices(self):
        map_ref = SimpleNamespace(
            map_data={}, nation_data={"A": {
                "conscription_slider": .6, "mat_to_fuel_slider": .2,
                "claim_queue": [{"prov_id": 4, "turns_left": 5}],
                "research_queue": [],
            }})
        commands = collect_map_commands(map_ref, "A")
        preferences = next(command for command in commands
                           if command["type"] == "country_preferences")
        claim_draft = next(command for command in commands if command["type"] == "claim_draft")
        self.assertEqual((preferences["conscription_slider"], preferences["mat_to_fuel_slider"]), (.6, .2))
        self.assertEqual(claim_draft["province_ids"], [4])

    def test_diplomacy_draft_is_collected_and_cannot_replace_inflight_offer(self):
        map_ref = SimpleNamespace(
            map_data={}, id_to_province={}, nation_colors={},
            nation_data={
                "A": {"name": "A", "color": [1, 2, 3], "research_queue": [],
                      "pending_diplomacy": {
                          "B": {"action": "REQ_MILITARY_ACCESS", "turns": 0,
                                "timer": 0, "message": "Please allow passage."},
                          "C": {"action": "TRADE", "turns": 2, "timer": 0,
                                "message": "Already sent."},
                      }, "diplo_responses": {}, "draft_lists": {}},
                "B": {}, "C": {},
            })
        commands = collect_map_commands(map_ref, "A")
        diplomacy = next(command for command in commands if command["type"] == "country_diplomacy")
        self.assertEqual(set(diplomacy["pending"]), {"B"})
        driver = MapRealtimeDriver(map_ref)
        canonical = driver.validate_draft("A", [diplomacy])[0]
        # The current request is canonicalized for end-of-turn processing;
        # the already-sent proposal was omitted from the client command.
        self.assertEqual(canonical["pending"]["B"]["action"], "REQ_MILITARY_ACCESS")
        with self.assertRaises(RealtimeError):
            driver.validate_draft("A", [{"type": "country_diplomacy", "pending": {
                "B": {"action": "NOT_A_REAL_ACTION", "timer": 0, "message": ""}},
                "responses": {}, "draft_lists": {}}])

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
                self.assertIsNone(client.socket.gettimeout())
                client.send("join", {"name": "Network Guest", "password": ""})
                deadline = time.monotonic() + 5.0
                events = []
                while time.monotonic() < deadline:
                    events.extend(client.poll())
                    if client.player_id:
                        break
                    time.sleep(.01)
                self.assertIsNotNone(client.player_id, (events, client.disconnect_message))
                # The host makes this change locally rather than through a
                # client request. A joined remote player must still receive
                # the authoritative broadcast immediately.
                client.poll()
                self.session.select_country(self.host, "A")
                state_events = []
                while time.monotonic() < deadline:
                    state_events.extend(client.poll())
                    if any(event.get("type") == "state" and any(
                            player.get("player_id") == self.host and player.get("country_id") == "A"
                            for player in event.get("payload", {}).get("players", []))
                           for event in state_events):
                        break
                    time.sleep(.01)
                self.assertTrue(any(event.get("type") == "state" and any(
                                player.get("player_id") == self.host and player.get("country_id") == "A"
                                for player in event.get("payload", {}).get("players", []))
                            for event in state_events), (state_events, client.disconnect_message))
                # A concurrent selection race must reject the losing request
                # without treating the player as a malformed/disconnected client.
                client.send("select_country", {"country_id": "A"})
                rejected = []
                while time.monotonic() < deadline:
                    rejected.extend(client.poll())
                    if any(event.get("type") == "error" for event in rejected):
                        break
                    time.sleep(.01)
                self.assertTrue(any(event.get("type") == "error" and
                                    "selected by another player" in event.get("payload", {}).get("message", "")
                                    for event in rejected), (rejected, client.disconnect_message))
                self.assertIsNotNone(client.socket)
                client.send("select_country", {"country_id": "B"})
                chosen = []
                while time.monotonic() < deadline:
                    chosen.extend(client.poll())
                    if any(event.get("payload", {}).get("state") for event in chosen):
                        break
                    time.sleep(.01)
                self.assertTrue(any(any(player.get("player_id") == client.player_id and
                                        player.get("country_id") == "B"
                                        for player in event.get("payload", {}).get("state", {}).get("players", []))
                                    for event in chosen), (chosen, client.disconnect_message))
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

    def test_host_lobby_shutdown_reaches_a_joined_guest_immediately(self):
        """Ending a lobby must be a visible protocol event, not something the
        guest discovers only by attempting its next action."""
        with tempfile.TemporaryDirectory() as directory:
            certificate, key, fingerprint = create_match_certificate(directory)
            server = RealtimeServer(self.session, certificate, key)
            port = server.start(0)
            client = None
            try:
                invite = decode_invite(encode_invite("127.0.0.1", port,
                                                     self.session.session_id, fingerprint))
                client = RealtimeClient(invite)
                client.connect()
                client.send("join", {"name": "Network Guest", "password": ""})
                deadline = time.monotonic() + 5.0
                while time.monotonic() < deadline and not client.player_id:
                    client.poll()
                    time.sleep(.01)
                self.assertIsNotNone(client.player_id, client.disconnect_message)

                server.stop("The host ended the real-time lobby. You have been disconnected.")
                events = []
                while time.monotonic() < deadline:
                    events.extend(client.poll())
                    if any(event.get("type") == "shutdown" for event in events):
                        break
                    time.sleep(.01)
                self.assertTrue(any(event.get("type") == "shutdown" for event in events),
                                (events, client.disconnect_message))
            finally:
                if client:
                    client.close()
                server.stop()


class RealtimeStrategicCommandCoverageTests(unittest.TestCase):
    """Regression coverage for strategic controls that used to be local-only."""

    def make_map(self):
        home = {"id": 1, "json_key": "home", "owner": "A", "terrain": "plains",
                "neighbors": [2], "cores": ["A", "P"], "units": [{"owner": "A", "type": "Infantry"}],
                "building_queue": [], "unit_queue": [], "is_coastal": False}
        foreign = {"id": 2, "json_key": "foreign", "owner": "B", "terrain": "plains",
                   "neighbors": [1], "cores": ["B"], "units": [], "building_queue": [],
                   "unit_queue": [], "is_coastal": False}
        nations = {
            "A": {"name": "A", "color": [1, 2, 3], "materials": 1000, "manpower": 1000,
                  "fuel": 1000, "research": {}, "claims": [1], "claim_queue": [],
                  "revoke_queue": [], "return_queue": [], "puppets": ["P"],
                  "release_puppet_queue": [], "faction": "Old Pact", "is_faction_leader": True,
                  "pending_ratification": {"terms": {}}, "research_queue": []},
            "B": {"name": "B", "color": [4, 5, 6], "claims": [1], "faction": "Old Pact"},
            "P": {"name": "P", "color": [7, 8, 9], "puppet_type": c.PUPPET_TYPE_INTEGRATED,
                  "siphon_rates": {"manpower": 0, "materials": 0, "fuel": 0}},
        }
        return SimpleNamespace(map_data={"home": home, "foreign": foreign},
                               id_to_province={1: home, 2: foreign}, nation_data=nations,
                               nation_colors={"A": (1, 2, 3), "B": (4, 5, 6), "P": (7, 8, 9)},
                               scenario_settings={})

    def test_collects_empty_queues_and_unit_identity_combat_intents(self):
        map_ref = self.make_map()
        unit = map_ref.map_data["home"]["units"][0]
        unit.update({"custom_name": "First Division", "combat_stance": "RESERVE", "lane_target": "B"})
        commands = collect_map_commands(map_ref, "A")
        unit_command = next(command for command in commands if command["type"] == "unit_order")
        self.assertEqual(unit_command["custom_name"], "First Division")
        self.assertEqual(unit_command["combat_stance"], "RESERVE")
        self.assertEqual(unit_command["lane_target"], "B")
        queues = [command for command in commands if command["type"] == "province_queue"]
        self.assertEqual({command["queue"] for command in queues}, {"building_queue", "unit_queue"})
        self.assertTrue(all(command["items"] == [] for command in queues))

    def test_an_idle_complete_draft_is_accepted(self):
        map_ref = self.make_map()
        # An ordinary player has many units with no order.  This regression
        # catches validators that treat an explicit no-order intent as a dict.
        MapRealtimeDriver(map_ref).validate_draft("A", collect_map_commands(map_ref, "A"))

    def test_claim_puppet_faction_and_ratification_drafts_are_server_validated(self):
        map_ref = self.make_map()
        driver = MapRealtimeDriver(map_ref)
        appearance = {"name": "Subject", "adjective": "Subject", "leader_name": "Leader",
                      "leader_title": "Chief", "flag_data": "DEFAULT", "portrait_data": "DEFAULT",
                      "color": [9, 8, 7]}
        commands = driver.validate_draft("A", [
            {"type": "claim_draft", "province_ids": [], "revoke_ids": [1],
             "returns": [{"prov_id": 1, "recipient": "B"}]},
            {"type": "puppet_draft", "puppet_order": ["P"],
             "siphons": {"P": {"manpower": .25, "materials": .20, "fuel": .15}},
             "release_subjects": [{"core_nation": "P", "keep_cores": False}],
             "appearances": {"P": appearance}},
            {"type": "faction_rename", "name": "New Pact"},
            {"type": "ratification_response", "verdict": "RATIFY"},
        ])
        claim = next(command for command in commands if command["type"] == "claim_draft")
        self.assertEqual(claim["revokes"], [{"prov_id": 1, "turns_left": 1}])
        self.assertEqual(claim["returns"], [{"prov_id": 1, "recipient": "B", "turns_left": 1}])
        self.assertEqual(next(command for command in commands if command["type"] == "faction_rename")["name"], "New Pact")
        with self.assertRaises(RealtimeError):
            driver.validate_draft("A", [{"type": "puppet_draft", "puppet_order": ["P"],
                                          "siphons": {"B": {"manpower": 1, "materials": 1, "fuel": 1}},
                                          "release_subjects": [], "appearances": {}}])

    def test_queue_items_are_rebuilt_from_server_costs_not_client_refunds(self):
        map_ref = self.make_map()
        driver = MapRealtimeDriver(map_ref)
        forged = {"order_type": "BUILDING", "item_name": "Factory", "turns_remaining": 0,
                  "refund": {"cost_materials": -999999, "cost_manpower": -999999, "cost_fuel": -999999}}
        with mock.patch("data.queries.get_building_library", return_value={"Factory": {}}), \
             mock.patch("data.queries.get_building_required_tech", return_value=("", 0)), \
             mock.patch("data.queries.get_building_cost", return_value={"time": 3, "group": "industry",
                                                                           "cost_materials": 25,
                                                                           "cost_manpower": 5,
                                                                           "cost_fuel": 2}), \
             mock.patch("data.queries.has_core", return_value=True):
            command = driver.validate_draft("A", [{"type": "province_queue", "province_id": 1,
                                                     "queue": "building_queue", "items": [forged]}])[0]
        item = command["items"][0]
        self.assertEqual(item["turns_remaining"], 3)
        self.assertEqual(item["refund"], {"cost_materials": 25, "cost_manpower": 5, "cost_fuel": 2})

    def test_repair_cost_is_deducted_by_the_server_not_the_client_order(self):
        map_ref = self.make_map()
        map_ref.player_country = "None"
        map_ref.map_data["home"]["units"][0].update({"health": 5, "max_health": 10})
        driver = MapRealtimeDriver(map_ref)
        with mock.patch("data.queries.get_unit_library", return_value={"Infantry": {
                "cost_materials": 20, "cost_manpower": 10, "cost_fuel": 4}}), \
             mock.patch("data.queries.get_scenario_flag", return_value=False), \
             mock.patch("data.queries.is_nation_in_combat_here", return_value=False):
            command = driver.validate_draft("A", [{"type": "unit_order", "province_id": 1,
                                                     "unit_index": 0,
                                                     "order": {"type": "REPAIR", "refund": {"cost_materials": 0}},
                                                     "custom_name": None, "combat_stance": None,
                                                     "lane_target": None}])
        async def no_op(_map_ref):
            return None
        before = map_ref.nation_data["A"]["materials"]
        with mock.patch("map_logic.turn_processing.turn_processor.prepare_turn", new=no_op), \
             mock.patch("map_logic.turn_processing.turn_processor.resolve_turn_logic", new=no_op):
            driver.process_turn({"A": command})
        self.assertEqual(map_ref.nation_data["A"]["materials"], before - 10)
        self.assertNotIn("realtime_cost", map_ref.map_data["home"]["units"][0]["order"])

    def test_volunteer_reservations_require_a_matching_authoritative_offer(self):
        map_ref = self.make_map()
        map_ref.nation_data["B"]["at_war_with"] = ["C"]
        map_ref.nation_data["C"] = {"name": "C", "at_war_with": ["B"]}
        driver = MapRealtimeDriver(map_ref)
        offer = {"type": "country_diplomacy", "pending": {
            "B": {"action": "SEND_VOLUNTEERS", "timer": 0, "message": "We can help."}},
            "responses": {}, "draft_lists": {}}
        reservation = {"type": "volunteer_draft", "target": "B",
                       "units": [{"province_id": 1, "unit_index": 0}]}
        commands = driver.validate_draft("A", [offer, reservation])
        self.assertEqual(next(command for command in commands if command["type"] == "volunteer_draft")["units"],
                         [{"province_id": 1, "unit_index": 0}])
        with self.assertRaises(RealtimeError):
            driver.validate_draft("A", [offer])


if __name__ == "__main__":
    unittest.main()
