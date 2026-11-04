"""Write tests/released_content.py from every release in the version.txt history.

Usage: python scripts/data/write_released_content.py

Run it after each release, when GAME_VERSION changes to the next version.
Commit the release first. The script reads only committed history.
It reads each release with git show, so the working tree does not change.
See data/migrations/MIGRATIONS.md, Released Names.
This developer tool is not required or shipped by any platform build.
"""

import ast
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from data import migrations, queries

OUTPUT = ROOT / "tests" / "released_content.py"
UNIT_DATA = "data/json/unit_data.json"
BUILDING_DATA = "data/json/building_data.json"
LINE_WIDTH = 100


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout


def release_commits():
    """Return {version: commit} for each release, oldest first.

    A release is the newest commit whose version.txt holds that stamp.
    Test edits, such as v999, are above the current release and are skipped.
    """
    if git("rev-parse", "--is-shallow-repository").strip() != "false":
        raise ValueError("Released content needs the full Git history. "
                         "Run git fetch --unshallow before generating the inventory.")
    latest_stamp = (ROOT / "version.txt").read_text(encoding="utf-8").strip()
    latest = migrations.version_number(latest_stamp)
    releases = {}
    for commit in git("log", "--format=%H", "--", "version.txt").split():
        stamp = git("show", f"{commit}:version.txt").strip()
        if re.fullmatch(r"v\d+", stamp) and migrations.version_number(stamp) <= latest:
            releases.setdefault(stamp, commit[:12])
    if latest_stamp not in releases:
        raise ValueError(f"Cannot find release {latest_stamp} in the Git history. "
                         "Commit the release and fetch the full Git history before generating the inventory.")
    return dict(sorted(releases.items(), key=lambda item: migrations.version_number(item[0])))


def validate_inventory(inventory):
    """Refuse to replace an inventory with fewer releases or released names."""
    if not inventory["RELEASES"]:
        raise ValueError("No releases found. Fetch the full Git history before generating the inventory.")
    if not OUTPUT.exists():
        return
    previous = {}
    try:
        for node in ast.parse(OUTPUT.read_text(encoding="utf-8")).body:
            if (isinstance(node, ast.Assign) and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name) and node.targets[0].id in inventory):
                previous[node.targets[0].id] = ast.literal_eval(node.value)
    except (SyntaxError, ValueError, TypeError) as error:
        raise ValueError(f"Cannot read the existing inventory {OUTPUT}. Correct it before regenerating.") from error
    for name, values in inventory.items():
        expected = dict if name == "RELEASES" else tuple
        old = previous.get(name)
        if not isinstance(old, expected):
            raise ValueError(f"The existing inventory must define {name} as a {expected.__name__}.")
        missing = sorted(set(old) - set(values))
        if missing:
            raise ValueError(f"Regeneration would remove {name}: {', '.join(missing)}. "
                             "Check the release history and libraries; the existing inventory was kept.")
        if name == "RELEASES" and any(values[stamp] != commit for stamp, commit in old.items()):
            raise ValueError("Regeneration would change recorded release commits. "
                             "Check the full Git history; the existing inventory was kept.")


def read_json(commit, path):
    try:
        library = json.loads(git("show", f"{commit}:{path}"))
    except (subprocess.CalledProcessError, json.JSONDecodeError) as error:
        raise ValueError(f"Cannot read release library {commit}:{path}. "
                         "Check the committed path and fetch the full Git history.") from error
    if not isinstance(library, dict) or not library:
        raise ValueError(f"Release library {commit}:{path} must be a nonempty JSON object.")
    return library


def unit_family(name, stats):
    """Return the settings family that this release wrote for the unit."""
    metadata = stats.get("metadata") if isinstance(stats, dict) else None
    if isinstance(metadata, dict) and "family" in metadata:
        return metadata.get("settings_family", metadata["family"])
    return queries.base_item_name_from_text(name)


def tuple_text(name, values):
    """Format sorted strings as a wrapped tuple."""
    lines, line = [], "   "
    for value in sorted(values):
        item = f" {json.dumps(value)},"
        if len(line) + len(item) > LINE_WIDTH:
            lines.append(line)
            line = "   "
        line += item
    lines.append(line)
    return f"{name} = (\n" + "\n".join(lines) + "\n)\n"


def main():
    releases = release_commits()
    units, buildings, unit_families, building_families = set(), set(), set(), set()
    for commit in releases.values():
        for name, stats in read_json(commit, UNIT_DATA).items():
            units.add(name)
            unit_families.add(unit_family(name, stats))
        for name in read_json(commit, BUILDING_DATA):
            buildings.add(name)
            building_families.add(queries.base_item_name_from_text(name))
    validate_inventory({"RELEASES": releases, "UNITS": units, "BUILDINGS": buildings,
                        "UNIT_FAMILIES": unit_families, "BUILDING_FAMILIES": building_families})
    text = ('"""Names that released games wrote into saves. Generated. Do not edit by hand.\n\n'
            "scripts/data/write_released_content.py writes this file from the version.txt history.\n"
            "ReleasedContentTests in tests/test_data_migrations.py reads it.\n"
            '"""\n\n'
            "#: Each release in this file and its commit.\n"
            "RELEASES = {\n" + "".join(f"    {json.dumps(v)}: {json.dumps(c)},\n" for v, c in releases.items())
            + "}\n\n"
            "#: Unit identifiers from every release library.\n" + tuple_text("UNITS", units) + "\n"
            "#: Building identifiers from every release library.\n" + tuple_text("BUILDINGS", buildings) + "\n"
            "#: Keys of unit_disabled, unit_turn_overrides, and unit_range_overrides.\n"
            + tuple_text("UNIT_FAMILIES", unit_families) + "\n"
            "#: Keys of building_disabled and building_turn_overrides.\n"
            + tuple_text("BUILDING_FAMILIES", building_families))
    OUTPUT.write_text(text, encoding="utf-8")
    print(f"Wrote {OUTPUT.relative_to(ROOT)}: {len(releases)} releases, {len(units)} units, "
          f"{len(buildings)} buildings.")


if __name__ == "__main__":
    main()
