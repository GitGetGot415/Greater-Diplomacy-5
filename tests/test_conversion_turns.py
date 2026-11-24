"""Scenario conversion timers agree across controls, execution, saves, and hosts."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from data import constants as c, queries
from data.multiplayer.realtime.session import MapRealtimeDriver, RealtimeError
from map_logic.system32 import air_processor, combat_processor, movement_processor
from tests import test_air_transport as transport_tests
from tests.air_fixtures import tile, wing
from tests.stub_map_screen import sample_map_screen
from tests.tournament_fixtures import fast_tournament_crypto


@fast_tournament_crypto()
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
        self.game.world.nation_data["A"]["research"]["trucks"] = 1

    def set_turns(self, action, turns):
        name = queries.CONVERSION_ACTIONS[action][0]
        self.game.world.scenario_settings.setdefault("conversion_turn_overrides", {})[name] = turns
        self.game.world.scenario_settings["use_default_other"] = False

    def test_legacy_defaults_malformed_values_and_limits(self):
        for action, (name, constant) in queries.CONVERSION_ACTIONS.items():
            default = getattr(c, constant)
            self.assertEqual(queries.get_conversion_turns(action, {}), default)
            self.assertEqual(queries.get_conversion_library()[name]["time"], default)
            for invalid in (None, "2", True, 1.5, {}, []):
                self.set_turns(action, invalid)
                self.assertEqual(queries.get_conversion_turns(action, self.game.world.scenario_settings), default)
            legal_turns = range(c.MIN_CONVERSION_TURNS, c.MAX_CONVERSION_TURNS + 1)
            cases = [(turns, turns) for turns in legal_turns]
            cases.extend(((-5, c.MIN_CONVERSION_TURNS), (0, c.MIN_CONVERSION_TURNS),
                          (c.MAX_CONVERSION_TURNS + 1, c.MAX_CONVERSION_TURNS)))
            for raw, expected in cases:
                self.set_turns(action, raw)
                self.assertEqual(queries.get_conversion_turns(action, self.game.world.scenario_settings), expected)
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
                        movement_processor.process_unit_maintenance_orders(self.game, order_types={"CONVERT"})
                        self.assertEqual(self.ship["type"], source)
                        self.assertEqual(self.ship["order"]["turns_left"], remaining)
                    movement_processor.process_unit_maintenance_orders(self.game, order_types={"CONVERT"})
                    self.assertEqual(self.ship["type"], result)
                    self.assertEqual(self.ship["order"], {"type": "MOVE", "path": []})

    def test_realtime_rebuilds_new_duration_and_retains_progress(self):
        duration = c.MAX_CONVERSION_TURNS
        self.set_turns("TRUCK_SHIP", duration)
        driver = MapRealtimeDriver(self.game)
        for transported, target in ((False, "Truck"), (True, "Ship")):
            with self.subTest(transported=transported):
                if transported:
                    queries.load_transport(self.ship, "Truck")
                self.ship["order"] = {"type": "MOVE", "path": []}
                command = {"type": "unit_order", "province_id": self.base["id"],
                           "unit_id": self.ship["unit_id"],
                           "order": {"type": "CONVERT", "to": target, "turns_left": 0}}
                self.assertEqual(driver.validate_draft("A", [command])[0]["order"]["turns_left"], duration)
                with self.assertRaises(RealtimeError):
                    driver.validate_draft("B", [command])
                with self.assertRaises(RealtimeError):
                    driver.validate_draft("A", [dict(command, order={"type": "CONVERT", "to": "invalid"})])
                self.ship["order"] = {"type": "CONVERT", "to": target, "turns_left": duration - 1}
                self.assertEqual(driver.validate_draft("A", [command])[0]["order"], self.ship["order"])

    def test_tournament_uses_host_settings_in_both_directions_and_keeps_progress(self):
        duration = c.MAX_CONVERSION_TURNS
        self.set_turns("TRUCK_SHIP", duration)
        for transported, target in ((False, "Truck"), (True, "Ship")):
            with self.subTest(transported=transported):
                if transported:
                    queries.load_transport(self.ship, "Truck")
                client = deepcopy(self.game)
                client.world.scenario_settings["conversion_turn_overrides"] = {}
                draft = next(u for u in client.world.id_to_province[self.base["id"]]["units"]
                             if u["unit_id"] == self.ship["unit_id"])
                draft["order"] = {"type": "CONVERT", "to": target, "turns_left": 0}
                self.assertEqual(self.fixture.import_client(client)["loaded"], 1)
                self.ship = next(u for u in self.base["units"] if u["unit_id"] == self.ship["unit_id"])
                self.assertEqual(self.ship["order"]["turns_left"], duration)
                self.ship["order"]["turns_left"] = duration - 1
                self.assertEqual(self.fixture.import_client(client)["loaded"], 1)
                self.ship = next(u for u in self.base["units"] if u["unit_id"] == self.ship["unit_id"])
                self.assertEqual(self.ship["order"]["turns_left"], duration - 1)
                self.ship["order"] = {"type": "MOVE", "path": []}

    def test_tournament_rejects_illegal_and_stale_conversion_atomically(self):
        self.set_turns("TRUCK_SHIP", 2)
        client = deepcopy(self.game)
        draft = next(u for u in client.world.id_to_province[self.base["id"]]["units"]
                     if u["unit_id"] == self.ship["unit_id"])
        draft["order"] = {"type": "CONVERT", "to": "Truck", "turns_left": 2}

        def submitted_order(data):
            return next(command["order"] for command in data["player_intents"]
                        if command["type"] == "unit_order" and command["unit_id"] == self.ship["unit_id"])

        for change in (lambda data: data.update(tournament_turn=0),
                       lambda data: submitted_order(data).update(type=None),
                       lambda data: submitted_order(data).update(to="invalid")):
            before = deepcopy(self.game.world.map_data)
            self.assertEqual(self.fixture.import_client(client, change)["rejected"], 1)
            self.assertEqual(self.game.world.map_data, before)
        self.game.world.nation_data["A"]["research"]["trucks"] = 0
        self.assertEqual(self.fixture.import_client(client)["rejected"], 1)
        self.assertEqual(self.game.world.map_data, before)

    def test_ai_drop_projection_and_resolution_use_scenario_recovery(self):
        duration = c.MAX_CONVERSION_TURNS
        self.set_turns("AIR_DROP_RECOVERY", duration)
        target = self.fixture.factory(tile(self.game, 4, 30, owner="B"))
        self.fixture.plan_air()
        air_processor.process_air_orders(self.game)
        with patch.object(self.game, "presentation_enabled", False):
            combat_processor.check_for_post_combat_captures(self.game)
        self.assertEqual(target["owner"], "A")
        self.assertEqual(queries.air_drop_recovery_turns(self.fixture.cargo), duration)

    def test_save_dictionary_preserves_independent_scenario_timers(self):
        self.set_turns("TRUCK_SHIP", 1)
        self.set_turns("AIR_DROP_RECOVERY", c.MAX_CONVERSION_TURNS)
        screen = sample_map_screen()
        screen.world.scenario_settings = self.game.world.scenario_settings
        restored = json.loads(json.dumps(queries.build_save_dict(screen)))["scenario_settings"]
        self.assertEqual(restored, self.game.world.scenario_settings)
        self.assertEqual(queries.get_conversion_turns("TRUCK_SHIP", restored), 1)
        self.assertEqual(queries.get_conversion_turns("AIR_DROP_RECOVERY", restored), c.MAX_CONVERSION_TURNS)

    def test_unified_maintenance_orders_processes_mixed_actions(self):
        # Setup units with repair, convert, and disband orders on the same tile
        p = self.base
        p["industry"] = 1
        unit_repair = {"type": "Infantry", "owner": "A", "health": 10, "max_health": 100,
                       "order": {"type": "REPAIR", "turns_left": 1}}
        unit_convert = {"type": "Infantry", "owner": "A", "health": 100, "max_health": 100,
                        "order": {"type": "CONVERT", "to": "Truck", "turns_left": 1}}
        unit_disband = {"type": "Infantry", "owner": "A", "health": 100, "max_health": 100,
                        "order": {"type": "DISBAND", "turns_left": 1}}
        p["units"] = [unit_repair, unit_convert, unit_disband]

        movement_processor.process_unit_maintenance_orders(self.game)

        # Disbanded unit should be removed; repair and convert should be completed
        self.assertEqual(len(p["units"]), 2)
        repaired = next(u for u in p["units"] if u["health"] == 100 and "Truck" not in u["type"])
        converted = next(u for u in p["units"] if "Truck" in u["type"])
        self.assertEqual(repaired["order"], {"type": "MOVE", "path": []})
        self.assertEqual(converted["order"], {"type": "MOVE", "path": []})
