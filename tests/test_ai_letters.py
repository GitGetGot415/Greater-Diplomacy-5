"""Covers AI letters, private notebooks, and the proposals letters lead to.

Every word between AI governments travels as an inbox letter. The model is not
trusted with anything but its words: recipients, opinions, and lengths are
checked here, and a letter changes the game only through its reader's opinion.

Nothing here touches the network. The guard in setUp makes that a hard failure.
"""

import unittest


import data.constants as c
from data import queries
from map_logic.ai import (ai_candidates as ac, ai_diplomacy, ai_director, ai_handler,
                          ai_letters, ai_llm_runner, ai_settings)
from tests.stub_map_screen import StubMapScreen


class LetterTestCase(unittest.TestCase):
    def setUp(self):
        def forbidden(*args, **kwargs):
            raise AssertionError("test attempted a real network call")

        for name in ("_session", "_gemini_client"):
            original = getattr(ai_handler, name)
            setattr(ai_handler, name, forbidden)
            self.addCleanup(lambda n=name, o=original: setattr(ai_handler, n, o))

        self.set_mode("CLAUDE", "ABSOLUTE")
        # No turn budget, whatever the local settings file says.
        self.patch(ai_llm_runner, "turn_deadline", lambda context=None, share=1.0: None)
        self.game = StubMapScreen(["A", "B", "C"], human_players=[])
        self.game.force_skip_llm = False
        self.prompts = []

    def patch(self, module, name, value):
        original = getattr(module, name)
        setattr(module, name, value)
        self.addCleanup(lambda: setattr(module, name, original))

    def set_mode(self, mode, immersion):
        """Both modules: ai_handler re-exports the settings getters by value."""
        for module in (ai_settings, ai_handler):
            self.patch(module, "get_ai_mode", lambda m=mode: m)
            self.patch(module, "get_ai_immersion_level", lambda i=immersion: i)

    def stub(self, answers):
        """`answers` maps a writer to a function of its user prompt, or to a reply."""
        def fake(mode, system, user, turn_id, canned, accepted=None, raw=False, schema=None):
            writer = next(n for n in self.game.nation_data
                          if f"You are the leader of {n}." in user)
            self.prompts.append((writer, user))
            answer = answers.get(writer, {"letters": [], "opinions": {}})
            return answer(user) if callable(answer) else answer
        self.patch(ai_handler, "_run_provider", fake)

    def run_letters(self):
        """One turn's sitting, then the send phase that delivers its letters."""
        ai_letters.process_letters(self.game)
        ai_letters.send_queued_letters(self.game)

    def await_answer(self, sender, receiver, text):
        """A player's plain message as the send phase leaves it: delivered, awaiting a reply."""
        from map_logic.diplomacy import diplomacy_messages
        diplomacy_messages.send_message(self.game, sender, receiver, text, "TEXT")
        diplomacy_messages.set_pending(self.game.nation_data, sender, receiver, f"MSG:{text}",
                                       turns=1, message=text)

    def letters_to(self, nation):
        return [m for m in self.game.nation_data[nation]["inbox"]
                if m.get(ai_letters.LETTER) and not m["sender"].startswith("To: ")]

    def write(self, sender, receiver, text):
        """A letter as the phase would have sent it."""
        from map_logic.diplomacy import diplomacy_messages
        diplomacy_messages.send_message(self.game, sender, receiver, text, "TEXT",
                                        extra={ai_letters.LETTER: True}, llm=True)


