"""File operations, saved-content summaries, research projects, and country appearance helpers."""

import copy
import json
import data.constants as c
import os
import re
import shutil
import zipfile
import beepbox_audio
from data.queries.tech import get_tech_requirements
from data.queries.countries import get_country_display_name
from data.queries.saves import normalized_scenario_metadata
from data import queries
from data import migrations


def import_destination_path(source_path, saves_dir, prefix, fallback_name):
    """Choose an unused save folder for a file imported from another game."""
    stem = re.sub(r"[^A-Za-z0-9 _-]+", "", os.path.splitext(os.path.basename(source_path))[0]).strip()
    stem = stem or fallback_name
    base = os.path.join(saves_dir, f"{prefix} - {stem}")
    destination, suffix = base, 2
    while os.path.exists(destination):
        destination = f"{base} ({suffix})"
        suffix += 1
    return destination


def read_saved_content_summary(directory):
    """Read browser details without loading map geometry, images, or history."""
    result = {"details": [], "error": "", "date_label": "", "author": "", "description": ""}
    if not os.path.isfile(os.path.join(directory, "map_data.json")):
        result["error"] = "map_data.json is missing. Import a complete map or save."
    meta_path = os.path.join(directory, "meta.json")
    if not os.path.exists(meta_path):
        return result
    try:
        with open(meta_path, encoding="utf-8") as source:
            meta = json.load(source)
        if not isinstance(meta, dict):
            raise ValueError("meta.json must contain an object.")
        migrations.check_version(meta.get("version"))
        metadata = normalized_scenario_metadata(meta.get("scenario_metadata", {}))
    except (OSError, ValueError) as error:
        result["error"] = f"Cannot open this item: {error}"
        return result

    details = result["details"]
    result.update({key: metadata[key] for key in ("author", "description")})
    date = meta.get("date", {})
    if isinstance(date, dict):
        # Dates are display-only here. The loader owns defaults and conversion.
        day, month, year = date.get("day"), date.get("month"), date.get("year")
        if all(isinstance(value, int) for value in (day, month, year)) and 0 <= month < 12:
            result["date_label"] = f"{day}/{month + 1}/{year}"
            details.append(f"Game date: {result['date_label']} (day/month/year)")
        if isinstance(date.get("total_turns"), int):
            details.append(f"Turn: {date['total_turns']}")
    country = meta.get("player_country")
    if country and country != "None":
        if country == "Spectator":
            details.append("Player: Spectator")
        elif isinstance(country, str):
            nations = dict(queries.get_country_data())
            saved_nations = meta.get("nation_data", {})
            if isinstance(saved_nations, dict):
                nations.update({key: value for key, value in saved_nations.items() if value})
            details.append(f"Player: {get_country_display_name(country, nations)}")
    if meta.get("version"):
        details.append(f"Game version: {meta['version']}")
    if metadata["author"]:
        details.append(f"Author: {metadata['author']}")
    if metadata["description"]:
        details.extend(("", metadata["description"]))
    return result


def validated_scenario_name(name, label="Scenario Name"):
    """Accept a single portable folder name, or empty text for automatic naming."""
    if not isinstance(name, str):
        raise ValueError(f"{label} must be text.")
    name = name.strip()
    if not name:
        return ""
    if (name in (".", "..") or name.endswith(".")
            or any(char in '<>:"/\\|?*' or ord(char) < 32 for char in name)):
        raise ValueError(f'{label} cannot contain <>:"/\\|?*, control characters, or end with a period.')
    base = name.split(".", 1)[0].upper()
    if base in ("CON", "PRN", "AUX", "NUL") or re.fullmatch(r"(?:COM|LPT)[1-9]", base):
        raise ValueError(f"{label} is reserved by the operating system. Choose another name.")
    return name


def is_deletable_album(album):
    """True unless the album is listed in c.UNDELETABLE_ALBUMS."""
    return album not in c.UNDELETABLE_ALBUMS


