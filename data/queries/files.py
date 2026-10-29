"""Export, import, ZIP, and file-picker helpers."""

import copy
import data.constants as c
import json
import os
import shutil
import zipfile
from pathlib import Path
from data.platform import sync_persisted_dir
from data.queries.tech import get_tech_requirements
from data import queries


def export_with_overwrite_confirmation(file_path, export, parent=None):
    """Run an export after confirmation when its destination already exists."""
    if not os.path.exists(file_path):
        return export()

    from ui import dialogs as confirm_dialog

    def after_choice(overwrite):
        if overwrite:
            export()

    confirm_dialog.ask_yes_no(
        "Overwrite existing file?",
        f"{os.path.basename(file_path)} already exists in:\n{os.path.dirname(file_path) or '.'}\n\n"
        "Overwrite this file?",
        on_result=after_choice, tk_parent=parent, yes_label="Overwrite", no_label="Cancel")
    return None


def _export_to_downloads(file_name, produce, parent=None):
    """Sends a file to the user, however it gets made.

    Desktop: written straight into the real Downloads folder. Web: there is no
    real filesystem to write into, so it is built in the browser's virtual FS
    and then handed to platform.download_file(), which uses pygbag's JS bridge
    to push it out to the user's real Downloads folder as a browser download.

    `produce(dest_path)` is the only part that differs between exporting a
    zipped folder and copying one file -- the destination, the web/desktop
    split and the success/error dialogs were written out twice, identically.
    """
    from ui import dialogs as confirm_dialog
    dest_path = file_name if queries.IS_WEB else os.path.join(queries.downloads_dir(), file_name)

    def export():
        try:
            produce(dest_path)

            if queries.IS_WEB:
                queries.download_file(dest_path)
                confirm_dialog.show_success("Export Success", f"{file_name} downloaded.", tk_parent=parent)
            else:
                confirm_dialog.show_success("Export Success", f"Exported to Downloads as {file_name}", tk_parent=parent)
            return dest_path
        except (OSError, ValueError, zipfile.BadZipFile, zipfile.LargeZipFile) as e:
            confirm_dialog.show_error("Export Error", str(e), tk_parent=parent)
            return None

    return export_with_overwrite_confirmation(dest_path, export, parent)


def _readable_json_payload(file_path):
    """Return a pretty JSON export payload, or ``None`` for other/unreadable files.

    Existing scenarios and saves may still contain compact JSON. Formatting the
    entry while building the ZIP makes those exports readable too, without
    rewriting the user's source folder just to change whitespace.
    """
    # Current histories are gzip files. Leave legacy plain history.json alone
    # so exporting an old, potentially very large timeline stays streaming and
    # does not require loading the whole history just to change whitespace.
    if (not file_path.lower().endswith(".json")
            or os.path.basename(file_path).lower() == "history.json"):
        return None
    try:
        with open(file_path, "r", encoding="utf-8") as file:
            value = json.load(file)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return json.dumps(value, indent=c.SAVE_INDENT).encode("utf-8")


