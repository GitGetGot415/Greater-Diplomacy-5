"""Scenario-owned music imports, selected album inventory, and standalone export files."""
import base64
import binascii
import json
import os

import data.constants as c
from data import queries
from data.io.starting_defaults import STARTING_DEFAULTS_PATH, read_starting_defaults

SONG_EXTENSIONS = c.MUSIC_AUDIO_EXTENSIONS + (".json",)


def _file_name(value):
    if not isinstance(value, str) or not value:
        return ""
    try:
        return queries.validated_scenario_name(value, label="Song Name")
    except ValueError:
        return ""


def normalized_music(value):
    """Old scenarios have no custom album, starting song, icon, or included base albums."""
    result = dict(value) if isinstance(value, dict) else {}
    for key in ("album_name", "starting_song", "icon"):
        if not isinstance(result.get(key), str):
            result[key] = ""
    songs, names = [], set()
    for song in result.get("songs", []) if isinstance(result.get("songs"), list) else ():
        if not isinstance(song, dict):
            continue
        name = _file_name(song.get("name"))
        if not name or name.casefold() in names or os.path.splitext(name)[1].lower() not in SONG_EXTENSIONS or not isinstance(song.get("data"), str) or not song["data"]:
            continue
        songs.append(dict(song, name=name))
        names.add(name.casefold())
    result["songs"] = songs
    if result["starting_song"] not in {song["name"] for song in songs}:
        result["starting_song"] = ""
    included = result.get("base_albums")
    result["base_albums"] = [album for album in c.UNDELETABLE_ALBUMS if isinstance(included, list) and album in included]
    return result


def import_song(music, path, *, starting=False):
    """Embed an imported song so the scenario does not depend on its original file."""
    music = normalized_music(music)
    extension = queries.validated_music_file(path)
    stem = os.path.splitext(os.path.basename(path))[0]
    name = queries.validated_scenario_name(stem + extension, label="Song Name")
    with open(path, "rb") as source:
        data = base64.b64encode(source.read()).decode("ascii")
    if not data:
        raise ValueError("Choose a song file that is not empty.")
    existing = next((song for song in music["songs"] if song["name"] == name and song["data"] == data), None)
    if existing is None:
        names = {song["name"].casefold() for song in music["songs"]}
        number = 2
        while name.casefold() in names:
            name = f"{stem} ({number}){extension}"
            number += 1
        music["songs"].append({"name": name, "data": data})
    if starting:
        music["starting_song"] = name
    return music


def import_icon(music, path):
    with open(path, "rb") as source:
        png = source.read()
    if not png.startswith(queries.PNG_SIGNATURE):
        raise ValueError("Choose a real PNG image for icon.png.")
    text = base64.b64encode(png).decode("ascii")
    queries.load_png_b64(text)
    return dict(normalized_music(music), icon=text)


def base_album_inventory():
    """Read shipped albums once on screen entry or before an export, never while drawing."""
    inventory = {}
    for album in c.UNDELETABLE_ALBUMS:
        root = os.path.join(c.MUSIC_DIR, album)
        if not os.path.isdir(root):
            continue
        files = []
        for parent, directories, names in os.walk(root):
            directories[:] = sorted(name for name in directories if not os.path.islink(os.path.join(parent, name)))
            for name in sorted(names):
                path = os.path.join(parent, name)
                if not os.path.isfile(path) or os.path.islink(path):
                    continue
                relative = os.path.relpath(path, root)
                files.append((path, relative, os.path.getsize(path)))
        inventory[album] = files
    return inventory


def decoded_size(text):
    return max(0, len(text) * 3 // 4 - (len(text) - len(text.rstrip("=")))) if text else 0


def music_size(music, inventory):
    music = normalized_music(music)
    return sum(decoded_size(song["data"]) for song in music["songs"]) + decoded_size(music["icon"]) + sum(size for album in music["base_albums"] for _source, _relative, size in inventory.get(album, ()))


def album_name(music, scenario_name):
    name = queries.validated_scenario_name(music["album_name"] or scenario_name, label="Album Name")
    if not name:
        raise ValueError("Set an album name before exporting custom music.")
    if name.casefold() in {album.casefold() for album in c.UNDELETABLE_ALBUMS}:
        raise ValueError("Choose a custom album name different from the base GD5 albums.")
    return name


def _decode(text, name):
    try:
        return base64.b64decode(text, validate=True)
    except (ValueError, binascii.Error) as error:
        raise ValueError(f"Import {name} again; its saved file data is invalid.") from error


def export_files(music, scenario_name, inventory=None):
    """Return copy and embedded-file queues, with all destination paths below assets/music."""
    music = normalized_music(music)
    inventory = base_album_inventory() if inventory is None else inventory
    copies, embedded = [], []
    for album in music["base_albums"]:
        if album not in inventory:
            raise ValueError(f"The base album {album} is missing. Deselect the album or restore its files.")
        copies.extend((source, os.path.join(c.MUSIC_DIR, album, relative)) for source, relative, _size in inventory[album])
    name = album_name(music, scenario_name) if music["songs"] or music["icon"] else ""
    for song in music["songs"]:
        embedded.append((os.path.join(c.MUSIC_DIR, name, song["name"]), _decode(song["data"], song["name"])))
    if music["icon"]:
        png = _decode(music["icon"], "icon.png")
        if not png.startswith(queries.PNG_SIGNATURE):
            raise ValueError("Import the album icon again; icon.png must be a real PNG image.")
        embedded.append((os.path.join(c.MUSIC_DIR, name, "icon.png"), png))
    # JSON songs need the existing synthesizers in source and frozen exports.
    needs_synth = any(path.lower().endswith(".json") and os.path.basename(path) != "volumes.json" for _source, path in copies) or any(song["name"].lower().endswith(".json") for song in music["songs"])
    if needs_synth:
        for root in ("assets/beepbox", "assets/ultrabox"):
            for parent, _directories, names in os.walk(root):
                copies.extend((os.path.join(parent, filename), os.path.join(parent, filename)) for filename in sorted(names))
    return copies, embedded


def write_music_defaults(destination, music, scenario_name):
    """Configure the exported game's one source of preference defaults before those files are written."""
    music = normalized_music(music)
    custom_name = album_name(music, scenario_name) if music["songs"] else None
    albums = ([custom_name] if custom_name else []) + music["base_albums"]
    starting = os.path.join(c.MUSIC_DIR, custom_name, music["starting_song"]).replace("\\", "/") if music["starting_song"] else None
    path = os.path.join(destination, STARTING_DEFAULTS_PATH)
    defaults = read_starting_defaults(path)
    defaults["active_albums.json"] = albums
    defaults["starting_song.json"] = {"track": starting}
    with open(path, "w", encoding="utf-8") as target:
        json.dump(defaults, target, indent=4)
        target.write("\n")
