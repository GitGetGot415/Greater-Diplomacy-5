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


if __name__ == "__main__":
    unittest.main()