class DeliveryTests(LetterTestCase):
    def test_a_letter_arrives_as_ordinary_mail(self):
        self.stub({"A": {"letters": [{"to": "B", "text": "We should talk about C."}]}})
        self.run_letters()
        received = self.letters_to("B")
        self.assertEqual([(m["sender"], m["content"], m["type"]) for m in received],
                         [("A", "We should talk about C.", "TEXT")])
        self.assertTrue(received[0]["llm"])
        self.assertIn(("out", "We should talk about C."), self.game.thread("A", "B"))

    def test_a_letter_waits_for_the_send_phase(self):
        """Nobody can read or react to a letter in the turn it was written."""
        self.stub({"A": {"letters": [{"to": "B", "text": "We should talk about C."}]}})
        ai_letters.process_letters(self.game)
        self.assertEqual(self.letters_to("B"), [])
        ai_letters.send_queued_letters(self.game)
        self.assertEqual([m["content"] for m in self.letters_to("B")], ["We should talk about C."])
        self.assertEqual(self.game.queued_letters, [])

    def test_the_diplomacy_send_phase_delivers_them(self):
        from map_logic.diplomacy import diplomacy_processor
        self.stub({"A": {"letters": [{"to": "B", "text": "We should talk about C."}]}})
        ai_letters.process_letters(self.game)
        diplomacy_processor._process_pass1_immediate_actions(self.game)
        self.assertEqual([m["content"] for m in self.letters_to("B")], ["We should talk about C."])

    def test_a_letter_is_answered_only_in_the_next_turn(self):
        self.stub({
            "A": lambda user: ({"letters": [{"to": "B", "text": "Join us against C."}]}
                               if "From B" not in user else {"letters": []}),
            "B": lambda user: ({"letters": [{"to": "A", "text": "We are listening."}]}
                               if "Join us against C." in user else {"letters": []}),
        })
        self.run_letters()
        b_prompts = [user for writer, user in self.prompts if writer == "B"]
        self.assertTrue(b_prompts and not any("Join us against C." in u for u in b_prompts),
                        "B read A's letter in the turn A wrote it")
        self.assertEqual(self.letters_to("A"), [])
        self.run_letters()
        self.assertEqual([m["content"] for m in self.letters_to("A")], ["We are listening."])

    def test_the_director_cannot_react_to_a_letter_before_it_is_delivered(self):
        """Its own-initiative proposals come from delivered correspondence only."""
        def offered_to_b():
            ai_diplomacy.process_basic_proactive_ai(self.game)
            choice = {c["nation"]: c for c in self.game.proactive_choices}.get("A")
            return [cand for cand in (choice["candidates"] if choice else [])
                    if ac.is_initiative(cand) and cand.target == "B"]

        self.stub({"B": {"letters": [{"to": "A", "text": "Shall we stand together?"}]}})
        ai_letters.process_letters(self.game)
        self.assertEqual(offered_to_b(), [])
        ai_letters.send_queued_letters(self.game)
        self.assertTrue(offered_to_b(), "a delivered letter should make B a correspondent")

    def test_the_schema_names_the_readers_and_the_authors(self):
        """Ollama enforces this schema: a letter goes only to a listed reader,
        and an opinion is given about each author whose letter was read."""
        self.write("A", "B", "First words.")
        schemas = {}

        def fake(mode, system, user, turn_id, canned, accepted=None, raw=False, schema=None):
            writer = next(n for n in self.game.nation_data if f"You are the leader of {n}." in user)
            schemas.setdefault(writer, schema)
            return {"letters": [], "opinions": {}}

        self.patch(ai_handler, "_run_provider", fake)
        self.run_letters()
        letters = schemas["B"]["properties"]["letters"]
        self.assertEqual(letters["items"]["properties"]["to"]["enum"], ["A", "C"])
        self.assertEqual(letters["maxItems"], c.AI_LETTERS_PER_CALL)
        self.assertEqual(schemas["B"]["properties"]["opinions"]["required"], ["A"])

    def test_the_schema_allows_no_letter_when_nobody_reads(self):
        schema = ai_letters.reply_schema([], [])
        self.assertEqual(schema["properties"]["letters"], {"type": "array", "maxItems": 0})

    def test_a_read_letter_is_not_read_again(self):
        self.write("A", "B", "First words.")
        self.stub({})
        self.run_letters()
        self.assertEqual(ai_letters.unread_letters(self.game.nation_data, "B"), [])
        sittings = [writer for writer, _ in self.prompts]
        self.assertEqual(sittings.count("B"), 1)

    def test_a_players_plain_message_is_not_a_letter(self):
        from map_logic.diplomacy import diplomacy_messages
        diplomacy_messages.send_message(self.game, "A", "B", "Hello from a player.", "TEXT")
        self.assertEqual(ai_letters.unread_letters(self.game.nation_data, "B"), [])
        self.assertEqual(ai_letters.correspondents(self.game.nation_data, "B", {"A", "B", "C"}),
                         ["A"])


