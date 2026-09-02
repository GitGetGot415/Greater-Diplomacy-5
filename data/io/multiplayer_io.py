import os
import json
import hashlib
import base64
import secrets
from cryptography.fernet import Fernet
import data.constants as c
from data import queries
from data.platform import sync_persisted_dir

def active_owners_of(map_ref):
    """Every nation that actually holds a province right now.

    Empty when there is no map loaded, which callers read as "no filter".
    Written out twice before.
    """
    if not getattr(map_ref, "map_data", None):
        return set()
    return set(p.get("owner") for p in map_ref.map_data.values() if p.get("owner"))


def display_name(nation_data, cid):
    """A country's readable name, falling back to its id.

    The isinstance guard is what makes this safe on a nation table that holds
    non-dict utility entries. Three key-listing loops repeated it.
    """
    entry = nation_data.get(cid)
    return entry.get("name", cid) if isinstance(entry, dict) else cid


def run_with_progress(jobs, worker, caption, on_result):
    """Runs `worker` over `jobs` in a thread pool, drawing the loading bar.

    Both the key-encryption pass and the move-decryption pass drove their own
    identical copy of this loop, down to the pygame.event.pump() that keeps the
    window responsive while the pool works.
    """
    import concurrent.futures
    import pygame
    from map_logic.turn_processing import loading_screen

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
                loading_screen.draw_simple_refresh_bar(surface, caption, completed, total)
                pygame.display.flip()


def hash_key(key):
    return hashlib.sha256(key.encode('utf-8')).hexdigest()

def generate_fernet_key_from_password(password, salt):
    derived_key = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt,
        200_000
    )
    return base64.urlsafe_b64encode(derived_key)

def encrypt_dict(data_dict, password):
    salt = secrets.token_bytes(16)
    key = generate_fernet_key_from_password(password, salt)
    f = Fernet(key)
    json_bytes = json.dumps(data_dict).encode('utf-8')
    encrypted_token = f.encrypt(json_bytes).decode('utf-8')
    salt_b64 = base64.urlsafe_b64encode(salt).decode('utf-8')
    return f"{salt_b64}:{encrypted_token}"

def decrypt_dict(encrypted_str, password):
    try:
        salt_b64, encrypted_token = encrypted_str.split(":", 1)
        salt = base64.urlsafe_b64decode(salt_b64.encode('utf-8'))
        key = generate_fernet_key_from_password(password, salt)
        f = Fernet(key)
        json_bytes = f.decrypt(encrypted_token.encode('utf-8'))
        return json.loads(json_bytes.decode('utf-8'))
    except Exception:
        return None

def strip_sensitive_data_for_player(map_ref, country_id):
    """
    Modifies the active map_ref in place to hide information that the player should not see.
    """
    map_ref.multiplayer_mode = True
    map_ref.player_country = country_id
    map_ref.active_players = [country_id]
    map_ref.current_player_index = 0

    for cid, country in map_ref.nation_data.items():
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

def write_host_keys(map_ref, keys_dict, output_dir=None):
    if output_dir is None:
        output_dir = c.TOURNAMENT_SAVES_DIR
    os.makedirs(output_dir, exist_ok=True)
    
    all_keys_path = os.path.join(output_dir, "ALL_Host_Keys.txt")
    keys_path = os.path.join(output_dir, "Host_Keys.txt")
    
    active_owners = active_owners_of(map_ref)
    nation_data = getattr(map_ref, 'nation_data', {})
    
    with open(all_keys_path, 'w') as f:
        f.write("Every key for every possible country:\n\n")
        for cid, key in keys_dict.items():
            name = display_name(nation_data, cid)
            f.write(f"{name} (ID {cid}): {key}\n")
            
    with open(keys_path, 'w') as f:
        f.write("Distribute these keys to your players:\n\n")
        for cid, key in keys_dict.items():
            if cid in active_owners:
                name = display_name(nation_data, cid)
                f.write(f"{name} (ID {cid}): {key}\n")

    # Web only: mirror the whole tournament_saves tree into IndexedDB so it
    # survives closing the tab (output_dir is always somewhere under this
    # root). No-op on desktop.
    sync_persisted_dir(c.TOURNAMENT_SAVES_DIR)

    return keys_path, all_keys_path

