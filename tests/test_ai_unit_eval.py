"""Covers the stat-derived replacement for the AI's hardcoded unit lists.

Deliberately built on a synthetic six-unit library rather than the real 602, so
that rebalancing unit_data.json -- which is exactly the thing this module exists
to react to -- cannot break these tests. What is asserted here is the shape of
the reasoning: fuel a nation hasn't got makes fuel units worthless, build time
discounts value, defense pays off super-linearly but finitely, and a role that
is already saturated stops winning.
"""

import os
import sys
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import data.constants as c
from map_logic.ai import ai_unit_eval as ue


def unit(attack=100, defense=0, health=1000, speed=1, mat=500, man=1000, fuel=0,
         time=2, naval=False, **extra):
    stats = {"attack": attack, "defense": defense, "health": health, "speed": speed,
             "cost_materials": mat, "cost_manpower": man, "cost_fuel": fuel,
             "production_time": time, "naval_unit": naval}
    stats.update(extra)
    return stats


#: Six units spanning the decisions the evaluator has to get right.
LIBRARY = {
    "Rifles":     unit(attack=100, defense=0, health=1000, mat=500, man=1000, time=2),
    "Bunkers":    unit(attack=40, defense=120, health=1200, mat=700, man=900, time=3),
    "Tanks":      unit(attack=2400, defense=150, health=2500, mat=9000, man=1000,
                       fuel=200, time=6),
    "Guns":       unit(attack=50, defense=0, health=100, mat=2000, man=500, time=3,
                       bombard_attack=400, bombard_range=1),
    "Ships":      unit(attack=400, defense=100, health=400, mat=20000, man=2000,
                       fuel=500, time=10, naval=True),
    "Slowpokes":  unit(attack=2400, defense=150, health=2500, mat=9000, man=1000,
                       fuel=200, time=30),
}


#: Two units rigged to differ in exactly one thing: what they absorb.
#: Against a volley of 2000 over a stack of 5 the share is 400, so Paper's bite
#: is 400 and Plated's is the AI_MIN_DAMAGE_FRACTION floor of 40 -- ten times
#: less. Giving Plated a tenth of the health therefore makes their durability
#: identical, and their attack is equal, so any remaining gap in `combat` is the
#: dilution term alone and can be asserted exactly.
SOAK_PAIR = {
    "Paper":  unit(attack=100, defense=0, health=1000),
    "Plated": unit(attack=100, defense=400, health=100),
}


def econ(materials=10000, manpower=10000, fuel=1000,
         upkeep_mat=0, upkeep_man=0, upkeep_fuel=0):
    return {"total_inc": {"materials": materials, "manpower": manpower, "fuel": fuel},
            "upkeep": {"materials": upkeep_mat, "manpower": upkeep_man, "fuel": upkeep_fuel}}


def stock(materials=50000, manpower=50000, fuel=5000):
    return {"materials": materials, "manpower": manpower, "fuel": fuel}


def context(prices=None, volley=2000.0, stack=5.0, enemy_def=0.0, enemy_stack=5.0,
            frontline=4.0, coast=0.0, budget=None):
    prices = prices or ue.resource_prices(econ(), stock())
    if budget is None:
        budget = ue.spending_budget(econ(), stock(), prices)
    return ue.context(prices, volley=volley, stack=stack, enemy_def=enemy_def,
                      enemy_stack=enemy_stack, frontline=frontline, coast=coast,
                      budget=budget)


def scores(ctx=None, library=None):
    ctx = ctx or context()
    library = library or LIBRARY
    return ue.evaluate(list(library), library, ctx)


class PricingTests(unittest.TestCase):
    """Scarcity pricing is what replaces the old fuel_shortage boolean."""

    def test_a_resource_with_no_income_and_no_stock_hits_the_cap(self):
        prices = ue.resource_prices(econ(fuel=0), stock(fuel=0))
        self.assertAlmostEqual(prices["fuel"], 1.0 / c.AI_MIN_RESOURCE_SLACK)

    def test_a_plentiful_resource_is_cheap(self):
        prices = ue.resource_prices(econ(), stock())
        self.assertLess(prices["materials"], prices["fuel"] * 10)
        self.assertGreater(prices["materials"], 0)

    def test_scarcity_is_monotonic_in_income(self):
        rich = ue.resource_prices(econ(fuel=10000), stock(fuel=100000))["fuel"]
        poor = ue.resource_prices(econ(fuel=10), stock(fuel=10))["fuel"]
        self.assertGreater(poor, rich)

    def test_upkeep_already_committed_makes_a_resource_dearer(self):
        free = ue.resource_prices(econ(materials=10000, upkeep_mat=0), stock())["materials"]
        spent = ue.resource_prices(econ(materials=10000, upkeep_mat=9999), stock())["materials"]
        self.assertGreater(spent, free)

    def test_a_nation_with_no_fuel_will_not_buy_fuel_units_at_any_stockpile(self):
        """The whole point: no boolean, no special case, just price."""
        dry = context(prices=ue.resource_prices(econ(fuel=0), stock(fuel=0)))
        values = scores(dry)
        land = [v for v in values.values() if not v.naval]
        best = max(land, key=lambda v: v.score)
        self.assertEqual(best.stats["cost_fuel"], 0,
                         f"picked a fuel unit ({best.name}) with no fuel economy")


