import pygame
from ui.dialogs.base import _BaseModal, _back_key, open_modal
from ui.widgets import ui_elements


class _YesNoModal(_BaseModal):
    BOX_MAX_W = 520
    BACK_BUTTON_GAP = 20
    BUTTON_MIN_W = 120
    BUTTON_TEXT_PADDING = 12

    def __init__(self, surface, title, message, on_result, yes_label, no_label, back_label=None):
        super().__init__(surface, title, message, on_result)
        self.yes_label = yes_label
        self.no_label = no_label
        self.back_label = back_label
        labels = [yes_label, no_label] + ([back_label] if back_label is not None else [])
        widths = [max(self.BUTTON_MIN_W, self.btn_font.size(label)[0] + 2 * self.BUTTON_TEXT_PADDING)
                  for label in labels]
        gap = self.BACK_BUTTON_GAP if back_label is not None else 2 * self.BACK_BUTTON_GAP
        x = self.box_rect.centerx - (sum(widths) + gap * (len(widths) - 1)) // 2
        rects = []
        for width in widths:
            rects.append(pygame.Rect(x, self.box_rect.bottom - 55, width, 40))
            x += width + gap
        self.yes_rect, self.no_rect = rects[:2]
        self.back_rect = rects[2] if back_label is not None else None

    def handle_events(self, events):
        for event in events:
            if event.type == pygame.KEYDOWN:
                if self.back_rect is not None and event.key in (pygame.K_ESCAPE, _back_key(), pygame.K_g):
                    ui_elements.play_ui_sound("back")
                    self._finish(None)
                elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_y):
                    self._finish(True)
                elif event.key in (pygame.K_ESCAPE, pygame.K_n, _back_key()):
                    self._finish(False)
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self.yes_rect.collidepoint(event.pos):
                    self._finish(True)
                elif self.no_rect.collidepoint(event.pos):
                    self._finish(False)
                elif self.back_rect is not None and self.back_rect.collidepoint(event.pos):
                    ui_elements.play_ui_sound("back")
                    self._finish(None)

    def draw_content(self, surface):
        self.draw_button(surface, self.yes_rect, self.yes_label, (0, 150, 0), (0, 190, 0))
        self.draw_button(surface, self.no_rect, self.no_label, (150, 0, 0), (190, 0, 0))
        if self.back_rect is not None:
            self.draw_button(surface, self.back_rect, self.back_label, (0, 100, 150), (0, 140, 190))


def ask_yes_no(title, message, on_result, tk_parent=None, yes_label="Yes", no_label="No", back_label=None):
    """Answers on_result(True/False) once the user picks Yes or No.

    An optional back_label adds a third button that returns None.
    Back and Escape also return None when this button is present.

    tk_parent, if given, is a tkinter widget to hide for the dialog's duration --
    only meaningful for the standalone dev-tool path (no game display up yet).
    """
    open_modal(lambda surface, callback: _YesNoModal(surface, title, message, callback,
                                                     yes_label, no_label, back_label),
               on_result, tk_parent, default_result=None if back_label is not None else False)
