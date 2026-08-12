"""A nation fires once a turn, and only at the enemy it is standing in front of.

The rule, stated by the playtest that found the pair loop broken, and then
narrowed by the lane model that replaced the pot:

    A tile splits into duels -- one per pair of hostile powers on it. A nation's
    volley is the attack of its front rank in a lane, split across the opposing
    front rank in that same lane, and nothing else. A nation on the tile at war
    with nobody present takes no damage and is not part of any combat
    calculation.

Two defects are pinned here, the second of which is why the first stopped being
enough. process_combat once walked every hostile *pair* independently and fired
each nation's full attack once per enemy, so a crowded tile did more total damage
the more sides joined it. Pooling the volley fixed that but left the receiving
side uncapped: damage divided across every hostile unit present, so bodies were
a way to thin somebody else's fire and a small ally beside a large one had its
damage diluted into nothing. Lanes cap both ends.

The same defect ran through head-on tile swaps, where the two sides are gathered
by direction of travel rather than by flag, so a neutral crossing alongside a
belligerent was shot at, shot back, and was dug in for the rest of the turn by
somebody else's war.

The fixture below is the one from the request, verbatim: A, B, C, D and E on one
tile, with A-B, A-C, B-C and B-D at war and E at war with nobody. Under lanes it
also demonstrates the coverage rule: B has three enemies here and two units, so
it turns up to its two heaviest fronts and the duel with D never forms.

tests/test_combat_lanes.py is the spec for the lane rule itself.
"""

import os
import sys
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import data.constants as c
from data import queries
from map_logic.rendering import overlay_renderer
from map_logic.turn_processing import combat_processor, combat_rules, movement_processor


class StubMapScreen:
    """Just enough of map_screen to resolve combat standalone."""

    def __init__(self):
        self.map_data = {}
        self.id_to_province = {}
        self.nation_data = {}
        self.tactical_mode = False
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
        return self.nation_data[name]

    def add_province(self, pid, owner, units=(), terrain="Plains"):
        prov = {
            "id": pid,
            "owner": owner,
            "_turn_start_owner": owner,
            "terrain": terrain,
            "is_coastal": False,
            "cores": [owner],
            "units": list(units),
            "building_queue": [],
        }
        self.map_data[pid] = prov
        self.id_to_province[pid] = prov
        return prov


def unit(owner, attack=100, health=100000, defense=0, path=(), kind="Infantry", speed=1):
    """A unit with enough health to survive the fight, so damage is readable.

    Defense defaults to 0 because apply_group_damage subtracts it flat from each
    defender's share -- with defense in play, "how much did A deal" stops being
    a single number and starts depending on who it landed on.
    """
    return {
        "type": kind,
        "owner": owner,
        "order": {"type": "MOVE", "path": list(path)},
        "speed": speed,
        "health": health,
        "max_health": health,
        "attack": attack,
        "defense": defense,
        "morale": 50.0,
    }


def damage_taken(units):
    return sum(u["max_health"] - u["health"] for u in units)


def five_nation_tile():
    """The tile from the request. Returns (screen, province, units by nation).

    A is at war with B and C. B is at war with A, C and D. C is at war with A
    and B. D is at war with B. E is at war with nobody and is only here because
    it has military access from whoever owns the tile.

    Unit counts are deliberately uneven -- B has 2 and C has 3 -- because the
    whole claim is about the size of the denominator.
    """
    screen = StubMapScreen()
    screen.add_nation("A", at_war_with=["B", "C"])
    screen.add_nation("B", at_war_with=["A", "C", "D"])
    screen.add_nation("C", at_war_with=["A", "B"])
    screen.add_nation("D", at_war_with=["B"])
    screen.add_nation("E")

    troops = {
        "A": [unit("A", attack=100)],
        "B": [unit("B", attack=60), unit("B", attack=60)],
        "C": [unit("C", attack=30), unit("C", attack=30), unit("C", attack=30)],
        "D": [unit("D", attack=40)],
        "E": [unit("E", attack=999)],
    }
    everyone = [u for side in troops.values() for u in side]
    prov = screen.add_province("p1", "A", units=everyone)
    return screen, prov, troops


def lanes_of(screen, prov):
    """{(nation, nation): lane} for the fight on this tile, keys order-free."""
    battle = combat_rules.build_battle([prov["units"]], screen.nation_data)
    return {frozenset((lane.a.nation, lane.b.nation)): lane for lane in battle.lanes}


