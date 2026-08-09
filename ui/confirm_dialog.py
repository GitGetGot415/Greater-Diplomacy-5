"""Pygame-rendered replacements for tkinter's messagebox.askyesno / simpledialog.askinteger.

Every function here is callback-based: instead of returning a value, it takes
an on_result callback and invokes it once the user answers. Two things drive
that shape (see ui/modal_stack.py for the full rationale):

- When a main-loop-managed display already exists (the normal in-game case),
  the dialog is pushed onto the modal stack and answered on a later frame --
  it can't block the caller, since blocking is exactly what freezes a pygbag
  browser tab (main.py's loop never gets to yield to the browser).
- When no display exists yet (standalone tkinter dev tools like
  data/editors/country_editor.py, run outside the game's main loop entirely),
  there's no modal stack pumping frames, so the dialog falls back to running
  its own short-lived blocking loop and calls on_result() right before
  returning -- same callback shape, just resolved synchronously.

Call sites always look the same either way: `ask_yes_no(title, msg, on_result=...)`.
"""
import pygame
import webbrowser
from data import queries
from map_logic.rendering.font_manager import fonts
from ui import modal_stack
from ui import text_utils
from ui.bars import ui_bars

_STANDALONE_SIZE = (520, 320)


def _back_key():
    """The rebound BACK key, so these dialogs dismiss on it same as everything else."""
    return queries.get_keybind("BACK", pygame.K_ESCAPE)


def _hide_tk_chain(tk_widget):
    """Withdraws a tkinter widget and every ancestor window so the pygame dialog isn't hidden behind a topmost tk window."""
    hidden = []
    widget = tk_widget
    seen = set()
    while widget is not None and id(widget) not in seen:
        seen.add(id(widget))
        try:
            if widget.winfo_exists() and widget.state() != "withdrawn":
                hidden.append(widget)
                widget.withdraw()
        except Exception:
            pass
        widget = getattr(widget, "master", None)
    return hidden


def _show_tk_chain(hidden):
    for widget in reversed(hidden):
        try:
            widget.deiconify()
        except Exception:
            pass


def _acquire_surface():
    return ui_bars.acquire_surface(_STANDALONE_SIZE, "Confirm")


def _release_surface(owns_display):
    ui_bars.release_surface(owns_display)


def _wrap_text(text, font, max_width):
    """Kept as the name checkbox_list_screen and scripted_events_editor already
    import; the implementation now lives in ui/text_utils.py."""
    return text_utils.wrap_text(text, font, max_width)


class _YesNoModal:
    def __init__(self, surface, title, message, on_result, yes_label, no_label):
        self.on_result = on_result
        self.background = surface.copy()
        self._resolved = False

        title_font = fonts.get("heading2")
        msg_font = fonts.get("normal")
        self.btn_font = fonts.get("button")

        box_w = min(520, surface.get_width() - 40)
        self.lines = _wrap_text(message, msg_font, box_w - 40)
        box_h = max(200, 130 + len(self.lines) * (msg_font.get_height() + 2))
        self.box_rect = pygame.Rect(0, 0, box_w, box_h)
        self.box_rect.center = (surface.get_width() // 2, surface.get_height() // 2)

        self.yes_rect = pygame.Rect(self.box_rect.centerx - 140, self.box_rect.bottom - 55, 120, 40)
        self.no_rect = pygame.Rect(self.box_rect.centerx + 20, self.box_rect.bottom - 55, 120, 40)

        self.title = title
        self.title_font = title_font
        self.msg_font = msg_font
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

    def update(self):
        if self._resolved:
            modal_stack.pop()
            self.on_result(self._result)

    def _finish(self, result):
        self._resolved = True
        self._result = result

    def draw(self, surface):
        surface.blit(self.background, (0, 0))
        overlay = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 180))
        surface.blit(overlay, (0, 0))

        pygame.draw.rect(surface, (40, 40, 40), self.box_rect)
        pygame.draw.rect(surface, (200, 200, 200), self.box_rect, 2)

        title_surf = self.title_font.render(self.title, True, (255, 255, 255))
        surface.blit(title_surf, title_surf.get_rect(center=(self.box_rect.centerx, self.box_rect.y + 35)))

        y = self.box_rect.y + 75
        for line in self.lines:
            line_surf = self.msg_font.render(line, True, (210, 210, 210))
            surface.blit(line_surf, line_surf.get_rect(center=(self.box_rect.centerx, y)))
            y += self.msg_font.get_height() + 2

        mx, my = pygame.mouse.get_pos()
        yes_color = (0, 190, 0) if self.yes_rect.collidepoint(mx, my) else (0, 150, 0)
        no_color = (190, 0, 0) if self.no_rect.collidepoint(mx, my) else (150, 0, 0)
        pygame.draw.rect(surface, yes_color, self.yes_rect, border_radius=4)
        pygame.draw.rect(surface, no_color, self.no_rect, border_radius=4)

        yes_surf = self.btn_font.render(self.yes_label, True, (255, 255, 255))
        no_surf = self.btn_font.render(self.no_label, True, (255, 255, 255))
        surface.blit(yes_surf, yes_surf.get_rect(center=self.yes_rect.center))
        surface.blit(no_surf, no_surf.get_rect(center=self.no_rect.center))


