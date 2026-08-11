"""Covers the single provider seam every LLM call now goes through.

There used to be two copies of the dispatch ladder -- one in ai_handler, one
inlined in ai_evaluation.generate_proactive_text -- and they had drifted: the
second built its own Gemini client, and reported provider failures as the
reply text, so a bad API key was delivered to the player as the wording of a
war declaration. Folding them left one function to stub, which is what makes
the director and negotiation phases testable without a network.

Nothing here touches the network. The guard in setUp makes that a hard failure
rather than a slow test.
"""

import os
import sys
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from map_logic.ai import ai_evaluation, ai_handler


class NoNetworkTestCase(unittest.TestCase):
    """Fails loudly if anything under test reaches for a socket."""

    def setUp(self):
        def forbidden(*args, **kwargs):
            raise AssertionError("test attempted a real network call")

        self._patches = []
        if ai_handler.requests is not None:
            self._patch(ai_handler, "_session", forbidden)
        self._patch(ai_handler, "_gemini_client", forbidden)

    def _patch(self, module, name, value):
        original = getattr(module, name)
        self._patches.append((module, name, original))
        setattr(module, name, value)
        self.addCleanup(lambda: setattr(module, name, original))


class DispatchTests(NoNetworkTestCase):
    def stub_calls(self, result):
        """Points every provider branch at one recorded fake."""
        seen = {}

        def fake(*args, **kwargs):
            seen["turn_id"] = kwargs.get("turn_id", args[-1] if args else None)
            return result

        for name in ("call_ollama", "call_openai_compatible", "call_claude", "call_gemini"):
            self._patch(ai_handler, name, fake)
        return seen

    def test_each_mode_reaches_its_own_provider(self):
        picked = []

        def tag(name):
            def fake(*args, **kwargs):
                picked.append(name)
                return {"message": "hi"}
            return fake

        for name in ("call_ollama", "call_openai_compatible", "call_claude", "call_gemini"):
            self._patch(ai_handler, name, tag(name))

        for mode, expected in (("OLLAMA", "call_ollama"),
                               ("CHATGPT", "call_openai_compatible"),
                               ("DEEPSEEK", "call_openai_compatible"),
                               ("KIMI", "call_openai_compatible"),
                               ("CLAUDE", "call_claude"),
                               ("GEMINI", "call_gemini")):
            picked.clear()
            ai_handler._call_provider(mode, "sys", "user", None)
            self.assertEqual(picked, [expected], mode)

    def test_an_unknown_mode_falls_through_to_gemini(self):
        """Gemini is the else-branch, so a mode from a newer build or a mod
        still gets an answer instead of raising."""
        picked = []
        self._patch(ai_handler, "call_gemini",
                    lambda *a, **k: picked.append("gemini") or {"message": "hi"})
        ai_handler._call_provider("SOMETHING_NEW", "sys", "user", None)
        self.assertEqual(picked, ["gemini"])

    def test_raw_returns_the_provider_dict_untouched(self):
        payload = {"message": "text", "action": "WAR_DECLARATION", "opinion_change": -5}
        self.stub_calls(payload)
        self.assertIs(ai_handler._run_provider("CLAUDE", "s", "u", None, "canned", raw=True),
                      payload)

    def test_raw_returns_none_when_the_request_was_abandoned(self):
        self.stub_calls(None)
        self.assertIsNone(ai_handler._run_provider("CLAUDE", "s", "u", None, "canned", raw=True))

    def test_a_reply_carries_the_action_fields_through(self):
        self.stub_calls({"message": "we refuse", "action": "CEASEFIRE",
                         "action_target": "Borland", "opinion_change": "-7"})
        reply = ai_handler._run_provider("CLAUDE", "s", "u", None, "canned", accepted=False)
        self.assertEqual(reply["accepted"], False)
        self.assertEqual(reply["message"], "we refuse")
        self.assertEqual(reply["action"], "CEASEFIRE")
        self.assertEqual(reply["action_target"], "Borland")
        self.assertEqual(reply["opinion_change"], -7, "coerced to int on every branch")

    def test_an_abandoned_request_uses_the_canned_line_on_every_provider(self):
        """The Ollama branch used to answer with its own "OLLAMA ERROR: No
        response" here, so pressing Force Skip put an error string in front of
        the player dressed as a diplomatic cable."""
        self.stub_calls(None)
        for mode in ("OLLAMA", "CHATGPT", "CLAUDE", "GEMINI"):
            reply = ai_handler._run_provider(mode, "s", "u", None, "we accept.", accepted=True)
            self.assertEqual(reply["message"], "we accept.", mode)
            self.assertEqual(reply["accepted"], True, mode)

    def test_a_reply_missing_its_message_field_says_so(self):
        self.stub_calls({"action": "NONE"})
        reply = ai_handler._run_provider("KIMI", "s", "u", None, "canned")
        self.assertIn("KIMI", reply["message"])


class ProviderErrorTests(NoNetworkTestCase):
    """Provider failures stay visible on a proposal and stay out of flavour text."""

    def test_provider_error_is_flagged(self):
        err = ai_handler._provider_error("HTTP ERROR 401: bad key")
        self.assertTrue(err["error"])
        self.assertIn("401", err["message"])

    def test_a_proposal_still_shows_the_error(self):
        """How a player finds out their API key is wrong."""
        self._patch(ai_handler, "call_claude",
                    lambda *a, **k: ai_handler._provider_error("HTTP ERROR 401: bad key"))
        reply = ai_handler._run_provider("CLAUDE", "s", "u", None, "canned", accepted=True)
        self.assertIn("401", reply["message"])

    def test_proactive_text_drops_the_error_and_takes_the_fallback(self):
        """A proactive one-liner has no verdict riding on it, so an error there
        is pure noise -- returning None makes the caller use its canned line."""
        self._patch(ai_handler, "_run_provider",
                    lambda *a, **k: ai_handler._provider_error("API ERROR: boom"))
        self.assertIsNone(self._generate_proactive())

    def test_proactive_text_returns_the_message_on_success(self):
        self._patch(ai_handler, "_run_provider", lambda *a, **k: {"message": "Prepare yourselves."})
        self.assertEqual(self._generate_proactive(), "Prepare yourselves.")

    def test_proactive_text_returns_none_when_abandoned(self):
        self._patch(ai_handler, "_run_provider", lambda *a, **k: None)
        self.assertIsNone(self._generate_proactive())

    def _generate_proactive(self):
        """Runs generate_proactive_text with the canned-reply gate forced open."""
        self._patch(ai_evaluation, "_use_canned_reply", lambda *a, **k: False)
        nation_data = {"Avaria": {"manpower": 1, "materials": 1, "inbox": []},
                       "Borland": {}}
        return ai_evaluation.generate_proactive_text(
            nation_data, ["Avaria", "Borland"], "Avaria", "Borland",
            "declaring war", human_players=[], turn_id=None)


if __name__ == "__main__":
    unittest.main()