class OneVolleyPerNationTests(unittest.TestCase):
    def test_a_splits_one_volley_between_the_fronts_it_is_holding(self):
        screen, prov, troops = five_nation_tile()

        # Silence everyone else so what lands is A's volley and nothing else.
        for name in ("B", "C", "D", "E"):
            for u in troops[name]:
                u["attack"] = 0

        # A has one unit and two enemies here. It holds both fronts -- being
        # short of men is not a reason an enemy standing in front of you cannot
        # attack -- so its 100 is split fifty each way.
        self.assertIn(frozenset(("A", "B")), lanes_of(screen, prov))
        self.assertIn(frozenset(("A", "C")), lanes_of(screen, prov))

        combat_processor.process_combat(screen)

        # Fifty onto B's front rank in the A-B lane (one unit), fifty onto C's
        # in the A-C lane (also one). The pot this replaced divided A's volley
        # across B's two units *and* C's three, for 20 apiece; the pair loop
        # before that gave B a full 100 and C another full 100.
        self.assertAlmostEqual(damage_taken(troops["B"]), 50.0, places=6)
        self.assertAlmostEqual(damage_taken(troops["C"]), 50.0, places=6)
        self.assertAlmostEqual(
            damage_taken(troops["B"]) + damage_taken(troops["C"]), 100.0, places=6,
            msg="A dealt more or less than its own attack")

    def test_a_nation_deals_its_front_rank_s_attack_once(self):
        screen, prov, troops = five_nation_tile()

        combat_processor.process_combat(screen)

        # Every point of damage came from one front rank firing once, so the
        # total is the sum of those ranks and nothing more -- with a unit
        # holding two fronts counted once across both. Under the pair loop A
        # alone fired 200 of its 100.
        battle = combat_rules.build_battle([prov["units"]], screen.nation_data)
        expected = sum(combat_rules.volley(side.front, battle.shares)
                       for lane in battle.lanes
                       for side in (lane.a, lane.b))
        dealt = damage_taken([u for side in troops.values() for u in side])
        self.assertAlmostEqual(dealt, expected, places=6)

    def test_the_share_is_per_enemy_unit_in_this_lane_only(self):
        screen, _prov, troops = five_nation_tile()

        combat_processor.process_combat(screen)

        # Four lanes: A-B, A-C, B-C, B-D. A holds two of them with one unit and
        # B holds three with two, so both split their attack across the fronts
        # they are standing on. E is at war with nobody and is untouched.
        #
        # Nobody deals more or less than their own attack, and nobody's damage
        # reaches a nation they share no lane with. That pair of properties is
        # the whole rule; the individual totals below just pin the arithmetic.
        self.assertAlmostEqual(damage_taken(troops["A"]), 60.0, places=6)
        self.assertAlmostEqual(damage_taken(troops["B"]), 150.0, places=6)
        self.assertAlmostEqual(damage_taken(troops["C"]), 110.0, places=6)
        self.assertAlmostEqual(damage_taken(troops["D"]), 30.0, places=6)
        self.assertAlmostEqual(damage_taken(troops["E"]), 0.0, places=6)

        dealt = damage_taken([u for side in troops.values() for u in side])
        self.assertAlmostEqual(dealt, 100 + 120 + 90 + 40, places=6,
                               msg="the tile dealt more or less than the attack standing on it")

    def test_a_nation_facing_more_enemies_does_not_deal_more_damage(self):
        alone = StubMapScreen()
        alone.add_nation("A", at_war_with=["B"])
        alone.add_nation("B", at_war_with=["A"])
        solo_a = [unit("A", attack=100)]
        solo_b = [unit("B", attack=1)]
        alone.add_province("p1", "A", units=solo_a + solo_b)
        combat_processor.process_combat(alone)
        one_front = damage_taken(solo_b)

        crowded = StubMapScreen()
        crowded.add_nation("A", at_war_with=["B", "C", "D"])
        for name in ("B", "C", "D"):
            crowded.add_nation(name, at_war_with=["A"])
        many_a = [unit("A", attack=100)]
        others = [unit(n, attack=1) for n in ("B", "C", "D")]
        crowded.add_province("p1", "A", units=many_a + others)
        combat_processor.process_combat(crowded)
        three_fronts = damage_taken(others)

        # A's output is A's attack, wherever it is pointed. Under the pair loop
        # the second number was three times the first.
        self.assertAlmostEqual(one_front, 100.0, places=6)
        self.assertAlmostEqual(three_fronts, 100.0, places=6)

    def test_combat_width_caps_the_whole_tile_not_each_nation(self):
        """The headline of the rework. Width is a tile budget, not a per-flag one.

        Under the rule this replaced the cap was applied inside
        queries.get_top_attackers, once per nation column, so five countries on
        a tile fielded five times the width and the number stopped meaning
        anything the moment a second flag turned up.
        """
        screen = StubMapScreen()
        names = ("A", "B", "C", "D", "E")
        for name in names:
            screen.add_nation(name, at_war_with=[n for n in names if n != name])

        # Sixty units, twelve apiece, everyone at war with everyone.
        troops = {n: [unit(n, attack=10) for _ in range(12)] for n in names}
        prov = screen.add_province(
            "p1", "A", units=[u for side in troops.values() for u in side])

        battle = combat_rules.build_battle([prov["units"]], screen.nation_data)
        seated = sum(len(side.front) for lane in battle.lanes for side in (lane.a, lane.b))

        # Ten duels among five mutually hostile powers, so the floor binds:
        # 12 // 20 is 0, and MIN_LANE_SLOTS_PER_SIDE holds every lane at 2.
        self.assertEqual(len(battle.lanes), 10)
        self.assertEqual(battle.width, seated)
        self.assertEqual(seated, len(battle.lanes) * 2 * c.MIN_LANE_SLOTS_PER_SIDE)
        self.assertLess(seated, len(prov["units"]),
                        "every unit on the tile got to fire")

    def test_the_lane_slot_cap_applies_to_each_side(self):
        screen = StubMapScreen()
        screen.add_nation("A", at_war_with=["B"])
        screen.add_nation("B", at_war_with=["A"])

        # One more unit than the lane can seat. sorted() puts the weakest last,
        # so it is the one left in reserve and it adds nothing to the volley.
        squad = [unit("A", attack=10) for _ in range(c.LANE_SLOTS_TYPICAL)]
        squad.append(unit("A", attack=1))
        target = [unit("B", attack=0)]
        screen.add_province("p1", "A", units=squad + target)

        combat_processor.process_combat(screen)

        self.assertAlmostEqual(damage_taken(target),
                               10.0 * c.LANE_SLOTS_TYPICAL, places=6)

    def test_a_dying_nation_still_fires_this_turn(self):
        screen = StubMapScreen()
        screen.add_nation("A", at_war_with=["B"])
        screen.add_nation("B", at_war_with=["A"])

        doomed = [unit("B", attack=25, health=1)]
        killer = [unit("A", attack=1000, health=100000)]
        screen.add_province("p1", "A", units=killer + doomed)

        combat_processor.process_combat(screen)

        # Volleys are measured before any of them land, so B's shot goes off
        # even though B is wiped out by the same exchange.
        self.assertEqual(screen.map_data["p1"]["units"], killer)
        self.assertAlmostEqual(damage_taken(killer), 25.0, places=6)


