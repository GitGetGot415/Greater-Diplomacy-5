"""Export and import helpers that ask the player for a file and report the result."""

import data.constants as c
import json
import os
import shutil
import zipfile
import pygame
from pathlib import Path
from data.platform import CHARACTERS_DIR, CUSTOM_SUBDIR, IS_WEB, download_file, downloads_dir, sync_persisted_dir
from data.queries.content import IMAGE_EXTENSIONS
from data.queries.files import extract_and_flatten_zip, read_saved_content_summary
from ui import dialogs
from ui.dialogs import pickers


def export_with_overwrite_confirmation(file_path, export, parent=None):
    """Run an export after confirmation when its destination already exists."""
    if not os.path.lexists(file_path):
        return export()

    def after_choice(overwrite):
        if overwrite:
            export()

    kind = "folder" if os.path.isdir(file_path) else "file"
    dialogs.ask_yes_no(
        f"Overwrite existing {kind}?",
        f"{os.path.basename(file_path)} already exists in:\n{os.path.dirname(file_path) or '.'}\n\n"
        f"Overwrite this {kind}?",
        on_result=after_choice, tk_parent=parent, yes_label="Overwrite", no_label="Cancel")
    return None


def choose_save_destination(default_path, on_ready, *, game_state=None, parent=None,
                            title="Save As", directory=False, allow_copy=False):
    """Choose a destination before writing. on_ready receives (path, overwrite).

    Browser builds retain virtual storage and browser-managed downloads because
    the in-game browser cannot select destinations on the host filesystem.
    """
    def picked(path):
        if not path:
            return
        if directory and os.path.lexists(path) and not os.path.isdir(path):
            dialogs.show_error(title, "A file already uses this folder name.", tk_parent=parent)
            return
        if directory and allow_copy and os.path.isdir(path):
            def chosen(answer):
                if answer is True:
                    on_ready(path, True)
                elif answer is False:
                    number = 1
                    while os.path.lexists(f"{path}-{number}"):
                        number += 1
                    on_ready(f"{path}-{number}", False)
            dialogs.ask_yes_no(
                "Scenario Already Exists", f'"{os.path.basename(path)}" already exists in:\n'
                f"{os.path.dirname(path)}\n\nOverwrite it, save a numbered copy, or cancel?",
                chosen, tk_parent=parent, yes_label="Overwrite", no_label="Save Copy", back_label="Cancel")
            return
        exists = os.path.lexists(path)
        return export_with_overwrite_confirmation(path, lambda: on_ready(path, exists), parent)

    if IS_WEB:
        return picked(default_path)
    extension = os.path.splitext(default_path)[1]
    return pickers.open_file_browser(
        game_state, title, os.path.dirname(default_path),
        mode="save_folder" if directory else "save_file",
        extensions=[extension] if extension and not directory else None,
        initial_name=os.path.basename(default_path), tk_parent=parent, on_result=picked)


def export_file(file_name, produce, parent=None, *, game_state=None):
    """Choose an export destination, starting in Downloads, then produce the file.

    Web exports use the existing browser download bridge and virtual filesystem.
    """
    default_path = file_name if IS_WEB else os.path.join(downloads_dir(), file_name)

    def export(dest_path, _overwrite):
        try:
            if not IS_WEB:
                os.makedirs(os.path.dirname(os.path.abspath(dest_path)), exist_ok=True)
            produce(dest_path)

            if IS_WEB:
                download_file(dest_path)
                dialogs.show_success("Export Success", f"{file_name} downloaded.", tk_parent=parent)
            else:
                dialogs.show_success("Export Success", f"Exported to {dest_path}", tk_parent=parent)
            return dest_path
        except (OSError, ValueError, pygame.error, zipfile.BadZipFile, zipfile.LargeZipFile) as e:
            dialogs.show_error("Export Error", str(e), tk_parent=parent)
            return None

    return choose_save_destination(default_path, export, game_state=game_state,
                                   parent=parent, title="Export File")


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


