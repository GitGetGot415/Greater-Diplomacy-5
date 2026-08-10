"""Imports every first-party module, so a refactor can't silently break one.

The existing suite only exercises map_logic/diplomacy, and CI only runs
compileall + a narrow flake8 selection -- neither of which executes an import.
That leaves import cycles, missed renames and bad `from X import name` edits
invisible until someone launches the game.

Two live top-level cycles exist and work only because of the order main.py
imports things in (map_logic.setup.player_setup <-> ui.buttons, and
ui.buttons <-> map_logic.turn_processing.turn_manager), so this file imports modules in
a shuffled order as well as individually -- a cycle that only resolves under one
particular ordering is a latent startup crash.
"""

import importlib
import os
import random
import subprocess
import sys
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# Directories that hold no runtime game code.
SKIP_DIRS = {
    ".git", ".eggs", "__pycache__", "venv", ".venv", "build", "dist",
    "web_stage", "assets", "base_maps", "saves", "scenarios", "tournament_saves",
    "compilation_scripts",  # chdir + sys.path mutation at import time
    "map_tools",            # standalone dev scripts, not in the runtime graph
    "mods",                 # mod sources are loaded by mod_loader, not imported
    "tests",
    "data/editors",         # tkinter-only dev tools, excluded from the web build
    # One-shot maintenance scripts that do their work at module scope: importing
    # context_generator rewrites combined_scripts.txt, and importing
    # data/json/fix_countries.py rewrites countries_data.json.
    "context",
    "data/json",
}

SKIP_MODULES = {
    "soloud",               # vendored, loads a native library
    "main",                 # constructs the app; covered by test_controller_construction
    "temp_multiplayer_io",  # empty placeholder, staged by no build script
}


def first_party_modules():
    """Dotted module names for every runtime .py file in the project."""
    found = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        rel_dir = os.path.relpath(dirpath, ROOT).replace(os.sep, "/")
        if rel_dir == ".":
            rel_dir = ""
        dirnames[:] = [
            d for d in dirnames
            if d not in SKIP_DIRS and f"{rel_dir}/{d}".lstrip("/") not in SKIP_DIRS
        ]
        if rel_dir in SKIP_DIRS:
            continue
        for filename in sorted(filenames):
            if not filename.endswith(".py"):
                continue
            stem = filename[:-3]
            parts = ([p for p in rel_dir.split("/") if p] +
                     ([] if stem == "__init__" else [stem]))
            if not parts:
                continue
            name = ".".join(parts)
            if name in SKIP_MODULES:
                continue
            found.append(name)
    return sorted(set(found))


class ImportSmokeTests(unittest.TestCase):
    def test_every_module_imports(self):
        failures = []
        for name in first_party_modules():
            try:
                importlib.import_module(name)
            except Exception as exc:
                failures.append(f"{name}: {type(exc).__name__}: {exc}")
        self.assertEqual(failures, [], "modules failed to import:\n  " + "\n  ".join(failures))

    def test_import_order_does_not_matter(self):
        """Each module must import cleanly in a fresh interpreter with nothing
        else loaded first. Run out-of-process because the cycles resolve
        differently once sys.modules is already populated by the test above."""
        names = first_party_modules()
        random.Random(0).shuffle(names)
        # A handful of representative entry points; importing all of them in
        # separate interpreters would dominate the suite's runtime.
        probes = [n for n in names if n.count(".") <= 1][:12]
        failures = []
        for name in probes:
            proc = subprocess.run(
                [sys.executable, "-c", f"import {name}"],
                cwd=ROOT, capture_output=True, text=True,
                env={**os.environ, "PYTHONPATH": ROOT},
            )
            if proc.returncode != 0:
                failures.append(f"{name}: {proc.stderr.strip().splitlines()[-1:]}")
        self.assertEqual(failures, [], "modules failed to import standalone:\n  "
                                       + "\n  ".join(failures))


if __name__ == "__main__":
    unittest.main()
