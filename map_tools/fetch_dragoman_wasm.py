"""Fetch the WebAssembly build of open-dragoman, for the browser version.

    python map_tools/fetch_dragoman_wasm.py

Desktop installs open-dragoman from requirements.txt like any other
dependency. The browser cannot: pygbag serves pure-Python wheels and its own
prebuilt WASM ones, and open-dragoman is a ctypes library, which is neither.

What a browser CAN do is load a WebAssembly side module sitting beside the
game -- pygbag's CPython opens it with ctypes and calls straight into it. So
the web build needs one file, `libdragoman.so`, next to main.py, and this
fetches it from the same release the pinned version in requirements.txt comes
from.

YOU DO NOT NORMALLY NEED TO RUN THIS. `libdragoman.so` is committed to the
repository, so a fresh clone can build for the web with plain `pygbag main.py`
and get a working Translate screen. It was not always so: the file used to be
fetched and gitignored, which meant anybody who cloned the repository and built
by hand got a browser build whose translation silently could not work.

Run it when the pinned version in requirements.txt changes -- Dependabot raises
that pin on its own -- to bring the committed binary back in step:

    rm libdragoman.so && python map_tools/fetch_dragoman_wasm.py

CI fails if the two disagree, so this is not something that can be forgotten
quietly.

The version is read from requirements.txt rather than written here, so the
library the browser loads and the one desktop installs cannot drift apart --
including the choice of whether to pin at all. An exact `==` fetches that
release; a looser specifier fetches the newest one.
"""

import hashlib
import os
import re
import sys
import urllib.request

VERSIONED_URL = ("https://github.com/Pr1nted/dragoman/releases/download/"
                 "v{version}/libdragoman.so")
# GitHub serves this redirect for whatever the newest release is, so tracking
# needs no API call and no token.
LATEST_URL = "https://github.com/Pr1nted/dragoman/releases/latest/download/libdragoman.so"
DESTINATION = "libdragoman.so"
REQUIREMENTS = "requirements.txt"


def wanted_release():
    """Which release to fetch, taken from requirements.txt.

    Returns (url, description). An exact pin fetches that exact release, so
    the browser build and the desktop build are the same library. Any looser
    specifier -- ~=, >=, or no version at all -- fetches the newest release
    instead, which is what tracking means.

    The point is that this file never has to be edited to change the policy:
    the answer lives in requirements.txt, next to the desktop dependency, and
    the two cannot disagree about which library the game uses.
    """
    try:
        with open(REQUIREMENTS, encoding="utf-8") as handle:
            text = handle.read()
    except OSError as exc:
        raise SystemExit(f"cannot read {REQUIREMENTS}: {exc}")

    exact = re.search(r"^open-dragoman==([0-9]+\.[0-9]+\.[0-9]+)\s*$", text, re.MULTILINE)
    if exact:
        return VERSIONED_URL.format(version=exact.group(1)), exact.group(1)

    if re.search(r"^open-dragoman\b", text, re.MULTILINE):
        return LATEST_URL, "the latest release"

    raise SystemExit(f"{REQUIREMENTS} does not mention open-dragoman at all")


def main():
    url, description = wanted_release()

    if os.path.exists(DESTINATION):
        print(f"{DESTINATION} is already here; delete it to fetch again")
        return 0

    print(f"fetching open-dragoman {description} for WebAssembly")
    print(f"  {url}")
    try:
        with urllib.request.urlopen(url) as response:
            data = response.read()
    except Exception as exc:
        raise SystemExit(f"could not fetch it: {exc}")

    # A repository that has moved, a release that was never published, or a
    # proxy serving an error page all arrive as bytes. A WebAssembly module
    # starts with \0asm, so anything else is not one and is not written out
    # under a name the game will later try to dlopen.
    if data[:4] != b"\0asm":
        raise SystemExit(f"that is not a WebAssembly module ({len(data)} bytes, "
                         f"starts {data[:16]!r})")

    with open(DESTINATION, "wb") as handle:
        handle.write(data)
    digest = hashlib.sha256(data).hexdigest()
    print(f"wrote {DESTINATION} ({len(data)} bytes, sha256 {digest[:16]}...)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
