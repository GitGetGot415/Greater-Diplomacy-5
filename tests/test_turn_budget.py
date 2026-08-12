"""One turn, one budget, and nobody allowed to spend it on nothing.

Measured against saves/i dont think this is working HERE, a turn at MAJOR with
a local llama3 spent 136 seconds and produced two directed nations out of ten.
Three separate faults, each invisible on its own:

  * `ai_turn_budget_seconds` was read once per phase, from that phase's own
    start, so a setting reading 45 bought 45 three times over.
  * A summit is five sequential requests inside one batch job, and a batch can
    only give up between jobs -- so a summit that could not finish spent the
    entire first 45 seconds and was then discarded whole, unserved. Every turn.
  * Giving up did not stop the request already in flight. future.cancel()
    refuses to start a job; it does nothing to a worker blocked reading a reply.
    Each phase's abandoned request went on streaming into the *next* phase's
    budget -- 17 to 19 seconds of it -- and its answer was thrown away on
    arrival because a fallback had already been recorded in its place.

None of the three shows up as an error, a hang, or a failing assertion
anywhere. They show up as the game quietly directing one nation and moving on.
"""

import os
import sys
import time
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import data.constants as c
from map_logic.ai import ai_diplomacy, ai_handler, ai_llm_runner, ai_settings
from tests.stub_map_screen import StubMapScreen


class Patcher(unittest.TestCase):
    def patch(self, module, name, value):
        original = getattr(module, name)
        setattr(module, name, value)
        self.addCleanup(lambda: setattr(module, name, original))

    def budget(self, seconds):
        from data import queries
        self.patch(queries, "get_ai_turn_budget_seconds", lambda: seconds)


class SharedBudgetTests(Patcher):
    """The setting says `turn`. It has to mean a turn."""

    def setUp(self):
        self.budget(30)
        self.screen = StubMapScreen(["A", "B"])

    def phases(self, screen):
        """The three shares in the order prepare_turn spends them."""
        return [
            ai_llm_runner.turn_deadline(screen, c.AI_BUDGET_SHARE_SUMMITS),
            ai_llm_runner.turn_deadline(screen, c.AI_BUDGET_SHARE_DIRECTOR),
            ai_llm_runner.turn_deadline(screen, c.AI_BUDGET_SHARE_RESPONSES),
        ]

    def test_no_phase_may_run_past_the_end_of_the_turn(self):
        ai_llm_runner.begin_turn(self.screen)
        end = self.screen.llm_deadline
        for i, deadline in enumerate(self.phases(self.screen)):
            self.assertLessEqual(deadline, end + 0.01,
                                 f"phase {i} was allowed past the turn's own deadline")

    def test_the_phases_together_cannot_outspend_the_turn(self):
        """The fault as it actually appeared: three phases each measuring the
        budget from their own start, so 45 seconds bought 135."""
        ai_llm_runner.begin_turn(self.screen)
        start = time.monotonic()
        self.assertLessEqual(max(self.phases(self.screen)) - start, 30 + 0.01)

    def test_the_first_phase_cannot_take_the_whole_turn(self):
        """Summits ran first and spent all 45 seconds serving nobody, before
        the nations a player actually reads had been asked anything."""
        ai_llm_runner.begin_turn(self.screen)
        summits = ai_llm_runner.turn_deadline(self.screen, c.AI_BUDGET_SHARE_SUMMITS)
        self.assertLess(summits - time.monotonic(), 30 * 0.9)

    def test_a_phase_that_finishes_early_hands_the_rest_forward(self):
        ai_llm_runner.begin_turn(self.screen)
        spent_nothing = ai_llm_runner.turn_deadline(self.screen, c.AI_BUDGET_SHARE_DIRECTOR)

        ai_llm_runner.begin_turn(self.screen)
        self.screen.llm_deadline -= 20      # as if an earlier phase had used 20s
        spent_plenty = ai_llm_runner.turn_deadline(self.screen, c.AI_BUDGET_SHARE_DIRECTOR)

        self.assertGreater(spent_nothing, spent_plenty,
                           "the share is not taken against what is left")

    def test_a_turn_already_over_gives_a_deadline_that_has_passed(self):
        """Not None, which would mean "no limit" and let a phase run unbounded
        precisely when there is no time for it."""
        ai_llm_runner.begin_turn(self.screen)
        self.screen.llm_deadline = time.monotonic() - 5
        deadline = ai_llm_runner.turn_deadline(self.screen, c.AI_BUDGET_SHARE_DIRECTOR)
        self.assertIsNotNone(deadline)
        self.assertLessEqual(deadline, time.monotonic())

    def test_a_budget_of_zero_still_means_no_limit(self):
        self.budget(0)
        ai_llm_runner.begin_turn(self.screen)
        self.assertIsNone(self.screen.llm_deadline)
        self.assertIsNone(ai_llm_runner.turn_deadline(self.screen, 0.5))

    def test_a_caller_outside_a_turn_gets_the_whole_budget(self):
        """turn_deadline is reachable without begin_turn -- from a test, or any
        caller that is not a turn -- and must behave as it always did there."""
        left = ai_llm_runner.turn_deadline(None) - time.monotonic()
        self.assertAlmostEqual(left, 30, delta=0.5)

    def test_the_turn_budget_is_opened_where_the_turn_starts(self):
        """prepare_turn has to be the thing that starts the clock; a phase
        opening it would reset it for the phases after it."""
        import inspect
        from map_logic.turn_processing import turn_processor
        source = inspect.getsource(turn_processor.prepare_turn)
        self.assertIn("begin_turn", source)


