"""Check release inventory against sources and inspect actual staging behavior."""
import ast
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from compilation_scripts import build_manifest as manifest, build_support as support

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "compilation_scripts")
INTENTIONALLY_UNSTAGED_FILES = set(manifest.DEV_ONLY_FILES)
NON_PACKAGE_DIRS = {
    ".git", ".github", ".eggs", "__pycache__", "venv", ".venv", "build", "dist",
    "web_stage", "assets", "base_maps", "saves", "scenarios", "tournament_saves",
    "compilation_scripts", "context", "map_tools", "scripts", "mods", "tests",
}
DEV_ONLY_PACKAGES = set(manifest.DEV_ONLY_PACKAGES)

def _sub_screen_opener_module_paths(tree):
    """First-arg string literals passed to every sub_screen_opener() call."""
    paths = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "sub_screen_opener" and node.args):
            try:
                paths.append(ast.literal_eval(node.args[0]))
            except (ValueError, SyntaxError):
                pass
    return paths


def top_level_modules():
    return {f for f in os.listdir(ROOT)
            if f.endswith(".py") and os.path.isfile(os.path.join(ROOT, f))
            and f not in INTENTIONALLY_UNSTAGED_FILES}


def first_party_packages():
    """Dotted names of every package (a directory with __init__.py) that ships."""
    found = set()
    for dirpath, dirnames, filenames in os.walk(ROOT):
        rel = os.path.relpath(dirpath, ROOT).replace(os.sep, "/")
        if rel == ".":
            dirnames[:] = [d for d in dirnames if d not in NON_PACKAGE_DIRS]
            continue
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        if "__init__.py" in filenames:
            found.add(rel.replace("/", "."))
    return found