def _ask_yes_no_standalone(title, message, on_result, tk_parent, yes_label, no_label):
    """No main loop is pumping frames here, so resolve with our own short blocking loop."""
    surface, owns_display = _acquire_surface()
    hidden_tk = _hide_tk_chain(tk_parent) if tk_parent is not None else []

    modal = _YesNoModal(surface, title, message, lambda r: None, yes_label, no_label)
    clock = pygame.time.Clock()
    result = False
    waiting = True

    try:
        while waiting:
            events = pygame.event.get()
            for event in events:
                if event.type == pygame.QUIT:
                    result, waiting = False, False
            modal.handle_events(events)
            if modal._resolved:
                result, waiting = modal._result, False

            modal.draw(surface)
            pygame.display.flip()
            clock.tick(60)
    finally:
        _show_tk_chain(hidden_tk)
        _release_surface(owns_display)

    on_result(result)


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


class _TextInputModal:
    def __init__(self, surface, title, message, initial_text, on_result, char_allowed, validate):
        self.on_result = on_result
        self.char_allowed = char_allowed
        self.validate = validate
        self.background = surface.copy()
        self._resolved = False

        self.title_font = fonts.get("heading2")
        self.msg_font = fonts.get("normal")
        self.btn_font = fonts.get("button")

        box_w = min(480, surface.get_width() - 40)
        self.lines = _wrap_text(message, self.msg_font, box_w - 40)
        box_h = max(230, 120 + len(self.lines) * (self.msg_font.get_height() + 2) + 90)
        self.box_rect = pygame.Rect(0, 0, box_w, box_h)
        self.box_rect.center = (surface.get_width() // 2, surface.get_height() // 2)

        self.input_rect = pygame.Rect(self.box_rect.x + 40, self.box_rect.bottom - 110, box_w - 80, 40)
        self.ok_rect = pygame.Rect(self.box_rect.centerx - 140, self.box_rect.bottom - 55, 120, 40)
        self.cancel_rect = pygame.Rect(self.box_rect.centerx + 20, self.box_rect.bottom - 55, 120, 40)

        self.title = title
        self.text = str(initial_text) if initial_text is not None else ""
        self.error_text = ""

    def handle_events(self, events):
        for event in events:
            if event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_ESCAPE, _back_key()):
                    self._finish(None)
                elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    value, self.error_text = self.validate(self.text)
                    if self.error_text == "":
                        self._finish(value)
                elif event.key == pygame.K_BACKSPACE:
                    self.text = self.text[:-1]
                    self.error_text = ""
                elif event.unicode and self.char_allowed(event.unicode, self.text):
                    self.text += event.unicode
                    self.error_text = ""
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self.ok_rect.collidepoint(event.pos):
                    value, self.error_text = self.validate(self.text)
                    if self.error_text == "":
                        self._finish(value)
                elif self.cancel_rect.collidepoint(event.pos):
                    self._finish(None)

    def update(self):
        if self._resolved:
            modal_stack.pop()
            self.on_result(self._result)

    def _finish(self, result):
        self._resolved = True
        self._result = result

    def draw(self, surface):
        surface.blit(self.background, (0, 0))
        overlay = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 180))
        surface.blit(overlay, (0, 0))

        pygame.draw.rect(surface, (40, 40, 40), self.box_rect)
        pygame.draw.rect(surface, (200, 200, 200), self.box_rect, 2)

        title_surf = self.title_font.render(self.title, True, (255, 255, 255))
        surface.blit(title_surf, title_surf.get_rect(center=(self.box_rect.centerx, self.box_rect.y + 35)))

        y = self.box_rect.y + 75
        for line in self.lines:
            line_surf = self.msg_font.render(line, True, (210, 210, 210))
            surface.blit(line_surf, line_surf.get_rect(center=(self.box_rect.centerx, y)))
            y += self.msg_font.get_height() + 2

        pygame.draw.rect(surface, (20, 20, 20), self.input_rect)
        border_color = (220, 80, 80) if self.error_text else (200, 200, 200)
        pygame.draw.rect(surface, border_color, self.input_rect, 2)
        input_surf = self.msg_font.render(self.text or " ", True, (255, 255, 255))
        surface.set_clip(self.input_rect.inflate(-10, -6))
        surface.blit(input_surf, input_surf.get_rect(midleft=(self.input_rect.x + 10, self.input_rect.centery)))
        surface.set_clip(None)

        if self.error_text:
            err_surf = fonts.get("small").render(self.error_text, True, (230, 100, 100))
            surface.blit(err_surf, err_surf.get_rect(center=(self.box_rect.centerx, self.input_rect.y - 14)))

        mx, my = pygame.mouse.get_pos()
        ok_color = (0, 190, 0) if self.ok_rect.collidepoint(mx, my) else (0, 150, 0)
        cancel_color = (190, 0, 0) if self.cancel_rect.collidepoint(mx, my) else (150, 0, 0)
        pygame.draw.rect(surface, ok_color, self.ok_rect, border_radius=4)
        pygame.draw.rect(surface, cancel_color, self.cancel_rect, border_radius=4)

        ok_surf = self.btn_font.render("OK", True, (255, 255, 255))
        cancel_surf = self.btn_font.render("Cancel", True, (255, 255, 255))
        surface.blit(ok_surf, ok_surf.get_rect(center=self.ok_rect.center))
        surface.blit(cancel_surf, cancel_surf.get_rect(center=self.cancel_rect.center))


