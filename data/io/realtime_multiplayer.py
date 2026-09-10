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


def decode_invite(value: str) -> dict[str, Any]:
    try:
        raw = value.strip()
        if raw.startswith("gd5rt:"):
            raw = raw[6:]
        raw += "=" * (-len(raw) % 4)
        data = json.loads(base64.urlsafe_b64decode(raw.encode()).decode("utf-8"))
    except Exception as exc:
        raise RealtimeError("Invalid real-time invite code.") from exc
    if (not isinstance(data, dict) or data.get("v") != PROTOCOL_VERSION
            or not isinstance(data.get("host"), str)
            or not isinstance(data.get("port"), int)
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
        records[invite["session"]] = {"token": token, "name": display_name,
                                       "host": invite["host"], "port": invite["port"],
                                       "fingerprint": invite["fingerprint"]}
        path.write_text(json.dumps(records, indent=2), encoding="utf-8")
    except OSError:
        return ""
    return str(path)


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
        if not isinstance(self.max_players, int) or not 1 <= self.max_players <= country_count:
            raise RealtimeError("Player capacity must fit the selected scenario.")
        if not isinstance(self.max_turns, int) or not 1 <= self.max_turns <= 100:
            raise RealtimeError("Maximum turns must be between 1 and 100.")
        if not isinstance(self.turn_minutes, int) or not 1 <= self.turn_minutes <= 240:
            raise RealtimeError("Turn time must be between 1 and 240 minutes.")
        if not isinstance(self.port, int) or not 1024 <= self.port <= 65535:
            raise RealtimeError("Port must be between 1024 and 65535.")


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
        self._password_salt = secrets.token_bytes(16)
        self._password_digest = _password_hash(password, self._password_salt) if password else None
        self.host_id = self._new_player(host_name).player_id

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
                    self._broadcast()
                    return copy.copy(player)
        raise RealtimeError("Invalid reconnect token.")

    def disconnect(self, player_id: str) -> None:
        with self.lock:
            player = self._player(player_id)
            player.connected = False
            if self.phase == "LOBBY":
                player.ready = False
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
                "session_id": self.session_id, "phase": self.phase,
                "turn": self.turn_number, "max_turns": self.config.max_turns,
                "turn_minutes": self.config.turn_minutes, "deadline_monotonic": self.deadline,
                "deadline_epoch": self.deadline_epoch,
                "server_monotonic": self.clock(), "processing": self._processing,
                "game_over_reason": self.game_over_reason,
                "submitted_count": submitted, "active_count": active,
                "players": [{"player_id": p.player_id, "name": p.name, "country_id": p.country_id,
                             "ready": p.ready, "connected": p.connected,
                             "submitted": p.submitted, "eliminated": p.eliminated}
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
                "players": [{"name": p.name, "country_id": p.country_id,
                             "eliminated": p.eliminated} for p in self.players.values()],
            }


class MapRealtimeDriver:
    """Adapter that lets the existing map/turn logic run only on the server.

    The command schema deliberately contains no arbitrary map replacement.
    It covers normal unit orders, owned production queues, and research
    selection. Additional UI domains can add explicit commands without
    widening trust.
    """
    _UNIT_MUTABLE_KEYS = {"order", "name", "combat_stance"}
    _AUTOMATION_KEYS = {"construction", "movement", "research"}
    _APPEARANCE_KEYS = {"name", "adjective", "leader_name", "leader_title",
                        "flag_data", "portrait_data", "color"}

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
        for command in commands:
            if not isinstance(command, dict):
                raise RealtimeError("Invalid order command.")
            kind = command.get("type")
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
            elif kind == "country_appearance":
                canonical.append(self._validate_country_appearance(country_id, command))
            else:
                raise RealtimeError("That order type is not supported by the server.")
        return canonical

    def _country(self, country_id: str) -> dict[str, Any]:
        country = self.map_ref.nation_data.get(country_id)
        if not isinstance(country, dict):
            raise RealtimeError("Unknown player country.")
        return country

    def _validate_country_preferences(self, country_id: str, command: dict[str, Any]) -> dict[str, Any]:
        """Validate the regular politics/automation controls for one country."""
        self._country(country_id)
        drift = command.get("political_drift", 0)
        automation = command.get("automation", {})
        if not isinstance(drift, int) or drift not in (-1, 0, 1):
            raise RealtimeError("Invalid political direction.")
        if not isinstance(automation, dict) or set(automation) - self._AUTOMATION_KEYS:
            raise RealtimeError("Invalid automation settings.")
        if any(not isinstance(value, bool) for value in automation.values()):
            raise RealtimeError("Invalid automation settings.")
        return {"type": "country_preferences", "political_drift": drift,
                "automation": {key: bool(automation.get(key, False))
                               for key in self._AUTOMATION_KEYS}}

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

    def _province(self, province_id: Any):
        try:
            return self.map_ref.id_to_province[int(province_id)]
        except (KeyError, TypeError, ValueError) as exc:
            raise RealtimeError("Unknown province in order.") from exc

    def _validate_unit_order(self, country_id: str, command: dict[str, Any]) -> dict[str, Any]:
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
        # A destination is checked against the same central movement rules the
        # order UI uses. Other order shapes are still bounded by the processor.
        if isinstance(order, dict) and "destination" in order:
            destination = self._province(order["destination"])
            from data import queries
            if not queries.can_land_units_enter(country_id, destination, self.map_ref.nation_data):
                raise RealtimeError("That unit cannot enter the selected province.")
        return {"type": "unit_order", "province_id": province["id"],
                "unit_index": index, "order": copy.deepcopy(order)}

    def _validate_queue(self, country_id: str, command: dict[str, Any]) -> dict[str, Any]:
        province = self._province(command.get("province_id"))
        if province.get("owner") != country_id:
            raise RealtimeError("Players may only change queues in their own provinces.")
        queue_type = command.get("queue")
        items = command.get("items")
        if queue_type not in ("building_queue", "unit_queue") or not isinstance(items, list):
            raise RealtimeError("Invalid province queue.")
        # The existing queue processor remains the final authority on the
        # queue's contents; bounded JSON prevents a forged arbitrary object.
        if len(items) > 100 or any(not isinstance(item, dict) for item in items):
            raise RealtimeError("Invalid province queue contents.")
        return {"type": "province_queue", "province_id": province["id"],
                "queue": queue_type, "items": copy.deepcopy(items)}

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
            for command in commands:
                if command["type"] == "unit_order":
                    province = self._province(command["province_id"])
                    unit = province["units"][command["unit_index"]]
                    if command["order"] is None:
                        unit.pop("order", None)
                    else:
                        unit["order"] = copy.deepcopy(command["order"])
                elif command["type"] == "province_queue":
                    province = self._province(command["province_id"])
                    province[command["queue"]] = copy.deepcopy(command["items"])
                elif command["type"] == "research_queue":
                    country_data = self.map_ref.nation_data[country_id]
                    country_data["research_queue"] = copy.deepcopy(command["projects"])
                    country_data["research_progress"] = copy.deepcopy(command["research_progress"])
                elif command["type"] == "country_preferences":
                    country_data = self.map_ref.nation_data[country_id]
                    country_data["political_drift"] = command["political_drift"]
                    country_data["automation"] = copy.deepcopy(command["automation"])
                elif command["type"] == "country_appearance":
                    country_data = self.map_ref.nation_data[country_id]
                    country_data.update(copy.deepcopy(command["appearance"]))
                    self.map_ref.nation_colors[country_id] = tuple(country_data["color"])
        # The normal turn processor's player-automation hook expects one local
        # player. A real-time server has none, so run each opted-in human here
        # under the same helpers before the shared turn simulation begins.
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
        from map_logic.turn_processing import turn_processor
        asyncio.run(turn_processor.prepare_turn(self.map_ref))
        asyncio.run(turn_processor.resolve_turn_logic(self.map_ref))

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

    This deliberately reads only order/queue/research choices, never mutable
    combat, resource, or research-progress fields from the client map.
    """
    commands: list[dict[str, Any]] = []
    for province in map_ref.map_data.values():
        for index, unit in enumerate(province.get("units", [])):
            if unit.get("owner") == country_id and "order" in unit:
                commands.append({"type": "unit_order", "province_id": province["id"],
                                 "unit_index": index, "order": copy.deepcopy(unit["order"])})
        if province.get("owner") == country_id:
            for queue_name in ("building_queue", "unit_queue"):
                if province.get(queue_name):
                    commands.append({"type": "province_queue", "province_id": province["id"],
                                     "queue": queue_name,
                                     "items": copy.deepcopy(province[queue_name])})
    country_data = map_ref.nation_data.get(country_id, {})
    research_queue = country_data.get("research_queue", []) if isinstance(country_data, dict) else []
    tech_names = [project.get("tech_name") for project in research_queue
                  if isinstance(project, dict) and isinstance(project.get("tech_name"), str)]
    # Include an empty selection too: pausing every project must be a real
    # draft change rather than silently preserving the server's old queue.
    commands.append({"type": "research_queue", "tech_names": tech_names})
    commands.append({"type": "country_preferences",
                     "political_drift": country_data.get("political_drift", 0),
                     "automation": copy.deepcopy(country_data.get("automation", {}))})
    commands.append({"type": "country_appearance", "appearance": {
        key: copy.deepcopy(country_data.get(key, "DEFAULT" if key.endswith("_data") else [] if key == "color" else ""))
        for key in MapRealtimeDriver._APPEARANCE_KEYS}})
    return commands


class RemoteSessionView:
    """Client-side, non-authoritative projection of server status/state."""
    def __init__(self, client: "RealtimeClient", state: dict[str, Any], player_id: str):
        self.client, self.player_id = client, player_id
        self.players: dict[str, SimpleNamespace] = {}
        self.update(state)

    def update(self, state: dict[str, Any]) -> None:
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

    def sync_draft(self, _player_id: str, turn: int, commands: list[dict[str, Any]]) -> None:
        self.client.send("sync_draft", {"turn": turn, "commands": commands})

    def submit(self, _player_id: str, turn: int) -> None:
        self.client.send("submit", {"turn": turn})

    def unsubmit(self, _player_id: str, turn: int) -> None:
        self.client.send("unsubmit", {"turn": turn})


def apply_authoritative_snapshot(map_ref, snapshot: dict[str, Any]) -> None:
    """Replace mutable game state on a client map after a server broadcast."""
    if not isinstance(snapshot, dict):
        return
    map_ref.nation_data = copy.deepcopy(snapshot.get("nation_data", map_ref.nation_data))
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
        self._stopped = threading.Event()
        self._clients: dict[str, socket.socket] = {}
        self._clients_lock = threading.Lock()
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
        self._listener = context.wrap_socket(listener, server_side=True)
        threading.Thread(target=self._accept_loop, daemon=True).start()
        threading.Thread(target=self._timer_loop, daemon=True).start()
        return self._listener.getsockname()[1]

    def stop(self) -> None:
        self._stopped.set()
        if self._listener:
            try: self._listener.close()
            except OSError: pass
        with self._clients_lock:
            for sock in self._clients.values():
                try: sock.close()
                except OSError: pass
            self._clients.clear()

    def _accept_loop(self) -> None:
        assert self._listener is not None
        while not self._stopped.is_set():
            try:
                connection, _address = self._listener.accept()
            except (OSError, ssl.SSLError):
                break
            threading.Thread(target=self._serve_connection, args=(connection,), daemon=True).start()

    def _timer_loop(self) -> None:
        last_status = 0.0
        while not self._stopped.wait(0.1):
            self.session.tick()
            # Clients derive a smooth local countdown, but this heartbeat
            # periodically refreshes their server-clock/deadline estimate.
            if time.monotonic() - last_status >= 5.0:
                last_status = time.monotonic()
                self._broadcast_state(self.session.public_state())

    def _serve_connection(self, connection: socket.socket) -> None:
        player_id: str | None = None
        try:
            while not self._stopped.is_set():
                message = read_message(connection)
                if message["session_id"] != self.session.session_id:
                    raise RealtimeError("Wrong match session.")
                result, player_id = self._handle_message(player_id, message)
                connection.sendall(encode_message("ok", self.session.session_id, result,
                                                  message.get("request_id")))
                if player_id:
                    with self._clients_lock:
                        self._clients[player_id] = connection
        except (ConnectionError, OSError, ssl.SSLError, RealtimeError) as exc:
            try:
                connection.sendall(encode_message("error", self.session.session_id,
                                                  {"message": str(exc)}))
            except OSError:
                pass
        finally:
            if player_id:
                self.session.disconnect(player_id)
                with self._clients_lock:
                    self._clients.pop(player_id, None)
            try: connection.close()
            except OSError: pass

    def _handle_message(self, player_id: str | None, message: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
        action, payload = message["type"], message["payload"]
        if action == "join":
            player = self.session.join(payload.get("name", ""), payload.get("password", ""))
            result = {"player_id": player.player_id, "reconnect_token": player.reconnect_token,
                      "state": self.session.public_state()}
            bundle = getattr(self.session.driver, "map_bundle", None)
            if bundle:
                result["map_bundle"] = bundle()
            return result, player.player_id
        if action == "reconnect":
            player = self.session.reconnect(payload.get("reconnect_token", ""))
            result = {"player_id": player.player_id, "state": self.session.public_state()}
            bundle = getattr(self.session.driver, "map_bundle", None)
            if bundle:
                result["map_bundle"] = bundle()
            return result, player.player_id
        if not player_id:
            raise RealtimeError("Join before sending lobby or turn commands.")
        if action == "select_country": self.session.select_country(player_id, payload.get("country_id", ""))
        elif action == "ready": self.session.set_ready(player_id, bool(payload.get("ready")))
        elif action == "rename": self.session.rename(player_id, payload.get("name", ""))
        elif action == "sync_draft": self.session.sync_draft(player_id, payload.get("turn"), payload.get("commands"))
        elif action == "submit": self.session.submit(player_id, payload.get("turn"))
        elif action == "unsubmit": self.session.unsubmit(player_id, payload.get("turn"))
        elif action == "start": self.session.start(player_id)
        elif action == "end_match": self.session.end_match(player_id)
        else: raise RealtimeError("Unknown real-time message type.")
        return {"state": self.session.public_state()}, player_id

    def _broadcast_state(self, state: dict[str, Any]) -> None:
        raw = encode_message("state", self.session.session_id, state)
        with self._clients_lock:
            clients = list(self._clients.items())
        for player_id, connection in clients:
            try: connection.sendall(raw)
            except OSError:
                self.session.disconnect(player_id)


class RealtimeClient:
    """Threaded desktop client with a queue the pygame loop can poll safely."""
    def __init__(self, invite: dict[str, Any], timeout: float = 8.0):
        self.invite, self.timeout = invite, timeout
        self.socket: socket.socket | None = None
        self.events: queue.SimpleQueue[dict[str, Any]] = queue.SimpleQueue()
        self.player_id: str | None = None
        self.reconnect_token: str | None = None
        self._send_lock = threading.Lock()

    def connect(self) -> None:
        if IS_WEB:
            raise RealtimeError("Real-time multiplayer is available on desktop builds only.")
        raw = socket.create_connection((self.invite["host"], self.invite["port"]), self.timeout)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname, context.verify_mode = False, ssl.CERT_NONE
        secured = context.wrap_socket(raw, server_hostname=self.invite["host"])
        fingerprint = hashlib.sha256(secured.getpeercert(binary_form=True)).hexdigest()
        if not secrets.compare_digest(fingerprint.lower(), self.invite["fingerprint"].lower()):
            secured.close()
            raise RealtimeError("The server certificate does not match this invite.")
        self.socket = secured
        threading.Thread(target=self._receive_loop, daemon=True).start()

    def send(self, message_type: str, payload: dict[str, Any]) -> None:
        if not self.socket: raise RealtimeError("Not connected to a real-time server.")
        with self._send_lock:
            self.socket.sendall(encode_message(message_type, self.invite["session"], payload))

    def poll(self) -> list[dict[str, Any]]:
        result = []
        while True:
            try: result.append(self.events.get_nowait())
            except queue.Empty: return result

    def close(self) -> None:
        if self.socket:
            try: self.socket.close()
            except OSError: pass
            self.socket = None

    def _receive_loop(self) -> None:
        try:
            while self.socket:
                message = read_message(self.socket)
                if message["session_id"] != self.invite["session"]:
                    raise RealtimeError("Server changed match sessions.")
                if message["type"] == "ok":
                    payload = message["payload"]
                    self.player_id = payload.get("player_id", self.player_id)
                    self.reconnect_token = payload.get("reconnect_token", self.reconnect_token)
                    self.map_bundle = payload.get("map_bundle", getattr(self, "map_bundle", None))
                self.events.put(message)
        except (ConnectionError, OSError, ssl.SSLError, RealtimeError) as exc:
            self.events.put({"type": "disconnected", "payload": {"message": str(exc)}})
