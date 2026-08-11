"""One driver for the game's batches of LLM calls.

Two turn phases fan a list of prompts out to the model and collect the answers:
the proactive-message pass in map_logic/ai/ai_diplomacy.py and the
proposal-response pass in map_logic/diplomacy/diplomacy_processor.py. Both had
their own copy of the same ~60 lines -- the ThreadPoolExecutor, the
`wait(timeout=0.1, FIRST_COMPLETED)` drain loop, the Force Skip cancel path,
the `shutdown(cancel_futures=)` fallback for older Pythons, and the sequential
web path -- and the two copies had drifted apart in how they treat a worker
that raises and a request that lands just as the user hits Force Skip.

What stays with the callers is what genuinely differs: which handler to call
for a job, how to record an answer, what the fallback answer is, and whether a
given job counts towards the loading bar. The six progress predicates in the
two phases are deliberately *not* merged -- they key off different things.

Kept a leaf (stdlib plus data.platform) so it can be imported from anywhere in
the AI package without closing a cycle.
"""

import concurrent.futures
import time
from collections import namedtuple

from data.platform import IS_WEB

#: What a batch actually managed. `abandoned` is how many jobs never got an
#: answer because the budget ran out or Force Skip was pressed -- which used to
#: be invisible, so a turn that served one nation of twelve looked exactly like
#: a turn that served all twelve and simply had little to say.
BatchOutcome = namedtuple("BatchOutcome", "total served abandoned reason")


def turn_deadline():
    """When this turn's LLM work must be done by, or None for no limit.

    Both batch call sites want the same budget measured from when their own
    batch starts, so they ask for it here rather than each reading the setting
    and doing the arithmetic.
    """
    from data import queries

    budget = queries.get_ai_turn_budget_seconds()
    return time.monotonic() + budget if budget else None


def report_unserved(map_screen, outcome, what):
    """Tells the player when the model did not get to everyone.

    A batch that ran out of budget looked identical to a batch with nothing to
    say: the loading bar counted up to whatever it reached, and then the turn
    carried on. On one thread against a local model that can be one nation of
    twelve, which reads as the game having quietly given up -- and it names the
    two settings that decide how many are reachable, since neither is guessable
    from the outside.
    """
    if not outcome or not outcome.abandoned:
        return
    if outcome.reason == "skipped":
        note = (f"{what}: skipped {outcome.abandoned} of {outcome.total}; "
                f"they used their staff's plan.")
    else:
        from data import queries
        budget = queries.get_ai_turn_budget_seconds()
        note = (f"{what}: {outcome.served} of {outcome.total} answered inside the "
                f"{budget}s budget; the other {outcome.abandoned} used their staff's "
                f"plan. Raise ai_turn_budget_seconds or ai_threads to reach more.")
    print(f"[AI] {note}")
    show = getattr(map_screen, "show_feedback", None)
    if show:
        show(note)


def run_llm_batch(jobs, call, on_result, on_fallback, on_progress=None,
                  should_abort=None, max_workers=1, poll=0.1, sequential=None,
                  deadline=None):
    """Runs `call(job)` for every job and hands each answer back as it lands.

    - `call(job)` produces the answer. It runs on a worker thread, or inline on
      the sequential path.
    - `on_result(job, result)` records a real answer. A caller that treats an
      empty answer as "use the fallback" does that here.
    - `on_fallback(job)` records the canned answer, used when the job was
      abandoned or the call raised.
    - `on_progress(job)` is called once per job after it resolves, whether it
      produced a result or a fallback. The caller decides whether the job
      counts towards its loading bar.
    - `should_abort()` is polled between drains; it is the Force Skip button.
      Already-finished requests still keep their real answers.
    - `deadline` is a time.monotonic() stamp past which the batch gives up on
      whatever is still out. A provider that has gone slow or unreachable then
      costs the budget rather than the turn, and every abandoned job takes its
      fallback -- which, once the director lands, is the heuristic's own choice.

    The deadline deliberately folds into the same predicate as `should_abort`
    rather than adding a second give-up path: the two want identical handling,
    and the one thing worse than a turn that hangs is two ways of ending it that
    disagree about which in-flight answers still count.

    `sequential` defaults to IS_WEB: Pyodide has no real OS threads, and AI
    networking is disabled on web anyway (see ai_handler's IS_WEB guard), so
    every call returns its fallback immediately rather than blocking.

    Returns a BatchOutcome saying how many jobs actually got an answer. The
    caller is expected to tell the player when that is fewer than it asked for:
    running out of budget used to look exactly like having nothing to say.
    """
    jobs = list(jobs)
    if not jobs:
        return BatchOutcome(0, 0, 0, "")

    tally = {"served": 0, "reason": ""}

    def give_up():
        if should_abort and should_abort():
            tally["reason"] = tally["reason"] or "skipped"
            return True
        if deadline is not None and time.monotonic() >= deadline:
            tally["reason"] = tally["reason"] or "budget"
            return True
        return False

    def served(job, result):
        tally["served"] += 1
        on_result(job, result)

    # Skipping before any request goes out costs nothing and avoids spawning
    # threads only to cancel them. Nothing counts towards the bar here --
    # the user asked not to wait for this batch at all.
    if give_up():
        for job in jobs:
            on_fallback(job)
        return BatchOutcome(len(jobs), 0, len(jobs), tally["reason"])

    if IS_WEB if sequential is None else sequential:
        for job in jobs:
            if give_up():
                on_fallback(job)
            elif not _settle_inline(job, call, served):
                on_fallback(job)
            if on_progress:
                on_progress(job)
        return BatchOutcome(len(jobs), tally["served"],
                            len(jobs) - tally["served"], tally["reason"])

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
    futures = {executor.submit(call, job): job for job in jobs}
    abandoned = False

    while futures:
        if give_up():
            abandoned = True
            for future in futures:
                future.cancel()

            for future, job in futures.items():
                # A request that came back just before the cancel still counts;
                # everything else falls back.
                if not _settle_future(future, job, served):
                    on_fallback(job)
                if on_progress:
                    on_progress(job)

            # Do not wait on in-flight API requests the user asked to abandon.
            try:
                executor.shutdown(wait=False, cancel_futures=True)
            except TypeError:   # cancel_futures landed in 3.9
                executor.shutdown(wait=False)
            break

        done, _ = concurrent.futures.wait(futures.keys(), timeout=poll,
                                          return_when=concurrent.futures.FIRST_COMPLETED)
        for future in done:
            job = futures.pop(future)
            if not _settle_future(future, job, served):
                on_fallback(job)
            if on_progress:
                on_progress(job)

    if not abandoned:
        executor.shutdown(wait=True)

    return BatchOutcome(len(jobs), tally["served"],
                        len(jobs) - tally["served"], tally["reason"])


def _settle_inline(job, call, on_result):
    """Runs one call inline. False means it produced no answer."""
    try:
        result = call(job)
    except Exception as exc:
        # The threaded path used to record the exception text as the AI's
        # actual reply, which put "THREAD ERROR: ..." in front of the player as
        # a diplomatic message. Both paths use the canned answer now and log
        # the error where it belongs.
        print(f"LLM task error: {exc}")
        return False
    on_result(job, result)
    return True


def _settle_future(future, job, on_result):
    """Records a finished future's answer. False means it had none to give."""
    if not future.done() or future.cancelled():
        return False
    try:
        result = future.result()
    except Exception as exc:
        print(f"LLM task error: {exc}")
        return False
    on_result(job, result)
    return True
