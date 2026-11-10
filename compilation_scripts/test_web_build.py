"""Serve the exported web distribution and open the browser once HTTP is ready."""

from pathlib import Path
import os
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen
import webbrowser


REPO_ROOT = Path(__file__).resolve().parent.parent
# The batch/shell entry points run this file directly from compilation_scripts.
if __name__ == "__main__" and str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from compilation_scripts import build_manifest as manifest, web_server_process

SERVER_HOST = "localhost"
SERVER_PORT = 8000
SERVER_URL = f"http://{SERVER_HOST}:{SERVER_PORT}/"
STARTUP_TIMEOUT_SECONDS = 180
SERVER_RELEASE_TIMEOUT_SECONDS = 5


def wait_for_server(process, url, timeout=STARTUP_TIMEOUT_SECONDS):
    deadline = time.monotonic() + timeout
    while process.poll() is None:
        try:
            with urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except (URLError, OSError):
            pass  # The server has not opened its listener yet.
        if time.monotonic() >= deadline:
            raise TimeoutError("The web server did not start. Check the server output above.")
        time.sleep(0.25)
    raise RuntimeError(f"Web server exited before HTTP was ready (exit {process.returncode}).")


def ensure_server_port_available(replaced_server=False):
    # A terminated Windows listener may need a moment to release its socket.
    deadline = time.monotonic() + (SERVER_RELEASE_TIMEOUT_SECONDS if replaced_server else 0)
    while True:
        # Test for a listener. A plain bind also rejects TIME_WAIT connections,
        # even though Python's HTTPServer can reuse the released address.
        with socket.socket() as probe:
            probe.settimeout(0.2)
            if probe.connect_ex((SERVER_HOST, SERVER_PORT)) != 0:
                return
        if time.monotonic() >= deadline:
            raise OSError(f"Port {SERVER_PORT} already has a running server.")
        time.sleep(0.1)


def main():
    web_output = REPO_ROOT / manifest.WEB_CONTENT_DIR
    if not (web_output / "index.html").is_file():
        print("No web build found. Run compilation_scripts/html_compilation.py first.")
        return 1

    try:
        replaced_server = False
        if os.name == "nt":
            replaced_server = web_server_process.stop_previous_server(REPO_ROOT)
            if replaced_server:
                print("Stopped the previous web test server for this checkout.", flush=True)
        # A different program using this port does not belong to our server job.
        ensure_server_port_available(replaced_server)
    except OSError as exc:
        print(f"Cannot start {SERVER_URL}: {exc}")
        print("Port 8000 may belong to another program or an older launcher. That process was left running.")
        return 1

    command = [
        sys.executable, "-m", "http.server", str(SERVER_PORT),
        "--bind", SERVER_HOST, "--directory", str(web_output),
    ]
    print("Preparing the web test server. The browser opens when HTTP is ready.", flush=True)
    process = None
    try:
        process = (web_server_process.WindowsServerProcess(command, REPO_ROOT)
                   if os.name == "nt" else subprocess.Popen(command, cwd=REPO_ROOT))
        wait_for_server(process, SERVER_URL)
        webbrowser.open(SERVER_URL)
        print("Close this window or press Ctrl+C to stop the server.", flush=True)
        return process.wait()
    except (OSError, RuntimeError) as exc:
        print(exc)
        return 1
    except KeyboardInterrupt:
        return 0
    finally:
        if isinstance(process, web_server_process.WindowsServerProcess):
            process.close()
        elif process is not None and process.poll() is None:
            process.terminate()
            process.wait()


if __name__ == "__main__":
    sys.exit(main())
