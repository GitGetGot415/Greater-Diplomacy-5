"""Supply, upkeep, and order regressions on small artificial maps."""

import asyncio
from unittest import TestCase
from unittest.mock import Mock, patch

import pygame
import data.constants as c
from data import queries
from map_logic import custom_battle, politics
from map_logic.system32 import combat_rules, turn_processor
from map_logic.system32.time_handler import TimeHandler
from tests.stub_map_screen import map_double
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
    def test_available_production_yields_shared_resource_ratios_and_nonlethal_attrition(self):
        tile = province(1, "A", output=(15, 20, 25))
        unit = division(tile, health=50)
        world = game(tile)
        fractions = queries.SupplySnapshot(world).fractions(unit)
        self.assertEqual(fractions, (0.3, 0.4, 0.5))
        self.assertAlmostEqual(queries.supply_fraction(fractions), 0.4)
        queries.apply_supply_attrition(world)
        self.assertAlmostEqual(unit["health"], 47)
        unit["health"] = 0.5
        tile["test_output"] = (0, 0, 0)
        for _ in range(12):
            queries.apply_supply_attrition(world)
        self.assertAlmostEqual(unit["health"], 0.5 * 0.9 ** 12)

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
        economies = queries.calculate_all_economies(world.map_data, world.nation_data, context=world)
        self.assertEqual(economies["A"]["upkeep"], {"manpower": 160, "materials": 160, "fuel": 110})

    def test_access_transits_friendly_output_without_taking_it(self):
        front = province(1, "A", [2])
        bridge = province(2, "C", [1, 3], output=(900, 900, 900))
        factories = province(3, "A", [2], output=(30, 40, 50))
        unit = division(front)
        world = game(front, bridge, factories)
        self.assertEqual(queries.SupplySnapshot(world).fractions(unit), (0, 0, 0))
        world.nation_data["C"]["military_access"] = ["A"]
        self.assertEqual(queries.SupplySnapshot(world).fractions(unit), (0.3, 0.4, 0.5))

    def test_sea_blockade_takes_both_routes_and_exposes_only_owned_summary(self):
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
        world.scenario_settings["fog_of_war"] = True
        raw = queries.build_save_dict(world)
        self.assertNotIn("player_supply", raw)
        projection = queries.player_snapshot_projection(world, raw, "A")
        self.assertEqual(projection["player_supply"], {unit["unit_id"]: (0, 0, 0)})
        self.assertEqual(projection["provinces"]["2"]["units"], [])

    def test_contested_tile_draws_once_and_cannot_join_two_areas(self):
        front = province(1, "A", [2], output=(50, 50, 50))
        contested = province(2, "A", [1, 3], output=(900, 900, 900))
        rear = province(3, "A", [2], output=(300, 300, 300))
        unit = division(contested)
        division(contested, "B")
        rear_unit = division(rear)
        world = game(front, contested, rear)
        snapshot = queries.SupplySnapshot(world)
        network = snapshot.for_country("A")
        self.assertNotEqual(network.province_area[1], network.province_area[3])
        self.assertEqual(network.unit_area[unit["unit_id"]], network.unit_area[rear_unit["unit_id"]])
        self.assertEqual(network.areas[network.province_area[3]].demand["fuel"], 200)

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
            self.assertTrue(any(row["details"] == "Supply attrition" for row in world.unit_event_log["events"]))
            bridge["units"].remove(invading)
            enemy["units"].append(invading)
            division(supply, order={"type": "MOVE", "path": [2]})
            asyncio.run(turn_processor.resolve_turn_logic(world))
        self.assertEqual(bridge["owner"], "A")
        self.assertEqual(unit["health"], 90)
        self.assertEqual(multipliers, [1, 0])

    def test_forecast_profile_tactical_roster_and_unit_panel_read_supply(self):
        tile = province(1, "A", output=(30, 40, 50))
        unit = division(tile)
        world = game(tile)
        queries.prepare_presentation_supply(world)
        sidebar_info.prepare_unit_roster(world, tile)
        row = world._unit_roster_cache[1][2][id(unit)]
        full_supply = sidebar_info.unit_roster_row(unit, tile, world.nation_data, False)
        self.assertIn("40%", row["supply"])
        self.assertAlmostEqual(row["attack"], full_supply["attack"] * 0.4)
        with queries.combat_supply(queries.freeze_combat_supply(world)):
            self.assertAlmostEqual(combat_rules.effective_damage_multiplier(queries.supply_combat_profile(unit)), 0.4)
            roster = custom_battle.campaign_roster([unit], self.library, tile["terrain"])
        self.assertAlmostEqual(combat_rules.effective_damage_multiplier(roster[0]), 0.4)
        self.assertNotIn("_supply_multiplier", unit)

    def test_sidebar_draws_owned_unit_supply_in_garrison_and_combat(self):
        surface = pygame.Surface((400, 300))
        font = Mock()
        font.render.return_value = pygame.Surface((10, 15))
        font.get_height.return_value = 15
        with (patch.object(sidebar_info.flag_icons, "draw_flag_centered", return_value=10),
              patch.object(sidebar_info, "draw_combat_stats")):
            for in_combat in (False, True):
                with self.subTest(in_combat=in_combat):
                    tile = province(1, "A")
                    unit = division(tile)
                    if in_combat:
                        division(tile, "B")
                    world = game(tile)
                    world.font = world.small_font = font
                    world.nation_colors = {}
                    queries.prepare_presentation_supply(world)
                    sidebar_info.prepare_unit_roster(world, tile)
                    _, battle, rows = world._unit_roster_cache[tile["id"]]
                    self.assertEqual(bool(battle.lanes), in_combat)

                    font.render.reset_mock()
                    sidebar_info.draw_unit_roster(world, surface, tile, tile["units"], True, 0, 0, surface.get_width())
                    rendered = [call.args[0] for call in font.render.call_args_list]
                    self.assertEqual(rendered.count(rows[id(unit)]["supply"]), 1)