def export_tournament(map_ref, file_path, master_key, keys_dict):
    """
    keys_dict maps Country_ID -> Country_Key
    """
    import shutil
    output_dir = os.path.dirname(file_path)
    os.makedirs(output_dir, exist_ok=True)
    
    # Process pending key regenerations if any
    pending_regen = getattr(map_ref, 'multiplayer_pending_key_regen', set())
    regenerated_keys = {}
    if pending_regen:
        for cid in list(pending_regen):
            new_key = secrets.token_hex(4)
            keys_dict[cid] = new_key
            if hasattr(map_ref, 'multiplayer_keys_dict'):
                map_ref.multiplayer_keys_dict[cid] = new_key
            nation_data = getattr(map_ref, 'nation_data', {})
            name = display_name(nation_data, cid)
            regenerated_keys[cid] = (name, new_key)
        map_ref.multiplayer_pending_key_regen.clear()

    keys_path, all_keys_path = write_host_keys(map_ref, keys_dict, output_dir=output_dir)
    
    if regenerated_keys:
        turn = map_ref.time_manager.total_turns if hasattr(map_ref, 'time_manager') else 0
        regen_keys_path = os.path.join(output_dir, f"Turn_{turn}_Regenerated_Keys.txt")
        with open(regen_keys_path, 'w') as f:
            f.write(f"Regenerated keys for Turn {turn}:\n\n")
            for cid, (name, new_key) in regenerated_keys.items():
                f.write(f"{name} (ID {cid}): {new_key}\n")

    from data import queries
    queries.scrub_default_images(map_ref.nation_data)
    save_dict = queries.build_save_dict(map_ref)
    
    # Embed the raw geometry so the tournament file is self-contained
    if hasattr(map_ref, 'raw_json_data'):
        save_dict["_raw_map_data"] = map_ref.raw_json_data
        
    import pygame
    temp_img_dir = os.path.join(c.TOURNAMENT_SAVES_DIR, "temp_img_export")
    os.makedirs(temp_img_dir, exist_ok=True)
    images = {}
    
    try:
        img_names = {
            "terrain.png": getattr(map_ref, 'terrain_map', None),
            "id_map.png": getattr(map_ref, 'id_map', None),
            "political.png": getattr(map_ref, 'political_map', None),
            "cores.png": getattr(map_ref, 'cores_map', None)
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
    
    session_key = getattr(map_ref, 'multiplayer_session_key', None)
    if not session_key:
        session_key = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode('utf-8')
        map_ref.multiplayer_session_key = session_key

    player_enc_cache = getattr(map_ref, 'multiplayer_player_enc_cache', {})
    
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
        }
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
            
    game_data_enc = encrypt_dict(save_dict, session_key)
    history_enc = None # History omitted for tournament saves to reduce file size
    
    payload = {
        "verification_table": verification_table,
        "game_data": game_data_enc,
        "history": history_enc
    }
    
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, 'w') as f:
        json.dump(payload, f, indent=c.SAVE_INDENT)

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
    except Exception:
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

    history = decrypt_dict(payload.get("history"), session_key) if payload.get("history") else []
    if history is None:
        history = []

    role = entry.get("role")
    cid = entry.get("country_id")
    if role not in ("HOST", "PLAYER"):
        return False, None, None, None, None, "Invalid tournament role"
    if role == "PLAYER" and cid is None:
        return False, None, None, None, None, "Invalid player entry"

    keys_dict = decrypted_session.get("keys_dict", {})
    if not isinstance(keys_dict, dict):
        return False, None, None, None, None, "Invalid key payload"

    temp_dir = os.path.join(c.TOURNAMENT_SAVES_DIR, "temp_load")
    os.makedirs(temp_dir, exist_ok=True)

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
                json.dump(raw_map_data, f)

        expected_image_names = {"terrain.png", "id_map.png", "political.png", "cores.png"}
        for name, b64_str in images.items():
            if name not in expected_image_names or not isinstance(b64_str, str):
                return False, None, None, None, None, "Invalid tournament image data"
            img_path = os.path.join(temp_dir, name)
            with open(img_path, "wb") as f:
                f.write(base64.b64decode(b64_str, validate=True))

        with open(os.path.join(temp_dir, "meta.json"), 'w') as f:
            json.dump(game_data, f)

        if history:
            with open(os.path.join(temp_dir, "history.json"), 'w') as f:
                json.dump(history, f)
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
    save_dict = queries.build_save_dict(map_ref)
    cid = map_ref.player_country
    
    player_data = {
        "nation_data": save_dict.get("nation_data", {}).get(cid, {}),
        "provinces": {}
    }

    session_key = getattr(map_ref, "multiplayer_session_key", None)
    if session_key:
        player_data["tournament_session"] = session_key
    if hasattr(map_ref, "time_manager"):
        player_data["tournament_turn"] = map_ref.time_manager.total_turns

    # A faction rename affects every member, while normal move data contains
    # only one nation record.  Preserve it as a separate host-validated command
    # rather than allowing the renamed leader to drift away from its members.
    pending_renames = getattr(map_ref, "multiplayer_pending_faction_renames", ())
    if pending_renames:
        player_data["faction_renames"] = list(pending_renames)

    pending_appearances = getattr(map_ref,
                                  "multiplayer_pending_appearance_updates", {})
    if pending_appearances:
        player_data["appearance_updates"] = [
            {"country_id": target, "appearance": appearance}
            for target, appearance in pending_appearances.items()
        ]
    
    for prov_key, prov_data in save_dict.get("provinces", {}).items():
        prov_updates = {}
        if prov_data.get("owner") == cid:
            if "building_queue" in prov_data:
                prov_updates["building_queue"] = prov_data["building_queue"]
            if "unit_queue" in prov_data:
                prov_updates["unit_queue"] = prov_data["unit_queue"]
                
        player_units = [u for u in prov_data.get("units", []) if u.get("owner") == cid]
        if player_units:
            prov_updates["units"] = player_units
            
        if prov_updates:
            player_data["provinces"][prov_key] = prov_updates
            
    payload = {
        "country_id": cid,
        "hash": hash_key(player_key),
        "data": encrypt_dict(player_data, player_key)
    }
    
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, 'w') as f:
        json.dump(payload, f, indent=c.SAVE_INDENT)

    # Web only: mirror the .gd5move into IndexedDB so it survives closing the
    # tab. No-op on desktop.
    sync_persisted_dir(c.TOURNAMENT_SAVES_DIR)

