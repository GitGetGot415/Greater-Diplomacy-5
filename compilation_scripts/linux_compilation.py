"""Package the game for Linux: a one-file executable with loose sources beside it.

Usage:
    python compilation_scripts/linux_compilation.py

The Linux build is the Windows build with two differences, and no others.

PyInstaller does not cross-compile, so this script runs on Linux and produces a
Linux executable only. The Windows script, the macOS script and this script each
build for the operating system running them.

The archive is a .tar.gz, not the .zip the Windows build makes. ZIP entries have
no POSIX permission bits that every extractor restores, so a player who unzipped
a Linux build would get an executable without its executable bit and a game that
refuses to start with "Permission denied". Tar stores the mode, and tar is what a
Linux player already has.

The audio library needs nothing new: soloud.py already selects
lin64-libsoloud.so on Linux, and the shared library is already in the repository.
Pygame-ce needs the SDL2 runtime libraries, which every desktop distribution
packages.

What a player needs installed is ALSA: lin64-libsoloud.so links libasound.so.2,
which every desktop distribution has and a minimal container does not. Without
libasound.so.2 the game prints

    CRITICAL DLL/DYLIB ERROR: Failed to load dynlib/dll ... lin64-libsoloud.so

which names the bundled file and says the file was probably missing when the
application was frozen. The file is there; the dependency it needs is not. That
message was read while verifying this script, and it is the one thing about a
Linux build that looks like a packaging fault and is not.
"""

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
    if sys.platform.startswith("win") or sys.platform == "darwin":
        print(f"The Linux build must run on Linux. This is {sys.platform}.")
        sys.exit(1)

    print("Running PyInstaller...")
    # The hidden imports, collected packages and added binaries are the Windows
    # build's, from the one list in build_manifest.py. The dynamically imported
    # screens that PyInstaller cannot see statically are dropped from a Linux
    # build for the same reason and in the same way, so a Linux-only inventory
    # would go stale the first time a screen was added.
    # Executable mode 0o755 ensures tar stores the bit even alongside loose source copies.
    run_pyinstaller_build(
        repo_root=REPO_ROOT,
        dist_relative=manifest.LINUX_DIST_DIR,
        platform_name="linux",
        label="Linux",
        pyinstaller_args=manifest.linux_arguments(),
        archive_base=f"GD5 LINUX {c.GAME_VERSION}",
        archive_format="gztar",
        archive_ext="tar.gz",
        executable_mode=0o755,
        run_cmd=subprocess.run,
        files_fn=distributed_files,
        reset_fn=reset_runtime_files,
    )


if __name__ == "__main__":
    main()
