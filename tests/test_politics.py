"""The political axis: what it does, how fast, and where it stops.

The rule, as specified:

    A line from libertarian to authoritarian. Further left means your armies
    deal less damage but your research is faster; further right means slower
    research and harder-hitting armies. Ten turns to go from the centre to
    either end, twenty to cross the whole thing. Everyone starts in the middle.
    Max left is 0.7x damage and 2.0x research; max right is 1.3x damage and
    0.0x research, linear in between.

Two things in there are easy to get quietly wrong and are pinned hardest here.
The first is *whose* multiplier applies: a volley is measured off a LaneSide's
front rank, which is a whole coalition's units, so applying one country's
multiplier to the total would leak a nation's politics into its allies' guns.
The second is what happens at the end of the axis -- the direction has to clear
itself, because the map button's arrow badge reads "am I still drifting" and a
country pressed against the wall forever would wear it forever.

The AI half is a target position rather than a direction, which is what stops
every country at war from ending up at +10 together.
"""

import os
import sys
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import data.constants as c
from map_logic import politics
from map_logic.turn_processing import combat_processor, combat_rules

from tests.test_multiparty_combat import StubMapScreen, damage_taken, unit


class StubTurnScreen:
    """Just the two attributes politics.tick reaches for."""

    def __init__(self, nation_data):
        self.nation_data = nation_data


def screen_with(**by_nation):
    """A nation_data holder where each nation is (value, drift)."""
    nation_data = {}
    for name, (value, drift) in by_nation.items():
        nation_data[name] = {"political_value": value, "political_drift": drift}
    return StubTurnScreen(nation_data)


# ============================================================================ #
#                              THE MULTIPLIERS                                 #
# ============================================================================ #

class MultiplierTests(unittest.TestCase):
    def multipliers_at(self, value):
        nation_data = {"A": {"political_value": value}}
        return (politics.damage_multiplier(nation_data, "A"),
                politics.research_multiplier(nation_data, "A"))

    def test_the_centre_changes_nothing(self):
        self.assertEqual(self.multipliers_at(0), (1.0, 1.0))

    def test_the_libertarian_end_is_weak_and_fast(self):
        damage, research = self.multipliers_at(c.POLITICS_MIN)
        self.assertAlmostEqual(damage, 0.7)
        self.assertAlmostEqual(research, 2.0)

    def test_the_authoritarian_end_is_strong_and_stopped(self):
        damage, research = self.multipliers_at(c.POLITICS_MAX)
        self.assertAlmostEqual(damage, 1.3)
        self.assertAlmostEqual(research, 0.0)

    def test_the_scale_is_linear(self):
        """Halfway along is halfway between, both ways."""
        for value in (-5, 5):
            damage, research = self.multipliers_at(value)
            self.assertAlmostEqual(damage, 1.0 + 0.3 * value / 10.0)
            self.assertAlmostEqual(research, 1.0 - 1.0 * value / 10.0)

    def test_a_nation_nobody_has_touched_is_centrist(self):
        """An old save has none of these keys, and must play exactly as before."""
        nation_data = {"A": {}}
        self.assertEqual(politics.value(nation_data, "A"), 0)
        self.assertEqual(politics.drift(nation_data, "A"), 0)
        self.assertEqual(politics.damage_multiplier(nation_data, "A"), 1.0)
        self.assertEqual(politics.research_multiplier(nation_data, "A"), 1.0)

    def test_a_nation_that_is_not_in_the_table_at_all_is_centrist(self):
        """Rebellions and splinter states are read before they are written."""
        self.assertEqual(politics.value({}, "Nobody"), 0)
        self.assertEqual(politics.damage_multiplier({}, "Nobody"), 1.0)

    def test_a_corrupt_value_reads_as_centrist_rather_than_crashing(self):
        nation_data = {"A": {"political_value": "left", "political_drift": None}}
        self.assertEqual(politics.value(nation_data, "A"), 0)
        self.assertEqual(politics.drift(nation_data, "A"), 0)


