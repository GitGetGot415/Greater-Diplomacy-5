"""Covers summits and the promises they produce.

A transcript is not the point; what it is turned into is. So most of this file
is about the commitment surviving contact with the rest of the game: mirrored on
both sides, saved, enforced by the same rules that decide wars, and expensive to
break for long enough that keeping one is worth something.

The model is never trusted for state. validate_terms is the boundary, and it is
tested against exactly the sort of thing a model actually says.
"""

import os
import sys
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import data.constants as c
from data import queries
from map_logic.ai import (ai_commitments as cm, ai_negotiation as neg,
                          ai_opinion, ai_personality, ai_world)
from tests.stub_map_screen import StubMapScreen


def game_with(*nations, human_players=()):
    return StubMapScreen(list(nations), human_players=list(human_players))


class MakeTests(unittest.TestCase):
    def setUp(self):
        self.game = game_with("A", "B", "C")
        self.nd = self.game.nation_data

    def test_a_promise_is_recorded_on_both_sides(self):
        """One party remembering is not a promise -- the wronged side has to be
        able to notice it was broken."""
        cm.make(self.nd, "A", "B", cm.NON_AGGRESSION, turns=20)
        self.assertTrue(cm.has_non_aggression(self.nd, "A", "B"))
        self.assertTrue(cm.has_non_aggression(self.nd, "B", "A"))

    def test_both_copies_share_an_id(self):
        entry = cm.make(self.nd, "A", "B", cm.NON_AGGRESSION)
        mirror = cm.all_for(self.nd, "B")[0]
        self.assertEqual(entry["id"], mirror["id"])

    def test_agreeing_the_same_thing_twice_is_one_promise(self):
        cm.make(self.nd, "A", "B", cm.NON_AGGRESSION, made_turn=1)
        cm.make(self.nd, "A", "B", cm.NON_AGGRESSION, made_turn=2)
        self.assertEqual(len(cm.active_with(self.nd, "A", "B", cm.NON_AGGRESSION)), 1)

    def test_an_unknown_type_is_refused(self):
        self.assertIsNone(cm.make(self.nd, "A", "B", "ANNEX_EVERYTHING"))

    def test_a_nation_cannot_promise_itself_anything(self):
        self.assertIsNone(cm.make(self.nd, "A", "A", cm.NON_AGGRESSION))

    def test_a_joint_war_needs_a_real_target(self):
        self.assertIsNone(cm.make(self.nd, "A", "B", cm.JOINT_WAR, target=None))
        self.assertIsNone(cm.make(self.nd, "A", "B", cm.JOINT_WAR, target="Atlantis"))
        self.assertIsNotNone(cm.make(self.nd, "A", "B", cm.JOINT_WAR, target="C"))

    def test_it_survives_a_save_round_trip(self):
        """Commitments live on nation_data, which is serialized wholesale."""
        import json
        cm.make(self.nd, "A", "B", cm.JOINT_WAR, target="C", turns=15)
        restored = json.loads(json.dumps(self.nd))
        self.assertEqual(cm.joint_war_target(restored, "A", "B"), "C")


