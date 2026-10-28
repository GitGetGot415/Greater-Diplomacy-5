"""Desktop convenience networking for real-time matches.

The authoritative game protocol stays in :mod:`realtime_multiplayer`.  This
module only makes direct hosting less fragile: it advertises a lobby on the
local network, finds those advertisements, and asks compatible home routers
for a temporary TCP mapping.  Every actual game connection remains TLS-pinned
by its normal invite, so discovery is never an authority or authentication
mechanism.

No third-party networking package is required.  UPnP IGD and NAT-PMP are both
small, well-documented local-router protocols and are used only after the
host explicitly opens a lobby.  A failed mapping is informational: manual
invites and manual port forwarding continue to work unchanged.
"""

from __future__ import annotations

import ipaddress
import json
import platform
import re
import socket
import struct
import subprocess
import threading
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as element_tree
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import urljoin

from data.platform import IS_WEB


LAN_DISCOVERY_PORT = 38476
LAN_DISCOVERY_INTERVAL_SECONDS = 1.5
LAN_MATCH_TTL_SECONDS = 6.0
MAX_DISCOVERY_BYTES = 4096
_DISCOVERY_TYPE = "gd5rt-lan-lobby"


@dataclass(frozen=True)
class LanMatch:
    """A lobby seen through a local broadcast, with the sender as its host."""

    invite: dict[str, Any]
    host_name: str
    scenario_name: str
    seen_at: float


@dataclass
class PortMappingResult:
    """The outcome of an automatic gateway mapping attempt.

    ``release`` is intentionally private.  It is kept by the host task so a
    successful temporary mapping is removed when the lobby ends.
    """

    protocol: str
    message: str
    external_address: str | None = None
    external_port: int | None = None
    gateway: str | None = None
    _release: Callable[[], None] | None = field(default=None, repr=False)

    @property
    def succeeded(self) -> bool:
        return bool(self.external_address and self.external_port and self._release)

    def release(self) -> None:
        if self._release is None:
            return
        release, self._release = self._release, None
        try:
            release()
        except OSError:
            # Router mappings are best-effort cleanup; a failed cleanup does
            # not affect the match and a NAT-PMP lease naturally expires.
            pass


def _valid_invite(invite: Any) -> dict[str, Any] | None:
    """Validate the non-secret invite shape without importing game UI code."""
    if not isinstance(invite, dict):
        return None
    if (invite.get("v") != 1 or not isinstance(invite.get("host"), str)
            or not invite["host"] or not isinstance(invite.get("port"), int)
            or not 1 <= invite["port"] <= 65535
            or not isinstance(invite.get("session"), str)
            or not isinstance(invite.get("fingerprint"), str)):
        return None
    return {"v": invite["v"], "host": invite["host"], "port": invite["port"],
            "session": invite["session"], "fingerprint": invite["fingerprint"]}


def make_lan_announcement(invite: dict[str, Any], host_name: str, scenario_name: str) -> bytes:
    """Serialize a bounded, non-secret UDP lobby announcement."""
    checked = _valid_invite(invite)
    if checked is None:
        raise ValueError("Invalid real-time invite for LAN discovery.")
    body = {"type": _DISCOVERY_TYPE, "invite": checked,
            "host_name": str(host_name)[:64], "scenario_name": str(scenario_name)[:96]}
    raw = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(raw) > MAX_DISCOVERY_BYTES:
        raise ValueError("LAN discovery announcement is too large.")
    return raw


