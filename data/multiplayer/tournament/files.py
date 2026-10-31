
# Keep presentation imports local so tournament file operations do not initialize UI support.

import concurrent.futures
import shutil

from data.state_access import world_for, session_for
import os
import json
import hashlib
import base64
import binascii
import secrets
import copy
import gzip
import zlib
import pygame
from cryptography.fernet import Fernet, InvalidToken
import data.constants as c
from data import migrations, queries
from data.map import history_io
from data.map.map_cache import remove_optional_layer_files
from data.platform import sync_persisted_dir

from data.multiplayer.tournament import v46_moves
from map_logic.actions.player_actions import collect_map_commands, PlayerActions


TOURNAMENT_GZIP_LEVEL = 6

def active_owners_of(map_ref):
    """Every nation entitled to a tournament move right now.

    This includes faction-backed governments in exile: their units and
    diplomatic choices are still authoritative player state even while they
    hold no province. Empty when there is no map loaded, which callers read as
    "no filter".
    """
    world_state = world_for(map_ref)
    if not map_ref.map_data:
        return set()
    return queries.get_politically_active_nations(
        world_state.map_data, map_ref.nation_data)


def run_with_progress(jobs, worker, caption, on_result):
    """Runs `worker` over `jobs` in a thread pool, drawing the loading bar.

    Both the key-encryption pass and the move-decryption pass drove their own
    identical copy of this loop, down to the pygame.event.pump() that keeps the
    window responsive while the pool works.
    """
    from ui.panels import turn_progress 
    surface = pygame.display.get_surface()
    total = len(jobs)
    completed = 0

    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = [executor.submit(worker, job) for job in jobs]
        for future in concurrent.futures.as_completed(futures):
            pygame.event.pump()
            result = future.result()
            if result:
                on_result(result)
            completed += 1
            if surface and total > 0:
                turn_progress.draw_simple_refresh_bar(surface, caption, completed, total)
                pygame.display.flip()


def hash_key(key):
    return hashlib.sha256(key.encode('utf-8')).hexdigest()


def is_reserved_tournament_key(key):
    """Whether a host key collides with the public tournament spectator key."""
    return isinstance(key, str) and key.strip().casefold() == c.TOURNAMENT_SPECTATOR_KEY.casefold()

def generate_fernet_key_from_password(password, salt):
    derived_key = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt,
        200_000
    )
    return base64.urlsafe_b64encode(derived_key)

def encrypt_dict(data_dict, password, *, compress=False):
    salt = secrets.token_bytes(16)
    key = generate_fernet_key_from_password(password, salt)
    f = Fernet(key)
    json_bytes = history_io.dump_compact_text(data_dict).encode('utf-8')
    if compress:
        # Compress plaintext. Encrypted bytes cannot compress effectively.
        compressed = gzip.compress(json_bytes, compresslevel=TOURNAMENT_GZIP_LEVEL, mtime=0)
        if len(compressed) < len(json_bytes):
            json_bytes = compressed
    encrypted_token = f.encrypt(json_bytes).decode('utf-8')
    salt_b64 = base64.urlsafe_b64encode(salt).decode('utf-8')
    return f"{salt_b64}:{encrypted_token}"

def decrypt_dict(encrypted_str, password):
    try:
        salt_b64, encrypted_token = encrypted_str.split(":", 1)
        salt = base64.urlsafe_b64decode(salt_b64.encode('utf-8'))
    except (AttributeError, ValueError, binascii.Error):
        # A move/tournament file is untrusted input.  Deliberately reject only
        # malformed encoded data; programming errors must remain visible.
        return None

    key = generate_fernet_key_from_password(password, salt)
    try:
        f = Fernet(key)
        json_bytes = f.decrypt(encrypted_token.encode('utf-8'))
        return migrations.decode_saved_json(json_bytes)
    except (InvalidToken, UnicodeDecodeError, json.JSONDecodeError, OSError, EOFError, zlib.error):
        # Bad ciphertext and non-JSON plaintext are malformed player data.
        return None

