"""Authoritative desktop real-time multiplayer primitives.

Tournament multiplayer intentionally remains in :mod:`multiplayer_io`.  This
module uses a small, versioned TLS protocol and has no file-format overlap with
the tournament system.
"""

# relay imports this module for protocol types. Keep relay imports local to avoid a cycle.


from __future__ import annotations

import shutil
from datetime import datetime, timedelta, timezone


from data.state_access import world_for, session_for
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
from data import migrations
from data.map import history_io
from data.platform import IS_WEB
from map_logic import politics
from map_logic.actions.player_actions import PlayerActions, PlayerActionError, collect_map_commands

from data.runtime_rules import rebuild
from data import queries
from data.state_access import replace_mapping
from map_logic.system32 import turn_processor, unit_events
from map_logic.ai import automation_logic
from map_logic.diplomacy import diplomacy_lifecycle, faction_records


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


RealtimeError = PlayerActionError


class GameVersionError(RealtimeError):
    """The other side runs a different game version. Snapshots are not version-converted."""


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
    from data.multiplayer.realtime.relay import relay_invite
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
        from data.multiplayer.realtime.relay import validate_relay_invite
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
    body = {"version": PROTOCOL_VERSION, "game_version": c.GAME_VERSION, "type": message_type,
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
    if message.get("game_version") != c.GAME_VERSION:
        # v46 and earlier did not send a game version.
        raise GameVersionError(
            f"The other side runs game version {message.get('game_version') or 'v46 or earlier'}. "
            f"This game is {c.GAME_VERSION}. Every player needs the same game version.")
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
            # Lightweight drivers can omit map setup. The game driver updates
            # its saved settings and ranges before the lobby broadcast.
            configure = getattr(self.driver, "configure_scenario_settings", None)
            if configure is not None:
                configure(settings)
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


class MapRealtimeDriver(PlayerActions):
    """Adapter that lets the existing map/turn logic run only on the server.

    The command schema deliberately contains no arbitrary map replacement.
    It covers every strategic player choice as a narrow intent command.  A
    client never supplies resources, turn counters, ownership, or a whole map
    record: the server derives those values from its own current map before it
    calls the normal turn processor.
    """
    def configure_scenario_settings(self, settings):
        """Apply host lobby ranges before snapshots or player commands use them."""
        self.world.scenario_settings = copy.deepcopy(settings)
        rebuild(self.map_ref)

    def start_game(self, countries: list[str]) -> None:
        self.session.active_players = list(countries)
        # A server is not a player: this prevents player automation/UI-only
        # behavior from giving its local process a country.
        self.session.player_country = "None"

    def process_turn(self, drafts: dict[str, list[dict[str, Any]]]) -> None:
        self.apply_validated_drafts(drafts)
        asyncio.run(turn_processor.prepare_turn(self.map_ref))
        asyncio.run(turn_processor.resolve_turn_logic(self.map_ref))
        # In a normal game this hook runs *after* resolution, so its orders
        # genuinely prepare the next turn.  The server has no local player and
        # therefore cannot use that single-player hook directly; replay it for
        # each opted-in real-time player at the same point in the turn instead.
        original_player = self.session.player_country
        try:
            for country_id in drafts:
                automation = self.world.nation_data.get(country_id, {}).get("automation", {})
                if not isinstance(automation, dict):
                    continue
                self.session.player_country = country_id
                if automation.get("construction"):
                    automation_logic.automate_player_construction(self.map_ref)
                if automation.get("movement"):
                    automation_logic.automate_player_movement(self.map_ref)
                if automation.get("research"):
                    automation_logic.automate_player_research(self.map_ref)
        finally:
            self.session.player_country = original_player

    def is_eliminated(self, country_id: str) -> bool:
        return country_id not in queries.get_politically_active_nations(
            self.world.map_data, self.world.nation_data)

    def snapshot(self) -> dict[str, Any]:
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
        return {"raw_map_data": copy.deepcopy(self.world.raw_json_data),
                "snapshot": self.snapshot(), "images": images}


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
    world_state = world_for(map_ref)
    if not isinstance(snapshot, dict):
        return
    settings = snapshot.get("scenario_settings")
    if isinstance(settings, dict):
        world_state.scenario_settings = copy.deepcopy(settings)
        rebuild(map_ref)
    # Badges are local preferences. Server broadcasts must not mark them unread again.
    local_event_reads = unit_events.saved_reads(map_ref) if hasattr(map_ref, "time_manager") else {}
    clear_selection = getattr(map_ref, "clear_map_unit_selection", None)
    if clear_selection:
        clear_selection()
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

    nation_data = copy.deepcopy(snapshot.get("nation_data", world_state.nation_data))
    if "nation_data" in snapshot:
        research_snapshot = {"nation_data": nation_data}
        if "research_years" in snapshot:
            research_snapshot["research_years"] = snapshot["research_years"]
        migrations.migrate_infantry_research(research_snapshot, queries.get_tech_tree(map_ref))
    diplomacy_lifecycle.normalize_diplomatic_records(nation_data)
    incoming_player = nation_data.get(player_country, {}) if isinstance(nation_data, dict) else {}
    for message in incoming_player.get("inbox", []) if isinstance(incoming_player, dict) else []:
        if not isinstance(message, dict):
            continue
        saved_state = local_message_state.get(message.get("message_id"))
        if saved_state:
            message.update(saved_state)
    replace_mapping(world_for(map_ref), "nation_data", nation_data)
    # Older snapshot fixtures use flat contexts without a declared faction mapping.
    if not hasattr(world_state, "factions"):
        world_state.factions = {}
    faction_records.restore(map_ref, snapshot.get("factions"))
    map_ref.country_economy_summaries = copy.deepcopy(snapshot.get("country_economy_summaries", {}))
    by_json_key = {province.get("json_key"): province for province in world_state.map_data.values()}
    for json_key, update in snapshot.get("provinces", {}).items():
        province = by_json_key.get(json_key)
        if not province or not isinstance(update, dict):
            continue
        for key in ("owner", "cores", "units", "building_queue", "unit_queue", "orders", "resources", "buildings"):
            if key in update:
                province[key] = copy.deepcopy(update[key])
    date = snapshot.get("date", {})
    if isinstance(date, dict) and hasattr(map_ref, "time_manager"):
        world_state.time_manager.day = date.get("day", world_state.time_manager.day)
        world_state.time_manager.month_index = date.get("month", world_state.time_manager.month_index)
        world_state.time_manager.year = date.get("year", world_state.time_manager.year)
        world_state.time_manager.total_turns = date.get("total_turns", world_state.time_manager.total_turns)
    if hasattr(map_ref, "time_manager"):
        unit_events.restore(map_ref, snapshot | {"unit_event_read_turns": local_event_reads})
    # These are local intent buffers.  The processed server snapshot has now
    # either applied or rejected them, so carrying them into the next turn
    # would replay an old subject edit or volunteer offer.
    if getattr(map_ref, "realtime_multiplayer", False):
        map_ref.realtime_pending_appearance_updates = {}
        map_ref.realtime_volunteer_drafts = {}
    if getattr(map_ref, "presentation_enabled", True):
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
        Path(destination, "map_data.json").write_text(
            history_io.dump_compact_text(bundle["raw_map_data"]), encoding="utf-8")
        snapshot = bundle.get("snapshot")
        if not isinstance(snapshot, dict):
            raise RealtimeError("Invalid host game state.")
        Path(destination, "meta.json").write_text(
            history_io.dump_compact_text(snapshot), encoding="utf-8")
        allowed = {"terrain.png", "id_map.png", "political.png", "cores.png"}
        for name, encoded in images.items():
            if name not in allowed or not isinstance(encoded, str):
                raise RealtimeError("Invalid host image bundle.")
            raw = base64.b64decode(encoded, validate=True)
            if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
                raise RealtimeError("Host sent an invalid PNG asset.")
            Path(destination, name).write_bytes(raw)
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise
    return destination


def _tls_context(protocol: int) -> ssl.SSLContext:
    """Create a match TLS context that refuses TLS 1.0 and 1.1.

    Both ends are always this game, so the minimum is set explicitly instead
    of trusting whichever Python or OpenSSL default a build happens to ship.
    """
    context = ssl.SSLContext(protocol)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


def create_match_certificate(directory: str | os.PathLike[str]) -> tuple[str, str, str]:
    """Create a short-lived self-signed TLS certificate and return its SHA-256 pin."""
    if IS_WEB:
        raise RealtimeError("Real-time multiplayer is available on desktop builds only.")
    try:
        # TLS certificates need the optional desktop cryptography package only when hosting.
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.x509.oid import NameOID
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
        context = _tls_context(ssl.PROTOCOL_TLS_SERVER)
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
        self._tls_context = _tls_context(ssl.PROTOCOL_TLS_SERVER)
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
                try:
                    message = read_message(connection)
                except GameVersionError:
                    # Tell the guest why before the connection closes. Older guests show this error too.
                    self._send_message(connection, "error", {"message": (
                        f"The host runs game version {c.GAME_VERSION}. "
                        "Every player needs the host's game version to join.")})
                    raise
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
                self._send_message(connection, "ok", self._project_payload(result, player_id), message.get("request_id"))
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
            try: self._send_message(connection, "state", self._project_payload({"state": state}, player_id)["state"])
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
                self._send_message(connection, "map_bundle", self._project_payload({"map_bundle": bundle}, player_id))
            except OSError:
                with self._clients_lock:
                    self._clients.pop(player_id, None)
                self.session.disconnect(player_id)

    def _project_payload(self, payload, player_id):
        """Guests never receive the host's canonical hidden state."""
        map_ref = getattr(self.session.driver, "map_ref", None)
        if map_ref is None:  # Protocol-only drivers have no game snapshot.
            return payload
        player = self.session.players.get(player_id)
        country = player.country_id if player else ""
        projected = copy.deepcopy(payload)
        state = projected.get("state")
        if state and "game_state" in state:
            state["game_state"] = queries.player_snapshot_projection(map_ref, state["game_state"], country)
        bundle = projected.get("map_bundle")
        if bundle:
            snapshot = dict(bundle["snapshot"], _raw_map_data=bundle["raw_map_data"])
            snapshot = queries.player_snapshot_projection(map_ref, snapshot, country)
            bundle["raw_map_data"] = snapshot.pop("_raw_map_data")
            bundle["snapshot"] = snapshot
        return projected

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
            from data.multiplayer.realtime.relay import connect_relay_client
            raw = connect_relay_client(self.invite, self.timeout)
        else:
            raw = socket.create_connection((self.invite["host"], self.invite["port"]), self.timeout)
        context = _tls_context(ssl.PROTOCOL_TLS_CLIENT)
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
