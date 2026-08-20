"""Manually trigger the crash handler to see what a player sees.

Right-click and "Run Python File in Terminal" (same as run_tests.py), or:

    python simulate_crash.py

Fakes an unhandled exception and feeds it to main._write_crash_log() -- the
same function main.py's top-level except block calls on a real crash -- so
the actual popup shows on screen and a real ~/GD5_crash.log gets written.
Not a unittest on purpose: it blocks on the dialog until you click OK, which
is exactly what you want when eyeballing it, but would hang run_tests.py if
it were discovered as a test (see tests/test_crash_handler.py for the
non-blocking, mocked version that runs there instead).
"""

import os

import main


def _simulate_bad_deployment():
    """Stands in for whatever deep call actually blows up during a real
    crash -- name chosen so the traceback in the popup/log looks like a
    plausible in-game failure rather than an obviously-fake test string."""
    raise ValueError("Simulated crash: no valid deployment target found for unit 42")


if __name__ == "__main__":
    crash_log_path = os.path.expanduser("~/GD5_crash.log")
    print("Triggering a fake crash...")
    print(f"Watch for the popup, then check: {crash_log_path}")

    try:
        _simulate_bad_deployment()
    except Exception:
        main._write_crash_log()

    print("\nDone. Crash log contents:\n")
    with open(crash_log_path, "r", encoding="utf-8") as f:
        print(f.read())