class PlayerMessageTests(LetterTestCase):
    """A player's message to a letter-writing AI is answered once, by its sitting."""

    def setUp(self):
        super().setUp()
        self.game = StubMapScreen(["P", "B", "C"], human_players=["P"])
        self.game.force_skip_llm = False

    def custom_tasks(self):
        from map_logic.diplomacy import diplomacy_processor
        return [t for t in diplomacy_processor._gather_ai_tasks(self.game)
                if t["action"] == "CUSTOM_MSG"]

    def test_the_sitting_reads_it_and_the_response_phase_does_not_reply(self):
        from map_logic.diplomacy import diplomacy_processor
        self.await_answer("P", "B", "Will you stand with us?")
        self.stub({"B": {"letters": [{"to": "P", "text": "We will consider it."}]}})
        self.run_letters()
        prompt = next(user for writer, user in self.prompts if writer == "B")
        self.assertIn("Will you stand with us?", prompt.split("--- LETTERS WAITING FOR YOU ---")[1])
        self.assertTrue(ai_letters.answered_by_letter(self.game, "P", "B"))
        self.assertEqual(self.custom_tasks(), [])

        inbox = len(self.game.nation_data["P"]["inbox"])
        info = self.game.nation_data["P"]["pending_diplomacy"]["B"]
        self.assertTrue(diplomacy_processor._resolve_awaited_action(
            self.game, {}, ["P", "B", "C"], [], "P", "B", info["action"], info))
        self.assertEqual(len(self.game.nation_data["P"]["inbox"]), inbox,
                         "the response phase replied a second time")
        self.assertEqual([m["content"] for m in self.letters_to("P")], ["We will consider it."])

    def test_a_failed_sitting_leaves_the_reply_to_the_response_phase(self):
        self.await_answer("P", "B", "Will you stand with us?")
        self.patch(ai_handler, "_run_provider",
                   lambda *a, **k: ai_handler._provider_error("API ERROR: boom"))
        self.run_letters()
        self.assertFalse(ai_letters.answered_by_letter(self.game, "P", "B"))
        self.assertEqual([(t["sender"], t["target"]) for t in self.custom_tasks()], [("P", "B")])

    def test_an_ai_that_writes_no_letters_still_gets_the_response_phase_reply(self):
        self.game.nation_data["B"]["llm_tier"] = c.AI_TIER_NEVER
        self.await_answer("P", "B", "Will you stand with us?")
        self.stub({})
        self.run_letters()
        self.assertNotIn("B", [writer for writer, _ in self.prompts])
        self.assertEqual([(t["sender"], t["target"]) for t in self.custom_tasks()], [("P", "B")])

    def test_a_player_can_receive_letters(self):
        game = StubMapScreen(["A", "B"], human_players=["A"])
        game.force_skip_llm = False
        self.game = game
        self.stub({"B": {"letters": [{"to": "A", "text": "A word in private."}]}})
        self.run_letters()
        self.assertEqual([m["content"] for m in self.letters_to("A")], ["A word in private."])


