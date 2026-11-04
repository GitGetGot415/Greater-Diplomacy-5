"""Non-blocking runner for the pygame screens that replaced the old Tk tool windows.

_run_pygame_sub_screen below covers screens layered on the live map. run_screen()
covers everything else: dialogs opened from the menus, and the standalone editors
in scripts/editors and scripts/maps that used to be their own Tk apps and so may run
with no pygame display up at all.

run_screen() takes an on_done(screen) callback instead of returning the finished
screen, and either pushes the screen onto ui/navigation/modal_stack.py (the normal in-game
case, where main.py's loop is already pumping frames) or -- only when there's no
display yet at all, i.e. a standalone dev tool with no main loop running -- falls
back to a short-lived blocking loop of its own and calls on_done() right before
returning. See ui/navigation/modal_stack.py's docstring for why the non-blocking path exists.
"""

import sys
from threading import Event

import pygame
import data.constants as c
from ui.navigation.screen import (dispatch_global_keys, synthesize_keybind_mouse_events,
                       keyboard_input_is_captured)
from ui.navigation import modal_stack
from ui.bars import ui_bars
from ui.panels import turn_progress
from data.platform import IS_WEB, run_background

from ui.dialogs.base import tk_hidden


class _LoadingModal:
    """Run staged loading with the normal event loop owning the display.

    Desktop work runs on one worker while the UI draws only a frozen background.
    Web advances one stage per frame because its runtime has no worker threads.
    Completion and error callbacks always run on the UI thread.
    """

    # Fullscreen changes must not replace the display during surface construction.
    listening_for = True
    text_input_active = True

    def __init__(self, steps, status, on_done, on_error):
        self.steps = iter(steps)
        self.total = steps.total
        self.completed = 0
        self.stage_started = False
        self.status = status
        self.on_done = on_done
        self.on_error = on_error
        self.background = pygame.display.get_surface().copy()
        self.drawn = False
        self.started = False
        self.finished = Event()
        self.result = None
        self.error = None

    def handle_events(self, events):
        pass

    def _advance(self):
        try:
            self.status = next(self.steps)
            if self.stage_started:
                self.completed += 1
            self.stage_started = True
        except StopIteration as done:
            if self.stage_started:
                self.completed += 1
            self.result = done.value
            self.finished.set()
        except Exception as error:
            # This job boundary reports failed loads instead of stranding the modal.
            self.error = error
            self.finished.set()

    def _run(self):
        while not self.finished.is_set():
            self._advance()

    def update(self):
        if not self.drawn:
            return
        if self.finished.is_set():
            modal_stack.pop()
            if self.error is not None:
                self.on_error(self.error)
            elif self.on_done:
                self.on_done(self.result)
            return
        if IS_WEB:
            self._advance()
        elif not self.started:
            self.started = True
            run_background(self._run)

    def draw(self, surface):
        surface.blit(self.background, (0, 0))
        turn_progress.draw_simple_refresh_bar(surface, self.status, self.completed, self.total)
        self.drawn = True


def run_loading(steps, status="Loading...", on_done=None, on_error=None):
    """Show completed/total progress for a LoadingSteps iterator."""
    if on_error is None:
        # dialogs imports screen_runner through its shared screen components.
        from ui import dialogs
        on_error = lambda error: dialogs.show_error("Load Failed", str(error))
    modal_stack.push(_LoadingModal(steps, status, on_done, on_error))


class _ScreenModal:
    """Pushed onto the modal stack in place of a blocking loop -- see
    ui/navigation/modal_stack.py for why nothing here is allowed to block.

    `clear_hover_for` is the map screen to wipe hovered_province on when the
    sub-screen closes: a screen layered over the live map leaves the province
    under the cursor highlighted otherwise. `pass_screen` is False for the
    callers whose on_done takes no argument.
    """

    def __init__(self, screen, on_done, clear_hover_for=None, pass_screen=True):
        self.screen = screen
        self.on_done = on_done
        self.clear_hover_for = clear_hover_for
        self.pass_screen = pass_screen
        screen.done = False

    def handle_events(self, events):
        for event in events:
            # Mirrors the main loop so screens get rebindable actions for free.
            dispatch_global_keys(self.screen, event)
        self.screen.handle_events(events)

    def update(self):
        self.screen.update()
        if self.screen.done:
            modal_stack.pop()
            if self.clear_hover_for is not None:
                self.clear_hover_for.hovered_province = None
            if self.on_done:
                self.on_done(self.screen) if self.pass_screen else self.on_done()

    def draw(self, surface):
        self.screen.draw(surface)


def _run_screen_standalone(screen, on_done, tk_parent, surface):
    """No main loop is pumping frames here, so resolve with our own blocking loop."""
    screen.done = False
    clock = pygame.time.Clock()

    try:
        with tk_hidden(tk_parent):
            while not screen.done:
                events = pygame.event.get()
                events = synthesize_keybind_mouse_events(
                    events, allow_keydown=not keyboard_input_is_captured(screen))
                for event in events:
                    if event.type == pygame.QUIT:
                        pygame.quit()
                        sys.exit()
                    dispatch_global_keys(screen, event)
                screen.handle_events(events)
                screen.update()
                screen.draw(surface)
                pygame.display.flip()
                clock.tick(c.TARGET_FPS)
    finally:
        pygame.display.quit()

    if on_done:
        on_done(screen)


def run_screen(screen_or_factory, on_done=None, tk_parent=None, caption=None, size=None,
               clear_hover_for=None, pass_screen=True):
    """Runs a screen until it marks itself done, then calls on_done(screen).

    Pass a zero-argument factory rather than a screen when the screen's
    constructor needs a display to exist (anything that reads the current
    surface or builds fonts) -- it is called after the window is up.

    Closing the window cancels just this screen when the call created the
    window (the standalone path below), and exits the game when it did not,
    matching the main loop's own QUIT handling.
    """
    surface, owns_display = ui_bars.acquire_surface(size, caption)
    screen = screen_or_factory() if callable(screen_or_factory) else screen_or_factory

    if owns_display:
        _run_screen_standalone(screen, on_done, tk_parent, surface)
        return

    # Embedded case: main.py's loop is already running, so hand off to the modal
    # stack instead of blocking. tk_parent doesn't apply here -- nothing tkinter
    # is ever on screen at the same time as the live game.
    modal_stack.push(_ScreenModal(screen, on_done, clear_hover_for, pass_screen))


def _run_pygame_sub_screen(map_screen, screen_obj, on_done=None):
    """Pushes screen_obj onto the modal stack until it marks itself done, then
    calls on_done() if given. Never blocks -- see ui/navigation/modal_stack.py.

    Kept as the name ~25 call sites already use (21 of them via an in-function
    import). It is the map-layered flavour of run_screen: the hosting map gets
    its hover cleared on close, and on_done takes no argument.
    """
    run_screen(screen_obj, on_done, clear_hover_for=map_screen, pass_screen=False)