def _run_text_input_dialog_standalone(title, message, initial_text, tk_parent, char_allowed, validate, on_result):
    surface, owns_display = _acquire_surface()
    hidden_tk = _hide_tk_chain(tk_parent) if tk_parent is not None else []

    modal = _TextInputModal(surface, title, message, initial_text, lambda r: None, char_allowed, validate)
    clock = pygame.time.Clock()
    result = None
    waiting = True

    try:
        while waiting:
            events = pygame.event.get()
            for event in events:
                if event.type == pygame.QUIT:
                    result, waiting = None, False
            modal.handle_events(events)
            if modal._resolved:
                result, waiting = modal._result, False

            modal.draw(surface)
            pygame.display.flip()
            clock.tick(60)
    finally:
        _show_tk_chain(hidden_tk)
        _release_surface(owns_display)

    on_result(result)


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


_KIND_ACCENTS = {
    "info": (80, 150, 220),
    "success": (60, 170, 90),
    "warning": (210, 160, 40),
    "error": (200, 70, 70),
}


class _MessageModal:
    def __init__(self, surface, title, message, on_result, kind):
        self.on_result = on_result
        self.background = surface.copy()
        self._resolved = False

        title_font = fonts.get("heading2")
        msg_font = fonts.get("normal")
        self.btn_font = fonts.get("button")
        self.accent = _KIND_ACCENTS.get(kind, _KIND_ACCENTS["info"])

        box_w = min(520, surface.get_width() - 40)
        self.lines = _wrap_text(message, msg_font, box_w - 40)
        box_h = max(200, 110 + len(self.lines) * (msg_font.get_height() + 2) + 60)
        self.box_rect = pygame.Rect(0, 0, box_w, box_h)
        self.box_rect.center = (surface.get_width() // 2, surface.get_height() // 2)

        self.ok_rect = pygame.Rect(self.box_rect.centerx - 60, self.box_rect.bottom - 55, 120, 40)

        self.title = title
        self.title_font = title_font
        self.msg_font = msg_font

    def handle_events(self, events):
        for event in events:
            if event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_ESCAPE, pygame.K_SPACE, _back_key()):
                    self._finish()
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self.ok_rect.collidepoint(event.pos):
                    self._finish()

    def update(self):
        if self._resolved:
            modal_stack.pop()
            if self.on_result:
                self.on_result()

    def _finish(self):
        self._resolved = True

    def draw(self, surface):
        surface.blit(self.background, (0, 0))
        overlay = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 180))
        surface.blit(overlay, (0, 0))

        pygame.draw.rect(surface, (40, 40, 40), self.box_rect)
        pygame.draw.rect(surface, self.accent, self.box_rect, 3)

        title_surf = self.title_font.render(self.title, True, (255, 255, 255))
        surface.blit(title_surf, title_surf.get_rect(center=(self.box_rect.centerx, self.box_rect.y + 35)))

        y = self.box_rect.y + 75
        for line in self.lines:
            line_surf = self.msg_font.render(line, True, (210, 210, 210))
            surface.blit(line_surf, line_surf.get_rect(center=(self.box_rect.centerx, y)))
            y += self.msg_font.get_height() + 2

        mx, my = pygame.mouse.get_pos()
        hovered = self.ok_rect.collidepoint(mx, my)
        ok_color = tuple(min(255, ch + 40) for ch in self.accent) if hovered else self.accent
        pygame.draw.rect(surface, ok_color, self.ok_rect, border_radius=4)
        ok_surf = self.btn_font.render("OK", True, (255, 255, 255))
        surface.blit(ok_surf, ok_surf.get_rect(center=self.ok_rect.center))


