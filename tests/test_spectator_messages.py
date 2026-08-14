"""What a spectator can tell about a message by looking at it.

Three things were unreadable. Every treaty announcement said "DIPLOMACY",
because the type is TEXT or DIPLOMACY and nothing else and the action that
produced it was never recorded anywhere that outlived the offer. A trade's
terms were on the message and simply not read. And a line the model wrote was
indistinguishable from the canned table's -- the fallback is substituted by
dict.get's default and travels the identical path into the identical send.

Old saves carry none of the new keys, so every test that adds one also has a
twin without it: degrading to yesterday's behaviour is the requirement, not an
accident that happens to hold.
"""

import unittest

import data.constants as c
from map_logic.diplomacy import diplomacy_messages as dm
from tests.stub_map_screen import StubMapScreen


class CategoryTests(unittest.TestCase):
    def test_each_action_reads_as_its_own_kind_of_act(self):
        for action, expected in (("WAR_DECLARATION", "WAR"),
                                 ("CEASEFIRE", "PEACE"),
                                 ("TRADE", "TRADE"),
                                 ("FACTION_INVITE", "FACTION"),
                                 ("REQ_MILITARY_ACCESS", "ACCESS"),
                                 ("ANNEX_PUPPET", "PUPPET"),
                                 ("BREAK_ALLIANCE", "ALLIANCE")):
            with self.subTest(action=action):
                self.assertEqual(
                    dm.message_category({"action": action, "type": "DIPLOMACY"}), expected)

    def test_a_message_from_an_older_save_still_reads(self):
        """No action recorded, because nothing recorded one until now."""
        self.assertEqual(dm.message_category({"type": "DIPLOMACY"}), "DIPLOMACY")
        self.assertEqual(dm.message_category({"type": "TEXT"}), "TEXT")

    def test_an_unknown_action_is_unlabelled_rather_than_broken(self):
        self.assertEqual(
            dm.message_category({"action": "MOD_ADDED_THIS", "type": "DIPLOMACY"}), "DIPLOMACY")

    def test_junk_does_not_raise(self):
        for junk in (None, "", 7, []):
            self.assertEqual(dm.message_category(junk), "")

    def test_every_bilateral_and_unilateral_action_has_a_category(self):
        """Otherwise a whole class of message silently reads DIPLOMACY again."""
        for action in list(c.BILATERAL_ACTIONS) + list(c.UNILATERAL_ACTIONS):
            with self.subTest(action=action):
                self.assertIn(action, c.MESSAGE_CATEGORIES)

    def test_joining_a_war_does_not_read_as_declaring_one(self):
        """The one confusion in this column a reader cannot afford: "WAR" from
        an ally you are already fighting beside looks exactly like that ally
        turning on you. Neither of these starts a war."""
        for action in ("CALL_TO_ARMS", "JOIN_WARS"):
            with self.subTest(action=action):
                category = dm.message_category({"action": action, "type": "DIPLOMACY"})
                self.assertNotEqual(category, "WAR")

    def test_declaring_war_still_reads_as_war(self):
        self.assertEqual(
            dm.message_category({"action": "WAR_DECLARATION", "type": "DIPLOMACY"}), "WAR")

    def test_asking_and_offering_are_told_apart(self):
        """CALL_TO_ARMS asks an ally into our wars and JOIN_WARS asks to be let
        into theirs.

        These shared one label, on the theory that which way round it is was
        already on the row -- sender, receiver, and the message itself. It is
        not. The message is written by a model that gets the direction wrong,
        and an autonomous puppet offering to join its master's war arrived
        saying "we request your aid" under a label reading JOIN WAR. Opening it
        was the only way to find out which had been sent.
        """
        self.assertNotEqual(dm.message_category({"action": "CALL_TO_ARMS"}),
                            dm.message_category({"action": "JOIN_WARS"}))

    def test_a_faction_changing_hands_is_not_filed_as_ordinary_faction_news(self):
        """Every other row in the FACTION group is somebody joining or leaving.
        This one is the bloc itself changing hands over the head of the nation
        that founded it, which is not the same news at all."""
        self.assertNotEqual(
            dm.message_category({"action": "CLAIM_FACTION_LEADERSHIP"}), "FACTION")
        self.assertNotEqual(
            dm.message_category({"action": "CLAIM_FACTION_LEADERSHIP"}), "DIPLOMACY")



