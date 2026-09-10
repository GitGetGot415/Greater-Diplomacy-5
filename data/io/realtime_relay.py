"""Temporary DigitalOcean relay provisioning and opaque relay transports.

The relay is intentionally separate from the game server.  A host and every
player make outbound TCP connections to it; after a short room handshake the
relay only copies bytes.  The existing TLS session is then negotiated *inside*
that tunnel and remains pinned by the match invite.

DigitalOcean is the first supported provider because its public API supports
small, short-lived droplets with cloud-init.  Provider tokens stay in memory
only; completed/aborted match saves and invite codes never contain them.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import queue
import secrets
import socket
import struct
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

from data.io.realtime_multiplayer import PROTOCOL_VERSION, RealtimeError
from data.platform import IS_WEB


DIGITALOCEAN_API = "https://api.digitalocean.com/v2"
DEFAULT_RELAY_REGION = "nyc1"
DEFAULT_RELAY_SIZE = "s-1vcpu-512mb-10gb"
DEFAULT_RELAY_PORT = 443
MAX_CONTROL_BYTES = 16 * 1024


def _receive_exactly(connection: socket.socket, count: int) -> bytes:
    parts: list[bytes] = []
    while count:
        value = connection.recv(count)
        if not value:
            raise ConnectionError("Relay connection closed.")
        parts.append(value)
        count -= len(value)
    return b"".join(parts)


def _read_control(connection: socket.socket) -> dict[str, Any]:
    size = struct.unpack("!I", _receive_exactly(connection, 4))[0]
    if not 2 <= size <= MAX_CONTROL_BYTES:
        raise RealtimeError("Invalid relay control response.")
    try:
        value = json.loads(_receive_exactly(connection, size).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RealtimeError("Invalid relay control response.") from exc
    if not isinstance(value, dict):
        raise RealtimeError("Invalid relay control response.")
    return value


def _send_control(connection: socket.socket, value: dict[str, Any]) -> None:
    raw = json.dumps(value, separators=(",", ":")).encode("utf-8")
    if len(raw) > MAX_CONTROL_BYTES:
        raise RealtimeError("Relay control request is too large.")
    connection.sendall(struct.pack("!I", len(raw)) + raw)


def _expect_ok(connection: socket.socket) -> dict[str, Any]:
    response = _read_control(connection)
    if response.get("ok") is not True:
        raise RealtimeError(str(response.get("error") or "Relay rejected the connection."))
    return response


def relay_invite(relay_host: str, session_id: str, fingerprint: str, join_key: str,
                 relay_port: int = DEFAULT_RELAY_PORT) -> dict[str, Any]:
    """Build the public, non-provider-secret part of a relay invite."""
    return {"v": PROTOCOL_VERSION, "transport": "relay", "relay_host": relay_host,
            "relay_port": int(relay_port), "session": session_id,
            "fingerprint": fingerprint, "join_key": join_key}


def is_relay_invite(invite: dict[str, Any]) -> bool:
    return isinstance(invite, dict) and invite.get("transport") == "relay"


def validate_relay_invite(invite: dict[str, Any]) -> dict[str, Any]:
    if (not is_relay_invite(invite) or invite.get("v") != PROTOCOL_VERSION
            or not isinstance(invite.get("relay_host"), str) or not invite["relay_host"]
            or not isinstance(invite.get("relay_port"), int)
            or not 1 <= invite["relay_port"] <= 65535
            or not isinstance(invite.get("session"), str)
            or not isinstance(invite.get("fingerprint"), str)
            or not isinstance(invite.get("join_key"), str)
            or not 16 <= len(invite["join_key"]) <= 128):
        raise RealtimeError("Unsupported or incomplete relay invite code.")
    return {key: invite[key] for key in ("v", "transport", "relay_host", "relay_port",
                                          "session", "fingerprint", "join_key")}


def connect_relay_client(invite: dict[str, Any], timeout: float) -> socket.socket:
    """Return a paired byte stream, ready for the game's inner TLS handshake."""
    invite = validate_relay_invite(invite)
    connection = socket.create_connection((invite["relay_host"], invite["relay_port"]), timeout)
    try:
        _send_control(connection, {"kind": "client_connect", "session": invite["session"],
                                   "join_key": invite["join_key"]})
        _expect_ok(connection)
        # The next bytes are the certificate-pinned game TLS handshake.
        connection.settimeout(timeout)
        return connection
    except Exception:
        connection.close()
        raise