def _show_message_standalone(title, message, tk_parent, kind, on_result):
    surface, owns_display = _acquire_surface()
    hidden_tk = _hide_tk_chain(tk_parent) if tk_parent is not None else []

    modal = _MessageModal(surface, title, message, None, kind)
    clock = pygame.time.Clock()
    waiting = True

    try:
        while waiting:
            events = pygame.event.get()
            for event in events:
                if event.type == pygame.QUIT:
                    waiting = False
            modal.handle_events(events)
            if modal._resolved:
                waiting = False

            modal.draw(surface)
            pygame.display.flip()
            clock.tick(60)
    finally:
        _show_tk_chain(hidden_tk)
        _release_surface(owns_display)

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


_LINK_COLOR = (100, 100, 255)
_LINK_HOVER_COLOR = (255, 255, 0)


class _PersonInfoModal:
    """Popup for a Credits entry: a title, an optional free-text info section,
    and an optional list of clickable links below it."""

    def __init__(self, surface, name, info_text, links, on_result, align="center"):
        self.on_result = on_result
        self.background = surface.copy()
        self._resolved = False
        self.align = align if align in ("left", "center", "right") else "center"

        self.title_font = fonts.get("heading2")
        self.msg_font = fonts.get("normal")
        self.link_font = fonts.get("normal")
        self.btn_font = fonts.get("button")

        box_w = min(560, surface.get_width() - 40)
        content_w = box_w - 80
        self.lines = _wrap_text(info_text, self.msg_font, content_w) if info_text else []
        self.links = links or []

        text_h = len(self.lines) * (self.msg_font.get_height() + 2)
        links_h = len(self.links) * (self.link_font.get_height() + 8)
        box_h = 110 + text_h + (20 if self.links else 0) + links_h + 70
        box_h = max(220, box_h)

        self.box_rect = pygame.Rect(0, 0, box_w, box_h)
        self.box_rect.center = (surface.get_width() // 2, surface.get_height() // 2)

        self.ok_rect = pygame.Rect(self.box_rect.centerx - 60, self.box_rect.bottom - 55, 120, 40)

        self.name = name
        self.text_y_start = self.box_rect.y + 75

        left_x = self.box_rect.x + 40
        right_x = self.box_rect.right - 40

        self.link_rects = []
        y = self.text_y_start + text_h + (20 if self.links else 0)
        for link in self.links:
            text = link.get("text", "")
            w = self.link_font.size(text)[0]
            if self.align == "left":
                x = left_x
            elif self.align == "right":
                x = right_x - w
            else:
                x = self.box_rect.centerx - w // 2
            rect = pygame.Rect(x, y, w, self.link_font.get_height())
            self.link_rects.append(rect)
            y += self.link_font.get_height() + 8

    def handle_events(self, events):
        for event in events:
            if event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_ESCAPE, pygame.K_SPACE, _back_key()):
                    self._finish()
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self.ok_rect.collidepoint(event.pos):
                    self._finish()
                    return
                for rect, link in zip(self.link_rects, self.links):
                    if link.get("url") and rect.collidepoint(event.pos):
                        webbrowser.open(link["url"])
                        return

    def update(self):
        if self._resolved:
            modal_stack.pop()
            if self.on_result:
                self.on_result()

    def _finish(self):
        self._resolved = True

    def draw(self, surface):
        surface.blit(self.background, (0, 0))
        overlay = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 180))
        surface.blit(overlay, (0, 0))

        pygame.draw.rect(surface, (40, 40, 40), self.box_rect)
        pygame.draw.rect(surface, _KIND_ACCENTS["info"], self.box_rect, 3)

        title_surf = self.title_font.render(self.name, True, (255, 255, 255))
        surface.blit(title_surf, title_surf.get_rect(center=(self.box_rect.centerx, self.box_rect.y + 35)))

        y = self.text_y_start
        left_x = self.box_rect.x + 40
        right_x = self.box_rect.right - 40
        for line in self.lines:
            line_surf = self.msg_font.render(line, True, (210, 210, 210))
            if self.align == "left":
                rect = line_surf.get_rect(midleft=(left_x, y))
            elif self.align == "right":
                rect = line_surf.get_rect(midright=(right_x, y))
            else:
                rect = line_surf.get_rect(center=(self.box_rect.centerx, y))
            surface.blit(line_surf, rect)
            y += self.msg_font.get_height() + 2

        mx, my = pygame.mouse.get_pos()
        for rect, link in zip(self.link_rects, self.links):
            text = link.get("text", "")
            has_url = bool(link.get("url"))
            is_hovered = has_url and rect.collidepoint(mx, my)
            color = _LINK_HOVER_COLOR if is_hovered else (_LINK_COLOR if has_url else (200, 200, 200))
            text_surf = self.link_font.render(text, True, color)
            surface.blit(text_surf, rect.topleft)
            if is_hovered:
                pygame.draw.line(surface, color, (rect.left, rect.bottom), (rect.right, rect.bottom), 2)

        hovered_ok = self.ok_rect.collidepoint(mx, my)
        accent = _KIND_ACCENTS["info"]
        ok_color = tuple(min(255, ch + 40) for ch in accent) if hovered_ok else accent
        pygame.draw.rect(surface, ok_color, self.ok_rect, border_radius=4)
        ok_surf = self.btn_font.render("Close", True, (255, 255, 255))
        surface.blit(ok_surf, ok_surf.get_rect(center=self.ok_rect.center))


