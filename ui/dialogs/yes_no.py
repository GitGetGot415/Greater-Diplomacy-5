import pygame
from ui.dialogs.base import DialogScreen, open_dialog
from ui.rendering.font_manager import fonts


class _YesNoModal(DialogScreen):
    BOX_MAX_W = 520
    BACK_BUTTON_GAP = 20
    BUTTON_MIN_W = 120
    BUTTON_TEXT_PADDING = 12

    def __init__(self, surface, title, message, yes_label, no_label, back_label=None):
        # Without a third button, closing or cancelling the dialog means No.
        self.DEFAULT_RESULT = None if back_label is not None else False
        super().__init__(surface, title, message)
        self.yes_label = yes_label
        self.no_label = no_label
        self.back_label = back_label
        labels = [yes_label, no_label] + ([back_label] if back_label is not None else [])
        btn_font = fonts.get("button")
        widths = [max(self.BUTTON_MIN_W, btn_font.size(label)[0] + 2 * self.BUTTON_TEXT_PADDING)
                  for label in labels]
        gap = self.BACK_BUTTON_GAP if back_label is not None else 2 * self.BACK_BUTTON_GAP
        x = self.panel_rect.centerx - (sum(widths) + gap * (len(widths) - 1)) // 2
        rects = []
        for width in widths:
            rects.append(pygame.Rect(x, self.panel_rect.bottom - 55, width, 40))
            x += width + gap
        self.yes_rect, self.no_rect = rects[:2]
        self.back_rect = rects[2] if back_label is not None else None

        self.add_button(self.yes_rect, yes_label, (0, 150, 0), (0, 190, 0), lambda: self.answer(True))
        self.add_button(self.no_rect, no_label, (150, 0, 0), (190, 0, 0), lambda: self.answer(False))
        if back_label is not None:
            self.add_button(self.back_rect, back_label, (0, 100, 150), (0, 140, 190),
                            lambda: self.answer(None), sound_kind="back")

    def cancel(self):
        # The third button's Back sound plays for its keys too.
        self.answer(self.DEFAULT_RESULT, sound="back" if self.back_label is not None else None)

    def handle_key(self, event):
        if self.back_label is not None and event.key == pygame.K_g:
            self.cancel()
        elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_y):
            self.answer(True)
        elif event.key == pygame.K_n:
            self.answer(False)
        else:
            super().handle_key(event)


def ask_yes_no(title, message, on_result, tk_parent=None, yes_label="Yes", no_label="No", back_label=None):
    """Answers on_result(True/False) once the user picks Yes or No.

    An optional back_label adds a third button that returns None.
    Back and Escape also return None when this button is present.

    tk_parent, if given, is a tkinter widget to hide for the dialog's duration --
    only meaningful for the standalone dev-tool path (no game display up yet).
    """
    open_dialog(lambda surface: _YesNoModal(surface, title, message, yes_label, no_label, back_label),
                on_result, tk_parent)