class ValuationTests(unittest.TestCase):
    def test_build_time_discounts_value(self):
        """Tanks and Slowpokes are identical apart from production_time."""
        values = scores()
        self.assertGreater(values["Tanks"].score, values["Slowpokes"].score)

    def test_defense_pays_off_but_stays_finite(self):
        """Flat per-hit subtraction against a diluted share means defense is worth
        a lot; AI_MIN_DAMAGE_FRACTION is what stops it being worth infinity.

        Volley 2000 over a stack of 5 is a 400 share, so the floor bites at
        400 * AI_MIN_DAMAGE_FRACTION = 40 damage however much defense is piled on.
        """
        library = {"Thin": unit(defense=0, health=1000),
                   "Thick": unit(defense=200, health=1000),
                   "Immune": unit(defense=100000, health=1000)}
        values = ue.evaluate(list(library), library, context(volley=2000.0, stack=5.0))
        self.assertAlmostEqual(values["Thin"].durability, 1000 / 400)
        self.assertAlmostEqual(values["Thick"].durability, 1000 / 200)
        self.assertAlmostEqual(values["Immune"].durability, 1000 / 40,
                               msg="the floor, not infinity")

    def test_the_damage_floor_caps_what_defense_can_buy(self):
        """Two units either side of the floor score the same, which is the
        deliberate ceiling on how far stacking defense can go."""
        library = {"Tough": unit(defense=380, health=1000),
                   "Absurd": unit(defense=999999, health=1000)}
        values = ue.evaluate(list(library), library, context(volley=2000.0, stack=5.0))
        self.assertEqual(values["Tough"].durability, values["Absurd"].durability)

    def test_a_zero_defense_body_earns_no_dilution_credit(self):
        """apply_group_damage deals sum(max(0, volley/N - defense)). At defense 0
        that is exactly `volley` however many bodies share it, so splitting into
        more of them absorbs nothing and must be worth nothing.

        This used to be a flat bonus every unit collected, which made the
        cheapest body in the game the best buy for any nation whose manpower was
        cheap -- the reason the USA filled its queues with militia.
        """
        values = ue.evaluate(list(SOAK_PAIR), SOAK_PAIR, context(volley=2000.0, stack=5.0))
        paper = values["Paper"]
        self.assertAlmostEqual(paper.combat - paper.offense - c.AI_W_DURABILITY, 0.0)

    def test_defense_still_earns_dilution_credit(self):
        """The term is scaled, not deleted: armour that actually absorbs a hit
        is still worth something purely for being an extra body."""
        values = ue.evaluate(list(SOAK_PAIR), SOAK_PAIR, context(volley=2000.0, stack=5.0))
        # The pair is built to have identical offense and identical durability,
        # so the whole gap between them is the dilution term -- and Plated's
        # defense covers the entire incoming share, so it earns the full weight.
        gap = values["Plated"].combat - values["Paper"].combat
        self.assertAlmostEqual(gap, c.AI_W_SOAK)

    def test_a_cheap_body_does_not_beat_a_better_one_of_the_same_role(self):
        """The militia case, in miniature: same manpower, a third of the
        materials, and half of everything that matters in a fight. Cheapness
        must not make up for it."""
        library = {"Militia": unit(attack=110, defense=0, health=1100,
                                   mat=300, man=1000, time=1),
                   "Regulars": unit(attack=410, defense=0, health=2550,
                                    mat=655, man=1000, time=2)}
        # A nation whose manpower is far cheaper than its materials -- exactly
        # the price ratio that used to flip this the wrong way.
        prices = {"manpower": 2.5, "materials": 15.0, "fuel": 15.0}
        values = ue.evaluate(list(library), library, context(prices=prices))
        self.assertGreater(values["Regulars"].score, values["Militia"].score)

    def test_a_heavier_volley_makes_everything_less_durable(self):
        light = ue.evaluate(list(LIBRARY), LIBRARY, context(volley=500.0))
        heavy = ue.evaluate(list(LIBRARY), LIBRARY, context(volley=50000.0))
        self.assertGreater(light["Rifles"].durability, heavy["Rifles"].durability)

    def test_a_bigger_stack_dilutes_the_volley(self):
        alone = ue.evaluate(list(LIBRARY), LIBRARY, context(stack=1.0))
        crowd = ue.evaluate(list(LIBRARY), LIBRARY, context(stack=20.0))
        self.assertGreater(crowd["Rifles"].durability, alone["Rifles"].durability)

    def test_an_empty_candidate_set_is_handled(self):
        self.assertEqual(ue.evaluate([], LIBRARY, context()), {})

    def test_unknown_names_are_skipped_rather_than_raising(self):
        self.assertEqual(list(ue.evaluate(["Nonexistent"], LIBRARY, context())), [])