def _move_context_error(map_ref, player_data):
    """Returns a reason a move targets the wrong tournament turn, if any.

    Old move files did not contain these fields, so they remain loadable for
    an in-progress tournament created by an earlier release.  Every newly
    exported move carries both values and is checked strictly.
    """
    expected_session = getattr(map_ref, "multiplayer_session_key", None)
    move_session = player_data.get("tournament_session")
    if move_session is not None and move_session != expected_session:
        return "belongs to a different tournament"

    if "tournament_turn" in player_data:
        time_manager = getattr(map_ref, "time_manager", None)
        expected_turn = getattr(time_manager, "total_turns", None)
        if player_data["tournament_turn"] != expected_turn:
            return "is for a different turn"

    return None


def _is_valid_map_color(color):
    return (isinstance(color, (list, tuple)) and len(color) in (3, 4)
            and all(isinstance(channel, int) and 0 <= channel <= 255
                    for channel in color))


def _sync_appearance_caches(map_ref, country_id, nation_data):
    """Keep cached country colours and labels consistent with a move import."""
    color = nation_data.get("color")
    if _is_valid_map_color(color) and hasattr(map_ref, "nation_colors"):
        map_ref.nation_colors[country_id] = tuple(color)

    from map_logic.rendering import country_names
    country_names.clear_country_name_cache(map_ref)


