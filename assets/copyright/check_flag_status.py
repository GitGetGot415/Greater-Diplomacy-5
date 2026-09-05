"""Display the copyright/status breakdown for the project's flags."""

from collections import Counter
from pathlib import Path
import re
import sys


STATUS_FILE = Path(__file__).with_name("flags_copyright_status.md")
ROW_RE = re.compile(r"^\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*$")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def read_flag_statuses():
    """Return (flag name, status) pairs from the copyright table."""
    entries = []
    for line in STATUS_FILE.read_text(encoding="utf-8").splitlines():
        match = ROW_RE.match(line)
        if not match or match.group(1) in {"Flag name", "---"}:
            continue
        entries.append(match.groups())
    return entries


def main():
    entries = read_flag_statuses()
    statuses = Counter(status for _, status in entries)

    print(f"- {len(statuses)} unique creator/status labels")
    print(f"- {len(entries)} flags total")
    print()
    print("Breakdown:")
    for status, count in sorted(statuses.items(), key=lambda item: -item[1]):
        print(f"- {status} — {count}")


if __name__ == "__main__":
    main()