class BandTests(unittest.TestCase):
    """The word and the color are one statement, so they come from one table."""

    def test_every_band_names_a_real_palette(self):
        for _bound, label, palette in politics.BANDS:
            self.assertIn(palette, c.UI_COLORS, f"{label} is painted in a color that does not exist")

    def test_the_axis_runs_light_blue_to_red(self):
        self.assertEqual(
            [politics.palette(v) for v in (-10, -5, 0, 5, 10)],
            ["light_blue", "green", "yellow", "orange", "red"])

    def test_an_untouched_country_is_yellow(self):
        """A blank map opens all one color, because centrist is a position."""
        self.assertEqual(politics.palette(c.POLITICS_START), "yellow")
        self.assertEqual(politics.palette(politics.value({"A": {}}, "A")), "yellow")

    def test_the_label_and_the_palette_never_disagree(self):
        expected = {"Libertarian": "light_blue", "Liberal": "green", "Centrist": "yellow",
                    "Statist": "orange", "Authoritarian": "red"}
        for value in range(c.POLITICS_MIN, c.POLITICS_MAX + 1):
            self.assertEqual(politics.palette(value), expected[politics.label(value)])

    def test_the_bands_still_say_what_they_always_said(self):
        """Adding color must not have moved a boundary."""
        self.assertEqual([politics.label(v) for v in range(-10, 11)],
                         ["Libertarian"] * 4 + ["Liberal"] * 4 + ["Centrist"] * 5
                         + ["Statist"] * 4 + ["Authoritarian"] * 4)

    def test_a_value_off_the_axis_is_still_painted(self):
        self.assertEqual(politics.palette(999), "red")
        self.assertEqual(politics.palette(-999), "light_blue")


# ============================================================================ #
#                                THE DRIFT                                     #
# ============================================================================ #

class DriftTests(unittest.TestCase):
    def test_one_step_per_processed_turn(self):
        screen = screen_with(A=(0, 1))
        politics.tick(screen)
        self.assertEqual(politics.value(screen.nation_data, "A"), 1)
        politics.tick(screen)
        self.assertEqual(politics.value(screen.nation_data, "A"), 2)

    def test_ten_turns_from_the_centre_reaches_an_end(self):
        screen = screen_with(A=(0, 1))
        for _ in range(10):
            politics.tick(screen)
        self.assertEqual(politics.value(screen.nation_data, "A"), c.POLITICS_MAX)

    def test_twenty_turns_crosses_the_whole_axis(self):
        screen = screen_with(A=(c.POLITICS_MIN, 1))
        for _ in range(20):
            politics.tick(screen)
        self.assertEqual(politics.value(screen.nation_data, "A"), c.POLITICS_MAX)

    def test_holding_still_moves_nothing(self):
        screen = screen_with(A=(3, 0))
        for _ in range(5):
            politics.tick(screen)
        self.assertEqual(politics.value(screen.nation_data, "A"), 3)

    def test_reaching_the_end_clears_the_direction(self):
        """Which is what puts the map button's arrow badge out by itself."""
        screen = screen_with(A=(c.POLITICS_MAX - 1, 1))
        politics.tick(screen)
        self.assertEqual(politics.value(screen.nation_data, "A"), c.POLITICS_MAX)
        self.assertEqual(politics.drift(screen.nation_data, "A"), 0)

    def test_the_value_never_leaves_the_axis(self):
        screen = screen_with(A=(c.POLITICS_MAX, 1), B=(c.POLITICS_MIN, -1))
        for _ in range(5):
            politics.tick(screen)
        self.assertEqual(politics.value(screen.nation_data, "A"), c.POLITICS_MAX)
        self.assertEqual(politics.value(screen.nation_data, "B"), c.POLITICS_MIN)

    def test_the_pseudo_nations_are_left_alone(self):
        """GLOBAL_EVENTS is a log, not a country."""
        screen = StubTurnScreen({"GLOBAL_EVENTS": {"political_drift": 1}})
        politics.tick(screen)
        self.assertNotIn("political_value", screen.nation_data["GLOBAL_EVENTS"])

    def test_each_nation_drifts_on_its_own(self):
        screen = screen_with(A=(0, 1), B=(0, -1), C=(0, 0))
        for _ in range(3):
            politics.tick(screen)
        self.assertEqual(politics.value(screen.nation_data, "A"), 3)
        self.assertEqual(politics.value(screen.nation_data, "B"), -3)
        self.assertEqual(politics.value(screen.nation_data, "C"), 0)


# ============================================================================ #
#                                THE DAMAGE                                    #
# ============================================================================ #

def two_nation_tile(a_value=0, b_value=0):
    """A and B at war on one tile, each with one unit. Returns (screen, prov)."""
    screen = StubMapScreen()
    screen.add_nation("A", at_war_with=["B"])
    screen.add_nation("B", at_war_with=["A"])
    politics.set_value(screen.nation_data, "A", a_value)
    politics.set_value(screen.nation_data, "B", b_value)
    prov = screen.add_province("p1", "A", units=[unit("A"), unit("B")])
    return screen, prov


