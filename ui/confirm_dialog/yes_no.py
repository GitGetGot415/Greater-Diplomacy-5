import pygame
from ui import modal_stack
from ui.confirm_dialog.base import _BaseModal, _back_key, _run_blocking


class _YesNoModal(_BaseModal):
    BOX_MAX_W = 520

    def __init__(self, surface, title, message, on_result, yes_label, no_label):
        super().__init__(surface, title, message, on_result)
        self.yes_rect = pygame.Rect(self.box_rect.centerx - 140, self.box_rect.bottom - 55, 120, 40)
        self.no_rect = pygame.Rect(self.box_rect.centerx + 20, self.box_rect.bottom - 55, 120, 40)
        self.yes_label = yes_label
        self.no_label = no_label

    def handle_events(self, events):
        for event in events:
            if event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_y):
                    self._finish(True)
                elif event.key in (pygame.K_ESCAPE, pygame.K_n, _back_key()):
                    self._finish(False)
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self.yes_rect.collidepoint(event.pos):
                    self._finish(True)
                elif self.no_rect.collidepoint(event.pos):
                    self._finish(False)

    def draw_content(self, surface):
        self.draw_button(surface, self.yes_rect, self.yes_label, (0, 150, 0), (0, 190, 0))
        self.draw_button(surface, self.no_rect, self.no_label, (150, 0, 0), (190, 0, 0))


def _ask_yes_no_standalone(title, message, on_result, tk_parent, yes_label, no_label):
    result = _run_blocking(
        lambda surf: _YesNoModal(surf, title, message, None, yes_label, no_label),
        tk_parent, default_result=False)
    on_result(bool(result))


def ask_yes_no(title, message, on_result, tk_parent=None, yes_label="Yes", no_label="No"):
    """Answers on_result(True/False) once the user picks Yes or No.

    tk_parent, if given, is a tkinter widget to hide for the dialog's duration --
    only meaningful for the standalone dev-tool path (no game display up yet).
    """
    surface = pygame.display.get_surface()
    if surface is None:
        _ask_yes_no_standalone(title, message, on_result, tk_parent, yes_label, no_label)
        return

    modal_stack.push(_YesNoModal(surface, title, message, on_result, yes_label, no_label))