class EnforcementTests(unittest.TestCase):
    """A promise nothing enforces is just chat."""

    def setUp(self):
        self.game = game_with("A", "B", "C")
        self.nd = self.game.nation_data
        self.world = ai_world.build(self.game)

    def set_loyalty(self, nation, value):
        base = {t: 0.5 for t in ai_personality.TRAITS}
        base["loyalty"] = value
        ai_personality.set_authored(self.nd, nation, base)

    def test_a_pact_restrains_a_loyal_nation_far_more_than_a_faithless_one(self):
        """The interesting outcome is that a faithless nation still breaks it."""
        cm.make(self.nd, "A", "B", cm.NON_AGGRESSION, turns=20)

        self.set_loyalty("A", 1.0)
        loyal = cm.war_restraint(self.nd, "A", "B")
        self.set_loyalty("A", 0.0)
        faithless = cm.war_restraint(self.nd, "A", "B")

        self.assertGreater(loyal, faithless)
        self.assertGreater(faithless, 0.0, "even the faithless honour a pact a little")

    def test_no_pact_means_no_restraint(self):
        self.assertEqual(cm.war_restraint(self.nd, "A", "B"), 0.0)

    def test_a_pact_lowers_the_appetite_for_war(self):
        self.set_loyalty("A", 0.9)
        before = ai_opinion.war_desire(self.world, "A", "B")
        cm.make(self.nd, "A", "B", cm.NON_AGGRESSION, turns=20)
        after = ai_opinion.war_desire(self.world, "A", "B")
        self.assertLess(after, before)

    def test_a_joint_war_promise_is_honoured_when_they_call(self):
        from map_logic.ai import ai_evaluation
        cm.make(self.nd, "A", "B", cm.JOINT_WAR, target="C", turns=20)
        verdict = ai_evaluation.evaluate_verdict(
            self.nd, self.game.map_data, "A", "B", "CALL_TO_ARMS")
        self.assertTrue(verdict.accepted)

    def test_without_the_promise_a_stranger_is_refused(self):
        from map_logic.ai import ai_evaluation
        verdict = ai_evaluation.evaluate_verdict(
            self.nd, self.game.map_data, "A", "B", "CALL_TO_ARMS")
        self.assertFalse(verdict.accepted)

    def test_an_access_agreement_opens_the_border(self):
        from map_logic.ai import ai_evaluation
        cm.make(self.nd, "A", "B", cm.MILITARY_ACCESS, turns=20)
        verdict = ai_evaluation.evaluate_verdict(
            self.nd, self.game.map_data, "A", "B", "REQ_MILITARY_ACCESS")
        self.assertTrue(verdict.accepted)


class TickTests(unittest.TestCase):
    def setUp(self):
        self.game = game_with("A", "B", "C")
        self.nd = self.game.nation_data

    def test_a_promise_ages_a_turn_at_a_time(self):
        cm.make(self.nd, "A", "B", cm.NON_AGGRESSION, turns=3)
        cm.tick(self.game)
        self.assertEqual(cm.active_with(self.nd, "A", "B")[0]["turns_left"], 2)

    def test_running_its_course_earns_goodwill_on_both_sides(self):
        cm.make(self.nd, "A", "B", cm.NON_AGGRESSION, turns=1)
        cm.tick(self.game)
        self.assertEqual(cm.active_with(self.nd, "A", "B"), [])
        self.assertEqual(cm.all_for(self.nd, "A")[0]["status"], cm.HONORED)
        self.assertGreater(queries.get_relation_score("A", "B", self.nd), 0)
        self.assertGreater(queries.get_relation_score("B", "A", self.nd), 0)

    def test_attacking_a_pact_partner_is_a_betrayal(self):
        cm.make(self.nd, "A", "B", cm.NON_AGGRESSION, turns=20)
        self.game.set_war("A", "B")
        cm.tick(self.game)
        self.assertEqual(cm.all_for(self.nd, "A")[0]["status"], cm.BROKEN)

    def test_the_grudge_is_durable_rather_than_fading(self):
        """REL_MOD_BROKEN_COMMITMENT is stored with decay 0 precisely so this
        still stings in fifty turns -- a betrayal nobody remembers next decade
        is not a betrayal, it is a free move."""
        cm.make(self.nd, "A", "B", cm.NON_AGGRESSION, turns=20)
        self.nd["A"]["claims"] = [2]        # A has the wargoal, so A is the aggressor
        self.game.set_war("A", "B")
        cm.tick(self.game)

        mods = self.nd["B"]["temp_modifiers"]["A"]
        entry = next(iter(mods.values()))
        self.assertEqual(queries.modifier_value(entry), c.REL_MOD_BROKEN_COMMITMENT)
        self.assertEqual(queries.modifier_decay(entry), 0)
        self.assertEqual(queries.modifier_turns(entry), c.REL_MOD_BROKEN_COMMITMENT_TURNS)

    def test_the_wronged_party_is_not_punished(self):
        cm.make(self.nd, "A", "B", cm.NON_AGGRESSION, turns=20)
        self.nd["A"]["claims"] = [2]
        self.game.set_war("A", "B")
        cm.tick(self.game)
        self.assertNotIn("A", self.nd.get("B", {}).get("temp_modifiers", {}).get("B", {}))
        self.assertEqual(self.nd["A"].get("temp_modifiers", {}).get("B", {}), {})

    def test_a_settled_promise_is_not_settled_twice(self):
        cm.make(self.nd, "A", "B", cm.NON_AGGRESSION, turns=1)
        cm.tick(self.game)
        before = queries.get_relation_score("A", "B", self.nd)
        cm.tick(self.game)
        self.assertEqual(queries.get_relation_score("A", "B", self.nd), before)

    def test_the_record_stays_bounded(self):
        """Settled promises are saved with everything else."""
        for i in range(c.AI_COMMITMENT_HISTORY_MAX + 20):
            cm.make(self.nd, "A", "B", cm.NON_AGGRESSION, turns=1, made_turn=i)
            cm.tick(self.game)
        self.assertLessEqual(len(cm.all_for(self.nd, "A")), c.AI_COMMITMENT_HISTORY_MAX)