class CombatDamageTests(unittest.TestCase):
    def damage_dealt_by_a(self, a_value):
        screen, prov = two_nation_tile(a_value=a_value)
        b_units = [u for u in prov["units"] if u["owner"] == "B"]
        combat_processor.process_combat(screen)
        return damage_taken(b_units)

    def test_a_centrist_nation_fights_exactly_as_it_always_did(self):
        self.assertAlmostEqual(self.damage_dealt_by_a(0), 100.0)

    def test_authoritarian_armies_hit_harder(self):
        self.assertAlmostEqual(self.damage_dealt_by_a(c.POLITICS_MAX), 130.0)

    def test_libertarian_armies_hit_softer(self):
        self.assertAlmostEqual(self.damage_dealt_by_a(c.POLITICS_MIN), 70.0)

    def test_it_applies_to_damage_dealt_while_defending_too(self):
        """A lane fight is simultaneous -- there is no attacker to single out."""
        screen, prov = two_nation_tile(b_value=c.POLITICS_MAX)
        a_units = [u for u in prov["units"] if u["owner"] == "A"]
        combat_processor.process_combat(screen)
        self.assertAlmostEqual(damage_taken(a_units), 130.0)

    def test_a_nations_politics_does_not_leak_into_its_allies_guns(self):
        """The multiplier is per unit, not per volley.

        A and B fight C side by side, sharing one LaneSide. If the multiplier
        were applied to the side's pooled attack, whichever of the two the code
        happened to read first would arm the other.
        """
        screen = StubMapScreen()
        screen.add_nation("A", at_war_with=["C"])
        screen.add_nation("B", at_war_with=["C"])
        screen.add_nation("C", at_war_with=["A", "B"])
        screen.nation_data["A"]["allied_with"] = ["B"]
        screen.nation_data["B"]["allied_with"] = ["A"]
        politics.set_value(screen.nation_data, "A", c.POLITICS_MAX)

        prov = screen.add_province("p1", "C", units=[unit("A"), unit("B"), unit("C")])
        c_units = [u for u in prov["units"] if u["owner"] == "C"]
        combat_processor.process_combat(screen)

        # A fires at 1.3x and its centrist ally B at 1.0x, not both at either.
        self.assertAlmostEqual(damage_taken(c_units), 130.0 + 100.0)

    def test_volley_without_nation_data_is_unmodified(self):
        """The callers that compare raw unit stats must see raw unit stats."""
        nation_data = {"A": {"political_value": c.POLITICS_MAX}}
        units = [unit("A")]
        self.assertAlmostEqual(combat_rules.volley(units), 100.0)
        self.assertAlmostEqual(combat_rules.volley(units, None, nation_data), 130.0)


class DisplayedDamageTests(unittest.TestCase):
    """What the panels print is what the fight delivers.

    The battle screen and the province sidebar both scale a unit's printed
    attack by how wounded it is. They have to scale it by the owner's politics
    too, or an authoritarian nation's roster advertises a number the resolver
    will not produce -- which is the same class of bug as the research screen
    quoting an unmodified pts/turn. One helper, read by both the screens and
    the resolver, is what keeps them from drifting.
    """

    def test_it_stacks_on_top_of_the_health_penalty(self):
        wounded = unit("A", attack=100, health=50000)
        wounded["max_health"] = 100000
        nation_data = {"A": {"political_value": c.POLITICS_MAX}}

        self.assertAlmostEqual(combat_rules.health_damage_multiplier(wounded), 0.5)
        self.assertAlmostEqual(
            combat_rules.effective_damage_multiplier(wounded, nation_data), 0.5 * 1.3)

    def test_it_runs_the_full_span(self):
        healthy = unit("A", attack=100)
        for value, expected in ((c.POLITICS_MIN, 0.7), (0, 1.0), (c.POLITICS_MAX, 1.3)):
            nation_data = {"A": {"political_value": value}}
            self.assertAlmostEqual(
                combat_rules.effective_damage_multiplier(healthy, nation_data), expected)

    def test_without_nation_data_it_is_the_bare_health_penalty(self):
        """The panels that price a unit type, not this country's copy of one."""
        wounded = unit("A", attack=100, health=50000)
        wounded["max_health"] = 100000
        self.assertAlmostEqual(combat_rules.effective_damage_multiplier(wounded), 0.5)

    def test_the_printed_figure_matches_what_the_turn_deals(self):
        """The contract, end to end: one unit, one enemy, one exchange."""
        for value in (c.POLITICS_MIN, 0, c.POLITICS_MAX):
            screen, prov = two_nation_tile(a_value=value)
            attacker = next(u for u in prov["units"] if u["owner"] == "A")
            defenders = [u for u in prov["units"] if u["owner"] == "B"]

            printed = (attacker["attack"]
                       * combat_rules.effective_damage_multiplier(attacker, screen.nation_data))
            combat_processor.process_combat(screen)

            self.assertAlmostEqual(damage_taken(defenders), printed,
                                   msg=f"panel and resolver disagree at {value:+d}")

    def test_the_map_combat_bubble_reads_the_same_number(self):
        from map_logic.rendering import overlay_renderer

        for value, expected in ((c.POLITICS_MIN, 70.0), (0, 100.0), (c.POLITICS_MAX, 130.0)):
            screen, _prov = two_nation_tile(a_value=value)
            friendly, enemy, involved = overlay_renderer.combat_strengths(
                [[unit("A"), unit("B")]], screen.nation_data, {"A"})
            self.assertTrue(involved)
            self.assertAlmostEqual(friendly, expected)
            self.assertAlmostEqual(enemy, 100.0, msg="the enemy's own politics is unaffected")


