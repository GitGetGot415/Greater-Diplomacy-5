"""Write built-in maps in the current save format.

Preview bundled maps: python scripts/maps/upgrade_shipped_maps.py
Apply the preview:    python scripts/maps/upgrade_shipped_maps.py --write
Upgrade an existing save or editor scenario explicitly:
    python scripts/maps/upgrade_shipped_maps.py --write "saves/My Save"

With no paths, only base_maps and shipped scenarios are visited. Personal saves,
tournament files and scenarios/map_editor are never included implicitly.
The tool runs the version steps on the files. It does not load the map, so no
load-time choice (such as time-appropriate research) is written into a file.
Run it after adding a version step. See documentation/data_migrations.txt.
This developer tool is not required or shipped by any platform build.
"""

import argparse
import copy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from data import constants as c, migrations
from data.map import history_io, load_map


def upgrade_map(directory, *, write=False):
    """Return the names of the files the version steps change, optionally writing them."""
    directory = Path(directory)
    save_meta, map_data, history = load_map.read_save_files(directory)
    before = copy.deepcopy((save_meta, map_data, history))
    migrations.upgrade_save(save_meta if save_meta is not None else {}, map_data, history)
    changed = [name for name, old, new in (("meta.json", before[0], save_meta),
                                           ("map_data.json", before[1], map_data),
                                           ("history", before[2], history))
               if new is not None and old != new]
    if write:
        for name, data in (("meta.json", save_meta), ("map_data.json", map_data)):
            if name in changed:
                (directory / name).write_text(history_io.dump_text(data, indent=c.SAVE_INDENT))
        if "history" in changed:
            history_io.write(str(directory), history)
    return changed


def built_in_maps():
    for root in (c.BASE_MAPS_DIR, c.SCENARIOS_HISTORICAL_DIR, c.SCENARIOS_ALTERNATE_DIR):
        for directory in sorted((ROOT / root).iterdir()):
            if (directory / "map_data.json").is_file():
                yield directory.relative_to(ROOT)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="*", help="Map or save folders. Default: built-in maps.")
    parser.add_argument("--write", action="store_true", help="Write the changed files.")
    args = parser.parse_args(argv)
    directories = [Path(path) for path in args.paths] or list(built_in_maps())
    total = 0
    for directory in directories:
        changed = upgrade_map(directory, write=args.write)
        total += bool(changed)
        if changed:
            print(f"{directory}: {', '.join(changed)}")
    action = "Upgraded" if args.write else "Would upgrade"
    print(f"{action} {total} of {len(directories)} maps to {c.GAME_VERSION}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