class FakeClock:
    """A clock the test advances by hand.

    Sleeping for real would make these depend on how loaded the machine is, and
    what they are about -- where in a five-request meeting the budget runs out
    -- is exactly the thing a flaky timer would blur.
    """

    def __init__(self, now):
        self.now = now

    def monotonic(self):
        return self.now


class NoLimitTests(Patcher):
    """0 means the turn takes as long as the world needs, and FORCE SKIP AI is
    what ends it early.

    A ceiling chosen in advance cannot know whether a given turn's wait is
    worth it; the player watching the loading bar can. So every mechanism that
    exists to stop work short has to stand down completely at 0, or "no limit"
    quietly becomes "no limit except this one".
    """

    def setUp(self):
        self.budget(0)
        self.screen = StubMapScreen(["A", "B"])
        ai_llm_runner.begin_turn(self.screen)

    def test_no_phase_gets_a_deadline(self):
        for share in (c.AI_BUDGET_SHARE_SUMMITS, c.AI_BUDGET_SHARE_DIRECTOR,
                      c.AI_BUDGET_SHARE_RESPONSES):
            self.assertIsNone(ai_llm_runner.turn_deadline(self.screen, share))

    def test_nothing_is_declined_as_unaffordable(self):
        """The guard that hands a too-small share to the next phase has no
        share to measure when there is no ceiling."""
        self.patch(ai_handler, "_CALL_SECONDS", [600.0])
        self.assertTrue(ai_llm_runner.affordable(None, 99))

    def test_a_batch_runs_every_job_however_long_it_takes(self):
        served = []
        outcome = ai_llm_runner.run_llm_batch(
            list(range(5)), lambda job: time.sleep(0.02) or job,
            lambda job, res: served.append(job), lambda job: None,
            sequential=True, deadline=None)
        self.assertEqual(served, list(range(5)))
        self.assertEqual(outcome.abandoned, 0)

    def test_force_skip_still_ends_it(self):
        """The whole argument for removing the ceiling."""
        fell_back = []
        outcome = ai_llm_runner.run_llm_batch(
            list(range(5)), lambda job: job, lambda job, res: None,
            fell_back.append, sequential=True, deadline=None,
            should_abort=lambda: True)
        self.assertEqual(outcome.reason, "skipped")
        self.assertEqual(len(fell_back), 5)

    def test_a_turn_that_reaches_everyone_says_nothing(self):
        screen = StubMapScreen(["A"])
        screen.notes = []
        screen.show_feedback = screen.notes.append
        ai_llm_runner.report_unserved(
            screen, ai_llm_runner.BatchOutcome(12, 12, 0, ""), "Directing AI nations")
        self.assertEqual(screen.notes, [])


