from setuptools import setup
import os

APP = ['main.py']

def find_data_files(source_dir, target_dir=None):
    """Recursively find all files in source_dir and return py2app-compatible tuples."""
    if target_dir is None:
        target_dir = source_dir
    result = []
    for dirpath, dirnames, filenames in os.walk(source_dir):
        if not filenames:
            continue
        rel = os.path.relpath(dirpath, source_dir)
        dest = target_dir if rel == '.' else os.path.join(target_dir, rel)
        files = [os.path.join(dirpath, f) for f in filenames]
        result.append((dest, files))
    return result

# ONLY raw assets go here — use tuples of (target_dir, [files]) for py2app.
DATA_FILES = []
DATA_FILES += find_data_files('assets')
DATA_FILES += find_data_files('base_maps')
DATA_FILES += find_data_files('scenarios')
DATA_FILES += find_data_files('data/json', 'data/json')
DATA_FILES.append(('.', ['mac64-libsoloud.dylib']))

OPTIONS = {
    # All packages and sub-packages must be listed explicitly for py2app.
    'packages': [
        'screens', 'screens.menu_screens', 'screens.map_related_screens',
        'map_logic', 'map_logic.ai', 'map_logic.camera', 'map_logic.diplomacy',
        'map_logic.random_map', 'map_logic.rendering', 'map_logic.setup', 'map_logic.system32',
        'ui', 'ui.bars', 'ui.information',
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
    setup_requires=['py2app'],
)