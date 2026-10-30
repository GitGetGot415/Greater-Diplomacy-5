"""Find tests that depend on current unit, building, and research values.

Usage:
    python scripts/checks/tuning_stress.py
    python scripts/checks/tuning_stress.py --variant stats --show-all

Each variant runs the test suite on changed copies of the data in a temporary folder.
Source data files do not change. A failure outside RECIPE_SYNC_TESTS means that a test
depends on current tuning. Rewrite that test around its rule.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
VARIANTS = ("stats", "no_prereqs", "prereq_levels", "years", "bonuses")

# These tests compare JSON to data/generators/recipes.py. Only the JSON changes here, so they must fail.
RECIPE_SYNC_TESTS = {
    "test_air_content.AirRulesTests.test_jet_transport_content_matches_its_generated_recipes",
    "test_air_mechanics.AirIntegrationTests.test_regeneration_preserves_air_stats_and_research_contract",
    "test_air_transport.TransportSaveSmokeTests.test_real_content_matches_recipes_unlocks_and_png_assets",
    "test_unit_progression.UnitProgressionTests.test_all_equipment_runtime_levels_match_their_base_rows_and_increases",
    "test_unit_progression.UnitProgressionTests.test_generated_runtime_data_matches_recipes",
    "test_unit_progression.UnitProgressionTests.test_generated_vehicle_profiles_match_each_stages_base_and_shared_rules",
    "test_unit_progression.UnitProgressionTests.test_organized_militia_covers_the_period_before_modern_militia",
    "test_unit_progression.UnitProgressionTests.test_source_rows_and_runtime_research_share_dates_and_level_counts",
}
UNIT_STATS = ("health", "attack", "defense", "cost_materials", "cost_manpower", "cost_fuel",
              "production_time", "bombard_attack", "bombard_range", "range")
BUILDING_STATS = ("time", "cost_materials", "cost_manpower", "cost_fuel",
                  "prod_materials", "prod_manpower", "prod_fuel")


def scaled(value):
    return int(round(value * 1.37)) + 1 if value > 0 else value


def shift_years(units, tree, end_year):
    moved = {}
    for key, entry in tree.items():
        years = entry.get("years", [])
        shifted = list(years)
        # Vehicle infantry tiers are defined by infantry_type years, so that track stays fixed.
        # Each first level stays fixed so that starting research stays available.
        if key != "infantry_type":
            for index in range(1, len(years)):
                limit = years[index + 1] if index + 1 < len(years) else min(end_year + 1, years[index] + 2)
                if years[index] + 1 < limit:
                    shifted[index] = years[index] + 1
        moved[key] = dict(zip(years, shifted))
        entry["years"] = shifted
    for unit in units.values():
        metadata = unit["metadata"]
        for item in (metadata.get("research", {}), *metadata.get("requirements", [])):
            if "year" in item:
                item["year"] = moved.get(item["tech"], {}).get(item["year"], item["year"])
        if metadata.get("tier_kind") == "stage":
            tech = metadata.get("research", {}).get("tech")
            metadata["tier_order"] = moved.get(tech, {}).get(metadata["tier_order"], metadata["tier_order"])


def perturb(variant, units, buildings, tree, end_year):
    if variant == "stats":
        for unit in units.values():
            for field in UNIT_STATS:
                if isinstance(unit.get(field), (int, float)) and not isinstance(unit[field], bool):
                    unit[field] = scaled(unit[field])
            unit["speed"] += 1
        for building in buildings.values():
            for field in BUILDING_STATS:
                if isinstance(building.get(field), (int, float)):
                    building[field] = scaled(building[field])
        for entry in tree.values():
            entry["cost"] = scaled(entry["cost"])
    elif variant == "no_prereqs":
        for entry in tree.values():
            entry["req"] = {}
            entry.pop("level_reqs", None)
    elif variant == "prereq_levels":
        for entry in tree.values():
            entry["req"] = {tech: 1 if isinstance(level, int) else level
                            for tech, level in entry.get("req", {}).items()}
    elif variant == "years":
        shift_years(units, tree, end_year)
    elif variant == "bonuses":
        for entry in tree.values():
            entry.pop("building_output_bonuses", None)


def run_variant(variant, output):
    """Run the suite in this process with the data paths pointed at changed copies."""
    os.chdir(ROOT)
    sys.path.insert(0, ROOT)
    # Local imports: the root path must be set first, and data paths must change before tests load.
    from tests import configure_test_audio
    configure_test_audio()
    if os.name == "nt":
        import ctypes
        # Match run_tests.py: a native crash must not open a blocking error dialog.
        ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0002 | 0x8000)
    from data import constants as c

    attributes = ("UNIT_DATA_PATH", "BUILDING_DATA_PATH", "RESEARCH_TEMPLATE_PATH")
    with tempfile.TemporaryDirectory() as directory:
        data = {}
        for attribute in attributes:
            with open(getattr(c, attribute), encoding="utf-8") as handle:
                data[attribute] = json.load(handle)
        perturb(variant, *(data[attribute] for attribute in attributes), c.END_YEAR)
        for attribute in attributes:
            path = os.path.join(directory, os.path.basename(getattr(c, attribute)))
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(data[attribute], handle)
            setattr(c, attribute, path)
        suite = unittest.defaultTestLoader.discover(start_dir="tests", top_level_dir=ROOT)
        with open(os.devnull, "w", encoding="utf-8") as sink:
            result = unittest.TextTestRunner(stream=sink, verbosity=0).run(suite)
    failed = sorted({re.sub(r"\s*\(.*\)$", "", str(test.id())).replace("tests.", "", 1)
                     for test, _trace in (*result.failures, *result.errors)})
    with open(output, "w", encoding="utf-8") as handle:
        json.dump({"ran": result.testsRun, "failed": failed}, handle)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--variant", action="append", choices=VARIANTS)
    parser.add_argument("--show-all", action="store_true", help="Also list the expected recipe comparison failures.")
    parser.add_argument("--child", help=argparse.SUPPRESS)
    parser.add_argument("--output", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.child:
        run_variant(args.child, args.output)
        return 0

    environment = dict(os.environ, SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy")
    unexpected = 0
    with tempfile.TemporaryDirectory() as directory:
        running = []
        for variant in args.variant or VARIANTS:
            path = os.path.join(directory, f"{variant}.json")
            running.append((variant, path, subprocess.Popen(
                [sys.executable, os.path.abspath(__file__), "--child", variant, "--output", path],
                env=environment, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)))
        for variant, path, process in running:
            if process.wait():
                raise SystemExit(f"The {variant} variant stopped before its report was written.")
            with open(path, encoding="utf-8") as handle:
                report = json.load(handle)
            problems = [name for name in report["failed"] if name not in RECIPE_SYNC_TESTS]
            unexpected += len(problems)
            print(f"{variant}: {report['ran']} tests, {len(problems)} depend on tuning")
            for name in problems:
                print(f"  {name}")
            if args.show_all:
                for name in sorted(set(report["failed"]) & RECIPE_SYNC_TESTS):
                    print(f"  expected: {name}")
    return 1 if unexpected else 0


if __name__ == "__main__":
    sys.exit(main())
