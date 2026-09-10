"""Desktop real-time multiplayer setup and lobby screens."""

import copy
import os
import tempfile
import secrets
import threading
import webbrowser

import pygame

import data.constants as c
from data import queries
from data.io.realtime_multiplayer import (
    DEFAULT_MAX_TURNS, DEFAULT_PORT, DEFAULT_TURN_MINUTES, MapRealtimeDriver,
    RealtimeClient, RealtimeConfig, RealtimeError, RealtimeServer, RealtimeSession, RemoteSessionView,
    default_advertised_address,
    persist_reconnect_token,
    create_match_certificate, decode_invite, encode_invite,
    encode_relay_invite,
)
from data.io.realtime_networking import (
    AutomaticPortMappingTask, LanMatchAdvertiser, LanMatchBrowser,
    host_network_diagnostics, is_public_ipv4,
)
from data.io.realtime_relay import (
    DEFAULT_RELAY_REGION, DEFAULT_RELAY_SIZE, DigitalOceanRelayTask,
    RelayHostTransport, destroy_temporary_relay,
)
from data.platform import IS_WEB
from gameState import GameState
from ui import confirm_dialog
from ui_elements import Button, make_back_button


def _delete_relay_quietly(token, droplet_id, firewall_id=None):
    """Best-effort background cleanup; a provider dashboard remains fallback."""
    try:
        destroy_temporary_relay(token, droplet_id, firewall_id)
    except RealtimeError:
        # The UI has already explained that a failed deletion can be retried
        # from the provider dashboard; never freeze map shutdown on the API.
        pass


def _scenario_entries():
    entries = []
    for label, directory in (("Historical", c.SCENARIOS_HISTORICAL_DIR),
                             ("Alternate", c.SCENARIOS_ALTERNATE_DIR),
                             ("Custom", c.SCENARIOS_CUSTOM_DIR),
                             ("Base Map", c.BASE_MAPS_DIR)):
        if not os.path.isdir(directory):
            continue
        for name in sorted(os.listdir(directory)):
            path = os.path.join(directory, name)
            if os.path.isdir(path) and os.path.isfile(os.path.join(path, "map_data.json")):
                entries.append((f"{label}: {name}", path))
    return entries


