"""Check supply decisions through the rule-based order planner."""

from data import queries
from map_logic.ai import ai_movement, ai_supply
from tests.test_supply import SupplyFixture, division, game, province


class AISupplyTests(SupplyFixture):
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
        self.assertEqual(planner.current(unit), 0)
        self.assertNotIn(2, known.occupants)
        self.assertEqual(known.fractions(unit), (1, 1, 1))