class BombardmentDamageTests(unittest.TestCase):
    def bombardment_damage(self, a_value):
        screen = StubMapScreen()
        screen.add_nation("A", at_war_with=["B"])
        screen.add_nation("B", at_war_with=["A"])
        politics.set_value(screen.nation_data, "A", a_value)

        gun = unit("A", kind="Artillery")
        gun["bombard_attack"] = 100
        gun["order"] = {"type": "BOMBARD", "target_id": "p2"}

        origin = screen.add_province("p1", "A", units=[gun])
        target = screen.add_province("p2", "B", units=[unit("B")])
        origin["neighbors"] = ["p2"]
        target["neighbors"] = ["p1"]

        defenders = list(target["units"])
        combat_processor.process_bombardments(screen)
        return damage_taken(defenders)

    def test_bombardment_scales_with_the_firing_nations_politics(self):
        centrist = self.bombardment_damage(0)
        if centrist <= 0:
            self.skipTest("this stub's artillery cannot reach -- see get_bombardment_range")
        self.assertAlmostEqual(self.bombardment_damage(c.POLITICS_MAX), centrist * 1.3)
        self.assertAlmostEqual(self.bombardment_damage(c.POLITICS_MIN), centrist * 0.7)


# ============================================================================ #
#                                THE RESEARCH                                  #
# ============================================================================ #

class ResearchTests(unittest.TestCase):
    """The resolver reads the multiplier off the nation whose queue it is on."""

    def points_after_one_turn(self, value):
        from map_logic.turn_processing import research_processor

        class Screen:
            pass

        screen = Screen()
        screen.scenario_settings = {}
        screen.player_country = "A"
        screen.nation_data = {
            "A": {"research": {"infantry_type": 0},
                  "research_queue": [{"tech_name": "infantry_type",
                                      "points_remaining": 100000}],
                  "political_value": value},
        }

        class Time:
            year, month_index, day, total_turns = 1910, 0, 1, 1

        screen.time_manager = Time()
        screen.show_feedback = lambda *_a, **_k: None

        before = screen.nation_data["A"]["research_queue"][0]["points_remaining"]
        research_processor.process_national_research(screen)
        after = screen.nation_data["A"]["research_queue"][0]["points_remaining"]
        return before - after

    def test_a_centrist_nation_researches_at_the_base_rate(self):
        self.assertGreater(self.points_after_one_turn(0), 0)

    def test_libertarian_research_is_twice_as_fast(self):
        base = self.points_after_one_turn(0)
        self.assertAlmostEqual(self.points_after_one_turn(c.POLITICS_MIN), base * 2.0)

    def test_authoritarian_research_stops_dead(self):
        self.assertAlmostEqual(self.points_after_one_turn(c.POLITICS_MAX), 0.0)


# ============================================================================ #
#                                  THE AI                                      #
# ============================================================================ #

class StubWorld:
    """The three things ai_politics asks an AIWorld for."""

    def __init__(self, nation_data, ratios=None, neighbors=None):
        self.nation_data = nation_data
        self._ratios = ratios or {}
        self.neighbors = neighbors or {}

    def power_ratio(self, nation, other):
        return self._ratios.get((nation, other), (1.0, 1.0))


def ai_world_with(*nations, **kwargs):
    nation_data = {n: {"name": n, "at_war_with": [], "allied_with": []} for n in nations}
    return StubWorld(nation_data, **kwargs)


