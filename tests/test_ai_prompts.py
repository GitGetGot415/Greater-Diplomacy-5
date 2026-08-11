"""Guards the shared tail of the three long AI system prompts.

The action list, the rules for using an action and the JSON reply schema used
to be written out once per prompt. They are assembled from
ai_prompts.action_rules_and_schema now, so the risk this file covers is the
opposite of drift: that generalising the block quietly changed what the model
is told, or blurred the three per-prompt hints that are meant to stay distinct.
"""

import os
import sys
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from map_logic.ai import ai_prompts


class SharedTailTests(unittest.TestCase):
    def prompts(self):
        return {
            "unilateral": ai_prompts.get_unilateral_system_prompt("CONTEXT"),
            "bilateral_accept": ai_prompts.get_bilateral_system_prompt(True),
            "bilateral_reject": ai_prompts.get_bilateral_system_prompt(False),
            "custom_message": ai_prompts.get_custom_message_system_prompt(),
        }

    def test_every_long_prompt_ends_with_the_shared_block(self):
        """The subject word is the only per-prompt difference above the schema."""
        subjects = {"unilateral": "event", "bilateral_accept": "proposal",
                    "bilateral_reject": "proposal", "custom_message": "message"}
        hints = {"unilateral": "In-character dialogue reacting to the event in english",
                 "bilateral_accept": "In-character dialogue responding to the proposal in english",
                 "bilateral_reject": "In-character dialogue responding to the proposal in english",
                 "custom_message": "Your in-character response here"}
        for name, text in self.prompts().items():
            with self.subTest(prompt=name):
                tail = ai_prompts.action_rules_and_schema(subjects[name], hints[name])
                self.assertTrue(text.endswith(tail))

    def test_the_rules_are_stated_exactly_once_per_prompt(self):
        """A prompt that repeated the block would be an assembly mistake."""
        for name, text in self.prompts().items():
            with self.subTest(prompt=name):
                self.assertEqual(text.count("RULES FOR ACTIONS:"), 1)
                self.assertEqual(text.count("Valid actions:"), 1)

    def test_the_schema_hints_stay_distinct(self):
        """The model reads the hint inside the schema, so the three prompts
        must not collapse onto one wording."""
        hints = {
            "In-character dialogue reacting to the event in english",
            "In-character dialogue responding to the proposal in english",
            "Your in-character response here",
        }
        prompts = self.prompts()
        for hint in hints:
            with self.subTest(hint=hint):
                self.assertEqual(sum(1 for t in prompts.values() if hint in t),
                                 2 if "proposal" in hint else 1)

    def test_the_action_list_is_the_same_in_all_of_them(self):
        line = ("Valid actions: 'WAR_DECLARATION', 'JOIN_WARS', 'LEAVE_FACTION', "
                "'JOIN_FACTION_REQ', 'CEASEFIRE', 'CALL_TO_ARMS', 'CREATE_FACTION', "
                "'KICK_FACTION_MEMBER', 'DISBAND_FACTION' or 'NONE'.")
        for name, text in self.prompts().items():
            with self.subTest(prompt=name):
                self.assertIn(line, text)

    def test_the_openings_are_still_different(self):
        """Only the tail was shared; each prompt's own framing is intact."""
        openings = {t.split("\n")[0] for t in self.prompts().values()}
        self.assertEqual(len(openings), 4)

    def test_the_proactive_prompt_stays_short(self):
        """It asks for a single sentence and no action, so it must NOT carry
        the action rules."""
        text = ai_prompts.get_proactive_system_prompt("France", "Italy", "offering peace")
        self.assertNotIn("RULES FOR ACTIONS:", text)
        self.assertIn("France", text)
        self.assertIn("Italy", text)


class FallbackTableTests(unittest.TestCase):
    def test_every_proactive_proposal_has_its_canned_line(self):
        """ai_diplomacy names these keys; a missing one used to be a KeyError
        on two of the seven paths and a silent literal on the rest."""
        from map_logic.ai import ai_diplomacy
        for action, spec in ai_diplomacy.PROACTIVE_PROPOSALS.items():
            with self.subTest(action=action):
                self.assertIn(spec.fallback_key, ai_prompts.AI_FALLBACK_RESPONSES)
                # The defensive literal must not have drifted from the table.
                # A key may now hold several interchangeable lines, so the
                # question is whether the literal is still one of them.
                self.assertIn(spec.fallback, ai_prompts.lines_for(spec.fallback_key))

    def test_every_canned_response_the_handler_names_exists(self):
        from map_logic.ai import ai_handler
        keys = set(ai_handler.LITE_RESPONSE_KEYS.values())
        keys |= {"AI_OFF_ACCEPT", "AI_OFF_REJECT", "AI_OFF_MESSAGE",
                 "GENERIC_ACCEPT", "GENERIC_MESSAGE"}
        for key in sorted(keys):
            with self.subTest(key=key):
                self.assertIn(key, ai_prompts.AI_FALLBACK_RESPONSES)


if __name__ == "__main__":
    unittest.main()
