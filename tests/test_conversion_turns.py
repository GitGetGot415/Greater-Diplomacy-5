"""Scenario conversion timers agree across controls, execution, saves, and hosts."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from data import constants as c, queries
from data.io.realtime_multiplayer import MapRealtimeDriver, RealtimeError
from map_logic.ai import ai_movement
from map_logic.turn_processing import air_processor, movement_processor
from tests import test_air_transport as transport_tests
from tests.test_air_mechanics import wing, tile
from tests.test_map_save_format import sample_map_screen


class ConversionTurnsTests(unittest.TestCase):
    def setUp(self):
        self.fixture = transport_tests.TransportTests()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.game = self.fixture.game
        self.base = self.fixture.base
        queries.get_unit_library()["Fixture Ship"] = {
            "health": 1200, "attack": 80, "defense": 0, "speed": 1,
            "cost_materials": 200, "cost_manpower": 40, "cost_fuel": 10,
            "production_time": 1, "naval_unit": True}
        self.ship = wing(self.base, "Fixture Ship")
        self.game.nation_data["A"]["research"]["trucks"] = 1

    def set_turns(self, action, turns):
        name = queries.CONVERSION_ACTIONS[action][0]
        self.game.scenario_settings.setdefault("conversion_turn_overrides", {})[name] = turns

    def test_legacy_defaults_malformed_values_and_limits(self):
        for action, (name, constant) in queries.CONVERSION_ACTIONS.items():
            default = getattr(c, constant)
            self.assertEqual(queries.get_conversion_turns(action, {}), default)
            self.assertEqual(queries.get_conversion_library()[name]["time"], default)
            for invalid in (None, "2", True, 1.5, {}, []):
                self.set_turns(action, invalid)
                self.assertEqual(queries.get_conversion_turns(action, self.game.scenario_settings), default)
            for raw, expected in ((-5, 1), (0, 1), (1, 1), (2, 2), (3, 3), (99, 3)):
                self.set_turns(action, raw)
                self.assertEqual(queries.get_conversion_turns(action, self.game.scenario_settings), expected)
            self.assertEqual(queries.get_conversion_turns(action, {"conversion_turn_overrides": []}), default)

    def test_ui_and_execution_use_both_conversion_directions(self):
        screen = self.fixture.screen()
        self.base["units"] = [self.ship]
        for turns in range(c.MIN_CONVERSION_TURNS, c.MAX_CONVERSION_TURNS + 1):
            self.set_turns("TRUCK_SHIP", turns)
            for target, result in (("Truck", "Truck (Fixture Ship)"), ("Ship", "Fixture Ship")):
                with self.subTest(turns=turns, target=target):
                    source = self.ship["type"]
                    screen.convert_unit(0, self.base)
                    self.assertEqual(self.ship["order"], {"type": "CONVERT", "to": target, "turns_left": turns})
                    for remaining in range(turns - 1, 0, -1):
                        movement_processor.process_conversions(self.game)
                        self.assertEqual(self.ship["type"], source)
                        self.assertEqual(self.ship["order"]["turns_left"], remaining)
                    movement_processor.process_conversions(self.game)
                    self.assertEqual(self.ship["type"], result)
                    self.assertEqual(self.ship["order"], {"type": "MOVE", "path": []})

    def test_realtime_rebuilds_new_duration_and_retains_progress(self):
        self.set_turns("TRUCK_SHIP", 3)
        driver = MapRealtimeDriver(self.game)
        for transported, target in ((False, "Truck"), (True, "Ship")):
            with self.subTest(transported=transported):
                if transported:
                    queries.load_transport(self.ship, "Truck")
                self.ship["order"] = {"type": "MOVE", "path": []}
                command = {"type": "unit_order", "province_id": self.base["id"],
                           "unit_id": self.ship["unit_id"],
                           "order": {"type": "CONVERT", "to": target, "turns_left": 0}}
                self.assertEqual(driver.validate_draft("A", [command])[0]["order"]["turns_left"], 3)
                with self.assertRaises(RealtimeError):
                    driver.validate_draft("B", [command])
                with self.assertRaises(RealtimeError):
                    driver.validate_draft("A", [dict(command, order={"type": "CONVERT", "to": "invalid"})])
                self.ship["order"] = {"type": "CONVERT", "to": target, "turns_left": 2}
                self.assertEqual(driver.validate_draft("A", [command])[0]["order"], self.ship["order"])

    def test_tournament_uses_host_settings_in_both_directions_and_keeps_progress(self):
        self.set_turns("TRUCK_SHIP", 3)
        for transported, target in ((False, "Truck"), (True, "Ship")):
            with self.subTest(transported=transported):
                if transported:
                    queries.load_transport(self.ship, "Truck")
                client = deepcopy(self.game)
                client.scenario_settings["conversion_turn_overrides"] = {}
                draft = next(u for u in client.id_to_province[self.base["id"]]["units"]
                             if u["unit_id"] == self.ship["unit_id"])
                draft["order"] = {"type": "CONVERT", "to": target, "turns_left": 0}
                self.assertEqual(self.fixture.import_client(client)["loaded"], 1)
                self.ship = next(u for u in self.base["units"] if u["unit_id"] == self.ship["unit_id"])
                self.assertEqual(self.ship["order"]["turns_left"], 3)
                self.ship["order"]["turns_left"] = 2
                self.assertEqual(self.fixture.import_client(client)["loaded"], 1)
                self.ship = next(u for u in self.base["units"] if u["unit_id"] == self.ship["unit_id"])
                self.assertEqual(self.ship["order"]["turns_left"], 2)
                self.ship["order"] = {"type": "MOVE", "path": []}

    def test_tournament_rejects_illegal_and_stale_conversion_atomically(self):
        self.set_turns("TRUCK_SHIP", 2)
        client = deepcopy(self.game)
        draft = next(u for u in client.id_to_province[self.base["id"]]["units"]
                     if u["unit_id"] == self.ship["unit_id"])
        draft["order"] = {"type": "CONVERT", "to": "Truck", "turns_left": 2}
        for change in (lambda data: data.update(tournament_turn=0),
                       lambda data: next(u for p in data["provinces"].values() for u in p["units"]
                           if u["unit_id"] == self.ship["unit_id"]).update(type=None),
                       lambda data: next(u for p in data["provinces"].values() for u in p["units"]
                           if u["unit_id"] == self.ship["unit_id"])["order"].update(to="invalid")):
            before = deepcopy(self.game.map_data)
            self.assertEqual(self.fixture.import_client(client, change)["rejected"], 1)
            self.assertEqual(self.game.map_data, before)
        self.game.nation_data["A"]["research"]["trucks"] = 0
        self.assertEqual(self.fixture.import_client(client)["rejected"], 1)
        self.assertEqual(self.game.map_data, before)

    def test_ai_drop_projection_and_resolution_use_scenario_recovery(self):
        self.set_turns("AIR_DROP_RECOVERY", 3)
        target = tile(self.game, 4, 30, owner="B")
        queries.build_air_geometry(self.game)
        with patch.object(ai_movement, "_attackers_would_survive", return_value=True) as projection:
            ai_movement._assign_air_transport(self.game, "A", self.fixture.plane, self.base, [], [target], [])
        dropped = projection.call_args.args[3]
        self.assertTrue(dropped)
        self.assertTrue(all(queries.air_drop_recovery_turns(unit) == 3 for unit in dropped))
        air_processor.process_air_orders(self.game)
        self.assertEqual(queries.air_drop_recovery_turns(self.fixture.cargo), 3)

    def test_save_dictionary_preserves_independent_scenario_timers(self):
        self.set_turns("TRUCK_SHIP", 1)
        self.set_turns("AIR_DROP_RECOVERY", 3)
        screen = sample_map_screen()
        screen.scenario_settings = self.game.scenario_settings
        restored = json.loads(json.dumps(queries.build_save_dict(screen)))["scenario_settings"]
        self.assertEqual(restored, self.game.scenario_settings)
        self.assertEqual(queries.get_conversion_turns("TRUCK_SHIP", restored), 1)
        self.assertEqual(queries.get_conversion_turns("AIR_DROP_RECOVERY", restored), 3)
