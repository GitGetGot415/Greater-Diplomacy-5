"""What each model worker thread is doing, for the turn loading screen.

ai_llm_runner opens a BatchActivity for every batch it starts, and each worker
records one RequestActivity per job it runs. ai_handler adds the model's text
to the worker's current request as it arrives: token by token from Ollama,
and all at once from the hosted providers, which do not stream.

The turn thread and the worker threads write here and the UI thread reads, so
every read and write takes _LOCK. Nothing here feeds back into game rules.

A leaf (stdlib only), so ai_handler, ai_llm_runner and the UI can all import it.
"""

import threading
import time

WAITING = "Waiting for model"
WRITING = "Writing"
DONE = "Done"
FAILED = "Failed"
STOPPED = "Stopped"

_LOCK = threading.Lock()
_WORKER = threading.local()
_BATCH = [None]


class RequestActivity:
    """One job on one worker thread."""

    def __init__(self, slot, label):
        self.slot = slot
        self.label = label
        self.started = time.monotonic()
        self.finished = None
        self.state = WAITING
        # FAILED or STOPPED once a provider call reports one; None means Done.
        self.outcome = None
        self.revision = 0
        self._chunks = []

    def add_output(self, text):
        if not text:
            return
        with _LOCK:
            self._chunks.append(text)
            if self.state == WAITING:
                self.state = WRITING
            self.revision += 1

    def output(self):
        with _LOCK:
            return "".join(self._chunks)

    def has_output(self):
        with _LOCK:
            return bool(self._chunks)

    def finish(self, state):
        """Ends the request. The first ending wins, so a worker that returns
        after its batch gave up on it stays Stopped."""
        with _LOCK:
            if self.finished is not None:
                return False
            self.finished = time.monotonic()
            self.state = state
            self.revision += 1
            return True

    def elapsed(self, now=None):
        end = self.finished if self.finished is not None else (now or time.monotonic())
        return max(0.0, end - self.started)


class BatchActivity:
    """One batch: its phase, its job counts, and one row per worker thread."""

    def __init__(self, phase, total, threads):
        self.phase = phase
        self.total = total
        self.slots = [None] * max(1, threads)
        self.started = 0
        self.finished = 0
        self.ended = False

    def begin(self, label):
        """Records a job starting on the lowest free thread row."""
        with _LOCK:
            index = next((i for i, request in enumerate(self.slots)
                          if request is None or request.finished is not None), None)
            if index is None:
                # More running jobs than rows means the caller sized the batch
                # wrongly; show the job anyway rather than losing it.
                self.slots.append(None)
                index = len(self.slots) - 1
            request = RequestActivity(index + 1, label)
            self.slots[index] = request
            self.started += 1
        _WORKER.request = request
        return request

    def end(self, request, state):
        if request.finish(state):
            with _LOCK:
                self.finished += 1
        _WORKER.request = None

    def close(self):
        """Ends the batch. A request still out was abandoned, so it is Stopped,
        and a job that never started will not start."""
        with _LOCK:
            self.ended = True
            running = [request for request in self.slots
                       if request is not None and request.finished is None]
        for request in running:
            if request.finish(STOPPED):
                with _LOCK:
                    self.finished += 1

    def rows(self):
        """(slot number, request or None) for every thread row."""
        with _LOCK:
            return [(index + 1, request) for index, request in enumerate(self.slots)]

    def counts(self):
        """(running, waiting, finished, skipped) job counts."""
        with _LOCK:
            running = sum(1 for request in self.slots
                          if request is not None and request.finished is None)
            unstarted = max(0, self.total - self.started)
            if self.ended:
                return running, 0, self.finished, unstarted
            return running, unstarted, self.finished, 0


def start_batch(phase, total, threads):
    batch = BatchActivity(phase, total, threads)
    with _LOCK:
        _BATCH[0] = batch
    return batch


def current_batch():
    with _LOCK:
        return _BATCH[0]


def clear():
    """Forgets the previous turn's batches."""
    with _LOCK:
        _BATCH[0] = None


def record_output(text):
    """Adds model text to the calling worker's current request, if it has one."""
    request = getattr(_WORKER, "request", None)
    if request is not None:
        request.add_output(text)


def record_reply(reply, as_text):
    """Records how a provider call ended for the calling worker's request.

    None is an abandoned call (Force Skip or a closed socket): Stopped. An
    error reply is Failed and always shows its message. `as_text` turns any
    other parsed reply into text, shown only when nothing streamed in, so a
    hosted provider's whole reply still appears.
    """
    request = getattr(_WORKER, "request", None)
    if request is None:
        return
    if reply is None:
        request.outcome = STOPPED
    elif not isinstance(reply, dict):
        return
    elif reply.get("error"):
        request.outcome = FAILED
        prefix = "\n" if request.has_output() else ""
        request.add_output(f"{prefix}{reply.get('message', '')}")
    elif not request.has_output():
        request.add_output(as_text(reply))