def parse_lan_announcement(raw: bytes, sender_address: str,
                           now: float | None = None) -> LanMatch | None:
    """Safely turn one received broadcast into a local match.

    The sender address deliberately replaces the invite's advertised address.
    A host may have entered a public address for WAN friends, but LAN clients
    should always use the directly observed private route instead.
    """
    if len(raw) > MAX_DISCOVERY_BYTES:
        return None
    try:
        body = json.loads(raw.decode("utf-8"))
        if not isinstance(body, dict) or body.get("type") != _DISCOVERY_TYPE:
            return None
        invite = _valid_invite(body.get("invite"))
        source = ipaddress.ip_address(sender_address)
        if invite is None or source.version != 4 or source.is_unspecified or source.is_loopback:
            return None
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
        return None
    invite["host"] = str(source)
    host_name = body.get("host_name") if isinstance(body.get("host_name"), str) else "Host"
    scenario_name = body.get("scenario_name") if isinstance(body.get("scenario_name"), str) else "Match"
    return LanMatch(invite, host_name[:64], scenario_name[:96], time.monotonic() if now is None else now)


class LanMatchAdvertiser:
    """Broadcasts a lobby while it is open; it never listens for commands."""

    def __init__(self, invite: dict[str, Any], host_name: str, scenario_name: str,
                 port: int = LAN_DISCOVERY_PORT):
        self._announcement = make_lan_announcement(invite, host_name, scenario_name)
        self.port = port
        self._stopped = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if IS_WEB or self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="gd5-lan-advertise", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stopped.set()

    def set_host_name(self, host_name: str) -> None:
        """Refresh the display name carried by future LAN announcements."""
        self._set_announcement_field("host_name", host_name)

    def set_scenario_name(self, scenario_name: str) -> None:
        """Refresh the scenario label carried by future LAN announcements."""
        self._set_announcement_field("scenario_name", scenario_name)

    def _set_announcement_field(self, field: str, value: str) -> None:
        try:
            body = json.loads(self._announcement.decode("utf-8"))
            invite = body.get("invite") if isinstance(body, dict) else None
            host_name = body.get("host_name", "Host") if isinstance(body, dict) else "Host"
            scenario_name = body.get("scenario_name", "Match") if isinstance(body, dict) else "Match"
            if field == "host_name":
                host_name = value
            else:
                scenario_name = value
            self._announcement = make_lan_announcement(invite, host_name, scenario_name)
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
            # The existing advert remains usable if an unexpected local
            # mutation ever damaged it; a name refresh must not stop LAN play.
            pass

    def _run(self) -> None:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as broadcast:
                broadcast.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                while not self._stopped.is_set():
                    try:
                        broadcast.sendto(self._announcement, ("255.255.255.255", self.port))
                    except OSError:
                        # A machine can temporarily have no usable network;
                        # retrying later is friendlier than killing its lobby.
                        pass
                    self._stopped.wait(LAN_DISCOVERY_INTERVAL_SECONDS)
        except OSError:
            pass