def create_album(name):
    """Makes an empty album folder under c.MUSIC_DIR and returns its folder name.

    Raises ValueError with a player-readable message when the name cannot be used.
    """
    name = validated_scenario_name(name, label="Album Name")
    if not name:
        raise ValueError("Enter a name for the album.")
    existing = {folder.casefold() for folder in os.listdir(c.MUSIC_DIR)} if os.path.isdir(c.MUSIC_DIR) else set()
    if name.casefold() in existing:
        raise ValueError(f"An album named {name} already exists.")
    album_dir = os.path.join(c.MUSIC_DIR, name)
    try:
        os.makedirs(album_dir)
    except OSError as error:
        raise ValueError(f"Could not create the album: {error}") from error
    queries.sync_persisted_dir(c.MUSIC_DIR)
    return name


def validated_music_file(source_path):
    """Validate an imported song with the same formats used by the music player."""
    extension = os.path.splitext(source_path)[1].lower()
    if not (extension in c.MUSIC_AUDIO_EXTENSIONS or (extension == ".json" and beepbox_audio.is_beepbox_song(source_path))):
        raise ValueError("The game plays MP3, WAV, and OGG files, and BeepBox or UltraBox JSON songs.")
    return extension


def add_song_to_album(source_path, album):
    """Copies a song file into an album folder and returns the new file name.

    Raises ValueError for an album in c.UNDELETABLE_ALBUMS, a missing album, a file
    the game cannot play, or a copy that fails.
    """
    album_dir = os.path.join(c.MUSIC_DIR, album)
    if not is_deletable_album(album) or not os.path.isdir(album_dir):
        raise ValueError(f"Songs cannot be added to {album}.")
    extension = validated_music_file(source_path)
    stem = os.path.splitext(os.path.basename(source_path))[0]
    file_name = stem + extension
    copy_number = 1
    while os.path.exists(os.path.join(album_dir, file_name)):
        copy_number += 1
        file_name = f"{stem} ({copy_number}){extension}"
    try:
        shutil.copy2(source_path, os.path.join(album_dir, file_name))
    except OSError as error:
        raise ValueError(f"Could not add the song: {error}") from error
    queries.sync_persisted_dir(c.MUSIC_DIR)
    return file_name


def is_deletable_song(track_path):
    """True when the song's album folder is not in c.UNDELETABLE_ALBUMS."""
    return is_deletable_album(os.path.basename(os.path.dirname(track_path)))


def delete_song(track_path):
    """Deletes one song file from its album folder.

    Raises ValueError for a song in an undeletable album, a path outside an album
    folder, a missing file, or a delete that fails.
    """
    album = os.path.basename(os.path.dirname(track_path))
    album_dir = os.path.join(c.MUSIC_DIR, album)
    if (not is_deletable_album(album) or os.path.normpath(os.path.dirname(track_path)) != os.path.normpath(album_dir)
            or not os.path.isfile(track_path)):
        raise ValueError(f"{os.path.basename(track_path)} cannot be deleted here.")
    try:
        os.remove(track_path)
    except OSError as error:
        raise ValueError(f"Could not delete the song: {error}") from error
    queries.sync_persisted_dir(c.MUSIC_DIR)


def delete_album(album):
    """Deletes an album folder.

    Raises ValueError for an album in c.UNDELETABLE_ALBUMS, or when the folder cannot be removed.
    """
    if not is_deletable_album(album):
        raise ValueError(f"{album} ships with the game, so it cannot be deleted here.")
    try:
        shutil.rmtree(os.path.join(c.MUSIC_DIR, album))
    except OSError as error:
        raise ValueError(f"Could not delete the album: {error}") from error
    queries.sync_persisted_dir(c.MUSIC_DIR)


