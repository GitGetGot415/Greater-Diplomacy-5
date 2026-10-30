"""Applies .py source-patch mods before the rest of the game imports.

A mod is a plain, syntactically valid .py file living in mods/. Its first line
declares which project-relative file it replaces. Two header formats are
accepted:

  * Legacy (deprecated, still works, logs a one-line warning at install):
        #data/queries/economy.py
        ...replacement source...

  * Current manifest format (preferred):
        # mod: target=data/queries/economy.py sandbox=auto
        ...replacement source...

  In the manifest format, `sandbox` may be:
    auto -- follow the user's per-mod toggle in enabled_mods.json (default)
    on   -- force sandboxed, regardless of the user's toggle
    off  -- request unsandboxed; the user's sandbox toggle still takes priority

The rest of the file is the replacement module's source -- normally started
as a copy of the real file, so IDE syntax highlighting, linting and accurate
line numbers in tracebacks all work exactly like editing the game itself.
The target file on disk is never written to: an enabled mod's source is
substituted in at import time via a sys.meta_path finder, so disabling or
deleting a mod just reverts to the real file on the next launch.

install() must run before any project module is imported (see the top of
main.py): Python only executes a module's top-level code once per process
and caches the result in sys.modules, so installing the finder any later
would miss every module already imported by that point.

Every mod is either sandboxed or unsandboxed.
The audit hook checks selected operations against registered module globals on the active Python call stack.
It also checks functions defined in a sandboxed mod when timers or threads call them.
See documentation/other/SANDBOX_SECURITY.md for settings, import exceptions, and limitations.
The sandbox does not make untrusted code safe.

A short list of project files are reserved and cannot be mod targets:
mod_loader itself (would let a mod rewrite the sandbox rules), main (boot),
and data.platform (the IndexedDB / FS sync layer on web). A mod file whose
target is one of these is reported invalid in describe_mod() and skipped
in install().

Deliberately dependency-free (stdlib only) so it can run as the very first
thing main.py does, before anything else -- including data.constants -- has
loaded.
"""

import asyncio
import traceback

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

