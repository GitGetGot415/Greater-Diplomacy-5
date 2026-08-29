"""How many units the AI puts on one tile, and whether that tracks combat width.

Everything else the AI does already scaled with the width -- what to buy (front
rank x frontline), what a unit is worth (a full front rank of them), how strong
a border is (the front and its relief). ai_movement referenced it nowhere.
Destinations were chosen purely by "fewest units assigned", so stacks landed at
total_units / targets: at width 2 it kept five on a tile where three could not
fire, and at width 10 it kept trickling one at a time and never massed.

Under the lane model the answer is per tile, not global: how many front slots a
nation gets there depends on how many ways that fight splits, so the tests pass
a capacity dict rather than patching a constant. A tile is worth filling to a
front rank AND the relief rank behind it -- bodies past that cannot reach a slot
before the tile resolves, and under lanes they absorb nothing while they wait.

Every test here supplies the number rather than assuming one, because "the
number is read" is the actual property -- a suite that hardcoded 5 would pass
just as well against a hardcoded 5 in the source.
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
    """Fixtures state a tile's front slots; saturation follows at front x depth."""

    def capacity_for(self, tiles, slots):
        return {tile: slots for tile in tiles}

    def saturates_at(self, slots):
        """The stack size at which a tile stops wanting another body."""
        return slots * c.AI_RESERVE_DEPTH


class TilePressureTests(WidthTestCase):
    """The one function in ai_movement that reads the width."""

    def pressure(self, stack, weight=0, tile=1, slots=5):
        return ai_movement._tile_pressure({tile: weight}, {tile: stack}, tile,
                                          {tile: slots})

    def test_a_tile_with_room_sorts_ahead_of_a_full_one(self):
        full = self.saturates_at(5)
        self.assertLess(self.pressure(stack=full - 1), self.pressure(stack=full))

    def test_a_full_tile_loses_however_much_the_weights_want_it(self):
        """A battle pulls at -AI_REINFORCE_COMBAT_WEIGHT. Once the tile holds a
        front and its relief that pull is buying nothing: the next body cannot
        reach a slot before the tile resolves, and absorbs nothing waiting."""
        cap = {1: 5, 2: 5}
        full_battle = ai_movement._tile_pressure(
            {1: -c.AI_REINFORCE_COMBAT_WEIGHT}, {1: self.saturates_at(5)}, 1, cap)
        empty_border = ai_movement._tile_pressure({2: 0}, {2: 0}, 2, cap)
        self.assertLess(empty_border, full_battle)

    def test_below_the_cap_the_weights_still_decide(self):
        """The saturation tier is added in front of the old ordering, not
        instead of it, so a battle still outranks a quiet border."""
        cap = {1: 5, 2: 5}
        battle = ai_movement._tile_pressure({1: -c.AI_REINFORCE_COMBAT_WEIGHT}, {1: 3}, 1, cap)
        border = ai_movement._tile_pressure({2: 0}, {2: 0}, 2, cap)
        self.assertLess(battle, border)

    def test_the_cap_moves_with_the_tile_s_own_slots(self):
        """A tile whose fight splits three ways seats fewer of ours than one
        where we face a single enemy, and saturates that much sooner."""
        for slots in (2, 5, 10):
            with self.subTest(slots=slots):
                full = self.saturates_at(slots)
                self.assertEqual(self.pressure(stack=full - 1, slots=slots)[0], 0)
                self.assertEqual(self.pressure(stack=full, slots=slots)[0], 1)

    def test_an_unmeasured_tile_falls_back_to_a_typical_lane(self):
        """A quiet border has no fight to measure, so it is worth the fight that
        would open there if one started."""
        typical = c.LANE_SLOTS_TYPICAL * c.AI_RESERVE_DEPTH
        self.assertEqual(ai_movement._tile_pressure({}, {99: typical - 1}, 99)[0], 0)
        self.assertEqual(ai_movement._tile_pressure({}, {99: typical}, 99)[0], 1)

    def test_a_tile_nobody_has_counted_is_empty_not_full(self):
        self.assertEqual(ai_movement._tile_pressure({}, {}, 99)[0], 0)


