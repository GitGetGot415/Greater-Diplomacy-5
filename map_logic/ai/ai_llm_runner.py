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

from data.platform import IS_WEB


def run_llm_batch(jobs, call, on_result, on_fallback, on_progress=None,
                  should_abort=None, max_workers=1, poll=0.1, sequential=None):
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

    `sequential` defaults to IS_WEB: Pyodide has no real OS threads, and AI
    networking is disabled on web anyway (see ai_handler's IS_WEB guard), so
    every call returns its fallback immediately rather than blocking.
    """
    jobs = list(jobs)
    if not jobs:
        return

    # Skipping before any request goes out costs nothing and avoids spawning
    # threads only to cancel them. Nothing counts towards the bar here --
    # the user asked not to wait for this batch at all.
    if should_abort and should_abort():
        for job in jobs:
            on_fallback(job)
        return

    if IS_WEB if sequential is None else sequential:
        for job in jobs:
            if not _settle_inline(job, call, on_result):
                on_fallback(job)
            if on_progress:
                on_progress(job)
        return

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
    futures = {executor.submit(call, job): job for job in jobs}
    abandoned = False

    while futures:
        if should_abort and should_abort():
            abandoned = True
            for future in futures:
                future.cancel()

            for future, job in futures.items():
                # A request that came back just before the cancel still counts;
                # everything else falls back.
                if not _settle_future(future, job, on_result):
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
            if not _settle_future(future, job, on_result):
                on_fallback(job)
            if on_progress:
                on_progress(job)

    if not abandoned:
        executor.shutdown(wait=True)


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
