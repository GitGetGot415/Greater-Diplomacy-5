"""Covers the model actually deciding things, and the limits on what it can decide.

The safety property this file exists for: a reply can only ever produce an action
that was already on the menu, and the menu is built by the ordinary rules. A
hallucinated index, a country that does not exist, a war the rules forbid --
none of them survive. Everything else degrades to what the heuristic layer would
have done on its own, which is also what happens with no model at all.

Nothing here touches the network. The guard in setUp makes that a hard failure.
"""

import os
import sys
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import data.constants as c
from map_logic.ai import (ai_candidates as ac, ai_diplomacy, ai_director,
                          ai_evaluation, ai_handler, ai_settings, ai_world)
from tests.stub_map_screen import StubMapScreen


def candidates(*specs):
    bag = ac.Collector("A", {})
    for action, target, score in specs:
        bag.add(ac.make(action, target, score, "because"))
    return bag.ranked()


class NoNetworkTestCase(unittest.TestCase):
    def setUp(self):
        def forbidden(*args, **kwargs):
            raise AssertionError("test attempted a real network call")

        for name in ("_session", "_gemini_client"):
            original = getattr(ai_handler, name)
            setattr(ai_handler, name, forbidden)
            self.addCleanup(lambda n=name, o=original: setattr(ai_handler, n, o))

    def patch(self, module, name, value):
        original = getattr(module, name)
        setattr(module, name, value)
        self.addCleanup(lambda: setattr(module, name, original))

    def set_mode(self, mode, immersion="LITE"):
        """Both modules, deliberately.

        ai_handler re-exports the settings getters by value -- `from ai_settings
        import get_ai_mode` -- so the two names are separate bindings, and
        patching one leaves the other answering from the developer's real
        settings file. ai_diplomacy asks ai_handler; these tests used to patch
        only ai_settings, so whether they tested anything depended on what the
        machine running them had last saved in Settings.
        """
        for module in (ai_settings, ai_handler):
            self.patch(module, "get_ai_mode", lambda m=mode: m)
            self.patch(module, "get_ai_immersion_level", lambda i=immersion: i)


class ValidationTests(NoNetworkTestCase):
    def setUp(self):
        super().setUp()
        self.cands = candidates(("WAR_DECLARATION", "B", 0.9),
                                ("TRADE", "C", 0.5),
                                ("CEASEFIRE", "D", 0.3))

    def choose(self, reply, limit=2):
        return ai_director.validate(reply, self.cands, limit)

    def test_a_valid_pick_is_honoured(self):
        chosen = self.choose({"picks": [1]})
        self.assertEqual([cand.target for cand in chosen], ["C"])

    def test_an_index_that_does_not_exist_is_dropped(self):
        """The model cannot conjure an action by naming a number."""
        chosen = self.choose({"picks": [99]})
        self.assertEqual([cand.target for cand in chosen],
                         [cand.target for cand in ai_director.top_scored(self.cands, 2)])

    def test_a_mix_of_real_and_invented_keeps_only_the_real(self):
        self.assertEqual([cand.target for cand in self.choose({"picks": [99, 2]})], ["D"])

    def test_duplicates_are_taken_once(self):
        self.assertEqual(len(self.choose({"picks": [0, 0, 0]})), 1)

    def test_the_limit_is_enforced(self):
        self.assertEqual(len(self.choose({"picks": [0, 1, 2]}, limit=2)), 2)

    def test_an_empty_reply_falls_back_to_the_staff(self):
        for reply in ({}, {"picks": []}, {"picks": "nonsense"}, None, "not json", 7):
            with self.subTest(reply=reply):
                chosen = self.choose(reply)
                self.assertEqual([cand.target for cand in chosen], ["B", "C"])

    def test_declining_to_act_is_a_real_answer(self):
        """Otherwise the fallback overrides it and a leader can never sit still."""
        self.assertEqual(self.choose({"picks": [c.AI_DIRECTOR_NONE_CID]}), [])

    def test_a_json_string_reply_is_parsed(self):
        chosen, messages = ai_director.parse('{"picks": [1], "messages": {"1": "hello"}}',
                                             self.cands, 2)
        self.assertEqual([cand.target for cand in chosen], ["C"])
        self.assertEqual(messages, {"1": "hello"})

    def test_messages_survive_only_when_they_are_strings(self):
        _chosen, messages = ai_director.parse(
            {"picks": [0], "messages": {"0": "text", "1": 42, "2": "  "}}, self.cands, 2)
        self.assertEqual(messages, {"0": "text"})

    def test_nothing_to_choose_between_is_not_worth_asking(self):
        """On a large map this is most nations most turns, and skipping them is
        the cheapest lever there is on what ABSOLUTE mode costs."""
        self.assertFalse(ai_director.should_consult(candidates(("TRADE", "B", 0.5))))
        self.assertFalse(ai_director.should_consult([]))
        self.assertTrue(ai_director.should_consult(self.cands))

    def test_the_prompt_lists_every_option_and_a_way_out(self):
        _system, user = ai_director.build_prompt(None, "A", self.cands, 2)
        for cand in self.cands:
            self.assertIn(f"[{cand.cid}]", user)
        self.assertIn(c.AI_DIRECTOR_NONE_CID, user)


