"""Checks that every first-party module is actually shipped by all three builds.

The desktop and web pipelines each declare, independently and with no shared
source of truth, which top-level modules and which packages to stage:

    compilation_scripts/html_compilation.py  SOURCE_FILES / SOURCE_PACKAGES
    compilation_scripts/windows_compilation.py  dirs_to_copy + a py_file tuple
    compilation_scripts/setup.py  DATA_FILES + OPTIONS['packages'] / ['includes']

Adding a module or a sub-package means editing all of them. Two of the three
fail *silently* when you forget: the web build only breaks in the browser with a
ModuleNotFoundError, and a missing entry in the desktop lists means mod_loader
can't find that file on disk, so every mod targeting it is rejected as "target
file not found". Nothing else in the repo or in CI catches either case.

The scripts are parsed with ast rather than imported: html_compilation.py does
sys.path.insert and os.chdir at module scope.
"""

import ast
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "compilation_scripts")

# Top-level .py files that are deliberately not shipped by any pipeline.
INTENTIONALLY_UNSTAGED_FILES = {
    "run_tests.py",           # developer entry point
    "simulate_crash.py",      # developer entry point, blocks on a dialog like run_tests.py
    "temp_multiplayer_io.py",  # empty placeholder, not in the runtime graph
}

# Directories at the repo root that hold no shippable game package.
NON_PACKAGE_DIRS = {
    ".git", ".github", ".eggs", "__pycache__", "venv", ".venv", "build", "dist",
    "web_stage", "assets", "base_maps", "saves", "scenarios", "tournament_saves",
    "compilation_scripts", "context", "map_tools", "mods", "tests",
}

# Sub-packages the web build drops on purpose.
WEB_EXCLUDED_SUBPACKAGES = {"data.editors"}  # tkinter dev tools

# Packages nothing imports at runtime, so py2app has no reason to bundle them
# for import. They are still shipped as loose .py by DATA_FILES, which is what
# mod targeting needs. Adding to this set is a deliberate statement that a
# package is dev-only -- a new *runtime* package must go in OPTIONS['packages'].
DEV_ONLY_PACKAGES = {"data.generators"}  # data-file generator scripts

# Modules py2app's static analysis cannot reach from main.py, because main.py
# imports them from inside _import_project_modules() rather than at module
# scope. These have to be named explicitly or they won't be bundled.
DEFERRED_IMPORT_MODULES = {"gameState", "ui_elements", "soloud"}


def _literal_lists(tree, names):
    """Every literal list/tuple assigned to one of `names`, anywhere in a tree."""
    out = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id in names:
                try:
                    out[target.id] = list(ast.literal_eval(node.value))
                except (ValueError, SyntaxError):
                    pass
    return out


def _parse(name):
    with open(os.path.join(SCRIPTS, name), encoding="utf-8") as fh:
        return ast.parse(fh.read())


def _parse_path(path):
    with open(path, encoding="utf-8") as fh:
        return ast.parse(fh.read())


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


def _windows_pyinstaller_hidden_imports(tree):
    """Module names passed via --hidden-import in windows_compilation's pyinstaller cmd.

    Adjacent string literals inside the `cmd = (...)` parens are concatenated
    by the parser itself, so this is a single string constant to literal_eval,
    not a list of pieces to join.
    """
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "cmd" for t in node.targets)):
            continue
        try:
            cmd = ast.literal_eval(node.value)
        except (ValueError, SyntaxError):
            continue
        if isinstance(cmd, str):
            return re.findall(r"--hidden-import (\S+)", cmd)
    return []


def _for_loop_literal(tree, var_name):
    """The literal a `for <var_name> in (...)` iterates over."""
    for node in ast.walk(tree):
        if (isinstance(node, ast.For) and isinstance(node.target, ast.Name)
                and node.target.id == var_name):
            try:
                return list(ast.literal_eval(node.iter))
            except (ValueError, SyntaxError):
                return []
    return []


