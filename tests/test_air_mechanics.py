"""Air rules across resolution, UI/AI, persistence and both network boundaries."""
import asyncio
import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
import pygame
from data import queries
import data.constants as c
from data.io import multiplayer_io
from data.io.realtime_multiplayer import (MapRealtimeDriver, RealtimeError, RealtimeServer,
                                         RealtimeSession, RealtimeConfig)
from map_logic.ai import ai_movement
from map_logic import politics
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


def wing(base, name="Monoplane Bomber", owner="A", order=None):
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

    def test_reusable_strike_and_patrol_match_listed_range_and_half_reposition(self):
        for name, stats in queries.get_unit_library().items():
            if not stats.get("air_role") or stats.get("air_consumable"):
                continue
            with self.subTest(unit=name):
                unit = {"type": name}
                strike = queries.air_order_radius(unit, "AIR_ATTACK")
                self.assertEqual(strike, stats["air_range_px"])
                self.assertEqual(strike, queries.air_order_radius(unit, "AIR_REPOSITION") / 2)
                self.assertEqual(queries.air_order_radius(unit, "AIR_PATROL"), strike)

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

    def attack(self, name="Monoplane Bomber"):
        return wing(self.base, name, order={"type": "AIR_ATTACK", "target_id": 2})

    def patrol(self, priority="WEAKEST"):
        return wing(self.defender_base, "Monoplane Fighter", "B",
                    {"type": "AIR_PATROL", "priority": priority})

    def combat_fixture(self, base, name, owner, attack=80, health=1000, defense=0, order=None):
        # Artificial combat stats isolate resolution from content tuning.
        unit = wing(base, name, owner, order)
        unit.update(attack=attack, health=health, max_health=health, defense=defense,
                    morale=c.DEFAULT_UNIT_MORALE)
        return unit

    def test_bomber_patrol_intercepts_and_remains_at_its_base(self):
        attacker = self.combat_fixture(self.base, "Monoplane Bomber", "A",
            order={"type": "AIR_ATTACK", "target_id": self.target["id"]})
        defender = self.combat_fixture(self.defender_base, "Monoplane Bomber", "B",
            order={"type": "AIR_PATROL", "priority": "STRONGEST"})
        before = defender["health"]
        with patch.object(combat_rules, "build_battle", wraps=combat_rules.build_battle) as battles:
            air_processor.process_air_orders(self.game)
        self.assertTrue(any(any(unit is defender for side in call.args[0] for unit in side)
                            for call in battles.call_args_list))
        self.assertLess(defender["health"], before)
        self.assertIn(defender, self.defender_base["units"])
        self.assertEqual(defender["order"]["type"], "AIR_PATROL")
        self.assertIn(attacker, self.base["units"])

    def test_patrol_interception_uses_half_movement_radius_and_tile_edges(self):
        defender = self.combat_fixture(self.defender_base, "Monoplane Fighter", "B",
            order={"type": "AIR_PATROL", "priority": "WEAKEST"})
        radius = queries.air_order_radius(defender, "AIR_PATROL")
        self.assertEqual(radius, queries.air_order_radius(defender, "AIR_REPOSITION") / 2)
        for offset, intercepts in ((0, True), (1, False)):
            with self.subTest(offset=offset):
                self.base["units"] = []
                edge_x = self.defender_base["center"][0] + radius + offset
                with pygame.PixelArray(self.game.id_map) as pixels:
                    pixels.replace(self.target["map_color"], (0, 0, 0))
                # The target's distant center must not remove its permitted
                # edge coverage, or grant coverage to a fully out-of-range tile.
                self.target = tile(self.game, 2, int(edge_x), owner="B", width=1,
                    center=(edge_x + radius, self.defender_base["center"][1]))
                self.base["center"] = (edge_x, self.defender_base["center"][1])
                attacker = self.combat_fixture(self.base, "Monoplane Bomber", "A",
                    order={"type": "AIR_ATTACK", "target_id": self.target["id"]})
                defender["health"] = defender["max_health"]
                before = defender["health"]
                queries.build_air_geometry(self.game)
                with patch.object(combat_rules, "build_battle", wraps=combat_rules.build_battle) as battles:
                    air_processor.process_air_orders(self.game)
                participated = any(any(unit is defender for side in call.args[0] for unit in side)
                                   for call in battles.call_args_list)
                self.assertEqual(participated, intercepts)
                self.assertEqual(defender["health"] < before, intercepts)
                self.assertIn(attacker, self.base["units"])

    def test_strike_is_reciprocal_normal_combat_and_retains_losses_at_base(self):
        aircraft = self.combat_fixture(self.base, "Monoplane Bomber", "A",
            order={"type": "AIR_ATTACK", "target_id": 2})
        defender = self.combat_fixture(self.target, "Infantry Type 1910", "B")
        # Strikes must use normal attack, even if a custom aircraft has a
        # separate bombardment stat. Wounds and political modifiers are shared.
        aircraft["bombard_attack"] = aircraft["attack"] * 10
        aircraft["health"] *= 0.6
        politics.set_value(self.game.nation_data, "B", c.POLITICS_MAX)
        battle = combat_rules.build_battle([[aircraft], [defender]], self.game.nation_data,
            terrain=self.target["terrain"], convert_aircraft=False)
        expected = combat_rules.projected_incoming_damage(battle, self.game.nation_data)
        before = {id(u): u["health"] for u in (aircraft, defender)}
        air_processor.process_air_orders(self.game)
        for unit in (aircraft, defender):
            self.assertAlmostEqual(before[id(unit)] - unit["health"], expected[id(unit)])
            self.assertLess(unit["morale"], c.DEFAULT_UNIT_MORALE)
            self.assertTrue(unit["_in_combat_this_turn"])
        self.assertGreater(expected[id(aircraft)], 0)
        self.assertGreater(expected[id(defender)], 0)
        self.assertTrue(queries.is_air_unit(aircraft))
        self.assertIn(aircraft, self.base["units"])
        self.assertNotIn(aircraft, self.target["units"])
        self.assertEqual(aircraft["order"], {"type": "MOVE", "path": []})
        damaged = (aircraft["health"], defender["health"])
        air_processor.process_air_orders(self.game)
        self.assertEqual((aircraft["health"], defender["health"]), damaged)
        self.assertEqual(self.target["owner"], "B")

    def test_ground_defender_and_aircraft_fire_even_when_both_destroyed(self):
        aircraft = self.combat_fixture(self.base, "Monoplane Bomber", "A", attack=200,
            health=100, order={"type": "AIR_ATTACK", "target_id": 2})
        defender = self.combat_fixture(self.target, "Infantry Type 1910", "B", attack=200, health=100)
        air_processor.process_air_orders(self.game)
        self.assertLessEqual(aircraft["health"], 0)
        self.assertLessEqual(defender["health"], 0)
        self.assertEqual(self.base["units"], [])
        self.assertEqual(self.target["units"], [])
        self.assertEqual(self.target["owner"], "B")

    def test_tanks_cannot_damage_aircraft_during_actual_strikes(self):
        library = queries.get_unit_library()
        tank_name = next(name for name, stats in library.items()
            if queries.classify_unit_group(queries.get_base_unit_name(name), stats) == queries.UNIT_GROUP_TANKS)
        aircraft = self.combat_fixture(self.base, "Monoplane Bomber", "A",
            order={"type": "AIR_ATTACK", "target_id": 2})
        tank = self.combat_fixture(self.target, tank_name, "B", attack=10000)
        air_processor.process_air_orders(self.game)
        self.assertEqual(aircraft["health"], aircraft["max_health"])
        self.assertLess(tank["health"], tank["max_health"])
        self.assertTrue(queries.is_air_unit(aircraft))

    def test_strike_uses_terrain_width_and_only_front_ranks_fight(self):
        terrain = next(name for name, width in c.COMBAT_WIDTH_BY_TERRAIN.items()
                       if width != c.COMBAT_WIDTH)
        self.target["terrain"] = terrain
        width = combat_rules.combat_width_for_terrain(terrain)
        slots = combat_rules.lane_slots(1, width)
        attackers = [self.combat_fixture(self.base, "Monoplane Bomber", "A",
            order={"type": "AIR_ATTACK", "target_id": 2}) for _ in range(slots + 2)]
        defenders = [self.combat_fixture(self.target, "Infantry Type 1910", "B")
                      for _ in range(slots + 2)]
        air_processor.process_air_orders(self.game)
        for units in (attackers, defenders):
            self.assertEqual(sum(u["health"] < u["max_health"] for u in units), slots)
            self.assertEqual(sum(bool(u.get("_in_combat_this_turn")) for u in units), slots)
        self.assertTrue(all(queries.is_air_unit(u) for u in attackers))

    def test_strike_obeys_multiparty_lanes_and_leaves_bystanders_alone(self):
        self.game.nation_data["D"] = {"at_war_with": [], "name": "Neutral"}
        aircraft = self.combat_fixture(self.base, "Monoplane Bomber", "A",
            order={"type": "AIR_ATTACK", "target_id": 2})
        defenders = [self.combat_fixture(self.target, "Infantry Type 1910", owner)
                     for owner in ("B", "C")]
        neutral = self.combat_fixture(self.target, "Infantry Type 1910", "D", attack=10000)
        battle = combat_rules.build_battle([[aircraft], defenders], self.game.nation_data,
            terrain=self.target["terrain"], convert_aircraft=False)
        self.assertEqual(len(battle.lanes), 2)
        expected = combat_rules.projected_incoming_damage(battle, self.game.nation_data)
        air_processor.process_air_orders(self.game)
        for unit in [aircraft] + defenders:
            self.assertAlmostEqual(unit["max_health"] - unit["health"], expected[id(unit)])
        self.assertEqual(neutral["health"], neutral["max_health"])
        self.assertNotIn("_in_combat_this_turn", neutral)

    def test_fort_protects_garrison_only_and_is_damaged_after_exchange(self):
        self.target["buildings"] = ["Fort Lvl 5"]
        level = queries.get_fort_level(self.target)
        aircraft = self.combat_fixture(self.base, "Monoplane Bomber", "A",
            order={"type": "AIR_ATTACK", "target_id": 2})
        # An attacker stationed in its own fort must not get that fort's defense
        # while flying a strike over the enemy target.
        self.base["buildings"] = ["Fort Lvl 5"]
        defender = self.combat_fixture(self.target, "Infantry Type 1910", "B")
        bonus = queries.get_fort_defense_bonus(self.target, defender, self.game.nation_data,
                                               combat_active=True)
        damage = aircraft["attack"] * combat_rules.effective_damage_multiplier(aircraft, self.game.nation_data)
        air_processor.process_air_orders(self.game)
        self.assertAlmostEqual(defender["max_health"] - defender["health"], max(0, damage - bonus))
        self.assertAlmostEqual(aircraft["max_health"] - aircraft["health"], defender["attack"])
        self.assertEqual(queries.get_fort_level(self.target), level - 1)

    def test_empty_fort_still_takes_damage_from_a_completed_strike(self):
        self.target["buildings"] = ["Fort Lvl 5"]
        level = queries.get_fort_level(self.target)
        aircraft = self.attack()
        air_processor.process_air_orders(self.game)
        self.assertEqual(queries.get_fort_level(self.target), level - 1)
        self.assertIn(aircraft, self.base["units"])

    def test_only_capable_aircraft_damage_hostile_forts(self):
        for name, stats in queries.get_unit_library().items():
            if not stats.get("air_role"):
                continue
            with self.subTest(unit=name):
                self.base["units"] = []
                self.target["buildings"] = ["Fort Lvl 5"]
                before = queries.get_fort_level(self.target)
                attacker = self.attack(name)
                expected = before - int(queries.air_unit_can_damage_forts(attacker))
                air_processor.process_air_orders(self.game)
                self.assertEqual(queries.get_fort_level(self.target), expected)

    def test_mixed_wings_count_only_capable_fort_hits(self):
        self.target["buildings"] = ["Fort Lvl 5"]
        before = queries.get_fort_level(self.target)
        attackers = [self.attack(name) for name in ("Biplane Fighter", "Monoplane Bomber", "Jet Fighter")]
        expected_hits = sum(queries.air_unit_can_damage_forts(u) for u in attackers)
        air_processor.process_air_orders(self.game)
        self.assertEqual(queries.get_fort_level(self.target), before - expected_hits)

    def test_fort_damage_capability_is_data_driven_even_for_fighters(self):
        attacker = self.attack("Biplane Fighter")
        self.target["buildings"] = ["Fort Lvl 5"]
        before = queries.get_fort_level(self.target)
        library = dict(queries.get_unit_library())
        library[attacker["type"]] = dict(library[attacker["type"]], air_damages_forts=True)
        with patch.object(queries, "get_unit_library", return_value=library):
            air_processor.process_air_orders(self.game)
        self.assertEqual(queries.get_fort_level(self.target), before - 1)

    def test_capable_aircraft_cannot_damage_nonhostile_fort(self):
        self.target["owner"] = "A"
        self.target["buildings"] = ["Fort Lvl 5"]
        before = queries.get_fort_level(self.target)
        self.attack()
        air_processor.process_air_orders(self.game)
        self.assertEqual(queries.get_fort_level(self.target), before)

    def test_naval_defender_can_fire_back_during_a_strike_at_sea(self):
        sea = tile(self.game, 4, 40, water=True)
        aircraft = self.combat_fixture(self.base, "Monoplane Bomber", "A",
            order={"type": "AIR_ATTACK", "target_id": sea["id"]})
        self.combat_fixture(sea, "Battleship", "B")
        air_processor.process_air_orders(self.game)
        self.assertLess(aircraft["health"], aircraft["max_health"])
        self.assertIn(aircraft, self.base["units"])
        self.assertEqual(sea["owner"], "Ocean")

    def test_one_use_weapons_take_return_fire_and_are_consumed(self):
        for name in ("V1 Flying Bomb", "V2 Rocket"):
            with self.subTest(unit=name):
                self.base["units"] = []
                self.target["units"] = []
                weapon = self.combat_fixture(self.base, name, "A",
                    order={"type": "AIR_ATTACK", "target_id": 2})
                defender = self.combat_fixture(self.target, "Infantry Type 1910", "B")
                air_processor.process_air_orders(self.game)
                # Consumption clears health, but morale still records damage
                # from the defender. V2 immunity applies only to interception.
                self.assertLess(weapon["morale"], c.DEFAULT_UNIT_MORALE)
                self.assertLess(defender["health"], defender["max_health"])
                self.assertNotIn(weapon, self.base["units"])

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
        wing(third_base, "Monoplane Fighter", "C", {"type": "AIR_PATROL"})
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

    def test_fighter_multiplier_only_against_air_and_not_transports(self):
        fighter = wing(self.base, "Monoplane Fighter")
        aircraft = wing(self.target, "Monoplane Bomber", "B")
        ground = wing(self.target, "Infantry Type 1910", "B")
        air_attack = combat_rules.damage_shots([fighter], [aircraft], air_to_air=True)[0][1]
        ground_attack = combat_rules.damage_shots([fighter], [ground])[0][1]
        self.assertAlmostEqual(air_attack, ground_attack * queries.air_unit_stats(fighter)["air_attack_multiplier"])
        queries.load_transport(aircraft, "Convoy")
        self.assertEqual(combat_rules.damage_shots([fighter], [aircraft])[0][1], ground_attack)

    def test_canonical_tanks_category_is_immune_but_infantry_is_not(self):
        plane = self.attack()
        # Isolate category immunity from the aircraft's tunable armor.
        plane["defense"] = 0
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

    def test_ground_combat_destroys_aircraft_before_damage(self):
        aircraft = self.attack("V2 Rocket")
        original = dict(aircraft)
        tank = wing(self.base, "WW1 Tank", "B")
        combat_processor.process_combat(self.game)
        self.assertEqual(aircraft["health"], 0)
        self.assertNotIn(aircraft, self.base["units"])
        self.assertEqual(aircraft["type"], original["type"])
        self.assertNotIn("original_type", aircraft)
        self.assertEqual(tank["health"], tank["max_health"])

    def test_ground_preview_projects_destruction_without_mutating(self):
        aircraft = self.attack()
        tank = wing(self.base, "WW1 Tank", "B")
        before = dict(aircraft)
        battle = combat_rules.build_battle([[aircraft, tank]], self.game.nation_data)
        self.assertEqual(battle.profiles[id(aircraft)]["health"], 0)
        self.assertEqual(battle.profiles[id(aircraft)]["attack"], 0)
        self.assertEqual(battle.lanes, [])
        self.assertEqual(combat_rules.projected_incoming_damage(battle, self.game.nation_data)[id(aircraft)], aircraft["max_health"])
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
        second = wing(other_base, "Monoplane Fighter", "B", {"type": "AIR_PATROL"})
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
        self.target["buildings"] = ["Fort Lvl 5"]
        fort_level = queries.get_fort_level(self.target)
        air_processor.process_air_orders(self.game)
        self.assertEqual(victim["health"], health)
        self.assertEqual(queries.get_fort_level(self.target), fort_level)
        self.assertNotIn(attacker, self.base["units"])

    def test_convoy_roundtrip_retains_fraction_and_original_type(self):
        unit = self.attack("V2 Rocket")
        self.base["is_coastal"] = True
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

    def test_listed_strike_boundary_agrees_in_ai_networks_and_resolution(self):
        radius = queries.air_unit_stats(self.plane)["air_range_px"]
        target = tile(self.game, 3, int(self.base["center"][0] + radius), owner="B")
        enemy = wing(target, "Infantry Type 1910", "B")
        order = {"type": "AIR_ATTACK", "target_id": target["id"]}
        canonical = queries.canonical_air_order(self.game, self.plane, self.base, order)
        self.assertIn(canonical, ai_movement.legal_air_candidates(self.game, self.plane, self.base))
        command = {"type": "unit_order", "province_id": self.base["id"], "unit_index": 0,
                   "unit_id": self.plane["unit_id"], "order": order}
        self.assertEqual(MapRealtimeDriver(self.game).validate_draft("A", [command])[0]["order"], canonical)
        _live, drafts = multiplayer_io._validate_aircraft_orders(self.game, "A",
            {"aircraft_orders": [{"unit_id": self.plane["unit_id"], "order": order}]}, {})
        self.assertEqual(drafts[0][1], canonical)
        self.plane["order"] = canonical
        health = enemy["health"]
        air_processor.process_air_orders(self.game)
        self.assertLess(enemy["health"], health)
        self.assertIn(self.plane, self.base["units"])
        self.assertNotIn(self.plane, target["units"])

    def test_legacy_patrol_defaults_and_save_transport_roundtrip(self):
        fighter = wing(self.base, "Biplane Fighter", order={"type": "AIR_PATROL"})
        queries.normalize_air_orders(self.game.map_data)
        self.assertEqual(fighter["order"]["priority"], queries.AIR_DEFAULT_PRIORITY)
        queries.load_transport(self.plane, "Convoy")
        saved = json.loads(json.dumps(queries.build_save_dict(self.game)))
        recovered = saved["provinces"][self.base["json_key"]]["units"]
        queries.revert_transport(recovered[0])
        self.assertEqual(recovered[0]["type"], "Monoplane Bomber")
        self.assertTrue(queries.air_unit_can_damage_forts(recovered[0]))
        self.assertNotIn("air_damages_forts", recovered[0])
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
        fighter = wing(self.base, "Biplane Fighter")
        screen.set_air_mission(fighter, self.base, "WEAKEST")
        self.assertEqual(fighter["order"]["priority"], queries.AIR_DEFAULT_PRIORITY)
        screen.set_air_mission(fighter, self.base, "STRONGEST")
        self.assertEqual(fighter["order"]["priority"], "STRONGEST")
        self.game.tactical_mode = True
        self.game.player_unit = self.plane
        before = dict(fighter["order"])
        screen.set_air_mission(fighter, self.base, "NONE")
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
                      {"type": ["AIR_ATTACK"]}, {"type": "AIR_PATROL", "priority": "INVALID"}):
            with self.subTest(order=order), self.assertRaises(RealtimeError):
                driver.validate_draft("A", [dict(command, order=order)])
        with self.assertRaises(RealtimeError):
            driver.validate_draft("A", [command, command])

    def test_realtime_strike_return_fire_occurs_only_at_server_resolution(self):
        from map_logic.turn_processing import turn_processor
        self.target["buildings"] = ["Fort Lvl 5"]
        fort_level = queries.get_fort_level(self.target)
        defender = wing(self.target, "Infantry Type 1910", "B")
        self.plane["defense"] = 0
        before = self.plane["health"]
        driver = MapRealtimeDriver(self.game)
        command = {"type": "unit_order", "province_id": 1, "unit_index": 0,
                   "order": {"type": "AIR_ATTACK", "target_id": 2}}
        draft = driver.validate_draft("A", [command])
        self.assertEqual(self.plane["health"], before)
        self.assertEqual(self.plane["order"]["type"], "MOVE")
        self.assertEqual(queries.get_fort_level(self.target), fort_level)
        async def resolve_air(game):
            air_processor.process_air_orders(game)
        # Exercise command application and the server's turn hook, isolating
        # the air phase from unrelated economy and diplomacy requirements.
        with patch.object(turn_processor, "prepare_turn", new_callable=AsyncMock), \
                patch.object(turn_processor, "resolve_turn_logic", side_effect=resolve_air):
            driver.process_turn({"A": draft})
        self.assertLess(self.plane["health"], before)
        self.assertIn(self.plane, self.base["units"])
        self.assertLess(defender["health"], defender["max_health"])
        self.assertEqual(queries.get_fort_level(self.target), fort_level - 1)

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
        enemy = wing(self.target, "Monoplane Fighter", "B", {"type": "AIR_PATROL"})
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
        foreign = wing(self.base, "Monoplane Bomber", "B")
        self.game.nation_data["A"]["at_war_with"] = ["C"]
        self.game.nation_data["B"]["at_war_with"] = ["C"]
        self.base["units"] = [foreign, self.plane]
        command = {"type": "unit_order", "province_id": 1, "unit_index": 0,
            "unit_id": self.plane["unit_id"], "order": {"type": "AIR_ATTACK", "target_id": 2}}
        canonical = MapRealtimeDriver(self.game).validate_draft("A", [command])[0]
        self.assertEqual(canonical["unit_index"], 1)

    def test_tournament_command_roundtrip_retains_host_stats_and_position(self):
        self.target["buildings"] = ["Fort Lvl 5"]
        fort_level = queries.get_fort_level(self.target)
        defender = wing(self.target, "Infantry Type 1910", "B")
        self.plane["defense"] = 0
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
            self.assertEqual(queries.get_fort_level(self.target), fort_level)
            air_processor.process_air_orders(self.game)
            self.assertLess(self.plane["health"], health)
            self.assertLess(defender["health"], defender["max_health"])
            self.assertIn(self.plane, self.base["units"])
            self.assertEqual(queries.get_fort_level(self.target), fort_level - 1)

    def test_tournament_rejects_foreign_duplicate_malformed_and_out_of_range_orders(self):
        enemy = wing(self.target, "Biplane Fighter", "B")
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
        attacker = wing(self.base, "Monoplane Fighter", order={"type": "AIR_ATTACK", "target_id": 2})
        based_enemy = wing(self.target, "Monoplane Bomber", "B")
        # Isolate the air bonus from the target's tunable armor.
        based_enemy["defense"] = 0
        before = based_enemy["health"]
        expected = attacker["attack"] * combat_rules.effective_damage_multiplier(attacker, self.game.nation_data)
        air_processor.process_air_orders(self.game)
        self.assertAlmostEqual(before - based_enemy["health"], expected)
        self.assertTrue(queries.is_air_unit(based_enemy))

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