class ReputationTests(unittest.TestCase):
    def setUp(self):
        self.game = game_with("A", "B")
        self.nd = self.game.nation_data

    def test_an_unknown_nation_gets_the_benefit_of_the_doubt(self):
        self.assertEqual(cm.reputation(self.nd, "A"), c.AI_DEFAULT_REPUTATION)

    def test_keeping_promises_builds_it_and_breaking_them_ruins_it(self):
        for i in range(3):
            cm.make(self.nd, "A", "B", cm.NON_AGGRESSION, turns=1, made_turn=i)
            cm.tick(self.game)
        good = cm.reputation(self.nd, "A")

        cm.make(self.nd, "A", "B", cm.NON_AGGRESSION, turns=20, made_turn=99)
        self.nd["A"]["claims"] = [2]
        self.game.set_war("A", "B")
        cm.tick(self.game)

        self.assertGreater(good, cm.reputation(self.nd, "A"))


class ValidationTests(unittest.TestCase):
    """The boundary the model's output crosses. Nothing past it is trusted."""

    def setUp(self):
        self.game = game_with("A", "B", "C")
        self.world = ai_world.build(self.game)

    def validate(self, terms):
        return neg.validate_terms(self.world, "A", "B", terms)

    def test_a_sound_term_survives(self):
        out = self.validate([{"type": "NON_AGGRESSION", "turns": 20}])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["type"], cm.NON_AGGRESSION)

    def test_an_invented_type_is_dropped(self):
        self.assertEqual(self.validate([{"type": "VASSALIZE_THEM"}]), [])

    def test_a_country_that_does_not_exist_is_dropped(self):
        self.assertEqual(self.validate([{"type": "JOINT_WAR", "target": "Atlantis"}]), [])

    def test_a_joint_war_against_one_of_the_parties_is_dropped(self):
        self.assertEqual(self.validate([{"type": "JOINT_WAR", "target": "B"}]), [])

    def test_one_bad_clause_does_not_void_a_sound_agreement(self):
        out = self.validate([{"type": "NONSENSE"},
                             {"type": "NON_AGGRESSION", "turns": 10}])
        self.assertEqual(len(out), 1)

    def test_a_term_length_is_clamped_to_something_sane(self):
        out = self.validate([{"type": "NON_AGGRESSION", "turns": 99999}])
        self.assertEqual(out[0]["turns"], c.AI_NEGOTIATION_MAX_TERM_TURNS)

    def test_a_nonsense_length_falls_back_to_the_default(self):
        out = self.validate([{"type": "NON_AGGRESSION", "turns": "soon"}])
        self.assertEqual(out[0]["turns"], c.AI_NEGOTIATION_DEFAULT_TURNS)

    def test_a_resource_transfer_needs_a_real_resource_and_amount(self):
        self.assertEqual(self.validate([{"type": "RESOURCE_TRANSFER",
                                         "resource": "gold", "amount": 100}]), [])
        self.assertEqual(self.validate([{"type": "RESOURCE_TRANSFER",
                                         "resource": "fuel", "amount": -5}]), [])
        out = self.validate([{"type": "RESOURCE_TRANSFER", "resource": "fuel",
                              "amount": 500, "from": "B"}])
        self.assertEqual(out[0]["params"], {"resource": "fuel", "amount": 500, "from": "B"})

    def test_a_transfer_from_a_third_party_is_reassigned_not_honoured(self):
        out = self.validate([{"type": "RESOURCE_TRANSFER", "resource": "fuel",
                              "amount": 500, "from": "C"}])
        self.assertEqual(out[0]["params"]["from"], "A")

    def test_a_non_aggression_pact_cannot_end_a_running_war(self):
        """That is a ceasefire, which is a different instrument with its own rules."""
        self.game.set_war("A", "B")
        world = ai_world.build(self.game)
        self.assertEqual(neg.validate_terms(world, "A", "B",
                                            [{"type": "NON_AGGRESSION"}]), [])

    def test_garbage_in_any_shape_is_survivable(self):
        for junk in (None, "terms", 42, [None], [[]], [{"type": None}]):
            with self.subTest(junk=junk):
                self.assertEqual(self.validate(junk), [])

    def test_the_number_of_terms_is_capped(self):
        out = self.validate([{"type": "NON_AGGRESSION"}] * 50)
        self.assertLessEqual(len(out), c.AI_NEGOTIATION_MAX_TERMS)