class BuildManifestTests(unittest.TestCase):
    def test_repository_inventory_is_complete(self):
        self.assertFalse(top_level_modules() - set(manifest.DESKTOP_SOURCE_FILES))
        self.assertFalse(top_level_modules() - set(manifest.WEB_SOURCE_FILES) - {"soloud.py"})
        packages = first_party_packages()
        self.assertFalse(packages - set(manifest.RUNTIME_PACKAGES) - DEV_ONLY_PACKAGES)
        self.assertFalse({p.split(".")[0] for p in packages} - set(manifest.SOURCE_PACKAGES))

    def test_dynamic_screens_have_explicit_hidden_imports(self):
        tree = ast.parse(Path(ROOT, "screens/game/map.py").read_text(encoding="utf-8"))
        needed = set(_sub_screen_opener_module_paths(tree))
        args = manifest.windows_arguments()
        hidden = {args[i + 1] for i, arg in enumerate(args[:-1]) if arg == "--hidden-import"}
        self.assertFalse(needed - hidden)
        for module in needed:
            self.assertTrue(Path(ROOT, module.replace(".", "/") + ".py").is_file())
        self.assertFalse(needed - set(manifest.MAC_INCLUDES))

    def test_platform_native_dependencies(self):
        args = manifest.windows_arguments()
        for package in ("dragoman", "cryptography", "quickjs", "py_mini_racer"):
            self.assertEqual(args[args.index(package) - 1], "--collect-all")
            self.assertIn(package, manifest.NATIVE_PACKAGES)
        self.assertEqual(set(manifest.DESKTOP_SOURCE_FILES) - set(manifest.WEB_SOURCE_FILES), {"soloud.py"})
        self.assertIn("libdragoman.so", manifest.WEB_SOURCE_FILES)
        self.assertTrue({"gameState", "ui_elements", "soloud"} <= set(manifest.MAC_INCLUDES))

    def test_dev_only_packages_really_are_unimported(self):
        importers = []
        for dirpath, dirnames, filenames in os.walk(ROOT):
            dirnames[:] = [d for d in dirnames if d not in NON_PACKAGE_DIRS]
            for filename in filenames:
                if not filename.endswith(".py"):
                    continue
                path = Path(dirpath, filename)
                module = str(path.relative_to(ROOT)).replace(os.sep, ".")[:-3]
                if any(module.startswith(pkg) for pkg in DEV_ONLY_PACKAGES):
                    continue
                source = path.read_text(encoding="utf-8")
                for pkg in DEV_ONLY_PACKAGES:
                    if f"import {pkg}" in source or f"from {pkg}" in source:
                        importers.append(f"{module} imports {pkg}")
        self.assertEqual(importers, [])

    def test_build_entry_points_are_import_safe(self):
        original = os.getcwd()
        for module in ("html_compilation", "windows_compilation", "macos_compilation", "setup"):
            with patch("subprocess.run", side_effect=AssertionError("process during import")):
                importlib.import_module("compilation_scripts." + module)
            self.assertEqual(os.getcwd(), original)

    def test_py2app_setup_runs_from_project_root(self):
        result = subprocess.run([sys.executable, os.path.join(SCRIPTS, "setup.py"), "--name"],
                                cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_staged_sources_saves_settings_and_scratch(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary, "source")
            for relative in set(manifest.DESKTOP_SOURCE_FILES + manifest.WEB_SOURCE_FILES + ("mac64-libsoloud.dylib",)):
                target = source / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("fixture")
            files = {
                "data/json/settings_config.json": '{"private": true}',
                "data/json/shuffle_disabled_tracks.json": '["local"]',
                "data/runtime.py": "pass", "data/__pycache__/runtime.pyc": "private",
                "scripts/editors/tool.py": "pass", "data/generators/tool.py": "pass",
                "screens/game/runtime.py": "pass", "ui/rendering/widget.py": "pass",
                "data/multiplayer/realtime/relay_service.py": "pass",
                "map_logic/action.py": "pass", "saves/local/save.json": "private",
                "tournament_saves/local.json": "private", "mods/local.py": "private",
                "scenarios/map_editor/scratch.json": "private",
                "scenarios/historical/map.json": "{}", "base_maps/map.json": "{}",
            }
            for relative, content in files.items():
                target = source / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content)
            image = source / "assets/image.png"
            image.parent.mkdir(parents=True)
            image.write_bytes(b"\x89PNG\r\n\x1a\nfixture")
            for platform in ("web", "windows", "macos"):
                destination = Path(temporary, platform)
                with patch.object(support, "is_git_ignored", return_value=False):
                    support.stage_release(source, destination, platform)
                for directory in manifest.EMPTY_DIRS:
                    self.assertEqual(list((destination / directory).iterdir()), [])
                self.assertFalse((destination / "scenarios/map_editor/scratch.json").exists())
                self.assertTrue((destination / "scenarios/historical/map.json").exists())
                self.assertFalse((destination / "data/__pycache__/runtime.pyc").exists())
                self.assertFalse((destination / "scripts/editors/tool.py").exists())
                for name, value in manifest.RUNTIME_JSON_DEFAULTS.items():
                    self.assertEqual(json.loads((destination / "data/json" / name).read_text()), value)
                for name in ("data/runtime.py", "screens/game/runtime.py", "ui/rendering/widget.py",
                             "data/multiplayer/realtime/relay_service.py", "map_logic/action.py"):
                    self.assertTrue((destination / name).is_file())
                self.assertEqual(support.png_signature_mismatches(destination), [])
                (destination / "assets/image.png").write_bytes(b"wrong format")
                self.assertEqual(support.png_signature_mismatches(destination), [str(destination / "assets/image.png")])
                if platform == "macos":
                    with patch.object(support, "is_git_ignored", return_value=False):
                        mac_files = {Path(f).relative_to(source) for _, files in support.mac_data_files(source) for f in files}
                    self.assertIn(Path("data/runtime.py"), mac_files)
                    self.assertNotIn(Path("saves/local/save.json"), mac_files)

    def test_audio_filter_preserves_platform_difference(self):
        audio = Path(ROOT, "assets/local.mp3")
        with patch("beepbox_audio.has_beepbox_replacement", return_value=True):
            with patch.object(support, "is_git_ignored", side_effect=lambda p: str(p).endswith(".json")):
                self.assertTrue(support.include_asset(audio, "web"))
                self.assertFalse(support.include_asset(audio, "windows"))
                self.assertFalse(support.include_asset(audio, "macos"))
            with patch.object(support, "is_git_ignored", return_value=False):
                self.assertFalse(support.include_asset(audio, "web"))

    def test_cleanup_paths_are_contained(self):
        with self.assertRaises(ValueError):
            support.verified_build_path(ROOT, "..")
        with self.assertRaises(ValueError):
            support.verified_build_path(ROOT, ".")
        self.assertEqual(support.verified_build_path(ROOT, "dist"), str(Path(ROOT, "dist")))


if __name__ == "__main__":
    unittest.main()
