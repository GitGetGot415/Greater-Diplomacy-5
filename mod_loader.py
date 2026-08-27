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

Every mod is also either sandboxed or unsandboxed (sandboxed by default --
see set_mod_sandboxed()/is_mod_sandboxed()). A sandboxed mod's own code
can't touch the filesystem or spawn processes/sockets; see the "Sandboxing"
section below for how and how well that's enforced.

Deliberately dependency-free (stdlib only) so it can run as the very first
thing main.py does, before anything else -- including data.constants -- has
loaded.
"""
import importlib.abc
import importlib.util
import json
import os
import sys

def _base_dir():
    """The game folder mod targets are resolved against.

    In dev mode this is just the directory this file lives in. In a frozen
    build it must NOT be derived from __file__: PyInstaller only extracts
    __file__'s module to the temp _MEIPASS dir (gone once the process exits,
    and not where a user would drop a mods/ folder), and py2app zips this
    module into lib/pythonXY.zip, whose __file__ looks like
    ".../pythonXY.zip/mod_loader.pyc" -- os.path.dirname() of that names the
    zip archive itself, not a real directory, so every os.path.isdir(MODS_DIR)
    check below would silently and permanently fail.
    """
    if getattr(sys, "frozen", False):
        if hasattr(sys, "_MEIPASS"):
            # PyInstaller onefile: real, persistent files live next to the
            # executable, not in the temp dir __file__ would point to.
            return os.path.dirname(sys.executable)
        # py2app: sys.executable is Contents/MacOS/<name>; the bundle's real
        # (unzipped) resources -- and the loose .py source tree copied in
        # for mod target validation -- live in the sibling Contents/Resources.
        return os.path.normpath(os.path.join(os.path.dirname(sys.executable), "..", "Resources"))
    return os.path.dirname(os.path.abspath(__file__))


BASE_DIR = _base_dir()
MODS_DIR = os.path.join(BASE_DIR, "mods")
STATE_PATH = os.path.join(MODS_DIR, "enabled_mods.json")

# Filenames actually patched in by install() at process start, and whether
# each was loaded sandboxed. Fixed for the life of the process -- toggling a
# mod (or its sandbox setting) afterwards changes enabled_mods.json but can't
# retroactively patch an already-imported module, so this is what the Mods
# screen compares against to tell "on"/"sandboxed" from "on, pending restart".
_active_mods = set()
_active_sandbox = {}

# Mods that got past the compile check but blew up when their top-level code
# actually ran, keyed by filename -> "ExceptionType: message". Populated by
# _ModSourceLoader.exec_module the moment (if ever) something actually
# imports that mod's target module -- a mod targeting something never
# imported this session just never gets an entry, since there's no way to
# know it's broken without running it.
_broken_mods = {}


def is_mod_active(filename):
    return filename in _active_mods


def is_mod_sandbox_active(filename):
    """Whether filename's currently-running instance (if any) was loaded
    sandboxed. A mod that isn't active this process (disabled, invalid, or
    never installed) has nothing running to diverge from, so this just
    mirrors its current sandboxed setting -- no "pending restart" color for
    a mod that isn't running at all."""
    return _active_sandbox.get(filename, is_mod_sandboxed(filename))


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


def _entry(filename):
    """The per-mod state dict, normalizing the legacy format (enabled_mods.json
    used to map filename -> a plain enabled bool, from before mods could be
    individually sandboxed) into {"enabled": ..., "sandboxed": ...}."""
    raw = _load_state().get(filename)
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, bool):
        return {"enabled": raw}
    return {}


def is_mod_enabled(filename):
    # A mod dropped in by hand, with no entry yet, defaults to disabled --
    # a mod silently patching game files the moment its file appears is
    # surprising behavior; it should have to be turned on explicitly via
    # the Mods screen.
    return _entry(filename).get("enabled", False)


def is_mod_sandboxed(filename):
    # No entry yet (freshly imported, or dropped in by hand) defaults to
    # sandboxed -- mods should be opt-in to filesystem/process access, not
    # opt-out.
    return _entry(filename).get("sandboxed", True)


def _set_field(filename, key, value):
    state = _load_state()
    entry = state.get(filename)
    entry = dict(entry) if isinstance(entry, dict) else {}
    entry[key] = value
    state[filename] = entry
    _save_state(state)


def set_mod_enabled(filename, enabled):
    """enabled=None clears the entry entirely (used when a mod is deleted)."""
    if enabled is None:
        state = _load_state()
        state.pop(filename, None)
        _save_state(state)
        return
    _set_field(filename, "enabled", enabled)


