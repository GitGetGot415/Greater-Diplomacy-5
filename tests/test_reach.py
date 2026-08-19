"""Land you cannot get to is not land you can be given.

A treaty could name any province on the map. Nobody asked whether the nation
receiving it had any way of reaching the place, so a war with the United Kingdom
could be settled by demanding Australia, and a trade could move a province
between two countries on opposite sides of the world.

Reported as: "if you're demanding land (in peace deals or trade deals) could you
make it so that any land you do take has to be land that you could actually
reach ... note that puppets and allies shouldn't count as ways to reach a
territory, it has to be something you alone with your territory could reach".

Both halves are pinned here: what the rule says (Reachability), and that a deal
cannot get round it -- at the click, at validation, and at execution, which is
the gate the AI and any scripted treaty go through as well.
"""

import os
import sys
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from map_logic.diplomacy import deal, deal_effects, reach
from tests.stub_map_screen import StubMapScreen


def land(prov_id, owner, neighbors=()):
    return {"id": prov_id, "owner": owner, "cores": [owner], "terrain": "plains",
            "neighbors": list(neighbors), "units": [], "buildings": []}


def sea(prov_id, neighbors=(), terrain="ocean"):
    return {"id": prov_id, "owner": "Ocean", "cores": [], "terrain": terrain,
            "neighbors": list(neighbors), "units": [], "buildings": []}


def world(*provinces):
    return {str(p["id"]): p for p in provinces}


class OverLandTests(unittest.TestCase):
    """A ---- B ---- C, in a line."""

    def setUp(self):
        self.map_data = world(land(1, "A", [2]),
                              land(2, "B", [1, 3]),
                              land(3, "C", [2]))
        self.reach = reach.index(self.map_data)

    def at(self, prov_id):
        return self.map_data[str(prov_id)]

    def test_your_own_ground_is_always_within_reach(self):
        self.assertTrue(self.reach.reachable("A", self.at(1)))

    def test_so_is_the_province_next_door(self):
        self.assertTrue(self.reach.reachable("A", self.at(2)))

    def test_but_not_the_one_past_it(self):
        self.assertFalse(self.reach.reachable("A", self.at(3)))

    def test_a_nation_that_holds_nothing_reaches_nothing(self):
        self.assertFalse(self.reach.reachable("Nobody", self.at(2)))

    def test_and_neither_does_the_ocean(self):
        self.assertFalse(self.reach.reachable("Ocean", self.at(2)))


class PendingChainTests(unittest.TestCase):
    """A ---- B ---- C ---- D, in a line, with A holding only the first tile.

    A demand naming both B and C at once can lean on B to reach C -- the
    Alsace-Lorraine-then-Rhineland case reported against the deal screen --
    but `pending` only ever helps ids actually named in it, and only where
    they actually connect back to something real.
    """

    def setUp(self):
        self.map_data = world(land(1, "A", [2]), land(2, "Owner2", [1, 3]),
                              land(3, "Owner3", [2, 4]), land(4, "Owner4", [3]))
        self.reach = reach.index(self.map_data)

    def at(self, prov_id):
        return self.map_data[str(prov_id)]

    def test_unreachable_alone(self):
        self.assertFalse(self.reach.reachable("A", self.at(3)))

    def test_reachable_once_the_connector_is_named_alongside_it(self):
        self.assertTrue(self.reach.reachable("A", self.at(3), pending=[2, 3]))

    def test_the_chain_can_run_two_deep(self):
        self.assertTrue(self.reach.reachable("A", self.at(4), pending=[2, 3, 4]))

    def test_a_pending_id_that_does_not_connect_grants_nothing(self):
        self.assertFalse(self.reach.reachable("A", self.at(3), pending=[3]))

    def test_unreachable_ids_defaults_pending_to_the_whole_batch(self):
        self.assertEqual(self.reach.unreachable_ids("A", [2, 3]), [])

    def test_unreachable_ids_without_the_connector_in_the_batch_stays_out_of_reach(self):
        self.assertEqual(self.reach.unreachable_ids("A", [3]), [3])

    def test_an_explicit_pending_can_widen_the_batch(self):
        """The connector can live in a different clause of the same deal --
        named through `pending` rather than being part of this batch itself."""
        self.assertEqual(self.reach.unreachable_ids("A", [3], pending=[2, 3]), [])