class LanMatchBrowser:
    """Receives local lobby broadcasts for the Join screen."""

    def __init__(self, port: int = LAN_DISCOVERY_PORT, ttl: float = LAN_MATCH_TTL_SECONDS):
        self.port, self.ttl = port, ttl
        self._matches: dict[str, LanMatch] = {}
        self._lock = threading.Lock()
        self._stopped = threading.Event()
        self._socket: socket.socket | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if IS_WEB or self._thread is not None:
            return
        receiver = None
        try:
            receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            receiver.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            receiver.bind(("", self.port))
            receiver.settimeout(0.5)
        except OSError:
            if receiver:
                try:
                    receiver.close()
                except OSError:
                    pass
            return
        self._socket = receiver
        self._thread = threading.Thread(target=self._run, name="gd5-lan-discover", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stopped.set()
        if self._socket:
            try:
                self._socket.close()
            except OSError:
                pass

    def matches(self) -> list[LanMatch]:
        now = time.monotonic()
        with self._lock:
            self._matches = {session: match for session, match in self._matches.items()
                             if now - match.seen_at <= self.ttl}
            return sorted(self._matches.values(), key=lambda match: (match.host_name.casefold(), match.scenario_name.casefold()))

    def _run(self) -> None:
        assert self._socket is not None
        while not self._stopped.is_set():
            try:
                raw, sender = self._socket.recvfrom(MAX_DISCOVERY_BYTES + 1)
            except socket.timeout:
                continue
            except OSError:
                break
            match = parse_lan_announcement(raw, sender[0])
            if match:
                with self._lock:
                    self._matches[match.invite["session"]] = match


def _first_ipv4(text: str) -> str | None:
    match = re.search(r"(?<![\d.])((?:\d{1,3}\.){3}\d{1,3})(?![\d.])", text)
    if not match:
        return None
    try:
        value = ipaddress.ip_address(match.group(1))
        return str(value) if value.version == 4 else None
    except ValueError:
        return None


def default_gateway() -> str | None:
    """Return the primary IPv4 gateway without adding a platform dependency."""
    system = platform.system()
    try:
        if system == "Windows":
            output = subprocess.check_output(["ipconfig"], text=True, stderr=subprocess.DEVNULL,
                                             timeout=2, encoding="utf-8", errors="replace")
            lines = output.splitlines()
            for index, line in enumerate(lines):
                if "Default Gateway" not in line:
                    continue
                candidate = _first_ipv4(line)
                if candidate:
                    return candidate
                if index + 1 < len(lines):
                    candidate = _first_ipv4(lines[index + 1])
                    if candidate:
                        return candidate
        elif system == "Darwin":
            output = subprocess.check_output(["route", "-n", "get", "default"], text=True,
                                             stderr=subprocess.DEVNULL, timeout=2,
                                             encoding="utf-8", errors="replace")
            for line in output.splitlines():
                if line.strip().startswith("gateway:"):
                    return _first_ipv4(line)
        else:
            with open("/proc/net/route", encoding="utf-8") as routes:
                next(routes, None)
                for line in routes:
                    fields = line.split()
                    if len(fields) >= 3 and fields[1] == "00000000" and int(fields[3], 16) & 2:
                        return socket.inet_ntoa(struct.pack("<L", int(fields[2], 16)))
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    return None


def _soap_request(control_url: str, service_type: str, action: str, arguments: dict[str, str],
                  timeout: float) -> bytes:
    values = "".join(f"<{name}>{value}</{name}>" for name, value in arguments.items())
    body = ("<?xml version=\"1.0\"?>"
            "<s:Envelope xmlns:s=\"http://schemas.xmlsoap.org/soap/envelope/\" "
            "s:encodingStyle=\"http://schemas.xmlsoap.org/soap/encoding/\">"
            f"<s:Body><u:{action} xmlns:u=\"{service_type}\">{values}</u:{action}>"
            "</s:Body></s:Envelope>").encode("utf-8")
    request = urllib.request.Request(control_url, data=body, method="POST", headers={
        "Content-Type": "text/xml; charset=\"utf-8\"",
        "SOAPAction": f'"{service_type}#{action}"',
    })
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read(MAX_DISCOVERY_BYTES * 4)


def _upnp_service(timeout: float) -> tuple[str, str] | None:
    search = ("M-SEARCH * HTTP/1.1\r\nHOST:239.255.255.250:1900\r\n"
              "MAN:\"ssdp:discover\"\r\nMX:1\r\n"
              "ST:urn:schemas-upnp-org:device:InternetGatewayDevice:1\r\n\r\n").encode("ascii")
    locations: list[str] = []
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP) as discovery:
        discovery.settimeout(timeout)
        discovery.sendto(search, ("239.255.255.250", 1900))
        end = time.monotonic() + timeout
        while time.monotonic() < end and len(locations) < 4:
            try:
                response, _sender = discovery.recvfrom(8192)
            except socket.timeout:
                break
            headers = response.decode("iso-8859-1", "ignore").splitlines()
            location = next((line.split(":", 1)[1].strip() for line in headers
                             if line.lower().startswith("location:")), None)
            if location and location.startswith("http") and location not in locations:
                locations.append(location)
    for location in locations:
        try:
            with urllib.request.urlopen(location, timeout=timeout) as response:
                root = element_tree.fromstring(response.read(256 * 1024))
            for service in root.findall(".//{*}service"):
                service_type = service.findtext("{*}serviceType", "")
                control = service.findtext("{*}controlURL", "")
                if control and ("WANIPConnection" in service_type or "WANPPPConnection" in service_type):
                    return urljoin(location, control), service_type
        except (OSError, urllib.error.URLError, element_tree.ParseError):
            continue
    return None


