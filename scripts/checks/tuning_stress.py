"""Find tests that depend on current unit, building, research, and policy tuning.

Usage:
    python scripts/checks/tuning_stress.py
    python scripts/checks/tuning_stress.py --variant stats --show-all

Each variant runs the test suite on changed copies of the data in a temporary folder.
The constants variant loads changed constants in memory. The policies variant
changes eligibility cutoffs and effect values in memory.
Source data files do not change. A failure outside EXPECTED_FAILURES means that a test
depends on current tuning. Rewrite that test around its rule.
"""

import argparse
import ast
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
VARIANTS = ("stats", "no_prereqs", "prereq_levels", "years", "bonuses", "constants", "policies")
CONSTANTS_PATH = os.path.join(ROOT, "data", "constants.py")
# constants.py numbers that are not gameplay tuning. The constants variant leaves them unchanged.
FIXED_CONSTANTS = {
    # Layout, colors, and art. Tests may check these, and a changed color can be invalid.
    # CUSTOM_BATTLE_UNITS_PER_COLUMN sets the custom battle roster's rows as well as its paired columns.
    "SCREEN_WIDTH", "SCREEN_HEIGHT", "UI_LEFT_OFFSET", "TOP_UI_HEIGHT", "BOT_UI_HEIGHT", "TOTAL_UI_HEIGHT",
    "TOP_BAR_UI_CENTER_Y", "BOTTOM_BAR_UI_CENTER_Y", "PROVINCE_UI", "SIZES", "MODAL_TITLE_Y_OFFSET", "SCROLL_STEP",
    "BACK_BTN_TOPLEFT", "MAX_CAMERA_ZOOM", "FLAG_SIZE", "PORTRAIT_SIZE", "ARMY_CUSTOM_SYMBOL_SIZE",
    "MENU_BOTTOM_TEXT_LINK_COLOR", "DEFAULT_BG_COLOR", "UI_COLORS", "COLOR_GOLD_HIGHLIGHT", "COLOR_SUCCESS_GREEN",
    "COLOR_DIM_BORDER", "COLOR_RESOURCE_MANPOWER", "COLOR_RESOURCE_MATERIALS", "COLOR_RESOURCE_FUEL", "COLOR_CHROMA_PINK",
    "UI_TEXT_BRIGHT", "UI_TEXT_LIGHT", "UI_TEXT_DIM", "UI_TEXT_MUTED", "UI_ACCENT_BLUE", "MODAL_OVERLAY_ALPHA", "MODAL_BG",
    "HUD_PANEL_BG", "HUD_PANEL_BORDER", "PANEL_THEME_DANGER", "PANEL_THEME_CONFIRM", "PANEL_THEME_INFO", "PANEL_THEME_EDIT",
    "PANEL_THEME_SPECIAL", "PANEL_THEME_CONFIRM_OVER_MAP", "PANEL_THEME_INFO_OVER_MAP", "INPUT_BORDER", "INPUT_BORDER_ACTIVE",
    "MSG_NOTIFICATION_COLOR", "BOMBARDMENT_ARROW_ICONS", "CUSTOM_BATTLE_UNITS_PER_COLUMN", "DEFAULT_ARMY_SYMBOL_COLOR", "UNASSIGNED_ARMY_COLOR",
    "ARMY_SYMBOL_COLOR_CHOICES", "ARMY_SYMBOL_ROTATIONS", "DEFAULT_ARMY_SYMBOL_ROTATION", "MAX_CHECKERBOARD_SCROLL_SPEED",
    "MAX_CHECKERBOARD_GRADIENT_STRENGTH", "HILDEHRAND_GRADIENT_MAX_STRENGTH", "HILDEHRAND_GRADIENT_MIN_BANDS",
    "HILDEHRAND_GRADIENT_MAX_BANDS",
    # Encodings and file formats: pygame button numbers, Roman numerals, and save layout.
    "MOUSE_BUTTONS", "ROMAN_SYMBOL_VALUES", "ROMAN_LETTER_VALUES", "ROMAN_NUMERALS",
    "HISTORY_INDENT", "LIBRARY_JSON_INDENT", "SAVE_INDENT", "SAVE_LINE_WIDTH", "HISTORY_GZIP_LEVEL",
    # The calendar must match research years in the JSON data. The years variant moves research years.
    "START_YEAR", "END_YEAR", "DEFAULT_EQUIPMENT_YEAR", "DEFAULT_1910_TECH", "TACTICAL_DEFAULT_YEAR",
    # Choices offered in settings, not tuning.
    "DAYS_PER_TURN_OPTIONS",
}

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
# These tests check that constants.py values agree with each other, so changing each value alone must fail them.
CONSTANT_RULE_TESTS = {
    # Each extra aircraft must add total attack, which ties the small-stack and large-stack curves together.
    "test_air_mechanics.AirResolutionTests.test_equal_aircraft_stacks_gain_total_attack_at_every_size",
}
EXPECTED_FAILURES = RECIPE_SYNC_TESTS | CONSTANT_RULE_TESTS
UNIT_STATS = ("health", "attack", "defense", "cost_materials", "cost_manpower", "cost_fuel",
              "production_time", "bombard_attack", "bombard_range", "range")
BUILDING_STATS = ("time", "cost_materials", "cost_manpower", "cost_fuel",
                  "prod_materials", "prod_manpower", "prod_fuel")


def scaled(value):
    return int(round(value * 1.37)) + 1 if value > 0 else value


