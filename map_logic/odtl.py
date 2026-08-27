"""The Open Doctrines translation layer: GD5 maps out, and back again.

Greater Diplomacy 5 and Open Doctrines describe the same kind of world and
share no file format. open-dragoman converts between them -- an MIT library
with no code from either game in it -- and this module is the whole of what
the rest of GD5 needs to know about it.

WHAT CROSSES, AND WHAT DOES NOT

Provinces, borders, owners, nations with their colors and flags, alliances
and wars, the date, and events as far as the two scripting systems overlap.

The conversion is lossy in both directions, and the losses are not the same
one way as the other. Open Doctrines has fortification and port technology GD5
does not; GD5 has manpower, fuel and faction leaders Open Doctrines does not.
Neither is invented for the other. Anything the destination game has no field
for is written to a sidecar file beside the map, and both games ignore files
they do not recognise -- so a translated map loads normally in the other game
AND comes home intact if it is translated back.

Whatever could not cross is reported, per conversion, and the screen shows it.

TWO WAYS TO REACH THE LIBRARY

On desktop it is the `open-dragoman` package from requirements.txt.

On web there is no such thing: pygbag installs pure-Python wheels and its own
prebuilt WASM ones, and open-dragoman is neither. So the browser build loads
the WASM side module shipped beside the game and declares by hand the six
calls used here. Both paths end at the same C ABI in the same library, and
abi_version() is checked either way, so a mismatch is refused rather than
guessed at.
"""

import ctypes
import datetime
import json
import os
import shutil
import sys

IS_WEB = sys.platform == "emscripten"

# The ABI this module was written against. open-dragoman bumps it when an
# existing call changes meaning, so a library that answers differently is one
# this code cannot safely call.
REQUIRED_ABI = 2

# Where the WASM side module is looked for in a browser build. pygbag packs
# the project directory into its archive, so this is a path inside the game.
WASM_LIBRARY = "libdragoman.so"

# dg_format, from dragoman.h.
_FORMAT_ODMAP = 1
_FORMAT_GD5 = 2

_package = None      # the desktop path: the open-dragoman package
_lib = None          # the web path: the library itself, through ctypes
_load_error = ""


class _Options(ctypes.Structure):
    """dg_options. Six ints, and the defaults come from the library itself
    rather than being repeated here, so a new option added upstream arrives
    with whatever value that release considers sensible."""
    _fields_ = [(name, ctypes.c_int) for name in (
        "carry_sidecar", "derive_geometry", "translate_scripts",
        "strict", "reencode_images", "synthesise_ocean")]


def _declare(lib):
    """The handful of C calls this module makes."""
    lib.dg_abi_version.restype = ctypes.c_int
    lib.dg_version_string.restype = ctypes.c_char_p
    lib.dg_last_error.restype = ctypes.c_char_p
    lib.dg_options_defaults.argtypes = [ctypes.POINTER(_Options)]
    lib.dg_convert.restype = ctypes.c_int
    lib.dg_convert.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int,
                               ctypes.POINTER(_Options),
                               ctypes.POINTER(ctypes.c_void_p)]
    lib.dg_report_count.restype = ctypes.c_int
    lib.dg_report_count.argtypes = [ctypes.c_void_p]
    lib.dg_report_message.restype = ctypes.c_char_p
    lib.dg_report_message.argtypes = [ctypes.c_void_p, ctypes.c_int]
    lib.dg_report_free.argtypes = [ctypes.c_void_p]
    return lib


