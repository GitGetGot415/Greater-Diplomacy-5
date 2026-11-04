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

import json
import unittest
from unittest import mock


import data.constants as c
from data import queries
from map_logic.ai import ai_evaluation, ai_handler, ai_prompts


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
                               ("OPENROUTER", "call_openai_compatible"),
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
        for mode in ("OLLAMA", "CHATGPT", "CLAUDE", "GEMINI", "DEEPSEEK", "KIMI", "OPENROUTER"):
            reply = ai_handler._run_provider(mode, "s", "u", None, "we accept.", accepted=True)
            self.assertEqual(reply["message"], "we accept.", mode)
            self.assertEqual(reply["accepted"], True, mode)

    def test_a_reply_missing_its_message_field_says_so(self):
        self.stub_calls({"action": "NONE"})
        reply = ai_handler._run_provider("KIMI", "s", "u", None, "canned")
        self.assertIn("KIMI", reply["message"])


class OpenRouterProviderTests(NoNetworkTestCase):
    def setUp(self):
        super().setUp()
        self._patch(ai_handler, "FORCE_SKIP", False)

    def test_openrouter_request_uses_saved_key_and_editable_model(self):
        for model in (c.DEFAULT_OPENROUTER_MODEL, "vendor/test-chat-model"):
            with self.subTest(model=model):
                session = mock.Mock()
                session.post.return_value.status_code = 200
                session.post.return_value.json.return_value = {
                    "choices": [{"message": {"content": '{"message":"We agree.","accepted":true}'}}]}
                with mock.patch.object(ai_handler, "_session", return_value=session), \
                        mock.patch.object(queries, "get_settings", return_value={
                            "openrouter_api_key": "test-key", "openrouter_model": model}):
                    result = ai_handler._dispatch("OPENROUTER", "system", "world", None)
                self.assertEqual(result, {"message": "We agree.", "accepted": True})
                args, kwargs = session.post.call_args
                self.assertEqual(args, (c.OPENROUTER_API_URL,))
                self.assertEqual(kwargs["headers"]["Authorization"], "Bearer test-key")
                self.assertEqual(kwargs["json"]["model"], model)
                self.assertEqual(kwargs["json"]["messages"], [
                    {"role": "user", "content": "world\n\nsystem"}])

    def test_legacy_provider_and_settings_dispatch_to_openrouter(self):
        from map_logic.ai import ai_settings
        for mode in ("LING", "OPENROUTER"):
            with self.subTest(mode=mode), mock.patch.object(queries, "get_settings", return_value={
                    "ai_mode": "LING", "ling_api_key": "old-key", "ling_model": "vendor/old-model"}), \
                    mock.patch.object(ai_handler, "call_openai_compatible") as call:
                self.assertEqual(ai_settings.get_ai_mode(), "OPENROUTER")
                ai_handler._dispatch(mode, "system", "world", None)
                call.assert_called_once_with(c.OPENROUTER_API_URL, "old-key", "vendor/old-model",
                                             "system", "world", None)

    def test_current_provider_keys_win_over_legacy_values(self):
        with mock.patch.object(queries, "get_settings", return_value={
                "ling_api_key": "old-key", "ling_model": "vendor/old-model",
                "openrouter_api_key": "", "openrouter_model": "vendor/current-model"}), \
                mock.patch.object(ai_handler, "call_openai_compatible") as call:
            ai_handler._dispatch("OPENROUTER", "s", "u", None)
        call.assert_called_once_with(c.OPENROUTER_API_URL, "", "vendor/current-model", "s", "u", None)

    def test_ollama_reads_legacy_url_and_respects_current_empty_url(self):
        from map_logic.ai import ai_settings
        with mock.patch.object(queries, "get_settings", return_value={"ollama_api_key": "http://old/api/chat"}):
            self.assertEqual(ai_settings.get_ollama_url(), "http://old/api/chat")
        with mock.patch.object(queries, "get_settings", return_value={
                "ollama_api_key": "http://old/api/chat", "ollama_base_url": ""}):
            self.assertEqual(ai_settings.get_ollama_url(), "http://localhost:11434/api/chat")

    def test_legacy_settings_supply_default_model_and_empty_key(self):
        with mock.patch.object(queries, "get_settings", return_value={}), \
                mock.patch.object(ai_handler, "call_openai_compatible") as call:
            ai_handler._dispatch("OPENROUTER", "system", "world", None)
        call.assert_called_once_with(c.OPENROUTER_API_URL, "", c.DEFAULT_OPENROUTER_MODEL,
                                     "system", "world", None)

    def test_legacy_local_ling_url_cannot_redirect_hosted_requests(self):
        with mock.patch.object(queries, "get_settings", return_value={
                "ling_base_url": "http://localhost:11434/v1", "openrouter_api_key": "test-key"}), \
                mock.patch.object(ai_handler, "call_openai_compatible") as call:
            ai_handler._dispatch("OPENROUTER", "s", "u", None)
        call.assert_called_once_with(c.OPENROUTER_API_URL, "test-key", c.DEFAULT_OPENROUTER_MODEL, "s", "u", None)

    def test_skip_and_stale_turn_prevent_openrouter_requests(self):
        self.assertIsNone(ai_handler._dispatch("OPENROUTER", "s", "u", ai_handler.CURRENT_TURN_ID - 1))
        ai_handler.FORCE_SKIP = True
        self.assertIsNone(ai_handler._dispatch("OPENROUTER", "s", "u", None))

    def test_http_failure_and_invalid_json_use_shared_handling(self):
        session = mock.Mock()
        with mock.patch.object(ai_handler, "_session", return_value=session):
            session.post.return_value.status_code = 401
            session.post.return_value.text = "invalid API key"
            failed = ai_handler._dispatch("OPENROUTER", "s", "u", None)
            self.assertTrue(failed["error"])
            self.assertIn("401", failed["message"])
            session.post.return_value.status_code = 200
            session.post.return_value.json.return_value = {
                "choices": [{"message": {"content": "plain reply"}}]}
            self.assertEqual(ai_handler._dispatch("OPENROUTER", "s", "u", None), {"message": "plain reply"})


