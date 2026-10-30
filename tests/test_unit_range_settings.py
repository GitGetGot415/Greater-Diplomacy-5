"""Scenario range editing, shared execution rules, and persistence boundaries."""
import asyncio
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import pygame

from data import queries
import data.constants as c
from data.multiplayer.tournament import files as tournament_files
from data.multiplayer.realtime.session import (
    MapRealtimeDriver,
    RealtimeConfig,
    RealtimeError,
    RealtimeSession,
    apply_authoritative_snapshot,
)
from map_logic.ai import ai_movement, ai_unit_eval
from map_logic.system32 import air_processor, combat_processor
from tests import app_harness
from tests.air_fixtures import tile, wing, world


def range_library():
    """Use artificial content with explicit capabilities and range progressions."""
    base = {"health": 1000, "attack": 80, "defense": 0, "speed": 1,
            "cost_materials": 100, "cost_manpower": 100, "cost_fuel": 0, "production_time": 2}
    return {
        "Fixture Gun I": dict(base, bombard_range=1, bombard_attack=80),
        "Fixture Gun III": dict(base, bombard_range=1, bombard_attack=80),
        "Fixture Wing IV": dict(base, air_role="fighter", air_range_px=55),
        "Fixture Wing I": dict(base, air_role="fighter", air_range_px=40),
        "Fixture Wing II": dict(base, air_role="fighter", air_range_px=45),
        "Fixture Transport": dict(base, air_role="transport", air_range_px=30, air_transport_capacity=1),
        "Fixture Missile": dict(base, air_role="strike", air_range_px=50, air_consumable=True),
        "Fixture Infantry": dict(base),
    }