class BuilderTests(WidthTestCase):
    """The stack counts have to be a true headcount, apart from the weights."""

    def build(self, units_info, active_battles=(), capacity=None, **borders):
        empty = {"peace_borders": set(), "coastal_borders": set(), "war_borders": set(),
                 "unclaimed_targets": set(), "all_unclaimed_coasts": set(),
                 "enemy_targets": set(), "all_enemy_coasts": set(),
                 "enemy_coastal_waters": set(), "expedition_targets": set()}
        empty.update(borders)
        return ai_movement._build_target_assignments(
            units_info, empty,
            {"active_battles": set(active_battles), "friendly_convoys": set(),
             "convoy_in_combat": set(), "convoy_near_ship": set(), "convoy_near_coast": set()},
            at_war=True, capacity=capacity)

    def test_the_headcount_is_free_of_the_weights(self):
        """A quiet border with one guard carries +AI_REAR_GUARD_PENALTY, which
        would read as a stack of 51 if the two numbers shared a dict."""
        prov = {"id": 1}
        built = self.build([({}, prov)], peace_borders={1}, coastal_borders=set())
        self.assertEqual(built["target_stacks"][1], 1)
        self.assertGreaterEqual(built["target_assignments"][1], c.AI_REAR_GUARD_PENALTY)

    def pull_on_battle(self, units_present, slots):
        """How badly a battle tile holding `units_present` wants one more."""
        prov = {"id": 1}
        built = self.build([({}, prov)] * units_present, active_battles={1},
                           capacity={1: slots})
        return built["target_assignments"][1]

    def test_an_empty_front_pulls_as_hard_as_it_ever_did(self):
        """The scaling changes how the pull fades, not how strong it starts."""
        self.assertAlmostEqual(self.pull_on_battle(0, 5), -c.AI_REINFORCE_COMBAT_WEIGHT)

    def test_the_pull_fades_as_the_front_fills(self):
        self.assertLess(self.pull_on_battle(1, 5), self.pull_on_battle(4, 5))

    def test_a_wider_front_keeps_asking_for_men_a_narrow_one_would_not(self):
        """The other half of the user's question. Same board, same four men
        standing there: with five slots the tile has nearly stopped competing,
        with ten it is still calling for the rest of a front."""
        self.assertLess(self.pull_on_battle(4, 10), self.pull_on_battle(4, 5))

    def test_a_full_front_and_relief_stops_asking(self):
        self.assertGreaterEqual(self.pull_on_battle(int(self.saturates_at(5)), 5), 0)

    def test_an_overfull_line_is_not_penalised_twice(self):
        """Past the cap the pull is clamped off rather than turning into a
        second, unbounded push. _tile_pressure already sorts a full tile last;
        letting the pull go negative as well would make an over-stacked battle
        repel harder the more men were on it, which is a retreat, not a rule
        about firing lines."""
        full = int(self.saturates_at(5))
        exact = self.pull_on_battle(full, 5)
        over = self.pull_on_battle(full + 2, 5)
        self.assertEqual(over - exact, 2, "only the two extra bodies should count")

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

    def route(self, stack_on_2, weight_on_2, stack_on_3=0, slots=5):
        provinces = {
            1: {"id": 1, "neighbors": [2, 3], "owner": "Avaria"},
            2: {"id": 2, "neighbors": [1], "owner": "Avaria"},
            3: {"id": 3, "neighbors": [1], "owner": "Avaria"},
        }
        return ai_movement._bfs_nearest_target(
            1, {2, 3}, {1, 2, 3}, provinces,
            target_assignments={2: weight_on_2, 3: 0},
            target_stacks={2: stack_on_2, 3: stack_on_3},
            target_capacity={2: slots, 3: slots},
            water_ids=set(),
            neighbor_ids={1: [2, 3], 2: [1], 3: [1]})

    def test_a_wanted_tile_wins_while_it_has_room(self):
        self.assertEqual(self.route(stack_on_2=self.saturates_at(5) - 1, weight_on_2=-20), [2])

    def test_the_same_tile_loses_once_it_is_full(self):
        self.assertEqual(self.route(stack_on_2=self.saturates_at(5), weight_on_2=-20), [3])

    def test_more_slots_keeps_feeding_the_same_tile(self):
        """The user's question in one assertion: a wider front means a bigger
        stack, from the identical board."""
        self.assertEqual(
            self.route(stack_on_2=self.saturates_at(5), weight_on_2=-20, slots=10), [2])

    def test_fewer_slots_spreads_them_out_sooner(self):
        self.assertEqual(
            self.route(stack_on_2=self.saturates_at(2), weight_on_2=-20, slots=2), [3])

    def test_when_everything_is_full_the_old_ordering_still_applies(self):
        """Nobody stands still because every tile is crowded -- the tier ranks
        full against not-full, and among equals the weights decide as before."""
        full = self.saturates_at(5)
        self.assertEqual(
            self.route(stack_on_2=full + 4, weight_on_2=-20, stack_on_3=full + 1), [2])

    def test_a_full_tile_still_loses_to_a_tile_with_one_slot_left(self):
        full = self.saturates_at(5)
        self.assertEqual(
            self.route(stack_on_2=full + 4, weight_on_2=-20, stack_on_3=full - 1), [3])

    def test_a_midpoint_battle_blocks_paths_that_would_cross_it(self):
        provinces = {
            1: {"id": 1, "neighbors": [2], "owner": "Avaria"},
            2: {"id": 2, "neighbors": [1, 3], "owner": "Bruland"},
            3: {"id": 3, "neighbors": [2], "owner": "Bruland"},
        }
        path = ai_movement._bfs_nearest_target(
            1, {3}, {1, 2, 3}, provinces, target_assignments={3: 0},
            target_stacks={3: 0}, target_capacity={3: 5}, water_ids=set(),
            neighbor_ids={1: [2], 2: [1, 3], 3: [2]},
            blocked_edges={(1, 2)}, reinforce_edges=set())

        self.assertEqual(path, [])

    def test_a_reinforcement_path_can_end_at_the_far_edge_endpoint(self):
        provinces = {
            1: {"id": 1, "neighbors": [2], "owner": "Avaria"},
            2: {"id": 2, "neighbors": [1, 3], "owner": "Bruland"},
            3: {"id": 3, "neighbors": [2], "owner": "Bruland"},
        }
        path = ai_movement._bfs_nearest_target(
            1, {2}, {1, 2, 3}, provinces, target_assignments={2: -20},
            target_stacks={2: 0}, target_capacity={2: 5}, water_ids=set(),
            neighbor_ids={1: [2], 2: [1, 3], 3: [2]},
            blocked_edges={(1, 2)}, reinforce_edges={(1, 2)})

        self.assertEqual(path, [2])


