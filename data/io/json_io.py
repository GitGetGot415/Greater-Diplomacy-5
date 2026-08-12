"""The two JSON chores the offline data tools and the generator both do.

`data/json/*.json` is hand-readable on purpose: one entry per line, with each
entry's own dict kept tight on that line. The generator and the tkinter unit
editor each wrote that formatting out separately -- the generator's own comment
said "same style as the tkinter unit editor's custom_json_dump" -- and the two
editors each had their own "read it or fall back to {}" loader, with different
error handling, so one of them raised on a corrupt file and the other didn't.

Kept stdlib-only and dependency-free so the standalone tools in data/editors
and data/generators can import it without pulling the game in behind them.
"""
import json
import os


def dump_compact(value):
    """One entry's value, on a single line: tight ', ' / ': ' separators."""
    return json.dumps(value, separators=(', ', ': '))


def load_json_or_empty(path):
    """A JSON file's contents, or {} if it is missing or unreadable.

    Unreadable counts as empty rather than fatal: these are editors, and being
    able to open one on a half-written file is how you fix it.
    """
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}