class UnitRangeRulesTests(unittest.TestCase):
    def setUp(self):
        self.library = range_library()
        self.defaults = queries.get_unit_range_defaults(self.library)
        self.enterContext(mock.patch.object(queries, "get_unit_library", return_value=self.library))

    def test_defaults_discover_capabilities_and_sort_levels(self):
        self.assertEqual(self.defaults["Fixture Gun"], {"bombard_range": 1})
        self.assertEqual(self.defaults["Fixture Wing"], {"air_range_start": 40, "air_range_per_level": 5})
        self.assertEqual(self.defaults["Fixture Transport"], {"air_range_start": 30, "air_range_per_level": 0})
        self.assertNotIn("Fixture Infantry", self.defaults)
        before = copy.deepcopy(self.library)
        queries.apply_unit_range_overrides(self.library, {})
        self.assertEqual(self.library, before)

    def test_family_overrides_apply_to_all_levels_and_shared_queries(self):
        settings = {"unit_range_overrides": {
            "Fixture Gun": {"bombard_range": 3},
            "Fixture Wing": {"air_range_start": 100, "air_range_per_level": 7},
            "Fixture Transport": {"air_range_start": 60},
            "Fixture Missile": {"air_range_start": 90},
            "Fixture Infantry": {"bombard_range": 10}}}
        queries.apply_unit_range_overrides(self.library, settings)
        for name in ("Fixture Gun I", "Fixture Gun III"):
            self.assertEqual(queries.get_bombardment_range(name), 3)
            self.assertEqual(ai_unit_eval.bombard_range(name, self.library[name]), 3)
        self.assertEqual(self.library["Fixture Wing I"]["air_range_px"], 100)
        self.assertEqual(self.library["Fixture Wing II"]["air_range_px"], 107)
        self.assertEqual(self.library["Fixture Wing IV"]["air_range_px"], 121)
        self.assertEqual(self.library["Fixture Transport"]["air_range_px"], 60)
        self.assertEqual(self.library["Fixture Missile"]["air_range_px"], 90)
        self.assertFalse(queries.can_bombard("Fixture Infantry"))
        self.assertFalse(queries.can_bombard("Convoy (Fixture Gun I)"))
        unit = {"type": "Fixture Wing II"}
        self.assertEqual(queries.air_order_radius(unit, "AIR_ATTACK"), 107)
        self.assertEqual(queries.air_order_radius(unit, "AIR_PATROL"), 107)
        self.assertEqual(queries.air_order_radius(unit, "AIR_REPOSITION"), 214)
        transport = {"type": "Fixture Transport"}
        self.assertEqual(queries.air_order_radius(transport, "AIR_REPOSITION"), 60)
        self.assertEqual(queries.air_order_radius(transport, "AIR_DROP"), 30)
        self.assertTrue(any("107" in line for line in queries.get_air_unit_traits(unit["type"])))

    def test_partial_overrides_zero_growth_and_invalid_values(self):
        for change, expected in (({"air_range_start": 80}, 95),
                                 ({"air_range_per_level": 0}, 40)):
            library = range_library()
            queries.apply_unit_range_overrides(library, {"unit_range_overrides": {"Fixture Wing": change}})
            self.assertEqual(library["Fixture Wing IV"]["air_range_px"], expected)
        for invalid in (None, [], "bad", True, -1, 1.5, "8"):
            with self.subTest(value=invalid):
                for raw in (invalid, {"Fixture Wing": invalid},
                            {"Fixture Wing": {"air_range_start": invalid, "air_range_per_level": invalid}}):
                    library = range_library()
                    queries.apply_unit_range_overrides(library, {"unit_range_overrides": raw})
                    self.assertEqual(library, range_library())
        for key in ("bombard_range", "air_range_start"):
            family = "Fixture Gun" if key == "bombard_range" else "Fixture Wing"
            self.assertEqual(queries.get_unit_range_overrides(
                {"unit_range_overrides": {family: {key: 0}}}, self.defaults), {})

    def test_badge_compares_effective_values_with_defaults(self):
        with mock.patch.object(queries, "get_unit_range_defaults", return_value=self.defaults):
            for settings in ({}, {"unit_range_overrides": self.defaults},
                             {"unit_range_overrides": {"Fixture Wing": {"air_range_start": -1}}}):
                self.assertFalse(queries.scenario_has_unit_stat_customizations(settings))
            self.assertTrue(queries.scenario_has_unit_stat_customizations(
                {"unit_range_overrides": {"Fixture Gun": {"bombard_range": 2}}}))

    def test_air_range_changes_agree_in_ai_both_hosts_and_resolution(self):
        game = world()
        base = tile(game, 1, 8)
        target = tile(game, 2, 88, owner="B")
        unit = wing(base, "Fixture Wing I")
        enemy = wing(target, "Fixture Infantry", "B")
        order = {"type": "AIR_ATTACK", "target_id": 2}
        command = {"type": "unit_order", "province_id": 1, "unit_index": 0,
                   "unit_id": unit["unit_id"], "order": order}
        driver = MapRealtimeDriver(game)
        payload = {"aircraft_orders": [{"unit_id": unit["unit_id"], "order": order}]}
        with self.assertRaises(RealtimeError):
            driver.validate_draft("A", [command])
        with self.assertRaises(ValueError):
            tournament_files._validate_aircraft_orders(game, "A", payload, {})
        game.scenario_settings = {"unit_range_overrides": {"Fixture Wing": {"air_range_start": 100}}}
        queries.apply_unit_range_overrides(self.library, game.scenario_settings)
        canonical = queries.canonical_air_order(game, unit, base, order)
        self.assertIn(canonical, ai_movement.legal_air_candidates(game, unit, base))
        self.assertEqual(driver.validate_draft("A", [command])[0]["order"], canonical)
        _live, drafts = tournament_files._validate_aircraft_orders(game, "A", payload, {})
        self.assertEqual(drafts[0][1], canonical)
        for country in ("B",):
            with self.assertRaises(RealtimeError):
                driver.validate_draft(country, [command])
            with self.assertRaises(ValueError):
                tournament_files._validate_aircraft_orders(game, country, payload, {})
        malformed = dict(command, order={"type": "AIR_ATTACK", "target_id": 999})
        with self.assertRaises(RealtimeError):
            driver.validate_draft("A", [malformed])
        unit["order"] = canonical
        health = enemy["health"]
        air_processor.process_air_orders(game)
        self.assertLess(enemy["health"], health)

    def test_bombardment_range_agrees_in_orders_ai_and_execution(self):
        game = world()
        base = tile(game, 1, 8)
        middle = tile(game, 2, 28)
        target = tile(game, 3, 48, owner="B")
        base["neighbors"] = [2]
        middle["neighbors"] = [1, 3]
        target["neighbors"] = [2]
        gun = wing(base, "Fixture Gun I")
        enemy = wing(target, "Fixture Infantry", "B")
        order = {"type": "BOMBARD", "target_id": 3}
        with self.assertRaises(ValueError):
            queries.canonical_unit_order(game, "A", base, gun, order)
        self.assertFalse(ai_movement._try_bombard(game, "A", gun, base))
        queries.apply_unit_range_overrides(self.library,
            {"unit_range_overrides": {"Fixture Gun": {"bombard_range": 2}}})
        self.assertEqual(queries.canonical_unit_order(game, "A", base, gun, order), order)
        self.assertTrue(ai_movement._try_bombard(game, "A", gun, base))
        self.assertEqual(gun["order"], order)
        health = enemy["health"]
        combat_processor.process_bombardments(game)
        self.assertLess(enemy["health"], health)


class UnitRangeEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.controller, cls.surface = app_harness.boot()

    def setUp(self):
        self.defaults = queries.get_unit_range_defaults(range_library())
        self.enterContext(mock.patch.object(queries, "get_unit_range_defaults", return_value=self.defaults))

    def editor(self, settings=None, persist=False):
        from screens.editors.unit_stats_editor import UnitStatsEditorScreen
        return UnitStatsEditorScreen(settings=settings if settings is not None else {}, persist=persist)

    def test_fields_save_to_draft_only_and_back_discards(self):
        settings = {"unit_turn_overrides": {"Fixture Gun": 7}}
        screen = self.editor(settings)
        field = next(element for element in screen.elements
                     if getattr(element, "entry_key", None) == "bombard_range")
        field.text = "4"
        screen.refresh_ui()
        screen.draw(self.surface)
        self.assertEqual(screen.values["Fixture Gun"]["bombard_range"], "4")
        self.assertNotIn("unit_range_overrides", settings)
        screen.handle_back_key()
        self.assertNotIn("unit_range_overrides", settings)
        screen = self.editor(settings)
        field = next(element for element in screen.elements
                     if getattr(element, "entry_key", None) == "bombard_range")
        field.text = "4"
        with mock.patch.object(queries, "save_scenario_settings") as save, \
                mock.patch("ui.dialogs.show_success"):
            screen.save_all()
        save.assert_not_called()
        self.assertEqual(settings["unit_range_overrides"], {"Fixture Gun": {"bombard_range": 4}})
        self.assertEqual(settings["unit_turn_overrides"], {"Fixture Gun": 7})

    def test_save_rejects_invalid_input_without_partial_changes(self):
        settings = {}
        screen = self.editor(settings)
        field = next(element for element in screen.elements
                     if getattr(element, "entry_key", None) == "air_range_start")
        field.text = ""
        with mock.patch("ui.dialogs.show_warning") as warning:
            screen.save_all()
        warning.assert_called_once()
        self.assertEqual(settings, {})

    def test_scroll_keeps_edits_and_last_row_is_editable(self):
        from screens.editors.unit_stats_editor import UnitStatsEditorScreen
        defaults = {f"Fixture Wing {index:02}": {"air_range_start": 40, "air_range_per_level": 5}
                    for index in range(30)}
        with mock.patch.object(queries, "get_unit_range_defaults", return_value=defaults):
            screen = UnitStatsEditorScreen(settings={}, persist=False)
            field = next(element for element in screen.elements if getattr(element, "entry_key", None))
            field.text = "88"
            screen.scroll_y = screen.max_scroll
            screen.refresh_ui()
            screen.draw(self.surface)
            self.assertEqual(screen.values["Fixture Wing 00"]["air_range_start"], "88")
            self.assertTrue(any(getattr(element, "entry_ref", None) is screen.values["Fixture Wing 29"]
                                for element in screen.elements))

    def test_reset_confirmation_and_persistence(self):
        settings = {"unit_range_overrides": {"Fixture Wing": {"air_range_start": 80, "air_range_per_level": 0}}}
        for answer in (False, True):
            screen = self.editor(settings, persist=True)
            with mock.patch("ui.dialogs.ask_yes_no", side_effect=lambda _t, _m, cb: cb(answer)), \
                    mock.patch("ui.dialogs.show_success"), \
                    mock.patch.object(queries, "save_scenario_settings") as save:
                screen.reset_to_defaults()
            if answer:
                save.assert_called_once_with(settings)
                self.assertEqual(settings["unit_range_overrides"], {})
            else:
                save.assert_not_called()
                self.assertTrue(settings["unit_range_overrides"])

    def test_scenario_button_refreshes_badge_and_uses_lobby_settings(self):
        from screens.setup.scenario_settings import Scenario_Settings
        screen = Scenario_Settings()
        screen.settings = {"unit_range_overrides": {"Fixture Gun": {"bombard_range": 4}}}
        screen._session_bound = True
        screen.refresh_ui()
        button = next(element for element in screen.elements if getattr(element, "text", "") == "Edit Unit Stats")
        self.assertEqual(button.notification_text, "!")
        with mock.patch("screens.editors.unit_stats_editor.open_unit_stats_editor") as open_editor:
            button.callback()
        self.assertIs(open_editor.call_args.kwargs["settings"], screen.settings)
        self.assertFalse(open_editor.call_args.kwargs["persist"])
        screen.settings["unit_range_overrides"] = {}
        open_editor.call_args.kwargs["on_done"](None)
        button = next(element for element in screen.elements if getattr(element, "text", "") == "Edit Unit Stats")
        self.assertFalse(button.notification_text)


class UnitRangePersistenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.controller, cls.surface = app_harness.boot()

    def setUp(self):
        self.directory = self.enterContext(tempfile.TemporaryDirectory())
        self.library_path = Path(self.directory, "units.json")
        self.library_path.write_text(json.dumps(range_library()), encoding="utf-8")
        self.enterContext(mock.patch.object(c, "UNIT_DATA_PATH", str(self.library_path)))
        self.enterContext(mock.patch.dict(queries._JSON_CACHE, {
            "unit_library": {"path": str(self.library_path), "data": None}}))
        self.settings = {"unit_range_overrides": {
            "Fixture Wing": {"air_range_start": 120, "air_range_per_level": 8},
            "Fixture Gun": {"bombard_range": 4}}}

    def make_save(self):
        from data.map import save_map
        game = world()
        base = tile(game, 1, 8)
        tile(game, 2, 88, owner="B")
        wing(base, "Fixture Wing II")
        wing(base, "Fixture Gun III")
        game.scenario_settings = copy.deepcopy(self.settings)
        game.raw_json_data = {province["json_key"]: dict(province) for province in game.map_data.values()}
        game.terrain_map = game.id_map.copy()
        game.political_map = game.id_map.copy()
        game.cores_map = game.id_map.copy()
        game.is_editor = False
        game.history = {}
        game.show_feedback = mock.Mock()
        with mock.patch.object(c, "SAVES_DIR", self.directory):
            asyncio.run(save_map.save_map_data(game, "ranges"))
        return Path(self.directory, "ranges")

    def test_actual_load_roundtrip_legacy_default_and_no_leak_to_next_map(self):
        from screens.game.map import Map
        path = self.make_save()
        with mock.patch.object(queries, "get_scenario_settings", return_value={}):
            loaded = Map(load_path=str(path), skip_initial_income=True)
            self.assertEqual(loaded.scenario_settings["unit_range_overrides"], self.settings["unit_range_overrides"])
            self.assertEqual(queries.air_order_radius(loaded.id_to_province[1]["units"][0], "AIR_ATTACK", context=loaded), 128)
            self.assertEqual(queries.get_bombardment_range("Fixture Gun III", context=loaded), 4)
            snapshot = json.loads(json.dumps(queries.build_save_dict(loaded)))
            self.assertEqual(snapshot["scenario_settings"]["unit_range_overrides"], self.settings["unit_range_overrides"])
            meta_path = path / "meta.json"
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            del meta["scenario_settings"]["unit_range_overrides"]
            meta_path.write_text(json.dumps(meta), encoding="utf-8")
            # A changed global preference cannot affect an existing legacy save.
            with mock.patch.object(queries, "get_scenario_settings", return_value=self.settings):
                Map(load_path=str(path), skip_initial_income=True)
            self.assertEqual(queries.get_unit_library(), range_library())
            del meta["scenario_settings"]
            meta_path.write_text(json.dumps(meta), encoding="utf-8")
            with mock.patch.object(queries, "get_scenario_settings", return_value=self.settings):
                Map(load_path=str(path), skip_initial_income=True)
            self.assertEqual(queries.get_unit_library(), range_library())

    def test_explicit_new_game_settings_apply_during_load_and_preserve_references(self):
        from screens.game.map import Map
        path = self.make_save()
        library = queries.get_unit_library()
        with mock.patch.object(queries, "get_scenario_settings", return_value={}):
            loaded = Map(load_path=str(path), is_scenario=True,
                         map_settings=self.settings, skip_initial_income=True)
        self.assertIs(queries.get_unit_library(), library)
        self.assertEqual(queries.get_bombardment_range("Fixture Gun III", context=loaded), 4)
        self.assertEqual(queries.air_order_radius({"type": "Fixture Wing IV"}, "AIR_ATTACK", context=loaded), 144)
        self.assertEqual(loaded.scenario_settings["unit_range_overrides"], self.settings["unit_range_overrides"])

    def test_lobby_host_updates_and_resets_ranges_before_snapshot(self):
        game = world()
        driver = MapRealtimeDriver(game)
        config = RealtimeConfig("fixture", {}, max_players=2)
        session = RealtimeSession(config, ["A", "B"], "Host", driver)
        library = queries.get_unit_library()
        library["Fixture Gun I"]["production_time"] = 9
        with self.assertRaises(RealtimeError):
            session.set_scenario_settings("unknown", self.settings)
        self.assertEqual(game.scenario_settings, {})
        session.set_scenario_settings(session.host_id, self.settings)
        self.assertIs(queries.get_unit_library(), library)
        self.assertEqual(game.scenario_settings, self.settings)
        self.assertEqual(driver.snapshot()["scenario_settings"]["unit_range_overrides"], self.settings["unit_range_overrides"])
        self.assertEqual(queries.get_bombardment_range("Fixture Gun I", context=game), 4)
        session.set_scenario_settings(session.host_id, {})
        self.assertEqual(queries.get_bombardment_range("Fixture Gun I", context=game), 1)
        self.assertEqual(library["Fixture Wing IV"]["air_range_px"], 55)
        self.assertEqual(library["Fixture Gun I"]["production_time"], 9)

    def test_client_snapshot_replaces_older_lobby_ranges(self):
        game = world()
        game.refresh_all_maps = mock.Mock()
        snapshot = queries.build_save_dict(game)
        snapshot["scenario_settings"] = copy.deepcopy(self.settings)
        apply_authoritative_snapshot(game, snapshot)
        self.assertEqual(game.scenario_settings, self.settings)
        self.assertEqual(queries.get_bombardment_range("Fixture Gun I", context=game), 4)
        self.assertEqual(queries.air_order_radius({"type": "Fixture Wing II"}, "AIR_ATTACK", context=game), 128)
        snapshot["scenario_settings"] = {}
        apply_authoritative_snapshot(game, snapshot)
        self.assertEqual(queries.get_unit_library(), range_library())


if __name__ == "__main__":
    unittest.main()
