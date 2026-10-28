"""Read and write the turn history used by the timeline.

Disk history uses compact JSON and compares two compressed representations.
The writer stores full snapshots or snapshot changes, whichever is smaller.
Reading restores independent full snapshots for all existing callers.
Legacy full snapshots remain supported in plain and compressed files.
Use read for history files. It prefers the compressed file.
Buffered text writes avoid json.dump's many small writes.
"""

import copy
from contextlib import ExitStack
import gzip
import json
import os
import tempfile

import data.constants as c

#: The compressed form is written; the plain form is only ever read, for saves
#: made before compression existed.
GZ_NAME = "history.json.gz"
PLAIN_NAME = "history.json"
DELTA_FORMAT = "gd5-history-delta-v1"


def dump_text(obj, indent=None):
    """Serialize in one buffered write rather than json.dump's many small ones."""
    return json.dumps(obj, indent=indent)


def dump_compact_text(obj):
    """Serialize JSON without indentation or optional whitespace."""
    return json.dumps(obj, separators=(",", ":"))


def _snapshot_delta(previous, current):
    """Return changed JSON values, with None for an unchanged value."""
    if type(previous) is not type(current):
        return ["set", current]
    if isinstance(current, dict):
        removed = [str(key) for key in previous if key not in current]
        changes = {}
        for key, value in current.items():
            delta = (_snapshot_delta(previous[key], value) if key in previous
                     else ["set", value])
            if delta is not None:
                changes[str(key)] = delta
        # Country order can affect turn processing. Preserve reordered keys.
        expected_order = [key for key in previous if key in current]
        expected_order.extend(key for key in current if key not in previous)
        order = [str(key) for key in current] if expected_order != list(current) else None
        if removed or changes or order is not None:
            return ["dict", removed, changes, order]
        return None
    if isinstance(current, (list, tuple)):
        changes = {}
        for index, value in enumerate(current):
            delta = (_snapshot_delta(previous[index], value) if index < len(previous)
                     else ["set", value])
            if delta is not None:
                changes[str(index)] = delta
        if changes or len(previous) != len(current):
            return ["list", len(current), changes]
        return None
    return None if previous == current else ["set", current]


def _restore_delta(previous, delta):
    """Restore a snapshot without changing its predecessor."""
    if delta is None:
        return previous
    if not isinstance(delta, list) or not delta:
        raise ValueError("invalid history delta")
    operation = delta[0]
    if operation == "set" and len(delta) == 2:
        return delta[1]
    if operation == "dict" and len(delta) == 4 and isinstance(previous, dict):
        removed, changes, order = delta[1:]
        if (not isinstance(removed, list) or not all(isinstance(key, str) for key in removed)
                or not isinstance(changes, dict)):
            raise ValueError("invalid history dictionary delta")
        removed = set(removed)
        result = {key: value for key, value in previous.items() if key not in removed}
        for key, change in changes.items():
            result[key] = _restore_delta(result.get(key), change)
        if order is not None:
            if (not isinstance(order, list) or not all(isinstance(key, str) for key in order)
                    or len(order) != len(result) or set(order) != set(result)):
                raise ValueError("invalid history dictionary order")
            result = {key: result[key] for key in order}
        return result
    if operation == "list" and len(delta) == 3 and isinstance(previous, list):
        length, changes = delta[1:]
        if type(length) is not int or length < 0 or not isinstance(changes, dict):
            raise ValueError("invalid history list delta")
        if any(str(index) not in changes for index in range(len(previous), length)):
            raise ValueError("missing history list entries")
        result = previous[:length] + [None] * max(0, length - len(previous))
        for key, change in changes.items():
            if not key.isdecimal() or not 0 <= int(key) < length:
                raise ValueError("invalid history list index")
            index = int(key)
            result[index] = _restore_delta(result[index], change)
        return result
    raise ValueError("invalid history delta operation")


