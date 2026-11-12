import pygame
import data.constants as c
from ui.rendering.font_manager import fonts
from ui.dialogs.base import DialogScreen, open_dialog
from ui.widgets.ui_elements import process_text_input, draw_text_input_background


# What makes the entry box read as "type here": a gold border, a hint while it is
# empty, and a caret that blinks.
INPUT_HINT = "Type here..."
CARET_BLINK_MS = 500
CARET_WIDTH = 2
# Clear's (color, hover color), keyed by whether there is text to clear.
CLEAR_COLORS = {True: ((135, 45, 45), (180, 65, 65)), False: ((85, 85, 85), (115, 115, 115))}


class _TextInputModal(DialogScreen):
    BOX_MAX_W = 480
    BOX_MIN_H = 230
    BOX_CHROME_H = 210   # 120 of chrome plus the 90 the input row occupies
    # The entry box owns every key, including the FULLSCREEN key and keys bound to mouse clicks.
    listening_for = True

    def __init__(self, surface, title, message, initial_text, char_allowed, validate):
        super().__init__(surface, title, message)
        self.char_allowed = char_allowed
        self.validate = validate

        # Keep Clear in the input row, but outside the black text box: it is
        # easy to find without covering the value being entered.
        self.clear_rect = pygame.Rect(self.panel_rect.x + 40, self.panel_rect.bottom - 107, 64, 34)
        self.input_rect = pygame.Rect(self.clear_rect.right + 8, self.panel_rect.bottom - 110,
                                      self.panel_rect.right - (self.clear_rect.right + 8) - 40, 40)
        self.ok_rect = pygame.Rect(self.panel_rect.centerx - 140, self.panel_rect.bottom - 55, 120, 40)
        self.cancel_rect = pygame.Rect(self.panel_rect.centerx + 20, self.panel_rect.bottom - 55, 120, 40)

        self.text = str(initial_text) if initial_text is not None else ""
        self.error_text = ""

        self.clear_button = self.add_button(self.clear_rect, "Clear", *CLEAR_COLORS[False], self._clear)
        self.add_button(self.ok_rect, "OK", (0, 150, 0), (0, 190, 0), self._submit)
        self.add_button(self.cancel_rect, "Cancel", (150, 0, 0), (190, 0, 0), self.cancel)
        self._set_text(self.text)

    def _set_text(self, text):
        self.text = text
        self.error_text = ""
        # Clear is red while there is something to clear.
        self.clear_button.set_colors(*CLEAR_COLORS[bool(self.text)])

    def _clear(self):
        self._set_text("")

    def _submit(self):
        value, self.error_text = self.validate(self.text)
        if self.error_text == "":
            self.answer(value)

    def handle_key(self, event):
        if self.is_cancel_key(event.key):
            self.cancel()
        elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            self._submit()
        else:
            # Every ordinary text field uses this shared handler,
            # including Ctrl/Cmd+V and Shift+Insert clipboard paste.
            candidate = [self.text]

            def is_allowed(char):
                allowed = self.char_allowed(char, candidate[0])
                if allowed:
                    candidate[0] += char
                return allowed

            new_text, _status = process_text_input(event, self.text, validation_func=is_allowed)
            if new_text != self.text:
                self._set_text(new_text)

    def draw_body(self, surface):
        self.draw_body_lines(surface)
        border_color = (220, 80, 80) if self.error_text else c.COLOR_GOLD_HIGHLIGHT
        draw_text_input_background(surface, self.input_rect, active=True,
                                   style_name="dialog", border_color=border_color)
        text_rect = self.input_rect.inflate(-8, -6)
        input_surf = self.msg_font.render(self.text or INPUT_HINT, True,
                                          (255, 255, 255) if self.text else c.UI_TEXT_MUTED)
        # A value wider than the box slides left so the caret stays in view.
        shift = min(0, text_rect.width - CARET_WIDTH - 4 - input_surf.get_width()) if self.text else 0
        text_x = text_rect.x + 2 + shift
        surface.set_clip(text_rect)
        surface.blit(input_surf, input_surf.get_rect(midleft=(text_x, self.input_rect.centery)))
        if pygame.time.get_ticks() // CARET_BLINK_MS % 2 == 0:
            caret_x = text_x + (input_surf.get_width() if self.text else 0) + 1
            pygame.draw.rect(surface, (255, 255, 255),
                             (caret_x, text_rect.y + 2, CARET_WIDTH, text_rect.height - 4))
        surface.set_clip(None)

        if self.error_text:
            err_surf = fonts.get("small").render(self.error_text, True, (230, 100, 100))
            surface.blit(err_surf, err_surf.get_rect(center=(self.panel_rect.centerx,
                                                             self.input_rect.y - 14)))


def _run_text_input_dialog(title, message, initial_text, tk_parent, char_allowed, validate, on_result):
    """Shared single-line text-entry modal used by ask_integer and ask_string.

    char_allowed(unicode_char, current_text) -> bool decides which typed characters are accepted.
    validate(text) -> (value, error_message); value is None (with a message) when the text isn't acceptable yet.
    """
    open_dialog(lambda surface: _TextInputModal(surface, title, message, initial_text, char_allowed, validate),
                on_result, tk_parent)


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


def ask_string(title, message, on_result, initial="", tk_parent=None, allow_empty=True, is_valid_char=None,
               max_length=None):
    """Answers on_result(str) once confirmed, or on_result(None) if cancelled.

    is_valid_char(char) limits the typed and pasted characters. The default accepts printable characters.
    max_length stops new characters when the text reaches that length.
    """

    def char_allowed(ch, current_text):
        if max_length is not None and len(current_text) >= max_length:
            return False
        return is_valid_char(ch) if is_valid_char else ch.isprintable()

    def validate(text):
        if not allow_empty and not text.strip():
            return None, "This field cannot be empty."
        return text, ""

    _run_text_input_dialog(title, message, initial, tk_parent, char_allowed, validate, on_result)
