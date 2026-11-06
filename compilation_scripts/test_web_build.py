"""Run pygbag's test server and open the browser once HTTP is ready."""

from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen
import webbrowser


REPO_ROOT = Path(__file__).resolve().parent.parent
SERVER_HOST = "localhost"
SERVER_PORT = 8000
SERVER_URL = f"http://{SERVER_HOST}:{SERVER_PORT}/"
STARTUP_TIMEOUT_SECONDS = 180


def wait_for_server(process, url, timeout=STARTUP_TIMEOUT_SECONDS):
    deadline = time.monotonic() + timeout
    while process.poll() is None:
        try:
            with urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except (URLError, OSError):
            pass  # Packing and CDN caching finish before pygbag serves HTTP.
        if time.monotonic() >= deadline:
            raise TimeoutError("The web server did not start. Check the pygbag output above.")
        time.sleep(0.25)
    raise RuntimeError(f"Pygbag exited before the web server was ready (exit {process.returncode}).")


def main():
    if not (REPO_ROOT / "web_stage/build/web/index.html").is_file():
        print("No web build found. Run compilation_scripts/html_compilation.py first.")
        return 1

    # Do not open an old server's page or terminate another program using this port.
    try:
        with socket.socket() as probe:
            probe.bind((SERVER_HOST, SERVER_PORT))
    except OSError as exc:
        print(f"Cannot start {SERVER_URL}: {exc}")
        print("Close the previous web server window, then run this script again.")
        return 1

    command = [
        sys.executable, "-m", "pygbag",
        "--app_name", "Greater Diplomacy 5",
        "--disable-sound-format-error", "--ume_block", "0",
        # Match the build template, including the canvas aspect ratio.
        "--template", "compilation_scripts/web_index.tmpl", "web_stage",
    ]
    print("Preparing the web test server. The browser opens when HTTP is ready.", flush=True)
    process = subprocess.Popen(command, cwd=REPO_ROOT)
    try:
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
        if process.poll() is None:
            process.terminate()
            process.wait()


if __name__ == "__main__":
    sys.exit(main())