class Realtime_Host_Setup(GameState):
    back_state = "REAL_TIME_MULTIPLAYER"
    title = "Host Real-Time Match"
    title_y = 35

    def __init__(self):
        super().__init__()
        self.bg_color = (12, 28, 50)
        self.scenario_path = os.path.join(c.SCENARIOS_HISTORICAL_DIR, "1939")
        self.settings = copy.deepcopy(queries.get_scenario_settings() or {})
        self.host_name = "Host"
        self.password = ""
        self.address = default_advertised_address()
        self.local_address = self.address
        self._address_is_detected = True
        self.port, self.capacity = DEFAULT_PORT, 4
        self.max_turns, self.turn_minutes = DEFAULT_MAX_TURNS, DEFAULT_TURN_MINUTES
        # Tokens are intentionally session-memory only.  A player can create
        # a fresh personal-access token for a later match if they restart.
        self.relay_enabled = False
        self.relay_token = ""
        self.relay_region, self.relay_size = DEFAULT_RELAY_REGION, DEFAULT_RELAY_SIZE
        self.refresh_ui()

    def refresh_ui(self):
        scenario_label = os.path.basename(self.scenario_path) if self.scenario_path else "Select Scenario"
        # Keep every setup control visible at ordinary desktop resolutions.
        # A single vertical stack made the bottom controls inaccessible.
        self.elements = [
            Button("centered-150", 120, "medium", "blue", f"Scenario: {scenario_label}",
                   lambda: self.go_to("REALTIME_SCENARIO_SELECT")),
            Button("centered-150", 200, "medium", "blue", f"Host Name: {self.host_name}", self.edit_name),
            Button("centered-150", 280, "medium", "blue", f"Advertised Address: {self.address}", self.edit_address),
            Button("centered-150", 360, "medium", "blue", f"Port: {self.port}", self.edit_port),
            Button("centered-150", 440, "medium", "blue", f"Lobby Password: {'SET' if self.password else 'None'}", self.edit_password),
            Button("centered+150", 120, "medium", "purple", f"Player Capacity: {self.capacity}", self.edit_capacity),
            Button("centered+150", 200, "medium", "purple", f"Maximum Turns: {self.max_turns}", self.edit_turns),
            Button("centered+150", 280, "medium", "purple", f"Turn Time: {self.turn_minutes} minutes", self.edit_minutes),
            Button("centered+150", 360, "medium", "pink", "Scenario Settings", self.edit_settings),
            Button("centered+150", 440, "medium", "green", "Open Lobby", self.open_lobby),
            Button("centered-150", 520, "medium", "purple",
                   "Temporary Relay: ON" if self.relay_enabled else "Temporary Relay: Off",
                   lambda: self.go_to("REALTIME_RELAY_SETUP")),
            Button("centered+150", 520, "medium", "light_blue", "Networking Help", self.show_network_help),
            make_back_button(self.exit_screen),
        ]

    def show_network_help(self):
        confirm_dialog.show_info(
            "Real-Time Multiplayer Help",
            "LAN (same router): hosts advertise open lobbies automatically. Players choose Find LAN Matches "
            "and click the lobby; no address, port, or copied invite is needed. A LAN invite remains available "
            "as a fallback. Guest Wi-Fi, VPNs, and Wi-Fi client isolation can block local connections.\n\n"
            "Temporary relay: choose Temporary Relay on the host setup screen to create a short-lived personal "
            "DigitalOcean relay. It needs a DigitalOcean account/API token but no router forwarding; delete it "
            "when the match ends to stop the Droplet allocation charge.\n\n"
            "Direct WAN hosting: after Open Lobby, the game automatically tries UPnP and NAT-PMP router mapping. "
            "Use Networking Status to see the result and copy the Internet Invite when mapping succeeds. "
            "Joining players never need port forwarding.\n\n"
            "If automatic mapping is unavailable, enter a public IP or DNS hostname as Advertised Address and "
            "use manual TCP forwarding to this computer's LAN IP and selected port. Double NAT or ISP CGNAT "
            "cannot be fixed by forwarding on this router alone.\n\n"
            "Do not test a public/WAN invite from another device on the same home network unless the router "
            "supports NAT loopback. Test the LAN address locally or use an external network, such as a phone "
            "hotspot. If LAN works but external WAN does not, check the forward target, a changing LAN IP, "
            "double NAT, or ISP CGNAT/inbound-port blocking.\n\n"
            "Keep the host lobby open. Changing address or port requires a new invite. A timeout means the "
            "address or port cannot be reached; connection refused means it was reached but no server is "
            "listening."
        )

    def _string(self, title, attr, prompt, allow_empty=False):
        def saved(value):
            if value is not None:
                setattr(self, attr, value.strip())
                self.refresh_ui()
        confirm_dialog.ask_string(title, prompt, saved, initial=getattr(self, attr), allow_empty=allow_empty)

    def _integer(self, title, attr, prompt, low, high):
        def saved(value):
            if value is not None:
                setattr(self, attr, value); self.refresh_ui()
        confirm_dialog.ask_integer(title, prompt, saved, low, high, getattr(self, attr))

    def edit_name(self): self._string("Host Display Name", "host_name", "Enter your display name:")

    def edit_address(self):
        def saved(value):
            if value is not None:
                self.address = value.strip()
                self._address_is_detected = False
                self.refresh_ui()
        confirm_dialog.ask_string("Advertised Address", "Enter LAN IP, public IP, or hostname to share:",
                                  saved, initial=self.address)
    def edit_password(self): self._string("Lobby Password", "password", "Optional password (blank removes it):", True)
    def edit_port(self): self._integer("Server Port", "port", "Forward this TCP port for WAN play:", 1024, 65535)
    def edit_turns(self): self._integer("Maximum Turns", "max_turns", "1 to 240:", 1, 240)
    def edit_minutes(self): self._integer("Turn Time", "turn_minutes", "Minutes per turn (1 to 240):", 1, 240)

    def edit_capacity(self):
        # Country count is checked authoritatively when opening the lobby.
        self._integer("Player Capacity", "capacity", "Maximum connected players:", 1, 100)

    def edit_settings(self):
        from screens.menu_screens.scenario_settings import Scenario_Settings
        Scenario_Settings.configure_realtime_session(self.settings, "REALTIME_HOST_SETUP")
        self.go_to("SCENARIO_SETTINGS")

    def open_lobby(self):
        if IS_WEB:
            confirm_dialog.show_error("Desktop Only", "Real-time hosting is available in desktop builds only.")
            return
        server = advertiser = mapping = None
        try:
            # Re-detect just before hosting: a Wi-Fi or VPN change since this
            # screen opened must not make LAN discovery advertise a stale IP.
            self.local_address = default_advertised_address()
            if self._address_is_detected:
                self.address = self.local_address
            from screens.menu_screens.map import Map
            server_map = Map(load_path=self.scenario_path, is_scenario=True,
                             map_settings=copy.deepcopy(self.settings))
            countries = queries.get_active_playable_nations(server_map.map_data, server_map.nation_data)
            config = RealtimeConfig(self.scenario_path, copy.deepcopy(self.settings), self.capacity,
                                    self.max_turns, self.turn_minutes, self.address, self.port)
            session = RealtimeSession(config, countries, self.host_name,
                                      MapRealtimeDriver(server_map), self.password)
            certificate_dir = tempfile.mkdtemp(prefix="gd5-realtime-")
            certificate, key, fingerprint = create_match_certificate(certificate_dir)
            server = RealtimeServer(session, certificate, key)
            self.realtime_session = session
            self.realtime_server = server
            self.realtime_server_map = server_map
            self.realtime_fingerprint = fingerprint
            if self.relay_enabled:
                self.relay_host_key, self.relay_join_key = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
                self.relay_task = DigitalOceanRelayTask(self.relay_token, session.session_id,
                                                         self.relay_region, self.relay_size)
                self.relay_task.start()
                self.go_to("REALTIME_RELAY_PROVISION")
                return
            actual_port = server.start(self.port)
            session.config.port = actual_port
            self.realtime_invite = encode_invite(self.address, actual_port, session.session_id, fingerprint)
            self.realtime_lan_invite = encode_invite(self.local_address, actual_port,
                                                     session.session_id, fingerprint)
            advertiser = LanMatchAdvertiser(
                decode_invite(self.realtime_lan_invite), self.host_name,
                os.path.basename(self.scenario_path),
            )
            advertiser.start()
            self.realtime_lan_advertiser = advertiser
            # UPnP/NAT-PMP is a convenience attempt only.  It runs in a
            # worker so opening a lobby never freezes the game UI, and the
            # existing manual invite remains usable if the router declines it.
            self.realtime_port_mapping = None
            if self.local_address != "127.0.0.1":
                mapping = AutomaticPortMappingTask(self.local_address, actual_port)
                mapping.start()
                self.realtime_port_mapping = mapping
            self.go_to("REALTIME_LOBBY")
        except (OSError, RealtimeError, FileNotFoundError) as exc:
            if mapping: mapping.stop()
            if advertiser: advertiser.stop()
            if server: server.stop()
            confirm_dialog.show_error("Could Not Open Lobby", str(exc))

    def finish_relay_provisioning(self, relay):
        """Attach the already-created server to the new relay room."""
        transport = RelayHostTransport(relay.address, self.realtime_session.session_id,
                                       self.relay_host_key, self.relay_join_key)
        self.realtime_server.start_relay(transport)
        self.realtime_temporary_relay = relay
        self.realtime_relay_transport = transport
        self.realtime_port_mapping = None
        self.realtime_lan_advertiser = None
        self.realtime_invite = encode_relay_invite(relay.address, 443, self.realtime_session.session_id,
                                                   self.realtime_fingerprint, self.relay_join_key)
        self.realtime_lan_invite = self.realtime_invite


