"""How many units the AI puts on one tile, and whether that tracks combat width.

Everything else the AI does already scaled with MAX_COMBAT_ATTACKERS -- what to
buy (width x frontline), what a unit is worth (a full firing line of them), how
strong a border is (the top width per tile). ai_movement referenced it nowhere.
Destinations were chosen purely by "fewest units assigned", so stacks landed at
total_units / targets: at width 2 it kept five on a tile where three could not
fire, and at width 10 it kept trickling one at a time and never massed.

Every test here patches the width rather than assuming 5, because "the number
is read" is the actual property -- a suite that hardcoded 5 would pass just as
well against a hardcoded 5 in the source.
"""

import os
import sys
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import data.constants as c
from map_logic.ai import ai_movement


class WidthTestCase(unittest.TestCase):
    def set_width(self, width):
        original = c.MAX_COMBAT_ATTACKERS
        c.MAX_COMBAT_ATTACKERS = width
        self.addCleanup(lambda: setattr(c, "MAX_COMBAT_ATTACKERS", original))


class TilePressureTests(WidthTestCase):
    """The one function in ai_movement that reads the width."""

    def pressure(self, stack, weight=0, tile=1):
        return ai_movement._tile_pressure({tile: weight}, {tile: stack}, tile)

    def test_a_tile_with_room_sorts_ahead_of_a_full_one(self):
        self.set_width(5)
        self.assertLess(self.pressure(stack=4), self.pressure(stack=5))

    def test_a_full_tile_loses_however_much_the_weights_want_it(self):
        """A battle pulls at -AI_REINFORCE_COMBAT_WEIGHT. Once the tile is full
        that pull is buying nothing, because the sixth body cannot fire."""
        self.set_width(5)
        full_battle = ai_movement._tile_pressure({1: -c.AI_REINFORCE_COMBAT_WEIGHT}, {1: 5}, 1)
        empty_border = ai_movement._tile_pressure({2: 0}, {2: 0}, 2)
        self.assertLess(empty_border, full_battle)

    def test_below_the_cap_the_weights_still_decide(self):
        """The saturation tier is added in front of the old ordering, not
        instead of it, so a battle still outranks a quiet border."""
        self.set_width(5)
        battle = ai_movement._tile_pressure({1: -c.AI_REINFORCE_COMBAT_WEIGHT}, {1: 3}, 1)
        border = ai_movement._tile_pressure({2: 0}, {2: 0}, 2)
        self.assertLess(battle, border)

    def test_the_cap_moves_with_the_constant(self):
        for width in (2, 5, 10):
            with self.subTest(width=width):
                self.set_width(width)
                self.assertEqual(self.pressure(stack=width - 1)[0], 0)
                self.assertEqual(self.pressure(stack=width)[0], 1)

    def test_a_tile_nobody_has_counted_is_empty_not_full(self):
        self.set_width(5)
        self.assertEqual(ai_movement._tile_pressure({}, {}, 99)[0], 0)


