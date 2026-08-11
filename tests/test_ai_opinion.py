"""Covers personality, durable grudges, and opinion-driven decisions.

Between them these are what stop every AI nation reasoning identically. The
cases that matter most are the ones the old logic could not express at all: that
good relations make a nation less likely to attack you, that a war can end with
land changing hands, that a trade can be fair, and that a betrayal is still
remembered a decade later.
"""

import os
import sys
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import data.constants as c
from data import queries
from map_logic.ai import ai_opinion, ai_personality, ai_world

from tests.test_ai_world import build_world, unit


class PersonalityTests(unittest.TestCase):
    def test_the_same_scenario_always_produces_the_same_nation(self):
        a = ai_personality.procedural("Avaria", "seed-1")
        b = ai_personality.procedural("Avaria", "seed-1")
        self.assertEqual(a, b)

    def test_it_is_stable_against_a_hardcoded_expectation(self):
        """The test that catches an accidental switch to hash(), which Python
        salts per process -- the same save would hand out different
        personalities on every launch and nobody would notice for months."""
        traits = ai_personality.procedural("Avaria", "greater-diplomacy-5")
        self.assertEqual(traits, {"aggression": 0.5684, "ambition": 0.5712,
                                  "caution": 0.6225, "loyalty": 0.4504,
                                  "trust": 0.6154})

    def test_different_nations_get_different_temperaments(self):
        a = ai_personality.procedural("Avaria", "s")
        b = ai_personality.procedural("Borland", "s")
        self.assertNotEqual(a, b)

    def test_every_trait_is_in_range(self):
        for name in ("Avaria", "Borland", "Carrow", "Dunmar", "", "x" * 200):
            traits = ai_personality.procedural(name, "s")
            for trait in ai_personality.TRAITS:
                self.assertGreaterEqual(traits[trait], 0.0, (name, trait))
                self.assertLessEqual(traits[trait], 1.0, (name, trait))

    def test_most_nations_are_moderate(self):
        """Averaging two uniforms rather than one, so a map is not one-third
        fanatics. Guards the shape of the distribution, not any single value."""
        extremes = 0
        total = 0
        for i in range(300):
            for value in ai_personality.procedural(f"N{i}", "s").values():
                total += 1
                if value < 0.2 or value > 0.8:
                    extremes += 1
        self.assertLess(extremes / total, 0.25)

    def test_a_scenario_can_override_one_trait_and_leave_the_rest(self):
        nation_data = {}
        settings = {"ai_personality_overrides": {"Avaria": {"aggression": 0.95}}}
        traits = ai_personality.get(nation_data, "Avaria", settings)
        procedural = ai_personality.procedural("Avaria", settings["ai_personality_seed"])
        self.assertEqual(traits["aggression"], 0.95)
        self.assertEqual(traits["caution"], procedural["caution"])
        self.assertEqual(traits["_source"], "scenario")

    def test_an_authored_personality_is_never_regenerated(self):
        nation_data = {}
        ai_personality.set_authored(nation_data, "Avaria", {"aggression": 0.1}, "editor")
        again = ai_personality.get(nation_data, "Avaria", {})
        self.assertEqual(again["aggression"], 0.1)
        self.assertEqual(again["_source"], "editor")

    def test_a_save_with_no_personalities_gets_them_once_and_keeps_them(self):
        nation_data = {"Avaria": {"manpower": 1}}
        settings = {}
        first = dict(ai_personality.get(nation_data, "Avaria", settings))
        second = ai_personality.get(nation_data, "Avaria", settings)
        self.assertEqual(first, second)
        self.assertIn("personality", nation_data["Avaria"])

    def test_out_of_range_overrides_are_clamped(self):
        nation_data = {}
        settings = {"ai_personality_overrides": {"Avaria": {"aggression": 4.0,
                                                           "caution": -2.0,
                                                           "loyalty": "nonsense"}}}
        traits = ai_personality.get(nation_data, "Avaria", settings)
        self.assertEqual(traits["aggression"], 1.0)
        self.assertEqual(traits["caution"], 0.0)
        self.assertEqual(traits["loyalty"], 0.5)