class Realtime_Relay_Setup(GameState):
    """Memory-only credentials for the host's own temporary relay account."""
    back_state = "REALTIME_HOST_SETUP"
    title = "Temporary Internet Relay"
    title_y = 35

    def __init__(self):
        super().__init__()
        self.bg_color, self.host_setup = (12, 28, 50), None
        self.refresh_ui()

    def bind_host(self, host_setup):
        self.host_setup = host_setup
        self.refresh_ui()

    def refresh_ui(self):
        self.elements = [make_back_button(self.exit_screen)]
        if not self.host_setup:
            return
        token_set = bool(self.host_setup.relay_token)
        self.elements.extend([
            Button("centered", 130, "medium", "blue", "DigitalOcean Token: SET" if token_set else "DigitalOcean Token", self.edit_token),
            Button("centered", 210, "medium", "blue", f"Region: {self.host_setup.relay_region}", self.edit_region),
            Button("centered", 290, "medium", "blue", f"Droplet Size: {self.host_setup.relay_size}", self.edit_size),
            Button("centered", 370, "medium", "light_blue", "Open DigitalOcean Token Page", self.open_token_page),
            Button("centered-120", 460, "medium", "green" if token_set else "grey",
                   "Use Temporary Relay" if token_set else "Enter Token First", self.enable),
            Button("centered+120", 460, "medium", "orange", "Use Direct Hosting", self.disable),
        ])

    def edit_token(self):
        def saved(value):
            if value is not None:
                self.host_setup.relay_token = value.strip()
                self.refresh_ui()
        confirm_dialog.ask_string("DigitalOcean API Token",
                                  "Paste a custom token with Droplet create/read/delete and Firewall create/delete:",
                                  saved, initial=self.host_setup.relay_token)

    def edit_region(self):
        def saved(value):
            if value is not None:
                self.host_setup.relay_region = value.strip().lower()
                self.refresh_ui()
        confirm_dialog.ask_string("DigitalOcean Region", "Example: nyc3, sfo3, lon1:", saved,
                                  initial=self.host_setup.relay_region)

    def edit_size(self):
        def saved(value):
            if value is not None:
                self.host_setup.relay_size = value.strip()
                self.refresh_ui()
        confirm_dialog.ask_string("Droplet Size", "Recommended: s-1vcpu-512mb-10gb:", saved,
                                  initial=self.host_setup.relay_size)

    def open_token_page(self):
        if IS_WEB:
            return
        try:
            webbrowser.open("https://cloud.digitalocean.com/account/api/tokens", new=2)
        except OSError:
            confirm_dialog.show_info("DigitalOcean Token", "Open DigitalOcean, then go to API > Personal Access Tokens.")

    def enable(self):
        if not self.host_setup.relay_token:
            confirm_dialog.show_error("Token Required", "Paste a DigitalOcean read/write personal access token first.")
            return
        self.host_setup.relay_enabled = True
        self.host_setup.refresh_ui()
        self.go_to("REALTIME_HOST_SETUP")

    def disable(self):
        self.host_setup.relay_enabled = False
        self.host_setup.refresh_ui()
        self.go_to("REALTIME_HOST_SETUP")