class CapacityIsRoomNotGarrisonTests(unittest.TestCase):
    """Where the capacity dict every test above supplies actually comes from.

    Those fixtures hand the number in deliberately -- the property under test is
    "the width is read", not what it happens to be. Nothing therefore exercised
    combat_rules.nation_front_capacity as the *producer*, and it was answering a
    different question from the one _tile_depth asks: how many slots we were
    given, which _caps bounds by the units already standing there. A lone
    defender's tile reported one slot, saturated at two, and sorted behind a
    quiet border worth twelve -- saves/THEYRE NOT PUTTING IN THEIR RESERVES.
    """

    def tile(self, mine, theirs):
        from tests.test_multiparty_combat import StubMapScreen, unit
        screen = StubMapScreen()
        screen.add_nation("A", at_war_with=["B"])
        screen.add_nation("B", at_war_with=["A"])
        units = [unit("A", attack=10) for _ in range(mine)]
        units += [unit("B", attack=10) for _ in range(theirs)]
        return screen, screen.add_province("p1", "A", units=units)

    def capacity(self, mine, theirs):
        from map_logic.turn_processing import combat_rules
        screen, prov = self.tile(mine, theirs)
        return combat_rules.nation_front_capacity("A", prov, screen.nation_data)

    def test_a_lone_defender_is_told_the_whole_lane_is_open_to_it(self):
        self.assertEqual(self.capacity(1, 8), c.LANE_SLOTS_TYPICAL)

    def test_the_answer_does_not_depend_on_how_many_we_brought(self):
        """The bug in one assertion: capacity used to track the garrison."""
        self.assertEqual({self.capacity(n, 8) for n in (1, 2, 3, 6, 7)},
                         {c.LANE_SLOTS_TYPICAL})

    def test_a_battle_tile_is_not_saturated_by_its_own_garrison(self):
        """_tile_depth is capacity x AI_RESERVE_DEPTH, and a one-man tile used
        to saturate at two -- so one reserve joined and the rest walked away."""
        depth = ai_movement._tile_depth({1: self.capacity(1, 8)}, 1)
        self.assertGreater(depth, 2)
        self.assertEqual(depth, c.LANE_SLOTS_TYPICAL * c.AI_RESERVE_DEPTH)

    def test_allies_already_holding_the_line_still_take_their_share(self):
        """Raising our demand must not take width off an ally who has bodies
        for it -- share_slots is still the thing dividing the lane."""
        from tests.test_multiparty_combat import StubMapScreen, unit
        from map_logic.turn_processing import combat_rules

        screen = StubMapScreen()
        screen.add_nation("A", at_war_with=["B"])
        screen.add_nation("ALLY", at_war_with=["B"])
        screen.add_nation("B", at_war_with=["A", "ALLY"])
        screen.nation_data["A"]["allied_with"] = ["ALLY"]
        screen.nation_data["ALLY"]["allied_with"] = ["A"]

        units = [unit("A", attack=10)]
        units += [unit("ALLY", attack=10) for _ in range(5)]
        units += [unit("B", attack=10) for _ in range(6)]
        prov = screen.add_province("p1", "A", units=units)

        self.assertLess(
            combat_rules.nation_front_capacity("A", prov, screen.nation_data),
            c.LANE_SLOTS_TYPICAL)