class SkipButtonReachableTests(Patcher):
    """Removing the ceiling only works if the button is on screen.

    Drawn for real onto a surface rather than asserted against the condition in
    the source: the button only exists as a rect the event handler can hit, and
    a test that restated the visibility rule would agree with a broken one.
    """

    @classmethod
    def setUpClass(cls):
        from tests import app_harness
        app_harness.boot()          # fonts and a display, which drawing needs

    def counters(self, **overrides):
        screen = StubMapScreen(["A"])
        counters = {"proactive_tasks_total": 1, "proactive_tasks_completed": 0,
                    "proactive_llm_tasks_total": 0, "proactive_llm_tasks_completed": 0,
                    "responsive_tasks_total": 0, "responsive_tasks_completed": 0,
                    "refresh_tasks_total": 7, "refresh_tasks_completed": 0,
                    "summits_total": 0, "summits_completed": 0,
                    "multi_turns_total": 0, "multi_turn_abort_requested": False}
        counters.update(overrides)
        for name, value in counters.items():
            setattr(screen, name, value)
        return screen

    def drawn(self, screen):
        """Whether the loading screen offers a way out, this frame."""
        import pygame
        from map_logic.turn_processing import loading_screen

        screen.force_skip_btn_rect = None
        surface = pygame.Surface((c.SCREEN_WIDTH, c.SCREEN_HEIGHT))
        loading_screen.draw_turn_loading_screen(screen, surface)
        return getattr(screen, "force_skip_btn_rect", None) is not None

    def test_a_summit_can_be_skipped(self):
        """Summits are the first model work of a turn and used to set none of
        the counters the button keys off, so the one phase with nothing else
        started yet was the one phase with no way out of it."""
        self.assertTrue(self.drawn(self.counters(summits_total=2)))

    def test_directing_can_be_skipped(self):
        self.assertTrue(self.drawn(self.counters(proactive_llm_tasks_total=10)))

    def test_answering_can_be_skipped(self):
        self.assertTrue(self.drawn(self.counters(responsive_tasks_total=15)))

    def test_a_turn_with_no_model_work_offers_no_button(self):
        self.assertFalse(self.drawn(self.counters()))


