"""Every nation asked in one turn must send the same prompt prefix.

A local model re-reads a prompt from the first token that differs from the last
one it saw, and the world picture is around ninety percent of what we send. So
naming the nation in the opening line, and weaving its own relation scores
through the politics block, made twelve nations pay the full cost twelve times:
measured against llama3 on the 1941 map, 179s for twelve majors, of which 156s
was re-reading a world that had not changed. Reordered so the shared part comes
first, the same twelve cost 28s and fit inside the default 45s turn budget.

Nothing about that is visible from reading the prompt, and any future edit that
puts a nation's name back at the top would silently undo it. Hence this file.
"""

import os
import sys
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from map_logic.ai import ai_candidates as ac, ai_director, ai_evaluation, ai_prompts

NATIONS = ["Alpha", "Beta", "Gamma", "Delta"]


def nation_data():
    data = {}
    for i, n in enumerate(NATIONS):
        data[n] = {
            "manpower": 1000 * (i + 1), "materials": 500 * (i + 1),
            "at_war_with": [NATIONS[(i + 1) % len(NATIONS)]],
            "faction": "Bloc" if i % 2 == 0 else "",
            "relations": {other: (i + 1) * 10 for other in NATIONS if other != n},
        }
    return data


def prompt_for(nation, data):
    """The whole thing, in the order ai_diplomacy actually sends it."""
    context = ai_evaluation.get_world_context(data, set(NATIONS), nation)
    bag = ac.Collector(nation, {})
    for other in NATIONS:
        if other != nation:
            bag.add(ac.make("TRADE", other, 0.5, "because"))
    system, user = ai_director.build_prompt(None, nation, bag.ranked(), 3)
    return f"{system}\n\n{context}\n{user}"


class SharedPrefixTests(unittest.TestCase):
    def setUp(self):
        self.data = nation_data()
        self.prompts = [prompt_for(n, self.data) for n in NATIONS]

    def test_most_of_the_prompt_is_identical_across_nations(self):
        shared = os.path.commonprefix(self.prompts)
        share = len(shared) / len(self.prompts[0])
        self.assertGreater(share, 0.5,
                           f"only {share:.0%} of the prompt is shared; a local model "
                           f"will re-read the world for every nation")

    def test_the_world_picture_is_inside_the_shared_part(self):
        shared = os.path.commonprefix(self.prompts)
        self.assertIn("--- GLOBAL POLITICS ---", shared)
        for nation in NATIONS:
            self.assertIn(f"- {nation}:", shared,
                          "a nation's standing in the world is not shared prefix")

    def test_no_nation_is_named_before_the_shared_part_ends(self):
        """The failure this file exists for: one "You are X" at the top costs
        the entire saving, and nothing else would notice."""
        shared = os.path.commonprefix(self.prompts)
        for nation in NATIONS:
            self.assertNotIn(f"You are the leader of {nation}", shared)

    def test_each_nation_is_still_told_who_it_is(self):
        for nation, prompt in zip(NATIONS, self.prompts):
            self.assertIn(f"You are the leader of {nation}.", prompt)

    def test_each_nation_still_gets_its_own_economy(self):
        for nation, prompt in zip(NATIONS, self.prompts):
            self.assertIn(f"{self.data[nation]['manpower']} Manpower", prompt)

    def test_each_nation_still_gets_its_own_opinions(self):
        tails = [p[len(os.path.commonprefix(self.prompts)):] for p in self.prompts]
        self.assertEqual(len(set(tails)), len(NATIONS), "the tails are not distinct")
        for nation, tail in zip(NATIONS, tails):
            self.assertIn("How you regard the others", tail)

    def test_the_politics_block_does_not_depend_on_who_is_asking(self):
        blocks = []
        for prompt in self.prompts:
            start = prompt.index("--- GLOBAL POLITICS ---")
            blocks.append(prompt[start:prompt.index("--- YOU ---")])
        self.assertEqual(len(set(blocks)), 1, "the politics block varies by asker")

    def test_the_order_is_stable_between_calls(self):
        """Sets iterate in whatever order they please; an unstable listing would
        break the shared prefix at random and be maddening to diagnose."""
        again = [prompt_for(n, self.data) for n in NATIONS]
        self.assertEqual(again, self.prompts)

    def test_the_politics_block_is_sorted_rather_than_merely_consistent(self):
        """Two calls in one process agree whatever a set does, so "same twice"
        proves nothing. The listing has to be sorted to be the same across a
        save and reload, or a different build of Python."""
        prompt = self.prompts[0]
        block = prompt[prompt.index("--- GLOBAL POLITICS ---"):prompt.index("--- YOU ---")]
        listed = [line[2:line.index(":")] for line in block.splitlines()
                  if line.startswith("- ")]
        self.assertEqual(listed, sorted(listed), f"politics listed as {listed}")


class RelationTrimTests(unittest.TestCase):
    def test_neutral_opinions_are_left_out(self):
        """Driven by what get_relation_score actually returns, not by what the
        fixture asked for: the score is computed from wars, factions and
        modifiers, so writing 0 into `relations` does not necessarily produce
        one, and a fixture that never hits zero would test nothing."""
        from data import queries

        data = nation_data()
        scores = {other: queries.get_relation_score("Alpha", other, data)
                  for other in NATIONS if other != "Alpha"}
        neutral = [n for n, s in scores.items() if s == 0]
        notable = [n for n, s in scores.items() if s != 0]
        self.assertTrue(neutral, f"fixture produced no neutral relations: {scores}")

        context = ai_evaluation.get_world_context(data, set(NATIONS), "Alpha")
        listed = context[context.index("How you regard"):]
        for n in neutral:
            self.assertNotIn(f"- {n}: 0", listed, f"{n} is neutral and should be omitted")
        for n in notable:
            self.assertIn(f"- {n}: {scores[n]}", listed)

    def test_the_model_is_told_what_an_omission_means(self):
        """Trimming the neutral entries only works if the absence is defined."""
        data = nation_data()
        context = ai_evaluation.get_world_context(data, set(NATIONS), "Alpha")
        header = context[context.index("How you regard"):]
        self.assertIn("neutral", header.split("\n- ")[0])

    def test_a_nation_with_no_opinions_at_all_still_builds(self):
        data = nation_data()
        data["Alpha"]["relations"] = {}
        context = ai_evaluation.get_world_context(data, set(NATIONS), "Alpha")
        self.assertIn("You are the leader of Alpha", context)


class VoiceStillStatedTests(unittest.TestCase):
    def test_the_director_prompt_still_states_the_voice(self):
        """Moving text between the two halves must not lose the rule that stops
        a nation talking about itself in the third person."""
        system, _user = ai_director.build_prompt(None, "Alpha", [], 3)
        self.assertIn(ai_prompts.VOICE_RULE, system)

    def test_a_personality_note_still_reaches_the_model(self):
        _system, user = ai_director.build_prompt(None, "Alpha", [], 3, "Your temperament: bold.\n")
        self.assertIn("Your temperament: bold.", user)


if __name__ == "__main__":
    unittest.main()
