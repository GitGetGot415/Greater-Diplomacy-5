"""The AI must speak as itself, and ABSOLUTE must let it speak at all.

Two separate faults with the same symptom -- messages that do not read like the
nation sent them.

Nothing ever told the model what voice to write in. Every prompt named the
nation ("You are the leader of X") and left the rest to be inferred, which a
strong model does and a small one does not: on llama3, Switzerland wrote
"Switzerland accepts your offer" into a message already labelled as from
Switzerland.

And should_consult returned len(candidates) > 1, gating on the size of the menu
before the immersion level was consulted at all. Because choosing and phrasing
were deliberately merged into one call, skipping the choice silently skipped the
wording too -- so a nation with exactly one legal option sent its canned line at
every level including ABSOLUTE, whose whole purpose is that the world writes its
own diplomacy. saves/generic message despite absolute ai is almost entirely
"We accept your proposal."
"""

import os
import sys
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import data.constants as c
from map_logic.ai import ai_director, ai_prompts


class VoiceRuleStatedTests(unittest.TestCase):
    """It has to actually be in the prompts, or none of the rest matters."""

    def test_the_shared_prompt_tail_states_the_voice(self):
        tail = ai_prompts.action_rules_and_schema("event", "text")
        self.assertIn(ai_prompts.VOICE_RULE, tail)

    def test_every_long_prompt_inherits_it(self):
        prompts = [ai_prompts.get_unilateral_system_prompt("They declared war."),
                   ai_prompts.get_bilateral_system_prompt(True),
                   ai_prompts.get_bilateral_system_prompt(False, allow_override=True,
                                                          reason="marginal", confidence=0.3)]
        for prompt in prompts:
            with self.subTest(prompt=prompt[:40]):
                self.assertIn("first person plural", prompt)

    def test_the_director_prompt_states_it_too(self):
        """The director's reply is what carries the wording for every proposal
        the AI opens on its own initiative."""
        system, _user = ai_director.build_prompt(None, "Switzerland", [], 3)
        self.assertIn(ai_prompts.VOICE_RULE, system)


class ThirdPersonDetectionTests(unittest.TestCase):

    NATIONS = {"Switzerland": {"name": "Swiss Confederation", "adjective": "Swiss"}}

    def reads_wrong(self, message, nation="Switzerland"):
        return ai_prompts.reads_as_third_person(message, nation, self.NATIONS)

    def test_the_reported_failure_is_caught(self):
        self.assertTrue(self.reads_wrong("Switzerland accepts your offer."))

    def test_the_long_form_name_is_caught(self):
        self.assertTrue(self.reads_wrong("Swiss Confederation rejects these terms."))

    def test_the_adjective_is_caught(self):
        self.assertTrue(self.reads_wrong("Swiss forces will not cross that border."))

    def test_a_quoted_opening_is_still_caught(self):
        self.assertTrue(self.reads_wrong('"Switzerland declines."'))

    def test_first_person_passes(self):
        self.assertFalse(self.reads_wrong("We accept your generous offer."))

    def test_naming_yourself_mid_sentence_is_ordinary_prose(self):
        self.assertFalse(self.reads_wrong("Our claim on Switzerland's borders stands."))

    def test_addressing_someone_then_speaking_is_fine(self):
        self.assertFalse(self.reads_wrong("Switzerland! We will not yield."))

    def test_a_possessive_opening_is_fine(self):
        self.assertFalse(self.reads_wrong("Switzerland's terms are these: we withdraw."))

    def test_naming_a_different_country_is_fine(self):
        self.assertFalse(self.reads_wrong("Austria has overreached, and we will answer."))

    def test_a_prefix_of_the_name_is_not_the_name(self):
        self.assertFalse(self.reads_wrong("Swit is not a country and we know it."))

    def test_nothing_at_all_is_not_third_person(self):
        self.assertFalse(self.reads_wrong(""))
        self.assertFalse(ai_prompts.reads_as_third_person("Anything.", ""))

    def test_it_works_without_a_nation_data_block(self):
        self.assertTrue(ai_prompts.reads_as_third_person("Switzerland accepts.", "Switzerland"))


