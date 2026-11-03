"""Build the map that a menu or lobby screen opens.

Each source screen calls one of these helpers from its `prepare_map` hook.
A helper stores the new map in the controller's MAP state.
"""

import copy
import os
import shutil


def _new_map(**settings):
    # screens.game.map imports the screens that import this module.
    from screens.game.map import Map
    return Map(**settings)


def open_new_map(app, **settings):
    app.states["MAP"] = _new_map(num_players=app.num_players, **settings)


def open_saved_map(app, path, *, force_editor=False, history_turn=None):
    open_new_map(app, load_path=path, is_scenario="scenarios" in path,
                 force_editor=force_editor, history_turn=history_turn)


def _player_encryption_cache(keys_dict, version_table):
    cache = {}
    for key_hash, entry in version_table.items():
        if entry.get("role") == "PLAYER":
            country_id = entry.get("country_id")
            if country_id and country_id in keys_dict:
                cache[country_id] = (keys_dict[country_id], key_hash, entry["enc_session"])
    return cache


def open_tournament_map(app, screen):
    """Load the tournament that `screen` selected. Return False when loading fails."""
    # Tournament files load cryptography dependencies only when a player opens one.
    from data.multiplayer.tournament import files as tournament_files
    from screens.game.map import render_buttons
    from ui import dialogs
    import data.constants as c

    path = screen.selected_tournament_path
    key = screen.selected_tournament_key
    result = tournament_files.load_tournament(path, key)
    success, role, country_id, temp_dir, keys_dict, message = result[:6]
    if not success:
        print(f"Failed to load tournament: {message}")
        dialogs.show_error("Load Failed", message)
        screen.done = False
        screen.next_state = "MULTIPLAYER_HUB"
        return False

    session_key, version_table = result[6:8]
    game_map = _new_map(load_path=temp_dir, is_scenario=False, force_editor=False,
                        num_players=app.num_players)
    app.states["MAP"] = game_map
    game_map.loaded_tournament_path = path
    game_map.multiplayer_tournament_dir = os.path.dirname(path)
    game_map.multiplayer_session_key = session_key
    game_map.multiplayer_player_enc_cache = _player_encryption_cache(keys_dict, version_table)

    if role == "HOST":
        game_map.multiplayer_host_mode = True
        game_map.player_country = "Spectator"
        game_map.multiplayer_master_key = key
        game_map.multiplayer_keys_dict = keys_dict
    elif role == "PLAYER":
        game_map.multiplayer_player_key = key
        tournament_files.strip_sensitive_data_for_player(game_map, country_id)
    elif role == c.TOURNAMENT_SPECTATOR_ROLE:
        tournament_files.strip_sensitive_data_for_tournament_spectator(game_map)

    shutil.rmtree(temp_dir, ignore_errors=True)
    game_map.refresh_all_maps()
    render_buttons(game_map)
    return True


def enter_realtime_map(app, realtime_map, session, player_id, country_id, after_layers=None):
    """Make a loaded map the active real-time board for one player."""
    from screens.game.map import render_buttons

    realtime_map.selection_mode = False
    realtime_map.pending_selection = None
    realtime_map.show_player_ready_screen = False
    realtime_map.realtime_multiplayer = True
    realtime_map.realtime_session = session
    realtime_map.realtime_player_id = player_id
    realtime_map.player_country = country_id
    realtime_map.active_players = [p.country_id for p in session.players.values() if p.country_id]
    realtime_map.set_play_view_defaults()
    # Map construction initially suppresses fog while scenario country
    # selection is active. Rebuild the player-dependent layers immediately
    # instead of waiting for the first processed turn to do it.
    realtime_map.refresh_map_layers("relations", "faction_territories", "fog")
    if after_layers:
        after_layers()
    app.states["MAP"] = realtime_map
    render_buttons(realtime_map)


def apply_initial_snapshot(realtime_map, view):
    # Real-time networking stays off web import paths until a real-time match opens.
    from data.multiplayer.realtime.session import apply_authoritative_snapshot
    if view.snapshot:
        apply_authoritative_snapshot(realtime_map, view.snapshot)
        realtime_map._realtime_snapshot_turn = view.turn_number
        realtime_map._realtime_snapshot_phase = view.phase


def open_hosted_realtime_map(app, lobby):
    # The host's visible board is a second map instance. The
    # server-owned map stays inside MapRealtimeDriver, preventing
    # host UI edits from bypassing authoritative validation.
    session = lobby.session
    realtime_map = _new_map(load_path=session.config.scenario_id, is_scenario=True,
                            map_settings=copy.deepcopy(session.config.scenario_settings),
                            num_players=len(session.players))
    host_player = session.players[session.host_id]
    realtime_map.realtime_server = lobby.server
    realtime_map.realtime_server_map = lobby.server_map
    realtime_map.realtime_port_mapping = lobby.port_mapping
    realtime_map.realtime_temporary_relay = lobby.temporary_relay
    realtime_map.realtime_relay_token = lobby.relay_token
    # Scenario loading supplies the finalized map, but the host
    # selected a country in the lobby already.  Do not re-enter
    # the ordinary single-player country-selection flow.
    enter_realtime_map(app, realtime_map, session, host_player.player_id, host_player.country_id)


def open_joined_realtime_map(app, lobby):
    # Real-time networking stays off web import paths until a real-time match opens.
    from data.multiplayer.realtime.session import materialize_map_bundle

    view = lobby.view
    bundle_path = materialize_map_bundle(lobby.client.map_bundle)
    try:
        realtime_map = _new_map(load_path=bundle_path, is_scenario=False,
                                num_players=len(view.players))
    finally:
        shutil.rmtree(bundle_path, ignore_errors=True)
    me = view.players[view.player_id]
    realtime_map.realtime_client = lobby.client
    # The map was loaded before the remote player's country was
    # known; the shared entry initializes that player's visibility.
    enter_realtime_map(app, realtime_map, view, view.player_id, me.country_id,
                       lambda: apply_initial_snapshot(realtime_map, view))
