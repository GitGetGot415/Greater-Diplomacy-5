"""Single source of truth for 'are we running under pygbag/Pyodide in a browser'.

Pyodide/pygbag report sys.platform == "emscripten" at runtime; every other
target (Windows/macOS/Linux desktop, PyInstaller, py2app) reports its normal
platform string. Import IS_WEB instead of re-checking sys.platform so the
detection logic only ever lives in one place.
"""
import asyncio
import os
import sys
import threading

IS_WEB = sys.platform == "emscripten"


def run_background(fn, *args, **kwargs):
    """Fire-and-forget a unit of work without blocking the caller's frame.

    If `fn` is a coroutine function (contains `await asyncio.sleep(0)` at
    natural checkpoints), it's scheduled cooperatively:
    - Web: `asyncio.ensure_future` on the SAME event loop main.py's Controller.run()
      is already running on. Pyodide has no real OS threads, so this is what
      actually lets the loading bar animate and keeps the browser tab (and its
      audio scheduling) alive during heavy turn processing -- every `await`
      inside `fn` hands control back to the render loop for a frame.
    - Desktop: a daemon thread running its own private event loop (via
      `asyncio.run`), preserving the old fully-parallel behavior -- the render
      thread never has to wait for `fn`'s `await` points at all.

    Plain (non-async) `fn` keeps the old behavior: a daemon thread on desktop,
    or run synchronously right now on web (only safe for call sites that are
    already tolerant of that, e.g. LLM AI networking, which is disabled on web).
    """
    if asyncio.iscoroutinefunction(fn):
        if IS_WEB:
            asyncio.ensure_future(fn(*args, **kwargs))
        else:
            threading.Thread(target=lambda: asyncio.run(fn(*args, **kwargs)), daemon=True).start()
    elif IS_WEB:
        fn(*args, **kwargs)
    else:
        threading.Thread(target=fn, args=args, kwargs=kwargs, daemon=True).start()


_download_js_defined = False


def download_file(path):
    """Send a file from the browser's virtual filesystem to the user's real
    Downloads folder (web only; no-op on desktop, where files are just written
    to a real path directly).

    `path` is a path inside the virtual FS (e.g. a relative path from the
    current working directory), not a real host path -- there is no such
    thing on web.

    pygbag ships a JS helper for exactly this (MM.download(), used by its own
    built-in xterm "rx" console command), but pygbag 0.9.3's bundled copy has
    a genuine bug: dl_blob(blob) only declares a `blob` parameter yet
    references a bare `filename` in its body, so calling MM.download(path)
    always throws "filename is not defined" (confirmed by pulling pygbag's
    own pythons.js from its CDN). So instead of relying on their broken
    helper, we define our own corrected version once via platform.window.eval
    and call that -- same approach (Blob + temporary <a download> click),
    minus the bug.
    """
    if not IS_WEB:
        return
    global _download_js_defined
    import platform  # stdlib `platform`, patched by pygbag with `.window` on web
    if not _download_js_defined:
        platform.window.eval(
            "window.__gd5_download = function(diskfile, filename) {"
            "  var blob = new Blob([FS.readFile(diskfile)]);"
            "  var elem = window.document.createElement('a');"
            "  elem.href = window.URL.createObjectURL(blob);"
            "  elem.download = filename;"
            "  document.body.appendChild(elem);"
            "  elem.click();"
            "  document.body.removeChild(elem);"
            "};"
        )
        _download_js_defined = True
    platform.window.__gd5_download(path, os.path.basename(path))
