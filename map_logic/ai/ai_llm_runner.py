"""One driver for the game's batches of LLM calls.

Three turn phases fan a list of prompts out to the model and collect the
answers: the letter passes in map_logic/ai/ai_letters.py, the proactive-message
pass in map_logic/ai/ai_diplomacy.py, and the proposal-response pass in
map_logic/diplomacy/diplomacy_processor.py. The original two had their own
copy of the same ~60 lines -- the ThreadPoolExecutor, the
`wait(timeout=0.1, FIRST_COMPLETED)` drain loop, the Force Skip cancel path,
the `shutdown(cancel_futures=)` fallback for older Pythons, and the sequential
web path -- and the two copies had drifted apart in how they treat a worker
that raises and a request that lands just as the user hits Force Skip.

What stays with the callers is what genuinely differs: which handler to call
for a job, how to record an answer, what the fallback answer is, and whether a
given job counts towards the loading bar. The progress predicates in the three
phases are deliberately *not* merged -- they key off different things.

Kept a leaf (stdlib plus data.platform) so it can be imported from anywhere in
the AI package without closing a cycle.
"""

from data.state_access import world_for, session_for
import concurrent.futures
import time
from collections import namedtuple

from data.platform import IS_WEB

from data import queries
from map_logic.ai import ai_activity, ai_settings, ai_handler


#: What a batch actually managed. `abandoned` is how many jobs never got an
#: answer because the budget ran out or Force Skip was pressed -- which used to
#: be invisible, so a turn that served one nation of twelve looked exactly like
#: a turn that served all twelve and simply had little to say.
BatchOutcome = namedtuple("BatchOutcome", "total served abandoned reason")


def make_progress_counter(context, label, done_attr, total):
    """An `on_progress` callback that ticks a counter and retitles the bar.

    All three phases wrote the same closure: bump `context.<done_attr>`, then
    format "Label (done/total)...". `total` is either an attribute name on
    context or a plain number, for a phase that counts a local list rather
    than publishing a total.

    The returned callable takes (and ignores) the job, which is the shape
    run_llm_batch hands its on_progress.
    """
    session_state = session_for(context)
    def count(_job=None):
        done = getattr(session_state, done_attr, 0) + 1
        setattr(session_state, done_attr, done)
        limit = getattr(session_state, total, 0) if isinstance(total, str) else total
        session_state.loading_status_text = f"{label} ({done}/{limit})..."

    return count


def begin_turn(context):
    """Opens the turn's LLM budget, once, before any phase spends from it.

    Without this every phase measured `ai_turn_budget_seconds` from its own
    start, so the three of them spent it three times over: a setting reading 45
    bought 135 seconds of model time, and the first phase in the turn could take
    a full third of it and still be told it was inside budget.
    """

    budget = queries.get_ai_turn_budget_seconds()
    context.llm_deadline = time.monotonic() + budget if budget else None
    ai_activity.clear()


def turn_deadline(context=None, share=1.0):
    """This phase's slice of what the turn has left, or None for no limit.

    A share rather than a fixed number of seconds, taken against the remaining
    budget at the moment the phase starts: a phase that comes in under costs the
    ones after it nothing, and a phase that would otherwise run long cannot
    empty the turn. The last phase passes 1.0 and takes the remainder.

    Called with no screen -- or before begin_turn, which is how the older tests
    and any caller outside a turn reach it -- it falls back to the whole budget
    measured from now, which is what it used to do for everyone.
    """

    end = getattr(context, "llm_deadline", None)
    if end is None:
        budget = queries.get_ai_turn_budget_seconds()
        if not budget:
            return None
        end = time.monotonic() + budget

    remaining = end - time.monotonic()
    if remaining <= 0:
        return time.monotonic()
    return time.monotonic() + remaining * max(0.0, min(1.0, share))


def report_unserved(context, outcome, what, fallback="used their staff's plan"):
    """Tells the player when the model did not get to everyone.

    `fallback` says what happens to the jobs the model did not reach.

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
                f"they {fallback}.")
    else:

        budget = queries.get_ai_turn_budget_seconds()
        levers = "ai_turn_budget_seconds"
        if ai_settings.get_ai_mode() != "OLLAMA":
            levers += " or ai_threads"
        note = (f"{what}: {outcome.served} of {outcome.total} answered inside this "
                f"phase's share of the {budget}s turn budget; the other "
                f"{outcome.abandoned} {fallback}. Raise "
                f"{levers} to reach more.")
    print(f"[AI] {note}")
    show = getattr(context, "show_feedback", None)
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

    typical = ai_handler.typical_call_seconds()
    if not typical:
        return True
    return deadline - time.monotonic() >= typical * calls


def run_llm_batch(jobs, call, on_result, on_fallback, **options):
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
    - `phase` and `describe(job)` name the batch and each job on the turn
      loading screen (see ai_activity). `describe` runs on the calling thread
      before any request goes out, so it may read game state.

    `sequential` defaults to IS_WEB: Pyodide has no real OS threads, and AI
    networking is disabled on web anyway (see ai_handler's IS_WEB guard), so
    every call returns its fallback immediately rather than blocking.

    Returns a BatchOutcome saying how many jobs actually got an answer. The
    caller is expected to tell the player when that is fewer than it asked for:
    running out of budget used to look exactly like having nothing to say.
    """
    return start_llm_batch(jobs, call, on_result, on_fallback, **options).collect()


