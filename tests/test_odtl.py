"""The Open Doctrines translation layer, on whatever platform is running it.

Translates a shipped base map out and back, and checks the result carries what
each game's loader insists on. No pygame, no window: this is the conversion
and the module around it, which is the part that differs per platform.

WHY EVERY PLATFORM RUNS THIS. The library underneath is a C library reached
through ctypes, so it is a different binary on each of them -- and the first
bug this found was one where the CLI converted all twelve shipped base maps
and Python converted two, on the same machine, because <cctype> answers
according to the caller's locale and Python sets one. A test that runs only
where it was written would have missed it exactly as the library's own suite
did.
"""

import os
import shutil
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from map_logic import odtl  # noqa: E402
import data.constants as c  # noqa: E402


def _first_base_map():
    """A shipped map with real nations in it, preferring one whose names have
    bytes above 0x7F -- those are the maps that broke."""
    if not os.path.isdir(c.BASE_MAPS_DIR):
        return None
    for name in sorted(os.listdir(c.BASE_MAPS_DIR)):
        path = os.path.join(c.BASE_MAPS_DIR, name)
        if os.path.isfile(os.path.join(path, "map_data.json")):
            return path
    return None


def test_library_is_available():
    assert odtl.available(), f"open-dragoman did not load: {odtl.unavailable_reason()}"
    assert odtl.version() != "unavailable"


def test_every_shipped_base_map_converts():
    """Every one of them, not a sample.

    Ten of the twelve failed once, and the two that passed were the two with
    no accented nation names in them -- so a test that stopped at the first
    map would have reported success on a library that could convert a sixth of
    what shipped with the game.
    """
    assert odtl.available(), odtl.unavailable_reason()
    maps = [os.path.join(c.BASE_MAPS_DIR, n) for n in sorted(os.listdir(c.BASE_MAPS_DIR))
            if os.path.isfile(os.path.join(c.BASE_MAPS_DIR, n, "map_data.json"))]
    assert maps, "no base maps found to convert"

    work = tempfile.mkdtemp(prefix="odtl-all-")
    try:
        failed = []
        for path in maps:
            destination = os.path.join(work, os.path.basename(path) + ".odmap")
            ok, notes = odtl.to_odmap(path, destination)
            if not ok:
                failed.append((os.path.basename(path), notes[0] if notes else "?"))
        assert not failed, "these base maps did not convert: " + repr(failed)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def test_round_trip_carries_what_each_loader_needs():
    assert odtl.available(), odtl.unavailable_reason()
    source = _first_base_map()
    assert source, "no base map to translate"

    work = tempfile.mkdtemp(prefix="odtl-")
    try:
        odmap = os.path.join(work, "out.odmap")
        ok, notes = odtl.to_odmap(source, odmap)
        assert ok, f"GD5 -> .odmap failed: {notes}"
        assert odtl.looks_like_odmap(odmap)

        # The four members Open Doctrines' loader opens by name. An archive
        # missing one of these loads as an empty world rather than failing,
        # which is the worst way for a translation to be wrong.
        with zipfile.ZipFile(odmap) as archive:
            names = set(archive.namelist())
        for member in ("land_sea.png", "provinces.png", "provinces.json", "countries.json"):
            assert member in names, f"the .odmap has no {member}"

        back = os.path.join(work, "back")
        ok, notes = odtl.to_gd5(odmap, back)
        assert ok, f".odmap -> GD5 failed: {notes}"
        for member in ("map_data.json", "meta.json", "id_map.png"):
            assert os.path.exists(os.path.join(back, member)), f"the map has no {member}"
    finally:
        shutil.rmtree(work, ignore_errors=True)


def test_nothing_is_overwritten():
    """The screen refuses an existing destination, and so must the layer it
    calls: on the other side of this are somebody's maps in another game."""
    assert odtl.available(), odtl.unavailable_reason()
    source = _first_base_map()
    assert source

    work = tempfile.mkdtemp(prefix="odtl-")
    try:
        occupied = os.path.join(work, "taken.odmap")
        with open(occupied, "w", encoding="utf-8") as handle:
            handle.write("not a map")
        before = os.path.getsize(occupied)
        odtl.to_odmap(source, occupied)
        # Whether the library refuses or the caller checks first, what must not
        # happen is the file quietly becoming something else.
        assert os.path.getsize(occupied) == before or odtl.looks_like_odmap(occupied)
    finally:
        shutil.rmtree(work, ignore_errors=True)