class ReserveFlowTests(unittest.TestCase):
    """The whole pipeline, on the board from the save that reported it.

    Province 1 is a contested frontier, province 2 is the rear holding eight
    reserves, province 6 is an enemy tile the rear also borders. Every test
    above works on one function; this one asks what the AI actually does, which
    is the thing that was wrong: with capacity tracking the garrison, exactly as
    many reserves marched to the fight as were already in it, and the remainder
    walked off to province 6 while the line held at one man.
    """

    def unit(self, owner):
        return {"owner": owner, "type": "Infantry", "attack": 10, "health": 100,
                "max_health": 100, "defense": 5, "speed": 1,
                "order": {"type": "MOVE", "path": []}}

    def board(self, defenders, reserves=8, attackers=8):
        from tests.test_multiparty_combat import StubMapScreen

        screen = StubMapScreen()
        for name, foe in (("A", "E"), ("E", "A")):
            screen.add_nation(name, at_war_with=[foe])
            screen.nation_data[name]["is_playable"] = True
        screen.player_country = "HUMAN"
        screen.active_players = ["HUMAN"]
        screen.scenario_settings = {}

        front = screen.add_province(1, "A",
                                    units=[self.unit("A") for _ in range(defenders)]
                                    + [self.unit("E") for _ in range(attackers)])
        rear = screen.add_province(2, "A",
                                   units=[self.unit("A") for _ in range(reserves)])
        enemy = screen.add_province(6, "E")
        front["neighbors"], rear["neighbors"], enemy["neighbors"] = [2], [1, 6], [2]
        return screen, rear

    def marching_to(self, rear, tile):
        return sum(1 for u in rear["units"]
                   if ((u.get("order") or {}).get("path") or [None])[0] == tile)

    def orders_for(self, defenders):
        screen, rear = self.board(defenders)
        ai_movement._generate_unit_orders(screen)
        return rear

    def test_a_thin_line_pulls_the_whole_reserve_in(self):
        """One man holding a tile against eight used to draw exactly one."""
        for defenders in (1, 2, 3):
            with self.subTest(defenders=defenders):
                rear = self.orders_for(defenders)
                self.assertEqual(self.marching_to(rear, 1), 8)
                self.assertEqual(self.marching_to(rear, 6), 0)

    def test_the_pull_fades_as_the_tile_fills(self):
        """Not a cliff -- the weight scales with the share of the tile still
        empty, so the reserve is split against the other things wanting it."""
        thin = self.marching_to(self.orders_for(1), 1)
        half = self.marching_to(self.orders_for(c.LANE_SLOTS_TYPICAL), 1)
        self.assertGreater(thin, half)
        self.assertGreater(half, 0)

    def test_a_full_front_and_relief_pulls_nobody(self):
        """The cap is the point of the whole mechanism -- bodies past the relief
        rank absorb nothing at all while they wait, so they go somewhere useful."""
        rear = self.orders_for(int(c.LANE_SLOTS_TYPICAL * c.AI_RESERVE_DEPTH))
        self.assertEqual(self.marching_to(rear, 1), 0)
        self.assertEqual(self.marching_to(rear, 6), 8)


class NavalTests(WidthTestCase):
    def test_ships_saturate_on_the_same_rule(self):
        """Naval stacks fight in lanes too, and used to be balanced by the same
        blind count."""
        cap = {1: 3, 2: 3}
        full = ai_movement._tile_pressure(
            {1: -c.AI_CONVOY_ESCORT_WEIGHT}, {1: self.saturates_at(3)}, 1, cap)
        empty = ai_movement._tile_pressure({2: 0}, {2: 0}, 2, cap)
        self.assertLess(empty, full)


if __name__ == "__main__":
    unittest.main()