def export_dir_as_zip(source_dir, zip_name, parent=None, *, game_state=None):
    """Zips a folder and sends it to the user.

    Counterpart to extract_and_flatten_zip, and the single implementation
    behind every "Export" button (saves, scenarios). JSON entries are formatted
    in the archive so older compact saves are readable too.
    """
    def zip_it(dest_path):
        destination = os.path.realpath(dest_path)
        with zipfile.ZipFile(dest_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root_dir, _dirs, files in os.walk(source_dir):
                for file in files:
                    full = os.path.join(root_dir, file)
                    if os.path.realpath(full) == destination:
                        continue
                    archive_name = os.path.relpath(full, source_dir)
                    readable_json = _readable_json_payload(full)
                    if readable_json is None:
                        zipf.write(full, archive_name)
                    else:
                        zipf.writestr(archive_name, readable_json)

    return export_file(zip_name, zip_it, parent, game_state=game_state)


def export_json_file(source_path, file_name, parent=None, *, game_state=None):
    """Copy a JSON file to the chosen export destination."""
    return export_file(file_name, lambda dest: shutil.copy2(source_path, dest), parent,
                       game_state=game_state)


def open_saved_content_folder(game_state, title, start_dir, on_selected):
    """Browse outside the library using the library's existing load checks."""
    def picked(path):
        if not path:
            return
        error = read_saved_content_summary(path)["error"]
        if error:
            dialogs.show_error(title, error)
            return
        on_selected(path)

    pickers.open_file_browser(game_state, title, start_dir, mode="select_folder", on_result=picked)


def import_json_file(game_state, title, on_loaded):
    """Prompts for a .json file, parses it, and hands the parsed object to
    on_loaded(data). Validating the shape and writing it anywhere is left to
    the caller -- different JSON files have different schemas, this just
    covers the shared "pick a file, parse it, report a read error" part.
    """
    def _after_pick(file_path):
        if not file_path:
            return
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            dialogs.show_error("Import Error", f"Couldn't read that file as JSON: {e}")
            return
        on_loaded(data)

    pickers.open_file_browser(game_state, title, downloads_dir(),
                      extensions=[".json"], on_result=_after_pick)


def import_zip_to_dir(game_state, target_parent_dir, on_success=None):
    """Prompts for a .zip and unpacks it into a folder named after the archive.

    Shared by the save and scenario import buttons; both used to open their own
    transient Tk root and duplicate the "_imported" collision suffix logic.
    """
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
            dialogs.show_success("Import Success", "Imported successfully.")
            if on_success:
                on_success()
        except Exception as e:
            dialogs.show_error("Import Error", str(e))

    pickers.open_file_browser(game_state, "Select Zip File", downloads_dir(),
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

    The mod is disabled by default (mod_loader.is_mod_enabled falls back to
    False for anything with no entry yet) and has to be enabled on the Mods
    screen. Even then it doesn't take effect until the game is restarted -- Python only imports a module once per process, so
    anything already running has already loaded the unmodded version.
    """
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
            dialogs.show_success("Import Success",
                "Mod imported. It is off for now. Turn it on in the Mods screen, then restart the game.")
            if on_success:
                on_success()
        except Exception as e:
            dialogs.show_error("Import Error", str(e))

    def _after_pick(file_path):
        if not file_path:
            return
        if IS_WEB:
            sandbox_note = ("On the web build there is no sandbox. The mod can use "
                            "everything your browser session can.")
        else:
            sandbox_note = ("It will run sandboxed by default (no file or process "
                            "access, see the Mods screen to change that) -- but "
                            "sandboxing is a best-effort guard, not a hard "
                            "security boundary.")
        dialogs.ask_yes_no(
            "Install Mod?",
            "This mod replaces part of the game's own code. "
            f"{sandbox_note}\n\n"
            "Only install mods from sources you trust.",
            lambda confirmed: _do_copy(file_path) if confirmed else None,
        )

    pickers.open_file_browser(game_state, "Select Mod (.py) File", downloads_dir(),
                      extensions=[".py"], on_result=_after_pick)


def import_character_portrait(game_state, on_success=None):
    """Prompts for an image file (starting in Downloads) and copies it into
    assets/characters/custom/, where the portrait picker's discover_character_images()
    picks it up like any curated portrait. Unlike import_mod_file, this needs no
    trust warning first -- an image can't run code, it can only be displayed.

    on_success, if given, is called with the new portrait's path relative to
    CHARACTERS_DIR (e.g. "Custom/photo.png").
    """
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
            dialogs.show_error("Import Error", str(e))

    pickers.open_file_browser(game_state, "Select a Portrait Image", downloads_dir(),
                      extensions=list(IMAGE_EXTENSIONS), on_result=_after_pick)
