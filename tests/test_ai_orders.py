"""Standing orders must survive the AI's per-turn movement re-plan.

ai_construction issues DISBAND, then ai_movement runs a few lines later in
prepare_turn and used to clear every AI unit's order back to MOVE. DISBAND is
only executed later still, by movement_processor, so the order was always gone
by the time anything could act on it -- which meant no AI unit had ever been
disbanded in the game's history: peacetime militia accumulated forever and the
obsolete-unit cull never ran once.
"""

import os
import sys
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import data.constants as c
from map_logic.ai import ai_movement


class FakeScreen:
    def __init__(self, units):
        self.map_data = {
            "p1": {"id": 1, "json_key": "p1", "owner": "Avaria", "neighbors": [],
                   "units": units}
        }
        self.id_to_province = {1: self.map_data["p1"]}
        self.nation_data = {"Avaria": {}}


def unit(order):
    return {"type": "Militia I", "owner": "Avaria", "health": 500, "order": order}


class OrderResetTests(unittest.TestCase):

    def reset(self, units):
        screen = FakeScreen(units)
        return ai_movement._reset_orders_and_collect_units(screen, ["Avaria"])

    def test_a_disband_order_survives_the_reset(self):
        u = unit({"type": "DISBAND", "turns_left": 1})
        self.reset([u])
        self.assertEqual(u["order"]["type"], "DISBAND")

    def test_a_converting_unit_is_left_alone(self):
        u = unit({"type": "CONVERT", "turns_left": 2, "to": "Convoy"})
        self.reset([u])
        self.assertEqual(u["order"]["type"], "CONVERT")
        self.assertEqual(u["order"]["turns_left"], 2, "the timer must not restart")

    def test_a_committed_unit_is_not_offered_for_re_tasking(self):
        """Leaving the order alone but still handing the unit to the movement
        planner would just get the order overwritten a moment later."""
        busy = unit({"type": "DISBAND", "turns_left": 1})
        free = unit({"type": "MOVE", "path": [7]})
        nation_units, _ = self.reset([busy, free])
        collected = [u for u, _prov in nation_units["Avaria"]]
        self.assertEqual(collected, [free])

    def test_an_ordinary_move_order_is_still_cleared(self):
        """The re-plan is the point; a stale path must not survive."""
        u = unit({"type": "MOVE", "path": [3, 4, 5]})
        self.reset([u])
        self.assertEqual(u["order"], {"type": "MOVE", "path": []})

    def test_a_bombard_order_is_cleared_so_the_ai_re_aims(self):
        """Bombardment is decided fresh each turn from where the enemy is now."""
        u = unit({"type": "BOMBARD", "target_id": 9})
        self.reset([u])
        self.assertEqual(u["order"], {"type": "MOVE", "path": []})

    def test_the_preserved_set_is_the_shared_one(self):
        """Both this and the player's 'cannot move while busy' check read the
        same constant, so they cannot drift apart."""
        for kind in c.MULTI_TURN_ORDER_TYPES:
            self.assertIn(kind, c.ORDERS_BLOCKING_MOVEMENT)


if __name__ == "__main__":
    unittest.main()
