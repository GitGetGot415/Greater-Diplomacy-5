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
fixtures. They are also what rules two simpler models out. Pairing every hostile
nation gives the alliance case four duels of quarter width, because in a real
alliance war A is at war with both X and Y. Pairing the allies off one-to-one
instead gives two, but then A can never touch Y even though both are standing
here at war -- the "strange how that works" save, where Germany and the United
Kingdom shared a province and fought different people. A lane is between two
SIDES, and every hostile pair on the tile is inside one.

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
    """Every nation pair that shares a lane -- who can actually shoot whom."""
    return [frozenset((mine, theirs)) for lane in battle.lanes
            for mine in lane.a.nations for theirs in lane.b.nations]


def sides_of(battle):
    return [(frozenset(lane.a.nations), frozenset(lane.b.nations))
            for lane in battle.lanes]


def side_for(battle, nation):
    """The first LaneSide `nation` fights on anywhere in this battle."""
    for lane in battle.lanes:
        for side in (lane.a, lane.b):
            if nation in side.nations:
                return side
    return None


def member_for(battle, nation):
    """`nation`'s own half of the first side it fights on: its slots and units."""
    side = side_for(battle, nation)
    if side is None:
        return None
    return next(m for m in side.members if m.nation == nation)


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
    def test_two_allies_against_two_allies_form_one_lane(self):
        screen, prov, _troops = alliance_tile()

        battle = combat_rules.build_battle([prov["units"]], screen.nation_data)

        self.assertEqual(len(battle.lanes), 1)
        self.assertEqual(sides_of(battle), [(frozenset(("A", "B")), frozenset(("X", "Y")))])
        self.assertEqual(battle.lanes[0].slots, c.COMBAT_WIDTH // 2)

    def test_everyone_at_war_here_is_in_the_lane_together(self):
        """The regression guard, and the bug from 'strange how that works'.

        Two earlier models both failed this. Pairing on the four hostility edges
        gives four duels of quarter width. Pairing the coalitions off member to
        member gives two, but leaves A unable to touch Y and B unable to touch X
        while all four stand on the same tile at war -- which is how Germany and
        the United Kingdom shared province 640 and fought different people.
        """
        screen, prov, _troops = alliance_tile()

        battle = combat_rules.build_battle([prov["units"]], screen.nation_data)

        self.assertEqual(set(pairs_of(battle)),
                         {frozenset(("A", "X")), frozenset(("A", "Y")),
                          frozenset(("B", "X")), frozenset(("B", "Y"))})

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

    def test_allies_share_the_width_they_can_use(self):
        """Nine units and one should field six, not four.

        Splitting a side's allowance evenly is the obvious rule and it wastes
        the half the small ally has no bodies for. share_slots hands the
        leftovers back, so the width ends up where the troops are.
        """
        self.assertEqual(combat_rules.share_slots([9, 1], 6), [5, 1])

    def test_an_ally_can_never_be_pushed_below_an_even_split(self):
        """The other half of the same rule, and the reason it is max-min fair.

        However many units the big ally brings, it cannot take more than its
        even share off one that can use it. Six slots between two nations that
        both want five is three each -- the 50/50 point -- and fifty units on
        one side does not move it.
        """
        self.assertEqual(combat_rules.share_slots([5, 5], 6), [3, 3])
        self.assertEqual(combat_rules.share_slots([50, 5], 6), [3, 3])

    def test_every_ally_present_gets_into_the_fight(self):
        """Four allies and two slots: the floor gives way, not the ally.

        The same call MIN_LANE_SLOTS_PER_SIDE makes one level up. A nation that
        marched here and is standing in the battle is in the battle, even when
        that means the side fields more than its allowance.
        """
        self.assertEqual(combat_rules.share_slots([9, 1, 1, 1], 2), [1, 1, 1, 1])

    def test_a_small_ally_is_not_squeezed_out_by_a_large_one(self):
        """The whole point of sharing rather than halving.

        Under the pot this replaced, SMALL's two units stood in the same fight
        as BIG's fifty and had the enemy volley divided across all fifty-two
        bodies. Here SMALL holds its own slots on the shared front.
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
        small = member_for(battle, "SMALL")
        big = member_for(battle, "BIG")

        self.assertIsNotNone(small, "the small ally was pushed out of the fight")
        self.assertEqual(len(small.front), len(troops["SMALL"]))
        # Sharing, not halving: BIG takes the width SMALL has no bodies for,
        # rather than the two of them cutting the side in half and BIG fielding
        # three while SMALL wastes one.
        self.assertEqual(small.slots + big.slots, battle.lanes[0].slots)
        self.assertGreater(big.slots, small.slots)

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
                         if {*lane.a.nations, *lane.b.nations} == {"A", "C"})
        a_side = against_c.a if "A" in against_c.a.nations else against_c.b

        self.assertEqual(len(a_side.front), 2)

    def test_an_impossible_pin_is_ignored_rather_than_raising(self):
        screen, prov, troops = free_for_all_tile(per_nation=2)
        troops["A"][0]["lane_target"] = "NOBODY_HERE"

        battle = combat_rules.build_battle([prov["units"]], screen.nation_data)

        self.assertIn("A", battle.engaged)
        self.assertIn(id(troops["A"][0]),
                      {id(u) for lane in battle.lanes
                       for side in (lane.a, lane.b) for u in side.front})


class CoalitionTests(unittest.TestCase):
    """A side is a coalition, and a coalition is not a merged war list."""

    def half_committed_tile(self):
        """ALLY stands with BIG but never joined the war against SMALLFOE."""
        screen = StubMapScreen()
        screen.add_nation("BIG", at_war_with=["FOE", "SMALLFOE"])
        screen.add_nation("ALLY", at_war_with=["FOE"])
        screen.add_nation("FOE", at_war_with=["BIG", "ALLY"])
        screen.add_nation("SMALLFOE", at_war_with=["BIG"])
        screen.nation_data["BIG"]["allied_with"] = ["ALLY"]
        screen.nation_data["ALLY"]["allied_with"] = ["BIG"]
        screen.nation_data["FOE"]["allied_with"] = ["SMALLFOE"]
        screen.nation_data["SMALLFOE"]["allied_with"] = ["FOE"]

        troops = {n: [unit(n, attack=10) for _ in range(3)]
                  for n in ("BIG", "ALLY", "FOE", "SMALLFOE")}
        return screen, tile(screen, troops, owner="BIG"), troops

    def test_a_member_never_shoots_somebody_it_is_at_peace_with(self):
        """Standing beside an ally does not enlist you in that ally's wars."""
        screen, prov, troops = self.half_committed_tile()

        battle = combat_rules.build_battle([prov["units"]], screen.nation_data)
        ally = member_for(battle, "ALLY")
        untouchable = {id(u) for u in troops["SMALLFOE"]}

        self.assertTrue(ally.targets)
        self.assertFalse(untouchable & {id(u) for u in ally.targets})

    def test_and_takes_no_fire_from_them_either(self):
        screen, _prov, troops = self.half_committed_tile()

        for u in troops["BIG"] + troops["FOE"]:
            u["attack"] = 0
        combat_processor.process_combat(screen)

        self.assertEqual(damage_taken(troops["ALLY"]), 0)

    def test_a_member_with_nobody_to_shoot_stays_out_of_the_side(self):
        """It would otherwise eat width in a battle it cannot take part in."""
        screen = StubMapScreen()
        screen.add_nation("BIG", at_war_with=["FOE"])
        screen.add_nation("NEUTRAL_ALLY", at_war_with=[])
        screen.add_nation("FOE", at_war_with=["BIG"])
        screen.nation_data["BIG"]["allied_with"] = ["NEUTRAL_ALLY"]
        screen.nation_data["NEUTRAL_ALLY"]["allied_with"] = ["BIG"]

        prov = tile(screen, {"BIG": [unit("BIG", attack=10)],
                             "NEUTRAL_ALLY": [unit("NEUTRAL_ALLY", attack=99)],
                             "FOE": [unit("FOE", attack=10)]}, owner="BIG")

        battle = combat_rules.build_battle([prov["units"]], screen.nation_data)

        self.assertEqual(sides_of(battle), [(frozenset(("BIG",)), frozenset(("FOE",)))])
        self.assertEqual(battle.bystanders, ["NEUTRAL_ALLY"])

    def test_slots_held_is_the_answer_the_ai_asks_for(self):
        """Two callers used to work this out from the lane list themselves."""
        screen, prov, _troops = self.half_committed_tile()

        battle = combat_rules.build_battle([prov["units"]], screen.nation_data)

        self.assertEqual(combat_rules.slots_held(battle, "BIG"),
                         combat_rules.nation_front_capacity("BIG", prov,
                                                            screen.nation_data))


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


class OutnumberedTests(unittest.TestCase):
    """Being short of men is not a way to be left alone.

    Both fixtures here come from the 'uh oh' save, where two tiles were quietly
    not fighting: one country could not join a battle it was standing in, and
    another battle was not happening at all.
    """

    def three_way_tile(self, defenders=1):
        """One defender, two separate attackers -- the Soviet/Romania/Germany tile."""
        screen = StubMapScreen()
        screen.add_nation("SOV", at_war_with=["ROM", "GER"])
        screen.add_nation("ROM", at_war_with=["SOV"])
        screen.add_nation("GER", at_war_with=["SOV"])

        troops = {"SOV": [unit("SOV", attack=100) for _ in range(defenders)],
                  "ROM": [unit("ROM", attack=30) for _ in range(3)],
                  "GER": [unit("GER", attack=10)]}
        return screen, tile(screen, troops, owner="SOV"), troops

    def test_a_lone_defender_is_fought_by_everyone_standing_on_it(self):
        screen, prov, troops = self.three_way_tile()

        battle = combat_rules.build_battle([prov["units"]], screen.nation_data)

        self.assertEqual(set(pairs_of(battle)),
                         {frozenset(("SOV", "ROM")), frozenset(("SOV", "GER"))})
        self.assertEqual(battle.bystanders, [])
        for lane in battle.lanes:
            self.assertTrue(lane.a.front and lane.b.front)

    def test_the_smaller_attacker_actually_lands_damage(self):
        screen, _prov, troops = self.three_way_tile()

        combat_processor.process_combat(screen)

        # Germany is the light one and would have been the lane that dissolved.
        self.assertGreater(damage_taken(troops["GER"]), 0)
        self.assertAlmostEqual(damage_taken(troops["SOV"]),
                               3 * 30 + 10, places=6)

    def test_a_unit_on_two_fronts_still_fires_only_one_volley(self):
        """The reason a unit could only hold one front to begin with."""
        screen, _prov, troops = self.three_way_tile()

        combat_processor.process_combat(screen)

        dealt_by_sov = damage_taken(troops["ROM"]) + damage_taken(troops["GER"])
        self.assertAlmostEqual(dealt_by_sov, 100.0, places=6)

    def test_width_counts_a_two_front_unit_once(self):
        screen, prov, _troops = self.three_way_tile()

        battle = combat_rules.build_battle([prov["units"]], screen.nation_data)

        self.assertEqual(battle.width,
                         len({id(u) for lane in battle.lanes
                              for side in (lane.a, lane.b) for u in side.front}))


class HeldBackTests(unittest.TestCase):
    def test_a_nation_that_held_everything_back_still_fights(self):
        """A stale RESERVE flag once deleted a whole battle.

        In the 'uh oh' save, Nationalist China's only unit on a tile carried a
        RESERVE stance left over from an AI rotation on some earlier turn. It
        was its only unit, so its side of the lane was empty, the lane
        dissolved, and five Japanese divisions stood on top of it doing nothing.
        Holding a unit back is a preference, honoured only while somebody else
        can take the slot.
        """
        screen = StubMapScreen()
        screen.add_nation("JAP", at_war_with=["CHI"])
        screen.add_nation("CHI", at_war_with=["JAP"])

        lone = unit("CHI", attack=20)
        lone["combat_stance"] = "RESERVE"
        prov = tile(screen, {"JAP": [unit("JAP", attack=50) for _ in range(5)],
                             "CHI": [lone]})

        battle = combat_rules.build_battle([prov["units"]], screen.nation_data)

        self.assertEqual(len(battle.lanes), 1)
        self.assertEqual([id(u) for u in member_for(battle, "CHI").front], [id(lone)])

        combat_processor.process_combat(screen)
        self.assertGreater(damage_taken([lone]), 0)

    def test_holding_back_is_still_honoured_when_somebody_can_replace_them(self):
        screen = StubMapScreen()
        screen.add_nation("A", at_war_with=["B"])
        screen.add_nation("B", at_war_with=["A"])

        held = unit("A", attack=999)
        held["combat_stance"] = "RESERVE"
        prov = tile(screen, {"A": [held, unit("A", attack=10)],
                             "B": [unit("B", attack=10)]})

        battle = combat_rules.build_battle([prov["units"]], screen.nation_data)

        self.assertNotIn(id(held), {id(u) for u in side_for(battle, "A").front})

    def test_a_stale_stance_is_dropped_when_the_unit_marches_away(self):
        from map_logic.turn_processing import movement_processor

        screen = StubMapScreen()
        screen.add_nation("A", at_war_with=["B"])
        screen.add_nation("B", at_war_with=["A"])

        mover = unit("A", attack=10, path=["p2"])
        mover["combat_stance"] = "RESERVE"
        home = screen.add_province("p1", "A", units=[mover])
        away = screen.add_province("p2", "A")
        home["neighbors"] = ["p2"]
        away["neighbors"] = ["p1"]
        mover["_current_province_id"] = "p1"

        movement_processor.process_movement(screen)

        self.assertNotIn("combat_stance", mover)


class DeterminismTests(unittest.TestCase):
    """The same input must resolve the same way, every time and everywhere."""

    def signature(self, battle):
        return [(lane.index, lane.slots, member.nation, member.slots,
                 [id(u) for u in member.front])
                for lane in battle.lanes for side in (lane.a, lane.b)
                for member in side.members]

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
                  for side in (lane.a, lane.b) if "ATK" in side.nations
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
