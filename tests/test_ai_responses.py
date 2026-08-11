"""Everything the AI says with the model switched off now lives in a data file.

It used to be fifty hardcoded strings in ai_prompts.py: one sentence per
situation, so the same war produced the same line every time and nobody could
add a variant without editing Python. data/json/ai_responses.json holds them
instead, keyed the same way, with two things the dict could not express -- a key
may carry several interchangeable lines, and a line may be conditioned on what
is actually true between the two nations.

The compatibility shim matters as much as the feature: forty-odd call sites
index AI_FALLBACK_RESPONSES directly, most of them with no second party to
condition on, and every one of them must keep working untouched.
"""

import os
import random
import sys
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from map_logic.ai import ai_prompts


def nation(**over):
    base = {"at_war_with": [], "allied_with": [], "faction": "", "master": "",
            "puppets": [], "temp_modifiers": {}, "relations": {}}
    base.update(over)
    return base


class TableShapeTests(unittest.TestCase):
    """The file has to answer for every key the code names."""

    def test_every_key_the_handler_names_exists(self):
        from map_logic.ai import ai_handler
        keys = set(ai_handler.LITE_RESPONSE_KEYS.values())
        keys |= {"AI_OFF_ACCEPT", "AI_OFF_REJECT", "AI_OFF_MESSAGE",
                 "GENERIC_ACCEPT", "GENERIC_MESSAGE"}
        for key in sorted(keys):
            with self.subTest(key=key):
                self.assertIsNotNone(ai_prompts.resolve(key))

    def test_every_proactive_proposal_has_lines(self):
        from map_logic.ai import ai_diplomacy
        for action, spec in ai_diplomacy.PROACTIVE_PROPOSALS.items():
            with self.subTest(action=action):
                self.assertTrue(ai_prompts.lines_for(spec.fallback_key))

    def test_the_readme_is_not_offered_as_a_response(self):
        self.assertNotIn("_README", ai_prompts.AI_FALLBACK_RESPONSES)

    def test_the_shipped_file_actually_varies_the_common_replies(self):
        """The complaint was that the hardcoded lines all felt the same."""
        for key in ("AI_OFF_ACCEPT", "AI_OFF_REJECT", "PROACTIVE_TRADE", "BETRAYAL"):
            with self.subTest(key=key):
                self.assertGreater(len(ai_prompts.lines_for(key)), 1)

    def test_every_line_is_a_string(self):
        for key in ai_prompts.AI_FALLBACK_RESPONSES:
            for line in ai_prompts.lines_for(key):
                self.assertIsInstance(line, str, key)


class ResolveShapeTests(unittest.TestCase):
    """A key may hold a bare string, a flat list, or conditioned groups."""

    def resolve(self, entry, **kw):
        real = ai_prompts.all_responses
        ai_prompts.all_responses = lambda: {"K": entry}
        try:
            return ai_prompts.resolve("K", **kw)
        finally:
            ai_prompts.all_responses = real

    def test_a_bare_string_still_resolves(self):
        """What lets the file be filled in a bit at a time, and what keeps a
        trimmed-down mod working."""
        self.assertEqual(self.resolve("Only one thing to say."), "Only one thing to say.")

    def test_an_unconditional_group_resolves(self):
        self.assertEqual(self.resolve([{"lines": ["Just this."]}]), "Just this.")

    def test_a_flat_list_of_strings_uses_all_of_them(self):
        """The simplest authoring shape, and by far the most common one in the
        shipped file. Gathering each bare string into its own group meant only
        the first was ever said, so most of the file was dead text."""
        seen = {self.resolve(["a", "b", "c"], rng=random.Random(s)) for s in range(40)}
        self.assertEqual(seen, {"a", "b", "c"})

    def test_a_conditioned_group_still_beats_loose_strings(self):
        entry = ["loose", {"when": {"strength": "weaker"}, "lines": ["conditioned"]}]
        real = ai_prompts.all_responses
        ai_prompts.all_responses = lambda: {"K": entry}
        try:
            weak = ai_prompts.resolve("K", sender="Us", target="Them",
                                      nation_data={"Us": nation(), "Them": nation()},
                                      map_data={"1": {"units": [{"owner": "Them",
                                                                "type": "Militia I",
                                                                "health": 9999}]}})
        finally:
            ai_prompts.all_responses = real
        self.assertEqual(weak, "conditioned")

    def test_a_missing_key_gives_back_the_default(self):
        self.assertEqual(ai_prompts.resolve("NO_SUCH_KEY", default="fallback"), "fallback")

    def test_a_missing_key_with_no_default_gives_nothing(self):
        self.assertIsNone(ai_prompts.resolve("NO_SUCH_KEY"))

    def test_a_key_holding_junk_gives_back_the_default(self):
        for junk in (None, 7, {}, [], [{}], [{"lines": []}]):
            with self.subTest(junk=junk):
                self.assertEqual(self.resolve(junk, default="d"), "d")

    def test_placeholders_are_filled(self):
        self.assertEqual(self.resolve("We aid {target}.", fmt={"target": "Poland"}),
                         "We aid Poland.")