class SummitClockTests(Patcher):
    """A summit is five requests. It has to watch the clock between them."""

    def setUp(self):
        # Started from the real clock: run_llm_batch keeps its own, and a
        # deadline in what it considers the past would abandon the batch before
        # a single line was spoken -- proving nothing about the summit.
        self.DEADLINE = time.monotonic() + 10.0

        for module in (ai_settings, ai_handler):
            self.patch(module, "get_ai_mode", lambda: "CLAUDE")
            self.patch(module, "get_ai_immersion_level", lambda: "ABSOLUTE")

        self.game = StubMapScreen(["A", "B", "C"], human_players=[])
        self.game.force_skip_llm = False
        self.game.set_war("A", "C")
        self.game.set_war("B", "C")
        self.calls = []

        self.clock = FakeClock(self.DEADLINE - 10.0)
        self.patch(ai_diplomacy, "time", self.clock)
        self.patch(ai_llm_runner, "turn_deadline",
                   lambda screen=None, share=1.0: self.DEADLINE)

    def stub_provider(self, expire_after=None, reply=None):
        """A provider that answers, and optionally runs the clock out.

        `expire_after` is how many lines get spoken before the budget is gone.
        """
        def fake(mode, system, user, turn_id, canned, accepted=None, raw=False):
            self.calls.append(system)
            if expire_after is not None and len(self.calls) >= expire_after:
                self.clock.now = self.DEADLINE + 1
            if reply is not None:
                return dict(reply, message=f"line {len(self.calls)}")
            if "closing" in system:
                return {"agreed": False, "message": "We are done here.", "terms": []}
            return {"message": f"line {len(self.calls)}"}
        self.patch(ai_handler, "_run_provider", fake)

    def transcripts(self):
        return [msg for data in self.game.nation_data.values()
                for msg in (data.get("inbox") or [])]

    def test_a_summit_with_time_still_runs_to_the_end(self):
        self.stub_provider()
        ai_diplomacy.process_summits(self.game)
        self.assertEqual(len(self.calls), c.AI_NEGOTIATION_ROUNDS * 2 + 1)

    def test_a_summit_out_of_time_stops_asking(self):
        """The whole point: it must not keep spending after the deadline just
        because the batch runner can only look between jobs."""
        self.stub_provider()
        self.clock.now = self.DEADLINE + 1
        ai_diplomacy.process_summits(self.game)
        self.assertEqual(self.calls, [], f"asked anyway: {len(self.calls)} calls")

    def test_it_stops_at_the_line_the_budget_ran_out_on(self):
        """It used to spend the whole 45 seconds regardless, because nothing
        between the first request and the fifth ever looked at the clock."""
        self.stub_provider(expire_after=2)
        ai_diplomacy.process_summits(self.game)
        self.assertEqual(len(self.calls), 2)

    def test_what_was_said_before_the_clock_ran_out_is_kept(self):
        """It used to be discarded entire -- forty-five seconds of model time
        producing nothing at all, which is exactly what it looked like."""
        self.stub_provider(expire_after=2)
        ai_diplomacy.process_summits(self.game)
        self.assertTrue(self.transcripts(), "the meeting that happened was thrown away")

    def test_a_meeting_only_one_side_attended_is_not_published(self):
        """One leader speaking and the other never answering is a nation
        talking to itself; publishing it would start the pair's cooldown for
        nothing."""
        self.stub_provider(expire_after=1)
        ai_diplomacy.process_summits(self.game)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.transcripts(), [])

    def test_a_summit_cut_short_agrees_nothing(self):
        """No closing call means no terms, which is the honest outcome -- not
        an excuse to keep whatever the last line happened to mention."""
        from map_logic.ai import ai_commitments as cm

        self.stub_provider(expire_after=2, reply={
            "agreed": True, "terms": [{"type": "NON_AGGRESSION", "turns": 25}]})
        ai_diplomacy.process_summits(self.game)
        self.assertEqual(cm.active_with(self.game.nation_data, "A", "B"), [])

    def test_the_closing_is_not_sent_on_a_budget_that_is_already_gone(self):
        """The last of the five is a request like any other. Talks that ran to
        the end of their rounds with nothing left still have to stop, and what
        they said stands as a meeting that reached no terms."""
        self.stub_provider(expire_after=c.AI_NEGOTIATION_ROUNDS * 2)
        ai_diplomacy.process_summits(self.game)
        self.assertEqual(len(self.calls), c.AI_NEGOTIATION_ROUNDS * 2)
        self.assertTrue(self.transcripts())

    def test_a_meeting_cut_off_mid_request_still_leaves_what_was_spoken(self):
        """The clock can only be checked between requests, so the one that
        overruns is abandoned by the batch and its return value never arrives.
        Everything said before it has to already be somewhere readable, or the
        share bought nothing -- which is the whole fault, one scale down.
        """
        self.patch(ai_llm_runner, "turn_deadline",
                   lambda screen=None, share=1.0: time.monotonic() + 0.25)
        self.patch(ai_diplomacy, "time", time)

        def fake(mode, system, user, turn_id, canned, accepted=None, raw=False):
            self.calls.append(system)
            if len(self.calls) > 2:         # the third line outlasts the share
                time.sleep(0.6)
            return {"message": f"line {len(self.calls)}"}
        self.patch(ai_handler, "_run_provider", fake)

        ai_diplomacy.process_summits(self.game)
        self.assertGreater(len(self.calls), 2, "the deadline never bit")
        self.assertTrue(self.transcripts(),
                        "the exchange that did happen was thrown away")

    def test_a_meeting_cut_off_before_anyone_answered_leaves_nothing(self):
        """One leader having spoken when the budget ran out is not a meeting.
        The salvage has to drop it, or an abandoned summit puts half a sentence
        in two inboxes and starts the pair's cooldown for it.
        """
        self.patch(ai_llm_runner, "turn_deadline",
                   lambda screen=None, share=1.0: time.monotonic() + 0.25)
        self.patch(ai_diplomacy, "time", time)

        def fake(mode, system, user, turn_id, canned, accepted=None, raw=False):
            self.calls.append(system)
            if len(self.calls) > 1:         # the answer never arrives in time
                time.sleep(0.6)
            return {"message": f"line {len(self.calls)}"}
        self.patch(ai_handler, "_run_provider", fake)

        ai_diplomacy.process_summits(self.game)
        self.assertEqual(len(self.calls), 2, "the deadline bit in the wrong place")
        self.assertEqual(self.transcripts(), [])

    def test_a_share_with_room_for_one_line_is_not_spent_on_half_a_summit(self):
        """Ten seconds and a six-second call: enough to make one request, not
        enough for anyone to answer it. The old failure in miniature -- spend
        the slice, publish nothing -- so the slice goes to the next phase."""
        self.patch(ai_handler, "_CALL_SECONDS", [6.0])
        self.stub_provider()
        ai_diplomacy.process_summits(self.game)
        self.assertEqual(self.calls, [], f"spent the share anyway: {self.calls}")

    def test_a_share_with_room_for_a_whole_meeting_is_used(self):
        self.patch(ai_handler, "_CALL_SECONDS", [1.0])
        self.stub_provider()
        ai_diplomacy.process_summits(self.game)
        self.assertTrue(self.calls)

    def test_summits_ask_for_their_own_share_and_not_the_turn(self):
        asked = []
        self.patch(ai_llm_runner, "turn_deadline",
                   lambda screen=None, share=1.0: asked.append(share) or self.DEADLINE)
        self.stub_provider()
        ai_diplomacy.process_summits(self.game)
        self.assertEqual(asked, [c.AI_BUDGET_SHARE_SUMMITS])

    def test_an_odd_trailing_line_is_dropped(self):
        self.assertEqual(ai_diplomacy._complete_exchanges(["a: 1"]), [])
        self.assertEqual(ai_diplomacy._complete_exchanges(["a: 1", "b: 2"]),
                         ["a: 1", "b: 2"])
        self.assertEqual(ai_diplomacy._complete_exchanges(["a: 1", "b: 2", "a: 3"]),
                         ["a: 1", "b: 2"])


