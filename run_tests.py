"""Runs the whole test suite.

Right-click this file in the editor and pick "Run Python File in Terminal" --
no arguments, no typing. Everything under tests/ named test_*.py is picked up
automatically, so new test files need no wiring up here.
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.abspath(__file__))
TESTS_DIR = os.path.join(ROOT, "tests")


def main():
    # Works no matter which directory the editor launched us from
    sys.path.insert(0, ROOT)
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    if os.name == "nt":
        # Inherit a non-modal native error policy in test subprocesses. A
        # crashing dependency still returns a failing exit code, but cannot
        # strand the test runner behind a Windows Application Error dialog.
        import ctypes
        ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0002 | 0x8000)
    # Native V8/SDL audio stress tests are opt-in via
    # GD5_RUN_NATIVE_AUDIO_TESTS=1; ordinary test runs avoid native audio
    # stress processes.

    suite = unittest.defaultTestLoader.discover(start_dir=TESTS_DIR, top_level_dir=ROOT)
    result = unittest.TextTestRunner(verbosity=2).run(suite)

    print()
    if result.wasSuccessful():
        print(f"All {result.testsRun} tests passed.")
    else:
        print(f"{len(result.failures)} failed, {len(result.errors)} errored, "
              f"out of {result.testsRun} tests.")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