class PairSelectionTests(unittest.TestCase):
    def setUp(self):
        self.game = game_with(*[f"N{i}" for i in range(10)])
        self.world = ai_world.build(self.game)

    def select(self, driven=None, turns=100):
        names = [f"N{i}" for i in range(10)]
        predicate = driven or (lambda n: True)
        return neg.select_pairs(self.world, names, predicate, turns)

    def test_only_model_driven_nations_meet(self):
        """Half a conversation is nothing."""
        allowed = {"N0", "N1"}
        pairs = self.select(driven=lambda n: n in allowed)
        for pair in pairs:
            self.assertIn(pair["a"], allowed)
            self.assertIn(pair["b"], allowed)

    def test_the_number_of_summits_is_capped(self):
        self.assertLessEqual(len(self.select()), c.AI_NEGOTIATION_MAX_PAIRS)

    def test_a_nation_attends_at_most_one_summit_a_turn(self):
        seen = set()
        for pair in self.select():
            self.assertNotIn(pair["a"], seen)
            self.assertNotIn(pair["b"], seen)
            seen.update((pair["a"], pair["b"]))

    def test_a_pair_that_just_met_does_not_meet_again(self):
        neg.record_summit(self.game.nation_data, "N0", "N1", 100)
        pairs = self.select(turns=100 + c.AI_NEGOTIATION_COOLDOWN - 1)
        self.assertNotIn({"N0", "N1"}, [{p["a"], p["b"]} for p in pairs])

    def test_but_it_can_once_the_cooldown_has_run(self):
        neg.record_summit(self.game.nation_data, "N0", "N1", 100)
        self.game.set_war("N0", "N5")
        self.game.set_war("N1", "N5")
        world = ai_world.build(self.game)
        pairs = neg.select_pairs(world, [f"N{i}" for i in range(10)], lambda n: True,
                                 100 + c.AI_NEGOTIATION_COOLDOWN)
        self.assertIn({"N0", "N1"}, [{p["a"], p["b"]} for p in pairs])

    def test_co_belligerents_have_the_most_to_discuss(self):
        self.game.set_war("N0", "N9")
        self.game.set_war("N1", "N9")
        world = ai_world.build(self.game)
        shared = neg.pressure(world, "N0", "N1")
        unrelated = neg.pressure(world, "N2", "N3")
        self.assertGreater(shared, unrelated)

    def test_nobody_wants_a_pact_with_a_known_oathbreaker(self):
        self.game.set_war("N0", "N9")
        self.game.set_war("N1", "N9")
        world = ai_world.build(self.game)
        honest = neg.pressure(world, "N0", "N1")

        cm.make(self.game.nation_data, "N1", "N8", cm.NON_AGGRESSION, turns=20)
        for entry in cm.all_for(self.game.nation_data, "N1"):
            entry["status"] = cm.BROKEN
        world = ai_world.build(self.game)
        self.assertLess(neg.pressure(world, "N0", "N1"), honest)