class SendTests(unittest.TestCase):
    def setUp(self):
        self.game = StubMapScreen(["A", "B"], human_players=[])

    def inbox(self, nation):
        return self.game.nation_data[nation].get("inbox", [])

    def test_a_treaty_message_records_the_action_on_both_copies(self):
        dm.send_treaty_message(self.game, "A", "B", "TRADE", "Let us deal.",
                               parameters={"give_materials": 100})
        received = self.inbox("B")[0]
        sent = self.inbox("A")[0]
        self.assertEqual(received["action"], "TRADE")
        self.assertEqual(sent["action"], "TRADE")
        self.assertEqual(dm.message_category(received), "TRADE")

    def test_a_war_declaration_is_not_filed_as_a_trade(self):
        dm.send_treaty_message(self.game, "A", "B", "WAR_DECLARATION")
        self.assertEqual(dm.message_category(self.inbox("B")[0]), "WAR")

    def test_the_terms_still_ride_along(self):
        params = {"give_materials": 500, "take_fuel": 200}
        dm.send_treaty_message(self.game, "A", "B", "TRADE", parameters=params)
        self.assertEqual(self.inbox("B")[0]["parameters"], params)

    def test_a_line_the_model_wrote_is_marked_and_a_canned_one_is_not(self):
        dm.send_message(self.game, "A", "B", "We have our reasons.", "DIPLOMACY", llm=True)
        dm.send_message(self.game, "A", "B", "We accept your proposal.", "DIPLOMACY")
        # Looked up by content: the inbox is newest-first, and which end a
        # message lands on is not what this test is about.
        by_text = {m["content"]: m for m in self.inbox("B")}
        marked, plain = by_text["We have our reasons."], by_text["We accept your proposal."]
        self.assertTrue(marked["llm"])
        self.assertNotIn("llm", plain,
                         "a canned line must not carry the flag at all, not even as False")

    def test_the_mark_is_on_the_sent_copy_too(self):
        dm.send_message(self.game, "A", "B", "Our terms.", "DIPLOMACY", llm=True)
        self.assertTrue(self.inbox("A")[0]["llm"])

    def test_the_type_is_untouched(self):
        """"DIPLOMACY" raises the popup and draws the gold bubble. Widening it
        would change behaviour rather than labelling it, so the category is
        derived for display and `type` stays exactly what it was."""
        dm.send_treaty_message(self.game, "A", "B", "TRADE")
        self.assertEqual(self.inbox("B")[0]["type"], "DIPLOMACY")


class TradeWordingTests(unittest.TestCase):
    PARAMS = {"give_materials": 400, "take_fuel": 150}

    def test_a_player_is_still_addressed_as_you(self):
        lines = dm.describe_trade(self.PARAMS)
        self.assertEqual(lines[0], "You receive: 400 Materials")
        self.assertEqual(lines[1], "You give: 150 Fuel")

    def test_a_proposer_still_sees_it_inverted(self):
        lines = dm.describe_trade(self.PARAMS, viewer_is_proposer=True)
        self.assertEqual(lines[0], "You receive: 150 Fuel")
        self.assertEqual(lines[1], "You give: 400 Materials")

    def test_a_third_party_reads_a_name_instead_of_you(self):
        lines = dm.describe_trade(self.PARAMS, subject="Poland")
        self.assertEqual(lines[0], "Poland receives: 400 Materials")
        self.assertEqual(lines[1], "Poland gives: 150 Fuel")

    def test_naming_a_subject_does_not_change_which_side_is_which(self):
        anonymous = dm.describe_trade(self.PARAMS, viewer_is_proposer=True)
        named = dm.describe_trade(self.PARAMS, viewer_is_proposer=True, subject="Poland")
        self.assertIn("150 Fuel", named[0])
        self.assertIn("150 Fuel", anonymous[0])

    def test_an_empty_side_says_nothing_rather_than_going_blank(self):
        lines = dm.describe_trade({"give_materials": 400}, subject="Poland")
        self.assertEqual(lines[1], "Poland gives: nothing")

    def test_a_non_trade_produces_no_lines(self):
        self.assertEqual(dm.describe_trade(None, subject="Poland"), [])