# --- Reserved mod targets ---------------------------------------------
#
# Modules whose replacement at import time would compromise the sandbox or
# the boot chain itself. A mod targeting any of these is refused at
# install() time and reported invalid in describe_mod(). Frozen so a mod
# that somehow reaches mod_loader._RESERVED_TARGETS can't add an entry that
# silently un-reserves itself (it would have to reassign the name on the
# module, but module-level lookups in the audit hook use closure-captured
# copies, not this name -- see _install_sandbox_audit_hook).
#
#   - mod_loader  : the loader itself; a mod here could rewrite the sandbox
#                  rules at runtime, or just uninstall the audit hook's
#                  effective config by mutating our globals.
#   - main        : bootstraps everything, including install(). A mod here
#                  could skip install() entirely.
#   - data.platform: the IndexedDB / FS sync layer on web; a mod here gets
#                  direct, unsandboxed browser storage access on the web
#                  build, where the Python-level sandbox doesn't apply
#                  anyway.
_RESERVED_TARGETS = frozenset({
    "mod_loader",
    "main",
    "data.platform",
})


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
    project, or (None, None) if the target is missing, malformed, would
    resolve outside the game folder, or is on the reserved-targets blacklist.
    Callers should also call _is_reserved_target() to produce a more useful
    error message in the reserved case."""
    module_name = _path_to_module_name(rel_path)
    if not module_name:
        return None, None
    if module_name in _RESERVED_TARGETS:
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


def _is_reserved_target(rel_path):
    candidate = _path_to_module_name(rel_path)
    return candidate is not None and candidate in _RESERVED_TARGETS


def _parse_first_line(first_line):
    """Parse a mod file's first line. Returns a dict with keys:
      target           -- the project-relative path string (e.g. "data/queries/economy.py"),
                         or None if the line is malformed.
      declared_sandbox -- "auto" (default), "on", or "off".
      legacy_format    -- True if the line was the bare "#path" form, False
                         if it was the manifest "# mod: ..." form.

    Both formats are accepted; legacy emits a deprecation log when the mod
    is actually loaded in install().
    """
    line = first_line.strip()
    if not line.startswith("#"):
        return {"target": None, "declared_sandbox": "auto", "legacy_format": False}

    body = line[1:].strip()
    # Manifest format: "# mod: target=... sandbox=auto"
    if body.lower().startswith("mod:"):
        fields = {}
        for token in body[4:].split():
            if "=" in token:
                k, _, v = token.partition("=")
                fields[k.strip().lower()] = v.strip()
            # Bare tokens (no '=') are ignored for forward-compat.
        target = fields.get("target")
        sandbox = fields.get("sandbox", "auto").lower()
        if sandbox not in ("auto", "on", "off"):
            sandbox = "auto"
        return {
            "target": target or None,
            "declared_sandbox": sandbox,
            "legacy_format": False,
        }
    # Legacy format: bare path after the '#'.
    return {
        "target": body or None,
        "declared_sandbox": "auto",
        "legacy_format": True,
    }


def read_mod(filename):
    """Backward-compatible (target_rel_path, source_text) tuple for callers
    that don't care about the manifest fields. Use _read_mod_full() for the
    declared sandbox and legacy flag. Raises ValueError on an empty file or
    a first line that isn't a recognized header comment, instead of letting
    a bad mod crash the caller with an IndexError.

    source_text is the *entire* file, first line included -- it's left in
    place as an ordinary comment rather than stripped, so a compile error
    inside the mod reports the same line number the user sees in their
    editor.
    """
    target, source, _declared, _legacy = _read_mod_full(filename)
    return target, source


def _read_mod_full(filename):
    """(target_rel_path, source_text, declared_sandbox, legacy_format)."""
    with open(os.path.join(MODS_DIR, filename), "r", encoding="utf-8") as f:
        text = f.read()
    first_line = text.split("\n", 1)[0]
    parsed = _parse_first_line(first_line)
    if not parsed["target"]:
        raise ValueError(
            'first line must be "#path/to/target.py" (legacy) or '
            '"# mod: target=path/to/target.py [sandbox=auto|on|off]" (current)'
        )
    return parsed["target"], text, parsed["declared_sandbox"], parsed["legacy_format"]


def describe_mod(filename):
    """Read-only summary for the Mods screen: target, module, validity, and
    current enabled/sandboxed state. Never raises -- a bad mod (including one
    with a syntax error, which would otherwise only surface as a crash the
    moment something imports its target module) just comes back invalid with
    an explanation in "error"."""
    info = {
        "target": None, "module": None, "valid": False, "error": None,
        "enabled": is_mod_enabled(filename), "active": is_mod_active(filename),
        "sandboxed": is_mod_sandboxed(filename),
        "sandbox_active": is_mod_sandbox_active(filename),
        "legacy_format": False,
    }
    try:
        target, source, declared_sandbox, legacy = _read_mod_full(filename)
        info["target"] = target
        info["legacy_format"] = legacy
        module_name, abs_target = _resolve_target(target)
        if module_name is None:
            if _is_reserved_target(target):
                info["error"] = (
                    f"target {target} is reserved for the game's own boot/sandbox "
                    "machinery and cannot be modded"
                )
            else:
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
# The audit hook checks selected operations against all active Python frames.
# Registration uses each mod's module dictionary identity, not a removable sentinel.
# Captured event tables resist reassignment of their module attributes.
# Synchronous calls through game functions still retain the mod's frame.
#
# A callback defined in a registered mod retains its registered globals.
# Deferred work with unregistered globals can run without a mod frame.
# Scheduling origins are not recorded. Browser calls can also bypass audit events.
# See documentation/other/SANDBOX_SECURITY.md for the full rules and limitations.

_SANDBOX_BLOCKED_EVENTS = frozenset({
    "open", "os.remove", "os.rmdir", "os.removedirs", "os.rename", "os.replace",
    "os.mkdir", "os.makedirs", "os.truncate", "os.chmod", "os.chown", "os.chflags",
    "os.lchflags", "os.link", "os.symlink", "os.listdir", "os.scandir", "os.system",
    "os.popen", "os.spawn", "os.exec", "os.fork", "os.forkpty", "os.posix_spawn",
    "os.kill", "os.killpg", "os.putenv", "os.unsetenv", "os.startfile",
    "subprocess.Popen", "shutil.rmtree", "shutil.copyfile", "shutil.copytree",
    "shutil.move",
})
_SANDBOX_BLOCKED_PREFIXES = ("socket.", "ctypes.")

# Module-name prefixes for CPython's own import machinery. When the *direct*
# caller of a blocked event is one of these, the hook skips the stack walk
# entirely: the import system legitimately opens .py files and lists
# directories to load modules a sandboxed mod asked for, and blocking that
# breaks every `import` statement a sandboxed mod issues. The threat model
# is the mod's *own* code doing I/O, not the import system's bookkeeping.
#
# Walking the stack underneath import machinery would still catch the mod's
# frame (which is what we want for game functions called by the mod, where
# the direct caller is the game function -- NOT import machinery). So this
# carve-out only applies when importlib itself is the immediate caller.
_IMPORT_MACHINERY_PREFIXES = (
    "_frozen_importlib",
    "_frozen_importlib_external",
    "importlib",
)

_audit_hook_installed = False
# Filled in by _install_sandbox_audit_hook(). _ModSourceLoader.exec_module
# uses it to register each sandboxed mod's module __dict__ id. Storing the
# *registrar* (rather than the set itself) as a module attribute is fine:
# the set is captured in the registrar's closure and is not reachable by
# reassigning this name. A sandboxed mod that reassigns
# _register_sandboxed_module = lambda m: None only breaks *future*
# registrations -- its own module was already registered before its
# top-level code started running.
_register_sandboxed_module = None


def _install_sandbox_audit_hook():
    """Install the PEP 578 audit hook with registration data and event tables in a closure.

    Reassigning module attributes does not replace these captured values.
    """
    global _audit_hook_installed, _register_sandboxed_module
    if _audit_hook_installed:
        return

    # Snapshot at install time. Even if a mod reassigns the module-level
    # _SANDBOX_BLOCKED_EVENTS later (e.g. via `import mod_loader;
    # mod_loader._SANDBOX_BLOCKED_EVENTS = set()`), the hook keeps using
    # these captured copies.
    blocked_events = frozenset(_SANDBOX_BLOCKED_EVENTS)
    blocked_prefixes = tuple(_SANDBOX_BLOCKED_PREFIXES)
    import_prefixes = tuple(_IMPORT_MACHINERY_PREFIXES)

    # id(module.__dict__) for every sandboxed module registered this
    # process. We hold strong refs to the modules themselves so their
    # __dict__ isn't GC'd before the module is (which would let a future
    # dict get the same id() and falsely read as sandboxed).
    sandboxed_dict_ids = set()
    sandboxed_module_refs = []

    def register(module):
        sandboxed_dict_ids.add(id(module.__dict__))
        sandboxed_module_refs.append(module)

    def is_import_machinery(frame):
        if frame is None:
            return False
        name = frame.f_globals.get("__name__", "")
        if not name:
            return False
        for p in import_prefixes:
            if name == p or name.startswith(p + "."):
                return True
        return False

    def hook(event, args):
        if event not in blocked_events and not any(
            event.startswith(p) for p in blocked_prefixes
        ):
            return
        # frame 0 is this hook itself; frame 1 is whatever Python code directly
        # invoked the audited operation.
        try:
            frame = sys._getframe(1)
        except (ValueError, RuntimeError):
            # No Python frame at all (e.g. the event fired from a C-level
            # call site with no Python caller). Be conservative: if we can't
            # tell who called it, allow it. The common case is interpreter
            # startup, not a mod smuggling an op through C.
            return

        # If the *direct* caller is Python's import machinery, skip the
        # stack walk entirely. The import system legitimately opens .py
        # files (read), lists directories, etc. to load modules a sandboxed
        # mod asked for via `import`. Blocking that breaks every import a
        # sandboxed mod issues, which makes the sandbox unusable rather than
        # safer.
        #
        # The threat model the sandbox is closing is "the mod's own code
        # does I/O via a game function it called" -- in that case the
        # direct caller is the game function, NOT importlib, so the
        # carve-out doesn't apply and the stack walk still catches the
        # mod's frame underneath.
        if is_import_machinery(frame):
            return

        # Walk the FULL call stack. If ANY frame on the stack has its
        # f_globals registered as a sandboxed mod's module __dict__, block.
        # This closes:
        #
        #   - the "delete your own marker" bypass (no marker in __dict__
        #     anymore; sandboxed-ness is keyed by dict identity);
        #   - the "hop through a game function that does file I/O" bypass
        #     (the mod's frame is still on the stack underneath the game
        #     function's);
        #   - the "exec(open, fresh_globals)" bypass (same -- the mod's
        #     frame is f_back of the exec'd frame).
        #
        # Mod-defined callbacks retain their registered globals, including on timers.
        # Deferred code with unregistered globals can lack a sandboxed frame.
        # See documentation/other/SANDBOX_SECURITY.md.
        while frame is not None:
            if id(frame.f_globals) in sandboxed_dict_ids:
                raise PermissionError(
                    f"'{event}' is blocked because a sandboxed mod is on "
                    "the call stack. Switch the mod to Unsandboxed on the "
                    "Mods screen if it genuinely needs this capability."
                )
            frame = frame.f_back

    sys.addaudithook(hook)
    _register_sandboxed_module = register
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
            # Register BEFORE exec, so the sandbox catches any audited op
            # the mod's top-level code triggers (including imports the mod
            # does at module load time). The set the registrar mutates is
            # a closure variable inside _install_sandbox_audit_hook -- it
            # is NOT this module's _SANDBOX_MARKER in module.__dict__, so
            # the mod cannot globals().pop(...) its way out.
            if _register_sandboxed_module is not None:
                _register_sandboxed_module(module)
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
    targets data/platform.py itself (now blocked by _RESERVED_TARGETS, but
    this duplication predates that and is still a reasonable isolation).
    So this duplicates just the read half of data/platform.py's
    hand-rolled IndexedDB glue, kept self-contained and stdlib-only like
    the rest of this file.
    """
    if sys.platform != "emscripten":
        return
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


