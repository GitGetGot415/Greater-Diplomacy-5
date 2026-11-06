"""Browser startup must not require native audio or tournament encryption."""

import asyncio
from contextlib import redirect_stderr
import io
import subprocess
import sys
import unittest
from unittest.mock import AsyncMock, Mock, patch

import main
from compilation_scripts import test_web_build


class WebStartupTests(unittest.TestCase):
    def test_startup_imports_without_native_only_dependencies(self):
        probe = r'''
import importlib.abc
import sys

class BrowserImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "wave" or fullname.split(".")[0] == "cryptography":
            raise ModuleNotFoundError("Browser does not include " + fullname)

sys.meta_path.insert(0, BrowserImports())
import main
main._import_project_modules()
'''
        result = subprocess.run(
            [sys.executable, "-c", probe], capture_output=True, text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_async_web_failure_reaches_browser_console(self):
        import platform

        window = Mock()
        with patch.object(main.sys, "platform", "emscripten"), \
                patch.object(main, "_run_game", AsyncMock(side_effect=ValueError("startup failed"))), \
                patch.object(platform, "window", window, create=True), \
                redirect_stderr(io.StringIO()) as error_output:
            asyncio.run(main._bootstrap())
        self.assertIn("ValueError: startup failed", error_output.getvalue())
        self.assertIn("ValueError: startup failed", window.console.error.call_args.args[0])
        self.assertFalse(window.pyconsole.hidden)

    def test_async_desktop_failure_still_propagates(self):
        with patch.object(main.sys, "platform", "win32"), \
                patch.object(main, "_run_game", AsyncMock(side_effect=ValueError("startup failed"))):
            with self.assertRaisesRegex(ValueError, "startup failed"):
                asyncio.run(main._bootstrap())

    def test_launcher_waits_for_http_success(self):
        process = Mock()
        process.poll.return_value = None
        response = Mock(status=200)
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        with patch.object(test_web_build, "urlopen", side_effect=[
                ConnectionRefusedError(), response]) as request, \
                patch.object(test_web_build.time, "sleep"):
            test_web_build.wait_for_server(process, "http://localhost:12345/")
        self.assertEqual(request.call_count, 2)

    def test_launcher_stops_waiting_when_pygbag_exits(self):
        process = Mock(returncode=1)
        process.poll.return_value = 1
        with patch.object(test_web_build, "urlopen") as request:
            with self.assertRaisesRegex(RuntimeError, "exit 1"):
                test_web_build.wait_for_server(process, "http://localhost:12345/")
        request.assert_not_called()

    def test_launcher_reports_startup_timeout(self):
        process = Mock()
        process.poll.return_value = None
        with patch.object(test_web_build, "urlopen", side_effect=ConnectionRefusedError()):
            with self.assertRaises(TimeoutError):
                test_web_build.wait_for_server(process, "http://localhost:12345/", timeout=0)


if __name__ == "__main__":
    unittest.main()