def _apply_faction_renames(map_ref, country_id, player_data, nation_update):
    """Apply a player's faction-rename commands before merging their move.

    A command is checked against the host's current roster, not the player's
    stale copy.  That prevents a non-leader from renaming a faction and means
    a later move from another member cannot undo an already accepted rename.
    """
    from map_logic.diplomacy import faction_actions

    has_commands = "faction_renames" in player_data
    commands = player_data.get("faction_renames", ())
    if commands is None:
        commands = ()
    if has_commands and not isinstance(commands, list):
        return 0

    applied = 0
    for command in commands:
        if not isinstance(command, dict):
            continue
        old_name = command.get("old_name")
        new_name = command.get("new_name")
        current_name = map_ref.nation_data.get(country_id, {}).get("faction", "")

        # Re-importing the same move is harmless.  In particular this lets a
        # player load their own already-exported move without renaming twice.
        if current_name == new_name:
            continue

        if faction_actions.rename_faction(map_ref.nation_data, country_id,
                                          old_name, new_name):
            applied += 1

    # Compatibility for a move exported by the prior tournament format: its
    # leader record is the only evidence of the rename.  Infer it only when
    # the host still has that country as the current leader, which is precisely
    # what the old Rename Faction UI was allowed to do.
    if not has_commands and isinstance(nation_update, dict):
        old_name = map_ref.nation_data.get(country_id, {}).get("faction", "")
        new_name = nation_update.get("faction", old_name)
        if old_name != new_name:
            if faction_actions.rename_faction(map_ref.nation_data, country_id,
                                              old_name, new_name):
                applied += 1

    if applied:
        from map_logic.rendering import country_names
        country_names.clear_country_name_cache(map_ref)
    return applied


def _merge_player_nation_data(map_ref, country_id, nation_update):
    """Merge a player's record without accepting faction state by accident.

    Faction membership is shared state.  The player can queue a leave/invite
    in their normal diplomacy data, but the authoritative outcome is resolved
    by the host at turn processing.  A member's old move must therefore not
    restore the previous faction string after its leader has renamed the bloc.
    """
    if not isinstance(nation_update, dict) or country_id not in map_ref.nation_data:
        return False

    existing = map_ref.nation_data[country_id]
    faction_state = {
        key: existing[key]
        for key in ("faction", "is_faction_leader", "faction_pressure", "faction_tenure")
        if key in existing
    }
    merged = dict(nation_update)
    for key in ("faction", "is_faction_leader", "faction_pressure", "faction_tenure"):
        if key in faction_state:
            merged[key] = faction_state[key]
        else:
            merged.pop(key, None)

    map_ref.nation_data[country_id] = merged
    if any(existing.get(key) != merged.get(key)
           for key in ("name", "adjective", "leader_name", "leader_title",
                       "flag_data", "portrait_data", "color")):
        _sync_appearance_caches(map_ref, country_id, merged)
    return True


def _apply_appearance_updates(map_ref, country_id, player_data):
    """Apply permitted integrated-puppet appearance edits from one move.

    The puppet editor intentionally lets a country customise its integrated
    subjects, but those nation records are not otherwise part of that
    country's move file.  The host verifies the ownership relationship and
    limits the payload to the fields that screen actually edits.
    """
    updates = player_data.get("appearance_updates", ())
    if not isinstance(updates, list):
        return 0

    appearance_keys = ("name", "adjective", "leader_name", "leader_title",
                       "flag_data", "portrait_data", "color")
    applied = 0
    for update in updates:
        if not isinstance(update, dict):
            continue
        target = update.get("country_id")
        appearance = update.get("appearance")
        target_data = map_ref.nation_data.get(target)
        if (not isinstance(target_data, dict) or not isinstance(appearance, dict)
                or target_data.get("master") != country_id
                or target_data.get("puppet_type") != c.PUPPET_TYPE_INTEGRATED):
            continue

        for key in appearance_keys[:-1]:
            value = appearance.get(key)
            if isinstance(value, str):
                target_data[key] = value

        color = appearance.get("color")
        if _is_valid_map_color(color):
            target_data["color"] = list(color)
        applied += 1

    if applied:
        for update in updates:
            if isinstance(update, dict):
                target = update.get("country_id")
                target_data = map_ref.nation_data.get(target)
                if isinstance(target_data, dict):
                    _sync_appearance_caches(map_ref, target, target_data)
    return applied


