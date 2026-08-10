from setuptools import setup
import os
import subprocess

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

def not_under_map_editor(path):
    # Mirrors windows_compilation.py's scenarios_ignore_func: map_editor
    # scenarios are dev/test scratch, not meant to ship.
    return "map_editor" not in os.path.normpath(path).split(os.sep)

def is_py_file(path):
    return path.endswith('.py')

# ONLY raw assets go here — use tuples of (target_dir, [files]) for py2app.
DATA_FILES = []
DATA_FILES += find_data_files('assets', file_filter=not_git_ignored)
DATA_FILES += find_data_files('base_maps')
DATA_FILES += find_data_files('scenarios', file_filter=not_under_map_editor)
DATA_FILES += find_data_files('data/json', 'data/json')
DATA_FILES.append(('.', ['mac64-libsoloud.dylib']))

# Loose .py copies of every project package/module py2app also bundles below
# (compiled, zipped into lib/pythonXY.zip). mod_loader resolves mod targets
# against real files on disk next to the app -- see mod_loader.py's
# _base_dir() docstring for why the zipped copies can't serve that role --
# so without these, every dropped-in mod is rejected as "target not found"
# even though the folder for it exists. Mirrors windows_compilation.py.
DATA_FILES += find_data_files('screens', file_filter=is_py_file)
DATA_FILES += find_data_files('map_logic', file_filter=is_py_file)
DATA_FILES += find_data_files('ui', file_filter=is_py_file)
DATA_FILES += find_data_files('data', 'data', file_filter=is_py_file)
DATA_FILES.append(('.', ['mod_loader.py', 'gameState.py', 'ui_elements.py', 'soloud.py']))

OPTIONS = {
    # All packages and sub-packages must be listed explicitly for py2app.
    'packages': [
        'screens', 'screens.menu_screens', 'screens.map_related_screens', 'screens.editor_screens',
        'map_logic', 'map_logic.ai', 'map_logic.camera', 'map_logic.diplomacy',
        'map_logic.random_map', 'map_logic.rendering', 'map_logic.setup', 'map_logic.turn_processing',
        'ui', 'ui.bars', 'ui.information', 'ui.buttons', 'ui.confirm_dialog',
        'data', 'data.editors', 'data.io', 'data.map',
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