class HangUpTests(Patcher):
    """Giving up has to end the request, not just stop waiting for it."""

    def batch(self, jobs, call=lambda job: job, **kw):
        return ai_llm_runner.run_llm_batch(
            jobs, call, lambda job, res: None, lambda job: None,
            sequential=False, max_workers=2, **kw)

    def record_hangups(self):
        seen = []
        self.patch(ai_handler, "abort_active_requests", lambda: seen.append(1))
        return seen

    def test_a_batch_that_runs_out_of_time_ends_the_request_still_out(self):
        seen = self.record_hangups()

        def slow(job):
            time.sleep(0.2)
            return job

        self.batch(list(range(4)), call=slow,
                   deadline=time.monotonic() + 0.05, poll=0.01)
        self.assertTrue(seen, "the abandoned request was left streaming")

    def test_force_skip_partway_ends_it_too(self):
        """Pressed before anything goes out there is nothing to sever, and the
        batch returns without spawning a thread at all -- so the flag has to
        turn over after the requests are away for this to mean anything."""
        seen = self.record_hangups()
        pressed = {"yet": False}

        def slow(job):
            pressed["yet"] = True
            time.sleep(0.2)
            return job

        self.batch(list(range(4)), call=slow,
                   should_abort=lambda: pressed["yet"], poll=0.01)
        self.assertTrue(seen)

    def test_a_batch_that_finishes_hangs_up_on_nobody(self):
        seen = self.record_hangups()
        self.batch([1, 2, 3])
        self.assertEqual(seen, [], "severed sockets that were not in use")

    def test_a_hang_up_that_itself_fails_does_not_end_the_turn(self):
        def boom():
            raise OSError("socket already gone")
        self.patch(ai_handler, "abort_active_requests", boom)

        def slow(job):
            time.sleep(0.2)
            return job

        outcome = self.batch(list(range(4)), call=slow,
                             deadline=time.monotonic() + 0.05, poll=0.01)
        self.assertEqual(outcome.reason, "budget")

    def test_hanging_up_does_not_unload_the_model(self):
        """The prefix cache is the only thing making a local model affordable
        here (see tests/test_prompt_sharing.py). Flushing VRAM to save a few
        seconds would make every following call re-read the whole world."""
        posted = []
        self.patch(ai_handler, "requests",
                   type("R", (), {"post": staticmethod(lambda *a, **k: posted.append(a))})())
        self.patch(ai_handler, "ACTIVE_OLLAMA_CONNECTIONS", [])
        ai_handler.abort_active_requests()
        self.assertEqual(posted, [])

    def test_force_skip_still_unloads_it(self):
        """The player pressing Skip wants the GPU back; a deadline does not."""
        posted = []
        self.patch(ai_handler, "requests",
                   type("R", (), {"post": staticmethod(lambda *a, **k: posted.append(a))})())
        self.patch(ai_handler, "ACTIVE_OLLAMA_CONNECTIONS", [])
        self.patch(ai_handler, "get_ai_mode", lambda: "OLLAMA")
        ai_handler.abort_ai_generation()
        self.assertTrue(posted, "Force Skip no longer frees the GPU")

    def test_a_severed_connection_is_forgotten(self):
        closed = []

        class Conn:
            sock = type("S", (), {"shutdown": staticmethod(lambda how: closed.append(how))})()

            def close(self):
                closed.append("close")

        live = [Conn()]
        self.patch(ai_handler, "ACTIVE_OLLAMA_CONNECTIONS", live)
        ai_handler.abort_active_requests()
        self.assertTrue(closed)
        self.assertEqual(live, [], "a dead connection was left on the list")