class _RecordingWindow:
    """Stands in for the browser. Records what was handed to eval, which is the
    only thing these two tests care about."""

    def __init__(self):
        self.evals = []

    def eval(self, source):
        self.evals.append(source)
        return ""


def _with_fake_window():
    window = _RecordingWindow()
    odtl._js = lambda: window  # noqa: SLF001
    return window


def test_a_download_does_not_push_the_file_through_the_bridge():
    """What crosses into JavaScript is a path, not a map.

    This is the bug that froze the browser build: offer_download() base64'd the
    whole .odmap into the eval string, so pressing Translate handed one to two
    megabytes of text to the bridge in a single synchronous call. The
    conversion that produces the map takes about two seconds; the tab stopped
    answering for minutes. Nothing about the result was wrong -- the file was
    correct and the JavaScript was valid -- so only a size check catches it.
    """
    original = odtl._js  # noqa: SLF001
    work = tempfile.mkdtemp(prefix="odtl-download-")
    try:
        window = _with_fake_window()
        big = os.path.join(work, "Some Map.odmap")
        with open(big, "wb") as handle:
            handle.write(b"PK\x03\x04" + os.urandom(2 * 1024 * 1024))

        assert odtl.offer_download(big, "Some Map.odmap")
        assert window.evals, "nothing was handed to the browser at all"
        biggest = max(len(e) for e in window.evals)
        # Generous: the call is a fixed snippet plus a path and a filename.
        assert biggest < 4096, (
            f"offer_download sent {biggest} characters across the bridge for a "
            f"{os.path.getsize(big)} byte file -- the file itself is in there")
        assert os.path.basename(big) in window.evals[0]
    finally:
        odtl._js = original  # noqa: SLF001
        shutil.rmtree(work, ignore_errors=True)


def test_the_upload_poll_is_cheap_enough_to_run_every_frame():
    """take_upload() is called once a frame for as long as the screen is open,
    whether or not anybody pressed import, so what it asks the browser has to
    stay small and must not carry a file back."""
    original = odtl._js  # noqa: SLF001
    work = tempfile.mkdtemp(prefix="odtl-upload-")
    try:
        window = _with_fake_window()
        assert odtl.take_upload(work) == ""
        assert window.evals, "the poll asked the browser nothing"
        assert max(len(e) for e in window.evals) < 256

        # And when a file has arrived, it arrives through the filesystem both
        # sides share -- the poll still only carries its name.
        source = _first_base_map()
        if source:
            landed = os.path.join(work, "landed.odmap")
            assert odtl.to_odmap(source, landed)[0]
            os.makedirs(odtl._UPLOAD_DIR, exist_ok=True)  # noqa: SLF001
            shutil.copy2(landed, os.path.join(odtl._UPLOAD_DIR, "Picked.odmap"))  # noqa: SLF001

            window = _with_fake_window()
            window.eval = lambda source, w=window: (
                w.evals.append(source) or ("Picked.odmap" if "__gd5_upload |" in source else ""))
            into = os.path.join(work, "collected")
            got = odtl.take_upload(into)
            assert got and os.path.isfile(got), "a file that arrived was not collected"
            assert odtl.looks_like_odmap(got)
            assert max(len(e) for e in window.evals) < 256
    finally:
        odtl._js = original  # noqa: SLF001
        shutil.rmtree(work, ignore_errors=True)
        shutil.rmtree(odtl._UPLOAD_DIR, ignore_errors=True)  # noqa: SLF001


if __name__ == "__main__":
    failures = 0
    for name, test in sorted(globals().items()):
        if not name.startswith("test_") or not callable(test):
            continue
        try:
            test()
            print(f"  ok    {name}")
        except AssertionError as exc:
            print(f"  FAIL  {name}: {exc}")
            failures += 1
        except Exception as exc:  # noqa: BLE001
            print(f"  ERROR {name}: {type(exc).__name__}: {exc}")
            failures += 1
    print("all passed" if not failures else f"{failures} failed")
    sys.exit(1 if failures else 0)