def start_llm_batch(jobs, call, on_result, on_fallback, **options):
    """Sends a batch's requests and returns at once. See run_llm_batch.

    The answers are recorded only by LLMBatch.collect, on the thread that
    calls it, so the caller can do other work while the requests are out.
    `call` must therefore not read game state that the caller changes in the
    meantime: build each job's prompt before starting the batch.
    """
    return LLMBatch(jobs, call, on_result, on_fallback, **options)


def _shutdown_now(executor):
    """Stops an executor without waiting on in-flight API requests."""
    try:
        executor.shutdown(wait=False, cancel_futures=True)
    except TypeError:   # cancel_futures landed in 3.9
        executor.shutdown(wait=False)


class LLMBatch:
    """A started batch. collect() records its answers; close() abandons it."""

    def __init__(self, jobs, call, on_result, on_fallback, on_progress=None,
                 should_abort=None, max_workers=1, poll=0.1, sequential=None,
                 deadline=None, min_calls=1, phase="Model requests", describe=None):
        self.jobs = list(jobs)
        self.call = call
        self.on_result = on_result
        self.on_fallback = on_fallback
        self.on_progress = on_progress
        self.should_abort = should_abort
        self.poll = poll
        self.deadline = deadline
        self.served = 0
        self.reason = ""
        self.declined = False
        self.sequential = False
        self.executor = None
        self.futures = {}
        self.outcome = None
        self.activity = None
        self.labels = []

        if not self.jobs:
            return

        # Skipping before any request goes out costs nothing and avoids spawning
        # threads only to cancel them. Nothing counts towards the bar here --
        # the user asked not to wait for this batch at all.
        if self._give_up():
            self.declined = True
            return

        # Declining is not the same as running out, and is checked after it: a
        # deadline already in the past is a batch with no budget, which is what
        # "budget" has always meant. This is the other case -- time left, but not
        # enough of it to finish the smallest piece of work this batch can show
        # for itself, so the slice goes to the next phase instead of being spent
        # on a request that will be cut off. `min_calls` is that smallest piece:
        # one, where a job is a single request; more where a job only produces
        # something after several requests.
        if not affordable(deadline, min_calls):
            self.reason = "unaffordable"
            self.declined = True
            return

        # Labelled here, on the calling thread, because describe may read
        # game state that the caller changes while the requests are out.
        self.labels = [describe(job) if describe else phase for job in self.jobs]
        self.sequential = IS_WEB if sequential is None else sequential
        self.activity = ai_activity.start_batch(phase, len(self.jobs),
                                                1 if self.sequential else max_workers)

        # The sequential path sends nothing until collect, which runs every job
        # inline on the collecting thread.
        if self.sequential:
            return

        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
        self.futures = {self.executor.submit(self._run, job, label): job
                        for job, label in zip(self.jobs, self.labels)}

    def _run(self, job, label):
        """`call(job)`, recorded as one request on the turn loading screen."""
        request = self.activity.begin(label)
        try:
            result = self.call(job)
        except Exception:
            self.activity.end(request, ai_activity.FAILED)
            raise
        self.activity.end(request, request.outcome or ai_activity.DONE)
        return result

    def _give_up(self):
        if self.should_abort and self.should_abort():
            self.reason = self.reason or "skipped"
            return True
        if self.deadline is not None and time.monotonic() >= self.deadline:
            self.reason = self.reason or "budget"
            return True
        return False

    def _served(self, job, result):
        self.served += 1
        self.on_result(job, result)

    def _resolved(self, job, answered):
        if not answered:
            self.on_fallback(job)
        if self.on_progress:
            self.on_progress(job)

    def collect(self):
        """Waits for the answers, records each one, and returns a BatchOutcome."""
        if self.outcome is not None:
            return self.outcome

        if self.declined:
            for job in self.jobs:
                self.on_fallback(job)
        elif self.sequential:
            for job, label in zip(self.jobs, self.labels):
                run = lambda job, label=label: self._run(job, label)
                self._resolved(job, not self._give_up()
                               and _settle_inline(job, run, self._served))
        elif self.executor is not None:
            self._drain()
        if self.activity is not None:
            self.activity.close()

        total = len(self.jobs)
        self.outcome = BatchOutcome(total, self.served, total - self.served, self.reason)
        return self.outcome

    def _drain(self):
        futures = self.futures
        while futures:
            if self._give_up():
                for future in futures:
                    future.cancel()
                _hang_up()

                for future, job in futures.items():
                    # A request that came back just before the cancel still counts;
                    # everything else falls back.
                    self._resolved(job, _settle_future(future, job, self._served))

                futures.clear()
                _shutdown_now(self.executor)
                return

            done, _ = concurrent.futures.wait(futures.keys(), timeout=self.poll,
                                              return_when=concurrent.futures.FIRST_COMPLETED)
            for future in done:
                job = futures.pop(future)
                self._resolved(job, _settle_future(future, job, self._served))

        self.executor.shutdown(wait=True)

    def close(self):
        """Abandons a batch that will not be collected, recording nothing.

        For a turn that fails between start and collect: its requests would
        otherwise keep streaming, and a hosted provider would bill them.
        """
        if self.outcome is not None:
            return
        if self.futures:
            for future in self.futures:
                future.cancel()
            _hang_up()
            self.futures.clear()
            _shutdown_now(self.executor)
        if self.activity is not None:
            self.activity.close()
        total = len(self.jobs)
        self.outcome = BatchOutcome(total, self.served, total - self.served,
                                    self.reason or "skipped")


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
