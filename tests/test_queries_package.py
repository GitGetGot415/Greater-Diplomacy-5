"""The queries package re-exports submodules with star imports, which silently replace names."""

import ast
import os
import unittest

import data.queries as queries

PACKAGE_DIR = os.path.dirname(queries.__file__)


def public_definitions():
    """Return {submodule: names} for public functions, classes, and variables each one defines."""
    definitions = {}
    for filename in sorted(os.listdir(PACKAGE_DIR)):
        if not filename.endswith(".py") or filename == "__init__.py":
            continue
        with open(os.path.join(PACKAGE_DIR, filename), encoding="utf-8") as stream:
            tree = ast.parse(stream.read())
        names = set()
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(node.name)
            elif isinstance(node, ast.Assign):
                names.update(target.id for target in node.targets if isinstance(target, ast.Name))
        definitions[filename[:-3]] = {name for name in names if not name.startswith("_")}
    return definitions


def imported_modules(path):
    """Return every module that a source file imports, at any depth."""
    with open(path, encoding="utf-8") as stream:
        tree = ast.parse(stream.read())
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and not node.level:
            modules.add(node.module or "")
    return modules


class LayeringTests(unittest.TestCase):
    def test_data_does_not_import_ui_or_screens(self):
        """Dialog helpers once kept almost every module in one import cycle."""
        # Tournament file work draws a progress bar and clears name caches. It is not part of a cycle.
        allowed = {os.path.join("multiplayer", "tournament", "files.py")}
        data_dir = os.path.dirname(PACKAGE_DIR)
        for root, _dirs, files in os.walk(data_dir):
            for filename in files:
                path = os.path.join(root, filename)
                if not filename.endswith(".py") or os.path.relpath(path, data_dir) in allowed:
                    continue
                for module in imported_modules(path):
                    with self.subTest(path=path, module=module):
                        self.assertNotIn(module.split(".")[0], ("ui", "screens"))


class QueriesPackageTests(unittest.TestCase):
    def test_public_names_are_unique_across_submodules(self):
        owners = {}
        for module, names in public_definitions().items():
            for name in names:
                self.assertNotIn(name, owners, f"{name} is public in {module} and {owners.get(name)}.")
                owners[name] = module

    def test_every_public_definition_reaches_the_package_unchanged(self):
        for module, names in public_definitions().items():
            submodule = getattr(queries, module)
            for name in names:
                with self.subTest(module=module, name=name):
                    self.assertIs(getattr(queries, name), getattr(submodule, name))


if __name__ == "__main__":
    unittest.main()
