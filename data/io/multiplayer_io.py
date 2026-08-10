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
        
    with open(file_path, 'r') as f:
        try:
            payload = json.load(f)
        except Exception:
            return False, None, None, None, None, "Invalid file format"
            
    ver_table = payload.get("verification_table", {})
    i_hash = hash_key(key)
    
    if i_hash not in ver_table:
        return False, None, None, None, None, "Invalid key"
        
    entry = ver_table[i_hash]
    decrypted_session = decrypt_dict(entry["enc_session"], key)
    
    if not decrypted_session or "sk" not in decrypted_session:
        return False, None, None, None, None, "Decryption failed (corrupt key payload)"
        
    session_key = decrypted_session["sk"]
    
    game_data = decrypt_dict(payload["game_data"], session_key)
    history = decrypt_dict(payload["history"], session_key) if payload.get("history") else []
    
    if not game_data:
        return False, None, None, None, None, "Failed to decrypt game data"
        
    temp_dir = os.path.join(c.TOURNAMENT_SAVES_DIR, "temp_load")
    os.makedirs(temp_dir, exist_ok=True)
    
    # Extract raw geometry if present
    raw_map_data = game_data.pop("_raw_map_data", None)
    if raw_map_data:
        with open(os.path.join(temp_dir, "map_data.json"), 'w') as f:
            json.dump(raw_map_data, f)
            
    # Extract images if present
    images = game_data.pop("_images", {})
    for name, b64_str in images.items():
        img_path = os.path.join(temp_dir, name)
        with open(img_path, "wb") as f:
            f.write(base64.b64decode(b64_str))
            
    with open(os.path.join(temp_dir, "meta.json"), 'w') as f:
        json.dump(game_data, f)
        
    if history:
        with open(os.path.join(temp_dir, "history.json"), 'w') as f:
            json.dump(history, f)
    
    role = entry.get("role")
    cid = entry.get("country_id")
    keys_dict = decrypted_session.get("keys_dict", {})
    
    return True, role, cid, temp_dir, keys_dict, "Loaded successfully", session_key, ver_table

def export_move_file(map_ref, file_path, player_key):
    """
    Exports a .gd5move file containing ONLY the orders for the current turn.
    """
    save_dict = queries.build_save_dict(map_ref)
    cid = map_ref.player_country
    
    player_data = {
        "nation_data": save_dict.get("nation_data", {}).get(cid, {}),
        "provinces": {}
    }
    
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

def load_move_files(map_ref, move_file_paths, keys_dict):
    """
    Loads a list of .gd5move files and applies their orders to the host's map_ref.
    keys_dict maps Country_ID -> Country_Key
    """
    processed_cids = set()

    def _decrypt_move(file_path):
        if not os.path.exists(file_path):
            return None
        with open(file_path, 'r') as f:
            try:
                payload = json.load(f)
            except Exception:
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
            continue
            
        cid, player_data = valid_moves[file_path]
        if not player_data:
            continue
            
        if "nation_data" in player_data and "provinces" in player_data:
            nd = player_data["nation_data"]
            provs = player_data["provinces"]
        else:
            nd = player_data
            provs = {}
            
        if cid in map_ref.nation_data:
            map_ref.nation_data[cid] = nd
            
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
        
    if move_file_paths and hasattr(map_ref, 'sync_units_to_data'):
        map_ref.sync_units_to_data()