class AffordabilityTests(Patcher):
    """A share too small to finish anything should go to somebody who can."""

    def setUp(self):
        self.patch(ai_handler, "_CALL_SECONDS", [5.0])

    def test_a_share_that_cannot_cover_one_call_is_declined(self):
        self.assertFalse(ai_llm_runner.affordable(time.monotonic() + 3, 1))

    def test_a_share_that_can_is_taken(self):
        self.assertTrue(ai_llm_runner.affordable(time.monotonic() + 8, 1))

    def test_a_summit_needs_room_for_both_sides_to_speak(self):
        """Half an exchange is not published, so nine seconds against a
        five-second call buys a summit precisely nothing."""
        deadline = time.monotonic() + 9
        self.assertTrue(ai_llm_runner.affordable(deadline, 1))
        self.assertFalse(ai_llm_runner.affordable(deadline, 2))

    def test_nothing_measured_yet_is_not_a_reason_to_refuse(self):
        """The first batch of a session finds out what a call costs by making
        one; refusing on no evidence would mean never making the first one.

        Asserted against a deadline that has already passed, because with any
        time left an unmeasured call and a free one give the same answer --
        `remaining >= 0 * calls` is true either way -- and the difference
        between "we have no estimate" and "the estimate is zero" would go
        untested. Running out of time is give_up's job, not this one's.
        """
        self.patch(ai_handler, "_CALL_SECONDS", [0.0])
        self.assertTrue(ai_llm_runner.affordable(time.monotonic() - 5, 5))

    def test_no_deadline_means_no_refusal(self):
        self.assertTrue(ai_llm_runner.affordable(None, 100))

    def test_a_declined_batch_takes_none_of_the_budget(self):
        called = []
        outcome = ai_llm_runner.run_llm_batch(
            [1, 2], lambda job: called.append(job), lambda job, res: None,
            lambda job: None, sequential=True,
            deadline=time.monotonic() + 1, min_calls=2)
        self.assertEqual(called, [], "spent the share it had just declined")
        self.assertEqual(outcome.reason, "unaffordable")

    def test_having_no_time_at_all_is_still_reported_as_the_budget(self):
        """Declining and running out are different things, and only one of
        them is worth telling the player about."""
        outcome = ai_llm_runner.run_llm_batch(
            [1, 2], lambda job: job, lambda job, res: None, lambda job: None,
            sequential=True, deadline=time.monotonic() - 1)
        self.assertEqual(outcome.reason, "budget")

    def test_declining_does_not_nag_the_player(self):
        screen = StubMapScreen(["A"])
        screen.notes = []
        screen.show_feedback = screen.notes.append
        ai_llm_runner.report_unserved(
            screen, ai_llm_runner.BatchOutcome(2, 0, 2, "unaffordable"), "Holding summits")
        self.assertEqual(screen.notes, [],
                         "nagged every turn about time that was never spent")


class CallMeterTests(Patcher):
    """The estimate has to come from somewhere real."""

    def setUp(self):
        self.patch(ai_handler, "_CALL_SECONDS", [0.0])

    def test_a_request_is_timed(self):
        self.patch(ai_handler, "_dispatch", lambda *a: time.sleep(0.02) or {"message": "hi"})
        ai_handler._call_provider("CLAUDE", "s", "u", None)
        self.assertGreater(ai_handler.typical_call_seconds(), 0.01)

    def test_a_request_that_fails_is_still_timed(self):
        """A provider that has gone slow and then errors is exactly the case
        the estimate exists for."""
        def boom(*a):
            time.sleep(0.02)
            raise RuntimeError("provider died")
        self.patch(ai_handler, "_dispatch", boom)
        with self.assertRaises(RuntimeError):
            ai_handler._call_provider("CLAUDE", "s", "u", None)
        self.assertGreater(ai_handler.typical_call_seconds(), 0.01)

    def test_one_slow_call_does_not_rewrite_the_estimate(self):
        """A cold start costs three times a warm call on the same machine;
        letting it set the number would have the game refuse to start work it
        can comfortably afford."""
        ai_handler._time_call(5.0)
        ai_handler._time_call(18.0)
        self.assertLess(ai_handler.typical_call_seconds(), 12.0)

    def test_the_estimate_does_follow_a_real_change(self):
        ai_handler._time_call(5.0)
        for _ in range(10):
            ai_handler._time_call(18.0)
        self.assertGreater(ai_handler.typical_call_seconds(), 15.0)