def export_dir_as_zip(source_dir, zip_name, parent=None):
    """Zips a folder and sends it to the user.

    Counterpart to extract_and_flatten_zip, and the single implementation
    behind every "Export" button (saves, scenarios). JSON entries are formatted
    in the archive so older compact saves are readable too.
    """
    def zip_it(dest_path):
        with zipfile.ZipFile(dest_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root_dir, _dirs, files in os.walk(source_dir):
                for file in files:
                    full = os.path.join(root_dir, file)
                    archive_name = os.path.relpath(full, source_dir)
                    readable_json = _readable_json_payload(full)
                    if readable_json is None:
                        zipf.write(full, archive_name)
                    else:
                        zipf.writestr(archive_name, readable_json)

    return queries._export_to_downloads(zip_name, zip_it, parent)


def export_json_file(source_path, file_name, parent=None):
    """Copies a single JSON file to the user's Downloads folder."""
    return queries._export_to_downloads(file_name, lambda dest: shutil.copy2(source_path, dest), parent)


def import_json_file(game_state, title, on_loaded):
    """Prompts for a .json file, parses it, and hands the parsed object to
    on_loaded(data). Validating the shape and writing it anywhere is left to
    the caller -- different JSON files have different schemas, this just
    covers the shared "pick a file, parse it, report a read error" part.
    """
    from ui import dialogs as confirm_dialog

    def _after_pick(file_path):
        if not file_path:
            return
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            confirm_dialog.show_error("Import Error", f"Couldn't read that file as JSON: {e}")
            return
        on_loaded(data)

    queries.open_file_browser(game_state, title, queries.downloads_dir(),
                      extensions=[".json"], on_result=_after_pick)


def import_zip_to_dir(game_state, target_parent_dir, on_success=None):
    """Prompts for a .zip and unpacks it into a folder named after the archive.

    Shared by the save and scenario import buttons; both used to open their own
    transient Tk root and duplicate the "_imported" collision suffix logic.
    """
    from ui import dialogs as confirm_dialog

    def _after_pick(file_path):
        if not file_path:
            return
        target_dir = os.path.join(target_parent_dir, Path(file_path).stem)
        if os.path.exists(target_dir):
            target_dir += "_imported"
        try:
            extract_and_flatten_zip(file_path, target_dir)
            # Web only: mirror the imported save into IndexedDB (no-op unless
            # target_parent_dir is one of the persisted directories).
            sync_persisted_dir(target_parent_dir)
            confirm_dialog.show_success("Import Success", "Imported successfully.")
            if on_success:
                on_success()
        except Exception as e:
            confirm_dialog.show_error("Import Error", str(e))

    queries.open_file_browser(game_state, "Select Zip File", queries.downloads_dir(),
                      extensions=[".zip"], on_result=_after_pick)


def import_mod_file(game_state, on_success=None):
    """Prompts for a .py mod file and copies it into mods/, after a warning that
    it can run arbitrary code with the user's own permissions on next launch --
    a mod's first line just names the whole Python module it replaces (see
    mod_loader.py). Picking one isn't a fully sandboxed action even though the
    file itself looks like ordinary source: mods are sandboxed by *default*
    (mod_loader.is_mod_sandboxed falls back to True for anything with no entry
    yet, matching the Mods screen's default for a freshly imported mod), which
    blocks filesystem/process access but is a best-effort guard, not a
    hardened security boundary -- see mod_loader.py's "Sandboxing" section.

    The mod is also enabled by default (mod_loader.is_mod_enabled falls back
    to True for anything with no entry yet) but doesn't take effect until the
    game is restarted -- Python only imports a module once per process, so
    anything already running has already loaded the unmodded version.
    """
    from ui import dialogs as confirm_dialog

    def _do_copy(file_path):
        target_name = os.path.basename(file_path)
        os.makedirs(c.MODS_DIR, exist_ok=True)
        dest = os.path.join(c.MODS_DIR, target_name)
        if os.path.exists(dest):
            stem, ext = os.path.splitext(target_name)
            dest = os.path.join(c.MODS_DIR, f"{stem}_imported{ext}")
        try:
            shutil.copy2(file_path, dest)
            sync_persisted_dir(c.MODS_DIR)
            confirm_dialog.show_success("Import Success",
                "Mod imported. Restart the game for it to take effect.")
            if on_success:
                on_success()
        except Exception as e:
            confirm_dialog.show_error("Import Error", str(e))

    def _after_pick(file_path):
        if not file_path:
            return
        confirm_dialog.ask_yes_no(
            "Install Mod?",
            "This mod replaces part of the game's own code. It will run "
            "sandboxed by default (no file or process access, see the Mods "
            "screen to change that) -- but sandboxing is a best-effort guard, "
            "not a hard security boundary.\n\n"
            "Only install mods from sources you trust.",
            lambda confirmed: _do_copy(file_path) if confirmed else None,
        )

    queries.open_file_browser(game_state, "Select Mod (.py) File", queries.downloads_dir(),
                      extensions=[".py"], on_result=_after_pick)


def import_character_portrait(game_state, on_success=None):
    """Prompts for an image file (starting in Downloads) and copies it into
    assets/characters/custom/, where the portrait picker's discover_character_images()
    picks it up like any curated portrait. Unlike import_mod_file, this needs no
    trust warning first -- an image can't run code, it can only be displayed.

    on_success, if given, is called with the new portrait's path relative to
    CHARACTERS_DIR (e.g. "Custom/photo.png").
    """
    from ui import dialogs as confirm_dialog
    from ui.dialogs.character_select_screen import CHARACTERS_DIR, CUSTOM_SUBDIR, IMAGE_EXTENSIONS

    custom_dir = os.path.join(CHARACTERS_DIR, CUSTOM_SUBDIR)

    def _after_pick(file_path):
        if not file_path:
            return
        target_name = os.path.basename(file_path)
        os.makedirs(custom_dir, exist_ok=True)
        dest = os.path.join(custom_dir, target_name)
        if os.path.exists(dest):
            stem, ext = os.path.splitext(target_name)
            dest = os.path.join(custom_dir, f"{stem}_imported{ext}")
        try:
            shutil.copy2(file_path, dest)
            sync_persisted_dir(custom_dir)
            if on_success:
                on_success(f"{CUSTOM_SUBDIR}/{os.path.basename(dest)}")
        except Exception as e:
            confirm_dialog.show_error("Import Error", str(e))

    queries.open_file_browser(game_state, "Select a Portrait Image", queries.downloads_dir(),
                      extensions=list(IMAGE_EXTENSIONS), on_result=_after_pick)


def ask_directory(game_state, title, initialdir, on_result):
    """Native folder picker; answers on_result with the chosen path, or None if cancelled."""
    queries.open_file_browser(game_state, title, initialdir, mode="select_folder", on_result=on_result)


def ask_color(game_state, title, initial, on_result):
    """Native color picker; answers on_result with an (r, g, b) tuple, or None if cancelled."""
    from ui.dialogs.color_picker_screen import ColorPickerScreen
    from ui.navigation.screen_runner import _run_pygame_sub_screen
    result = {}
    screen = ColorPickerScreen(game_state, title, initial, lambda color: result.setdefault("color", color))
    _run_pygame_sub_screen(game_state, screen, on_done=lambda: on_result(result.get("color")))


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
