"""Check runtime imports and initialization boundaries in fresh interpreters.

The map, player setup, and turn manager have reciprocal dependencies.
Backend state and game rules must also load without creating a map screen.
Fresh-process probes detect cycles hidden by an already populated module cache.
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
    "scripts",              # offline editors, maintenance, previews, and benchmarks
    # The source export tool writes its output when imported.
    "context",
    "data/json",
}

SKIP_MODULES = {
    "soloud",               # vendored, loads a native library
    "main",                 # constructs the app; covered by test_controller_construction
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
        # Include deeper boundaries affected by imports moving to module scope.
        probes = [n for n in names if n.count(".") <= 1][:12]
        probes += [
            "data.queries", "data.runtime_rules", "data.migrations",
            "data.multiplayer.realtime.session",
            "map_logic.actions.player_actions",
            "map_logic.ai.ai_handler", "map_logic.ai.ai_evaluation",
            "map_logic.diplomacy.action_definitions",
            "map_logic.system32.turn_processor",
            "screens.game.map", "screens.game.orders",
            "screens.setup.player_setup", "ui.dialogs",
        ]
        failures = []
        for name in dict.fromkeys(probes):
            proc = subprocess.run(
                [sys.executable, "-c", f"import {name}"],
                cwd=ROOT, capture_output=True, text=True,
                env={**os.environ, "PYTHONPATH": ROOT},
            )
            if proc.returncode != 0:
                failures.append(f"{name}: {proc.stderr.strip().splitlines()[-1:]}")
        self.assertEqual(failures, [], "modules failed to import standalone:\n  "
                                       + "\n  ".join(failures))

    def test_main_waits_for_mod_installation_before_loading_game_modules(self):
        script = """
import sys
import main
for name in ('data.constants', 'data.queries', 'ui_elements', 'screens.game.map'):
    assert name not in sys.modules, name
"""
        result = subprocess.run(
            [sys.executable, "-c", script], cwd=ROOT,
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