def _load():
    """Finds the library once, by whichever route this platform has."""
    global _package, _lib, _load_error
    if _package is not None or _lib is not None or _load_error:
        return

    if not IS_WEB:
        try:
            import dragoman
        except Exception as exc:
            _load_error = f"open-dragoman is not installed ({exc})"
            return
        try:
            if dragoman.abi_version() != REQUIRED_ABI:
                _load_error = (f"open-dragoman speaks ABI {dragoman.abi_version()}, "
                               f"this needs {REQUIRED_ABI}")
                return
        except Exception as exc:
            _load_error = f"open-dragoman would not answer: {exc}"
            return
        _package = dragoman
        return

    # Web. The .so sits beside the game inside pygbag's archive.
    #
    # BY ABSOLUTE PATH, and that is the whole of this bug. A bare soname is
    # resolved by emscripten's own loader, which looks next to the CPython
    # runtime -- on pygame-web's CDN -- and not in the game's directory at all.
    # The player saw:
    #
    #   Could not load dynamic lib: libdragoman.so
    #   .../cdn/0.9.3/cpython312/libdragoman.so: file not found
    #
    # which names a path nobody could put a file into. It worked when tried by
    # hand only because that test app's working directory happened to be the
    # one holding the library.
    tried = []
    for candidate in (os.path.join(game_root(), WASM_LIBRARY),
                      os.path.abspath(WASM_LIBRARY),
                      WASM_LIBRARY):
        if candidate in tried:
            continue
        tried.append(candidate)
        try:
            lib = _declare(ctypes.CDLL(candidate))
        except Exception:
            continue
        if lib.dg_abi_version() != REQUIRED_ABI:
            _load_error = (f"{candidate} speaks ABI {lib.dg_abi_version()}, "
                           f"this needs {REQUIRED_ABI}")
            return
        _lib = lib
        return

    # Every path, not just the last error. The library is committed to this
    # repository, so a missing one means a partial checkout or a deleted file
    # rather than a forgotten build step -- and a message naming where it was
    # expected is the difference between fixing that in a minute and guessing.
    _load_error = (WASM_LIBRARY + " was not found. Looked in: " + ", ".join(tried)
                   + ". It ships in the repository; restore it with "
                   + "map_tools/fetch_dragoman_wasm.py.")


def available():
    """Can anything here actually run?"""
    _load()
    return _package is not None or _lib is not None


def unavailable_reason():
    """Why not, in a sentence a player can act on."""
    _load()
    return _load_error


def version():
    _load()
    if _package is not None:
        return _package.library_version()
    if _lib is not None:
        return _lib.dg_version_string().decode("utf-8", "replace")
    return "unavailable"


def _convert(src, dst, fmt):
    """Returns (ok, notes). Notes are the library's own diagnostics, and a
    conversion can succeed with plenty of them -- that is the normal case,
    because the two games do not hold the same set of facts."""
    _load()
    if _package is not None:
        try:
            report = _package.convert(src, dst, fmt)
            return True, [d.message for d in report]
        except Exception as exc:
            return False, [str(exc)]

    if _lib is None:
        return False, [_load_error or "the translation layer is not available"]

    options = _Options()
    _lib.dg_options_defaults(ctypes.byref(options))
    handle = ctypes.c_void_p()
    code = _lib.dg_convert(src.encode("utf-8"), dst.encode("utf-8"),
                           _FORMAT_ODMAP if fmt == "odmap" else _FORMAT_GD5,
                           ctypes.byref(options), ctypes.byref(handle))

    notes = []
    if handle:
        for i in range(_lib.dg_report_count(handle)):
            message = _lib.dg_report_message(handle, i)
            if message:
                notes.append(message.decode("utf-8", "replace"))
        _lib.dg_report_free(handle)

    # Zero is success: it is the C convention, and reading it the other way
    # makes a finished map look like a failure.
    if code != 0:
        error = _lib.dg_last_error()
        notes.insert(0, error.decode("utf-8", "replace") if error
                     else "the conversion failed without saying why")
    return code == 0, notes


def to_odmap(map_dir, odmap_path):
    """A GD5 map directory -> an Open Doctrines .odmap."""
    return _convert(map_dir, odmap_path, "odmap")


def to_gd5(odmap_path, map_dir):
    """An Open Doctrines .odmap -> a GD5 map directory."""
    return _convert(odmap_path, map_dir, "gd5")


# ------------------------------------------------------------ finding the game
#
# Two ways, cheapest first. Neither runs on its own: the game does not look at
# what else is on somebody's disk until they press a button that says it will.

# Where a game writes down where it is -- see the locator file, documented at
# https://github.com/Pr1nted/dragoman/blob/main/docs/locator.md. Both games
# write their own on startup, so the usual case needs no searching at all.
LOCATOR_DIR_NAME = "game-locators"
OPEN_DOCTRINES_ID = "open-doctrines"
THIS_GAME_ID = "greater-diplomacy-5"
LOCATOR_FORMAT = 1