class Realtime_Relay_Provision(GameState):
    """Non-blocking provisioning screen while DigitalOcean starts the VPS."""
    back_state = "REALTIME_HOST_SETUP"
    title = "Creating Temporary Relay"
    title_y = 55

    def __init__(self):
        super().__init__()
        self.bg_color, self.host_setup = (12, 28, 50), None
        self._relay_transitioned = False
        self.elements = [Button("centered", 450, "medium", "red", "Cancel and Delete Relay", self.cancel)]

    def bind_host(self, host_setup):
        self.host_setup = host_setup
        self._relay_transitioned = False

    def cancel(self):
        if self.host_setup and getattr(self.host_setup, "relay_task", None):
            self.host_setup.relay_task.cancel_and_destroy()
        if self.host_setup and getattr(self.host_setup, "realtime_server", None):
            self.host_setup.realtime_server.stop()
        self.go_to("REALTIME_HOST_SETUP")

    def update(self):
        task = getattr(self.host_setup, "relay_task", None) if self.host_setup else None
        # The result remains available after the worker finishes.  Consume it
        # once: a relay transport can only be attached to a server once.
        if task and task.done() and not self._relay_transitioned:
            self._relay_transitioned = True
            if task.result:
                try:
                    self.host_setup.finish_relay_provisioning(task.result)
                    # This screen, rather than Host Setup, is active while
                    # provisioning.  It therefore owns the state transition.
                    self.go_to("REALTIME_LOBBY")
                except (OSError, RealtimeError) as exc:
                    task.cancel_and_destroy()
                    self.host_setup.realtime_server.stop()
                    confirm_dialog.show_error("Relay Could Not Start", str(exc))
                    self.go_to("REALTIME_HOST_SETUP")
            else:
                confirm_dialog.show_error("Relay Could Not Be Created", task.error or "Unknown provisioning error.")
                self.go_to("REALTIME_HOST_SETUP")
        super().update()

    def additional_draw(self, surface):
        font = pygame.font.Font(None, 28)
        text = "DigitalOcean is creating a small relay. This can take a minute or two."
        surface.blit(font.render(text, True, (235, 235, 235)), (55, 180))
        task = getattr(self.host_setup, "relay_task", None) if self.host_setup else None
        text = task.status if task else "Preparing relay setup..."
        surface.blit(font.render(text, True, (235, 235, 235)), (85, 225))
        text = "You can cancel safely; GD5 will delete any Droplet it created."
        surface.blit(font.render(text, True, (235, 235, 235)), (85, 270))


