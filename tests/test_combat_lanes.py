"""The lane model: a tile is a container that splits into duels.

The rule, from the request that specified it:

    Instead of all units on a tile rolling attacks against one another in a big
    formulaic pot, the tile acts as a container that dynamically creates lanes
    between specific factions based on their diplomatic relationships. The
    global tile combat width is distributed among active lanes. Damage dealt by
    A in lane 1 strictly applies to X; B in lane 2 takes zero. Only so many
    units can enter a lane at a time; the rest wait in reserve until active
    units shatter or retreat.

Three fixtures were given with it, and the first three tests here are those
fixtures. They are also what rules the pairwise model out: pairing every hostile
nation reproduces the free-for-all but gives the alliance case four duels rather
than two, because in a real alliance war A is at war with both X and Y.

tests/test_multiparty_combat.py holds the damage arithmetic and the bystander
rules; this file is the spec for lane construction, width, reserves and
determinism.
"""

import os
import sys
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import data.constants as c
from map_logic.turn_processing import combat_processor, combat_rules

from tests.test_multiparty_combat import StubMapScreen, damage_taken, unit


def tile(screen, troops, owner=None):
    """One province holding everyone, in the order the nations were listed."""
    everyone = [u for side in troops.values() for u in side]
    return screen.add_province("p1", owner or next(iter(troops)), units=everyone)


def pairs_of(battle):
    return [frozenset((lane.a.nation, lane.b.nation)) for lane in battle.lanes]


def side_for(battle, nation):
    """The first LaneSide `nation` holds anywhere in this battle."""
    for lane in battle.lanes:
        for side in (lane.a, lane.b):
            if side.nation == nation:
                return side
    return None


def alliance_tile(per_nation=8):
    """A and B allied against X and Y allied, everyone at war across the divide."""
    screen = StubMapScreen()
    for name, allies in (("A", ["B"]), ("B", ["A"]), ("X", ["Y"]), ("Y", ["X"])):
        enemies = ["X", "Y"] if name in ("A", "B") else ["A", "B"]
        screen.add_nation(name, at_war_with=enemies)
        screen.nation_data[name]["allied_with"] = allies

    troops = {n: [unit(n, attack=10) for _ in range(per_nation)]
              for n in ("A", "B", "X", "Y")}
    return screen, tile(screen, troops), troops


def free_for_all_tile(per_nation=8):
    """A, B and C mutually hostile: the triangular front."""
    screen = StubMapScreen()
    for name in ("A", "B", "C"):
        screen.add_nation(name, at_war_with=[n for n in ("A", "B", "C") if n != name])

    troops = {n: [unit(n, attack=10) for _ in range(per_nation)] for n in ("A", "B", "C")}
    return screen, tile(screen, troops), troops


