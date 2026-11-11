"""Map defaults for Unit / Building Stats: per-category Use Defaults, conversion, map editor deletion, and the unit brush."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from data import migrations, queries
from data.runtime_rules import RuntimeRules, rebuild
from tests import app_harness
from tests.air_fixtures import tile, world


def fixture_libraries():
    """Artificial units of one family with two levels, and no buildings."""
    unit = {"health": 10, "attack": 1, "defense": 0, "speed": 1, "cost_materials": 1, "cost_manpower": 1,
            "cost_fuel": 0, "production_time": 2, "naval_unit": False}
    return {"unit_library": {"Fixture Gun I": dict(unit), "Fixture Gun II": dict(unit)},
            "building_library": {}, "tech_tree": {}}


def real_family_units():
    """Return a unit family from the complete library and its unit names."""
    library = queries.get_unit_library()
    family = queries.get_base_item_name(next(iter(library)))
    return family, [name for name in library if queries.get_base_item_name(name) == family]


class CategorySettingTests(unittest.TestCase):
    MAP = {"unit_turn_overrides": {"Fixture Gun": 7}, "unit_disabled": ["Other"]}
    PLAYER = {"unit_turn_overrides": {"Fixture Gun": 3}}

    def test_use_defaults_selects_the_map_or_the_player_for_each_category(self):
        settings = dict(self.PLAYER, map_defaults=self.MAP)
        self.assertEqual(queries.get_category_setting(settings, "unit_turn_overrides", {}), {"Fixture Gun": 7})
        settings["use_default_units"] = False
        self.assertEqual(queries.get_category_setting(settings, "unit_turn_overrides", {}), {"Fixture Gun": 3})
        # The map editor always reads the map's own defaults.
        self.assertEqual(queries.get_category_setting(settings, "unit_turn_overrides", {}, map_editor=True),
                         {"Fixture Gun": 7})
        # Another category keeps its own Use Defaults.
        self.assertEqual(queries.get_category_setting(
            dict(settings, administrative_disabled=["Remove Cores"]), "administrative_disabled", []), [])

    def test_missing_or_malformed_map_values_use_the_library(self):
        for map_defaults in (None, [], "bad", {}):
            with self.subTest(map_defaults=map_defaults):
                settings = dict(self.PLAYER, map_defaults=map_defaults)
                self.assertEqual(queries.get_category_setting(settings, "unit_turn_overrides", {}), {})

    def test_rebuild_applies_the_values_that_apply(self):
        for flag, turns in ((True, 7), (False, 3)):
            with self.subTest(use_default_units=flag):
                runtime = RuntimeRules()
                settings = dict(self.PLAYER, map_defaults={"unit_turn_overrides": {"Fixture Gun": 7}},
                                use_default_units=flag)
                runtime.rebuild(settings, copy.deepcopy(fixture_libraries()))
                self.assertEqual(runtime.libraries["unit_library"]["Fixture Gun II"]["production_time"], turns)
        # A map default can disable a family. Saved settings stay unchanged.
        settings = {"map_defaults": {"unit_disabled": ["Fixture Gun"]}}
        runtime = RuntimeRules()
        runtime.rebuild(settings, copy.deepcopy(fixture_libraries()))
        self.assertNotIn("Fixture Gun I", runtime.libraries["unit_library"])
        self.assertEqual(settings, {"map_defaults": {"unit_disabled": ["Fixture Gun"]}})

    def test_administrative_and_conversion_rules_read_the_values_that_apply(self):
        name = queries.ADMINISTRATIVE_ACTIONS["CORE"][0]
        default = queries.get_administrative_turns("CORE", {})
        settings = {"administrative_turn_overrides": {name: default + 1},
                    "map_defaults": {"administrative_turn_overrides": {name: default + 2},
                                     "administrative_disabled": [name]}}
        self.assertEqual(queries.get_administrative_turns("CORE", settings), default + 2)
        self.assertFalse(queries.is_administrative_action_enabled("CORE", settings))
        settings["use_default_other"] = False
        self.assertEqual(queries.get_administrative_turns("CORE", settings), default + 1)
        self.assertTrue(queries.is_administrative_action_enabled("CORE", settings))


class ScenarioSettingsConversionTests(unittest.TestCase):
    def test_older_settings_keep_their_values_and_current_settings_do_not_change(self):
        older = {"unit_turn_overrides": {"Fixture Gun": 3}, "unit_disabled": [], "unit_range_overrides": {}}
        migrations.convert_scenario_settings(older)
        self.assertIs(older["use_default_units"], False)
        # Categories without values keep the map's defaults.
        for key in ("use_default_buildings", "use_default_range", "use_default_other"):
            self.assertNotIn(key, older)
        current = {"unit_turn_overrides": {"Fixture Gun": 3}, "use_default_units": True}
        migrations.convert_scenario_settings(current)
        self.assertEqual(current, {"unit_turn_overrides": {"Fixture Gun": 3}, "use_default_units": True})

    def test_saves_and_the_player_settings_file_convert_on_load(self):
        meta = {"scenario_settings": {"unit_range_overrides": {"Fixture Gun": {"bombard_range": 4}}}}
        migrations.upgrade_save(meta, {})
        self.assertIs(meta["scenario_settings"]["use_default_range"], False)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "scenario_settings.json")
            path.write_text(json.dumps({"building_disabled": ["Fort"]}), encoding="utf-8")
            entry = {"path": str(path), "data": None, "default": "scenario_settings.json"}
            with mock.patch.dict(queries._JSON_CACHE, {"scenario_settings": entry}):
                self.assertIs(queries.get_scenario_settings()["use_default_buildings"], False)


class UnitFamilyTests(unittest.TestCase):
    def test_stored_units_resolve_their_settings_family_from_the_complete_library(self):
        library = queries.get_unit_library()
        # A world's active library omits disabled families, so a name alone must not decide the family.
        name = next((name for name in library
                     if queries.get_base_item_name(name) != queries.base_item_name_from_text(name)), None)
        if name is None:
            self.skipTest("Every unit's settings family matches its name.")
        family = queries.get_base_item_name(name)
        unit = {"type": name}
        convoy = {"type": f"Convoy ({name})"}
        self.assertEqual(queries.get_stored_unit_family(unit), family)
        self.assertEqual(queries.get_stored_unit_family(convoy), family)
        province = {"units": [unit, {"type": "Other", "air_cargo": [convoy]}]}
        queries.remove_units_of_families(province, {family})
        self.assertEqual(province["units"], [{"type": "Other", "air_cargo": []}])


class MapEditorUnitDefaultsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.controller, cls.surface = app_harness.boot()

    def map_screen(self):
        family, names = real_family_units()
        game = world()
        game.is_editor = True
        province = tile(game, 7, 8, center=(10.4, 20.6))
        other = tile(game, 8, 20)
        library = queries.get_unit_library()
        province["units"] = [queries.create_unit_dict(names[0], "A", library),
                             queries.create_unit_dict(names[-1], "A", library)]
        other_family = next(name for name in library if queries.get_base_item_name(name) != family)
        other["units"] = [queries.create_unit_dict(other_family, "A", library)]
        game.refresh_all_maps = mock.Mock()
        game.show_feedback = mock.Mock()
        return game, family

    def open_editor(self, game):
        from screens.editors.unit_stats_editor import MapUnitBuildingStatsScreen
        with mock.patch("ui.navigation.modal_screen.host_map_screen", return_value=game):
            return MapUnitBuildingStatsScreen(game)

    def test_disabling_a_unit_on_the_map_asks_and_lists_where_its_units_are(self):
        game, family = self.map_screen()
        screen = self.open_editor(game)
        with mock.patch("ui.dialogs.ask_yes_no", side_effect=lambda _t, _m, cb: cb(False)) as ask:
            screen.toggle_disabled("unit", family)
        message = ask.call_args.args[1]
        self.assertIn("2 units", message)
        self.assertIn("Province 7", message)
        self.assertIn("10, 21", message)
        self.assertNotIn(family, screen.turn_tabs["unit"]["disabled_set"])
        with mock.patch("ui.dialogs.ask_yes_no", side_effect=lambda _t, _m, cb: cb(True)):
            screen.toggle_disabled("unit", family)
        self.assertIn(family, screen.turn_tabs["unit"]["disabled_set"])
        # Enabling again does not ask.
        with mock.patch("ui.dialogs.ask_yes_no") as ask:
            screen.toggle_disabled("unit", family)
        ask.assert_not_called()

    def test_saving_deletes_units_of_disabled_families_and_back_keeps_them(self):
        game, family = self.map_screen()
        screen = self.open_editor(game)
        with mock.patch("ui.dialogs.ask_yes_no", side_effect=lambda _t, _m, cb: cb(True)):
            screen.toggle_disabled("unit", family)
        screen.handle_back_key()
        self.assertEqual(len(game.id_to_province[7]["units"]), 2)
        self.assertNotIn("map_defaults", game.scenario_settings)
        screen = self.open_editor(game)
        with mock.patch("ui.dialogs.ask_yes_no", side_effect=lambda _t, _m, cb: cb(True)):
            screen.toggle_disabled("unit", family)
        screen.save_all()
        self.assertEqual(game.id_to_province[7]["units"], [])
        self.assertEqual(len(game.id_to_province[8]["units"]), 1)
        self.assertEqual(game.scenario_settings["map_defaults"]["unit_disabled"], [family])
        game.refresh_all_maps.assert_called_once()
        # The map editor's libraries apply the map's defaults.
        self.assertNotIn(family, {queries.get_base_item_name(name) for name in queries.get_unit_library(game)})

    def test_unit_brush_lists_disabled_units_as_disabled(self):
        from screens.editors import menus
        from screens.game import map_input
        game, family = self.map_screen()
        _family, names = real_family_units()
        game.scenario_settings["map_defaults"] = {"unit_disabled": [family]}
        rebuild(game)
        with mock.patch("ui.dialogs.pickers.open_listbox_selector") as picker:
            menus.select_unit_brush(game)
        items = picker.call_args.args[3]
        is_enabled = picker.call_args.kwargs["is_enabled"]
        disabled = [item for item in items if isinstance(item, tuple) and item[1] in names]
        self.assertEqual(len(disabled), len(names))
        self.assertFalse(any(is_enabled(item) for item in disabled))
        self.assertTrue(is_enabled("None"))
        self.assertTrue(any(is_enabled(item) for item in items if isinstance(item, tuple)))
        # The Spawn Unit picker of a scripted event lists disabled units as disabled too.
        from screens.editors import scripted_events_editor
        from ui.widgets import text_utils
        enabled = next(name for name in queries.get_unit_library(game))
        game.nation_data["A"]["scripted_events"] = [{"actions": [{"type": "Spawn Unit", "unit_type": enabled}]}]
        with mock.patch("ui.navigation.modal_screen.host_map_screen", return_value=game):
            event_screen = scripted_events_editor._EventEditScreen(game, game, "A", 0)
        label = text_utils.truncate_chars(queries.get_unit_display_name(enabled, context=game), 26)
        combo = next(element for element in event_screen.elements if getattr(element, "text", "") == label)
        with mock.patch("ui.dialogs.pickers.open_listbox_selector") as picker:
            combo.callback()
        items, is_enabled = picker.call_args.args[3], picker.call_args.kwargs["is_enabled"]
        self.assertFalse(any(is_enabled(item) for item in items if item[1] in names))
        self.assertEqual(len([item for item in items if item[1] in names]), len(names))
        self.assertTrue(is_enabled(next(item for item in items if item[1] == enabled)))
        # A brush picked before the family was disabled places nothing.
        game.brush_unit = names[0]
        province = game.id_to_province[8]
        before = list(province["units"])
        self.assertFalse(map_input._place_unit_with_brush(game, province))
        self.assertEqual(province["units"], before)


if __name__ == "__main__":
    unittest.main()