class PlayerFirstTests(Patcher):
    """192 proposals, one budget, and an arbitrary order deciding who is heard."""

    TASKS = [
        {"sender": "B", "target": "C", "action": "TRADE", "content": ""},
        {"sender": "C", "target": "B", "action": "TRADE", "content": ""},
        {"sender": "B", "target": "A", "action": "TRADE", "content": ""},
        {"sender": "A", "target": "C", "action": "TRADE", "content": ""},
    ]

    def run_tasks(self, game, immersion="ABSOLUTE"):
        """(what went to the model, in order) for one response pass."""
        from map_logic.ai import ai_handler, ai_settings
        from map_logic.diplomacy import diplomacy_processor

        for module in (ai_settings, ai_handler):
            self.patch(module, "get_ai_mode", lambda: "CLAUDE")
            self.patch(module, "get_ai_immersion_level", lambda i=immersion: i)

        captured = {"jobs": []}

        def fake_batch(jobs, call, on_result, on_fallback, **kw):
            captured["jobs"] = list(jobs)
            for job in captured["jobs"]:
                on_fallback(job)
            return ai_llm_runner.BatchOutcome(len(jobs), 0, len(jobs), "budget")

        self.patch(ai_llm_runner, "run_llm_batch", fake_batch)
        results = diplomacy_processor._execute_ai_tasks(
            game, [dict(t) for t in self.TASKS], ["A", "B", "C"])
        return [(t["sender"], t["target"]) for t in captured["jobs"]], results

    def test_the_players_own_correspondence_is_answered_first(self):
        game = StubMapScreen(["A", "B", "C"], human_players=["A"])
        order, _ = self.run_tasks(game)
        self.assertEqual(sorted(order[:2]), [("A", "C"), ("B", "A")],
                         f"the human waited behind AI chatter: {order}")

    def test_everyone_else_keeps_the_order_they_arrived_in(self):
        """A stable sort, so this changes who is starved and nothing else."""
        game = StubMapScreen(["A", "B", "C"], human_players=["A"])
        order, _ = self.run_tasks(game)
        self.assertEqual(order[2:], [("B", "C"), ("C", "B")])

    def test_a_spectator_game_is_left_alone(self):
        game = StubMapScreen(["A", "B", "C"], human_players=[])
        order, _ = self.run_tasks(game)
        self.assertEqual(order, [("B", "C"), ("C", "B"), ("B", "A"), ("A", "C")])