class RoleTests(unittest.TestCase):
    def test_roles_come_from_stats_not_names(self):
        values = scores()
        self.assertEqual(values["Guns"].role, ue.ROLE_BOMBARD)
        self.assertEqual(values["Ships"].role, ue.ROLE_NAVAL)
        self.assertEqual(values["Tanks"].role, ue.ROLE_ASSAULT)
        self.assertEqual(values["Bunkers"].role, ue.ROLE_LINE)

    def test_renaming_a_unit_does_not_change_its_role(self):
        """is_ai_tank matched the substring "Tank"; nothing here reads the name."""
        library = {"Daffodil": LIBRARY["Tanks"], "Panzer VIII": LIBRARY["Bunkers"]}
        values = ue.evaluate(list(library), library, context())
        self.assertEqual(values["Daffodil"].role, ue.ROLE_ASSAULT)
        self.assertEqual(values["Panzer VIII"].role, ue.ROLE_LINE)

    def test_a_naval_bombard_unit_counts_as_naval(self):
        """Carriers bombard, but they still have to be built on a coast."""
        library = {"Carrier": unit(naval=True, bombard_attack=300, bombard_range=2)}
        values = ue.evaluate(list(library), library, context())
        self.assertEqual(values["Carrier"].role, ue.ROLE_NAVAL)

    def test_bombard_range_increases_value(self):
        library = {"Short": unit(bombard_attack=400, bombard_range=1),
                   "Long": unit(bombard_attack=400, bombard_range=3)}
        values = ue.evaluate(list(library), library, context())
        self.assertGreater(values["Long"].combat, values["Short"].combat)