class ReplyParsingTests(unittest.TestCase):
    def test_json_code_blocks_preserve_action_fields(self):
        payload = '{"message":"Ready","accepted":true,"action":"NONE"}'
        expected = {"message": "Ready", "accepted": True, "action": "NONE"}
        for wrapper in ("```json\n{}\n```", "```\n{}\n```", "  ```JSON\r\n{}\r\n```  "):
            with self.subTest(wrapper=wrapper):
                self.assertEqual(ai_handler._parse_reply_json(wrapper.format(payload)), expected)

    def test_invalid_json_keeps_the_original_fallback_text(self):
        """Flagged as an error, so a letter or proactive line drops it rather
        than sending "JSON ERROR: ..." as a leader's words."""
        for reply in (" ```json\nnot json\n``` ", "```python\nprint('hello')\n```", "ordinary text"):
            with self.subTest(reply=reply):
                self.assertEqual(ai_handler._parse_reply_json(reply, lambda text: "JSON ERROR: " + text),
                                 {"message": "JSON ERROR: " + reply, "error": True})

    def test_invalid_json_without_a_fallback_is_plain_text(self):
        """A hosted model that answers in prose still said something usable."""
        self.assertEqual(ai_handler._parse_reply_json("ordinary text"),
                         {"message": "ordinary text"})


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


class OllamaTests(NoNetworkTestCase):
    """call_ollama against a fake connection, so nothing opens a socket."""

    def setUp(self):
        super().setUp()
        self._patch(ai_handler, "FORCE_SKIP", False)
        settings = mock.patch.object(queries, "get_settings", return_value={})
        settings.start()
        self.addCleanup(settings.stop)
        self.sent = {}

    def connect(self, fail=None, status=200, body=b"", lines=()):
        sent = self.sent

        class Response:
            def __init__(self):
                self.status = status
                self.lines = list(lines)

            def read(self):
                return body

            def readline(self):
                return self.lines.pop(0) if self.lines else b""

        class Connection:
            sock = None

            def __init__(self, *args, **kwargs):
                pass

            def request(self, method, path, body=None, headers=None):
                sent["payload"] = json.loads(body)
                if fail:
                    raise fail

            def getresponse(self):
                return Response()

            def close(self):
                pass

        patcher = mock.patch.object(ai_handler.http.client, "HTTPConnection", Connection)
        patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def chunk(text):
        return (json.dumps({"message": {"content": text}}) + "\n").encode("utf-8")

    def test_an_unreachable_server_is_a_provider_error(self):
        """Unflagged, this text became a leader's words and a proactive cable."""
        self.connect(fail=ConnectionRefusedError("refused"))
        result = ai_handler.call_ollama("s", "u")
        self.assertTrue(result["error"])
        self.assertTrue(result["message"].startswith("OLLAMA ERROR"))

    def test_an_http_failure_is_a_provider_error(self):
        self.connect(status=500, body=b'{"error": "model not found"}')
        result = ai_handler.call_ollama("s", "u")
        self.assertTrue(result["error"])
        self.assertIn("model not found", result["message"])

    def test_mangled_output_is_a_provider_error(self):
        self.connect(lines=[self.chunk("not json")])
        result = ai_handler.call_ollama("s", "u")
        self.assertEqual(result, {"message": "JSON ERROR: not json", "error": True})

    def test_a_good_reply_is_parsed(self):
        self.connect(lines=[self.chunk('{"message": '), self.chunk('"We agree."}')])
        self.assertEqual(ai_handler.call_ollama("s", "u"), {"message": "We agree."})

    def test_every_request_sets_the_same_context_window(self):
        """Ollama's own default can be smaller than one world-map prompt, and
        a value that changed between requests would reload the model."""
        self.connect(lines=[self.chunk('{"message": "ok"}')])
        ai_handler.call_ollama("system", "world")
        self.assertEqual(self.sent["payload"]["options"]["num_ctx"],
                         ai_handler.OLLAMA_CONTEXT_TOKENS)
        self.assertEqual(self.sent["payload"]["messages"],
                         [{"role": "user", "content": "world\n\nsystem"}])