def _soap_external_address(control_url: str, service_type: str, timeout: float) -> str | None:
    raw = _soap_request(control_url, service_type, "GetExternalIPAddress", {}, timeout)
    root = element_tree.fromstring(raw)
    address = root.findtext(".//{*}NewExternalIPAddress")
    try:
        parsed = ipaddress.ip_address(address or "")
        return str(parsed) if parsed.version == 4 else None
    except ValueError:
        return None


def try_upnp_port_mapping(local_address: str, port: int, timeout: float = 1.5) -> PortMappingResult:
    """Ask an IGD router to forward a TCP port to the host address."""
    try:
        service = _upnp_service(timeout)
        if service is None:
            return PortMappingResult("UPnP", "No UPnP Internet Gateway Device was found.")
        control_url, service_type = service
        external_address = _soap_external_address(control_url, service_type, timeout)
        _soap_request(control_url, service_type, "AddPortMapping", {
            "NewRemoteHost": "", "NewExternalPort": str(port), "NewProtocol": "TCP",
            "NewInternalPort": str(port), "NewInternalClient": local_address,
            "NewEnabled": "1", "NewPortMappingDescription": "Greater Diplomacy 5",
            "NewLeaseDuration": "0",
        }, timeout)

        def release() -> None:
            _soap_request(control_url, service_type, "DeletePortMapping", {
                "NewRemoteHost": "", "NewExternalPort": str(port), "NewProtocol": "TCP",
            }, timeout)

        if not external_address:
            return PortMappingResult("UPnP", "UPnP added a mapping but the router did not report a public IPv4 address.",
                                     _release=release)

        return PortMappingResult("UPnP", "UPnP created a TCP mapping.", external_address, port,
                                 _release=release)
    except (OSError, urllib.error.URLError, urllib.error.HTTPError, element_tree.ParseError, ValueError) as exc:
        return PortMappingResult("UPnP", f"UPnP could not create a mapping: {exc}")


def _natpmp_request(gateway: str, request: bytes, timeout: float) -> bytes:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
        client.settimeout(timeout)
        client.sendto(request, (gateway, 5351))
        response, sender = client.recvfrom(64)
        if sender[0] != gateway:
            raise OSError("NAT-PMP reply came from an unexpected gateway.")
        return response


def try_natpmp_port_mapping(local_address: str, port: int, gateway: str | None = None,
                            timeout: float = 1.5) -> PortMappingResult:
    """Ask a NAT-PMP gateway for a two-hour TCP mapping."""
    gateway = gateway or default_gateway()
    if not gateway:
        return PortMappingResult("NAT-PMP", "Could not determine the local network gateway.")
    try:
        address_reply = _natpmp_request(gateway, b"\x00\x00", timeout)
        if len(address_reply) < 12 or address_reply[1] != 128 or struct.unpack("!H", address_reply[2:4])[0] != 0:
            raise OSError("NAT-PMP gateway rejected the public-address request.")
        external_address = socket.inet_ntoa(address_reply[8:12])
        request = struct.pack("!BBHHHI", 0, 2, 0, port, port, 7200)
        reply = _natpmp_request(gateway, request, timeout)
        if len(reply) < 16 or reply[1] != 130 or struct.unpack("!H", reply[2:4])[0] != 0:
            raise OSError("NAT-PMP gateway rejected the TCP mapping request.")
        external_port = struct.unpack("!H", reply[10:12])[0]

        def release() -> None:
            _natpmp_request(gateway, struct.pack("!BBHHHI", 0, 2, 0, port, external_port, 0), timeout)

        return PortMappingResult("NAT-PMP", "NAT-PMP created a two-hour TCP mapping.", external_address,
                                 external_port, gateway, release)
    except OSError as exc:
        return PortMappingResult("NAT-PMP", f"NAT-PMP could not create a mapping: {exc}", gateway=gateway)