class ValidationTests(LetterTestCase):
    def test_recipients_must_be_countries_that_read_letters(self):
        self.game.nation_data["C"]["llm_tier"] = c.AI_TIER_NEVER
        self.stub({"A": {"letters": [{"to": "C", "text": "Nobody reads this."},
                                     {"to": "A", "text": "Talking to ourselves."},
                                     {"to": "Atlantis", "text": "Lost at sea."}]}})
        self.run_letters()
        for nation in ("A", "B", "C"):
            self.assertEqual(self.letters_to(nation), [])

    def test_one_letter_per_country_and_a_cap_per_sitting(self):
        self.game = StubMapScreen(["A", "B", "C", "D", "E"], human_players=[])
        self.game.force_skip_llm = False
        self.stub({"A": {"letters": [{"to": "B", "text": "One."}, {"to": "B", "text": "Two."},
                                     {"to": "C", "text": "Three."}, {"to": "D", "text": "Four."},
                                     {"to": "E", "text": "Five."}]}})
        self.run_letters()
        sent = [m for m in self.game.nation_data["A"]["inbox"] if m["sender"].startswith("To: ")]
        self.assertEqual(len(sent), c.AI_LETTERS_PER_CALL)
        self.assertEqual([m["content"] for m in self.letters_to("B")], ["One."])

    def test_a_display_name_finds_its_country(self):
        self.game.nation_data["B"]["name"] = "Republic of B"
        self.stub({"A": {"letters": [{"to": "republic of b", "text": "Greetings."}]}})
        self.run_letters()
        self.assertEqual([m["content"] for m in self.letters_to("B")], ["Greetings."])

    def test_a_letter_in_the_third_person_is_dropped(self):
        self.stub({"A": {"letters": [{"to": "B", "text": "A wishes you well."}]}})
        self.run_letters()
        self.assertEqual(self.letters_to("B"), [])

    def test_a_letter_with_placeholder_text_is_dropped(self):
        self.stub({"A": {"letters": [{"to": "B", "text": "We will send you [insert resource]."},
                                     {"to": "C", "text": "We will send you coal."}]}})
        self.run_letters()
        self.assertEqual(self.letters_to("B"), [])
        self.assertEqual([m["content"] for m in self.letters_to("C")], ["We will send you coal."])

    def test_a_letter_is_cut_to_its_length(self):
        self.stub({"A": {"letters": [{"to": "B", "text": "w" * (c.AI_LETTER_LENGTH + 50)}]}})
        self.run_letters()
        self.assertEqual(len(self.letters_to("B")[0]["content"]), c.AI_LETTER_LENGTH)


class OpinionTests(LetterTestCase):
    def general(self, reader, author):
        mods = self.game.nation_data[reader].get("temp_modifiers", {}).get(author, {})
        return queries.modifier_value(mods.get("general", 0))

    def test_reading_a_letter_moves_the_readers_opinion(self):
        self.write("A", "B", "We admire your restraint.")
        self.stub({"B": {"letters": [], "opinions": {"A": 7}}})
        self.run_letters()
        self.assertEqual(self.general("B", "A"), 7)

    def test_one_letter_cannot_move_it_past_the_limit(self):
        self.write("A", "B", "Your king is a fool.")
        self.stub({"B": {"letters": [], "opinions": {"A": -500}}})
        self.run_letters()
        self.assertEqual(self.general("B", "A"), -c.AI_OPINION_CHANGE_MAX)

    def test_an_opinion_needs_a_letter_behind_it(self):
        self.stub({"B": {"letters": [], "opinions": {"C": 15}}})
        self.run_letters()
        self.assertEqual(self.general("B", "C"), 0)

    def test_a_replys_opinion_change_has_the_same_limit(self):
        """A player's letter to an AI moves its opinion through the reply."""
        queries.add_opinion_change("B", "A", 999, self.game.nation_data)
        self.assertEqual(self.general("B", "A"), c.AI_OPINION_CHANGE_MAX)
        self.assertEqual(queries.add_opinion_change("B", "A", "lots", self.game.nation_data), 0)


class NotebookTests(LetterTestCase):
    def test_the_notebook_is_kept_and_cut_to_length(self):
        self.stub({"A": {"letters": [], "notebook": "n" * (c.AI_NOTEBOOK_LENGTH + 10)}})
        self.run_letters()
        self.assertEqual(len(ai_letters.notebook(self.game.nation_data, "A")), c.AI_NOTEBOOK_LENGTH)

    def test_a_reply_without_a_notebook_keeps_the_old_one(self):
        self.game.nation_data["A"][ai_letters.NOTEBOOK] = "Trust nobody."
        self.stub({"A": {"letters": []}})
        self.run_letters()
        self.assertEqual(ai_letters.notebook(self.game.nation_data, "A"), "Trust nobody.")

    def test_the_writer_is_told_its_geography(self):
        self.stub({})
        self.run_letters()
        prompt = next(user for writer, user in self.prompts if writer == "A")
        self.assertTrue("Your neighbors:" in prompt or "You border no country by land." in prompt)

    def test_the_writer_reads_its_own_notebook(self):
        self.game.nation_data["A"][ai_letters.NOTEBOOK] = "C is the danger."
        self.stub({})
        self.run_letters()
        prompt = next(user for writer, user in self.prompts if writer == "A")
        self.assertIn("C is the danger.", prompt)

    def test_the_director_reads_it_too(self):
        self.game.nation_data["A"][ai_letters.NOTEBOOK] = "Ally with B."
        seen = []

        def fake(mode, system, user, turn_id, canned, accepted=None, raw=False, schema=None):
            seen.append(user)
            return {"picks": ["none"]}
        self.patch(ai_handler, "_run_provider", fake)
        self.game.set_war("A", "C")
        self.game.set_war("B", "C")
        ai_diplomacy.process_basic_proactive_ai(self.game)
        ai_diplomacy.process_proactive_llm_tasks(self.game)
        self.assertTrue(any("Ally with B." in user for user in seen))

    def test_other_countries_never_see_it_in_a_multiplayer_snapshot(self):
        self.game.nation_data["A"][ai_letters.NOTEBOOK] = "Secret plans."
        for key, province in self.game.map_data.items():
            province["json_key"] = key
        snapshot = queries.player_snapshot_projection(
            self.game, {"nation_data": {k: dict(v) for k, v in self.game.nation_data.items()}}, "B")
        self.assertNotIn(ai_letters.NOTEBOOK, snapshot["nation_data"]["A"])


