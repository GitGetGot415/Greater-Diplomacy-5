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

from map_logic.turn_processing import movement_processor


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


if __name__ == "__main__":
    unittest.main()