def strip_sensitive_data_for_player(map_ref, country_id):
    """
    Modifies the active map_ref in place to hide information that the player should not see.
    """
    world_state = world_for(map_ref)
    session_state = session_for(map_ref)
    map_ref.country_economy_summaries = queries.get_shared_country_economy_summaries(
        country_id, world_state.map_data, world_state.nation_data, context=map_ref)
    session_state.multiplayer_mode = True
    session_state.player_country = country_id
    session_state.active_players = [country_id]
    session_state.current_player_index = 0

    for cid, country in world_state.nation_data.items():
        if cid != country_id:
            # Hide production queues
            country["production_queue"] = []
            country["manpower_pool"] = 0
            country["materials_pool"] = 0
            country["fuel_pool"] = 0
            
            # Hide orders
            country["orders"] = []
            
            # Hide research
            country["current_research"] = None
            country["research_queue"] = []


def strip_sensitive_data_for_tournament_spectator(map_ref):
    """Project a tournament archive into the fog-limited spectator view.

    A tournament archive necessarily contains the canonical world so it can be
    resolved by the host.  This local projection removes every nation's private
    planning/economy data and gives the viewer no country, so all remaining map
    presentation flows through the existing no-territory fog rules.
    """
    world_state = world_for(map_ref)
    session_state = session_for(map_ref)
    map_ref.country_economy_summaries = {}
    session_state.multiplayer_mode = True
    session_state.player_country = c.TOURNAMENT_SPECTATOR
    session_state.active_players = [c.TOURNAMENT_SPECTATOR]
    session_state.current_player_index = 0

    for country in world_state.nation_data.values():
        # ``nation_data`` also contains shared metadata such as faction war
        # maps. It is not a country record and must retain its own schema.
        if not isinstance(country, dict) or "is_playable" not in country:
            continue
        country["production_queue"] = []
        country["manpower_pool"] = 0
        country["materials_pool"] = 0
        country["fuel_pool"] = 0
        country["orders"] = []
        country["current_research"] = None
        country["research_queue"] = []
        country["inbox"] = []
        country["pending_diplomacy"] = {}
        country["diplo_responses"] = {}

    for province in world_state.map_data.values():
        for unit in province.get("units", []):
            unit.pop("order", None)
            unit.pop("air_cargo", None)


def build_tournament_spectator_save(save_dict):
    """Return the public, fog-limited projection stored for spectators.

    The spectator key must never disclose the session key that decrypts the
    host's complete snapshot. This companion save therefore preserves only the
    map data necessary to draw the board, with private plans and economy data
    removed before it is encrypted with the public spectator key.
    """
    spectator_save = copy.deepcopy(save_dict)
    spectator_save["player_country"] = c.TOURNAMENT_SPECTATOR
    spectator_save["active_players"] = [c.TOURNAMENT_SPECTATOR]
    spectator_save["current_player_index"] = 0
    spectator_save["unit_event_log"] = {
        "turn": spectator_save.get("date", {}).get("total_turns", 0), "events": []}
    spectator_save["unit_event_read_turns"] = {}

    nation_data = spectator_save.get("nation_data", {})
    if isinstance(nation_data, dict):
        for country in nation_data.values():
            if not isinstance(country, dict) or "is_playable" not in country:
                continue
            country["production_queue"] = []
            country["manpower_pool"] = 0
            country["materials_pool"] = 0
            country["fuel_pool"] = 0
            country["manpower"] = 0
            country["materials"] = 0
            country["fuel"] = 0
            country["orders"] = []
            country["current_research"] = None
            country["research_queue"] = []
            country["research"] = {}
            country["inbox"] = []
            country["pending_diplomacy"] = {}
            country["diplo_responses"] = {}

    for province in spectator_save.get("provinces", {}).values():
        if not isinstance(province, dict):
            continue
        province["building_queue"] = []
        province["unit_queue"] = []
        province["orders"] = []
        for unit in province.get("units", []):
            if isinstance(unit, dict):
                unit.pop("order", None)
                unit.pop("air_cargo", None)

    # A self-contained tournament also includes raw geometry. Older maps may
    # have mutable province fields mixed into that geometry, so scrub the same
    # fields defensively before writing the public projection.
    raw_map_data = spectator_save.get("_raw_map_data")
    if isinstance(raw_map_data, dict):
        for province in raw_map_data.values():
            if not isinstance(province, dict):
                continue
            province["building_queue"] = []
            province["unit_queue"] = []
            province["orders"] = []
            for unit in province.get("units", []):
                if isinstance(unit, dict):
                    unit.pop("order", None)
                    unit.pop("air_cargo", None)

    return spectator_save

