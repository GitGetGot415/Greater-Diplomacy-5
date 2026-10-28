"""A deliberately small, opaque relay for Greater Diplomacy 5 matches.

This module is copied verbatim into a temporary VPS by the desktop client.  It
must therefore remain standard-library only and must not import the game.  It
does not decrypt or understand the real-time game protocol: it authenticates a
short-lived room, pairs an outbound host connection with an outbound player
connection, then copies bytes in both directions.

Run it on a relay machine with ``python3 realtime_relay_service.py``.  The
provisioner uses port 443 so ordinary outbound home-network traffic works.
"""

from __future__ import annotations

import json
import secrets
import socket
import struct
import threading
import time


MAX_CONTROL_BYTES = 16 * 1024
ROOM_IDLE_SECONDS = 60 * 60 * 12


def _receive_exactly(connection, count):
    chunks = []
    while count:
        part = connection.recv(count)
        if not part:
            raise ConnectionError("Connection closed.")
        chunks.append(part)
        count -= len(part)
    return b"".join(chunks)


def read_control(connection):
    size = struct.unpack("!I", _receive_exactly(connection, 4))[0]
    if not 2 <= size <= MAX_CONTROL_BYTES:
        raise ValueError("Invalid relay control frame.")
    value = json.loads(_receive_exactly(connection, size).decode("utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("kind"), str):
        raise ValueError("Invalid relay control request.")
    return value


def send_control(connection, value):
    raw = json.dumps(value, separators=(",", ":")).encode("utf-8")
    if len(raw) > MAX_CONTROL_BYTES:
        raise ValueError("Relay control response is too large.")
    connection.sendall(struct.pack("!I", len(raw)) + raw)


def _copy(source, destination):
    try:
        while True:
            data = source.recv(65536)
            if not data:
                break
            destination.sendall(data)
    except OSError:
        pass
    finally:
        for connection in (source, destination):
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                connection.close()
            except OSError:
                pass


def bridge(first, second):
    """Pipe two opaque streams until either side leaves."""
    threading.Thread(target=_copy, args=(first, second), daemon=True).start()
    threading.Thread(target=_copy, args=(second, first), daemon=True).start()


class Relay:
    def __init__(self):
        self.rooms = {}
        self.pending = {}
        self.lock = threading.RLock()

    def _valid_text(self, value):
        return isinstance(value, str) and 8 <= len(value) <= 128

    def serve(self, connection):
        try:
            request = read_control(connection)
            kind = request["kind"]
            if kind == "host_register":
                self._host_register(connection, request)
                return  # The control socket is owned by its reader.
            if kind == "client_connect":
                self._client_connect(connection, request)
                return  # Held open until a host peer arrives.
            if kind == "host_peer":
                self._host_peer(connection, request)
                return  # bridge now owns the socket.
            send_control(connection, {"ok": False, "error": "Unknown relay request."})
        except (ConnectionError, OSError, ValueError, json.JSONDecodeError):
            try:
                connection.close()
            except OSError:
                pass

    def _host_register(self, connection, request):
        session, host_key, join_key = request.get("session"), request.get("host_key"), request.get("join_key")
        if not all(self._valid_text(value) for value in (session, host_key, join_key)):
            send_control(connection, {"ok": False, "error": "Invalid room registration."})
            connection.close(); return
        with self.lock:
            previous = self.rooms.get(session)
            if previous and previous["host_key"] != host_key:
                send_control(connection, {"ok": False, "error": "Room is already registered."})
                connection.close(); return
            self.rooms[session] = {"host_key": host_key, "join_key": join_key,
                                   "control": connection, "send_lock": threading.Lock(),
                                   "last_seen": time.monotonic()}
        send_control(connection, {"ok": True, "type": "registered"})
        try:
            while True:
                # A tiny host heartbeat detects a dropped control connection.
                message = read_control(connection)
                if message.get("kind") != "heartbeat":
                    raise ValueError("Unexpected host control message.")
                with self.lock:
                    room = self.rooms.get(session)
                    if room and room["control"] is connection:
                        room["last_seen"] = time.monotonic()
                        send_lock = room["send_lock"]
                    else:
                        send_lock = None
                if send_lock is None:
                    raise ConnectionError("Relay room was replaced.")
                with send_lock:
                    send_control(connection, {"ok": True, "type": "heartbeat"})
        except (ConnectionError, OSError, ValueError, json.JSONDecodeError):
            with self.lock:
                room = self.rooms.get(session)
                if room and room["control"] is connection:
                    self.rooms.pop(session, None)
        finally:
            try: connection.close()
            except OSError: pass

    def _client_connect(self, connection, request):
        session, join_key = request.get("session"), request.get("join_key")
        if not all(self._valid_text(value) for value in (session, join_key)):
            send_control(connection, {"ok": False, "error": "Invalid relay invite."})
            connection.close(); return
        with self.lock:
            room = self.rooms.get(session)
            if (not room or room["join_key"] != join_key
                    or time.monotonic() - room["last_seen"] > ROOM_IDLE_SECONDS):
                send_control(connection, {"ok": False, "error": "The host relay room is not available."})
                connection.close(); return
            peer_id = secrets.token_urlsafe(18)
            self.pending[(session, peer_id)] = connection
            # Finish the relay control exchange before notifying the host.  As
            # soon as a host peer is paired, this socket becomes opaque inner
            # TLS bytes and no further relay frame may be written to it.
            send_control(connection, {"ok": True, "type": "waiting"})
            try:
                with room["send_lock"]:
                    send_control(room["control"], {"type": "peer", "peer_id": peer_id})
            except OSError:
                self.pending.pop((session, peer_id), None)
                connection.close(); return

    def _host_peer(self, connection, request):
        session, host_key, peer_id = request.get("session"), request.get("host_key"), request.get("peer_id")
        if not all(self._valid_text(value) for value in (session, host_key, peer_id)):
            send_control(connection, {"ok": False, "error": "Invalid relay peer request."})
            connection.close(); return
        with self.lock:
            room = self.rooms.get(session)
            client = self.pending.pop((session, peer_id), None)
            if not room or room["host_key"] != host_key or client is None:
                send_control(connection, {"ok": False, "error": "Relay peer is no longer waiting."})
                connection.close(); return
        send_control(connection, {"ok": True, "type": "paired"})
        # The setup handshake has a timeout; an idle Diplomacy turn may last
        # hours, so the opaque game stream itself must not inherit it.
        connection.settimeout(None)
        client.settimeout(None)
        bridge(connection, client)


def main():
    relay = Relay()
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("0.0.0.0", 443))
    listener.listen(64)
    while True:
        connection, _ = listener.accept()
        connection.settimeout(60)
        threading.Thread(target=relay.serve, args=(connection,), daemon=True).start()


if __name__ == "__main__":
    main()