def game_root():
    """This game's own directory -- map_logic/odtl.py, two levels up."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def locator_dir():
    """The shared directory, per platform. Created only when writing."""
    if IS_WEB:
        return ""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA", "")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, LOCATOR_DIR_NAME) if base else ""


def write_locator():
    """Say where THIS game is, for whoever wants to translate into it.

    Best effort by design: a read-only or missing directory is not worth
    interrupting anybody over, and the feature works without it.
    """
    directory = locator_dir()
    if not directory:
        return False
    try:
        os.makedirs(directory, exist_ok=True)
        payload = {
            "locator": LOCATOR_FORMAT,
            "id": THIS_GAME_ID,
            "name": "Greater Diplomacy 5",
            # Where the GAME is, not where it was started from: a shortcut
            # or a shell in another folder must not make this file point at
            # somebody's home directory.
            "path": game_root(),
            "updated": datetime.datetime.now(datetime.timezone.utc)
                               .strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        with open(os.path.join(directory, THIS_GAME_ID + ".json"), "w",
                  encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
        return True
    except Exception:
        return False


def looks_like_open_doctrines(directory):
    """Does this directory hold Open Doctrines?

    Recognised by its own shipped maps: data/STDmaps with at least one .odmap
    in it. That is the folder a translated map is going to be read from, so a
    directory without it could not be translated into anyway.

    macOS keeps the game inside an .app bundle, so that layout is accepted too.
    """
    if not directory or not os.path.isdir(directory):
        return False
    for maps in (os.path.join(directory, "data", "STDmaps"),
                 os.path.join(directory, "OpenDoctrines.app", "Contents", "data", "STDmaps"),
                 os.path.join(directory, "Contents", "data", "STDmaps")):
        if os.path.isdir(maps):
            try:
                if any(n.lower().endswith(".odmap") for n in os.listdir(maps)):
                    return True
            except OSError:
                continue
    return False


def open_doctrines_from_locator():
    """The path Open Doctrines wrote down, if it still checks out.

    A locator is a claim, not a fact: the game it names may have been moved or
    deleted since. Verified before it is offered, and never deleted when it
    fails -- the file is not ours.
    """
    directory = locator_dir()
    if not directory:
        return ""
    path = os.path.join(directory, OPEN_DOCTRINES_ID + ".json")
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        return ""
    if data.get("locator") != LOCATOR_FORMAT:
        return ""
    claimed = data.get("path") or ""
    return claimed if looks_like_open_doctrines(claimed) else ""


def search_locations():
    """The places Open Doctrines is normally installed.

    Returned so the screen can say how many folders a search would read
    BEFORE it reads them. Shallow on purpose: this is somebody's home
    directory, not a haystack to be walked.
    """
    if IS_WEB:
        return []
    home = os.path.expanduser("~")
    if sys.platform == "win32":
        roots = [os.environ.get("ProgramFiles", ""), os.environ.get("ProgramFiles(x86)", ""),
                 os.environ.get("LOCALAPPDATA", ""),
                 os.path.join(home, "Documents"), os.path.join(home, "Downloads"),
                 os.path.join(home, "Games")]
    elif sys.platform == "darwin":
        roots = ["/Applications", os.path.join(home, "Applications"),
                 os.path.join(home, "Documents"), os.path.join(home, "Downloads"),
                 os.path.join(home, "Games")]
    else:
        roots = [home, os.path.join(home, "Documents"), os.path.join(home, "Downloads"),
                 os.path.join(home, "Games"), "/opt", "/usr/local/games"]
    return [r for r in roots if r]


def find_open_doctrines():
    """Every Open Doctrines found, locator first, then the usual places.

    Only subdirectories whose NAME already suggests the game are opened, which
    is the whole of the "one level deep" promise: reading a directory listing
    is the least a search can do, and walking into everything it finds is not
    something to do to somebody's home folder.
    """
    found = []
    claimed = open_doctrines_from_locator()
    if claimed:
        found.append(claimed)

    for root in search_locations():
        if looks_like_open_doctrines(root):
            found.append(root)
            continue
        try:
            names = sorted(os.listdir(root))
        except OSError:
            continue
        for name in names:
            lowered = name.lower()
            if "doctrine" not in lowered and "opendoctrines" not in lowered:
                continue
            child = os.path.join(root, name)
            if looks_like_open_doctrines(child):
                found.append(child)

    seen, unique = set(), []
    for path in found:
        if path not in seen:
            seen.add(path)
            unique.append(path)
    return unique


def open_doctrines_maps_dir(directory):
    """Where a translated map belongs inside an Open Doctrines install, or ""
    if that is not one. Custom maps, not the shipped ones: a translated world
    is the player's, and shipped maps are the game's."""
    if not looks_like_open_doctrines(directory):
        return ""
    for data in (os.path.join(directory, "data"),
                 os.path.join(directory, "OpenDoctrines.app", "Contents", "data"),
                 os.path.join(directory, "Contents", "data")):
        if os.path.isdir(os.path.join(data, "STDmaps")):
            return os.path.join(data, "custom_maps")
    return ""


# ------------------------------------------------------------ the browser
#
# A browser has no folders. It will hand a page a FILE the player picked, and
# it will accept a file the page hands back, and that is the whole of the
# vocabulary -- which is why the desktop screen's "choose a folder" has no web
# equivalent and why, without these two, a translated map on the web is written
# into a virtual filesystem the player cannot reach.

def _js():
    """pygbag's handle on the real browser window, or None off the web."""
    if not IS_WEB:
        return None
    try:
        from platform import window
        return window
    except Exception:
        return None