class RelayHostTransport:
    """Keeps a host room available and turns relay peers into server sockets."""
    def __init__(self, relay_host: str, session_id: str, host_key: str, join_key: str,
                 relay_port: int = DEFAULT_RELAY_PORT, timeout: float = 12.0):
        self.relay_host, self.relay_port = relay_host, relay_port
        self.session_id, self.host_key, self.join_key = session_id, host_key, join_key
        self.timeout = timeout
        self._control: socket.socket | None = None
        self._stopped = threading.Event()
        self._server_connection: Callable[[socket.socket], None] | None = None
        self._thread: threading.Thread | None = None

    def start(self, server_connection: Callable[[socket.socket], None]) -> None:
        if self._thread is not None:
            return
        if IS_WEB:
            raise RealtimeError("Temporary relays are available on desktop builds only.")
        connection = socket.create_connection((self.relay_host, self.relay_port), self.timeout)
        try:
            _send_control(connection, {"kind": "host_register", "session": self.session_id,
                                       "host_key": self.host_key, "join_key": self.join_key})
            _expect_ok(connection)
        except Exception:
            connection.close()
            raise
        self._control = connection
        self._server_connection = server_connection
        self._thread = threading.Thread(target=self._control_loop, name="gd5-relay-host", daemon=True)
        self._thread.start()

    @property
    def connected(self) -> bool:
        return self._control is not None and not self._stopped.is_set()

    def stop(self) -> None:
        self._stopped.set()
        if self._control:
            try: self._control.close()
            except OSError: pass
            self._control = None

    def _control_loop(self) -> None:
        assert self._control is not None
        control = self._control
        last_heartbeat = 0.0
        try:
            control.settimeout(1.0)
            while not self._stopped.is_set():
                now = time.monotonic()
                if now - last_heartbeat >= 15.0:
                    _send_control(control, {"kind": "heartbeat"})
                    last_heartbeat = now
                try:
                    message = _read_control(control)
                except socket.timeout:
                    continue
                if message.get("type") == "peer" and isinstance(message.get("peer_id"), str):
                    threading.Thread(target=self._attach_peer, args=(message["peer_id"],), daemon=True).start()
        except (ConnectionError, OSError, RealtimeError):
            pass
        finally:
            self.stop()

    def _attach_peer(self, peer_id: str) -> None:
        if self._stopped.is_set() or self._server_connection is None:
            return
        try:
            connection = socket.create_connection((self.relay_host, self.relay_port), self.timeout)
            _send_control(connection, {"kind": "host_peer", "session": self.session_id,
                                       "host_key": self.host_key, "peer_id": peer_id})
            _expect_ok(connection)
            connection.settimeout(None)
            self._server_connection(connection)
        except (ConnectionError, OSError, RealtimeError):
            try: connection.close()
            except (OSError, UnboundLocalError): pass


def relay_service_source() -> str:
    """Read the standard-library relay program shipped with this desktop build."""
    path = Path(__file__).with_name("realtime_relay_service.py")
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RealtimeError("The packaged relay service file is missing.") from exc


def relay_cloud_init() -> str:
    """Cloud-init payload that installs and starts one self-contained relay."""
    encoded = base64.b64encode(relay_service_source().encode("utf-8")).decode("ascii")
    return """#cloud-config
bootcmd:
  - mkdir -p /opt/gd5-relay
write_files:
  - path: /opt/gd5-relay/realtime_relay_service.py
    permissions: '0755'
    encoding: b64
    content: {source}
  - path: /etc/systemd/system/gd5-relay.service
    permissions: '0644'
    content: |
      [Unit]
      Description=Greater Diplomacy 5 temporary relay
      After=network-online.target
      Wants=network-online.target
      [Service]
      Type=simple
      ExecStart=/usr/bin/python3 /opt/gd5-relay/realtime_relay_service.py
      Restart=always
      RestartSec=2
      [Install]
      WantedBy=multi-user.target
runcmd:
  - systemctl daemon-reload
  - systemctl enable --now gd5-relay.service
""".format(source=encoded)


