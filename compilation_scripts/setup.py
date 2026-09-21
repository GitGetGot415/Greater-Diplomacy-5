from setuptools import setup
import os
import subprocess
import sys

# py2app runs this file as ``compilation_scripts/setup.py``.  Python puts that
# directory, rather than the project root, at the front of sys.path, so shared
# root-level build helpers (including beepbox_audio.py) would otherwise be
# unavailable when the macOS wrapper invokes this script.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
os.chdir(REPO_ROOT)

from beepbox_audio import has_beepbox_replacement


def configure_py2app_tk_recipe():
    """Avoid py2app creating a Tcl interpreter merely to read its version.

    With the current Python.org arm64 build, ``_tkinter.create()`` aborts the
    *packaging* process before py2app writes an app.  GD5 only reaches tkinter
    from its last-resort crash dialog, and py2app's own recipe needs no Tcl/Tk
    copying for this framework Python (there are no ``lib/tcl*`` or ``lib/tk*``
    directories under the virtual environment).  Its current-version branch
    already returns no recipe data; provide that known-safe answer without
    initializing Tcl during the build.
    """
    from py2app.recipes import tkinter as tkinter_recipe

    tkinter_recipe.tk_version = lambda: tkinter_recipe.NEW_TK


if "py2app" in sys.argv:
    configure_py2app_tk_recipe()

APP = ['main.py']

def find_data_files(source_dir, target_dir=None, file_filter=None):
    """Recursively find all files in source_dir and return py2app-compatible tuples.

    file_filter(path), if given, is called per file; only files it accepts
    (returns True for) are included.
    """
    if target_dir is None:
        target_dir = source_dir
    result = []
    for dirpath, dirnames, filenames in os.walk(source_dir):
        files = [os.path.join(dirpath, f) for f in filenames]
        if file_filter is not None:
            files = [f for f in files if file_filter(f)]
        if not files:
            continue
        rel = os.path.relpath(dirpath, source_dir)
        dest = target_dir if rel == '.' else os.path.join(target_dir, rel)
        result.append((dest, files))
    return result

def not_git_ignored(path):
    # Mirrors windows_compilation.py's assets_ignore_func: only bundle files
    # git doesn't ignore, e.g. assets/music/* is ignored except the handful
    # of albums explicitly un-ignored in .gitignore.
    try:
        return subprocess.run(["git", "check-ignore", "-q", path]).returncode != 0
    except Exception as e:
        print(f"Error checking git ignore for {path}: {e}")
        return True

def include_native_audio_asset(path):
    if has_beepbox_replacement(path):
        return False
    return not_git_ignored(path)

def not_under_map_editor(path):
    # Mirrors windows_compilation.py's scenarios_ignore_func: map_editor
    # scenarios are dev/test scratch, not meant to ship.
    return "map_editor" not in os.path.normpath(path).split(os.sep)

def is_py_file(path):
    return path.endswith('.py')

# ONLY raw assets go here — use tuples of (target_dir, [files]) for py2app.
DATA_FILES = []
DATA_FILES += find_data_files('assets', file_filter=include_native_audio_asset)
DATA_FILES += find_data_files('base_maps')
DATA_FILES += find_data_files('scenarios', file_filter=not_under_map_editor)
DATA_FILES += find_data_files('data/json', 'data/json')
DATA_FILES.append(('.', ['mac64-libsoloud.dylib']))

# Loose .py copies of every project package/module py2app also bundles below;
# this includes screens/menu_screens/multiplayer_menu.py.
# (compiled, zipped into lib/pythonXY.zip). mod_loader resolves mod targets
# against real files on disk next to the app -- see mod_loader.py's
# _base_dir() docstring for why the zipped copies can't serve that role --
# so without these, every dropped-in mod is rejected as "target not found"
# even though the folder for it exists. Mirrors windows_compilation.py.
DATA_FILES += find_data_files('screens', file_filter=is_py_file)
DATA_FILES += find_data_files('map_logic', file_filter=is_py_file)
DATA_FILES += find_data_files('ui', file_filter=is_py_file)
DATA_FILES += find_data_files('data', 'data', file_filter=is_py_file)
DATA_FILES.append(('.', ['mod_loader.py', 'gameState.py', 'ui_elements.py', 'soloud.py', 'beepbox_audio.py']))

OPTIONS = {
    # All packages and sub-packages must be listed explicitly for py2app.
    'packages': [
        'screens', 'screens.menu_screens', 'screens.map_related_screens', 'screens.editor_screens',
        'map_logic', 'map_logic.ai', 'map_logic.camera', 'map_logic.diplomacy',
        'map_logic.random_map', 'map_logic.rendering', 'map_logic.setup', 'map_logic.turn_processing',
        'ui', 'ui.bars', 'ui.information', 'ui.confirm_dialog',
        'data', 'data.editors', 'data.io', 'data.map',
        # open-dragoman, named here rather than left to the module graph. It is
        # a ctypes library, so what matters is the .dylib beside its Python
        # files; py2app copies a named package's directory whole, data and all,
        # where a graph-discovered dependency brings only the modules.
        'dragoman',
        'cryptography',
        'quickjs',
        'py_mini_racer',
    ],
    # Standalone modules that aren't packages but are imported by the app.
    'includes': ['gameState', 'ui_elements', 'soloud', 'pygame', 'tkinter'],
    'excludes': ['PyInstaller', 'PySide6', 'PyQt6', 'PyQt5'],
    'resources': ['mac64-libsoloud.dylib'],
}

setup(
    app=APP,
    data_files=DATA_FILES,
    options={'py2app': OPTIONS},
)
