"""Interactive balance explorer for comparing every unit and building.

Run from the repository root with ``python scripts/previews/balance_explorer.py``.
The script reads the default unit and building libraries and writes one
self-contained HTML page beneath the system temporary directory. It then opens
the page in the default browser. Use ``--out PATH`` to choose the file and
``--no-open`` to skip the browser. Use ``--style`` to draw icons in an art
style other than the one in the saved settings. The script never changes game
data.
"""

import argparse
import base64
import io
import json
import os
import sys
import tempfile
import webbrowser
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Icons load through pygame, which needs a display mode but no visible window.
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import pygame

import data.constants as c
from data import queries
from data.io import settings_schema
from ui.rendering import symbol_loader


TEMPLATE_PATH = Path(__file__).with_name("balance_explorer.html")
DATA_MARKER = "/*BALANCE_DATA*/null"
DEFAULT_OUT = Path(tempfile.gettempdir()) / "gd5_balance_explorer.html"

UNIT_FIELDS = ("health", "attack", "defense", "speed", "cost_materials", "cost_manpower",
               "cost_fuel", "production_time", "bombard_attack", "air_range_px")
BUILDING_FIELDS = ("group", "time", "cost_materials", "cost_manpower", "cost_fuel",
                   "prod_materials", "prod_manpower", "prod_fuel")

# The largest size the page draws an icon at, when zoomed in.
ICON_FIT = (48, 48)
# The game tints the red parts of unit art with the owner's color. The explorer
# tints them with the group color instead. Keep these equal to the light-mode
# --s1 to --s4 values in balance_explorer.html.
GROUP_ICON_COLORS = {
    "Infantry": (0x2a, 0x78, 0xd6), "Tanks": (0x00, 0x83, 0x00),
    "Navy": (0xe8, 0x7b, 0xa4), "Air": (0xed, 0xa1, 0x00),
    "industry": (0x2a, 0x78, 0xd6), "recruitment": (0x00, 0x83, 0x00),
    "fortification": (0xe8, 0x7b, 0xa4),
}


class IconSheet:
    """Collects each distinct icon once and gives rows an index into the list."""

    def __init__(self):
        self.icons = []
        self._index = {}

    def add(self, surface):
        buffer = io.BytesIO()
        pygame.image.save(surface, buffer, "icon.png")
        uri = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
        if uri not in self._index:
            self._index[uri] = len(self.icons)
            self.icons.append({"uri": uri, "w": surface.get_width(), "h": surface.get_height()})
        return self._index[uri]


def _icon(sheet, name, group):
    surface = symbol_loader.get_symbol(name, 1, color=GROUP_ICON_COLORS[group], fit_size=ICON_FIT)
    return None if surface is None else sheet.add(surface)


def _research_year(tech_tree, tech, level):
    """The year the research tree gives for one tech level, or None."""
    years = tech_tree.get(tech, {}).get("years", [])
    return years[level - 1] if 1 <= level <= len(years) else None


def _unit_rows(unit_library, tech_tree, sheet):
    rows = []
    for name, stats in unit_library.items():
        meta = stats["metadata"]
        research = meta.get("research", {})
        # Infantry families store their year. Other units store a tech level,
        # which the research tree dates.
        year = research.get("year")
        if year is None:
            year = _research_year(tech_tree, research["tech"], research["level"])
        row = {field: stats.get(field) for field in UNIT_FIELDS}
        row.update(name=name, family=meta["family"], group=meta["production_group"],
                   year=year, level=research.get("level"),
                   tier_order=meta.get("tier_order", 0), tier_label=meta.get("tier_label"))
        row["icon"] = _icon(sheet, name, row["group"])
        row["icon_fallback"] = False
        if row["icon"] is None and meta.get("settings_family"):
            # The map draws no symbol for this unit. Show its family art so
            # the point still has a picture, and flag it on the page.
            row["icon"] = _icon(sheet, meta["settings_family"], row["group"])
            row["icon_fallback"] = row["icon"] is not None
        rows.append(row)
    return rows


def _building_rows(building_library, tech_tree, sheet):
    rows = []
    for name, stats in building_library.items():
        row = {field: stats.get(field) for field in BUILDING_FIELDS}
        # Some base buildings store the string "null" as their requirement.
        req = stats.get("req")
        # Buildings without a research requirement, such as forts, have no year.
        tech, level = queries.get_building_required_tech(name)
        row.update(name=name, req=req if req in building_library else None,
                   year=_research_year(tech_tree, tech, level) if tech else None,
                   icon=_icon(sheet, name, row["group"]))
        rows.append(row)
    by_name = {row["name"]: row for row in rows}

    def level(row, seen=()):
        if row["req"] is None or row["name"] in seen:
            return 0
        return level(by_name[row["req"]], seen + (row["name"],)) + 1

    for row in rows:
        row["level"] = level(row)
    return rows


def saved_art_style():
    return settings_schema.from_json_dict(queries.get_settings())["unit_art_style"]


def build_page(style):
    pygame.display.init()
    pygame.display.set_mode((1, 1))
    c.apply_runtime_settings({"unit_art_style": style})
    symbol_loader.load_symbols()
    sheet = IconSheet()
    tech_tree = queries.get_tech_tree()
    data = {
        "units": _unit_rows(queries.get_unit_library(), tech_tree, sheet),
        "buildings": _building_rows(queries.get_building_library(), tech_tree, sheet),
        "icons": sheet.icons,
        "icon_size": max(ICON_FIT),
        "style": style,
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    pygame.display.quit()
    missing = [row["name"] for row in data["units"] + data["buildings"] if row["icon"] is None]
    fallback = [row["name"] for row in data["units"] if row["icon_fallback"]]
    if fallback:
        print(f"{len(fallback)} units have no map icon in the {style} style; "
              f"the page shows their family art. First: {fallback[0]}")
    if missing:
        print(f"{len(missing)} entries have no icon at all. First: {missing[0]}")
    undated = [row["name"] for row in data["units"] if row["year"] is None]
    if undated:
        print(f"{len(undated)} units need a tech level past the end of its research track: "
              f"{', '.join(undated)}")
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
    parser.add_argument("--style", choices=c.UNIT_ART_STYLES,
                        help="unit art style for icons (default: the saved setting)")
    args = parser.parse_args()
    args.out.write_text(build_page(args.style or saved_art_style()), encoding="utf-8")
    print(f"Wrote {args.out}")
    if not args.no_open:
        webbrowser.open(args.out.resolve().as_uri())


if __name__ == "__main__":
    main()