def _show_person_info_standalone(name, info_text, links, align, tk_parent, on_result):
    surface, owns_display = _acquire_surface()
    hidden_tk = _hide_tk_chain(tk_parent) if tk_parent is not None else []

    modal = _PersonInfoModal(surface, name, info_text, links, None, align)
    clock = pygame.time.Clock()
    waiting = True

    try:
        while waiting:
            events = pygame.event.get()
            for event in events:
                if event.type == pygame.QUIT:
                    waiting = False
            modal.handle_events(events)
            if modal._resolved:
                waiting = False

            modal.draw(surface)
            pygame.display.flip()
            clock.tick(60)
    finally:
        _show_tk_chain(hidden_tk)
        _release_surface(owns_display)

    if on_result:
        on_result()


def show_person_info(name, info_text="", links=None, align="center", tk_parent=None, on_result=None):
    """Popup with free-text info about `name`, plus a list of clickable links below it.

    links is a list of {"text": str, "url": str} dicts; each renders as its own
    clickable line and opens its url in a browser when clicked. align controls
    the info text's horizontal alignment: "left", "center" (default), or "right".
    """
    surface = pygame.display.get_surface()
    if surface is None:
        _show_person_info_standalone(name, info_text, links, align, tk_parent, on_result)
        return

    modal_stack.push(_PersonInfoModal(surface, name, info_text, links, on_result, align))
