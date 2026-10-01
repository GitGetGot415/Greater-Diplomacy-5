"""Air rules across resolution, UI/AI, persistence and both network boundaries."""
import asyncio
import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
import pygame
from data import queries
import data.constants as c
from data.io import multiplayer_io
from data.io.realtime_multiplayer import (MapRealtimeDriver, RealtimeError, RealtimeServer,
                                         RealtimeSession, RealtimeConfig)
from map_logic.ai import ai_movement
from map_logic.turn_processing import air_processor, combat_processor, combat_rules, movement_processor
from screens.map_related_screens.orders import Orders_Screen
from screens.menu_screens.map import Map
from tests.test_tournament_moves import synchronous_progress


def world():
    nations = {name: {"name": name, "is_playable": True,
        "at_war_with": [other for other in ("A", "B", "C") if other != name],
        "research": {}, "materials": 100000, "fuel": 100000, "manpower": 100000}
        for name in ("A", "B", "C")}
    return SimpleNamespace(map_data={}, id_to_province={}, nation_data=nations,
        id_map=pygame.Surface((2400, 32)), scenario_settings={}, tactical_mode=False,
        player_unit=None, player_country="A", loop_map=False, active_players=["A"],
        current_player_index=0, script_variables={}, default_research={},
        time_manager=SimpleNamespace(day=1, month_index=0, year=1939, total_turns=4),
        multiplayer_session_key="air-test-session", submitted_moves=set())


def tile(game, pid, x, owner="A", water=False, width=4, center=None):
    color = (pid, 1, 1)
    province = {"id": pid, "center": center or (x + width / 2, 5), "map_color": color,
        "json_key": str(color), "terrain": c.WATER_TERRAINS[0] if water else "Plains",
        "owner": "Ocean" if water else owner, "units": [], "neighbors": [],
        "buildings": [], "cores": [], "resources": {}, "unit_queue": [], "building_queue": []}
    game.map_data[color] = province
    game.id_to_province[pid] = province
    pygame.draw.rect(game.id_map, color, pygame.Rect(x, 4, width, 2))
    return province


def wing(base, name="Piston Bomber", owner="A", order=None):
    unit = queries.create_unit_dict(name, owner, queries.get_unit_library())
    if order:
        unit["order"] = dict(order, base_id=base["id"])
    base["units"].append(unit)
    return unit


class RangeTests(unittest.TestCase):
    def setUp(self):
        self.game = world()
        self.base = tile(self.game, 1, 8)
        self.plane = wing(self.base)
        self.radius = queries.air_order_radius(self.plane, "AIR_ATTACK")

    def test_tile_edge_and_disconnected_pixels_count_when_center_is_outside(self):
        target = tile(self.game, 2, int(10 + self.radius), owner="B", center=(1500, 5))
        queries.build_air_geometry(self.game)
        self.assertEqual(queries.air_distance_squared(self.game, self.base, 2), self.radius ** 2)
        self.assertIn(2, queries.get_air_targets(self.game, self.plane, self.base, "AIR_ATTACK"))
        pygame.draw.rect(self.game.id_map, target["map_color"], (1800, 4, 4, 2))
        queries.build_air_geometry(self.game)
        self.assertIn(2, queries.get_air_targets(self.game, self.plane, self.base, "AIR_ATTACK"))

    def test_just_outside_radius_is_rejected(self):
        tile(self.game, 2, int(11 + self.radius), owner="B")
        with self.assertRaises(ValueError):
            queries.canonical_air_order(self.game, self.plane, self.base,
                {"type": "AIR_ATTACK", "target_id": 2})

    def test_camera_and_viewport_never_change_radius(self):
        tile(self.game, 2, 30, owner="B")
        before = queries.get_air_targets(self.game, self.plane, self.base, "AIR_ATTACK")
        self.game.camera = SimpleNamespace(zoom=0.01, pos=(10000, 999), tilt_factor=0.2)
        self.game.viewport = (1, 1)
        self.assertEqual(before, queries.get_air_targets(self.game, self.plane, self.base, "AIR_ATTACK"))

    def test_command_validation_checks_only_its_target_geometry(self):
        target = tile(self.game, 2, 30, owner="B")
        tile(self.game, 3, 900)
        queries.build_air_geometry(self.game)
        with patch.object(queries, "air_distance_squared", wraps=queries.air_distance_squared) as distance:
            queries.canonical_air_order(self.game, self.plane, self.base,
                {"type": "AIR_ATTACK", "target_id": target["id"]})
        self.assertEqual(distance.call_count, 1)
        self.assertEqual(distance.call_args.args[2], target["id"])

    def test_flight_crosses_water_and_foreign_land_without_adjacency(self):
        tile(self.game, 2, 25, water=True)
        target = tile(self.game, 3, int(10 + queries.air_order_radius(self.plane, "AIR_REPOSITION")), owner="B")
        order = queries.canonical_air_order(self.game, self.plane, self.base,
            {"type": "AIR_REPOSITION", "target_id": target["id"]})
        self.plane["order"] = order
        air_processor.process_air_orders(self.game)
        self.assertIn(self.plane, target["units"])
        self.assertEqual(target["owner"], "B")
        combat_processor.check_for_post_combat_captures(self.game)
        self.assertEqual(target["owner"], "B")

    def test_strike_water_but_cannot_land_or_launch_there(self):
        sea = tile(self.game, 2, 30, water=True)
        self.assertIn(2, queries.get_air_targets(self.game, self.plane, self.base, "AIR_ATTACK"))
        self.assertNotIn(2, queries.get_air_targets(self.game, self.plane, self.base, "AIR_REPOSITION"))
        with self.assertRaises(ValueError):
            queries.canonical_air_order(self.game, self.plane, sea, {"type": "AIR_PATROL"})

    def test_land_speed_does_not_define_flight_and_ordinary_move_is_illegal(self):
        target = tile(self.game, 2, 30, owner="B")
        self.base["neighbors"] = [2]
        self.plane["speed"] = 1000
        self.assertEqual(queries.air_order_radius(self.plane, "AIR_ATTACK"), self.radius)
        self.assertFalse(queries.can_unit_move_step(self.plane, self.base, target, self.game.nation_data))
        self.plane["order"] = {"type": "MOVE", "path": [2]}
        movement_processor.process_movement(self.game)
        self.assertIn(self.plane, self.base["units"])

    def test_geometry_rebuild_invalidates_distances(self):
        target = tile(self.game, 2, 30)
        first = queries.air_distance_squared(self.game, self.base, 2)
        self.game.id_map.fill((0, 0, 0), pygame.Rect(30, 4, 4, 2))
        pygame.draw.rect(self.game.id_map, target["map_color"], (900, 4, 4, 2))
        queries.build_air_geometry(self.game)
        self.assertGreater(queries.air_distance_squared(self.game, self.base, 2), first)

    def test_obsolete_air_move_cannot_pin_or_create_meeting_predictions(self):
        target = tile(self.game, 2, 30, owner="B")
        self.game.is_editor = False
        self.plane["order"] = {"type": "MOVE", "path": [2]}
        defender = wing(target, "Infantry Type 1910", "B", {"type": "MOVE", "path": [1]})
        self.assertEqual(combat_rules.movers_into(self.base, 2), [])
        self.assertEqual(combat_rules.find_meeting_pairs(self.game.map_data, self.game.nation_data), [])
        self.assertEqual(queries.get_combat_predictions(self.game), [])
        tile(self.game, 3, 45, owner="A")
        defender["order"] = {"type": "MOVE", "path": [3]}
        with patch.object(combat_rules, "build_battle", side_effect=AssertionError("air movement fight")):
            combat_processor.process_pinning(self.game)
        self.assertEqual(defender["order"]["path"], [3])