class AirGroundTransportTests(unittest.TestCase):
    def setUp(self):
        self.game = world()
        self.base = tile(self.game, 1, 8)
        self.base["is_coastal"] = True
        self.land = tile(self.game, 2, 30)
        self.sea = tile(self.game, 3, 50, water=True)
        self.base["neighbors"] = [2, 3]
        self.land["neighbors"] = [1]
        self.sea["neighbors"] = [1]

    def test_air_conversion_and_both_network_validators_accept_only_convoys(self):
        for name, stats in queries.get_unit_library().items():
            if not stats.get("air_role"):
                continue
            with self.subTest(unit=name):
                self.base["units"] = []
                unit = wing(self.base, name)
                order = queries.air_conversion_order(unit)
                self.assertEqual(order["to"], "Convoy")
                driver = MapRealtimeDriver(self.game)
                command = {"type": "unit_order", "province_id": 1, "unit_index": 0,
                           "unit_id": unit["unit_id"], "order": order}
                self.assertEqual(driver.validate_draft("A", [command])[0]["order"], order)
                live, drafts = multiplayer_io._validate_aircraft_orders(self.game, "A",
                    {"aircraft_orders": [{"unit_id": unit["unit_id"], "order": order}]}, {})
                self.assertIn(unit["unit_id"], live)
                self.assertEqual(drafts[0][1], order)
                bad = dict(order, to="Truck")
                with self.assertRaises(RealtimeError):
                    driver.validate_draft("A", [dict(command, order=bad)])
                with self.assertRaises(ValueError):
                    multiplayer_io._validate_aircraft_orders(self.game, "A",
                        {"aircraft_orders": [{"unit_id": unit["unit_id"], "order": bad}]}, {})
                with self.assertRaises(ValueError):
                    queries.load_transport(unit, "Truck")
                self.assertFalse(queries.is_air_transport(unit))

    def test_conversion_coast_and_unloading_land_requirements(self):
        unit = wing(self.land)
        with self.assertRaises(ValueError):
            queries.canonical_unit_order(self.game, "A", self.land, unit, queries.air_conversion_order(unit))
        unit["order"] = queries.air_conversion_order(unit)
        movement_processor.process_conversions(self.game)
        self.assertTrue(queries.is_air_unit(unit))
        queries.load_transport(unit, "Convoy")
        with self.assertRaises(ValueError):
            queries.canonical_unit_order(self.game, "A", self.sea, unit, queries.air_conversion_order(unit))

    def test_ui_and_editor_conversion_use_convoys(self):
        from screens.editor_screens.brush_screens import Convoy_Converter_Screen
        unit = wing(self.base)
        self.game.show_feedback = Mock()
        self.game.queue_editor_visual_refresh = Mock()
        screen = object.__new__(Orders_Screen)
        screen.map_screen = self.game
        screen.target_province = self.base
        screen.read_only = False
        screen.refresh_ui = Mock()
        screen._mark_draft_changed = Mock()
        screen.convert_unit(0, self.base)
        self.assertEqual(unit["order"], queries.air_conversion_order(unit))
        self.base["is_coastal"] = False
        unit["order"] = {}
        screen.convert_unit(0, self.base)
        self.assertEqual(unit["order"], {})
        editor = object.__new__(Convoy_Converter_Screen)
        editor.map_screen = self.game
        editor.province = self.base
        editor.unit_lib = queries.get_unit_library()
        editor.selected = {0}
        editor.save()
        self.assertTrue(queries.is_air_transport(unit))
        self.assertEqual(unit["type"], "Convoy (Monoplane Bomber)")
        editor.selected = set()
        editor.save()
        self.assertTrue(queries.is_air_unit(unit))

    def test_missile_routes_agree_with_ui_ai_networks_and_ground_speed(self):
        for name in ("V1 Flying Bomb", "V2 Rocket"):
            with self.subTest(unit=name):
                self.base["units"] = []
                self.land["units"] = []
                unit = wing(self.base, name)
                speed = queries.get_unit_library()[name]["speed"]
                route = [2]
                previous = self.land
                for offset in range(speed):
                    next_tile = tile(self.game, 4 + offset, 80 + offset * 8)
                    previous["neighbors"].append(next_tile["id"])
                    next_tile["neighbors"] = [previous["id"]]
                    route.append(next_tile["id"])
                    previous = next_tile
                self.game.selected_unit_records = lambda: [(unit, self.base)]
                self.game.can_select_map_units = lambda: True
                self.game.invalidate_map_presentation_cache = Mock()
                self.game.show_feedback = Mock()
                self.game.select_map_units = Mock()
                Map.issue_selected_move_orders(self.game, previous)
                self.assertEqual(unit["order"], {"type": "MOVE", "path": route})
                command = {"type": "unit_order", "province_id": 1, "unit_index": 0,
                           "unit_id": unit["unit_id"], "order": unit["order"]}
                self.assertEqual(MapRealtimeDriver(self.game).validate_draft("A", [command])[0]["order"], unit["order"])
                _, drafts = multiplayer_io._validate_aircraft_orders(self.game, "A",
                    {"aircraft_orders": [{"unit_id": unit["unit_id"], "order": unit["order"]}]}, {})
                self.assertEqual(drafts[0][1], unit["order"])
                self.assertFalse(queries.can_unit_move_step(unit, self.base, self.sea, self.game.nation_data))
                with self.assertRaises(ValueError):
                    queries.canonical_air_order(self.game, unit, self.base,
                        {"type": "AIR_REPOSITION", "target_id": 2})
                movement_processor.process_movement(self.game)
                self.assertIn(unit, self.game.id_to_province[route[speed - 1]]["units"])
                self.assertEqual(unit["order"]["path"], route[speed:])

    def test_heuristic_missiles_relocate_without_converting(self):
        for name in ("V1 Flying Bomb", "V2 Rocket"):
            with self.subTest(unit=name):
                self.base["units"] = []
                unit = wing(self.base, name)
                radius = queries.air_order_radius(unit, "AIR_ATTACK")
                self.game.id_map.fill((0, 0, 0), pygame.Rect(80, 0, 2300, 32))
                target = tile(self.game, 4, int(self.base["center"][0] + radius + 8), owner="B")
                queries.build_air_geometry(self.game)
                with patch.object(c, "USE_FOG_OF_WAR", False):
                    ai_movement._assign_air_orders(self.game, "A", [(unit, self.base)])
                self.assertEqual(unit["order"], {"type": "MOVE", "path": [2]})

    def test_ground_combat_spares_neutrals_and_air_convoys_at_sea(self):
        self.game.nation_data["C"]["at_war_with"] = []
        for nation in ("A", "B"):
            self.game.nation_data[nation]["at_war_with"].remove("C")
        aircraft = wing(self.base)
        neutral = wing(self.base, owner="C")
        tank = wing(self.base, "WW1 Tank", "B")
        carried = wing(self.sea)
        queries.load_transport(carried, "Convoy")
        wing(self.sea, "Submarine I", "B")
        combat_processor.process_combat(self.game)
        self.assertNotIn(aircraft, self.base["units"])
        self.assertIn(neutral, self.base["units"])
        self.assertEqual(neutral["health"], neutral["max_health"])
        self.assertEqual(tank["health"], tank["max_health"])
        self.assertTrue(queries.is_air_transport(carried))
        self.assertEqual(carried["type"], "Convoy (Monoplane Bomber)")

    def test_heuristic_missile_uses_a_convoy_for_an_island_crossing(self):
        unit = wing(self.base, "V2 Rocket")
        self.base["neighbors"] = [3]
        self.sea["neighbors"] = [1, 2]
        self.land["neighbors"] = [3]
        radius = queries.air_order_radius(unit, "AIR_ATTACK")
        tile(self.game, 4, int(self.base["center"][0] + radius + 8), owner="B")
        queries.build_air_geometry(self.game)
        with patch.object(c, "USE_FOG_OF_WAR", False):
            ai_movement._assign_air_orders(self.game, "A", [(unit, self.base)])
        self.assertEqual(unit["order"], queries.air_conversion_order(unit))
        movement_processor.process_conversions(self.game)
        self.assertTrue(queries.is_air_transport(unit))
        with patch.object(c, "USE_FOG_OF_WAR", False):
            ai_movement._assign_air_orders(self.game, "A", [(unit, self.base)])
        self.assertEqual(unit["order"], {"type": "MOVE", "path": [3, 2]})

    def test_old_air_truck_saved_at_sea_becomes_a_convoy(self):
        unit = wing(self.sea)
        queries.load_transport(unit, "Convoy")
        unit.update(type="Truck (Monoplane Bomber)", max_health=c.TRUCK_MAX_HP,
                    health=c.TRUCK_MAX_HP * 0.4, naval_unit=False)
        queries.migrate_aircraft_stats(self.game.map_data)
        self.assertEqual(unit["type"], "Convoy (Monoplane Bomber)")
        self.assertTrue(unit["naval_unit"])
        self.assertAlmostEqual(unit["health"] / unit["max_health"], 0.4)
        self.assertEqual(unit["original_attack"], queries.get_unit_library()["Monoplane Bomber"]["attack"])

    def test_missile_crossing_a_ground_enemy_dies_without_dealing_damage(self):
        from map_logic.rendering import overlay_renderer
        self.land["owner"] = "B"
        missile = wing(self.base, "V2 Rocket", order={"type": "MOVE", "path": [2]})
        enemy = wing(self.land, "Infantry Type 1910", "B", {"type": "MOVE", "path": [1]})
        before = dict(missile)
        estimate = overlay_renderer.estimated_combat_outcome([[missile], [enemy]], self.game.nation_data)
        self.assertEqual(estimate["winner_side"], 1)
        self.assertEqual(missile, before)
        combat_processor.process_meeting_engagements(self.game)
        self.assertNotIn(missile, self.base["units"])
        self.assertEqual(enemy["health"], enemy["max_health"])
        self.assertFalse(enemy.get("_combat_locked", False))

    def test_air_convoy_crossing_a_shore_enemy_keeps_its_sea_profile(self):
        from map_logic.rendering import overlay_renderer
        convoy = wing(self.sea)
        queries.load_transport(convoy, "Convoy")
        enemy = wing(self.base, "Infantry Type 1910", "B")
        battle = combat_rules.build_battle([[convoy], [enemy]], self.game.nation_data,
                                           grounded_sides={1})
        self.assertNotIn(id(convoy), battle.profiles)
        expected = combat_rules.projected_incoming_damage(battle, self.game.nation_data)
        before = convoy["health"]
        with patch.object(queries, "prepare_aircraft_for_ground_combat",
                          wraps=queries.prepare_aircraft_for_ground_combat) as prepare:
            overlay_renderer.estimated_combat_outcome([[convoy], [enemy]], self.game.nation_data,
                                                       grounded_sides={1})
        self.assertFalse(prepare.call_args_list[0].kwargs["on_land"])
        combat_processor.resolve_meeting_engagement(self.sea, self.base, [convoy], [enemy], self.game.nation_data)
        self.assertEqual(convoy["health"], before - expected.get(id(convoy), 0))
        self.assertTrue(queries.is_air_transport(convoy))

    def test_aircraft_landing_never_captures_and_dies_to_surface_defenders(self):
        self.land["owner"] = "B"
        for defenders in (False, True):
            with self.subTest(defenders=defenders):
                self.base["units"] = []
                self.land["units"] = []
                self.sea["units"] = []
                unit = wing(self.sea)
                queries.load_transport(unit, "Convoy")
                self.sea["neighbors"] = [2]
                unit["order"] = {"type": "MOVE", "path": [2]}
                if defenders:
                    wing(self.land, "Infantry Type 1910", "B")
                movement_processor.process_movement(self.game)
                combat_processor.process_combat(self.game)
                combat_processor.check_for_post_combat_captures(self.game)
                self.assertEqual(self.land["owner"], "B")
                self.assertEqual(unit in self.land["units"], not defenders)
                self.assertTrue(queries.is_air_unit(unit))

    def test_legacy_trucks_and_pending_orders_migrate_idempotently(self):
        carried = wing(self.base)
        queries.load_transport(carried, "Convoy")
        # Deliberate old-save fixture: current gameplay cannot create this Truck.
        carried.update(type="Truck (Monoplane Bomber)", max_health=c.TRUCK_MAX_HP,
                       health=c.TRUCK_MAX_HP * 0.4, naval_unit=False,
                       order={"type": "MOVE", "path": [2]})
        pending = wing(self.base, "V1 Flying Bomb")
        pending["order"] = {"type": "CONVERT", "to": "Truck", "turns_left": 1}
        missile = wing(self.land, "V2 Rocket")
        missile["order"] = {"type": "MOVE", "path": [1]}
        queries.migrate_aircraft_stats(self.game.map_data)
        queries.normalize_air_orders(self.game.map_data)
        self.assertTrue(queries.is_air_unit(carried))
        self.assertNotIn("original_type", carried)
        self.assertAlmostEqual(carried["health"] / carried["max_health"], 0.4)
        self.assertEqual(carried["order"]["path"], [])
        self.assertEqual(pending["order"], queries.air_conversion_order(pending))
        self.assertEqual(missile["order"]["path"], [1])
        saved = json.loads(json.dumps(queries.build_save_dict(self.game)))
        queries.migrate_aircraft_stats(self.game.map_data)
        queries.normalize_air_orders(self.game.map_data)
        self.assertEqual(json.loads(json.dumps(queries.build_save_dict(self.game)))["provinces"], saved["provinces"])


