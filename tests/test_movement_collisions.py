"""Two ways units used to slip past a hostile unit without ever fighting it.

process_movement resolves a turn's movement one step at a time, and keeps
every mover out of province["units"] while its path is still being walked --
that's what lets two units on the same step move "simultaneously" without
either one blocking the other. It has one deliberate exception,
combat_rules.find_meeting_pairs, which fights a direct tile swap before any
movement starts. But that check only ever looked at a unit's very first step,
and the step loop used to re-strip *every* mover before each later step, even
one that had already finished moving. Together those left two real gaps:

  * a unit that becomes adjacent to an enemy only partway through the turn
    (e.g. a 2-speed unit catching up to one that already took its step) could
    swap tiles with it for free, since neither ever saw the other as a
    "defender" -- test_a_multi_speed_unit_fights_a_mid_turn_swap.
  * a unit that finished its move early (used up a 1-speed order, or hit a
    defender) went invisible to everyone else's later steps too, so a faster
    enemy could walk straight through the tile it was resting in --
    test_a_finished_mover_still_blocks_a_later_arrival.

Both are exercised directly against movement_processor.process_movement with
a hand-built map, isolated from the rest of turn resolution.
"""

import unittest
from unittest.mock import patch


from tests.combat_fixtures import StubBattleMap

from map_logic.system32 import combat_processor, movement_processor
from map_logic import custom_battle


def make_unit(owner, path, speed=1, health=1000, attack=100, defense=50):
    return {
        "type": "Infantry",
        "owner": owner,
        "order": {"type": "MOVE", "path": list(path)},
        "speed": speed,
        "health": health,
        "max_health": health,
        "attack": attack,
        "defense": defense,
    }


class MidTurnSwapTests(unittest.TestCase):
    def test_a_turn_start_head_on_swap_bounces_both_sides(self):
        """Hostile armies trade one volley but remain on their own tiles."""
        screen = StubBattleMap(terrain="Plains")
        screen.add_nation("A", at_war_with=["B"])
        screen.add_nation("B", at_war_with=["A"])

        unit_a = make_unit("A", ["p2"])
        unit_b = make_unit("B", ["p1"])
        p1 = screen.add_province("p1", "A", units=[unit_a])
        p2 = screen.add_province("p2", "B", units=[unit_b])

        combat_processor.process_meeting_engagements(screen)
        movement_processor.process_movement(screen)

        self.assertIn(unit_a, p1["units"])
        self.assertIn(unit_b, p2["units"])
        self.assertNotIn(unit_a, p2["units"])
        self.assertNotIn(unit_b, p1["units"])

    def test_a_multi_speed_unit_fights_a_mid_turn_swap(self):
        screen = StubBattleMap(terrain="Plains")
        screen.add_nation("A", at_war_with=["B"])
        screen.add_nation("B", at_war_with=["A"])

        unit_a = make_unit("A", ["p2", "p3"], speed=2)
        unit_b = make_unit("B", ["p3", "p2"], speed=2)

        screen.add_province("p1", "A", units=[unit_a])
        screen.add_province("p2", "A")
        screen.add_province("p3", "B")
        screen.add_province("p4", "B", units=[unit_b])

        # Not adjacent at turn start (p1 borders p2, not p4), so the
        # turn-start meeting-pairs pass -- which this test intentionally
        # never calls -- would not have caught them anyway. They only meet
        # after each has taken one step, on the p2<->p3 edge, at step 2.
        movement_processor.process_movement(screen)

        self.assertLess(unit_a["health"], 1000, "unit A should have taken damage in the swap")
        self.assertLess(unit_b["health"], 1000, "unit B should have taken damage in the swap")

        # Neither should have completed the crossing into the other's tile.
        self.assertEqual(unit_a["_current_province_id"], "p2")
        self.assertEqual(unit_b["_current_province_id"], "p3")
        self.assertNotIn(unit_a, screen.id_to_province["p3"]["units"])
        self.assertNotIn(unit_b, screen.id_to_province["p2"]["units"])