def _api_request(token: str, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    raw = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(DIGITALOCEAN_API + path, data=raw, method=method,
                                     headers={"Authorization": f"Bearer {token}",
                                              "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read(2 * 1024 * 1024)
    except urllib.error.HTTPError as exc:
        try:
            message = json.loads(exc.read().decode("utf-8")).get("message", "")
        except (UnicodeDecodeError, json.JSONDecodeError):
            message = ""
        raise RealtimeError(f"DigitalOcean API rejected the request ({exc.code}): {message or exc.reason}") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise RealtimeError(f"Could not contact DigitalOcean: {exc}") from exc
    try:
        value = json.loads(body.decode("utf-8")) if body else {}
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RealtimeError("DigitalOcean returned an invalid API response.") from exc
    if not isinstance(value, dict):
        raise RealtimeError("DigitalOcean returned an invalid API response.")
    return value


@dataclass(frozen=True)
class TemporaryRelay:
    droplet_id: int
    address: str
    region: str
    size: str


class DigitalOceanRelayTask:
    """Create one short-lived relay without freezing pygame's event loop."""
    def __init__(self, token: str, session_id: str, region: str = DEFAULT_RELAY_REGION,
                 size: str = DEFAULT_RELAY_SIZE):
        self.token, self.session_id, self.region, self.size = token.strip(), session_id, region.strip(), size.strip()
        self.result: TemporaryRelay | None = None
        self.error: str | None = None
        self._done = threading.Event()
        self._cancelled = threading.Event()
        self._droplet_id: int | None = None

    def start(self) -> None:
        if IS_WEB:
            self.error = "Temporary relays are available on desktop builds only."
            self._done.set(); return
        threading.Thread(target=self._run, name="gd5-create-relay", daemon=True).start()

    def done(self) -> bool:
        return self._done.is_set()

    def cancel_and_destroy(self) -> None:
        self._cancelled.set()
        if self._droplet_id:
            try: _api_request(self.token, "DELETE", f"/droplets/{self._droplet_id}")
            except RealtimeError: pass

    def _run(self) -> None:
        try:
            if len(self.token) < 20:
                raise RealtimeError("Enter a valid DigitalOcean personal access token.")
            payload = {"name": "gd5-relay-" + self.session_id[:10], "region": self.region,
                       "size": self.size, "image": "ubuntu-24-04-x64", "backups": False,
                       "ipv6": False, "monitoring": False, "tags": ["gd5-temporary-relay"],
                       "user_data": relay_cloud_init()}
            created = _api_request(self.token, "POST", "/droplets", payload).get("droplet", {})
            if not isinstance(created, dict) or not isinstance(created.get("id"), int):
                raise RealtimeError("DigitalOcean did not return the temporary relay ID.")
            self._droplet_id = created["id"]
            deadline = time.monotonic() + 180.0
            while time.monotonic() < deadline:
                if self._cancelled.is_set():
                    self.cancel_and_destroy(); return
                data = _api_request(self.token, "GET", f"/droplets/{self._droplet_id}")
                droplet = data.get("droplet", {})
                networks = droplet.get("networks", {}) if isinstance(droplet, dict) else {}
                public = networks.get("v4", []) if isinstance(networks, dict) else []
                address = next((entry.get("ip_address") for entry in public if isinstance(entry, dict)
                                and entry.get("type") == "public" and isinstance(entry.get("ip_address"), str)), None)
                if address:
                    try:
                        probe = socket.create_connection((address, DEFAULT_RELAY_PORT), timeout=2)
                        probe.close()
                        self.result = TemporaryRelay(self._droplet_id, address, self.region, self.size)
                        return
                    except OSError:
                        pass
                time.sleep(3)
            raise RealtimeError("The temporary relay did not become ready within three minutes.")
        except RealtimeError as exc:
            self.error = str(exc)
            if self._droplet_id:
                try: _api_request(self.token, "DELETE", f"/droplets/{self._droplet_id}")
                except RealtimeError: pass
        finally:
            self._done.set()


def destroy_temporary_relay(token: str, droplet_id: int) -> None:
    """Delete the VPS, ending its Droplet allocation charge."""
    if not isinstance(droplet_id, int) or droplet_id <= 0:
        raise RealtimeError("Invalid temporary relay identifier.")
    _api_request(token, "DELETE", f"/droplets/{droplet_id}")
