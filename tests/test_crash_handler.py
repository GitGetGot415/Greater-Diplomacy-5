"""Exercises main._write_crash_log(), the top-level handler main.py's
`if __name__ == "__main__":` block calls when the game dies with an
unhandled exception. Simulates a crash without actually killing the
interpreter, so it can run as part of the normal suite (python run_tests.py)
instead of needing a real game crash to check the handler still works.

tkinter is mocked throughout: there's no display in CI, and a real
messagebox.showerror() call would block the test run waiting for a click.
"""

import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import main


class CrashHandlerTests(unittest.TestCase):
    def setUp(self):
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.crash_log_path = os.path.join(
            self._temporary_directory.name, "GD5_crash.log"
        )

    def tearDown(self):
        self._temporary_directory.cleanup()

    def _simulate_crash(self):
        """Raises and hands the exception to _write_crash_log(), the same
        way main.py's top-level except block does -- traceback.print_exc()
        inside the handler reads off sys.exc_info(), so this has to be
        called while the except block is still active."""
        try:
            raise ValueError("simulated crash for testing")
        except ValueError:
            main._write_crash_log(self.crash_log_path)

    @mock.patch("tkinter.messagebox.showerror")
    @mock.patch("tkinter.Tk")
    def test_writes_traceback_and_shows_popup(self, mock_tk, mock_showerror):
        self._simulate_crash()

        self.assertTrue(os.path.exists(self.crash_log_path))
        with open(self.crash_log_path, "r", encoding="utf-8") as f:
            contents = f.read()

        self.assertIn("Greater Diplomacy 5 crash report", contents)
        self.assertIn("Time:", contents)
        self.assertIn("OS:", contents)
        self.assertIn("ValueError: simulated crash for testing", contents)

        # The popup is what tells a player the file exists at all -- confirm
        # it actually fired and pointed at the same path we just wrote.
        mock_showerror.assert_called_once()
        popup_body = mock_showerror.call_args[0][1]
        self.assertIn(self.crash_log_path, popup_body)

    def test_missing_display_does_not_swallow_the_log(self):
        """A machine with no display (or a broken tkinter) still has to end
        up with the crash log on disk -- the popup is best-effort, the file
        write is not."""
        with mock.patch("tkinter.Tk", side_effect=RuntimeError("no display")):
            self._simulate_crash()

        self.assertTrue(os.path.exists(self.crash_log_path))
        with open(self.crash_log_path, "r", encoding="utf-8") as f:
            contents = f.read()
        self.assertIn("ValueError: simulated crash for testing", contents)


if __name__ == "__main__":
    unittest.main()
