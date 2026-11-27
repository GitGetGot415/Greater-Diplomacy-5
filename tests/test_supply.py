"""Supply, upkeep, and order regressions on small artificial maps."""

import asyncio
from math import nextafter
from unittest import TestCase
from unittest.mock import Mock, patch

import pygame
import data.constants as c
from data import queries
from map_logic import politics, tactical_campaign
from map_logic.system32 import combat_rules, turn_processor
from map_logic.system32.time_handler import TimeHandler
from tests.stub_map_screen import bare_orders_screen, map_double
from ui.panels import sidebar_info


def province(key, owner, neighbors=(), *, sea=False, coast=False, output=(0, 0, 0)):
    return {"id": key, "json_key": str(key), "owner": owner, "neighbors": list(neighbors),
            "terrain": "ocean" if sea else "plains", "is_coastal": coast, "units": [],
            "buildings": [], "building_queue": [], "unit_queue": [], "orders": [],
            "cores": [owner], "resources": {}, "center": (key, 0), "test_output": output}


def division(where, owner="A", health=100, kind="Supply Test Division", **extra):
    unit = {"unit_id": f"{where['id']}-{len(where['units'])}", "owner": owner,
            "type": kind, "health": health, "max_health": 100, "attack": 100, "defense": 0,
            "speed": 2, "order": {"type": "MOVE", "path": []}, **extra}
    where["units"].append(unit)
    return unit


def game(*provinces):
    tiles = {tile["id"]: tile for tile in provinces}
    return map_double(map_data={str(key): tile for key, tile in tiles.items()}, id_to_province=tiles,
                      nation_data={"A": {"at_war_with": ["B"]}, "B": {"at_war_with": ["A"]}, "C": {}},
                      scenario_settings={"fog_of_war": False}, time_manager=TimeHandler(start_year=1939),
                      player_country="A", presentation_enabled=False)


class SupplyFixture(TestCase):
    def setUp(self):
        upkeep = {f"cost_{resource}": 100 for resource in c.ECON_RESOURCE_KEYS}
        self.library = {
            "Supply Test Division": {"health": 100, **upkeep},
            "Supply Test Infantry": {"health": 100, **upkeep, "cost_fuel": 0},
            "Supply Test Ship": {"health": 100, **upkeep, "naval_unit": True},
            "Supply Test Plane": {"health": 100, **upkeep, "air_role": "fighter"},
            "Submarine Supply Test": {"health": 100, **upkeep, "naval_unit": True},
        }
        self.enterContext(patch.object(queries, "get_unit_library", return_value=self.library))
        self.enterContext(patch.object(c, "UPKEEP_MODIFIERS", dict.fromkeys(c.ECON_RESOURCE_KEYS, 1)))
        axis_effect = politics.axis_effect
        self.enterContext(patch.object(politics, "axis_effect", side_effect=lambda nations, owner, effect:
                                       1.0 if effect == "unit_upkeep" else axis_effect(nations, owner, effect)))
        self.enterContext(patch.object(queries.ProvinceProduction, "breakdown", side_effect=lambda tile: {
            "core": dict(zip(c.ECON_RESOURCE_KEYS, tile["test_output"])),
        }))


