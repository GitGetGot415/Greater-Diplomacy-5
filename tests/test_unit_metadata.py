"""Check content identity and compound requirements with artificial libraries."""

import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import patch

from data import migrations, queries
from map_logic.ai import ai_research, ai_tech_eval, ai_unit_eval


def fixture_metadata(*, family="Fixture", tier=1, level=1):
    return {"family": family, "tier_order": tier,
            "research": {"tech": "fixture_track", "level": level},
            "requirements": [{"tech": "fixture_track", "level": level}],
            "recruitment": {"industry": "none", "coastal": False}}


class UnitMetadataTests(unittest.TestCase):
    def test_custom_identifiers_use_metadata_for_families_tiers_unlocks_and_upgrades(self):
        library = {"strange designation": {"metadata": fixture_metadata(tier=3)},
                   "a second design": {"metadata": fixture_metadata(tier=7, level=2)}}
        with patch.object(queries, "get_unit_library", return_value=library):
            self.assertEqual(queries.get_base_unit_name("strange designation"), "Fixture")
            self.assertEqual(queries.get_unit_tier("a second design"), 7)
            self.assertEqual(ai_unit_eval.buildable_units({"fixture_track": 1}, library), ["strange designation"])
            self.assertEqual(queries.get_upgrade_target("strange designation", {"fixture_track": 2}, library, {}),
                             "a second design")

    def test_compound_year_and_gate_requirements_are_explicit(self):
        metadata = fixture_metadata()
        metadata["requirements"] = [{"tech": "fixture_gate", "level": 1},
                                    {"tech": "fixture_years", "minimum_year": 2020}]
        library = {"custom carrier infantry": {"metadata": metadata}}
        with patch.object(queries, "get_tech_tree", return_value={"fixture_years": {"years": [2000, 2020]}}):
            for research, expected in (({"fixture_years": 2}, False),
                                       ({"fixture_gate": 1, "fixture_years": 1}, False),
                                       ({"fixture_gate": 1, "fixture_years": 2}, True)):
                self.assertEqual(queries.is_unit_unlocked("custom carrier infantry", research, library), expected)

    def test_in_place_metadata_and_year_edits_invalidate_indexes(self):
        metadata = fixture_metadata()
        metadata["research"] = {"tech": "custom_years", "year": 2020}
        metadata["requirements"] = [metadata["research"].copy()]
        library = {"custom": {"metadata": metadata}}
        tree = {"custom_years": {"years": [2000, 2020]}}
        with patch.object(queries, "get_tech_tree", return_value=tree):
            self.assertEqual(ai_unit_eval.buildable_units({"custom_years": 1}, library), [])
            tree["custom_years"]["years"].reverse()
            self.assertEqual(ai_unit_eval.buildable_units({"custom_years": 1}, library), ["custom"])
            metadata["requirements"] = [{"tech": "locked", "level": 1}]
            self.assertEqual(ai_unit_eval.buildable_units({"custom_years": 1}, library), [])
            library.clear()
            self.assertEqual(ai_unit_eval.buildable_units({"locked": 1}, library), [])

    def test_research_pass_checks_the_library_once_and_refreshes_after_an_edit(self):
        library = {
            name: {"metadata": fixture_metadata(tier=level, level=level), "attack": level * 10,
                   "health": 100, "defense": 0, "speed": 1, "cost_materials": 100,
                   "cost_manpower": 100, "cost_fuel": 0, "production_time": 1, "naval_unit": False}
            for name, level in (("early", 1), ("later", 2))}
        tree = {key: {"max_lvl": 2, "cost": 100, "years": [2000, 2001], "req": {}}
                for key in ("fixture_track", "other")}
        research = {"fixture_track": 1}
        game = SimpleNamespace(map_data={}, time_manager=SimpleNamespace(year=2001), nation_data={
            name: {"research": dict(research), "research_queue": []} for name in ("A", "B")})
        with ExitStack() as stack:
            for name, result in (("get_tech_tree", tree), ("get_unit_library", library),
                                 ("get_building_library", {}), ("calculate_all_economies", {}),
                                 ("get_active_ai_nations", ["A", "B"])):
                stack.enter_context(patch.object(queries, name, return_value=result))
            stack.enter_context(patch.object(ai_research.ai_world, "for_screen", return_value=None))
            checks = stack.enter_context(patch.object(queries, "get_unit_research_index",
                                                     wraps=queries.get_unit_research_index))
            ai_research.process_ai_research(game)
            self.assertEqual(checks.call_count, 1)
            self.assertEqual(game.nation_data["A"]["research_queue"], game.nation_data["B"]["research_queue"])
            self.assertEqual({project["tech_name"] for project in game.nation_data["A"]["research_queue"]},
                             set(tree))
            self.assertEqual(ai_tech_eval.units_unlocked_by("fixture_track", research, library), ("later",))
            checks.reset_mock()
            library["later"]["metadata"]["requirements"].append({"tech": "locked", "level": 1})
            for country in game.nation_data.values():
                country["research_queue"].clear()
            ai_research.process_ai_research(game)
            self.assertEqual(checks.call_count, 1)
            self.assertEqual(ai_tech_eval.units_unlocked_by("fixture_track", research, library), ())

    def test_legacy_content_is_adapted_without_overwriting_explicit_or_unknown_fields(self):
        old = migrations.legacy_unit_metadata("Fixture Model XII", {})
        self.assertEqual((old["family"], old["tier_order"]), ("Fixture Model", 12))
        explicit = fixture_metadata(family="Custom 2040", tier=9)
        explicit["future_field"] = {"keep": True}
        library = {"Fixture Model XII": {"metadata": explicit}}
        self.assertIs(queries.get_unit_metadata("Fixture Model XII", library), explicit)
        self.assertEqual(explicit["future_field"], {"keep": True})
        unit = queries.create_unit_dict("Fixture Model XII", "A", library)
        self.assertNotIn("metadata", unit)

    def test_older_requirement_tuple_remains_a_compatibility_adapter(self):
        library = {"Fixture Model XII": {}}
        self.assertEqual(queries.get_unit_unlock_requirement("Fixture Model XII", library),
                         ("fixture_model", 12, None))
        self.assertTrue(queries.unit_requirement_is_met(("fixture_model", 12, None), {"fixture_model": 12}))

    def test_invalid_explicit_metadata_is_actionable(self):
        for value in (None, {}, dict(fixture_metadata(), tier_order=-1)):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "Unit custom: metadata"):
                queries.get_unit_metadata("custom", {"custom": {"metadata": value}})