def extract_and_flatten_zip(zip_path, extract_target_dir):
    """
    Extracts a zip file and flattens it if the archiver created a redundant root directory.
    This fixes the issue where importing a map/mod creates folder/folder/data.json.
    """
    # Ensure the target directory exists before unpacking
    os.makedirs(extract_target_dir, exist_ok=True)

    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(extract_target_dir)

    # Remove macOS junk folder which often breaks the single directory check
    macosx_path = os.path.join(extract_target_dir, "__MACOSX")
    if os.path.exists(macosx_path):
        shutil.rmtree(macosx_path)

    # Filter out OS junk files (like .DS_Store on Mac) to see if there's only one REAL item
    valid_items = [item for item in os.listdir(extract_target_dir) if not item.startswith('.')]

    # If the only valid item extracted is a single directory, it's been nested. Let's flatten it.
    if len(valid_items) == 1:
        single_folder_path = os.path.join(extract_target_dir, valid_items[0])
        
        if os.path.isdir(single_folder_path):
            # Move all internal contents up one level into the target directory
            for item in os.listdir(single_folder_path):
                shutil.move(os.path.join(single_folder_path, item), extract_target_dir)
            
            # Clean up the now-empty redundant folder
            try:
                os.rmdir(single_folder_path)
            except OSError:
                shutil.rmtree(single_folder_path)
    else:
        # Fallback: If there are multiple items but map_data.json is hiding inside a subdirectory
        if not os.path.exists(os.path.join(extract_target_dir, "map_data.json")):
            for item in valid_items:
                potential_path = os.path.join(extract_target_dir, item)
                if os.path.isdir(potential_path) and os.path.exists(os.path.join(potential_path, "map_data.json")):
                    # Found the true map folder, flatten it!
                    for sub_item in os.listdir(potential_path):
                        shutil.move(os.path.join(potential_path, sub_item), extract_target_dir)
                    
                    try:
                        os.rmdir(potential_path)
                    except OSError:
                        shutil.rmtree(potential_path) # Fallback if hidden files got left behind
                    break


MAX_UNIT_ORDER_PATH = 200


def build_research_project(tech_name, points_remaining):
    """Construct the current project schema without changing progress policy."""
    return {"tech_name": tech_name, "points_remaining": points_remaining}


def canonical_research_selection(country_data, requested, tech_tree=None, *, context=None):
    """Preview an ordered selection using authoritative progress and prerequisites."""
    if (not isinstance(requested, list) or len(requested) > c.RESEARCH_SLOTS or
            any(not isinstance(tech, str) for tech in requested) or
            len(set(requested)) != len(requested)):
        raise ValueError("Invalid research selection.")
    if not isinstance(country_data, dict):
        raise ValueError("Unknown country research selection.")
    tech_tree = queries.get_tech_tree(context) if tech_tree is None else tech_tree
    research = country_data.get("research", {})
    if not isinstance(research, dict):
        raise ValueError("Invalid authoritative research data.")
    current_queue = country_data.get("research_queue", [])
    if not isinstance(current_queue, list):
        raise ValueError("Invalid authoritative research queue.")
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
            raise ValueError("Unknown research technology.")
        if tech_name in running:
            # Keep the server's project object and progress, never the
            # similarly shaped value supplied by a client.
            project = copy.deepcopy(running[tech_name])
        else:
            current_level = research.get(tech_name, 0)
            if not isinstance(current_level, int) or current_level < 0:
                raise ValueError("Invalid research level.")
            if current_level >= tech.get("max_lvl", 0):
                raise ValueError("That research is already complete.")
            if not queries.check_tech_requirements(research, get_tech_requirements(tech, current_level + 1), current_level + 1):
                raise ValueError("Research requirements are not met.")
            cost = tech.get("cost")
            if not isinstance(cost, (int, float)) or cost <= 0:
                raise ValueError("Invalid research technology.")
            remaining = progress.pop(tech_name, cost)
            if not isinstance(remaining, (int, float)) or remaining < 0:
                remaining = cost
            project = build_research_project(tech_name, remaining)
        progress.pop(tech_name, None)
        canonical_projects.append(project)
    return {"projects": canonical_projects,
            "research_progress": progress}


def apply_country_appearance(nation_data, country_id, appearance):
    """Apply identity fields after the caller validates its mode and authority."""
    if country_id not in nation_data or not isinstance(appearance, dict):
        raise ValueError("Invalid country appearance target or data.")
    if set(appearance) - set(c.COUNTRY_APPEARANCE_FIELDS):
        raise ValueError("Country appearance cannot change gameplay fields.")
    country = nation_data[country_id]
    changed = tuple(key for key, value in appearance.items() if country.get(key) != value)
    country.update(copy.deepcopy(appearance))
    return changed
