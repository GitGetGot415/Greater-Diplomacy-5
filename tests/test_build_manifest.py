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
import zipfile
from unittest.mock import patch

from compilation_scripts import build_manifest as manifest, build_support as support
from data.io import starting_defaults

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "compilation_scripts")
INTENTIONALLY_UNSTAGED_FILES = set(manifest.DEV_ONLY_FILES)
NON_PACKAGE_DIRS = {
    ".git", ".github", ".eggs", "__pycache__", "venv", ".venv", "build", "dist",
    "web_stage", "assets", "base_maps", "saves", "scenarios", "tournament_saves",
    "compilation_scripts", "context", "scripts", "mods", "tests",
}
DEV_ONLY_PACKAGES = set(manifest.DEV_ONLY_PACKAGES)

def _sub_screen_opener_module_paths(tree):
    """Module-path string literals passed to every _sub_screen_opener() call."""
    paths = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "_sub_screen_opener" and len(node.args) > 1):
            try:
                paths.append(ast.literal_eval(node.args[1]))
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
        tree = ast.parse(Path(ROOT, "screens/game/map_buttons.py").read_text(encoding="utf-8"))
        needed = set(_sub_screen_opener_module_paths(tree))
        self.assertTrue(needed)
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
        self.assertIn("soloud", manifest.MAC_INCLUDES)

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
        for module in ("html_compilation", "windows_compilation", "macos_compilation", "setup",
                       "android_tools", "android_compilation", "test_android_build"):
            with patch("subprocess.run", side_effect=AssertionError("process during import")):
                importlib.import_module("compilation_scripts." + module)
            self.assertEqual(os.getcwd(), original)

    def test_py2app_setup_runs_from_project_root(self):
        result = subprocess.run([sys.executable, os.path.join(SCRIPTS, "setup.py"), "--name"],
                                cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_asset_inventory_batches_git_rules_and_refreshes_each_scan(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            subprocess.run(["git", "init", "-q", str(root)], check=True, capture_output=True)
            (root / ".gitignore").write_text("*.tmp\n/assets/fallback.json\n", encoding="utf-8")
            assets = root / "assets"
            nested = assets / "nested"
            nested.mkdir(parents=True)
            (nested / ".gitignore").write_text("!keep.tmp\n", encoding="utf-8")
            for relative in ("ignored.tmp", "nested/keep.tmp", "visible space é.txt", "fallback.mp3", "full.mp3"):
                (assets / relative).write_text("fixture", encoding="utf-8")
            for name in ("fallback.json", "full.json"):
                (assets / name).write_text(json.dumps({"format": "BeepBox", "channels": []}), encoding="utf-8")
            for platform in ("web", "windows", "macos"):
                with self.subTest(platform=platform), patch.object(
                        support.subprocess, "run", wraps=subprocess.run) as run:
                    inventory = {relative.as_posix() for _, relative in support.distributed_files(root, platform)}
                self.assertEqual(run.call_count, 1)
                self.assertIn("--stdin", run.call_args.args[0])
                self.assertIn("-z", run.call_args.args[0])
                self.assertIn("assets/nested/keep.tmp", inventory)
                self.assertIn("assets/visible space é.txt", inventory)
                self.assertIn("assets/full.json", inventory)
                self.assertNotIn("assets/ignored.tmp", inventory)
                self.assertNotIn("assets/fallback.json", inventory)
                self.assertNotIn("assets/full.mp3", inventory)
                self.assertEqual("assets/fallback.mp3" in inventory, platform == "web")
            (root / ".gitignore").write_text("", encoding="utf-8")
            inventory = {relative.as_posix() for _, relative in support.distributed_files(root, "web")}
            self.assertIn("assets/ignored.tmp", inventory)
            self.assertIn("assets/fallback.json", inventory)
            self.assertNotIn("assets/fallback.mp3", inventory)

    def test_git_inventory_preserves_missing_git_and_non_repository_behavior(self):
        path = Path(ROOT, "assets/fixture.txt")
        for failure in (FileNotFoundError("git is unavailable"),
                        subprocess.CompletedProcess([], 128, stdout=b"", stderr=b"not a repository")):
            options = {"side_effect": failure} if isinstance(failure, OSError) else {"return_value": failure}
            with self.subTest(failure=failure), patch.object(support.subprocess, "run", **options):
                self.assertEqual(support.git_ignored_paths(ROOT, [path]), set())
        with patch.object(support.subprocess, "run") as run:
            self.assertEqual(support.git_ignored_paths(ROOT, []), set())
            run.assert_not_called()

    def test_staged_sources_saves_settings_and_scratch(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary, "source").resolve()
            for relative in set(manifest.DESKTOP_SOURCE_FILES + manifest.WEB_SOURCE_FILES + ("mac64-libsoloud.dylib",)):
                target = source / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("fixture")
            files = {
                "data/json/settings_config.json": '{"private": true}',
                "data/json/shuffle_disabled_tracks.json": '["local"]',
                "data/json/research_display.json": '{"defaults": {"icon_scale": 3}}',
                "data/research_display.py": "pass",
                "data/runtime.py": "pass", "data/__pycache__/runtime.pyc": "private",
                "scripts/editors/tool.py": "pass", "data/generators/tool.py": "pass",
                "screens/game/runtime.py": "pass", "ui/rendering/widget.py": "pass",
                "data/multiplayer/realtime/relay_service.py": "pass",
                "map_logic/action.py": "pass", "saves/local/save.json": "private",
                "tournament_saves/local.json": "private", "mods/local.py": "private",
                "scenarios/map_editor/scratch.json": "private",
                "scenarios/historical/map.json": "{}", "base_maps/map.json": "{}",
            }
            defaults = starting_defaults.read_starting_defaults()
            defaults["active_albums.json"] = ["Fixture Album"]
            defaults["starting_song.json"] = {"track": "assets/music/Fixture Album/start.ogg"}
            defaults["scenario_settings.json"] = {"fog_of_war": False}
            files[manifest.STARTING_DEFAULTS_PATH] = json.dumps(defaults)
            for relative, content in files.items():
                target = source / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content)
            image = source / "assets/image.png"
            image.parent.mkdir(parents=True)
            image.write_bytes(b"\x89PNG\r\n\x1a\nfixture")
            for platform in ("web", "windows", "macos"):
                destination = Path(temporary, platform)
                with patch.object(support, "git_ignored_paths", return_value=set()):
                    support.stage_release(source, destination, platform)
                for directory in manifest.EMPTY_DIRS:
                    self.assertEqual(list((destination / directory).iterdir()), [])
                self.assertFalse((destination / "scenarios/map_editor/scratch.json").exists())
                self.assertTrue((destination / "scenarios/historical/map.json").exists())
                self.assertFalse((destination / "data/__pycache__/runtime.pyc").exists())
                self.assertFalse((destination / "scripts/editors/tool.py").exists())
                for name in starting_defaults.PREFERENCE_FILES:
                    self.assertEqual(json.loads((destination / "data/json" / name).read_text()), defaults[name])
                for name in ("random_setup", "ai_defaults"):
                    self.assertFalse((destination / "data/json" / name).exists())
                self.assertEqual(json.loads((destination / manifest.STARTING_DEFAULTS_PATH).read_text()), defaults)
                self.assertEqual(json.loads((destination / "data/json/research_display.json").read_text()),
                                 {"defaults": {"icon_scale": 3}})
                for name in ("data/runtime.py", "screens/game/runtime.py", "ui/rendering/widget.py",
                             "data/multiplayer/realtime/relay_service.py", "map_logic/action.py",
                             "data/research_display.py"):
                    self.assertTrue((destination / name).is_file())
                self.assertEqual(support.png_signature_mismatches(destination), [])
                (destination / "assets/image.png").write_bytes(b"wrong format")
                self.assertEqual(support.png_signature_mismatches(destination), [str(destination / "assets/image.png")])
                if platform == "macos":
                    with patch.object(support, "git_ignored_paths", return_value=set()):
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
        self.assertEqual(support.verified_build_path(ROOT, "dist"), str(Path(ROOT, "dist").resolve()))

    def test_windows_build_preserves_other_platform_outputs(self):
        # Import the entry point only for this integration of cleanup, compiler, and ZIP staging.
        from compilation_scripts import windows_compilation

        original_directory = os.getcwd()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            # Use temporary fixture paths, never the checkout's distribution directories.
            output = root / "packages/windows"
            output.mkdir(parents=True)
            (output / "obsolete.dat").write_bytes(b"old Windows output")
            android = root / "packages/android/game.apk"
            android.parent.mkdir()
            android.write_bytes(b"keep Android output")
            unrelated = root / "packages/other.dat"
            unrelated.write_bytes(b"keep other output")
            source = root / "runtime.py"
            source.write_text("# fixture\n", encoding="utf-8")

            def compile_fixture(command):
                destination = root / command[command.index("--distpath") + 1]
                destination.mkdir(parents=True, exist_ok=True)
                (destination / "main.exe").write_bytes(b"compiled Windows executable")
                return subprocess.CompletedProcess(command, 0)

            try:
                with patch.object(windows_compilation, "REPO_ROOT", str(root)), \
                        patch.object(manifest, "WINDOWS_DIST_DIR", "packages/windows"), \
                        patch.object(windows_compilation.subprocess, "run", side_effect=compile_fixture), \
                        patch.object(windows_compilation, "distributed_files", return_value=[
                            (source, Path("runtime.py"))]), \
                        patch.object(windows_compilation, "reset_runtime_files"):
                    windows_compilation.main()
                self.assertEqual(android.read_bytes(), b"keep Android output")
                self.assertEqual(unrelated.read_bytes(), b"keep other output")
                self.assertFalse((output / "obsolete.dat").exists())
                self.assertEqual((output / "main.exe").read_bytes(), b"compiled Windows executable")
                archives = list(output.glob("*.zip"))
                self.assertEqual(len(archives), 1)
                with zipfile.ZipFile(archives[0]) as archive:
                    self.assertEqual(set(archive.namelist()), {"main.exe", "runtime.py"})
                    self.assertEqual(archive.read("main.exe"), b"compiled Windows executable")
            finally:
                os.chdir(original_directory)

    def test_macos_build_preserves_other_platform_outputs_and_caches(self):
        # Exercise the entry point with a temporary compiler/ditto fixture, not macOS tools.
        from compilation_scripts import macos_compilation

        original_directory = os.getcwd()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            output, work = root / "packages/macos", root / "work/macos"
            for folder in (output, work):
                folder.mkdir(parents=True)
                (folder / "obsolete.dat").write_bytes(b"old macOS output")
            siblings = (root / "packages/android/game.apk", root / "packages/windows/game.exe",
                        root / "packages/web/index.html", root / "work/android/cache.dat")
            for sibling in siblings:
                sibling.parent.mkdir(parents=True, exist_ok=True)
                sibling.write_bytes(b"keep")

            def run_fixture(command):
                if command[0] == "ditto":
                    self.assertEqual(Path(command[-2]), output / "package")
                    self.assertTrue((output / "package/main.app/Contents/MacOS/main").is_file())
                    Path(command[-1]).write_bytes(b"macOS archive")
                else:
                    self.assertEqual(Path(command[command.index("--dist-dir") + 1]), output)
                    self.assertEqual(Path(command[command.index("--bdist-base") + 1]), work)
                    app = output / "main.app/Contents/MacOS/main"
                    app.parent.mkdir(parents=True)
                    app.write_bytes(b"macOS executable")
                    work.mkdir(parents=True)
                return subprocess.CompletedProcess(command, 0)

            try:
                with patch.object(macos_compilation, "REPO_ROOT", str(root)), \
                        patch.object(manifest, "MACOS_DIST_DIR", "packages/macos"), \
                        patch.object(manifest, "MACOS_BUILD_DIR", "work/macos"), \
                        patch.object(macos_compilation.subprocess, "run", side_effect=run_fixture), \
                        patch.object(macos_compilation, "reset_runtime_files"):
                    macos_compilation.main()
                for sibling in siblings:
                    self.assertEqual(sibling.read_bytes(), b"keep")
                self.assertFalse((output / "obsolete.dat").exists())
                self.assertFalse((work / "obsolete.dat").exists())
                self.assertEqual(len(list(output.glob("*.zip"))), 1)
                self.assertTrue((output / "package/README.txt").is_file())
            finally:
                os.chdir(original_directory)

    def test_web_export_preserves_siblings_and_separates_archive_from_runtime(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            source = root / "browser-output"
            source.mkdir()
            (source / "index.html").write_text("game", encoding="utf-8")
            (source / "game.apk").write_bytes(b"game bundle")
            archive = root / "release.zip"
            archive.write_bytes(b"web archive")
            output = root / "packages/web"
            output.mkdir(parents=True)
            (output / "obsolete.dat").write_bytes(b"old")
            siblings = [root / "packages" / name / "keep.dat" for name in ("windows", "macos", "android")]
            for sibling in siblings:
                sibling.parent.mkdir()
                sibling.write_bytes(b"keep")
            with patch.object(manifest, "WEB_DIST_DIR", "packages/web"), \
                    patch.object(manifest, "WEB_CONTENT_DIR", "packages/web/package"):
                content, release = support.export_web_build(root, source, archive, "GD5 WEB fixture.zip")
                self.assertEqual((content / "index.html").read_text(), "game")
                self.assertEqual((content / "game.apk").read_bytes(), b"game bundle")
                self.assertEqual(release.read_bytes(), b"web archive")
                self.assertEqual(list(content.glob("*.zip")), [])
                self.assertFalse((output / "obsolete.dat").exists())
                # A failed rebuild must leave the previous exported package available.
                with self.assertRaises(FileNotFoundError):
                    support.export_web_build(root, source, root / "missing.zip", "new.zip")
                self.assertEqual(release.read_bytes(), b"web archive")
            for sibling in siblings:
                self.assertEqual(sibling.read_bytes(), b"keep")


if __name__ == "__main__":
    unittest.main()