class ConditionTests(unittest.TestCase):
    """Which group wins, given what is true between the two nations."""

    ENTRY = [
        {"when": {"strength": "weaker"}, "lines": ["We are outmatched."]},
        {"when": {"strength": "stronger"}, "lines": ["You are outmatched."]},
        {"when": {"strength": "stronger", "at_war": True}, "lines": ["Still outmatched, still fighting."]},
        {"lines": ["An even thing."]},
    ]

    def setUp(self):
        self.real = ai_prompts.all_responses
        ai_prompts.all_responses = lambda: {"K": self.ENTRY}
        self.nation_data = {"Us": nation(), "Them": nation()}

    def tearDown(self):
        ai_prompts.all_responses = self.real

    class World:
        def __init__(self, mine, theirs):
            self._s = {"Us": mine, "Them": theirs}

        def strength(self, n):
            return self._s[n]

    def line(self, mine, theirs):
        return ai_prompts.resolve("K", sender="Us", target="Them",
                                  nation_data=self.nation_data,
                                  world=self.World(mine, theirs))

    def test_the_weaker_side_gets_the_weaker_line(self):
        self.assertEqual(self.line(100, 1000), "We are outmatched.")

    def test_the_stronger_side_gets_the_stronger_line(self):
        self.assertEqual(self.line(1000, 100), "You are outmatched.")

    def test_an_even_match_falls_through_to_the_catch_all(self):
        self.assertEqual(self.line(1000, 1000), "An even thing.")

    def test_the_more_specific_group_wins_when_both_hold(self):
        self.nation_data["Us"]["at_war_with"] = ["Them"]
        self.nation_data["Them"]["at_war_with"] = ["Us"]
        self.assertEqual(self.line(1000, 100), "Still outmatched, still fighting.")

    def test_with_no_second_party_the_catch_all_answers(self):
        """The forty-odd call sites that have nobody to compare against."""
        self.assertEqual(ai_prompts.resolve("K"), "An even thing.")

    def test_an_unanswerable_condition_never_fires(self):
        ai_prompts.all_responses = lambda: {
            "K": [{"when": {"nonsense": "yes"}, "lines": ["wrong"]}, {"lines": ["right"]}]}
        self.assertEqual(self.line(1000, 1000), "right")

    def test_a_condition_may_name_several_acceptable_values(self):
        ai_prompts.all_responses = lambda: {
            "K": [{"when": {"strength": ["weaker", "even"]}, "lines": ["not winning"]},
                  {"lines": ["catch-all"]}]}
        self.assertEqual(self.line(100, 1000), "not winning")
        self.assertEqual(self.line(1000, 1000), "not winning")
        self.assertEqual(self.line(1000, 100), "catch-all")

    def test_an_enemy_with_no_army_leaves_us_stronger(self):
        self.assertEqual(self.line(500, 0), "You are outmatched.")

    def test_two_empty_armies_are_an_even_match(self):
        self.assertEqual(self.line(0, 0), "An even thing.")

    def test_strength_is_read_off_the_map_not_the_nation_table(self):
        """get_military_strength counts units on the map, so it wants map_data.
        Handing it nation_data returns 0 for everyone and silently reads every
        war in the game as an even match -- which is what it did at first."""
        map_data = {
            "1": {"units": [{"owner": "Them", "type": "Militia I", "health": 5000}]},
        }
        line = ai_prompts.resolve("K", sender="Us", target="Them",
                                  nation_data=self.nation_data, map_data=map_data)
        self.assertEqual(line, "We are outmatched.")

    def test_with_no_map_and_no_world_the_catch_all_answers(self):
        """Better than guessing 'even' and picking a line off the guess."""
        self.assertEqual(ai_prompts.resolve("K", sender="Us", target="Them",
                                            nation_data=self.nation_data),
                         "An even thing.")


class VariationTests(unittest.TestCase):
    """Several lines per key, so the same interaction stops reading the same."""

    def setUp(self):
        self.real = ai_prompts.all_responses
        ai_prompts.all_responses = lambda: {"K": [{"lines": ["one", "two", "three"]}]}

    def tearDown(self):
        ai_prompts.all_responses = self.real

    def test_it_picks_from_all_of_them(self):
        seen = {ai_prompts.resolve("K", rng=random.Random(seed)) for seed in range(40)}
        self.assertEqual(seen, {"one", "two", "three"})

    def test_the_same_seed_gives_the_same_line(self):
        a = ai_prompts.resolve("K", rng=random.Random(7))
        b = ai_prompts.resolve("K", rng=random.Random(7))
        self.assertEqual(a, b)


class CompatibilityShimTests(unittest.TestCase):
    """AI_FALLBACK_RESPONSES is indexed directly in forty-odd places."""

    def test_indexing_still_works(self):
        self.assertIsInstance(ai_prompts.AI_FALLBACK_RESPONSES["AI_OFF_ACCEPT"], str)

    def test_get_still_works(self):
        self.assertIsInstance(
            ai_prompts.AI_FALLBACK_RESPONSES.get("AI_OFF_ACCEPT", "x"), str)

    def test_get_returns_the_default_for_a_missing_key(self):
        self.assertEqual(ai_prompts.AI_FALLBACK_RESPONSES.get("NOPE", "d"), "d")

    def test_a_missing_key_still_raises_on_indexing(self):
        with self.assertRaises(KeyError):
            ai_prompts.AI_FALLBACK_RESPONSES["NOPE"]

    def test_membership_still_works(self):
        self.assertIn("AI_OFF_ACCEPT", ai_prompts.AI_FALLBACK_RESPONSES)
        self.assertNotIn("NOPE", ai_prompts.AI_FALLBACK_RESPONSES)

    def test_format_still_works_on_the_keys_that_take_placeholders(self):
        line = ai_prompts.AI_FALLBACK_RESPONSES["NOT_AT_WAR"].format(target="Poland")
        self.assertIn("Poland", line)

    def test_iteration_yields_keys(self):
        self.assertIn("AI_OFF_ACCEPT", list(ai_prompts.AI_FALLBACK_RESPONSES))


if __name__ == "__main__":
    unittest.main()