class AirMissionSelectionTests(unittest.TestCase):
    def setUp(self):
        self.game = world()
        self.base = tile(self.game, 1, 8)
        self.target = tile(self.game, 2, 30, owner="B")
        self.unit = wing(self.base, "Monoplane Fighter")
        self.game.show_feedback = Mock()
        self.screen = Orders_Screen()
        self.screen.map_screen = self.game
        self.screen.target_province = self.base
        self.screen.refresh_ui = Mock()
        self.screen._mark_draft_changed = Mock()

    def buttons(self):
        with patch.object(self.screen, "_add_action_button", side_effect=lambda *a, **k: Mock()) as add:
            self.screen._build_unit_action_buttons(0, 0, self.unit, self.base, 0, None,
                False, False, False, True, self.game.nation_data["A"]["research"])
        return {call.args[2]: call for call in add.call_args_list}

    def test_icon_tracks_each_mission_and_upgrade_stays_separate(self):
        from screens.map_related_screens.orders import ACTION_COL_BOMBARD, ACTION_COL_UPGRADE
        for mission, icon in (("NONE", "No Mission"), ("WEAKEST", "Weakest First"),
                              ("STRONGEST", "Strongest First")):
            with self.subTest(mission=mission):
                self.screen.set_air_mission(self.unit, self.base, mission)
                buttons = self.buttons()
                self.assertEqual(buttons[ACTION_COL_BOMBARD].args[6], icon)
                self.assertEqual(buttons[ACTION_COL_UPGRADE].args[6], "Upgrading")
                self.assertFalse(buttons[ACTION_COL_UPGRADE].kwargs["enabled"])
        self.unit["order"] = {"type": "AIR_ATTACK", "base_id": 1, "target_id": 2}
        self.assertEqual(self.buttons()[ACTION_COL_BOMBARD].args[6], "Strike Selected")

    def test_move_icon_tracks_relocation_and_ground_movement(self):
        from pathlib import Path
        from screens.map_related_screens.orders import ACTION_COL_BOMBARD
        asset = Path(__file__).resolve().parents[1] / "assets" / "images" / "Air Move.png"
        self.assertEqual(asset.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
        for name, order in (("Monoplane Fighter", {"type": "AIR_REPOSITION", "target_id": 2}),
                            ("V1 Flying Bomb", {"type": "MOVE", "path": [2]}),
                            ("V2 Rocket", {"type": "MOVE", "path": [2]})):
            with self.subTest(unit=name):
                self.unit["type"] = name
                self.unit["order"] = order
                self.assertEqual(self.buttons()[ACTION_COL_BOMBARD].args[6], "Air Move")
                self.screen.set_air_mission(self.unit, self.base, "STRIKE", row_key=0)
                self.assertEqual(self.buttons()[ACTION_COL_BOMBARD].args[6], "Strike Selected")
                self.screen.set_air_mission(self.unit, self.base, "NONE")
                self.assertEqual(self.buttons()[ACTION_COL_BOMBARD].args[6], "No Mission")

    def test_selector_shows_all_missions_and_disables_unsupported_defense(self):
        for name in ("Monoplane Fighter", "Monoplane Bomber", "V1 Flying Bomb", "V2 Rocket"):
            with self.subTest(unit=name):
                self.unit["type"] = name
                before = dict(self.unit["order"])
                with patch("screens.map_related_screens.orders._AirMissionSelectScreen") as popup, \
                        patch("ui.screen_runner._run_pygame_sub_screen"):
                    self.screen.open_air_mission_select(0, self.base)
                choices = [choice[0] for choice in popup.call_args.args[1]]
                self.assertEqual(choices, ["NONE", *queries.AIR_INTERCEPTION_PRIORITIES, "STRIKE"])
                expected = {"NONE", "STRIKE"}
                if queries.air_unit_can_patrol(self.unit):
                    expected.update(queries.AIR_INTERCEPTION_PRIORITIES)
                self.assertEqual(popup.call_args.kwargs["enabled_missions"], expected)
                self.assertEqual(self.unit["order"], before)
                if "WEAKEST" not in choices:
                    self.screen.set_air_mission(self.unit, self.base, "WEAKEST")
                    self.assertEqual(self.unit["order"], before)

    def test_strike_selection_targets_then_second_button_click_cancels(self):
        from screens.map_related_screens.orders import ACTION_COL_BOMBARD
        self.screen.set_air_mission(self.unit, self.base, "WEAKEST")
        self.screen.set_air_mission(self.unit, self.base, "STRIKE", row_key=0)
        self.assertEqual(self.screen.bombarding_unit_index, 0)
        self.assertEqual(self.unit["order"], {"type": "MOVE", "path": []})
        self.assertEqual(self.buttons()[ACTION_COL_BOMBARD].args[6], "Strike Selected")
        self.screen.set_bombard_target(0, self.target, self.base)
        self.assertEqual(self.unit["order"], queries.canonical_air_order(self.game, self.unit, self.base,
            {"type": "AIR_ATTACK", "target_id": 2}))
        with patch("screens.map_related_screens.orders._AirMissionSelectScreen") as popup:
            self.screen.open_air_mission_select(0, self.base)
            popup.assert_not_called()
        self.assertEqual(self.unit["order"], {"type": "MOVE", "path": []})
        self.assertIsNone(self.screen.bombarding_unit_index)
        self.assertEqual(self.buttons()[ACTION_COL_BOMBARD].args[6], "No Mission")

    def test_no_mission_clears_patrol_and_pending_strike_targeting(self):
        self.screen.set_air_mission(self.unit, self.base, "STRONGEST")
        self.screen.set_air_mission(self.unit, self.base, "NONE")
        self.assertEqual(self.unit["order"], {"type": "MOVE", "path": []})
        self.screen.set_air_mission(self.unit, self.base, "STRIKE")
        self.screen.set_air_mission(self.unit, self.base, "NONE")
        self.assertIsNone(self.screen.bombarding_unit_index)

    def test_selection_rechecks_stale_identity_permissions_and_combat(self):
        for condition in ("foreign", "tactical", "read_only", "removed", "replaced_province", "combat", "water"):
            self.setUp()
            before = dict(self.unit["order"])
            if condition == "foreign":
                self.unit["owner"] = "B"
            elif condition == "tactical":
                self.game.tactical_mode = True
                self.game.player_unit = wing(self.base)
            elif condition == "read_only":
                self.screen.read_only = True
            elif condition == "removed":
                self.base["units"] = []
            elif condition == "replaced_province":
                self.game.id_to_province[1] = dict(self.base)
            elif condition == "combat":
                wing(self.base, "Infantry Type 1910", "B")
            elif condition == "water":
                self.base["terrain"] = c.WATER_TERRAINS[0]
            for mission in ("WEAKEST", "STRIKE"):
                with self.subTest(condition=condition, mission=mission):
                    self.screen.set_air_mission(self.unit, self.base, mission)
                    self.assertEqual(self.unit["order"], before)

    def test_mission_orders_use_existing_multiplayer_commands(self):
        for mission in ("NONE", "WEAKEST", "STRONGEST", "STRIKE"):
            with self.subTest(mission=mission):
                self.screen.set_air_mission(self.unit, self.base, mission)
                if mission == "STRIKE":
                    self.screen.set_bombard_target(0, self.target, self.base)
                order = dict(self.unit["order"])
                command = {"type": "unit_order", "province_id": 1, "unit_index": 0,
                           "unit_id": self.unit["unit_id"], "order": order}
                self.assertEqual(MapRealtimeDriver(self.game).validate_draft("A", [command])[0]["order"], order)
                _, drafts = multiplayer_io._validate_aircraft_orders(self.game, "A",
                    {"aircraft_orders": [{"unit_id": self.unit["unit_id"], "order": order}]}, {})
                self.assertEqual(drafts[0][1], order)

    def test_named_aircraft_cannot_upgrade_through_ui_networks_or_execution(self):
        self.base["buildings"] = ["Arms Factory Lvl 1"]
        self.game.nation_data["A"]["research"] = {key: stats.get("max_lvl", 1)
                                                   for key, stats in queries.get_tech_tree().items()}
        for name, stats in queries.get_unit_library().items():
            if stats.get("air_role") and queries.get_unit_tier(name) == 0:
                self.assertIsNone(queries.get_upgrade_target(name, self.game.nation_data["A"]["research"],
                                                            queries.get_unit_library(), queries.get_tech_tree()))
        self.screen.upgrade_unit(0, "Jet Fighter", self.base)
        self.assertNotEqual(self.unit["order"].get("type"), "UPGRADE")
        order = {"type": "UPGRADE", "target_type": "Jet Fighter"}
        command = {"type": "unit_order", "province_id": 1, "unit_index": 0, "order": order}
        with self.assertRaises(RealtimeError):
            MapRealtimeDriver(self.game).validate_draft("A", [command])
        with self.assertRaises(ValueError):
            multiplayer_io._validate_aircraft_orders(self.game, "A",
                {"aircraft_orders": [{"unit_id": self.unit["unit_id"], "order": order}]}, {})
        self.unit["order"] = dict(order, turns_left=1)
        movement_processor.process_upgrades(self.game)
        self.assertEqual(self.unit["type"], "Monoplane Fighter")

    def test_numbered_aircraft_use_existing_upgrade_button_and_rule(self):
        from screens.map_related_screens.orders import ACTION_COL_UPGRADE
        # Artificial numbered family: real named aircraft do not get new tiers.
        stats = dict(queries.get_unit_library()[self.unit["type"]])
        library = {"Test Plane I": stats, "Test Plane II": dict(stats)}
        tree = {"test_plane": {"max_lvl": 2, "req": {}, "years": [1900, 1901]}}
        self.unit["type"] = "Test Plane I"
        self.screen.unit_library = library
        self.game.nation_data["A"]["research"] = {"test_plane": 2}
        self.base["buildings"] = ["Arms Factory Lvl 1"]
        with patch.object(queries, "get_unit_library", return_value=library), \
                patch.object(queries, "get_tech_tree", return_value=tree):
            target = queries.get_upgrade_target(self.unit["type"], {"test_plane": 2}, library, tree)
            button = self.buttons()[ACTION_COL_UPGRADE]
            self.assertTrue(button.kwargs["enabled"])
            button.args[5]()
            self.assertEqual(self.unit["order"]["target_type"], target)
            movement_processor.process_upgrades(self.game)
            self.assertEqual(self.unit["type"], target)


class GroupAirMissionSelectionTests(unittest.TestCase):
    def setUp(self):
        self.game = world()
        self.base = tile(self.game, 1, 8)
        self.target = tile(self.game, 2, 30, owner="B")
        self.remote = tile(self.game, 3, 900)
        self.fighter = wing(self.base, "Monoplane Fighter")
        self.bomber = wing(self.remote, "Monoplane Bomber")
        self.v1 = wing(self.base, "V1 Flying Bomb")
        self.v2 = wing(self.remote, "V2 Rocket")
        self.ground = wing(self.base, "Infantry Type 1910")
        self.carried = wing(self.base, "Monoplane Bomber")
        queries.load_transport(self.carried, "Convoy")
        self.foreign = wing(self.target, "Monoplane Bomber", "B")
        self.records = [(self.fighter, self.base), (self.bomber, self.remote),
                        (self.v1, self.base), (self.v2, self.remote),
                        (self.ground, self.base), (self.carried, self.base),
                        (self.foreign, self.target)]
        self.game.selected_unit_records = lambda: list(self.records)
        self.game.show_feedback = Mock()
        self.screen = Orders_Screen()
        self.screen.map_screen = self.game
        self.screen.target_province = self.base
        self.screen.refresh_ui = Mock()
        self.screen._mark_draft_changed = Mock()

    def test_patrol_capability_and_ai_candidates_cover_every_reusable_aircraft(self):
        for name, stats in queries.get_unit_library().items():
            if not stats.get("air_role"):
                continue
            with self.subTest(unit=name):
                unit = {"type": name, "owner": "A"}
                expected = not stats.get("air_consumable", False)
                self.assertEqual(queries.air_unit_can_patrol(unit), expected)
                candidates = ai_movement.legal_air_candidates(self.game, unit, self.base)
                self.assertEqual(any(order["type"] == "AIR_PATROL" for order in candidates), expected)
                self.assertEqual(bool(queries.get_air_targets(self.game, unit, self.base, "AIR_PATROL")), expected)
        self.assertFalse(queries.air_unit_can_patrol(self.carried))
        self.assertFalse(queries.air_unit_can_patrol(self.ground))

    def test_heuristic_bomber_defends_when_no_visible_enemy_target_exists(self):
        with patch.object(c, "USE_FOG_OF_WAR", True), \
                patch.object(queries, "get_visible_provinces", return_value=({1, 3}, set())):
            ai_movement._assign_air_orders(self.game, "A", [(self.bomber, self.remote)])
        self.assertEqual(self.bomber["order"], queries.canonical_air_order(self.game, self.bomber, self.remote,
            {"type": "AIR_PATROL", "priority": queries.AIR_DEFAULT_PRIORITY}))

    def test_group_selector_counts_aircraft_and_always_offers_every_choice(self):
        from screens.map_related_screens.orders import AIR_MISSION_CHOICES
        self.assertEqual(len(self.screen._batch_command_candidates("MISSION")), 4)
        # Even a selection containing only missiles retains the defense choices.
        self.records = [(self.v1, self.base), (self.v2, self.remote)]
        with patch("screens.map_related_screens.orders._AirMissionSelectScreen") as popup, \
                patch("ui.screen_runner._run_pygame_sub_screen"):
            self.screen.open_selected_air_mission_select()
        self.assertEqual(popup.call_args.args[1], AIR_MISSION_CHOICES)
        self.records = [(self.bomber, self.remote)]
        popup.call_args.args[2]("STRONGEST")
        self.assertNotEqual(self.bomber["order"]["type"], "AIR_PATROL")

    def test_group_patrol_skips_weapons_transports_and_foreign_units_without_refunds(self):
        refund = {"cost_materials": 37, "cost_manpower": 0, "cost_fuel": 0}
        for unit in (self.fighter, self.bomber, self.v1):
            unit["order"] = {"type": "REPAIR", "refund": refund}
        before = {id(unit): unit["order"] for unit, _base in self.records}
        resources = self.game.nation_data["A"]["materials"]
        self.screen.set_selected_air_mission("STRONGEST")
        for unit, base in self.records:
            if unit is self.fighter or unit is self.bomber:
                self.assertEqual(unit["order"], queries.canonical_air_order(self.game, unit, base,
                    {"type": "AIR_PATROL", "priority": "STRONGEST"}))
            else:
                self.assertIs(unit["order"], before[id(unit)])
        self.assertEqual(self.game.nation_data["A"]["materials"], resources + 2 * refund["cost_materials"])
        self.screen._mark_draft_changed.assert_called_once()

    def test_group_strike_checks_each_range_and_base_preserving_skipped_orders(self):
        # Deliberately artificial ranges test comparison without assuming any
        # lasting range relationship between real aircraft designs.
        stats = dict(queries.get_unit_library()["Monoplane Bomber"])
        library = dict(queries.get_unit_library(), **{
            "Test Short Wing": dict(stats, air_range_px=10),
            "Test Long Wing": dict(stats, air_range_px=60)})
        self.fighter["type"] = "Test Short Wing"
        self.bomber["type"] = self.v1["type"] = "Test Long Wing"
        records = self.records[:3]
        old_orders = [unit["order"] for unit, _base in records]
        with patch.object(queries, "get_unit_library", return_value=library):
            self.screen.set_selected_air_mission("STRIKE", records)
            self.assertEqual([unit["order"] for unit, _base in records], old_orders)
            self.screen._mark_draft_changed.assert_not_called()
            self.screen.set_bombard_target(None, self.target)
            expected = queries.canonical_air_order(self.game, self.v1, self.base,
                {"type": "AIR_ATTACK", "target_id": self.target["id"]})
        self.assertEqual(self.v1["order"], expected)
        self.assertIs(self.fighter["order"], old_orders[0])
        self.assertIs(self.bomber["order"], old_orders[1])
        self.assertIsNone(self.screen.bombarding_unit_index)
        self.assertFalse(self.screen.air_mission_targeting_units)
        self.screen._mark_draft_changed.assert_called_once()

    def test_group_no_mission_clears_aircraft_only_and_canceling_targeting_preserves_orders(self):
        for unit, _base in self.records:
            unit["order"] = {"type": "DISBAND", "turns_left": 1}
        before = [unit["order"] for unit, _base in self.records]
        self.screen.set_selected_air_mission("STRIKE")
        self.screen.handle_back_key()
        self.assertEqual([unit["order"] for unit, _base in self.records], before)
        self.assertFalse(self.screen.air_mission_targeting_units)
        self.screen.set_selected_air_mission("NONE")
        for index, (unit, _base) in enumerate(self.records):
            if index < 4:
                self.assertEqual(unit["order"], {"type": "MOVE", "path": []})
            else:
                self.assertIs(unit["order"], before[index])

    def test_group_selection_and_targeting_recheck_live_permissions_and_identity(self):
        for condition in ("foreign", "tactical", "read_only", "removed", "replaced_province",
                          "combat", "water", "transport", "realtime_submitted"):
            for mission in ("WEAKEST", "STRIKE"):
                with self.subTest(condition=condition, mission=mission):
                    self.setUp()
                    records = [(self.bomber, self.remote)]
                    before = self.bomber["order"]
                    if mission == "STRIKE":
                        self.screen.set_selected_air_mission(mission, records)
                    if condition == "foreign":
                        self.bomber["owner"] = "B"
                    elif condition == "tactical":
                        self.game.tactical_mode = True
                        self.game.player_unit = self.fighter
                    elif condition == "read_only":
                        self.screen.read_only = True
                    elif condition == "removed":
                        self.remote["units"] = [self.v2]
                    elif condition == "replaced_province":
                        self.game.id_to_province[3] = dict(self.remote)
                    elif condition == "combat":
                        wing(self.remote, "Infantry Type 1910", "B")
                    elif condition == "water":
                        self.remote["terrain"] = c.WATER_TERRAINS[0]
                    elif condition == "transport":
                        queries.load_transport(self.bomber, "Convoy")
                    elif condition == "realtime_submitted":
                        self.game.can_select_map_units = lambda: False
                    if mission == "STRIKE":
                        self.screen.set_bombard_target(None, self.remote)
                    else:
                        self.screen.set_selected_air_mission(mission, records)
                    self.assertIs(self.bomber["order"], before)

    def test_group_patrols_use_authoritative_existing_network_commands(self):
        self.screen.set_selected_air_mission("WEAKEST")
        commands = [{"type": "unit_order", "province_id": base["id"],
            "unit_index": base["units"].index(unit), "unit_id": unit["unit_id"], "order": dict(unit["order"])}
            for unit, base in self.records[:2]]
        self.assertEqual([c["order"] for c in MapRealtimeDriver(self.game).validate_draft("A", commands)],
                         [c["order"] for c in commands])
        tournament = [{"unit_id": c["unit_id"], "order": c["order"]} for c in commands]
        _, drafts = multiplayer_io._validate_aircraft_orders(self.game, "A", {"aircraft_orders": tournament}, {})
        self.assertEqual([d[1] for d in drafts], [c["order"] for c in commands])
        for bad in (dict(commands[1], order={"type": "AIR_PATROL", "priority": []}),
                    dict(commands[1], order={"type": "AIR_PATROL", "base_id": self.base["id"]}),
                    dict(commands[1], unit_id=self.v2["unit_id"], province_id=self.remote["id"], unit_index=1)):
            with self.subTest(command=bad):
                with self.assertRaises(RealtimeError):
                    MapRealtimeDriver(self.game).validate_draft("A", [bad])
                with self.assertRaises(ValueError):
                    multiplayer_io._validate_aircraft_orders(self.game, "A",
                        {"aircraft_orders": [{"unit_id": bad["unit_id"], "order": bad["order"]}]}, {})
        with self.assertRaises(RealtimeError):
            MapRealtimeDriver(self.game).validate_draft("B", commands)
        with self.assertRaises(ValueError):
            multiplayer_io._validate_aircraft_orders(self.game, "B", {"aircraft_orders": tournament}, {})


class AirAppSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests import app_harness
        cls.controller, cls.surface = app_harness.boot()

    def test_orders_command_icons_fill_buttons_and_preserve_proportions(self):
        from map_logic.rendering import symbol_loader
        from screens.map_related_screens.orders import ACTION_ICON_INSET, AIR_MISSION_CHOICES
        screen = Orders_Screen()
        icons = [icon for _mission, _label, icon in AIR_MISSION_CHOICES]
        icons.extend(("Air Move", "Convoying", "Disbanding", "Repairing", "Text",
                      "Upgrading", "Bombardment Arrows"))
        for button_size in (c.SIZES["orders_action_icon"], c.SIZES["list_row"]):
            available = min(button_size) - 2 * ACTION_ICON_INSET
            for name in icons:
                with self.subTest(name=name, button_size=button_size):
                    native = symbol_loader.get_native_size(name)
                    icon = screen._get_action_icon(name, button_size)
                    width, height = icon.get_size()
                    self.assertEqual(max(width, height), available)
                    self.assertLessEqual(width, available)
                    self.assertLessEqual(height, available)
                    ratio = available / max(native)
                    self.assertAlmostEqual(width, native[0] * ratio, delta=0.5)
                    self.assertAlmostEqual(height, native[1] * ratio, delta=0.5)
                    self.assertIs(icon, screen._get_action_icon(name, button_size))

        # Unit portraits retain their natural relative sizes; filling buttons
        # applies only to command glyphs.
        small_portrait = pygame.Surface((2, 2), pygame.SRCALPHA)
        self.assertIs(screen.fit_icon(small_portrait, "orders_action_icon"), small_portrait)

    def make_runtime_save(self, directory, legacy_truck=False, patrol_type="Biplane Fighter"):
        game = world()
        base = tile(game, 1, 8)
        tile(game, 2, 30, owner="B")
        fighter = wing(base, patrol_type, order={"type": "AIR_PATROL", "priority": "STRONGEST"})
        rocket = wing(base, "V2 Rocket")
        queries.load_transport(rocket, "Convoy")
        if legacy_truck:
            rocket.update(type="Truck (V2 Rocket)", max_health=c.TRUCK_MAX_HP,
                          health=c.TRUCK_MAX_HP * 0.4, naval_unit=False)
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

    def test_bomber_patrol_save_roundtrip_preserves_mission_and_priority(self):
        with tempfile.TemporaryDirectory() as directory:
            _original, bomber, _rocket, path = self.make_runtime_save(directory, patrol_type="Monoplane Bomber")
            loaded = Map(load_path=path, skip_initial_income=True)
            base = loaded.id_to_province[1]
            restored = base["units"][0]
            self.assertEqual(restored["unit_id"], bomber["unit_id"])
            self.assertEqual(restored["order"], bomber["order"])
            self.assertEqual(restored["order"], queries.canonical_air_order(loaded, restored, base, restored["order"]))

    def test_group_mission_button_fits_header_and_strike_consumes_one_map_click(self):
        from ui import modal_stack
        from screens.map_related_screens.orders import BATCH_BTN_ROW_OFFSET_Y, PANEL_Y, ACTION_COL_BOMBARD
        with tempfile.TemporaryDirectory() as directory:
            _original, _fighter, _rocket, path = self.make_runtime_save(directory)
            loaded = Map(load_path=path, skip_initial_income=True)
            loaded.selection_mode = False
            loaded.player_country = "A"
            base = loaded.id_to_province[1]
            bomber = wing(base, "Monoplane Bomber")
            missile = wing(base, "V1 Flying Bomb")
            wing(base, "Infantry Type 1910")
            loaded.select_map_units(base["units"])
            screen = Orders_Screen()
            screen.start_with_province(base, loaded)
            mission_button = next(button for button in screen.elements
                                  if getattr(button, "text", "").startswith("Set Mission"))
            eligible = len(screen._batch_command_candidates("MISSION"))
            self.assertEqual(mission_button.text, f"Set Mission ({eligible})")
            batch_buttons = [button for button in screen.elements
                             if button.rect.y == PANEL_Y + BATCH_BTN_ROW_OFFSET_Y]
            self.assertEqual(len(batch_buttons), 4)
            for index, button in enumerate(batch_buttons):
                self.assertTrue(screen.panel_rect.contains(button.rect))
                self.assertLess(button.font.size(button.text)[0], button.rect.width)
                for other in batch_buttons[index + 1:]:
                    self.assertFalse(button.rect.colliderect(other.rect))
            mission_button.callback()
            wrapper = modal_stack.active()
            popup = wrapper.screen
            try:
                self.assertEqual(len(popup.choices), 4)
                popup.elements[next(i for i, choice in enumerate(popup.choices)
                                    if choice[0] == "STRONGEST")].callback()
                wrapper.update()
                self.assertEqual(bomber["order"]["type"], "AIR_PATROL")
                self.assertNotEqual(missile["order"]["type"], "AIR_PATROL")
            finally:
                if modal_stack.active() is wrapper:
                    modal_stack.pop()
            screen.disband_selected_units()
            # Cancel labels are longer than start labels, but must still fit
            # after adding the fourth batch control.
            for button in screen.elements:
                if button.rect.y == PANEL_Y + BATCH_BTN_ROW_OFFSET_Y:
                    self.assertLess(button.font.size(button.text)[0], button.rect.width)
            screen.set_selected_air_mission("STRIKE")
            rows = {key: unit for key, unit, _province, _index in screen._visible_rows()}
            mission_buttons = [button for button in screen.action_buttons
                               if button.action_slot == ACTION_COL_BOMBARD
                               and id(rows[button.unit_index]) in screen.air_mission_targeting_ids]
            self.assertTrue(mission_buttons)
            self.assertTrue(all(button.image is screen._get_action_icon("Strike Selected")
                                for button in mission_buttons))
            with patch.object(queries, "canonical_air_order", side_effect=AssertionError("frame air rule")), \
                    patch.object(queries, "get_air_targets", side_effect=AssertionError("frame range sweep")), \
                    patch.object(queries, "air_unit_can_launch", side_effect=AssertionError("frame mission eligibility")):
                screen.draw(self.surface)
            screen.exit_screen = Mock()
            target = base
            position = (screen.panel_rect.right + 100, screen.panel_rect.centery)
            with patch.object(queries, "get_clicked_province", return_value=target):
                for event_type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP):
                    screen.handle_events([pygame.event.Event(event_type, button=1, pos=position)])
            screen.exit_screen.assert_not_called()
            self.assertIsNone(screen.bombarding_unit_index)
            self.assertFalse(screen.air_mission_targeting_units)
            self.assertEqual(bomber["order"]["type"], "AIR_ATTACK")

    def test_right_click_strike_targeting_cannot_fall_through_to_movement(self):
        with tempfile.TemporaryDirectory() as directory:
            _original, _fighter, _rocket, path = self.make_runtime_save(directory)
            loaded = Map(load_path=path, skip_initial_income=True)
            loaded.selection_mode = False
            loaded.player_country = "A"
            base = loaded.id_to_province[1]
            fighter = base["units"][0]
            radius = queries.air_order_radius(fighter, "AIR_ATTACK")
            edge_x = base["center"][0] + radius
            outside = tile(loaded, 3, int(edge_x + 1), width=1)
            touching = tile(loaded, 4, int(edge_x), width=1,
                center=(edge_x + radius, base["center"][1]))
            queries.build_air_geometry(loaded)
            self.assertTrue(queries.air_target_in_range(loaded, fighter, base, "AIR_REPOSITION", outside["id"]))
            self.assertFalse(queries.air_target_in_range(loaded, fighter, base, "AIR_ATTACK", outside["id"]))
            loaded.select_map_units([fighter])
            screen = Orders_Screen()
            screen.start_with_province(base, loaded)
            position = (screen.panel_rect.right + 100, screen.panel_rect.centery)
            screen.exit_screen = Mock()
            for group in (False, True):
                with self.subTest(group=group):
                    if group:
                        screen.set_selected_air_mission("STRIKE", [(fighter, base)])
                    else:
                        screen.set_air_mission(fighter, base, "STRIKE")
                    before = dict(fighter["order"])
                    with patch.object(c, "MOUSE_BUTTON_ACTIONS", c.default_mouse_button_actions()), \
                            patch.object(queries, "get_clicked_province", return_value=outside), \
                            patch.object(loaded, "issue_selected_move_orders", wraps=loaded.issue_selected_move_orders) as move:
                        for event_type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP):
                            screen.handle_events([pygame.event.Event(event_type, button=3, pos=position)])
                    move.assert_not_called()
                    self.assertEqual(fighter["order"], before)
                    # A skipped group strike ends targeting; re-arm it for the
                    # allowed boundary click, while a single strike stays armed.
                    if group:
                        screen.set_selected_air_mission("STRIKE", [(fighter, base)])
                    with patch.object(c, "MOUSE_BUTTON_ACTIONS", c.default_mouse_button_actions()), \
                            patch.object(queries, "get_clicked_province", return_value=touching), \
                            patch.object(loaded, "issue_selected_move_orders", wraps=loaded.issue_selected_move_orders) as move, \
                            patch.object(screen, "set_bombard_target", wraps=screen.set_bombard_target) as strike:
                        for event_type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP):
                            screen.handle_events([pygame.event.Event(event_type, button=3, pos=position)])
                    move.assert_not_called()
                    strike.assert_called_once()
                    self.assertEqual(fighter["order"], queries.canonical_air_order(loaded, fighter, base,
                        {"type": "AIR_ATTACK", "target_id": touching["id"]}))
                    command = {"type": "unit_order", "province_id": base["id"], "unit_index": 0,
                               "unit_id": fighter["unit_id"], "order": dict(fighter["order"])}
                    self.assertEqual(MapRealtimeDriver(loaded).validate_draft("A", [command])[0]["order"], fighter["order"])
                    _, drafts = multiplayer_io._validate_aircraft_orders(loaded, "A", {"aircraft_orders": [
                        {"unit_id": fighter["unit_id"], "order": command["order"]}]}, {})
                    self.assertEqual(drafts[0][1], fighter["order"])
                    invalid = dict(command, order={"type": "AIR_ATTACK", "target_id": outside["id"]})
                    with self.assertRaises(RealtimeError):
                        MapRealtimeDriver(loaded).validate_draft("A", [invalid])
                    with self.assertRaises(ValueError):
                        multiplayer_io._validate_aircraft_orders(loaded, "A", {"aircraft_orders": [
                            {"unit_id": fighter["unit_id"], "order": invalid["order"]}]}, {})
                    screen.exit_screen.assert_not_called()

    def test_air_mission_popup_uses_real_icons_fits_and_applies_a_choice(self):
        from pathlib import Path
        from ui import modal_stack
        from map_logic.rendering import symbol_loader
        with tempfile.TemporaryDirectory() as directory:
            _original, _fighter, _rocket, path = self.make_runtime_save(directory)
            loaded = Map(load_path=path, skip_initial_income=True)
            loaded.selection_mode = False
            loaded.player_country = "A"
            base = loaded.id_to_province[1]
            fighter = base["units"][0]
            loaded.select_map_units([fighter])
            screen = Orders_Screen()
            screen.start_with_province(base, loaded)
            screen.open_air_mission_select(0, base)
            wrapper = modal_stack.active()
            popup = wrapper.screen
            try:
                self.assertEqual(len(popup.choices), 4)
                self.assertTrue(self.surface.get_rect().contains(popup.panel_rect))
                for index, (_mission, _label, icon) in enumerate(popup.choices):
                    asset = Path(c.ASSETS_DIR) / (icon + ".png")
                    self.assertEqual(asset.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
                    self.assertEqual(symbol_loader._resolve_name(icon)[1], icon)
                    button = popup.elements[index]
                    self.assertTrue(popup.panel_rect.contains(button.rect))
                    self.assertEqual((button.color, button.hover_color), c.UI_COLORS["blue"])
                    self.assertIs(button.right_image, screen._get_action_icon(icon, button.rect.size))
                    self.assertTrue(button.rect.contains(
                        button.right_image.get_rect(midright=(button.rect.right - 5, button.rect.centery))))
                    self.assertLess(button.font.size(button.text)[0],
                                    button.rect.width - button.right_image.get_width() - 15)
                    for other in popup.elements[index + 1:]:
                        self.assertFalse(button.rect.colliderect(other.rect))
                with patch.object(queries, "canonical_air_order", side_effect=AssertionError("frame air rule")), \
                        patch.object(queries, "get_air_targets", side_effect=AssertionError("frame range sweep")):
                    wrapper.draw(self.surface)
                weakest_index = next(i for i, choice in enumerate(popup.choices) if choice[0] == "WEAKEST")
                popup.elements[weakest_index].callback()
                wrapper.update()
                self.assertEqual(fighter["order"]["priority"], "WEAKEST")
                self.assertIsNot(modal_stack.active(), wrapper)
            finally:
                if modal_stack.active() is wrapper:
                    modal_stack.pop()

    def test_unavailable_air_missions_remain_visible_and_ignore_clicks(self):
        from ui import modal_stack
        for name, invalid_base in (("V1 Flying Bomb", False), ("V2 Rocket", False),
                                   ("Monoplane Fighter", True)):
            with self.subTest(unit=name, invalid_base=invalid_base):
                game = world()
                base = tile(game, 1, 8, water=invalid_base)
                unit = wing(base, name)
                screen = Orders_Screen()
                screen.map_screen = game
                screen.set_air_mission = Mock()
                screen.open_air_mission_select(0, base)
                wrapper = modal_stack.active()
                popup = wrapper.screen
                try:
                    self.assertEqual(len(popup.choices), 4)
                    for index, (mission, _label, _icon) in enumerate(popup.choices):
                        button = popup.elements[index]
                        unavailable = mission in queries.AIR_INTERCEPTION_PRIORITIES or (
                            invalid_base and mission == "STRIKE")
                        self.assertEqual(button.disabled, unavailable)
                        self.assertEqual((button.color, button.hover_color),
                                         c.UI_COLORS["grey" if unavailable else "blue"])
                        self.assertTrue(button.visible)
                        self.assertTrue(popup.panel_rect.contains(button.rect))
                        if unavailable:
                            for event_type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP):
                                button.handle_event(pygame.event.Event(event_type,
                                    button=1, pos=button.rect.center))
                            button.callback()
                            screen.set_air_mission.assert_not_called()
                            self.assertIs(modal_stack.active(), wrapper)
                    popup.elements[0].callback()
                    screen.set_air_mission.assert_called_once_with(unit, base, "NONE", None)
                finally:
                    if modal_stack.active() is wrapper:
                        modal_stack.pop()

    def test_dismissing_air_mission_popup_preserves_existing_mission(self):
        from ui import modal_stack
        game = world()
        base = tile(game, 1, 8)
        fighter = wing(base, "Monoplane Fighter", order={"type": "AIR_PATROL", "priority": "STRONGEST"})
        screen = Orders_Screen()
        screen.map_screen = game
        before = dict(fighter["order"])
        screen.open_air_mission_select(0, base)
        wrapper = modal_stack.active()
        wrapper.screen.handle_back_key()
        wrapper.update()
        self.assertIsNot(modal_stack.active(), wrapper)
        self.assertEqual(fighter["order"], before)

    def test_actual_load_unpacks_legacy_air_trucks_with_health_and_identity_intact(self):
        with tempfile.TemporaryDirectory() as directory:
            _original, _fighter, rocket, path = self.make_runtime_save(directory, legacy_truck=True)
            loaded = Map(load_path=path, skip_initial_income=True)
            recovered = loaded.id_to_province[1]["units"][1]
            self.assertTrue(queries.is_air_unit(recovered))
            self.assertEqual(recovered["type"], rocket["original_type"])
            self.assertEqual(recovered["unit_id"], rocket["unit_id"])
            self.assertNotIn("original_type", recovered)
            self.assertAlmostEqual(recovered["health"] / recovered["max_health"], 0.4)

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

    def test_strike_losses_survive_actual_save_load(self):
        from data.map import save_map
        with tempfile.TemporaryDirectory() as directory:
            game, aircraft, _rocket, _path = self.make_runtime_save(directory)
            aircraft["defense"] = 0
            aircraft["order"] = {"type": "AIR_ATTACK", "base_id": 1, "target_id": 2}
            wing(game.id_to_province[2], "Infantry Type 1910", "B")
            before = aircraft["health"]
            air_processor.process_air_orders(game)
            self.assertLess(aircraft["health"], before)
            with patch.object(c, "SAVES_DIR", directory):
                asyncio.run(save_map.save_map_data(game, "after-strike"))
            loaded = Map(load_path=os.path.join(directory, "after-strike"), skip_initial_income=True)
            recovered = next(u for u in loaded.id_to_province[1]["units"]
                             if u["unit_id"] == aircraft["unit_id"])
            self.assertEqual(recovered["health"], aircraft["health"])
            self.assertEqual(recovered["morale"], aircraft["morale"])
            self.assertEqual(recovered["order"], aircraft["order"])
            self.assertTrue(queries.is_air_unit(recovered))

    def test_air_outlines_deduplicate_and_project_zoom_tilt_without_target_markers(self):
        from screens.map_related_screens.orders import MOVE_TARGET_COLOR, BOMBARD_TARGET_COLOR
        with tempfile.TemporaryDirectory() as directory:
            _original, _fighter, _rocket, path = self.make_runtime_save(directory)
            loaded = Map(load_path=path, skip_initial_income=True)
            loaded.selection_mode = False
            loaded.player_country = "A"
            base = loaded.id_to_province[1]
            fighter = base["units"][0]
            duplicate = wing(base, "Biplane Fighter", order={"type": "AIR_PATROL"})
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

    def test_small_map_fully_covered_range_keeps_a_visible_closed_boundary(self):
        game = world()
        game.map_w, game.map_h = 80, 40
        base = tile(game, 1, 8)
        game.camera = SimpleNamespace(pos=pygame.Vector2(-20, -10), zoom=2, tilt_factor=0.5)
        game.top_ui_height, game.total_ui_h = 12, 22
        screen = Orders_Screen()
        screen.map_screen = game
        surface = pygame.Surface((300, 130), pygame.SRCALPHA)
        color = (0, 255, 0)
        radius = queries.air_order_radius(wing(base), "AIR_ATTACK")
        screen.draw_air_range(surface, base, radius, color)
        left, top = queries.world_to_screen((0, 0), game)
        right, bottom = queries.world_to_screen((game.map_w, game.map_h), game)
        for point in ((left, (top + bottom) / 2), (right - 1, (top + bottom) / 2),
                      ((left + right) / 2, top), ((left + right) / 2, bottom - 1)):
            self.assertEqual(surface.get_at(tuple(int(p) for p in point))[:3], color)
        self.assertEqual(surface.get_at((int(left) - 1, int(top))).a, 0)
        self.assertEqual(surface.get_at((int(left) + 8, int(top) + 8)).a, 0)

    def test_range_cache_reuses_pixels_and_invalidates_camera_radius_and_clip(self):
        game = world()
        game.map_w, game.map_h = 160, 120
        base = tile(game, 1, 8)
        game.camera = SimpleNamespace(pos=pygame.Vector2(-10, -10), zoom=1, tilt_factor=1)
        game.top_ui_height = game.total_ui_h = 0
        screen = Orders_Screen()
        screen.map_screen = game
        surface = pygame.Surface((200, 150), pygame.SRCALPHA)
        clip = pygame.Rect(2, 3, 195, 140)
        surface.set_clip(clip)
        with patch.object(pygame.draw, "ellipse", wraps=pygame.draw.ellipse) as ellipse:
            screen.draw_air_range(surface, base, 60, (0, 255, 0))
            first = pygame.image.tobytes(surface, "RGBA")
            surface.fill((0, 0, 0, 0))
            screen.draw_air_range(surface, base, 60, (0, 255, 0))
            self.assertEqual(ellipse.call_count, 1)
            self.assertEqual(pygame.image.tobytes(surface, "RGBA"), first)
            self.assertEqual(surface.get_clip(), clip)
            game.camera.pos.x += 5
            screen.draw_air_range(surface, base, 60, (0, 255, 0))
            game.camera.zoom = 0.5
            screen.draw_air_range(surface, base, 60, (0, 255, 0))
            screen.draw_air_range(surface, base, 70, (0, 255, 0))
            surface.set_clip(pygame.Rect(5, 6, 170, 100))
            screen.draw_air_range(surface, base, 70, (0, 255, 0))
            self.assertEqual(ellipse.call_count, 5)

    def test_wrapped_range_edge_does_not_cover_far_side_of_previous_copy(self):
        from screens.map_related_screens.orders import AIR_RANGE_THICKNESS
        game = world()
        game.map_w, game.map_h = 200, 120
        base = tile(game, 1, 8, center=(10, 60))
        game.camera = SimpleNamespace(pos=pygame.Vector2(180, 0), zoom=1, tilt_factor=1)
        game.top_ui_height = game.total_ui_h = 0
        game.loop_map = True
        screen = Orders_Screen()
        screen.map_screen = game
        surface = pygame.Surface((220, 120), pygame.SRCALPHA)
        screen.draw_air_range(surface, base, 60, (0, 255, 0))
        # Closing the next copy's left edge must not bleed into the far-away
        # provinces at the right edge of the preceding copy.
        self.assertEqual(surface.get_at((19, 60)).a, 0)
        self.assertGreater(surface.get_at((20, 60)).a, 0)
        self.assertEqual(surface.get_at((20 + AIR_RANGE_THICKNESS + 1, 60)).a, 0)

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

    def test_ground_combat_rosters_show_cached_casualties_without_mutating_aircraft(self):
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
            self.assertEqual(sidebar_row["profile"]["attack"], 0)
            self.assertEqual(battle_row["profile"]["health"], 0)
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
            loaded.brush_unit = "Monoplane Bomber"
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