class CompositionTests(unittest.TestCase):
    def test_assault_target_is_a_lane_s_front_rank(self):
        """Only a lane's front rank fires, so that is exactly how many assault
        units a frontline tile is worth."""
        targets = ue.role_targets(context(frontline=4.0), naval_need=0)
        self.assertEqual(targets[ue.ROLE_ASSAULT], c.LANE_SLOTS_TYPICAL * 4.0)

    def test_depth_is_capped_at_the_relief_rank(self):
        """New under lanes. A body past the relief rank cannot reach a front
        slot before the tile resolves, and absorbs nothing at all while it
        waits, so it is pure waste rather than merely diminishing value."""
        targets = ue.role_targets(context(frontline=4.0), naval_need=0)
        self.assertLessEqual(
            targets[ue.ROLE_LINE],
            c.LANE_SLOTS_TYPICAL * 4.0 * (c.AI_RESERVE_DEPTH - 1.0))

    def test_a_landlocked_nation_wants_no_navy(self):
        targets = ue.role_targets(context(), naval_need=0)
        self.assertEqual(targets[ue.ROLE_NAVAL], 0.0)

    def test_depth_is_targeted_by_spend_so_cheap_bodies_get_more_slots(self):
        """A count-based depth target commits nearly the whole budget to armour
        without anyone choosing that, because a tank costs many infantry. Pricing
        the target keeps the split intact whatever the units cost."""
        values = scores()
        targets = ue.role_targets(context(frontline=6.0), naval_need=0, values=values)
        self.assertGreater(targets[ue.ROLE_LINE], targets[ue.ROLE_ASSAULT],
                           "cheap bodies must earn more slots than expensive hitters")

    def test_making_bodies_dearer_shrinks_how_many_are_wanted(self):
        cheap = {"Hitter": LIBRARY["Tanks"], "Body": unit(mat=500, man=500)}
        dear = {"Hitter": LIBRARY["Tanks"], "Body": unit(mat=8000, man=8000)}
        ctx = context(frontline=6.0)
        cheap_target = ue.role_targets(
            ctx, 0, ue.evaluate(list(cheap), cheap, ctx))[ue.ROLE_LINE]
        dear_target = ue.role_targets(
            ctx, 0, ue.evaluate(list(dear), dear, ctx))[ue.ROLE_LINE]
        self.assertGreater(cheap_target, dear_target)

    def test_targets_still_work_before_a_valuation_exists(self):
        targets = ue.role_targets(context(frontline=6.0), naval_need=0)
        self.assertGreater(targets[ue.ROLE_LINE], 0)

    def test_a_saturated_role_stops_winning(self):
        values = scores()
        targets = ue.role_targets(context(frontline=4.0), naval_need=0)
        empty = ue.marginal_score(values["Tanks"], {}, targets)
        full = ue.marginal_score(values["Tanks"], {ue.ROLE_ASSAULT: targets[ue.ROLE_ASSAULT]}, targets)
        self.assertLess(full, empty)
        self.assertAlmostEqual(full, empty * c.AI_ROLE_DIMINISH)

    def test_picking_repeatedly_produces_a_mixed_army(self):
        """The old loop bought one tank per infantry by arithmetic. This one has
        no ratio in it at all -- the mix falls out of saturation."""
        values = scores()
        targets = ue.role_targets(context(frontline=4.0), naval_need=0)
        have = {}
        for _ in range(40):
            pick, _m = ue.pick_next(values, have, targets)
            have[pick.role] = have.get(pick.role, 0) + 1
        self.assertGreaterEqual(len(have), 2, f"army was all one role: {have}")
        self.assertIn(ue.ROLE_ASSAULT, have)

    def test_a_role_with_no_target_is_never_picked(self):
        values = scores()
        targets = ue.role_targets(context(frontline=4.0), naval_need=0)
        have = {}
        for _ in range(30):
            pick, _m = ue.pick_next(values, have, targets)
            have[pick.role] = have.get(pick.role, 0) + 1
        self.assertNotIn(ue.ROLE_NAVAL, have, "built a navy with no coastline")

    def test_affordability_filters_the_choice(self):
        values = scores()
        targets = ue.role_targets(context(), naval_need=0)
        pick, _m = ue.pick_next(values, {}, targets, affordable={"Rifles"})
        self.assertEqual(pick.name, "Rifles")

    def test_nothing_affordable_means_no_pick(self):
        values = scores()
        targets = ue.role_targets(context(), naval_need=0)
        pick, marginal = ue.pick_next(values, {}, targets, affordable=set())
        self.assertIsNone(pick)
        self.assertEqual(marginal, 0.0)

    def test_best_by_role_ignores_what_is_already_built(self):
        values = scores()
        self.assertEqual(ue.best_by_role(values, ue.ROLE_NAVAL), "Ships")
        self.assertIsNone(ue.best_by_role({}, ue.ROLE_ASSAULT))