class TacticalSwapTests(unittest.TestCase):
    def setUp(self):
        self.library = {"Fixture Infantry I": {
            "health": 1000, "attack": 100, "defense": 0, "speed": 3,
            "naval_unit": False, "bombard_range": 0,
        }}
        self.enterContext(patch("data.queries.get_unit_library", return_value=self.library))

    def screen(self):
        screen = StubBattleMap(terrain="plains")
        screen.add_nation("A", at_war_with=["B"])
        screen.add_nation("B", at_war_with=["A"])
        screen.tactical_mode = True
        return screen

    def mover(self, owner, path, **stats):
        unit = make_unit(owner, path, **stats)
        unit["type"] = "Fixture Infantry I"
        return unit

    def test_tactical_unit_wins_turn_start_crossing_in_either_direction_without_damage(self):
        for player_country in ("A", "B"):
            with self.subTest(player_country=player_country):
                screen = self.screen()
                first = self.mover("A", ["p2"])
                second = self.mover("B", ["p1"])
                p1 = screen.add_province("p1", "A", units=[first])
                p2 = screen.add_province("p2", "B", units=[second])
                player, opponent = (first, second) if player_country == "A" else (second, first)
                player.update(health=1, max_health=1, attack=0, defense=0)
                opponent.update(attack=100000, defense=0)
                screen.player_unit = player
                origin, destination = (p1, p2) if player_country == "A" else (p2, p1)

                combat_processor.process_pinning(screen)
                combat_processor.process_meeting_engagements(screen)
                movement_processor.process_movement(screen)
                combat_processor.process_combat(screen)

                self.assertEqual((player["health"], opponent["health"]), (1, 1000))
                self.assertTrue(any(unit is player for unit in destination["units"]))
                self.assertTrue(any(unit is opponent for unit in destination["units"]))
                self.assertEqual(origin["units"], [])
                self.assertEqual(destination["owner"], opponent["owner"])
                self.assertIsNotNone(custom_battle.tactical_encounter(screen, destination))
                self.assertNotIn("_combat_locked", opponent)

    def test_tactical_mid_turn_crossing_stops_fast_unit_on_the_encounter_tile(self):
        screen = self.screen()
        player = self.mover("A", ["p2", "p3", "p5"], speed=3, health=1, attack=0, defense=0)
        opponent = self.mover("B", ["p3", "p2"], speed=2, attack=100000, defense=0)
        screen.player_unit = player
        screen.add_province("p1", "A", units=[player])
        screen.add_province("p2", "A")
        destination = screen.add_province("p3", "B")
        screen.add_province("p4", "B", units=[opponent])
        screen.add_province("p5", "B")

        combat_processor.process_pinning(screen)
        combat_processor.process_meeting_engagements(screen)
        movement_processor.process_movement(screen)
        self.assertEqual(player["order"]["path"], ["p5"])
        self.assertEqual(opponent["order"]["path"], ["p2"])
        combat_processor.process_combat(screen)

        self.assertEqual({id(unit) for unit in destination["units"]}, {id(player), id(opponent)})
        self.assertEqual((player["health"], opponent["health"]), (1, 1000))
        self.assertEqual(destination["owner"], "B")
        self.assertEqual(player["order"]["path"], [])
        self.assertEqual(opponent["order"]["path"], [])
        self.assertIsNotNone(custom_battle.tactical_encounter(screen, destination))
        self.assertTrue(all("_skip_remaining_steps" not in unit for unit in (player, opponent)))

    def test_priority_does_not_apply_outside_tactical_play_or_in_either_multiplayer_mode(self):
        for mode in ("ordinary", "tournament", "realtime", "different_unit"):
            with self.subTest(mode=mode):
                screen = self.screen()
                first = self.mover("A", ["p2"])
                second = self.mover("B", ["p1"])
                p1 = screen.add_province("p1", "A", units=[first])
                p2 = screen.add_province("p2", "B", units=[second])
                screen.player_unit = first
                if mode == "ordinary":
                    screen.tactical_mode = False
                elif mode == "tournament":
                    screen.multiplayer_mode = True
                elif mode == "realtime":
                    screen.realtime_multiplayer = True
                else:
                    screen.player_unit = self.mover("A", [])
                    screen.add_province("p3", "A", units=[screen.player_unit])
                combat_processor.process_meeting_engagements(screen)
                movement_processor.process_movement(screen)
                self.assertEqual(p1["units"], [first])
                self.assertEqual(p2["units"], [second])
                self.assertLess(first["health"], first["max_health"])
                self.assertLess(second["health"], second["max_health"])

    def test_neutral_crossing_bystander_is_not_held_for_the_tactical_fight(self):
        screen = self.screen()
        screen.add_nation("C")
        screen.nation_data["A"]["military_access"] = ["C"]
        player = self.mover("A", ["p2"])
        opponent = self.mover("B", ["p1"])
        bystander = self.mover("C", ["p1"])
        screen.player_unit = player
        origin = screen.add_province("p1", "A", units=[player])
        destination = screen.add_province("p2", "B", units=[opponent, bystander])
        combat_processor.process_pinning(screen)
        combat_processor.process_meeting_engagements(screen)
        movement_processor.process_movement(screen)
        combat_processor.process_combat(screen)
        self.assertEqual(origin["units"], [bystander])
        self.assertEqual({id(unit) for unit in destination["units"]}, {id(player), id(opponent)})
        self.assertEqual(bystander["health"], bystander["max_health"])

    def test_tactical_crossing_priority_requires_a_living_mobile_unit_and_legal_destination(self):
        for problem in ("dead", "immobile", "water", "naval_opponent"):
            with self.subTest(problem=problem):
                screen = self.screen()
                player = self.mover("A", ["p2"])
                opponent = self.mover("B", ["p1"])
                origin = screen.add_province("p1", "A", units=[player])
                destination = screen.add_province("p2", "B", units=[opponent])
                screen.player_unit = player
                if problem == "dead":
                    player["health"] = 0
                elif problem == "immobile":
                    player["speed"] = 0
                elif problem == "water":
                    destination["terrain"] = "ocean"
                else:
                    self.library["Fixture Ship I"] = {"naval_unit": True, "bombard_range": 0}
                    opponent["type"] = "Fixture Ship I"
                self.assertIsNone(custom_battle.tactical_meeting_side(
                    screen, origin, destination, [player], [opponent]))

    def test_unrelated_war_on_the_same_crossing_still_resolves_normally(self):
        for mid_turn in (False, True):
            with self.subTest(mid_turn=mid_turn):
                screen = self.screen()
                screen.add_nation("C", at_war_with=["D"])
                screen.add_nation("D", at_war_with=["C"])
                player = self.mover("A", ["p2"], attack=0, defense=0)
                opponent = self.mover("B", ["p1"], attack=0, defense=0)
                third = self.mover("C", ["p2"], attack=100, defense=0)
                fourth = self.mover("D", ["p1"], attack=100, defense=0)
                screen.player_unit = player
                origin = screen.add_province("p1", "A", units=[player, third])
                destination = screen.add_province("p2", "B", units=[opponent, fourth])
                if not mid_turn:
                    combat_processor.process_pinning(screen)
                    combat_processor.process_meeting_engagements(screen)
                movement_processor.process_movement(screen)
                combat_processor.process_combat(screen)
                self.assertEqual({id(unit) for unit in origin["units"]}, {id(third)})
                self.assertEqual({id(unit) for unit in destination["units"]},
                                 {id(player), id(opponent), id(fourth)})
                self.assertEqual((player["health"], opponent["health"]), (1000, 1000))
                self.assertEqual((third["health"], fourth["health"]), (900, 900))


class FinishedMoverVisibilityTests(unittest.TestCase):
    def test_a_finished_mover_still_blocks_a_later_arrival(self):
        screen = StubBattleMap(terrain="Plains")
        screen.add_nation("A", at_war_with=["B"])
        screen.add_nation("B", at_war_with=["A"])

        # C has 1 speed and finishes moving on step 1 (index 0).
        unit_c = make_unit("A", ["c2"], speed=1)
        # D has 2 speed and only reaches c2 on its second step (index 1),
        # by which point C is done moving but should still be standing there.
        unit_d = make_unit("B", ["mid", "c2"], speed=2)

        screen.add_province("c1", "A", units=[unit_c])
        screen.add_province("c2", "A")
        screen.add_province("mid", "B")
        screen.add_province("d1", "B", units=[unit_d])

        movement_processor.process_movement(screen)

        c2 = screen.id_to_province["c2"]
        self.assertIn(unit_c, c2["units"], "the finished unit should still be resting in c2")
        self.assertIn(unit_d, c2["units"], "the arriving unit should have stopped alongside it, not through it")
        self.assertEqual(c2["owner"], "A", "an enemy present should block the capture, not just the advance")


if __name__ == "__main__":
    unittest.main()
