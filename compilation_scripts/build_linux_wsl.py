"""Build GD5's Linux release from Windows using an Ubuntu WSL distribution.

Usage: python compilation_scripts/build_linux_wsl.py [--distro Ubuntu]
"""

import argparse
import hashlib
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = Path(__file__).resolve().relative_to(REPO_ROOT).as_posix()
UBUNTU_PACKAGES = ("binutils", "git", "libasound2t64", "libgl1", "python3-venv")

# Direct invocation puts compilation_scripts on sys.path, so add the repository root.
if __name__ == "__main__" and str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from compilation_scripts import build_manifest as manifest
from compilation_scripts.build_support import verified_build_path


def install_system_dependencies():
    installed = subprocess.run(
        ["dpkg-query", "-W", "-f=${Package}\t${db:Status-Status}\n"],
        check=True, capture_output=True, text=True,
    ).stdout.splitlines()
    missing = [package for package in UBUNTU_PACKAGES if f"{package}\tinstalled" not in installed]
    if missing:
        print(f"Installing Ubuntu build packages: {', '.join(missing)}", flush=True)
        subprocess.run(["sudo", "apt-get", "update"], check=True)
        subprocess.run(["sudo", "apt-get", "install", "-y", *missing], check=True)


def stage_working_tree(destination):
    """Copy current contents, including uncommitted edits and new source files."""
    files = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "--deduplicate", "-z"],
        cwd=REPO_ROOT, check=True, stdout=subprocess.PIPE,
    ).stdout.split(b"\0")
    for name in filter(None, files):
        relative = Path(os.fsdecode(name))
        source = REPO_ROOT / relative
        if source.is_file():
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)


def publish_archive(archive, output_dir):
    """Keep any previous archive available until the new copy completes."""
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / archive.name
    with tempfile.NamedTemporaryFile(dir=output_dir, prefix=".gd5-linux-", delete=False) as pending:
        temporary = Path(pending.name)
    try:
        shutil.copyfile(archive, temporary)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    print(f"Linux archive ready: {destination}", flush=True)


def build_in_wsl():
    # Windows Python also imports this launcher. The file lock is needed only in WSL.
    import fcntl

    if platform.machine() != "x86_64" or sys.version_info < (3, 11):
        raise RuntimeError("The Linux build needs x86-64 and Python 3.11 or newer. Use Ubuntu 24.04 or newer in WSL.")

    checkout_key = hashlib.sha256(os.fsencode(REPO_ROOT)).hexdigest()[:16]
    cache = Path.home() / ".cache" / "gd5-wsl-build" / checkout_key
    cache.mkdir(parents=True, exist_ok=True)
    output_dir = Path(verified_build_path(REPO_ROOT, manifest.LINUX_DIST_DIR))
    with (cache / "build.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        install_system_dependencies()
        git_dir = subprocess.check_output(["git", "rev-parse", "--absolute-git-dir"], cwd=REPO_ROOT, text=True).rstrip("\n")
        with tempfile.TemporaryDirectory(prefix="build-", dir=cache) as scratch:
            stage = Path(scratch)
            print("Copying the Windows working tree into WSL...", flush=True)
            stage_working_tree(stage)

            venv = cache / f"python{sys.version_info.major}.{sys.version_info.minor}"
            python = venv / "bin" / "python"
            if not (venv / "bin" / "pip").is_file():
                subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
            subprocess.run([str(python), "-m", "pip", "install", "-r", "requirements.txt", "pyinstaller"], cwd=stage, check=True)

            # Give the existing asset filter the original index and the staged files.
            env = dict(os.environ, GIT_DIR=git_dir, GIT_WORK_TREE=str(stage))
            subprocess.run([str(python), "-u", "compilation_scripts/linux_compilation.py"], cwd=stage, env=env, check=True)
            archives = list((stage / manifest.LINUX_DIST_DIR).glob("*.tar.gz"))
            if len(archives) != 1:
                raise RuntimeError("The Linux build did not produce exactly one .tar.gz archive.")
            publish_archive(archives[0], output_dir)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--distro", default="Ubuntu", help="Ubuntu WSL distribution name (default: Ubuntu)")
    args = parser.parse_args()
    try:
        if sys.platform == "win32":
            print(f"Building GD5 through WSL ({args.distro})...", flush=True)
            return subprocess.run([
                "wsl.exe", "--distribution", args.distro, "--cd", str(REPO_ROOT),
                "--exec", "python3", "-u", SCRIPT_PATH,
            ]).returncode
        if sys.platform == "linux" and os.environ.get("WSL_DISTRO_NAME"):
            build_in_wsl()
            return 0
        raise RuntimeError("Run this launcher from Windows Python with an Ubuntu WSL distribution installed.")
    except subprocess.CalledProcessError as error:
        print(f"Linux build command failed (exit {error.returncode}). See output above.", file=sys.stderr)
        return 1
    except (OSError, RuntimeError, ValueError) as error:
        print(f"Linux build failed: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
