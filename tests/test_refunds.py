"""Covers the queue-cancellation refund rule.

Three places cancel a production or construction queue -- the Production
screen's Cancel button, the AI's own queue clearing, and the automation toggle
that hands a player's turn to the AI. They all have to hand back what was
actually paid, which is what each entry's "refund" dict records.

The automation path did not: it read a "building_type" key that queue entries
have never carried (they use order_type + item_name), so a cancelled building
queue silently refunded nothing.
"""

import os
import sys
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data import queries
from map_logic.ai import automation_logic


def nation(materials=0, manpower=0, fuel=0):
    return {"materials": materials, "manpower": manpower, "fuel": fuel}


def building_order(name="Workshop", materials=100, manpower=10, fuel=5):
    """Matches what production.py and ai_construction.py actually queue."""
    return {"order_type": "BUILDING", "item_name": name, "turns_remaining": 3,
            "refund": {"cost_materials": materials, "cost_manpower": manpower,
                       "cost_fuel": fuel}}


def unit_order(unit_type="Infantry", materials=20, manpower=50, fuel=0):
    return {"unit_type": unit_type, "turns_remaining": 2,
            "refund": {"cost_materials": materials, "cost_manpower": manpower,
                       "cost_fuel": fuel}}


class RefundQueueItemTests(unittest.TestCase):
    def test_uses_the_stored_refund(self):
        data = nation()
        queries.refund_queue_item(data, building_order())
        self.assertEqual(data, {"materials": 100, "manpower": 10, "fuel": 5})

    def test_refund_is_added_to_existing_stock(self):
        data = nation(materials=7, manpower=3, fuel=1)
        queries.refund_queue_item(data, unit_order(materials=20, manpower=50, fuel=0))
        self.assertEqual(data, {"materials": 27, "manpower": 53, "fuel": 1})

    def test_entry_without_a_refund_falls_back_to_the_library(self):
        """Old saves predate the refund field, so pricing has to come from the
        unit library instead of silently refunding nothing."""
        lib = queries.get_unit_library()
        unit_type = next(iter(lib))
        stats = lib[unit_type]

        data = nation()
        queries.refund_queue_item(data, {"unit_type": unit_type, "turns_remaining": 1})
        self.assertEqual(data["materials"], stats.get("cost_materials", 0))
        self.assertEqual(data["manpower"], stats.get("cost_manpower", 0))

    def test_unrecognised_entry_refunds_nothing_rather_than_raising(self):
        data = nation(materials=5)
        queries.refund_queue_item(data, {"turns_remaining": 1})
        self.assertEqual(data["materials"], 5)


class StubMap:
    """Just enough map for clear_player_construction."""

    def __init__(self, provinces, player="A"):
        self.player_country = player
        self.map_data = {str(i): p for i, p in enumerate(provinces)}
        self.nation_data = {player: nation()}


class ClearPlayerConstructionTests(unittest.TestCase):
    def test_building_queue_is_actually_refunded(self):
        """The regression this exists for: before, this refunded zero."""
        prov = {"owner": "A", "building_queue": [building_order(materials=100, manpower=10, fuel=5)]}
        game_map = StubMap([prov])

        automation_logic.clear_player_construction(game_map)

        self.assertEqual(game_map.nation_data["A"],
                         {"materials": 100, "manpower": 10, "fuel": 5})
        self.assertEqual(prov["building_queue"], [])

    def test_unit_queue_is_refunded_and_cleared(self):
        prov = {"owner": "A", "unit_queue": [unit_order(materials=20, manpower=50)]}
        game_map = StubMap([prov])

        automation_logic.clear_player_construction(game_map)

        self.assertEqual(game_map.nation_data["A"]["manpower"], 50)
        self.assertEqual(game_map.nation_data["A"]["materials"], 20)
        self.assertEqual(prov["unit_queue"], [])

    def test_both_queues_across_several_provinces(self):
        provs = [
            {"owner": "A", "building_queue": [building_order(materials=100, manpower=0, fuel=0)],
             "unit_queue": [unit_order(materials=20, manpower=50, fuel=0)]},
            {"owner": "A", "building_queue": [building_order(materials=30, manpower=0, fuel=0)]},
        ]
        game_map = StubMap(provs)

        automation_logic.clear_player_construction(game_map)

        self.assertEqual(game_map.nation_data["A"]["materials"], 150)
        self.assertEqual(game_map.nation_data["A"]["manpower"], 50)
        self.assertTrue(all(not p.get("building_queue") and not p.get("unit_queue")
                            for p in provs))

    def test_other_nations_queues_are_untouched(self):
        mine = {"owner": "A", "building_queue": [building_order(materials=100)]}
        theirs = {"owner": "B", "building_queue": [building_order(materials=999)]}
        game_map = StubMap([mine, theirs])

        automation_logic.clear_player_construction(game_map)

        self.assertEqual(game_map.nation_data["A"]["materials"], 100)
        self.assertEqual(len(theirs["building_queue"]), 1)


if __name__ == "__main__":
    unittest.main()