class SummitTests(unittest.TestCase):
    """A whole summit, with the provider stubbed. No network is touched."""

    def setUp(self):
        from map_logic.ai import ai_handler, ai_settings

        def forbidden(*args, **kwargs):
            raise AssertionError("test attempted a real network call")

        for module, name in ((ai_handler, "_session"), (ai_handler, "_gemini_client")):
            original = getattr(module, name)
            setattr(module, name, forbidden)
            self.addCleanup(lambda m=module, n=name, o=original: setattr(m, n, o))

        self.set_mode("CLAUDE", "ABSOLUTE")

        # Two co-belligerents, so they have something to talk about.
        self.game = game_with("A", "B", "C", human_players=[])
        self.game.force_skip_llm = False
        self.game.set_war("A", "C")
        self.game.set_war("B", "C")

    def patch(self, module, name, value):
        original = getattr(module, name)
        setattr(module, name, value)
        self.addCleanup(lambda: setattr(module, name, original))

    def set_mode(self, mode, immersion):
        """Both modules, deliberately.

        ai_handler re-exports the settings getters by value -- `from ai_settings
        import get_ai_mode` -- so the two names are separate bindings and
        patching one leaves the other answering from the real settings file.
        """
        from map_logic.ai import ai_handler, ai_settings
        for module in (ai_settings, ai_handler):
            self.patch(module, "get_ai_mode", lambda m=mode: m)
            self.patch(module, "get_ai_immersion_level", lambda i=immersion: i)

    def stub_provider(self, closing_reply):
        from map_logic.ai import ai_handler
        state = {"calls": 0}

        def fake(mode, system, user, turn_id, canned, accepted=None, raw=False):
            state["calls"] += 1
            if "closing" in system:
                return closing_reply
            return {"message": f"line {state['calls']}"}

        self.patch(ai_handler, "_run_provider", fake)
        return state

    def run_summits(self):
        from map_logic.ai import ai_diplomacy
        ai_diplomacy.process_summits(self.game)

    def test_an_agreement_becomes_a_commitment_on_both_sides(self):
        self.stub_provider({"agreed": True, "message": "Then we are agreed.",
                            "terms": [{"type": "NON_AGGRESSION", "turns": 25}]})
        self.run_summits()
        self.assertTrue(cm.has_non_aggression(self.game.nation_data, "A", "B"))
        self.assertTrue(cm.has_non_aggression(self.game.nation_data, "B", "A"))

    def test_the_transcript_reaches_both_inboxes(self):
        """So a spectator can read the whole meeting afterwards."""
        self.stub_provider({"agreed": False, "message": "We are done here.", "terms": []})
        self.run_summits()
        self.assertTrue(self.game.nation_data["A"]["inbox"])
        self.assertTrue(self.game.nation_data["B"]["inbox"])

    def test_talks_that_agree_nothing_are_a_normal_outcome(self):
        self.stub_provider({"agreed": False, "message": "We are done here.", "terms": []})
        self.run_summits()
        self.assertEqual(cm.active_with(self.game.nation_data, "A", "B"), [])

    def test_invented_terms_produce_no_commitment(self):
        """The model can say anything; only validated terms change the game."""
        self.stub_provider({"agreed": True, "message": "Agreed.",
                            "terms": [{"type": "GIVE_US_EVERYTHING"},
                                      {"type": "JOINT_WAR", "target": "Atlantis"}]})
        self.run_summits()
        self.assertEqual(cm.all_for(self.game.nation_data, "A"), [])

    def test_a_summit_is_recorded_so_the_pair_does_not_meet_again_at_once(self):
        self.stub_provider({"agreed": False, "message": "Done.", "terms": []})
        self.run_summits()
        self.assertIn("B", self.game.nation_data["A"].get("summit_log", {}))

    def test_nothing_happens_with_the_model_off(self):
        self.set_mode("OFF", "ABSOLUTE")
        self.stub_provider({"agreed": True, "terms": [{"type": "NON_AGGRESSION"}]})
        self.run_summits()
        self.assertEqual(cm.all_for(self.game.nation_data, "A"), [])

    def test_nothing_happens_below_the_major_tier(self):
        """FULL and below pay nothing for summits at all."""
        self.set_mode("CLAUDE", "FULL")
        self.stub_provider({"agreed": True, "terms": [{"type": "NON_AGGRESSION"}]})
        self.run_summits()
        self.assertEqual(cm.all_for(self.game.nation_data, "A"), [])

    def test_a_provider_failure_leaves_no_half_agreement(self):
        from map_logic.ai import ai_handler
        self.patch(ai_handler, "_run_provider",
                   lambda *a, **k: ai_handler._provider_error("API ERROR: boom"))
        self.run_summits()
        self.assertEqual(cm.all_for(self.game.nation_data, "A"), [])
        self.assertEqual(self.game.nation_data["A"]["inbox"], [])

    def test_force_skip_produces_no_commitments(self):
        self.game.force_skip_llm = True
        self.stub_provider({"agreed": True, "terms": [{"type": "NON_AGGRESSION"}]})
        self.run_summits()
        self.assertEqual(cm.all_for(self.game.nation_data, "A"), [])


if __name__ == "__main__":
    unittest.main()
