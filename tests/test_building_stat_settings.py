"""Building cost and income settings: linear family stats, Use Defaults, map defaults, editors, loading, and lobbies."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from data import queries
import data.constants as c
from data.map import load_map
from data.multiplayer.realtime.session import MapRealtimeDriver
from data.queries import economy
from data.runtime_rules import RuntimeRules
from data.state_access import BackendState
from tests import app_harness
from tests.air_fixtures import world


def building_library():
    """Use artificial buildings: a linear three-level family and a single-level family."""
    base = {"time": 2, "req": None, "cost_materials": 100, "cost_manpower": 10, "cost_fuel": 1,
            "prod_materials": 50, "prod_manpower": 0, "prod_fuel": 5}
    return {
        "Fixture Factory Lvl 1": dict(base, group="industry"),
        "Fixture Factory Lvl 2": dict(base, group="industry", req="Fixture Factory Lvl 1",
                                      cost_materials=200, prod_materials=80),
        "Fixture Factory Lvl 3": dict(base, group="industry", req="Fixture Factory Lvl 2",
                                      cost_materials=300, prod_materials=110),
        "Fixture Fort": dict(base, group="fortification", prod_materials=0, prod_fuel=0),
    }


def rebuilt_buildings(settings):
    runtime = RuntimeRules()
    runtime.rebuild(settings, {"unit_library": {}, "building_library": building_library(), "tech_tree": {}})
    return runtime.libraries["building_library"]


MAP_STATS = {"Fixture Factory": {"prod_materials": 70, "cost_fuel_per_level": 2}}
PLAYER_STATS = {"Fixture Factory": {"prod_materials_per_level": 40}, "Fixture Fort": {"cost_materials": 400}}
#: A map's defaults block that sets only building stats.
MAP_DEFAULTS = {"building_stat_overrides": MAP_STATS}


class BuildingStatRulesTests(unittest.TestCase):
    def setUp(self):
        self.defaults = queries.get_building_stat_defaults(building_library())

    def test_defaults_give_level_one_values_and_increases_in_library_order(self):
        self.assertEqual(list(self.defaults), ["Fixture Factory", "Fixture Fort"])
        factory = self.defaults["Fixture Factory"]
        self.assertEqual((factory["cost_materials"], factory["cost_materials_per_level"]), (100, 100))
        self.assertEqual((factory["prod_materials"], factory["prod_materials_per_level"]), (50, 30))
        self.assertEqual((factory["cost_fuel"], factory["cost_fuel_per_level"]), (1, 0))
        # A single-level family has no increases.
        self.assertEqual(set(self.defaults["Fixture Fort"]), set(queries.BUILDING_STAT_FIELDS))

    def test_families_with_calculated_costs_have_no_cost_fields(self):
        with mock.patch.object(economy, "DYNAMIC_COST_BUILDINGS", frozenset({"Fixture Fort"})):
            fields = queries.get_building_stat_defaults(building_library())["Fixture Fort"]
            self.assertFalse(any(key.startswith("cost_") for key in fields))
            library = rebuilt_buildings({"use_default_buildings": False,
                                         "building_stat_overrides": {"Fixture Fort": {"cost_materials": 9}}})
        self.assertEqual(library["Fixture Fort"]["cost_materials"], 100)

    def test_overrides_keep_only_valid_changes(self):
        raw = {"Fixture Factory": {"prod_materials": 60, "cost_materials": 100, "prod_fuel": -1,
                                   "cost_fuel": 1.5, "cost_manpower": "8", "time": 9,
                                   "prod_materials_per_level": 0},
               "Fixture Fort": {"cost_materials": 0, "cost_materials_per_level": 5},
               "Unknown Building": {"cost_materials": 5}}
        self.assertEqual(queries.get_building_stat_overrides(raw, self.defaults), {
            "Fixture Factory": {"prod_materials": 60, "prod_materials_per_level": 0},
            "Fixture Fort": {"cost_materials": 0}})
        for invalid in (None, [], "bad", 5, {"Fixture Factory": "bad"}):
            self.assertEqual(queries.get_building_stat_overrides(invalid, self.defaults), {})

    def test_changed_fields_follow_level_one_value_plus_increase(self):
        library = rebuilt_buildings({"use_default_buildings": False, "building_stat_overrides": {
            "Fixture Factory": {"prod_materials_per_level": 40, "cost_materials": 500}}})
        self.assertEqual([library[f"Fixture Factory Lvl {level}"]["prod_materials"] for level in (1, 2, 3)],
                         [50, 90, 130])
        self.assertEqual([library[f"Fixture Factory Lvl {level}"]["cost_materials"] for level in (1, 2, 3)],
                         [500, 600, 700])
        # Unchanged fields keep their library values.
        self.assertEqual(library["Fixture Factory Lvl 3"]["cost_manpower"], 10)

    def test_use_defaults_selects_map_stats_and_ignores_player_stats(self):
        settings = {"map_defaults": MAP_DEFAULTS, "building_stat_overrides": PLAYER_STATS}
        for flag in (True, None):
            with self.subTest(flag=flag):
                case = dict(settings) if flag is None else dict(settings, use_default_buildings=flag)
                library = rebuilt_buildings(case)
                self.assertEqual(library["Fixture Factory Lvl 3"]["prod_materials"], 130)
                self.assertEqual(library["Fixture Factory Lvl 3"]["cost_fuel"], 5)
                self.assertEqual(library["Fixture Fort"], building_library()["Fixture Fort"])
        library = rebuilt_buildings(dict(settings, use_default_buildings=False))
        self.assertEqual(library["Fixture Factory Lvl 3"]["prod_materials"], 130)
        self.assertEqual(library["Fixture Factory Lvl 3"]["cost_fuel"], 1)
        self.assertEqual(library["Fixture Fort"]["cost_materials"], 400)
        self.assertEqual(rebuilt_buildings({}), building_library())

    def test_building_use_defaults_does_not_affect_unit_ranges(self):
        units = {"Fixture Gun I": {"bombard_range": 1, "bombard_attack": 5}}
        ranges = {"unit_range_overrides": {"Fixture Gun": {"bombard_range": 3}}, "use_default_range": False}
        for flag in (True, False):
            runtime = RuntimeRules()
            runtime.rebuild(dict(ranges, use_default_buildings=flag),
                            {"unit_library": copy.deepcopy(units), "building_library": {}, "tech_tree": {}})
            self.assertEqual(runtime.libraries["unit_library"]["Fixture Gun I"]["bombard_range"], 3)

    def test_production_and_income_read_applied_stats(self):
        library = rebuilt_buildings({"use_default_buildings": False, "building_stat_overrides": PLAYER_STATS})
        output = queries.get_building_output("Fixture Factory Lvl 2", {}, library)
        self.assertEqual(output["materials"], 90)

    def test_badge_reports_player_building_changes_only_without_use_defaults(self):
        with mock.patch.object(queries, "get_building_stat_defaults", return_value=self.defaults), \
                mock.patch.object(queries, "get_unit_range_defaults", return_value={}):
            custom = {"use_default_buildings": False}
            self.assertTrue(queries.scenario_has_unit_stat_customizations(
                dict(custom, building_stat_overrides=PLAYER_STATS)))
            self.assertFalse(queries.scenario_has_unit_stat_customizations(
                dict(custom, building_stat_overrides={"Fixture Fort": {"cost_materials": 100}})))
            self.assertFalse(queries.scenario_has_unit_stat_customizations(
                {"building_stat_overrides": PLAYER_STATS}))
            self.assertFalse(queries.scenario_has_unit_stat_customizations(
                dict(custom, map_defaults=MAP_DEFAULTS)))
        ranges = {"Fixture Gun": {"bombard_range": 3}}
        with mock.patch.object(queries, "get_unit_range_defaults", return_value={"Fixture Gun": {"bombard_range": 1}}):
            self.assertTrue(queries.scenario_has_unit_stat_customizations(
                {"unit_range_overrides": ranges, "use_default_range": False}))
            # Range uses the map's defaults by default, so the player's ranges do not count.
            self.assertFalse(queries.scenario_has_unit_stat_customizations({"unit_range_overrides": ranges}))


class BuildingStatPersistenceTests(unittest.TestCase):
    def test_global_settings_file_keeps_player_values_but_not_map_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "scenario_settings.json")
            path.write_text(json.dumps({"use_default_buildings": False}), encoding="utf-8")
            entry = {"path": str(path), "data": None, "default": "scenario_settings.json"}
            with mock.patch.dict(queries._JSON_CACHE, {"scenario_settings": entry}):
                loaded = queries.get_scenario_settings()
                queries.save_scenario_settings(dict(loaded, building_stat_overrides=PLAYER_STATS,
                                                    map_defaults=MAP_DEFAULTS))
            written = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(written["building_stat_overrides"], PLAYER_STATS)
        self.assertNotIn("map_defaults", written)

    def load_settings(self, player_settings, meta, *, new_game):
        context = BackendState()
        context.session.selection_mode = new_game
        context.world.scenario_settings = copy.deepcopy(player_settings)
        load_map._apply_saved_scenario_settings(context, copy.deepcopy(meta))
        return context.world.scenario_settings

    def test_new_games_take_map_defaults_from_the_map_only(self):
        player = {"use_default_buildings": True, "building_stat_overrides": PLAYER_STATS,
                  "map_defaults": {"building_stat_overrides": {"Fixture Fort": {"cost_materials": 1}}}}
        meta = {"scenario_settings": {"map_defaults": MAP_DEFAULTS,
                                      "building_stat_overrides": {"Fixture Fort": {"cost_fuel": 9}}}}
        settings = self.load_settings(player, meta, new_game=True)
        self.assertEqual(settings["map_defaults"], MAP_DEFAULTS)
        self.assertEqual(settings["building_stat_overrides"], PLAYER_STATS)
        for older_meta in ({"scenario_settings": {}}, {}):
            settings = self.load_settings(player, older_meta, new_game=True)
            self.assertNotIn("map_defaults", settings)
        # A save in progress keeps the settings it was created with.
        settings = self.load_settings(player, meta, new_game=False)
        self.assertEqual(settings, meta["scenario_settings"] | {
            "force_time_appropriate_research": c.DEFAULT_FORCE_TIME_APPROPRIATE_RESEARCH})

    def test_lobby_rules_keep_the_loaded_map_defaults(self):
        game = world()
        game.scenario_settings = {"map_defaults": MAP_DEFAULTS}
        driver = MapRealtimeDriver(game)
        lobby = {"use_default_buildings": False, "building_stat_overrides": PLAYER_STATS,
                 "map_defaults": {"building_stat_overrides": {"Fixture Fort": {"cost_materials": 1}}}}
        driver.configure_scenario_settings(lobby)
        self.assertEqual(game.scenario_settings["map_defaults"], MAP_DEFAULTS)
        self.assertEqual(game.scenario_settings["building_stat_overrides"], PLAYER_STATS)
        self.assertEqual(driver.snapshot()["scenario_settings"]["map_defaults"], MAP_DEFAULTS)


class BuildingStatEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.controller, cls.surface = app_harness.boot()

    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        path = Path(directory, "buildings.json")
        path.write_text(json.dumps(building_library()), encoding="utf-8")
        self.enterContext(mock.patch.object(c, "BUILDING_DATA_PATH", str(path)))

    def fields(self, screen, family):
        return {element.entry_key: element for element in screen.elements
                if getattr(element, "entry_ref", None) is screen.building_values.get(family)}

    def use_defaults_toggle(self, screen):
        return next((element for element in screen.elements
                     if str(getattr(element, "text", "")).startswith("Use Defaults")), None)

    def test_rows_show_level_one_values_and_increases(self):
        from screens.editors.unit_stats_editor import UnitStatsEditorScreen
        screen = UnitStatsEditorScreen(settings={"use_default_buildings": False}, persist=False)
        screen.select_category("buildings")
        fields = self.fields(screen, "Fixture Factory")
        self.assertEqual(fields["prod_materials"].text, "50")
        self.assertEqual(fields["prod_materials_per_level"].text, "30")
        self.assertNotIn("cost_materials_per_level", self.fields(screen, "Fixture Fort"))
        screen.draw(self.surface)

    def test_use_defaults_locks_fields_and_keeps_saved_player_stats(self):
        from screens.editors.unit_stats_editor import UnitStatsEditorScreen
        settings = {"building_stat_overrides": copy.deepcopy(PLAYER_STATS)}
        screen = UnitStatsEditorScreen(settings=settings, persist=False)
        screen.select_category("buildings")
        locked = [element for element in screen.elements if getattr(element, "disabled", False)]
        self.assertTrue(locked)
        self.assertFalse(self.fields(screen, "Fixture Factory"))
        screen.draw(self.surface)
        with mock.patch("ui.dialogs.show_success"):
            screen.save_all()
        self.assertIs(settings["use_default_buildings"], True)
        self.assertEqual(settings["building_stat_overrides"], PLAYER_STATS)

    def test_each_category_has_a_scrolling_use_defaults_row_that_locks_only_that_category(self):
        from screens.editors.unit_stats_editor import UnitStatsEditorScreen
        screen = UnitStatsEditorScreen(settings={}, persist=False)
        for key, _label in screen.CATEGORIES:
            with self.subTest(category=key):
                screen.select_category(key)
                self.assertTrue(self.use_defaults_toggle(screen).is_scrollable)
        screen.select_category("buildings")
        top = self.use_defaults_toggle(screen).rect.y
        screen.scroll_y = -10
        screen.refresh_ui()
        self.assertEqual(self.use_defaults_toggle(screen).rect.y, top - 10)
        screen.scroll_y = 0
        screen.refresh_ui()
        self.use_defaults_toggle(screen).callback()
        self.assertFalse(screen.use_defaults["buildings"])
        self.assertTrue(self.fields(screen, "Fixture Factory"))
        # Other categories stay locked.
        screen.select_category("range")
        self.assertTrue(screen.use_defaults["range"])
        self.assertFalse(any(getattr(element, "entry_ref", None) is not None for element in screen.elements))

    def test_reset_with_use_defaults_clears_saved_player_values(self):
        from screens.editors.unit_stats_editor import UnitStatsEditorScreen
        settings = {"building_stat_overrides": copy.deepcopy(PLAYER_STATS), "use_default_range": False,
                    "unit_range_overrides": {"Fixture Gun": {"bombard_range": 4}}}
        screen = UnitStatsEditorScreen(settings=settings, persist=False)
        with mock.patch("ui.dialogs.ask_yes_no", side_effect=lambda _t, _m, cb: cb(True)), \
                mock.patch("ui.dialogs.show_success"):
            screen.reset_to_defaults()
        self.assertFalse(settings.get("building_stat_overrides"))
        self.assertFalse(settings.get("unit_range_overrides"))
        # Reset turns every Use Defaults back to its starting value.
        for category, key in queries.USE_MAP_DEFAULTS_KEYS.items():
            self.assertIs(settings[key], queries.uses_map_defaults({}, category))

    def test_turning_use_defaults_off_saves_edited_increases(self):
        from screens.editors.unit_stats_editor import UnitStatsEditorScreen
        settings = {}
        screen = UnitStatsEditorScreen(settings=settings, persist=False)
        screen.select_category("buildings")
        screen.toggle_use_defaults("buildings")
        self.fields(screen, "Fixture Factory")["prod_materials_per_level"].text = "99"
        screen.select_category("range")
        screen.select_category("buildings")
        self.assertEqual(self.fields(screen, "Fixture Factory")["prod_materials_per_level"].text, "99")
        with mock.patch("ui.dialogs.show_success"):
            screen.save_all()
        self.assertIs(settings["use_default_buildings"], False)
        self.assertEqual(settings["building_stat_overrides"],
                         {"Fixture Factory": {"prod_materials_per_level": 99}})

    def test_unchanged_fractional_default_increase_saves_without_a_warning(self):
        from screens.editors.unit_stats_editor import UnitStatsEditorScreen
        library = building_library()
        # The increase comes from the first and last levels: (105 - 50) / 2 = 27.5.
        library["Fixture Factory Lvl 3"]["prod_materials"] = 105
        Path(c.BUILDING_DATA_PATH).write_text(json.dumps(library), encoding="utf-8")
        settings = {"use_default_buildings": False}
        screen = UnitStatsEditorScreen(settings=settings, persist=False)
        with mock.patch("ui.dialogs.show_warning") as warning, mock.patch("ui.dialogs.show_success"):
            screen.save_all()
        warning.assert_not_called()
        self.assertEqual(settings["building_stat_overrides"], {})

    def test_invalid_building_stat_blocks_the_whole_save(self):
        from screens.editors.unit_stats_editor import UnitStatsEditorScreen
        settings = {"use_default_buildings": False}
        screen = UnitStatsEditorScreen(settings=settings, persist=False)
        screen.select_category("buildings")
        self.fields(screen, "Fixture Fort")["cost_fuel"].text = "-"
        with mock.patch("ui.dialogs.show_warning") as warning:
            screen.save_all()
        warning.assert_called_once()
        self.assertEqual(settings, {"use_default_buildings": False})

    def turn_controls(self, screen, family):
        """Return the family's turns field and ON/OFF button in the Buildings category."""
        values = screen.turn_tabs["building"]["values"]
        field = next(element for element in screen.elements
                     if getattr(element, "entry_ref", None) is values and element.entry_key == family)
        index = screen.elements.index(field)
        return field, screen.elements[index + 1]

    def test_buildings_use_defaults_locks_turns_and_enabled_too(self):
        from screens.editors.unit_stats_editor import UnitStatsEditorScreen
        settings = {"building_turn_overrides": {"Fixture Factory": 9}}
        screen = UnitStatsEditorScreen(settings=settings, persist=False)
        screen.select_category("buildings")
        values = screen.turn_tabs["building"]["values"]
        self.assertFalse(any(getattr(element, "entry_ref", None) is values for element in screen.elements))
        locked_buttons = [element for element in screen.elements
                          if getattr(element, "text", "") == "ON" and element.disabled]
        self.assertTrue(locked_buttons)
        with mock.patch("ui.dialogs.show_success"):
            screen.save_all()
        # The player's saved turns stay unchanged and unused.
        self.assertEqual(settings["building_turn_overrides"], {"Fixture Factory": 9})

    def test_buildings_rows_edit_turns_and_enabled_without_use_defaults(self):
        from screens.editors.unit_stats_editor import UnitStatsEditorScreen
        settings = {"use_default_buildings": False}
        screen = UnitStatsEditorScreen(settings=settings, persist=False)
        screen.select_category("buildings")
        default = screen.turn_tabs["building"]["defaults"]["Fixture Factory"]
        field, toggle = self.turn_controls(screen, "Fixture Factory")
        field.text = str(default + 2)
        toggle.callback()
        self.assertEqual(settings, {"use_default_buildings": False})
        with mock.patch("ui.dialogs.show_success"):
            screen.save_all()
        self.assertEqual(settings["building_turn_overrides"], {"Fixture Factory": default + 2})
        self.assertEqual(settings["building_disabled"], ["Fixture Factory"])
        self.assertIs(settings["use_default_buildings"], False)

    def test_invalid_building_stat_blocks_turn_changes_too(self):
        from screens.editors.unit_stats_editor import UnitStatsEditorScreen
        settings = {"use_default_buildings": False}
        screen = UnitStatsEditorScreen(settings=settings, persist=False)
        screen.select_category("buildings")
        field, toggle = self.turn_controls(screen, "Fixture Fort")
        field.text = str(screen.turn_tabs["building"]["defaults"]["Fixture Fort"] + 1)
        toggle.callback()
        self.fields(screen, "Fixture Fort")["cost_fuel"].text = "-"
        with mock.patch("ui.dialogs.show_warning") as warning:
            screen.save_all()
        warning.assert_called_once()
        self.assertEqual(settings, {"use_default_buildings": False})

    def test_map_editor_edits_only_the_map_defaults(self):
        from screens.editors.unit_stats_editor import MapUnitBuildingStatsScreen
        map_screen = mock.Mock()
        map_screen.map_data = {}
        map_screen.scenario_settings = {"building_stat_overrides": PLAYER_STATS}
        with mock.patch("ui.navigation.modal_screen.host_map_screen", return_value=map_screen):
            screen = MapUnitBuildingStatsScreen(map_screen)
        self.assertEqual([key for key, _label in screen.CATEGORIES], list(queries.EDITOR_CATEGORY_SETTINGS))
        screen.select_category("buildings")
        self.assertEqual(list(screen.building_values), ["Fixture Factory", "Fixture Fort"])
        self.assertIsNone(self.use_defaults_toggle(screen))
        self.fields(screen, "Fixture Factory")["cost_materials_per_level"].text = "150"
        self.fields(screen, "Fixture Fort")["cost_materials"].text = "700"
        # Back leaves the map without a defaults block.
        self.assertNotIn("map_defaults", map_screen.scenario_settings)
        with mock.patch("screens.editors.unit_stats_editor.rebuild") as rebuild, \
                mock.patch.object(queries, "save_scenario_settings") as save:
            screen.save_all()
        save.assert_not_called()
        rebuild.assert_called_once_with(map_screen)
        self.assertEqual(map_screen.scenario_settings["building_stat_overrides"], PLAYER_STATS)
        self.assertEqual(map_screen.scenario_settings["map_defaults"]["building_stat_overrides"],
                         {"Fixture Factory": {"cost_materials_per_level": 150},
                          "Fixture Fort": {"cost_materials": 700}})
        self.assertNotIn("use_default_buildings", map_screen.scenario_settings["map_defaults"])
        with mock.patch("ui.navigation.modal_screen.host_map_screen", return_value=map_screen):
            screen = MapUnitBuildingStatsScreen(map_screen)
        with mock.patch("ui.dialogs.ask_yes_no", side_effect=lambda _t, _m, cb: cb(True)), \
                mock.patch("screens.editors.unit_stats_editor.rebuild"):
            screen.reset_to_defaults()
        self.assertEqual(map_screen.scenario_settings["map_defaults"]["building_stat_overrides"], {})


if __name__ == "__main__":
    unittest.main()