class BuilderTests(WidthTestCase):
    """The stack counts have to be a true headcount, apart from the weights."""

    def build(self, units_info, active_battles=(), **borders):
        empty = {"peace_borders": set(), "coastal_borders": set(), "war_borders": set(),
                 "unclaimed_targets": set(), "all_unclaimed_coasts": set(),
                 "enemy_targets": set(), "all_enemy_coasts": set(),
                 "enemy_coastal_waters": set(), "expedition_targets": set()}
        empty.update(borders)
        return ai_movement._build_target_assignments(
            units_info, empty,
            {"active_battles": set(active_battles), "friendly_convoys": set(),
             "convoy_in_combat": set(), "convoy_near_ship": set(), "convoy_near_coast": set()},
            at_war=True)

    def test_the_headcount_is_free_of_the_weights(self):
        """A quiet border with one guard carries +AI_REAR_GUARD_PENALTY, which
        would read as a stack of 51 if the two numbers shared a dict."""
        prov = {"id": 1}
        built = self.build([({}, prov)], peace_borders={1}, coastal_borders=set())
        self.assertEqual(built["target_stacks"][1], 1)
        self.assertGreaterEqual(built["target_assignments"][1], c.AI_REAR_GUARD_PENALTY)

    def pull_on_battle(self, units_present, width):
        """How badly a battle tile holding `units_present` wants one more."""
        self.set_width(width)
        prov = {"id": 1}
        built = self.build([({}, prov)] * units_present, active_battles={1})
        return built["target_assignments"][1]

    def test_an_empty_front_pulls_as_hard_as_it_ever_did(self):
        """The scaling changes how the pull fades, not how strong it starts."""
        self.assertAlmostEqual(self.pull_on_battle(0, 5), -c.AI_REINFORCE_COMBAT_WEIGHT)

    def test_the_pull_fades_as_the_firing_line_fills(self):
        self.assertLess(self.pull_on_battle(1, 5), self.pull_on_battle(4, 5))

    def test_a_wider_front_keeps_asking_for_men_a_narrow_one_would_not(self):
        """The other half of the user's question. Same board, same four men
        standing there: at width 5 the tile has nearly stopped competing, at
        width 10 it is still calling for the rest of a firing line."""
        self.assertLess(self.pull_on_battle(4, 10), self.pull_on_battle(4, 5))

    def test_a_full_line_stops_asking(self):
        self.assertGreaterEqual(self.pull_on_battle(5, 5), 0)

    def test_an_overfull_line_is_not_penalised_twice(self):
        """Past the cap the pull is clamped off rather than turning into a
        second, unbounded push. _tile_pressure already sorts a full tile last;
        letting the pull go negative as well would make an over-stacked battle
        repel harder the more men were on it, which is a retreat, not a rule
        about firing lines."""
        five = self.pull_on_battle(5, 5)
        seven = self.pull_on_battle(7, 5)
        self.assertEqual(seven - five, 2, "only the two extra bodies should count")

    def test_a_battle_tile_counts_its_bodies_not_its_pull(self):
        """The battle bias is subtracted before the units are counted, so a
        headcount that shared the weighted dict would come out negative -- and
        a tile at -18 reads as nowhere near full however many are standing on it.
        """
        prov = {"id": 1}
        built = self.build([({}, prov), ({}, prov)], active_battles={1})
        self.assertEqual(built["target_stacks"][1], 2)
        self.assertLess(built["target_assignments"][1], 0,
                        "fixture is not exercising the bias it exists to test")


class RoutingTests(WidthTestCase):
    """Where a unit is actually sent, through the real pathfinder.

    Two reachable destinations one step away: tile 2 already holds a stack,
    tile 3 is empty but far less wanted. Which one wins is exactly the
    behaviour under test.
    """

    def route(self, stack_on_2, weight_on_2, stack_on_3=0):
        provinces = {
            1: {"id": 1, "neighbors": [2, 3], "owner": "Avaria"},
            2: {"id": 2, "neighbors": [1], "owner": "Avaria"},
            3: {"id": 3, "neighbors": [1], "owner": "Avaria"},
        }
        return ai_movement._bfs_nearest_target(
            1, {2, 3}, {1, 2, 3}, provinces,
            target_assignments={2: weight_on_2, 3: 0},
            target_stacks={2: stack_on_2, 3: stack_on_3},
            water_ids=set(),
            neighbor_ids={1: [2, 3], 2: [1], 3: [1]})

    def test_a_wanted_tile_wins_while_it_has_room(self):
        self.set_width(5)
        self.assertEqual(self.route(stack_on_2=4, weight_on_2=-20), [2])

    def test_the_same_tile_loses_once_it_is_full(self):
        self.set_width(5)
        self.assertEqual(self.route(stack_on_2=5, weight_on_2=-20), [3])

    def test_raising_the_width_keeps_feeding_the_same_tile(self):
        """The user's question in one assertion: a wider front means a bigger
        stack, from the identical board."""
        self.set_width(10)
        self.assertEqual(self.route(stack_on_2=5, weight_on_2=-20), [2])

    def test_lowering_the_width_spreads_them_out_sooner(self):
        self.set_width(2)
        self.assertEqual(self.route(stack_on_2=2, weight_on_2=-20), [3])

    def test_when_everything_is_full_the_old_ordering_still_applies(self):
        """Nobody stands still because every tile is crowded -- the tier ranks
        full against not-full, and among equals the weights decide as before."""
        self.set_width(5)
        self.assertEqual(self.route(stack_on_2=9, weight_on_2=-20, stack_on_3=6), [2])

    def test_a_full_tile_still_loses_to_a_tile_with_one_slot_left(self):
        self.set_width(5)
        self.assertEqual(self.route(stack_on_2=9, weight_on_2=-20, stack_on_3=4), [3])


class NavalTests(WidthTestCase):
    def test_ships_saturate_on_the_same_rule(self):
        """Naval stacks fight by the same combat width, and used to be balanced
        by the same blind count."""
        self.set_width(3)
        full = ai_movement._tile_pressure({1: -c.AI_CONVOY_ESCORT_WEIGHT}, {1: 3}, 1)
        empty = ai_movement._tile_pressure({2: 0}, {2: 0}, 2)
        self.assertLess(empty, full)


if __name__ == "__main__":
    unittest.main()
