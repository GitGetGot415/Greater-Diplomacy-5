"""Exercise real Windows server trees, including forced launcher termination."""

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from compilation_scripts import test_web_build, web_server_process


# The child writes its listening port only after bind/listen has succeeded.
LISTENER = """
import json, os, socket, sys, time
from pathlib import Path
with socket.socket() as listener:
    listener.bind(('127.0.0.1', 0))
    listener.listen()
    Path(sys.argv[1]).write_text(json.dumps({'pid': os.getpid(), 'port': listener.getsockname()[1]}))
    time.sleep(60)
"""
PARENT = """
import subprocess, sys, time
from pathlib import Path
subprocess.Popen([sys.executable, '-c', sys.argv[2], sys.argv[1]])
while not Path(sys.argv[1]).exists():
    time.sleep(.01)
if len(sys.argv) < 4:
    time.sleep(60)
"""


class WebServerPortTests(unittest.TestCase):
    def test_unrelated_listener_is_preserved(self):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            listener.listen()
            port = listener.getsockname()[1]
            with patch.object(test_web_build, 'SERVER_HOST', '127.0.0.1'), \
                    patch.object(test_web_build, 'SERVER_PORT', port):
                with self.assertRaisesRegex(OSError, 'running server'):
                    test_web_build.ensure_server_port_available()
            with socket.create_connection(('127.0.0.1', port), timeout=1):
                pass

    def test_check_does_not_bind_time_wait_addresses(self):
        with patch.object(test_web_build.socket, 'socket') as factory:
            probe = factory.return_value.__enter__.return_value
            probe.connect_ex.return_value = 10061  # Windows connection refused.
            test_web_build.ensure_server_port_available()
            probe.bind.assert_not_called()


@unittest.skipUnless(os.name == 'nt', 'Windows job object lifecycle')
class WindowsWebServerProcessTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='gd5-server-test-')
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.info_path = self.root / 'listener-info'

    def wait_for_info(self):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if self.info_path.is_file():
                try:
                    return json.loads(self.info_path.read_text())
                except json.JSONDecodeError:
                    pass  # The child may still be completing its ready record.
            time.sleep(.02)
        self.fail('The child listener never became ready.')

    def assert_listener_stopped(self, port):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            with socket.socket() as probe:
                probe.settimeout(.1)
                if probe.connect_ex(('127.0.0.1', port)) != 0:
                    return
            time.sleep(.02)
        self.fail(f'Server child is still listening on port {port}.')

    def start_tree(self, *, parent_exits=False):
        command = [sys.executable, '-c', PARENT, str(self.info_path), LISTENER]
        if parent_exits:
            command.append('exit')
        process = web_server_process.WindowsServerProcess(command, self.root)
        self.addCleanup(process.close)
        return process

    def test_normal_close_stops_grandchild_listener(self):
        process = self.start_tree()
        info = self.wait_for_info()
        process.close()
        self.assert_listener_stopped(info['port'])

    def test_cleanup_stops_children_even_when_direct_process_already_exited(self):
        process = self.start_tree(parent_exits=True)
        info = self.wait_for_info()
        self.assertEqual(process.wait(), 0)
        process.close()
        self.assert_listener_stopped(info['port'])

    def test_relaunch_replaces_only_its_own_checkout_job(self):
        process = self.start_tree()
        info = self.wait_for_info()
        other_root = self.root / 'other-checkout'
        self.assertFalse(web_server_process.stop_previous_server(other_root))
        with socket.create_connection(('127.0.0.1', info['port']), timeout=1):
            pass
        self.assertTrue(web_server_process.stop_previous_server(self.root))
        process.wait()
        self.assert_listener_stopped(info['port'])

    def test_forced_owner_exit_stops_server_tree_without_finally(self):
        # Use base Python for the owner so kill() reaches the actual job owner.
        # The server tree still uses the venv and includes its redirectors.
        code = """
import sys, time
from compilation_scripts.web_server_process import WindowsServerProcess
process = WindowsServerProcess([sys.argv[5], '-c', sys.argv[3], sys.argv[1], sys.argv[4]], sys.argv[2])
time.sleep(60)
"""
        owner = subprocess.Popen(
            [sys._base_executable, '-c', code, str(self.info_path), str(self.root),
             PARENT, LISTENER, sys.executable],
            cwd=Path(__file__).resolve().parent.parent,
        )
        self.addCleanup(owner.wait, timeout=10)
        self.addCleanup(owner.kill)
        self.addCleanup(web_server_process.stop_previous_server, self.root)
        info = self.wait_for_info()
        owner.kill()
        owner.wait(timeout=10)
        self.assert_listener_stopped(info['port'])


if __name__ == '__main__':
    unittest.main()