def _effective_sandbox_setting(filename, declared_sandbox):
    """Combine the manifest preference with the user's per-mod toggle.

    auto follows the user's toggle. on always enables the sandbox.
    off permits unsandboxed execution only when the user also selects it.
    A conflicting off preference logs a warning and keeps the sandbox enabled.
    """
    if declared_sandbox == "on":
        return True
    if declared_sandbox == "off":
        if is_mod_sandboxed(filename):
            print(f"Mod '{filename}' declares sandbox=off but the user has it sandboxed; "
                  "honoring the user's setting (sandboxed). Switch it to Unsandboxed on "
                  "the Mods screen if the mod genuinely needs file access.")
            return True
        return False
    return is_mod_sandboxed(filename)


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
                target, source, declared_sandbox, legacy = _read_mod_full(filename)
            except Exception as e:
                print(f"Skipping mod '{filename}': {e}")
                continue

            if legacy:
                print(f"Mod '{filename}' uses the legacy '#path' header format; "
                      "consider migrating to '# mod: target=... sandbox=auto'.")

            module_name, abs_target = _resolve_target(target)
            if module_name is None:
                if _is_reserved_target(target):
                    print(f"Skipping mod '{filename}': target {target} is a reserved "
                          "module (mod_loader, main, or data.platform) and cannot be modded")
                else:
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

            sandboxed = _effective_sandbox_setting(filename, declared_sandbox)

            # On web, 'sandboxed' is advisory only. platform.window is
            # reachable from any Python code via `import platform` (stdlib,
            # patched by pygbag) and gives the mod the full browser: fetch,
            # XMLHttpRequest, localStorage, eval. None of those are CPython
            # audit events, so the audit hook can't see them. Tell the user
            # in plain text -- don't pretend the sandbox holds.
            if sandboxed and sys.platform == "emscripten":
                print(f"Mod '{filename}' is marked sandboxed, but on the web build the "
                      "Python-level sandbox does not extend to platform.window or browser "
                      "APIs. Treat it as fully privileged. A WASM runtime is proposed "
                      "in issue #51 but is not planned.")

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
                platform.window.console.log(f"[gd5 mods] install() raised: {e}")
                platform.window.console.log(traceback.format_exc())
            except Exception:
                pass