class BystanderTests(unittest.TestCase):
    def test_a_neutral_on_the_tile_takes_no_damage(self):
        screen, _prov, troops = five_nation_tile()

        combat_processor.process_combat(screen)

        self.assertEqual(damage_taken(troops["E"]), 0)

    def test_a_neutral_deals_no_damage_however_strong_it_is(self):
        screen, prov, troops = five_nation_tile()

        # E's unit has attack 999, far above anyone else on the tile.
        combat_processor.process_combat(screen)

        battle = combat_rules.build_battle([prov["units"]], screen.nation_data)
        expected = sum(combat_rules.volley(side.front, battle.shares)
                       for lane in battle.lanes
                       for side in (lane.a, lane.b))
        dealt = damage_taken([u for side in troops.values() for u in side])
        self.assertAlmostEqual(dealt, expected, places=6)
        self.assertNotIn("E", [n for pair in lanes_of(screen, prov) for n in pair])

    def test_a_neutral_keeps_its_marching_orders(self):
        screen, _prov, troops = five_nation_tile()
        for side in troops.values():
            for u in side:
                u["order"]["path"] = ["p2"]

        combat_processor.process_combat(screen)

        self.assertEqual(troops["E"][0]["order"]["path"], ["p2"],
                         "a bystander was frozen in place by other people's war")
        for name in ("A", "B", "C", "D"):
            for u in troops[name]:
                self.assertEqual(u["order"]["path"], [])

    def test_an_enemy_short_of_men_still_has_to_fight_you(self):
        """Being outnumbered is not a way to be left alone.

        D is at war with B and standing on the tile with it, but B has three
        enemies here and two units. An earlier version of the lane rule let B
        seat those two against its heavier fronts and simply not turn up to the
        duel with D, so D spent the turn dealing and taking nothing -- which is
        the "Germany could not join in" report from the 'uh oh' save, where the
        Soviet Union's single unit could only be fought by one of the two
        countries standing on top of it.

        B now holds all three fronts, splitting its attack between them.
        """
        screen, prov, troops = five_nation_tile()

        battle = combat_rules.build_battle([prov["units"]], screen.nation_data)
        self.assertNotIn("D", battle.bystanders)
        self.assertIn(frozenset(("B", "D")), set(lanes_of(screen, prov)))

        combat_processor.process_combat(screen)

        self.assertGreater(damage_taken(troops["D"]), 0)

    def test_a_neutral_does_not_lose_morale_for_a_battle_it_was_not_in(self):
        screen, _prov, troops = five_nation_tile()

        combat_processor.process_combat(screen)

        # turn_processor reads this flag to dock 5 morale; without it a unit
        # recovers 5 instead.
        self.assertNotIn("_in_combat_this_turn", troops["E"][0])
        self.assertTrue(troops["A"][0].get("_in_combat_this_turn"))

    def test_a_neutral_convoy_stays_loaded(self):
        screen = StubMapScreen()
        screen.add_nation("A", at_war_with=["B"])
        screen.add_nation("B", at_war_with=["A"])
        screen.add_nation("E")

        def convoy(owner):
            u = unit(owner, attack=10, kind="Convoy")
            u.update({"original_type": "Infantry", "original_speed": 1,
                      "original_max_health": 100000, "original_attack": 10,
                      "original_defense": 0})
            return u

        theirs, mine, neutral = convoy("A"), unit("B", attack=10), convoy("E")
        screen.add_province("p1", "A", units=[theirs, mine, neutral])

        combat_processor.process_combat(screen)

        self.assertEqual(theirs["type"], "Infantry", "a belligerent's convoy should unpack")
        self.assertEqual(neutral["type"], "Convoy", "a bystander's convoy was unpacked")

    def test_a_neutral_warship_in_a_contested_port_survives(self):
        screen = StubMapScreen()
        screen.add_nation("A", at_war_with=["B"])
        screen.add_nation("B", at_war_with=["A"])
        screen.add_nation("E")

        theirs = unit("A", attack=10, kind="Destroyer I")
        mine = unit("B", attack=10)
        neutral = unit("E", attack=10, kind="Destroyer I")
        screen.add_province("p1", "A", units=[theirs, mine, neutral])

        combat_processor.process_combat(screen)

        survivors = screen.map_data["p1"]["units"]
        self.assertIn(neutral, survivors, "a bystander's ship was scuttled by someone else's war")
        self.assertNotIn(theirs, survivors, "a belligerent's ship should still be scuttled on land")


