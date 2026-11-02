"""Shared test setup, applied before importing game modules."""

import os
import re
from concurrent.futures import ThreadPoolExecutor


def add_test_cases(case_type, check, cases):
    """Expose each named content item as a normal unittest method.

    Set parallel_cases on a class only when each method can run independently.
    Shared class and module fixtures must also support separate processes.
    """
    for index, (label, value) in enumerate(cases):
        name = f"test_{check.__name__}_{index:03d}_{re.sub(r'[^a-zA-Z0-9]+', '_', str(label))}"

        def test(self, value=value):
            check(self, value)

        test.__name__ = name
        test.__qualname__ = f"{case_type.__qualname__}.{name}"
        test.__doc__ = str(label)
        setattr(case_type, name, test)


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