class EndToEndMarkingTests(unittest.TestCase):
    """The flag has to survive the whole path, not just send_message.

    It is set where the text is authored and then rides in `pending_diplomacy`
    beside the `message` it belongs to, through the outgoing pass, into both
    inbox copies. Unit-testing the ends of that would prove nothing about the
    middle, which is where a line the model wrote used to become
    indistinguishable from the table's.
    """

    def patch(self, module, name, value):
        original = getattr(module, name)
        setattr(module, name, value)
        self.addCleanup(lambda: setattr(module, name, original))

    def set_mode(self, mode, immersion="LITE"):
        from map_logic.ai import ai_handler, ai_settings
        for module in (ai_settings, ai_handler):
            self.patch(module, "get_ai_mode", lambda m=mode: m)
            self.patch(module, "get_ai_immersion_level", lambda i=immersion: i)

    def run_turn(self):
        from map_logic.ai import ai_diplomacy
        from map_logic.diplomacy import diplomacy_processor
        game = StubMapScreen(["A", "B", "C"], human_players=[])
        game.set_war("A", "B")
        game.force_skip_llm = False
        ai_diplomacy.process_basic_proactive_ai(game)
        ai_diplomacy.process_proactive_llm_tasks(game)
        diplomacy_processor._process_pass1_immediate_actions(game)
        return [m for n in ("A", "B", "C")
                for m in game.nation_data[n].get("inbox", [])]

    def test_a_line_the_model_wrote_arrives_marked(self):
        from map_logic.ai import ai_handler
        self.set_mode("CLAUDE", "ABSOLUTE")
        self.patch(ai_handler, "_run_provider",
                   lambda *a, **k: {"picks": ["0"], "messages": {"0": "MODEL WROTE THIS."}})

        written = [m for m in self.run_turn() if m.get("content") == "MODEL WROTE THIS."]
        self.assertTrue(written, "the model's line never reached an inbox")
        for msg in written:
            self.assertTrue(msg.get("llm"))
            self.assertTrue(msg.get("action"), "the act it announced was not recorded")

    def test_with_the_model_off_nothing_is_marked(self):
        self.set_mode("OFF")
        sent = self.run_turn()
        self.assertTrue(sent, "nothing was sent at all")
        for msg in sent:
            self.assertFalse(msg.get("llm"), msg.get("content"))

    def test_a_provider_that_answers_nothing_leaves_lines_unmarked(self):
        """The canned fallback travels the identical path; that is the point."""
        from map_logic.ai import ai_handler
        self.set_mode("CLAUDE", "ABSOLUTE")
        self.patch(ai_handler, "_run_provider", lambda *a, **k: None)

        sent = self.run_turn()
        self.assertTrue(sent, "nothing was sent at all")
        for msg in sent:
            self.assertFalse(msg.get("llm"), msg.get("content"))

    # -- the other origin: answering somebody's proposal ------------------

    def answer(self):
        """One AI's reply to a proposal, which is _reply's own path."""
        from map_logic.ai import ai_evaluation
        game = StubMapScreen(["A", "B"], human_players=[])
        return ai_evaluation.evaluate_diplomatic_proposal(
            game.nation_data, game.map_data, ["A", "B"], "B", "A", "TRADE",
            custom_msg="Care to deal?", human_players=[])

    def test_an_answer_the_model_wrote_is_marked(self):
        from map_logic.ai import ai_handler
        self.set_mode("CLAUDE", "ABSOLUTE")
        self.patch(ai_handler, "_run_provider",
                   lambda *a, **k: {"message": "We will consider it."})
        reply = self.answer()
        self.assertEqual(reply["message"], "We will consider it.")
        self.assertTrue(reply["llm"])

    def test_a_canned_answer_is_not_marked(self):
        self.set_mode("OFF")
        self.assertFalse(self.answer()["llm"])

    def test_an_answer_that_fell_back_is_not_marked(self):
        """A missing reply is substituted by dict.get's default and travels the
        identical path -- which is exactly how the two became indistinguishable."""
        from map_logic.ai import ai_handler
        self.set_mode("CLAUDE", "ABSOLUTE")
        self.patch(ai_handler, "_run_provider", lambda *a, **k: None)
        self.assertFalse(self.answer()["llm"])