class BuildableTests(unittest.TestCase):
    """Runs against the real library, since it is about tech gating, not balance."""

    def test_only_the_top_tier_of_each_family_is_offered(self):
        from data import queries
        library = queries.get_unit_library()
        research = {"destroyer": 8, "medium_tank": 3, "infantry_type": 30}
        names = ue.buildable_units(research, library)

        destroyers = [n for n in names if queries.get_base_unit_name(n) == "Destroyer"]
        self.assertEqual(destroyers, ["Destroyer VIII"])

    def test_nothing_researched_yields_nothing_or_only_free_units(self):
        from data import queries
        library = queries.get_unit_library()
        for name in ue.buildable_units({}, library):
            self.assertTrue(queries.is_unit_unlocked(name, {}), name)

    def test_the_same_research_is_only_worked_out_once(self):
        """Scanning the 602-entry library is regex-heavy and was most of the
        research pass. Nations in a scenario mostly share research, so a
        fifty-country map asks a handful of distinct questions, not fifty.

        Asserted by counting distinct entries after asking distinct questions,
        NOT by counting entries after asking the same one twice -- the first
        version of this test did the latter, which stays at one entry whether
        the cache works or is being wiped on every call, and so sat green over
        exactly that bug.
        """
        from data import queries
        library = queries.get_unit_library()
        a = {"destroyer": 8, "medium_tank": 3, "infantry_type": 30}
        b = {"destroyer": 8, "medium_tank": 4, "infantry_type": 30}

        ue._BUILDABLE_CACHE.clear()
        first = ue.buildable_units(a, library)
        ue.buildable_units(b, library)
        again = ue.buildable_units(dict(a), library)

        self.assertEqual(first, again)
        self.assertEqual(len(ue._BUILDABLE_CACHE), 2,
                         "both questions must still be remembered")

    def test_the_cache_survives_repeated_calls(self):
        """Directly pins the bug above: the library check compared id() values
        with `is not`, and large ints are not interned, so it was always true."""
        from data import queries
        library = queries.get_unit_library()
        ue._BUILDABLE_CACHE.clear()
        for level in range(1, 6):
            ue.buildable_units({"medium_tank": level}, library)
        self.assertEqual(len(ue._BUILDABLE_CACHE), 5)

    def test_different_research_gets_a_different_answer(self):
        from data import queries
        library = queries.get_unit_library()
        few = ue.buildable_units({"infantry_type": 30}, library)
        many = ue.buildable_units({"infantry_type": 30, "medium_tank": 3}, library)
        self.assertNotEqual(few, many)

    def test_swapping_the_library_invalidates_the_cache(self):
        """A mod replacing unit_data must not be answered from the old library."""
        research = {"infantry_type": 30}
        real = __import__("data.queries", fromlist=["queries"]).get_unit_library()
        ue.buildable_units(research, real)
        substitute = dict(LIBRARY)
        self.assertNotEqual(ue.buildable_units(research, substitute),
                            ue.buildable_units(research, real))

    def test_the_candidate_set_stays_small(self):
        """~25 families, not 602 tiers -- the valuation runs per nation per turn."""
        from data import queries
        library = queries.get_unit_library()
        research = {k: 99 for k in queries.get_tech_tree()}
        self.assertLess(len(ue.buildable_units(research, library)), 40)


class EffectiveAttackTests(unittest.TestCase):
    """Attack is not worth its face value: defense is subtracted flat per hit."""

    def test_an_attack_too_weak_to_beat_enemy_defense_lands_nothing(self):
        """Which is precisely why an army of cheap bodies loses to armour, and
        the thing the old preference lists could not express at all."""
        ctx = context(enemy_def=500.0, enemy_stack=5.0)
        self.assertEqual(ue.effective_attack(100.0, ctx), 0.0)

    def test_a_strong_enough_attack_gets_most_of_itself_through(self):
        ctx = context(enemy_def=200.0, enemy_stack=5.0)
        self.assertGreater(ue.effective_attack(3600.0, ctx), 3000.0)

    def test_it_is_measured_for_a_full_firing_line_not_a_lone_unit(self):
        """One unit's attack rarely clears a defense value alone; five of them
        routinely do. Scoring solo would write off every light unit in the game."""
        ctx = context(enemy_def=300.0, enemy_stack=5.0)
        self.assertGreater(ue.effective_attack(400.0, ctx), 0.0)

    def test_an_undefended_enemy_takes_the_full_attack(self):
        ctx = context(enemy_def=0.0, enemy_stack=7.0)
        self.assertAlmostEqual(ue.effective_attack(250.0, ctx), 250.0)

    def test_facing_armour_shifts_the_choice_toward_hitters(self):
        soft = scores(context(enemy_def=0.0))
        armoured = scores(context(enemy_def=300.0))
        soft_gap = soft["Tanks"].score / soft["Rifles"].score
        armoured_gap = armoured["Tanks"].score / armoured["Rifles"].score
        self.assertGreater(armoured_gap, soft_gap)


class ThreatProfileTests(unittest.TestCase):
    def test_peacetime_falls_back_to_what_it_could_face(self):
        """Not zero -- a zero volley makes every unit immortal and defense free."""
        volley, enemy_def, enemy_stack = ue.threat_profile(
            None, "Avaria", LIBRARY, list(LIBRARY))
        self.assertGreater(volley, 1.0)
        self.assertGreater(enemy_def, 0.0)
        self.assertGreaterEqual(enemy_stack, 1.0)

    def test_wartime_measures_the_actual_enemy_on_the_border(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "fx", os.path.join(os.path.dirname(__file__), "test_ai_world.py"))
        fx = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fx)
        world, _map_data, _nd, _idp = fx.build_world()

        volley, enemy_def, enemy_stack = ue.threat_profile(
            world, "Avaria", LIBRARY, list(LIBRARY))
        self.assertGreater(volley, 1.0)
        self.assertGreaterEqual(enemy_stack, 1.0)


if __name__ == "__main__":
    unittest.main()
