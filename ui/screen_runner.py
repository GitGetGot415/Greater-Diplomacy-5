"""Blocking runner for the pygame screens that replaced the old Tk tool windows.

_run_pygame_sub_screen in ui/player_diplomacy_menus.py covers screens layered on
the live map. This covers everything else: dialogs opened from the menus, and the
standalone editors in data/editors and map_tools that used to be their own Tk
apps and so may run with no pygame display up at all.
"""
import pygame
import data.constants as c
from gameState import dispatch_global_keys


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


def run_screen(screen_or_factory, tk_parent=None, caption=None, size=None):
    """Runs a screen until it marks itself done, then returns it.

    Pass a zero-argument factory rather than a screen when the screen's
    constructor needs a display to exist (anything that reads the current
    surface or builds fonts) -- it is called after the window is up.

    Closing the window cancels just this screen when the call created the
    window, and exits the game when it did not, matching the main loop.
    """
    surface, owns_display = acquire_surface(size, caption)

    hidden_tk = []
    if tk_parent is not None:
        from ui.confirm_dialog import _hide_tk_chain
        hidden_tk = _hide_tk_chain(tk_parent)

    screen = screen_or_factory() if callable(screen_or_factory) else screen_or_factory
    screen.done = False
    clock = pygame.time.Clock()

    try:
        while not screen.done:
            events = pygame.event.get()
            for event in events:
                if event.type == pygame.QUIT:
                    if owns_display:
                        screen.done = True
                    else:
                        import sys
                        pygame.quit()
                        sys.exit()
                # Mirrors the main loop so these screens get BACK/ORDERS for free.
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
        if owns_display:
            pygame.display.quit()
        else:
            # Clear the phantom inputs the blocking loop leaves behind.
            pygame.event.pump()

    return screen
