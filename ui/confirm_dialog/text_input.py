import pygame
import data.constants as c
from map_logic.rendering.font_manager import fonts
from ui import modal_stack
from ui.confirm_dialog.base import _BaseModal, _back_key, _run_blocking


class _TextInputModal(_BaseModal):
    BOX_MAX_W = 480
    BOX_MIN_H = 230
    BOX_CHROME_H = 210   # 120 of chrome plus the 90 the input row occupies

    def __init__(self, surface, title, message, initial_text, on_result, char_allowed, validate):
        super().__init__(surface, title, message, on_result)
        self.char_allowed = char_allowed
        self.validate = validate

        self.input_rect = pygame.Rect(self.box_rect.x + 40, self.box_rect.bottom - 110,
                                      self.box_rect.width - 80, 40)
        self.ok_rect = pygame.Rect(self.box_rect.centerx - 140, self.box_rect.bottom - 55, 120, 40)
        self.cancel_rect = pygame.Rect(self.box_rect.centerx + 20, self.box_rect.bottom - 55, 120, 40)

        self.text = str(initial_text) if initial_text is not None else ""
        self.error_text = ""

    def _submit(self):
        value, self.error_text = self.validate(self.text)
        if self.error_text == "":
            self._finish(value)

    def handle_events(self, events):
        for event in events:
            if event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_ESCAPE, _back_key()):
                    self._finish(None)
                elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    self._submit()
                elif event.key == pygame.K_BACKSPACE:
                    self.text = self.text[:-1]
                    self.error_text = ""
                elif event.unicode and self.char_allowed(event.unicode, self.text):
                    self.text += event.unicode
                    self.error_text = ""
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self.ok_rect.collidepoint(event.pos):
                    self._submit()
                elif self.cancel_rect.collidepoint(event.pos):
                    self._finish(None)

    def draw_content(self, surface):
        pygame.draw.rect(surface, (20, 20, 20), self.input_rect)
        border_color = (220, 80, 80) if self.error_text else c.UI_TEXT_LIGHT
        pygame.draw.rect(surface, border_color, self.input_rect, 2)
        input_surf = self.msg_font.render(self.text or " ", True, (255, 255, 255))
        surface.set_clip(self.input_rect.inflate(-10, -6))
        surface.blit(input_surf, input_surf.get_rect(midleft=(self.input_rect.x + 10,
                                                             self.input_rect.centery)))
        surface.set_clip(None)

        if self.error_text:
            err_surf = fonts.get("small").render(self.error_text, True, (230, 100, 100))
            surface.blit(err_surf, err_surf.get_rect(center=(self.box_rect.centerx,
                                                             self.input_rect.y - 14)))

        self.draw_button(surface, self.ok_rect, "OK", (0, 150, 0), (0, 190, 0))
        self.draw_button(surface, self.cancel_rect, "Cancel", (150, 0, 0), (190, 0, 0))


def _run_text_input_dialog_standalone(title, message, initial_text, tk_parent, char_allowed,
                                      validate, on_result):
    on_result(_run_blocking(
        lambda surf: _TextInputModal(surf, title, message, initial_text, None,
                                     char_allowed, validate),
        tk_parent, default_result=None))


def _run_text_input_dialog(title, message, initial_text, tk_parent, char_allowed, validate, on_result):
    """Shared single-line text-entry modal used by ask_integer and ask_string.

    char_allowed(unicode_char, current_text) -> bool decides which typed characters are accepted.
    validate(text) -> (value, error_message); value is None (with a message) when the text isn't acceptable yet.
    """
    surface = pygame.display.get_surface()
    if surface is None:
        _run_text_input_dialog_standalone(title, message, initial_text, tk_parent, char_allowed, validate, on_result)
        return

    modal_stack.push(_TextInputModal(surface, title, message, initial_text, on_result, char_allowed, validate))


def ask_integer(title, message, on_result, minvalue=None, maxvalue=None, initial=None, tk_parent=None):
    """Answers on_result(int) once confirmed, or on_result(None) if cancelled."""

    def char_allowed(ch, current_text):
        return ch.isdigit() or (ch == "-" and not current_text)

    def validate(text):
        if not text:
            return None, "Enter a number."
        try:
            value = int(text)
        except ValueError:
            return None, "Enter a whole number."
        if minvalue is not None and value < minvalue:
            return None, f"Minimum is {minvalue}."
        if maxvalue is not None and value > maxvalue:
            return None, f"Maximum is {maxvalue}."
        return value, ""

    initial_text = str(initial) if initial is not None else ""
    _run_text_input_dialog(title, message, initial_text, tk_parent, char_allowed, validate, on_result)


def ask_string(title, message, on_result, initial="", tk_parent=None, allow_empty=True):
    """Answers on_result(str) once confirmed, or on_result(None) if cancelled."""

    def char_allowed(ch, current_text):
        return ch.isprintable()

    def validate(text):
        if not allow_empty and not text.strip():
            return None, "This field cannot be empty."
        return text, ""

    _run_text_input_dialog(title, message, initial, tk_parent, char_allowed, validate, on_result)
