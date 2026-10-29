"""Interactive balance explorer for comparing every unit and building.

Run from the repository root with ``python scripts/previews/balance_explorer.py``.
The script reads the default unit and building libraries and writes one
self-contained HTML page beneath the system temporary directory. It then opens
the page in the default browser. Use ``--out PATH`` to choose the file and
``--no-open`` to skip the browser. The script never changes game data.
"""

import argparse
import json
import sys
import tempfile
import webbrowser
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data import queries


TEMPLATE_PATH = Path(__file__).with_name("balance_explorer.html")
DATA_MARKER = "/*BALANCE_DATA*/null"
DEFAULT_OUT = Path(tempfile.gettempdir()) / "gd5_balance_explorer.html"

UNIT_FIELDS = ("health", "attack", "defense", "speed", "cost_materials", "cost_manpower",
               "cost_fuel", "production_time", "bombard_attack", "air_range_px")
BUILDING_FIELDS = ("group", "time", "cost_materials", "cost_manpower", "cost_fuel",
                   "prod_materials", "prod_manpower", "prod_fuel")


def _unit_rows(unit_library):
    rows = []
    for name, stats in unit_library.items():
        meta = stats["metadata"]
        research = meta.get("research", {})
        row = {field: stats.get(field) for field in UNIT_FIELDS}
        row.update(name=name, family=meta["family"], group=meta["production_group"],
                   year=research.get("year"), level=research.get("level"),
                   tier_order=meta.get("tier_order", 0), tier_label=meta.get("tier_label"))
        rows.append(row)
    return rows


def _building_rows(building_library):
    rows = []
    for name, stats in building_library.items():
        row = {field: stats.get(field) for field in BUILDING_FIELDS}
        # Some base buildings store the string "null" as their requirement.
        req = stats.get("req")
        row.update(name=name, req=req if req in building_library else None)
        rows.append(row)
    by_name = {row["name"]: row for row in rows}

    def level(row, seen=()):
        if row["req"] is None or row["name"] in seen:
            return 0
        return level(by_name[row["req"]], seen + (row["name"],)) + 1

    for row in rows:
        row["level"] = level(row)
    return rows


def build_page():
    data = {
        "units": _unit_rows(queries.get_unit_library()),
        "buildings": _building_rows(queries.get_building_library()),
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    # "</" would end the inline script early if a name ever contained it.
    payload = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    if DATA_MARKER not in template:
        raise ValueError(f"{TEMPLATE_PATH.name} is missing the {DATA_MARKER} marker.")
    return template.replace(DATA_MARKER, payload)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="HTML file to write")
    parser.add_argument("--no-open", action="store_true", help="do not open the page in a browser")
    args = parser.parse_args()
    args.out.write_text(build_page(), encoding="utf-8")
    print(f"Wrote {args.out}")
    if not args.no_open:
        webbrowser.open(args.out.resolve().as_uri())


if __name__ == "__main__":
    main()
