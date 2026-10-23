import os
import subprocess
import sys

# py2app runs this file as ``compilation_scripts/setup.py``.  Python puts that
# directory, rather than the project root, at the front of sys.path, so shared
# root-level build helpers (including beepbox_audio.py) would otherwise be
# unavailable when the macOS wrapper invokes this script.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if __name__ == "__main__" and REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from compilation_scripts import build_manifest as manifest
from compilation_scripts.build_support import mac_data_files


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


APP = ['main.py']
OPTIONS = {
    'packages': list(manifest.RUNTIME_PACKAGES + manifest.NATIVE_PACKAGES),
    'includes': list(manifest.MAC_INCLUDES),
    'excludes': ['PyInstaller', 'PySide6', 'PyQt6', 'PyQt5'],
    'resources': ['mac64-libsoloud.dylib'],
}


def main():
    from setuptools import setup
    os.chdir(REPO_ROOT)
    if "py2app" in sys.argv:
        configure_py2app_tk_recipe()
    setup(app=APP, data_files=mac_data_files(REPO_ROOT), options={'py2app': OPTIONS})


if __name__ == "__main__":
    main()
