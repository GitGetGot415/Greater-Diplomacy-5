from setuptools import setup

APP = ['main.py']

# ONLY raw assets go here. No Python folders.
DATA_FILES = [
    'assets', 
    'base_maps', 
    'scenarios', 
    'data', 
    'mac64-libsoloud.dylib'
] 

OPTIONS = {
    # Now that these have __init__.py files, py2app will successfully zip them!
    'packages': ['screens', 'map_logic', 'ui', 'data'], 
    'excludes': ['PyInstaller', 'PySide6', 'PyQt6', 'PyQt5']
}

setup(
    app=APP,
    data_files=DATA_FILES,
    options={'py2app': OPTIONS},
    setup_requires=['py2app'],
)