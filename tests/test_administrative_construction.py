"""Scenario administrative timers agree across UI, AI and host boundaries."""
import copy
import json
import unittest
from types import SimpleNamespace
from unittest import mock

from data import queries
import data.constants as c
from data.io.multiplayer_io import _validate_administrative_orders
from data.io.realtime_multiplayer import MapRealtimeDriver, RealtimeError
from map_logic.ai.ai_construction import _apply_coring_priority
from tests.test_map_save_format import sample_map_screen


class AdministrativeConstructionTests(unittest.TestCase):
    def setUp(self):
        self.settings = {"administrative_turn_overrides": {}, "administrative_disabled": []}
        self.province = {"id": 1, "json_key": "home", "owner": "A", "cores": ["B"],
                         "is_coastal": True, "building_queue": [], "units": []}
        self.world = SimpleNamespace(scenario_settings=self.settings,
                                     map_data={1: self.province},
                                     nation_data={"A": {"manpower": c.AI_SURPLUS_MANPOWER_FOR_CORING * 100}},
                                     id_to_province={1: self.province})

    def test_defaults_and_malformed_override(self):
        for order, (name, constant) in queries.ADMINISTRATIVE_ACTIONS.items():
            self.assertEqual(queries.get_administrative_turns(order, {}), getattr(c, constant))
            for invalid in (None, "invalid", {}):
                self.settings["administrative_turn_overrides"][name] = invalid
                self.assertEqual(queries.get_administrative_turns(order, self.settings), getattr(c, constant))
            self.settings["administrative_turn_overrides"][name] = -3
            self.assertEqual(queries.get_administrative_turns(order, self.settings), 1)

    def test_independent_disabling_and_shared_cost_timers(self):
        for order, (name, constant) in queries.ADMINISTRATIVE_ACTIONS.items():
            duration = getattr(c, constant) + 3
            self.settings["administrative_turn_overrides"][name] = duration
            cost_fn = queries.get_core_cost if order == "CORE" else queries.get_remove_core_cost
            self.assertEqual(cost_fn("A", self.world.map_data, self.settings)["time"], duration)
            self.settings["administrative_disabled"] = [name]
            self.assertFalse(queries.is_administrative_action_enabled(order, self.settings))
            other = next(key for key in queries.ADMINISTRATIVE_ACTIONS if key != order)
            self.assertTrue(queries.is_administrative_action_enabled(other, self.settings))
        self.settings["disable_cores"] = True
        for order in queries.ADMINISTRATIVE_ACTIONS:
            self.assertFalse(queries.is_administrative_action_enabled(order, self.settings))

    def test_ai_uses_timer_and_does_not_spend_when_disabled(self):
        name = queries.ADMINISTRATIVE_ACTIONS["CORE"][0]
        duration = c.CORE_CONSTRUCTION_TURNS + 3
        self.settings["administrative_turn_overrides"][name] = duration
        country = self.world.nation_data["A"]
        before = copy.deepcopy(country)
        self.settings["administrative_disabled"] = [name]
        _apply_coring_priority(self.world, "A", country, [self.province])
        self.assertEqual(country, before)
        self.assertFalse(self.province["building_queue"])
        self.settings["administrative_disabled"] = []
        with mock.patch.object(queries, "has_industry", return_value=False):
            _apply_coring_priority(self.world, "A", country, [self.province])
        self.assertEqual(self.province["building_queue"][0]["turns_remaining"], duration)

    def test_realtime_rebuilds_timers_and_rejects_disabled_actions(self):
        driver = MapRealtimeDriver(self.world)
        for order, (name, constant) in queries.ADMINISTRATIVE_ACTIONS.items():
            duration = getattr(c, constant) + 3
            self.settings["administrative_turn_overrides"][name] = duration
            intent = {"order_type": order, "turns_remaining": 999}
            item, _cost = driver._build_queue_item("A", self.province, "building_queue", intent)
            self.assertEqual(item["turns_remaining"], duration)
            self.settings["administrative_disabled"] = [name]
            with self.assertRaises(RealtimeError):
                driver._build_queue_item("A", self.province, "building_queue", intent)
            self.settings["administrative_disabled"] = []

    def test_tournament_validates_new_entries_preserves_paid_progress(self):
        for order, (name, constant) in queries.ADMINISTRATIVE_ACTIONS.items():
            duration = getattr(c, constant) + 3
            self.settings["administrative_turn_overrides"][name] = duration
            item = {"order_type": order, "turns_remaining": duration}
            updates = {"home": {"building_queue": [item]}}
            _validate_administrative_orders(self.world, "A", updates)
            with self.assertRaises(ValueError):
                _validate_administrative_orders(self.world, "B", updates)
            for malformed in (None, "3", True, duration + 1):
                item["turns_remaining"] = malformed
                with self.assertRaises(ValueError):
                    _validate_administrative_orders(self.world, "A", updates)
            item["turns_remaining"] = duration
            self.settings["administrative_disabled"] = [name]
            with self.assertRaises(ValueError):
                _validate_administrative_orders(self.world, "A", updates)
            item["turns_remaining"] = 1
            self.province["building_queue"] = [copy.deepcopy(item)]
            _validate_administrative_orders(self.world, "A", updates)
            self.province["building_queue"] = []
            self.settings["administrative_disabled"] = []

    def test_settings_survive_save_dictionary_and_json_round_trip(self):
        screen = sample_map_screen()
        name = queries.ADMINISTRATIVE_ACTIONS["REMOVE_CORE"][0]
        self.settings["administrative_turn_overrides"][name] = c.REMOVE_CORE_TURNS + 3
        self.settings["administrative_disabled"] = [name]
        screen.scenario_settings = self.settings
        restored = json.loads(json.dumps(queries.build_save_dict(screen)))["scenario_settings"]
        self.assertEqual(restored, self.settings)
        self.assertEqual(queries.get_administrative_turns("REMOVE_CORE", restored), c.REMOVE_CORE_TURNS + 3)

    def test_production_permissions_and_disabled_callback_cannot_spend(self):
        from screens.map_related_screens.production import Production_Screen
        screen = object.__new__(Production_Screen)
        screen.map_screen = self.world
        screen.target_province = self.province
        screen.can_edit_realtime = lambda: True
        self.world.player_country = "A"
        self.world.tactical_mode = False
        for order, (name, _constant) in queries.ADMINISTRATIVE_ACTIONS.items():
            self.assertTrue(screen._can_start_administrative_action(order))
            self.settings["administrative_disabled"] = [name]
            before = copy.deepcopy(self.world.nation_data)
            callback = screen.start_coring if order == "CORE" else screen.start_remove_cores
            callback()
            self.assertEqual(self.world.nation_data, before)
            self.assertFalse(self.province["building_queue"])
            self.settings["administrative_disabled"] = []
            for viewer, tactical in (("B", False), ("A", True)):
                self.world.player_country, self.world.tactical_mode = viewer, tactical
                self.assertFalse(screen._can_start_administrative_action(order))
            self.world.player_country, self.world.tactical_mode = "Spectator", False
            with mock.patch.object(c, "SPECTATOR_CAN_EDIT_PRODUCTION", False):
                self.assertFalse(screen._can_start_administrative_action(order))
            with mock.patch.object(c, "SPECTATOR_CAN_EDIT_PRODUCTION", True):
                self.assertTrue(screen._can_start_administrative_action(order))
            self.world.player_country = "A"

    def test_paid_core_order_finishes_after_its_configured_duration(self):
        from map_logic.turn_processing.economy_processor import process_queues
        name = queries.ADMINISTRATIVE_ACTIONS["CORE"][0]
        self.settings["administrative_turn_overrides"][name] = 3  # Artificial short scenario.
        duration = queries.get_administrative_turns("CORE", self.settings)
        self.province["building_queue"] = [{"order_type": "CORE", "turns_remaining": duration}]
        self.world.active_players = ["A"]
        self.world.player_country = "A"
        self.world.show_feedback = mock.Mock()
        self.settings["administrative_disabled"] = [name]  # Already paid work is preserved.
        with mock.patch.object(queries, "is_province_in_active_combat", return_value=False):
            for _ in range(duration - 1):
                process_queues(self.world)
                self.assertNotIn("A", self.province["cores"])
            process_queues(self.world)
        self.assertIn("A", self.province["cores"])
        self.assertFalse(self.province["building_queue"])
