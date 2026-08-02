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


_upload_js_defined = False


def pick_upload_file(on_result, extensions=None, multiple=False):
    """Opens the browser's native file picker (web only) so the user can
    choose real file(s) from their own machine, then calls on_result with a
    virtual-FS path (or list of paths, if `multiple`) whose basename(s) match
    what was picked -- or None/[] if the picker was cancelled. No-op call
    (immediately on_result(None)) on desktop, where the real file browser is
    used instead.

    `extensions` is a list like [".zip"], used as the input's `accept` filter.

    Self-contained via platform.window.eval(), same reasoning as
    download_file: pygbag's own upload path (webbrowser.open_file +
    EventTarget) relays picked-file data through Python-exec'd, JSON-in-JSON
    encoded strings we can't fully verify without a live browser -- given we
    already hit one real bug in pygbag's bundled JS for downloads, this stays
    in code we control. The wait-for-a-JS-flag polling loop below mirrors the
    exact pattern pygbag's own boot code already uses to wait for user media
    engagement (`while not platform.window.MM.UME: await asyncio.sleep(.1)`),
    confirmed to work in this runtime.
    """
    if not IS_WEB:
        on_result([] if multiple else None)
        return

    global _upload_js_defined
    import json
    import shutil
    import platform  # stdlib `platform`, patched by pygbag with `.window` on web

    if not _upload_js_defined:
        platform.window.eval(
            "window.__gd5_pick_file = function(accept, multiple) {"
            "  window.__gd5_upload_ready = false;"
            "  window.__gd5_upload_names = null;"
            "  var inp = document.createElement('input');"
            "  inp.type = 'file';"
            "  inp.accept = accept;"
            "  inp.multiple = multiple;"
            "  function finish(names) {"
            "    window.__gd5_upload_names = names ? JSON.stringify(names) : null;"
            "    window.__gd5_upload_ready = true;"
            "  }"
            "  inp.addEventListener('change', function() {"
            "    var files = Array.from(inp.files);"
            "    if (!files.length) { finish(null); return; }"
            "    var names = []; var remaining = files.length;"
            "    files.forEach(function(file, idx) {"
            "      var fr = new FileReader();"
            "      fr.onload = function() {"
            "        FS.writeFile('/tmp/gd5_upload_' + idx, new Uint8Array(fr.result));"
            "        names[idx] = file.name;"
            "        remaining -= 1;"
            "        if (remaining === 0) finish(names);"
            "      };"
            "      fr.readAsArrayBuffer(file);"
            "    });"
            "  }, { once: true });"
            "  inp.addEventListener('cancel', function() { finish(null); }, { once: true });"
            "  inp.click();"
            "};"
        )
        _upload_js_defined = True

    accept = ",".join(extensions) if extensions else ""
    platform.window.__gd5_pick_file(accept, multiple)

    async def _wait_for_upload():
        # ~120s safety net in case a browser doesn't fire "cancel" on an
        # abandoned file picker, so this can't hang forever.
        for _ in range(1200):
            if platform.window.__gd5_upload_ready:
                break
            await asyncio.sleep(0.1)

        names_json = platform.window.__gd5_upload_names
        if not names_json:
            on_result([] if multiple else None)
            return

        names = json.loads(names_json)
        paths = []
        for idx, name in enumerate(names):
            src = f"/tmp/gd5_upload_{idx}"
            dest = os.path.join("/tmp", name)
            try:
                shutil.move(src, dest)
            except Exception:
                dest = src
            paths.append(dest)

        on_result(paths if multiple else paths[0])

    run_background(_wait_for_upload)
