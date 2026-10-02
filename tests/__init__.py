"""Shared test setup, applied before importing game modules."""

import os


def configure_test_audio():
    """Send SDL audio to its silent driver, even with a local driver override."""
    os.environ["SDL_AUDIODRIVER"] = "dummy"


# Covers focused `python -m unittest tests.test_*` runs as well as discovery.
configure_test_audio()