class DirectorMessageFilterTests(unittest.TestCase):
    """A dropped line costs one piece of flavour; a kept one reads as a bug."""

    NATIONS = {"Switzerland": {"name": "Switzerland", "adjective": "Swiss"}}

    def test_a_third_person_line_is_dropped(self):
        reply = {"messages": {"0": "Switzerland proposes a truce."}}
        self.assertEqual(ai_director.messages_from(reply, "Switzerland", self.NATIONS), {})

    def test_a_first_person_line_is_kept(self):
        reply = {"messages": {"0": "We propose a truce."}}
        self.assertEqual(ai_director.messages_from(reply, "Switzerland", self.NATIONS),
                         {"0": "We propose a truce."})

    def test_one_bad_line_does_not_take_the_good_ones_with_it(self):
        reply = {"messages": {"0": "Switzerland proposes a truce.", "1": "We stand ready."}}
        kept = ai_director.messages_from(reply, "Switzerland", self.NATIONS)
        self.assertEqual(kept, {"1": "We stand ready."})

    def test_without_a_nation_nothing_is_filtered(self):
        """parse() is called with no nation from older paths; they must not break."""
        reply = {"messages": {"0": "Switzerland proposes a truce."}}
        self.assertEqual(ai_director.messages_from(reply), {"0": "Switzerland proposes a truce."})

    def test_parse_passes_the_nation_through(self):
        reply = {"picks": [], "messages": {"0": "Switzerland proposes a truce."}}
        _chosen, messages = ai_director.parse(reply, [], 3, "Switzerland", self.NATIONS)
        self.assertEqual(messages, {})


class ShouldConsultTests(unittest.TestCase):
    """Choosing and phrasing are two questions, not one."""

    def test_a_real_choice_is_always_worth_asking_about(self):
        self.assertTrue(ai_director.should_consult(["a", "b"], wants_prose=False))

    def test_a_forced_choice_is_skipped_when_nobody_wants_the_prose(self):
        """The cost lever this was added for: on a large map, most nations most
        turns. That must keep working."""
        self.assertFalse(ai_director.should_consult(["a"], wants_prose=False))

    def test_a_forced_choice_is_asked_when_the_prose_is_the_point(self):
        self.assertTrue(ai_director.should_consult(["a"], wants_prose=True))

    def test_an_empty_menu_is_never_worth_a_request(self):
        self.assertFalse(ai_director.should_consult([], wants_prose=True))
        self.assertFalse(ai_director.should_consult([], wants_prose=False))


class ProactiveWordingTests(unittest.TestCase):
    """The reply was in hand and every branch threw it away for a constant."""

    def setUp(self):
        from map_logic.diplomacy import diplomacy_processor
        self.dp = diplomacy_processor
        self.nation_data = {
            "Switzerland": {"at_war_with": ["Austria"], "faction": "", "puppets": [],
                            "master": "", "diplo_cooldowns": {}, "truces": {},
                            "pending_diplomacy": {}, "name": "Switzerland",
                            "adjective": "Swiss"},
            "Austria": {"at_war_with": ["Switzerland"], "faction": "", "puppets": [],
                        "master": "", "diplo_cooldowns": {}, "truces": {},
                        "pending_diplomacy": {}, "name": "Austria"},
        }

    class Screen:
        class Clock:
            total_turns = 5
        time_manager = Clock()

        def __init__(self, nation_data):
            self.nation_data = nation_data
            self.map_data = {}

    def retaliate(self, message, action="CEASEFIRE"):
        out = []
        self.dp._process_ai_retaliation(
            self.Screen(self.nation_data), ["Switzerland", "Austria"], out,
            "Switzerland",
            {"action": action, "action_target": "Austria", "message": message,
             "follow_up_action": "NONE", "follow_up_target": "NONE"})
        return [row[4] for row in out]

    def test_the_leaders_own_words_are_what_gets_sent(self):
        self.assertEqual(self.retaliate("We have bled enough. Name your terms."),
                         ["We have bled enough. Name your terms."])

    def test_an_empty_reply_falls_back_to_the_canned_line(self):
        self.assertIn(self.retaliate("")[0], ai_prompts.lines_for("PROACTIVE_CEASEFIRE"))

    def test_a_third_person_reply_falls_back_too(self):
        self.assertIn(self.retaliate("Switzerland offers a ceasefire.")[0],
                      ai_prompts.lines_for("PROACTIVE_CEASEFIRE"))

    def test_a_call_to_arms_carries_its_own_words_as_well(self):
        self.nation_data["Switzerland"]["faction"] = "Pact"
        self.nation_data["Austria"]["faction"] = "Pact"
        self.assertEqual(self.retaliate("Our line is breaking. Come now.", "CALL_TO_ARMS"),
                         ["Our line is breaking. Come now."])

    def test_a_war_declaration_still_carries_its_wargoal(self):
        """Its message field is the wargoal, not prose -- the same exception
        PROACTIVE_PROPOSALS.queued_message already makes."""
        real = c.AI_LLM_DIRECT_RETALIATION
        c.AI_LLM_DIRECT_RETALIATION = True
        try:
            sent = self.retaliate("We march at dawn.", "WAR_DECLARATION")
        finally:
            c.AI_LLM_DIRECT_RETALIATION = real
        self.assertEqual(sent, [c.WARGOAL_NO_CB])


if __name__ == "__main__":
    unittest.main()
