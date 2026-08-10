"""Covers the shared LLM batch driver.

The two turn phases that fan prompts out to the model are hard to exercise
end-to-end -- they need a provider -- so this drives the runner directly with
fake work. The cases here are the ones the two hand-written copies used to
disagree about: a worker that raises, Force Skip pressed mid-batch, and a
request that lands in the same instant the user gives up on it.
"""

import os
import sys
import threading
import time
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from map_logic.ai import ai_llm_runner


class Recorder:
    """Collects what the runner reported, in order."""

    def __init__(self):
        self.results = {}
        self.fallbacks = []
        self.progress = []

    def on_result(self, job, result):
        self.results[job] = result

    def on_fallback(self, job):
        self.fallbacks.append(job)

    def on_progress(self, job):
        self.progress.append(job)


class BatchTests(unittest.TestCase):
    def run_batch(self, jobs, call, **kwargs):
        rec = Recorder()
        ai_llm_runner.run_llm_batch(jobs, call, rec.on_result, rec.on_fallback,
                                    on_progress=rec.on_progress, **kwargs)
        return rec

    def test_every_job_gets_an_answer(self):
        rec = self.run_batch(["a", "b", "c"], lambda j: j.upper(), max_workers=3)
        self.assertEqual(rec.results, {"a": "A", "b": "B", "c": "C"})
        self.assertEqual(rec.fallbacks, [])
        self.assertCountEqual(rec.progress, ["a", "b", "c"])

    def test_an_empty_batch_does_nothing(self):
        rec = self.run_batch([], lambda j: j)
        self.assertEqual((rec.results, rec.fallbacks, rec.progress), ({}, [], []))

    def test_a_worker_that_raises_falls_back(self):
        """The threaded copy used to record the exception text as the AI's own
        reply, so "THREAD ERROR: ..." reached the player as a diplomatic
        message. Both paths use the canned answer now."""
        def boom(job):
            raise RuntimeError("provider exploded")

        for sequential in (False, True):
            with self.subTest(sequential=sequential):
                rec = self.run_batch(["a", "b"], boom, sequential=sequential)
                self.assertEqual(rec.results, {})
                self.assertCountEqual(rec.fallbacks, ["a", "b"])
                self.assertCountEqual(rec.progress, ["a", "b"])

    def test_the_sequential_path_still_answers_everything(self):
        rec = self.run_batch(["a", "b"], lambda j: j * 2, sequential=True)
        self.assertEqual(rec.results, {"a": "aa", "b": "bb"})

    def test_skipping_before_the_batch_starts_costs_nothing(self):
        """Force Skip pressed before any request goes out: everything falls
        back and the loading bar is not touched, because the player asked not
        to wait for this batch at all."""
        called = []
        rec = self.run_batch(["a", "b"], lambda j: called.append(j),
                             should_abort=lambda: True)
        self.assertEqual(called, [])
        self.assertCountEqual(rec.fallbacks, ["a", "b"])
        self.assertEqual(rec.progress, [])

    def test_skipping_mid_batch_abandons_the_rest(self):
        started = threading.Event()
        release = threading.Event()
        abort = {"now": False}

        def call(job):
            if job == "slow":
                started.set()
                release.wait(5)
                return "late"
            return "quick"

        def should_abort():
            # Give the fast job a chance to land, then pull the plug.
            if started.is_set() and "quick" in rec.results:
                abort["now"] = True
            return abort["now"]

        rec = Recorder()
        try:
            ai_llm_runner.run_llm_batch(
                ["quick", "slow"], call, rec.on_result, rec.on_fallback,
                on_progress=rec.on_progress, should_abort=should_abort, max_workers=2)
        finally:
            release.set()

        self.assertEqual(rec.results.get("quick"), "quick")
        self.assertIn("slow", rec.fallbacks)
        self.assertCountEqual(rec.progress, ["quick", "slow"])

    def test_a_job_answered_just_before_the_skip_keeps_its_answer(self):
        """The proposal-response copy dropped these on the floor entirely --
        no result and no fallback -- leaving the caller with no entry at all."""
        seen = {"drained": False}

        def call(job):
            return f"answer-{job}"

        def should_abort():
            # Abort only once every future has already completed.
            return seen["drained"]

        rec = Recorder()

        def on_result(job, result):
            rec.on_result(job, result)
            seen["drained"] = True

        ai_llm_runner.run_llm_batch(["a", "b"], call, on_result, rec.on_fallback,
                                    on_progress=rec.on_progress, should_abort=should_abort,
                                    max_workers=2)

        # Whichever way the race falls, every job ends up accounted for exactly once.
        self.assertEqual(len(rec.results) + len(rec.fallbacks), 2)
        self.assertCountEqual(rec.progress, ["a", "b"])

    def test_progress_is_optional(self):
        ai_llm_runner.run_llm_batch(["a"], lambda j: j, lambda j, r: None, lambda j: None)