class WhoIsActuallyFightingTests(unittest.TestCase):
    def test_a_nation_at_war_with_someone_who_is_not_here_is_a_bystander(self):
        screen = StubMapScreen()
        screen.add_nation("A", at_war_with=["B"])
        screen.add_nation("B", at_war_with=["A"])
        screen.add_nation("F", at_war_with=["Z"])
        screen.add_nation("Z", at_war_with=["F"])

        elsewhere = unit("F", attack=500)
        here = [unit("A", attack=10), unit("B", attack=10), elsewhere]
        screen.add_province("p1", "A", units=here)

        combat_processor.process_combat(screen)

        self.assertEqual(damage_taken([elsewhere]), 0)
        self.assertNotIn("_in_combat_this_turn", elsewhere)

    def test_a_lopsided_war_list_resolves_the_same_whoever_stands_first(self):
        # A scenario or the editor can leave one side's war list out of step.
        # The pair loop this replaced checked hostility one way round only, so
        # the answer depended on the order units happened to sit in the province.
        def run(order):
            screen = StubMapScreen()
            screen.add_nation("A", at_war_with=["B"])
            screen.add_nation("B")               # B's list never got A added
            troops = {"A": [unit("A", attack=100)], "B": [unit("B", attack=40)]}
            screen.add_province("p1", "A", units=[troops[n][0] for n in order])
            combat_processor.process_combat(screen)
            return damage_taken(troops["A"]), damage_taken(troops["B"])

        self.assertEqual(run(("A", "B")), run(("B", "A")))
        self.assertEqual(run(("A", "B")), (40.0, 100.0))

    def test_build_battle_leaves_out_everyone_with_nobody_to_shoot(self):
        screen, prov, _troops = five_nation_tile()

        battle = combat_rules.build_battle([prov["units"]], screen.nation_data)

        # Only E, which is at war with nobody here. Everyone with an enemy on
        # this tile is in a lane against them, however short of units they are.
        self.assertEqual(battle.engaged, ["A", "B", "C", "D"])
        self.assertEqual(battle.bystanders, ["E"])

    def test_a_column_marching_the_same_way_is_not_fought(self):
        # Two sides means a head-on clash, and a lane always crosses the divide.
        # Two nations at war while marching together settle it where they land,
        # not while they cross.
        screen = StubMapScreen()
        screen.add_nation("A", at_war_with=["B", "C"])
        screen.add_nation("B", at_war_with=["A", "C"])
        screen.add_nation("C", at_war_with=["A", "B"])

        # Two A units, so A can turn up to both of its lanes and the only thing
        # left to explain a missing lane is the rule under test.
        a = [unit("A", attack=10), unit("A", attack=10)]
        b, cc = unit("B", attack=10), unit("C", attack=10)

        # B and C are at war with each other, and marching shoulder to shoulder.
        battle = combat_rules.build_battle([[b, cc], a], screen.nation_data)

        pairs = {frozenset((lane.a.nation, lane.b.nation)) for lane in battle.lanes}
        self.assertEqual(pairs, {frozenset(("B", "A")), frozenset(("C", "A"))})
        self.assertNotIn(frozenset(("B", "C")), pairs)


