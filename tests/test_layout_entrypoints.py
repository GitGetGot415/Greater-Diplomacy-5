"""Check entry points and resource paths affected by source relocation."""

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class LayoutEntrypointTests(unittest.TestCase):
    def test_file_browser_game_folder_still_points_to_the_repository(self):
        from ui.dialogs.file_browser_screen import build_places, DRIVE_VIEW

        places = [Path(path) for _label, path in build_places() if path != DRIVE_VIEW]
        self.assertIn(ROOT, places)

    def test_benchmark_launchers_find_the_project_from_another_directory(self):
        for relative in ("scripts/benchmarks/ojh_benchmark.py", "map_tools/ojh_benchmark.py"):
            with self.subTest(command=relative), tempfile.TemporaryDirectory() as directory:
                result = subprocess.run(
                    [sys.executable, str(ROOT / relative), "--help"],
                    cwd=directory,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("turns", result.stdout)
                self.assertIn("fps", result.stdout)


if __name__ == "__main__":
    unittest.main()
