"""Check generated unit progression through shared gameplay interfaces."""

import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from data import constants as c, migrations, queries
from data.generators import generate_data, recipes
from map_logic.ai import ai_tech_eval, ai_unit_eval
from tests.test_map_save_format import sample_map_screen


class UnitProgressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.library = queries.get_unit_library()
        cls.tree = queries.get_tech_tree()

    def final_research(self):
        return {key: entry['max_lvl'] for key, entry in self.tree.items()}

    def test_generated_runtime_data_matches_recipes(self):
        for path, builder in ((c.UNIT_DATA_PATH, generate_data.build_unit_data_text),
                              (c.BUILDING_DATA_PATH, generate_data.build_building_data_text),
                              (c.RESEARCH_TEMPLATE_PATH, generate_data.build_research_template_text)):
            with self.subTest(path=path):
                self.assertEqual(json.loads(Path(path).read_text(encoding='utf-8')), json.loads(builder()))

    def test_dated_unit_row_drives_stats_level_count_and_research(self):
        row = (1900, "Fixture Ship", 123, 17, 4, 2, 41, 19, 7, 6, 11,
               (3, 4, {"health": 9, "attack": 5, "cost_materials": 3, "bombard_attack": 2}),
               {"unnumbered_first": True})
        with patch.object(recipes, "NAVAL_UNIT_RECIPES", [row]):
            entries = recipes.unit_family(row, naval_unit=True).entries()
            tech, research = recipes.research_recipe((recipes.unit_years("Fixture Ship"),
                                                     "fixture_ship", "NAVY", 23, {}, {}))
        self.assertEqual(tech, "fixture_ship")
        self.assertEqual(research["years"], [1900, 1904, 1908])
        self.assertEqual(research["max_lvl"], 3)
        self.assertEqual([name for name, _ in entries], ["Fixture Ship", "Fixture Ship II", "Fixture Ship III"])
        self.assertEqual([(entry["health"], entry["attack"], entry["cost_materials"], entry["bombard_attack"])
                          for _, entry in entries], [(123, 17, 41, 11), (132, 22, 44, 13), (141, 27, 47, 15)])
        for level, (_, entry) in enumerate(entries, 1):
            self.assertTrue(entry["naval_unit"])
            self.assertEqual(entry["metadata"]["tier_order"], level)
            self.assertEqual(entry["metadata"]["research"], {"tech": tech, "level": level})
            for field, value in (("defense", 4), ("speed", 2), ("cost_manpower", 19),
                                 ("cost_fuel", 7), ("production_time", 6)):
                self.assertEqual(entry[field], value)

    def test_air_row_keeps_optional_stats_and_research_for_every_unit_tier(self):
        row = (1920, "Fixture Plane", 101, 13, 3, 1, 43, 17, 5, 2, None,
               "bomber", 70, None, True, None, True, None,
               (4, 3, {"health": 7, "air_range_px": 11}), {})
        with patch.object(recipes, "AIR_UNIT_RECIPES", [row]):
            entries = recipes.unit_family(row, air=True).entries()
            _, research = recipes.research_recipe((recipes.unit_years("Fixture Plane"),
                                                  "fixture_plane", "AIR", 31, {}, {}))
        self.assertEqual(len(entries), 4)
        self.assertEqual(research["years"], [1920, 1923, 1926, 1929])
        self.assertEqual(research["max_lvl"], 4)
        self.assertEqual([entry["air_range_px"] for _, entry in entries], [70, 81, 92, 103])
        self.assertEqual([entry["health"] for _, entry in entries], [101, 108, 115, 122])
        for _, entry in entries:
            self.assertEqual(entry["production_group"], "Air")
            self.assertEqual(entry["air_role"], "bomber")
            self.assertTrue(entry["air_consumable"])
            self.assertTrue(entry["air_damages_forts"])
            self.assertNotIn("bombard_attack", entry)
            self.assertNotIn("air_attack_multiplier", entry)
            self.assertNotIn("air_interception_immune", entry)
            self.assertNotIn("air_transport_capacity", entry)

    def test_unit_row_keeps_piecewise_stats_in_the_same_row(self):
        row = (1900, "Fixture Vehicle", 101, 13, 3, recipes.piecewise([(0, 2, 0), (2, 5, 0)]),
               43, 17, 5, 2, None, (4, 3, {"attack": 7}), {})
        entries = recipes.unit_family(row).entries()
        self.assertEqual([entry["speed"] for _, entry in entries], [2, 2, 5, 5])
        self.assertEqual([entry["attack"] for _, entry in entries], [13, 20, 27, 34])

    def test_building_rows_share_dates_and_preserve_chained_requirements(self):
        stages = [
            (1800, "Fixture Workshop", 3, "industry", 11, 7, 5, 13, 2, 1,
             (1, 1, {}), {"numbered": False, "req": "null"}),
            (1820, "Fixture Factory", 4, "industry", 23, 11, 7, 31, 5, 3,
             (3, 6, {"cost_materials": 9, "prod_materials": 7, "prod_fuel": 2}), {}),
        ]
        with patch.object(recipes, "BUILDING_RECIPES", [stages]):
            entries = recipes.BuildingChain(stages).entries()
            _, research = recipes.research_recipe((recipes.building_years("Fixture Factory"),
                                                  "fixture_factory", "INDUSTRY", 37, {}, {}))
        self.assertEqual([name for name, _ in entries],
                         ["Fixture Workshop", "Fixture Factory 1", "Fixture Factory 2", "Fixture Factory 3"])
        self.assertEqual([entry["req"] for _, entry in entries],
                         ["null", "Fixture Workshop", "Fixture Factory 1", "Fixture Factory 2"])
        self.assertEqual([entry["cost_materials"] for _, entry in entries], [11, 23, 32, 41])
        self.assertEqual([entry["prod_materials"] for _, entry in entries], [13, 31, 38, 45])
        self.assertEqual([entry["prod_fuel"] for _, entry in entries], [1, 3, 5, 7])
        self.assertEqual(research["years"], [1820, 1826, 1832])
        self.assertEqual(research["max_lvl"], 3)

    def test_undated_building_row_emits_its_first_numbered_level_once(self):
        row = (None, "Fixture Fort", 2, "fortification", 17, 0, 0, 0, 0, 0,
               (3, 1, {"cost_materials": 7}), {})
        entries = recipes.BuildingChain([row]).entries()
        self.assertEqual([name for name, _ in entries], ["Fixture Fort 1", "Fixture Fort 2", "Fixture Fort 3"])
        self.assertEqual([entry["req"] for _, entry in entries], [None, "Fixture Fort 1", "Fixture Fort 2"])
        self.assertEqual([entry["cost_materials"] for _, entry in entries], [17, 24, 31])

    def test_source_rows_and_runtime_research_share_dates_and_level_counts(self):
        for rows in (recipes.LAND_UNIT_RECIPES, recipes.NAVAL_UNIT_RECIPES, recipes.AIR_UNIT_RECIPES):
            for row in rows:
                name = row[1]
                family = next(family for block in recipes.UNIT_SECTIONS for family in block if family.prefix == name)
                with self.subTest(unit=name):
                    self.assertEqual(self.tree[family.research_key]["years"], recipes.unit_years(name))
                    self.assertEqual(len(family.entries()), row[-2][0])
                    self.assertEqual(self.tree[family.research_key]["max_lvl"], len(family.entries()))
        for stages in recipes.BUILDING_RECIPES:
            for row in stages:
                if row[0] is None:
                    continue
                # Building-to-technology lookup is the same boundary used by runtime production.
                name = row[1] if not row[-1].get("numbered", True) else row[1] + " 1"
                tech, _ = queries.get_building_required_tech(name)
                with self.subTest(building=name):
                    self.assertEqual(self.tree[tech]["years"], recipes.building_years(row[1]))

    def test_equipment_profiles_generate_units_without_growth_formulas(self):
        first = {"health": 120, "attack": 17, "defense": 3, "speed": 2,
                 "cost_materials": 41, "cost_manpower": 11, "cost_fuel": 5,
                 "production_time": 6}
        second = {"health": 90, "attack": 31, "defense": 8, "speed": 1,
                  "cost_materials": 23, "cost_manpower": 19, "cost_fuel": 0,
                  "production_time": 4}
        stages = [(1800, "Fixture First Stage", 120, 17, 3, 2, 41, 11, 5, 6, None),
                  (1810, "Fixture Second Stage", 90, 31, 8, 1, 23, 19, 0, 4, None)]
        with patch.dict(recipes.EQUIPMENT_STAGES, {"infantry_type": stages}):
            entries = recipes.equipment_family("Infantry Type", "infantry_type").entries()
        for stage, profile, (name, entry) in zip(stages, (first, second), entries):
            year, label = stage[:2]
            with self.subTest(stage=label):
                self.assertEqual(name, label)
                self.assertEqual({field: entry[field] for field in recipes.UNIT_STAT_KEYS},
                                 {**{field: profile[field] for field in recipes.UNIT_STAT_KEYS}, "cost_fuel": 0})
                self.assertEqual(entry["metadata"]["research"], {"tech": "infantry_type", "year": year})

    def test_vehicle_variants_derive_stats_from_base_infantry_without_changing_the_base(self):
        base = {"health": 113, "attack": 80, "defense": 9, "speed": 1,
                "cost_materials": 41, "cost_manpower": 13, "cost_fuel": 7,
                "production_time": 5}
        expected = {"Motorized Infantry Type": (61.5, 80, 9),
                    "Mechanized Infantry Type": (82, 80, 16),
                    "Infantry Fighting Vehicle Type": (123, 120, 24)}
        values = (113, 80, 9, 1, 41, 13, 7, 5, None)
        stages = [(recipes.INFANTRY_VARIANT_FIRST_YEAR - 1, "Fixture Earlier Infantry", *values),
                  (recipes.INFANTRY_VARIANT_FIRST_YEAR, "Fixture Infantry", *values)]
        original = list(stages)
        with patch.dict(recipes.EQUIPMENT_STAGES, {"infantry_type": stages}):
            foot = recipes.equipment_family("Infantry Type", "infantry_type").entries()[0][1]
            self.assertEqual(foot["cost_fuel"], 0)
            self.assertEqual(queries.get_unit_upkeep(foot)["fuel"], 0)
            for family, (materials, attack, defense) in expected.items():
                with self.subTest(family=family):
                    entries = recipes.equipment_family(family, "infantry_type").entries()
                    self.assertEqual(len(entries), 1)
                    entry = entries[0][1]
                    self.assertEqual((entry["cost_materials"], entry["attack"], entry["defense"]),
                                     (materials, attack, defense))
                    self.assertEqual(entry["speed"], 2)
                    for field in ("health", "cost_manpower", "cost_fuel", "production_time"):
                        self.assertEqual(entry[field], base[field])
            self.assertEqual(stages, original)

    def test_generated_vehicle_profiles_match_each_stages_base_and_shared_rules(self):
        checked = set()
        for stage in recipes.expanded_equipment_stages("infantry_type"):
            year = stage[0]
            if year < recipes.INFANTRY_VARIANT_FIRST_YEAR:
                continue
            columns = dict(zip(recipes.EQUIPMENT_COLUMNS, stage[2:], strict=True))
            for family in recipes.INFANTRY_VARIANT_RULES:
                expected = recipes.equipment_profile(family, stage)
                name = queries.get_unit_for_family_tier(self.library, family, year)
                with self.subTest(unit=name):
                    self.assertIsNotNone(name)
                    checked.add(name)
                    for field in recipes.UNIT_STAT_KEYS:
                        self.assertEqual(self.library[name][field], expected[field])
                    self.assertEqual(self.library[name]["cost_fuel"], columns["FUEL"])
        self.assertTrue(checked)
        self.assertEqual(checked, {name for name, stats in self.library.items()
                                  if stats["metadata"]["family"] in recipes.INFANTRY_VARIANT_RULES})

    def test_vehicle_multiplier_rounds_float_artifacts_and_keeps_fractions(self):
        stage = (1905, "Fixture Infantry", 100, 131, 0, 1, 41, 50, 6, 2, None)
        rule = {"speed": 2, "material_multiplier": 0.3, "attack_multiplier": 1.5,
                "defense_multiplier": 0.2}
        with patch.dict(recipes.INFANTRY_VARIANT_RULES, {"Fixture Vehicle": rule}):
            profile = recipes.equipment_profile("Fixture Vehicle", stage)
        self.assertEqual(profile["defense"], 26.2)
        self.assertEqual(profile["cost_materials"], 12.3)
        self.assertEqual(profile["attack"], 196.5)

    def test_infantry_upgrade_row_generates_units_and_research(self):
        stages = [(1905, "Fixture Infantry", 100, 20, 3, 1, 40, 50, 6, 2, None,
                   (3, 2, {"health": 7, "attack": 4, "cost_materials": 3})),
                  (1912, "Next Infantry", 150, 40, 3, 1, 60, 50, 6, 2, None,
                   (1, 1, {}))]
        with patch.dict(recipes.EQUIPMENT_STAGES, {"infantry_type": stages}):
            entries = recipes.equipment_family("Infantry Type", "infantry_type").entries()
            research = recipes.extend_infantry_research("infantry_type", {})
            vehicles = recipes.equipment_family("Motorized Infantry Type", "infantry_type").entries()
        self.assertEqual([name for name, _ in entries],
                         ["Fixture Infantry I", "Fixture Infantry II", "Fixture Infantry III", "Next Infantry I"])
        self.assertEqual(research["years"], [1905, 1907, 1909, 1912])
        self.assertEqual([(entry["health"], entry["attack"], entry["cost_materials"]) for _, entry in entries],
                         [(100, 20, 40), (107, 24, 43), (114, 28, 46), (150, 40, 60)])
        self.assertEqual([entry["attack"] for _, entry in vehicles], [20, 24, 28, 40])

    def test_infantry_upgrade_years_cannot_overlap_next_stage(self):
        stages = [(1800, "First", 100, 20, 0, 1, 40, 50, 0, 2, None, (3, 5, {})),
                  (1810, "Second", 100, 20, 0, 1, 40, 50, 0, 2, None, (1, 1, {}))]
        with patch.dict(recipes.EQUIPMENT_STAGES, {"infantry_type": stages}):
            with self.assertRaisesRegex(ValueError, "before the next stage"):
                recipes.expanded_equipment_stages("infantry_type")

    def test_other_equipment_upgrades_share_expansion_research_and_variant_rules(self):
        families = {"militia": ("Militia",), "cavalry": ("Cavalry",),
                    "artillery": ("Artillery", "Heavy Artillery")}
        for tech, prefixes in families.items():
            stages = [(1800, "Fixture Equipment", 123, 13, 4, 3, 41, 19, 7, 4, 17,
                       (3, 2, {"health": 7, "attack": 3, "cost_materials": 5, "bombard_attack": 4})),
                      (1810, "Next Equipment", 150, 29, 6, 2, 67, 23, 9, 5, 31, (1, 1, {}))]
            with self.subTest(tech=tech), patch.dict(recipes.EQUIPMENT_STAGES, {tech: stages}):
                expanded = recipes.expanded_equipment_stages(tech)
                expected_names = ["Fixture Equipment I", "Fixture Equipment II",
                                  "Fixture Equipment III", "Next Equipment I"]
                self.assertEqual([row[:2] for row in expanded], list(zip([1800, 1802, 1804, 1810], expected_names)))
                self.assertEqual([row[2] for row in expanded], [123, 130, 137, 150])
                self.assertEqual([row[3] for row in expanded], [13, 16, 19, 29])
                self.assertEqual([row[6] for row in expanded], [41, 46, 51, 67])
                self.assertEqual([row[-1] for row in expanded], [17, 21, 25, 31])
                research = recipes.extend_infantry_research(tech, {})
                self.assertEqual(research["years"], [1800, 1802, 1804, 1810])
                self.assertEqual(research["max_lvl"], len(expected_names))
                self.assertEqual(research["level_names"],
                                 {str(i): name for i, name in enumerate(expected_names, 1)})
                for prefix in prefixes:
                    entries = recipes.equipment_family(prefix, tech).entries()
                    self.assertEqual([name for name, _ in entries],
                                     [("Heavy " if prefix == "Heavy Artillery" else "") + name
                                      for name in expected_names])
                    for row, (_, entry) in zip(expanded, entries):
                        profile = recipes.equipment_profile(prefix, row)
                        for field, value in profile.items():
                            self.assertEqual(entry[field], value)
                        self.assertEqual(entry["metadata"]["research"], {"tech": tech, "year": row[0]})

    def test_other_equipment_upgrade_years_cannot_overlap_next_stage(self):
        stages = [(1800, "First", 100, 20, 0, 1, 40, 50, 0, 2, 10, (3, 5, {})),
                  (1810, "Second", 100, 20, 0, 1, 40, 50, 0, 2, 10, (1, 1, {}))]
        for tech in ("militia", "cavalry", "artillery"):
            with self.subTest(tech=tech), patch.dict(recipes.EQUIPMENT_STAGES, {tech: stages}):
                with self.assertRaisesRegex(ValueError, "before the next stage"):
                    recipes.expanded_equipment_stages(tech)

    def test_all_equipment_runtime_levels_match_their_base_rows_and_increases(self):
        families = {"infantry_type": ("Infantry Type",), "militia": ("Militia",),
                    "cavalry": ("Cavalry",), "artillery": ("Artillery", "Heavy Artillery")}
        for tech, prefixes in families.items():
            expected_years = []
            expected_names = []
            for year, name, *values in recipes.EQUIPMENT_STAGES[tech]:
                levels, interval, increases = values.pop()
                base = recipes.table_values(recipes.EQUIPMENT_COLUMNS, values)
                for level in range(levels):
                    upgrade_year = year + interval * level
                    label = f"{name} {c.ROMAN_NUMERALS[level + 1]}"
                    expected_years.append(upgrade_year)
                    expected_names.append(label)
                    profile = [base[field] + increases.get(field, 0) * level if base[field] is not None else None
                               for field in recipes.EQUIPMENT_COLUMNS.values()]
                    for prefix in prefixes:
                        unit_name = ("Heavy " if prefix == "Heavy Artillery" else "") + label
                        with self.subTest(unit=unit_name):
                            entry = self.library[unit_name]
                            expected = recipes.equipment_profile(prefix, (upgrade_year, label, *profile))
                            for field, value in expected.items():
                                self.assertEqual(entry[field], value)
                            self.assertEqual(entry["metadata"]["research"], {"tech": tech, "year": upgrade_year})
            self.assertEqual(self.tree[tech]["years"], expected_years)
            self.assertEqual(self.tree[tech]["level_names"],
                             {str(i): name for i, name in enumerate(expected_names, 1)})

    def test_unnumbered_equipment_names_migrate_to_each_stages_first_level(self):
        aliases = migrations.equipment_stage_aliases()
        for tech in ("militia", "cavalry", "artillery"):
            for row in recipes.EQUIPMENT_STAGES[tech]:
                prefixes = ("", "Heavy ") if tech == "artillery" else ("",)
                for prefix in prefixes:
                    older = prefix + row[1]
                    with self.subTest(unit=older):
                        self.assertEqual(aliases[older], older + " I")
                        self.assertIn(aliases[older], self.library)

    def test_organized_militia_covers_the_period_before_modern_militia(self):
        stages = recipes.EQUIPMENT_STAGES["militia"]
        organized_index = next(i for i, stage in enumerate(stages) if stage[1] == "Organized Militia")
        stage = stages[organized_index]
        next_year = stages[organized_index + 1][0]
        _, interval, _ = stage[-1]
        organized_years = [stats["metadata"]["tier_order"] for name, stats in self.library.items()
                           if name.startswith("Organized Militia ")]
        self.assertEqual(organized_years, list(range(stage[0], next_year, interval)))
        self.assertFalse(any(name.startswith("Reserve Infantry") for name in self.library))
        for field in ("level_names", "level_icons"):
            self.assertFalse(any(name.startswith("Reserve Infantry")
                                 for name in self.tree["militia"][field].values()))

    def test_added_equipment_levels_preserve_saved_years_history_and_unfinished_points(self):
        for tech in ("militia", "cavalry", "artillery"):
            source_years = [row[0] for row in recipes.EQUIPMENT_STAGES[tech]]
            for level, year in enumerate(source_years, 1):
                country = {"research": {tech: level},
                           "research_queue": [{"tech_name": tech, "points_remaining": 73}],
                           "research_progress": {tech: 73}}
                saved = {"research_years": {tech: source_years}, "default_research": {tech: level},
                         "nation_data": {"A": country}}
                history = {"1": {"nation_data": {"A": copy.deepcopy(country)}}}
                with self.subTest(tech=tech, year=year):
                    migrations.migrate_infantry_research(saved, self.tree, history)
                    expected = sum(value <= year for value in self.tree[tech]["years"])
                    self.assertEqual(country["research"], {tech: expected})
                    self.assertEqual(saved["default_research"], {tech: expected})
                    self.assertEqual(history["1"]["nation_data"]["A"], country)
                    self.assertEqual(country["research_queue"], [{"tech_name": tech, "points_remaining": 73}])
                    self.assertEqual(country["research_progress"], {tech: 73})
                    restored = json.loads(json.dumps(saved))
                    migrations.migrate_infantry_research(restored, self.tree)
                    self.assertEqual(restored, saved)

    def test_heavy_artillery_is_generated_from_independent_base_attack_and_bombardment(self):
        base = {"health": 123, "attack": 13, "bombard_attack": 17, "defense": 4, "speed": 3,
                "cost_materials": 41, "cost_manpower": 19, "cost_fuel": 7,
                "production_time": 4}
        stages = [(1800, "Fixture Artillery", 123, 13, 4, 3, 41, 19, 7, 4, 17)]
        with patch.dict(recipes.EQUIPMENT_STAGES, {"artillery": stages}):
            name, heavy = recipes.equipment_family("Heavy Artillery", "artillery").entries()[0]
        self.assertEqual(name, "Heavy Fixture Artillery")
        self.assertEqual((heavy["attack"], heavy["bombard_attack"], heavy["cost_materials"], heavy["production_time"]),
                         (26, 34, 82, 7))
        for field in ("health", "defense", "speed", "cost_manpower", "cost_fuel"):
            self.assertEqual(heavy[field], base[field])

    def test_ongoing_unit_tracks_match_their_content_dates_within_the_timeline(self):
        tracks = ('infantry_type', 'militia', 'artillery', 'armored_car', 'light_tank',
                  'main_battle_tank', 'carrack', 'ironclad', 'pre-dreadnought',
                  'dreadnought', 'battleship', 'destroyer', 'submarine', 'aircraft_carrier',
                  'jet_fighter', 'jet_bomber', 'jet_transport')
        for key in tracks:
            with self.subTest(tech=key):
                entry = self.tree[key]
                years = entry['years']
                self.assertEqual(entry['max_lvl'], len(years))
                self.assertEqual(years, sorted(set(years)))
                self.assertGreaterEqual(years[0], c.START_YEAR)
                self.assertLessEqual(years[-1], c.END_YEAR)
                # Content can cover only part of the playable timeline.
                # Every dated research level must still unlock equipment.
                equipment_levels = {
                    queries.get_unit_research_requirement(name, self.library)[1]
                    for name, stats in self.library.items()
                    if stats['metadata']['research']['tech'] == key}
                self.assertEqual(equipment_levels, set(range(1, entry['max_lvl'] + 1)))

    def test_final_unit_tiers_agree_for_unlocks_upgrades_and_ai(self):
        research = self.final_research()
        candidates = ai_unit_eval.buildable_units(research, self.library)
        for family, tiers in queries.get_unit_research_index(self.library):
            if len(tiers) < 2:
                continue
            latest = tiers[0][0]
            previous = tiers[1][0]
            with self.subTest(family=family):
                self.assertTrue(queries.is_unit_unlocked(latest, research, self.library))
                self.assertEqual(queries.get_upgrade_target(previous, research, self.library, self.tree), latest)
                if queries.is_unit_obsolete(family, research):
                    continue
                self.assertIn(latest, candidates)
                tech, level = queries.get_unit_research_requirement(latest, self.library)
                if tech in c.VEHICLE_INFANTRY_GATES:
                    tech = 'infantry_type'
                    level = research[tech]
                before = dict(research, **{tech: level - 1})
                self.assertFalse(queries.is_unit_unlocked(latest, before, self.library))
                self.assertIn(latest, ai_tech_eval.units_unlocked_by(tech, before, self.library))

    def test_latest_units_and_research_survive_save_data_round_trip(self):
        game = sample_map_screen()
        research = self.final_research()
        units = [queries.create_unit_dict(name, game.player_country, self.library)
                 for name in ai_unit_eval.buildable_units(research, self.library)]
        game.time_manager.year = c.END_YEAR
        game.nation_data[game.player_country]['research'] = research
        province = next(iter(game.map_data.values()))
        province['units'] = units
        saved = json.loads(json.dumps(queries.build_save_dict(game)))
        loaded_provinces = queries.map_data_with_saved_provinces(game.raw_json_data, saved['provinces'])
        self.assertEqual(saved['date']['year'], c.END_YEAR)
        loaded_research = saved['nation_data'][game.player_country]['research']
        self.assertEqual(loaded_research, research)
        loaded_units = next(iter(loaded_provinces.values()))['units']
        self.assertEqual(loaded_units, units)
        for unit in loaded_units:
            self.assertTrue(queries.is_unit_unlocked(unit['type'], loaded_research, self.library))