class HeadOnTests(unittest.TestCase):
    """resolve_meeting_engagement: two tiles swapping garrisons."""

    def build(self):
        screen = StubMapScreen()
        screen.add_nation("A", at_war_with=["C"])
        screen.add_nation("C", at_war_with=["A"])
        screen.add_nation("E")
        return screen

    def test_a_neutral_crossing_alongside_is_not_shot_at(self):
        screen = self.build()
        a = unit("A", attack=100, path=["p2"])
        e = unit("E", attack=100, path=["p2"])
        cc = unit("C", attack=100, path=["p1"])
        p1 = screen.add_province("p1", "A", units=[a, e])
        p2 = screen.add_province("p2", "C", units=[cc])

        result = combat_processor.resolve_meeting_engagement(
            p1, p2, [a, e], [cc], screen.nation_data)

        self.assertEqual(damage_taken([e]), 0)
        self.assertAlmostEqual(damage_taken([a]), 100.0, places=6)
        self.assertAlmostEqual(damage_taken([cc]), 100.0, places=6,
                               msg="the neutral's attack was counted against C")
        self.assertNotIn(id(e), result.fought)

    def test_a_neutral_crossing_alongside_is_not_dug_in(self):
        screen = self.build()
        a = unit("A", attack=100, path=["p2"])
        e = unit("E", attack=100, path=["p2"])
        cc = unit("C", attack=100, path=["p1"])
        p1 = screen.add_province("p1", "A", units=[a, e])
        p2 = screen.add_province("p2", "C", units=[cc])

        combat_processor.resolve_meeting_engagement(
            p1, p2, [a, e], [cc], screen.nation_data)

        self.assertTrue(a.get("_combat_locked"))
        self.assertFalse(e.get("_combat_locked"),
                         "a bystander was pinned by a battle it was not in")

    def test_survivors_still_include_the_bystander(self):
        # The movement pass subtracts the survivors from what it handed in to
        # find the dead, so a bystander left out of that list would be deleted.
        screen = self.build()
        a = unit("A", attack=100, path=["p2"])
        e = unit("E", attack=100, path=["p2"])
        cc = unit("C", attack=100, path=["p1"])
        p1 = screen.add_province("p1", "A", units=[a, e])
        p2 = screen.add_province("p2", "C", units=[cc])

        result = combat_processor.resolve_meeting_engagement(
            p1, p2, [a, e], [cc], screen.nation_data)

        self.assertIn(e, result.survivors1)
        self.assertIn(a, result.survivors1)

    def test_a_bystander_keeps_walking_through_a_mid_turn_swap(self):
        screen = self.build()
        a = unit("A", attack=100, path=["p2"], speed=2)
        e = unit("E", attack=100, path=["p2", "p3"], speed=2)
        cc = unit("C", attack=100, path=["p1"], speed=2)
        screen.add_province("p1", "A", units=[a, e])
        # Unclaimed so the neutral's route is not blocked by an access rule,
        # which would prove nothing about the battle it walked past.
        screen.add_province("p2", "Unclaimed", units=[cc])
        screen.add_province("p3", "Unclaimed")

        movement_processor.process_movement(screen)

        self.assertIn(e, screen.map_data["p3"]["units"],
                      "a bystander was stopped by a swap it was not part of")


