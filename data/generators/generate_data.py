"""
Regenerates data/json/unit_data.json, building_data.json, and
research_template.json from the compact recipes in recipes.py.

Usage:
    python data/generators/generate_data.py            # write the files
    python data/generators/generate_data.py --check     # show what would change, don't write

Edit recipes.py to change base stats, growth rates, or add new levels/units,
then re-run this script. The game only reads data/json/*.json, so this never
needs to touch any other code.
"""
import sys
import os
import json
import argparse

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
import data.constants as c
from data.generators import recipes as r


def dump_compact(value):
    """Same style as the tkinter unit editor's custom_json_dump: tight,
    single-line, ', '/': ' separators, no indent."""
    return json.dumps(value, separators=(', ', ': '))


def render_flat_file(sections, spacer):
    """sections: list of blocks, each a list of (key, value) pairs.
    Renders '{ <lines...> }' with one entry per line, a blank `spacer` line
    between blocks, and no trailing newline."""
    lines = ["{"]
    all_blocks = []
    for block in sections:
        all_blocks.append(block)

    total_entries = sum(len(block) for block in all_blocks)
    written = 0
    for b_idx, block in enumerate(all_blocks):
        for key, value in block:
            written += 1
            comma = "," if written < total_entries else ""
            lines.append(f'    "{key}": {dump_compact(value)}{comma}')
        if spacer is not None and b_idx < len(all_blocks) - 1:
            lines.append(spacer)
    lines.append("}")
    return "\r\n".join(lines)


def render_research_file(sections):
    """research_template.json wraps each entry's outer braces with a space:
    '{ "category": ... }' instead of '{"category": ...}'."""
    lines = ["{"]
    total_entries = sum(len(block) for block in sections)
    written = 0
    for b_idx, block in enumerate(sections):
        for key, value in block:
            written += 1
            comma = "," if written < total_entries else ""
            inner = dump_compact(value)
            padded = "{ " + inner[1:-1] + " }"
            lines.append(f'    "{key}": {padded}{comma}')
        if b_idx < len(sections) - 1:
            lines.append("    ")
    lines.append("}")
    return "\r\n".join(lines)


def build_unit_data_text():
    sections = [[fam.entries() for fam in block] for block in r.UNIT_SECTIONS]
    flat_sections = []
    for block in sections:
        flat_block = []
        for fam_entries in block:
            flat_block.extend(fam_entries)
        flat_sections.append(flat_block)
    # unit_data.json keeps a trailing newline after the closing brace.
    return render_flat_file(flat_sections, spacer="") + "\r\n"


def build_building_data_text():
    sections = [chain.entries() for chain in r.BUILDING_CHAINS]
    return render_flat_file(sections, spacer=None)


def build_research_template_text():
    return render_research_file(r.RESEARCH_SECTIONS)


TARGETS = [
    (c.UNIT_DATA_PATH, build_unit_data_text),
    (c.BUILDING_DATA_PATH, build_building_data_text),
    (c.RESEARCH_TEMPLATE_PATH, build_research_template_text),
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true",
                         help="Print whether each file would change, without writing.")
    args = parser.parse_args()

    changed_any = False
    for path, builder in TARGETS:
        new_text = builder()
        old_text = None
        if os.path.exists(path):
            with open(path, "r", newline="") as f:
                old_text = f.read()

        if new_text == old_text:
            print(f"unchanged: {path}")
            continue

        changed_any = True
        if args.check:
            print(f"WOULD CHANGE: {path}")
        else:
            with open(path, "w", newline="") as f:
                f.write(new_text)
            print(f"wrote: {path}")

    if not args.check:
        try:
            from data import queries
            queries.clear_json_caches()
        except Exception:
            pass

    if args.check and not changed_any:
        print("All generated files match the recipes.")


if __name__ == "__main__":
    main()