class TheFixturesFromTheRequestTests(unittest.TestCase):
    def test_two_allies_against_two_allies_form_two_lanes(self):
        screen, prov, _troops = alliance_tile()

        battle = combat_rules.build_battle([prov["units"]], screen.nation_data)

        self.assertEqual(len(battle.lanes), 2)
        self.assertEqual(set(pairs_of(battle)),
                         {frozenset(("A", "X")), frozenset(("B", "Y"))})
        for lane in battle.lanes:
            self.assertEqual(lane.slots, c.COMBAT_WIDTH // 4)

    def test_the_alliance_case_is_not_four_lanes(self):
        """The regression guard on the coalition rule.

        A is at war with X *and* Y, and B with both as well, so the hostility
        graph has four edges. Pairing on those edges is the obvious
        implementation and it produces a front nobody asked for: four duels of
        half the width, with each ally fighting both enemies at once.
        """
        screen, prov, _troops = alliance_tile()

        battle = combat_rules.build_battle([prov["units"]], screen.nation_data)

        self.assertNotIn(frozenset(("A", "Y")), pairs_of(battle))
        self.assertNotIn(frozenset(("B", "X")), pairs_of(battle))

    def test_three_mutually_hostile_powers_form_a_triangle(self):
        screen, prov, _troops = free_for_all_tile()

        battle = combat_rules.build_battle([prov["units"]], screen.nation_data)

        self.assertEqual(set(pairs_of(battle)),
                         {frozenset(("A", "B")), frozenset(("B", "C")),
                          frozenset(("A", "C"))})
        for lane in battle.lanes:
            self.assertEqual(lane.slots, max(c.MIN_LANE_SLOTS_PER_SIDE,
                                             c.COMBAT_WIDTH // 6))

    def test_coalitions_collapse_to_one_per_nation_when_nobody_is_allied(self):
        screen, _prov, _troops = free_for_all_tile()

        self.assertEqual(combat_rules.coalitions(["A", "B", "C"], screen.nation_data),
                         [["A"], ["B"], ["C"]])


class WidthTests(unittest.TestCase):
    def test_width_is_split_between_lanes(self):
        for lanes, expected in ((1, c.COMBAT_WIDTH // 2), (2, c.COMBAT_WIDTH // 4)):
            self.assertEqual(combat_rules.lane_slots(lanes), expected)

    def test_a_lane_never_falls_below_the_floor(self):
        self.assertEqual(combat_rules.lane_slots(99), c.MIN_LANE_SLOTS_PER_SIDE)

    def test_a_small_ally_is_not_squeezed_out_by_a_large_one(self):
        """The whole point of giving every matchup its own slice of the width.

        Under the pot this replaced, SMALL's two units stood in the same fight
        as BIG's fifty and had the enemy volley divided across all fifty-two
        bodies. Here SMALL gets a lane of its own and fights in it.
        """
        screen = StubMapScreen()
        screen.add_nation("BIG", at_war_with=["X"])
        screen.add_nation("SMALL", at_war_with=["X"])
        screen.add_nation("X", at_war_with=["BIG", "SMALL"])
        screen.nation_data["BIG"]["allied_with"] = ["SMALL"]
        screen.nation_data["SMALL"]["allied_with"] = ["BIG"]

        troops = {"BIG": [unit("BIG", attack=10) for _ in range(50)],
                  "SMALL": [unit("SMALL", attack=10) for _ in range(2)],
                  "X": [unit("X", attack=10) for _ in range(20)]}
        prov = tile(screen, troops, owner="BIG")

        battle = combat_rules.build_battle([prov["units"]], screen.nation_data)
        small = side_for(battle, "SMALL")

        self.assertIsNotNone(small, "the small ally was pushed out of the fight")
        self.assertEqual(len(small.front), len(troops["SMALL"]))
        self.assertGreaterEqual(
            next(lane.slots for lane in battle.lanes
                 if "SMALL" in (lane.a.nation, lane.b.nation)),
            c.MIN_LANE_SLOTS_PER_SIDE)

    def test_one_unit_holds_at_most_one_front_slot(self):
        """Or a nation at war with two powers here fires the same units twice."""
        screen, prov, _troops = free_for_all_tile()

        battle = combat_rules.build_battle([prov["units"]], screen.nation_data)
        seated = [u for lane in battle.lanes
                  for side in (lane.a, lane.b)
                  for u in side.front]

        self.assertEqual(len(seated), len({id(u) for u in seated}))
        self.assertEqual(battle.width, len(seated))

    def test_every_lane_is_covered_before_any_lane_gets_depth(self):
        """Nobody dodges a fight by concentrating everything elsewhere.

        Without this a nation could put its whole army into one duel, leave the
        others with an empty side, and spend the turn untouched by an enemy that
        had committed to fighting it.
        """
        screen, prov, _troops = free_for_all_tile()

        battle = combat_rules.build_battle([prov["units"]], screen.nation_data)

        self.assertEqual(len(battle.lanes), 3)
        for lane in battle.lanes:
            self.assertTrue(lane.a.front and lane.b.front)


class ReserveTests(unittest.TestCase):
    def test_a_reserve_deals_no_damage_and_takes_none(self):
        screen = StubMapScreen()
        screen.add_nation("A", at_war_with=["B"])
        screen.add_nation("B", at_war_with=["A"])

        deep = [unit("A", attack=10) for _ in range(c.LANE_SLOTS_TYPICAL + 5)]
        thin = [unit("B", attack=10)]
        prov = tile(screen, {"A": deep, "B": thin})

        battle = combat_rules.build_battle([prov["units"]], screen.nation_data)
        side = side_for(battle, "A")
        reserve_ids = {id(u) for u in side.reserve}

        self.assertEqual(len(side.front), c.LANE_SLOTS_TYPICAL)
        self.assertEqual(len(side.reserve), 5)

        combat_processor.process_combat(screen)

        # B's whole volley goes to the front rank; the reserve is untouched, and
        # did not add its attack to A's either.
        self.assertEqual(damage_taken([u for u in deep if id(u) in reserve_ids]), 0)
        self.assertAlmostEqual(damage_taken(thin), 10.0 * c.LANE_SLOTS_TYPICAL, places=6)

    def test_depth_no_longer_thins_an_enemy_volley(self):
        """The exploit the lane model closes.

        Damage divides across the front rank, not the stack, so the hundredth
        body behind the line protects nobody. Under the pot, adding bodies was
        the cheapest defensive move in the game.
        """
        def damage_to_front(extra_bodies):
            screen = StubMapScreen()
            screen.add_nation("A", at_war_with=["B"])
            screen.add_nation("B", at_war_with=["A"])
            defenders = [unit("A", attack=0) for _ in range(c.LANE_SLOTS_TYPICAL + extra_bodies)]
            attackers = [unit("B", attack=60)]
            tile(screen, {"A": defenders, "B": attackers})
            combat_processor.process_combat(screen)
            return damage_taken(defenders)

        self.assertAlmostEqual(damage_to_front(0), damage_to_front(40), places=6)

    def test_a_unit_held_back_by_its_commander_stays_out_of_the_front(self):
        screen = StubMapScreen()
        screen.add_nation("A", at_war_with=["B"])
        screen.add_nation("B", at_war_with=["A"])

        held = unit("A", attack=999)
        held["combat_stance"] = "RESERVE"
        squad = [held, unit("A", attack=10)]
        prov = tile(screen, {"A": squad, "B": [unit("B", attack=10)]})

        battle = combat_rules.build_battle([prov["units"]], screen.nation_data)
        side = side_for(battle, "A")

        self.assertEqual([id(u) for u in side.front], [id(squad[1])])
        self.assertEqual([id(u) for u in side.reserve], [id(held)])


class TargetingTests(unittest.TestCase):
    def test_a_unit_pinned_to_a_lane_fights_there(self):
        screen, prov, troops = free_for_all_tile(per_nation=2)

        # Both of A's units are told to face C, which is not where the default
        # priority would have put the first of them.
        for u in troops["A"]:
            u["lane_target"] = "C"

        battle = combat_rules.build_battle([prov["units"]], screen.nation_data)
        against_c = next(lane for lane in battle.lanes
                         if {lane.a.nation, lane.b.nation} == {"A", "C"})
        a_side = against_c.a if against_c.a.nation == "A" else against_c.b

        self.assertEqual(len(a_side.front), 2)

    def test_an_impossible_pin_is_ignored_rather_than_raising(self):
        screen, prov, troops = free_for_all_tile(per_nation=2)
        troops["A"][0]["lane_target"] = "NOBODY_HERE"

        battle = combat_rules.build_battle([prov["units"]], screen.nation_data)

        self.assertIn("A", battle.engaged)
        self.assertIn(id(troops["A"][0]),
                      {id(u) for lane in battle.lanes
                       for side in (lane.a, lane.b) for u in side.front})


class DissolveTests(unittest.TestCase):
    def test_a_lane_dissolves_when_one_side_is_wiped_and_the_others_widen(self):
        """The flanking case from the request, resolved across turns.

        Recomputing the lanes each turn is all this takes: the routed nation is
        no longer present, its duel no longer exists, and the width it was
        holding is redistributed to the duels that remain.
        """
        screen = StubMapScreen()
        for name in ("A", "B", "C"):
            screen.add_nation(name, at_war_with=[n for n in ("A", "B", "C") if n != name])

        troops = {"A": [unit("A", attack=100) for _ in range(6)],
                  "B": [unit("B", attack=10) for _ in range(6)],
                  # Two, so C can turn up to both of its duels and all three
                  # lanes exist before the rout.
                  "C": [unit("C", attack=1, health=1) for _ in range(2)]}
        prov = tile(screen, troops)

        before = combat_rules.build_battle([prov["units"]], screen.nation_data)
        self.assertEqual(len(before.lanes), 3)

        combat_processor.process_combat(screen)

        self.assertEqual([u for u in prov["units"] if u["owner"] == "C"], [],
                         "C was supposed to be routed by this exchange")

        after = combat_rules.build_battle([prov["units"]], screen.nation_data)
        self.assertEqual(len(after.lanes), 1)
        self.assertGreater(after.lanes[0].slots, before.lanes[0].slots)


class DeterminismTests(unittest.TestCase):
    """The same input must resolve the same way, every time and everywhere."""

    def signature(self, battle):
        return [(lane.index, lane.slots, side.nation, [id(u) for u in side.front])
                for lane in battle.lanes for side in (lane.a, lane.b)]

    def test_the_same_fight_resolves_identically_twice(self):
        screen, prov, _troops = free_for_all_tile()

        first = combat_rules.build_battle([prov["units"]], screen.nation_data)
        second = combat_rules.build_battle([prov["units"]], screen.nation_data)

        self.assertEqual(self.signature(first), self.signature(second))

    def test_nation_data_insertion_order_does_not_change_the_answer(self):
        """A save round-trip can reorder nation_data; the fight must not notice."""
        screen, prov, _troops = free_for_all_tile()
        baseline = self.signature(
            combat_rules.build_battle([prov["units"]], screen.nation_data))

        screen.nation_data = {name: screen.nation_data[name]
                              for name in reversed(list(screen.nation_data))}

        self.assertEqual(
            self.signature(combat_rules.build_battle([prov["units"]], screen.nation_data)),
            baseline)


class ChargeProbeTests(unittest.TestCase):
    def test_the_charge_probe_and_the_tile_fight_agree(self):
        """process_pinning predicts the fight process_combat would run.

        The probe used to restate the pooled rule by hand, so tuning either half
        silently desynchronised them. Both now go through build_battle.
        """
        screen = StubMapScreen()
        screen.add_nation("DEF", at_war_with=["ATK"])
        screen.add_nation("ATK", at_war_with=["DEF"])

        garrison = [unit("DEF", attack=50) for _ in range(3)]
        charge = [unit("ATK", attack=5, health=10) for _ in range(2)]

        probe = combat_rules.build_battle([garrison, charge], screen.nation_data)
        predicted = {id(u) for lane in probe.lanes for u in lane.b.front}

        prov = tile(screen, {"DEF": garrison, "ATK": charge})
        fight = combat_rules.build_battle([prov["units"]], screen.nation_data)
        actual = {id(u) for lane in fight.lanes
                  for side in (lane.a, lane.b) if side.nation == "ATK"
                  for u in side.front}

        self.assertEqual(predicted, actual)

    def test_a_charge_deeper_than_the_lane_is_not_annihilated_outright(self):
        """A documented consequence: the surplus is in reserve, out of reach.

        Fifty militia cannot all be shot down in one exchange, so the early
        resolution that used to wipe a doomed charge stops applying once the
        charge is deeper than the lane can seat.
        """
        screen = StubMapScreen()
        screen.add_nation("DEF", at_war_with=["ATK"])
        screen.add_nation("ATK", at_war_with=["DEF"])

        garrison = [unit("DEF", attack=1000) for _ in range(3)]
        charge = [unit("ATK", attack=1, health=1)
                  for _ in range(c.LANE_SLOTS_TYPICAL + 4)]

        home = screen.add_province("p1", "DEF", units=garrison)
        away = screen.add_province("p2", "ATK", units=charge)
        home["neighbors"] = ["p2"]
        away["neighbors"] = ["p1"]
        for u in charge:
            u["order"]["path"] = ["p1"]

        combat_processor.process_pinning(screen)

        self.assertTrue(any(u.get("health", 0) > 0 for u in charge),
                        "a charge deeper than the lane was wiped out in one probe")


class LaneOrderLifetimeTests(unittest.TestCase):
    """lane_target names an enemy on one tile, so it must not outlive the tile."""

    def test_a_lane_pin_is_dropped_when_the_unit_marches_away(self):
        from map_logic.turn_processing import movement_processor

        screen = StubMapScreen()
        screen.add_nation("A", at_war_with=["B"])
        screen.add_nation("B", at_war_with=["A"])

        mover = unit("A", attack=10, path=["p2"])
        mover["lane_target"] = "B"
        home = screen.add_province("p1", "A", units=[mover])
        away = screen.add_province("p2", "A")
        home["neighbors"] = ["p2"]
        away["neighbors"] = ["p1"]
        mover["_current_province_id"] = "p1"

        movement_processor.process_movement(screen)

        self.assertEqual(mover["_current_province_id"], "p2")
        self.assertNotIn("lane_target", mover)


class AiRotationTests(unittest.TestCase):
    def test_the_ai_pulls_a_shot_up_unit_out_when_a_fresh_one_can_take_the_slot(self):
        from map_logic.ai import ai_movement

        screen = StubMapScreen()
        screen.add_nation("A", at_war_with=["B"])
        screen.add_nation("B", at_war_with=["A"])

        hurt = unit("A", attack=10, health=10)
        hurt["max_health"] = 100
        fresh = [unit("A", attack=10, health=100) for _ in range(c.LANE_SLOTS_TYPICAL)]
        for u in fresh:
            u["max_health"] = 100
        prov = tile(screen, {"A": [hurt] + fresh, "B": [unit("B", attack=10)]})

        ai_movement._rotate_damaged_units(screen, "A", {prov["id"]})

        self.assertEqual(hurt.get("combat_stance"), "RESERVE")
        self.assertNotIn(id(hurt),
                         {id(u) for lane in combat_rules.build_battle(
                             [prov["units"]], screen.nation_data).lanes
                          for side in (lane.a, lane.b) for u in side.front})

    def test_a_hurt_unit_holds_its_slot_when_nobody_can_replace_it(self):
        """An empty slot dissolves the lane, which is worse than a hurt unit in it."""
        from map_logic.ai import ai_movement

        screen = StubMapScreen()
        screen.add_nation("A", at_war_with=["B"])
        screen.add_nation("B", at_war_with=["A"])

        hurt = [unit("A", attack=10, health=5) for _ in range(2)]
        for u in hurt:
            u["max_health"] = 100
        prov = tile(screen, {"A": hurt, "B": [unit("B", attack=10)]})

        ai_movement._rotate_damaged_units(screen, "A", {prov["id"]})

        for u in hurt:
            self.assertNotIn("combat_stance", u)


if __name__ == "__main__":
    unittest.main()
