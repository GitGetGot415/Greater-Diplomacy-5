"""Global stack of full-screen-blocking modals (dialogs, sub-screens, editor
popups) that main.py's loop drives instead of Controller.active_state whenever
the stack is non-empty.

A modal is any object exposing handle_events(events), update(), draw(surface).
Push one with modal_stack.push(modal); the modal is responsible for popping
itself (via modal_stack.pop()) once it has resolved -- usually from inside its
own update() -- right before invoking whatever completion callback it was given.

This exists so blocking UI (confirm dialogs, text prompts, sub-screens layered
on the map) can resolve without ever running their own nested `while` event
loop. A nested loop never returns control to main.py's `await asyncio.sleep(0)`,
which is exactly the thing that freezes the browser tab under pygbag -- there's
no real OS thread to fall back to like there is for background AI processing
(see data/platform.py's run_background). Routing everything through one stack
that the existing async loop already drives sidesteps that without requiring
every screen class to become async itself.
"""

_stack = []


def push(modal):
    # The modal being covered is about to stop receiving events -- including
    # the MOUSEBUTTONUP matching whatever MOUSEBUTTONDOWN opened this new one
    # (e.g. clicking a table row to open its detail view). Cancel any content-
    # drag it had mid-gesture now, or it's left stuck armed and the next
    # MOUSEMOTION it sees once this modal closes gets misread as a live drag.
    # See GameState.cancel_active_drags.
    if _stack:
        screen = getattr(_stack[-1], "screen", _stack[-1])
        cancel = getattr(screen, "cancel_active_drags", None)
        if cancel:
            cancel()
    _stack.append(modal)


def pop():
    if _stack:
        return _stack.pop()
    return None


def active():
    return _stack[-1] if _stack else None


def is_empty():
    return not _stack