class WarDeclarationTests(unittest.TestCase):
    """The one action whose words had nowhere to live.

    WAR_DECLARATION is the only proposal with a queued_message, and it is the
    wargoal the rules act on -- so it took the `message` field and both the
    model's line and the situational fallback were computed and then dropped.
    The send site then built its own hardcoded sentence, so every war in the
    game was declared in identical words at every immersion level, and the nine
    PROACTIVE_DECLARE_WAR lines in ai_responses.json were dead text.
    """

    def declare(self, model_line=None):
        from map_logic.ai import ai_diplomacy
        from map_logic.diplomacy import diplomacy_processor
        game = StubMapScreen(["A", "B"], human_players=[])
        pending = game.nation_data["A"].setdefault("pending_diplomacy", {})
        ai_diplomacy._queue_proactive_proposal(
            game, pending, "A", "B", "WAR_DECLARATION", message=model_line)
        entry = dict(pending["B"])
        diplomacy_processor._process_pass1_immediate_actions(game)
        received = next(m for m in game.nation_data["B"]["inbox"]
                        if not str(m.get("sender", "")).startswith("To:"))
        return entry, received

    def test_the_wargoal_still_reaches_the_rules(self):
        """Whatever else changes, `message` has to stay the wargoal: it is what
        gets written into wargoals[target]."""
        entry, _ = self.declare("Some prose entirely.")
        self.assertEqual(entry["message"], c.WARGOAL_TAKE_CLAIMS)

    def test_the_leaders_own_words_are_sent(self):
        _entry, msg = self.declare("You have held what is ours for long enough.")
        self.assertIn("You have held what is ours for long enough.", msg["content"])
        self.assertTrue(msg["llm"])

    def test_the_goal_is_still_readable_in_the_message(self):
        _entry, msg = self.declare("Anything.")
        self.assertIn(c.WARGOAL_TAKE_CLAIMS, msg["content"])

    def test_with_no_model_a_canned_line_is_used_rather_than_a_constant(self):
        from map_logic.ai import ai_prompts
        _entry, msg = self.declare(None)
        lines = ai_prompts.lines_for("PROACTIVE_DECLARE_WAR")
        self.assertTrue(any(line in msg["content"] for line in lines),
                        f"{msg['content']!r} is not one of the war-declaration lines")
        self.assertFalse(msg.get("llm"))

    def test_a_declaration_reads_as_war_not_diplomacy(self):
        _entry, msg = self.declare("Anything.")
        self.assertEqual(dm.message_category(msg), "WAR")

    def test_a_player_declaring_war_still_gets_a_sentence(self):
        """The human path queues the wargoal through toggle_diplomacy_action and
        never sets prose, so it has to keep working without one."""
        from map_logic.diplomacy import diplomacy_processor
        game = StubMapScreen(["A", "B"], human_players=["A"])
        diplomacy_processor.toggle_diplomacy_action(
            game.nation_data, "A", "B", "WAR_DECLARATION", custom_msg=c.WARGOAL_TAKE_CLAIMS)
        diplomacy_processor._process_pass1_immediate_actions(game)
        msg = next(m for m in game.nation_data["B"]["inbox"]
                   if not str(m.get("sender", "")).startswith("To:"))
        self.assertIn(c.WARGOAL_TAKE_CLAIMS, msg["content"])
        self.assertEqual(dm.message_category(msg), "WAR")

    def test_the_words_suit_who_is_being_declared_on(self):
        """A nation that knows it is outmatched declares war differently from
        one that knows it is not -- which is what the fallback table is for and
        what this action never reached."""
        from map_logic.ai import ai_diplomacy, ai_prompts

        game = StubMapScreen(["Strong", "Weak"], human_players=[])
        for prov in list(game.map_data.values())[:6]:
            prov["owner"] = "Strong"
            prov["units"] = [{"type": "Infantry Type 1936", "owner": "Strong",
                              "health": 1000, "attack": 100, "defense": 50}]

        def prose(sender, target):
            pending = {}
            ai_diplomacy._queue_proactive_proposal(
                game, pending, sender, target, "WAR_DECLARATION")
            return pending[target]["prose"]

        weaker = {prose("Weak", "Strong") for _ in range(30)}
        stronger = {prose("Strong", "Weak") for _ in range(30)}
        self.assertTrue(weaker.isdisjoint(stronger),
                        f"both sides used the same words: {weaker & stronger}")


