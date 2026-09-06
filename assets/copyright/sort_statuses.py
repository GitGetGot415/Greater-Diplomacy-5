"""Alphabetically sort the flag and portrait copyright-status tables."""

from pathlib import Path
import re


COPYRIGHT_DIR = Path(__file__).resolve().parent
STATUS_FILES = (
    COPYRIGHT_DIR / "flags_copyright_status.md",
    COPYRIGHT_DIR / "portraits_copyright_status.md",
)
TABLE_ROW_RE = re.compile(r"^\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*$")


def sort_status_file(path):
    """Sort the Markdown table in *path* by its first column."""
    raw_text = path.read_bytes().decode("utf-8")
    newline = "\r\n" if "\r\n" in raw_text else "\n"
    lines = raw_text.splitlines()

    separator_index = next(
        index for index, line in enumerate(lines)
        if line.strip() == "| --- | --- |"
    )

    body_lines = lines[separator_index + 1:]
    table_rows = []
    for index, line in enumerate(body_lines):
        match = TABLE_ROW_RE.match(line)
        if match:
            table_rows.append((match.group(1), index, line))

    sorted_rows = [
        line for _, _, line in sorted(table_rows, key=lambda row: row[0].casefold())
    ]
    for (_, index, _), sorted_row in zip(table_rows, sorted_rows):
        body_lines[index] = sorted_row
    sorted_lines = lines[:separator_index + 1] + body_lines
    output = newline.join(sorted_lines)
    if raw_text.endswith(("\n", "\r")):
        output += newline

    if output != raw_text:
        path.write_bytes(output.encode("utf-8"))
        return True
    return False


def main():
    for path in STATUS_FILES:
        changed = sort_status_file(path)
        action = "Sorted" if changed else "Already sorted"
        print(f"{action}: {path.name}")


if __name__ == "__main__":
    main()
