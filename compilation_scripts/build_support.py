"""Stage release files without initializing game or native audio engines."""

import json
import os
from pathlib import Path
import shutil
import subprocess

from compilation_scripts import build_manifest as manifest


def is_git_ignored(path):
    try:
        return subprocess.run(["git", "check-ignore", "-q", str(Path(path).resolve())],
                              cwd=Path(path).resolve().parent).returncode == 0
    except OSError as error:
        print(f"Error checking git ignore for {path}: {error}")
        return False


def git_ignored_paths(root, paths):
    """Check one inventory with Git. Discard the result after this inventory."""
    names = dict.fromkeys(os.fsencode(Path(path).resolve()) for path in paths)
    if not names:
        return set()
    try:
        result = subprocess.run(
            ["git", "check-ignore", "--stdin", "-z"], cwd=root,
            input=b"\0".join(names) + b"\0", capture_output=True)
    except OSError as error:
        print(f"Error checking git ignore for {root}: {error}")
        return set()
    if result.returncode not in (0, 1):
        print(f"Error checking git ignore for {root}: {os.fsdecode(result.stderr).strip()}")
        return set()
    return {Path(os.fsdecode(name)).resolve() for name in result.stdout.split(b"\0") if name}


def include_asset(path, platform, *, ignore_check=None):
    # Import the audio file predicate only. It does not initialize an engine.
    from beepbox_audio import has_beepbox_replacement
    if ignore_check is None:
        ignore_check = is_git_ignored
    if ignore_check(path):
        return False
    if has_beepbox_replacement(str(path)):
        # Web cannot use a replacement JSON which its own filter excludes.
        return platform == "web" and ignore_check(Path(path).with_suffix(".json"))
    return True


def include_file(path, relative, platform, *, ignore_check=None):
    """Apply common filters and retain each platform's source policy."""
    relative = Path(relative)
    parts = relative.parts
    if "__pycache__" in parts:
        return False
    root = parts[0]
    if root in manifest.EMPTY_DIRS:
        return False
    if root == "scenarios" and "map_editor" in parts:
        return False
    if root == "assets":
        return include_asset(path, platform, ignore_check=ignore_check)
    if platform == "web":
        return not any(relative.as_posix().startswith(pkg.replace(".", "/") + "/")
                       for pkg in manifest.WEB_EXCLUDED_SUBPACKAGES)
    if root == "data":
        return path.suffix in (".py", ".json") if platform == "windows" else (
            path.suffix == ".py" or relative.as_posix().startswith("data/json/"))
    if root in manifest.SOURCE_PACKAGES:
        return path.suffix == ".py"
    return True


def distributed_files(root, platform):
    """Yield source and relative paths. Do not read local save directories."""
    if platform not in ("windows", "macos", "web"):
        raise ValueError(f"Unknown build platform: {platform}")
    root = Path(root).resolve()
    sources = manifest.WEB_SOURCE_FILES if platform == "web" else manifest.DESKTOP_SOURCE_FILES
    if platform == "macos":
        sources = tuple(name for name in sources if name != "main.py") + ("mac64-libsoloud.dylib",)
    for name in sources:
        yield root / name, Path(name)
    for directory in manifest.SOURCE_PACKAGES + manifest.DATA_DIRS:
        base = root / directory
        candidates = []
        for parent, directories, filenames in os.walk(base):
            directories[:] = [name for name in directories if name != "__pycache__"]
            candidates.extend(Path(parent) / name for name in filenames)
        ignore_check = None
        if directory == "assets":
            # Include companion JSON paths so web audio keeps its existing filter rule.
            ignored = git_ignored_paths(root, candidates + [path.with_suffix(".json") for path in candidates])
            ignore_check = lambda path: Path(path).resolve() in ignored
        for path in candidates:
            relative = path.relative_to(root)
            if include_file(path, relative, platform, ignore_check=ignore_check):
                yield path, relative


def reset_runtime_files(destination):
    destination = Path(destination)
    for directory in manifest.EMPTY_DIRS:
        (destination / directory).mkdir(parents=True, exist_ok=True)
    json_dir = destination / "data" / "json"
    if json_dir.is_dir():
        for name, value in manifest.RUNTIME_JSON_DEFAULTS.items():
            (json_dir / name).write_text(json.dumps(value), encoding="utf-8")


def stage_release(root, destination, platform):
    """Copy release material into an empty destination owned by the caller."""
    destination = Path(destination).resolve()
    if destination.exists() and any(destination.iterdir()):
        raise ValueError(f"Staging destination must be empty: {destination}")
    destination.mkdir(parents=True, exist_ok=True)
    for source, relative in distributed_files(root, platform):
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    reset_runtime_files(destination)


def mac_data_files(root):
    grouped = {}
    for source, relative in distributed_files(root, "macos"):
        grouped.setdefault(str(relative.parent), []).append(str(source))
    return list(grouped.items())


def png_signature_mismatches(root):
    """Return staged PNG paths whose content has another file format."""
    mismatches = []
    for path in Path(root).rglob("*.png"):
        with path.open("rb") as stream:
            if stream.read(8) != b"\x89PNG\r\n\x1a\n":
                mismatches.append(str(path))
    return mismatches


def verified_build_path(root, relative):
    """Check the final target before build cleanup or moves."""
    root = Path(root).resolve()
    path = (root / relative).resolve()
    if path == root or root not in path.parents:
        raise ValueError(f"Build target is outside the repository: {path}")
    return str(path)