class PhaseTests(LetterTestCase):
    def test_nothing_is_written_with_the_model_off(self):
        self.set_mode("OFF", "ABSOLUTE")
        self.stub({"A": {"letters": [{"to": "B", "text": "Hello."}]}})
        self.run_letters()
        self.assertEqual(self.prompts, [])
        self.assertEqual(self.game.letters_total, 0)

    def test_nothing_is_written_below_the_major_tier(self):
        self.set_mode("CLAUDE", "FULL")
        self.stub({"A": {"letters": [{"to": "B", "text": "Hello."}]}})
        self.run_letters()
        self.assertEqual(self.prompts, [])

    def test_force_skip_leaves_letters_unread(self):
        self.write("A", "B", "Answer when you can.")
        self.game.force_skip_llm = True
        self.stub({})
        self.run_letters()
        self.assertEqual(self.prompts, [])
        self.assertEqual(len(ai_letters.unread_letters(self.game.nation_data, "B")), 1)

    def test_a_provider_error_leaves_letters_unread(self):
        self.write("A", "B", "Answer when you can.")
        self.patch(ai_handler, "_run_provider",
                   lambda *a, **k: ai_handler._provider_error("API ERROR: boom"))
        self.run_letters()
        self.assertEqual(len(ai_letters.unread_letters(self.game.nation_data, "B")), 1)
        self.assertIsNotNone(self.game.nation_data["B"].get(ai_letters.LAST_SAT))

    def test_the_bar_counts_every_country_that_sits(self):
        self.stub({})
        self.run_letters()
        sat = len({writer for writer, _ in self.prompts})
        self.assertEqual((self.game.letters_completed, self.game.letters_total), (sat, sat))

    def test_unread_letters_come_first_then_whoever_waited_longest(self):
        nd = self.game.nation_data
        nd["A"][ai_letters.LAST_SAT] = 5
        nd["B"][ai_letters.LAST_SAT] = 2
        self.write("A", "C", "Hello.")
        self.assertEqual(ai_letters.first_sitting(nd, ["A", "B", "C"], limit=1), ["C", "B"])

    def test_the_instructions_name_no_country(self):
        """The system half follows the shared world context for every writer."""
        world_state = self.game
        alive = {"A", "B", "C"}
        first = ai_letters.build_prompt(world_state, "A", [], ["A", "B", "C"], alive, "now")
        second = ai_letters.build_prompt(world_state, "B", [], ["A", "B", "C"], alive, "now")
        self.assertEqual(first[0], second[0])