def write_host_keys(map_ref, keys_dict, output_dir=None):
    if output_dir is None:
        output_dir = c.TOURNAMENT_SAVES_DIR
    os.makedirs(output_dir, exist_ok=True)
    
    all_keys_path = os.path.join(output_dir, "ALL_Host_Keys.txt")
    keys_path = os.path.join(output_dir, "Host_Keys.txt")
    
    active_owners = active_owners_of(map_ref)
    nation_data = map_ref.nation_data
    
    with open(all_keys_path, 'w') as f:
        f.write("Every key for every possible country:\n\n")
        for cid, key in keys_dict.items():
            name = queries.get_country_display_name(cid, nation_data)
            f.write(f"{name} (ID {cid}): {key}\n")
        f.write("\nTournament Spectator (fog-limited): "
                f"{c.TOURNAMENT_SPECTATOR_KEY}\n")
            
    with open(keys_path, 'w') as f:
        f.write("Distribute these keys to your players:\n\n")
        for cid, key in keys_dict.items():
            if cid in active_owners:
                name = queries.get_country_display_name(cid, nation_data)
                f.write(f"{name} (ID {cid}): {key}\n")
        f.write("\nTournament Spectator (fog-limited): "
                f"{c.TOURNAMENT_SPECTATOR_KEY}\n")

    # Web only: mirror the whole tournament_saves tree into IndexedDB so it
    # survives closing the tab (output_dir is always somewhere under this
    # root). No-op on desktop.
    sync_persisted_dir(c.TOURNAMENT_SAVES_DIR)

    return keys_path, all_keys_path