class SupplyTests(SupplyFixture):
    def test_converted_fuel_follows_supply_routes_and_restores_full_speed(self):
        front = province(1, "A", [2], coast=True, output=(100, 0, 0))
        sea = province(2, "Ocean", [1, 3], sea=True)
        factory = province(3, "A", [2], coast=True, output=(0, 1900, 0))
        unit = division(front, speed=5)
        world = game(front, sea, factory)
        nation = world.world.nation_data["A"]
        nation.update(mat_to_fuel_slider=0.75, conscription_slider=1)
        with (patch.object(c, "COUNTRY_BASE_YIELDS", {"manpower": 0, "materials": 100, "fuel": 0}),
              patch.object(c, "FUEL_CONVERSION_RATIO", 0.1),
              patch.object(queries, "get_max_fuel_conversion", return_value=0.5)):
            economy = queries.calculate_all_economies(world.world.map_data, world.world.nation_data, context=world)["A"]
            snapshot = queries.SupplySnapshot(world)
            network = snapshot.for_country("A")
            self.assertEqual(economy["breakdown"]["fuel"]["conversion"], 100)
            self.assertEqual(network.production_tiles[factory["id"]]["materials"], 950)
            self.assertEqual(network.production_tiles[front["id"]]["fuel"], 2.5)
            self.assertEqual(snapshot.fractions(unit), (1, 1, 1))
            queries.prepare_presentation_supply(world)
            sidebar_info.prepare_unit_roster(world, front)
            self.assertNotIn("fuel", world._unit_roster_cache[front["id"]][2][id(unit)])
            with queries.combat_supply(queries.freeze_combat_supply(world)):
                self.assertEqual(queries.unit_movement_speed(unit), 5)
            world.world.scenario_settings["fog_of_war"] = True
            projected = queries.player_snapshot_projection(world, queries.build_save_dict(world), "A")
            self.assertEqual(projected["player_supply"][unit["unit_id"]], (1, 1, 1))

            blocked = snapshot.sea_projection("A", block=(sea["id"],), blocker="B")
            self.assertEqual(snapshot.fractions(unit, network=blocked)[2], 0.025)
            division(sea, "B", kind="Supply Test Ship")
            self.assertEqual(queries.SupplySnapshot(world).fractions(unit)[2], 0.025)
            nation["mat_to_fuel_slider"] = 0
            self.assertEqual(queries.SupplySnapshot(world).fractions(unit)[2], 0)

    def test_supply_conversion_uses_economy_rounding_and_conscription_income(self):
        tile = province(1, "A", output=(40, 147, 0))
        world = game(tile)
        world.world.nation_data["A"].update(mat_to_fuel_slider=0.5, conscription_slider=0.5)
        with (patch.object(c, "COUNTRY_BASE_YIELDS", {"manpower": 40, "materials": 100, "fuel": 0}),
              patch.object(c, "FUEL_CONVERSION_RATIO", 0.1),
              patch.object(c, "CONSCRIPTION_RATIO", 0.25),
              patch.object(queries, "get_max_fuel_conversion", return_value=0.5)):
            economy = queries.calculate_all_economies(world.world.map_data, world.world.nation_data, context=world)["A"]
            snapshot = queries.SupplySnapshot(world)
            actual = snapshot.income_conversions_for("A")[tile["id"]]
            production = snapshot.for_country("A").production_tiles[tile["id"]]
            self.assertEqual(economy["gross_materials"], 257)
            self.assertEqual(economy["breakdown"]["materials"]["conversion"], -120)
            self.assertEqual(actual["manpower"], -20)
            self.assertEqual(actual["conscription"]["materials"], 10)
            self.assertEqual(actual["fuel"], economy["breakdown"]["fuel"]["conversion"])
            self.assertAlmostEqual(actual["materials"], 10 - 120 * 157 / 257)
            self.assertEqual(production["manpower"], 20)
            self.assertAlmostEqual(production["materials"], 157 - 120 * 157 / 257)
            self.assertEqual(production["fuel"], economy["breakdown"]["fuel"]["conversion"])

    def test_conscription_conversion_updates_manpower_and_materials_supply_without_fuel_conversion(self):
        front = province(1, "A", [2], output=(60, 0, 0))
        rear = province(2, "A", [1], output=(40, 0, 0))
        unit = division(front, kind="Supply Test Infantry")
        world = game(front, rear)
        world.world.nation_data["A"].update(mat_to_fuel_slider=0, conscription_slider=0.4)
        self.library[unit["type"]].update(cost_manpower=40, cost_materials=12)
        with (patch.object(c, "COUNTRY_BASE_YIELDS", dict.fromkeys(c.ECON_RESOURCE_KEYS, 0)),
              patch.object(c, "CONSCRIPTION_RATIO", 0.2)):
            snapshot = queries.SupplySnapshot(world)
            network = snapshot.for_country("A")
            self.assertEqual(network.production_tiles[front["id"]]["manpower"], 24)
            self.assertEqual(network.production_tiles[rear["id"]]["manpower"], 16)
            self.assertAlmostEqual(network.production_tiles[front["id"]]["materials"], 7.2)
            self.assertAlmostEqual(network.production_tiles[rear["id"]]["materials"], 4.8)
            self.assertEqual(snapshot.fractions(unit), (1.0, 1.0, 1.0))
            world.world.nation_data["A"]["conscription_slider"] = 0.0
            drained = queries.SupplySnapshot(world)
            self.assertEqual(drained.fractions(unit), (0.0, 1.0, 1.0))

    def test_fractional_province_conversion_can_cover_exact_fuel_demand(self):
        front = province(1, "A", [2, 3], output=(100, 32, 0))
        first = province(2, "A", [1], output=(0, 36, 0))
        second = province(3, "A", [1], output=(0, 15, 0))
        unit = division(front, speed=5)
        world = game(front, first, second)
        world.world.nation_data["A"].update(mat_to_fuel_slider=0.65, conscription_slider=1)
        self.library[unit["type"]]["cost_fuel"] = 10
        with (patch.object(c, "COUNTRY_BASE_YIELDS", dict.fromkeys(c.ECON_RESOURCE_KEYS, 0)),
              patch.object(c, "FUEL_CONVERSION_RATIO", 0.2),
              patch.object(queries, "get_max_fuel_conversion", return_value=0.65)):
            snapshot = queries.SupplySnapshot(world)
            self.assertEqual(snapshot.fractions(unit)[2], 1.0)
            self.assertEqual(queries.unit_movement_speed(unit, supply={unit["unit_id"]: snapshot.status(unit)}), 5)

    def test_capture_projection_moves_ashore_demand_and_adds_embarked_demand(self):
        home = province(1, "A", [2], output=(100, 100, 100))
        target = province(2, "B", [1], output=(50, 50, 50))
        already_ashore = division(home)
        embarked = division(home)
        home["units"].remove(embarked)
        world = game(home, target)
        snapshot = queries.SupplySnapshot(world)
        projected = snapshot.land_supply_after_capture("A", {2: "A"}, [(2, already_ashore), (2, embarked)])
        self.assertEqual(snapshot.status(already_ashore).readiness, 1)
        self.assertIsNone(snapshot.status(embarked))
        self.assertEqual(home["units"], [already_ashore])
        self.assertEqual(target["owner"], "B")

        target.update(owner="A", units=[already_ashore, embarked])
        home["units"].clear()
        actual = queries.SupplySnapshot(world)
        self.assertEqual(projected, (actual.status(already_ashore), actual.status(embarked)))
        self.assertEqual(projected[0].readiness, 0.75)

    def test_available_production_yields_shared_resource_ratios_and_nonlethal_attrition(self):
        tile = province(1, "A", output=(15, 20, 25))
        unit = division(tile, health=50)
        world = game(tile)
        status = queries.SupplySnapshot(world).status(unit)
        self.assertEqual(status.fractions, (0.3, 0.4, 0.5))
        self.assertAlmostEqual(status.readiness, 0.35)
        queries.apply_supply_attrition(world)
        self.assertAlmostEqual(unit["health"], 46.75)
        unit["health"] = 0.5
        tile["test_output"] = (0, 0, 0)
        for _ in range(12):
            queries.apply_supply_attrition(world)
        self.assertAlmostEqual(unit["health"], 0.5 * 0.9 ** 12)

    def test_readiness_weights_live_upkeep_and_attrition_scales_with_health(self):
        modifiers = {"manpower": 0.5, "materials": 1, "fuel": 1}
        with patch.object(c, "UPKEEP_MODIFIERS", modifiers):
            for manpower, materials, readiness in ((1000, 9000, 0.10), (2000, 1000, 2 / 3),
                                                    (1000, 0, 1), (0, 1000, 0), (0, 0, 1)):
                with self.subTest(manpower=manpower, materials=materials):
                    self.library["Supply Test Division"].update(cost_manpower=2 * manpower, cost_materials=materials)
                    tile = province(1, "A", output=(manpower * 2, 0, 0))
                    unit = division(tile, health=50)
                    world = game(tile)
                    self.assertAlmostEqual(queries.SupplySnapshot(world).status(unit).readiness, readiness)
                    queries.apply_supply_attrition(world)
                    self.assertAlmostEqual(unit["health"], 50 - 5 * (1 - readiness))

    def test_fuel_speed_tiers_use_strict_fractional_cutoffs(self):
        for base in (0, 1, 2, 3, 4, 5, 6):
            with self.subTest(base=base):
                self.assertEqual(queries.fuel_movement_speed(base, 1.0), base)
                self.assertEqual(queries.fuel_movement_speed(base, 0.0), min(base, 1))
                self.assertEqual(queries.fuel_movement_speed(base, nextafter(1.0, 0.0)), max(1, base - 1) if base else 0)
                for speed in range(1, base - 1):
                    threshold = speed / (base - 1)
                    self.assertEqual(queries.fuel_movement_speed(base, threshold), speed)
                    self.assertEqual(queries.fuel_movement_speed(base, nextafter(threshold, 1.0)), speed + 1)

    def test_only_fuel_users_lose_speed_and_fuel_never_counts_toward_combat(self):
        tile = province(1, "A", output=(200, 0, 0))
        fuel_user = division(tile, speed=5)
        infantry = division(tile, speed=5, kind="Supply Test Infantry")
        world = game(tile)
        queries.prepare_presentation_supply(world)
        sidebar_info.prepare_unit_roster(world, tile)

        rows = world._unit_roster_cache[1][2]
        with queries.combat_supply(queries.presentation_supply(world)):
            for unit, speed in ((fuel_user, 1), (infantry, 5)):
                self.assertEqual(queries.unit_supply_multiplier(unit), 0.5)
                self.assertEqual(queries.unit_movement_speed(unit), speed)
                self.assertEqual(queries.presentation_move_speed(world, unit), speed)
                self.assertEqual(rows[id(unit)]["speed"], speed)
        self.assertEqual(rows[id(fuel_user)]["fuel"], ("0%", -4))
        self.assertNotIn("fuel", rows[id(infantry)])

    def test_sidebar_omits_fully_supplied_units_but_shows_a_fuel_only_shortage(self):
        tile = province(1, "A", output=(200, 200, 99.9))
        fuel_user = division(tile)
        infantry = division(tile, kind="Supply Test Infantry")
        world = game(tile)

        queries.prepare_presentation_supply(world)
        sidebar_info.prepare_unit_roster(world, tile)

        rows = world._unit_roster_cache[tile["id"]][2]
        self.assertNotIn("supply", rows[id(infantry)])
        self.assertNotIn("fuel", rows[id(infantry)])
        self.assertNotIn("supply", rows[id(fuel_user)])
        self.assertEqual(rows[id(fuel_user)]["fuel"], ("<100%", -1))

        fuel_user["speed"] = 1
        sidebar_info.prepare_unit_roster(world, tile)
        self.assertEqual(world._unit_roster_cache[tile["id"]][2][id(fuel_user)]["fuel"], ("<100%", 0))

        tile["test_output"] = (200, 200, 100)
        queries.prepare_presentation_supply(world)
        sidebar_info.prepare_unit_roster(world, tile)
        full_row = world._unit_roster_cache[tile["id"]][2][id(fuel_user)]
        self.assertNotIn("supply", full_row)
        self.assertNotIn("fuel", full_row)

    def test_fuel_caps_turn_movement_and_preserves_the_queued_route(self):
        tiles = [province(key, "Unclaimed" if key == 2 else "A",
                          [neighbor for neighbor in (key - 1, key + 1) if 1 <= neighbor <= 6])
                 for key in range(1, 7)]
        tiles[0]["test_output"] = (100, 100, 50)
        tiles[1]["test_output"] = (0, 0, 50)
        unit = division(tiles[0], speed=5, order={"type": "MOVE", "path": [2, 3, 4, 5, 6]})
        world = game(*tiles)

        with (patch.object(c, "RECORD_HISTORY", False),
              patch.object(turn_processor.politics, "tick", return_value=None),
              patch.object(turn_processor.research_processor, "process_national_research")):
            asyncio.run(turn_processor.resolve_turn_logic(world))
            self.assertEqual(tiles[1]["owner"], "A")
            self.assertIn(unit, tiles[2]["units"])
            self.assertEqual(unit["order"]["path"], [4, 5, 6])
            self.assertEqual((unit["speed"], unit["health"]), (5, 100))

            asyncio.run(turn_processor.resolve_turn_logic(world))
            self.assertIn(unit, tiles[-1]["units"])
            self.assertEqual(unit["order"]["path"], [])

    def test_pin_checks_only_steps_the_units_fuel_allows_this_turn(self):
        origin = province(1, "A", [2, 4], output=(100, 100, 0))
        safe = province(2, "A", [1, 3])
        enemy_target = province(3, "B", [2])
        enemy_origin = province(4, "B", [1])
        unit = division(origin, speed=2, order={"type": "MOVE", "path": [2, 3]})
        division(enemy_origin, "B", order={"type": "MOVE", "path": [1]})
        world = game(origin, safe, enemy_target, enemy_origin)

        self.assertIn(id(unit), queries.find_movement_pins(world))
        with queries.combat_supply(queries.freeze_combat_supply(world)):
            self.assertNotIn(id(unit), queries.find_movement_pins(world))

    def test_hp_based_upkeep_applies_on_land_at_sea_and_in_air_cargo(self):
        land = province(1, "A")
        sea = province(2, "Ocean", sea=True)
        ground = division(land, health=50, kind="Supply Test Infantry")
        transport = division(land, health=25, kind="Supply Test Plane")
        cargo = division(land, health=10)
        land["units"].remove(cargo)
        transport["air_cargo"] = [cargo]
        ship = division(sea, health=75, kind="Supply Test Ship")
        world = game(land, sea)
        snapshot = queries.SupplySnapshot(world)
        self.assertEqual(snapshot.fractions(ground), (0, 0, 1))
        for unit in (transport, cargo, ship):
            self.assertIsNone(snapshot.fractions(unit))
        economies = queries.calculate_all_economies(world.world.map_data, world.world.nation_data, context=world)
        self.assertEqual(economies["A"]["upkeep"], {"manpower": 160, "materials": 160, "fuel": 110})

    def test_access_transits_friendly_output_without_taking_it(self):
        front = province(1, "A", [2])
        bridge = province(2, "C", [1, 3], output=(900, 900, 900))
        factories = province(3, "A", [2], output=(30, 40, 50))
        unit = division(front)
        world = game(front, bridge, factories)
        self.assertEqual(queries.SupplySnapshot(world).fractions(unit), (0, 0, 0))
        world.world.nation_data["C"]["military_access"] = ["A"]
        self.assertEqual(queries.SupplySnapshot(world).fractions(unit), (0.3, 0.4, 0.5))

    def test_allies_share_only_surplus_after_domestic_upkeep(self):
        donor = province(1, "A", [2, 3], output=(250, 190, 100))
        first = province(2, "C", [1])
        second = province(3, "D", [1])
        domestic = division(donor)
        ally = division(first, "C")
        wounded_ally = division(second, "D", health=50)
        world = game(donor, first, second)
        world.world.nation_data["D"] = {}
        for member in ("A", "C", "D"):
            world.world.nation_data[member]["faction"] = "Test Faction"
        for order in ((ally, wounded_ally), (wounded_ally, ally)):
            snapshot = queries.SupplySnapshot(world)
            for unit in order:
                self.assertEqual(snapshot.fractions(unit), (1, 0.6, 0))
            self.assertEqual(snapshot.fractions(domestic), (1, 1, 1))

    def test_surplus_with_a_dedicated_route_frees_shared_production_for_another_ally(self):
        shared = province(1, "E", [2, 3], output=(100, 100, 100))
        first = province(2, "A", [1, 4])
        second = province(3, "D", [1])
        transit = province(4, "F", [2, 5])
        dedicated = province(5, "C", [4], output=(100, 100, 100))
        first_unit = division(first)
        second_unit = division(second, "D")
        world = game(shared, first, second, transit, dedicated)
        world.world.nation_data.update({"D": {}, "E": {}, "F": {"military_access": ["A"]}})
        for member in ("A", "C", "D", "E"):
            world.world.nation_data[member]["faction"] = "Test Faction"
        snapshot = queries.SupplySnapshot(world)

        self.assertEqual(snapshot.fractions(first_unit), (1, 1, 1))
        self.assertEqual(snapshot.fractions(second_unit), (1, 1, 1))

    def test_subject_draws_from_its_masters_connected_production(self):
        front = province(1, "A", [2])
        source = province(2, "C", [1], output=(100, 100, 100))
        unit = division(front)
        world = game(front, source)
        world.world.nation_data["A"]["master"] = "C"
        world.world.nation_data["C"]["puppets"] = ["A"]
        snapshot = queries.SupplySnapshot(world)
        self.assertEqual(snapshot.fractions(unit), (1, 1, 1))

    def test_ally_must_be_able_to_reach_the_actual_source_of_surplus(self):
        front = province(1, "A", [2])
        allied_border = province(2, "C", [1, 3])
        bridge = province(3, "D", [2, 4])
        source = province(4, "C", [3], output=(100, 100, 100))
        unit = division(front)
        world = game(front, allied_border, bridge, source)
        world.world.nation_data["D"] = {"military_access": ["C"]}
        for member in ("A", "C"):
            world.world.nation_data[member]["faction"] = "Test Faction"
        snapshot = queries.SupplySnapshot(world)
        donor = snapshot.for_country("C")
        self.assertEqual(donor.province_area[2], donor.province_area[4])
        self.assertEqual(snapshot.fractions(unit), (0, 0, 0))

        world.world.nation_data["D"]["military_access"].append("A")
        self.assertEqual(queries.SupplySnapshot(world).fractions(unit), (1, 1, 1))

    def test_contested_group_can_choose_allied_supply_without_joining_areas(self):
        stranded = province(1, "A", [2])
        contested = province(2, "B", [1, 3])
        source = province(3, "C", [2], output=(100, 100, 100))
        unit = division(contested)
        division(contested, "B")
        world = game(stranded, contested, source)
        for member in ("A", "C"):
            world.world.nation_data[member]["faction"] = "Test Faction"
        snapshot = queries.SupplySnapshot(world)
        network = snapshot.for_country("A")

        self.assertEqual(snapshot.fractions(unit), (1, 1, 1))
        self.assertNotIn(2, network.province_area)
        self.assertNotEqual(network.province_area[1], network.province_area[3])
        self.assertEqual(network.unit_area[unit["unit_id"]], network.province_area[3])

    def test_blocking_the_last_sea_route_cuts_allied_supply(self):
        front = province(1, "A", [2, 3], coast=True)
        north = province(2, "Ocean", [1, 4], sea=True)
        south = province(3, "Ocean", [1, 4], sea=True)
        source = province(4, "C", [2, 3], coast=True, output=(100, 100, 100))
        unit = division(front)
        division(north, "B", kind="Supply Test Ship")
        world = game(front, north, south, source)
        for member in ("A", "C"):
            world.world.nation_data[member]["faction"] = "Test Faction"
        snapshot = queries.SupplySnapshot(world)
        self.assertEqual(snapshot.fractions(unit), (1, 1, 1))
        self.assertEqual(snapshot.fractions(unit, network=snapshot.sea_projection("A", block=(3,), blocker="B")), (0, 0, 0))

        division(south, "B", kind="Supply Test Ship")
        snapshot = queries.SupplySnapshot(world)
        self.assertEqual(snapshot.fractions(unit), (0, 0, 0))
        self.assertEqual(snapshot.fractions(unit, network=snapshot.sea_projection("A", reopen=(3,))), (1, 1, 1))

    def test_sea_blockade_takes_both_routes_and_hides_submarines_in_projection(self):
        front = province(1, "A", [2, 3], coast=True)
        north = province(2, "Ocean", [1, 4], sea=True)
        south = province(3, "Ocean", [1, 4], sea=True)
        factories = province(4, "A", [2, 3], coast=True, output=(100, 100, 100))
        unit = division(front)
        division(north, "B", kind="Submarine Supply Test")
        world = game(front, north, south, factories)
        self.assertEqual(queries.SupplySnapshot(world).fractions(unit), (1, 1, 1))
        # Any hostile unit on the sea tile blocks it.
        division(south, "B", kind="Supply Test Plane")
        self.assertEqual(queries.SupplySnapshot(world).fractions(unit), (0, 0, 0))
        world.world.scenario_settings["fog_of_war"] = True
        raw = queries.build_save_dict(world)
        self.assertNotIn("player_supply", raw)
        projection = queries.player_snapshot_projection(world, raw, "A")
        self.assertEqual(projection["player_supply"], {unit["unit_id"]: (0, 0, 0)})
        self.assertEqual(projection["provinces"]["2"]["units"], [])

    def test_contested_bridge_connects_supply_until_its_defenders_leave(self):
        front = province(1, "A", [2], output=(50, 50, 50))
        contested = province(2, "A", [1, 3], output=(900, 900, 900))
        rear = province(3, "A", [2], output=(300, 300, 300))
        front_unit = division(front)
        defender = division(contested)
        division(contested, "B")
        rear_unit = division(rear)
        world = game(front, contested, rear)
        world.world.nation_data["A"]["military_access"] = ["C"]
        world.world.nation_data["C"]["at_war_with"] = ["B"]
        world.world.nation_data["B"]["at_war_with"].append("C")
        snapshot = queries.SupplySnapshot(world)
        network = snapshot.for_country("A")
        self.assertEqual(network.province_area[1], network.province_area[3])
        self.assertEqual(network.unit_area[defender["unit_id"]], network.unit_area[rear_unit["unit_id"]])
        self.assertEqual(snapshot.fractions(front_unit), (1, 1, 1))
        self.assertNotIn(2, snapshot.for_country("B").province_area)
        self.assertIn(2, snapshot.for_country("C").province_area)

        projected = snapshot.land_projection("A", block=(2,), occupier="B")
        self.assertEqual(snapshot.fractions(front_unit, network=projected), (0.5, 0.5, 0.5))

        contested["units"].remove(defender)
        snapshot = queries.SupplySnapshot(world)
        network = snapshot.for_country("A")
        self.assertNotIn(2, network.province_area)
        self.assertNotEqual(network.province_area[1], network.province_area[3])
        self.assertEqual(snapshot.fractions(front_unit), (0.5, 0.5, 0.5))

    def test_contested_coast_draws_supply_through_open_sea(self):
        beach = province(1, "B", [2], coast=True)
        sea = province(2, "Ocean", [1, 3], sea=True)
        home = province(3, "A", [2], coast=True, output=(100, 100, 100))
        unit = division(beach)
        division(beach, "B")
        world = game(beach, sea, home)

        snapshot = queries.SupplySnapshot(world)
        network = snapshot.for_country("A")
        self.assertEqual(snapshot.fractions(unit), (1, 1, 1))
        self.assertNotIn(beach["id"], network.province_area)

        division(sea, "B", kind="Supply Test Ship")
        self.assertEqual(queries.SupplySnapshot(world).fractions(unit), (0, 0, 0))

    def test_contested_group_chooses_the_route_that_covers_more_of_its_upkeep(self):
        self.library["Supply Test Division"].update(cost_manpower=100, cost_materials=900, cost_fuel=0)
        manpower = province(1, "A", [3], output=(100, 0, 0))
        materials = province(2, "A", [3], output=(0, 900, 0))
        contested = province(3, "B", [1, 2])
        unit = division(contested)
        division(contested, "B")
        snapshot = queries.SupplySnapshot(game(manpower, materials, contested))

        self.assertEqual(snapshot.fractions(unit), (0, 1, 1))
        self.assertAlmostEqual(snapshot.status(unit).readiness, 0.9)

    def test_turn_cut_and_reopening_use_frozen_combat_and_resolved_attrition(self):
        front = province(1, "A", [2])
        bridge = province(2, "A", [1, 3, 4])
        supply = province(3, "A", [2], output=(300, 300, 300))
        enemy = province(4, "B", [2], output=(100, 100, 100))
        unit = division(front)
        invading = division(enemy, "B", order={"type": "MOVE", "path": [2]})
        world = game(front, bridge, supply, enemy)
        multipliers = []
        capture = lambda context: multipliers.append(queries.unit_supply_multiplier(unit))
        with (patch.object(c, "RECORD_HISTORY", False),
              patch.object(turn_processor.politics, "tick", return_value=None),
              patch.object(turn_processor.combat_processor, "process_combat", side_effect=capture),
              patch.object(turn_processor.research_processor, "process_national_research")):
            asyncio.run(turn_processor.resolve_turn_logic(world))
            self.assertEqual(bridge["owner"], "B")
            self.assertEqual(unit["health"], 90)
            self.assertTrue(any(row["details"] == "Supply attrition" for row in world.world.unit_event_log["events"]))
            bridge["units"].remove(invading)
            enemy["units"].append(invading)
            division(supply, order={"type": "MOVE", "path": [2]})
            asyncio.run(turn_processor.resolve_turn_logic(world))
        self.assertEqual(bridge["owner"], "A")
        self.assertEqual(unit["health"], 90)
        self.assertEqual(multipliers, [1, 0])

    def test_forecast_profile_tactical_roster_and_unit_panel_read_supply(self):
        self.library["Supply Test Division"].update(cost_materials=900)
        tile = province(1, "A", output=(100, 0, 50))
        unit = division(tile)
        world = game(tile)
        queries.prepare_presentation_supply(world)
        sidebar_info.prepare_unit_roster(world, tile)
        row = world._unit_roster_cache[1][2][id(unit)]
        full_supply = sidebar_info.unit_roster_row(unit, tile, world.world.nation_data, False)
        self.assertIn("10%", row["supply"][0])
        self.assertAlmostEqual(row["attack"], full_supply["attack"] * 0.1)
        with queries.combat_supply(queries.freeze_combat_supply(world)):
            self.assertAlmostEqual(combat_rules.effective_damage_multiplier(queries.supply_combat_profile(unit)), 0.1)
            roster = tactical_campaign.campaign_roster([unit], self.library, tile["terrain"])
        self.assertAlmostEqual(combat_rules.effective_damage_multiplier(roster[0]), 0.1)
        self.assertNotIn("_supply_multiplier", unit)

    def test_sidebar_draws_available_unit_supply_in_garrison_and_combat(self):
        surface = pygame.Surface((400, 300))
        font = Mock()
        font.render.return_value = pygame.Surface((10, 15))
        font.get_height.return_value = 15
        with (patch.object(sidebar_info.flag_icons, "draw_flag_centered", return_value=10),
              patch.object(sidebar_info, "draw_combat_stats"),
              patch.object(sidebar_info, "draw_icon_row", wraps=sidebar_info.draw_icon_row) as icon_row):
            for in_combat in (False, True):
                with self.subTest(in_combat=in_combat):
                    tile = province(1, "A")
                    unit = division(tile)
                    foreign = division(tile, "B" if in_combat else "C", kind="Supply Test Infantry")
                    world = game(tile)
                    world.font = world.small_font = font
                    world.nation_colors = {}
                    queries.prepare_presentation_supply(world)
                    sidebar_info.prepare_unit_roster(world, tile)
                    _, battle, rows = world._unit_roster_cache[tile["id"]]
                    self.assertEqual(bool(battle.lanes), in_combat)

                    icon_row.reset_mock()
                    sidebar_info.draw_unit_roster(world, surface, tile, tile["units"], True, 0, 0, surface.get_width())
                    rendered = [(call.args[2], call.args[3], call.args[5]) for call in icon_row.call_args_list]
                    fuel_entry = ((sidebar_info.RESOURCE_ICONS["fuel"], "0%"),)
                    speed_entry = ((sidebar_info.ICON_SPEED, ""),)
                    self.assertCountEqual(
                        [line[:2] for line in rendered],
                        [rows[id(unit)]["supply"], ("Fuel: ", fuel_entry), ("-1 ", speed_entry), rows[id(foreign)]["supply"]])
                    fuel_index = next(index for index, line in enumerate(rendered) if line[1] == fuel_entry)
                    self.assertGreater(rendered[fuel_index][2], rendered[fuel_index - 1][2])
                    self.assertEqual(rendered[fuel_index + 1][2], rendered[fuel_index][2])

    def test_sidebar_uses_the_player_supply_projection(self):
        self.library["Supply Test Division"].update(cost_materials=900)
        tile = province(1, "A", output=(100, 0, 50))
        unit = division(tile, speed=5)
        foreign = division(tile, "C", speed=5)
        behind_fog = province(2, "C")
        hidden = division(behind_fog, "C")
        world = game(tile, behind_fog)
        world.world.scenario_settings["fog_of_war"] = True
        snapshot = queries.player_snapshot_projection(world, queries.build_save_dict(world), "A")
        world.player_supply_projection = queries.normalize_supply_projection(snapshot["player_supply"])

        queries.prepare_presentation_supply(world)
        sidebar_info.prepare_unit_roster(world, tile)

        rows = world._unit_roster_cache[tile["id"]][2]
        self.assertEqual(world.player_supply_projection, {unit["unit_id"]: (1, 0, 0.5), foreign["unit_id"]: (0, 0, 0)})
        self.assertNotIn(hidden["unit_id"], world.player_supply_projection)
        self.assertIn("10%", rows[id(unit)]["supply"][0])
        self.assertEqual(rows[id(unit)]["fuel"], ("50%", -3))
        with queries.combat_supply(queries.presentation_supply(world)):
            self.assertAlmostEqual(queries.unit_supply_multiplier(unit), 0.1)
        self.assertIn("supply", rows[id(foreign)])
        self.assertIn("fuel", rows[id(foreign)])
        self.assertEqual(queries.presentation_move_speed(world, unit), 2)
        self.assertEqual(queries.presentation_move_speed(world, foreign), 1)

        legacy = {unit["unit_id"]: (1, 0, 0.5)}
        upgraded = queries.player_snapshot_projection(world, queries.build_save_dict(world), "A", player_supply=legacy)
        self.assertEqual(upgraded["player_supply"], world.player_supply_projection)

    def test_spectator_sees_supply_with_fog_even_with_a_country_record(self):
        tile = province(1, "A", output=(50, 50, 0))
        unit = division(tile)
        world = game(tile)
        world.world.scenario_settings["fog_of_war"] = True
        world.world.nation_data["Spectator"] = {}
        world.session.player_country = "Spectator"
        world.visible_provinces, _ = queries.get_visible_provinces(world)

        queries.prepare_presentation_supply(world)
        sidebar_info.prepare_unit_roster(world, tile)

        status = queries.unit_supply_status(queries.presentation_supply(world), unit)
        self.assertEqual(status, queries.SupplySnapshot(world).status(unit))
        self.assertEqual(queries.presentation_move_speed(world, unit), 1)
        self.assertIn("supply", world._unit_roster_cache[tile["id"]][2][id(unit)])
        screen = bare_orders_screen()
        screen.map_screen = world
        self.assertTrue(any(line.startswith("Supply ") for line in screen._unit_portrait_tooltip_lines(0, unit, tile)))

        for viewer in ("B", c.TOURNAMENT_SPECTATOR):
            with self.subTest(viewer=viewer):
                world.session.player_country = viewer
                queries.prepare_presentation_supply(world)
                self.assertIsNone(queries.unit_supply_status(queries.presentation_supply(world), unit))

    def test_orders_portrait_details_use_visible_supply_and_keep_foreign_orders_private(self):
        self.library["Supply Test Division"].update(cost_materials=900)
        tile = province(1, "A", output=(100, 0, 50))
        unit = division(tile, speed=5, custom_name="Long division name")
        foreign = division(tile, "C", speed=5, order={"type": "MOVE", "path": [99]})
        world = game(tile)
        world.world.scenario_settings["fog_of_war"] = True
        world.visible_provinces = {tile["id"]}
        queries.prepare_presentation_supply(world)
        screen = bare_orders_screen()
        screen.map_screen = world
        screen._row_order_summaries = {0: ("Move: 1 step to P2", None)}

        lines = screen._unit_portrait_tooltip_lines(0, unit, tile)
        self.assertIn(unit["custom_name"], lines)
        self.assertIn(queries.get_unit_display_name(unit["type"], self.library), lines)
        self.assertIn("HP 100 / 100", lines)
        self.assertIn("Supply 10% | Manpower 100% | Materials 0%", lines)
        self.assertIn("Fuel: 50% | Speed -3", lines)
        self.assertIn("Move: 1 step to P2", lines)

        foreign_lines = screen._unit_portrait_tooltip_lines(1, foreign, tile)
        self.assertTrue(foreign_lines)
        self.assertTrue(any(line.startswith("Supply ") for line in foreign_lines))
        self.assertTrue(any(line.startswith("Fuel:") for line in foreign_lines))
        self.assertFalse(any(line.startswith("Move:") for line in foreign_lines))
        world.visible_provinces.clear()
        self.assertFalse(screen._unit_portrait_tooltip_lines(1, foreign, tile))

    def test_visible_foreign_transport_shows_its_passengers(self):
        tile = province(1, "A")
        passenger = division(tile, "B", custom_name="Carried division")
        tile["units"].remove(passenger)
        plane = division(tile, "B", kind="Supply Test Plane", air_cargo=[passenger])
        world = game(tile)
        world.world.scenario_settings["fog_of_war"] = True
        world.visible_provinces, _ = queries.get_map_fog_visibility(world)
        queries.prepare_presentation_supply(world)
        sidebar_info.prepare_unit_roster(world, tile)

        row = world._unit_roster_cache[tile["id"]][2][id(plane)]
        self.assertEqual(row["cargo"][0][0], passenger["custom_name"])
        screen = bare_orders_screen()
        screen.map_screen = world
        lines = screen._unit_portrait_tooltip_lines(0, plane, tile)
        self.assertTrue(any(passenger["custom_name"] in line for line in lines))
        self.assertEqual(sum(line.startswith("Attack ") for line in lines), 2)
        self.assertIsNone(queries.SupplySnapshot(world).status(passenger))
