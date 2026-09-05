"""JSON chores shared by offline data tools and data generators.

`data/json/*.json` is hand-readable on purpose: one entry per line, with each
entry's own dict kept tight on that line. The tkinter unit editor writes
through the same renderer instead of carrying a second copy of that format.
The editors also share the forgiving "read it or fall back to {}" loader.

Kept stdlib-only and dependency-free so the standalone tools in data/editors
and data/generators can import it without pulling the game in behind them.
"""
import json
import os


def dump_compact(value):
    """One entry's value, on a single line: tight ', ' / ': ' separators."""
    return json.dumps(value, separators=(', ', ': '))


def render_compact_mapping(mapping, newline="\n"):
    """Renders a mapping with one compact JSON value per top-level line."""
    items = list(mapping.items())
    lines = ["{"]
    for index, (key, value) in enumerate(items):
        comma = "," if index < len(items) - 1 else ""
        lines.append(f'    {json.dumps(str(key))}: {dump_compact(value)}{comma}')
    lines.append("}")
    return newline.join(lines)


def write_compact_mapping(path, mapping, newline="\n"):
    """Writes ``mapping`` in the project's hand-readable compact format."""
    with open(path, "w", encoding="utf-8", newline="") as file:
        file.write(render_compact_mapping(mapping, newline))


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
