"""Shared test setup, applied before importing game modules."""

import os
from concurrent.futures import ThreadPoolExecutor


def run_process_probes(check, items, *, workers=None):
    """Launch isolated process checks concurrently. Keep results in input order.

    Each check must own its child process and temporary files. Game tests and
    patches of shared state must stay on the calling thread.
    """
    if workers is None:
        workers = min(4, os.cpu_count() or 1)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(check, items))


def configure_test_audio():
    """Send SDL audio to its silent driver, even with a local driver override."""
    os.environ["SDL_AUDIODRIVER"] = "dummy"


# Covers focused `python -m unittest tests.test_*` runs as well as discovery.
configure_test_audio()
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