def _dict_key_lists(tree, dict_name, keys):
    """Literal lists stored under `keys` in a literal dict assigned to `dict_name`."""
    out = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not (isinstance(target, ast.Name) and target.id == dict_name):
                continue
            if not isinstance(node.value, ast.Dict):
                continue
            for key_node, value_node in zip(node.value.keys, node.value.values):
                try:
                    key = ast.literal_eval(key_node)
                except (ValueError, SyntaxError):
                    continue
                if key in keys:
                    try:
                        out[key] = list(ast.literal_eval(value_node))
                    except (ValueError, SyntaxError):
                        pass
    return out


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
    @classmethod
    def setUpClass(cls):
        cls.html = _parse("html_compilation.py")
        cls.windows = _parse("windows_compilation.py")
        cls.setup = _parse("setup.py")
        cls.map_screen = _parse_path(os.path.join(ROOT, "screens", "menu_screens", "map.py"))

    # --- web ---------------------------------------------------------------

    def test_web_stages_every_top_level_module(self):
        staged = set(_literal_lists(self.html, {"SOURCE_FILES"}).get("SOURCE_FILES", []))
        staged.add("soloud.py")  # deliberately desktop-only; see html_compilation's comment
        missing = top_level_modules() - staged
        self.assertEqual(missing, set(),
                         "html_compilation.SOURCE_FILES is missing these; the web build "
                         "would fail with ModuleNotFoundError in the browser only")

    def test_web_stages_every_root_package(self):
        staged = set(_literal_lists(self.html, {"SOURCE_PACKAGES"}).get("SOURCE_PACKAGES", []))
        roots = {p.split(".")[0] for p in first_party_packages()}
        self.assertEqual(roots - staged, set(), "html_compilation.SOURCE_PACKAGES is incomplete")

    # --- windows -----------------------------------------------------------

    def test_windows_copies_every_top_level_module(self):
        staged = set(_for_loop_literal(self.windows, "py_file"))
        missing = top_level_modules() - staged
        self.assertEqual(missing, set(),
                         "windows_compilation's py_file tuple is missing these; mods "
                         "targeting them would be rejected as 'target file not found'")

    def test_windows_copies_every_root_package(self):
        staged = set(_literal_lists(self.windows, {"dirs_to_copy"}).get("dirs_to_copy", []))
        roots = {p.split(".")[0] for p in first_party_packages()}
        self.assertEqual(roots - staged, set(), "windows_compilation.dirs_to_copy is incomplete")

    def test_windows_hidden_imports_cover_sub_screen_opener(self):
        """sub_screen_opener() (screens/menu_screens/map.py) late-imports a screen
        via importlib.import_module() with a runtime string, which PyInstaller's
        static analysis never sees -- each target needs its own --hidden-import
        line in windows_compilation.py or the frozen exe raises ModuleNotFoundError
        the moment that screen is opened, never at build time and never when
        running from source. See the long comment above the pyinstaller cmd."""
        needed = set(_sub_screen_opener_module_paths(self.map_screen))
        declared = set(_windows_pyinstaller_hidden_imports(self.windows))
        self.assertEqual(needed - declared, set(),
                         "windows_compilation.py's pyinstaller --hidden-import list is "
                         "missing these sub_screen_opener() targets")

    # --- macOS -------------------------------------------------------------

    def test_py2app_lists_every_runtime_package(self):
        """py2app bundles nothing it isn't told about, so OPTIONS['packages'] has
        to name every sub-package explicitly -- a root entry does not recurse."""
        declared = set(_dict_key_lists(self.setup, "OPTIONS", {"packages"}).get("packages", []))
        missing = first_party_packages() - declared - DEV_ONLY_PACKAGES
        self.assertEqual(missing, set(),
                         "setup.py OPTIONS['packages'] is missing these sub-packages; "
                         "py2app will not bundle them. If a package is genuinely "
                         "dev-only, add it to DEV_ONLY_PACKAGES instead.")

    def test_dev_only_packages_really_are_unimported(self):
        """Keeps DEV_ONLY_PACKAGES honest: if game code starts importing one of
        these, it has to move into OPTIONS['packages'] or the macOS build ships
        an app that crashes on that import."""
        importers = []
        for dirpath, dirnames, filenames in os.walk(ROOT):
            rel = os.path.relpath(dirpath, ROOT).replace(os.sep, "/")
            if rel.split("/")[0] in NON_PACKAGE_DIRS:
                continue
            dirnames[:] = [d for d in dirnames if d not in NON_PACKAGE_DIRS]
            for filename in filenames:
                if not filename.endswith(".py"):
                    continue
                path = os.path.join(dirpath, filename)
                module = os.path.relpath(path, ROOT).replace(os.sep, ".")[:-3]
                if any(module.startswith(pkg) for pkg in DEV_ONLY_PACKAGES):
                    continue  # a dev-only package may import itself
                with open(path, encoding="utf-8") as fh:
                    source = fh.read()
                for pkg in DEV_ONLY_PACKAGES:
                    if f"import {pkg}" in source or f"from {pkg}" in source:
                        importers.append(f"{module} imports {pkg}")
        self.assertEqual(importers, [])

    def test_py2app_includes_the_deferred_modules(self):
        """main.py imports these from inside _import_project_modules(), so
        py2app's static analysis never sees them."""
        declared = set(_dict_key_lists(self.setup, "OPTIONS", {"includes"}).get("includes", []))
        self.assertEqual(DEFERRED_IMPORT_MODULES - declared, set(),
                         "setup.py OPTIONS['includes'] is missing these modules")

    def test_py2app_ships_loose_copies_for_mod_targeting(self):
        """mod_loader resolves a mod's target against a real file on disk, so
        every top-level module needs a loose copy alongside the bundle."""
        staged = set()
        for node in ast.walk(self.setup):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "append"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "DATA_FILES"):
                continue
            try:
                dest, files = ast.literal_eval(node.args[0])
            except (ValueError, SyntaxError, IndexError):
                continue
            if dest == ".":
                staged.update(files)
        missing = top_level_modules() - staged - {"main.py"}  # main.py is APP
        self.assertEqual(missing, set(),
                         "setup.py DATA_FILES is missing loose copies of these; mods "
                         "targeting them would be rejected as 'target file not found'")

    # --- consistency between pipelines -------------------------------------

    def test_pipelines_agree_on_the_module_set(self):
        web = set(_literal_lists(self.html, {"SOURCE_FILES"}).get("SOURCE_FILES", []))
        windows = set(_for_loop_literal(self.windows, "py_file"))
        # Windows additionally ships soloud.py, which the web build has no use for.
        self.assertEqual(windows - web, {"soloud.py"},
                         "the desktop and web module lists have drifted apart")

    def test_web_exclusions_are_the_documented_ones(self):
        """Guards the one intentional asymmetry: data/editors is tkinter-only and
        dropped from the web build, so mods targeting it work on desktop only."""
        self.assertIn("data.editors", first_party_packages())
        self.assertEqual(WEB_EXCLUDED_SUBPACKAGES, {"data.editors"})


if __name__ == "__main__":
    unittest.main()