class ClaudeTests(NoNetworkTestCase):
    def setUp(self):
        super().setUp()
        self._patch(ai_handler, "FORCE_SKIP", False)

    def world_prompt(self):
        nation_data = {"Avaria": {"manpower": 1, "materials": 1}, "Borland": {}}
        context = ai_evaluation.get_world_context(
            nation_data, {"Avaria", "Borland"}, "Avaria", current_date="1 May, 1939 AD")
        return ai_handler._combined_prompt("instructions", f"{context}\nChoose.")

    def send(self, body):
        session = mock.Mock()
        session.post.return_value.status_code = 200
        session.post.return_value.json.return_value = body
        self._patch(ai_handler, "_session", lambda: session)
        result = ai_handler.call_claude("key", "model", "instructions", "world")
        return result, session.post.call_args.kwargs["json"]

    def test_the_shared_world_is_cached_separately(self):
        """Claude caches only up to a marked block, so the part every nation
        shares has to end exactly where the per-nation part begins."""
        prompt = self.world_prompt()
        blocks = ai_handler._claude_content(prompt)
        self.assertEqual(blocks[0]["cache_control"], {"type": "ephemeral"})
        self.assertNotIn("cache_control", blocks[1])
        self.assertNotIn("You are the leader of Avaria", blocks[0]["text"])
        self.assertIn("Current Date: 1 May, 1939 AD", blocks[0]["text"])
        self.assertTrue(blocks[1]["text"].startswith(ai_prompts.SHARED_CONTEXT_END))
        self.assertEqual("".join(block["text"] for block in blocks), prompt)

    def test_a_prompt_without_the_world_is_plain_text(self):
        self.assertEqual(ai_handler._claude_content("just a task"), "just a task")

    def test_the_text_block_is_read_after_a_thinking_block(self):
        result, payload = self.send({"content": [
            {"type": "thinking", "thinking": ""},
            {"type": "text", "text": '{"message": "We agree."}'}]})
        self.assertEqual(result, {"message": "We agree."})
        self.assertEqual(payload["max_tokens"], ai_handler.CLAUDE_MAX_TOKENS)
        self.assertNotIn("system", payload, "the instructions belong after the world")

    def test_a_reply_without_text_is_a_provider_error(self):
        result, _payload = self.send({"content": [], "stop_reason": "refusal"})
        self.assertTrue(result["error"])
        self.assertIn("refusal", result["message"])


class HostedAbortTests(unittest.TestCase):
    """Abandoned hosted requests used to run, billed, for up to two minutes."""

    def setUp(self):
        for name, value in (("_HOSTED_CONNECTIONS", ai_handler.weakref.WeakSet()),
                            ("ACTIVE_OLLAMA_CONNECTIONS", [])):
            original = getattr(ai_handler, name)
            setattr(ai_handler, name, value)
            self.addCleanup(setattr, ai_handler, name, original)

    @unittest.skipIf(ai_handler.requests is None, "hosted providers are desktop-only")
    def test_the_session_records_each_connection_it_opens(self):
        adapter = ai_handler._TrackedAdapter()
        pool = adapter.poolmanager.connection_from_url("https://example.invalid")
        self.assertIs(pool.ConnectionCls, ai_handler._TrackedHTTPSConnection)

        conn = ai_handler._TrackedHTTPSConnection("example.invalid")
        with mock.patch.object(ai_handler.HTTPSConnection, "connect"):
            conn.connect()
        self.assertIn(conn, ai_handler._HOSTED_CONNECTIONS)

    def test_an_abort_closes_hosted_connections(self):
        closed = []

        class Conn:
            sock = type("S", (), {"shutdown": staticmethod(lambda how: closed.append(how))})()

            def close(self):
                closed.append("close")

        conn = Conn()
        ai_handler._HOSTED_CONNECTIONS.add(conn)
        ai_handler.abort_active_requests()
        self.assertIn("close", closed)
        self.assertEqual(len(ai_handler._HOSTED_CONNECTIONS), 0)


if __name__ == "__main__":
    unittest.main()