class ModelBudgetOnlyBoundsModelWorkTests(Patcher):
    """A deadline for the model must not starve work the model never sees."""

    TASKS = PlayerFirstTests.TASKS

    def run_tasks(self, game, immersion):
        return PlayerFirstTests.run_tasks(self, game, immersion)

    def test_proposals_answered_from_the_rules_never_join_the_queue(self):
        """At LITE, AI-to-AI proposals are decided locally in microseconds.
        Putting them behind a slow model meant a hundred and eighty of them
        took a fallback verdict because twelve nations were being written for.
        """
        game = StubMapScreen(["A", "B", "C"], human_players=[])
        order, _ = self.run_tasks(game, "LITE")
        self.assertEqual(order, [], f"queued work the model was never asked for: {order}")

    def test_they_are_answered_all_the_same(self):
        game = StubMapScreen(["A", "B", "C"], human_players=[])
        _, results = self.run_tasks(game, "LITE")
        self.assertEqual(len(results), len(self.TASKS),
                         "proposals the budget could not reach went unanswered")

    def test_the_ones_that_do_need_the_model_still_go_through_the_budget(self):
        game = StubMapScreen(["A", "B", "C"], human_players=[])
        order, _ = self.run_tasks(game, "ABSOLUTE")
        self.assertEqual(len(order), len(self.TASKS))

    def test_the_bar_does_not_count_work_that_finishes_instantly(self):
        """Sizing it from every gathered proposal instead of the queue would
        put a bar on screen that jumps most of the way in the first frame and
        then crawls -- the 192-against-15 gap, drawn."""
        from map_logic.ai import ai_handler, ai_settings
        from map_logic.diplomacy import diplomacy_processor

        for module in (ai_settings, ai_handler):
            self.patch(module, "get_ai_mode", lambda: "CLAUDE")
            self.patch(module, "get_ai_immersion_level", lambda: "LITE")
        self.patch(ai_llm_runner, "run_llm_batch",
                   lambda jobs, *a, **kw: ai_llm_runner.BatchOutcome(len(jobs), 0, 0, ""))

        game = StubMapScreen(["A", "B", "C"], human_players=["A"])
        tasks = [
            {"sender": "A", "target": "B", "action": "TRADE", "content": "Coal for oil."},
            {"sender": "B", "target": "C", "action": "TRADE", "content": "Coal for oil."},
            {"sender": "C", "target": "B", "action": "TRADE", "content": "Coal for oil."},
        ]
        diplomacy_processor._execute_ai_tasks(game, tasks, ["A", "B", "C"])
        self.assertEqual(game.responsive_tasks_total, 1,
                         "the bar is counting proposals the model never sees")

    def test_words_a_human_wrote_are_always_worth_the_model(self):
        """LITE's whole rule is that a person's own message gets a written
        reply and AI-to-AI traffic does not, so which side of that line a task
        falls on has to be read the right way round."""
        from map_logic.ai import ai_handler, ai_settings
        from map_logic.diplomacy import diplomacy_processor

        for module in (ai_settings, ai_handler):
            self.patch(module, "get_ai_mode", lambda: "CLAUDE")
            self.patch(module, "get_ai_immersion_level", lambda: "LITE")

        captured = {"jobs": []}

        def fake_batch(jobs, call, on_result, on_fallback, **kw):
            captured["jobs"] = list(jobs)
            for job in captured["jobs"]:
                on_fallback(job)
            return ai_llm_runner.BatchOutcome(len(jobs), 0, len(jobs), "budget")

        self.patch(ai_llm_runner, "run_llm_batch", fake_batch)
        game = StubMapScreen(["A", "B", "C"], human_players=["A"])
        diplomacy_processor._execute_ai_tasks(game, [
            {"sender": "A", "target": "B", "action": "TRADE",
             "content": "Take the Rhineland, we want the coal."},
            {"sender": "B", "target": "C", "action": "TRADE",
             "content": "Take the Rhineland, we want the coal."},
        ], ["A", "B", "C"])
        self.assertEqual([(t["sender"], t["target"]) for t in captured["jobs"]],
                         [("A", "B")])

    def test_the_loading_bar_is_sized_from_the_queue_it_is_watching(self):
        """It used to be sized by a fourth copy of the immersion rules, which
        had no MAJOR branch at all -- so the phase ran with the bar reading 0/0
        at the level the game recommends, and a player waiting on a turn with
        no ceiling had nothing telling them how much was left."""
        game = StubMapScreen(["A", "B", "C"], human_players=[])
        order, _ = self.run_tasks(game, "ABSOLUTE")
        self.assertEqual(game.responsive_tasks_total, len(order))
        self.assertGreater(game.responsive_tasks_total, 0)

    def test_the_bar_counts_up_as_the_queue_drains(self):
        game = StubMapScreen(["A", "B", "C"], human_players=[])
        # A batch skipped before it starts deliberately ticks nothing along --
        # the player asked not to wait for it -- so the flag has to be down for
        # this to be about the bar rather than about Force Skip.
        game.force_skip_llm = False

        from map_logic.ai import ai_handler, ai_settings
        from map_logic.diplomacy import diplomacy_processor

        for module in (ai_settings, ai_handler):
            self.patch(module, "get_ai_mode", lambda: "CLAUDE")
            self.patch(module, "get_ai_immersion_level", lambda: "ABSOLUTE")
        self.patch(ai_handler, "_run_provider", lambda *a, **k: None)

        diplomacy_processor._execute_ai_tasks(
            game, [dict(t) for t in self.TASKS], ["A", "B", "C"])
        self.assertEqual(game.responsive_tasks_completed, game.responsive_tasks_total)

    def test_the_report_counts_only_what_was_asked_of_the_model(self):
        """"10 of 192 answered" was measuring the wrong thing: 177 of those
        were never going to be asked."""
        game = StubMapScreen(["A", "B", "C"], human_players=["A"])
        order, _ = self.run_tasks(game, "LITE")
        self.assertLess(len(order), len(self.TASKS))


if __name__ == "__main__":
    unittest.main()