class Realtime_Scenario_Select(GameState):
    back_state = "REALTIME_HOST_SETUP"
    title = "Select Real-Time Scenario"
    title_y = 35

    def __init__(self):
        super().__init__()
        self.bg_color = (12, 28, 50)
        self.page = 0
        self.refresh_ui()

    def refresh_ui(self):
        self.elements = [make_back_button(self.exit_screen)]
        self.entries = _scenario_entries()
        per_page = 10
        page_count = max(1, (len(self.entries) + per_page - 1) // per_page)
        self.page = min(self.page, page_count - 1)
        start = self.page * per_page
        for index, (label, path) in enumerate(self.entries[start:start + per_page]):
            column, row = index % 2, index // 2
            x = "centered-200" if column == 0 else "centered+200"
            self.elements.append(Button(x, 110 + row * 70, "medium", "blue", label,
                                        lambda selected=path: self.select(selected)))
        if self.page:
            self.elements.append(Button("centered-180", 530, "small", "blue", "Previous", self.previous_page))
        if self.page + 1 < page_count:
            self.elements.append(Button("centered+80", 530, "small", "blue", "Next", self.next_page))

    def previous_page(self):
        self.page = max(0, self.page - 1)
        self.refresh_ui()

    def next_page(self):
        self.page += 1
        self.refresh_ui()

    def select(self, path):
        # The host setup is a persistent controller state; the controller gives
        # this selector its reference immediately before transition.
        if hasattr(self, "host_setup"):
            self.host_setup.scenario_path = path
            self.host_setup.refresh_ui()
        self.go_to("REALTIME_HOST_SETUP")


class Realtime_Lobby(GameState):
    back_state = "REALTIME_HOST_SETUP"
    title = "Real-Time Lobby"
    title_y = 30

    def __init__(self):
        super().__init__()
        self.bg_color = (12, 28, 50)
        self.session = None
        self.server = None
        self.server_map = None
        self.invite = ""
        self.lan_invite = ""
        self.port_mapping = None
        self.local_address = ""
        self.fingerprint = ""
        self.manual_advertised_address = False
        self.temporary_relay = None
        self.relay_token = ""
        self.country_page = 0
        self.refresh_ui()

    def bind_host(self, host_setup):
        self.session = host_setup.realtime_session
        self.server = host_setup.realtime_server
        self.server_map = host_setup.realtime_server_map
        self.invite = host_setup.realtime_invite
        self.lan_invite = host_setup.realtime_lan_invite
        self.port_mapping = host_setup.realtime_port_mapping
        self.local_address = host_setup.local_address
        self.fingerprint = host_setup.realtime_fingerprint
        self.manual_advertised_address = not host_setup._address_is_detected
        self.advertiser = host_setup.realtime_lan_advertiser
        self.temporary_relay = getattr(host_setup, "realtime_temporary_relay", None)
        # Retained only in the running host process so it can delete its own
        # temporary Droplet.  It is never placed in an invite or save.
        self.relay_token = host_setup.relay_token if self.temporary_relay else ""
        self._lobby_signature = None
        self.country_page = 0
        self.refresh_ui()

    def refresh_ui(self):
        self.elements = [make_back_button(self.leave_lobby)]
        if not self.session:
            return
        host = self.session.host_id
        self.elements.extend([
            Button("centered-220", 100, "medium", "blue",
                   "Copy Relay Invite" if self.temporary_relay else "Copy LAN Invite", self.show_lan_invite),
            Button("centered", 100, "medium", "green", "Start Match", self.start_match),
            Button("centered+220", 100, "medium", "red", "End Lobby", self.end_lobby),
            Button("centered-120", 150, "medium", self.internet_button_color(),
                   self.internet_button_label(), self.show_internet_invite),
            Button("centered+120", 150, "medium", "light_blue", "Networking Status", self.show_network_status),
        ])
        countries = self.session.countries
        per_page = 8
        page_count = max(1, (len(countries) + per_page - 1) // per_page)
        self.country_page = min(self.country_page, page_count - 1)
        start = self.country_page * per_page
        for index, country in enumerate(countries[start:start + per_page]):
            selected = next((p.name for p in self.session.players.values() if p.country_id == country), None)
            label = f"{country}: {selected or 'Available'}"
            color = "green" if not selected or selected == self.session.players[host].name else "grey"
            column, row = index % 2, index // 2
            x = "centered-140" if column == 0 else "centered+140"
            self.elements.append(Button(x, 215 + row * 65, (270, 44), color, label,
                                        lambda country_id=country: self.choose_host_country(country_id)))
        if self.country_page:
            self.elements.append(Button("centered-140", 480, "small", "blue", "Previous", self.previous_country_page))
        if self.country_page + 1 < page_count:
            self.elements.append(Button("centered+140", 480, "small", "blue", "Next", self.next_country_page))
        ready = self.session.players[host].ready
        self.elements.append(Button("centered", 535, "medium", "green" if ready else "orange",
                                    "Host Ready" if ready else "Mark Host Ready", self.toggle_ready))

    def previous_country_page(self):
        self.country_page = max(0, self.country_page - 1)
        self.refresh_ui()

    def next_country_page(self):
        self.country_page += 1
        self.refresh_ui()

    def choose_host_country(self, country_id):
        try:
            self.session.select_country(self.session.host_id, country_id)
            self.refresh_ui()
        except RealtimeError as exc:
            confirm_dialog.show_error("Country Unavailable", str(exc))

    def toggle_ready(self):
        try:
            player = self.session.players[self.session.host_id]
            self.session.set_ready(player.player_id, not player.ready)
            self.refresh_ui()
        except RealtimeError as exc:
            confirm_dialog.show_error("Cannot Ready", str(exc))

    def internet_button_label(self):
        if self.temporary_relay:
            return "Copy Relay Invite"
        result = self.port_mapping.result() if self.port_mapping else None
        if result is None and self.port_mapping:
            return "Internet Mapping..."
        if result and result.succeeded and is_public_ipv4(result.external_address):
            return "Copy Internet Invite"
        if self.manual_advertised_address:
            return "Copy Manual Invite"
        return "Internet Invite Unavailable"

    def internet_button_color(self):
        if self.temporary_relay:
            return "purple"
        result = self.port_mapping.result() if self.port_mapping else None
        if result and result.succeeded and is_public_ipv4(result.external_address):
            return "purple"
        return "orange" if self.manual_advertised_address else "grey"

    def _show_copied_invite(self, title, invite, note):
        copied = queries.copy_to_clipboard(invite)
        clipboard_note = ("The invite code has been copied to your clipboard."
                          if copied else
                          "Clipboard copy was unavailable; select the code below manually.")
        confirm_dialog.show_info(
            title, invite + "\n\n" + clipboard_note + "\n\n" + note)

    def show_lan_invite(self):
        if self.temporary_relay:
            self._show_copied_invite(
                "Internet Relay Invite", self.invite,
                "Players can use this from any normal internet connection. No player needs port forwarding. "
                "Share any lobby password separately.")
            return
        self._show_copied_invite(
            "LAN Invite", self.lan_invite,
            "This works for players on the same local network. They can also use Find LAN Matches. "
            "Share any lobby password separately.")

    def show_internet_invite(self):
        if self.temporary_relay:
            self._show_copied_invite(
                "Internet Relay Invite", self.invite,
                "This match uses your temporary DigitalOcean relay. The host and players only make outbound "
                "connections. Share any lobby password separately.")
            return
        result = self.port_mapping.result() if self.port_mapping else None
        if result and result.succeeded and is_public_ipv4(result.external_address):
            invite = encode_invite(result.external_address, result.external_port,
                                   self.session.session_id, self.fingerprint)
            self._show_copied_invite(
                "Internet Invite", invite,
                "Your router accepted an automatic mapping. Share any lobby password separately. "
                "Ask a player on another network to test it; some ISPs block incoming connections.")
            return
        if self.manual_advertised_address:
            self._show_copied_invite(
                "Manual Internet Invite", self.invite,
                "This uses the public address or DNS hostname entered in host setup. Share any lobby password "
                "separately; it still requires a working manual port forward.")
            return
        confirm_dialog.show_info(
            "Internet Invite Unavailable",
            "The router has not provided a usable public mapping yet. Open Networking Status for the exact "
            "result. Do not send the LAN/shared invite to an internet player: it contains a private local address."
        )

    def show_network_status(self):
        if self.temporary_relay:
            confirm_dialog.show_info(
                "Temporary Relay Status",
                f"Relay is running at {self.temporary_relay.address}:443. No router forwarding is needed. "
                "The host's certificate-pinned game connection remains end-to-end through the relay. "
                "End the lobby, or return to the multiplayer menu after the match, to delete this temporary "
                "Droplet and stop its allocation charge.")
            return
        result = self.port_mapping.result() if self.port_mapping else None
        confirm_dialog.show_info(
            "Real-Time Networking Status",
            host_network_diagnostics(self.local_address, self.session.config.port,
                                     bool(self.server and self.server.listening), result)
        )

    def start_match(self):
        try:
            self.session.start(self.session.host_id)
        except RealtimeError as exc:
            confirm_dialog.show_error("Cannot Start", str(exc)); return
        if getattr(self, "advertiser", None):
            self.advertiser.stop()
        self.selected_realtime_session = self.session
        self.selected_realtime_server = self.server
        self.selected_realtime_server_map = self.server_map
        self.selected_realtime_port_mapping = self.port_mapping
        self.selected_realtime_temporary_relay = self.temporary_relay
        self.selected_realtime_relay_token = self.relay_token
        self.selected_realtime_scenario_path = self.session.config.scenario_id
        self.selected_realtime_settings = copy.deepcopy(self.session.config.scenario_settings)
        self.selected_realtime_player_id = self.session.host_id
        self.go_to("MAP")

    def end_lobby(self):
        if getattr(self, "advertiser", None): self.advertiser.stop()
        if self.port_mapping: self.port_mapping.stop()
        if self.server: self.server.stop()
        self._destroy_temporary_relay()
        self.session = self.server = self.server_map = None
        self.go_to("REALTIME_HOST_SETUP")

    def _destroy_temporary_relay(self):
        if not self.temporary_relay or not self.relay_token:
            return
        relay, token = self.temporary_relay, self.relay_token
        self.temporary_relay = None
        threading.Thread(target=lambda: _delete_relay_quietly(token, relay.droplet_id, relay.firewall_id), daemon=True).start()

    def leave_lobby(self):
        self.end_lobby()

    def update(self):
        if self.session:
            signature = tuple((p.player_id, p.country_id, p.ready, p.connected)
                              for p in self.session.players.values())
            mapping = self.port_mapping.result() if self.port_mapping else None
            signature += ((mapping.protocol, mapping.message, mapping.external_address, mapping.external_port)
                          if mapping else ("mapping",))
            if signature != getattr(self, "_lobby_signature", None):
                self._lobby_signature = signature
                self.refresh_ui()
        super().update()

    def additional_draw(self, surface):
        if not self.session: return
        font = pygame.font.Font(None, 22)
        players = list(self.session.players.values())
        for index, player in enumerate(players[:5]):
            text = f"{player.name} — {player.country_id or 'No country'} — {'READY' if player.ready else 'waiting'}"
            surface.blit(font.render(text, True, (230, 230, 230)), (30, 585 + index * 24))


class Realtime_Join(GameState):
    back_state = "REAL_TIME_MULTIPLAYER"
    title = "Join Real-Time Match"
    title_y = 40

    def __init__(self):
        super().__init__()
        self.bg_color = (12, 28, 50)
        self.invite_text = ""
        self.name, self.password, self.reconnect_token = "Player", "", ""
        self.lan_browser = LanMatchBrowser()
        self.lan_browser.start()
        self.refresh_ui()

    def refresh_ui(self):
        invite_set = bool(self.invite_text)
        self.elements = [
            Button("centered", 120, "large", "light_blue", "Find LAN Matches", self.find_lan_matches),
            Button("centered", 210, "large", "blue",
                   "Replace Invite Code" if invite_set else "Paste Invite Code", self.edit_invite),
            Button("centered", 300, "medium", "blue", f"Name: {self.name}", self.edit_name),
            Button("centered", 360, "medium", "blue", f"Password: {'SET' if self.password else 'None'}", self.edit_password),
            Button("centered", 420, "medium", "purple", "Reconnect Token" if not self.reconnect_token else "Reconnect Token: SET", self.edit_reconnect_token),
            Button("centered", 500, "medium", "green", "Reconnect" if self.reconnect_token else "Connect", self.connect),
            make_back_button(self.exit_screen),
        ]

    def _edit(self, attr, title, allow_empty=False):
        def saved(value):
            if value is not None: setattr(self, attr, value); self.refresh_ui()
        confirm_dialog.ask_string(title, "Enter value:", saved, initial=getattr(self, attr), allow_empty=allow_empty)

    def edit_invite(self): self._edit("invite_text", "Real-Time Invite")
    def edit_name(self): self._edit("name", "Display Name")
    def edit_password(self): self._edit("password", "Lobby Password", True)
    def edit_reconnect_token(self): self._edit("reconnect_token", "Reconnect Token", True)

    def find_lan_matches(self):
        if IS_WEB:
            confirm_dialog.show_error("Desktop Only", "Real-time multiplayer is available in desktop builds only.")
            return
        self.go_to("REALTIME_LAN_BROWSER")

    def connect(self):
        if IS_WEB:
            confirm_dialog.show_error("Desktop Only", "Real-time multiplayer is available in desktop builds only.")
            return
        try:
            invite = decode_invite(self.invite_text)
            client = RealtimeClient(invite)
            client.connect()
            if self.reconnect_token:
                client.send("reconnect", {"reconnect_token": self.reconnect_token})
            else:
                client.send("join", {"name": self.name, "password": self.password})
            self.client = client
        except TimeoutError:
            confirm_dialog.show_error(
                "Could Not Connect",
                "The host did not answer in time. For a local match, use Find LAN Matches and make sure both "
                "devices are on the same non-guest network. For an internet match, ask the host to check "
                "Networking Status."
            )
        except (OSError, RealtimeError) as exc:
            confirm_dialog.show_error("Could Not Connect", str(exc))

    def update(self):
        client = getattr(self, "client", None)
        if client:
            for event in client.poll():
                if event.get("type") == "ok" and event.get("payload", {}).get("state"):
                    self.realtime_client = client
                    self.realtime_view = RemoteSessionView(client, event["payload"]["state"], client.player_id)
                    if client.reconnect_token:
                        persist_reconnect_token(client.invite, client.reconnect_token, self.name)
                        self.reconnect_token = client.reconnect_token
                    self.go_to("REALTIME_REMOTE_LOBBY")
                elif event.get("type") == "error":
                    confirm_dialog.show_error("Join Rejected", event.get("payload", {}).get("message", "Unknown error"))
                elif event.get("type") == "disconnected":
                    self.client = None
                    confirm_dialog.show_error("Connection Lost", event.get("payload", {}).get(
                        "message", "The host closed the connection."))
        super().update()


class Realtime_Lan_Browser(GameState):
    """A no-address, no-port join path for matches announced on the LAN."""

    back_state = "REALTIME_JOIN"
    title = "Find LAN Matches"
    title_y = 35

    def __init__(self):
        super().__init__()
        self.bg_color = (12, 28, 50)
        self.join_screen = None
        self.matches = []
        self._signature = None
        self.refresh_ui()

    def bind_join(self, join_screen):
        self.join_screen = join_screen
        self._signature = None
        self.refresh_ui()

    def refresh_ui(self):
        self.elements = [make_back_button(self.exit_screen)]
        if not self.join_screen:
            return
        self.matches = self.join_screen.lan_browser.matches()
        self.elements.append(Button("centered", 85, "small", "light_blue", "Refresh Local List", self.refresh_ui))
        if not self.matches:
            self.elements.append(Button("centered", 180, "medium", "grey",
                                        "Searching for open local lobbies...", lambda: None))
            return
        for index, match in enumerate(self.matches[:8]):
            column, row = index % 2, index // 2
            x = "centered-200" if column == 0 else "centered+200"
            label = f"{match.host_name}: {match.scenario_name}"
            self.elements.append(Button(x, 150 + row * 80, "medium", "green", label,
                                        lambda selected=match: self.join_match(selected)))

    def join_match(self, match):
        from data.io.realtime_multiplayer import encode_invite
        self.join_screen.invite_text = encode_invite(match.invite["host"], match.invite["port"],
                                                     match.invite["session"], match.invite["fingerprint"])
        self.join_screen.connect()
        # Reuse the normal join screen's response/error handling once the
        # selected local invite has opened its TLS connection.
        self.go_to("REALTIME_JOIN")

    def update(self):
        if self.join_screen:
            matches = self.join_screen.lan_browser.matches()
            signature = tuple((match.invite["session"], match.host_name, match.scenario_name,
                               match.invite["host"], match.invite["port"]) for match in matches)
            if signature != self._signature:
                self._signature = signature
                self.refresh_ui()
        super().update()


class Realtime_Remote_Lobby(GameState):
    back_state = "REAL_TIME_MULTIPLAYER"
    title = "Real-Time Lobby"
    title_y = 30

    def __init__(self):
        super().__init__()
        self.bg_color = (12, 28, 50)
        self.client = self.view = None
        self.country_page = 0
        self.refresh_ui()

    def bind_join(self, join_screen):
        self.client, self.view = join_screen.realtime_client, join_screen.realtime_view
        self.country_page = 0
        self.refresh_ui()

    def refresh_ui(self):
        self.elements = [make_back_button(self.leave)]
        if not self.view:
            return
        me = self.view.players.get(self.view.player_id)
        countries = list(getattr(self.view, "available_countries", ()))
        per_page = 8
        page_count = max(1, (len(countries) + per_page - 1) // per_page)
        self.country_page = min(self.country_page, page_count - 1)
        start = self.country_page * per_page
        for index, country in enumerate(countries[start:start + per_page]):
            selected = next((p.name for p in self.view.players.values() if p.country_id == country), None)
            column, row = index % 2, index // 2
            x = "centered-280" if column == 0 else "centered+10"
            self.elements.append(Button(x, 175 + row * 65, (270, 44),
                                        "green" if not selected or me and me.country_id == country else "grey",
                                        f"{country}: {selected or 'Available'}",
                                        lambda picked=country: self.client.send("select_country", {"country_id": picked})))
        if self.country_page:
            self.elements.append(Button("centered-180", 455, "small", "blue", "Previous", self.previous_country_page))
        if self.country_page + 1 < page_count:
            self.elements.append(Button("centered+80", 455, "small", "blue", "Next", self.next_country_page))
        if me:
            self.elements.append(Button("centered", 515, "medium", "orange" if not me.ready else "green",
                                        "Ready" if me.ready else "Mark Ready",
                                        lambda: self.client.send("ready", {"ready": not me.ready})))

    def previous_country_page(self):
        self.country_page = max(0, self.country_page - 1)
        self.refresh_ui()

    def next_country_page(self):
        self.country_page += 1
        self.refresh_ui()

    def update(self):
        if self.client:
            for event in self.client.poll():
                payload = event.get("payload", {})
                state = payload.get("state") if event.get("type") == "ok" else payload if event.get("type") == "state" else None
                if state:
                    self.view.update(state)
                    # Country names are available from the initial state only
                    # after the host chooses a scenario; preserve the list.
                    self.view.available_countries = getattr(self.view, "available_countries", [])
                    self.refresh_ui()
                    if self.view.phase in ("TURN", "PROCESSING", "GAME_OVER"):
                        self.selected_realtime_client = self.client
                        self.selected_realtime_view = self.view
                        self.go_to("MAP")
                elif event.get("type") == "error":
                    confirm_dialog.show_error("Server Rejected Request", payload.get("message", "Unknown error"))
                elif event.get("type") == "disconnected":
                    self.client = None
                    confirm_dialog.show_error("Connection Lost", payload.get(
                        "message", "The host closed the connection."))
                    self.go_to("REAL_TIME_MULTIPLAYER")
        super().update()

    def leave(self):
        if self.client: self.client.close()
        self.exit_screen()

    def additional_draw(self, surface):
        if not self.view: return
        font = pygame.font.Font(None, 22)
        for index, player in enumerate(list(self.view.players.values())[:5]):
            text = f"{player.name} — {player.country_id or 'No country'} — {'READY' if player.ready else 'waiting'}"
            surface.blit(font.render(text, True, (230, 230, 230)), (30, 585 + index * 24))