class AirResolutionTests(unittest.TestCase):
    def setUp(self):
        self.game = world()
        self.base = tile(self.game, 1, 8)
        self.target = tile(self.game, 2, 30, owner="B")
        self.defender_base = tile(self.game, 3, 50, owner="B")

    def attack(self, name="Piston Bomber"):
        return wing(self.base, name, order={"type": "AIR_ATTACK", "target_id": 2})

    def patrol(self, priority="WEAKEST"):
        return wing(self.defender_base, "Piston Fighter", "B",
                    {"type": "AIR_PATROL", "priority": priority})

    def test_once_only_returns_exact_base_and_retains_damage(self):
        attacker = self.attack()
        self.patrol()
        victim = wing(self.target, "Infantry Type 1910", "B")
        original_health = attacker["health"]
        air_processor.process_air_orders(self.game)
        self.assertIn(attacker, self.base["units"])
        self.assertLess(attacker["health"], original_health)
        damaged_health = victim["health"]
        air_processor.process_air_orders(self.game)
        self.assertEqual(victim["health"], damaged_health)
        self.assertEqual(attacker["order"], {"type": "MOVE", "path": []})
        self.assertEqual(self.target["owner"], "B")

    def test_all_attacking_wings_and_all_covering_fighters_share_one_battle(self):
        attackers = [self.attack() for _ in range(c.COMBAT_WIDTH)]
        defenders = [self.patrol() for _ in range(c.COMBAT_WIDTH)]
        build = combat_rules.build_battle
        with patch.object(combat_rules, "build_battle", wraps=build) as calls:
            air_processor.process_air_orders(self.game)
        self.assertEqual(calls.call_count, 1)
        self.assertEqual({id(u) for u in calls.call_args.args[0][0]},
                         {id(u) for u in attackers + defenders})
        battle = build([attackers + defenders], self.game.nation_data,
                       width=c.COMBAT_WIDTH, air_combat=True)
        self.assertEqual(len(battle.lanes), 1)
        self.assertEqual(len(battle.lanes[0].a.front), combat_rules.lane_slots(1, c.COMBAT_WIDTH))
        self.assertEqual(len(battle.lanes[0].b.front), combat_rules.lane_slots(1, c.COMBAT_WIDTH))

    def test_three_hostile_sides_use_shared_lanes_and_global_width(self):
        self.attack()
        self.patrol()
        third_base = tile(self.game, 4, 70, owner="C")
        wing(third_base, "Piston Fighter", "C", {"type": "AIR_PATROL"})
        battles = []
        build = combat_rules.build_battle
        def record(*args, **kwargs):
            battle = build(*args, **kwargs)
            battles.append(battle)
            return battle
        with patch.object(combat_rules, "build_battle", side_effect=record):
            air_processor.process_air_orders(self.game)
        self.assertEqual(len(battles[0].lanes), 3)
        self.assertEqual(battles[0].lanes[0].slots, combat_rules.lane_slots(3, c.COMBAT_WIDTH))

    def test_fighter_multiplier_only_against_air_and_not_trucks(self):
        fighter = wing(self.base, "Piston Fighter")
        aircraft = wing(self.target, "Piston Bomber", "B")
        ground = wing(self.target, "Infantry Type 1910", "B")
        air_attack = combat_rules.damage_shots([fighter], [aircraft], air_to_air=True)[0][1]
        ground_attack = combat_rules.damage_shots([fighter], [ground])[0][1]
        self.assertAlmostEqual(air_attack, ground_attack * queries.air_unit_stats(fighter)["air_attack_multiplier"])
        queries.load_transport(aircraft, "Truck")
        self.assertEqual(combat_rules.damage_shots([fighter], [aircraft])[0][1], ground_attack)

    def test_canonical_tanks_category_is_immune_but_infantry_is_not(self):
        plane = self.attack()
        library = queries.get_unit_library()
        tank_name = next(name for name, stats in library.items()
                         if queries.classify_unit_group(queries.get_base_unit_name(name), stats) == queries.UNIT_GROUP_TANKS)
        tank = wing(self.target, tank_name, "B")
        infantry = wing(self.target, "Infantry Type 1910", "B")
        for attacker, expected in ((tank, 0), (infantry, infantry["attack"])):
            before = plane["health"]
            for targets, damage in combat_rules.damage_shots([attacker], [plane]):
                combat_processor.apply_group_damage(damage, targets)
            self.assertEqual(before - plane["health"], expected)

    def test_bombardment_obeys_tank_category_immunity(self):
        rocket = self.attack("V2 Rocket")
        gun = wing(self.target, "WW1 Railroad Gun", "B")
        self.target["neighbors"] = [1]
        gun["order"] = {"type": "BOMBARD", "target_id": 1}
        health = rocket["health"]
        self.assertEqual(queries.classify_unit_group(queries.get_base_unit_name(gun["type"]),
            queries.get_unit_library()[gun["type"]]), queries.UNIT_GROUP_TANKS)
        combat_processor.process_bombardments(self.game)
        self.assertEqual(rocket["health"], health)

    def test_ground_combat_converts_before_damage_and_preserves_original_stats(self):
        aircraft = self.attack("V2 Rocket")
        original = dict(aircraft)
        tank = wing(self.base, "WW1 Tank", "B")
        combat_processor.process_combat(self.game)
        self.assertTrue(queries.is_air_transport(aircraft))
        self.assertFalse(queries.is_air_unit(aircraft))
        self.assertEqual(aircraft["original_attack"], original["attack"])
        self.assertLess(aircraft["health"], c.TRUCK_MAX_HP)
        self.assertEqual(aircraft["attack"], c.TRUCK_ATK)
        self.assertEqual(tank["health"], tank["max_health"] - max(0, c.TRUCK_ATK - tank["defense"]))

    def test_ground_preview_projects_conversion_without_mutating(self):
        aircraft = self.attack()
        tank = wing(self.base, "WW1 Tank", "B")
        before = dict(aircraft)
        battle = combat_rules.build_battle([[aircraft, tank]], self.game.nation_data)
        self.assertEqual(battle.profiles[id(aircraft)]["attack"], c.TRUCK_ATK)
        self.assertGreater(combat_rules.projected_incoming_damage(battle, self.game.nation_data)[id(aircraft)], 0)
        self.assertEqual(aircraft, before)

    def test_interceptions_repeat_in_requested_force_strength_order(self):
        third_target = tile(self.game, 4, 80, owner="B")
        for priority, expected_first in (("WEAKEST", 2), ("STRONGEST", 4)):
            with self.subTest(priority=priority):
                self.base["units"] = []
                self.defender_base["units"] = []
                weak = self.attack()
                strong = wing(self.base, order={"type": "AIR_ATTACK", "target_id": third_target["id"]})
                wing(self.base, order={"type": "AIR_ATTACK", "target_id": third_target["id"]})
                defender = self.patrol(priority)
                defender["health"] = defender["max_health"] = sum(
                    unit["attack"] for unit in self.base["units"]) * 2
                seen = []
                real = combat_rules.build_battle
                def record(sides, *args, **kwargs):
                    seen.append((next(u["order"]["target_id"] for u in sides[0]
                                      if u["order"]["type"] == "AIR_ATTACK"), defender["health"]))
                    return real(sides, *args, **kwargs)
                with patch.object(combat_rules, "build_battle", side_effect=record):
                    air_processor.process_air_orders(self.game)
                self.assertEqual(seen[0][0], expected_first)
                self.assertEqual(len(seen), 2)
                self.assertLess(seen[1][1], seen[0][1])

    def test_overlapping_coverage_respects_every_compatible_priority(self):
        middle = tile(self.game, 4, 80, owner="B")
        other_base = tile(self.game, 5, 100, owner="B")
        weakest = tile(self.game, 6, 120, owner="B")
        for target, count in ((self.target, 2), (middle, 3), (weakest, 1)):
            for _ in range(count):
                wing(self.base, order={"type": "AIR_ATTACK", "target_id": target["id"]})
        first = self.patrol()
        second = wing(other_base, "Piston Fighter", "B", {"type": "AIR_PATROL"})
        for defender in (first, second):
            defender["health"] = defender["max_health"] = sum(
                unit["attack"] for unit in self.base["units"]) * 2
        real_targets = queries.get_air_targets
        real_build = combat_rules.build_battle
        seen = []
        def coverage(game, unit, base, kind):
            if kind == "AIR_PATROL":
                return {2, 4} if unit is first else {4, 6}
            return real_targets(game, unit, base, kind)
        def record(sides, *args, **kwargs):
            seen.append(next(unit["order"]["target_id"] for unit in sides[0]
                             if unit["order"]["type"] == "AIR_ATTACK"))
            return real_build(sides, *args, **kwargs)
        with patch.object(queries, "get_air_targets", side_effect=coverage), \
                patch.object(combat_rules, "build_battle", side_effect=record):
            air_processor.process_air_orders(self.game)
        self.assertEqual(seen, [2, 6, 4])

    def test_v1_intercepted_v2_immune_and_both_consumed(self):
        for name, intercepted in (("V1 Flying Bomb", True), ("V2 Rocket", False)):
            with self.subTest(unit=name):
                self.base["units"] = []
                self.defender_base["units"] = []
                attacker = self.attack(name)
                self.patrol()
                with patch.object(combat_rules, "build_battle", wraps=combat_rules.build_battle) as build:
                    air_processor.process_air_orders(self.game)
                self.assertEqual(bool(build.call_count), intercepted)
                self.assertNotIn(attacker, self.base["units"])

    def test_destroyed_aircraft_has_no_ground_impact(self):
        attacker = self.attack("V1 Flying Bomb")
        attacker["health"] = 1
        self.patrol()
        victim = wing(self.target, "Infantry Type 1910", "B")
        health = victim["health"]
        air_processor.process_air_orders(self.game)
        self.assertEqual(victim["health"], health)
        self.assertNotIn(attacker, self.base["units"])

    def test_one_turn_truck_roundtrip_retains_fraction_and_original_type(self):
        unit = self.attack("V2 Rocket")
        unit["health"] *= 0.6
        unit["order"] = queries.air_conversion_order(unit)
        movement_processor.process_conversions(self.game)
        self.assertTrue(queries.is_air_transport(unit))
        self.assertAlmostEqual(unit["health"] / unit["max_health"], 0.6)
        unit["health"] *= 0.5
        unit["order"] = queries.air_conversion_order(unit)
        movement_processor.process_conversions(self.game)
        self.assertEqual(unit["type"], "V2 Rocket")
        self.assertAlmostEqual(unit["health"] / unit["max_health"], 0.3)
        self.assertNotIn("original_type", unit)

    def test_one_use_restrictions_and_full_strike_range(self):
        for name in ("V1 Flying Bomb", "V2 Rocket"):
            unit = self.attack(name)
            for kind in ("AIR_PATROL", "AIR_REPOSITION"):
                with self.subTest(unit=name, kind=kind), self.assertRaises(ValueError):
                    queries.canonical_air_order(self.game, unit, self.base, {"type": kind, "target_id": 2})
            self.assertEqual(queries.air_order_radius(unit, "AIR_ATTACK"), queries.air_unit_stats(unit)["air_range_px"])


class AirIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.game = world()
        self.base = tile(self.game, 1, 8)
        self.target = tile(self.game, 2, 30, owner="B")
        self.base["neighbors"] = [2]
        self.target["neighbors"] = [1]
        self.plane = wing(self.base)

    def test_legacy_patrol_defaults_and_save_transport_roundtrip(self):
        fighter = wing(self.base, "Biplane", order={"type": "AIR_PATROL"})
        queries.normalize_air_orders(self.game.map_data)
        self.assertEqual(fighter["order"]["priority"], queries.AIR_DEFAULT_PRIORITY)
        queries.load_transport(self.plane, "Truck")
        saved = json.loads(json.dumps(queries.build_save_dict(self.game)))
        recovered = saved["provinces"][self.base["json_key"]]["units"]
        queries.revert_transport(recovered[0])
        self.assertEqual(recovered[0]["type"], "Piston Bomber")
        self.assertEqual(recovered[1]["order"], fighter["order"])
        self.assertNotIn("_air_geometry", saved)

    def test_placeholder_migration_is_idempotent_and_preserves_damage(self):
        self.plane.update(max_health=1000, health=250, attack=100)
        queries.migrate_aircraft_stats(self.game.map_data)
        self.assertEqual(self.plane["attack"], queries.get_unit_library()[self.plane["type"]]["attack"])
        self.assertAlmostEqual(self.plane["health"] / self.plane["max_health"], 0.25)
        before = dict(self.plane)
        queries.migrate_aircraft_stats(self.game.map_data)
        self.assertEqual(self.plane, before)

    def test_ai_candidates_are_canonical_and_heuristic_issues_attack(self):
        candidates = ai_movement.legal_air_candidates(self.game, self.plane, self.base)
        for order in candidates:
            self.assertEqual(order, queries.canonical_air_order(self.game, self.plane, self.base, order))
        with patch("map_logic.ai.ai_handler.call_llm", create=True) as llm:
            ai_movement._assign_air_orders(self.game, "A", [(self.plane, self.base)])
            llm.assert_not_called()
        self.assertEqual(self.plane["order"]["type"], "AIR_ATTACK")

    def test_ui_strike_and_patrol_enforce_ownership_and_tactical_permission(self):
        screen = object.__new__(Orders_Screen)
        screen.map_screen = self.game
        screen.read_only = False
        screen.refresh_ui = Mock()
        screen._mark_draft_changed = Mock()
        self.game.show_feedback = Mock()
        screen.target_province = self.base
        screen.bombarding_unit_province = self.base
        fighter = wing(self.base, "Biplane")
        screen.cycle_air_patrol(1, self.base)
        self.assertEqual(fighter["order"]["priority"], queries.AIR_DEFAULT_PRIORITY)
        screen.cycle_air_patrol(1, self.base)
        self.assertEqual(fighter["order"]["priority"], "STRONGEST")
        self.game.tactical_mode = True
        self.game.player_unit = self.plane
        before = dict(fighter["order"])
        screen.cycle_air_patrol(1, self.base)
        self.assertEqual(fighter["order"], before)
        screen.set_bombard_target(0, self.target, self.base)
        self.assertEqual(self.plane["order"]["type"], "AIR_ATTACK")
        self.game.player_country = "Spectator"
        self.plane["order"] = {}
        screen.set_bombard_target(0, self.target, self.base)
        self.assertEqual(self.plane["order"], {})

    def test_realtime_air_orders_authority_and_malformed_input(self):
        driver = MapRealtimeDriver(self.game)
        command = {"type": "unit_order", "province_id": 1, "unit_index": 0,
                   "order": {"type": "AIR_ATTACK", "target_id": 2}}
        canonical = driver.validate_draft("A", [command])[0]
        self.assertEqual(canonical["order"]["base_id"], 1)
        self.assertEqual(self.plane["order"]["type"], "MOVE")
        with self.assertRaises(RealtimeError):
            driver.validate_draft("B", [command])
        for order in ({"type": "AIR_ATTACK", "target_id": True},
                      {"type": "AIR_ATTACK", "target_id": 999},
                      {"type": "AIR_ATTACK", "target_id": 2, "base_id": 2},
                      {"type": ["AIR_ATTACK"]}, {"type": "AIR_PATROL"}):
            with self.subTest(order=order), self.assertRaises(RealtimeError):
                driver.validate_draft("A", [dict(command, order=order)])
        with self.assertRaises(RealtimeError):
            driver.validate_draft("A", [command, command])

    def test_realtime_air_drafts_reject_stale_locked_and_nonplanning_turns(self):
        driver = MapRealtimeDriver(self.game)
        session = RealtimeSession(RealtimeConfig("air-test", {}, 2, 5, 10), ["A", "B"], "Host", driver)
        host = session.players[session.host_id]
        host.country_id = "A"
        commands = [{"type": "unit_order", "province_id": 1, "unit_index": 0,
                     "order": {"type": "AIR_ATTACK", "target_id": 2}}]
        with self.assertRaises(RealtimeError):
            session.sync_draft(host.player_id, session.turn_number, commands)
        session.phase = "TURN"
        session.sync_draft(host.player_id, session.turn_number, commands)
        self.assertEqual(host.draft[0]["order"]["type"], "AIR_ATTACK")
        self.assertEqual(self.plane["order"]["type"], "MOVE")
        with self.assertRaises(RealtimeError):
            session.sync_draft(host.player_id, session.turn_number + 1, commands)
        host.submitted = True
        with self.assertRaises(RealtimeError):
            session.sync_draft(host.player_id, session.turn_number, commands)

    def test_snapshot_hides_orders_and_fogged_units_including_initial_geometry(self):
        enemy = wing(self.target, "Piston Fighter", "B", {"type": "AIR_PATROL"})
        remote = tile(self.game, 3, 1000, owner="B")
        hidden = wing(remote, "V2 Rocket", "B")
        saved = queries.build_save_dict(self.game)
        saved["_raw_map_data"] = {p["json_key"]: dict(p) for p in self.game.map_data.values()}
        projected = queries.player_snapshot_projection(self.game, saved, "A")
        self.assertEqual(projected["provinces"][remote["json_key"]]["units"], [])
        self.assertNotIn("order", projected["provinces"][self.target["json_key"]]["units"][0])
        self.assertEqual(projected["_raw_map_data"][remote["json_key"]]["units"], [])
        self.assertIn("order", enemy)
        self.assertIn(hidden, remote["units"])
        server = object.__new__(RealtimeServer)
        server.session = SimpleNamespace(driver=MapRealtimeDriver(self.game),
            players={"guest": SimpleNamespace(country_id="A")})
        payload = server._project_payload({"state": {"game_state": saved}}, "guest")
        self.assertEqual(payload["state"]["game_state"], projected)

    def test_realtime_stable_id_handles_filtered_client_index(self):
        foreign = wing(self.base, "Piston Bomber", "B")
        self.game.nation_data["A"]["at_war_with"] = ["C"]
        self.game.nation_data["B"]["at_war_with"] = ["C"]
        self.base["units"] = [foreign, self.plane]
        command = {"type": "unit_order", "province_id": 1, "unit_index": 0,
            "unit_id": self.plane["unit_id"], "order": {"type": "AIR_ATTACK", "target_id": 2}}
        canonical = MapRealtimeDriver(self.game).validate_draft("A", [command])[0]
        self.assertEqual(canonical["unit_index"], 1)

    def test_tournament_command_roundtrip_retains_host_stats_and_position(self):
        self.plane["order"] = {"type": "AIR_ATTACK", "base_id": 1, "target_id": 2}
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "air.gd5move")
            multiplayer_io.export_move_file(self.game, path, "player-key")
            with open(path) as f:
                data = multiplayer_io.decrypt_dict(json.load(f)["data"], "player-key")
            self.assertEqual(len(data["aircraft_orders"]), 1)
            self.assertFalse(any(update.get("units") for update in data["provinces"].values()))
            self.plane["order"] = {}
            health = self.plane["health"]
            with patch.object(multiplayer_io, "run_with_progress", synchronous_progress):
                result = multiplayer_io.load_move_files(self.game, [path, path], {"A": "player-key"})
            self.assertEqual(result["loaded"], 1)
            self.assertEqual(result["rejected"], 1)
            self.assertEqual(self.plane["health"], health)
            self.assertIs(self.base["units"][0], self.plane)
            self.assertEqual(self.plane["order"]["type"], "AIR_ATTACK")

    def test_tournament_rejects_foreign_duplicate_malformed_and_out_of_range_orders(self):
        enemy = wing(self.target, "Biplane", "B")
        remote = tile(self.game, 3, 2000, owner="B")
        valid = {"unit_id": self.plane["unit_id"], "order": {"type": "AIR_ATTACK", "target_id": 2}}
        bad = ([dict(valid, unit_id=enemy["unit_id"])], [valid, valid],
               [dict(valid, order={"type": "AIR_ATTACK", "target_id": remote["id"]})],
               [dict(valid, order={"type": ["AIR_ATTACK"]})])
        for commands in bad:
            with self.subTest(commands=commands), self.assertRaises(ValueError):
                multiplayer_io._validate_aircraft_orders(self.game, "A", {"aircraft_orders": commands}, {})

    def test_tournament_legacy_snapshot_cannot_change_aircraft_health_or_location(self):
        submitted = dict(self.plane, health=1, attack=100000,
            order={"type": "AIR_ATTACK", "target_id": 2})
        live, drafts = multiplayer_io._validate_aircraft_orders(self.game, "A", {},
            {self.target["json_key"]: {"units": [submitted]}})
        self.assertIn(self.plane["unit_id"], live)
        self.assertIs(drafts[0][0], self.plane)
        self.assertEqual(self.plane["health"], self.plane["max_health"])
        self.assertEqual(drafts[0][1]["base_id"], self.base["id"])

    def test_tactical_ai_preserves_the_commanded_aircraft_order(self):
        self.game.tactical_mode = True
        self.game.player_unit = self.plane
        self.plane["order"] = {"type": "AIR_ATTACK", "target_id": 2, "base_id": 1}
        before = dict(self.plane["order"])
        collected, _provinces = ai_movement._reset_orders_and_collect_units(self.game, ["A"])
        self.assertNotIn((self.plane, self.base), collected["A"])
        ai_movement._assign_air_orders(self.game, "A", [(self.plane, self.base)])
        self.assertEqual(self.plane["order"], before)

    def test_tournament_stale_air_move_is_rejected_without_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "stale.gd5move")
            self.plane["order"] = {"type": "AIR_ATTACK", "base_id": 1, "target_id": 2}
            multiplayer_io.export_move_file(self.game, path, "player-key")
            self.game.time_manager.total_turns += 1
            self.plane["order"] = {}
            with patch.object(multiplayer_io, "run_with_progress", synchronous_progress):
                result = multiplayer_io.load_move_files(self.game, [path], {"A": "player-key"})
            self.assertEqual(result["rejected"], 1)
            self.assertEqual(self.plane["order"], {})

    def test_fighter_ground_strike_never_receives_air_bonus(self):
        attacker = wing(self.base, "Piston Fighter", order={"type": "AIR_ATTACK", "target_id": 2})
        based_enemy = wing(self.target, "Piston Bomber", "B")
        before = based_enemy["health"]
        air_processor.process_air_orders(self.game)
        expected = attacker["attack"] * combat_rules.effective_damage_multiplier(attacker, self.game.nation_data)
        self.assertAlmostEqual(before - based_enemy["health"], expected)

    def test_regeneration_preserves_air_stats_and_research_contract(self):
        from data.generators.generate_data import build_unit_data_text, build_research_template_text
        regenerated_units = json.loads(build_unit_data_text())
        regenerated_tree = json.loads(build_research_template_text())
        for name, stats in queries.get_unit_library().items():
            if stats.get("air_role"):
                self.assertEqual(regenerated_units[name], stats)
        for key, entry in queries.get_tech_tree().items():
            if entry.get("category") == "AEROSPACE":
                self.assertEqual(regenerated_tree[key], entry)


class AirAppSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests import app_harness
        cls.controller, cls.surface = app_harness.boot()

    def make_runtime_save(self, directory):
        game = world()
        base = tile(game, 1, 8)
        tile(game, 2, 30, owner="B")
        fighter = wing(base, "Biplane", order={"type": "AIR_PATROL", "priority": "STRONGEST"})
        rocket = wing(base, "V2 Rocket")
        queries.load_transport(rocket, "Truck")
        game.raw_json_data = {p["json_key"]: dict(p) for p in game.map_data.values()}
        game.terrain_map = game.id_map.copy()
        game.political_map = game.id_map.copy()
        game.cores_map = game.id_map.copy()
        game.is_editor = False
        game.history = {}
        game.show_feedback = Mock()
        with patch.object(c, "SAVES_DIR", directory):
            from data.map import save_map
            asyncio.run(save_map.save_map_data(game, "air-roundtrip"))
        return game, fighter, rocket, os.path.join(directory, "air-roundtrip")

    def test_actual_save_load_and_air_orders_panel_draw_cache_only(self):
        with tempfile.TemporaryDirectory() as directory:
            original, fighter, rocket, path = self.make_runtime_save(directory)
            loaded = Map(load_path=path, skip_initial_income=True)
            loaded.selection_mode = False
            loaded.player_country = "A"
            base = loaded.id_to_province[1]
            self.assertEqual(base["units"][0]["order"], fighter["order"])
            self.assertTrue(queries.is_air_transport(base["units"][1]))
            self.assertEqual(base["units"][1]["original_type"], rocket["original_type"])
            loaded.select_map_units(base["units"])
            screen = Orders_Screen()
            screen.start_with_province(base, loaded)
            screen.start_bombard_targeting(0, base)
            with patch.object(queries, "get_air_targets", side_effect=AssertionError("frame range calculation")), \
                    patch.object(queries, "build_air_geometry", side_effect=AssertionError("frame geometry scan")):
                screen.draw(self.surface)
            for button in screen.action_buttons:
                self.assertTrue(screen.panel_rect.contains(button.rect))

    def test_air_outlines_deduplicate_and_project_zoom_tilt_without_target_markers(self):
        from screens.map_related_screens.orders import MOVE_TARGET_COLOR, BOMBARD_TARGET_COLOR
        with tempfile.TemporaryDirectory() as directory:
            _original, _fighter, _rocket, path = self.make_runtime_save(directory)
            loaded = Map(load_path=path, skip_initial_income=True)
            loaded.selection_mode = False
            loaded.player_country = "A"
            base = loaded.id_to_province[1]
            fighter = base["units"][0]
            duplicate = wing(base, "Biplane", order={"type": "AIR_PATROL"})
            loaded.select_map_units([fighter, duplicate])
            screen = Orders_Screen()
            screen.start_with_province(base, loaded)
            loaded.camera.pos.update(0, 0)
            loaded.camera.zoom = 2
            loaded.camera.tilt_factor = 0.5
            self.assertEqual(len(screen.air_range_previews), 1)
            for kind, color in (("AIR_PATROL", MOVE_TARGET_COLOR), ("AIR_ATTACK", BOMBARD_TARGET_COLOR)):
                with self.subTest(kind=kind):
                    if kind == "AIR_ATTACK":
                        screen.start_bombard_targeting(0, base)
                    radius = queries.air_order_radius(fighter, kind)
                    clip_before = self.surface.get_clip()
                    with patch.object(pygame.draw, "ellipse", wraps=pygame.draw.ellipse) as ellipse, \
                            patch.object(screen, "draw_target_markers", side_effect=AssertionError("air tile markers")), \
                            patch.object(queries, "get_air_targets", side_effect=AssertionError("frame targets")), \
                            patch.object(queries, "air_order_radius", side_effect=AssertionError("frame radius")):
                        screen.draw_range_previews(self.surface)
                    self.assertEqual(ellipse.call_count, 1)
                    rect = ellipse.call_args.args[2]
                    self.assertEqual(ellipse.call_args.args[1], color)
                    self.assertEqual(rect.width, round(2 * radius * loaded.camera.zoom))
                    self.assertEqual(rect.height, round(rect.width * loaded.camera.tilt_factor))
                    self.assertEqual(rect.center, tuple(round(p) for p in queries.world_to_screen(base["center"], loaded)))
                    self.assertEqual(self.surface.get_clip(), clip_before)

    def test_wrapped_air_outlines_clip_to_their_own_map_copy(self):
        game = world()
        base = tile(game, 1, 8)
        game.map_w, game.map_h = game.id_map.get_size()
        game.camera = SimpleNamespace(pos=pygame.Vector2(game.map_w - 40, 0), zoom=1, tilt_factor=1)
        game.top_ui_height = game.total_ui_h = 0
        game.loop_map = True
        screen = Orders_Screen()
        screen.map_screen = game
        clips = []
        def record_clip(_surface, _color, rect, _width):
            clips.append((rect, _surface.get_clip()))
        with patch.object(pygame.draw, "ellipse", side_effect=record_clip):
            screen.draw_air_range(self.surface, base, 100, (0, 255, 0))
        self.assertTrue(clips)
        for rect, clip in clips:
            # The duplicate base near the seam may only paint its own image,
            # never imply coverage on the previous copy's far-side provinces.
            if rect.centerx > 0:
                map_left = round(queries.world_to_screen((0, 0), game, game.map_w)[0])
                self.assertGreaterEqual(clip.left, map_left)

    def test_tournament_player_archive_never_reveals_host_secret_or_hidden_aircraft(self):
        with tempfile.TemporaryDirectory() as directory:
            game, fighter, _rocket, _path = self.make_runtime_save(directory)
            far = tile(game, 3, 1500, owner="B")
            hidden = wing(far, "V2 Rocket", "B")
            game.raw_json_data = {p["json_key"]: dict(p) for p in game.map_data.values()}
            archive = os.path.join(directory, "air.gd5tour")
            with patch.object(c, "TOURNAMENT_SAVES_DIR", directory), \
                    patch.object(multiplayer_io, "run_with_progress", synchronous_progress):
                multiplayer_io.export_tournament(game, archive, "host-key", {"A": "a-key", "B": "b-key"})
                with open(archive) as handle:
                    payload = json.load(handle)
                entry = payload["verification_table"][multiplayer_io.hash_key("a-key")]
                context = multiplayer_io.decrypt_dict(entry["enc_session"], "a-key")["sk"]
                self.assertNotEqual(context, game.multiplayer_session_key)
                self.assertIsNone(multiplayer_io.decrypt_dict(payload["game_data"], context))
                result = multiplayer_io.load_tournament(archive, "a-key")
                self.assertTrue(result[0])
                loaded = Map(load_path=result[3], skip_initial_income=True)
                self.assertEqual(loaded.id_to_province[3]["units"], [])
                self.assertEqual(loaded.id_to_province[1]["units"][0]["unit_id"], fighter["unit_id"])
                self.assertIn(hidden, far["units"])

    def test_ground_combat_rosters_show_cached_truck_stats_without_mutating_aircraft(self):
        from ui import sidebar_info
        from screens.map_related_screens.battle_screen import Battle_Screen
        with tempfile.TemporaryDirectory() as directory:
            _original, _fighter, _rocket, path = self.make_runtime_save(directory)
            loaded = Map(load_path=path, skip_initial_income=True)
            loaded.selection_mode = False
            loaded.player_country = "A"
            base = loaded.id_to_province[1]
            aircraft = base["units"][0]
            wing(base, "WW1 Tank", "B")
            loaded.selected_province = base
            loaded.invalidate_map_presentation_cache()
            battle_screen = Battle_Screen(loaded, base)
            sidebar_row = loaded._unit_roster_cache[1][2][id(aircraft)]
            battle_row = battle_screen.combat_row_data[id(aircraft)]
            self.assertEqual(sidebar_row["attack"], battle_row["attack"])
            self.assertEqual(sidebar_row["profile"]["attack"], c.TRUCK_ATK)
            self.assertEqual(battle_row["profile"]["max_health"], c.TRUCK_MAX_HP)
            with patch.object(combat_rules, "build_battle", side_effect=AssertionError("frame battle")), \
                    patch.object(queries, "ground_combat_profile", side_effect=AssertionError("frame conversion")), \
                    patch.object(combat_rules, "effective_damage_multiplier", side_effect=AssertionError("frame damage")):
                sidebar_info.draw_unit_roster(loaded, self.surface, base, base["units"], True, 0, 0, 370)
                battle_screen.draw(self.surface)
            self.assertTrue(queries.is_air_unit(aircraft))

    def test_air_tutorial_content_fits_above_navigation_controls(self):
        from ui.confirm_dialog.message_box import _NavigationIntroPopup
        popup = _NavigationIntroPopup(SimpleNamespace())
        popup.page_index = len(popup.PAGE_TITLES) - 1
        line_height = popup.body_font.get_height() + popup.ARMY_STEP_LINE_GAP
        content_height = sum(popup.label_font.get_height() + 2 + len(lines) * line_height
                             + popup.ARMY_STEP_GAP for _heading, lines in popup.air_step_lines)
        subtitle_offset = max(0, len(popup._subtitle_lines()) - 1) * (
            popup.body_font.get_height() + popup.SUBTITLE_LINE_GAP)
        self.assertLess(popup.rect.y + 91 + subtitle_offset + content_height, popup.checkbox_rect.top)
        popup.draw(self.surface)

    def test_editor_air_brush_requires_land(self):
        from ui import event_handler
        with tempfile.TemporaryDirectory() as directory:
            _original, _fighter, _rocket, path = self.make_runtime_save(directory)
            loaded = Map(load_path=path, force_editor=True, skip_initial_income=True)
            loaded.secondary_mode = "BLANK"
            loaded.editor_mode = "UNIT"
            loaded.brush_unit = "Piston Bomber"
            base = loaded.id_to_province[1]
            event = pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=(600, 400), button=1)
            for terrain, allowed in (("Plains", True), (c.WATER_TERRAINS[0], False)):
                with self.subTest(terrain=terrain):
                    base["terrain"] = terrain
                    before = len(base["units"])
                    with patch.object(queries, "get_clicked_province", return_value=base):
                        event_handler.handle_map_events(loaded, event)
                    self.assertEqual(len(base["units"]), before + int(allowed))


if __name__ == "__main__":
    unittest.main()
