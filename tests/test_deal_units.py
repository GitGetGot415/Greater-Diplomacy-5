"""A deal moves land. It does not move armies, and it does not leave them there.

Reported as "I took some land from the UK and got some mechanized infantry with
it". No code path in a deal has ever written a unit's owner -- conquer_province
does not read province["units"] at all -- but until now nothing moved them
either: the seller's garrison simply stood on the buyer's new province until
process_stranded_units swept the map at the end of the turn, and only then if
the seller had no access. Both halves are pinned here, because "the units did
not change hands" is not much comfort if they are still standing there.
"""

import os
import sys
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from map_logic.diplomacy import deal, deal_effects
from tests.stub_map_screen import StubMapScreen


def unit(owner, kind="Infantry"):
    return {"owner": owner, "type": kind, "attack": 10, "health": 100,
            "max_health": 100, "defense": 1, "speed": 1,
            "order": {"type": "MOVE", "path": [99]}}


class TradedLandTests(unittest.TestCase):
    """B sells A a province it has three divisions standing on."""

    def setUp(self):
        self.game = StubMapScreen(["A", "B"])
        self.sold = self.game.add_province("B", cores=["B"])
        self.home = next(p for p in self.game.map_data.values()
                         if p["owner"] == "B" and p is not self.sold)
        # A borders the province it is buying. Land has to be within reach of
        # whoever receives it (map_logic/diplomacy/reach.py), so a buyer on the
        # far side of the world is not a buyer at all.
        self.buyer_home = next(p for p in self.game.map_data.values()
                               if p["owner"] == "A")
        self.sold["neighbors"] = [self.home["id"], self.buyer_home["id"]]
        self.home["neighbors"] = [self.sold["id"]]
        self.buyer_home["neighbors"] = [self.sold["id"]]
        self.garrison = [unit("B") for _ in range(3)]
        self.sold["units"] = list(self.garrison)

    def trade(self):
        agreement = deal.new(deal.KIND_TRADE, ["B"], ["A"],
                             [deal.tiles_clause("B", "A", [self.sold["id"]])])
        deal_effects.execute(self.game, agreement)

    def test_the_land_changes_hands(self):
        self.trade()
        self.assertEqual(self.game.owner_of(self.sold["id"]), "A")

    def test_no_unit_changes_hands(self):
        self.trade()
        self.assertEqual([u["owner"] for u in self.garrison], ["B", "B", "B"])

    def test_the_buyer_does_not_receive_a_garrison_with_it(self):
        self.trade()
        self.assertEqual(self.sold["units"], [])

    def test_the_seller_keeps_its_army_on_its_own_ground(self):
        self.trade()
        self.assertEqual([u for u in self.home["units"]], self.garrison)

    def test_their_marching_orders_are_torn_up(self):
        """The path was drawn through a province they no longer occupy."""
        self.trade()
        for u in self.garrison:
            self.assertEqual(u["order"]["path"], [])

    def test_the_buyers_own_units_are_left_where_they_stand(self):
        theirs = unit("A")
        self.sold["units"].append(theirs)
        self.trade()
        self.assertEqual(self.sold["units"], [theirs])

    def test_a_seller_with_nowhere_to_go_keeps_its_army_in_place(self):
        """Rather than deleting it. This is its last province."""
        self.game.map_data.pop(str(self.home["id"]))
        self.game.id_to_province.pop(self.home["id"])
        self.trade()
        self.assertEqual([u["owner"] for u in self.sold["units"]], ["B", "B", "B"])


class CededLandTests(unittest.TestCase):
    """The same rule on a peace treaty, which shares the one transfer path."""

    def setUp(self):
        self.game = StubMapScreen(["A", "B"])
        self.game.set_war("A", "B")
        self.ceded = self.game.add_province("B", cores=["B"])
        self.home = next(p for p in self.game.map_data.values()
                         if p["owner"] == "B" and p is not self.ceded)
        winner_home = next(p for p in self.game.map_data.values()
                           if p["owner"] == "A")
        self.ceded["neighbors"] = [self.home["id"], winner_home["id"]]
        self.home["neighbors"] = [self.ceded["id"]]
        winner_home["neighbors"] = [self.ceded["id"]]
        self.garrison = [unit("B")]
        self.ceded["units"] = list(self.garrison)

    def test_a_ceded_province_hands_over_no_defenders(self):
        agreement = deal.new(deal.KIND_PEACE, ["A"], ["B"],
                             [deal.tiles_clause("B", "A", [self.ceded["id"]])])
        deal_effects.execute(self.game, agreement)

        self.assertEqual(self.game.owner_of(self.ceded["id"]), "A")
        self.assertEqual(self.ceded["units"], [])
        self.assertEqual(self.garrison[0]["owner"], "B")


if __name__ == "__main__":
    unittest.main()
