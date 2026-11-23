"""Check supply decisions through the rule-based order planner."""

from unittest.mock import patch

import data.constants as c
from data import queries
from map_logic.ai import ai_movement, ai_supply
from map_logic.system32 import movement_processor
from tests.test_supply import SupplyFixture, division, game, province


class AISupplyTests(SupplyFixture):
    def test_destroyer_too_far_away_leaves_immediate_landing_to_the_army(self):
        beach = province(1, "A", [2, 3, 6], coast=True)
        approach = province(2, "Ocean", [1, 4], sea=True)
        rear = province(3, "A", [1, 7], output=(200, 200, 200))
        middle = province(4, "Ocean", [2, 5], sea=True)
        far_sea = province(5, "Ocean", [4], sea=True)
        foothold = province(6, "B", [1])
        distraction = province(7, "B", [3])
        guard = division(rear)
        division(approach, "B", kind="Convoy (Supply Test Division)", speed=1)
        division(far_sea, kind="Supply Test Ship", speed=1)
        world = game(beach, approach, rear, middle, far_sea, foothold, distraction)

        ai_movement.process_ai_unit_orders(world, countries=["A"])

        self.assertEqual(guard["order"]["path"], [1])

    def test_a_ship_that_can_get_to_the_approach_first_intercepts(self):
        beach = province(1, "A", [2, 3], coast=True)
        approach = province(2, "Ocean", [1, 4, 5], sea=True)
        rear = province(3, "A", [1], output=(100, 100, 100))
        convoy_sea = province(4, "Ocean", [2], sea=True)
        ship_sea = province(5, "Ocean", [2], sea=True)
        guard = division(rear)
        convoy = division(convoy_sea, "B", kind="Convoy (Supply Test Division)", speed=2, attack=1,
                          order={"type": "MOVE", "path": [2, 1]})
        ship = division(ship_sea, kind="Supply Test Ship", speed=1, attack=1000)
        world = game(beach, approach, rear, convoy_sea, ship_sea)

        ai_movement.process_ai_unit_orders(world, countries=["A"])

        self.assertEqual(ship["order"]["path"], [2])
        self.assertEqual(guard["order"]["path"], [])
        movement_processor.process_movement(world)
        self.assertIn(convoy, approach["units"])
        self.assertEqual(beach["units"], [])

    def test_a_second_approach_can_keep_a_landing_threat_active(self):
        beach = province(1, "A", [2, 3, 6], coast=True)
        north = province(2, "Ocean", [1, 4, 5], sea=True)
        south = province(3, "Ocean", [1, 4], sea=True)
        convoy_sea = province(4, "Ocean", [2, 3], sea=True)
        ship_sea = province(5, "Ocean", [2], sea=True)
        rear = province(6, "A", [1], output=(100, 100, 100))
        division(convoy_sea, "B", kind="Convoy (Supply Test Division)", speed=2, attack=1)
        division(ship_sea, kind="Supply Test Ship", speed=1, attack=1000)
        guard = division(rear)
        world = game(beach, north, south, convoy_sea, ship_sea, rear)

        ai_movement.process_ai_unit_orders(world, countries=["A"])

        self.assertEqual(guard["order"]["path"], [1])

    def test_reserves_a_guard_when_an_enemy_shore_is_the_only_warning(self):
        beach = province(1, "A", [2, 3], coast=True)
        sea = province(2, "Ocean", [1, 4], sea=True)
        rear = province(3, "A", [1, 5], output=(200, 200, 200))
        enemy_coast = province(4, "B", [2], coast=True)
        distraction = province(5, "B", [3])
        guard = division(rear)
        world = game(beach, sea, rear, enemy_coast, distraction)

        ai_movement.process_ai_unit_orders(world, countries=["A"])

        self.assertEqual(guard["order"]["path"], [1])

    def test_two_route_blockade_is_assigned_and_held_by_two_ships(self):
        front = province(1, "B", [2, 3], coast=True)
        north = province(2, "Ocean", [1, 4, 5], sea=True)
        south = province(3, "Ocean", [1, 4, 5], sea=True)
        source = province(4, "B", [2, 3], coast=True, output=(100, 100, 100))
        harbor = province(5, "A", [2, 3, 6], coast=True)
        distraction = province(6, "Ocean", [5, 7], sea=True)
        other_coast = province(7, "B", [6], coast=True)
        victim = division(front, "B")
        ships = [division(harbor, kind="Supply Test Ship", speed=1) for _ in range(2)]
        world = game(front, north, south, source, harbor, distraction, other_coast)
        snapshot = queries.SupplySnapshot(world)

        self.assertEqual(snapshot.fractions(victim, network=snapshot.sea_projection("B", block=(2,))), (1, 1, 1))
        self.assertEqual(snapshot.fractions(victim, network=snapshot.sea_projection("B", block=(2, 3))), (0, 0, 0))
        ai_movement.process_ai_unit_orders(world, countries=["A"])
        self.assertEqual({tuple(ship["order"]["path"]) for ship in ships}, {(2,), (3,)})

        harbor["units"].clear()
        for ship in ships:
            world.id_to_province[ship["order"]["path"][0]]["units"].append(ship)
        ai_movement.process_ai_unit_orders(world, countries=["A"])

        self.assertTrue(all(ship["order"]["path"] == [] for ship in ships))

    def test_a_ship_attacks_a_visible_blocker_to_restore_own_supply(self):
        front = province(1, "A", [2], coast=True)
        strait = province(2, "Ocean", [1, 3, 4], sea=True)
        source = province(3, "A", [2], coast=True, output=(100, 100, 100))
        sea = province(4, "Ocean", [2, 5], sea=True)
        distraction = province(5, "B", [4], coast=True)
        division(front)
        division(strait, "B", kind="Supply Test Ship", attack=1)
        relief = division(sea, kind="Supply Test Ship", attack=1000)
        world = game(front, strait, source, sea, distraction)

        ai_movement.process_ai_unit_orders(world, countries=["A"])

        self.assertEqual(relief["order"]["path"], [2])

    def test_naval_relief_prioritizes_the_shortage_with_more_upkeep(self):
        self.library["Supply Test Division"].update(cost_materials=900, cost_fuel=0)
        front = province(1, "A", [2, 3], coast=True)
        north = province(2, "Ocean", [1, 4, 6], sea=True)
        south = province(3, "Ocean", [1, 5, 6], sea=True)
        manpower = province(4, "A", [2], coast=True, output=(100, 0, 0))
        materials = province(5, "A", [3], coast=True, output=(0, 900, 0))
        sea = province(6, "Ocean", [2, 3], sea=True)
        division(front)
        for opening in (north, south):
            division(opening, "B", kind="Supply Test Ship", attack=1)
        relief = division(sea, kind="Supply Test Ship", speed=1, attack=1000)
        world = game(front, north, south, manpower, materials, sea)

        ai_movement.process_ai_unit_orders(world, countries=["A"])

        self.assertEqual(relief["order"]["path"], [3])

    def test_a_ship_scouts_a_plausible_cut_when_the_blocker_is_hidden(self):
        front = province(1, "A", [2], coast=True)
        strait = province(2, "Ocean", [1, 3, 4], sea=True)
        source = province(3, "A", [2], coast=True, output=(100, 100, 100))
        sea = province(4, "Ocean", [2, 5], sea=True)
        distraction = province(5, "B", [4], coast=True)
        division(front)
        division(strait, "B", kind="Submarine Supply Test", attack=1000)
        scout = division(sea, kind="Supply Test Ship", attack=1)
        world = game(front, strait, source, sea, distraction)
        world.scenario_settings["fog_of_war"] = True

        ai_movement.process_ai_unit_orders(world, countries=["A"])

        self.assertEqual(scout["order"]["path"], [2])

    def test_foreign_projection_uses_an_estimate_of_hidden_production(self):
        front = province(1, "B", [2], coast=True)
        sea = province(2, "Ocean", [1, 3], sea=True)
        source = province(3, "B", [2], coast=True, output=(200, 200, 200))
        unit = division(front, "B")
        world = game(front, sea, source)
        actual = queries.SupplySnapshot(world)
        known = queries.SupplySnapshot(world, visible_to="A", visible_provinces={1, 2}, source=actual)

        with patch.object(c, "BASE_YIELDS", dict.fromkeys(c.ECON_RESOURCE_KEYS, 50)):
            self.assertEqual(known.fractions(unit, network=known.sea_projection("B")), (0.5, 0.5, 0.5))
            self.assertEqual(known.fractions(unit, network=known.sea_projection("B", block=(2,))), (0, 0, 0))
        self.assertEqual(actual.fractions(unit), (1, 1, 1))

    def test_ai_projects_supply_from_open_sea_for_a_contested_coast(self):
        beach = province(1, "B", [2, 4], coast=True)
        sea = province(2, "Ocean", [1, 3], sea=True)
        home = province(3, "A", [2], coast=True, output=(100, 100, 100))
        pocket = province(4, "A", [1])
        unit = division(pocket)
        division(beach, "B")
        world = game(beach, sea, home, pocket)
        snapshot = queries.SupplySnapshot(world)
        planner = ai_supply.SupplyPlanner(snapshot, snapshot, "A")

        self.assertEqual(planner.current(unit), (0, 1))
        self.assertEqual(planner.quality(unit, beach["id"]), (1, unit["speed"]))

    def test_ai_caps_fast_advances_at_the_units_fuel_speed(self):
        tiles = [province(key, "A" if key == 1 else "B",
                          [neighbor for neighbor in (key - 1, key + 1) if 1 <= neighbor <= 6])
                 for key in range(1, 7)]
        tiles[0]["test_output"] = (100, 100, 50)
        unit = division(tiles[0], speed=5)
        world = game(*tiles)

        ai_movement.process_ai_unit_orders(world, countries=["A"])

        self.assertEqual(unit["order"], {"type": "MOVE", "path": [2, 3]})

    def test_ai_uses_existing_move_order_to_escape_an_isolated_area(self):
        front = province(1, "A", [2])
        bridge = province(2, "B", [1, 3])
        factories = province(3, "A", [2], output=(400, 400, 400))
        unit = division(front)
        world = game(front, bridge, factories)
        ai_movement.process_ai_unit_orders(world, countries=["A"])
        self.assertEqual(unit["order"], {"type": "MOVE", "path": [2]})

    def test_ai_reserves_a_guard_for_a_threatened_supply_corridor(self):
        front = province(1, "A", [2])
        bridge = province(2, "A", [1, 3, 4])
        factories = province(3, "A", [2], output=(400, 400, 400))
        enemy = province(4, "B", [2])
        division(front)
        guard = division(bridge)
        world = game(front, bridge, factories, enemy)
        ai_movement.process_ai_unit_orders(world, countries=["A"])
        self.assertEqual(guard["order"], {"type": "MOVE", "path": []})
        snapshot = queries.SupplySnapshot(world)
        self.assertEqual(ai_supply.SupplyPlanner(snapshot, snapshot, "A").critical, {2})

    def test_ai_outside_a_pocket_sends_relief(self):
        front = province(1, "A", [2])
        bridge = province(2, "B", [1, 3])
        factories = province(3, "A", [2, 4], output=(400, 400, 400))
        diversion = province(4, "B", [3])
        division(front)
        relief = division(factories)
        world = game(front, bridge, factories, diversion)
        ai_movement.process_ai_unit_orders(world, countries=["A"])
        self.assertEqual(relief["order"], {"type": "MOVE", "path": [2]})

    def test_ai_rejects_reinforcements_that_reduce_the_fronts_damage(self):
        supply = province(1, "A", [2], output=(100, 100, 100))
        front = province(2, "A", [1, 3])
        isolated = province(3, "A", [2])
        division(front)
        division(front, "B", health=500, max_health=500, attack=0)
        weak = division(isolated, attack=0)
        world = game(supply, front, isolated)
        snapshot = queries.SupplySnapshot(world)
        planner = ai_supply.SupplyPlanner(snapshot, snapshot, "A")
        self.assertFalse(planner.improves_reinforcement(weak, front))

    def test_ai_sees_own_shortage_without_seeing_submarine(self):
        front = province(1, "A", [2], coast=True)
        strait = province(2, "Ocean", [1, 3], sea=True)
        factories = province(3, "A", [2], coast=True, output=(100, 100, 100))
        unit = division(front)
        division(strait, "B", kind="Submarine Supply Test")
        world = game(front, strait, factories)
        actual = queries.SupplySnapshot(world)
        known = queries.SupplySnapshot(world, visible_to="A", visible_provinces={1, 2, 3}, source=actual)
        planner = ai_supply.SupplyPlanner(actual, known, "A")
        self.assertEqual(planner.current(unit), (0, 1))
        self.assertNotIn(2, known.occupants)
        self.assertEqual(known.fractions(unit), (1, 1, 1))
