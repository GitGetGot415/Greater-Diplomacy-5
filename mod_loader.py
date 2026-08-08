"""Applies .py source-patch mods before the rest of the game imports.

A mod is a plain, syntactically valid .py file living in mods/: its first
line is a comment naming the project-relative file it replaces (e.g.
"#data/queries.py"), and the rest is that module's replacement source --
normally started as a copy of the real file, so IDE syntax highlighting,
linting and accurate line numbers in tracebacks all work exactly like
editing the game itself. Unlike the old .GD5MOD design, the target file on
disk is never written to -- an enabled mod's source is substituted in at
import time via a sys.meta_path finder, so disabling or deleting a mod just
reverts to the real file on the next launch, with nothing to restore and
no risk of losing the original.

install() must run before any project module is imported (see the top of
main.py): Python only executes a module's top-level code once per process
and caches the result in sys.modules, so installing the finder any later
would miss every module already imported by that point.

Deliberately dependency-free (stdlib only) so it can run as the very first
thing main.py does, before anything else -- including data.constants -- has
loaded.
"""
import importlib.abc
import importlib.util
import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODS_DIR = os.path.join(BASE_DIR, "mods")
STATE_PATH = os.path.join(MODS_DIR, "enabled_mods.json")

# Filenames actually patched in by install() at process start. Fixed for the
# life of the process -- toggling a mod afterwards changes enabled_mods.json
# but can't retroactively patch an already-imported module, so this is what
# the Mods screen compares against to tell "on" from "on, pending restart".
_active_mods = set()


def is_mod_active(filename):
    return filename in _active_mods


def mod_files():
    """Every .py mod file in mods/, sorted for a deterministic scan order."""
    if not os.path.isdir(MODS_DIR):
        return []
    return sorted(f for f in os.listdir(MODS_DIR)
                  if f.lower().endswith(".py") and os.path.isfile(os.path.join(MODS_DIR, f)))


def _load_state():
    if not os.path.isfile(STATE_PATH):
        return {}
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_state(state):
    os.makedirs(MODS_DIR, exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def is_mod_enabled(filename):
    # A mod dropped in by hand, with no entry yet, defaults to enabled --
    # matches the old drop-in-and-go behavior for anyone not using the UI.
    return _load_state().get(filename, True)


def set_mod_enabled(filename, enabled):
    """enabled=None clears the entry entirely (used when a mod is deleted)."""
    state = _load_state()
    if enabled is None:
        state.pop(filename, None)
    else:
        state[filename] = enabled
    _save_state(state)


def _path_to_module_name(rel_path):
    rel_path = rel_path.strip().replace("\\", "/")
    if not rel_path or not rel_path.endswith(".py"):
        return None
    parts = [p for p in rel_path[:-3].split("/") if p not in ("", ".")]
    if not parts or ".." in parts:
        return None
    return ".".join(parts)


def _resolve_target(rel_path):
    """(module_name, abs_path) for a target that's a real .py file inside the
    project, or (None, None) if the target is missing, malformed, or would
    resolve outside the game folder."""
    module_name = _path_to_module_name(rel_path)
    if not module_name:
        return None, None
    # Rebuilt from module_name's parts (always "/"-delimited, per
    # _path_to_module_name) rather than joining rel_path directly -- a mod
    # written on Windows arrives with backslashes, which os.path.join treats
    # as a literal filename character on macOS/Linux instead of a separator,
    # so joining rel_path as-is would look for a file that can't exist there.
    parts = module_name.split(".")
    abs_target = os.path.normpath(os.path.join(BASE_DIR, *parts[:-1], parts[-1] + ".py"))
    try:
        if os.path.commonpath([BASE_DIR, abs_target]) != BASE_DIR:
            return None, None
    except ValueError:
        return None, None  # e.g. different drives on Windows
    if not os.path.isfile(abs_target):
        return None, None
    return module_name, abs_target


def read_mod(filename):
    """(target_rel_path, source_text) for a mod file. source_text is the
    *entire* file, first line included -- it's left in place as an ordinary
    comment rather than stripped, so a compile error inside the mod reports
    the same line number the user sees in their editor. Raises ValueError on
    an empty file or a first line that isn't a "#path" comment, instead of
    letting a bad mod crash the caller with an IndexError."""
    with open(os.path.join(MODS_DIR, filename), "r", encoding="utf-8") as f:
        text = f.read()
    first_line = text.split("\n", 1)[0].strip()
    if not first_line.startswith("#"):
        raise ValueError('first line must be a "#path/to/target.py" comment')
    target = first_line[1:].strip()
    if not target:
        raise ValueError("missing target file after the '#' on the first line")
    return target, text


def describe_mod(filename):
    """Read-only summary for the Mods screen: target, module, validity, and
    current enabled state. Never raises -- a bad mod just comes back invalid
    with an explanation in "error"."""
    info = {"target": None, "module": None, "valid": False, "error": None,
            "enabled": is_mod_enabled(filename), "active": is_mod_active(filename)}
    try:
        target, _source = read_mod(filename)
        info["target"] = target
        module_name, abs_target = _resolve_target(target)
        if module_name is None:
            info["error"] = "target must be a .py file inside the game folder"
        elif abs_target is None:
            info["error"] = f"target file not found: {target}"
        else:
            info["module"] = module_name
            info["valid"] = True
    except Exception as e:
        info["error"] = str(e)
    return info


class _ModSourceLoader(importlib.abc.Loader):
    def __init__(self, source, origin):
        self.source = source
        self.origin = origin

    def exec_module(self, module):
        # Set before exec (not left to importlib's own has_location/spec
        # machinery, which doesn't kick in for a plain Loader like this one)
        # so __file__ is already there both for the mod's own top-level code
        # and for the module afterwards -- several screens (map.py, the
        # editors, the file browser) read __file__ for asset-relative paths,
        # and would break without it even though the code actually came from
        # the mod instead of disk.
        module.__file__ = self.origin
        code = compile(self.source, self.origin, "exec")
        exec(code, module.__dict__)

    def get_source(self, fullname):
        return self.source


class _ModFinder(importlib.abc.MetaPathFinder):
    def __init__(self, overrides):
        self.overrides = overrides  # module_name -> (source, origin_path)

    def find_spec(self, fullname, path, target=None):
        entry = self.overrides.get(fullname)
        if entry is None:
            return None
        source, origin = entry
        return importlib.util.spec_from_loader(fullname, _ModSourceLoader(source, origin), origin=origin)


def install():
    """Builds the override table from every enabled, valid mod and installs
    the import finder. Safe to call even with a corrupt state file or a
    garbage mod dropped in by hand -- anything that doesn't check out is
    skipped with a console message rather than blocking the game from
    starting at all.
    """
    try:
        overrides = {}
        for filename in mod_files():
            if not is_mod_enabled(filename):
                continue
            try:
                target, source = read_mod(filename)
            except Exception as e:
                print(f"Skipping mod '{filename}': {e}")
                continue

            module_name, abs_target = _resolve_target(target)
            if module_name is None:
                print(f"Skipping mod '{filename}': target must be a .py file inside the game folder")
                continue
            if abs_target is None:
                print(f"Skipping mod '{filename}': target file not found ({target})")
                continue
            if module_name in overrides:
                print(f"Skipping mod '{filename}': {target} is already patched by another enabled mod")
                continue

            overrides[module_name] = (source, abs_target)
            _active_mods.add(filename)

        if overrides:
            sys.meta_path.insert(0, _ModFinder(overrides))
    except Exception as e:
        print(f"Mod loading failed, continuing without mods: {e}")
