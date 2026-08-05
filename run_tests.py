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
