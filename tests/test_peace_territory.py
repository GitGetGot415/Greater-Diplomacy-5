"""What a peace treaty does to the map, and only what it says it does.

Peace used to leave the front line exactly where the armies had left it. A white
peace -- whose own description used to read "the fighting stops, the map stands" --
froze every conquest permanently, which made the territorial clauses of a treaty
very nearly decorative: whether or not you demanded the ground you were standing
on, you kept it.

It also made a settlement impossible to read. Combat resolves in phase 2 and
diplomacy in phase 1 of the turn after, so the map always moves at least once
between an offer being written and it being signed, and every one of those
changes arrived alongside the treaty with nothing to distinguish them from it.
In `what the hell happened here` that produced a player convinced their peace
deal had given the Netherlands a province, when Dutch troops had simply retaken
it the turn before.

So: only tiles the treaty names change hands for good, everything else occupied
goes back to whoever held it before the war, and anything the treaty could not
honour says so out loud.
"""

import os
import sys
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from map_logic.diplomacy import deal, deal_effects, war_actions
from tests.stub_map_screen import StubMapScreen


class RestoreOccupiedTests(unittest.TestCase):
    def setUp(self):
        self.game = StubMapScreen(["A", "B"])
        # Two provinces each, snapshotted, then A overruns both of B's.
        self.mine = self.game.add_province("A")
        self.also_mine = self.game.add_province("A")
        self.theirs = self.game.add_province("B")
        self.also_theirs = self.game.add_province("B")
        # One shared frontier, so every province here is within reach of both of
        # them -- otherwise no term could move anything. See stub.border.
        self.game.border(self.game.home_of("A")["id"], self.game.home_of("B")["id"],
                         self.mine["id"], self.also_mine["id"],
                         self.theirs["id"], self.also_theirs["id"])

        for nation in ("A", "B"):
            war_actions.save_own_pre_war_map(self.game.map_data, self.game.nation_data, nation)
        self.game.set_war("A", "B")
        self.theirs["owner"] = "A"
        self.also_theirs["owner"] = "A"

    def white_peace(self):
        return deal_effects.execute(self.game, deal.ceasefire_deal("A", "B"))

    def test_a_white_peace_gives_the_conquests_back(self):
        self.white_peace()
        self.assertEqual(self.game.owner_of(self.theirs["id"]), "B")
        self.assertEqual(self.game.owner_of(self.also_theirs["id"]), "B")

    def test_and_says_so(self):
        notes = self.white_peace()
        self.assertTrue(any("returned to their pre-war owners" in note for note in notes), notes)

    def test_a_province_the_treaty_names_is_kept(self):
        agreement = deal.new(deal.KIND_PEACE, ["A"], ["B"],
                             [deal.white_peace(),
                              deal.tiles_clause("B", "A", [self.theirs["id"]])])
        deal_effects.execute(self.game, agreement)

        self.assertEqual(self.game.owner_of(self.theirs["id"]), "A",
                         "the treaty asked for this one")
        self.assertEqual(self.game.owner_of(self.also_theirs["id"]), "B",
                         "and did not ask for this one")

    def test_the_winner_keeps_its_own_land(self):
        self.white_peace()
        self.assertEqual(self.game.owner_of(self.mine["id"]), "A")
        self.assertEqual(self.game.owner_of(self.also_mine["id"]), "A")

    def test_a_third_party_is_not_this_treaty_s_business(self):
        """C is not in the deal. Land A took from C stays taken -- the treaty
        settles one war, not every war on the map."""
        self.game._add_nation("C")
        theirs = self.game.add_province("C")
        war_actions.save_own_pre_war_map(self.game.map_data, self.game.nation_data, "C")
        self.game.set_war("A", "C")
        theirs["owner"] = "A"

        self.white_peace()
        self.assertEqual(self.game.owner_of(theirs["id"]), "A")

    def test_a_trade_moves_land_without_giving_any_back(self):
        """restore_occupied belongs to ending a war. A peacetime exchange of
        territory is not one, and must not quietly undo a war going on beside it."""
        agreement = deal.new(deal.KIND_TRADE, ["A"], ["B"],
                             [deal.tiles_clause("A", "B", [self.mine["id"]])])
        deal_effects.execute(self.game, agreement)

        self.assertEqual(self.game.owner_of(self.mine["id"]), "B")
        self.assertEqual(self.game.owner_of(self.theirs["id"]), "A", "war conquest untouched")


