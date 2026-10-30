import os
import subprocess
import shutil
import sys

# This script lives in compilation_scripts/ but every relative path below (dist_dir,
# the data dirs to copy, etc.) is meant to resolve against the actual project root, so
# hop up one level and put the root on sys.path before importing first-party packages.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if __name__ == "__main__" and REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import data.constants as c
from compilation_scripts import build_manifest as manifest
from compilation_scripts.build_support import reset_runtime_files, distributed_files, verified_build_path

def main():
    os.chdir(REPO_ROOT)
    dist_dir = verified_build_path(REPO_ROOT, "dist")
    if os.path.exists(dist_dir):
        print("Cleaning dist folder...")
        shutil.rmtree(dist_dir)

    # 1. Run pyinstaller
    print("Running PyInstaller...")
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
    cmd = [sys.executable, "-m", "PyInstaller"] + manifest.windows_arguments()

    result = subprocess.run(cmd)
    if result.returncode != 0:
        print("PyInstaller failed.")
        sys.exit(result.returncode)
        
    print("PyInstaller finished successfully.")

    # Ensure dist exists
    os.makedirs(dist_dir, exist_ok=True)
    
    # Loose source copies remain available to the existing source replacement loader.
    for source, relative in distributed_files(REPO_ROOT, "windows"):
        target = os.path.join(dist_dir, relative)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copy2(source, target)
    reset_runtime_files(dist_dir)

    print("Compilation and copying finished successfully.")

    zip_name = f"GD5 WINDOWS {c.GAME_VERSION}"
    print(f"Zipping {dist_dir} into {zip_name}.zip...")
    shutil.make_archive(zip_name, 'zip', dist_dir)
    
    zip_filename = f"{zip_name}.zip"
    dst_zip_path = os.path.join(dist_dir, zip_filename)
    if os.path.exists(dst_zip_path):
        os.remove(dst_zip_path)
    shutil.move(zip_filename, dst_zip_path)
    print(f"Moved {zip_filename} into {dist_dir}/.")

if __name__ == "__main__":
    main()