def export_tournament(map_ref, file_path, master_key, keys_dict):
    """
    keys_dict maps Country_ID -> Country_Key
    """
    world_state = world_for(map_ref)
    if is_reserved_tournament_key(master_key):
        raise ValueError("'Spectator' is reserved for tournament spectator access and cannot be a Master Key.")

    output_dir = os.path.dirname(file_path)
    os.makedirs(output_dir, exist_ok=True)
    
    # Process pending key regenerations if any
    pending_regen = map_ref.multiplayer_pending_key_regen
    regenerated_keys = {}
    if pending_regen:
        for cid in list(pending_regen):
            new_key = secrets.token_hex(4)
            keys_dict[cid] = new_key
            map_ref.multiplayer_keys_dict[cid] = new_key
            nation_data = map_ref.nation_data
            name = queries.get_country_display_name(cid, nation_data)
            regenerated_keys[cid] = (name, new_key)
        map_ref.multiplayer_pending_key_regen.clear()

    keys_path, all_keys_path = write_host_keys(map_ref, keys_dict, output_dir=output_dir)
    
    if regenerated_keys:
        turn = world_state.time_manager.total_turns if hasattr(map_ref, 'time_manager') else 0
        regen_keys_path = os.path.join(output_dir, f"Turn_{turn}_Regenerated_Keys.txt")
        with open(regen_keys_path, 'w') as f:
            f.write(f"Regenerated keys for Turn {turn}:\n\n")
            for cid, (name, new_key) in regenerated_keys.items():
                f.write(f"{name} (ID {cid}): {new_key}\n")

    queries.scrub_default_images(world_state.nation_data)
    queries.ensure_unit_ids(world_state.map_data)
    save_dict = queries.build_save_dict(map_ref)
    
    # Embed the raw geometry so the tournament file is self-contained
    if hasattr(map_ref, 'raw_json_data'):
        save_dict["_raw_map_data"] = queries.build_map_geometry_save(
            world_state.raw_json_data, save_dict["provinces"])
        
    temp_img_dir = os.path.join(c.TOURNAMENT_SAVES_DIR, "temp_img_export")
    os.makedirs(temp_img_dir, exist_ok=True)
    images = {}
    
    try:
        img_names = {
            "terrain.png": getattr(map_ref, 'terrain_map', None),
            "id_map.png": getattr(map_ref, 'id_map', None),
        }
        
        for name, surf in img_names.items():
            if surf:
                img_path = os.path.join(temp_img_dir, name)
                pygame.image.save(surf, img_path)
                with open(img_path, "rb") as f:
                    images[name] = base64.b64encode(f.read()).decode('utf-8')
    finally:
        if os.path.exists(temp_img_dir):
            shutil.rmtree(temp_img_dir, ignore_errors=True)
    
    save_dict["_images"] = images
    
    session_key = map_ref.multiplayer_session_key
    if not session_key:
        session_key = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode('utf-8')
        map_ref.multiplayer_session_key = session_key

    player_enc_cache = map_ref.multiplayer_player_enc_cache
    
    active_owners = active_owners_of(map_ref)

    tasks_to_encrypt = []
    for cid, ckey in keys_dict.items():
        if not ckey:
            continue
        if active_owners and cid not in active_owners:
            continue
        cached = player_enc_cache.get(cid)
        if not cached or cached[0] != ckey:
            tasks_to_encrypt.append((cid, ckey))

    m_hash = hash_key(master_key)
    verification_table = {
        m_hash: {
            "role": "HOST",
            "enc_session": encrypt_dict({"sk": session_key, "keys_dict": keys_dict}, master_key)
        },
        hash_key(c.TOURNAMENT_SPECTATOR_KEY): {
            "role": c.TOURNAMENT_SPECTATOR_ROLE,
            # Deliberately lacks ``sk``: the public spectator key can decrypt
            # only ``spectator_game_data``, never the host's game session.
            "enc_session": encrypt_dict({"role": c.TOURNAMENT_SPECTATOR_ROLE},
                                          c.TOURNAMENT_SPECTATOR_KEY)
        },
    }

    for cid, (cached_ckey, r_hash, r_enc) in list(player_enc_cache.items()):
        if cid in keys_dict and keys_dict[cid] == cached_ckey and (not active_owners or cid in active_owners):
            verification_table[r_hash] = {
                "role": "PLAYER",
                "country_id": cid,
                "enc_session": r_enc
            }

    if tasks_to_encrypt:
        def _encrypt_player(task):
            cid, ckey = task
            if not ckey: return None
            return cid, hash_key(ckey), encrypt_dict({"sk": session_key}, ckey)

        def _record(result):
            r_cid, r_hash, r_enc = result
            verification_table[r_hash] = {
                "role": "PLAYER",
                "country_id": r_cid,
                "enc_session": r_enc
            }
            player_enc_cache[r_cid] = (keys_dict[r_cid], r_hash, r_enc)

        run_with_progress(tasks_to_encrypt, _encrypt_player,
                          "Encrypting Player Keys...", _record)

    map_ref.multiplayer_player_enc_cache = player_enc_cache
            
    game_data_enc = encrypt_dict(save_dict, session_key, compress=True)
    spectator_game_data_enc = encrypt_dict(
        build_tournament_spectator_save(save_dict), c.TOURNAMENT_SPECTATOR_KEY, compress=True)
    history_enc = None # History omitted for tournament saves to reduce file size
    
    payload = {
        "verification_table": verification_table,
        "game_data": game_data_enc,
        "spectator_game_data": spectator_game_data_enc,
        "history": history_enc
    }
    
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, 'w') as f:
        f.write(history_io.dump_compact_text(payload))

    # Web only: mirror the .gd5tour (and any regen-keys txt above) into
    # IndexedDB so it survives closing the tab. No-op on desktop.
    sync_persisted_dir(c.TOURNAMENT_SAVES_DIR)

    print(f"Tournament file exported to {file_path}")
    return keys_path, all_keys_path

