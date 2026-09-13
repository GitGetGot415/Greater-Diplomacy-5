import pygame
from data import queries
from ui import modal_stack
from ui.confirm_dialog.base import _BaseModal, _back_key, _lighten, _run_blocking

_KIND_ACCENTS = {
    "info": (80, 150, 220),
    "success": (60, 170, 90),
    "warning": (210, 160, 40),
    "error": (200, 70, 70),
}


class _MessageModal(_BaseModal):
    BOX_MAX_W = 520
    BOX_CHROME_H = 170   # 110 of chrome plus the 60 the OK row occupies
    BORDER_WIDTH = 3
    PASSES_RESULT = False

    def __init__(self, surface, title, message, on_result, kind):
        self.accent = _KIND_ACCENTS.get(kind, _KIND_ACCENTS["info"])
        super().__init__(surface, title, message, on_result)
        self.BORDER_COLOR = self.accent
        self.ok_rect = pygame.Rect(self.box_rect.centerx - 60, self.box_rect.bottom - 55, 120, 40)

    def handle_events(self, events):
        for event in events:
            if event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_ESCAPE,
                                 pygame.K_SPACE, _back_key()):
                    self._finish()
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self.ok_rect.collidepoint(event.pos):
                    self._finish()

    def draw_content(self, surface):
        self.draw_button(surface, self.ok_rect, "OK", self.accent, _lighten(self.accent))


class _NavigationIntroModal(_BaseModal):
    """One-time fresh-game tutorial with a persisted opt-out checkbox."""
    BOX_MAX_W = 610
    BOX_CHROME_H = 205
    BORDER_COLOR = _KIND_ACCENTS["info"]

    def __init__(self, surface):
        super().__init__(
            surface, "Map Navigation",
            "Left-click unit stacks to select them. With units selected, right-click "
            "a province to order movement; Shift+right-click adds a waypoint.\n"
            "Middle-mouse drag pans the map. In Units view, right-drag draws a "
            "selection box; Shift+right-drag adds to the selection.",
            None, extra_h=40)
        self.dont_show_again = False
        self.checkbox_rect = pygame.Rect(self.box_rect.x + 42, self.box_rect.bottom - 88, 22, 22)
        self.ok_rect = pygame.Rect(self.box_rect.centerx - 70, self.box_rect.bottom - 48, 140, 34)

    def handle_events(self, events):
        for event in events:
            if event.type == pygame.KEYDOWN and event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_ESCAPE, _back_key()):
                self._finish()
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self.checkbox_rect.collidepoint(event.pos):
                    self.dont_show_again = not self.dont_show_again
                elif self.ok_rect.collidepoint(event.pos):
                    self._finish()

    def update(self):
        if self._resolved and self.dont_show_again:
            settings = dict(queries.get_settings() or {})
            settings["show_intro_popup"] = False
            queries.save_cached_json("settings", settings)
        super().update()

    def draw_content(self, surface):
        pygame.draw.rect(surface, (230, 230, 230), self.checkbox_rect, 2)
        if self.dont_show_again:
            pygame.draw.line(surface, (80, 190, 100), self.checkbox_rect.topleft,
                             self.checkbox_rect.bottomright, 3)
            pygame.draw.line(surface, (80, 190, 100), self.checkbox_rect.topright,
                             self.checkbox_rect.bottomleft, 3)
        label = self.msg_font.render("Don't show this popup again", True, (220, 220, 220))
        surface.blit(label, (self.checkbox_rect.right + 10, self.checkbox_rect.y))
        self.draw_button(surface, self.ok_rect, "Got it", self.BORDER_COLOR,
                         _lighten(self.BORDER_COLOR))


def _show_message_standalone(title, message, tk_parent, kind, on_result):
    _run_blocking(lambda surf: _MessageModal(surf, title, message, None, kind), tk_parent)
    if on_result:
        on_result()


def show_message(title, message, tk_parent=None, kind="info", on_result=None):
    """Drop-in replacement for messagebox.showinfo / showwarning / showerror.

    `kind` picks the accent color: "info", "success", "warning", or "error".
    on_result, if given, is called (with no arguments) once the user dismisses it.
    """
    surface = pygame.display.get_surface()
    if surface is None:
        _show_message_standalone(title, message, tk_parent, kind, on_result)
        return

    modal_stack.push(_MessageModal(surface, title, message, on_result, kind))


def show_info(title, message, tk_parent=None, on_result=None):
    show_message(title, message, tk_parent=tk_parent, kind="info", on_result=on_result)


def show_success(title, message, tk_parent=None, on_result=None):
    show_message(title, message, tk_parent=tk_parent, kind="success", on_result=on_result)


def show_warning(title, message, tk_parent=None, on_result=None):
    show_message(title, message, tk_parent=tk_parent, kind="warning", on_result=on_result)


def show_error(title, message, tk_parent=None, on_result=None):
    show_message(title, message, tk_parent=tk_parent, kind="error", on_result=on_result)


def show_navigation_intro():
    """Push the non-blocking fresh-game navigation tutorial."""
    surface = pygame.display.get_surface()
    if surface is not None:
        modal_stack.push(_NavigationIntroModal(surface))