class StaleTermTests(unittest.TestCase):
    """Terms the world moved out from under between offer and signature."""

    def setUp(self):
        self.game = StubMapScreen(["A", "B", "Ally", "Outsider"])
        self.promised = self.game.add_province("B")
        # A borders what it is being promised; these tests are about title
        # moving out from under a term, not about reach.
        self.game.border(self.game.home_of("A")["id"], self.promised["id"])
        self.game.set_war("A", "B")

    def deal_for(self, sides_b=("B",)):
        return deal.new(deal.KIND_PEACE, ["A"], list(sides_b),
                        [deal.tiles_clause("B", "A", [self.promised["id"]])])

    def test_a_province_taken_by_a_co_belligerent_is_still_handed_over(self):
        """The window is unavoidable -- combat runs after diplomacy is written --
        and what usually happens in it is that somebody on the *giving* side
        takes the tile. Dropping the term let that ally keep it, which is not
        what either signatory agreed to.
        """
        self.promised["owner"] = "Ally"
        agreement = self.deal_for(sides_b=("B", "Ally"))

        notes = deal_effects.execute(self.game, agreement)

        self.assertEqual(self.game.owner_of(self.promised["id"]), "A")
        self.assertTrue(any("co-belligerents" in note for note in notes), notes)

    def test_a_province_that_left_the_war_entirely_is_dropped_and_reported(self):
        self.promised["owner"] = "Outsider"
        notes = deal_effects.execute(self.game, self.deal_for())

        self.assertEqual(self.game.owner_of(self.promised["id"]), "Outsider")
        self.assertTrue(any("could not be given" in note for note in notes), notes)


class PreWarSnapshotTests(unittest.TestCase):
    """Every belligerent needs a record of where its borders were, not only the
    ones that happen to be in a faction."""

    def setUp(self):
        self.game = StubMapScreen(["A", "B"])
        self.prov = self.game.add_province("A")

    def snapshot(self, nation):
        war_actions.save_own_pre_war_map(self.game.map_data, self.game.nation_data, nation)
        return self.game.nation_data.get("WAR_PRE_MAPS", {}).get(nation)

    def test_a_nation_with_no_faction_gets_one(self):
        mine = {str(p["id"]): "A" for p in self.game.map_data.values()
                if p.get("owner") == "A"}
        self.assertEqual(self.snapshot("A"), mine)
        self.assertIn(str(self.prov["id"]), mine)

    def test_it_is_merged_into_the_pre_war_index(self):
        self.snapshot("A")
        index = deal.prewar_index(self.game.nation_data)
        self.assertEqual(index.get(str(self.prov["id"])), "A")

    def test_a_second_war_does_not_ratify_the_first_one_s_conquests(self):
        """Re-snapshotting mid-war would write today's front line down as where
        the borders had always been, and peace would hand back nothing."""
        self.snapshot("A")
        self.game.set_war("A", "B")
        taken = self.game.add_province("A")

        self.assertNotIn(str(taken["id"]), self.snapshot("A") or {})

    def test_it_is_dropped_once_the_wars_are_over(self):
        self.snapshot("A")
        war_actions.clear_own_pre_war_map_if_peace(self.game.nation_data, "A")
        self.assertNotIn("A", self.game.nation_data.get("WAR_PRE_MAPS", {}))

    def test_but_not_while_one_is_still_running(self):
        self.snapshot("A")
        self.game.set_war("A", "B")
        war_actions.clear_own_pre_war_map_if_peace(self.game.nation_data, "A")
        self.assertIn("A", self.game.nation_data.get("WAR_PRE_MAPS", {}))

    def test_a_member_walking_out_mid_war_takes_its_borders_with_it(self):
        """A separate peace is a nation leaving its faction, and the faction's
        snapshot was the only record of where its borders had been. Deleting its
        share on the way out left the pre-war owner to be guessed from cores at
        the exact moment a treaty needed to know it."""
        from data import queries
        from map_logic.diplomacy import faction_actions

        self.game.set_faction("The Pact", "B", "A")
        self.game.set_war("A", "B2" if "B2" in self.game.nation_data else "B")
        queries.save_faction_pre_war_map("The Pact", self.game.map_data,
                                         self.game.nation_data)

        faction_actions.leave_faction(self.game.nation_data, "A")

        kept = self.game.nation_data.get("WAR_PRE_MAPS", {}).get("A")
        self.assertTrue(kept, "the leaver kept no record of its own borders")
        self.assertIn(str(self.prov["id"]), kept)
        self.assertTrue(all(owner == "A" for owner in kept.values()),
                        "it should carry out its own tiles and nobody else's")


if __name__ == "__main__":
    unittest.main()
