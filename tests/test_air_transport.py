"""Transport rules use artificial unit data and authoritative network state."""
import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, Mock, patch

from data import queries
from data import constants as c
from data.io import multiplayer_io
from data.io.realtime_multiplayer import MapRealtimeDriver, RealtimeError, collect_map_commands
from map_logic.ai import ai_movement
from map_logic.ai import ai_unit_eval
from map_logic.turn_processing import air_processor, combat_processor, movement_processor, unit_events
from screens.map_related_screens.orders import Orders_Screen, _AirMissionSelectScreen
from tests import test_air_mechanics as air_tests
from tests.test_air_mechanics import install_air_fixture, world, tile, wing
from tests.test_tournament_moves import synchronous_progress


class TransportTests(unittest.TestCase):
    def setUp(self):
        install_air_fixture(self)
        library = queries.get_unit_library()
        library["Monoplane Transport"] = {
            "health": 1000, "attack": 0, "defense": 0, "speed": 1,
            "cost_materials": 500, "cost_manpower": 30, "cost_fuel": 20,
            "production_time": 2, "naval_unit": False,
            "air_role": "transport", "air_range_px": 100, "air_transport_capacity": 1}
        library["Monoplane Transport I"] = deepcopy(library["Monoplane Transport"])
        library["Fixture Cargo"] = {
            "health": 2800, "attack": 50, "defense": 0, "speed": 2,
            "cost_materials": 100, "cost_manpower": 40, "cost_fuel": 10,
            "production_time": 1, "naval_unit": False}
        with open(c.UNIT_DATA_PATH, "w", encoding="utf-8") as handle:
            json.dump(library, handle)
        self.game = world()
        self.base = tile(self.game, 1, 8)
        self.destination = tile(self.game, 2, 80)
        self.base["neighbors"] = [2]
        self.destination["neighbors"] = [1]
        queries.build_air_geometry(self.game)
        self.plane = wing(self.base, "Monoplane Transport")
        self.cargo = wing(self.base, "Fixture Cargo")

    def load(self):
        queries.set_air_cargo(self.game, "A", self.plane, self.base, [self.cargo["unit_id"]])

    def screen(self):
        screen = Orders_Screen()
        screen.map_screen = self.game
        screen.target_province = self.base
        screen.refresh_ui = Mock()
        screen._mark_draft_changed = Mock()
        self.game.show_feedback = Mock()
        return screen

    def test_only_transport_aircraft_offer_transport_and_only_move_is_a_flight(self):
        self.assertEqual(queries.available_air_missions(self.game, self.plane, self.base),
                         {"NONE", "MOVE", "TRANSPORT"})
        combat = wing(self.base, "Monoplane Bomber I")
        self.assertNotIn("TRANSPORT", queries.available_air_missions(self.game, combat, self.base))
        for kind in ("AIR_ATTACK", "AIR_PATROL", "BOMBARD"):
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                queries.canonical_unit_order(self.game, "A", self.base, self.plane,
                    {"type": kind, "target_id": 2, "priority": "WEAKEST"})
        self.assertEqual({o["type"] for o in ai_movement.legal_air_candidates(self.game, self.plane, self.base)},
                         {"AIR_REPOSITION"})

    def test_transport_range_comes_from_data_and_rejects_distant_destinations(self):
        radius = queries.air_unit_stats(self.plane)["air_range_px"]
        self.assertEqual(queries.air_order_radius(self.plane, "AIR_REPOSITION"), radius)
        far = tile(self.game, 3, int(self.base["center"][0] + radius + 1))
        queries.build_air_geometry(self.game)
        with self.assertRaises(ValueError):
            queries.air_move_order(self.game, self.plane, self.base, far, "MOVE")

    def plan_drop(self):
        target = tile(self.game, 4, 30, owner="B")
        queries.build_air_geometry(self.game)
        self.load()
        self.plane["order"] = queries.air_move_order(self.game, self.plane, self.base, target)
        self.assertEqual(self.plane["order"]["type"], "AIR_DROP")
        return target

    def test_air_drop_uses_half_move_range_and_includes_tile_boundary(self):
        self.load()
        radius = queries.air_order_radius(self.plane, "AIR_REPOSITION") / 2
        self.assertEqual(queries.air_order_radius(self.plane, "AIR_DROP"), radius)
        target = tile(self.game, 4, int(self.base["center"][0] + radius), owner="B")
        queries.build_air_geometry(self.game)
        order = queries.air_move_order(self.game, self.plane, self.base, target, "AIR_DROP")
        self.assertEqual(order["target_id"], target["id"])
        far = tile(self.game, 5, int(self.base["center"][0] + radius + 1), owner="B")
        queries.build_air_geometry(self.game)
        with self.assertRaises(ValueError):
            queries.air_move_order(self.game, self.plane, self.base, far, "AIR_DROP")

    def test_air_drop_requires_cargo_enemy_land_and_current_launch_base(self):
        target = self.plan_drop()
        good = deepcopy(self.plane["order"])
        sea = tile(self.game, 5, 40, water=True)
        queries.build_air_geometry(self.game)
        for order in (dict(good, target_id=self.base["id"]), dict(good, target_id=sea["id"]),
                      dict(good, base_id=999), dict(good, target_id=True), dict(good, target_id=999)):
            with self.subTest(order=order), self.assertRaises(ValueError):
                queries.canonical_air_order(self.game, self.plane, self.base, order)
        self.game.nation_data["A"]["at_war_with"].remove("B")
        self.game.nation_data["B"]["at_war_with"].remove("A")
        with self.assertRaises(ValueError):
            queries.canonical_air_order(self.game, self.plane, self.base, good)
        self.game.nation_data["A"]["at_war_with"].append("B")
        self.game.nation_data["B"]["at_war_with"].append("A")
        queries.set_air_cargo(self.game, "A", self.plane, self.base, [])
        self.assertNotIn("AIR_DROP", queries.available_air_missions(self.game, self.plane, self.base))
        for unit in (self.plane, wing(self.base, "Monoplane Bomber I")):
            with self.subTest(unit=unit["type"]), self.assertRaises(ValueError):
                queries.canonical_air_order(self.game, unit, self.base, good)

    def test_drop_keeps_carrier_at_base_and_cargo_joins_ground_capture(self):
        target = self.plan_drop()
        tile(self.game, 5, 180, owner="B")
        self.game.is_editor = False
        self.game.viewing_ai_moves = True
        self.assertEqual(queries.air_unit_mission_icon(self.plane), "AIR_DROP")
        self.assertEqual(queries.unit_map_stack_key(self.plane), ("AIR", "AIR_DROP"))
        self.assertEqual(queries.air_range_preview_kind(self.game, self.plane, target), "AIR_DROP")
        air_processor.process_air_orders(self.game)
        self.assertEqual(target["units"], [self.cargo])
        self.assertEqual(self.base["units"], [self.plane])
        self.assertFalse(self.plane.get("air_cargo"))
        self.assertEqual(queries.air_unit_mission(self.plane), "NONE")
        movement_processor.process_movement(self.game)
        combat_processor.process_combat(self.game)
        combat_processor.check_for_post_combat_captures(self.game)
        self.assertEqual(target["owner"], "A")
        air_processor.process_air_orders(self.game)
        self.assertEqual(target["units"], [self.cargo])

    def test_interception_damage_reaches_cargo_before_drop_and_retains_reports(self):
        target = self.plan_drop()
        wing(target, "Monoplane Fighter I", "B", order={"type": "AIR_PATROL"})
        plane_health, cargo_health = self.plane["health"], self.cargo["health"]
        with unit_events.record_turn(self.game):
            air_processor.process_air_orders(self.game)
        self.assertLess(self.plane["health"], plane_health)
        self.assertGreater(self.plane["health"], 0)
        self.assertAlmostEqual(self.cargo["health"], cargo_health * self.plane["health"] / plane_health)
        self.assertIn(self.cargo, target["units"])
        self.assertIn(self.plane, self.base["units"])
        self.assertTrue(any(row["unit_id"] == self.cargo["unit_id"] and "Interception" in row["details"]
                            for row in self.game.unit_event_log["events"]))

    def test_tied_drop_capture_returns_cargo_to_its_launch_tile(self):
        target = self.plan_drop()
        # Loading can follow earlier ground movement. Its old origin must not
        # become the return tile for a tied capture after this flight.
        self.cargo["_previous_province_id"] = self.destination["id"]
        wing(target, "Fixture Cargo", "C")
        self.game.scenario_settings["bounce_tiebreaker"] = True
        air_processor.process_air_orders(self.game)
        combat_processor.check_for_post_combat_captures(self.game)
        self.assertIn(self.cargo, self.base["units"])
        self.assertNotIn(self.cargo, self.destination["units"])
        self.assertNotIn(self.cargo, target["units"])
        self.assertEqual(target["owner"], "B")

    def test_destroyed_transport_and_all_cargo_never_reach_drop_tile(self):
        queries.air_unit_stats(self.plane)["air_transport_capacity"] = 2
        second = wing(self.base, "Fixture Cargo")
        target = self.plan_drop()
        queries.set_air_cargo(self.game, "A", self.plane, self.base,
                              [self.cargo["unit_id"], second["unit_id"]])
        defender = wing(target, "Monoplane Fighter I", "B", order={"type": "AIR_PATROL"})
        defender["attack"] = self.plane["health"] * 10
        air_processor.process_air_orders(self.game)
        self.assertEqual(self.plane["health"], 0)
        self.assertNotIn(self.plane, self.base["units"])
        for cargo in (self.cargo, second):
            self.assertEqual(cargo["health"], 0)
            self.assertNotIn(cargo, target["units"])

    def test_ground_garrison_cannot_shoot_the_transport_before_drop(self):
        target = self.plan_drop()
        defender = wing(target, "Fixture Cargo", "B")
        defender["attack"] = self.plane["health"] * 10
        plane_health, cargo_health = self.plane["health"], self.cargo["health"]
        air_processor.process_air_orders(self.game)
        self.assertEqual(self.plane["health"], plane_health)
        self.assertEqual(self.cargo["health"], cargo_health)
        self.assertIn(self.cargo, target["units"])
        combat_processor.process_combat(self.game)
        self.assertEqual(self.cargo["health"], 0)
        self.assertEqual(self.plane["health"], plane_health)

    def test_drop_cancels_safely_after_peace(self):
        target = self.plan_drop()
        self.game.nation_data["A"]["at_war_with"].remove("B")
        self.game.nation_data["B"]["at_war_with"].remove("A")
        air_processor.process_air_orders(self.game)
        self.assertEqual(queries.air_unit_mission(self.plane), "NONE")
        self.assertEqual(self.plane["air_cargo"], [self.cargo])
        self.assertNotIn(self.cargo, target["units"])

    def test_map_movement_click_routes_loaded_transport_to_air_drop(self):
        from screens.menu_screens.map import Map
        target = self.plan_drop()
        self.plane.pop("order")
        self.game.can_select_map_units = lambda: True
        self.game.selected_unit_records = lambda: [(self.plane, self.base)]
        self.game.invalidate_map_presentation_cache = Mock()
        self.game.show_feedback = Mock()
        self.assertTrue(Map.issue_selected_move_orders(self.game, target))
        self.assertEqual(queries.air_unit_mission(self.plane), "AIR_DROP")

    def test_group_drop_preserves_all_orders_if_one_transport_cannot_reach(self):
        target = self.plan_drop()
        remote = tile(self.game, 5, 300)
        second = wing(remote, "Monoplane Transport")
        cargo = wing(remote, "Fixture Cargo")
        queries.set_air_cargo(self.game, "A", second, remote, [cargo["unit_id"]])
        queries.build_air_geometry(self.game)
        screen = self.screen()
        records = [(self.plane, self.base), (second, remote)]
        before = [deepcopy(unit["order"]) for unit, _base in records]
        screen.set_selected_air_mission("AIR_DROP", records)
        screen.set_air_target(target)
        self.assertEqual([unit["order"] for unit, _base in records], before)
        self.assertEqual(screen._air_target_records, records)

    def test_drop_and_strike_share_interception_but_only_bomber_strikes(self):
        from map_logic.turn_processing import combat_rules
        target = self.plan_drop()
        bomber = wing(self.base, "Monoplane Bomber I", order={"type": "AIR_ATTACK", "target_id": target["id"]})
        defender = wing(target, "Monoplane Fighter I", "B", order={"type": "AIR_PATROL"})
        with patch.object(combat_rules, "build_battle", wraps=combat_rules.build_battle) as build:
            air_processor.process_air_orders(self.game)
        interception, strike = build.call_args_list
        self.assertTrue(interception.kwargs["air_combat"])
        self.assertEqual({id(unit) for unit in interception.args[0][0]},
                         {id(self.plane), id(bomber), id(defender)})
        self.assertEqual(strike.args[0][0], [bomber])
        self.assertIn(self.cargo, target["units"])

    def test_ai_loads_and_drops_only_legal_cargo_on_reachable_enemy_land(self):
        target = tile(self.game, 4, 30, owner="B")
        queries.build_air_geometry(self.game)
        ai_movement._assign_air_transport(self.game, "A", self.plane, self.base, [],
                                          [target], [(self.plane, self.base), (self.cargo, self.base)])
        self.assertEqual(self.plane["air_cargo"], [self.cargo])
        self.assertEqual(self.plane["order"]["type"], "AIR_DROP")
        self.assertIn(self.plane["order"], ai_movement.legal_air_candidates(self.game, self.plane, self.base))
        self.assertNotIn("AIR_ATTACK", {order["type"] for order in
            ai_movement.legal_air_candidates(self.game, self.plane, self.base)})

    def test_ai_drop_respects_tactical_control_and_first_exchange_survival(self):
        target = tile(self.game, 4, 30, owner="B")
        queries.build_air_geometry(self.game)
        self.game.tactical_mode = True
        self.game.player_unit = self.cargo
        ai_movement._assign_air_transport(self.game, "A", self.plane, self.base, [], [target], [])
        self.assertFalse(self.plane.get("air_cargo"))
        self.game.tactical_mode = False
        defender = wing(target, "Fixture Cargo", "B")
        defender["attack"] = self.cargo["health"] * 10
        ai_movement._assign_air_transport(self.game, "A", self.plane, self.base, [], [target], [])
        self.assertFalse(self.plane.get("air_cargo"))

    def test_drop_ui_picker_targets_and_rechecks_permissions(self):
        target = self.plan_drop()
        self.plane.pop("order")
        screen = self.screen()
        with patch("ui.screen_runner._run_pygame_sub_screen") as runner:
            screen.open_air_transport(self.plane, self.base)
        popup = runner.call_args.args[1]
        popup.select(next(item for item in popup.items if item[1][0] == "AIR_DROP"))
        self.assertEqual(screen._air_target_mission, "AIR_DROP")
        self.assertEqual(queries.air_unit_mission(self.plane), "NONE")
        screen._refresh_air_range_previews()
        self.assertEqual(screen.air_strike_range_previews,
                         [(self.base, queries.air_order_radius(self.plane, "AIR_DROP"))])
        screen.read_only = True
        screen.set_air_target(target)
        self.assertEqual(queries.air_unit_mission(self.plane), "NONE")
        screen.read_only = False
        screen.set_air_mission(self.plane, self.base, "AIR_DROP")
        screen.set_air_target(target)
        self.assertEqual(queries.air_unit_mission(self.plane), "AIR_DROP")

    def drop_client(self):
        target = tile(self.game, 4, 30, owner="B")
        queries.build_air_geometry(self.game)
        client = deepcopy(self.game)
        base = client.id_to_province[self.base["id"]]
        plane, cargo = base["units"]
        queries.set_air_cargo(client, "A", plane, base, [cargo["unit_id"]])
        plane["order"] = queries.air_move_order(client, plane, base, client.id_to_province[target["id"]])
        return client, plane, cargo, target

    def test_realtime_load_and_drop_in_one_draft_keep_host_health(self):
        client, plane, cargo, target = self.drop_client()
        plane["health"], cargo["health"] = 1, 1
        commands = [command for command in collect_map_commands(client, "A")
                    if command["type"] in ("air_transport", "unit_order")]
        driver = MapRealtimeDriver(self.game)
        canonical = driver.validate_draft("A", commands)
        self.assertEqual(self.base["units"], [self.plane, self.cargo])
        with patch("map_logic.turn_processing.turn_processor.prepare_turn", new=AsyncMock()), \
                patch("map_logic.turn_processing.turn_processor.resolve_turn_logic", new=AsyncMock()):
            driver.process_turn({"A": canonical})
        self.assertEqual(queries.air_unit_mission(self.plane), "AIR_DROP")
        air_processor.process_air_orders(self.game)
        self.assertIn(self.cargo, target["units"])
        self.assertEqual(self.cargo["health"], self.cargo["max_health"])
        self.assertEqual(self.plane["health"], self.plane["max_health"])

    def test_realtime_rejects_unauthorized_malformed_stale_or_empty_drop(self):
        client, plane, cargo, _target = self.drop_client()
        commands = [command for command in collect_map_commands(client, "A")
                    if command["type"] in ("air_transport", "unit_order")]
        driver = MapRealtimeDriver(self.game)
        for bad_order in (dict(plane["order"], base_id=999), dict(plane["order"], target_id=True),
                          dict(plane["order"], target_id=2), dict(plane["order"], target_id=999)):
            bad = deepcopy(commands)
            next(command for command in bad if command["type"] == "unit_order")["order"] = bad_order
            with self.subTest(order=bad_order), self.assertRaises(RealtimeError):
                driver.validate_draft("A", bad)
            self.assertEqual(self.base["units"], [self.plane, self.cargo])
        with self.assertRaises(RealtimeError):
            driver.validate_draft("B", commands)
        with self.assertRaises(RealtimeError):
            driver.validate_draft("A", [command for command in commands if command["type"] != "air_transport"])

    def test_tournament_load_and_drop_keep_host_cargo_and_health(self):
        client, plane, cargo, target = self.drop_client()
        plane["health"], cargo["health"] = 1, 1
        self.assertEqual(self.import_client(client)["loaded"], 1)
        self.assertEqual(queries.air_unit_mission(self.plane), "AIR_DROP")
        air_processor.process_air_orders(self.game)
        self.assertIn(self.cargo, target["units"])
        self.assertEqual(self.cargo["health"], self.cargo["max_health"])
        self.assertEqual(self.plane["health"], self.plane["max_health"])

    def test_tournament_rejects_invalid_or_stale_drop_atomically(self):
        client, plane, _cargo, _target = self.drop_client()
        for transform in (lambda data: data["aircraft_orders"][0]["order"].update(base_id=999),
                          lambda data: data["aircraft_orders"][0]["order"].update(target_id=True),
                          lambda data: data["aircraft_orders"][0]["order"].update(target_id=2),
                          lambda data: data["air_transport"][0].update(cargo_ids=[]),
                          lambda data: data.update(tournament_turn=0)):
            with self.subTest(transform=transform):
                before = deepcopy(self.game.map_data)
                self.assertEqual(self.import_client(client, transform)["rejected"], 1)
                self.assertEqual(self.game.map_data, before)

    def test_load_release_preserve_identity_health_and_allow_immediate_movement(self):
        self.cargo["order"] = {"type": "MOVE", "path": [2]}
        self.load()
        self.assertEqual(self.base["units"], [self.plane])
        self.assertIs(self.plane["air_cargo"][0], self.cargo)
        self.assertEqual(self.cargo["order"], {"type": "MOVE", "path": []})
        queries.set_air_cargo(self.game, "A", self.plane, self.base, [])
        self.cargo["order"] = queries.canonical_unit_order(self.game, "A", self.base, self.cargo,
                                                          {"type": "MOVE", "path": [2]})
        movement_processor.process_movement(self.game)
        self.assertIn(self.cargo, self.destination["units"])

    def test_flight_keeps_cargo_hidden_and_releases_at_destination(self):
        self.load()
        self.plane["order"] = queries.air_move_order(self.game, self.plane, self.base, self.destination, "MOVE")
        self.assertEqual(queries.air_unit_mission(self.plane), "MOVE")
        self.assertEqual(queries.air_unit_mission_icon(self.plane), "TRANSPORT")
        self.assertEqual(queries.unit_map_stack_key(self.plane), ("AIR", "TRANSPORT"))
        air_processor.process_air_orders(self.game)
        self.assertEqual(self.base["units"], [])
        self.assertEqual(self.destination["units"], [self.plane])
        self.assertEqual(queries.air_unit_mission_icon(self.plane), "TRANSPORT")
        queries.set_air_cargo(self.game, "A", self.plane, self.destination, [])
        self.assertIn(self.cargo, self.destination["units"])
        self.assertEqual(queries.air_unit_mission_icon(self.plane), "NONE")

    def test_capacity_is_data_driven_and_rejections_are_atomic(self):
        second = wing(self.base, "Fixture Cargo")
        ids = [self.cargo["unit_id"], second["unit_id"]]
        before = deepcopy(self.game.map_data)
        with self.assertRaises(ValueError):
            queries.set_air_cargo(self.game, "A", self.plane, self.base, ids)
        self.assertEqual(self.game.map_data, before)
        queries.air_unit_stats(self.plane)["air_transport_capacity"] = 3
        queries.set_air_cargo(self.game, "A", self.plane, self.base, ids)
        self.assertEqual(self.plane["air_cargo"], [self.cargo, second])
        queries.set_air_cargo(self.game, "A", self.plane, self.base, [second["unit_id"]])
        self.assertIn(self.cargo, self.base["units"])
        self.assertEqual(queries.air_unit_mission_icon(self.plane), "TRANSPORT")

    def test_transport_transfer_does_not_depend_on_carrier_command_order(self):
        receiving = wing(self.base, "Monoplane Transport")
        self.load()
        commands = queries.air_transport_commands(self.game, "A")
        commands[0]["cargo_ids"] = []
        commands[1]["cargo_ids"] = [self.cargo["unit_id"]]
        queries.apply_air_transport_commands(self.game, "A", list(reversed(commands)))
        self.assertEqual(self.plane["air_cargo"], [])
        self.assertIs(receiving["air_cargo"][0], self.cargo)
        self.assertNotIn(self.cargo, self.base["units"])

    def test_paid_order_and_invalid_base_reject_cargo_changes_without_mutation(self):
        self.cargo["order"] = {"type": "REPAIR", "refund": {"cost_materials": 10}}
        before = deepcopy(self.game.map_data)
        with self.assertRaises(ValueError):
            self.load()
        self.assertEqual(self.game.map_data, before)
        self.cargo["order"] = {"type": "MOVE", "path": []}
        self.load()
        wing(self.base, "Infantry Type 1910", "B")
        before = deepcopy(self.game.map_data)
        with self.assertRaises(ValueError):
            queries.set_air_cargo(self.game, "A", self.plane, self.base, [])
        self.assertEqual(self.game.map_data, before)

    def test_ai_loads_moves_and_releases_ground_reinforcements(self):
        enemy = tile(self.game, 3, 220, owner="B")
        queries.build_air_geometry(self.game)
        records = [(self.plane, self.base), (self.cargo, self.base)]
        relocation = queries.air_move_order(self.game, self.plane, self.base, self.destination, "MOVE")
        ai_movement._assign_air_transport(self.game, "A", self.plane, self.base,
                                          [relocation], [enemy], records)
        self.assertEqual(self.plane["air_cargo"], [self.cargo])
        self.assertEqual(self.plane["order"], relocation)
        air_processor.process_air_orders(self.game)
        ai_movement._assign_air_transport(self.game, "A", self.plane, self.destination, [], [enemy], records)
        self.assertEqual(self.plane["air_cargo"], [])
        self.assertIn((self.cargo, self.destination), records)

    def test_ai_transport_valuation_uses_capacity_range_and_separate_role(self):
        library = queries.get_unit_library()
        ctx = ai_unit_eval.context(dict.fromkeys(ai_unit_eval.RESOURCES, 1))
        value = ai_unit_eval.evaluate(["Monoplane Transport"], library, ctx)["Monoplane Transport"]
        self.assertEqual(value.role, ai_unit_eval.ROLE_TRANSPORT)
        library["Monoplane Transport"]["air_transport_capacity"] *= 2
        larger = ai_unit_eval.evaluate(["Monoplane Transport"], library, ctx)["Monoplane Transport"]
        self.assertGreater(larger.score, value.score)
        library["Monoplane Transport"]["air_range_px"] *= 2
        farther = ai_unit_eval.evaluate(["Monoplane Transport"], library, ctx)["Monoplane Transport"]
        self.assertGreater(farther.score, larger.score)

    def test_load_rejects_planes_ships_foreign_units_remote_units_and_tactical_division(self):
        candidates = [wing(self.base, "Battleship"), wing(self.base, "Monoplane Bomber I"),
                      wing(self.base, "Fixture Cargo", "B"), wing(self.destination, "Fixture Cargo")]
        for unit in candidates:
            with self.subTest(unit=unit["type"]), self.assertRaises(ValueError):
                queries.set_air_cargo(self.game, "A", self.plane, self.base, [unit["unit_id"]])
        self.game.tactical_mode = True
        self.game.player_unit = self.cargo
        with self.assertRaises(ValueError):
            self.load()

    def test_ship_packed_in_truck_can_be_cargo(self):
        ship = wing(self.base, "Battleship")
        queries.load_transport(ship, "Truck")
        queries.set_air_cargo(self.game, "A", self.plane, self.base, [ship["unit_id"]])
        queries.set_air_cargo(self.game, "A", self.plane, self.base, [])
        self.assertEqual(ship["original_type"], "Battleship")
        self.assertTrue(ship["type"].startswith("Truck ("))

    def test_damage_matches_both_examples_and_compounds_from_current_health(self):
        self.load()
        for plane_hp, cargo_hp, cargo_max, damage, expected in (
                (500, 1400, 2800, 250, 700), (1000, 1000, 2000, 250, 250)):
            with self.subTest(plane_hp=plane_hp):
                self.plane["health"] = plane_hp
                self.cargo.update(health=cargo_hp, max_health=cargo_max)
                combat_processor.apply_group_damage(damage, [self.plane])
                self.assertEqual(self.cargo["health"], cargo_hp - expected)
                combat_processor.apply_group_damage(plane_hp - damage, [self.plane])
                self.assertEqual(self.cargo["health"], 0)

    def test_ground_destruction_kills_cargo_and_records_its_damage(self):
        self.load()
        wing(self.base, "Infantry Type 1910", "B")
        with unit_events.record_turn(self.game):
            queries.prepare_aircraft_for_ground_combat(self.base["units"], self.game.nation_data)
        self.assertEqual(self.cargo["health"], 0)
        self.assertEqual(self.plane["health"], 0)
        self.assertTrue(any(row["unit_id"] == self.cargo["unit_id"] for row in self.game.unit_event_log["events"]))

    def test_upkeep_ids_army_membership_and_migration_include_cargo(self):
        army = queries.create_army("A", [self.cargo["unit_id"]], self.game.nation_data, self.game.map_data)
        before = queries.calculate_all_economies(self.game.map_data, self.game.nation_data)["A"]["upkeep"]
        self.load()
        self.assertEqual(queries.calculate_all_economies(self.game.map_data, self.game.nation_data)["A"]["upkeep"], before)
        self.assertEqual(queries.ensure_unit_ids(self.game.map_data), [])
        queries.normalize_armies(self.game.nation_data, self.game.map_data)
        self.assertIn(self.cargo["unit_id"], army["unit_ids"])
        self.cargo["health"] /= 2
        queries.get_unit_library()["Fixture Cargo"]["health"] *= 2
        queries.migrate_units_to_current_stats(self.game.map_data, queries.get_unit_library())
        self.assertEqual(self.cargo["health"] / self.cargo["max_health"], 0.5)

    def test_carrier_ownership_changes_include_cargo_and_division_counts(self):
        from map_logic.diplomacy import volunteers
        before = volunteers.total_divisions(self.game, "A")
        self.load()
        self.assertEqual(volunteers.total_divisions(self.game, "A"), before)
        queries.set_unit_owner(self.plane, "B")
        self.assertEqual(self.plane["owner"], "B")
        self.assertEqual(self.cargo["owner"], "B")
        queries.set_air_cargo(self.game, "B", self.plane, self.base, [])
        self.assertIn(self.cargo, self.base["units"])

    def test_ui_picker_has_load_release_callbacks_and_rechecks_permission(self):
        screen = self.screen()
        with patch("ui.screen_runner._run_pygame_sub_screen") as runner:
            screen.open_air_transport(self.plane, self.base)
        popup = runner.call_args.args[1]
        popup.select(popup.items[0])
        self.assertEqual(self.plane["air_cargo"], [self.cargo])
        with patch("ui.screen_runner._run_pygame_sub_screen") as runner:
            screen.set_air_mission(self.plane, self.base, "TRANSPORT")
        popup = runner.call_args.args[1]
        screen.read_only = True
        popup.select(popup.items[0])
        self.assertEqual(self.plane["air_cargo"], [self.cargo])
        screen.read_only = False
        screen.change_air_transport(self.plane, self.base, "RELEASE", self.cargo["unit_id"])
        self.assertIn(self.cargo, self.base["units"])

    def test_loaded_transport_air_mission_button_opens_cargo_picker_directly(self):
        self.load()
        screen = self.screen()
        with patch("screens.map_related_screens.orders._AirMissionSelectScreen") as mission_picker, \
                patch("ui.screen_runner._run_pygame_sub_screen") as runner:
            screen.open_air_mission_select(0, self.base)
        mission_picker.assert_not_called()
        self.assertEqual(runner.call_args.args[1].title, "Air transport")

        screen._batch_command_candidates = Mock(return_value=[(self.plane, self.base)])
        with patch("screens.map_related_screens.orders._AirMissionSelectScreen") as mission_picker, \
                patch("ui.screen_runner._run_pygame_sub_screen") as runner:
            screen.open_selected_air_mission_select()
        mission_picker.assert_not_called()
        self.assertEqual(runner.call_args.args[1].title, "Air transport")

    def test_cargo_picker_stays_open_and_refreshes_after_each_load(self):
        queries.air_unit_stats(self.plane)["air_transport_capacity"] = 2
        second = wing(self.base, "Fixture Cargo")
        screen = self.screen()
        with patch("ui.screen_runner._run_pygame_sub_screen") as runner:
            screen.open_air_transport(self.plane, self.base)
        popup = runner.call_args.args[1]

        for unit in (self.cargo, second):
            item = next(item for item in popup.items
                        if item[1] == ("LOAD", unit["unit_id"]))
            popup.select(item)
            self.assertFalse(popup.done)
            self.assertIn(unit, self.plane["air_cargo"])

        self.assertEqual(popup.prompt, "Cargo: 2 / 2. Choose a unit to load or release.")
        self.assertFalse(any(item[1][0] == "LOAD" for item in popup.items))
        self.assertEqual({item[1][1] for item in popup.items if item[1][0] == "RELEASE"},
                         {self.cargo["unit_id"], second["unit_id"]})

    def test_disabled_mission_choices_remain_present_and_ignore_clicks(self):
        screen = self.screen()
        chosen = Mock()
        popup = _AirMissionSelectScreen(screen, c.AIR_MISSION_CHOICES, chosen,
            enabled_missions=queries.available_air_missions(self.game, self.plane, self.base))
        for index, (mission, _label, _icon) in enumerate(popup.choices):
            if mission in ("STRIKE", *queries.AIR_INTERCEPTION_PRIORITIES):
                self.assertTrue(popup.elements[index].disabled)
                popup.select(mission, chosen)
        chosen.assert_not_called()

    def test_cargo_picker_disables_loading_when_full_and_keeps_release_available(self):
        self.load()
        extra = wing(self.base, "Fixture Cargo")
        with patch("ui.screen_runner._run_pygame_sub_screen") as runner:
            self.screen().open_air_transport(self.plane, self.base)
        popup = runner.call_args.args[1]
        load = next(item for item in popup.items if item[1][1] == extra["unit_id"])
        release = next(item for item in popup.items if item[1][0] == "RELEASE")
        self.assertFalse(popup._item_enabled(load))
        self.assertTrue(popup._item_enabled(release))
        popup.select(load)
        self.assertEqual(self.plane["air_cargo"], [self.cargo])

    def test_realtime_validation_and_application_keep_host_stats(self):
        client = deepcopy(self.game)
        plane, cargo = client.id_to_province[1]["units"]
        queries.set_air_cargo(client, "A", plane, client.id_to_province[1], [cargo["unit_id"]])
        cargo["health"] = 1
        commands = [command for command in collect_map_commands(client, "A")
                    if command["type"] in ("air_transport", "unit_order")]
        driver = MapRealtimeDriver(self.game)
        canonical = driver.validate_draft("A", commands)
        self.assertEqual(self.base["units"], [self.plane, self.cargo])
        with patch("map_logic.turn_processing.turn_processor.prepare_turn", new=AsyncMock()), \
                patch("map_logic.turn_processing.turn_processor.resolve_turn_logic", new=AsyncMock()):
            driver.process_turn({"A": canonical})
        self.assertEqual(self.plane["air_cargo"], [self.cargo])
        self.assertEqual(self.cargo["health"], self.cargo["max_health"])

    def test_realtime_release_accepts_ground_order_from_same_draft(self):
        self.load()
        client = deepcopy(self.game)
        plane = client.id_to_province[1]["units"][0]
        queries.set_air_cargo(client, "A", plane, client.id_to_province[1], [])
        client.id_to_province[1]["units"][1]["order"] = {"type": "MOVE", "path": [2]}
        commands = [command for command in collect_map_commands(client, "A")
                    if command["type"] in ("air_transport", "unit_order")]
        canonical = MapRealtimeDriver(self.game).validate_draft("A", commands)
        ground = next(command for command in canonical if command.get("unit_id") == self.cargo["unit_id"])
        self.assertEqual(ground["order"]["path"], [2])
        self.assertNotIn(self.cargo, self.base["units"])

    def test_network_rejects_foreign_malformed_duplicate_and_stale_transport(self):
        good = dict(queries.air_transport_commands(self.game, "A")[0], cargo_ids=[self.cargo["unit_id"]])
        driver = MapRealtimeDriver(self.game)
        for commands in ([dict(good, cargo_ids=["unknown"])], [dict(good, cargo_ids="bad")],
                         [dict(good, province_id=2)], [good, good],
                         [dict(good, cargo_ids=[self.cargo["unit_id"]] * 2)]):
            with self.subTest(commands=commands), self.assertRaises(RealtimeError):
                driver.validate_draft("A", commands)
            self.assertEqual(self.base["units"], [self.plane, self.cargo])
        with self.assertRaises(RealtimeError):
            driver.validate_draft("B", [good])

    def test_tournament_rejects_foreign_transport_and_duplicate_cargo(self):
        foreign = wing(self.base, "Fixture Cargo", "B")
        wing(self.base, "Monoplane Transport")
        client = deepcopy(self.game)
        for transform in (lambda data: data["air_transport"][0].update(cargo_ids=[foreign["unit_id"]]),
                          lambda data: [command.update(cargo_ids=[self.cargo["unit_id"]])
                                        for command in data["air_transport"]]):
            with self.subTest(transform=transform):
                before = deepcopy(self.game.map_data)
                self.assertEqual(self.import_client(client, transform)["rejected"], 1)
                self.assertEqual(self.game.map_data, before)

    def test_loaded_carrier_disband_is_rejected_in_ui_and_execution(self):
        self.load()
        screen = self.screen()
        screen.disband_unit(0, self.base)
        self.assertNotEqual(self.plane["order"].get("type"), "DISBAND")
        with self.assertRaises(ValueError):
            queries.canonical_unit_order(self.game, "A", self.base, self.plane, {"type": "DISBAND"})
        self.plane["order"] = {"type": "DISBAND", "turns_left": 1}
        movement_processor.process_disbands(self.game)
        self.assertIn(self.plane, self.base["units"])
        self.assertEqual(self.plane["air_cargo"], [self.cargo])

    def test_snapshot_hides_foreign_cargo_even_without_fog(self):
        self.load()
        snapshot = queries.build_save_dict(self.game)
        self.game.scenario_settings["fog_of_war"] = False
        projected = queries.player_snapshot_projection(self.game, snapshot, "B")
        foreign = projected["provinces"][self.base["json_key"]]["units"][0]
        self.assertNotIn("air_cargo", foreign)
        own = queries.player_snapshot_projection(self.game, snapshot, "A")
        self.assertEqual(own["provinces"][self.base["json_key"]]["units"][0]["air_cargo"], [self.cargo])

    def import_client(self, client, transform=None):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "transport.gd5move")
            multiplayer_io.export_move_file(client, path, "key")
            if transform:
                with open(path) as handle:
                    payload = json.load(handle)
                data = multiplayer_io.decrypt_dict(payload["data"], "key")
                transform(data)
                payload["data"] = multiplayer_io.encrypt_dict(data, "key")
                with open(path, "w") as handle:
                    json.dump(payload, handle)
            with patch.object(multiplayer_io, "run_with_progress", synchronous_progress):
                return multiplayer_io.load_move_files(self.game, [path], {"A": "key"})

    def test_tournament_load_and_release_use_commands_preserve_stats_and_orders(self):
        client = deepcopy(self.game)
        plane, cargo = client.id_to_province[1]["units"]
        queries.set_air_cargo(client, "A", plane, client.id_to_province[1], [cargo["unit_id"]])
        cargo["health"] = 1
        self.assertEqual(self.import_client(client)["loaded"], 1)
        self.assertEqual(self.plane["air_cargo"], [self.cargo])
        client = deepcopy(self.game)
        plane = client.id_to_province[1]["units"][0]
        queries.set_air_cargo(client, "A", plane, client.id_to_province[1], [])
        released = client.id_to_province[1]["units"][1]
        released["order"] = {"type": "MOVE", "path": [2]}
        released["health"] = 1
        self.assertEqual(self.import_client(client)["loaded"], 1)
        self.assertEqual(self.cargo["health"], self.cargo["max_health"])
        self.assertEqual(self.cargo["order"]["path"], [2])
        self.assertEqual(len(self.base["units"]), 2)

    def test_tournament_rejects_bad_transport_and_stale_turn_atomically(self):
        client = deepcopy(self.game)
        for transform in (lambda data: data["air_transport"][0].update(cargo_ids=["missing"]),
                          lambda data: data["air_transport"][0].update(province_id=2),
                          lambda data: data.update(tournament_turn=0)):
            with self.subTest(transform=transform):
                before = deepcopy(self.game.map_data)
                self.assertEqual(self.import_client(client, transform)["rejected"], 1)
                self.assertEqual(self.game.map_data, before)


class TransportSaveSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests import app_harness
        cls.controller, cls.surface = app_harness.boot()

    def test_cargo_survives_actual_save_load_and_legacy_empty_defaults(self):
        case = TransportTests()
        self.addCleanup(case.doCleanups)
        case.setUp()
        with tempfile.TemporaryDirectory() as directory:
            game, _, _, _ = air_tests.AirAppSmokeTests.make_runtime_save(self, directory)
            base = game.id_to_province[1]
            plane = wing(base, "Monoplane Transport I")
            cargo = wing(base, "Fixture Cargo")
            queries.set_air_cargo(game, "A", plane, base, [cargo["unit_id"]])
            cargo["health"] /= 2
            plane["order"] = queries.air_move_order(game, plane, base, game.id_to_province[2])
            from data.map import save_map
            from screens.menu_screens.map import Map
            with patch.object(c, "SAVES_DIR", directory):
                asyncio.run(save_map.save_map_data(game, "cargo"))
            loaded = Map(load_path=os.path.join(directory, "cargo"), skip_initial_income=True)
            restored = next(u for u in loaded.id_to_province[1]["units"] if u["unit_id"] == plane["unit_id"])
            self.assertEqual(restored["air_cargo"][0]["unit_id"], cargo["unit_id"])
            self.assertEqual(restored["air_cargo"][0]["health"], cargo["health"])
            self.assertEqual(restored["order"], plane["order"])
            self.assertFalse(any(u["unit_id"] == cargo["unit_id"] for u in loaded.id_to_province[1]["units"]))
            loaded.selection_mode = False
            loaded.player_country = "A"
            loaded.select_map_units([restored])
            screen = Orders_Screen()
            screen.start_with_province(loaded.id_to_province[1], loaded)
            with patch.object(queries, "get_air_targets", side_effect=AssertionError("frame range calculation")), \
                    patch.object(queries, "canonical_air_order", side_effect=AssertionError("frame air rule")):
                screen.draw(self.surface)
            queries.set_air_cargo(loaded, "A", restored, loaded.id_to_province[1], [])
            air_processor.process_air_orders(loaded)
            self.assertEqual(queries.air_unit_mission(restored), "NONE")
            restored.pop("air_cargo")
            queries.normalize_air_orders(loaded.map_data)
            self.assertEqual(queries.air_unit_mission_icon(restored), "NONE")

    def test_load_filters_disabled_cargo_and_repairs_embarked_truck_stats(self):
        case = TransportTests()
        self.addCleanup(case.doCleanups)
        case.setUp()
        with tempfile.TemporaryDirectory() as directory:
            game, _, _, _ = air_tests.AirAppSmokeTests.make_runtime_save(self, directory)
            base = game.id_to_province[1]
            plane = wing(base, "Monoplane Transport I")
            truck = wing(base, "Fixture Cargo")
            truck["original_type"] = "Fixture Cargo"
            truck["type"] = "Truck (Fixture Cargo)"
            truck["defense"] = 99
            disabled_cargo = wing(base, "Fixture Cargo")
            disabled_cargo["type"] = "Fixture Disabled"
            plane["air_cargo"] = [truck, disabled_cargo]
            base["units"].remove(truck)
            base["units"].remove(disabled_cargo)
            game.scenario_settings["unit_disabled"] = ["Fixture Disabled"]

            from data.map import save_map
            from screens.menu_screens.map import Map
            with patch.object(c, "SAVES_DIR", directory):
                asyncio.run(save_map.save_map_data(game, "cargo-migrations"))
            loaded = Map(load_path=os.path.join(directory, "cargo-migrations"),
                         skip_initial_income=True)

        restored = next(unit for unit in loaded.id_to_province[1]["units"]
                        if unit["unit_id"] == plane["unit_id"])
        self.assertEqual([unit["type"] for unit in restored["air_cargo"]],
                         ["Truck (Fixture Cargo)"])
        self.assertEqual(restored["air_cargo"][0]["defense"], c.TRUCK_DEF)

    def test_real_content_matches_recipes_unlocks_and_png_assets(self):
        from data.generators.generate_data import build_unit_data_text, build_research_template_text
        names = [f"Monoplane Transport {c.ROMAN_NUMERALS[level]}" for level in range(1, 4)]
        generated_units = json.loads(build_unit_data_text())
        for name in names:
            with self.subTest(unit=name):
                self.assertEqual(queries.get_unit_library()[name], generated_units[name])
        key, level = queries.get_unit_research_requirement(names[0])
        tree = queries.get_tech_tree()
        self.assertEqual(tree[key], json.loads(build_research_template_text())[key])
        research = dict(tree[key]["req"])
        self.assertTrue(queries.check_tech_requirements(research, tree[key]["req"], level))
        research[key] = level
        for name in names:
            unit_level = queries.get_unit_research_requirement(name)[1]
            self.assertTrue(queries.is_unit_unlocked(name, dict(research, **{key: unit_level})))
        for path in ("assets/classic/Monoplane Transport.png", "assets/images/Air Transport.png",
                     "assets/images/Air Drop.png"):
            self.assertEqual(Path(path).read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
