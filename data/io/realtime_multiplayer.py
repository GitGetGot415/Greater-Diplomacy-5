"""Authoritative desktop real-time multiplayer primitives.

Tournament multiplayer intentionally remains in :mod:`multiplayer_io`.  This
module uses a small, versioned TLS protocol and has no file-format overlap with
the tournament system.
"""

from __future__ import annotations

import base64
import copy
import asyncio
import hashlib
import json
import os
import queue
import secrets
import socket
import ssl
import struct
import tempfile
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from types import SimpleNamespace
from pathlib import Path
from typing import Any, Callable

import data.constants as c
from data.platform import IS_WEB


PROTOCOL_VERSION = 1
DEFAULT_PORT = 38475
DEFAULT_MAX_TURNS = 20
DEFAULT_TURN_MINUTES = 10
# Real-time match setup limits. Keep these together so a host/modder can tune
# the lobby without hunting through UI and validation code. The UI imports the
# same names, so a changed limit is enforced and displayed consistently.
MIN_PLAYER_CAPACITY = 1
MAX_PLAYER_CAPACITY = 500
MIN_MATCH_TURNS = 1
MAX_MATCH_TURNS = 240
MIN_TURN_MINUTES = 1
MAX_TURN_MINUTES = 240
MIN_SERVER_PORT = 1024
MAX_SERVER_PORT = 65535
# Initial map bundles include four PNGs. Keep a firm bound while allowing the
# large historical maps to join without fragile ad-hoc chunking.
MAX_FRAME_BYTES = 64 * 1024 * 1024
MAX_NAME_LENGTH = 24


def default_advertised_address() -> str:
    """Return the local IPv4 address other devices can usually reach.

    A UDP connect selects the address for the machine's normal outbound route
    without sending application data.  This is a better multiplayer default
    than ``127.0.0.1``, which only works when the client is on the host itself.
    Hosts can still replace this with a public IP or DNS name for WAN play.
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("8.8.8.8", 80))
        address = probe.getsockname()[0]
        if address and address != "0.0.0.0":
            return address
    except OSError:
        pass
    finally:
        probe.close()
    return "127.0.0.1"


class RealtimeError(ValueError):
    """A client-safe real-time multiplayer rejection."""


def sanitize_display_name(value: Any) -> str:
    """Return a safe display name or raise a useful rejection.

    Names are normalized so visually identical Unicode spellings cannot evade
    the lobby's case-insensitive uniqueness rule.  Controls are forbidden
    rather than silently rendered into a different name.
    """
    if not isinstance(value, str):
        raise RealtimeError("Display name must be text.")
    normalized = unicodedata.normalize("NFKC", value)
    if any(unicodedata.category(ch).startswith("C") for ch in normalized):
        raise RealtimeError("Display names cannot contain control characters.")
    name = normalized.strip()
    if not name:
        raise RealtimeError("Display name cannot be empty.")
    if len(name) > MAX_NAME_LENGTH:
        raise RealtimeError(f"Display names are limited to {MAX_NAME_LENGTH} characters.")
    return name


def _name_key(name: str) -> str:
    return unicodedata.normalize("NFKC", name).casefold()


def _password_hash(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000).hex()


def encode_invite(address: str, port: int, session_id: str, fingerprint: str) -> str:
    """Encode shareable, non-secret connection information."""
    payload = {"v": PROTOCOL_VERSION, "host": address, "port": int(port),
               "session": session_id, "fingerprint": fingerprint}
    encoded = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode()
    return "gd5rt:" + encoded.rstrip("=")


def encode_relay_invite(relay_host: str, relay_port: int, session_id: str,
                        fingerprint: str, join_key: str) -> str:
    """Encode an invite that reaches the authoritative host through a relay.

    ``join_key`` authorizes a connection to one short-lived relay room.  It is
    not a provider credential and does not replace the optional lobby password
    or the inner certificate pin.
    """
    from data.io.realtime_relay import relay_invite
    payload = relay_invite(relay_host, session_id, fingerprint, join_key, relay_port)
    encoded = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode()
    return "gd5rt:" + encoded.rstrip("=")


def decode_invite(value: str) -> dict[str, Any]:
    try:
        raw = value.strip()
        if raw.startswith("gd5rt:"):
            raw = raw[6:]
        raw += "=" * (-len(raw) % 4)
        data = json.loads(base64.urlsafe_b64decode(raw.encode()).decode("utf-8"))
    except Exception as exc:
        raise RealtimeError("Invalid real-time invite code.") from exc
    if isinstance(data, dict) and data.get("transport") == "relay":
        from data.io.realtime_relay import validate_relay_invite
        return validate_relay_invite(data)
    if (not isinstance(data, dict) or data.get("v") != PROTOCOL_VERSION
            or not isinstance(data.get("host"), str) or not data["host"]
            or not isinstance(data.get("port"), int) or not 1 <= data["port"] <= 65535
            or not isinstance(data.get("session"), str)
            or not isinstance(data.get("fingerprint"), str)):
        raise RealtimeError("Unsupported or incomplete invite code.")
    return data


def persist_reconnect_token(invite: dict[str, Any], token: str, display_name: str) -> str:
    """Keep a desktop reconnect token locally without placing it in saves.

    Tokens are bearer credentials; the UI also shows the token so a player can
    keep an independent copy if this local file is removed.
    """
    if IS_WEB:
        return ""
    from data import constants as c
    directory = Path(c.SAVES_DIR)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / ".gd5_realtime_reconnect.json"
    try:
        records = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        if not isinstance(records, dict): records = {}
        record = {"token": token, "name": display_name, "fingerprint": invite["fingerprint"]}
        if invite.get("transport") == "relay":
            record.update({"transport": "relay", "relay_host": invite["relay_host"],
                           "relay_port": invite["relay_port"], "join_key": invite["join_key"]})
        else:
            record.update({"host": invite["host"], "port": invite["port"]})
        records[invite["session"]] = record
        path.write_text(json.dumps(records, indent=2), encoding="utf-8")
    except OSError:
        return ""
    return str(path)


def load_reconnect_token(invite: dict[str, Any]) -> str:
    """Return this computer's saved reconnect token for the exact match invite."""
    if IS_WEB or not isinstance(invite, dict):
        return ""
    session_id, fingerprint = invite.get("session"), invite.get("fingerprint")
    if not isinstance(session_id, str) or not isinstance(fingerprint, str):
        return ""
    from data import constants as c
    path = Path(c.SAVES_DIR) / ".gd5_realtime_reconnect.json"
    try:
        records = json.loads(path.read_text(encoding="utf-8"))
        record = records.get(session_id, {}) if isinstance(records, dict) else {}
        token = record.get("token") if isinstance(record, dict) else ""
        if (isinstance(token, str) and token
                and secrets.compare_digest(str(record.get("fingerprint", "")).lower(), fingerprint.lower())):
            return token
    except (OSError, json.JSONDecodeError, TypeError):
        pass
    return ""


def encode_message(message_type: str, session_id: str, payload: dict[str, Any] | None = None,
                   request_id: str | None = None) -> bytes:
    body = {"version": PROTOCOL_VERSION, "type": message_type,
            "session_id": session_id, "request_id": request_id or secrets.token_hex(8),
            "payload": payload or {}}
    raw = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(raw) > MAX_FRAME_BYTES:
        raise RealtimeError("Network message is too large.")
    return struct.pack("!I", len(raw)) + raw


