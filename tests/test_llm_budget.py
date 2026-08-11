"""Who gets the model when the budget cannot reach everybody, and saying so.

The batch runs its jobs in list order, and that order came from nation_data --
the scenario file's order, which never varies. So whenever the turn budget
could not cover every nation, the same nation won it every single turn and the
rest were never consulted once. One thread against a local model is enough to
do that with a single call: saves/it kinda just stopped for some reason has a
loading bar promising twelve nations, of which the German Reich (the first
major power in the file) was the only one ever asked.

The second half is that none of this was visible. A batch that ran out of
budget looked exactly like a batch with nothing to say.
"""

import os
import sys
import time
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from map_logic.ai import ai_diplomacy, ai_llm_runner


class FakeScreen:
    def __init__(self, nations, turn=1):
        self.nation_data = {n: {} for n in nations}
        self.time_manager = type("T", (), {"total_turns": turn})()
        self.notes = []

    def show_feedback(self, text):
        self.notes.append(text)


def jobs_for(nations):
    return [{"nation": n, "candidates": [], "chosen": [], "pending": {}} for n in nations]


class FairnessTests(unittest.TestCase):
    NATIONS = [f"N{i:02d}" for i in range(6)]

    def order(self, screen):
        return [j["nation"] for j
                in ai_diplomacy._longest_waiting_first(screen, jobs_for(self.NATIONS))]

    def test_nobody_consulted_yet_keeps_the_file_order(self):
        """A fresh game has no history to be fair about, so it should not
        invent an arbitrary shuffle either."""
        screen = FakeScreen(self.NATIONS)
        self.assertEqual(self.order(screen), sorted(self.NATIONS))

    def test_a_nation_just_consulted_goes_to_the_back(self):
        screen = FakeScreen(self.NATIONS, turn=5)
        screen.nation_data["N00"]["llm_last_turn"] = 5
        self.assertEqual(self.order(screen)[-1], "N00")

    def test_the_longest_wait_comes_first(self):
        screen = FakeScreen(self.NATIONS, turn=10)
        for i, n in enumerate(self.NATIONS):
            screen.nation_data[n]["llm_last_turn"] = 10 - i
        self.assertEqual(self.order(screen)[0], self.NATIONS[-1])

    def test_someone_never_consulted_beats_everyone_who_has_been(self):
        screen = FakeScreen(self.NATIONS, turn=10)
        for n in self.NATIONS:
            screen.nation_data[n]["llm_last_turn"] = 1
        del screen.nation_data["N03"]["llm_last_turn"]
        self.assertEqual(self.order(screen)[0], "N03")

    def test_a_budget_of_one_call_still_reaches_everyone_eventually(self):
        """The property that was actually broken. With room for one call a turn,
        six turns should consult six different nations, not one nation six
        times."""
        screen = FakeScreen(self.NATIONS)
        served = []
        for turn in range(1, len(self.NATIONS) + 1):
            screen.time_manager.total_turns = turn
            first = ai_diplomacy._longest_waiting_first(screen, jobs_for(self.NATIONS))[0]
            screen.nation_data[first["nation"]]["llm_last_turn"] = turn
            served.append(first["nation"])
        self.assertEqual(sorted(served), sorted(self.NATIONS),
                         f"the budget went to {served}")

    def test_the_stamp_is_kept_where_saves_keep_things(self):
        """nation_data is serialized wholesale, so the rotation survives a save
        and reload without any migration."""
        screen = FakeScreen(self.NATIONS, turn=3)
        ordered = ai_diplomacy._longest_waiting_first(screen, jobs_for(self.NATIONS))
        self.assertEqual(ordered[0]["_turn"], 3)


class OutcomeTests(unittest.TestCase):
    """run_llm_batch has to say what it managed, not just do it."""

    def batch(self, jobs, **kw):
        seen = {"results": [], "fallbacks": []}
        outcome = ai_llm_runner.run_llm_batch(
            jobs,
            kw.pop("call", lambda job: f"answer-{job}"),
            lambda job, res: seen["results"].append(job),
            lambda job: seen["fallbacks"].append(job),
            sequential=True, **kw)
        return outcome, seen

    def test_a_batch_that_finishes_reports_everything_served(self):
        outcome, seen = self.batch([1, 2, 3])
        self.assertEqual((outcome.total, outcome.served, outcome.abandoned), (3, 3, 0))
        self.assertEqual(seen["fallbacks"], [])

    def test_an_empty_batch_is_not_an_error(self):
        outcome, _ = self.batch([])
        self.assertEqual(outcome.abandoned, 0)

    def test_an_expired_budget_is_reported_as_such(self):
        outcome, seen = self.batch([1, 2, 3], deadline=time.monotonic() - 1)
        self.assertEqual((outcome.served, outcome.abandoned), (0, 3))
        self.assertEqual(outcome.reason, "budget")
        self.assertEqual(seen["fallbacks"], [1, 2, 3])

    def test_force_skip_is_distinguished_from_running_out_of_time(self):
        outcome, _ = self.batch([1, 2, 3], should_abort=lambda: True)
        self.assertEqual(outcome.reason, "skipped")

    def test_a_call_that_raises_is_not_counted_as_served(self):
        def boom(job):
            raise RuntimeError("provider died")
        outcome, seen = self.batch([1, 2], call=boom)
        self.assertEqual((outcome.served, outcome.abandoned), (0, 2))
        self.assertEqual(seen["fallbacks"], [1, 2])

    def test_a_budget_that_expires_partway_keeps_what_it_got(self):
        deadline = time.monotonic() + 0.05

        def slow(job):
            time.sleep(0.04)
            return job

        outcome, seen = self.batch([1, 2, 3, 4, 5], call=slow, deadline=deadline)
        self.assertGreater(outcome.served, 0, "nothing was served at all")
        self.assertGreater(outcome.abandoned, 0, "the deadline never bit")
        self.assertEqual(outcome.served + outcome.abandoned, 5)


