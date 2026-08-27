"""Non-blocking runner for the pygame screens that replaced the old Tk tool windows.

_run_pygame_sub_screen below covers screens layered on the live map. run_screen()
covers everything else: dialogs opened from the menus, and the standalone editors
in data/editors and map_tools that used to be their own Tk apps and so may run
with no pygame display up at all.

run_screen() takes an on_done(screen) callback instead of returning the finished
screen, and either pushes the screen onto ui/modal_stack.py (the normal in-game
case, where main.py's loop is already pumping frames) or -- only when there's no
display yet at all, i.e. a standalone dev tool with no main loop running -- falls
back to a short-lived blocking loop of its own and calls on_done() right before
returning. See ui/modal_stack.py's docstring for why the non-blocking path exists.
"""
import pygame
import data.constants as c
from gameState import dispatch_global_keys
from ui import modal_stack
from ui.bars import ui_bars


def acquire_surface(size=None, caption=None):
    """Kept as the name this module's callers use; the implementation is shared
    with ui/confirm_dialog/ via ui_bars."""
    return ui_bars.acquire_surface(size, caption)


class _ScreenModal:
    """Pushed onto the modal stack in place of a blocking loop -- see
    ui/modal_stack.py for why nothing here is allowed to block.

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
    hidden_tk = []
    if tk_parent is not None:
        from ui.confirm_dialog import _hide_tk_chain
        hidden_tk = _hide_tk_chain(tk_parent)

    screen.done = False
    clock = pygame.time.Clock()

    try:
        while not screen.done:
            events = pygame.event.get()
            for event in events:
                if event.type == pygame.QUIT:
                    import sys
                    pygame.quit()
                    sys.exit()
                dispatch_global_keys(screen, event)
            screen.handle_events(events)
            screen.update()
            screen.draw(surface)
            pygame.display.flip()
            clock.tick(c.TARGET_FPS)
    finally:
        if hidden_tk:
            from ui.confirm_dialog import _show_tk_chain
            _show_tk_chain(hidden_tk)
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
    surface, owns_display = acquire_surface(size, caption)
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
    calls on_done() if given. Never blocks -- see ui/modal_stack.py.

    Kept as the name ~25 call sites already use (21 of them via an in-function
    import). It is the map-layered flavour of run_screen: the hosting map gets
    its hover cleared on close, and on_done takes no argument.
    """
    run_screen(screen_obj, on_done, clear_hover_for=map_screen, pass_screen=False)
