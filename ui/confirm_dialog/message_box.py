import pygame
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


def _show_message_standalone(title, message, tk_parent, kind, on_result):
    _run_blocking(lambda surf: _MessageModal(surf, title, message, None, kind), tk_parent)
    if on_result:
        on_result()


def show_message(title, message, tk_parent=None, kind="info", on_result=None):
    """Drop-in replacement for messagebox.showinfo / showwarning / showerror.

    `kind` picks the accent colour: "info", "success", "warning", or "error".
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