class InitiativeTests(LetterTestCase):
    def test_several_initiatives_can_share_a_country(self):
        bag = ac.Collector("A", {})
        bag.add_initiative(ac.make("TRADE", "B", 0.0, "goods"))
        bag.add_initiative(ac.make("REQ_MILITARY_ACCESS", "B", 0.0, "passage"))
        ranked = bag.ranked()
        self.assertEqual(len(ranked), 2)
        self.assertTrue(all(ac.is_initiative(cand) for cand in ranked))

    def test_an_initiative_must_be_legal(self):
        bag = ac.Collector("A", {}, context=self.game)
        self.game.set_war("A", "B")
        self.assertFalse(bag.add_initiative(ac.make("REQ_MILITARY_ACCESS", "B", 0.0, "passage")))

    def test_allies_cannot_ask_each_other_for_military_access(self):
        """Faction members already move through each other's territory, so the
        request asks for nothing. The UK and France asked anyway, then refused."""
        from map_logic.diplomacy.action_definitions import availability
        for nation in ("A", "B"):
            self.game.nation_data[nation]["faction"] = "Pact"
        verdict = availability(self.game, "A", "B", "REQ_MILITARY_ACCESS")
        self.assertFalse(verdict.allowed)
        self.assertIn("already have military access", verdict.reason)
        bag = ac.Collector("A", {}, context=self.game)
        self.assertFalse(bag.add_initiative(ac.make("REQ_MILITARY_ACCESS", "B", 0.0, "passage")))
        self.assertTrue(availability(self.game, "A", "C", "REQ_MILITARY_ACCESS").allowed)

    def test_an_initiative_does_not_repeat_the_staff_proposal(self):
        bag = ac.Collector("A", {})
        bag.add(ac.make("TRADE", "B", 0.4, "staff"))
        self.assertFalse(bag.add_initiative(ac.make("TRADE", "B", 0.0, "own")))

    def test_the_staff_fallback_never_takes_an_initiative(self):
        bag = ac.Collector("A", {})
        bag.add_initiative(ac.make("TRADE", "B", 0.9, "own"))
        bag.add(ac.make("TRADE", "C", 0.1, "staff"))
        chosen = ai_director.top_scored(bag.ranked(), 3)
        self.assertEqual([(cand.action, cand.target) for cand in chosen], [("TRADE", "C")])

    def test_a_leader_picks_one_proposal_per_country_and_one_faction_request(self):
        bag = ac.Collector("A", {})
        for action, target in (("TRADE", "B"), ("REQ_MILITARY_ACCESS", "B"),
                               ("CREATE_FACTION", "C"), ("JOIN_FACTION_REQ", "D")):
            bag.add_initiative(ac.make(action, target, 0.0, "own"))
        ranked = bag.ranked()
        picks = [cand.cid for cand in sorted(ranked, key=lambda cand: cand.action != "TRADE")]
        chosen = ai_director.validate({"picks": picks}, ranked, 4)
        self.assertEqual([(cand.action, cand.target) for cand in chosen],
                         [("TRADE", "B"), ("CREATE_FACTION", "C")])

    def menu(self):
        ai_diplomacy.process_basic_proactive_ai(self.game)
        return {choice["nation"]: choice for choice in self.game.proactive_choices}

    def test_a_correspondent_gets_proposals_no_rule_asked_for(self):
        self.write("B", "A", "Shall we stand together?")
        choice = self.menu()["A"]
        offered = {(cand.action, cand.target) for cand in choice["candidates"]
                   if ac.is_initiative(cand)}
        self.assertIn(("CREATE_FACTION", "B"), offered)
        self.assertFalse(any(ac.is_initiative(cand) for cand in choice["chosen"]))

    def test_the_leader_can_take_one(self):
        self.write("B", "A", "Shall we stand together?")

        def fake(mode, system, user, turn_id, canned, accepted=None, raw=False, schema=None):
            if "You are the leader of A." not in user:
                return {"picks": ["none"]}
            cid = next(line.split("]")[0].strip(" [") for line in user.splitlines()
                       if "propose founding a faction with B" in line)
            return {"picks": [cid], "messages": {cid: "Let us found a pact."}}
        self.patch(ai_handler, "_run_provider", fake)
        ai_diplomacy.process_basic_proactive_ai(self.game)
        ai_diplomacy.process_proactive_llm_tasks(self.game)
        self.assertEqual(self.game.pending_action("A", "B"), "CREATE_FACTION")

    def test_no_initiatives_without_the_model(self):
        self.set_mode("OFF", "ABSOLUTE")
        self.write("B", "A", "Shall we stand together?")
        choices = self.menu()
        candidates = choices["A"]["candidates"] if "A" in choices else []
        self.assertFalse(any(ac.is_initiative(cand) for cand in candidates))


if __name__ == "__main__":
    unittest.main()