class AIPoliticsTests(unittest.TestCase):
    def setUp(self):
        from map_logic.ai import ai_politics
        self.ai_politics = ai_politics

    def test_a_nation_at_peace_and_safe_leans_libertarian(self):
        world = ai_world_with("A", "B")
        self.assertLess(self.ai_politics.desired_value(world, "A"), 0)

    def test_a_nation_at_war_leans_authoritarian(self):
        world = ai_world_with("A", "B")
        world.nation_data["A"]["at_war_with"] = ["B"]
        world.nation_data["B"]["at_war_with"] = ["A"]
        self.assertGreater(self.ai_politics.desired_value(world, "A"), 0)

    def test_losing_a_war_centralises_harder_than_winning_one(self):
        def target(border, glob):
            world = ai_world_with("A", "B", ratios={("A", "B"): (border, glob)})
            world.nation_data["A"]["at_war_with"] = ["B"]
            world.nation_data["B"]["at_war_with"] = ["A"]
            return self.ai_politics.desired_value(world, "A")

        self.assertGreater(target(0.2, 0.2), target(5.0, 5.0))

    def test_a_war_it_is_winning_does_not_go_to_the_wall(self):
        """The nuance the whole target-position design exists for."""
        world = ai_world_with("A", "B", ratios={("A", "B"): (5.0, 5.0)})
        world.nation_data["A"]["at_war_with"] = ["B"]
        world.nation_data["B"]["at_war_with"] = ["A"]
        self.assertLess(self.ai_politics.desired_value(world, "A"), c.POLITICS_MAX)

    def test_a_threatening_neighbour_holds_a_peaceful_nation_nearer_the_centre(self):
        safe = ai_world_with("A", "B", neighbors={"A": {"B"}},
                             ratios={("A", "B"): (1.0, 5.0)})
        scared = ai_world_with("A", "B", neighbors={"A": {"B"}},
                               ratios={("A", "B"): (1.0, 0.1)})
        self.assertGreater(self.ai_politics.desired_value(scared, "A"),
                           self.ai_politics.desired_value(safe, "A"))

    def test_a_peaceful_nation_does_not_go_to_the_wall_either(self):
        world = ai_world_with("A", "B", neighbors={"A": {"B"}},
                              ratios={("A", "B"): (1.0, 100.0)})
        self.assertGreater(self.ai_politics.desired_value(world, "A"), c.POLITICS_MIN)

    def test_an_ally_next_door_is_not_a_menace(self):
        allied = ai_world_with("A", "B", neighbors={"A": {"B"}},
                               ratios={("A", "B"): (1.0, 0.1)})
        allied.nation_data["A"]["allied_with"] = ["B"]
        allied.nation_data["B"]["allied_with"] = ["A"]
        alone = ai_world_with("A", neighbors={"A": set()})
        self.assertEqual(self.ai_politics.desired_value(allied, "A"),
                         self.ai_politics.desired_value(alone, "A"))

    def test_it_walks_toward_the_target_and_stops_on_arrival(self):
        world = ai_world_with("A", "B")
        target = self.ai_politics.desired_value(world, "A")

        politics.set_value(world.nation_data, "A", 0)
        self.assertEqual(self.ai_politics.decide(world, "A", world.nation_data), -1)

        politics.set_value(world.nation_data, "A", target)
        self.assertEqual(self.ai_politics.decide(world, "A", world.nation_data), 0)
        self.assertEqual(politics.drift(world.nation_data, "A"), 0)

        politics.set_value(world.nation_data, "A", c.POLITICS_MIN)
        self.assertEqual(self.ai_politics.decide(world, "A", world.nation_data), 1)

    def test_a_war_turns_a_drifting_nation_around(self):
        """The target is recomputed every turn, so it reverses rather than snaps."""
        world = ai_world_with("A", "B")
        politics.set_value(world.nation_data, "A", -4)
        self.assertEqual(self.ai_politics.decide(world, "A", world.nation_data), -1)

        world.nation_data["A"]["at_war_with"] = ["B"]
        world.nation_data["B"]["at_war_with"] = ["A"]
        self.assertEqual(self.ai_politics.decide(world, "A", world.nation_data), 1)
        self.assertEqual(politics.value(world.nation_data, "A"), -4,
                         "deciding must not move the value; only tick does that")

    def test_the_same_world_decides_the_same_way_twice(self):
        """No `random` -- see the note in ai_personality.procedural."""
        first = ai_world_with("A", "B")
        second = ai_world_with("A", "B")
        self.assertEqual(self.ai_politics.desired_value(first, "A"),
                         self.ai_politics.desired_value(second, "A"))


if __name__ == "__main__":
    unittest.main()