def load_tournament(file_path, key):
    """
    Loads a tournament file, authenticates with input_key, and applies it to map_ref.
    Returns (Success: bool, Role: str, Country_ID: int/None, ErrorMsg: str)
    """
    if not os.path.exists(file_path):
        return False, None, None, None, None, "File not found"
        
    try:
        with open(file_path, 'r') as f:
            payload = json.load(f)
    except OSError:
        return False, None, None, None, None, "Could not read tournament file"
    except ValueError:
        return False, None, None, None, None, "Invalid file format"

    if not isinstance(payload, dict):
        return False, None, None, None, None, "Invalid file format"

    ver_table = payload.get("verification_table")
    if not isinstance(ver_table, dict):
        return False, None, None, None, None, "Invalid verification data"

    i_hash = hash_key(key)
    entry = ver_table.get(i_hash)
    if not isinstance(entry, dict):
        return False, None, None, None, None, "Invalid key"

    role = entry.get("role")
    cid = entry.get("country_id")
    if role not in ("HOST", "PLAYER", c.TOURNAMENT_SPECTATOR_ROLE):
        return False, None, None, None, None, "Invalid tournament role"
    if role == "PLAYER" and cid is None:
        return False, None, None, None, None, "Invalid player entry"
    if role == c.TOURNAMENT_SPECTATOR_ROLE and cid is not None:
        return False, None, None, None, None, "Invalid tournament spectator entry"

    if role == c.TOURNAMENT_SPECTATOR_ROLE:
        # The public key decrypts only the pre-scrubbed spectator projection;
        # it never receives the session key for the host's canonical snapshot.
        decrypted_session = {}
        session_key = None
        game_data = decrypt_dict(payload.get("spectator_game_data"), key)
        if not isinstance(game_data, dict):
            return False, None, None, None, None, "Tournament does not include spectator data"
    else:
        encrypted_session = entry.get("enc_session")
        if not isinstance(encrypted_session, str):
            return False, None, None, None, None, "Invalid key payload"

        decrypted_session = decrypt_dict(encrypted_session, key)
        if not isinstance(decrypted_session, dict) or "sk" not in decrypted_session:
            return False, None, None, None, None, "Decryption failed (corrupt key payload)"

        session_key = decrypted_session["sk"]
        if not isinstance(session_key, str):
            return False, None, None, None, None, "Invalid key payload"

        game_data = decrypt_dict(payload.get("game_data"), session_key)
        if not isinstance(game_data, dict):
            return False, None, None, None, None, "Failed to decrypt game data"

    keys_dict = decrypted_session.get("keys_dict", {})
    if not isinstance(keys_dict, dict):
        return False, None, None, None, None, "Invalid key payload"
    try:
        # An older game cannot read a newer tournament. Older tournaments upgrade on load.
        migrations.check_version(game_data.get("version"), "This tournament")
    except migrations.NewerVersionError as error:
        return False, None, None, None, None, str(error)

    temp_dir = os.path.join(c.TOURNAMENT_SAVES_DIR, "temp_load")
    os.makedirs(temp_dir, exist_ok=True)
    # A tournament loads one turn. Clear history and derived images left by
    # earlier loads, including legacy archives that stored these files.
    history_io.write(temp_dir, {})
    remove_optional_layer_files(temp_dir)

    # Extract raw geometry if present.  Reject a malformed archive here so the
    # player gets a useful load error instead of a later Map-constructor crash.
    raw_map_data = game_data.pop("_raw_map_data", None)
    images = game_data.pop("_images", {})
    if images is None:
        images = {}
    if not isinstance(images, dict):
        return False, None, None, None, None, "Invalid tournament image data"

    try:
        if raw_map_data:
            with open(os.path.join(temp_dir, "map_data.json"), 'w') as f:
                f.write(history_io.dump_compact_text(raw_map_data))

        expected_image_names = {"terrain.png", "id_map.png", "political.png", "cores.png"}
        for name, b64_str in images.items():
            if name not in expected_image_names or not isinstance(b64_str, str):
                return False, None, None, None, None, "Invalid tournament image data"
            img_path = os.path.join(temp_dir, name)
            with open(img_path, "wb") as f:
                f.write(base64.b64decode(b64_str, validate=True))

        with open(os.path.join(temp_dir, "meta.json"), 'w') as f:
            f.write(history_io.dump_compact_text(game_data))

    except (OSError, TypeError, ValueError):
        return False, None, None, None, None, "Invalid tournament data"

    return True, role, cid, temp_dir, keys_dict, "Loaded successfully", session_key, ver_table