def offer_download(path, suggested_name):
    """Hand a finished file to the browser as a download.

    The bytes do not cross into JavaScript. Python and the page share one
    emscripten filesystem, so what crosses is the path -- a few dozen
    characters -- and the page reads the file itself.

    That is not a micro-optimisation. The first version of this base64-encoded
    the whole map into the eval string, so every translation pushed one to two
    megabytes of text through the Python-to-JavaScript bridge in a single
    synchronous call, on the frame the player pressed the button. The
    conversion that produces the map takes about two seconds for the largest
    one shipped; the browser stopped answering for minutes.
    """
    window = _js()
    if window is None:
        return False
    if not os.path.isfile(path):
        return False

    safe = "".join(c for c in suggested_name if c.isalnum() or c in "._- ")
    try:
        window.eval(
            "(function(p,name){"
            "var buf=FS.readFile(p);"
            "var u=URL.createObjectURL(new Blob([buf],{type:'application/octet-stream'}));"
            "var a=document.createElement('a');a.href=u;a.download=name;"
            "document.body.appendChild(a);a.click();document.body.removeChild(a);"
            # Revoked on a timer rather than immediately: a browser that has not
            # started reading the blob yet cancels the download if the URL goes
            # away underneath it.
            "setTimeout(function(){URL.revokeObjectURL(u)},60000);"
            "})(" + json.dumps(path) + "," + json.dumps(safe) + ")")
        return True
    except Exception:
        return False


# Where the page drops a file the player picked. Python reads it from here, so
# the bytes never travel as a string.
_UPLOAD_DIR = "/tmp/gd5_upload"


def ask_for_upload():
    """Open the browser's file picker for a .odmap.

    Returns immediately -- the player has not chosen anything yet. The bytes
    arrive later, and take_upload() below is how a screen collects them. That
    split is not a style choice: a browser will not block on a file dialog, so
    there is no version of this that can return a path.
    """
    window = _js()
    if window is None:
        return False
    try:
        window.eval(
            "(function(dir){"
            "window.__gd5_upload=null;"
            "var i=document.createElement('input');i.type='file';i.accept='.odmap';"
            "i.onchange=function(){"
            "var f=i.files[0];if(!f)return;"
            "var r=new FileReader();"
            "r.onload=function(){"
            "try{FS.mkdir(dir)}catch(e){}"
            # The page names the file; Python only ever sees a basename it
            # re-checks, and the character class here is the same one the
            # download side allows.
            "var name=f.name.replace(/[^A-Za-z0-9._ -]/g,'_');"
            "FS.writeFile(dir+'/'+name,new Uint8Array(r.result));"
            "window.__gd5_upload=name;"
            "};"
            "r.readAsArrayBuffer(f);"
            "};"
            "i.click();"
            "})(" + json.dumps(_UPLOAD_DIR) + ")")
        return True
    except Exception:
        return False


def take_upload(into_dir):
    """Collect a file the player picked, if one has finished arriving.

    Called once a frame by the screen, which is why what crosses the bridge
    here is a filename and not a file: this runs sixty times a second for as
    long as the Translate screen is open, whether or not anybody ever pressed
    the import button.
    """
    window = _js()
    if window is None:
        return ""
    try:
        pending = window.eval("window.__gd5_upload || ''")
    except Exception:
        return ""
    name = os.path.basename(str(pending or ""))
    if not name:
        return ""
    try:
        window.eval("window.__gd5_upload=null")
    except Exception:
        pass

    source = os.path.join(_UPLOAD_DIR, name)
    if not name.lower().endswith(".odmap"):
        name += ".odmap"
    os.makedirs(into_dir, exist_ok=True)
    destination = os.path.join(into_dir, name)
    try:
        with open(source, "rb") as incoming, open(destination, "wb") as handle:
            shutil.copyfileobj(incoming, handle)
    except OSError:
        return ""
    try:
        os.remove(source)
    except OSError:
        pass
    return destination if looks_like_odmap(destination) else ""


def looks_like_odmap(path):
    """A .odmap is a zip. Checked by extension and by the two bytes every zip
    starts with, so a renamed file is not offered as one."""
    if not path.lower().endswith(".odmap") or not os.path.isfile(path):
        return False
    try:
        with open(path, "rb") as handle:
            return handle.read(2) == b"PK"
    except OSError:
        return False