def encode_history(history):
    """Store one initial snapshot and the changes for each later turn."""
    previous = None
    turns = []
    for turn, snapshot in history.items():
        turns.append([str(turn), _snapshot_delta(previous, snapshot)])
        previous = snapshot
    return {"_history_format": DELTA_FORMAT, "turns": turns}


def decode_history(payload):
    """Read the delta format or legacy full snapshots."""
    if not isinstance(payload, dict):
        raise ValueError("history root must be an object")
    if "_history_format" not in payload:
        return payload
    if payload["_history_format"] != DELTA_FORMAT or not isinstance(payload.get("turns"), list):
        raise ValueError("unsupported history format")
    history = {}
    previous = None
    for entry in payload["turns"]:
        if (not isinstance(entry, list) or len(entry) != 2
                or not isinstance(entry[0], str) or entry[0] in history):
            raise ValueError("invalid history turn entry")
        turn, delta = entry
        snapshot = _restore_delta(previous, delta)
        if not isinstance(snapshot, dict):
            raise ValueError("history snapshot must be an object")
        # Timeline edits or save migrations must not change another turn.
        previous = history[turn] = copy.deepcopy(snapshot)
    return history


def _write_compressed_history(save_path, history):
    """Compare compressed full snapshots and deltas before replacing the file.

    Serialize one turn at a time. Indented patches can expand large histories.
    Comparing actual compressed sizes also handles histories with many changes.
    Temporary files keep the existing history intact if serialization fails.
    """
    target = os.path.join(save_path, GZ_NAME)
    temporary_paths = []
    try:
        with ExitStack() as stack:
            streams = []
            for _ in range(2):
                descriptor, path = tempfile.mkstemp(prefix=".history-", suffix=".gz", dir=save_path)
                temporary_paths.append(path)
                raw = stack.enter_context(os.fdopen(descriptor, "wb"))
                streams.append(stack.enter_context(gzip.GzipFile(
                    filename="", mode="wb", fileobj=raw,
                    compresslevel=c.HISTORY_GZIP_LEVEL, mtime=0)))
            full, deltas = streams
            full.write(b'{')
            deltas.write(('{"_history_format":' + dump_compact_text(DELTA_FORMAT)
                          + ',"turns":[').encode('utf-8'))
            previous = None
            for index, (turn, snapshot) in enumerate(history.items()):
                if index:
                    full.write(b',')
                    deltas.write(b',')
                full.write((dump_compact_text(str(turn)) + ':'
                            + dump_compact_text(snapshot)).encode('utf-8'))
                deltas.write(dump_compact_text(
                    [str(turn), _snapshot_delta(previous, snapshot)]).encode('utf-8'))
                previous = snapshot
            full.write(b'}')
            deltas.write(b']}')
        smallest = min(temporary_paths, key=os.path.getsize)
        os.replace(smallest, target)
    finally:
        for path in temporary_paths:
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
    return target


def write(save_path, history, compress=True):
    """Writes the history into `save_path`, returning the file actually written.

    Removes the other form so a folder never holds a stale plain history beside
    a fresh compressed one -- `read` prefers the compressed file, and a leftover
    would otherwise sit there confusing anyone looking at the folder. Empty
    history has no timeline to preserve, so it is represented by no file.
    """
    if not history:
        for filename in (GZ_NAME, PLAIN_NAME):
            try:
                os.remove(os.path.join(save_path, filename))
            except FileNotFoundError:
                pass
        return None

    if compress:
        target = _write_compressed_history(save_path, history)
        stale = os.path.join(save_path, PLAIN_NAME)
    else:
        payload = dump_text(encode_history(history), indent=c.HISTORY_INDENT)
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
                         (plain_path, lambda p: open(p, "r", encoding="utf-8"))):
        if not os.path.exists(path):
            continue
        try:
            with opener(path) as f:
                payload = json.load(f)
            return decode_history(payload)
        except (OSError, EOFError, UnicodeError, ValueError) as e:
            print(f"Error loading {os.path.basename(path)}: {e}")
            # A partially written compressed file should not hide a valid
            # legacy history.json beside it.  Try the next supported format.
            continue

    return {}
