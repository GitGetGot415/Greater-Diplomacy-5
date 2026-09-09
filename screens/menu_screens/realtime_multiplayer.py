"""Desktop real-time multiplayer setup and lobby screens."""

import copy
import os
import tempfile

import pygame

import data.constants as c
from data import queries
from data.io.realtime_multiplayer import (
    DEFAULT_MAX_TURNS, DEFAULT_PORT, DEFAULT_TURN_MINUTES, MapRealtimeDriver,
    RealtimeClient, RealtimeConfig, RealtimeError, RealtimeServer, RealtimeSession, RemoteSessionView,
    persist_reconnect_token,
    create_match_certificate, decode_invite, encode_invite,
)
from data.platform import IS_WEB
from gameState import GameState
from ui import confirm_dialog
from ui_elements import Button, make_back_button


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
        self.address = "127.0.0.1"
        self.port, self.capacity = DEFAULT_PORT, 4
        self.max_turns, self.turn_minutes = DEFAULT_MAX_TURNS, DEFAULT_TURN_MINUTES
        self.refresh_ui()

    def refresh_ui(self):
        scenario_label = os.path.basename(self.scenario_path) if self.scenario_path else "Select Scenario"
        self.elements = [
            Button("centered", 125, "medium", "blue", f"Scenario: {scenario_label}",
                   lambda: self.go_to("REALTIME_SCENARIO_SELECT")),
            Button("centered", 185, "medium", "blue", f"Host Name: {self.host_name}", self.edit_name),
            Button("centered", 245, "medium", "blue", f"Advertised Address: {self.address}", self.edit_address),
            Button("centered", 305, "medium", "blue", f"Port: {self.port}", self.edit_port),
            Button("centered", 365, "medium", "blue", f"Lobby Password: {'SET' if self.password else 'None'}", self.edit_password),
            Button("centered", 425, "medium", "purple", f"Player Capacity: {self.capacity}", self.edit_capacity),
            Button("centered", 485, "medium", "purple", f"Maximum Turns: {self.max_turns}", self.edit_turns),
            Button("centered", 545, "medium", "purple", f"Turn Time: {self.turn_minutes} minutes", self.edit_minutes),
            Button("centered", 605, "medium", "pink", "Scenario Settings", self.edit_settings),
            Button("centered", 675, "medium", "green", "Open Lobby", self.open_lobby),
            make_back_button(self.exit_screen),
        ]

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
    def edit_address(self): self._string("Advertised Address", "address", "Enter LAN/public IP or hostname to share:")
    def edit_password(self): self._string("Lobby Password", "password", "Optional password (blank removes it):", True)
    def edit_port(self): self._integer("Server Port", "port", "Forward this TCP port for WAN play:", 1024, 65535)
    def edit_turns(self): self._integer("Maximum Turns", "max_turns", "1 to 100:", 1, 100)
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
        try:
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
            actual_port = server.start(self.port)
            session.config.port = actual_port
            self.realtime_session = session
            self.realtime_server = server
            self.realtime_server_map = server_map
            self.realtime_invite = encode_invite(self.address, actual_port, session.session_id, fingerprint)
            self.go_to("REALTIME_LOBBY")
        except (OSError, RealtimeError, FileNotFoundError) as exc:
            confirm_dialog.show_error("Could Not Open Lobby", str(exc))


