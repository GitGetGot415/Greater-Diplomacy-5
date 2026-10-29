"""Check generated unit progression through shared gameplay interfaces."""

import json
import unittest
from pathlib import Path
from unittest.mock import patch

from data import constants as c, queries
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
                              (c.RESEARCH_TEMPLATE_PATH, generate_data.build_research_template_text)):
            with self.subTest(path=path):
                self.assertEqual(json.loads(Path(path).read_text(encoding='utf-8')), json.loads(builder()))

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
                  'main_battle_tank', 'destroyer', 'submarine', 'aircraft_carrier',
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
            latest, _, requirement = tiers[0]
            previous = tiers[1][0]
            # Some historical families retain library tiers beyond their research cap.
            if not queries.unit_requirement_is_met(requirement, research):
                continue
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
