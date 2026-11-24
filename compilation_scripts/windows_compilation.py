import os
import subprocess
import sys

# This script lives in compilation_scripts/ but every relative path below (dist_dir,
# the data dirs to copy, etc.) is meant to resolve against the actual project root, so
# hop up one level and put the root on sys.path before importing first-party packages.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if __name__ == "__main__" and REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import data.constants as c
from compilation_scripts import build_manifest as manifest
from compilation_scripts.build_support import distributed_files, reset_runtime_files, run_pyinstaller_build


def main():
    # --hidden-import (one per module) below, not --collect-submodules: screens/game/map.py's
    # sub_screen_opener() loads screens (automation_screen, declare_independence,
    # politics_screen) via
    # importlib.import_module(module_path) with module_path as a runtime string, so PyInstaller's
    # static analysis never sees the import and silently drops the module from the build -- it only
    # breaks in the compiled exe (ModuleNotFoundError), never when running from source.
    # --collect-submodules screens.game looks like the fix and does list both modules
    # among the names it discovers, but verified empirically (PyInstaller 6.20, three separate clean
    # builds) that they still get silently dropped before the final archive -- something in how
    # collect-submodules-derived hidden imports get merged into the module graph loses exactly these
    # two, while every statically-imported sibling in the same package survives. Passing each module
    # as its own literal --hidden-import does not have that problem and was confirmed to land both
    # modules in the built archive. If a new screen is ever added via sub_screen_opener(), it needs
    # its own HIDDEN_IMPORTS entry in build_manifest.py.
    # open-dragoman is a ctypes library: its .dll is package DATA sitting beside
    # the Python files, and PyInstaller collects package data for nobody unless
    # asked. Analysis would find `import dragoman` and bundle the module, then
    # the frozen game would fail at ctypes.CDLL with the library missing --
    # green CI, dead Translate screen, and nothing in between to notice.
    # --collect-all takes the module, its submodules and its binaries together.
    print("Running PyInstaller...")
    run_pyinstaller_build(
        repo_root=REPO_ROOT,
        dist_relative=manifest.WINDOWS_DIST_DIR,
        platform_name="windows",
        label="Windows",
        pyinstaller_args=manifest.windows_arguments(),
        archive_base=f"GD5 WINDOWS {c.GAME_VERSION}",
        archive_format="zip",
        archive_ext="zip",
        run_cmd=subprocess.run,
        files_fn=distributed_files,
        reset_fn=reset_runtime_files,
    )


if __name__ == "__main__":
    main()