def load_move_files(map_ref, move_file_paths, keys_dict):
    """
    Loads a list of .gd5move files and applies their orders to the host's map.

    Returns a summary with ``loaded``, ``rejected``, and ``legacy`` counts so
    callers can report what happened instead of claiming every selected file
    was imported.  ``keys_dict`` maps Country_ID -> Country_Key.
    """
    processed_cids = set()
    processed_move_cids = set()
    summary = {"loaded": 0, "rejected": 0, "legacy": 0,
               "faction_renames": 0, "appearance_updates": 0}

    def _decrypt_move(file_path):
        if not os.path.exists(file_path):
            return None
        with open(file_path, 'r') as f:
            try:
                payload = json.load(f)
            except Exception:
                return None
        
        if not isinstance(payload, dict):
            return None

        cid = payload.get("country_id")
        p_hash = payload.get("hash")
        
        if cid not in keys_dict:
            return None
            
        player_key = keys_dict[cid]
        if hash_key(player_key) != p_hash:
            return None
            
        player_data = decrypt_dict(payload.get("data"), player_key)
        return file_path, cid, player_data
        
    valid_moves = {}

    def _record(result):
        file_path, cid, player_data = result
        valid_moves[file_path] = (cid, player_data)

    run_with_progress(move_file_paths, _decrypt_move,
                      "Decrypting Move Files...", _record)
                
    for file_path in move_file_paths:
        if file_path not in valid_moves:
            summary["rejected"] += 1
            continue
            
        cid, player_data = valid_moves[file_path]
        if not isinstance(player_data, dict):
            summary["rejected"] += 1
            continue

        context_error = _move_context_error(map_ref, player_data)
        if context_error:
            summary["rejected"] += 1
            continue
        if "tournament_session" not in player_data or "tournament_turn" not in player_data:
            summary["legacy"] += 1
            
        if "nation_data" in player_data and "provinces" in player_data:
            nd = player_data["nation_data"]
            provs = player_data["provinces"]
        else:
            nd = player_data
            provs = {}
            
        if not isinstance(nd, dict) or not isinstance(provs, dict):
            summary["rejected"] += 1
            continue

        if cid in processed_move_cids:
            # A country gets one coherent submission per turn.  Applying two
            # files in picker order previously made the last one silently win.
            summary["rejected"] += 1
            continue
        processed_move_cids.add(cid)

        summary["faction_renames"] += _apply_faction_renames(
            map_ref, cid, player_data, nd)
        if not _merge_player_nation_data(map_ref, cid, nd):
            summary["rejected"] += 1
            continue
        summary["appearance_updates"] += _apply_appearance_updates(
            map_ref, cid, player_data)
            
        if provs:
            if cid not in processed_cids:
                for target_prov in map_ref.map_data.values():
                    target_prov["units"] = [u for u in target_prov.get("units", []) if u.get("owner") != cid]
                processed_cids.add(cid)
                
            # Create a lookup for json_key -> tuple key
            json_key_map = {v.get("json_key"): k for k, v in map_ref.map_data.items()}
                
            for prov_key, updates in provs.items():
                real_key = json_key_map.get(prov_key)
                if real_key not in map_ref.map_data:
                    continue
                target_prov = map_ref.map_data[real_key]
                
                if "building_queue" in updates:
                    target_prov["building_queue"] = updates["building_queue"]
                if "unit_queue" in updates:
                    target_prov["unit_queue"] = updates["unit_queue"]
                    
                if "units" in updates:
                    if "units" not in target_prov:
                        target_prov["units"] = []
                    target_prov["units"].extend(updates["units"])
            
        # Also mark this country as having submitted a move
        if not hasattr(map_ref, 'submitted_moves'):
            map_ref.submitted_moves = set()
        map_ref.submitted_moves.add(cid)
        summary["loaded"] += 1
        
    if summary["loaded"] and hasattr(map_ref, 'sync_units_to_data'):
        map_ref.sync_units_to_data()

    return summary
