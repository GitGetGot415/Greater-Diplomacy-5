"""Non-blocking runner for the pygame screens that replaced the old Tk tool windows.

_run_pygame_sub_screen in ui/player_diplomacy_menus.py covers screens layered on
the live map. This covers everything else: dialogs opened from the menus, and the
standalone editors in data/editors and map_tools that used to be their own Tk
apps and so may run with no pygame display up at all.

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


def acquire_surface(size=None, caption=None):
    """Returns (surface, owns_display), creating a window only when none exists."""
    surface = pygame.display.get_surface()
    if surface is not None:
        return surface, False

    if not pygame.get_init():
        pygame.init()
    surface = pygame.display.set_mode(size or (c.SCREEN_WIDTH, c.SCREEN_HEIGHT))
    if caption:
        pygame.display.set_caption(caption)
    return surface, True


class _ScreenModal:
    def __init__(self, screen, on_done):
        self.screen = screen
        self.on_done = on_done
        screen.done = False

    def handle_events(self, events):
        for event in events:
            # Mirrors the main loop so these screens get BACK/ORDERS for free.
            dispatch_global_keys(self.screen, event)
        self.screen.handle_events(events)

    def update(self):
        self.screen.update()
        if self.screen.done:
            modal_stack.pop()
            if self.on_done:
                self.on_done(self.screen)

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


def run_screen(screen_or_factory, on_done=None, tk_parent=None, caption=None, size=None):
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
    modal_stack.push(_ScreenModal(screen, on_done))