class ModifierStorageTests(unittest.TestCase):
    """Old int modifiers and new dict ones have to coexist forever."""

    def test_a_bare_int_reads_as_it_always_did(self):
        self.assertEqual(queries.modifier_value(-20), -20)
        self.assertEqual(queries.modifier_decay(-20), 1)
        self.assertIsNone(queries.modifier_turns(-20))

    def test_a_dict_carries_its_own_decay_and_lifetime(self):
        entry = {"value": -40, "decay": 0, "turns": 60}
        self.assertEqual(queries.modifier_value(entry), -40)
        self.assertEqual(queries.modifier_decay(entry), 0)
        self.assertEqual(queries.modifier_turns(entry), 60)

    def test_garbage_does_not_raise(self):
        for junk in (None, "x", {}, {"value": "x"}, [1]):
            self.assertEqual(queries.modifier_value(junk), 0)

    def test_a_plain_modifier_is_still_stored_as_a_plain_int(self):
        """Keeps saves readable and lets an older build make sense of the
        common case."""
        nation_data = {"A": {}}
        queries.add_temporary_modifier("A", "B", "recent_war", -20, nation_data)
        self.assertEqual(nation_data["A"]["temp_modifiers"]["B"]["recent_war"], -20)

    def test_a_durable_modifier_is_stored_as_a_dict(self):
        nation_data = {"A": {}}
        queries.add_temporary_modifier("A", "B", "broke_pact", -40, nation_data,
                                       decay=0, turns=60, reason="betrayal")
        entry = nation_data["A"]["temp_modifiers"]["B"]["broke_pact"]
        self.assertEqual((entry["value"], entry["decay"], entry["turns"]), (-40, 0, 60))

    def test_general_opinion_still_stacks_across_both_forms(self):
        nation_data = {"A": {}}
        queries.add_temporary_modifier("A", "B", "general", -10, nation_data)
        queries.add_temporary_modifier("A", "B", "general", -15, nation_data)
        self.assertEqual(queries.modifier_value(
            nation_data["A"]["temp_modifiers"]["B"]["general"]), -25)


class ModifierDecayTests(unittest.TestCase):
    def decay_once(self, mods):
        from map_logic.diplomacy import diplomacy_processor

        class Screen:
            nation_data = {"A": {"temp_modifiers": {"B": mods}, "truces": {},
                                 "war_durations": {}}}
        diplomacy_processor._decay_modifiers_and_truces(Screen())
        return Screen.nation_data["A"]["temp_modifiers"]["B"]

    def test_an_old_style_int_still_fades_by_exactly_one_a_turn(self):
        mods = self.decay_once({"recent_war": -20})
        self.assertEqual(mods["recent_war"], -19)

    def test_a_positive_modifier_fades_toward_zero_too(self):
        self.assertEqual(self.decay_once({"good": 5})["good"], 4)

    def test_a_modifier_that_reaches_zero_is_removed(self):
        self.assertNotIn("recent_war", self.decay_once({"recent_war": -1}))

    def test_a_grudge_with_no_decay_does_not_soften(self):
        """The point of the whole storage change: a betrayal nobody remembers
        next decade is not a betrayal, it is a free move."""
        mods = self.decay_once({"broke_pact": {"value": -40, "decay": 0, "turns": 60}})
        self.assertEqual(mods["broke_pact"]["value"], -40)
        self.assertEqual(mods["broke_pact"]["turns"], 59)

    def test_but_it_still_expires_when_its_time_runs_out(self):
        mods = self.decay_once({"broke_pact": {"value": -40, "decay": 0, "turns": 1}})
        self.assertNotIn("broke_pact", mods)

    def test_the_two_forms_decay_side_by_side(self):
        mods = self.decay_once({"old": -20,
                                "new": {"value": -40, "decay": 0, "turns": 60}})
        self.assertEqual(mods["old"], -19)
        self.assertEqual(mods["new"]["value"], -40)