class ThroughOtherPeopleTests(unittest.TestCase):
    """The point of the rule: only your own territory counts as a starting line.

    A ---- B ---- C, where B is A's puppet and its ally. That is exactly the
    arrangement the rule was asked for -- "puppets and allies shouldn't count as
    ways to reach a territory" -- and queries.is_nation_reachable, which answers
    a different question for war planning, would say yes to all of it.
    """

    def setUp(self):
        self.map_data = world(land(1, "A", [2]),
                              land(2, "B", [1, 3]),
                              land(3, "C", [2]))
        self.reach = reach.index(self.map_data)

    def test_a_puppets_border_is_not_your_border(self):
        self.assertFalse(self.reach.reachable("A", self.map_data["3"]))

    def test_the_puppet_can_reach_it_itself(self):
        self.assertTrue(self.reach.reachable("B", self.map_data["3"]))


class AcrossWaterTests(unittest.TestCase):
    """A and C on opposite shores of one sea; D on a lake of its own.

        1(A) -- 10(sea) -- 11(sea) -- 3(C)
        4(D) -- 20(lake) -- 5(E)
    """

    def setUp(self):
        self.map_data = world(
            land(1, "A", [10]), land(3, "C", [11]),
            sea(10, [1, 11]), sea(11, [10, 3], terrain="coastal_sea"),
            land(4, "D", [20]), land(5, "E", [20]),
            sea(20, [4, 5], terrain="lakes"),
        )
        self.reach = reach.index(self.map_data)

    def test_a_sea_between_you_is_still_a_connection(self):
        self.assertTrue(self.reach.reachable("A", self.map_data["3"]))
        self.assertTrue(self.reach.reachable("C", self.map_data["1"]))

    def test_a_lake_connects_its_own_shores(self):
        self.assertTrue(self.reach.reachable("D", self.map_data["5"]))
        self.assertTrue(self.reach.reachable("E", self.map_data["4"]))

    def test_but_a_lake_is_not_a_way_out_to_sea(self):
        """The 1941 map has one ocean and twenty-six separate lakes on it, which
        is why water is walked as bodies rather than read off an is_coastal flag."""
        self.assertFalse(self.reach.reachable("D", self.map_data["1"]))
        self.assertFalse(self.reach.reachable("A", self.map_data["4"]))

    def test_nobody_is_handed_an_ocean_tile(self):
        self.assertFalse(self.reach.reachable("A", self.map_data["10"]))