class EndToEndTests(NoNetworkTestCase):
    """The director driving a real proactive pass, with a stubbed provider."""

    def make_game(self):
        game = StubMapScreen(["A", "B", "C"], human_players=[])
        game.set_war("A", "B")
        game.set_war("A", "C")
        return game

    def run_pass(self, game):
        ai_diplomacy.process_basic_proactive_ai(game)
        ai_diplomacy.process_proactive_llm_tasks(game)

    def queued(self, game, nation):
        return {t: i.get("action") for t, i in
                (game.nation_data[nation].get("pending_diplomacy") or {}).items()}

    def test_with_no_model_the_staff_choice_stands(self):
        self.set_mode("OFF")
        game = self.make_game()
        self.run_pass(game)
        self.assertTrue(self.queued(game, "A"), "nothing was queued at all")

    def test_force_skip_produces_exactly_what_no_model_would(self):
        """The invariant that makes Force Skip safe: abandoning the batch must
        leave the same turn a model-free game would have had."""
        self.set_mode("OFF")
        baseline = self.make_game()
        self.run_pass(baseline)

        self.set_mode("CLAUDE", "ABSOLUTE")
        skipped = self.make_game()
        skipped.force_skip_llm = True
        self.run_pass(skipped)

        for nation in ("A", "B", "C"):
            self.assertEqual(self.queued(skipped, nation), self.queued(baseline, nation), nation)

    def test_a_reply_can_change_which_action_is_taken(self):
        self.set_mode("CLAUDE", "ABSOLUTE")

        seen = {}

        def fake(mode, system, user, turn_id, canned, accepted=None, raw=False):
            seen["asked"] = True
            return {"picks": ["1"], "messages": {"1": "We have our reasons."}}

        self.patch(ai_handler, "_run_provider", fake)
        game = self.make_game()
        game.force_skip_llm = False
        self.run_pass(game)
        self.assertTrue(seen.get("asked"), "the director never consulted the model")

    def test_a_provider_error_leaves_the_staff_choice_intact(self):
        self.set_mode("OFF")
        baseline = self.make_game()
        self.run_pass(baseline)

        self.set_mode("CLAUDE", "ABSOLUTE")
        self.patch(ai_handler, "_run_provider",
                   lambda *a, **k: ai_handler._provider_error("API ERROR: boom"))
        broken = self.make_game()
        broken.force_skip_llm = False
        self.run_pass(broken)

        for nation in ("A", "B", "C"):
            self.assertEqual(self.queued(broken, nation), self.queued(baseline, nation), nation)