class WarDesireTests(unittest.TestCase):
    def setUp(self):
        self.world, self.map_data, self.nation_data, self.id_to_province = build_world()
        self.settings = {}

    def desire(self, a="Avaria", b="Carrow"):
        return ai_opinion.war_desire(self.world, a, b, self.settings)

    def set_traits(self, nation, **traits):
        base = {t: 0.5 for t in ai_personality.TRAITS}
        base.update(traits)
        ai_personality.set_authored(self.nation_data, nation, base)

    def rebuild(self):
        self.world = ai_world.AIWorld(self.map_data, self.nation_data, self.id_to_province)

    def test_desire_is_a_degree_not_a_boolean(self):
        value = self.desire()
        self.assertGreaterEqual(value, 0.0)
        self.assertLessEqual(value, 1.0)

    def test_good_relations_suppress_war(self):
        """The headline change. Previously nothing did."""
        self.set_traits("Avaria")
        self.nation_data["Avaria"]["temp_modifiers"]["Carrow"] = {"general": -150}
        self.rebuild()
        hostile = self.desire()

        self.nation_data["Avaria"]["temp_modifiers"]["Carrow"] = {"general": 150}
        self.rebuild()
        friendly = self.desire()

        self.assertGreater(hostile, friendly)

    def test_an_aggressive_nation_wants_war_more_than_a_peaceable_one(self):
        self.set_traits("Avaria", aggression=1.0)
        self.rebuild()
        aggressive = self.desire()

        self.set_traits("Avaria", aggression=0.0)
        self.rebuild()
        peaceable = self.desire()

        self.assertGreater(aggressive, peaceable)

    def test_a_cautious_nation_needs_better_odds(self):
        self.set_traits("Avaria", caution=0.0)
        self.rebuild()
        bold = self.desire()

        self.set_traits("Avaria", caution=1.0)
        self.rebuild()
        careful = self.desire()

        self.assertGreater(bold, careful)

    def test_a_nation_already_at_war_is_less_keen_on_another(self):
        self.set_traits("Avaria")
        self.rebuild()
        before = self.desire()

        self.nation_data["Avaria"]["at_war_with"] = ["Borland", "Dunmar", "Carrow-Other"]
        self.rebuild()
        self.assertLess(self.desire(), before)

    def test_holding_our_cores_makes_a_target_more_appealing(self):
        self.set_traits("Avaria")
        self.rebuild()
        baseline = self.desire(b="Dunmar")

        for prov in self.map_data.values():
            if prov["owner"] == "Dunmar":
                prov["cores"].append("Avaria")
        self.rebuild()
        self.assertGreater(self.desire(b="Dunmar"), baseline)


