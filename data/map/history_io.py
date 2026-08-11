"""Reading and writing the per-turn history that backs the timeline.

History is by far the largest thing a save contains -- a full nation_data and
province snapshot per turn, so a long game writes hundreds of megabytes of
extremely repetitive JSON. Two things matter here and both were measured on a
130-turn, 752-nation save:

  * `json.dump(obj, f)` writes through the text-IO layer in many small chunks
    and cost 12.9s where `f.write(json.dumps(obj))` cost 2.0s. Same bytes,
    same module, 6.5x apart -- so every history write goes through
    `_dump_text` rather than json.dump.
  * The snapshots compress about 13x (373MB -> 29MB) for 1.0s of gzip at
    level 1, which is cheaper than writing the extra 344MB.

Old saves hold a plain `history.json` and must keep loading forever, so
`read` looks for the compressed file first and falls back. Nothing else in the
codebase should open a history file directly.
"""

import gzip
import json
import os

import data.constants as c

#: The compressed form is written; the plain form is only ever read, for saves
#: made before compression existed.
GZ_NAME = "history.json.gz"
PLAIN_NAME = "history.json"


def dump_text(obj, indent=None):
    """Serialize in one buffered write rather than json.dump's many small ones."""
    return json.dumps(obj, indent=indent)


def write(save_path, history, compress=True):
    """Writes the history into `save_path`, returning the file actually written.

    Removes the other form so a folder never holds a stale plain history beside
    a fresh compressed one -- `read` prefers the compressed file, and a leftover
    would otherwise sit there confusing anyone looking at the folder.
    """
    payload = dump_text(history, indent=c.HISTORY_INDENT)

    if compress:
        target, stale = os.path.join(save_path, GZ_NAME), os.path.join(save_path, PLAIN_NAME)
        with gzip.open(target, "wt", encoding="utf-8",
                       compresslevel=c.HISTORY_GZIP_LEVEL) as f:
            f.write(payload)
    else:
        target, stale = os.path.join(save_path, PLAIN_NAME), os.path.join(save_path, GZ_NAME)
        with open(target, "w") as f:
            f.write(payload)

    if os.path.exists(stale):
        try:
            os.remove(stale)
        except OSError:
            pass  # A stale file is untidy, not a failed save.

    return target


def read(load_path):
    """Loads a history from `load_path`, compressed or not. {} if there is none.

    A corrupt or unreadable history costs the timeline, not the save, so this
    reports and returns empty rather than raising into the load path.
    """
    gz_path = os.path.join(load_path, GZ_NAME)
    plain_path = os.path.join(load_path, PLAIN_NAME)

    for path, opener in ((gz_path, lambda p: gzip.open(p, "rt", encoding="utf-8")),
                         (plain_path, lambda p: open(p, "r"))):
        if not os.path.exists(path):
            continue
        try:
            with opener(path) as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading {os.path.basename(path)}: {e}")
            return {}

    return {}