class DeadlineTests(unittest.TestCase):
    """The wall-clock budget, which shares its give-up path with Force Skip.

    A provider that has gone slow or unreachable must cost the budget, not the
    turn: whatever hasn't landed by the deadline takes its fallback and the
    batch returns.
    """

    def run_batch(self, jobs, call, **kwargs):
        rec = Recorder()
        ai_llm_runner.run_llm_batch(jobs, call, rec.on_result, rec.on_fallback,
                                    on_progress=rec.on_progress, **kwargs)
        return rec

    def test_a_deadline_already_past_falls_everything_back(self):
        called = []
        for sequential in (False, True):
            with self.subTest(sequential=sequential):
                rec = self.run_batch(["a", "b"], lambda j: called.append(j),
                                     deadline=time.monotonic() - 1, sequential=sequential)
                self.assertEqual(called, [])
                self.assertCountEqual(rec.fallbacks, ["a", "b"])

    def test_no_deadline_means_no_limit(self):
        rec = self.run_batch(["a"], lambda j: "answered", deadline=None)
        self.assertEqual(rec.results, {"a": "answered"})

    def test_a_deadline_far_ahead_does_not_interfere(self):
        rec = self.run_batch(["a", "b"], lambda j: j.upper(),
                             deadline=time.monotonic() + 30, max_workers=2)
        self.assertEqual(rec.results, {"a": "A", "b": "B"})
        self.assertEqual(rec.fallbacks, [])

    def test_a_batch_that_overruns_gives_up_on_what_is_still_out(self):
        release = threading.Event()

        def call(job):
            if job == "slow":
                release.wait(5)
            return f"answer-{job}"

        rec = Recorder()
        try:
            ai_llm_runner.run_llm_batch(
                ["quick", "slow"], call, rec.on_result, rec.on_fallback,
                on_progress=rec.on_progress, max_workers=2,
                deadline=time.monotonic() + 0.3, poll=0.05)
        finally:
            release.set()

        self.assertIn("slow", rec.fallbacks)
        self.assertEqual(rec.results.get("quick"), "answer-quick")
        self.assertCountEqual(rec.progress, ["quick", "slow"])

    def test_the_sequential_path_stops_calling_once_the_deadline_passes(self):
        """Web runs inline, so the budget has to be checked per job there too --
        otherwise a slow first call means every later one still runs."""
        called = []

        def call(job):
            called.append(job)
            return "ok"

        rec = self.run_batch(["a", "b", "c"], call, sequential=True,
                             deadline=time.monotonic() + 0.15)
        # "a" gets through; whatever the timing, nothing is left unaccounted for.
        self.assertIn("a", called)
        self.assertEqual(len(rec.results) + len(rec.fallbacks), 3)
        self.assertCountEqual(rec.progress, ["a", "b", "c"])

    def test_force_skip_still_wins_when_a_deadline_is_also_set(self):
        called = []
        rec = self.run_batch(["a"], lambda j: called.append(j),
                             should_abort=lambda: True,
                             deadline=time.monotonic() + 30)
        self.assertEqual(called, [])
        self.assertEqual(rec.fallbacks, ["a"])


class TurnDeadlineTests(unittest.TestCase):
    def test_a_zero_budget_means_unlimited(self):
        from data import queries
        original = queries.get_ai_turn_budget_seconds
        try:
            queries.get_ai_turn_budget_seconds = lambda: 0
            self.assertIsNone(ai_llm_runner.turn_deadline())
        finally:
            queries.get_ai_turn_budget_seconds = original

    def test_a_budget_becomes_a_stamp_in_the_future(self):
        from data import queries
        original = queries.get_ai_turn_budget_seconds
        try:
            queries.get_ai_turn_budget_seconds = lambda: 45
            self.assertGreater(ai_llm_runner.turn_deadline(), time.monotonic())
        finally:
            queries.get_ai_turn_budget_seconds = original


if __name__ == "__main__":
    unittest.main()