def export_move_file(map_ref, file_path, player_key):
    """
    Exports a .gd5move file containing ONLY the submitting player's changes
    for the current tournament turn.

    The session and turn fields make an accidental import of an old move (or a
    move from another tournament using the same player key) detectable by the
    host.  They live inside the encrypted player payload so they cannot be
    altered without that player's key.
    """
    world_state = world_for(map_ref)
    session_state = session_for(map_ref)
    cid = session_state.player_country
    if cid not in world_state.nation_data:
        raise ValueError("Only a tournament country player may export a move file.")

    queries.ensure_unit_ids(world_state.map_data)
    save_dict = queries.build_save_dict(map_ref)
    
    player_data = {
        "nation_data": copy.deepcopy(save_dict.get("nation_data", {}).get(cid, {})),
        "research_years": save_dict["research_years"],
        "provinces": {},
        # A move must be able to say "I have no units left".  Older moves
        # inferred that from a non-empty province update, which lost an
        # all-disbanded army (and an all-volunteer army) because there was
        # nothing left to serialize.  New hosts use this marker to replace
        # the submitting country's complete map-unit snapshot atomically.
        "unit_snapshot": True,
        "aircraft_orders": [],
        "air_transport": queries.air_transport_commands(map_ref, cid),
        "game_version": c.GAME_VERSION,
        "release_subjects": [{"core_nation": entry["core_nation"],
                              "keep_cores": entry.get("keep_cores", False),
                              "release_type": entry["release_type"]}
                             for entry in save_dict.get("nation_data", {}).get(cid, {}).get("release_puppet_queue", [])],
    }

    session_key = map_ref.multiplayer_session_key
    if session_key:
        player_data["tournament_session"] = session_key
    if hasattr(map_ref, "time_manager"):
        player_data["tournament_turn"] = world_state.time_manager.total_turns

    # A faction rename affects every member, while normal move data contains
    # only one nation record.  Preserve it as a separate host-validated command
    # rather than allowing the renamed leader to drift away from its members.
    pending_renames = map_ref.multiplayer_pending_faction_renames
    if pending_renames:
        player_data["faction_renames"] = list(pending_renames)

    pending_appearances = map_ref.multiplayer_pending_appearance_updates
    if pending_appearances:
        player_data["appearance_updates"] = [
            {"country_id": target, "appearance": appearance}
            for target, appearance in pending_appearances.items()
        ]

    # Integrated-puppet siphon sliders live on the subject's country record,
    # not on the controlling player's record.  Carry their values as a small
    # explicit command, just like integrated-puppet appearance edits, so an
    # asynchronous player does not silently lose them on host import.
    siphon_updates = []
    player_country = save_dict.get("nation_data", {}).get(cid, {})
    for puppet in player_country.get("puppets", []) if isinstance(player_country, dict) else ():
        puppet_data = save_dict.get("nation_data", {}).get(puppet, {})
        if (isinstance(puppet_data, dict)
                and puppet_data.get("master") == cid
                and puppet_data.get("puppet_type") == c.PUPPET_TYPE_INTEGRATED):
            siphon_updates.append({"country_id": puppet,
                                   "siphon_rates": puppet_data.get("siphon_rates", {})})
    if siphon_updates:
        player_data["puppet_siphon_updates"] = siphon_updates

    player_data["player_intents"] = collect_map_commands(map_ref, cid)
    for command in player_data["player_intents"]:
        if command["type"] == "army_roster":
            player_data["nation_data"]["armies"] = copy.deepcopy(command["armies"])
        if command["type"] == "faction_rename" and pending_renames:
            command["name"] = pending_renames[-1]["new_name"]
        elif command["type"] == "puppet_draft" and pending_appearances:
            command["appearances"] = {
                target: {**{key: copy.deepcopy(world_state.nation_data[target].get(key))
                            for key in c.COUNTRY_APPEARANCE_FIELDS}, **appearance}
                for target, appearance in pending_appearances.items()}
    
    for prov_key, prov_data in save_dict.get("provinces", {}).items():
        prov_updates = {}
        if prov_data.get("owner") == cid:
            if "building_queue" in prov_data:
                prov_updates["building_queue"] = prov_data["building_queue"]
            if "unit_queue" in prov_data:
                prov_updates["unit_queue"] = prov_data["unit_queue"]
                
        player_units = []
        for unit in prov_data.get("units", []):
            if unit.get("owner") != cid:
                continue
            if queries.is_air_unit(unit, context=map_ref) or queries.is_air_transport(unit, context=map_ref):
                # Position, health and transported stats always belong to the
                # host. A planning file carries only identity and desired orders.
                player_data["aircraft_orders"].append({
                    "unit_id": unit["unit_id"], "order": unit.get("order"),
                    "custom_name": unit.get("custom_name")})
            else:
                player_units.append(unit)
        if player_units:
            prov_updates["units"] = player_units
            
        if prov_updates:
            player_data["provinces"][prov_key] = prov_updates
            
    payload = {
        "country_id": cid,
        "hash": hash_key(player_key),
        "data": encrypt_dict(player_data, player_key, compress=True)
    }
    
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, 'w') as f:
        f.write(history_io.dump_compact_text(payload))

    # Web only: mirror the .gd5move into IndexedDB so it survives closing the
    # tab. No-op on desktop.
    sync_persisted_dir(c.TOURNAMENT_SAVES_DIR)