class Realtime_Scenario_Select(GameState):
    back_state = "REALTIME_HOST_SETUP"
    title = "Select Real-Time Scenario"
    title_y = 35

    def __init__(self):
        super().__init__()
        self.bg_color = (12, 28, 50)
        self.refresh_ui()

    def refresh_ui(self):
        self.elements = [make_back_button(self.exit_screen)]
        self.entries = _scenario_entries()
        for index, (label, path) in enumerate(self.entries[:9]):
            self.elements.append(Button("centered", 110 + index * 62, "medium", "blue", label,
                                        lambda selected=path: self.select(selected)))

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
        self.refresh_ui()

    def bind_host(self, host_setup):
        self.session = host_setup.realtime_session
        self.server = host_setup.realtime_server
        self.server_map = host_setup.realtime_server_map
        self.invite = host_setup.realtime_invite
        self._lobby_signature = None
        self.refresh_ui()

    def refresh_ui(self):
        self.elements = [make_back_button(self.leave_lobby)]
        if not self.session:
            return
        host = self.session.host_id
        self.elements.extend([
            Button("centered", 105, "medium", "blue", "Show Invite Code", self.show_invite),
            Button("centered", 165, "medium", "green", "Start Match", self.start_match),
            Button("centered", 225, "medium", "red", "End Lobby", self.end_lobby),
        ])
        countries = self.session.countries
        for index, country in enumerate(countries[:8]):
            selected = next((p.name for p in self.session.players.values() if p.country_id == country), None)
            label = f"{country}: {selected or 'Available'}"
            color = "green" if not selected or selected == self.session.players[host].name else "grey"
            self.elements.append(Button("centered", 290 + index * 46, "small", color, label,
                                        lambda country_id=country: self.choose_host_country(country_id)))
        ready = self.session.players[host].ready
        self.elements.append(Button("centered", 670, "medium", "green" if ready else "orange",
                                    "Host Ready" if ready else "Mark Host Ready", self.toggle_ready))

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

    def show_invite(self):
        confirm_dialog.show_info("Share This Invite", self.invite + "\n\nShare any lobby password separately. WAN hosts must forward the selected TCP port.")

    def start_match(self):
        try:
            self.session.start(self.session.host_id)
        except RealtimeError as exc:
            confirm_dialog.show_error("Cannot Start", str(exc)); return
        self.selected_realtime_session = self.session
        self.selected_realtime_server = self.server
        self.selected_realtime_server_map = self.server_map
        self.selected_realtime_scenario_path = self.session.config.scenario_id
        self.selected_realtime_settings = copy.deepcopy(self.session.config.scenario_settings)
        self.selected_realtime_player_id = self.session.host_id
        self.go_to("MAP")

    def end_lobby(self):
        if self.server: self.server.stop()
        self.session = self.server = self.server_map = None
        self.go_to("REALTIME_HOST_SETUP")

    def leave_lobby(self):
        self.end_lobby()

    def update(self):
        if self.session:
            signature = tuple((p.player_id, p.country_id, p.ready, p.connected)
                              for p in self.session.players.values())
            if signature != getattr(self, "_lobby_signature", None):
                self._lobby_signature = signature
                self.refresh_ui()
        super().update()

    def additional_draw(self, surface):
        if not self.session: return
        font = pygame.font.Font(None, 22)
        players = list(self.session.players.values())
        for index, player in enumerate(players):
            text = f"{player.name} — {player.country_id or 'No country'} — {'READY' if player.ready else 'waiting'}"
            surface.blit(font.render(text, True, (230, 230, 230)), (30, 110 + index * 26))


class Realtime_Join(GameState):
    back_state = "REAL_TIME_MULTIPLAYER"
    title = "Join Real-Time Match"
    title_y = 40

    def __init__(self):
        super().__init__()
        self.bg_color = (12, 28, 50)
        self.invite_text = ""
        self.name, self.password, self.reconnect_token = "Player", "", ""
        self.refresh_ui()

    def refresh_ui(self):
        self.elements = [
            Button("centered", 200, "large", "blue", "Paste Invite Code", self.edit_invite),
            Button("centered", 290, "medium", "blue", f"Name: {self.name}", self.edit_name),
            Button("centered", 350, "medium", "blue", f"Password: {'SET' if self.password else 'None'}", self.edit_password),
            Button("centered", 410, "medium", "purple", "Reconnect Token" if not self.reconnect_token else "Reconnect Token: SET", self.edit_reconnect_token),
            Button("centered", 490, "medium", "green", "Reconnect" if self.reconnect_token else "Connect", self.connect),
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
        super().update()


class Realtime_Remote_Lobby(GameState):
    back_state = "REAL_TIME_MULTIPLAYER"
    title = "Real-Time Lobby"
    title_y = 30

    def __init__(self):
        super().__init__()
        self.bg_color = (12, 28, 50)
        self.client = self.view = None
        self.refresh_ui()

    def bind_join(self, join_screen):
        self.client, self.view = join_screen.realtime_client, join_screen.realtime_view
        self.refresh_ui()

    def refresh_ui(self):
        self.elements = [make_back_button(self.leave)]
        if not self.view:
            return
        me = self.view.players.get(self.view.player_id)
        for index, country in enumerate(getattr(self.view, "available_countries", ())):
            selected = next((p.name for p in self.view.players.values() if p.country_id == country), None)
            self.elements.append(Button("centered", 190 + index * 46, "small",
                                        "green" if not selected or me and me.country_id == country else "grey",
                                        f"{country}: {selected or 'Available'}",
                                        lambda picked=country: self.client.send("select_country", {"country_id": picked})))
        if me:
            self.elements.append(Button("centered", 650, "medium", "orange" if not me.ready else "green",
                                        "Ready" if me.ready else "Mark Ready",
                                        lambda: self.client.send("ready", {"ready": not me.ready})))

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
        super().update()

    def leave(self):
        if self.client: self.client.close()
        self.exit_screen()

    def additional_draw(self, surface):
        if not self.view: return
        font = pygame.font.Font(None, 22)
        for index, player in enumerate(self.view.players.values()):
            text = f"{player.name} — {player.country_id or 'No country'} — {'READY' if player.ready else 'waiting'}"
            surface.blit(font.render(text, True, (230, 230, 230)), (30, 95 + index * 25))