def scaled_constant(value):
    """Move a constants.py number enough to expose a copied literal, keeping its sign and 0-1 range."""
    if isinstance(value, bool) or value == 0:
        return value
    if isinstance(value, int):
        # 1 and -1 often mean one step or one direction; larger counts can grow.
        return value + (1 if value > 0 else -1) if abs(value) >= 2 else value
    return value * (0.9 if -1 < value < 1 else 1.1)


class ConstantScaler(ast.NodeTransformer):
    def visit_Subscript(self, node):
        # An index or slice picks an item; changing it would change the data's shape, not its tuning.
        node.value = self.visit(node.value)
        return node

    def visit_BinOp(self, node):
        # Arithmetic on another name, such as COMBAT_WIDTH // 2, is a formula. The named value changes instead.
        if any(isinstance(child, ast.Name) for child in ast.walk(node)):
            return node
        return self.generic_visit(node)

    def visit_Constant(self, node):
        if isinstance(node.value, (int, float)):
            return ast.copy_location(ast.Constant(scaled_constant(node.value)), node)
        return node


def install_scaled_constants():
    """Load data.constants with every assigned number changed, before any other module imports it.

    Running the changed source keeps constants built from other constants consistent.
    """
    with open(CONSTANTS_PATH, encoding="utf-8") as handle:
        tree = ast.parse(handle.read(), CONSTANTS_PATH)
    for statement in tree.body:
        targets = statement.targets if isinstance(statement, ast.Assign) else [getattr(statement, "target", None)]
        names = {target.id for target in targets if isinstance(target, ast.Name)}
        if isinstance(statement, (ast.Assign, ast.AnnAssign)) and statement.value is not None and not names & FIXED_CONSTANTS:
            statement.value = ConstantScaler().visit(statement.value)
    ast.fix_missing_locations(tree)
    module = importlib.util.module_from_spec(importlib.util.spec_from_file_location("data.constants", CONSTANTS_PATH))
    sys.modules["data.constants"] = module
    exec(compile(tree, CONSTANTS_PATH, "exec"), module.__dict__)
    import data
    data.constants = module


def perturb_policies():
    """Change the policy definitions after the child process sets its import path."""
    from data import constants as c
    from map_logic import politics

    # The policy list and ID index both reference these definitions.
    for definition in politics.POLICIES:
        for key, (_, comparison) in politics.POLICY_REQUIREMENTS.items():
            if key in definition:
                bound = definition[key]
                change = 3 if comparison == ">" else -3
                moved = bound + change
                definition[key] = moved if c.POLITICS_MIN < moved < c.POLITICS_MAX else bound - change
        for effect, value in definition["effects"].items():
            definition["effects"][effect] = value + 1 if isinstance(value, int) else value * 1.15


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


def run_variant(variant, output, tests):
    """Run the suite in this process with the data paths pointed at changed copies."""
    os.chdir(ROOT)
    sys.path.insert(0, ROOT)
    if variant == "constants":
        install_scaled_constants()
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
        if variant == "policies":
            perturb_policies()
        elif variant != "constants":
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
        loader = unittest.defaultTestLoader
        suite = loader.loadTestsFromNames(tests) if tests else loader.discover(start_dir="tests", top_level_dir=ROOT)
        with open(os.devnull, "w", encoding="utf-8") as sink:
            result = unittest.TextTestRunner(stream=sink, verbosity=0).run(suite)
    details = {}
    for test, trace in (*result.failures, *result.errors):
        name = re.sub(r"\s*\(.*\)$", "", str(test.id())).replace("tests.", "", 1)
        details.setdefault(name, trace.strip().splitlines()[-1])
    with open(output, "w", encoding="utf-8") as handle:
        json.dump({"ran": result.testsRun, "failed": sorted(details), "details": details}, handle)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--variant", action="append", choices=VARIANTS)
    parser.add_argument("--tests", nargs="+", metavar="TEST", help="Run these unittest names instead of discovering the full suite.")
    parser.add_argument("--show-all", action="store_true", help="Also list the expected recipe and constant rule failures.")
    parser.add_argument("--details", action="store_true", help="Print the error line under each failing test.")
    parser.add_argument("--child", help=argparse.SUPPRESS)
    parser.add_argument("--output", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.child:
        run_variant(args.child, args.output, args.tests)
        return 0

    environment = dict(os.environ, SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy")
    unexpected = 0
    with tempfile.TemporaryDirectory() as directory:
        running = []
        test_args = ["--tests", *args.tests] if args.tests else []
        for variant in args.variant or VARIANTS:
            path = os.path.join(directory, f"{variant}.json")
            running.append((variant, path, subprocess.Popen(
                [sys.executable, os.path.abspath(__file__), "--child", variant, "--output", path, *test_args],
                env=environment, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)))
        for variant, path, process in running:
            if process.wait():
                raise SystemExit(f"The {variant} variant stopped before its report was written.")
            with open(path, encoding="utf-8") as handle:
                report = json.load(handle)
            problems = [name for name in report["failed"] if name not in EXPECTED_FAILURES]
            unexpected += len(problems)
            print(f"{variant}: {report['ran']} tests, {len(problems)} depend on tuning")
            for name in problems:
                print(f"  {name}")
                if args.details:
                    print(f"      {report['details'][name]}")
            if args.show_all:
                for name in sorted(set(report["failed"]) & EXPECTED_FAILURES):
                    print(f"  expected: {name}")
    return 1 if unexpected else 0


if __name__ == "__main__":
    sys.exit(main())
