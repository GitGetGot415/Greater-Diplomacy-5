"""Check supply decisions through the rule-based order planner."""

from unittest.mock import patch

import data.constants as c
from data import queries
from map_logic.ai import ai_movement, ai_supply
from map_logic.system32 import movement_processor
from tests.test_supply import SupplyFixture, division, game, province


class AISupplyTests(SupplyFixture):
    def test_ai_cuts_enemy_land_supply_and_holds_the_route(self):
        home = province(1, "A", [2, 3], output=(300, 300, 300))
        front = province(2, "B", [1, 3])
        cut = province(3, "B", [1, 2, 4])
        source = province(4, "B", [3], output=(100, 100, 100))
        attacker = division(home, speed=1)
        enemy = division(front, "B", attack=5)
        world = game(home, front, cut, source)

        ai_movement.process_ai_unit_orders(world, countries=["A"])
        self.assertEqual(attacker["order"]["path"], [3])
        movement_processor.process_movement(world)
        self.assertEqual(cut["owner"], "A")
        self.assertEqual(queries.SupplySnapshot(world).status(enemy).readiness, 0)

        followup = division(home, speed=1)
        ai_movement.process_ai_unit_orders(world, countries=["A"])
        self.assertEqual(attacker["order"]["path"], [])
        self.assertEqual(followup["order"]["path"], [2])

    def test_ai_commits_both_land_cuts_when_the_routes_are_redundant(self):
        home = province(1, "A", [2, 3, 4], output=(300, 300, 300))
        distraction = province(2, "B", [1])
        north = province(3, "B", [1, 5, 6])
        south = province(4, "B", [1, 5, 6])
        front = province(5, "B", [3, 4])
        source = province(6, "B", [3, 4], output=(200, 200, 200))
        remote = province(7, "A", output=(100, 100, 100))
        attacker = division(home, speed=1)
        division(remote, speed=1)
        enemy = division(front, "B", attack=5)
        world = game(home, distraction, north, south, front, source, remote)
        snapshot = queries.SupplySnapshot(world)
        self.assertEqual(snapshot.status(enemy, network=snapshot.land_projection("B", block=(3,))).readiness, 1)
        self.assertEqual(snapshot.status(enemy, network=snapshot.land_projection("B", block=(4,))).readiness, 1)
        self.assertEqual(snapshot.status(enemy, network=snapshot.land_projection("B", block=(3, 4))).readiness, 0)

        ai_movement.process_ai_unit_orders(world, countries=["A"])
        self.assertEqual(attacker["order"]["path"], [2])

        second = division(home, speed=1)
        ai_movement.process_ai_unit_orders(world, countries=["A"])
        self.assertEqual({tuple(unit["order"]["path"]) for unit in (attacker, second)}, {(3,), (4,)})
        movement_processor.process_movement(world)
        self.assertEqual(queries.SupplySnapshot(world).status(enemy).readiness, 0)
        ai_movement.process_ai_unit_orders(world, countries=["A"])
        self.assertEqual([unit["order"]["path"] for unit in (attacker, second)], [[], []])

    def test_ai_holds_a_captured_source_that_would_supply_the_enemy(self):
        home = province(1, "A", [2])
        captured = province(2, "A", [1, 3], output=(200, 200, 200))
        front = province(3, "B", [2])
        guard = division(captured, speed=1)
        enemy = division(front, "B", attack=5)
        world = game(home, captured, front)
        world.nation_data["B"]["claims"] = [2]
        snapshot = queries.SupplySnapshot(world)
        self.assertEqual(snapshot.status(enemy).readiness, 0)
        recaptured = snapshot.land_projection("B", reopen={2: "B"})
        self.assertEqual(snapshot.status(enemy, network=recaptured).readiness, 1)

        ai_movement.process_ai_unit_orders(world, countries=["A"])

        self.assertEqual(guard["order"]["path"], [])
        self.assertEqual(captured["owner"], "A")

    def test_land_cut_scoring_uses_visible_enemy_forces(self):
        home = province(1, "A", [2], output=(100, 100, 100))
        cut = province(2, "B", [1, 3, 4])
        front = province(3, "B", [2])
        source = province(4, "B", [2], output=(100, 100, 100))
        division(home)
        division(front, "B")
        world = game(home, cut, front, source)
        actual = queries.SupplySnapshot(world)
        known = queries.SupplySnapshot(world, visible_to="A", visible_provinces={1, 2, 4}, source=actual)

        observed = ai_supply.SupplyPlanner(actual, actual, "A")
        fogged = ai_supply.SupplyPlanner(actual, known, "A")
        self.assertIn((2,), observed.land_supply_objectives({2}, {}, can_coordinate=False)[0])
        self.assertFalse(fogged.land_supply_objectives({2}, {}, can_coordinate=False)[0])

    def test_ai_keeps_a_land_cut_off_the_list_when_allied_sea_supply_survives(self):
        home = province(1, "A", [2, 3], output=(100, 100, 100))
        front = province(2, "B", [1, 3, 5], coast=True)
        cut = province(3, "B", [1, 2, 4])
        source = province(4, "B", [3], output=(100, 100, 100))
        sea = province(5, "Ocean", [2, 6], sea=True)
        ally = province(6, "C", [5], coast=True, output=(100, 100, 100))
        division(home)
        division(front, "B")
        world = game(home, front, cut, source, sea, ally)
        for country in ("B", "C"):
            world.nation_data[country]["faction"] = "Test Faction"
        snapshot = queries.SupplySnapshot(world)
        planner = ai_supply.SupplyPlanner(snapshot, snapshot, "A")

        cuts, _ = planner.land_supply_objectives({3}, {}, can_coordinate=False)

        self.assertFalse(cuts)

    def test_ai_avoids_a_land_cut_it_cannot_win(self):
        home = province(1, "A", [2, 3], output=(100, 100, 100))
        distraction = province(2, "B", [1])
        cut = province(3, "B", [1, 4, 5])
        front = province(4, "B", [3])
        source = province(5, "B", [3], output=(300, 300, 300))
        attacker = division(home, speed=1)
        division(cut, "B", attack=1000)
        division(front, "B", attack=5)
        world = game(home, distraction, cut, front, source)

        ai_movement.process_ai_unit_orders(world, countries=["A"])

        self.assertEqual(attacker["order"]["path"], [2])

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

    def test_ai_reopens_sea_supply_from_an_ally(self):
        front = province(1, "A", [2], coast=True)
        strait = province(2, "Ocean", [1, 3, 4], sea=True)
        source = province(3, "C", [2], coast=True, output=(100, 100, 100))
        sea = province(4, "Ocean", [2, 5], sea=True)
        distraction = province(5, "B", [4], coast=True)
        division(front)
        division(strait, "B", kind="Supply Test Ship", attack=1)
        relief = division(sea, kind="Supply Test Ship", attack=1000)
        world = game(front, strait, source, sea, distraction)
        for member in ("A", "C"):
            world.nation_data[member]["faction"] = "Test Faction"

        ai_movement.process_ai_unit_orders(world, countries=["A"])

        self.assertEqual(relief["order"]["path"], [2])

    def test_ai_recalculates_allied_upkeep_coverage_when_booking_reinforcements(self):
        front = province(1, "A", [2, 3])
        source = province(2, "C", [1], output=(100, 100, 100))
        blocked = province(3, "B", [1, 4])
        rear = province(4, "A", [3])
        division(front)
        incoming = division(rear)
        next_unit = division(rear)
        world = game(front, source, blocked, rear)
        for member in ("A", "C"):
            world.nation_data[member]["faction"] = "Test Faction"
        snapshot = queries.SupplySnapshot(world)
        planner = ai_supply.SupplyPlanner(snapshot, snapshot, "A")

        self.assertEqual(planner.quality(incoming, 1), (0.5, 1))
        planner.book(incoming, [1])
        readiness, speed = planner.quality(next_unit, 1)
        self.assertAlmostEqual(readiness, 1 / 3)
        self.assertEqual(speed, 1)

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
