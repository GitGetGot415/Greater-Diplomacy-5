"""Single source of truth for 'are we running under pygbag/Pyodide in a browser'.

Pyodide/pygbag report sys.platform == "emscripten" at runtime; every other
target (Windows/macOS/Linux desktop, PyInstaller, py2app) reports its normal
platform string. Import IS_WEB instead of re-checking sys.platform so the
detection logic only ever lives in one place.
"""
import sys
import threading

IS_WEB = sys.platform == "emscripten"


def run_background(fn, *args, **kwargs):
    """Fire-and-forget a unit of work without blocking the caller's frame.

    Desktop: a daemon thread, same as calling threading.Thread(...).start() directly.

    Web: Pyodide has no real OS threads by default, so fn runs synchronously,
    right now, on the caller's frame. Callers on the web path must already be
    tolerant of that (e.g. LLM AI networking, the only genuinely slow work these
    call sites did, is disabled on web).
    """
    if IS_WEB:
        fn(*args, **kwargs)
    else:
        threading.Thread(target=fn, args=args, kwargs=kwargs, daemon=True).start()