def read_message(sock: socket.socket) -> dict[str, Any]:
    """Read exactly one bounded protocol frame."""
    def receive_exactly(count: int) -> bytes:
        parts: list[bytes] = []
        remaining = count
        while remaining:
            chunk = sock.recv(remaining)
            if not chunk:
                raise ConnectionError("Connection closed.")
            parts.append(chunk)
            remaining -= len(chunk)
        return b"".join(parts)

    size = struct.unpack("!I", receive_exactly(4))[0]
    if not 2 <= size <= MAX_FRAME_BYTES:
        raise RealtimeError("Invalid network message size.")
    try:
        message = json.loads(receive_exactly(size).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RealtimeError("Invalid network message.") from exc
    if (not isinstance(message, dict) or message.get("version") != PROTOCOL_VERSION
            or not isinstance(message.get("type"), str)
            or not isinstance(message.get("session_id"), str)
            or not isinstance(message.get("payload"), dict)):
        raise RealtimeError("Incompatible network message.")
    return message


@dataclass
class RealtimeConfig:
    scenario_id: str
    scenario_settings: dict[str, Any]
    max_players: int = 4
    max_turns: int = DEFAULT_MAX_TURNS
    turn_minutes: int = DEFAULT_TURN_MINUTES
    advertised_address: str = "127.0.0.1"
    port: int = DEFAULT_PORT

    def validate(self, country_count: int) -> None:
        if (not isinstance(self.max_players, int)
                or not MIN_PLAYER_CAPACITY <= self.max_players <= min(MAX_PLAYER_CAPACITY, country_count)):
            raise RealtimeError(
                f"Player capacity must be between {MIN_PLAYER_CAPACITY} and "
                f"{min(MAX_PLAYER_CAPACITY, country_count)} for this scenario.")
        if not isinstance(self.max_turns, int) or not MIN_MATCH_TURNS <= self.max_turns <= MAX_MATCH_TURNS:
            raise RealtimeError(f"Maximum turns must be between {MIN_MATCH_TURNS} and {MAX_MATCH_TURNS}.")
        if not isinstance(self.turn_minutes, int) or not MIN_TURN_MINUTES <= self.turn_minutes <= MAX_TURN_MINUTES:
            raise RealtimeError(f"Turn time must be between {MIN_TURN_MINUTES} and {MAX_TURN_MINUTES} minutes.")
        if not isinstance(self.port, int) or not MIN_SERVER_PORT <= self.port <= MAX_SERVER_PORT:
            raise RealtimeError(f"Port must be between {MIN_SERVER_PORT} and {MAX_SERVER_PORT}.")


@dataclass
class Player:
    player_id: str
    name: str
    reconnect_token: str
    country_id: str | None = None
    ready: bool = False
    connected: bool = True
    submitted: bool = False
    eliminated: bool = False
    ping_ms: int | None = None
    draft: list[dict[str, Any]] = field(default_factory=list)


class RealtimeSession:
    """Thread-safe authoritative lobby and timed-turn state machine.

    ``driver`` is intentionally narrow and can be a real map adapter or a
    lightweight test double.  It owns game-specific command validation and
    processing; this class owns identity, timing, submission, and atomicity.
    """
    def __init__(self, config: RealtimeConfig, countries: list[str], host_name: str,
                 driver: Any, password: str = "", clock: Callable[[], float] = time.monotonic):
        self.countries = list(dict.fromkeys(countries))
        if not self.countries:
            raise RealtimeError("The selected scenario has no playable countries.")
        config.validate(len(self.countries))
        self.config = config
        self.driver = driver
        self.clock = clock
        self.lock = threading.RLock()
        self.session_id = secrets.token_hex(16)
        self.phase = "LOBBY"
        self.turn_number = 1
        self.deadline: float | None = None
        self.deadline_epoch: float | None = None
        self.processing_epoch = 0
        self._processing = False
        self._end_after_processing: str | None = None
        self.game_over_reason: str | None = None
        self.listeners: list[Callable[[dict[str, Any]], None]] = []
        # Lobby departures do not occupy an on-screen slot, country, or name,
        # but retain their authenticated identity long enough for an explicit
        # reconnect.  This store is deliberately not included in public state.
        self._lobby_reconnects: dict[str, Player] = {}
        self._password_salt = secrets.token_bytes(16)
        self._password_digest = _password_hash(password, self._password_salt) if password else None
        self.host_id = self._new_player(host_name).player_id
        # The host's game client shares the authoritative local process; it
        # has no network hop to measure.
        self.players[self.host_id].ping_ms = 0

    def _new_player(self, name: str) -> Player:
        name = sanitize_display_name(name)
        self._assert_name_available(name)
        player = Player(secrets.token_hex(12), name, secrets.token_urlsafe(32))
        if not hasattr(self, "players"):
            self.players: dict[str, Player] = {}
        self.players[player.player_id] = player
        return player

    def _assert_name_available(self, name: str, except_id: str | None = None) -> None:
        wanted = _name_key(name)
        for player in getattr(self, "players", {}).values():
            if player.player_id != except_id and _name_key(player.name) == wanted:
                raise RealtimeError("That display name is already in this lobby.")

    def add_listener(self, listener: Callable[[dict[str, Any]], None]) -> None:
        self.listeners.append(listener)

    def _broadcast(self) -> None:
        state = self.public_state()
        for listener in list(self.listeners):
            try:
                listener(state)
            except Exception:
                pass

    def join(self, name: str, password: str = "") -> Player:
        with self.lock:
            if self.phase != "LOBBY":
                raise RealtimeError("This game has already started.")
            if len(self.players) >= self.config.max_players:
                raise RealtimeError("The lobby is full.")
            if self._password_digest is not None and _password_hash(password, self._password_salt) != self._password_digest:
                raise RealtimeError("Incorrect lobby password.")
            player = self._new_player(name)
            self._broadcast()
            return copy.copy(player)

    def reconnect(self, token: str) -> Player:
        with self.lock:
            for player in self.players.values():
                if secrets.compare_digest(player.reconnect_token, str(token)):
                    player.connected = True
                    if player.player_id != self.host_id:
                        player.ping_ms = None
                    self._broadcast()
                    return copy.copy(player)

            # Before the game starts, a departed player is hidden from the
            # lobby and frees their country.  Restore that identity only on
            # explicit token authentication, leaving it unready and without a
            # country if another player claimed it while they were away.
            player = self._lobby_reconnects.get(str(token))
            if player is not None:
                if len(self.players) >= self.config.max_players:
                    raise RealtimeError("The lobby is full.")
                self._assert_name_available(player.name)
                if any(p.country_id == player.country_id for p in self.players.values()):
                    player.country_id = None
                player.ready = False
                player.connected = True
                player.ping_ms = None
                self.players[player.player_id] = player
                del self._lobby_reconnects[str(token)]
                self._broadcast()
                return copy.copy(player)
        raise RealtimeError("Invalid reconnect token.")

    def disconnect(self, player_id: str) -> None:
        with self.lock:
            # A lobby connection is not an active match identity yet. Remove
            # it entirely, freeing its name and country immediately rather
            # than leaving a misleading permanent "offline" slot behind.
            # Once play starts, disconnected players intentionally remain so
            # their country/draft can be restored with their reconnect code.
            player = self.players.get(player_id)
            if player is None:
                return
            if self.phase == "LOBBY" and player_id != self.host_id:
                self._lobby_reconnects[player.reconnect_token] = player
                del self.players[player_id]
                self._broadcast()
                return
            player.connected = False
            if player_id != self.host_id:
                player.ping_ms = None
            self._broadcast()

    def set_ping(self, player_id: str, ping_ms: int) -> None:
        """Publish a server-measured application round-trip time for the UI."""
        with self.lock:
            player = self._player(player_id)
            if player.player_id == self.host_id:
                return
            player.ping_ms = max(0, min(60_000, int(ping_ms)))
            self._broadcast()

    def rename(self, player_id: str, name: str) -> None:
        with self.lock:
            self._require_lobby()
            player = self._player(player_id)
            name = sanitize_display_name(name)
            self._assert_name_available(name, player_id)
            player.name, player.ready = name, False
            self._broadcast()

    def set_capacity(self, host_id: str, capacity: int) -> None:
        with self.lock:
            self._require_host_lobby(host_id)
            if len(self.players) > capacity:
                raise RealtimeError("Remove players before reducing capacity.")
            previous = self.config.max_players
            self.config.max_players = capacity
            try:
                self.config.validate(len(self.countries))
            except Exception:
                self.config.max_players = previous
                raise
            self._broadcast()

    def set_turn_limit(self, host_id: str, max_turns: int) -> None:
        with self.lock:
            self._require_host_lobby(host_id)
            previous = self.config.max_turns
            self.config.max_turns = max_turns
            try:
                self.config.validate(len(self.countries))
            except Exception:
                self.config.max_turns = previous
                raise
            self._broadcast()

    def set_turn_minutes(self, host_id: str, turn_minutes: int) -> None:
        with self.lock:
            self._require_host_lobby(host_id)
            previous = self.config.turn_minutes
            self.config.turn_minutes = turn_minutes
            try:
                self.config.validate(len(self.countries))
            except Exception:
                self.config.turn_minutes = previous
                raise
            self._broadcast()

    def set_scenario_settings(self, host_id: str, settings: dict[str, Any]) -> None:
        """Replace the pre-game rule bundle and notify every lobby client."""
        with self.lock:
            self._require_host_lobby(host_id)
            if not isinstance(settings, dict):
                raise RealtimeError("Scenario settings must be an object.")
            self.config.scenario_settings = copy.deepcopy(settings)
            self._broadcast()

    def reconfigure_lobby(self, host_id: str, scenario_id: str,
                          scenario_settings: dict[str, Any], countries: list[str],
                          driver: Any, max_players: int) -> None:
        """Atomically install a new pre-game map and reset all selections.

        The host may alter the map only before start. No old country assignment
        or Ready state can survive a map change, and clients receive one state
        update containing the new map identity, countries, capacity and rules.
        """
        with self.lock:
            self._require_host_lobby(host_id)
            new_countries = list(dict.fromkeys(countries))
            if not new_countries:
                raise RealtimeError("The selected scenario has no playable countries.")
            if len(self.players) > max_players:
                raise RealtimeError("Remove players before switching to a map with fewer player slots.")
            new_config = RealtimeConfig(
                scenario_id, copy.deepcopy(scenario_settings), max_players,
                self.config.max_turns, self.config.turn_minutes,
                self.config.advertised_address, self.config.port)
            new_config.validate(len(new_countries))
            self.countries, self.config, self.driver = new_countries, new_config, driver
            for player in self.players.values():
                player.country_id, player.ready = None, False
            for player in self._lobby_reconnects.values():
                player.country_id, player.ready = None, False
            self._broadcast()

    def kick(self, host_id: str, player_id: str) -> None:
        with self.lock:
            self._require_host_lobby(host_id)
            if player_id == self.host_id:
                raise RealtimeError("The host cannot remove themselves.")
            self._player(player_id)
            del self.players[player_id]
            self._broadcast()

    def select_country(self, player_id: str, country_id: str) -> None:
        with self.lock:
            self._require_lobby()
            player = self._player(player_id)
            if country_id not in self.countries:
                raise RealtimeError("That country is not available in this scenario.")
            if any(p.player_id != player_id and p.country_id == country_id for p in self.players.values()):
                raise RealtimeError("That country was selected by another player.")
            player.country_id, player.ready = country_id, False
            self._broadcast()

    def set_ready(self, player_id: str, ready: bool) -> None:
        with self.lock:
            self._require_lobby()
            player = self._player(player_id)
            if ready and not player.country_id:
                raise RealtimeError("Choose a country before marking ready.")
            player.ready = bool(ready)
            self._broadcast()

    def can_start(self) -> tuple[bool, str]:
        if not self.players:
            return False, "No players are connected."
        assigned = [p.country_id for p in self.players.values()]
        if any(not country for country in assigned):
            return False, "Every player must choose a country."
        if len(set(assigned)) != len(assigned):
            return False, "Country assignments must be unique."
        if not all(p.connected and p.ready for p in self.players.values()):
            return False, "Every connected player must be ready."
        return True, ""

    def start(self, host_id: str) -> None:
        with self.lock:
            self._require_host_lobby(host_id)
            valid, reason = self.can_start()
            if not valid:
                raise RealtimeError(reason)
            starter = getattr(self.driver, "start_game", None)
            if starter:
                starter([p.country_id for p in self.players.values() if p.country_id])
            self.phase = "TURN"
            self.turn_number = 1
            self._open_turn_locked()
            self._broadcast()

    def sync_draft(self, player_id: str, turn_number: int, commands: list[dict[str, Any]]) -> None:
        with self.lock:
            self._require_turn(turn_number)
            player = self._player(player_id)
            if player.eliminated:
                raise RealtimeError("Eliminated players cannot issue orders.")
            if player.submitted:
                raise RealtimeError("Unsubmit before editing orders.")
            if not isinstance(commands, list):
                raise RealtimeError("Orders must be a command list.")
            # The real adapter replays the command list from the current
            # authoritative turn base and returns its canonical JSON form.
            validator = getattr(self.driver, "validate_draft", None)
            canonical = validator(player.country_id, commands) if validator else commands
            if not isinstance(canonical, list):
                raise RealtimeError("The server rejected these orders.")
            player.draft = copy.deepcopy(canonical)

    def submit(self, player_id: str, turn_number: int) -> None:
        with self.lock:
            self._require_turn(turn_number)
            player = self._player(player_id)
            if player.eliminated:
                return
            player.submitted = True
            self._broadcast()
            self._maybe_begin_processing_locked()

    def unsubmit(self, player_id: str, turn_number: int) -> None:
        with self.lock:
            self._require_turn(turn_number)
            if self._processing:
                raise RealtimeError("This turn is already processing.")
            player = self._player(player_id)
            if player.eliminated:
                raise RealtimeError("Eliminated players cannot unsubmit.")
            player.submitted = False
            self._broadcast()

    def tick(self) -> None:
        with self.lock:
            if self.phase == "TURN" and not self._processing and self.deadline is not None and self.clock() >= self.deadline:
                self._begin_processing_locked()

    def _maybe_begin_processing_locked(self) -> None:
        eligible = [p for p in self.players.values() if not p.eliminated]
        if eligible and all(p.submitted for p in eligible):
            self._begin_processing_locked()

    def _begin_processing_locked(self) -> None:
        if self._processing or self.phase != "TURN":
            return
        self._processing = True
        self.phase = "PROCESSING"
        self.processing_epoch += 1
        epoch = self.processing_epoch
        drafts = {p.country_id: copy.deepcopy(p.draft) for p in self.players.values()
                  if p.country_id and not p.eliminated}
        self._broadcast()
        # Threading keeps server receiver threads responsive while an existing
        # game turn performs AI work. The epoch prevents a late completion from
        # reopening a newer turn.
        threading.Thread(target=self._process, args=(epoch, drafts), daemon=True).start()

    def _process(self, epoch: int, drafts: dict[str, list[dict[str, Any]]]) -> None:
        error: str | None = None
        try:
            processor = getattr(self.driver, "process_turn", None)
            if processor:
                processor(drafts)
        except Exception as exc:
            error = str(exc)
        with self.lock:
            if epoch != self.processing_epoch or not self._processing:
                return
            if error:
                # Preserve the locked turn: a failed simulation must never be
                # accidentally replayed as a fresh one.
                self.game_over_reason = "server_error"
                self.phase, self._processing = "GAME_OVER", False
            elif self._end_after_processing:
                self.game_over_reason = self._end_after_processing
                self._end_after_processing = None
                self.phase, self._processing = "GAME_OVER", False
            elif self.turn_number >= self.config.max_turns:
                self.game_over_reason = "turn_limit"
                self.phase, self._processing = "GAME_OVER", False
            else:
                self.turn_number += 1
                self._processing = False
                self.phase = "TURN"
                for player in self.players.values():
                    player.submitted = player.eliminated
                    player.draft = []
                    is_eliminated = getattr(self.driver, "is_eliminated", lambda _country: False)
                    player.eliminated = bool(player.country_id and is_eliminated(player.country_id))
                    if player.eliminated:
                        player.submitted = True
                self._open_turn_locked()
            self._broadcast()

    def end_match(self, host_id: str, reason: str = "host_aborted") -> None:
        with self.lock:
            if host_id != self.host_id:
                raise RealtimeError("Only the host can end this match.")
            if self.phase == "GAME_OVER":
                return
            if self._processing:
                # Do not interrupt the existing game simulation halfway
                # through. It finishes once, then closes without opening a
                # subsequent turn.
                self._end_after_processing = reason
                return
            self.phase, self.game_over_reason = "GAME_OVER", reason
            self._broadcast()

    def _open_turn_locked(self) -> None:
        self.deadline = self.clock() + self.config.turn_minutes * 60
        self.deadline_epoch = time.time() + self.config.turn_minutes * 60
        for player in self.players.values():
            player.submitted = player.eliminated
            player.draft = []

    def _player(self, player_id: str) -> Player:
        try:
            return self.players[player_id]
        except KeyError as exc:
            raise RealtimeError("Unknown player.") from exc

    def _require_lobby(self) -> None:
        if self.phase != "LOBBY":
            raise RealtimeError("Lobby changes are locked after the game starts.")

    def _require_host_lobby(self, player_id: str) -> None:
        self._require_lobby()
        if player_id != self.host_id:
            raise RealtimeError("Only the host may change lobby administration.")

    def _require_turn(self, turn_number: int) -> None:
        if self.phase != "TURN":
            raise RealtimeError("The turn is not accepting orders.")
        if turn_number != self.turn_number:
            raise RealtimeError("Those orders are for a stale turn.")

    def public_state(self) -> dict[str, Any]:
        with self.lock:
            submitted = sum(1 for p in self.players.values() if p.submitted or p.eliminated)
            active = sum(1 for p in self.players.values() if not p.eliminated)
            state = {
                "session_id": self.session_id, "host_id": self.host_id, "phase": self.phase,
                "turn": self.turn_number, "max_turns": self.config.max_turns,
                "turn_minutes": self.config.turn_minutes, "deadline_monotonic": self.deadline,
                "deadline_epoch": self.deadline_epoch,
                "server_monotonic": self.clock(), "processing": self._processing,
                "game_over_reason": self.game_over_reason,
                "submitted_count": submitted, "active_count": active,
                "players": [{"player_id": p.player_id, "name": p.name, "country_id": p.country_id,
                             "ready": p.ready, "connected": p.connected,
                             "submitted": p.submitted, "eliminated": p.eliminated,
                             "ping_ms": p.ping_ms}
                            for p in self.players.values()],
                "config": {"scenario_id": self.config.scenario_id,
                           "scenario_settings": copy.deepcopy(self.config.scenario_settings),
                           "max_players": self.config.max_players},
                "countries": list(self.countries),
            }
            snapshot = getattr(self.driver, "snapshot", None)
            if snapshot and self.phase in ("TURN", "PROCESSING", "GAME_OVER"):
                state["game_state"] = snapshot()
            return state

    def completed_metadata(self) -> dict[str, Any]:
        """Serializable, non-secret result metadata for a normal GD5 save."""
        with self.lock:
            return {
                "format": "gd5-realtime-v1", "session_id": self.session_id,
                "scenario_id": self.config.scenario_id,
                "scenario_settings": copy.deepcopy(self.config.scenario_settings),
                "max_turns": self.config.max_turns, "turn_minutes": self.config.turn_minutes,
                "final_turn": self.turn_number, "game_over": self.phase == "GAME_OVER",
                "end_reason": self.game_over_reason,
                # A completed match is deliberately no longer an active
                # session when opened from Saves. It is an offline replay
                # view, so do not accidentally restore the server map's
                # internal ``None`` country as a playable identity.
                "offline_view": "spectator",
                "players": [{"name": p.name, "country_id": p.country_id,
                             "eliminated": p.eliminated} for p in self.players.values()],
            }


class MapRealtimeDriver:
    """Adapter that lets the existing map/turn logic run only on the server.

    The command schema deliberately contains no arbitrary map replacement.
    It covers every strategic player choice as a narrow intent command.  A
    client never supplies resources, turn counters, ownership, or a whole map
    record: the server derives those values from its own current map before it
    calls the normal turn processor.
    """
    _UNIT_MUTABLE_KEYS = {"order", "custom_name", "combat_stance", "lane_target"}
    _AUTOMATION_KEYS = {"construction", "movement", "research"}
    _APPEARANCE_KEYS = {"name", "adjective", "leader_name", "leader_title",
                        "flag_data", "portrait_data", "color"}
    _MAX_CLAIM_DRAFTS = 100
    _MAX_QUEUE_ITEMS = 100
    _MAX_UNIT_PATH = 200

    def __init__(self, map_ref):
        self.map_ref = map_ref

    def start_game(self, countries: list[str]) -> None:
        self.map_ref.active_players = list(countries)
        # A server is not a player: this prevents player automation/UI-only
        # behavior from giving its local process a country.
        self.map_ref.player_country = "None"

    def validate_draft(self, country_id: str, commands: list[dict[str, Any]]) -> list[dict[str, Any]]:
        canonical = []
        has_research_command = False
        seen = set()
        for command in commands:
            if not isinstance(command, dict):
                raise RealtimeError("Invalid order command.")
            kind = command.get("type")
            # A draft is a complete projection of each mutable domain.  One
            # command per domain prevents a client from smuggling a later
            # conflicting value through the same update.
            if kind in seen and kind in {"research_queue", "country_preferences", "claim_draft",
                                        "country_appearance", "country_diplomacy", "puppet_draft",
                                        "faction_rename", "ratification_response"}:
                raise RealtimeError("Only one command is allowed for that game action.")
            if kind == "unit_order":
                canonical.append(self._validate_unit_order(country_id, command))
            elif kind == "province_queue":
                canonical.append(self._validate_queue(country_id, command))
            elif kind == "research_queue":
                if has_research_command:
                    raise RealtimeError("Only one research selection may be submitted per turn.")
                canonical.append(self._validate_research_queue(country_id, command))
                has_research_command = True
            elif kind == "country_preferences":
                canonical.append(self._validate_country_preferences(country_id, command))
            elif kind == "claim_draft":
                canonical.append(self._validate_claim_draft(country_id, command))
            elif kind == "country_appearance":
                canonical.append(self._validate_country_appearance(country_id, command))
            elif kind == "country_diplomacy":
                canonical.append(self._validate_country_diplomacy(country_id, command))
            elif kind == "puppet_draft":
                canonical.append(self._validate_puppet_draft(country_id, command))
            elif kind == "faction_rename":
                canonical.append(self._validate_faction_rename(country_id, command))
            elif kind == "ratification_response":
                canonical.append(self._validate_ratification_response(country_id, command))
            elif kind == "volunteer_draft":
                canonical.append(self._validate_volunteer_draft(country_id, command))
            else:
                raise RealtimeError("That order type is not supported by the server.")
            seen.add(kind)
        self._validate_queue_budget(country_id, canonical)
        self._validate_volunteer_commands(country_id, canonical)
        return canonical

    def _validate_volunteer_commands(self, country_id: str, commands: list[dict[str, Any]]) -> None:
        """Keep a volunteer request and its reserved divisions inseparable."""
        from map_logic.diplomacy import volunteers
        pending_targets = set()
        offered_targets, offered_count = set(), 0
        for command in commands:
            if command.get("type") == "country_diplomacy":
                pending_targets = {target for target, info in command.get("pending", {}).items()
                                   if isinstance(info, dict) and info.get("action") == volunteers.ACTION}
            elif command.get("type") == "volunteer_draft":
                target = command["target"]
                if target in offered_targets:
                    raise RealtimeError("Only one volunteer offer may be made to each country.")
                offered_targets.add(target)
                offered_count += len(command["units"])
        if pending_targets != offered_targets:
            raise RealtimeError("Volunteer offers must include their selected divisions.")
        if offered_count > volunteers.remaining_capacity(self.map_ref, country_id):
            raise RealtimeError("The selected volunteer divisions exceed your available capacity.")

    def _country(self, country_id: str) -> dict[str, Any]:
        country = self.map_ref.nation_data.get(country_id)
        if not isinstance(country, dict):
            raise RealtimeError("Unknown player country.")
        return country

    def _validate_country_preferences(self, country_id: str, command: dict[str, Any]) -> dict[str, Any]:
        """Validate politics, automation, economy, and custom unit choices."""
        from data import queries

        country = self._country(country_id)
        drift = command.get("political_drift", 0)
        automation = command.get("automation", {})
        if not isinstance(drift, int) or drift not in (-1, 0, 1):
            raise RealtimeError("Invalid political direction.")
        if not isinstance(automation, dict) or set(automation) - self._AUTOMATION_KEYS:
            raise RealtimeError("Invalid automation settings.")
        if any(not isinstance(value, bool) for value in automation.values()):
            raise RealtimeError("Invalid automation settings.")
        conscription = command.get("conscription_slider", 1.0)
        fuel_conversion = command.get("mat_to_fuel_slider", 0.0)
        if (isinstance(conscription, bool) or not isinstance(conscription, (int, float))
                or not 0.0 <= float(conscription) <= 1.0):
            raise RealtimeError("Invalid manpower conversion setting.")
        max_conversion = max(0.0, float(queries.get_max_fuel_conversion(country)))
        if (isinstance(fuel_conversion, bool) or not isinstance(fuel_conversion, (int, float))
                or not 0.0 <= float(fuel_conversion) <= max_conversion):
            raise RealtimeError("Invalid material-to-fuel conversion setting.")
        custom_units = command.get("custom_production_units", [])
        if (not isinstance(custom_units, list) or len(custom_units) > 100
                or any(not isinstance(name, str) for name in custom_units)
                or len(set(custom_units)) != len(custom_units)):
            raise RealtimeError("Invalid custom production selection.")
        unit_library = queries.get_unit_library()
        research = country.get("research", {})
        if any(name not in unit_library or not queries.is_unit_unlocked(name, research)
               for name in custom_units):
            raise RealtimeError("A selected custom unit is not researched.")
        return {"type": "country_preferences", "political_drift": drift,
                "automation": {key: bool(automation.get(key, False))
                               for key in self._AUTOMATION_KEYS},
                "conscription_slider": float(conscription),
                "mat_to_fuel_slider": float(fuel_conversion),
                "custom_production_units": list(custom_units)}

    def _validate_claim_draft(self, country_id: str, command: dict[str, Any]) -> dict[str, Any]:
        """Validate a player's desired claim queue without trusting timers.

        Clients name the provinces they want to keep in their queue. The
        authoritative map retains timers for existing entries and assigns the
        normal fabrication duration to new ones. This lets a player add or
        cancel claims while preventing forged instant claims or countdowns.
        """
        country = self._country(country_id)
        requested = command.get("province_ids", [])
        requested_revokes = command.get("revoke_ids", [])
        requested_returns = command.get("returns", [])
        if (not isinstance(requested, list) or len(requested) > self._MAX_CLAIM_DRAFTS
                or any(isinstance(province_id, bool) or not isinstance(province_id, int)
                       for province_id in requested)
                or len(set(requested)) != len(requested)):
            raise RealtimeError("Invalid claim draft.")
        if (not isinstance(requested_revokes, list) or len(requested_revokes) > self._MAX_CLAIM_DRAFTS
                or any(isinstance(province_id, bool) or not isinstance(province_id, int)
                       for province_id in requested_revokes)
                or len(set(requested_revokes)) != len(requested_revokes)):
            raise RealtimeError("Invalid claim revocation draft.")
        if (not isinstance(requested_returns, list) or len(requested_returns) > self._MAX_CLAIM_DRAFTS
                or any(not isinstance(entry, dict) for entry in requested_returns)):
            raise RealtimeError("Invalid territory return draft.")

        existing = {}
        for entry in country.get("claim_queue", []):
            if not isinstance(entry, dict):
                continue
            province_id, turns_left = entry.get("prov_id"), entry.get("turns_left")
            if (isinstance(province_id, int) and not isinstance(province_id, bool)
                    and isinstance(turns_left, int) and not isinstance(turns_left, bool)):
                existing[province_id] = {"prov_id": province_id, "turns_left": max(0, turns_left)}

        claims = set(country.get("claims", []))
        queue = []
        for province_id in requested:
            if province_id in existing:
                # This entry was accepted by the server on an earlier turn;
                # preserve its authoritative remaining time exactly.
                queue.append(existing[province_id])
                continue
            province = self._province(province_id)
            owner = province.get("owner")
            if owner == country_id or owner in c.UNPLAYABLE_NATIONS:
                raise RealtimeError("Claims must target a foreign playable province.")
            if province_id in claims:
                raise RealtimeError("That province is already claimed.")
            queue.append({"prov_id": province_id, "turns_left": c.CLAIM_TURN_NON_CORE})
        existing_revokes = {entry.get("prov_id"): entry for entry in country.get("revoke_queue", [])
                            if isinstance(entry, dict) and isinstance(entry.get("prov_id"), int)}
        revokes = []
        claims = set(country.get("claims", []))
        for province_id in requested_revokes:
            province = self._province(province_id)
            if province.get("owner") != country_id:
                raise RealtimeError("Only owned territory can have its claim revoked.")
            if province_id not in claims and country_id not in province.get("cores", []):
                raise RealtimeError("That territory has no claim or core to revoke.")
            old = existing_revokes.get(province_id)
            revokes.append({"prov_id": province_id,
                            "turns_left": max(0, int(old.get("turns_left", 1))) if old else 1})

        existing_returns = {entry.get("prov_id"): entry for entry in country.get("return_queue", [])
                            if isinstance(entry, dict) and isinstance(entry.get("prov_id"), int)}
        returns, returned_ids = [], set()
        for entry in requested_returns:
            province_id, recipient = entry.get("prov_id"), entry.get("recipient")
            if (isinstance(province_id, bool) or not isinstance(province_id, int)
                    or not isinstance(recipient, str) or province_id in returned_ids):
                raise RealtimeError("Invalid territory return.")
            province = self._province(province_id)
            recipient_data = self.map_ref.nation_data.get(recipient)
            if province.get("owner") != country_id or not isinstance(recipient_data, dict):
                raise RealtimeError("Invalid territory return.")
            if recipient not in province.get("cores", []) and province_id not in recipient_data.get("claims", []):
                raise RealtimeError("The recipient has no claim on that territory.")
            old = existing_returns.get(province_id)
            # Recipient is an authoritative choice too.  A pending return may
            # be kept or cancelled, but cannot be redirected from a stale map.
            if old and old.get("recipient") != recipient:
                raise RealtimeError("Cancel a territory return before changing its recipient.")
            returns.append({"prov_id": province_id, "recipient": recipient,
                            "turns_left": max(0, int(old.get("turns_left", 1))) if old else 1})
            returned_ids.add(province_id)
        return {"type": "claim_draft", "queue": queue, "revokes": revokes,
                "returns": returns}

    def _validate_country_appearance(self, country_id: str, command: dict[str, Any]) -> dict[str, Any]:
        """Allow identity changes without allowing a client to alter gameplay data."""
        self._country(country_id)
        appearance = command.get("appearance")
        if not isinstance(appearance, dict) or set(appearance) - self._APPEARANCE_KEYS:
            raise RealtimeError("Invalid country appearance.")
        canonical = {}
        for key in ("name", "adjective", "leader_name", "leader_title"):
            value = appearance.get(key, "")
            if not isinstance(value, str) or len(value) > 120 or any(ord(ch) < 32 for ch in value):
                raise RealtimeError("Invalid country appearance text.")
            canonical[key] = value
        for key in ("flag_data", "portrait_data"):
            value = appearance.get(key, "DEFAULT")
            if not isinstance(value, str) or len(value) > 4_000_000:
                raise RealtimeError("Invalid country appearance image.")
            canonical[key] = value
        color = appearance.get("color")
        if (not isinstance(color, list) or len(color) not in (3, 4) or
                any(not isinstance(channel, int) or not 0 <= channel <= 255 for channel in color)):
            raise RealtimeError("Invalid country color.")
        canonical["color"] = list(color)
        return {"type": "country_appearance", "appearance": canonical}

    def _canonical_appearance(self, appearance: Any) -> dict[str, Any]:
        """Use the same narrow identity schema for a player and their subject."""
        if not isinstance(appearance, dict) or set(appearance) - self._APPEARANCE_KEYS:
            raise RealtimeError("Invalid country appearance.")
        canonical = {}
        for key in ("name", "adjective", "leader_name", "leader_title"):
            value = appearance.get(key, "")
            if not isinstance(value, str) or len(value) > 120 or any(ord(ch) < 32 for ch in value):
                raise RealtimeError("Invalid country appearance text.")
            canonical[key] = value
        for key in ("flag_data", "portrait_data"):
            value = appearance.get(key, "DEFAULT")
            if not isinstance(value, str) or len(value) > 4_000_000:
                raise RealtimeError("Invalid country appearance image.")
            canonical[key] = value
        color = appearance.get("color")
        if (not isinstance(color, list) or len(color) not in (3, 4)
                or any(not isinstance(channel, int) or not 0 <= channel <= 255 for channel in color)):
            raise RealtimeError("Invalid country color.")
        canonical["color"] = list(color)
        return canonical

    def _validate_puppet_draft(self, country_id: str, command: dict[str, Any]) -> dict[str, Any]:
        """Validate the controller-only subject controls from the Puppets UI."""
        country = self._country(country_id)
        puppet_order = command.get("puppet_order", [])
        siphons = command.get("siphons", {})
        releases = command.get("release_subjects", [])
        appearances = command.get("appearances", {})
        controlled = list(country.get("puppets", []))
        if not isinstance(puppet_order, list) or sorted(puppet_order) != sorted(controlled):
            raise RealtimeError("Invalid puppet order.")
        if not all(isinstance(value, dict) for value in (siphons, appearances)):
            raise RealtimeError("Invalid puppet settings.")
        if not isinstance(releases, list) or len(releases) > self._MAX_CLAIM_DRAFTS:
            raise RealtimeError("Invalid puppet release queue.")
        canonical_siphons = {}
        for puppet, values in siphons.items():
            puppet_data = self.map_ref.nation_data.get(puppet)
            if (puppet not in controlled or not isinstance(puppet_data, dict)
                    or puppet_data.get("puppet_type") != c.PUPPET_TYPE_INTEGRATED
                    or not isinstance(values, dict)):
                raise RealtimeError("You may only change your integrated subjects.")
            rates = {}
            for resource in ("manpower", "materials", "fuel"):
                value = values.get(resource, 0)
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= c.MAX_PUPPET_SIPHON:
                    raise RealtimeError("Invalid puppet siphon rate.")
                rates[resource] = value
            canonical_siphons[puppet] = rates
        canonical_appearances = {}
        for puppet, appearance in appearances.items():
            puppet_data = self.map_ref.nation_data.get(puppet)
            if (puppet not in controlled or not isinstance(puppet_data, dict)
                    or puppet_data.get("puppet_type") != c.PUPPET_TYPE_INTEGRATED):
                raise RealtimeError("You may only edit an integrated subject.")
            canonical_appearances[puppet] = self._canonical_appearance(appearance)
        old_releases = {entry.get("core_nation"): entry for entry in country.get("release_puppet_queue", [])
                        if isinstance(entry, dict) and isinstance(entry.get("core_nation"), str)}
        canonical_releases, seen_subjects = [], set()
        for entry in releases:
            subject, keep_cores = entry.get("core_nation"), entry.get("keep_cores", False)
            if not isinstance(subject, str) or not isinstance(keep_cores, bool) or subject in seen_subjects:
                raise RealtimeError("Invalid integrated puppet release.")
            if subject not in self.map_ref.nation_data or subject in c.UNPLAYABLE_NATIONS:
                raise RealtimeError("Unknown integrated puppet subject.")
            has_core = any(province.get("owner") == country_id and subject in province.get("cores", [])
                           for province in self.map_ref.map_data.values())
            if not has_core:
                raise RealtimeError("That subject has no eligible core territory.")
            old = old_releases.get(subject)
            if old and bool(old.get("keep_cores", False)) != keep_cores:
                raise RealtimeError("Cancel the existing puppet release before changing it.")
            canonical_releases.append({"core_nation": subject, "keep_cores": keep_cores,
                                       "turns_left": max(0, int(old.get("turns_left", 1))) if old else 1})
            seen_subjects.add(subject)
        return {"type": "puppet_draft", "puppet_order": list(puppet_order),
                "siphons": canonical_siphons, "release_subjects": canonical_releases,
                "appearances": canonical_appearances}

    def _validate_faction_rename(self, country_id: str, command: dict[str, Any]) -> dict[str, Any]:
        country = self._country(country_id)
        name = command.get("name")
        if name is None:
            return {"type": "faction_rename", "name": None}
        if not isinstance(name, str) or len(name.strip()) > 40:
            raise RealtimeError("Invalid faction name.")
        old_name = country.get("faction", "")
        if name.strip() == old_name:
            return {"type": "faction_rename", "name": None}
        if not country.get("is_faction_leader") or not old_name:
            raise RealtimeError("Only a faction leader may rename their faction.")
        from map_logic.diplomacy import faction_actions
        # Validate against a copy: the helper owns the collision and membership
        # rules, while the real mutation waits for atomic turn processing.
        probe = copy.deepcopy(self.map_ref.nation_data)
        if not faction_actions.rename_faction(probe, country_id, old_name, name.strip()):
            raise RealtimeError("That faction name is unavailable.")
        return {"type": "faction_rename", "name": name.strip()}

    def _validate_ratification_response(self, country_id: str, command: dict[str, Any]) -> dict[str, Any]:
        verdict = command.get("verdict")
        pending = self._country(country_id).get("pending_ratification")
        if verdict is not None and verdict not in ("RATIFY", "REFUSE"):
            raise RealtimeError("Invalid treaty ratification response.")
        if verdict is not None and not isinstance(pending, dict):
            raise RealtimeError("There is no treaty awaiting ratification.")
        return {"type": "ratification_response", "verdict": verdict}

    def _validate_volunteer_draft(self, country_id: str, command: dict[str, Any]) -> dict[str, Any]:
        """Identify divisions by their authoritative province/index, never data."""
        from data import queries
        target, units = command.get("target"), command.get("units", [])
        if (not isinstance(target, str) or target == country_id or target not in self.map_ref.nation_data
                or not isinstance(units, list) or not units or len(units) > 100):
            raise RealtimeError("Invalid volunteer offer.")
        from map_logic.diplomacy import volunteers
        legal, reason = volunteers.is_eligible(country_id, target, self.map_ref.nation_data)
        if not legal:
            raise RealtimeError(reason)
        canonical, seen = [], set()
        for ref in units:
            if not isinstance(ref, dict):
                raise RealtimeError("Invalid volunteer division.")
            province = self._province(ref.get("province_id"))
            index = ref.get("unit_index")
            if not isinstance(index, int) or not 0 <= index < len(province.get("units", [])):
                raise RealtimeError("Unknown volunteer division.")
            unit = province["units"][index]
            key = (province["id"], index)
            if (key in seen or unit.get("owner") != country_id or unit.get("volunteer_host")
                    or queries.is_naval_unit(unit.get("type", ""))):
                raise RealtimeError("That division cannot volunteer.")
            canonical.append({"province_id": province["id"], "unit_index": index})
            seen.add(key)
        return {"type": "volunteer_draft", "target": target, "units": canonical}

    def _validate_country_diplomacy(self, country_id: str, command: dict[str, Any]) -> dict[str, Any]:
        """Validate only this country's unprocessed diplomatic draft.

        Diplomacy is deliberately a command rather than copied client map data.
        In-flight proposals remain on the authoritative map; clients can only
        replace their own unsent proposals and responses for the current turn.
        """
        self._country(country_id)
        pending = command.get("pending", {})
        responses = command.get("responses", {})
        draft_lists = command.get("draft_lists", {})
        if not all(isinstance(value, dict) for value in (pending, responses, draft_lists)):
            raise RealtimeError("Invalid diplomacy draft.")
        if any(len(value) > 100 for value in (pending, responses, draft_lists)):
            raise RealtimeError("Too many diplomatic actions in one turn.")
        allowed_actions = set(c.UNILATERAL_ACTIONS) | set(c.BILATERAL_ACTIONS)

        def target_ok(target: Any) -> str:
            if (not isinstance(target, str) or target == country_id or
                    target not in self.map_ref.nation_data):
                raise RealtimeError("Invalid diplomacy target.")
            return target

        def text(value: Any, label: str, limit: int = 4000) -> str:
            if (not isinstance(value, str) or len(value) > limit or
                    any(ord(character) < 32 and character not in "\n\t" for character in value)):
                raise RealtimeError(f"Invalid diplomacy {label}.")
            return value

        canonical_pending = {}
        for target, info in pending.items():
            target_ok(target)
            if not isinstance(info, dict):
                raise RealtimeError("Invalid diplomatic action.")
            action = info.get("action")
            if not isinstance(action, str) or len(action) > 4500:
                raise RealtimeError("Invalid diplomatic action.")
            if action.startswith("MSG:"):
                text(action[4:], "message")
            elif action not in allowed_actions:
                raise RealtimeError("Unknown diplomatic action.")
            timer = info.get("timer", 0)
            if not isinstance(timer, int) or isinstance(timer, bool) or not -1 <= timer <= 1000:
                raise RealtimeError("Invalid diplomacy timer.")
            entry = {"action": action, "turns": 0,
                     "timer": timer,
                     "message": text(info.get("message", ""), "message")}
            if "parameters" in info:
                try:
                    encoded = json.dumps(info["parameters"], separators=(",", ":"))
                except (TypeError, ValueError) as exc:
                    raise RealtimeError("Invalid diplomacy terms.") from exc
                if len(encoded) > 50_000:
                    raise RealtimeError("Diplomacy terms are too large.")
                entry["parameters"] = copy.deepcopy(info["parameters"])
            canonical_pending[target] = entry

        canonical_responses = {}
        for target, info in responses.items():
            target_ok(target)
            if not isinstance(info, dict):
                raise RealtimeError("Invalid diplomatic response.")
            verdict, action = info.get("verdict"), info.get("action")
            if verdict not in ("ACCEPT", "REJECT") or action not in c.BILATERAL_ACTIONS:
                raise RealtimeError("Invalid diplomatic response.")
            entry = {"verdict": verdict, "action": action,
                     "message": text(info.get("message", ""), "response message")}
            if "parameters" in info:
                try:
                    encoded = json.dumps(info["parameters"], separators=(",", ":"))
                except (TypeError, ValueError) as exc:
                    raise RealtimeError("Invalid diplomacy terms.") from exc
                if len(encoded) > 50_000:
                    raise RealtimeError("Diplomacy terms are too large.")
                entry["parameters"] = copy.deepcopy(info["parameters"])
            canonical_responses[target] = entry

        canonical_lists = {}
        for target, messages in draft_lists.items():
            target_ok(target)
            if (not isinstance(messages, list) or len(messages) > 20 or
                    any(not isinstance(message, str) or len(message) > 4000 or
                        any(ord(character) < 32 and character not in "\n\t" for character in message)
                        for message in messages)):
                raise RealtimeError("Invalid diplomatic message draft.")
            canonical_lists[target] = list(messages)
        return {"type": "country_diplomacy", "pending": canonical_pending,
                "responses": canonical_responses, "draft_lists": canonical_lists}

    def _province(self, province_id: Any):
        try:
            return self.map_ref.id_to_province[int(province_id)]
        except (KeyError, TypeError, ValueError) as exc:
            raise RealtimeError("Unknown province in order.") from exc

    def _validate_unit_order(self, country_id: str, command: dict[str, Any]) -> dict[str, Any]:
        from data import queries
        province = self._province(command.get("province_id"))
        index = command.get("unit_index")
        if not isinstance(index, int) or not 0 <= index < len(province.get("units", [])):
            raise RealtimeError("Unknown unit in order.")
        unit = province["units"][index]
        if unit.get("owner") != country_id:
            raise RealtimeError("Players may only order their own units.")
        order = command.get("order")
        if order is not None and not isinstance(order, dict):
            raise RealtimeError("Invalid unit order.")
        canonical_order = self._canonical_unit_order(country_id, province, unit, order)
        custom_name = command.get("custom_name")
        if custom_name is not None and (not isinstance(custom_name, str) or len(custom_name.strip()) > 120
                                        or any(ord(character) < 32 for character in custom_name)):
            raise RealtimeError("Invalid unit name.")
        stance = command.get("combat_stance")
        if stance not in (None, "RESERVE"):
            raise RealtimeError("Invalid combat stance.")
        lane_target = command.get("lane_target")
        if lane_target is not None and (not isinstance(lane_target, str)
                                        or lane_target not in self.map_ref.nation_data
                                        or not queries.are_at_war(country_id, lane_target, self.map_ref.nation_data)):
            raise RealtimeError("Invalid battle lane target.")
        return {"type": "unit_order", "province_id": province["id"],
                "unit_index": index, "order": canonical_order,
                "custom_name": custom_name.strip() if isinstance(custom_name, str) and custom_name.strip() else None,
                "combat_stance": stance, "lane_target": lane_target}

    def _canonical_unit_order(self, country_id: str, province: dict[str, Any], unit: dict[str, Any],
                              order: dict[str, Any] | None) -> dict[str, Any] | None:
        """Validate every order form before the existing processor sees it."""
        from data import queries
        if order is None or order == {}:
            return None
        kind = order.get("type")
        if kind == "MOVE":
            path = order.get("path", [])
            if (not isinstance(path, list) or len(path) > self._MAX_UNIT_PATH
                    or any(isinstance(province_id, bool) or not isinstance(province_id, int)
                           for province_id in path)):
                raise RealtimeError("Invalid movement path.")
            previous = province
            combat_owner = queries.get_unit_combat_owner(unit)
            for province_id in path:
                destination = self._province(province_id)
                if destination["id"] not in previous.get("neighbors", []):
                    raise RealtimeError("Movement path contains non-adjacent provinces.")
                unit_type = unit.get("type", "")
                if unit_type.startswith("Convoy"):
                    legal = queries.can_convoy_enter(previous, destination)
                elif queries.is_naval_unit(unit_type):
                    legal = queries.can_ships_enter(combat_owner, destination, self.map_ref.nation_data)
                else:
                    legal = queries.can_land_units_enter(combat_owner, destination, self.map_ref.nation_data)
                if not legal:
                    raise RealtimeError("That unit cannot enter a province in this path.")
                previous = destination
            return {"type": "MOVE", "path": list(path)}
        if kind == "BOMBARD":
            target = self._province(order.get("target_id"))
            unit_type = unit.get("type", "")
            if (queries.is_water_province(province)
                    and not (unit.get("naval_unit") or queries.is_naval_unit(unit_type))):
                raise RealtimeError("That unit cannot bombard from water.")
            targets = queries.get_bombardment_targets(
                province, self.map_ref.id_to_province, queries.get_bombardment_range(unit_type))
            if target["id"] not in targets:
                raise RealtimeError("Bombardment target is out of range.")
            return {"type": "BOMBARD", "target_id": target["id"]}
        if kind == "DISBAND":
            return {"type": "DISBAND", "turns_left": 1}
        if kind == "REPAIR":
            if queries.is_nation_in_combat_here(country_id, province, self.map_ref.nation_data):
                raise RealtimeError("Units cannot repair in combat.")
            unit_type = unit.get("original_type", unit.get("type", ""))
            stats = queries.get_unit_library().get(unit_type, {})
            if queries.get_scenario_flag("free_repairs", c.DEFAULT_FREE_REPAIRS,
                                         self.map_ref.scenario_settings):
                cost = {"cost_materials": 0, "cost_manpower": 0, "cost_fuel": 0}
            else:
                missing = (unit.get("max_health", 1) - unit.get("health", 0)) / max(1, unit.get("max_health", 1))
                cost = {key: int(stats.get(key, 0) * missing)
                        for key in ("cost_materials", "cost_manpower", "cost_fuel")}
            return {"type": "REPAIR", "turns_left": 1, "refund": cost, "realtime_cost": cost}
        if kind == "UPGRADE":
            target_type = order.get("target_type")
            unit_library = queries.get_unit_library()
            research = self._country(country_id).get("research", {})
            if (not isinstance(target_type, str) or target_type not in unit_library
                    or not queries.is_unit_unlocked(target_type, research)
                    or not queries.has_industry(province)
                    or queries.is_nation_in_combat_here(country_id, province, self.map_ref.nation_data)):
                raise RealtimeError("Invalid unit upgrade.")
            return {"type": "UPGRADE", "turns_left": 1, "target_type": target_type, "refund": {}}
        if kind == "CONVERT":
            source = unit.get("type", "")
            if queries.is_nation_in_combat_here(country_id, province, self.map_ref.nation_data):
                raise RealtimeError("Units cannot convert in combat.")
            if source.startswith("Convoy"):
                expected, turns = "Land Unit", 1
            elif source.startswith("Truck"):
                expected, turns = "Ship", c.TRUCK_CONVERT_TURNS
            elif queries.is_naval_unit(source):
                if self._country(country_id).get("research", {}).get("trucks", 0) < 1:
                    raise RealtimeError("Trucks research is required for this conversion.")
                expected, turns = "Truck", c.TRUCK_CONVERT_TURNS
            else:
                expected, turns = "Convoy", 1
            if order.get("to") != expected:
                raise RealtimeError("Invalid unit conversion.")
            return {"type": "CONVERT", "turns_left": turns, "to": expected}
        raise RealtimeError("Unknown unit order.")

    def _validate_queue(self, country_id: str, command: dict[str, Any]) -> dict[str, Any]:
        from data import queries
        province = self._province(command.get("province_id"))
        if province.get("owner") != country_id:
            raise RealtimeError("Players may only change queues in their own provinces.")
        queue_type = command.get("queue")
        items = command.get("items")
        if queue_type not in ("building_queue", "unit_queue") or not isinstance(items, list):
            raise RealtimeError("Invalid province queue.")
        if len(items) > self._MAX_QUEUE_ITEMS or any(not isinstance(item, dict) for item in items):
            raise RealtimeError("Invalid province queue contents.")
        # Existing orders are preserved exactly; new entries are rebuilt from
        # server libraries and costs rather than the client's refund/timer data.
        remaining = [copy.deepcopy(item) for item in province.get(queue_type, []) if isinstance(item, dict)]
        canonical, new_costs = [], []
        for item in items:
            match_index = next((index for index, existing in enumerate(remaining) if existing == item), None)
            if match_index is not None:
                canonical.append(remaining.pop(match_index))
                continue
            rebuilt, cost = self._build_queue_item(country_id, province, queue_type, item)
            canonical.append(rebuilt)
            new_costs.append(cost)
        return {"type": "province_queue", "province_id": province["id"], "queue": queue_type,
                "items": canonical, "cancelled": remaining, "new_costs": new_costs}

    def _build_queue_item(self, country_id: str, province: dict[str, Any], queue_type: str,
                          intent: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        """Build a queue entry using the same data the normal UI uses."""
        from data import queries
        country = self._country(country_id)
        if queue_type == "building_queue":
            order_type = intent.get("order_type", "BUILDING")
            if order_type == "CORE":
                if country_id in province.get("cores", []):
                    raise RealtimeError("That territory is already cored.")
                cost = queries.get_core_cost(country_id, self.map_ref.map_data)
                item_name, group = "Core Territory", "administration"
            elif order_type == "REMOVE_CORE":
                if not [core for core in province.get("cores", []) if core != country_id]:
                    raise RealtimeError("That territory has no foreign cores to remove.")
                cost = queries.get_remove_core_cost(country_id, self.map_ref.map_data)
                item_name, group = "Remove Cores", "administration"
            elif order_type == "BUILDING":
                item_name = intent.get("item_name")
                library = queries.get_building_library()
                if (not isinstance(item_name, str) or item_name not in library
                        or not queries.has_core(country_id, province)):
                    raise RealtimeError("Invalid building order.")
                requirement, level = queries.get_building_required_tech(item_name)
                if requirement and country.get("research", {}).get(requirement, 0) < level:
                    raise RealtimeError("Required building research is not complete.")
                cost = queries.get_building_cost(item_name, country_id, self.map_ref.map_data, library)
                group = cost.get("group", "")
            else:
                raise RealtimeError("Invalid building order.")
            refund = {key: cost.get(key, 0) for key in ("cost_materials", "cost_manpower", "cost_fuel")}
            return ({"order_type": order_type, "item_name": item_name,
                     "turns_remaining": max(1, cost.get("time", 1)), "group": group,
                     "refund": refund}, refund)
        unit_name = intent.get("unit_type")
        library = queries.get_unit_library()
        if (not isinstance(unit_name, str) or unit_name not in library
                or not queries.has_core(country_id, province)
                or not queries.is_unit_unlocked(unit_name, country.get("research", {}))):
            raise RealtimeError("Invalid unit production order.")
        stats = library[unit_name]
        if stats.get("naval_unit") and not province.get("is_coastal", False):
            raise RealtimeError("Naval units require a coastal province.")
        if queries.get_base_unit_name(unit_name) == "Militia":
            factory_ok = queries.has_industry(province)
        else:
            factory_ok = queries.has_basic_factory(province)
        from map_logic.diplomacy import restrictions
        if not factory_ok or not restrictions.can_raise_units(country_id, self.map_ref.nation_data):
            raise RealtimeError("That province cannot recruit this unit.")
        refund = {key: stats.get(key, 0) for key in ("cost_materials", "cost_manpower", "cost_fuel")}
        return ({"unit_type": unit_name, "turns_remaining": max(1, stats.get("production_time", 1)),
                 "refund": refund}, refund)

    def _validate_queue_budget(self, country_id: str, commands: list[dict[str, Any]]) -> None:
        """Ensure queue changes can be paid for before accepting a draft."""
        from data import queries
        country = self._country(country_id)
        available = {key: float(country.get(key.replace("cost_", ""), 0))
                     for key in ("cost_materials", "cost_manpower", "cost_fuel")}
        for command in commands:
            if command.get("type") == "province_queue":
                for item in command.get("cancelled", []):
                    refund = item.get("refund", {}) if isinstance(item, dict) else {}
                    for key in available:
                        available[key] += max(0, float(refund.get(key, 0)))
                for cost in command.get("new_costs", []):
                    for key in available:
                        available[key] -= float(cost.get(key, 0))
            elif command.get("type") == "unit_order":
                order = command.get("order")
                if isinstance(order, dict) and order.get("type") == "REPAIR":
                    for key in available:
                        available[key] -= float(order["realtime_cost"].get(key, 0))
        if any(value < 0 for value in available.values()):
            raise RealtimeError("These production and repair orders exceed available resources.")

    def _validate_research_queue(self, country_id: str, command: dict[str, Any]) -> dict[str, Any]:
        """Replay a player's start/pause choices without trusting client points.

        Clients submit only the desired ordered tech names. Progress always
        comes from the authoritative map: pausing stores that server progress,
        and resuming restores it. A forged client therefore cannot finish a
        technology by claiming a smaller point cost.
        """
        from data import queries

        requested = command.get("tech_names")
        if (not isinstance(requested, list) or len(requested) > c.RESEARCH_SLOTS or
                any(not isinstance(tech, str) for tech in requested) or
                len(set(requested)) != len(requested)):
            raise RealtimeError("Invalid research selection.")
        country_data = self.map_ref.nation_data.get(country_id)
        if not isinstance(country_data, dict):
            raise RealtimeError("Unknown country research selection.")
        tech_tree = queries.get_tech_tree()
        research = country_data.get("research", {})
        if not isinstance(research, dict):
            raise RealtimeError("Invalid authoritative research data.")
        current_queue = country_data.get("research_queue", [])
        if not isinstance(current_queue, list):
            raise RealtimeError("Invalid authoritative research queue.")
        running = {project.get("tech_name"): project for project in current_queue
                   if isinstance(project, dict) and isinstance(project.get("tech_name"), str)}
        progress = copy.deepcopy(country_data.get("research_progress", {}))
        if not isinstance(progress, dict):
            progress = {}

        # Paused projects retain the authoritative remaining point total.
        for tech_name, project in running.items():
            if tech_name not in requested:
                remaining = project.get("points_remaining", tech_tree.get(tech_name, {}).get("cost", 0))
                if isinstance(remaining, (int, float)) and remaining >= 0:
                    progress[tech_name] = remaining

        canonical_projects = []
        for tech_name in requested:
            tech = tech_tree.get(tech_name)
            if not isinstance(tech, dict):
                raise RealtimeError("Unknown research technology.")
            if tech_name in running:
                # Keep the server's project object and progress, never the
                # similarly shaped value supplied by a client.
                project = copy.deepcopy(running[tech_name])
            else:
                current_level = research.get(tech_name, 0)
                if not isinstance(current_level, int) or current_level < 0:
                    raise RealtimeError("Invalid research level.")
                if current_level >= tech.get("max_lvl", 0):
                    raise RealtimeError("That research is already complete.")
                if not queries.check_tech_requirements(research, tech.get("req", {}), current_level + 1):
                    raise RealtimeError("Research requirements are not met.")
                cost = tech.get("cost")
                if not isinstance(cost, (int, float)) or cost <= 0:
                    raise RealtimeError("Invalid research technology.")
                remaining = progress.pop(tech_name, cost)
                if not isinstance(remaining, (int, float)) or remaining < 0:
                    remaining = cost
                project = {"tech_name": tech_name, "points_remaining": remaining}
            progress.pop(tech_name, None)
            canonical_projects.append(project)
        return {"type": "research_queue", "projects": canonical_projects,
                "research_progress": progress}

    def process_turn(self, drafts: dict[str, list[dict[str, Any]]]) -> None:
        for country_id, commands in drafts.items():
            country_data = self.map_ref.nation_data[country_id]
            for command in commands:
                if command["type"] == "unit_order":
                    province = self._province(command["province_id"])
                    unit = province["units"][command["unit_index"]]
                    order = command["order"]
                    if isinstance(order, dict) and order.get("type") == "REPAIR":
                        from data import queries
                        queries.deduct_resources(country_data, order.pop("realtime_cost"))
                    if command["order"] is None:
                        unit.pop("order", None)
                    else:
                        unit["order"] = copy.deepcopy(command["order"])
                    for key in ("custom_name", "combat_stance", "lane_target"):
                        value = command.get(key)
                        if value is None:
                            unit.pop(key, None)
                        else:
                            unit[key] = value
                elif command["type"] == "province_queue":
                    province = self._province(command["province_id"])
                    from data import queries
                    for item in command.get("cancelled", []):
                        queries.refund_queue_item(country_data, item, country_id, self.map_ref.map_data)
                    for cost in command.get("new_costs", []):
                        queries.deduct_resources(country_data, cost)
                    province[command["queue"]] = copy.deepcopy(command["items"])
                elif command["type"] == "research_queue":
                    country_data["research_queue"] = copy.deepcopy(command["projects"])
                    country_data["research_progress"] = copy.deepcopy(command["research_progress"])
                elif command["type"] == "country_preferences":
                    country_data["political_drift"] = command["political_drift"]
                    country_data["automation"] = copy.deepcopy(command["automation"])
                    country_data["conscription_slider"] = command["conscription_slider"]
                    country_data["mat_to_fuel_slider"] = command["mat_to_fuel_slider"]
                    country_data["custom_production_units"] = copy.deepcopy(command["custom_production_units"])
                elif command["type"] == "claim_draft":
                    country_data["claim_queue"] = copy.deepcopy(command["queue"])
                    country_data["revoke_queue"] = copy.deepcopy(command["revokes"])
                    country_data["return_queue"] = copy.deepcopy(command["returns"])
                elif command["type"] == "country_appearance":
                    country_data.update(copy.deepcopy(command["appearance"]))
                    self.map_ref.nation_colors[country_id] = tuple(country_data["color"])
                elif command["type"] == "country_diplomacy":
                    # A proposal already travelling belongs to the server and
                    # cannot be cancelled or rewritten by a stale client view.
                    existing = country_data.get("pending_diplomacy", {})
                    in_flight = {target: copy.deepcopy(info) for target, info in existing.items()
                                 if isinstance(info, dict) and info.get("turns", 0) > 0}
                    in_flight.update(copy.deepcopy(command["pending"]))
                    country_data["pending_diplomacy"] = in_flight
                    country_data["diplo_responses"] = copy.deepcopy(command["responses"])
                    country_data["draft_lists"] = copy.deepcopy(command["draft_lists"])
                elif command["type"] == "puppet_draft":
                    country_data["puppets"] = list(command["puppet_order"])
                    country_data["release_puppet_queue"] = copy.deepcopy(command["release_subjects"])
                    for puppet, rates in command["siphons"].items():
                        self.map_ref.nation_data[puppet]["siphon_rates"] = copy.deepcopy(rates)
                    for puppet, appearance in command["appearances"].items():
                        subject = self.map_ref.nation_data[puppet]
                        subject.update(copy.deepcopy(appearance))
                        self.map_ref.nation_colors[puppet] = tuple(subject["color"])
                elif command["type"] == "faction_rename" and command.get("name"):
                    from map_logic.diplomacy import faction_actions
                    faction_actions.rename_faction(self.map_ref.nation_data, country_id,
                                                   country_data.get("faction", ""), command["name"])
                elif command["type"] == "ratification_response":
                    pending = country_data.get("pending_ratification")
                    if isinstance(pending, dict):
                        if command["verdict"] is None:
                            pending.pop("verdict", None)
                        else:
                            pending["verdict"] = command["verdict"]
            # Volunteer reservations must be created after their diplomatic
            # request has been placed on the server map, just like the normal
            # player UI does in an offline game.
            for command in commands:
                if command["type"] != "volunteer_draft":
                    continue
                pending = country_data.get("pending_diplomacy", {}).get(command["target"], {})
                if not isinstance(pending, dict) or pending.get("action") != "SEND_VOLUNTEERS":
                    continue
                from map_logic.diplomacy import volunteers
                chosen = []
                for ref in command["units"]:
                    province = self._province(ref["province_id"])
                    chosen.append((province, province["units"][ref["unit_index"]]))
                _details, error = volunteers.create_offer(self.map_ref, country_id, command["target"], chosen)
                if error:
                    raise RealtimeError(error)
        from map_logic.turn_processing import turn_processor
        asyncio.run(turn_processor.prepare_turn(self.map_ref))
        asyncio.run(turn_processor.resolve_turn_logic(self.map_ref))
        # In a normal game this hook runs *after* resolution, so its orders
        # genuinely prepare the next turn.  The server has no local player and
        # therefore cannot use that single-player hook directly; replay it for
        # each opted-in real-time player at the same point in the turn instead.
        from map_logic.ai import automation_logic
        original_player = self.map_ref.player_country
        try:
            for country_id in drafts:
                automation = self.map_ref.nation_data.get(country_id, {}).get("automation", {})
                if not isinstance(automation, dict):
                    continue
                self.map_ref.player_country = country_id
                if automation.get("construction"):
                    automation_logic.automate_player_construction(self.map_ref)
                if automation.get("movement"):
                    automation_logic.automate_player_movement(self.map_ref)
                if automation.get("research"):
                    automation_logic.automate_player_research(self.map_ref)
        finally:
            self.map_ref.player_country = original_player

    def is_eliminated(self, country_id: str) -> bool:
        from data import queries
        return country_id not in queries.get_living_nations(self.map_ref.map_data)

    def snapshot(self) -> dict[str, Any]:
        from data import queries
        return queries.build_save_dict(self.map_ref)

    def map_bundle(self) -> dict[str, Any]:
        """Self-contained initial map payload for a joining desktop client."""
        source = self.map_ref.load_path
        if not source or not os.path.isdir(source):
            raise RealtimeError("The host map cannot be bundled.")
        images = {}
        for name in ("terrain.png", "id_map.png", "political.png", "cores.png"):
            path = os.path.join(source, name)
            if not os.path.isfile(path):
                continue
            raw = Path(path).read_bytes()
            if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
                raise RealtimeError(f"Host map asset {name} is not a PNG file.")
            images[name] = base64.b64encode(raw).decode("ascii")
        if not {"terrain.png", "id_map.png"}.issubset(images):
            raise RealtimeError("Host map is missing required PNG assets.")
        return {"raw_map_data": copy.deepcopy(self.map_ref.raw_json_data),
                "snapshot": self.snapshot(), "images": images}


def collect_map_commands(map_ref, country_id: str) -> list[dict[str, Any]]:
    """Serialize supported local order controls into server commands.

    This deliberately reads only player choices, never mutable combat,
    resource, research-progress, or claim-timer fields from the client map.
    """
    commands: list[dict[str, Any]] = []
    for province in map_ref.map_data.values():
        for index, unit in enumerate(province.get("units", [])):
            if unit.get("owner") == country_id:
                commands.append({"type": "unit_order", "province_id": province["id"],
                                 "unit_index": index, "order": copy.deepcopy(unit.get("order")),
                                 "custom_name": unit.get("custom_name"),
                                 "combat_stance": unit.get("combat_stance"),
                                 "lane_target": unit.get("lane_target")})
        if province.get("owner") == country_id:
            for queue_name in ("building_queue", "unit_queue"):
                # Empty queues are meaningful: they are how a player cancels
                # already-paid work on the authoritative server.
                commands.append({"type": "province_queue", "province_id": province["id"],
                                 "queue": queue_name,
                                 "items": copy.deepcopy(province.get(queue_name, []))})
    country_data = map_ref.nation_data.get(country_id, {})
    research_queue = country_data.get("research_queue", []) if isinstance(country_data, dict) else []
    tech_names = [project.get("tech_name") for project in research_queue
                  if isinstance(project, dict) and isinstance(project.get("tech_name"), str)]
    # Include an empty selection too: pausing every project must be a real
    # draft change rather than silently preserving the server's old queue.
    commands.append({"type": "research_queue", "tech_names": tech_names})
    commands.append({"type": "country_preferences",
                     "political_drift": country_data.get("political_drift", 0),
                     "automation": copy.deepcopy(country_data.get("automation", {})),
                     "conscription_slider": country_data.get("conscription_slider", 1.0),
                     "mat_to_fuel_slider": country_data.get("mat_to_fuel_slider", 0.0),
                     "custom_production_units": copy.deepcopy(country_data.get("custom_production_units", []))})
    # Claim timers are server state. A client only says which existing/new
    # claims should remain queued; validation restores server timers and gives
    # new claims the standard fabrication time.
    claim_queue = country_data.get("claim_queue", []) if isinstance(country_data, dict) else []
    commands.append({"type": "claim_draft", "province_ids": [entry.get("prov_id")
                     for entry in claim_queue if isinstance(entry, dict)
                     and isinstance(entry.get("prov_id"), int)
                     and not isinstance(entry.get("prov_id"), bool)],
                     "revoke_ids": [entry.get("prov_id") for entry in country_data.get("revoke_queue", [])
                                    if isinstance(entry, dict) and isinstance(entry.get("prov_id"), int)
                                    and not isinstance(entry.get("prov_id"), bool)],
                     "returns": [{"prov_id": entry.get("prov_id"), "recipient": entry.get("recipient")}
                                 for entry in country_data.get("return_queue", [])
                                 if isinstance(entry, dict)]})
    commands.append({"type": "country_appearance", "appearance": {
        key: copy.deepcopy(country_data.get(key, "DEFAULT" if key.endswith("_data") else [] if key == "color" else ""))
        for key in MapRealtimeDriver._APPEARANCE_KEYS}})
    # Only unsent proposals are a local draft.  Messages already in transit
    # are server-owned and are deliberately omitted so a stale client cannot
    # cancel or alter them on its next ordinary sync.
    pending = country_data.get("pending_diplomacy", {})
    if not isinstance(pending, dict):
        pending = {}
    responses = country_data.get("diplo_responses", {})
    if not isinstance(responses, dict):
        responses = {}
    draft_lists = country_data.get("draft_lists", {})
    if not isinstance(draft_lists, dict):
        draft_lists = {}
    commands.append({"type": "country_diplomacy",
                     "pending": {target: copy.deepcopy(info) for target, info in pending.items()
                                 if isinstance(target, str) and isinstance(info, dict)
                                 and info.get("turns", 0) <= 0},
                     "responses": copy.deepcopy(responses),
                     "draft_lists": copy.deepcopy(draft_lists)})
    controlled = country_data.get("puppets", []) if isinstance(country_data, dict) else []
    siphons = {}
    for puppet in controlled:
        subject = map_ref.nation_data.get(puppet, {})
        if isinstance(subject, dict) and subject.get("puppet_type") == c.PUPPET_TYPE_INTEGRATED:
            siphons[puppet] = copy.deepcopy(subject.get("siphon_rates", {}))
    commands.append({"type": "puppet_draft", "puppet_order": list(controlled), "siphons": siphons,
                     "release_subjects": [{"core_nation": entry.get("core_nation"),
                                           "keep_cores": bool(entry.get("keep_cores", False))}
                                          for entry in country_data.get("release_puppet_queue", [])
                                          if isinstance(entry, dict)],
                     "appearances": copy.deepcopy(getattr(map_ref, "realtime_pending_appearance_updates", {}))})
    commands.append({"type": "faction_rename", "name": country_data.get("faction", "")})
    pending_ratification = country_data.get("pending_ratification", {})
    commands.append({"type": "ratification_response",
                     "verdict": pending_ratification.get("verdict") if isinstance(pending_ratification, dict) else None})
    volunteer_drafts = getattr(map_ref, "realtime_volunteer_drafts", {})
    if isinstance(volunteer_drafts, dict):
        for target, units in volunteer_drafts.items():
            commands.append({"type": "volunteer_draft", "target": target, "units": copy.deepcopy(units)})
    return commands


class RemoteSessionView:
    """Client-side, non-authoritative projection of server status/state."""
    def __init__(self, client: "RealtimeClient", state: dict[str, Any], player_id: str):
        self.client, self.player_id = client, player_id
        self.players: dict[str, SimpleNamespace] = {}
        self.update(state)

    def update(self, state: dict[str, Any]) -> None:
        self.host_id = state.get("host_id")
        self.phase = state.get("phase", "LOBBY")
        self.turn_number = state.get("turn", 1)
        self.max_turns = state.get("max_turns", 1)
        self.game_over_reason = state.get("game_over_reason")
        self.config = SimpleNamespace(max_turns=self.max_turns,
                                      turn_minutes=state.get("turn_minutes", 1),
                                      **state.get("config", {}))
        deadline_epoch = state.get("deadline_epoch")
        self.deadline = (time.monotonic() + max(0.0, deadline_epoch - time.time())
                         if isinstance(deadline_epoch, (int, float)) else None)
        self.snapshot = state.get("game_state")
        self.available_countries = list(state.get("countries", getattr(self, "available_countries", [])))
        self.players = {item["player_id"]: SimpleNamespace(**item)
                        for item in state.get("players", []) if isinstance(item, dict)}

    def sync_draft(self, _player_id: str, turn: int, commands: list[dict[str, Any]]) -> bool:
        return self.client.send("sync_draft", {"turn": turn, "commands": commands})

    def submit(self, _player_id: str, turn: int) -> bool:
        return self.client.send("submit", {"turn": turn})

    def unsubmit(self, _player_id: str, turn: int) -> bool:
        return self.client.send("unsubmit", {"turn": turn})


def apply_authoritative_snapshot(map_ref, snapshot: dict[str, Any]) -> None:
    """Replace mutable game state on a client map after a server broadcast."""
    if not isinstance(snapshot, dict):
        return
    # Message read and popup flags are local UI state, not game-state changes.
    # The server deliberately keeps inbound messages unread so a reconnecting
    # player can still discover them.  Retain a matching local message's flags
    # while replacing the authoritative diplomatic/game data, otherwise every
    # state broadcast makes an already handled offer look new again.
    local_message_state = {}
    player_country = getattr(map_ref, "player_country", None)
    current_player = getattr(map_ref, "nation_data", {}).get(player_country, {})
    for message in current_player.get("inbox", []) if isinstance(current_player, dict) else []:
        if not isinstance(message, dict):
            continue
        message_id = message.get("message_id")
        if message_id:
            local_message_state[message_id] = {
                key: message[key] for key in ("read", "popup_shown", "spectator_read")
                if key in message
            }

    nation_data = copy.deepcopy(snapshot.get("nation_data", map_ref.nation_data))
    incoming_player = nation_data.get(player_country, {}) if isinstance(nation_data, dict) else {}
    for message in incoming_player.get("inbox", []) if isinstance(incoming_player, dict) else []:
        if not isinstance(message, dict):
            continue
        saved_state = local_message_state.get(message.get("message_id"))
        if saved_state:
            message.update(saved_state)
    map_ref.nation_data = nation_data
    by_json_key = {province.get("json_key"): province for province in map_ref.map_data.values()}
    for json_key, update in snapshot.get("provinces", {}).items():
        province = by_json_key.get(json_key)
        if not province or not isinstance(update, dict):
            continue
        for key in ("owner", "cores", "units", "building_queue", "unit_queue", "orders", "resources", "buildings"):
            if key in update:
                province[key] = copy.deepcopy(update[key])
    date = snapshot.get("date", {})
    if isinstance(date, dict) and hasattr(map_ref, "time_manager"):
        map_ref.time_manager.day = date.get("day", map_ref.time_manager.day)
        map_ref.time_manager.month_index = date.get("month", map_ref.time_manager.month_index)
        map_ref.time_manager.year = date.get("year", map_ref.time_manager.year)
        map_ref.time_manager.total_turns = date.get("total_turns", map_ref.time_manager.total_turns)
    # These are local intent buffers.  The processed server snapshot has now
    # either applied or rejected them, so carrying them into the next turn
    # would replay an old subject edit or volunteer offer.
    if getattr(map_ref, "realtime_multiplayer", False):
        map_ref.realtime_pending_appearance_updates = {}
        map_ref.realtime_volunteer_drafts = {}
    map_ref.refresh_all_maps()


def materialize_map_bundle(bundle: dict[str, Any]) -> str:
    """Write a validated received bundle to a temporary map folder.

    The caller constructs ``Map`` from the returned path and then removes it;
    pygame keeps loaded surfaces and parsed geometry in memory.
    """
    if not isinstance(bundle, dict) or not isinstance(bundle.get("raw_map_data"), dict):
        raise RealtimeError("Invalid host map bundle.")
    images = bundle.get("images")
    if not isinstance(images, dict) or not {"terrain.png", "id_map.png"}.issubset(images):
        raise RealtimeError("Incomplete host map bundle.")
    destination = tempfile.mkdtemp(prefix="gd5-realtime-client-")
    try:
        Path(destination, "map_data.json").write_text(json.dumps(bundle["raw_map_data"]), encoding="utf-8")
        snapshot = bundle.get("snapshot")
        if not isinstance(snapshot, dict):
            raise RealtimeError("Invalid host game state.")
        Path(destination, "meta.json").write_text(json.dumps(snapshot), encoding="utf-8")
        allowed = {"terrain.png", "id_map.png", "political.png", "cores.png"}
        for name, encoded in images.items():
            if name not in allowed or not isinstance(encoded, str):
                raise RealtimeError("Invalid host image bundle.")
            raw = base64.b64decode(encoded, validate=True)
            if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
                raise RealtimeError("Host sent an invalid PNG asset.")
            Path(destination, name).write_bytes(raw)
    except Exception:
        import shutil
        shutil.rmtree(destination, ignore_errors=True)
        raise
    return destination


def create_match_certificate(directory: str | os.PathLike[str]) -> tuple[str, str, str]:
    """Create a short-lived self-signed TLS certificate and return its SHA-256 pin."""
    if IS_WEB:
        raise RealtimeError("Real-time multiplayer is available on desktop builds only.")
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.x509.oid import NameOID
        from datetime import datetime, timedelta, timezone
    except ImportError as exc:
        raise RealtimeError("The desktop cryptography dependency is unavailable.") from exc
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Greater Diplomacy 5 Real-Time")])
    certificate = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
                   .public_key(key.public_key()).serial_number(x509.random_serial_number())
                   .not_valid_before(datetime.now(timezone.utc) - timedelta(minutes=1))
                   .not_valid_after(datetime.now(timezone.utc) + timedelta(days=2))
                   .sign(key, hashes.SHA256()))
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    cert_path, key_path = directory / "realtime-cert.pem", directory / "realtime-key.pem"
    cert_bytes = certificate.public_bytes(serialization.Encoding.PEM)
    cert_path.write_bytes(cert_bytes)
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                           serialization.PrivateFormat.PKCS8,
                                           serialization.NoEncryption()))
    der = certificate.public_bytes(serialization.Encoding.DER)
    return str(cert_path), str(key_path), hashlib.sha256(der).hexdigest()


