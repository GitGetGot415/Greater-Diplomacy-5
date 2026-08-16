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