class PeaceTests(unittest.TestCase):
    def setUp(self):
        self.world, self.map_data, self.nation_data, self.id_to_province = build_world()
        # A one-sided war. Avaria loses its army, its friends and its treasury;
        # simply deleting its units is not enough, because allied strength and
        # stockpiles keep it ahead on the global term -- which is the model
        # working, and was what made the first version of this test wrong.
        self.nation_data["Avaria"]["allied_with"] = []
        self.nation_data["Avaria"]["puppets"] = []
        self.nation_data["Dunmar"]["master"] = ""
        for resource in ("manpower", "materials", "fuel"):
            self.nation_data["Avaria"][resource] = 0
        for prov in self.map_data.values():
            prov["units"] = [u for u in prov.get("units", []) if u["owner"] != "Avaria"]
            if prov["owner"] == "Borland":
                prov["units"] += [unit("Borland", 900, 200) for _ in range(6)]
        self.rebuild()

    def rebuild(self):
        self.world = ai_world.AIWorld(self.map_data, self.nation_data, self.id_to_province)

    def test_the_fixture_really_is_one_sided(self):
        border, glob = self.world.power_ratio("Avaria", "Borland")
        self.assertLess(border, 1.0)
        self.assertLess(glob, 1.0)

    def test_a_long_losing_war_can_end_with_land_changing_hands(self):
        """Previously impossible: will_ai_accept_peace refused a claims demand
        unconditionally, so no AI war ever resolved into a settlement."""
        self.nation_data["Avaria"]["war_durations"] = {"Borland": 60}
        self.rebuild()
        self.assertTrue(ai_opinion.accepts_peace(
            self.world, "Avaria", "Borland", c.PEACE_DEMAND_CLAIMS))

    def test_but_not_while_it_is_winning(self):
        self.nation_data["Borland"]["war_durations"] = {"Avaria": 60}
        self.rebuild()
        self.assertFalse(ai_opinion.accepts_peace(
            self.world, "Borland", "Avaria", c.PEACE_DEMAND_CLAIMS))

    def test_nor_before_the_war_has_even_started(self):
        self.nation_data["Avaria"]["war_durations"] = {"Borland": 0}
        self.rebuild()
        self.assertFalse(ai_opinion.accepts_peace(
            self.world, "Avaria", "Borland", c.PEACE_DEMAND_CLAIMS))

    def test_a_ceasefire_is_easier_to_agree_to_than_giving_up_land(self):
        self.nation_data["Avaria"]["war_durations"] = {"Borland": 5}
        self.rebuild()
        self.assertTrue(ai_opinion.accepts_peace(
            self.world, "Avaria", "Borland", c.PEACE_WHITE_PEACE))

    def test_weariness_grows_with_the_war(self):
        self.nation_data["Avaria"]["war_durations"] = {"Borland": 1}
        self.rebuild()
        early = ai_opinion.peace_appetite(self.world, "Avaria", "Borland")
        self.nation_data["Avaria"]["war_durations"] = {"Borland": 100}
        self.rebuild()
        self.assertGreater(ai_opinion.peace_appetite(self.world, "Avaria", "Borland"), early)


class TradeTests(unittest.TestCase):
    def setUp(self):
        self.world, self.map_data, self.nation_data, self.id_to_province = build_world()
        self.prices = {"materials": 1.0, "manpower": 1.0, "fuel": 5.0}

    def appetite(self, receive, give, nation="Avaria", sender="Carrow"):
        return ai_opinion.trade_appetite(self.world, nation, sender, receive, give,
                                         self.prices)

    def test_a_pure_gift_is_welcome(self):
        self.assertGreater(self.appetite({"materials": 500}, {}), 0)

    def test_giving_away_everything_for_nothing_is_not(self):
        self.assertLess(self.appetite({}, {"materials": 500}), 0)

    def test_a_fair_swap_of_scarce_for_plentiful_is_worth_taking(self):
        """500 materials for 100 fuel: even money by volume, good by scarcity.
        The old rule refused this outright -- it accepted a trade only if the AI
        gave literally nothing."""
        self.assertGreater(self.appetite({"fuel": 100}, {"materials": 400}), 0)

    def test_a_friend_gets_a_better_rate_than_a_stranger(self):
        even = ({"materials": 500}, {"materials": 500})
        self.nation_data["Avaria"]["temp_modifiers"]["Carrow"] = {"general": 150}
        friendly_world = ai_world.AIWorld(self.map_data, self.nation_data, self.id_to_province)
        friendly = ai_opinion.trade_appetite(friendly_world, "Avaria", "Carrow",
                                             *even, prices=self.prices)

        self.nation_data["Avaria"]["temp_modifiers"]["Carrow"] = {"general": -150}
        hostile_world = ai_world.AIWorld(self.map_data, self.nation_data, self.id_to_province)
        hostile = ai_opinion.trade_appetite(hostile_world, "Avaria", "Carrow",
                                            *even, prices=self.prices)

        self.assertGreater(friendly, hostile)


if __name__ == "__main__":
    unittest.main()
