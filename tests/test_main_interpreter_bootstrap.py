import os
import unittest
from unittest.mock import patch

import main as game_main


class MainInterpreterBootstrapTests(unittest.TestCase):
    def test_system_python_relaunches_source_with_the_project_venv(self):
        expected_python = os.path.join(
            os.path.dirname(game_main.__file__), "venv", "bin", "python"
        )
        with patch.object(game_main.sys, "executable", "/usr/bin/python3"), \
                patch.object(game_main.sys, "argv", [game_main.__file__, "--debug"]), \
                patch.object(game_main.os.path, "isfile", return_value=True), \
                patch.object(game_main.os, "execve") as execve:
            game_main._relaunch_with_project_venv()

        executable, argv, environment = execve.call_args.args
        self.assertEqual(executable, expected_python)
        self.assertEqual(argv, [expected_python, os.path.abspath(game_main.__file__), "--debug"])
        self.assertEqual(environment["GD5_VENV_REEXEC"], "1")

    def test_packaged_build_never_relaunches(self):
        with patch.object(game_main.sys, "frozen", True, create=True), \
                patch.object(game_main.os, "execve") as execve:
            game_main._relaunch_with_project_venv()

        execve.assert_not_called()


if __name__ == "__main__":
    unittest.main()