class ThreadedOutcomeTests(unittest.TestCase):
    """The same accounting on the path the game actually takes.

    Every test above runs sequentially, which is the web path; the desktop game
    uses the thread pool, and its outcome is assembled by different lines.
    """

    def batch(self, jobs, call=lambda job: job, **kw):
        fell_back = []
        outcome = ai_llm_runner.run_llm_batch(
            jobs, call, lambda job, res: None, fell_back.append,
            sequential=False, max_workers=2, **kw)
        return outcome, fell_back

    def test_a_finished_pool_reports_everything_served(self):
        outcome, fell_back = self.batch([1, 2, 3])
        self.assertEqual((outcome.total, outcome.served, outcome.abandoned), (3, 3, 0))
        self.assertEqual(fell_back, [])

    def test_a_pool_cut_short_reports_what_it_lost(self):
        def slow(job):
            time.sleep(0.05)
            return job

        outcome, fell_back = self.batch(list(range(8)), call=slow,
                                        deadline=time.monotonic() + 0.06, poll=0.01)
        self.assertGreater(outcome.abandoned, 0, "the deadline never bit")
        self.assertEqual(outcome.served + outcome.abandoned, 8)
        self.assertEqual(len(fell_back), outcome.abandoned)
        self.assertEqual(outcome.reason, "budget")

    def test_a_raising_call_falls_back_rather_than_counting(self):
        def boom(job):
            raise RuntimeError("provider died")

        outcome, fell_back = self.batch([1, 2], call=boom)
        self.assertEqual((outcome.served, outcome.abandoned), (0, 2))
        self.assertEqual(sorted(fell_back), [1, 2])


class StampTests(unittest.TestCase):
    """The rotation is only fair if something actually writes the stamp.

    _longest_waiting_first reads llm_last_turn; process_proactive_llm_tasks is
    the only thing that sets it, so testing the sort alone proves nothing about
    whether the queue ever moves.
    """

    def patch(self, module, name, value):
        original = getattr(module, name)
        setattr(module, name, value)
        self.addCleanup(lambda: setattr(module, name, original))

    def run_pass(self, reply):
        from map_logic.ai import ai_candidates as ac, ai_handler, ai_settings
        from tests.stub_map_screen import StubMapScreen

        for module in (ai_settings, ai_handler):
            self.patch(module, "get_ai_mode", lambda: "CLAUDE")
            self.patch(module, "get_ai_immersion_level", lambda: "ABSOLUTE")
        self.patch(ai_handler, "_run_provider", lambda *a, **k: reply)

        game = StubMapScreen(["A", "B", "C"], human_players=[])
        game.set_war("A", "B")
        game.force_skip_llm = False

        bag = ac.Collector("A", {})
        bag.add(ac.make("CEASEFIRE", "B", 0.9, "because"))
        bag.add(ac.make("TRADE", "C", 0.5, "because"))
        ranked = bag.ranked()
        game.proactive_choices = [{
            "nation": "A",
            "pending": game.nation_data["A"].setdefault("pending_diplomacy", {}),
            "candidates": ranked,
            "chosen": ranked[:1],
            "messages": {},
        }]
        ai_diplomacy.process_proactive_llm_tasks(game)
        return game

    def test_being_consulted_moves_a_nation_to_the_back_of_the_queue(self):
        game = self.run_pass({"picks": ["0"], "messages": {"0": "We agree."}})
        self.assertIsNotNone(game.nation_data["A"].get("llm_last_turn"),
                             "nothing recorded that A had its turn at the model")

    def test_a_wasted_call_still_counts_as_a_turn(self):
        """A nation whose provider keeps erroring must not sit at the front of
        the queue burning the budget forever."""
        game = self.run_pass({"error": "provider died"})
        self.assertIsNotNone(game.nation_data["A"].get("llm_last_turn"))


class ReportingTests(unittest.TestCase):
    def test_a_full_batch_says_nothing(self):
        screen = FakeScreen(["A"])
        ai_llm_runner.report_unserved(
            screen, ai_llm_runner.BatchOutcome(3, 3, 0, ""), "Directing")
        self.assertEqual(screen.notes, [])

    def test_running_out_of_budget_tells_the_player_and_names_the_levers(self):
        screen = FakeScreen(["A"])
        ai_llm_runner.report_unserved(
            screen, ai_llm_runner.BatchOutcome(12, 1, 11, "budget"), "Directing AI nations")
        self.assertEqual(len(screen.notes), 1)
        note = screen.notes[0]
        self.assertIn("1 of 12", note)
        self.assertIn("ai_turn_budget_seconds", note)
        self.assertIn("ai_threads", note)

    def test_a_deliberate_skip_does_not_nag_about_settings(self):
        screen = FakeScreen(["A"])
        ai_llm_runner.report_unserved(
            screen, ai_llm_runner.BatchOutcome(12, 1, 11, "skipped"), "Directing")
        self.assertNotIn("ai_turn_budget_seconds", screen.notes[0])

    def test_a_screen_with_no_feedback_channel_is_survivable(self):
        ai_llm_runner.report_unserved(
            object(), ai_llm_runner.BatchOutcome(12, 1, 11, "budget"), "Directing")


if __name__ == "__main__":
    unittest.main()