class TreatyTests(unittest.TestCase):
    """The rule as a deal actually meets it.

    Buyer -- Seller -- Distant, in a line, so the Buyer borders what the Seller
    is next to and nothing beyond it.
    """

    def setUp(self):
        self.game = StubMapScreen(["Buyer", "Seller", "Distant"])
        self.near = self.game.add_province("Seller", cores=["Seller"])
        self.far = self.game.add_province("Distant", cores=["Distant"])
        self.game.border(self.game.home_of("Buyer")["id"], self.near["id"])
        self.game.border(self.near["id"], self.far["id"])

    def trade(self, prov_id, giver, receiver="Buyer"):
        agreement = deal.new(deal.KIND_TRADE, [giver], [receiver],
                             [deal.tiles_clause(giver, receiver, [prov_id])])
        return deal_effects.execute(self.game, agreement)

    def test_a_province_on_the_border_can_be_bought(self):
        self.trade(self.near["id"], "Seller")
        self.assertEqual(self.game.owner_of(self.near["id"]), "Buyer")

    def test_one_two_countries_away_cannot(self):
        notes = self.trade(self.far["id"], "Distant")
        self.assertEqual(self.game.owner_of(self.far["id"]), "Distant")
        self.assertTrue(any("beyond anything Buyer could reach" in note
                            for note in notes), notes)

    def test_validate_says_so_before_the_offer_is_ever_sent(self):
        agreement = deal.new(deal.KIND_TRADE, ["Distant"], ["Buyer"],
                             [deal.tiles_clause("Distant", "Buyer", [self.far["id"]])])
        problems = deal.validate(agreement, self.game.map_data, self.game.nation_data)
        self.assertTrue(any("cannot reach" in p for p in problems), problems)

    def test_an_ally_cannot_be_used_as_a_pair_of_hands(self):
        """Routing the province to somebody who *can* reach it is fine; routing
        it to somebody who cannot is the loophole, and it is judged on them."""
        self.game.nation_data["Buyer"]["allied_with"] = ["Seller"]
        self.game.nation_data["Seller"]["allied_with"] = ["Buyer"]

        self.trade(self.far["id"], "Distant", receiver="Seller")
        self.assertEqual(self.game.owner_of(self.far["id"]), "Seller",
                         "the Seller does border it")

        another = self.game.add_province("Distant", cores=["Distant"])
        self.trade(another["id"], "Distant", receiver="Buyer")
        self.assertEqual(self.game.owner_of(another["id"]), "Distant",
                         "and the Buyer still does not")

    def test_the_rest_of_a_treaty_survives_one_unreachable_province(self):
        """A province with nothing else in the deal to connect it stays out of
        reach even though the rest of the treaty goes through -- this is about
        one clause failing without taking the others down with it, not about
        the two provinces having anything to do with each other."""
        stray = self.game.add_province("Loner", cores=["Loner"])
        agreement = deal.new(deal.KIND_TRADE, ["Seller", "Loner"], ["Buyer"], [
            deal.tiles_clause("Seller", "Buyer", [self.near["id"]]),
            deal.tiles_clause("Loner", "Buyer", [stray["id"]]),
        ])
        deal_effects.execute(self.game, agreement)

        self.assertEqual(self.game.owner_of(self.near["id"]), "Buyer")
        self.assertEqual(self.game.owner_of(stray["id"]), "Loner")

    def test_a_second_clause_can_lean_on_the_connection_the_first_makes(self):
        """Alsace-Lorraine, then the Rhineland: the Rhineland does not border
        Buyer, but Buyer's own demand for the province in between does, and the
        treaty would land them both at once. Judged on the deal as a whole
        rather than clause by clause, which is the whole point -- 'near' and
        'far' are written as two separate TILES clauses exactly like the case
        above, so this is what tells the two apart from it."""
        agreement = deal.new(deal.KIND_TRADE, ["Seller", "Distant"], ["Buyer"], [
            deal.tiles_clause("Seller", "Buyer", [self.near["id"]]),
            deal.tiles_clause("Distant", "Buyer", [self.far["id"]]),
        ])
        deal_effects.execute(self.game, agreement)

        self.assertEqual(self.game.owner_of(self.near["id"]), "Buyer")
        self.assertEqual(self.game.owner_of(self.far["id"]), "Buyer")

    def test_validate_agrees_the_chain_is_fine(self):
        agreement = deal.new(deal.KIND_TRADE, ["Seller", "Distant"], ["Buyer"], [
            deal.tiles_clause("Seller", "Buyer", [self.near["id"]]),
            deal.tiles_clause("Distant", "Buyer", [self.far["id"]]),
        ])
        problems = deal.validate(agreement, self.game.map_data, self.game.nation_data)
        self.assertEqual(problems, [])

    def test_dropping_the_connector_is_not_a_way_round_the_rule(self):
        """The obvious exploit: ask for the connecting province, ask for what it
        would connect, then withdraw the connector before sending. There is
        nothing to withdraw *from* here -- each check reads the deal actually
        being sent, so a deal naming only the far province is judged exactly as
        if the near one had never been asked for."""
        agreement = deal.new(deal.KIND_TRADE, ["Distant"], ["Buyer"],
                             [deal.tiles_clause("Distant", "Buyer", [self.far["id"]])])
        problems = deal.validate(agreement, self.game.map_data, self.game.nation_data)
        self.assertTrue(any("cannot reach" in p for p in problems), problems)

        notes = deal_effects.execute(self.game, agreement)
        self.assertEqual(self.game.owner_of(self.far["id"]), "Distant")
        self.assertTrue(any("beyond anything Buyer could reach" in note
                            for note in notes), notes)


class OccupiedGroundTests(unittest.TestCase):
    """The commonest demand there is, and it must never be caught by this.

    A peace treaty names the ground your army is standing on -- that is what
    winning a war looks like, and unnamed occupied land goes home when the
    fighting stops. You can always reach what you are already on.
    """

    def setUp(self):
        self.game = StubMapScreen(["Winner", "Loser"])
        self.game.set_war("Winner", "Loser")
        # Deep inside the Loser, with no border to the Winner at all: taken by
        # an army that marched there before the front moved on.
        self.overrun = self.game.add_province("Loser", cores=["Loser"])
        self.overrun["owner"] = "Winner"

    def test_land_you_are_standing_on_is_yours_to_ask_for(self):
        agreement = deal.new(deal.KIND_PEACE, ["Winner"], ["Loser"],
                             [deal.white_peace(),
                              deal.tiles_clause("Loser", "Winner", [self.overrun["id"]])])
        deal_effects.execute(self.game, agreement)
        self.assertEqual(self.game.owner_of(self.overrun["id"]), "Winner")


if __name__ == "__main__":
    unittest.main()