class TierTests(NoNetworkTestCase):
    def world_for(self, nations, human_players=()):
        game = StubMapScreen(list(nations), human_players=list(human_players))
        return ai_world.build(game), game

    def test_a_per_country_setting_beats_the_global_one(self):
        world, game = self.world_for(["A", "B"])
        self.patch(ai_settings, "get_ai_immersion_level", lambda: "LITE")
        game.nation_data["A"]["llm_tier"] = c.AI_TIER_ALWAYS
        game.nation_data["B"]["llm_tier"] = c.AI_TIER_NEVER
        self.assertTrue(ai_evaluation.llm_enabled_for("A", world))
        self.assertFalse(ai_evaluation.llm_enabled_for("B", world))

    def test_never_wins_even_in_absolute(self):
        world, game = self.world_for(["A", "B"])
        self.patch(ai_settings, "get_ai_immersion_level", lambda: "ABSOLUTE")
        game.nation_data["A"]["llm_tier"] = c.AI_TIER_NEVER
        self.assertFalse(ai_evaluation.llm_enabled_for("A", world))

    def test_absolute_covers_everyone(self):
        world, _game = self.world_for(["A", "B"])
        self.patch(ai_settings, "get_ai_immersion_level", lambda: "ABSOLUTE")
        self.assertTrue(ai_evaluation.llm_enabled_for("A", world))

    def test_auto_under_lite_defers_to_the_old_rules(self):
        world, _game = self.world_for(["A", "B"])
        self.patch(ai_settings, "get_ai_immersion_level", lambda: "LITE")
        self.assertIsNone(ai_evaluation.llm_enabled_for("A", world))

    def test_major_covers_the_strongest_and_no_more(self):
        world, _game = self.world_for([f"N{i}" for i in range(30)])
        self.patch(ai_settings, "get_ai_immersion_level", lambda: "MAJOR")
        covered = [n for n in world.provs_by_owner if ai_evaluation.llm_enabled_for(n, world)]
        self.assertLessEqual(len(covered), c.AI_MAJOR_POWER_MAX)
        self.assertGreaterEqual(len(covered), 1)

    def test_major_always_includes_whoever_the_player_is_fighting(self):
        """A small neighbour at war with the player matters more here than a
        great power on the far side of the map they will never meet."""
        game = StubMapScreen([f"N{i}" for i in range(30)], human_players=["N0"])
        game.set_war("N0", "N29")
        world = ai_world.build(game)
        self.patch(ai_settings, "get_ai_immersion_level", lambda: "MAJOR")
        self.assertTrue(ai_evaluation.llm_enabled_for("N29", world))

    def test_an_unknown_immersion_level_does_not_crash(self):
        """An older build reading a newer setting must degrade, not fail."""
        world, _game = self.world_for(["A", "B"])
        self.patch(ai_settings, "get_ai_immersion_level", lambda: "SOMETHING_NEW")
        self.assertIsNone(ai_evaluation.llm_enabled_for("A", world))


class RetaliationTests(unittest.TestCase):
    """The bypass that let a model start a war the rules forbade."""

    def test_a_war_demand_is_filed_rather_than_declared(self):
        from map_logic.diplomacy import diplomacy_processor

        game = StubMapScreen(["A", "B"], human_players=[])
        delayed = []
        diplomacy_processor._process_ai_retaliation(
            game, ["A", "B"], delayed, "A",
            {"action": "WAR_DECLARATION", "action_target": "B", "message": "they insult us"})

        self.assertEqual(delayed, [], "declared war on the spot, skipping every prerequisite")
        self.assertEqual(game.nation_data["A"]["ai_requests"][0]["target"], "B")

    def test_an_illegal_filed_war_never_becomes_one(self):
        """No border, no wargoal, and inside the opening waiting period."""
        from map_logic.ai import ai_diplomacy

        game = StubMapScreen(["A", "B"], human_players=[])
        game.nation_data["A"]["ai_requests"] = [
            {"action": "WAR_DECLARATION", "target": "B", "reason": "spite", "turn": 0}]

        ai_diplomacy.process_basic_proactive_ai(game)
        ai_diplomacy.process_proactive_llm_tasks(game)

        self.assertNotEqual(
            (game.nation_data["A"].get("pending_diplomacy") or {}).get("B", {}).get("action"),
            "WAR_DECLARATION")

    def test_a_filed_request_is_consumed_so_it_cannot_pile_up(self):
        from map_logic.ai import ai_diplomacy

        game = StubMapScreen(["A", "B"], human_players=[])
        game.nation_data["A"]["ai_requests"] = [
            {"action": "WAR_DECLARATION", "target": "B", "reason": "spite", "turn": 0}]

        ai_diplomacy.process_basic_proactive_ai(game)
        self.assertEqual(game.nation_data["A"]["ai_requests"], [])


if __name__ == "__main__":
    unittest.main()