def _move_context_error(map_ref, player_data):
    """Returns a reason a move targets the wrong tournament turn, if any.

    Old move files did not contain these fields, so they remain loadable for
    an in-progress tournament created by an earlier release.  Every newly
    exported move carries both values and is checked strictly.
    """
    expected_session = map_ref.multiplayer_session_key
    move_session = player_data.get("tournament_session")
    if move_session is not None and move_session != expected_session:
        return "belongs to a different tournament"

    if "tournament_turn" in player_data:
        time_manager = map_ref.time_manager
        expected_turn = getattr(time_manager, "total_turns", None)
        if player_data["tournament_turn"] != expected_turn:
            return f"is for turn {player_data['tournament_turn']!r}; the host expects turn {expected_turn}"

    return None


def load_move_files(map_ref, move_file_paths, keys_dict, *, accept_stat_mismatches=False,
                    accept_older_versions=False, loaded_countries=()):
    """
    Loads a list of .gd5move files and applies their orders to the host's map.

    Return counts and per-file rejection details. keys_dict maps country IDs to keys.
    accept_stat_mismatches permits numeric differences only. All other checks still apply.
    accept_older_versions converts moves from the previous release. They are then validated normally.
    A rejection the host can override names its override: "stats" or "version".
    loaded_countries preserves batch duplicate checks during a host's review callbacks.
    """
    world_state = world_for(map_ref)
    processed_move_cids = set(loaded_countries)
    summary = {"loaded": 0, "rejected": 0, "legacy": 0, "converted": 0,
               "faction_renames": 0, "appearance_updates": 0,
               "puppet_siphon_updates": 0, "rejections": [], "overridden": 0,
               "loaded_countries": []}

    def reject(file_path, cid, reason, *, override=None):
        summary["rejected"] += 1
        summary["rejections"].append({"file_path": file_path, "country_id": cid,
                                      "reason": reason, "overridable": override is not None,
                                      "override": override})

    def _decrypt_move(file_path):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                payload = json.load(f)
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            return file_path, None, None, f"Cannot read the move file: {error}"
        
        if not isinstance(payload, dict):
            return file_path, None, None, "Invalid move file: expected a JSON object."

        cid = payload.get("country_id")
        p_hash = payload.get("hash")
        
        if not isinstance(cid, str) or cid not in keys_dict:
            return file_path, None, None, "The country ID has no tournament player key."
            
        player_key = keys_dict[cid]
        if hash_key(player_key) != p_hash:
            return file_path, cid, None, "The player key does not match the host's key."
            
        player_data = decrypt_dict(payload.get("data"), player_key)
        error = None if isinstance(player_data, dict) else "Cannot decrypt a valid move record with this player's key."
        return file_path, cid, player_data, error
        
    valid_moves = {}

    def _record(result):
        file_path, cid, player_data, error = result
        valid_moves[file_path] = (cid, player_data, error)

    run_with_progress(move_file_paths, _decrypt_move,
                      "Decrypting Move Files...", _record)
                
    for file_path in move_file_paths:
        cid, player_data, error = valid_moves[file_path]
        if error:
            reject(file_path, cid, error)
            continue

        try:
            version = migrations.move_version(player_data)
        except ValueError as error:
            reject(file_path, cid, str(error))
            continue
        older_release = version < migrations.CURRENT_VERSION
        if older_release and not accept_older_versions:
            reject(file_path, cid,
                   f"This move was made with game version v{version}. The host runs {c.GAME_VERSION}. "
                   "The host can convert it. The converted move must then pass all normal checks.",
                   override="version")
            continue
        try:
            # Steps for the next release also convert moves from this release.
            migrations.upgrade_move(player_data)
        except ValueError as error:
            reject(file_path, cid, str(error))
            continue
        summary["converted"] += older_release

        context_error = _move_context_error(map_ref, player_data)
        if context_error:
            reject(file_path, cid, f"The move {context_error}.")
            continue
        if "factions" in player_data:
            reject(file_path, cid, "Players cannot replace faction records.")
            continue
        has_intents = "player_intents" in player_data
        structure_error = None if has_intents else v46_moves.structure_error(player_data)
        if structure_error:
            reject(file_path, cid, structure_error)
            continue
        if cid in processed_move_cids:
            # A country gets one coherent submission per selected batch. Applying two
            # files in picker order previously made the last one silently win.
            reject(file_path, cid, "This country already has a loaded move in this import.")
            continue
        if has_intents:
            try:
                commands = migrations.tournament_player_intents(player_data, world_state.map_data)
                service = PlayerActions(map_ref)
                validated = service.validate_draft(cid, commands)
            except ValueError as error:
                reject(file_path, cid, str(error))
                continue
            service.apply_validated_drafts({cid: validated})
        else:
            try:
                snapshot = v46_moves.prepare(map_ref, cid, player_data)
            except ValueError as error:
                reject(file_path, cid, str(error))
                continue
            if snapshot.warnings and not accept_stat_mismatches:
                reject(file_path, cid, "\n".join(snapshot.warnings), override="stats")
                continue
            v46_moves.apply(map_ref, cid, player_data, snapshot, summary)
        processed_move_cids.add(cid)

        # Also mark this country as having submitted a move
        map_ref.submitted_moves.add(cid)
        summary["loaded"] += 1
        summary["loaded_countries"].append(cid)
        
    if summary["loaded"] and hasattr(map_ref, 'sync_units_to_data'):
        map_ref.sync_units_to_data()
    if summary["loaded"] and any(
            isinstance(country, dict) and "armies" in country
            for country in world_state.nation_data.values()):
        # Nation data carries army metadata while the move file replaces the
        # submitting country's unit snapshot.  Normalize only after that
        # replacement so valid incoming member IDs are retained and malformed
        # or foreign references cannot survive host import.
        queries.normalize_armies(world_state.nation_data, world_state.map_data)

    return summary