class PredictionBubbleTests(unittest.TestCase):
    """The bubble has to agree with the fight the turn will actually resolve."""

    def weigh(self, screen, prov, friendly_nations):
        """The real thing draw_combat_bubbles calls, not a restatement of it."""
        return overlay_renderer.combat_strengths(
            [prov["units"]], screen.nation_data, friendly_nations)

    def test_a_three_way_fight_counts_only_the_lane_you_are_in(self):
        screen = StubMapScreen()
        screen.add_nation("P", at_war_with=["X"])
        screen.add_nation("X", at_war_with=["P", "Y"])
        screen.add_nation("Y", at_war_with=["X"])

        mine = [unit("P", attack=60)]
        theirs = [unit("X", attack=100), unit("X", attack=100)]
        third = [unit("Y", attack=10)]
        prov = screen.add_province("p1", "P", units=mine + theirs + third)

        friendly, enemy, involved = self.weigh(screen, prov, {"P"})

        # X has two enemies here and two units, so coverage puts one in each
        # lane: one unit's worth of fire reaches me, not both. Summing X's raw
        # attack called this a loss; it is a draw, and the bubble now says so
        # for the same reason the turn will.
        self.assertTrue(involved)
        self.assertAlmostEqual(friendly, 60.0, places=6)
        self.assertAlmostEqual(enemy, 100.0, places=6)

        combat_processor.process_combat(screen)
        self.assertAlmostEqual(damage_taken(mine), 100.0, places=6,
                               msg="the bubble promised a fight the turn did not run")
        self.assertAlmostEqual(damage_taken(third), 100.0, places=6)

    def test_a_tile_where_only_a_bystander_ally_stands_is_not_your_fight(self):
        screen = StubMapScreen()
        screen.add_nation("P")
        screen.add_nation("ALLY")
        screen.add_nation("X", at_war_with=["Y"])
        screen.add_nation("Y", at_war_with=["X"])
        screen.nation_data["P"]["allied_with"] = ["ALLY"]

        prov = screen.add_province("p1", "X", units=[
            unit("ALLY", attack=50), unit("X", attack=100), unit("Y", attack=100)])

        friendly, enemy, involved = self.weigh(screen, prov, {"P", "ALLY"})

        self.assertFalse(involved,
                         "a battle your ally is only standing next to is not yours")
        self.assertEqual((friendly, enemy), (0.0, 0.0))


class ChargeTests(unittest.TestCase):
    """process_pinning's suicide-charge probe, which also applies real damage."""

    def test_a_bystander_neither_absorbs_nor_answers_a_doomed_charge(self):
        screen = StubMapScreen()
        screen.add_nation("DEF", at_war_with=["ATK"])
        screen.add_nation("ATK", at_war_with=["DEF"])
        screen.add_nation("E")

        defender = unit("DEF", attack=1000, health=100000)
        neutral = unit("E", attack=1000, health=100000)
        charger = unit("ATK", attack=20, health=1, path=["p1"])

        screen.add_province("p1", "DEF", units=[defender, neutral])
        screen.add_province("p2", "ATK", units=[charger])

        combat_processor.process_pinning(screen)

        self.assertEqual(charger["health"], 0, "the charge should have been wiped out")
        # The charge's 20 lands on DEF alone; E was standing here on access and
        # used to both add its 1000 to the defence and eat a share of the reply.
        self.assertAlmostEqual(damage_taken([defender]), 20.0, places=6)
        self.assertEqual(damage_taken([neutral]), 0)


if __name__ == "__main__":
    unittest.main()
