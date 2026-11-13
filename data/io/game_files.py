"""Name the files that a desktop copy of the game keeps next to its executable.

Release builds and standalone game exports both read these lists.
Release builds do not ship compilation_scripts/, so a running game cannot read build_manifest.py.
Keep this module free of game and packaging engine imports.
"""

SOURCE_PACKAGES = ("data", "ui", "screens", "map_logic")
SOURCE_FILES = ("main.py", "mod_loader.py", "beepbox_audio.py")
DESKTOP_SOURCE_FILES = SOURCE_FILES + ("soloud.py",)
NATIVE_BINARIES = ("win64-libsoloud.dll", "mac64-libsoloud.dylib", "lin64-libsoloud.so")
LICENSE_FILE = "LICENSE"
# Standalone games are exported here, one folder per game.
EXPORTS_DIR = "exports"
