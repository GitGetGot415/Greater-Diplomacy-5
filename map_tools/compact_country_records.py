"""Remove duplicated, unused country templates from map metadata.

Preview bundled maps: python map_tools/compact_country_records.py
Apply the preview:    python map_tools/compact_country_records.py --write
Clean an existing save or editor scenario explicitly:
    python map_tools/compact_country_records.py --write "saves/My Save"

With no paths, only base_maps and shipped scenarios are visited. Personal saves,
tournament files and scenarios/map_editor are never included implicitly.
Province files, history, assets and the shared country catalog are untouched.
This developer tool is not required or shipped by any platform build.
"""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from data import constants as c, queries


def compact_map_metadata(directory, *, write=False):
    """Return (replaced records, bytes saved), optionally writing only meta.json."""
    directory = Path(directory)
    meta_path = directory / "meta.json"
    map_path = directory / "map_data.json"
    if not meta_path.is_file() or not map_path.is_file():
        return 0, 0
    original = meta_path.read_bytes()
    meta = json.loads(original)
    if "nation_data" not in meta:
        return 0, 0
    provinces = json.loads(map_path.read_bytes())
    nations = meta["nation_data"]
    queries.compact_save_nation_data(meta, provinces)
    compact = meta["nation_data"]
    replaced = sum(bool(nations[name]) and not record
                   for name, record in compact.items())
    if not replaced:
        return 0, 0
    payload = json.dumps(meta, indent=c.SAVE_INDENT).encode("utf-8")
    if write:
        meta_path.write_bytes(payload)
    return replaced, len(original) - len(payload)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path,
                        help="map folders or roots to visit (includes user data only if named)")
    parser.add_argument("--write", action="store_true", help="apply changes; otherwise preview")
    args = parser.parse_args(argv)
    roots = args.paths or [ROOT / "base_maps", ROOT / "scenarios"]
    files = records = saved = 0
    visited = set()
    for root in roots:
        if not root.is_dir():
            parser.error(f"Directory does not exist: {root}")
        for meta_path in sorted(root.rglob("meta.json")):
            if not args.paths and "map_editor" in meta_path.parts:
                continue
            directory = meta_path.parent.resolve()
            if directory in visited:
                continue
            visited.add(directory)
            count, byte_count = compact_map_metadata(directory, write=args.write)
            if count:
                files += 1
                records += count
                saved += byte_count
                print(f"{directory}: {count} templates, {byte_count:,} bytes saved")
    action = "Compacted" if args.write else "Would compact"
    print(f"{action} {records:,} country records across {files} maps; {saved:,} bytes saved.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