def set_mod_sandboxed(filename, sandboxed):
    _set_field(filename, "sandboxed", sandboxed)


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
    current enabled/sandboxed state. Never raises -- a bad mod (including one
    with a syntax error, which would otherwise only surface as a crash the
    moment something imports its target module) just comes back invalid with
    an explanation in "error"."""
    info = {"target": None, "module": None, "valid": False, "error": None,
            "enabled": is_mod_enabled(filename), "active": is_mod_active(filename),
            "sandboxed": is_mod_sandboxed(filename),
            "sandbox_active": is_mod_sandbox_active(filename)}
    try:
        target, source = read_mod(filename)
        info["target"] = target
        module_name, abs_target = _resolve_target(target)
        if module_name is None:
            info["error"] = "target must be a .py file inside the game folder"
        elif abs_target is None:
            info["error"] = f"target file not found: {target}"
        else:
            compile(source, os.path.join(MODS_DIR, filename), "exec")
            info["module"] = module_name
            info["valid"] = True
    except SyntaxError as e:
        info["error"] = f"syntax error: {e}"
    except Exception as e:
        info["error"] = str(e)

    # Passing the compile check only means the mod is syntactically valid --
    # it can still have blown up when its top-level code actually ran (see
    # _ModSourceLoader.exec_module). That's a stronger, more specific verdict
    # than anything above, so it wins even over "valid": True.
    runtime_error = _broken_mods.get(filename)
    if runtime_error:
        info["valid"] = False
        info["error"] = f"failed to load: {runtime_error}"
    return info


# --- Sandboxing -------------------------------------------------------
#
# A sandboxed mod's own code shouldn't be able to touch the filesystem or
# spawn processes/sockets. Stripping dangerous names out of its builtins
# doesn't actually hold up: every other already-imported module's
# __dict__["__builtins__"] still points at the real, unrestricted builtins,
# so a mod could get back to the real open() just by importing something
# harmless and reading it off there.
#
# sys.addaudithook() (PEP 578) does hold up -- it intercepts these
# operations at the C level no matter what name or module was used to reach
# them, and once installed it can't be removed from Python. The hook below
# only blocks the call when the *direct* Python caller of the audited
# operation is a sandboxed mod's own code (marked via a sentinel key in its
# module dict, i.e. every frame of every function that mod defines). If a
# sandboxed mod calls into other, already-existing game code that does file
# I/O as part of its normal job, that's the existing code's own business --
# not a new capability the mod introduced -- so it's left alone.
#
# This is a best-effort guard against careless or lazily malicious mods, not
# a hardened security boundary: a sufficiently determined mod could still
# find another way to reach the filesystem through CPython internals. Only
# install mods -- sandboxed or not -- from sources you trust.

_SANDBOX_BLOCKED_EVENTS = {
    "open", "os.remove", "os.rmdir", "os.removedirs", "os.rename", "os.replace",
    "os.mkdir", "os.makedirs", "os.truncate", "os.chmod", "os.chown", "os.chflags",
    "os.lchflags", "os.link", "os.symlink", "os.listdir", "os.scandir", "os.system",
    "os.popen", "os.spawn", "os.exec", "os.fork", "os.forkpty", "os.posix_spawn",
    "os.kill", "os.killpg", "os.putenv", "os.unsetenv", "os.startfile",
    "subprocess.Popen", "shutil.rmtree", "shutil.copyfile", "shutil.copytree",
    "shutil.move",
}
_SANDBOX_BLOCKED_PREFIXES = ("socket.", "ctypes.")
_SANDBOX_MARKER = "__gd5_mod_sandbox__"
_audit_hook_installed = False


def _sandbox_audit_hook(event, args):
    if event not in _SANDBOX_BLOCKED_EVENTS and not event.startswith(_SANDBOX_BLOCKED_PREFIXES):
        return
    # frame 0 is this hook itself; frame 1 is whatever Python code directly
    # invoked the audited operation.
    caller = sys._getframe(1)
    if caller is not None and caller.f_globals.get(_SANDBOX_MARKER):
        raise PermissionError(
            f"'{event}' is disabled because this mod is running sandboxed -- "
            "switch it to Unsandboxed on the Mods screen if it needs file/system access."
        )


def _install_sandbox_audit_hook():
    global _audit_hook_installed
    if not _audit_hook_installed:
        sys.addaudithook(_sandbox_audit_hook)
        _audit_hook_installed = True


class _ModSourceLoader(importlib.abc.Loader):
    def __init__(self, source, origin, sandboxed, mod_filename):
        self.source = source
        self.origin = origin
        self.sandboxed = sandboxed
        self.mod_filename = mod_filename

    def exec_module(self, module):
        # Set before exec (not left to importlib's own has_location/spec
        # machinery, which doesn't kick in for a plain Loader like this one)
        # so __file__ is already there both for the mod's own top-level code
        # and for the module afterwards -- several screens (map.py, the
        # editors, the file browser) read __file__ for asset-relative paths,
        # and would break without it even though the code actually came from
        # the mod instead of disk.
        module.__file__ = self.origin
        if self.sandboxed:
            # Lives in the module's own globals, so every function this mod
            # defines carries it forever (as f_globals), for as long as
            # anything -- mod code or later game code -- calls into them.
            module.__dict__[_SANDBOX_MARKER] = True
        code = compile(self.source, self.origin, "exec")
        try:
            exec(code, module.__dict__)
        except Exception as e:
            # Compiling only proves the mod is syntactically valid -- its
            # top-level code (a typo'd name, a bad default-argument
            # expression, whatever) can still blow up the moment it actually
            # runs. Rather than let that exception propagate up through
            # whatever import statement first pulled this module in (almost
            # always deep inside main.py's own startup chain, taking the
            # whole game down before it even reaches a screen that could
            # explain why), fall back to the real, unmodified file so the
            # rest of the game boots normally; the Mods screen picks up
            # _broken_mods to show what happened.
            _broken_mods[self.mod_filename] = f"{type(e).__name__}: {e}"
            _active_mods.discard(self.mod_filename)
            _active_sandbox.pop(self.mod_filename, None)
            print(f"Mod '{self.mod_filename}' failed to load ({type(e).__name__}: {e}) -- "
                  f"falling back to the original file.")

            # The failed exec() above may have partially populated
            # module.__dict__ before raising -- clear it back to a blank
            # slate (short of the housekeeping dunders importlib already
            # set) so none of the mod's half-applied state leaks into the
            # real module.
            for key in list(module.__dict__):
                if key not in ("__name__", "__loader__", "__spec__", "__file__", "__package__", "__path__"):
                    del module.__dict__[key]

            with open(self.origin, "r", encoding="utf-8") as f:
                real_source = f.read()
            real_code = compile(real_source, self.origin, "exec")
            exec(real_code, module.__dict__)

    def get_source(self, fullname):
        return self.source


class _ModFinder(importlib.abc.MetaPathFinder):
    def __init__(self, overrides):
        self.overrides = overrides  # module_name -> (source, origin_path, sandboxed, mod_filename)

    def find_spec(self, fullname, path, target=None):
        entry = self.overrides.get(fullname)
        if entry is None:
            return None
        source, origin, sandboxed, mod_filename = entry
        loader = _ModSourceLoader(source, origin, sandboxed, mod_filename)
        return importlib.util.spec_from_loader(fullname, loader, origin=origin)


async def restore_mods_dir_from_indexeddb():
    """Web only, and must be *awaited* from a coroutine main.py's own
    asyncio.run(_bootstrap()) is actually driving -- see main.py's
    _bootstrap()/_import_project_modules(), which call this before
    install() and before any other project module import. Calling this via
    a second, separate asyncio.run() (as an earlier version of this function
    did) does NOT work: pygbag's own aio.run() (see
    pygbag/support/cross/aio/__init__.py's run()) already calls itself once
    internally before main.py ever starts executing, so every call after
    that first one just logs "aio.run called twice" and returns immediately
    without pumping anything -- the given coroutine gets queued onto pygbag's
    requestAnimationFrame-driven task loop and only actually runs frames
    later, long after whatever synchronous code called asyncio.run() has
    already moved on. Confirmed by reading that file directly, and by the
    browser console: the [gd5 mods] logs below printed in the wrong order
    around install()'s own logging when this was called that way. A bare
    `await` from within a coroutine that loop is already stepping (i.e.
    _bootstrap()) doesn't have this problem.

    pygbag 0.9.3's WASM build only links MEMFS in (see the matching comment
    in data/platform.py), so the virtual filesystem starts completely empty
    on every page load/refresh -- a mod uploaded (and mirrored into
    IndexedDB via data.platform.sync_persisted_dir) in an earlier session
    would otherwise just be invisible to install() on the very next refresh,
    even though the mirror is still sitting in IndexedDB. That mirror can
    only be read back asynchronously (no synchronous browser API for
    IndexedDB exists), and install() has to run before any other project
    module is imported (see this file's own docstring), so this can't just
    delegate to data.platform.restore_persisted_dir() -- importing
    data.platform this early would let it dodge patching by any mod that
    targets data/platform.py itself. So this duplicates just the read half
    of data/platform.py's hand-rolled IndexedDB glue, kept self-contained
    and stdlib-only like the rest of this file.
    """
    if sys.platform != "emscripten":
        return
    import asyncio
    import platform  # stdlib `platform`, patched by pygbag with `.window` on web

    # print() apparently doesn't reach the browser devtools console under
    # pygbag (only its own in-page terminal overlay does) -- these diagnostics
    # matter enough, for code this hard to test outside a real browser, to go
    # straight to window.console.log via JS instead, so a player can actually
    # see and report them. Every call is wrapped so a logging failure itself
    # can never be why mod restore breaks.
    def _log(msg):
        try:
            platform.window.console.log(str(msg))
        except Exception:
            pass

    target = os.path.abspath(MODS_DIR)
    _log(f"[gd5 mods] restoring {target!r} from IndexedDB...")

    platform.window.eval(
        "window.__gd5_mods_pull = function(root) {"
        "  window.__gd5_mods_pull_ready = false;"
        "  window.__gd5_mods_pull_error = null;"
        "  var req = indexedDB.open('gd5_persist', 1);"
        "  req.onupgradeneeded = function(e) {"
        "    var db = e.target.result;"
        "    if (!db.objectStoreNames.contains('files')) db.createObjectStore('files');"
        "  };"
        "  req.onsuccess = function(e) {"
        "    var db = e.target.result;"
        "    var tx = db.transaction('files', 'readonly');"
        "    var store = tx.objectStore('files');"
        "    var prefix = root + '/';"
        "    var n = 0;"
        "    var cur = store.openCursor();"
        "    cur.onsuccess = function(ev) {"
        "      var cursor = ev.target.result;"
        "      if (cursor) {"
        "        var path = cursor.key;"
        "        if (path.indexOf(prefix) === 0) {"
        "          var dir = path.substring(0, path.lastIndexOf('/'));"
        "          try { FS.mkdirTree(dir); } catch (e) {}"
        "          try { FS.writeFile(path, new Uint8Array(cursor.value)); n++; }"
        "          catch (e) { window.__gd5_mods_pull_error = 'writeFile ' + path + ': ' + e; }"
        "        }"
        "        cursor.continue();"
        "      } else {"
        "        console.log('[gd5 mods] IndexedDB cursor done, ' + n + ' file(s) restored under ' + prefix);"
        "      }"
        "    };"
        "    tx.oncomplete = function() { window.__gd5_mods_pull_ready = true; };"
        "    tx.onerror = function() { window.__gd5_mods_pull_error = String(tx.error); window.__gd5_mods_pull_ready = true; };"
        "  };"
        "  req.onerror = function() { window.__gd5_mods_pull_error = String(req.error); window.__gd5_mods_pull_ready = true; };"
        "};"
    )
    platform.window.__gd5_mods_pull(target)
    for i in range(200):  # ~20s safety net, mirrors data/platform.py's own polling loops
        if platform.window.__gd5_mods_pull_ready:
            err = platform.window.__gd5_mods_pull_error
            _log(f"[gd5 mods] pull finished after {i * 0.1:.1f}s"
                 + (f" with error: {err}" if err else ""))
            break
        await asyncio.sleep(0.1)
    else:
        _log("[gd5 mods] pull timed out after 20s")

    _log(f"[gd5 mods] mods/ dir now contains: {mod_files()}")


def install():
    """Builds the override table from every enabled, valid mod and installs
    the import finder. Safe to call even with a corrupt state file or a
    garbage mod dropped in by hand -- anything that doesn't check out is
    skipped with a console message rather than blocking the game from
    starting at all.

    On web, restore_mods_dir_from_indexeddb() must already have been awaited
    before this runs, or mods/ will still be empty in pygbag's in-memory
    filesystem -- see that function's docstring and main.py's _bootstrap().
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

            try:
                compile(source, os.path.join(MODS_DIR, filename), "exec")
            except SyntaxError as e:
                print(f"Skipping mod '{filename}': syntax error: {e}")
                continue

            sandboxed = is_mod_sandboxed(filename)
            overrides[module_name] = (source, abs_target, sandboxed, filename)
            _active_mods.add(filename)
            _active_sandbox[filename] = sandboxed

        if overrides:
            if any(sandboxed for _source, _origin, sandboxed, _filename in overrides.values()):
                _install_sandbox_audit_hook()
            sys.meta_path.insert(0, _ModFinder(overrides))

        if sys.platform == "emscripten":
            try:
                import platform
                platform.window.console.log(f"[gd5 mods] install() finished, active mods: {sorted(_active_mods)}")
            except Exception:
                pass
    except Exception as e:
        print(f"Mod loading failed, continuing without mods: {e}")
        if sys.platform == "emscripten":
            try:
                import platform
                import traceback
                platform.window.console.log(f"[gd5 mods] install() raised: {e}")
                platform.window.console.log(traceback.format_exc())
            except Exception:
                pass
