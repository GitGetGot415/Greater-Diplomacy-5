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


def begin_turn(map_screen):
    """Opens the turn's LLM budget, once, before any phase spends from it.

    Without this every phase measured `ai_turn_budget_seconds` from its own
    start, so the three of them spent it three times over: a setting reading 45
    bought 135 seconds of model time, and the first phase in the turn -- summits
    -- could take a full third of it and still be told it was inside budget.
    """
    from data import queries

    budget = queries.get_ai_turn_budget_seconds()
    map_screen.llm_deadline = time.monotonic() + budget if budget else None


def turn_deadline(map_screen=None, share=1.0):
    """This phase's slice of what the turn has left, or None for no limit.

    A share rather than a fixed number of seconds, taken against the remaining
    budget at the moment the phase starts: a phase that comes in under costs the
    ones after it nothing, and a phase that would otherwise run long cannot
    empty the turn. The last phase passes 1.0 and takes the remainder.

    Called with no screen -- or before begin_turn, which is how the older tests
    and any caller outside a turn reach it -- it falls back to the whole budget
    measured from now, which is what it used to do for everyone.
    """
    from data import queries

    end = getattr(map_screen, "llm_deadline", None)
    if end is None:
        budget = queries.get_ai_turn_budget_seconds()
        if not budget:
            return None
        end = time.monotonic() + budget

    remaining = end - time.monotonic()
    if remaining <= 0:
        return time.monotonic()
    return time.monotonic() + remaining * max(0.0, min(1.0, share))


def report_unserved(map_screen, outcome, what):
    """Tells the player when the model did not get to everyone.

    A batch that ran out of budget looked identical to a batch with nothing to
    say: the loading bar counted up to whatever it reached, and then the turn
    carried on. On one thread against a local model that can be one nation of
    twelve, which reads as the game having quietly given up -- and it names the
    settings that decide how many are reachable, since none of them is guessable
    from the outside.

    ai_threads is named only where it would help. A hosted provider answers
    concurrent requests independently, so more of them is close to free
    throughput; a local Ollama is one model on one GPU, and telling someone to
    raise a number that will make their turn slower is worse than saying
    nothing.
    """
    if not outcome or not outcome.abandoned:
        return
    if outcome.reason == "unaffordable":
        # Nothing was spent and nothing was lost, so there is nothing to
        # explain. This report exists to account for time that went somewhere
        # the player could not see; a phase that declined to start took none.
        print(f"[AI] {what}: skipped, too little of the turn's budget left to "
              f"be worth starting.")
        return
    if outcome.reason == "skipped":
        note = (f"{what}: skipped {outcome.abandoned} of {outcome.total}; "
                f"they used their staff's plan.")
    else:
        from data import queries
        from map_logic.ai import ai_settings

        budget = queries.get_ai_turn_budget_seconds()
        levers = "ai_turn_budget_seconds"
        if ai_settings.get_ai_mode() != "OLLAMA":
            levers += " or ai_threads"
        note = (f"{what}: {outcome.served} of {outcome.total} answered inside this "
                f"phase's share of the {budget}s turn budget; the other "
                f"{outcome.abandoned} used their staff's plan. Raise "
                f"{levers} to reach more.")
    print(f"[AI] {note}")
    show = getattr(map_screen, "show_feedback", None)
    if show:
        show(note)


def affordable(deadline, calls):
    """Whether `deadline` leaves room for that many requests.

    A phase whose share cannot cover the smallest useful piece of work spends
    the share anyway and produces nothing: it starts a request, gets cut off
    at the deadline, and hands the next phase a budget shorter by the whole
    slice. Better to decline and let the time go to somebody who can use it.

    Unmeasured means unknown, and unknown is not a reason to refuse -- the
    first batch of a session finds out what a call costs by making one.
    """
    if deadline is None:
        return True
    from map_logic.ai import ai_handler

    typical = ai_handler.typical_call_seconds()
    if not typical:
        return True
    return deadline - time.monotonic() >= typical * calls


def run_llm_batch(jobs, call, on_result, on_fallback, on_progress=None,
                  should_abort=None, max_workers=1, poll=0.1, sequential=None,
                  deadline=None, min_calls=1):
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

    # Declining is not the same as running out, and is checked after it: a
    # deadline already in the past is a batch with no budget, which is what
    # "budget" has always meant. This is the other case -- time left, but not
    # enough of it to finish the smallest piece of work this batch can show
    # for itself, so the slice goes to the next phase instead of being spent
    # on a request that will be cut off. `min_calls` is that smallest piece:
    # one, where a job is a single request; two for a summit, because one
    # leader speaking with nobody answering is not a meeting and is not
    # published.
    if not affordable(deadline, min_calls):
        tally["reason"] = "unaffordable"
        for job in jobs:
            on_fallback(job)
        return BatchOutcome(len(jobs), 0, len(jobs), "unaffordable")

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
            _hang_up()

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


def _hang_up():
    """Ends the requests a batch has just stopped waiting for.

    future.cancel() only refuses to *start* a job; the one already blocked
    reading a reply is untouched by it, and by shutdown(wait=False) too. So the
    request a batch abandoned went on streaming into the next phase, spending
    17 to 19 seconds of a budget that had been handed to somebody else, and its
    answer was discarded on arrival because the batch that asked for it had
    already recorded a fallback.

    Imported here rather than at module scope on purpose: this file is a leaf
    (see the module docstring) and ai_handler is not, so the import has to
    happen after both are loaded.
    """
    try:
        from map_logic.ai import ai_handler
        ai_handler.abort_active_requests()
    except Exception:
        # Never let tidying up be the thing that ends a turn.
        pass


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