def automatic_tcp_port_mapping(local_address: str, port: int, timeout: float = 1.5) -> PortMappingResult:
    """Try UPnP first, then NAT-PMP.  Neither failure changes the lobby."""
    upnp = try_upnp_port_mapping(local_address, port, timeout)
    if upnp.succeeded:
        return upnp
    # Do not leave a permanent UPnP entry behind merely because the router
    # could not provide the public address needed to make a usable invite.
    upnp.release()
    natpmp = try_natpmp_port_mapping(local_address, port, timeout=timeout)
    if natpmp.succeeded:
        return natpmp
    return PortMappingResult("none", f"Automatic router mapping was unavailable. {upnp.message} {natpmp.message}",
                             gateway=natpmp.gateway)


class AutomaticPortMappingTask:
    """Run router discovery away from the pygame frame loop and retain its lease."""

    def __init__(self, local_address: str, port: int, timeout: float = 1.5):
        self.local_address, self.port, self.timeout = local_address, port, timeout
        self._result: PortMappingResult | None = None
        self._lock = threading.Lock()
        self._stopped = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if IS_WEB or self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="gd5-port-map", daemon=True)
        self._thread.start()

    def result(self) -> PortMappingResult | None:
        with self._lock:
            return self._result

    def stop(self) -> None:
        self._stopped.set()
        result = self.result()
        if result:
            result.release()

    def _run(self) -> None:
        result = automatic_tcp_port_mapping(self.local_address, self.port, self.timeout)
        with self._lock:
            self._result = result
        if self._stopped.is_set():
            result.release()


def is_public_ipv4(address: str | None) -> bool:
    """True only for an address that can plausibly receive internet traffic."""
    try:
        parsed = ipaddress.ip_address(address or "")
        return parsed.version == 4 and parsed.is_global
    except ValueError:
        return False


def host_network_diagnostics(local_address: str, port: int, listener_running: bool,
                             mapping: PortMappingResult | None) -> str:
    """Return concise, actionable host status without claiming an external probe."""
    lines = [f"Game server: {'listening' if listener_running else 'not listening'} on TCP {port}.",
             f"Local address: {local_address}."]
    if mapping is None:
        lines.append("Automatic router mapping is still checking UPnP and NAT-PMP.")
    elif mapping.succeeded and is_public_ipv4(mapping.external_address):
        lines.append(f"{mapping.protocol} mapped public {mapping.external_address}:{mapping.external_port}.")
        lines.append("The router accepted the mapping. Test from an external network to confirm ISP reachability.")
    elif mapping and mapping.succeeded:
        lines.append(f"{mapping.protocol} mapped {mapping.external_address}:{mapping.external_port}, but that is not a public IPv4 address.")
        lines.append("This usually means double NAT or ISP CGNAT; manual forwarding on this router alone cannot fix it.")
    else:
        lines.append(mapping.message if mapping else "Automatic router mapping is unavailable.")
        if mapping and mapping.gateway:
            lines.append(f"Local gateway checked: {mapping.gateway}.")
        lines.append("LAN discovery still works. For WAN, enable UPnP/NAT-PMP or use manual forwarding/a relay.")
    lines.append("If LAN players cannot find or join this lobby, allow the game through the host firewall "
                 "for TCP %d and UDP %d, then disable guest/client isolation." % (port, LAN_DISCOVERY_PORT))
    return "\n\n".join(lines)