class RealtimeServer:
    """Small threaded TLS server that translates protocol messages to a session."""
    def __init__(self, session: RealtimeSession, certificate_path: str, key_path: str,
                 bind_address: str = "0.0.0.0"):
        self.session, self.certificate_path, self.key_path = session, certificate_path, key_path
        self.bind_address = bind_address
        self._listener: socket.socket | None = None
        self._tls_context: ssl.SSLContext | None = None
        self._stopped = threading.Event()
        self._clients: dict[str, socket.socket] = {}
        self._clients_lock = threading.Lock()
        # A state broadcast can originate from the host UI, a client worker,
        # or the timer thread.  TLS frames must never be written concurrently
        # to the same connection or their length prefixes can interleave.
        self._send_lock = threading.Lock()
        self._open_connections: set[socket.socket] = set()
        self._connection_lock = threading.Lock()
        self._relay_transport = None
        self._timer_started = False
        self._ping_lock = threading.Lock()
        self._pending_pings: dict[str, tuple[str, float]] = {}
        self.session.add_listener(self._broadcast_state)

    def start(self, port: int) -> int:
        if IS_WEB:
            raise RealtimeError("Real-time hosting is available on desktop builds only.")
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(self.certificate_path, self.key_path)
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((self.bind_address, port))
        listener.listen()
        # Keep the listening socket plain TCP and perform TLS handshakes in
        # per-client workers.  A port scanner or diagnostic ``nc`` probe must
        # never make the one accept loop exit with an SSL handshake error.
        self._listener = listener
        self._tls_context = context
        threading.Thread(target=self._accept_loop, daemon=True).start()
        self._start_timer()
        return self._listener.getsockname()[1]

    def start_relay(self, relay_transport: Any) -> None:
        """Expose this server through an outbound relay instead of a listener.

        The relay hands us a fresh raw byte stream for each player.  The normal
        per-player TLS handshake and authoritative message loop are unchanged.
        """
        if IS_WEB:
            raise RealtimeError("Real-time hosting is available on desktop builds only.")
        if self._listener or self._relay_transport:
            raise RealtimeError("The real-time server has already started.")
        self._tls_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self._tls_context.load_cert_chain(self.certificate_path, self.key_path)
        relay_transport.start(self._serve_connection)
        self._relay_transport = relay_transport
        self._start_timer()

    def _start_timer(self) -> None:
        if not self._timer_started:
            self._timer_started = True
            threading.Thread(target=self._timer_loop, daemon=True).start()

    @property
    def listening(self) -> bool:
        """Whether the server still owns its TCP listening socket."""
        return bool((self._listener is not None or self._relay_transport is not None)
                    and not self._stopped.is_set())

    def stop(self, reason: str | None = None) -> None:
        """Stop accepting clients and close every active connection.

        A normal socket close looks indistinguishable from a cable or relay
        failure to a guest. When the host deliberately ends a lobby or match,
        send a final protocol message first so clients can explain what
        happened instead of leaving a disabled Submit button with no context.
        """
        if self._stopped.is_set():
            return
        if reason:
            self._broadcast_shutdown(reason)
        self._stopped.set()
        if self._relay_transport:
            self._relay_transport.stop()
            self._relay_transport = None
        if self._listener:
            try: self._listener.close()
            except OSError: pass
        with self._clients_lock:
            for sock in self._clients.values():
                try: sock.close()
                except OSError: pass
            self._clients.clear()
        with self._connection_lock:
            connections, self._open_connections = list(self._open_connections), set()
        for connection in connections:
            try: connection.close()
            except OSError: pass

    def kick_player(self, host_id: str, player_id: str) -> None:
        """Remove one pre-game guest and immediately close their connection."""
        with self._clients_lock:
            connection = self._clients.pop(player_id, None)
        # Removing the connection first prevents the kicked client receiving a
        # normal state update that still looks like a healthy lobby transition.
        self.session.kick(host_id, player_id)
        if connection is None:
            return
        try:
            self._send_message(connection, "kicked", {
                "message": "The host removed you from the real-time lobby.",
            })
        except OSError:
            pass
        finally:
            try: connection.close()
            except OSError: pass

    def _broadcast_shutdown(self, reason: str) -> None:
        """Best-effort final notice before ``stop`` closes the TLS streams."""
        with self._clients_lock:
            clients = list(self._clients.items())
        for _player_id, connection in clients:
            try:
                self._send_message(connection, "shutdown", {"message": reason})
            except OSError:
                # A client already gone receives no worse outcome from this
                # than it would from the following socket close.
                pass

    def _accept_loop(self) -> None:
        assert self._listener is not None
        while not self._stopped.is_set():
            try:
                connection, _address = self._listener.accept()
            except OSError:
                break
            with self._connection_lock:
                self._open_connections.add(connection)
            threading.Thread(target=self._serve_connection, args=(connection,), daemon=True).start()

    def _timer_loop(self) -> None:
        last_status = 0.0
        last_ping = 0.0
        while not self._stopped.wait(0.1):
            self.session.tick()
            if time.monotonic() - last_ping >= 3.0:
                last_ping = time.monotonic()
                self._send_ping_requests()
            # Clients derive a smooth local countdown, but this heartbeat
            # periodically refreshes their server-clock/deadline estimate.
            if time.monotonic() - last_status >= 5.0:
                last_status = time.monotonic()
                self._broadcast_state(self.session.public_state())

    def _send_ping_requests(self) -> None:
        """Send server-originated probes so displayed ping cannot freeze the UI."""
        with self._clients_lock:
            clients = list(self._clients.items())
        for player_id, connection in clients:
            nonce = secrets.token_hex(8)
            with self._ping_lock:
                self._pending_pings[player_id] = (nonce, time.monotonic())
            try:
                self._send_message(connection, "ping", {"nonce": nonce})
            except OSError:
                with self._clients_lock:
                    self._clients.pop(player_id, None)
                self.session.disconnect(player_id)

    def _record_pong(self, player_id: str, nonce: Any) -> None:
        with self._ping_lock:
            expected = self._pending_pings.get(player_id)
            if not expected or not isinstance(nonce, str) or not secrets.compare_digest(expected[0], nonce):
                raise RealtimeError("Invalid ping response.")
            del self._pending_pings[player_id]
        self.session.set_ping(player_id, round((time.monotonic() - expected[1]) * 1000))

    def _serve_connection(self, connection: socket.socket) -> None:
        player_id: str | None = None
        raw_connection = connection
        with self._connection_lock:
            self._open_connections.add(raw_connection)
        try:
            assert self._tls_context is not None
            connection = self._tls_context.wrap_socket(connection, server_side=True)
            with self._connection_lock:
                self._open_connections.add(connection)
            while not self._stopped.is_set():
                message = read_message(connection)
                if message["session_id"] != self.session.session_id:
                    raise RealtimeError("Wrong match session.")
                try:
                    result, player_id = self._handle_message(player_id, message)
                except RealtimeError as exc:
                    # A valid client can make an invalid lobby/order request.
                    # That must be a request-level rejection, never a reason
                    # to disconnect them (notably for country-selection races).
                    self._send_message(connection, "error", {"message": str(exc)},
                                       message.get("request_id"))
                    continue
                if player_id:
                    # Register before acknowledging the join.  Once the
                    # client can see its lobby, it must also be eligible for
                    # a host-originated state broadcast in that same instant.
                    with self._clients_lock:
                        self._clients[player_id] = connection
                self._send_message(connection, "ok", result, message.get("request_id"))
        except (ConnectionError, OSError, ssl.SSLError, RealtimeError) as exc:
            try:
                self._send_message(connection, "error", {"message": str(exc)})
            except OSError:
                pass
        finally:
            if player_id:
                # ``kick_player`` already removed a lobby guest.  The stream
                # then reaches this cleanup path too, where disconnect must be
                # harmless rather than raising from a background thread.
                with self._clients_lock:
                    self._clients.pop(player_id, None)
                self.session.disconnect(player_id)
            try: connection.close()
            except OSError: pass
            with self._connection_lock:
                self._open_connections.discard(raw_connection)
                self._open_connections.discard(connection)

    def _handle_message(self, player_id: str | None, message: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
        action, payload = message["type"], message["payload"]
        if action == "join":
            player = self.session.join(payload.get("name", ""), payload.get("password", ""))
            result = {"player_id": player.player_id, "reconnect_token": player.reconnect_token,
                      "display_name": player.name,
                      "state": self.session.public_state()}
            bundle = getattr(self.session.driver, "map_bundle", None)
            if bundle:
                result["map_bundle"] = bundle()
            return result, player.player_id
        if action == "reconnect":
            player = self.session.reconnect(payload.get("reconnect_token", ""))
            result = {"player_id": player.player_id, "display_name": player.name,
                      "state": self.session.public_state()}
            bundle = getattr(self.session.driver, "map_bundle", None)
            if bundle:
                result["map_bundle"] = bundle()
            return result, player.player_id
        if not player_id:
            raise RealtimeError("Join before sending lobby or turn commands.")
        if action == "select_country": self.session.select_country(player_id, payload.get("country_id", ""))
        elif action == "ready": self.session.set_ready(player_id, bool(payload.get("ready")))
        elif action == "rename": self.session.rename(player_id, payload.get("name", ""))
        elif action == "kick": self.kick_player(player_id, payload.get("player_id", ""))
        elif action == "sync_draft": self.session.sync_draft(player_id, payload.get("turn"), payload.get("commands"))
        elif action == "submit": self.session.submit(player_id, payload.get("turn"))
        elif action == "unsubmit": self.session.unsubmit(player_id, payload.get("turn"))
        elif action == "pong": self._record_pong(player_id, payload.get("nonce"))
        elif action == "start": self.session.start(player_id)
        elif action == "end_match": self.session.end_match(player_id)
        else: raise RealtimeError("Unknown real-time message type.")
        return {"state": self.session.public_state()}, player_id

    def _broadcast_state(self, state: dict[str, Any]) -> None:
        with self._clients_lock:
            clients = list(self._clients.items())
        for player_id, connection in clients:
            try: self._send_message(connection, "state", state)
            except OSError:
                with self._clients_lock:
                    self._clients.pop(player_id, None)
                self.session.disconnect(player_id)

    def broadcast_map_bundle(self) -> None:
        """Send a newly selected lobby map to already-connected guests.

        The ordinary state message carries the new country/configuration list;
        this separate message carries the potentially large PNG/map bundle only
        when the host actually changes scenario, not on every lobby update.
        """
        bundle_factory = getattr(self.session.driver, "map_bundle", None)
        if not bundle_factory:
            return
        bundle = bundle_factory()
        with self._clients_lock:
            clients = list(self._clients.items())
        for player_id, connection in clients:
            try:
                self._send_message(connection, "map_bundle", {"map_bundle": bundle})
            except OSError:
                with self._clients_lock:
                    self._clients.pop(player_id, None)
                self.session.disconnect(player_id)

    def _send_message(self, connection: socket.socket, message_type: str,
                      payload: dict[str, Any], request_id: str | None = None) -> None:
        """Serialize every server write so framed TLS messages stay intact."""
        raw = encode_message(message_type, self.session.session_id, payload, request_id)
        with self._send_lock:
            connection.sendall(raw)


class RealtimeClient:
    """Threaded desktop client with a queue the pygame loop can poll safely."""
    def __init__(self, invite: dict[str, Any], timeout: float = 8.0):
        self.invite, self.timeout = invite, timeout
        self.socket: socket.socket | None = None
        self.events: queue.SimpleQueue[dict[str, Any]] = queue.SimpleQueue()
        self.player_id: str | None = None
        # This comes from the server's join/reconnect acknowledgement.  It is
        # never inferred from a local text field, which may be stale when a
        # reconnect restores an existing player identity.
        self.display_name: str | None = None
        self.reconnect_token: str | None = None
        self.disconnect_message: str | None = None
        self._send_lock = threading.Lock()
        self._outbound: queue.SimpleQueue[tuple[str, dict[str, Any]] | None] = queue.SimpleQueue()
        self._sender_lock = threading.Lock()
        self._sender_started = False
        self._disconnect_lock = threading.Lock()
        self._disconnect_notified = False
        self._receiver_lock = threading.Lock()
        self._receiver_started = False

    def connect(self) -> None:
        if IS_WEB:
            raise RealtimeError("Real-time multiplayer is available on desktop builds only.")
        if self.invite.get("transport") == "relay":
            from data.io.realtime_relay import connect_relay_client
            raw = connect_relay_client(self.invite, self.timeout)
        else:
            raw = socket.create_connection((self.invite["host"], self.invite["port"]), self.timeout)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname, context.verify_mode = False, ssl.CERT_NONE
        # Relay invites contain no direct host address; hostname validation is
        # disabled and the match certificate SHA-256 pin below is authoritative.
        secured = context.wrap_socket(raw, server_hostname=self.invite.get("host", self.invite.get("relay_host")))
        fingerprint = hashlib.sha256(secured.getpeercert(binary_form=True)).hexdigest()
        if not secrets.compare_digest(fingerprint.lower(), self.invite["fingerprint"].lower()):
            secured.close()
            raise RealtimeError("The server certificate does not match this invite.")
        # ``create_connection`` deliberately has a short setup timeout. It is
        # not a gameplay read deadline: an uneventful timed turn may have no
        # packets for longer than that. Use a blocking TLS stream thereafter.
        secured.settimeout(None)
        self.socket = secured

    def _start_receiver(self) -> None:
        """Start reads after the first request has fully left the TLS socket.

        On some Windows OpenSSL builds, immediately beginning a blocking read
        in a second thread while the main thread performs the first post-
        handshake write can intermittently stall that first write.  Joining is
        always the first protocol request, so delaying the reader by one send
        avoids that platform race without changing the wire protocol.
        """
        with self._receiver_lock:
            if self._receiver_started:
                return
            self._receiver_started = True
            threading.Thread(target=self._receive_loop, daemon=True).start()

    def send(self, message_type: str, payload: dict[str, Any]) -> bool:
        """Queue a request without ever blocking the pygame event loop."""
        if not self.socket:
            self._mark_disconnected("The connection to the real-time host has closed.")
            return False
        self._outbound.put((message_type, payload))
        self._start_sender()
        return True

    def _start_sender(self) -> None:
        with self._sender_lock:
            if self._sender_started:
                return
            self._sender_started = True
            threading.Thread(target=self._send_loop, daemon=True).start()

    def _send_loop(self) -> None:
        """Own the potentially blocking TLS writes away from input handling."""
        while True:
            request = self._outbound.get()
            if request is None:
                return
            message_type, payload = request
            with self._send_lock:
                connection = self.socket
                if connection is None:
                    return
                try:
                    connection.sendall(encode_message(message_type, self.invite["session"], payload))
                except (ConnectionError, OSError, ssl.SSLError) as exc:
                    self._mark_disconnected(str(exc))
                    return
            self._start_receiver()

    def poll(self) -> list[dict[str, Any]]:
        result = []
        while True:
            try: result.append(self.events.get_nowait())
            except queue.Empty: return result

    def close(self) -> None:
        with self._disconnect_lock:
            connection, self.socket = self.socket, None
        if connection:
            try: connection.close()
            except OSError: pass
        self._outbound.put(None)

    def _mark_disconnected(self, message: str) -> None:
        """Close and report a failed connection exactly once across both threads."""
        with self._disconnect_lock:
            if self._disconnect_notified:
                return
            self._disconnect_notified = True
            self.disconnect_message = message or "Disconnected from the real-time host."
            connection, self.socket = self.socket, None
        if connection:
            try: connection.close()
            except OSError: pass
        self._outbound.put(None)
        self.events.put({"type": "disconnected", "payload": {"message": self.disconnect_message}})

    def _receive_loop(self) -> None:
        try:
            while True:
                connection = self.socket
                if connection is None:
                    return
                try:
                    message = read_message(connection)
                except TimeoutError:
                    # Defensive compatibility with a socket restored by an
                    # older launcher/configuration that still has a timeout.
                    # A quiet connection is healthy; wait for its heartbeat.
                    continue
                if message["session_id"] != self.invite["session"]:
                    raise RealtimeError("Server changed match sessions.")
                if message["type"] in ("shutdown", "kicked"):
                    # A server shutdown is an intentional, user-facing end to
                    # the match (or the host explicitly removed this guest).
                    # Stop reading before TLS close is reported as a second,
                    # misleading generic disconnection.
                    with self._disconnect_lock:
                        self._disconnect_notified = True
                    self.events.put(message)
                    self.close()
                    return
                if message["type"] == "ping":
                    nonce = message.get("payload", {}).get("nonce")
                    if isinstance(nonce, str):
                        self.send("pong", {"nonce": nonce})
                    continue
                if message["type"] == "ok":
                    payload = message["payload"]
                    self.player_id = payload.get("player_id", self.player_id)
                    self.display_name = payload.get("display_name", self.display_name)
                    self.reconnect_token = payload.get("reconnect_token", self.reconnect_token)
                    self.map_bundle = payload.get("map_bundle", getattr(self, "map_bundle", None))
                elif message["type"] == "map_bundle":
                    payload = message["payload"]
                    self.map_bundle = payload.get("map_bundle", getattr(self, "map_bundle", None))
                self.events.put(message)
        except (ConnectionError, OSError, ssl.SSLError, RealtimeError) as exc:
            # A local, intentional close (such as leaving the lobby) is not a
            # second network failure to surface in the UI.
            if self.socket is not None:
                self._mark_disconnected(str(exc))