class OverviewTests(unittest.TestCase):
    """The spectator's table, built from a real map."""

    @classmethod
    def setUpClass(cls):
        from tests import app_harness
        app_harness.boot()
        cls.map = app_harness.boot_map()

    def build(self):
        """Runs open_spectator_messages and captures what it would show."""
        from ui import editor_menus
        captured = {}

        def fake_launch(map_screen, screen):
            captured["screen"] = screen

        original = editor_menus._launch
        editor_menus._launch = fake_launch
        try:
            editor_menus.open_spectator_messages(self.map)
        finally:
            editor_menus._launch = original
        return captured.get("screen")

    def send(self, sender, receiver, **kwargs):
        dm.send_treaty_message(self.map, sender, receiver, **kwargs)
        return receiver

    def test_every_category_fits_the_column_it_is_drawn_in(self):
        """A label wider than its column is caught by nothing else here --
        message_category would go on returning it, correctly, and the table
        would go on drawing it over its neighbour. "CALL TO ARMS" renders at
        exactly the 100px available, which is why a call to arms and a request
        to join share one label rather than having two.

        The width is read off the table the game actually builds, so this
        cannot quietly pass against a copy of it.
        """
        from map_logic.rendering.font_manager import fonts

        table = self.build()
        width = next(col.width for col in table.columns if col.key == "type")
        font = fonts.get("small")
        for label in set(c.MESSAGE_CATEGORIES.values()) | {"DIPLOMACY", "TEXT"}:
            with self.subTest(label=label):
                drawn = font.size(label)[0]
                self.assertLess(drawn, width,
                                f"{label!r} is {drawn}px in a {width}px column")

    def test_a_join_war_row_says_so(self):
        """End to end: an ally asking for help must not arrive in the table
        looking like a declaration of war, and the two directions must not
        arrive looking like each other."""
        living = sorted(n for n in self.map.nation_data
                        if isinstance(self.map.nation_data[n], dict)
                        and self.map.nation_data[n].get("is_playable"))
        a, b, d = living[0], living[1], living[2]
        self.send(a, b, action="CALL_TO_ARMS", custom_msg="Stand with us.")
        self.send(d, b, action="JOIN_WARS", custom_msg="Let us fight beside you.")

        table = self.build()

        def row_for(sender, message):
            return next(r for r in table.rows if r["sender"] == sender
                        and r["receiver"] == b and r["message"] == message)

        called = row_for(a, "Stand with us.")
        joined = row_for(d, "Let us fight beside you.")
        for row in (called, joined):
            self.assertNotEqual(row["type"], "WAR")
        self.assertNotEqual(called["type"], joined["type"])

    def test_a_trade_row_carries_its_terms_and_kind(self):
        living = sorted(self.map.nation_data)
        a, b = self.map.player_country, next(
            n for n in living if n != self.map.player_country
            and isinstance(self.map.nation_data[n], dict)
            and self.map.nation_data[n].get("is_playable"))

        params = {"give_materials": 4200, "take_fuel": 1100}
        self.send(a, b, action="TRADE", custom_msg="A proposal.", parameters=params)

        table = self.build()
        row = next(r for r in table.rows
                   if r["sender"] == a and r["receiver"] == b and r["message"] == "A proposal.")
        self.assertEqual(row["type"], "TRADE")
        self.assertEqual(row["parameters"], params)

    def test_clicking_a_trade_shows_what_was_offered(self):
        living = sorted(self.map.nation_data)
        a, b = self.map.player_country, next(
            n for n in living if n != self.map.player_country
            and isinstance(self.map.nation_data[n], dict)
            and self.map.nation_data[n].get("is_playable"))
        self.send(a, b, action="TRADE", custom_msg="Another proposal.",
                  parameters={"give_materials": 777})

        table = self.build()
        row = next(r for r in table.rows if r["message"] == "Another proposal.")

        from ui import editor_menus
        captured = {}
        original = editor_menus._launch
        editor_menus._launch = lambda ms, screen: captured.setdefault("screen", screen)
        try:
            table.on_row_click(row)
        finally:
            editor_menus._launch = original

        detail = captured["screen"]
        self.assertIn("777 Materials", detail.body)
        self.assertIn(b, detail.body, "the terms must name whose side they are")

    def test_the_tint_marks_model_lines_only(self):
        table = self.build()
        self.assertIsNotNone(table.row_tint)
        self.assertEqual(table.row_tint({"llm": True}), c.MESSAGE_LLM_ROW_COLOR)
        self.assertIsNone(table.row_tint({"llm": False}))
        self.assertIsNone(table.row_tint({}), "an old message must not read as model-written")

    def test_a_table_with_no_tint_draws_as_before(self):
        from ui.table_screen import TableScreen, TableColumn
        plain = TableScreen(self.map, "t", [TableColumn("a", "A", 100)], [{"a": 1}])
        self.assertIsNone(plain.row_tint)

    def test_a_model_written_message_reaches_the_row_as_such(self):
        living = sorted(self.map.nation_data)
        a, b = self.map.player_country, next(
            n for n in living if n != self.map.player_country
            and isinstance(self.map.nation_data[n], dict)
            and self.map.nation_data[n].get("is_playable"))
        dm.send_message(self.map, a, b, "A LINE THE MODEL WROTE.", "DIPLOMACY", llm=True)
        dm.send_message(self.map, a, b, "A LINE THE TABLE PICKED.", "DIPLOMACY")

        rows = {r["message"]: r for r in self.build().rows}
        self.assertTrue(rows["A LINE THE MODEL WROTE."]["llm"])
        self.assertFalse(rows["A LINE THE TABLE PICKED."]["llm"])

    def test_the_tint_is_actually_painted(self):
        """A callback nothing draws with is a callback that does nothing."""
        import pygame
        from ui.table_screen import TableScreen, TableColumn

        surface = pygame.Surface((c.SCREEN_WIDTH, c.SCREEN_HEIGHT))
        table = TableScreen(self.map, "t", [TableColumn("a", "A", 200)],
                            [{"a": "only row"}],
                            row_tint=lambda row: c.MESSAGE_LLM_ROW_COLOR)
        surface.fill((0, 0, 0))
        table.draw(surface)

        rect = pygame.Rect(table.table_x, table.ROW_TOP, table.total_w, table.ROW_HEIGHT)
        painted = {surface.get_at((x, rect.centery))[:3]
                   for x in range(rect.x + 2, rect.right - 2, 7)}
        self.assertIn(c.MESSAGE_LLM_ROW_COLOR, painted,
                      "the tint never reached the surface")


if __name__ == "__main__":
    unittest.main()
