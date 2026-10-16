"""Air drop recovery blocks commands and damage across authoritative boundaries."""
import asyncio
from copy import deepcopy
import os
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from data import constants as c, queries
from data.io.realtime_multiplayer import MapRealtimeDriver, RealtimeError, collect_map_commands
from map_logic.ai import ai_movement, ai_world
from map_logic.diplomacy import volunteers
from map_logic.turn_processing import air_processor, combat_processor, combat_rules, turn_processor
from screens.map_related_screens.battle_screen import Battle_Screen
from screens.menu_screens.map import Map
from tests import test_air_transport as transport_tests
from tests.test_air_mechanics import tile, wing


class AirDropRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.fixture = transport_tests.TransportTests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.game = self.fixture.game
        self.cargo = self.fixture.cargo
        self.base = self.fixture.base
        self.enterContext(patch.object(c, "AIR_DROP_RECOVERY_TURNS", 2))

    def land(self):
        target = self.fixture.plan_drop()
        target["neighbors"] = [self.base["id"]]
        self.base["neighbors"].append(target["id"])
        air_processor.process_air_orders(self.game)
        return target

    def test_duration_is_tunable_and_zero_disables_recovery(self):
        for turns in (0, 1, 3):
            with self.subTest(turns=turns), patch.object(c, "AIR_DROP_RECOVERY_TURNS", turns):
                queries.begin_air_drop_recovery(self.cargo)
                self.assertEqual(queries.air_drop_recovery_turns(self.cargo), turns)
                for remaining in range(turns - 1, -1, -1):
                    queries.finish_air_drop_recovery_turn([self.cargo])
                    self.assertEqual(queries.air_drop_recovery_turns(self.cargo), remaining)
                self.assertFalse(queries.unit_is_air_drop_recovering(self.cargo))
                self.assertGreater(combat_rules.effective_damage_multiplier(self.cargo, self.game.nation_data), 0)

    def test_drop_blocks_movement_and_damage_but_can_take_damage(self):
        target = self.land()
        self.assertEqual(queries.air_drop_recovery_turns(self.cargo), c.AIR_DROP_RECOVERY_TURNS)
        self.assertFalse(queries.can_unit_move_step(self.cargo, target, self.base, self.game.nation_data))
        defender = wing(target, "Fixture Cargo", "B")
        health, enemy_health = self.cargo["health"], defender["health"]
        self.assertEqual(combat_rules.volley([self.cargo], nation_data=self.game.nation_data), 0)
        shots = combat_rules.damage_shots([self.cargo], [defender], nation_data=self.game.nation_data,
                                          attack_field="bombard_attack")
        self.assertEqual(sum(shot[1] for shot in shots), 0)
        combat_processor.process_combat(self.game)
        self.assertLess(self.cargo["health"], health)
        self.assertEqual(defender["health"], enemy_health)

    def test_recovering_cargo_cannot_destroy_grounded_aircraft(self):
        target = self.land()
        aircraft = wing(target, "Monoplane Bomber I", "B")
        before = aircraft["health"]
        combat_processor.process_combat(self.game)
        self.assertEqual(aircraft["health"], before)
        self.assertIn(aircraft, target["units"])

    def test_shared_validator_rejects_every_replacement_order(self):
        target = self.land()
        for order in (None, {"type": "MOVE", "path": []}, {"type": "MOVE", "path": [1]},
                      {"type": "DISBAND", "turns_left": 1}, {"type": "REPAIR"},
                      {"type": "UPGRADE"}, {"type": "CONVERT"}, {"type": "BOMBARD", "target_id": 1}):
            with self.subTest(order=order), self.assertRaises(ValueError):
                queries.canonical_unit_order(self.game, "A", target, self.cargo, order)
        self.assertEqual(queries.canonical_unit_order(self.game, "A", target, self.cargo,
                                                     self.cargo["order"]), self.cargo["order"])

    def test_orders_callbacks_and_map_commands_preserve_recovery(self):
        target = self.land()
        screen = self.fixture.screen()
        before = deepcopy(self.cargo)
        for callback in (screen.start_renaming, screen.save_unit_name, screen.repair_unit,
                         screen.disband_unit, screen.convert_unit, screen.start_bombard_targeting,
                         screen.cancel_unit_order):
            callback(0, target)
            self.assertEqual(self.cargo, before)
        screen.upgrade_unit(0, "Fixture Cargo", target)
        self.assertEqual(self.cargo, before)
        self.game.can_select_map_units = lambda: True
        self.game.selected_unit_records = lambda: [(self.cargo, target)]
        self.game.invalidate_map_presentation_cache = Mock()
        self.assertFalse(Map.issue_selected_move_orders(self.game, self.base))
        self.assertEqual(Map.selected_map_unit_ids(self.game), [])
        self.assertEqual(self.cargo, before)

    def test_battle_callbacks_cannot_rotate_or_pin_recovering_units(self):
        target = self.land()
        screen = object.__new__(Battle_Screen)
        screen.map_screen = self.game
        screen.province = target
        screen.player = "A"
        screen.refresh_ui = Mock()
        before = deepcopy(self.cargo)
        screen.toggle_stance(self.cargo)
        screen.send_to_lane(self.cargo, None)
        screen.clear_orders()
        self.assertFalse(screen.can_command(self.cargo))
        self.assertEqual(self.cargo, before)

    def test_loading_and_volunteer_selection_cannot_bypass_recovery(self):
        target = self.land()
        plane = wing(target, "Monoplane Transport")
        self.assertFalse(queries.air_cargo_is_eligible(plane, self.cargo))
        with self.assertRaises(ValueError):
            queries.set_air_cargo(self.game, "A", plane, target, [self.cargo["unit_id"]])
        self.assertNotIn((target, self.cargo), volunteers.available_units(self.game, "A"))

    def test_army_assignments_and_automatic_orders_cannot_replace_recovery(self):
        army = queries.create_army("A", [self.cargo["unit_id"]], self.game.nation_data, self.game.map_data)
        target = self.land()
        before = deepcopy(self.cargo)
        self.assertIsNone(queries.create_army("A", [self.cargo["unit_id"]], self.game.nation_data, self.game.map_data))
        self.assertFalse(queries.ungroup_units("A", [self.cargo["unit_id"]], self.game.nation_data, self.game.map_data))
        self.assertFalse(queries.disband_army("A", army["id"], self.game.nation_data, self.game.map_data))
        queries.set_army_defense_area("A", army["id"], [self.base["id"]], self.game.nation_data, self.game.map_data)
        self.assertEqual(queries.queue_army_defense_orders(self.game, "A", army["id"]), 0)
        ai_movement._rotate_damaged_units(self.game, "A", [target["id"]])
        self.assertEqual(self.cargo, before)

    def test_ai_planning_preserves_recovery_and_does_not_rotate_the_unit(self):
        target = self.land()
        self.cargo["health"] = self.cargo["max_health"] * c.AI_ROTATE_HEALTH_FRACTION / 2
        self.cargo["combat_stance"] = "RESERVE"
        for _ in range(2):
            wing(target, "Fixture Cargo")
        wing(target, "Fixture Cargo", "B")
        before = deepcopy(self.cargo)
        snapshot = SimpleNamespace(provs_by_owner={"A": [self.base]},
                                   units_by_owner={"A": [(self.cargo, target)]})
        with patch.object(ai_world, "for_screen", return_value=snapshot):
            units, _provinces = ai_movement._reset_orders_and_collect_units(self.game, ["A"])
        self.assertEqual(units["A"], [])
        ai_movement._rotate_damaged_units(self.game, "A", [target["id"]])
        self.assertEqual(self.cargo, before)

    def test_realtime_rejects_changed_recovery_orders_names_and_stances(self):
        self.land()
        commands = collect_map_commands(self.game, "A")
        command = next(command for command in commands if command.get("unit_id") == self.cargo["unit_id"])
        driver = MapRealtimeDriver(self.game)
        self.assertEqual(driver.validate_draft("A", [command])[0]["order"], self.cargo["order"])
        for changes in ({"order": None}, {"order": {"type": "MOVE", "path": []}},
                        {"order": {"type": "AIR_DROP_RECOVERY", "turns_left": 1}},
                        {"custom_name": "Changed"}, {"combat_stance": "RESERVE"}, {"lane_target": "B"}):
            with self.subTest(changes=changes), self.assertRaises(RealtimeError):
                driver.validate_draft("A", [dict(command, **changes)])
        with self.assertRaises(RealtimeError):
            driver.validate_draft("B", [command])

    def test_tournament_preserves_host_recovery_and_rejects_changed_drafts(self):
        target = self.land()
        before = deepcopy(self.cargo)
        client = deepcopy(self.game)
        client.id_to_province[target["id"]]["units"][0]["health"] = 1
        self.assertEqual(self.fixture.import_client(client)["loaded"], 1)
        self.assertEqual(self.cargo, before)
        self.assertIs(self.game.id_to_province[target["id"]]["units"][0], self.cargo)
        for changes in ({"order": {"type": "MOVE", "path": []}}, {"custom_name": "Changed"},
                        {"combat_stance": "RESERVE"},
                        {"order": {"type": "AIR_DROP_RECOVERY", "turns_left": 1}}):
            client = deepcopy(self.game)
            client.id_to_province[target["id"]]["units"][0].update(changes)
            with self.subTest(changes=changes):
                self.assertEqual(self.fixture.import_client(client)["rejected"], 1)
                self.assertEqual(self.cargo, before)

    def test_network_army_rosters_cannot_reassign_recovering_units(self):
        army = queries.create_army("A", [self.cargo["unit_id"]], self.game.nation_data, self.game.map_data)
        self.land()
        with self.assertRaises(RealtimeError):
            MapRealtimeDriver(self.game).validate_draft("A", [{"type": "army_roster", "armies": []}])
        client = deepcopy(self.game)
        client.nation_data["A"]["armies"] = []
        self.assertEqual(self.fixture.import_client(client)["rejected"], 1)
        self.assertIn(self.cargo["unit_id"], army["unit_ids"])

    def test_legacy_and_invalid_recovery_orders_load_safely(self):
        queries.normalize_air_orders(self.game.map_data)
        self.assertFalse(queries.unit_is_air_drop_recovering(self.cargo))
        for value in (None, True, "bad", -1, 0):
            self.cargo["order"] = {"type": "AIR_DROP_RECOVERY", "turns_left": value}
            queries.normalize_air_orders(self.game.map_data)
            self.assertEqual(self.cargo["order"], {"type": "MOVE", "path": []})


class RecoveryRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests import app_harness
        cls.controller, cls.surface = app_harness.boot()

    def runtime(self, directory):
        fixture = transport_tests.TransportTests()
        self.addCleanup(fixture.doCleanups)
        fixture.setUp()
        _game, _fighter, _rocket, path = transport_tests.air_tests.AirAppSmokeTests.make_runtime_save(self, directory)
        game = Map(load_path=path, skip_initial_income=True)
        game.selection_mode = False
        game.player_country = "A"
        game.show_feedback = Mock()
        return game

    def test_complete_turns_do_not_expire_recovery_on_the_landing_turn(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(c, "AIR_DROP_RECOVERY_TURNS", 1), \
                patch.object(c, "RECORD_HISTORY", False):
            game = self.runtime(directory)
            base, target = game.id_to_province[1], game.id_to_province[2]
            plane, cargo = wing(base, "Monoplane Transport"), wing(base, "Fixture Cargo")
            defender = wing(target, "Fixture Cargo", "B")
            queries.set_air_cargo(game, "A", plane, base, [cargo["unit_id"]])
            plane["order"] = queries.air_move_order(game, plane, base, target)
            enemy_health = defender["health"]
            asyncio.run(turn_processor.resolve_turn_logic(game))
            self.assertEqual(queries.air_drop_recovery_turns(cargo), 1)
            self.assertEqual(defender["health"], enemy_health)
            asyncio.run(turn_processor.resolve_turn_logic(game))
            self.assertFalse(queries.unit_is_air_drop_recovering(cargo))
            self.assertEqual(defender["health"], enemy_health)
            asyncio.run(turn_processor.resolve_turn_logic(game))
            self.assertLess(defender["health"], enemy_health)

    def test_recovery_survives_actual_save_load_and_keeps_orders_read_only(self):
        from data.map import save_map
        from screens.map_related_screens.orders import Orders_Screen
        with tempfile.TemporaryDirectory() as directory:
            game = self.runtime(directory)
            base = game.id_to_province[1]
            cargo = wing(base, "Fixture Cargo")
            with patch.object(c, "AIR_DROP_RECOVERY_TURNS", 3):
                queries.begin_air_drop_recovery(cargo)
            with patch.object(c, "SAVES_DIR", directory):
                asyncio.run(save_map.save_map_data(game, "recovering"))
            loaded = Map(load_path=os.path.join(directory, "recovering"), skip_initial_income=True)
            restored = next(unit for unit in loaded.id_to_province[1]["units"] if unit["unit_id"] == cargo["unit_id"])
            self.assertEqual(queries.air_drop_recovery_turns(restored), 3)
            loaded.selection_mode = False
            loaded.player_country = "A"
            loaded.select_map_units([restored])
            screen = Orders_Screen()
            screen.start_with_province(loaded.id_to_province[1], loaded)
            self.assertTrue(screen._command_blocked_silent(restored))
            screen.draw(self.surface)
