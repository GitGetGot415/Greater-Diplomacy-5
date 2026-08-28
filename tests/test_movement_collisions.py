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

import os
import sys
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data import queries
from map_logic.turn_processing import combat_processor, movement_processor


class StubMapScreen:
    """Just enough of map_screen for process_movement to run standalone."""

    def __init__(self):
        self.map_data = {}
        self.id_to_province = {}
        self.nation_data = {}
        self.tactical_mode = False
        # Lets edit_province_ownership.conquer_province run without a real
        # pygame surface: the visual-update branch is skipped outright.
        self.is_editor = False
        self.viewing_ai_moves = True
        self.ai_is_thinking = False
        self.centers_need_update = False

    def add_nation(self, name, at_war_with=()):
        self.nation_data[name] = {
            "name": name,
            "at_war_with": list(at_war_with),
            "allied_with": [],
            "claims": [],
        }

    def add_province(self, pid, owner, units=()):
        prov = {
            "id": pid,
            "owner": owner,
            "_turn_start_owner": owner,
            "terrain": "Plains",
            "is_coastal": False,
            "cores": [owner],
            "units": list(units),
            "building_queue": [],
        }
        self.map_data[pid] = prov
        self.id_to_province[pid] = prov
        return prov


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
        "morale": 50.0,
    }


class MidTurnSwapTests(unittest.TestCase):
    def test_a_multi_speed_unit_fights_a_mid_turn_swap(self):
        screen = StubMapScreen()
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

    def test_a_decisive_multi_speed_swap_stops_the_winner_on_enemy_tile(self):
        screen = StubMapScreen()
        screen.add_nation("A", at_war_with=["B"])
        screen.add_nation("B", at_war_with=["A"])

        unit_a = make_unit("A", ["p2", "p3", "p4"], speed=3, attack=2000)
        unit_b = make_unit("B", ["p3", "p2"], speed=2, attack=0)
        screen.add_province("p1", "A", units=[unit_a])
        screen.add_province("p2", "A")
        screen.add_province("p3", "B")
        p4 = screen.add_province("p4", "B", units=[unit_b])

        movement_processor.process_movement(screen)

        self.assertNotIn(unit_b, p4["units"])
        self.assertNotIn("_edge_battle", unit_a)
        self.assertEqual(unit_a["_current_province_id"], "p3")
        self.assertIn(unit_a, screen.id_to_province["p3"]["units"])
        self.assertNotIn(unit_a, p4["units"])
        self.assertEqual(unit_a["order"]["path"], [])


class FinishedMoverVisibilityTests(unittest.TestCase):
    def test_a_finished_mover_still_blocks_a_later_arrival(self):
        screen = StubMapScreen()
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


class PersistentEdgeBattleTests(unittest.TestCase):
    """Head-on movement becomes one saved midpoint battle, not a bounce."""

    def build(self, a_units=1, a_attack=100, b_attack=100):
        screen = StubMapScreen()
        screen.add_nation("A", at_war_with=["B"])
        screen.add_nation("B", at_war_with=["A"])
        a = [make_unit("A", ["p2"], attack=a_attack) for _ in range(a_units)]
        b = make_unit("B", ["p1"], attack=b_attack)
        p1 = screen.add_province("p1", "A", units=a)
        p2 = screen.add_province("p2", "B", units=[b])
        return screen, p1, p2, a, b

    def start(self, screen):
        combat_processor.process_meeting_engagements(screen)
        movement_processor.process_movement(screen)

    def test_survivors_remain_in_a_persistent_midpoint_battle(self):
        screen, p1, p2, a, b = self.build()

        self.start(screen)

        self.assertIn("_edge_battle", a[0])
        self.assertIn("_edge_battle", b)
        self.assertEqual(a[0]["_edge_battle"]["origin_id"], "p1")
        self.assertEqual(b["_edge_battle"]["origin_id"], "p2")
        self.assertIn(a[0], p1["units"])
        self.assertIn(b, p2["units"])
        self.assertEqual([], queries.units_on_province(p1))
        first_health = (a[0]["health"], b["health"])

        self.start(screen)

        self.assertLess(a[0]["health"], first_health[0])
        self.assertLess(b["health"], first_health[1])
        self.assertIn("_edge_battle", a[0])
        self.assertIn("_edge_battle", b)

    def test_winner_moves_only_onto_the_opposing_origin(self):
        screen, _p1, p2, a, b = self.build(a_attack=2000, b_attack=0)
        p3 = screen.add_province("p3", "B")
        a[0]["speed"] = 2
        a[0]["order"]["path"].append("p3")

        self.start(screen)

        self.assertNotIn(b, p2["units"])
        self.assertNotIn("_edge_battle", a[0])
        self.assertIn(a[0], p2["units"])
        self.assertNotIn(a[0], p3["units"])
        self.assertEqual(a[0]["order"]["path"], [])

    def test_war_ending_releases_both_sides_to_their_existing_orders(self):
        screen, p1, p2, a, b = self.build()
        self.start(screen)
        screen.nation_data["A"]["at_war_with"] = []
        screen.nation_data["B"]["at_war_with"] = []
        screen.nation_data["A"]["military_access"] = ["B"]
        screen.nation_data["B"]["military_access"] = ["A"]

        self.start(screen)

        self.assertNotIn("_edge_battle", a[0])
        self.assertNotIn("_edge_battle", b)
        self.assertIn(a[0], p2["units"])
        self.assertIn(b, p1["units"])

    def test_a_noncombatant_crossing_the_same_edge_keeps_moving(self):
        screen, p1, p2, a, b = self.build()
        screen.add_nation("C", at_war_with=[])
        screen.nation_data["B"]["allied_with"] = ["C"]
        screen.nation_data["C"]["allied_with"] = ["B"]
        bystander = make_unit("C", ["p2"])
        p1["units"].append(bystander)

        self.start(screen)

        self.assertIn("_edge_battle", a[0])
        self.assertIn("_edge_battle", b)
        self.assertNotIn("_edge_battle", bystander)
        self.assertIn(bystander, p2["units"])

    def test_individual_retreat_leaves_other_fighters_midpoint_and_restarts_on_origin(self):
        screen, p1, _p2, a, b = self.build(a_units=2)
        self.start(screen)

        self.assertTrue(combat_processor.request_edge_retreat(a[0]))
        self.start(screen)

        self.assertNotIn("_edge_battle", a[0])
        self.assertEqual(a[0]["order"]["path"], [])
        self.assertIn("_edge_battle", a[1], "the unretreated unit should hold the edge")
        self.assertIn("_edge_battle", b, "the enemy should keep fighting the remaining unit")

        self.assertTrue(combat_processor.request_edge_retreat(a[1]))
        self.start(screen)
        combat_processor.process_combat(screen)

        self.assertNotIn("_edge_battle", b)
        self.assertIn(a[0], p1["units"])
        self.assertIn(a[1], p1["units"])
        self.assertIn(b, p1["units"], "the advancing enemy should meet the retreating units at their origin")

    def test_fast_retreat_uses_its_second_step_beyond_the_origin(self):
        screen, p1, _p2, a, _b = self.build(a_units=2)
        rear = screen.add_province("rear", "A")
        a[0]["speed"] = 2
        self.start(screen)

        self.assertTrue(combat_processor.request_edge_retreat(a[0], ["p1", "rear"]))
        self.start(screen)

        self.assertNotIn("_edge_battle", a[0])
        self.assertIn(a[0], rear["units"])
        self.assertNotIn(a[0], p1["units"])
        self.assertEqual(a[0]["order"]["path"], [])


if __name__ == "__main__":
    unittest.main()
